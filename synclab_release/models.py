from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SigningConfig:
    enabled: bool
    profile: str | None = None
    expected_signer_dn: str | None = None


@dataclass(frozen=True)
class TargetConfig:
    name: str
    build_command: list[str]
    artifact_pattern: str
    asset_name: str
    signing: SigningConfig


@dataclass(frozen=True)
class VersionConfig:
    source: str
    file: Path
    version_name_scheme: str
    version_code_formula: str


@dataclass(frozen=True)
class GitHubReleaseConfig:
    tag_format: str
    name_format: str
    prerelease: bool


@dataclass(frozen=True)
class SigningServiceConfig:
    url_env: str
    requires_tailscale: bool
    tls_verify: bool


@dataclass(frozen=True)
class ReleaseConfig:
    project_name: str
    version: VersionConfig
    bundle_targets: list[str]
    targets: dict[str, TargetConfig]
    github_release: GitHubReleaseConfig
    signing_service: SigningServiceConfig


@dataclass(frozen=True)
class GradleVersion:
    version_name: str
    version_code: int


@dataclass(frozen=True)
class ResolvedVersion:
    current: GradleVersion
    next: GradleVersion
    mode: str
    bump: str | None


@dataclass(frozen=True)
class Artifact:
    target: str
    source_path: Path
    output_path: Path
    asset_name: str
    sha256: str
    signing_profile: str | None
