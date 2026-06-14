from __future__ import annotations

import glob
import shutil
from pathlib import Path

from .command import run_command
from .errors import BuildError
from .models import ReleaseConfig, TargetConfig


def build_target(repo_root: Path, target: TargetConfig) -> Path:
    try:
        result = run_command(target.build_command, repo_root)
    except Exception as exc:
        raise BuildError(f"Target {target.name} build command failed: {exc}") from exc

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
    for name in config.bundle_targets:
        artifacts[name] = build_target(repo_root, config.targets[name])
    return artifacts
