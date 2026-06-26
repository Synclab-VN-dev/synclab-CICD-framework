import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from synclab_release.apk_verifier import sha256_file
from synclab_release.errors import ShipError
from synclab_release.shipper import (
    _assert_target_repo_commit_permission,
    _assert_target_repo_push_permission,
    _assert_source_repo_permission,
    _assert_target_repo_permission,
    _history_dir_name,
    _require_repo,
    _write_ship_history,
    validate_source_release,
    verify_checksum_file,
)


class ShipperTest(unittest.TestCase):
    def test_accepts_source_read_permission(self):
        with patch("synclab_release.shipper._gh_json", return_value={"viewerPermission": "READ"}):
            permission = _assert_source_repo_permission("owner/repo", cwd=Path("."), token="token")

        self.assertEqual(permission, "READ")

    def test_accepts_target_write_permission(self):
        with patch("synclab_release.shipper._gh_json", return_value={"viewerPermission": "WRITE"}):
            permission = _assert_target_repo_permission("owner/repo", cwd=Path("."), token="token")

        self.assertEqual(permission, "WRITE")

    def test_rejects_unknown_source_permission(self):
        with patch("synclab_release.shipper._gh_json", return_value={"viewerPermission": ""}):
            with self.assertRaises(ShipError):
                _assert_source_repo_permission("owner/repo", cwd=Path("."), token="token")

    def test_rejects_target_read_permission(self):
        with patch("synclab_release.shipper._gh_json", return_value={"viewerPermission": "READ"}):
            with self.assertRaises(ShipError):
                _assert_target_repo_permission("owner/read-only", cwd=Path("."), token="token")

    def test_reads_target_default_branch_for_commit_permission(self):
        response = {"viewerPermission": "WRITE", "defaultBranchRef": {"name": "main"}}
        with patch("synclab_release.shipper._gh_json", return_value=response):
            permission, branch = _assert_target_repo_commit_permission("owner/repo", cwd=Path("."), token="token")

        self.assertEqual(permission, "WRITE")
        self.assertEqual(branch, "main")

    def test_rejects_target_without_default_branch(self):
        response = {"viewerPermission": "WRITE", "defaultBranchRef": None}
        with patch("synclab_release.shipper._gh_json", return_value=response):
            with self.assertRaises(ShipError):
                _assert_target_repo_commit_permission("owner/repo", cwd=Path("."), token="token")

    def test_history_dir_name_url_encodes_source_tag(self):
        self.assertEqual(_history_dir_name("v1.2.3"), "v1.2.3")
        self.assertEqual(_history_dir_name("release/v1.2.3"), "release%2Fv1.2.3")

    def test_push_preflight_fails_when_dry_run_push_fails(self):
        calls = []

        def fake_run(command, *, cwd, token, check=True):
            calls.append(command)
            if command[:3] == ["git", "push", "--dry-run"]:
                return CompletedProcess(command, 1, stdout="protected branch")
            return CompletedProcess(command, 0, stdout="")

        with patch("synclab_release.shipper._run_git", side_effect=fake_run):
            with self.assertRaises(ShipError) as context:
                _assert_target_repo_push_permission("owner/repo", "main", "v1", token="token")

        self.assertIn("Token cannot push directly", str(context.exception))
        self.assertTrue(any(command[:3] == ["git", "push", "--dry-run"] for command in calls))

    def test_push_preflight_rejects_existing_history_before_push(self):
        def fake_clone(repo, branch, destination, *, token):
            history_dir = destination / ".synclab" / "ship-history" / "v1"
            history_dir.mkdir(parents=True)

        with patch("synclab_release.shipper._clone_target_repo", side_effect=fake_clone):
            with patch("synclab_release.shipper._run_git") as run_git:
                with self.assertRaises(ShipError):
                    _assert_target_repo_push_permission("owner/repo", "main", "v1", token="token")

        run_git.assert_not_called()

    def test_writes_ship_history_without_apk_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_dir = root / "out"
            asset_dir = root / "assets"
            repo_dir = root / "target"
            output_dir.mkdir()
            asset_dir.mkdir()
            repo_dir.mkdir()
            for filename in ("ship-manifest.json", "source-release.json", "release-notes.md", "asset-tree.txt"):
                (output_dir / filename).write_text(filename, encoding="utf-8")
            (asset_dir / "metadata.json").write_text("{}", encoding="utf-8")
            (asset_dir / "app.apk").write_bytes(b"apk")

            history_dir = _write_ship_history(output_dir, asset_dir, repo_dir, "release/v1")

            self.assertEqual(history_dir.relative_to(repo_dir), Path(".synclab/ship-history/release%2Fv1"))
            self.assertTrue((history_dir / "ship-manifest.json").exists())
            self.assertTrue((history_dir / "metadata.json").exists())
            self.assertFalse((history_dir / "app.apk").exists())

    def test_rejects_existing_ship_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_dir = root / "out"
            asset_dir = root / "assets"
            repo_dir = root / "target"
            output_dir.mkdir()
            asset_dir.mkdir()
            (repo_dir / ".synclab" / "ship-history" / "v1").mkdir(parents=True)

            with self.assertRaises(ShipError):
                _write_ship_history(output_dir, asset_dir, repo_dir, "v1")

    def test_requires_owner_repo_format(self):
        self.assertEqual(_require_repo("Synclab-VN-dev/batmon", "target repo"), "Synclab-VN-dev/batmon")
        for value in ("", "batmon", "a/b/c", "/batmon", "Synclab-VN-dev/"):
            with self.subTest(value=value):
                with self.assertRaises(ShipError):
                    _require_repo(value, "target repo")

    def test_verifies_checksum_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "app.apk"
            asset.write_bytes(b"apk")
            digest = sha256_file(asset)
            (root / "checksum.sha256").write_text(f"{digest}  app.apk\n", encoding="utf-8")

            self.assertEqual(verify_checksum_file(root), {"app.apk": digest})

    def test_validates_source_release(self):
        release = {"isDraft": False, "assets": [{"name": "metadata.json"}, {"name": "checksum.sha256"}, {"name": "app.apk"}]}

        self.assertEqual(validate_source_release("v1", release), ["metadata.json", "checksum.sha256", "app.apk"])

    def test_rejects_draft_source_release(self):
        release = {"isDraft": True, "assets": [{"name": "metadata.json"}, {"name": "checksum.sha256"}]}

        with self.assertRaises(ShipError):
            validate_source_release("v1", release)

    def test_rejects_source_release_without_assets(self):
        with self.assertRaises(ShipError):
            validate_source_release("v1", {"isDraft": False, "assets": []})

    def test_rejects_source_release_without_metadata(self):
        release = {"isDraft": False, "assets": [{"name": "checksum.sha256"}, {"name": "app.apk"}]}

        with self.assertRaises(ShipError):
            validate_source_release("v1", release)

    def test_rejects_source_release_without_checksum(self):
        release = {"isDraft": False, "assets": [{"name": "metadata.json"}, {"name": "app.apk"}]}

        with self.assertRaises(ShipError):
            validate_source_release("v1", release)

    def test_rejects_missing_checksum_file(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ShipError):
                verify_checksum_file(Path(temp))

    def test_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app.apk").write_bytes(b"apk")
            (root / "checksum.sha256").write_text("0" * 64 + "  app.apk\n", encoding="utf-8")

            with self.assertRaises(ShipError):
                verify_checksum_file(root)

    def test_rejects_missing_asset_from_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checksum.sha256").write_text("0" * 64 + "  app.apk\n", encoding="utf-8")

            with self.assertRaises(ShipError):
                verify_checksum_file(root)

    def test_rejects_unsafe_checksum_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checksum.sha256").write_text("0" * 64 + "  ../app.apk\n", encoding="utf-8")

            with self.assertRaises(ShipError):
                verify_checksum_file(root)


if __name__ == "__main__":
    unittest.main()
