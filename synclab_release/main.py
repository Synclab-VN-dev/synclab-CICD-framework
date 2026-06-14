from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import SynclabReleaseError
from .pipeline import run_release
from .shipper import ship_release


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synclab-release")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("preflight", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--config-file", default="synclab-release.json")
        sub.add_argument("--bump", default="d", choices=("a", "b", "c", "d"))
        sub.add_argument("--version-name")
        sub.add_argument("--dry-run", action="store_true")
        sub.add_argument("--repo-root", default=".")

    ship = subparsers.add_parser("ship")
    ship.add_argument("--source-tag", required=False)
    ship.add_argument("--target-repo", required=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ship":
            ship_release()
        else:
            run_release(
                repo_root=Path(args.repo_root).resolve(),
                config_file=args.config_file,
                bump=args.bump,
                version_name=args.version_name or None,
                dry_run=args.dry_run,
                preflight_only=args.command == "preflight",
            )
        return 0
    except SynclabReleaseError as exc:
        print(exc.format(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
