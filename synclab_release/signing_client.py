from __future__ import annotations

import json
import os
import ssl
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from .errors import SignError


def sign_apk(
    *,
    signing_url: str,
    api_key: str,
    profile: str,
    metadata: dict[str, str],
    apk_path: Path,
    output_path: Path,
    tls_verify: bool,
) -> Path:
    boundary = f"----synclab-{uuid.uuid4().hex}"
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")

    add_field("profile", profile)
    add_field("metadata", json.dumps(metadata, separators=(",", ":")))
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="apk"; filename="{apk_path.name}"\r\n'
        "Content-Type: application/vnd.android.package-archive\r\n\r\n".encode()
    )
    body.extend(apk_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"{signing_url.rstrip('/')}/v1/sign/android/apk",
        data=bytes(body),
        headers={
            "X-Synclab-Api-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    context = None if tls_verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            output_path.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SignError(f"NAS returned HTTP {exc.code}") from exc
    except OSError as exc:
        raise SignError(f"NAS signing request failed: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SignError("NAS returned an empty signed APK")
    return output_path


def api_key_for_profile(profile: str) -> str:
    env_name = f"SYNCLAB_SIGNING_API_KEY_{profile.upper()}"
    value = os.getenv(env_name)
    if not value:
        raise SignError(f"{env_name} is required")
    return value
