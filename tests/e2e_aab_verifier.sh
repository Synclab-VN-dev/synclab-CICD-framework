#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DN="CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN"

mkdir -p "$TMP/payload/base/manifest"
printf 'bundle-config\n' > "$TMP/payload/BundleConfig.pb"
printf 'manifest\n' > "$TMP/payload/base/manifest/AndroidManifest.xml"
(cd "$TMP/payload" && zip -qr "$TMP/unsigned.aab" .)

PYTHONPATH="$ROOT" python - "$TMP/unsigned.aab" <<'PY'
import sys
from pathlib import Path
from synclab_release.apk_verifier import verify_aab_signer
from synclab_release.errors import VerifyError
try:
    verify_aab_signer(Path("."), Path(sys.argv[1]), "CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN", "A1" * 32)
except VerifyError:
    print("PASS: unsigned AAB rejected by signer verification")
else:
    raise SystemExit("FAIL: unsigned AAB was accepted")
PY

cp "$TMP/unsigned.aab" "$TMP/test.aab"
keytool -genkeypair -alias synclab-test -keyalg RSA -keysize 2048 -validity 3650   -dname "$DN" -keystore "$TMP/test.p12" -storetype PKCS12 -storepass changeit -keypass changeit >/dev/null 2>&1
jarsigner -keystore "$TMP/test.p12" -storetype PKCS12 -storepass changeit -keypass changeit   "$TMP/test.aab" synclab-test >/dev/null
FP="$(keytool -list -v -keystore "$TMP/test.p12" -storetype PKCS12 -storepass changeit -alias synclab-test |
  sed -n 's/.*SHA256: //p' | head -1 | tr -d ':[:space:]')"

PYTHONPATH="$ROOT" python - "$TMP/test.aab" "$FP" <<'PY'
import sys
from pathlib import Path
from synclab_release.apk_verifier import verify_aab_signer
verify_aab_signer(Path("."), Path(sys.argv[1]), "CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN", sys.argv[2])
print("PASS: real jarsigner/keytool verification")
PY

cp "$TMP/unsigned.aab" "$TMP/same-dn.aab"
keytool -genkeypair -alias same-dn -keyalg RSA -keysize 2048 -validity 3650   -dname "$DN" -keystore "$TMP/same-dn.p12" -storetype PKCS12 -storepass changeit -keypass changeit >/dev/null 2>&1
jarsigner -keystore "$TMP/same-dn.p12" -storetype PKCS12 -storepass changeit -keypass changeit   "$TMP/same-dn.aab" same-dn >/dev/null
PYTHONPATH="$ROOT" python - "$TMP/same-dn.aab" "$FP" <<'PY'
import sys
from pathlib import Path
from synclab_release.apk_verifier import verify_aab_signer
from synclab_release.errors import VerifyError
try:
    verify_aab_signer(Path("."), Path(sys.argv[1]), "CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN", sys.argv[2])
except VerifyError as exc:
    if "fingerprint mismatch" not in exc.message:
        raise
    print("PASS: different certificate with same Subject DN rejected")
else:
    raise SystemExit("FAIL: same-DN different certificate was accepted")
PY

cp "$TMP/test.aab" "$TMP/corrupted.aab"
mkdir -p "$TMP/corrupt"
printf 'changed-after-sign\n' > "$TMP/corrupt/BundleConfig.pb"
(cd "$TMP/corrupt" && zip -q "$TMP/corrupted.aab" BundleConfig.pb)
PYTHONPATH="$ROOT" python - "$TMP/corrupted.aab" "$FP" <<'PY'
import sys
from pathlib import Path
from synclab_release.apk_verifier import verify_aab_signer
from synclab_release.errors import VerifyError
try:
    verify_aab_signer(Path("."), Path(sys.argv[1]), "CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN", sys.argv[2])
except VerifyError:
    print("PASS: corrupted signed entry rejected")
else:
    raise SystemExit("FAIL: corrupted signed entry was accepted")
PY

printf 'tampered\n' > "$TMP/tampered.txt"
(cd "$TMP" && zip -q test.aab tampered.txt)
PYTHONPATH="$ROOT" python - "$TMP/test.aab" "$FP" <<'PY'
import sys
from pathlib import Path
from synclab_release.apk_verifier import verify_aab_signer
from synclab_release.errors import VerifyError
try:
    verify_aab_signer(Path("."), Path(sys.argv[1]), "CN=Synclab AAB E2E, OU=CI, O=Synclab, C=VN", sys.argv[2])
except VerifyError as exc:
    if "unsigned entries" not in exc.message:
        raise
    print("PASS: post-sign unsigned ZIP entry rejected")
else:
    raise SystemExit("FAIL: tampered AAB with unsigned entry was accepted")
PY
