import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synclab_release.errors import PreflightError, SignError
from synclab_release.staged_pipeline import (
    build_stage,
    prepare_stage,
    release_plan_requires_bundletool,
    sign_stage,
    validate_signing_mode_for_plan,
    verify_publish_stage,
)


FP = "A1" * 32


def _config() -> dict:
    base_signing = {
        "enabled": True,
        "profile": "test",
        "expectedSignerDn": "CN=Synclab CI",
        "expectedSignerSha256": FP,
    }
    return {
        "schemaVersion": 1,
        "project": {"name": "ci-fixture"},
        "version": {
            "source": "gradle",
            "file": "version.gradle",
            "versionNameScheme": "quad",
            "versionCodeFormula": "a*100000000+b*1000000+c*10000+d",
        },
        "bundle": {"name": "android", "targets": ["release", "play"]},
        "targets": {
            "release": {
                "artifactType": "apk",
                "buildCommand": ["echo", "build-apk"],
                "artifactPattern": "fixture-build/release.apk",
                "assetName": "ci-fixture-{versionName}.apk",
                "signing": dict(base_signing),
            },
            "play": {
                "artifactType": "aab",
                "buildCommand": ["echo", "build-aab"],
                "artifactPattern": "fixture-build/play.aab",
                "assetName": "ci-fixture-{versionName}.aab",
                "signing": dict(base_signing),
            },
        },
        "githubRelease": {
            "tagFormat": "v{versionName}",
            "nameFormat": "{project} {versionName}",
            "prerelease": False,
        },
        "signingService": {
            "urlEnv": "SYNCLAB_SIGNING_URL",
            "requiresTailscale": False,
            "tlsVerify": False,
        },
    }


class StagedMixedPipelineTest(unittest.TestCase):
    def _repo(self, temp: str) -> Path:
        root = Path(temp)
        (root / "version.gradle").write_text(
            'versionName "1.0.0.0"\nversionCode 100000000\n',
            encoding="utf-8",
        )
        (root / "synclab-release.json").write_text(json.dumps(_config()), encoding="utf-8")
        build = root / "fixture-build"
        build.mkdir()
        (build / "release.apk").write_bytes(b"unsigned-apk")
        (build / "play.aab").write_bytes(b"unsigned-aab")
        return root

    def test_mixed_staged_pipeline_carries_type_metadata_and_final_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._repo(temp)
            plan_dir = root / "plan"
            unsigned = root / "unsigned"
            signed = root / "signed"
            final = root / "final"

            prepare_stage(
                repo_root=root,
                config_file="synclab-release.json",
                bump="d",
                version_name=None,
                output_dir=plan_dir,
                dry_run=True,
            )
            plan_file = plan_dir / "release-plan.json"
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            self.assertEqual(
                [(item["name"], item["artifactType"]) for item in plan["targets"]],
                [("release", "apk"), ("play", "aab")],
            )
            self.assertTrue(release_plan_requires_bundletool(plan_file))

            built = {
                "release": root / "fixture-build" / "release.apk",
                "play": root / "fixture-build" / "play.aab",
            }
            with patch("synclab_release.staged_pipeline.build_all", return_value=built):
                build_stage(repo_root=root, plan_file=plan_file, output_dir=unsigned)

            unsigned_manifest = json.loads((unsigned / "unsigned-manifest.json").read_text())
            self.assertEqual(
                {(x["target"], x["artifactType"], x["path"]) for x in unsigned_manifest["artifacts"]},
                {("release", "apk", "release.apk"), ("play", "aab", "play.aab")},
            )

            captured = []

            def fake_sign(**kwargs):
                captured.append(kwargs)
                shutil.copy2(kwargs["artifact_path"], kwargs["output_path"])
                return kwargs["output_path"]

            env = {
                "SYNCLAB_SIGNING_URL": "https://sign.test",
                "SYNCLAB_SIGNING_API_KEY_TEST": "ci-secret",
                "GITHUB_REPOSITORY": "Synclab-VN-dev/ci-fixture",
                "GITHUB_SHA": "abc123",
                "GITHUB_RUN_ID": "456789",
            }
            with patch.dict("os.environ", env, clear=False), patch(
                "synclab_release.staged_pipeline.assert_unsigned_artifact"
            ), patch(
                "synclab_release.staged_pipeline._http_get_json_or_text",
                return_value='{"profiles":["test"]}',
            ), patch(
                "synclab_release.staged_pipeline.sign_android_artifact",
                side_effect=fake_sign,
            ):
                sign_stage(
                    repo_root=root,
                    plan_file=plan_file,
                    unsigned_dir=unsigned,
                    output_dir=signed,
                    require_unsigned_check=True,
                    targets=None,
                )

            self.assertEqual([x["artifact_type"] for x in captured], ["apk", "aab"])
            for request in captured:
                metadata = request["metadata"]
                self.assertEqual(
                    set(["repo", "target", "artifactType", "version", "versionCode", "sha", "run_id"]).difference(metadata),
                    set(),
                )
                self.assertEqual(metadata["repo"], "Synclab-VN-dev/ci-fixture")
                self.assertEqual(metadata["sha"], "abc123")
                self.assertEqual(metadata["run_id"], "456789")

            signed_manifest = json.loads((signed / "signed-manifest.json").read_text())
            self.assertEqual(
                {(x["target"], x["artifactType"], x["path"]) for x in signed_manifest["artifacts"]},
                {("release", "apk", "release-signed.apk"), ("play", "aab", "play-signed.aab")},
            )

            with patch("synclab_release.staged_pipeline.verify_artifact_version") as version_verify, patch(
                "synclab_release.staged_pipeline.verify_artifact_signer"
            ) as signer_verify, patch("synclab_release.staged_pipeline.publish_release") as publish:
                verify_publish_stage(
                    repo_root=root,
                    plan_file=plan_file,
                    signed_dir=signed,
                    output_dir=final,
                    dry_run=True,
                )

            self.assertEqual(version_verify.call_count, 2)
            self.assertEqual(signer_verify.call_count, 2)
            publish.assert_not_called()

            metadata = json.loads((final / "metadata.json").read_text())
            artifacts = {x["artifactType"]: x for x in metadata["artifacts"]}
            self.assertEqual(set(artifacts), {"apk", "aab"})
            self.assertTrue((final / artifacts["apk"]["assetName"]).is_file())
            self.assertTrue((final / artifacts["aab"]["assetName"]).is_file())

            checksum_lines = (final / "checksum.sha256").read_text().strip().splitlines()
            self.assertEqual(len(checksum_lines), 2)
            self.assertTrue(any(line.endswith(artifacts["apk"]["assetName"]) for line in checksum_lines))
            self.assertTrue(any(line.endswith(artifacts["aab"]["assetName"]) for line in checksum_lines))

    def test_sign_stage_propagates_sign_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._repo(temp)
            plan_dir = root / "plan"
            unsigned = root / "unsigned"
            signed = root / "signed"
            prepare_stage(
                repo_root=root,
                config_file="synclab-release.json",
                bump="d",
                version_name=None,
                output_dir=plan_dir,
                dry_run=True,
            )
            plan_file = plan_dir / "release-plan.json"
            unsigned.mkdir()
            (unsigned / "release.apk").write_bytes(b"apk")
            (unsigned / "play.aab").write_bytes(b"aab")
            with patch.dict(
                "os.environ",
                {
                    "SYNCLAB_SIGNING_URL": "https://sign.test",
                    "SYNCLAB_SIGNING_API_KEY_TEST": "ci-secret",
                },
                clear=False,
            ), patch(
                "synclab_release.staged_pipeline._http_get_json_or_text",
                return_value='{"profiles":["test"]}',
            ), patch(
                "synclab_release.staged_pipeline.sign_android_artifact",
                side_effect=SignError("HTTP failure"),
            ):
                with self.assertRaises(SignError):
                    sign_stage(
                        repo_root=root,
                        plan_file=plan_file,
                        unsigned_dir=unsigned,
                        output_dir=signed,
                        require_unsigned_check=False,
                        targets=None,
                    )

    def test_bundletool_gate_and_signing_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk_plan = root / "apk.json"
            apk_plan.write_text(
                json.dumps({"targets": [{"name": "release", "artifactType": "apk", "signingEnabled": True}]}),
                encoding="utf-8",
            )
            mixed_plan = root / "mixed.json"
            mixed_plan.write_text(
                json.dumps(
                    {
                        "targets": [
                            {"name": "release", "artifactType": "apk", "signingEnabled": True},
                            {"name": "play", "artifactType": "aab", "signingEnabled": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertFalse(release_plan_requires_bundletool(apk_plan))
            self.assertTrue(release_plan_requires_bundletool(mixed_plan))
            with self.assertRaises(PreflightError):
                validate_signing_mode_for_plan(apk_plan, "self-hosted")
            validate_signing_mode_for_plan(apk_plan, "public-api")
            validate_signing_mode_for_plan(mixed_plan, "public-api")


if __name__ == "__main__":
    unittest.main()
