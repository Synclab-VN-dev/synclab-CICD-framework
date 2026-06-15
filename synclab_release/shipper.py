from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .apk_verifier import sha256_file
from .errors import ShipError


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _run_gh(command: list[str], *, cwd: Path, token: str, check: bool = True):
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    import subprocess

    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )


def _gh_json(command: list[str], *, cwd: Path, token: str) -> dict[str, Any]:
    result = _run_gh(command, cwd=cwd, token=token, check=False)
    if result.returncode != 0:
        raise ShipError(f"Command failed: {' '.join(command)}\n{result.stdout}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ShipError(f"Invalid JSON from command: {' '.join(command)}") from exc


def _require_repo(value: str, name: str) -> str:
    if not value or "/" not in value or value.count("/") != 1:
        raise ShipError(f"{name} must use OWNER/REPO format")
    owner, repo = value.split("/", 1)
    if not owner or not repo:
        raise ShipError(f"{name} must use OWNER/REPO format")
    return value


def _asset_names(release: dict[str, Any]) -> list[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ShipError("Source release assets response is invalid")
    names = []
    for asset in assets:
        name = asset.get("name") if isinstance(asset, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def validate_source_release(source_tag: str, release: dict[str, Any]) -> list[str]:
    if release.get("isDraft"):
        raise ShipError(f"Source release is draft: {source_tag}")
    names = _asset_names(release)
    if not names:
        raise ShipError(f"Source release has no assets: {source_tag}")
    if "metadata.json" not in names:
        raise ShipError("Source release is missing metadata.json")
    if "checksum.sha256" not in names:
        raise ShipError("Source release is missing checksum.sha256")
    return names


def _safe_checksum_entries(checksum_path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line_no, raw_line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ShipError(f"Invalid checksum line {line_no}: {raw_line}")
        digest, filename = parts
        filename = filename.strip()
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise ShipError(f"Invalid sha256 digest on checksum line {line_no}")
        path = Path(filename)
        if path.is_absolute() or ".." in path.parts or filename.endswith("/"):
            raise ShipError(f"Unsafe checksum filename on line {line_no}: {filename}")
        entries.append((digest.lower(), filename))
    if not entries:
        raise ShipError("checksum.sha256 has no entries")
    return entries


def verify_checksum_file(asset_dir: Path) -> dict[str, str]:
    checksum_path = asset_dir / "checksum.sha256"
    if not checksum_path.exists():
        raise ShipError("Source release is missing checksum.sha256")

    verified: dict[str, str] = {}
    for expected, filename in _safe_checksum_entries(checksum_path):
        asset_path = asset_dir / filename
        if not asset_path.exists() or not asset_path.is_file():
            raise ShipError(f"Checksum entry points to missing asset: {filename}")
        actual = sha256_file(asset_path)
        if actual.lower() != expected:
            raise ShipError(f"Checksum mismatch for {filename}")
        verified[filename] = actual
    return verified


def _write_tree(directory: Path, output: Path) -> None:
    lines = []
    for item in sorted(directory.rglob("*")):
        rel = item.relative_to(directory)
        suffix = f" ({item.stat().st_size} bytes)" if item.is_file() else "/"
        lines.append(f"{rel}{suffix}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _release_notes(release: dict[str, Any], source_repo: str, source_tag: str) -> str:
    body = release.get("body") if isinstance(release.get("body"), str) else ""
    source_url = release.get("url") if isinstance(release.get("url"), str) else ""
    prefix = (
        f"Shipped from `{source_repo}` release `{source_tag}`.\n\n"
        f"Source release: {source_url or source_repo}\n\n"
    )
    return prefix + body


def ship_release(
    *,
    source_tag: str,
    target_repo: str,
    source_repo: str | None,
    output_dir: Path,
    dry_run: bool,
) -> None:
    token = os.getenv("RELEASE_GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise ShipError("RELEASE_GH_TOKEN or GITHUB_TOKEN is required")
    if not source_tag:
        raise ShipError("source tag is required")

    resolved_source_repo = _require_repo(source_repo or os.getenv("GITHUB_REPOSITORY", ""), "source repo")
    resolved_target_repo = _require_repo(target_repo, "target repo")
    if resolved_source_repo == resolved_target_repo:
        raise ShipError("target repo must be different from source repo")

    output_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = output_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)

    cwd = Path.cwd()
    source_release = _gh_json(
        [
            "gh",
            "release",
            "view",
            source_tag,
            "--repo",
            resolved_source_repo,
            "--json",
            "tagName,name,body,isDraft,isPrerelease,assets,url",
        ],
        cwd=cwd,
        token=token,
    )
    _write_json(output_dir / "source-release.json", source_release)

    validate_source_release(source_tag, source_release)

    target_result = _run_gh(
        ["gh", "repo", "view", resolved_target_repo, "--json", "nameWithOwner"],
        cwd=cwd,
        token=token,
        check=False,
    )
    if target_result.returncode != 0:
        raise ShipError(f"Cannot access target repo: {resolved_target_repo}\n{target_result.stdout}")

    target_release = _run_gh(
        ["gh", "release", "view", source_tag, "--repo", resolved_target_repo],
        cwd=cwd,
        token=token,
        check=False,
    )
    if target_release.returncode == 0:
        raise ShipError(f"Target release already exists: {resolved_target_repo}@{source_tag}")

    download = _run_gh(
        ["gh", "release", "download", source_tag, "--repo", resolved_source_repo, "--dir", str(asset_dir), "--clobber"],
        cwd=cwd,
        token=token,
        check=False,
    )
    if download.returncode != 0:
        raise ShipError(f"Failed to download source release assets\n{download.stdout}")

    _write_tree(asset_dir, output_dir / "asset-tree.txt")
    verified = verify_checksum_file(asset_dir)
    notes = _release_notes(source_release, resolved_source_repo, source_tag)
    notes_path = output_dir / "release-notes.md"
    notes_path.write_text(notes, encoding="utf-8")

    asset_paths = sorted(path for path in asset_dir.iterdir() if path.is_file())
    manifest = {
        "sourceRepo": resolved_source_repo,
        "targetRepo": resolved_target_repo,
        "sourceTag": source_tag,
        "dryRun": dry_run,
        "assetCount": len(asset_paths),
        "verifiedChecksums": verified,
        "assets": [path.name for path in asset_paths],
    }
    _write_json(output_dir / "ship-manifest.json", manifest)

    print(f"Source release verified: {resolved_source_repo}@{source_tag}")
    print(f"Target repo verified: {resolved_target_repo}")
    print(f"Downloaded {len(asset_paths)} asset(s) into {asset_dir}")

    if dry_run:
        print("Dry-run enabled; skipping target release creation")
        return

    title = source_release.get("name") if isinstance(source_release.get("name"), str) and source_release.get("name") else source_tag
    create_command = [
        "gh",
        "release",
        "create",
        source_tag,
        "--repo",
        resolved_target_repo,
        "--draft",
        "--title",
        title,
        "--notes-file",
        str(notes_path),
    ]
    if source_release.get("isPrerelease"):
        create_command.append("--prerelease")
    create_command.extend(str(path) for path in asset_paths)

    create = _run_gh(create_command, cwd=cwd, token=token, check=False)
    if create.returncode != 0:
        raise ShipError(f"Failed to create target release\n{create.stdout}")
    publish = _run_gh(
        ["gh", "release", "edit", source_tag, "--repo", resolved_target_repo, "--draft=false"],
        cwd=cwd,
        token=token,
        check=False,
    )
    if publish.returncode != 0:
        raise ShipError(f"Failed to publish target release\n{publish.stdout}")
    print(f"Shipped release to {resolved_target_repo}@{source_tag}")
