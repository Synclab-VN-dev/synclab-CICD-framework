import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from synclab_release.errors import SignError
from synclab_release.preflight import _http_get_json_or_text
from synclab_release.signing_client import sign_apk


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class PublicSigningHttpTest(unittest.TestCase):
    def test_profile_request_sets_framework_user_agent(self):
        captured = {}

        def fake_urlopen(request, timeout, context):
            captured["request"] = request
            return _Response(b'[{"name":"preview"}]')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            body = _http_get_json_or_text(
                "https://sign.synclab.com.vn/v1/profiles",
                headers={"X-Synclab-Api-Key": "secret"},
            )

        self.assertIn("preview", body)
        self.assertEqual(captured["request"].get_header("User-agent"), "Synclab-CICD/1.0")
        self.assertEqual(captured["request"].get_header("X-synclab-api-key"), "secret")

    def test_sign_request_sets_framework_user_agent(self):
        captured = {}

        def fake_urlopen(request, timeout, context):
            captured["request"] = request
            return _Response(b"signed-apk")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk = root / "app.apk"
            output = root / "signed.apk"
            apk.write_bytes(b"unsigned-apk")

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                sign_apk(
                    signing_url="https://sign.synclab.com.vn",
                    api_key="secret",
                    profile="prod",
                    metadata={"repo": "owner/repo"},
                    apk_path=apk,
                    output_path=output,
                    tls_verify=True,
                )

            self.assertEqual(output.read_bytes(), b"signed-apk")

        self.assertEqual(captured["request"].get_header("User-agent"), "Synclab-CICD/1.0")
        self.assertEqual(captured["request"].get_header("X-synclab-api-key"), "secret")

    def test_empty_signing_response_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk = root / "app.apk"
            output = root / "signed.apk"
            apk.write_bytes(b"unsigned-apk")
            with patch("urllib.request.urlopen", return_value=_Response(b"")):
                with self.assertRaises(SignError):
                    sign_apk(
                        signing_url="https://sign.synclab.com.vn",
                        api_key="secret",
                        profile="prod",
                        metadata={"repo": "owner/repo"},
                        apk_path=apk,
                        output_path=output,
                        tls_verify=True,
                    )

    def test_http_signing_error_fails(self):
        error = urllib.error.HTTPError(
            "https://sign.synclab.com.vn/v1/sign/android/apk",
            503,
            "Service Unavailable",
            hdrs=None,
            fp=None,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk = root / "app.apk"
            output = root / "signed.apk"
            apk.write_bytes(b"unsigned-apk")
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(SignError):
                    sign_apk(
                        signing_url="https://sign.synclab.com.vn",
                        api_key="secret",
                        profile="prod",
                        metadata={"repo": "owner/repo"},
                        apk_path=apk,
                        output_path=output,
                        tls_verify=True,
                    )


if __name__ == "__main__":
    unittest.main()
