from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .command import run_command
from .errors import VerifyError
from .models import GradleVersion


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_tool(tool: str) -> str:
    resolved = shutil.which(tool)
    if not resolved:
        sdk_root = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
        if sdk_root:
            build_tools = Path(sdk_root) / "build-tools"
            candidates = sorted(build_tools.glob(f"*/{tool}"), reverse=True)
            if candidates:
                return str(candidates[0])
    if not resolved:
        raise VerifyError(f"{tool} not found in PATH or Android SDK build-tools")
    return resolved


def verify_signer(repo_root: Path, apk_path: Path, expected_dn: str | None) -> None:
    if not expected_dn:
        return
    apksigner = _find_tool("apksigner")
    result = run_command([apksigner, "verify", "--print-certs", "--verbose", str(apk_path)], repo_root, check=False)
    if result.returncode != 0:
        raise VerifyError(f"apksigner failed for {apk_path.name}")
    if expected_dn not in result.stdout:
        raise VerifyError(f"{apk_path.name} signer DN mismatch")


def verify_version(repo_root: Path, apk_path: Path, expected: GradleVersion) -> None:
    try:
        aapt = _find_tool("aapt")
    except VerifyError:
        return
    result = run_command([aapt, "dump", "badging", str(apk_path)], repo_root, check=False)
    if result.returncode != 0:
        raise VerifyError(f"aapt failed for {apk_path.name}")
    if f"versionName='{expected.version_name}'" not in result.stdout:
        raise VerifyError(f"{apk_path.name} versionName mismatch")
    if f"versionCode='{expected.version_code}'" not in result.stdout:
        raise VerifyError(f"{apk_path.name} versionCode mismatch")
