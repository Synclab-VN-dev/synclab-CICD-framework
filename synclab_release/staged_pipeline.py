from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .apk_verifier import assert_unsigned, verify_signer, verify_version
from .artifact_manager import copy_final_artifact, render_name, write_release_files
from .builder import build_all, clean_artifacts
from .config_loader import load_config
from .errors import BuildError, PreflightError, SignError, VerifyError
from .gradle_version import read_gradle_version, write_gradle_version
from .github_release import publish_release
from .models import Artifact, GradleVersion, ReleaseConfig, ResolvedVersion
from .preflight import _http_get_json_or_text
from .signing_client import api_key_for_profile, sign_apk
from .version_resolver import resolve_version


LOCAL_SIGNING_URL = "https://127.0.0.1:8443"


def _plan_path(output_dir: Path) -> Path:
    return output_dir / "release-plan.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolved_from_plan(plan: dict[str, Any]) -> ResolvedVersion:
    return ResolvedVersion(
        current=GradleVersion(plan["currentVersionName"], int(plan["currentVersionCode"])),
        next=GradleVersion(plan["versionName"], int(plan["versionCode"])),
        mode=plan["mode"],
        bump=plan.get("bump"),
    )


def _tag_for(config: ReleaseConfig, version_name: str) -> str:
    return config.github_release.tag_format.format(versionName=version_name)


def _signing_url(config: ReleaseConfig) -> str:
    return os.getenv(config.signing_service.url_env) or LOCAL_SIGNING_URL


def _debug_tree(path: Path, output: Path) -> None:
    lines = []
    if path.exists():
        for item in sorted(path.rglob("*")):
            rel = item.relative_to(path)
            suffix = f" ({item.stat().st_size} bytes)" if item.is_file() else "/"
            lines.append(f"{rel}{suffix}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_stage(
    *,
    repo_root: Path,
    config_file: str,
    bump: str,
    version_name: str | None,
    output_dir: Path,
    dry_run: bool,
) -> None:
    config = load_config(repo_root / config_file)
    current = read_gradle_version(repo_root / config.version.file)
    resolved = resolve_version(current, bump, version_name)
    tag = _tag_for(config, resolved.next.version_name)

    if not dry_run:
        import subprocess

        remote_tag = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", tag],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if remote_tag.returncode == 0 and remote_tag.stdout.strip():
            raise PreflightError(f"Remote Git tag already exists: {tag}")

    plan_targets = []
    for name in config.bundle_targets:
        target = config.targets[name]
        plan_targets.append(
            {
                "name": name,
                "assetName": render_name(target.asset_name, config.project_name, resolved.next, name),
                "signingEnabled": target.signing.enabled,
                "profile": target.signing.profile,
                "expectedSignerDn": target.signing.expected_signer_dn,
            }
        )

    _write_json(
        _plan_path(output_dir),
        {
            "project": config.project_name,
            "configFile": config_file,
            "currentVersionName": resolved.current.version_name,
            "currentVersionCode": resolved.current.version_code,
            "versionName": resolved.next.version_name,
            "versionCode": resolved.next.version_code,
            "mode": resolved.mode,
            "bump": resolved.bump,
            "tag": tag,
            "dryRun": dry_run,
            "targets": plan_targets,
        },
    )
    print(f"[POC] Prepared {resolved.current.version_name}/{resolved.current.version_code} -> {resolved.next.version_name}/{resolved.next.version_code}")
    print(f"[POC] Tag: {tag}")


def build_stage(*, repo_root: Path, plan_file: Path, output_dir: Path) -> None:
    plan = _read_json(plan_file)
    config = load_config(repo_root / plan["configFile"])
    resolved = _resolved_from_plan(plan)
    write_gradle_version(repo_root / config.version.file, resolved.next)

    built_dir = clean_artifacts(repo_root)
    built = build_all(repo_root, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"versionName": resolved.next.version_name, "versionCode": resolved.next.version_code, "artifacts": []}
    for name, source in built.items():
        destination = output_dir / f"{name}.apk"
        shutil.copy2(source, destination)
        manifest["artifacts"].append({"target": name, "path": destination.name, "source": str(source)})
    _write_json(output_dir / "unsigned-manifest.json", manifest)
    shutil.copy2(plan_file, output_dir / "release-plan.json")
    _debug_tree(output_dir, output_dir / "unsigned-tree.txt")
    _debug_tree(built_dir, output_dir / "build-artifacts-tree.txt")
    print(f"[POC] Built unsigned artifacts in {output_dir}")


def sign_stage(*, repo_root: Path, plan_file: Path, unsigned_dir: Path, output_dir: Path) -> None:
    plan = _read_json(plan_file)
    config = load_config(repo_root / plan["configFile"])
    resolved = _resolved_from_plan(plan)
    signing_url = _signing_url(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    health = _http_get_json_or_text(f"{signing_url.rstrip('/')}/health", tls_verify=config.signing_service.tls_verify)
    (output_dir / "signing-health.json").write_text(health + "\n", encoding="utf-8")

    manifest = {"versionName": resolved.next.version_name, "versionCode": resolved.next.version_code, "artifacts": []}
    for name in config.bundle_targets:
        target = config.targets[name]
        source = unsigned_dir / f"{name}.apk"
        if not source.exists():
            raise SignError(f"Unsigned artifact missing for target {name}: {source}")
        if target.signing.enabled:
            assert_unsigned(repo_root, source)
            api_key = api_key_for_profile(target.signing.profile or "")
            profiles_body = _http_get_json_or_text(
                f"{signing_url.rstrip('/')}/v1/profiles",
                headers={"X-Synclab-Api-Key": api_key},
                tls_verify=config.signing_service.tls_verify,
            )
            (output_dir / f"{name}-profiles.json").write_text(profiles_body + "\n", encoding="utf-8")
            signed_path = output_dir / f"{name}-signed.apk"
            final_path = sign_apk(
                signing_url=signing_url,
                api_key=api_key,
                profile=target.signing.profile or "",
                metadata={
                    "repo": os.getenv("GITHUB_REPOSITORY", config.project_name),
                    "target": name,
                    "version": resolved.next.version_name,
                    "versionCode": str(resolved.next.version_code),
                    "sha": os.getenv("GITHUB_SHA", "local"),
                    "run_id": os.getenv("GITHUB_RUN_ID", "local"),
                    "poc": "selfhost-signing",
                },
                apk_path=source,
                output_path=signed_path,
                tls_verify=config.signing_service.tls_verify,
            )
        else:
            final_path = output_dir / f"{name}.apk"
            shutil.copy2(source, final_path)
        manifest["artifacts"].append({"target": name, "path": final_path.name, "signed": target.signing.enabled})

    shutil.copy2(plan_file, output_dir / "release-plan.json")
    _write_json(output_dir / "signed-manifest.json", manifest)
    _debug_tree(output_dir, output_dir / "signed-tree.txt")
    print(f"[POC] Signed artifacts in {output_dir}")


def verify_publish_stage(
    *,
    repo_root: Path,
    plan_file: Path,
    signed_dir: Path,
    output_dir: Path,
    dry_run: bool,
) -> None:
    plan = _read_json(plan_file)
    config = load_config(repo_root / plan["configFile"])
    resolved = _resolved_from_plan(plan)
    write_gradle_version(repo_root / config.version.file, resolved.next)

    output_dir.mkdir(parents=True, exist_ok=True)
    final_artifacts: list[Artifact] = []
    for name in config.bundle_targets:
        target = config.targets[name]
        candidate = signed_dir / (f"{name}-signed.apk" if target.signing.enabled else f"{name}.apk")
        if not candidate.exists():
            raise VerifyError(f"Signed artifact missing for target {name}: {candidate}")
        verify_version(repo_root, candidate, resolved.next)
        verify_signer(repo_root, candidate, target.signing.expected_signer_dn)
        final_artifacts.append(copy_final_artifact(output_dir, config, target, candidate, resolved.next))

    release_files = [artifact.output_path for artifact in final_artifacts]
    release_files.extend(write_release_files(output_dir, config, resolved, final_artifacts))
    shutil.copy2(plan_file, output_dir / "release-plan.json")
    _debug_tree(output_dir, output_dir / "final-tree.txt")
    print(f"[POC] Verified final artifacts in {output_dir}")
    if dry_run:
        print("[POC] Dry-run enabled; skipping publish")
        return
    publish_release(repo_root, config, resolved, release_files)
