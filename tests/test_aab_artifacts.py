import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from synclab_release.apk_verifier import verify_aab_signer, verify_aab_version
from synclab_release.config_loader import load_config
from synclab_release.errors import ConfigError
from synclab_release.models import GradleVersion
from synclab_release.signing_client import sign_aab


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
        "githubRelease": {
            "tagFormat": "v{versionName}",
            "nameFormat": "{project} {versionName}",
            "prerelease": False,
        },
    }


class AabArtifactTest(unittest.TestCase):
    def test_config_defaults_artifact_type_to_apk(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config(None)), encoding="utf-8")
            config = load_config(path)

        self.assertEqual(config.targets["release"].artifact_type, "apk")

    def test_config_accepts_aab_artifact_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config("aab")), encoding="utf-8")
            config = load_config(path)

        self.assertEqual(config.targets["release"].artifact_type, "aab")

    def test_config_rejects_unknown_artifact_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(_config("zip")), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_aab_signing_uses_aab_endpoint_and_field(self):
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
                    metadata={"repo": "owner/repo"},
                    aab_path=source,
                    output_path=output,
                    tls_verify=True,
                )

            self.assertEqual(output.read_bytes(), b"signed-aab")

        request = captured["request"]
        self.assertEqual(request.full_url, "https://sign.synclab.com.vn/v1/sign/android/aab")
        self.assertIn(b'name="aab"', request.data)
        self.assertIn(b'filename="app.aab"', request.data)
        self.assertEqual(request.get_header("X-synclab-api-key"), "secret")

    def test_verify_aab_signer_matches_expected_dn(self):
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "      X.509, CN=Synclab Android Upload, OU=Synclab Signing, O=Synclab\n"
                "jar verified.\n"
            ),
        )
        with patch("synclab_release.apk_verifier._find_tool", return_value="jarsigner"), patch(
            "synclab_release.apk_verifier.run_command", return_value=result
        ):
            verify_aab_signer(
                Path("."),
                Path("app.aab"),
                "CN=Synclab Android Upload, OU=Synclab Signing, O=Synclab",
            )

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
                verify_aab_version(
                    Path("."),
                    Path("app.aab"),
                    GradleVersion("18.0.0.1", 1800000001),
                )


if __name__ == "__main__":
    unittest.main()
