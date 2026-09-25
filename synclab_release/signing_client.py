from __future__ import annotations

import json
import os
import ssl
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from .errors import SignError


_ARTIFACT_HTTP = {
    "apk": {
        "field": "apk",
        "content_type": "application/vnd.android.package-archive",
        "accept": "application/vnd.android.package-archive",
    },
    "aab": {
        "field": "aab",
        "content_type": "application/octet-stream",
        "accept": "application/octet-stream",
    },
}


def sign_android_artifact(
    *,
    signing_url: str,
    api_key: str,
    profile: str,
    metadata: dict[str, str],
    artifact_type: str,
    artifact_path: Path,
    output_path: Path,
    tls_verify: bool,
) -> Path:
    if artifact_type not in _ARTIFACT_HTTP:
        raise SignError(f"Unsupported Android artifact type: {artifact_type}")

    http = _ARTIFACT_HTTP[artifact_type]
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
        (
            f'Content-Disposition: form-data; name="{http["field"]}"; filename="{artifact_path.name}"\r\n'
            f'Content-Type: {http["content_type"]}\r\n\r\n'
        ).encode()
    )
    body.extend(artifact_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"{signing_url.rstrip('/')}/v1/sign/android/{artifact_type}",
        data=bytes(body),
        headers={
            "X-Synclab-Api-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Synclab-CICD/1.0",
            "Accept": http["accept"],
        },
        method="POST",
    )
    context = None if tls_verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            output_path.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SignError(f"NAS returned HTTP {exc.code} for {artifact_type} signing") from exc
    except OSError as exc:
        raise SignError(f"NAS {artifact_type} signing request failed: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SignError(f"NAS returned an empty signed {artifact_type.upper()}")
    return output_path


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
    return sign_android_artifact(
        signing_url=signing_url,
        api_key=api_key,
        profile=profile,
        metadata=metadata,
        artifact_type="apk",
        artifact_path=apk_path,
        output_path=output_path,
        tls_verify=tls_verify,
    )


def sign_aab(
    *,
    signing_url: str,
    api_key: str,
    profile: str,
    metadata: dict[str, str],
    aab_path: Path,
    output_path: Path,
    tls_verify: bool,
) -> Path:
    return sign_android_artifact(
        signing_url=signing_url,
        api_key=api_key,
        profile=profile,
        metadata=metadata,
        artifact_type="aab",
        artifact_path=aab_path,
        output_path=output_path,
        tls_verify=tls_verify,
    )


def api_key_for_profile(profile: str) -> str:
    env_name = f"SYNCLAB_SIGNING_API_KEY_{profile.upper()}"
    value = os.getenv(env_name)
    if not value:
        raise SignError(f"{env_name} is required")
    return value
