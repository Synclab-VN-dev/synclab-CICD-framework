from __future__ import annotations

import os
from pathlib import Path

from .command import run_command
from .errors import PublishError
from .models import ReleaseConfig, ResolvedVersion


def publish_release(repo_root: Path, config: ReleaseConfig, resolved: ResolvedVersion, files: list[Path]) -> None:
    token = os.getenv("RELEASE_GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise PublishError("RELEASE_GH_TOKEN or GITHUB_TOKEN is required")

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    tag = config.github_release.tag_format.format(versionName=resolved.next.version_name)
    title = config.github_release.name_format.format(
        project=config.project_name,
        versionName=resolved.next.version_name,
        versionCode=resolved.next.version_code,
    )

    def run(command: list[str]) -> None:
        import subprocess

        result = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if result.returncode != 0:
            raise PublishError(f"Command failed: {' '.join(command)}\n{result.stdout}")

    run(["git", "config", "user.name", "synclab-release-bot"])
    run(["git", "config", "user.email", "release-bot@synclab.local"])
    run(["git", "add", str(config.version.file)])
    run(["git", "commit", "-m", f"Release {resolved.next.version_name}"])
    run(["git", "tag", "-a", tag, "-m", title])
    run(["git", "push", "origin", "HEAD"])
    run(["git", "push", "origin", tag])

    notes = (
        f"Synclab release for {config.project_name} {resolved.next.version_name}\n\n"
        f"- versionCode: {resolved.next.version_code}\n"
        f"- mode: {resolved.mode}\n"
    )
    release_command = [
        "gh",
        "release",
        "create",
        tag,
        "--draft",
        "--title",
        title,
        "--notes",
        notes,
    ]
    if config.github_release.prerelease:
        release_command.append("--prerelease")
    release_command.extend(str(path) for path in files)
    run(release_command)
    run(["gh", "release", "edit", tag, "--draft=false"])


def assert_release_missing(repo_root: Path, config: ReleaseConfig, resolved: ResolvedVersion) -> None:
    tag = config.github_release.tag_format.format(versionName=resolved.next.version_name)
    result = run_command(["gh", "release", "view", tag], repo_root, check=False)
    if result.returncode == 0:
        raise PublishError(f"GitHub release already exists: {tag}")
