from __future__ import annotations

import json
import shutil
from pathlib import Path

from .apk_verifier import sha256_file
from .models import Artifact, GradleVersion, ReleaseConfig, ResolvedVersion, TargetConfig


def render_name(template: str, project: str, version: GradleVersion, target: str) -> str:
    return template.format(
        project=project,
        versionName=version.version_name,
        versionCode=version.version_code,
        target=target,
    )


def copy_final_artifact(
    output_dir: Path,
    config: ReleaseConfig,
    target: TargetConfig,
    source_path: Path,
    version: GradleVersion,
) -> Artifact:
    asset_name = render_name(target.asset_name, config.project_name, version, target.name)
    output_path = output_dir / asset_name
    shutil.copy2(source_path, output_path)
    return Artifact(
        target=target.name,
        source_path=source_path,
        output_path=output_path,
        asset_name=asset_name,
        sha256=sha256_file(output_path),
        artifact_type=target.artifact_type,
        signing_profile=target.signing.profile if target.signing.enabled else None,
    )


def write_release_files(output_dir: Path, config: ReleaseConfig, resolved: ResolvedVersion, artifacts: list[Artifact]) -> list[Path]:
    metadata = {
        "project": config.project_name,
        "versionName": resolved.next.version_name,
        "versionCode": resolved.next.version_code,
        "mode": resolved.mode,
        "bump": resolved.bump,
        "artifacts": [
            {
                "target": artifact.target,
                "assetName": artifact.asset_name,
                "sha256": artifact.sha256,
                "artifactType": artifact.artifact_type,
                "signingProfile": artifact.signing_profile,
            }
            for artifact in artifacts
        ],
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    checksum_path = output_dir / "checksum.sha256"
    checksum_path.write_text(
        "".join(f"{artifact.sha256}  {artifact.asset_name}\n" for artifact in artifacts),
        encoding="utf-8",
    )
    return [metadata_path, checksum_path]
