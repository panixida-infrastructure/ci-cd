"""Build and restore the shared, project-independent Sonar component archive."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile


CONFIG = Path(__file__).with_name("versions.json")
REPOSITORY = "PANiXiDA-Infrastructure/ci-cd"
ASSET = "sonar-cache.tar.gz"


def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def identity(config):
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]
    return f"sonar-cache-{config['server_version']}-dotnet-{config['scanner_version']}-{fingerprint}"


def output(name, value):
    print(f"{name}={value}")
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "panixida-sonar-cache"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)


def manifest_attributes(jar):
    # JAR manifests fold long values onto continuation lines.
    content = jar.read("META-INF/MANIFEST.MF").decode("utf-8").replace("\r\n", "\n")
    content = content.replace("\n ", "")
    return dict(line.split(": ", 1) for line in content.splitlines() if ": " in line)


def copy_component(source, root, relative):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def build(config, sonar_dir, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        engines = list((sonar_dir / "lib/scanner").glob("sonar-scanner-engine-*.jar"))
        if len(engines) != 1:
            raise ValueError("Expected exactly one scanner engine in the pinned SonarQube image")
        engine = engines[0]
        copy_component(engine, root, f"cache/{digest(engine)}/{engine.name}")
        plugins = []
        roslyn = []
        for plugin in sorted((sonar_dir / "lib/extensions").glob("*.jar")):
            with zipfile.ZipFile(plugin) as jar:
                attributes = manifest_attributes(jar)
                key = attributes["Plugin-Key"]
                version = attributes["Plugin-Version"]
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", key):
                    raise ValueError(f"Invalid plugin key: {key}")
                checksum = digest(plugin, "md5")
                copy_component(plugin, root, f"cache/{checksum}/sonar-{key}-plugin.jar")
                plugins.append({"key": key, "version": version, "hash": checksum})
                if key in ("csharp", "vbnet"):
                    resources = [name for name in jar.namelist()
                                 if name.startswith("static/") and name.endswith(".zip")]
                    if len(resources) != 1:
                        raise ValueError(f"Expected one Roslyn analyzer archive in {key}")
                    resource = resources[0]
                    directory = f"resources/{len(roslyn)}"
                    with zipfile.ZipFile(io.BytesIO(jar.read(resource))) as analyzers:
                        analyzers.extractall(root / directory)
                    roslyn.append({"key": f"{key}/{version}/{Path(resource).name}",
                                   "directory": directory})
        if not plugins or len(roslyn) != 2:
            raise ValueError("The image must include plugins and both .NET analyzers")

        nuget = root / "nuget"
        nuget.mkdir()
        package = f"dotnet-sonarscanner.{config['scanner_version']}.nupkg"
        download(f"https://api.nuget.org/v3-flatcontainer/dotnet-sonarscanner/"
                 f"{config['scanner_version']}/{package}", nuget / package)
        # Preserve upstream notices; the JARs and NuGet package also retain their licenses.
        for name in ("COPYING", "LICENSE", "NOTICE"):
            if (sonar_dir / name).is_file():
                copy_component(sonar_dir / name, root, f"licenses/{name}")
        if (sonar_dir / "licenses").is_dir():
            shutil.copytree(sonar_dir / "licenses", root / "licenses/upstream")
        manifest = {
            "config": config, "tag": identity(config), "plugins": plugins, "roslyn": roslyn,
            "files": {str(path.relative_to(root)).replace("\\", "/"): digest(path)
                      for path in sorted(root.rglob("*")) if path.is_file()},
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        archive = destination / ASSET
        with tarfile.open(archive, "w:gz") as bundle:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    bundle.add(path, arcname=path.relative_to(root), recursive=False)
        (destination / f"{ASSET}.sha256").write_text(f"{digest(archive)}  {ASSET}\n", encoding="utf-8")
        shutil.copyfile(root / "manifest.json", destination / "manifest.json")
        output("tag", identity(config))
        output("archive", archive)


def extract_verified(archive, checksum_file, target, config):
    expected = checksum_file.read_text(encoding="utf-8").split()[0]
    if digest(archive) != expected:
        raise ValueError("Shared Sonar archive SHA-256 mismatch")
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or ":" in member.name):
                raise ValueError(f"Unsafe archive entry: {member.name}")
        bundle.extractall(target, filter="data")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest["config"] != config or manifest["tag"] != identity(config):
        raise ValueError("Shared Sonar archive version mismatch")
    actual = {path.relative_to(target).as_posix(): digest(path)
              for path in target.rglob("*") if path.is_file() and path != target / "manifest.json"}
    if actual != manifest["files"]:
        raise ValueError("Shared Sonar archive file manifest mismatch")
    return manifest


def restore(config, destination, server_version, source=None):
    if server_version != config["server_version"]:
        print(f"::warning::No shared archive configured for SonarQube {server_version}; using normal downloads")
        output("restored", "false")
        return
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        archive = temporary / ASSET
        checksum = temporary / f"{ASSET}.sha256"
        if source:
            shutil.copyfile(source / ASSET, archive)
            shutil.copyfile(source / f"{ASSET}.sha256", checksum)
        else:
            base = f"https://github.com/{REPOSITORY}/releases/download/{identity(config)}"
            try:
                download(f"{base}/{ASSET}.sha256", checksum)
                download(f"{base}/{ASSET}", archive)
            except (OSError, urllib.error.URLError) as error:
                print(f"::warning::Shared Sonar archive unavailable ({error}); using normal downloads")
                output("restored", "false")
                return
        extracted = temporary / "extracted"
        manifest = extract_verified(archive, checksum, extracted, config)
        for directory in ("cache", "resources", "nuget"):
            shutil.copytree(extracted / directory, destination / directory, dirs_exist_ok=True)
        # .NET's Roslyn index contains absolute paths; regenerate it for this runner.
        index = {item["key"]: str((destination / item["directory"]).resolve())
                 for item in manifest["roslyn"]}
        (destination / "resources/index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")
        (destination / "nuget.config").write_text(
            '<configuration><packageSources><clear />'
            '<add key="shared-sonar" value="nuget" />'
            '</packageSources></configuration>\n', encoding="utf-8")
        output("restored", "true")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("info", "build", "restore"))
    parser.add_argument("--sonarqube-dir", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--server-version")
    parser.add_argument("--source", type=Path, help="Local archive directory for offline validation")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if args.command == "info":
        for key in ("scanner_version", "server_version", "server_image"):
            output(key.replace("_", "-"), config[key])
        output("tag", identity(config))
    elif args.command == "build":
        build(config, args.sonarqube_dir, args.destination)
    else:
        restore(config, args.destination, args.server_version, args.source)


if __name__ == "__main__":
    main()
