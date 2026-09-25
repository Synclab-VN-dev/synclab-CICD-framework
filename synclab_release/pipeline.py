from __future__ import annotations

import os
from pathlib import Path

from .apk_verifier import assert_unsigned_artifact, verify_artifact_signer, verify_artifact_version
from .artifact_manager import copy_final_artifact, write_release_files
from .builder import build_all, clean_artifacts
from .config_loader import load_config
from .gradle_version import read_gradle_version, write_gradle_version
from .github_release import publish_release
from .models import Artifact
from .preflight import run_preflight
from .signing_client import api_key_for_profile, sign_android_artifact
from .version_resolver import resolve_version


def run_release(
    *,
    repo_root: Path,
    config_file: str,
    bump: str,
    version_name: str | None,
    dry_run: bool,
    preflight_only: bool = False,
) -> None:
    config = load_config(repo_root / config_file)
    current = read_gradle_version(repo_root / config.version.file)
    resolved = resolve_version(current, bump, version_name)

    run_preflight(repo_root, config, resolved, dry_run)
    if preflight_only:
        print(f"Preflight OK: {resolved.current.version_name} -> {resolved.next.version_name}")
        return

    write_gradle_version(repo_root / config.version.file, resolved.next)
    output_dir = clean_artifacts(repo_root)
    built_artifacts = build_all(repo_root, config)

    final_artifacts: list[Artifact] = []
    signing_url = os.getenv(config.signing_service.url_env, "")
    for target_name in config.bundle_targets:
        target = config.targets[target_name]
        source = built_artifacts[target_name]
        if target.signing.enabled:
            assert_unsigned_artifact(repo_root, source, target.artifact_type)
            signed_path = output_dir / f"{target.name}-signed.{target.artifact_type}"
            metadata = {
                "project": config.project_name,
                "target": target.name,
                "artifactType": target.artifact_type,
                "version": resolved.next.version_name,
                "versionCode": str(resolved.next.version_code),
                "sha": os.getenv("GITHUB_SHA", "local"),
            }
            source = sign_android_artifact(
                signing_url=signing_url,
                api_key=api_key_for_profile(target.signing.profile or ""),
                profile=target.signing.profile or "",
                metadata=metadata,
                artifact_type=target.artifact_type,
                artifact_path=source,
                output_path=signed_path,
                tls_verify=config.signing_service.tls_verify,
            )
        verify_artifact_version(repo_root, source, target.artifact_type, resolved.next)
        verify_artifact_signer(repo_root, source, target.artifact_type, target.signing.expected_signer_dn)
        final_artifacts.append(copy_final_artifact(output_dir, config, target, source, resolved.next))

    release_files = [artifact.output_path for artifact in final_artifacts]
    release_files.extend(write_release_files(output_dir, config, resolved, final_artifacts))
    if dry_run:
        print(f"Dry-run OK. Artifacts written to {output_dir}")
        return
    publish_release(repo_root, config, resolved, release_files)
