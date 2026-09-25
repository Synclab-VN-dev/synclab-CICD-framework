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


def _bundletool_jar() -> Path:
    raw = os.getenv("BUNDLETOOL_JAR")
    if not raw:
        raise VerifyError("BUNDLETOOL_JAR is required to verify AAB metadata")
    path = Path(raw)
    if not path.is_file():
        raise VerifyError(f"BUNDLETOOL_JAR does not exist: {path}")
    return path


def _bundletool_manifest_value(repo_root: Path, aab_path: Path, xpath: str) -> str:
    java = _find_tool("java")
    result = run_command(
        [
            java,
            "-jar",
            str(_bundletool_jar()),
            "dump",
            "manifest",
            f"--bundle={aab_path}",
            f"--xpath={xpath}",
        ],
        repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise VerifyError(f"bundletool failed for {aab_path.name}: {xpath}")
    return result.stdout.strip().strip('"')


def verify_signer(repo_root: Path, apk_path: Path, expected_dn: str | None) -> None:
    if not expected_dn:
        return
    apksigner = _find_tool("apksigner")
    result = run_command([apksigner, "verify", "--print-certs", "--verbose", str(apk_path)], repo_root, check=False)
    if result.returncode != 0:
        raise VerifyError(f"apksigner failed for {apk_path.name}")
    if expected_dn not in result.stdout:
        raise VerifyError(f"{apk_path.name} signer DN mismatch")


def verify_aab_signer(repo_root: Path, aab_path: Path, expected_dn: str | None) -> None:
    if not expected_dn:
        return
    jarsigner = _find_tool("jarsigner")
    result = run_command([jarsigner, "-verify", "-verbose", "-certs", str(aab_path)], repo_root, check=False)
    output = result.stdout
    if result.returncode != 0 or "jar verified." not in output.lower():
        raise VerifyError(f"jarsigner failed for {aab_path.name}")
    if expected_dn not in output:
        raise VerifyError(f"{aab_path.name} signer DN mismatch")


def verify_artifact_signer(
    repo_root: Path,
    artifact_path: Path,
    artifact_type: str,
    expected_dn: str | None,
) -> None:
    if artifact_type == "apk":
        verify_signer(repo_root, artifact_path, expected_dn)
        return
    if artifact_type == "aab":
        verify_aab_signer(repo_root, artifact_path, expected_dn)
        return
    raise VerifyError(f"Unsupported Android artifact type: {artifact_type}")


def assert_unsigned(repo_root: Path, apk_path: Path) -> None:
    apksigner = _find_tool("apksigner")
    result = run_command([apksigner, "verify", "--verbose", str(apk_path)], repo_root, check=False)
    if result.returncode == 0:
        raise VerifyError(f"{apk_path.name} is already signed; signing targets must provide unsigned APKs")


def assert_unsigned_aab(repo_root: Path, aab_path: Path) -> None:
    jarsigner = _find_tool("jarsigner")
    result = run_command([jarsigner, "-verify", "-verbose", "-certs", str(aab_path)], repo_root, check=False)
    output = result.stdout.lower()
    if "jar is unsigned" in output:
        return
    if result.returncode == 0:
        raise VerifyError(f"{aab_path.name} is already signed; signing targets must provide unsigned AABs")
    raise VerifyError(f"Unable to verify unsigned AAB state for {aab_path.name}")


def assert_unsigned_artifact(repo_root: Path, artifact_path: Path, artifact_type: str) -> None:
    if artifact_type == "apk":
        assert_unsigned(repo_root, artifact_path)
        return
    if artifact_type == "aab":
        assert_unsigned_aab(repo_root, artifact_path)
        return
    raise VerifyError(f"Unsupported Android artifact type: {artifact_type}")


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


def verify_aab_version(repo_root: Path, aab_path: Path, expected: GradleVersion) -> None:
    version_name = _bundletool_manifest_value(repo_root, aab_path, "/manifest/@android:versionName")
    version_code = _bundletool_manifest_value(repo_root, aab_path, "/manifest/@android:versionCode")
    if version_name != expected.version_name:
        raise VerifyError(f"{aab_path.name} versionName mismatch")
    if version_code != str(expected.version_code):
        raise VerifyError(f"{aab_path.name} versionCode mismatch")


def verify_artifact_version(
    repo_root: Path,
    artifact_path: Path,
    artifact_type: str,
    expected: GradleVersion,
) -> None:
    if artifact_type == "apk":
        verify_version(repo_root, artifact_path, expected)
        return
    if artifact_type == "aab":
        verify_aab_version(repo_root, artifact_path, expected)
        return
    raise VerifyError(f"Unsupported Android artifact type: {artifact_type}")
