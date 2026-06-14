from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .models import (
    GitHubReleaseConfig,
    ReleaseConfig,
    SigningConfig,
    SigningServiceConfig,
    TargetConfig,
    VersionConfig,
)


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be an object")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{name} must be a non-empty string")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list")
    return value


def load_config(path: str | Path) -> ReleaseConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    root = _require_dict(raw, "config")
    if root.get("schemaVersion") != 1:
        raise ConfigError("schemaVersion must be 1")

    project = _require_dict(root.get("project"), "project")
    version = _require_dict(root.get("version"), "version")
    bundle = _require_dict(root.get("bundle"), "bundle")
    targets_raw = _require_dict(root.get("targets"), "targets")
    release = _require_dict(root.get("githubRelease"), "githubRelease")
    signing_service_raw = _require_dict(
        root.get(
            "signingService",
            {
                "urlEnv": "SYNCLAB_SIGNING_URL",
                "requiresTailscale": False,
                "tlsVerify": False,
            },
        ),
        "signingService",
    )

    project_name = _require_str(project.get("name"), "project.name")
    source = _require_str(version.get("source"), "version.source")
    if source != "gradle":
        raise ConfigError("version.source must be gradle")
    version_file = Path(_require_str(version.get("file"), "version.file"))
    scheme = _require_str(version.get("versionNameScheme"), "version.versionNameScheme")
    if scheme != "quad":
        raise ConfigError("version.versionNameScheme must be quad")

    target_names = [_require_str(item, "bundle.targets[]") for item in _require_list(bundle.get("targets"), "bundle.targets")]
    if not target_names:
        raise ConfigError("bundle.targets must not be empty")

    targets: dict[str, TargetConfig] = {}
    for name, target_raw in targets_raw.items():
        target = _require_dict(target_raw, f"targets.{name}")
        command = [_require_str(item, f"targets.{name}.buildCommand[]") for item in _require_list(target.get("buildCommand"), f"targets.{name}.buildCommand")]
        signing_raw = _require_dict(target.get("signing", {"enabled": False}), f"targets.{name}.signing")
        signing_enabled = _require_bool(signing_raw.get("enabled"), f"targets.{name}.signing.enabled")
        signing = SigningConfig(
            enabled=signing_enabled,
            profile=_require_str(signing_raw.get("profile"), f"targets.{name}.signing.profile") if signing_enabled else None,
            expected_signer_dn=_require_str(signing_raw.get("expectedSignerDn"), f"targets.{name}.signing.expectedSignerDn") if signing_enabled else None,
        )
        targets[name] = TargetConfig(
            name=name,
            build_command=command,
            artifact_pattern=_require_str(target.get("artifactPattern"), f"targets.{name}.artifactPattern"),
            asset_name=_require_str(target.get("assetName"), f"targets.{name}.assetName"),
            signing=signing,
        )

    for name in target_names:
        if name not in targets:
            raise ConfigError(f"bundle target {name} is not declared in targets")

    return ReleaseConfig(
        project_name=project_name,
        version=VersionConfig(
            source=source,
            file=version_file,
            version_name_scheme=scheme,
            version_code_formula=_require_str(version.get("versionCodeFormula"), "version.versionCodeFormula"),
        ),
        bundle_targets=target_names,
        targets=targets,
        github_release=GitHubReleaseConfig(
            tag_format=_require_str(release.get("tagFormat"), "githubRelease.tagFormat"),
            name_format=_require_str(release.get("nameFormat"), "githubRelease.nameFormat"),
            prerelease=bool(release.get("prerelease", False)),
        ),
        signing_service=SigningServiceConfig(
            url_env=_require_str(signing_service_raw.get("urlEnv"), "signingService.urlEnv"),
            requires_tailscale=bool(signing_service_raw.get("requiresTailscale", False)),
            tls_verify=bool(signing_service_raw.get("tlsVerify", False)),
        ),
    )
