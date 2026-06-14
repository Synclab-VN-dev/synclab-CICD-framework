# Synclab Android Release Process

Tai lieu nay mo ta cach cac Android client repo cua Synclab goi `synclab-CICD-framework` de build, ky APK bang NAS signing appliance, verify va publish GitHub Release.

## 1. Kien truc release

Client repo, vi du `batmon`, khong copy release logic vao repo rieng. Client repo chi khai bao workflow goi reusable workflow cua framework:

```yaml
jobs:
  release:
    permissions:
      contents: write
      actions: read
    uses: Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-release.yml@v1
    with:
      configFile: synclab-release.json
      bump: ${{ inputs.bump }}
      versionName: ${{ inputs.versionName }}
      dryRun: ${{ inputs.dryRun }}
    secrets:
      SYNCLAB_SIGNING_API_KEY_PREVIEW: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PREVIEW }}
      SYNCLAB_SIGNING_API_KEY_PROD: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PROD }}
      RELEASE_GH_TOKEN: ${{ secrets.RELEASE_GH_TOKEN }}
```

Release flow:

```text
prepare -> build -> sign -> verify_publish
```

- `prepare`: chay tren GitHub-hosted runner, doc `synclab-release.json`, doc version hien tai tu Gradle, tinh version moi, sinh `release-plan.json`.
- `build`: chay tren GitHub-hosted runner, update version local theo release plan, build cac APK unsigned, upload artifact `unsigned-apks`.
- `sign`: chay tren NAS self-hosted runner `synclab-signing`, khong checkout source, khong build Android, khong chay Python framework. Job nay chi download unsigned APK va goi local signing service bang shell/curl tai `https://127.0.0.1:8443`.
- `verify_publish`: chay tren GitHub-hosted runner, verify version/signature, tao checksum/metadata, va publish GitHub Release neu `dryRun=false`.

NAS self-hosted runner chi duoc dung cho signing. Khong dua tac vu build, test, publish, Python CLI, hoac Android Gradle build len NAS.

## 2. Workflow inputs va secrets

Reusable workflow:

```text
Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-release.yml@v1
```

Inputs:

| Input | Required | Default | Gia tri hop le | Y nghia |
| --- | --- | --- | --- | --- |
| `configFile` | No | `synclab-release.json` | Path file JSON trong client repo | Release contract file. |
| `bump` | No | `d` | `a`, `b`, `c`, `d` | Auto bump level khi khong truyen `versionName`. |
| `versionName` | No | empty | Format `a.b.c.d` | Manual version override. Neu co gia tri thi framework khong auto bump. |
| `dryRun` | No | `true` | `true`, `false` | `true` thi build/sign/verify nhung khong commit, tag, publish release. |

Secrets can khai bao o tung client repo:

| Secret | Required | Y nghia |
| --- | --- | --- |
| `SYNCLAB_SIGNING_API_KEY_PREVIEW` | Yes | API key duoc phep ky profile `preview`. |
| `SYNCLAB_SIGNING_API_KEY_PROD` | Yes | API key duoc phep ky profile `prod`. |
| `RELEASE_GH_TOKEN` | Optional | Token publish release. Neu khong co, workflow dung `github.token`. |

Runner requirement:

```yaml
runs-on: [self-hosted, linux, x64, synclab-signing]
```

Org runner phai duoc allow cho client repo. Neu job `sign` queued lau, thuong la runner offline, label sai, hoac runner group chua allow repo.

## 3. Version rule

Framework chi support version name dang:

```text
a.b.c.d
```

Range:

- `a >= 0`
- `0 <= b <= 99`
- `0 <= c <= 99`
- `0 <= d <= 9999`

Version code duoc tinh tu version name:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Vi du:

```text
10.3.5.6 -> 1003050006
```

Auto bump:

| `bump` | Ket qua |
| --- | --- |
| `d` | `a.b.c.(d+1)` |
| `c` | `a.b.(c+1).0` |
| `b` | `a.(b+1).0.0` |
| `a` | `(a+1).0.0.0` |

Manual version:

- `versionName` phai dung format `a.b.c.d`.
- `versionName` moi phai lon hon version hien tai trong Gradle.
- `versionCode` moi duoc tinh tu `versionName`, khong nhap rieng.
- Version hien tai trong Gradle phai co `versionCode` khop cong thuc tren, neu khong workflow fail som o `prepare`.

## 4. `synclab-release.json` contract

Vi du day du:

```json
{
  "schemaVersion": 1,
  "project": {
    "name": "batmon"
  },
  "version": {
    "source": "gradle",
    "file": "app/build.gradle",
    "versionNameScheme": "quad",
    "versionCodeFormula": "a*100000000+b*1000000+c*10000+d"
  },
  "signingService": {
    "urlEnv": "SYNCLAB_SIGNING_URL",
    "requiresTailscale": false,
    "tlsVerify": false
  },
  "bundle": {
    "name": "android_all",
    "targets": ["debug", "prerelease", "release"]
  },
  "targets": {
    "debug": {
      "buildCommand": ["./gradlew", "assembleDebug"],
      "artifactPattern": "app/build/outputs/apk/debug/*.apk",
      "signing": {
        "enabled": false
      },
      "assetName": "{project}-debug-{versionName}.apk"
    },
    "prerelease": {
      "buildCommand": ["./gradlew", "assemblePrerelease"],
      "artifactPattern": "app/build/outputs/apk/prerelease/*.apk",
      "signing": {
        "enabled": true,
        "profile": "preview",
        "expectedSignerDn": "CN=Synclab Android Preview, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN"
      },
      "assetName": "{project}-prerelease-{versionName}.apk"
    },
    "release": {
      "buildCommand": ["./gradlew", "assembleRelease"],
      "artifactPattern": "app/build/outputs/apk/release/*.apk",
      "signing": {
        "enabled": true,
        "profile": "prod",
        "expectedSignerDn": "CN=Synclab Android Upload, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN"
      },
      "assetName": "{project}-release-{versionName}.apk"
    }
  },
  "githubRelease": {
    "tagFormat": "v{versionName}",
    "nameFormat": "{project} {versionName}",
    "prerelease": true
  }
}
```

### Root fields

| Field | Required | Type | Gia tri hop le |
| --- | --- | --- | --- |
| `schemaVersion` | Yes | number | Hien tai chi support `1`. |
| `project` | Yes | object | Project metadata. |
| `version` | Yes | object | Noi framework doc va update version. |
| `signingService` | No | object | Config signing service legacy/CLI. Production reusable workflow dung local endpoint tren NAS. |
| `bundle` | Yes | object | Nhom target release. |
| `targets` | Yes | object | Khai bao tung build target. |
| `githubRelease` | Yes | object | Tag/name/prerelease cua GitHub Release. |

### `project`

| Field | Required | Type | Ghi chu |
| --- | --- | --- | --- |
| `name` | Yes | string | Dung trong asset/release name qua token `{project}`. |

### `version`

| Field | Required | Type | Gia tri hop le |
| --- | --- | --- | --- |
| `source` | Yes | string | Hien chi support `gradle`. |
| `file` | Yes | string | Path Gradle file trong client repo, vi du `app/build.gradle`. |
| `versionNameScheme` | Yes | string | Hien chi support `quad`. |
| `versionCodeFormula` | Yes | string | Nen khai bao dung `a*100000000+b*1000000+c*10000+d`. |

Gradle file phai co version hien tai de framework doc va update:

```gradle
versionName "0.0.0.1"
versionCode 1
```

hoac cu phap tuong duong ma parser cua framework dang support trong client repo.

### `signingService`

| Field | Required | Type | Default | Ghi chu |
| --- | --- | --- | --- | --- |
| `urlEnv` | No | string | `SYNCLAB_SIGNING_URL` | Dung cho CLI/preflight legacy. |
| `requiresTailscale` | No | boolean | `false` | Production CI/CD khong dung Tailscale cho signing path. |
| `tlsVerify` | No | boolean | `false` | Self-signed cert tren NAS nen mac dinh false. |

Trong reusable workflow production, job `sign` goi truc tiep:

```text
https://127.0.0.1:8443
```

Endpoint nay chi co y nghia ben trong NAS self-hosted runner container dung host network.

### `bundle`

| Field | Required | Type | Ghi chu |
| --- | --- | --- | --- |
| `name` | Yes | string | Ten bundle de document/debug. |
| `targets` | Yes | string array | Danh sach target se build/sign/publish. Moi item phai ton tai trong `targets`. |

### `targets.<name>`

| Field | Required | Type | Ghi chu |
| --- | --- | --- | --- |
| `buildCommand` | Yes | string array | Command build chay tren GitHub-hosted runner. |
| `artifactPattern` | Yes | string | Glob tim APK sau khi build. Phai match dung 1 APK cho target. |
| `signing` | Yes | object | Signing rule cho target. |
| `assetName` | Yes | string | Ten GitHub Release asset sau verify. |

`assetName` ho tro token:

```text
{project}
{versionName}
{versionCode}
{target}
```

`signing`:

| Field | Required | Type | Gia tri hop le |
| --- | --- | --- | --- |
| `enabled` | Yes | boolean | `true` hoac `false`. |
| `profile` | Required khi `enabled=true` | string | `preview` hoac `prod`. |
| `expectedSignerDn` | Required khi `enabled=true` | string | DN dung de verify APK da ky. |

Khuyen nghi target:

- `debug`: `signing.enabled=false`.
- `prerelease`: `profile=preview`.
- `release`: `profile=prod`.

Expected signer DN hien tai:

```text
preview: CN=Synclab Android Preview, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN
prod:    CN=Synclab Android Upload, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN
```

### `githubRelease`

| Field | Required | Type | Ghi chu |
| --- | --- | --- | --- |
| `tagFormat` | Yes | string | Vi du `v{versionName}`. |
| `nameFormat` | Yes | string | Vi du `{project} {versionName}`. |
| `prerelease` | No | boolean | `true` tao prerelease, `false` tao release stable. |

`tagFormat` va `nameFormat` ho tro token:

```text
{project}
{versionName}
{versionCode}
```

## 5. Artifacts va output

Workflow artifact chinh:

| Artifact | Job tao | Noi dung |
| --- | --- | --- |
| `release-plan` | `prepare` | `release-plan.json`, metadata version/target/release. |
| `unsigned-apks` | `build` | APK unsigned theo target, vi du `debug.apk`, `prerelease.apk`, `release.apk`. |
| `build-debug-logs` | `build` | Gradle/build logs de debug. |
| `signed-apks` | `sign` | `debug.apk`, `prerelease-signed.apk`, `release-signed.apk`, signing logs. |
| `sign-debug-logs` | `sign` | Health response, HTTP headers, HTTP code, file tree. |
| `final-artifacts` | `verify_publish` | APK asset cuoi, `metadata.json`, `checksum.sha256`. |

GitHub Release assets mac dinh theo config Batmon:

```text
batmon-debug-{versionName}.apk
batmon-prerelease-{versionName}.apk
batmon-release-{versionName}.apk
metadata.json
checksum.sha256
```

Khi `dryRun=true`, workflow van build/sign/verify va upload workflow artifacts, nhung khong commit version, khong tao tag, khong publish GitHub Release.

Khi `dryRun=false`, job `verify_publish` se:

```text
commit version file -> create tag -> push commit/tag -> create GitHub Release -> upload assets
```

## 6. Debug va loi thuong gap

Loi config:

```text
[PRE_FLIGHT_FAILED] Config file not found
[PRE_FLIGHT_FAILED] schemaVersion must be 1
[PRE_FLIGHT_FAILED] version.source must be gradle
[PRE_FLIGHT_FAILED] bundle target <name> is not declared in targets
```

Loi version:

```text
[PRE_FLIGHT_FAILED] Version name must use a.b.c.d format
[PRE_FLIGHT_FAILED] Current versionCode ... does not match versionName ...
[PRE_FLIGHT_FAILED] Next version ... must be greater than current ...
```

Loi build:

```text
[BUILD_FAILED] Target <name> build command failed
[BUILD_FAILED] Expected exactly one APK for target <name>
```

Loi signing:

```text
[SIGN_FAILED] signing API key is required for profile: preview
[SIGN_FAILED] unsigned APK not found
HTTP_CODE=401
HTTP_CODE=403
```

- `401`: secret sai hoac missing.
- `403`: API key dung nhung khong duoc phep dung profile do.
- Job queued lau: NAS runner offline, label sai, hoac repo chua duoc allow runner group.
- Job sign fail health check: signing service tren NAS chua chay hoac runner container khong goi duoc `https://127.0.0.1:8443`.

Loi verify/publish:

```text
[VERIFY_FAILED] signer DN mismatch
[VERIFY_FAILED] versionName/versionCode mismatch
[PUBLISH_FAILED] GitHub release already exists
```

Neu can debug nhanh, uu tien download cac artifacts:

```text
release-plan
build-debug-logs
sign-debug-logs
final-artifacts
```

## 7. Quy trinh test release

Test lan dau tren client repo:

1. Chay workflow voi `dryRun=true`.
2. Xac nhan `prepare`, `build`, `sign`, `verify_publish` deu pass.
3. Xac nhan job `sign` chay tren runner `nas5cb6ad-signing-01` hoac runner Synclab co label `synclab-signing`.
4. Download `final-artifacts`.
5. Verify `checksum.sha256`.
6. Verify signer DN cua prerelease/release APK bang `apksigner`.

Test release that:

1. Dung tag tam, vi du `cicd-test-v{versionName}`, de tranh trung release production.
2. Chay workflow voi `dryRun=false`.
3. Kiem tra GitHub Release, assets, metadata va checksum.
4. Sau khi review xong thi xoa release/tag/branch test neu do chi la release gia.

Production release:

1. Dam bao branch/repo da merge config dung.
2. Chay workflow voi `versionName` manual neu can chot version cu the, hoac de trong va dung `bump`.
3. Dung `dryRun=true` truoc neu co thay doi config/build moi.
4. Chay lai voi `dryRun=false` de publish.
