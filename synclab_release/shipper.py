from __future__ import annotations

from .errors import SynclabReleaseError


def ship_release() -> None:
    raise SynclabReleaseError("ship command is reserved for Phase 2")
