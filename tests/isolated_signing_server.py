#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import glob
import json
import os
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


API_KEY = "ci-secret"


def find_apksigner() -> str:
    direct = shutil.which("apksigner")
    if direct:
        return direct
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        candidates = sorted(glob.glob(str(Path(sdk) / "build-tools" / "*" / "apksigner")), reverse=True)
        if candidates:
            return candidates[0]
    raise RuntimeError("apksigner not found")


class Handler(BaseHTTPRequestHandler):
    server_version = "SynclabCiSigning/1.0"

    def _authorized(self) -> bool:
        return self.headers.get("X-Synclab-Api-Key") == API_KEY

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/v1/profiles":
            self._send_json(404, {"detail": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"detail": "unauthorized"})
            return
        self._send_json(200, {"api_key_name": "ci", "profiles": ["test"]})

    def do_POST(self) -> None:
        if self.path not in {"/v1/sign/android/apk", "/v1/sign/android/aab"}:
            self._send_json(404, {"detail": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"detail": "unauthorized"})
            return

        artifact_type = self.path.rsplit("/", 1)[-1]
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        profile = form.getfirst("profile")
        metadata_raw = form.getfirst("metadata")
        if profile != "test" or not metadata_raw or artifact_type not in form:
            self._send_json(400, {"detail": "invalid multipart contract"})
            return

        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            self._send_json(400, {"detail": "invalid metadata"})
            return

        required = {"repo", "target", "artifactType", "version", "versionCode", "sha", "run_id"}
        if required.difference(metadata) or metadata.get("artifactType") != artifact_type:
            self._send_json(400, {"detail": "missing signing metadata"})
            return

        upload = form[artifact_type]
        data = upload.file.read()
        if not data:
            self._send_json(400, {"detail": "empty artifact"})
            return

        try:
            with tempfile.TemporaryDirectory() as temp:
                temp_path = Path(temp)
                source = temp_path / f"input.{artifact_type}"
                output = temp_path / f"output.{artifact_type}"
                source.write_bytes(data)
                if artifact_type == "apk":
                    subprocess.run(
                        [
                            find_apksigner(),
                            "sign",
                            "--v4-signing-enabled",
                            "false",
                            "--ks",
                            self.server.keystore,
                            "--ks-key-alias",
                            self.server.alias,
                            "--ks-pass",
                            f"pass:{self.server.password}",
                            "--key-pass",
                            f"pass:{self.server.password}",
                            "--out",
                            str(output),
                            str(source),
                        ],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                else:
                    shutil.copy2(source, output)
                    subprocess.run(
                        [
                            "jarsigner",
                            "-keystore",
                            self.server.keystore,
                            "-storetype",
                            "PKCS12",
                            "-storepass",
                            self.server.password,
                            "-keypass",
                            self.server.password,
                            str(output),
                            self.server.alias,
                        ],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                signed = output.read_bytes()
        except Exception as exc:
            print(f"signing failure: {exc}", flush=True)
            self._send_json(500, {"detail": "signing failed"})
            return

        record = {
            "artifactType": artifact_type,
            "profile": profile,
            "metadata": metadata,
            "inputSize": len(data),
            "outputSize": len(signed),
        }
        with Path(self.server.records).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        content_type = (
            "application/vnd.android.package-archive"
            if artifact_type == "apk"
            else "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(signed)))
        self.end_headers()
        self.wfile.write(signed)

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--keystore", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    server.keystore = args.keystore
    server.alias = args.alias
    server.password = args.password
    server.records = args.records
    server.serve_forever()


if __name__ == "__main__":
    main()
