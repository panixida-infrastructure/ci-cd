import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile


spec = importlib.util.spec_from_file_location(
    "sonar_cache", Path(__file__).parents[1] / ".github/actions/sonar-cache/cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class SharedSonarCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = json.loads(cache.CONFIG.read_text())
        self.image = self.root / "image"
        (self.image / "lib/scanner").mkdir(parents=True)
        (self.image / "lib/scanner/sonar-scanner-engine-test.jar").write_bytes(b"engine")
        (self.image / "lib/extensions").mkdir()
        for key in ("csharp", "vbnet"):
            resources = io.BytesIO()
            with zipfile.ZipFile(resources, "w") as resource:
                resource.writestr("SonarAnalyzer.dll", f"{key} analyzer")
            with zipfile.ZipFile(self.image / f"lib/extensions/{key}.jar", "w") as jar:
                jar.writestr("META-INF/MANIFEST.MF",
                             f"Plugin-Key: {key}\r\nPlugin-Version: 1.2.3\r\n")
                jar.writestr("static/analyzers.zip", resources.getvalue())
        self.archive = self.root / "archive"
        with patch.object(cache, "download", side_effect=lambda url, path: path.write_bytes(b"nupkg")):
            cache.build(self.config, self.image, self.archive)

    def extract(self):
        return cache.extract_verified(self.archive / cache.ASSET,
                                      self.archive / f"{cache.ASSET}.sha256",
                                      self.root / "extracted", self.config)

    def rewrite_archive(self, transform):
        path = self.archive / cache.ASSET
        with tarfile.open(path) as bundle:
            entries = [(item, bundle.extractfile(item).read()) for item in bundle.getmembers()]
        with tarfile.open(path, "w:gz") as bundle:
            for item, content in entries:
                item, content = transform(item, content)
                item.size = len(content)
                bundle.addfile(item, io.BytesIO(content))
        (self.archive / f"{cache.ASSET}.sha256").write_text(cache.digest(path))

    def test_cross_repository_restore_uses_scanner_cache_layout_and_rebases_roslyn_index(self):
        for repository in ("api", "core"):
            target = self.root / repository / ".sonar"
            cache.restore(self.config, target, self.config["server_version"], self.archive)
            engine_hash = hashlib.sha256(b"engine").hexdigest()
            self.assertEqual((target / f"cache/{engine_hash}/sonar-scanner-engine-test.jar").read_bytes(), b"engine")
            index = json.loads((target / "resources/index.json").read_text())
            analyzer = Path(index["csharp/1.2.3/analyzers.zip"])
            self.assertTrue(analyzer.is_relative_to(target))
            self.assertEqual((analyzer / "SonarAnalyzer.dll").read_text(), "csharp analyzer")
            plugin = self.image / "lib/extensions/csharp.jar"
            self.assertTrue((target / f"cache/{cache.digest(plugin, 'md5')}/sonar-csharp-plugin.jar").is_file())

    def test_server_mismatch_does_not_restore_or_download(self):
        with patch.object(cache, "download") as download:
            cache.restore(self.config, self.root / "missing", "different-server")
            download.assert_not_called()
        self.assertFalse((self.root / "missing").exists())

    def test_unpublished_archive_falls_back_without_creating_cache(self):
        error = urllib.error.HTTPError("https://github.com/archive", 404, "Not Found", {}, None)
        with patch.object(cache, "download", side_effect=error):
            cache.restore(self.config, self.root / "missing", self.config["server_version"])
        self.assertFalse((self.root / "missing").exists())

    def test_corrupt_archive_is_rejected(self):
        with (self.archive / cache.ASSET).open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.extract()

    def test_modified_component_is_rejected_even_with_valid_archive_checksum(self):
        self.rewrite_archive(lambda item, content: (item, b"changed")
                             if item.name.endswith(".nupkg") else (item, content))
        with self.assertRaisesRegex(ValueError, "file manifest mismatch"):
            self.extract()

    def test_wrong_version_manifest_is_rejected(self):
        self.config = {**self.config, "revision": self.config["revision"] + 1}
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            self.extract()

    def test_archive_path_traversal_is_rejected(self):
        def traversal(item, content):
            item.name = "../outside"
            return item, content
        self.rewrite_archive(traversal)
        with self.assertRaisesRegex(ValueError, "Unsafe archive entry"):
            self.extract()
        self.assertFalse((self.root / "outside").exists())

    def test_archive_symlink_is_rejected(self):
        def symlink(item, content):
            item.type = tarfile.SYMTYPE
            item.linkname = "/tmp/outside"
            return item, b""
        self.rewrite_archive(symlink)
        with self.assertRaisesRegex(ValueError, "Unsafe archive entry"):
            self.extract()

    def test_image_scanner_or_revision_change_produces_new_archive_identity(self):
        original = cache.identity(self.config)
        for field in ("server_version", "server_image", "scanner_version", "revision"):
            self.assertNotEqual(original, cache.identity({**self.config, field: "changed"}))


if __name__ == "__main__":
    unittest.main()
