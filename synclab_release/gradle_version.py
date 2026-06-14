from __future__ import annotations

import re
from pathlib import Path

from .errors import PreflightError
from .models import GradleVersion


VERSION_NAME_RE = re.compile(r"^(?P<indent>\s*)versionName(?:\s+|(?:\s*=\s*))(['\"])(?P<value>[^'\"]+)\2(?P<tail>\s*)$")
VERSION_CODE_RE = re.compile(r"^(?P<indent>\s*)versionCode(?:\s+|(?:\s*=\s*))(?P<value>\d+)(?P<tail>\s*)$")


def read_gradle_version(path: str | Path) -> GradleVersion:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    name_matches = [(index, match) for index, line in enumerate(lines) if (match := VERSION_NAME_RE.match(line))]
    code_matches = [(index, match) for index, line in enumerate(lines) if (match := VERSION_CODE_RE.match(line))]

    if len(name_matches) != 1:
        raise PreflightError(f"Expected exactly one versionName declaration in {path}, found {len(name_matches)}")
    if len(code_matches) != 1:
        raise PreflightError(f"Expected exactly one versionCode declaration in {path}, found {len(code_matches)}")

    return GradleVersion(
        version_name=name_matches[0][1].group("value"),
        version_code=int(code_matches[0][1].group("value")),
    )


def write_gradle_version(path: str | Path, version: GradleVersion) -> None:
    gradle_path = Path(path)
    lines = gradle_path.read_text(encoding="utf-8").splitlines(keepends=True)
    name_indices = []
    code_indices = []
    for index, line in enumerate(lines):
        stripped_newline = line.rstrip("\n")
        if VERSION_NAME_RE.match(stripped_newline):
            name_indices.append(index)
        if VERSION_CODE_RE.match(stripped_newline):
            code_indices.append(index)

    if len(name_indices) != 1:
        raise PreflightError(f"Expected exactly one versionName declaration in {path}, found {len(name_indices)}")
    if len(code_indices) != 1:
        raise PreflightError(f"Expected exactly one versionCode declaration in {path}, found {len(code_indices)}")

    name_index = name_indices[0]
    code_index = code_indices[0]
    name_line = lines[name_index]
    code_line = lines[code_index]
    name_newline = "\n" if name_line.endswith("\n") else ""
    code_newline = "\n" if code_line.endswith("\n") else ""
    name_match = VERSION_NAME_RE.match(name_line.rstrip("\n"))
    code_match = VERSION_CODE_RE.match(code_line.rstrip("\n"))
    assert name_match and code_match

    lines[name_index] = f'{name_match.group("indent")}versionName "{version.version_name}"{name_match.group("tail")}{name_newline}'
    lines[code_index] = f'{code_match.group("indent")}versionCode {version.version_code}{code_match.group("tail")}{code_newline}'
    gradle_path.write_text("".join(lines), encoding="utf-8")
