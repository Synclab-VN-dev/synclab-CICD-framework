import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synclab_release.builder import build_all, resolve_build_command
from synclab_release.errors import BuildError
from synclab_release.models import (
    GitHubReleaseConfig,
    ReleaseConfig,
    SigningConfig,
    SigningServiceConfig,
    TargetConfig,
    VersionConfig,
)


def _target(name: str, command: list[str]) -> TargetConfig:
    return TargetConfig(
        name=name,
        build_command=command,
        artifact_pattern=f"outputs/{name}.apk",
        asset_name=f"{name}.apk",
        signing=SigningConfig(enabled=False),
    )


class BuilderTest(unittest.TestCase):
    def test_resolves_secret_placeholder_in_build_command(self):
        target = _target("debug", ["./gradlew", "assembleDebug", "-Ptoken={{secret.TEST_SECRET}}"])

        with patch.dict(os.environ, {"TEST_SECRET": "secret-value"}, clear=True):
            self.assertEqual(
                resolve_build_command(target),
                ["./gradlew", "assembleDebug", "-Ptoken=secret-value"],
            )

    def test_rejects_missing_secret_placeholder(self):
        target = _target("prerelease", ["./gradlew", "assemblePrerelease", "-Ptoken={{secret.TEST_SECRET}}"])

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(BuildError) as raised:
                resolve_build_command(target)

        self.assertIn("Missing build secret for target prerelease: TEST_SECRET", raised.exception.message)

    def test_build_all_strips_managed_secret_env_from_child_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "gradlew"
            script.write_text(
                """#!/usr/bin/env bash
set -eu
mkdir -p outputs
target="$1"
shift
if [ "$target" = "assembleDebug" ]; then
  printf '%s\n' "$*" > outputs/debug.args
  [ "${TEST_SECRET:-}" = "" ] || exit 11
  touch outputs/debug.apk
elif [ "$target" = "assembleRelease" ]; then
  printf '%s\n' "$*" > outputs/release.args
  [ "${TEST_SECRET:-}" = "" ] || exit 12
  touch outputs/release.apk
else
  exit 13
fi
""",
                encoding="utf-8",
            )
            script.chmod(0o755)
            debug = _target("debug", ["./gradlew", "assembleDebug", "-Ptoken={{secret.TEST_SECRET}}"])
            release = _target("release", ["./gradlew", "assembleRelease"])
            config = ReleaseConfig(
                project_name="test",
                version=VersionConfig("gradle", Path("build.gradle"), "quad", "a*100000000+b*1000000+c*10000+d"),
                bundle_targets=["debug", "release"],
                targets={"debug": debug, "release": release},
                github_release=GitHubReleaseConfig("v{versionName}", "{project} {versionName}", True),
                signing_service=SigningServiceConfig("SYNCLAB_SIGNING_URL", False, False),
            )

            with patch.dict(os.environ, {"TEST_SECRET": "secret-value"}, clear=True):
                artifacts = build_all(root, config)

            self.assertEqual(artifacts["debug"], root / "outputs/debug.apk")
            self.assertEqual(artifacts["release"], root / "outputs/release.apk")
            self.assertEqual((root / "outputs/debug.args").read_text(encoding="utf-8").strip(), "-Ptoken=secret-value")
            self.assertEqual((root / "outputs/release.args").read_text(encoding="utf-8").strip(), "")


if __name__ == "__main__":
    unittest.main()
