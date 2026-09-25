import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from synclab_release.apk_verifier import verify_aab_signer, verify_aab_version
from synclab_release.config_loader import load_config
from synclab_release.errors import ConfigError, PreflightError, VerifyError
from synclab_release.models import GradleVersion
from synclab_release.signing_client import sign_aab
from synclab_release.staged_pipeline import validate_signing_mode_for_plan


TEST_FP = "A1" * 32
TEST_FP_COLON = ":".join(TEST_FP[i:i+2] for i in range(0, len(TEST_FP), 2))


class _Response:
    def __init__(self, body: bytes):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return self.body


def _config(artifact_type: str | None) -> dict:
    target = {
        "buildCommand": ["./gradlew", "bundleRelease"],
        "artifactPattern": "app/build/outputs/bundle/release/*.aab",
        "assetName": "app-{versionName}.aab",
        "signing": {
            "enabled": True,
            "profile": "prod",
            "expectedSignerDn": "CN=Synclab Android Upload",
        },
    }
    if artifact_type is not None:
        target["artifactType"] = artifact_type
    if artifact_type == "aab":
        target["signing"]["expectedSignerSha256"] = TEST_FP_COLON
    return {
        "schemaVersion": 1,
        "project": {"name": "test"},
        "version": {
            "source": "gradle",
            "file": "version.gradle",
            "versionNameScheme": "quad",
            "versionCodeFormula": "a*100000000+b*1000000+c*10000+d",
        },
        "bundle": {"name": "android", "targets": ["release"]},
        "targets": {"release": target},
        "githubRelease": {"tagFormat": "v{versionName}", "nameFormat": "{project} {versionName}", "prerelease": False},
    }


class AabArtifactTest(unittest.TestCase):
    def test_config_defaults_artifact_type_to_apk(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config(None)), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.targets["release"].artifact_type, "apk")

    def test_config_accepts_aab_and_normalizes_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config("aab")), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.targets["release"].artifact_type, "aab")
        self.assertEqual(config.targets["release"].signing.expected_signer_sha256, TEST_FP)

    def test_signed_aab_requires_expected_fingerprint(self):
        raw = _config("aab")
        del raw["targets"]["release"]["signing"]["expectedSignerSha256"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_config_rejects_invalid_fingerprint(self):
        raw = _config("aab")
        raw["targets"]["release"]["signing"]["expectedSignerSha256"] = "bad"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_config_rejects_unknown_artifact_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config("zip")), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_aab_signing_uses_aab_endpoint_field_profile_and_metadata(self):
        captured = {}
        def fake_urlopen(request, timeout, context):
            captured["request"] = request
            return _Response(b"signed-aab")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "app.aab"
            output = root / "signed.aab"
            source.write_bytes(b"unsigned-aab")
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                sign_aab(
                    signing_url="https://sign.synclab.com.vn",
                    api_key="secret",
                    profile="prod",
                    metadata={"repo": "owner/repo", "artifactType": "aab"},
                    aab_path=source,
                    output_path=output,
                    tls_verify=True,
                )
        request = captured["request"]
        self.assertEqual(request.full_url, "https://sign.synclab.com.vn/v1/sign/android/aab")
        self.assertIn(b'name="aab"', request.data)
        self.assertIn(b'name="profile"', request.data)
        self.assertIn(b'name="metadata"', request.data)
        self.assertIn(b'"artifactType":"aab"', request.data)

    def test_verify_aab_signer_checks_integrity_dn_and_fingerprint(self):
        calls = [
            SimpleNamespace(returncode=0, stdout="X.509, CN=Synclab Android Upload\njar verified.\n"),
            SimpleNamespace(returncode=4, stdout="self-signed certificate warning\n"),
            SimpleNamespace(returncode=0, stdout=f"SHA256: {TEST_FP_COLON}\n"),
        ]
        with patch("synclab_release.apk_verifier._find_tool", side_effect=lambda tool: tool), patch(
            "synclab_release.apk_verifier.run_command", side_effect=calls
        ):
            verify_aab_signer(Path("."), Path("app.aab"), "CN=Synclab Android Upload", TEST_FP)

    def test_verify_aab_signer_rejects_unsigned_entries(self):
        calls = [
            SimpleNamespace(returncode=0, stdout="CN=Synclab Android Upload\njar verified.\n"),
            SimpleNamespace(returncode=20, stdout="unsigned entries + self-signed warning\n"),
        ]
        with patch("synclab_release.apk_verifier._find_tool", return_value="jarsigner"), patch(
            "synclab_release.apk_verifier.run_command", side_effect=calls
        ):
            with self.assertRaises(VerifyError) as raised:
                verify_aab_signer(Path("."), Path("app.aab"), "CN=Synclab Android Upload", TEST_FP)
        self.assertIn("unsigned entries", raised.exception.message)

    def test_verify_aab_signer_rejects_wrong_fingerprint(self):
        wrong = "B2" * 32
        wrong_colon = ":".join(wrong[i:i+2] for i in range(0, len(wrong), 2))
        calls = [
            SimpleNamespace(returncode=0, stdout="CN=Synclab Android Upload\njar verified.\n"),
            SimpleNamespace(returncode=4, stdout="self-signed warning\n"),
            SimpleNamespace(returncode=0, stdout=f"SHA256: {wrong_colon}\n"),
        ]
        with patch("synclab_release.apk_verifier._find_tool", side_effect=lambda tool: tool), patch(
            "synclab_release.apk_verifier.run_command", side_effect=calls
        ):
            with self.assertRaises(VerifyError):
                verify_aab_signer(Path("."), Path("app.aab"), "CN=Synclab Android Upload", TEST_FP)

    def test_verify_aab_signer_rejects_corrupted_signature(self):
        with patch("synclab_release.apk_verifier._find_tool", return_value="jarsigner"), patch(
            "synclab_release.apk_verifier.run_command",
            return_value=SimpleNamespace(returncode=1, stdout="security exception"),
        ):
            with self.assertRaises(VerifyError):
                verify_aab_signer(Path("."), Path("app.aab"), "CN=Synclab Android Upload", TEST_FP)

    def test_verify_aab_version_reads_bundletool_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            bundletool = Path(temp) / "bundletool.jar"
            bundletool.write_bytes(b"stub")
            calls = [
                SimpleNamespace(returncode=0, stdout="18.0.0.1\n"),
                SimpleNamespace(returncode=0, stdout="1800000001\n"),
            ]
            with patch.dict(os.environ, {"BUNDLETOOL_JAR": str(bundletool)}, clear=False), patch(
                "synclab_release.apk_verifier._find_tool", return_value="java"
            ), patch("synclab_release.apk_verifier.run_command", side_effect=calls):
                verify_aab_version(Path("."), Path("app.aab"), GradleVersion("18.0.0.1", 1800000001))

    def test_verify_aab_version_rejects_wrong_version(self):
        with tempfile.TemporaryDirectory() as temp:
            bundletool = Path(temp) / "bundletool.jar"
            bundletool.write_bytes(b"stub")
            calls = [SimpleNamespace(returncode=0, stdout="18.0.0.2\n"), SimpleNamespace(returncode=0, stdout="1800000001\n")]
            with patch.dict(os.environ, {"BUNDLETOOL_JAR": str(bundletool)}, clear=False), patch(
                "synclab_release.apk_verifier._find_tool", return_value="java"
            ), patch("synclab_release.apk_verifier.run_command", side_effect=calls):
                with self.assertRaises(VerifyError):
                    verify_aab_version(Path("."), Path("app.aab"), GradleVersion("18.0.0.1", 1800000001))

    def test_verify_aab_version_requires_bundletool(self):
        with patch.dict(os.environ, {}, clear=True), patch("synclab_release.apk_verifier._find_tool", return_value="java"):
            with self.assertRaises(VerifyError):
                verify_aab_version(Path("."), Path("app.aab"), GradleVersion("18.0.0.1", 1800000001))

    def test_self_hosted_mode_rejects_signed_aab_early(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "release-plan.json"
            plan.write_text(json.dumps({"targets": [{"name": "play", "artifactType": "aab", "signingEnabled": True}]}), encoding="utf-8")
            with self.assertRaises(PreflightError):
                validate_signing_mode_for_plan(plan, "self-hosted")

    def test_public_api_mode_accepts_signed_aab(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "release-plan.json"
            plan.write_text(json.dumps({"targets": [{"name": "play", "artifactType": "aab", "signingEnabled": True}]}), encoding="utf-8")
            validate_signing_mode_for_plan(plan, "public-api")


if __name__ == "__main__":
    unittest.main()
