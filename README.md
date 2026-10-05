# CI-CD
Тут хранятся общие шаблоны для пайплайнов, чтобы не дублировать код в каждом репозитории.

## Application chart persistence

The `charts/application` chart can provision one namespace-scoped ReadWriteOnce
PVC and mount it into the application container:

```yaml
persistence:
  enabled: true
  mountPath: /var/lib/application
  storageClass: nvme.network-drives.csi.timeweb.cloud
  size: 10Gi
podSecurityContext:
  fsGroup: 1654
  fsGroupChangePolicy: OnRootMismatch
```

Persistence is disabled by default. When enabled, the chart requires one replica
and uses `Recreate` updates to avoid concurrent attachment on different nodes.
Set a suitable `fsGroup` for the image's non-root user. The PVC is retained on Helm
uninstall and Argo CD prune/deletion; deleting it manually can permanently destroy
application data. This feature does not encrypt stored data or create backups.
The PVC and Deployment share sync wave `0` so `WaitForFirstConsumer` storage classes
can provision the volume after the pod has been scheduled.

## SSH deploy folders

GitHub SSH deploy actions place files under `/opt` by default.

For example:

```yaml
with:
  service-folder: core-platform/edge
```

deploys to:

```text
/opt/core-platform/edge
```

Use `deploy-root` only when a repository intentionally needs another base directory.

## .NET format workflow

The reusable `.github/workflows/dotnet-format.yml` workflow restores the solution
and runs `dotnet format --verify-no-changes --severity warn --no-restore`.
When a root `global.json` exists, the workflow installs the SDK it specifies.
Repositories without that file continue using the runner's installed SDK.
Use `PROJECT_FOLDER` for solutions outside the repository root.

For solutions with source generators or analyzers referenced as projects, enable
`build-before-format`. The formatter needs their compiled assemblies, but does
not build those project references itself on a clean checkout.

```yaml
format:
  uses: PANiXiDA-Infrastructure/ci-cd/.github/workflows/dotnet-format.yml@main
  with:
    build-before-format: true
  secrets:
    registry-user: ${{ secrets.REGISTRY_USER }}
    registry-token: ${{ secrets.REGISTRY_TOKEN }}
```

The optional input defaults to `false`, so existing callers do not need changes.
When enabled, it adds `dotnet build --no-restore` between restore and formatting.
This builds the solution and its project dependencies in the default Debug
configuration used by the formatter. It adds a build to the format job and
requires that build to succeed.

Checkout fetches the full Git history so versioning tools such as
Nerdbank.GitVersioning can calculate the package version during the build.

## .NET test workflow

The reusable `.github/workflows/dotnet-tests.yml` workflow discovers every
`*Tests.csproj` and runs the projects concurrently through a dynamic matrix.
Matrix fail-fast is disabled, so every discovered test project runs even when
another project fails.

Each matrix job publishes its TRX and Cobertura outputs as a short-lived
artifact. The final reporting job downloads all artifacts, publishes the full
test report, merges the canonical Cobertura file from every covered test
project, publishes `dotnet-coverage-sonarqube` for the SonarQube workflow, and
applies `COVERAGE_THRESHOLD` independently to the combined line and branch
coverage.

The consuming repository can configure:

- `PROJECT_FOLDER` for repositories whose solution is not at the root;
- `COVERAGE_EXCLUDED_TEST_PROJECTS` as space-separated glob patterns for test
  projects that cannot run with coverage instrumentation;
- `COVERAGE_ASSEMBLY_FILTERS` for ReportGenerator assembly filtering;
- `COVERAGE_THRESHOLD` for the minimum combined line and branch coverage. Each
  metric must meet the threshold independently.

Projects matched by `COVERAGE_EXCLUDED_TEST_PROJECTS` still run and publish
TRX results; only their coverage instrumentation is disabled.

## .NET SonarQube workflow

The reusable `.github/workflows/dotnet-sonar.yml` workflow restores, builds,
and analyzes a .NET solution, then waits for the SonarQube Quality Gate.

The workflow selects Eclipse Temurin Java 21 explicitly and disables scanner
JRE auto-provisioning. Analysis uses the configured Java runtime without
downloading a JRE from SonarQube or relying on the runner's default Java version.

Scanner HTTP requests allow 900 seconds, matching the platform's 15-minute
SonarQube route timeout. This lets cold scanner-engine downloads finish instead
of being cancelled by the .NET scanner's default 100-second timeout.
All callers share a versioned component archive published in this repository's
GitHub Releases. It contains the scanner engine, bundled plugins, Roslyn
analyzers and the pinned .NET scanner package. The normal per-repository Actions
cache remains the first lookup; a miss restores the shared archive. Unpublished
archives and server-version mismatches fall back to normal downloads.

The separate `Publish shared Sonar cache` workflow builds the archive from the
official SonarQube image after a successful `Validate` run for a push to `main`.
It skips already published versions and can also be run manually from Actions
on `main`. Consumer repositories only read the archive; publication needs no
production Sonar secrets. After the first merge, wait for publication to finish.

Update `.github/actions/sonar-cache/versions.json` through a PR:

- When upgrading SonarQube, update `server_version` and `server_image` (including
  its digest) together; the archive must match the running server.
- To upgrade the .NET scanner, change `scanner_version`.
- To rebuild the same versions after a packaging fix, increment `revision`.

After merge and validation, the workflow publishes a new immutable archive.
New repositories and branches need no archive changes. To roll back, restore
the previous version settings matching the server; published archives are kept.

Add the following job to a consuming repository:

```yaml
tests:
  uses: PANiXiDA-Infrastructure/ci-cd/.github/workflows/dotnet-tests.yml@main
  secrets:
    registry-user: ${{ secrets.REGISTRY_USER }}
    registry-token: ${{ secrets.REGISTRY_TOKEN }}

sonar:
  needs: tests
  uses: PANiXiDA-Infrastructure/ci-cd/.github/workflows/dotnet-sonar.yml@main
  with:
    project-key: ${{ vars.SONAR_PROJECT_KEY }}
  secrets:
    sonar-token: ${{ secrets.SONAR_TOKEN }}
    registry-user: ${{ secrets.REGISTRY_USER }}
    registry-token: ${{ secrets.REGISTRY_TOKEN }}
```

The `needs: tests` dependency is required because the SonarQube workflow
downloads the `dotnet-coverage-sonarqube` artifact produced by the test
workflow. The test workflow applies the overall `COVERAGE_THRESHOLD`
independently to combined line and branch coverage, while the SonarQube Quality
Gate evaluates coverage on new code.

The consuming repository must configure:

- `PROJECT_FOLDER` with the directory containing the .NET solution;
- `SONAR_HOST_URL` with the SonarQube server URL;
- `SONAR_PROJECT_KEY` with the project key passed to the workflow;
- `SONAR_TOKEN`, `REGISTRY_USER`, and `REGISTRY_TOKEN` as secrets.

Use the optional `exclusions` input to replace the default SonarQube
exclusions.
