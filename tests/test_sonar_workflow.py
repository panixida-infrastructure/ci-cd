import json
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / '.github/workflows/dotnet-sonar.yml'
SOURCE = WORKFLOW.read_text().split('      - name: Build and analyze\n', 1)[1]
PROGRAM = textwrap.dedent(SOURCE.split('        run: |\n', 1)[1])


class SonarWorkflowTests(unittest.TestCase):
    def analyze(self, *, version_file='', version='3.0', event='pull_request', ref_type='branch'):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'coverage.xml').write_text('<coverage/>')
            (root / 'version.json').write_text(json.dumps({'version': version}))
            mock = root / 'dotnet'
            mock.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                            'with open(os.environ["ARGUMENT_LOG"], "a") as log:\n'
                            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n')
            mock.chmod(0o755)
            log = root / 'arguments.jsonl'
            env = {
                **os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
                'GITHUB_WORKSPACE': str(root), 'ARGUMENT_LOG': str(log),
                'SONAR_HOST_URL': 'https://sonar.example.test', 'SONAR_PROJECT_KEY': 'test',
                'SONAR_TOKEN': 'test-token', 'SONAR_COVERAGE_REPORT': 'coverage.xml',
                'SONAR_EXCLUSIONS': '', 'SONAR_VERSION_FILE': version_file,
                'SONAR_EVENT_NAME': event, 'SONAR_REF_TYPE': ref_type,
                'SONAR_BRANCH': 'development', 'SONAR_PR_KEY': '42',
                'SONAR_PR_BRANCH': 'feature/quoted$(touch unwanted)',
                'SONAR_PR_BASE': 'development', 'SONAR_REVISION': 'head-sha',
            }
            result = subprocess.run(['bash', '-c', PROGRAM], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            self.assertFalse((root / 'unwanted').exists())
            return result, calls

    def test_pr_compares_with_target_and_uses_head_revision_without_branch_parameter(self):
        result, calls = self.analyze(version_file='version.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = calls[0]
        self.assertIn('/d:sonar.pullrequest.base=development', args)
        self.assertIn('/d:sonar.pullrequest.key=42', args)
        self.assertIn('/d:sonar.pullrequest.branch=feature/quoted$(touch unwanted)', args)
        self.assertIn('/d:sonar.scm.revision=head-sha', args)
        self.assertIn('/v:3.0', args)
        self.assertFalse(any('sonar.branch.' in arg for arg in args))

    def test_service_push_has_named_branch_and_no_version(self):
        result, calls = self.analyze(event='push')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/d:sonar.branch.name=development', calls[0])
        self.assertFalse(any('sonar.pullrequest.' in arg or arg.startswith('/v:') for arg in calls[0]))

    def test_invalid_or_missing_version_stops_before_scanner(self):
        for version in ('', None, 3, '3.0\nnext'):
            with self.subTest(version=version):
                result, calls = self.analyze(version_file='version.json', version=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
        result, calls = self.analyze(version_file='missing.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_version_file_cannot_escape_repository(self):
        for path in ('../version.json', '/tmp/version.json'):
            with self.subTest(path=path):
                result, calls = self.analyze(version_file=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must stay within', result.stderr)
                self.assertEqual(calls, [])

    def test_tag_cannot_overwrite_main_analysis(self):
        result, calls = self.analyze(event='push', ref_type='tag')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


class PullRequestCoverageTests(unittest.TestCase):
    def collect(self, *, omit_report=False, exclusions='*ContainerTests.csproj'):
        source = WORKFLOW.read_text().split('      - name: Collect pull request head coverage\n', 1)[1]
        program = textwrap.dedent(source.split('        run: |\n', 1)[1].split('      - name: Build and analyze\n', 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name in ('UnitTests.csproj', 'ContainerTests.csproj'):
                (root / name).write_text('<Project/>')
            bin_directory = root / 'bin'
            bin_directory.mkdir()
            tools_directory = root / '.dotnet/tools'
            tools_directory.mkdir(parents=True)
            dotnet = bin_directory / 'dotnet'
            dotnet.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['ARGUMENT_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[0] == 'test' and os.environ['OMIT_REPORT'] != 'true':
    directory = pathlib.Path(args[args.index('--results-directory') + 1])
    directory.mkdir(parents=True)
    (directory / 'coverage.cobertura.xml').write_text('<coverage/>')
''')
            dotnet.chmod(0o755)
            generator = tools_directory / 'reportgenerator'
            generator.write_text('''#!/usr/bin/env python3
import pathlib
directory = pathlib.Path('tests-report/sonar')
directory.mkdir(parents=True)
(directory / 'SonarQube.xml').write_text('head-coverage')
''')
            generator.chmod(0o755)
            log = root / 'calls'
            env = {**os.environ, 'HOME': str(root), 'PATH': f'{bin_directory}:{os.environ["PATH"]}',
                   'ARGUMENT_LOG': str(log), 'OMIT_REPORT': str(omit_report).lower(),
                   'COVERAGE_EXCLUDED_TEST_PROJECTS': exclusions, 'COVERAGE_ASSEMBLY_FILTERS': ''}
            result = subprocess.run(['bash', '-c', program], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            report = root / 'tests-report/sonar/SonarQube.xml'
            return result, calls, report.read_text() if report.exists() else None

    def test_head_coverage_respects_instrumentation_exclusions_and_produces_sonar_report(self):
        result, calls, report = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        tests = [call for call in calls if call[0] == 'test']
        self.assertEqual(len(tests), 1)
        self.assertIn('./UnitTests.csproj', tests[0])
        self.assertIn('--coverage', tests[0])
        self.assertEqual(report, 'head-coverage')

    def test_missing_or_ineligible_head_coverage_fails_without_reusing_merge_report(self):
        for options in ({'omit_report': True}, {'exclusions': '*Tests.csproj'}):
            with self.subTest(options=options):
                result, _, report = self.collect(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(report)


if __name__ == '__main__':
    unittest.main()
