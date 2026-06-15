import tempfile
import unittest
from pathlib import Path

from synclab_release.apk_verifier import sha256_file
from synclab_release.errors import ShipError
from synclab_release.shipper import _require_repo, validate_source_release, verify_checksum_file


class ShipperTest(unittest.TestCase):
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
