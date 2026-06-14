from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import SynclabReleaseError
from .pipeline import run_release
from .shipper import ship_release
from .staged_pipeline import build_stage, prepare_stage, sign_stage, verify_publish_stage


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

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--config-file", default="synclab-release.json")
    prepare.add_argument("--bump", default="d", choices=("a", "b", "c", "d"))
    prepare.add_argument("--version-name")
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--repo-root", default=".")
    prepare.add_argument("--output-dir", default="synclab-release-plan")

    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--plan-file", required=True)
    build.add_argument("--output-dir", default="synclab-unsigned-apks")

    sign = subparsers.add_parser("sign")
    sign.add_argument("--repo-root", default=".")
    sign.add_argument("--plan-file", required=True)
    sign.add_argument("--unsigned-dir", required=True)
    sign.add_argument("--output-dir", default="synclab-signed-apks")
    sign.add_argument("--targets", help="Optional comma-separated target names for sign command.")
    sign.add_argument(
        "--require-unsigned-check",
        action="store_true",
        help="Require apksigner on the current runner to verify APKs are unsigned before signing.",
    )

    verify = subparsers.add_parser("verify-publish")
    verify.add_argument("--repo-root", default=".")
    verify.add_argument("--plan-file", required=True)
    verify.add_argument("--signed-dir", required=True)
    verify.add_argument("--output-dir", default="synclab-final-artifacts")
    verify.add_argument("--dry-run", action="store_true")

    ship = subparsers.add_parser("ship")
    ship.add_argument("--source-tag", required=False)
    ship.add_argument("--target-repo", required=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ship":
            ship_release()
        elif args.command == "prepare":
            prepare_stage(
                repo_root=Path(args.repo_root).resolve(),
                config_file=args.config_file,
                bump=args.bump,
                version_name=args.version_name or None,
                dry_run=args.dry_run,
                output_dir=Path(args.output_dir).resolve(),
            )
        elif args.command == "build":
            build_stage(
                repo_root=Path(args.repo_root).resolve(),
                plan_file=Path(args.plan_file).resolve(),
                output_dir=Path(args.output_dir).resolve(),
            )
        elif args.command == "sign":
            sign_stage(
                repo_root=Path(args.repo_root).resolve(),
                plan_file=Path(args.plan_file).resolve(),
                unsigned_dir=Path(args.unsigned_dir).resolve(),
                output_dir=Path(args.output_dir).resolve(),
                require_unsigned_check=args.require_unsigned_check,
                targets=[item.strip() for item in args.targets.split(",") if item.strip()] if args.targets else None,
            )
        elif args.command == "verify-publish":
            verify_publish_stage(
                repo_root=Path(args.repo_root).resolve(),
                plan_file=Path(args.plan_file).resolve(),
                signed_dir=Path(args.signed_dir).resolve(),
                output_dir=Path(args.output_dir).resolve(),
                dry_run=args.dry_run,
            )
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
