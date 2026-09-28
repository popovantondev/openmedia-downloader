"""Release-Helfer testen, ohne eine App zu bauen oder Daten hochzuladen."""
import importlib.util
import json
import plistlib
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/create_release.py"
SPEC = importlib.util.spec_from_file_location("release_packaging", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleasePackagingTests(unittest.TestCase):
    def make_source(self, root):
        source = root / "source"
        source.mkdir()
        directories = {"Sources", "Tests", "backend", "scripts", "assets", "docs", "licenses", "vendor"}
        for name in release.SOURCE_ITEMS:
            item = source / name
            item.mkdir() if name in directories else item.write_text("fixture")
        (source / "VERSION").write_text("4.0.1")
        for name in ("RELEASE_README.md", "RELEASE_NOTES_4.0.1.md", "START_RU.txt", "MACOS_SIGNATUR.md"):
            (source / "docs" / name).write_text("Release documentation")
        (source / "scripts/verify_release.command").write_text("#!/bin/zsh\n")
        (source / "licenses/LICENSE.txt").write_text("Public license")
        (source / "vendor/sources").mkdir()
        (source / "vendor/sources/PROVENANCE.md").write_text("Third party sources")
        for name in ("build_ffmpeg.command", "FFMPEG_BUILD_REPORT.md"):
            (source / "vendor" / name).write_text("Public build information")
        app = source / "dist" / release.APP_NAME
        (app / "Contents").mkdir(parents=True)
        metadata = {"CFBundleShortVersionString": "4.0.1", "CFBundleVersion": "401", "LSMinimumSystemVersion": "15.0"}
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
        (app / "Contents/payload").write_text("Original application")
        dmg = source / "dist/OpenMedia-Downloader-4.0.1-macOS-arm64.dmg"
        dmg.write_bytes(b"Original disk image")
        return source, app, dmg, metadata

    def test_invalid_version_cannot_escape_release_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "VERSION").write_text("../../outside")
            with self.assertRaises(ValueError):
                release.read_version(source)

    def test_existing_release_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "VERSION").write_text("4.0.1")
            existing = root / "releases/v4.0.1"
            existing.mkdir(parents=True)
            marker = existing / "keep.txt"
            marker.write_text("unchanged")
            with self.assertRaises(FileExistsError):
                release.create_release(source, root)
            self.assertEqual(marker.read_text(), "unchanged")

    def test_snapshot_excludes_generated_and_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in release.SOURCE_ITEMS:
                (source / name).mkdir() if "." not in name and name not in ("VERSION", "Sources", "Tests") else (source / name).write_text("test")
            backend = source / "backend"
            (backend / "__pycache__").mkdir()
            (backend / "__pycache__/cached.pyc").write_text("cache")
            (backend / "cookies.txt").write_text("private")
            (backend / "example.py").write_text("source")
            paths = {path.relative_to(source).as_posix() for path in release.snapshot_paths(source)}
            self.assertIn("backend/example.py", paths)
            self.assertNotIn("backend/cookies.txt", paths)
            self.assertFalse(any("__pycache__" in path for path in paths))

    def test_checksum_manifest_covers_regular_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file with spaces.txt").write_text("content")
            (root / "alias").symlink_to("file with spaces.txt")
            release.write_checksums(root)
            content = (root / "CHECKSUMS.sha256").read_text()
            self.assertIn("  file with spaces.txt\n", content)
            self.assertNotIn("alias", content)
            self.assertNotIn("CHECKSUMS.sha256", content)

    def test_exclusive_rename_preserves_even_an_empty_existing_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "staged", root / "existing"
            source.mkdir()
            (source / "file").write_text("new")
            destination.mkdir()
            with self.assertRaises(FileExistsError):
                release.rename_exclusive(source, destination)
            self.assertTrue((source / "file").is_file())
            self.assertEqual(list(destination.iterdir()), [])

    def test_bundle_fingerprint_detects_stale_app_with_same_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            for app in (first, second):
                (app / "version.txt").write_text("4.0.1")
                (app / "executable").write_text("same")
            self.assertEqual(release.bundle_fingerprint(first), release.bundle_fingerprint(second))
            (second / "executable").write_text("different build")
            self.assertNotEqual(release.bundle_fingerprint(first), release.bundle_fingerprint(second))

    def test_snapshot_excludes_contents_of_nested_private_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _, _, _ = self.make_source(Path(directory))
            for name in ("cookies-backup", ".ENV-backup", "local", "sessions", "recording.MP4"):
                hidden = source / "backend/nested" / name
                hidden.mkdir(parents=True)
                (hidden / "secret.txt").write_text("private fixture")
            (source / "backend/kept.py").write_text("pass")
            paths = {path.relative_to(source).as_posix() for path in release.snapshot_paths(source)}
            self.assertIn("backend/kept.py", paths)
            self.assertFalse(any("secret.txt" in path for path in paths))
            self.assertFalse(any("cookies-backup" in path or ".ENV-backup" in path for path in paths))

    def test_public_trees_apply_same_private_filter_as_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "licenses"
            source.mkdir()
            (source / "LICENSE.txt").write_text("Public license")
            for name in ("local", "cookies-private", ".env-old"):
                private = source / name
                private.mkdir()
                (private / "data.txt").write_text("private fixture")
            (source / "capture.LOG").write_text("private log")
            destination = root / "public"
            release.copy_public_tree(source, destination)
            self.assertEqual([path.name for path in destination.iterdir()], ["LICENSE.txt"])

    def test_public_tree_rejects_regular_and_private_named_symlinks(self):
        for name in ("linked-license.txt", "cookies.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "licenses"
                source.mkdir()
                private = root / "private.txt"
                private.write_text("private fixture")
                (source / name).symlink_to(private)
                with self.assertRaises(ValueError):
                    release.copy_public_tree(source, root / "public")

    def test_snapshot_rejects_broken_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _, _, _ = self.make_source(Path(directory))
            (source / "backend/link.py").symlink_to(source / "missing.py")
            with self.assertRaises(ValueError):
                list(release.snapshot_paths(source))

    def test_private_archive_is_staged_outside_releases_and_owner_readable_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, app, dmg, metadata = self.make_source(root)
            archive_paths = []
            original_writer = release.write_source_snapshot

            def check_snapshot_location(source_path, archive, version):
                archive_paths.append(archive)
                self.assertIn(root / "source-snapshots", archive.parents)
                self.assertNotIn(root / "releases", archive.parents)
                original_writer(source_path, archive, version)

            with mock.patch.object(release, "verify_build", return_value=(app, dmg, metadata)), mock.patch.object(release, "verify_artifacts", return_value=metadata), mock.patch.object(release, "write_source_snapshot", side_effect=check_snapshot_location):
                destination = release.create_release(source, root)
            self.assertEqual(len(archive_paths), 1)
            archives = list((root / "source-snapshots").glob("*.tar.gz"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(stat.S_IMODE(archives[0].stat().st_mode), 0o600)
            self.assertFalse(any(path.name.endswith("private-source.tar.gz") for path in destination.rglob("*")))
            with tarfile.open(archives[0]) as archive:
                self.assertTrue(all(item.uid == 0 and item.gid == 0 and item.uname == "" and item.gname == "" for item in archive.getmembers()))

    def test_manifest_describes_staged_assets_even_if_original_build_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, app, dmg, metadata = self.make_source(root)
            expected_image = dmg.read_bytes()
            staged_metadata = dict(metadata, CFBundleVersion="verified-staged-build")

            def check_staged(staged_app, staged_dmg, version):
                self.assertNotEqual(staged_app, app)
                self.assertNotEqual(staged_dmg, dmg)
                self.assertIn(root / "releases", staged_app.parents)
                self.assertEqual(staged_dmg.read_bytes(), expected_image)
                self.assertEqual(version, "4.0.1")
                dmg.write_bytes(b"Different concurrent build")
                return staged_metadata

            with mock.patch.object(release, "verify_build", return_value=(app, dmg, metadata)), mock.patch.object(release, "verify_artifacts", side_effect=check_staged) as staged_check:
                destination = release.create_release(source, root)
            staged_check.assert_called_once()
            manifest = json.loads((destination / "manifest.json").read_text())
            copied_dmg = destination / dmg.name
            self.assertEqual(manifest["build"], "verified-staged-build")
            self.assertEqual(manifest["dmg"]["bytes"], len(expected_image))
            self.assertEqual(manifest["dmg"]["sha256"], release.sha256(copied_dmg))
            self.assertNotEqual(manifest["dmg"]["sha256"], release.sha256(dmg))
            private_archive = destination / manifest["privateSource"]["path"]
            self.assertEqual(manifest["privateSource"]["sha256"], release.sha256(private_archive))
            for line in (destination / "CHECKSUMS.sha256").read_text().splitlines():
                checksum, name = line.split("  ", 1)
                self.assertEqual(checksum, release.sha256(destination / name))

    def test_failed_staged_verification_publishes_neither_release_nor_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, app, dmg, metadata = self.make_source(root)
            with mock.patch.object(release, "verify_build", return_value=(app, dmg, metadata)), mock.patch.object(release, "verify_artifacts", side_effect=ValueError("Mismatching staged application")):
                with self.assertRaises(ValueError):
                    release.create_release(source, root)
            self.assertEqual(list((root / "releases").iterdir()), [])
            self.assertEqual(list((root / "source-snapshots").iterdir()), [])
            self.assertEqual((app / "Contents/payload").read_text(), "Original application")

    def test_publish_race_preserves_existing_release_and_rolls_back_new_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, app, dmg, metadata = self.make_source(root)

            def concurrent_release(_staged, destination):
                destination.mkdir()
                (destination / "keep.txt").write_text("Concurrent release")
                raise FileExistsError("Release already exists")

            with mock.patch.object(release, "verify_build", return_value=(app, dmg, metadata)), mock.patch.object(release, "verify_artifacts", return_value=metadata), mock.patch.object(release, "rename_exclusive", side_effect=concurrent_release):
                with self.assertRaises(FileExistsError):
                    release.create_release(source, root)
            self.assertEqual((root / "releases/v4.0.1/keep.txt").read_text(), "Concurrent release")
            self.assertEqual(list((root / "source-snapshots").iterdir()), [])

    def test_existing_private_snapshot_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _, _ = self.make_source(root)
            snapshots = root / "source-snapshots"
            snapshots.mkdir()
            existing = snapshots / "openmedia-downloader-4.0.1-private-source.tar.gz"
            existing.write_bytes(b"Existing archive")
            with self.assertRaises(FileExistsError):
                release.create_release(source, root)
            self.assertEqual(existing.read_bytes(), b"Existing archive")


if __name__ == "__main__":
    unittest.main()
