import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASH = os.environ.get("GITLAB_TEST_BASH", shutil.which("bash"))


def template(name):
    return yaml.safe_load((ROOT / "gitlab-templates" / name).read_text(encoding="utf-8"))


def run_shell(script, cwd, variables=None):
    env = dict(os.environ, TEMPLATE_TEST_PYTHON=sys.executable)
    env.update(variables or {})
    return subprocess.run(
        [BASH], input=script, cwd=cwd, env=env, text=True,
        encoding="utf-8", capture_output=True,
    )


class GitLabTemplatesTests(unittest.TestCase):
    def test_all_templates_parse_and_shell_syntax_is_valid(self):
        for path in sorted((ROOT / "gitlab-templates").glob("*.yml")):
            with self.subTest(template=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertFalse(any(line.lstrip().startswith("#") for line in content.splitlines()))
                for config in yaml.safe_load(content).values():
                    if not isinstance(config, dict):
                        continue
                    for key in ("before_script", "script", "after_script"):
                        commands = config.get(key, [])
                        self.assertTrue(all(isinstance(command, str) for command in commands))
                        result = subprocess.run(
                            [BASH, "-n"], input="\n".join(commands), text=True,
                            encoding="utf-8", capture_output=True,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_checklist_reads_full_description_and_fails_on_api_error(self):
        stubs = """
curl() { printf '%s' "$MR_FULL_JSON"; return "${MR_FETCH_EXIT:-0}"; }
jq() { "$TEMPLATE_TEST_PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("description") or "")'; }
"""
        descriptions = [("x" * 2800 + "\n- [ ] unfinished", 1), ("x" * 2800 + "\n- [x] done", 0), (None, 0)]
        for job in (".validate-checklist", ".validate-checklist-old"):
            script = stubs + "\n".join(template(".validate-checklist.yml")[job]["script"])
            with tempfile.TemporaryDirectory() as directory:
                for description, code in descriptions:
                    with self.subTest(job=job, description=str(description)[-30:]):
                        result = run_shell(script, directory, {
                            "CI_MERGE_REQUEST_IID": "1", "CI_MERGE_REQUEST_DESCRIPTION": "x" * 2700,
                            "MR_FULL_JSON": json.dumps({"description": description}),
                            "GITLAB_API_TOKEN": "test-token", "CI_API_V4_URL": "https://example.invalid/api/v4",
                            "CI_PROJECT_ID": "1",
                        })
                        self.assertEqual(result.returncode, code, result.stderr)
                result = run_shell(script, directory, {"CI_MERGE_REQUEST_IID": "1", "MR_FULL_JSON": "{}", "MR_FETCH_EXIT": "22"})
                self.assertEqual(result.returncode, 22, result.stderr)
                result = run_shell(script, directory, {"CI_MERGE_REQUEST_IID": "", "MR_FULL_JSON": "{}", "MR_FETCH_EXIT": "22"})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_nuget_pack_skips_build_only_when_requested(self):
        script = template(".nuget-publish-template.yml")[".nuget_publish_template"]["script"][1]
        script += '\nprintf "PACK_FLAGS=%s\\n" "$NO_BUILD_PARAM"\n'
        with tempfile.TemporaryDirectory() as directory:
            for value, expected in (("true", "--no-build"), ("TRUE", "--no-build"), ("false", ""), ("", ""), (None, "")):
                with self.subTest(value=value):
                    variables = {} if value is None else {"SKIP_BUILD_ON_PACK": value}
                    result = run_shell("unset NO_BUILD_PARAM SKIP_BUILD_ON_PACK\n" + (f'export SKIP_BUILD_ON_PACK="{value}"\n' if value is not None else "") + script, directory, variables)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"PACK_FLAGS={expected}\n", result.stdout)

    def test_tool_install_receives_nuget_configuration(self):
        jobs = [(".build-sonar-template.yml", ".build-sonar-fast")]
        jobs += [(".dotnet-format-template.yml", job) for job in (".format_dotnet", ".format_dotnet_fast", ".format_dotnet_shell")]
        with tempfile.TemporaryDirectory() as directory:
            for file, job in jobs:
                with self.subTest(job=job):
                    install = next(command for command in template(file)[job]["script"] if "dotnet tool install" in command)
                    stub = 'dotnet() { printf "%s\\n" "$@"; return 1; }\n'
                    result = run_shell(stub + install, directory)
                    self.assertEqual(result.returncode, 0)
                    self.assertIn("--configfile\n./nuget.config\n", result.stdout)

    def test_go_lint_checkout_contains_old_diff_base(self):
        config = template(".go-lint-template.yml")[".lint_go"]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            source.mkdir()
            def git(*args, cwd=source):
                return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "--quiet")
            git("config", "user.name", "Template Test")
            git("config", "user.email", "test@example.invalid")
            git("commit", "--allow-empty", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            for index in range(22):
                git("commit", "--allow-empty", "--quiet", "-m", str(index))
            shallow = root / "shallow"
            git("clone", "--quiet", "--no-local", "--depth", "20", str(source), str(shallow))
            self.assertNotEqual(subprocess.run(["git", "cat-file", "-e", base], cwd=shallow, capture_output=True).returncode, 0)
            checkout = root / "checkout"
            depth = int(config["variables"].get("GIT_DEPTH", "20"))
            args = ["clone", "--quiet", "--no-local"]
            if depth:
                args += ["--depth", str(depth)]
            git(*args, str(source), str(checkout))
            stubs = 'golangci-lint() { git cat-file -e "${CI_MERGE_REQUEST_DIFF_BASE_SHA}^{commit}"; }\ngo() { return 0; }\n'
            result = run_shell("set -e\n" + stubs + "\n".join(config["script"]), checkout, {"CI_MERGE_REQUEST_DIFF_BASE_SHA": base, "STRICT_LINT": "true"})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dynamic_tests_keep_project_paths_and_distinct_artifacts(self):
        configs = template(".dotnet-tests-template.yml")
        generator = configs[".dotnet_tests_generate_dynamic"]
        paths = ["services/a/Tests.csproj", "services/b/Tests.csproj", "services/with space/Tests.csproj", "services/it's/Tests.csproj"]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for path in paths:
                project = root / path
                project.parent.mkdir(parents=True)
                project.write_text('<Project><PackageReference Include="Microsoft.NET.Test.Sdk" /></Project>', encoding="utf-8")
            (root / "nuget.source").write_text("<configuration />", encoding="utf-8")
            result = run_shell("\n".join(generator["script"]), root, {"DOTNET_TESTS_TEMPLATE_URL": generator["variables"]["DOTNET_TESTS_TEMPLATE_URL"]})
            self.assertEqual(result.returncode, 0, result.stderr)
            child = yaml.safe_load((root / "tests-child.yml").read_text(encoding="utf-8"))
            selected = child["tests"]["parallel"]["matrix"][0]["TEST_PROJECT"]
            self.assertCountEqual(selected, paths)
            script = configs[".dotnet_test_cell"]["script"][0].split("TOOLS=")[0]
            stubs = 'dotnet() { if [ "$1" = "test" ]; then printf "%s\\n" "$@" > "$TEST_LOG"; fi; }\n'
            reports = []
            for index, path in enumerate(selected):
                log = f"test-{index}.log"
                result = run_shell(stubs + script, root, {"TEST_PROJECT": path, "NUGET_CONFIG_FILE": "nuget.source", "REPORT_DIRECTORY": "tests-report", "TEST_LOG": log})
                self.assertEqual(result.returncode, 0, result.stderr)
                args = (root / log).read_text(encoding="utf-8").splitlines()
                self.assertEqual(args[args.index("--project") + 1], path)
                reports.append(args[args.index("--coverage-output") + 1])
                self.assertNotIn("/", args[args.index("--report-trx-filename") + 1])
            self.assertEqual(len(set(reports)), len(paths))
            result = run_shell(stubs + script, root, {"TEST_PROJECT": "", "TEST_SUITE": "Tests", "NUGET_CONFIG_FILE": "nuget.source", "REPORT_DIRECTORY": "tests-report", "TEST_LOG": "manual.log"})
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
