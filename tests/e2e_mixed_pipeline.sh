#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
APP="$TMP/android-app"
PLAN="$TMP/plan"
UNSIGNED="$TMP/unsigned"
SIGNED="$TMP/signed"
FINAL="$TMP/final"
RECORDS="$TMP/signing-records.jsonl"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

if [[ -z "${BUNDLETOOL_JAR:-}" || ! -f "$BUNDLETOOL_JAR" ]]; then
  echo "BUNDLETOOL_JAR must point to the pinned bundletool jar" >&2
  exit 1
fi

cp -R "$ROOT/tests/fixtures/android-mixed" "$APP"

keytool -genkeypair -alias synclab-ci -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=Synclab CI, OU=CI, O=Synclab, C=VN" -keystore "$TMP/ci.p12" -storetype PKCS12 -storepass changeit -keypass changeit >/dev/null 2>&1
FP="$(keytool -list -v -keystore "$TMP/ci.p12" -storetype PKCS12 -storepass changeit -alias synclab-ci | sed -n 's/.*SHA256: //p' | head -1 | tr -d ':[:space:]')"

python - "$APP/synclab-release.json" "$FP" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(path.read_text().replace("__CI_FINGERPRINT__", sys.argv[2]), encoding="utf-8")
PY

PORT="$(python - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

python "$ROOT/tests/isolated_signing_server.py" --port "$PORT" --keystore "$TMP/ci.p12" --alias synclab-ci --password changeit --records "$RECORDS" >"$TMP/signing-server.log" 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 50); do
  if curl -fsS -H "X-Synclab-Api-Key: ci-secret" "http://127.0.0.1:$PORT/v1/profiles" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl -fsS -H "X-Synclab-Api-Key: ci-secret" "http://127.0.0.1:$PORT/v1/profiles" >/dev/null

export SYNCLAB_SIGNING_URL="http://127.0.0.1:$PORT"
export SYNCLAB_SIGNING_API_KEY_TEST="ci-secret"
export GITHUB_REPOSITORY="Synclab-VN-dev/ci-fixture"
export GITHUB_SHA="ci-head-sha"
export GITHUB_RUN_ID="9001"
export PYTHONPATH="$ROOT"

python -m synclab_release.main prepare --repo-root "$APP" --config-file synclab-release.json --bump d --dry-run --output-dir "$PLAN"

python - "$PLAN/release-plan.json" <<'PY'
import json
import sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
assert plan["versionName"] == "1.0.0.1"
assert plan["versionCode"] == 100000001
assert [(x["name"], x["artifactType"]) for x in plan["targets"]] == [("release", "apk"), ("play", "aab")]
print("PASS: prepare produced mixed APK/AAB release plan")
PY

if ! python -m synclab_release.main build --repo-root "$APP" --plan-file "$PLAN/release-plan.json" --output-dir "$UNSIGNED"; then
  echo "=== Gradle fixture build logs ===" >&2
  find "$APP/synclab-release-artifacts" -maxdepth 1 -type f -name '*-build.log' -print -exec cat {} \; >&2 || true
  echo "=== End Gradle fixture build logs ===" >&2
  exit 1
fi

test -s "$UNSIGNED/release.apk"
test -s "$UNSIGNED/play.aab"
if apksigner verify "$UNSIGNED/release.apk" >/dev/null 2>&1; then
  echo "FAIL: fixture APK unexpectedly signed" >&2
  exit 1
fi
if ! jarsigner -verify -verbose -certs "$UNSIGNED/play.aab" 2>&1 | grep -qi "jar is unsigned"; then
  echo "FAIL: fixture AAB is not detected as unsigned" >&2
  exit 1
fi
echo "PASS: real Gradle APK/AAB build produced unsigned artifacts"

python -m synclab_release.main sign --repo-root "$APP" --plan-file "$PLAN/release-plan.json" --unsigned-dir "$UNSIGNED" --output-dir "$SIGNED" --require-unsigned-check

test -s "$SIGNED/release-signed.apk"
test -s "$SIGNED/play-signed.aab"

python -m synclab_release.main verify-publish --repo-root "$APP" --plan-file "$PLAN/release-plan.json" --signed-dir "$SIGNED" --output-dir "$FINAL" --dry-run

python - "$RECORDS" "$FINAL" <<'PY'
import json
import sys
from pathlib import Path

records = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
assert {r["artifactType"] for r in records} == {"apk", "aab"}
required = {"repo", "target", "artifactType", "version", "versionCode", "sha", "run_id"}
for record in records:
    assert not (required - set(record["metadata"]))
    assert record["metadata"]["repo"] == "Synclab-VN-dev/ci-fixture"
    assert record["metadata"]["sha"] == "ci-head-sha"
    assert record["metadata"]["run_id"] == "9001"

final = Path(sys.argv[2])
metadata = json.loads((final / "metadata.json").read_text())
artifacts = {x["artifactType"]: x for x in metadata["artifacts"]}
assert set(artifacts) == {"apk", "aab"}
assert (final / artifacts["apk"]["assetName"]).is_file()
assert (final / artifacts["aab"]["assetName"]).is_file()
assert artifacts["apk"]["assetName"].endswith(".apk")
assert artifacts["aab"]["assetName"].endswith(".aab")
assert (final / "checksum.sha256").is_file()
print("PASS: HTTP signing contract, final extensions, metadata and mixed artifacts verified")
PY

(cd "$FINAL" && sha256sum -c checksum.sha256)
echo "PASS: final checksum.sha256 verified"

cp "$APP/synclab-release.json" "$TMP/config-good.json"
python - "$APP/synclab-release.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text())
data["targets"]["play"]["signing"]["expectedSignerSha256"] = "B2" * 32
path.write_text(json.dumps(data, indent=2) + "\n")
PY
if python -m synclab_release.main verify-publish --repo-root "$APP" --plan-file "$PLAN/release-plan.json" --signed-dir "$SIGNED" --output-dir "$TMP/final-wrong-fp" --dry-run; then
  echo "FAIL: signer fingerprint mismatch was accepted" >&2
  exit 1
fi
cp "$TMP/config-good.json" "$APP/synclab-release.json"
echo "PASS: full verify-publish rejects signer fingerprint mismatch"

cp "$SIGNED/play-signed.aab" "$TMP/play-good.aab"
printf 'post-sign tamper\n' > "$TMP/tampered-after-sign.txt"
(cd "$TMP" && zip -q "$SIGNED/play-signed.aab" tampered-after-sign.txt)
if python -m synclab_release.main verify-publish --repo-root "$APP" --plan-file "$PLAN/release-plan.json" --signed-dir "$SIGNED" --output-dir "$TMP/final-tampered" --dry-run; then
  echo "FAIL: post-sign unsigned AAB entry was accepted" >&2
  exit 1
fi
cp "$TMP/play-good.aab" "$SIGNED/play-signed.aab"
echo "PASS: full verify-publish rejects post-sign unsigned AAB entry"

echo "=== MIXED PIPELINE E2E RESULT: PASS ==="
