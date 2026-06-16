from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

from .command import run_command
from .errors import BuildError
from .models import ReleaseConfig, TargetConfig


BUILD_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(secret|env)\.([A-Z0-9_]+)\s*\}\}")


def collect_build_secret_env_names(targets: list[TargetConfig]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        for arg in target.build_command:
            names.update(match.group(2) for match in BUILD_PLACEHOLDER_PATTERN.finditer(arg) if match.group(1) == "secret")
    return names


def resolve_build_command(target: TargetConfig) -> list[str]:
    def replace(match: re.Match[str]) -> str:
        source = match.group(1)
        name = match.group(2)
        value = os.environ.get(name)
        if value is None or value == "":
            raise BuildError(f"Missing build {source} for target {target.name}: {name}")
        return value

    return [BUILD_PLACEHOLDER_PATTERN.sub(replace, arg) for arg in target.build_command]


def _build_child_env(managed_env_names: set[str]) -> dict[str, str]:
    child_env = os.environ.copy()
    for name in managed_env_names:
        child_env.pop(name, None)
    return child_env


def build_target(repo_root: Path, target: TargetConfig, managed_env_names: set[str] | None = None) -> Path:
    command = resolve_build_command(target)
    child_env = _build_child_env(managed_env_names or collect_build_secret_env_names([target]))
    try:
        result = run_command(command, repo_root, env=child_env)
    except BuildError:
        raise
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            (repo_root / "synclab-release-artifacts").mkdir(exist_ok=True)
            (repo_root / "synclab-release-artifacts" / f"{target.name}-build.log").write_text(exc.stdout, encoding="utf-8")
        raise BuildError(f"Target {target.name} build command failed with exit code {exc.returncode}") from exc
    except Exception as exc:
        raise BuildError(f"Target {target.name} build command failed") from exc

    matches = [Path(path) for path in glob.glob(str(repo_root / target.artifact_pattern))]
    if len(matches) != 1:
        raise BuildError(f"Target {target.name} artifact pattern matched {len(matches)} files")
    if result.stdout:
        (repo_root / "synclab-release-artifacts").mkdir(exist_ok=True)
        (repo_root / "synclab-release-artifacts" / f"{target.name}-build.log").write_text(result.stdout, encoding="utf-8")
    return matches[0]


def clean_artifacts(repo_root: Path) -> Path:
    output_dir = repo_root / "synclab-release-artifacts"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    return output_dir


def build_all(repo_root: Path, config: ReleaseConfig) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    managed_env_names = collect_build_secret_env_names([config.targets[name] for name in config.bundle_targets])
    for name in config.bundle_targets:
        artifacts[name] = build_target(repo_root, config.targets[name], managed_env_names)
    return artifacts
