from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import PreflightError


VERSION_RE = re.compile(r"^(?P<a>\d+)\.(?P<b>\d+)\.(?P<c>\d+)\.(?P<d>\d+)$")


@dataclass(frozen=True, order=True)
class QuadVersion:
    a: int
    b: int
    c: int
    d: int

    @classmethod
    def parse(cls, value: str) -> "QuadVersion":
        match = VERSION_RE.match(value)
        if not match:
            raise PreflightError(f"Version name must use a.b.c.d format, got {value}")
        version = cls(*(int(match.group(part)) for part in ("a", "b", "c", "d")))
        version.validate_ranges(value)
        return version

    def validate_ranges(self, original: str) -> None:
        if self.a < 0 or not (0 <= self.b <= 99) or not (0 <= self.c <= 99) or not (0 <= self.d <= 9999):
            raise PreflightError(f"Version components out of range for {original}")

    def bump(self, level: str) -> "QuadVersion":
        if level == "d":
            return QuadVersion(self.a, self.b, self.c, self.d + 1)
        if level == "c":
            return QuadVersion(self.a, self.b, self.c + 1, 0)
        if level == "b":
            return QuadVersion(self.a, self.b + 1, 0, 0)
        if level == "a":
            return QuadVersion(self.a + 1, 0, 0, 0)
        raise PreflightError(f"Unsupported bump level: {level}")

    def to_version_code(self) -> int:
        return self.a * 100000000 + self.b * 1000000 + self.c * 10000 + self.d

    def __str__(self) -> str:
        return f"{self.a}.{self.b}.{self.c}.{self.d}"
