from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


def _repo_permission(repo: str, *, cwd: Path, token: str) -> str:
    data = _gh_json(["gh", "repo", "view", repo, "--json", "viewerPermission"], cwd=cwd, token=token)
    permission = data.get("viewerPermission")
    if not isinstance(permission, str) or not permission:
        raise ShipError(f"Cannot determine token permission for repo: {repo}")
    return permission.upper()


def _target_repo_info(repo: str, *, cwd: Path, token: str) -> tuple[str, str]:
    data = _gh_json(
        ["gh", "repo", "view", repo, "--json", "viewerPermission,defaultBranchRef"],
        cwd=cwd,
        token=token,
    )
    permission = data.get("viewerPermission")
    if not isinstance(permission, str) or not permission:
        raise ShipError(f"Cannot determine token permission for repo: {repo}")
    default_branch_ref = data.get("defaultBranchRef")
    default_branch = default_branch_ref.get("name") if isinstance(default_branch_ref, dict) else None
    if not isinstance(default_branch, str) or not default_branch:
        raise ShipError(f"Cannot determine default branch for target repo: {repo}")
    return permission.upper(), default_branch


def _assert_source_repo_permission(repo: str, *, cwd: Path, token: str) -> str:
    permission = _repo_permission(repo, cwd=cwd, token=token)
    allowed = {"READ", "TRIAGE", "WRITE", "MAINTAIN", "ADMIN"}
    if permission not in allowed:
        raise ShipError(f"Token must have read access to source repo {repo}; current permission: {permission}")
    return permission


def _assert_target_repo_permission(repo: str, *, cwd: Path, token: str) -> str:
    permission = _repo_permission(repo, cwd=cwd, token=token)
    allowed = {"WRITE", "MAINTAIN", "ADMIN"}
    if permission not in allowed:
        raise ShipError(f"Token must have write access to target repo {repo}; current permission: {permission}")
    return permission


def _assert_target_repo_commit_permission(repo: str, *, cwd: Path, token: str) -> tuple[str, str]:
    permission, default_branch = _target_repo_info(repo, cwd=cwd, token=token)
    allowed = {"WRITE", "MAINTAIN", "ADMIN"}
    if permission not in allowed:
        raise ShipError(f"Token must have write access to target repo {repo}; current permission: {permission}")
    return permission, default_branch


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


def _run_git(command: list[str], *, cwd: Path, token: str, check: bool = True):
    env = os.environ.copy()
    auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {auth}"
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


def _checked_git(command: list[str], *, cwd: Path, token: str, failure: str) -> None:
    result = _run_git(command, cwd=cwd, token=token, check=False)
    if result.returncode != 0:
        raise ShipError(f"{failure}\n{result.stdout}")


def _history_dir_name(source_tag: str) -> str:
    return quote(source_tag, safe="")


def _ship_history_dir(target_repo_dir: Path, source_tag: str) -> Path:
    return target_repo_dir / ".synclab" / "ship-history" / _history_dir_name(source_tag)


def _assert_ship_history_missing(target_repo_dir: Path, source_tag: str) -> None:
    if _ship_history_dir(target_repo_dir, source_tag).exists():
        raise ShipError(f"Ship history already exists for source tag: {source_tag}")


def _target_repo_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def _clone_target_repo(repo: str, branch: str, destination: Path, *, token: str) -> None:
    _checked_git(
        ["git", "clone", "--depth", "1", "--branch", branch, _target_repo_url(repo), str(destination)],
        cwd=destination.parent,
        token=token,
        failure=f"Failed to clone target repo {repo}@{branch}",
    )


def _configure_history_author(repo_dir: Path, *, token: str) -> None:
    _checked_git(["git", "config", "user.name", "synclab-release-bot"], cwd=repo_dir, token=token, failure="Failed to configure git user.name")
    _checked_git(
        ["git", "config", "user.email", "release-bot@synclab.local"],
        cwd=repo_dir,
        token=token,
        failure="Failed to configure git user.email",
    )


def _assert_target_repo_push_permission(repo: str, branch: str, source_tag: str, *, token: str) -> None:
    with tempfile.TemporaryDirectory(prefix="synclab-ship-preflight-") as temp:
        repo_dir = Path(temp) / "target"
        _clone_target_repo(repo, branch, repo_dir, token=token)
        _assert_ship_history_missing(repo_dir, source_tag)
        _configure_history_author(repo_dir, token=token)
        marker = repo_dir / ".synclab" / ".ship-push-check"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"preflight {uuid.uuid4()}\n", encoding="utf-8")
        _checked_git(["git", "add", str(marker.relative_to(repo_dir))], cwd=repo_dir, token=token, failure="Failed to stage push preflight marker")
        _checked_git(
            ["git", "commit", "-m", "chore: verify ship history push permission"],
            cwd=repo_dir,
            token=token,
            failure="Failed to create push preflight commit",
        )
        _checked_git(
            ["git", "push", "--dry-run", "origin", f"HEAD:{branch}"],
            cwd=repo_dir,
            token=token,
            failure=f"Token cannot push directly to target repo {repo}@{branch}",
        )


def _copy_history_file(source: Path, destination: Path) -> None:
    if source.exists() and source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _write_ship_history(output_dir: Path, asset_dir: Path, target_repo_dir: Path, source_tag: str) -> Path:
    history_dir = _ship_history_dir(target_repo_dir, source_tag)
    _assert_ship_history_missing(target_repo_dir, source_tag)
    history_dir.mkdir(parents=True)

    for filename in ("ship-manifest.json", "source-release.json", "release-notes.md", "asset-tree.txt"):
        _copy_history_file(output_dir / filename, history_dir / filename)
    _copy_history_file(asset_dir / "metadata.json", history_dir / "metadata.json")
    return history_dir


def _commit_and_push_ship_history(repo: str, branch: str, source_tag: str, output_dir: Path, asset_dir: Path, *, token: str) -> None:
    with tempfile.TemporaryDirectory(prefix="synclab-ship-history-") as temp:
        repo_dir = Path(temp) / "target"
        _clone_target_repo(repo, branch, repo_dir, token=token)
        _configure_history_author(repo_dir, token=token)
        history_dir = _write_ship_history(output_dir, asset_dir, repo_dir, source_tag)
        _checked_git(
            ["git", "add", str(history_dir.relative_to(repo_dir))],
            cwd=repo_dir,
            token=token,
            failure="Failed to stage ship history",
        )
        diff = _run_git(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, token=token, check=False)
        if diff.returncode == 0:
            raise ShipError(f"Ship history has no changes for source tag: {source_tag}")
        if diff.returncode not in (0, 1):
            raise ShipError(f"Failed to inspect staged ship history\n{diff.stdout}")
        _checked_git(
            ["git", "commit", "-m", f"chore: record ship history {source_tag}"],
            cwd=repo_dir,
            token=token,
            failure="Failed to commit ship history",
        )
        _checked_git(
            ["git", "push", "origin", f"HEAD:{branch}"],
            cwd=repo_dir,
            token=token,
            failure=f"Failed to push ship history to target repo {repo}@{branch}",
        )


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
    source_permission = _assert_source_repo_permission(resolved_source_repo, cwd=cwd, token=token)
    target_permission, target_default_branch = _assert_target_repo_commit_permission(resolved_target_repo, cwd=cwd, token=token)
    _assert_target_repo_push_permission(resolved_target_repo, target_default_branch, source_tag, token=token)

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
        "sourcePermission": source_permission,
        "targetPermission": target_permission,
        "targetDefaultBranch": target_default_branch,
        "assetCount": len(asset_paths),
        "verifiedChecksums": verified,
        "assets": [path.name for path in asset_paths],
    }
    _write_json(output_dir / "ship-manifest.json", manifest)

    print(f"Source release verified: {resolved_source_repo}@{source_tag}")
    print(f"Target repo verified: {resolved_target_repo}")
    print(f"Target repo direct push verified: {resolved_target_repo}@{target_default_branch}")
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
    _commit_and_push_ship_history(
        resolved_target_repo,
        target_default_branch,
        source_tag,
        output_dir,
        asset_dir,
        token=token,
    )
    print(f"Shipped release to {resolved_target_repo}@{source_tag}")
    print(f"Recorded ship history in {resolved_target_repo}@{target_default_branch}")
