from __future__ import annotations

from .errors import PreflightError
from .models import GradleVersion, ResolvedVersion
from .quad_version import QuadVersion


def resolve_version(current: GradleVersion, bump: str, manual_version_name: str | None) -> ResolvedVersion:
    current_quad = QuadVersion.parse(current.version_name)
    expected_current_code = current_quad.to_version_code()
    if current.version_code != expected_current_code:
        raise PreflightError(
            f"Current versionCode {current.version_code} does not match versionName {current.version_name}; expected {expected_current_code}"
        )

    if manual_version_name:
        next_quad = QuadVersion.parse(manual_version_name)
        mode = "manual"
        bump_level = None
    else:
        next_quad = current_quad.bump(bump)
        mode = "auto"
        bump_level = bump

    if next_quad <= current_quad:
        raise PreflightError(f"Next version {next_quad} must be greater than current {current.version_name}")

    next_version = GradleVersion(version_name=str(next_quad), version_code=next_quad.to_version_code())
    if next_version.version_code <= current.version_code:
        raise PreflightError(
            f"Next versionCode {next_version.version_code} must be greater than current {current.version_code}"
        )

    return ResolvedVersion(current=current, next=next_version, mode=mode, bump=bump_level)
