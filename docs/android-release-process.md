# Synclab Android Release Process

Tài liệu này mô tả cách các Android client repo gọi `synclab-CICD-framework` để build, ký APK qua Synclab signing service, verify và publish GitHub Release.

## 1. Kiến trúc release

Client repo, ví dụ `batmon`, không copy release logic vào repo riêng. Client repo chỉ khai báo workflow gọi reusable workflow của framework:

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
    secrets: inherit
```

Release flow:

```text
prepare -> build -> sign -> verify_publish
```

- `prepare`: chạy trên GitHub-hosted runner, đọc `synclab-release.json`, đọc version hiện tại từ Gradle, tính version mới, sinh `release-plan.json`.
- `build`: chạy trên GitHub-hosted runner, update version local theo release plan, build các APK unsigned, upload artifact `unsigned-apks`.
- `sign`: hỗ trợ hai mode. `self-hosted` chạy trên NAS runner `synclab-signing` và gọi local signing service tại `https://127.0.0.1:8443`; `public-api` chạy trên `ubuntu-latest`, reuse framework `command: sign` và gọi endpoint public được cấu hình qua `signingUrl`.
- `verify_publish`: chạy trên GitHub-hosted runner, verify version/signature, tạo checksum/metadata, và publish GitHub Release nếu `dryRun=false`.

Mode mặc định là `self-hosted` để giữ backward compatibility cho các caller hiện tại như Batmon.

## 2. Workflow inputs và secrets

Reusable workflow:

```text
Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-release.yml@v1
```

Inputs:

| Input | Required | Default | Giá trị hợp lệ | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `configFile` | No | `synclab-release.json` | Path file JSON trong client repo | Release contract file. |
| `bump` | No | `d` | `a`, `b`, `c`, `d` | Auto bump level khi không truyền `versionName`. |
| `versionName` | No | empty | Format `a.b.c.d` | Manual version override. Nếu có giá trị thì framework không auto bump. |
| `dryRun` | No | `true` | `true`, `false` | `true` thì build/sign/verify nhưng không commit, tag, publish release. |
| `signingMode` | No | `self-hosted` | `self-hosted`, `public-api` | Chọn backend/runner cho signing job. |
| `signingUrl` | No | `https://sign.synclab.com.vn` | HTTPS URL | Endpoint dùng khi `signingMode=public-api`. |

Secrets cần khai báo ở từng client repo và truyền qua `secrets: inherit`:

| Secret | Required | Ý nghĩa |
| --- | --- | --- |
| `SYNCLAB_SIGNING_API_KEY_PREVIEW` | Khi bundle có target dùng `preview` | API key được phép ký profile `preview`. |
| `SYNCLAB_SIGNING_API_KEY_PROD` | Khi bundle có target dùng `prod` | API key được phép ký profile `prod`. |

Android release workflow publish bằng `github.token`; không cần `RELEASE_GH_TOKEN`. Secret này chỉ còn cần cho ship workflow/cross-repo ở mục 8.

Các secret khác là build-command secret do client tự định nghĩa trong
`synclab-release.json` bằng placeholder `{{secret.NAME}}`. Ví dụ Batmon dùng:

| Secret | Required khi config có dùng | Ý nghĩa |
| --- | --- | --- |
| `SYNCLAB_PREVIEW_OWNER` | Yes | GitHub owner dùng cho Preview Program của client repo. |
| `SYNCLAB_PREVIEW_REPO` | Yes | GitHub repo dùng cho Preview Program của client repo. |
| `SYNCLAB_PREVIEW_OAUTH_CLIENT_ID` | Yes | OAuth client id dùng cho GitHub Preview login. |

Khi client thêm secret mới cho build, chỉ cần thêm repo secret và tham chiếu
`{{secret.NEW_SECRET}}` trong target `buildCommand`; không cần sửa framework.

Runner requirement:

- `self-hosted`: dùng `[self-hosted, linux, x64, synclab-signing]`. Org runner phải được allow cho caller repo.
- `public-api`: dùng GitHub-hosted `ubuntu-latest`; phù hợp cho caller repo có quyền truy cập framework nhưng không có hoặc không muốn phụ thuộc shared signing runner.

Ví dụ public signing:

```yaml
jobs:
  release:
    uses: Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-release.yml@v1
    with:
      configFile: synclab-release.json
      signingMode: public-api
      signingUrl: https://sign.synclab.com.vn
      dryRun: true
    secrets:
      SYNCLAB_SIGNING_API_KEY_PREVIEW: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PREVIEW }}
      SYNCLAB_SIGNING_API_KEY_PROD: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PROD }}
```

Public signing mode không thay đổi GitHub repository access policy. Caller vẫn phải có quyền truy cập repository chứa reusable workflow.

Với `public-api`, caller vẫn cấu hình `signingService.tlsVerify` trong `synclab-release.json` và dùng các secret `SYNCLAB_SIGNING_API_KEY_PREVIEW/PROD` như hiện tại.

## 3. Version rule

Framework chỉ support version name dạng:

```text
a.b.c.d
```

Range:

- `a >= 0`
- `0 <= b <= 99`
- `0 <= c <= 99`
- `0 <= d <= 9999`

Version code được tính từ version name:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Ví dụ:

```text
10.3.5.6 -> 1003050006
```

Auto bump:

| `bump` | Kết quả |
| --- | --- |
| `d` | `a.b.c.(d+1)` |
| `c` | `a.b.(c+1).0` |
| `b` | `a.(b+1).0.0` |
| `a` | `(a+1).0.0.0` |

Manual version:

- `versionName` phải đúng format `a.b.c.d`.
- `versionName` mới phải lớn hơn version hiện tại trong Gradle.
- `versionCode` mới được tính từ `versionName`, không nhập riêng.
- Version hiện tại trong Gradle phải có `versionCode` khớp công thức trên, nếu không workflow fail sớm ở `prepare`.

## 4. `synclab-release.json` contract

Ví dụ đầy đủ:

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
      "buildCommand": [
        "./gradlew",
        "assembleDebug",
        "-PGITHUB_PREVIEW_OWNER={{secret.SYNCLAB_PREVIEW_OWNER}}",
        "-PGITHUB_PREVIEW_REPO={{secret.SYNCLAB_PREVIEW_REPO}}",
        "-PGITHUB_PREVIEW_OAUTH_CLIENT_ID={{secret.SYNCLAB_PREVIEW_OAUTH_CLIENT_ID}}",
        "-PGITHUB_PREVIEW_RELEASE_TAG_PREFIX=preview",
        "-PGITHUB_PREVIEW_APK_ASSET_PATTERN=.*\\.apk"
      ],
      "artifactPattern": "app/build/outputs/apk/debug/*.apk",
      "signing": {
        "enabled": false
      },
      "assetName": "{project}-debug-{versionName}.apk"
    },
    "prerelease": {
      "buildCommand": [
        "./gradlew",
        "assemblePrerelease",
        "-PGITHUB_PREVIEW_OWNER={{secret.SYNCLAB_PREVIEW_OWNER}}",
        "-PGITHUB_PREVIEW_REPO={{secret.SYNCLAB_PREVIEW_REPO}}",
        "-PGITHUB_PREVIEW_OAUTH_CLIENT_ID={{secret.SYNCLAB_PREVIEW_OAUTH_CLIENT_ID}}",
        "-PGITHUB_PREVIEW_RELEASE_TAG_PREFIX=preview",
        "-PGITHUB_PREVIEW_APK_ASSET_PATTERN=.*\\.apk"
      ],
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

| Field | Required | Type | Giá trị hợp lệ |
| --- | --- | --- | --- |
| `schemaVersion` | Yes | number | Hiện tại chỉ support `1`. |
| `project` | Yes | object | Project metadata. |
| `version` | Yes | object | Nơi framework đọc và update version. |
| `signingService` | No | object | Config signing service. `self-hosted` dùng local NAS endpoint; `public-api` dùng public endpoint được truyền qua workflow. |
| `bundle` | Yes | object | Nhóm target release. |
| `targets` | Yes | object | Khai báo từng build target. |
| `githubRelease` | Yes | object | Tag/name/prerelease của GitHub Release. |

### `project`

| Field | Required | Type | Ghi chú |
| --- | --- | --- | --- |
| `name` | Yes | string | Dùng trong asset/release name qua token `{project}`. |

### `version`

| Field | Required | Type | Giá trị hợp lệ |
| --- | --- | --- | --- |
| `source` | Yes | string | Hiện chỉ support `gradle`. |
| `file` | Yes | string | Path Gradle file trong client repo, ví dụ `app/build.gradle`. |
| `versionNameScheme` | Yes | string | Hiện chỉ support `quad`. |
| `versionCodeFormula` | Yes | string | Nên khai báo đúng `a*100000000+b*1000000+c*10000+d`. |

Gradle file phải có version hiện tại để framework đọc và update:

```gradle
versionName "0.0.0.1"
versionCode 1
```

hoặc cú pháp tương đương mà parser của framework đang support trong client repo.

### `signingService`

| Field | Required | Type | Default | Ghi chú |
| --- | --- | --- | --- | --- |
| `urlEnv` | No | string | `SYNCLAB_SIGNING_URL` | Dùng cho CLI/preflight legacy. |
| `requiresTailscale` | No | boolean | `false` | Production CI/CD không dùng Tailscale cho signing path. |
| `tlsVerify` | No | boolean | `false` | Self-signed cert trên NAS nên mặc định false. |

Trong reusable workflow production:

- `self-hosted`: job `sign` gọi `https://127.0.0.1:8443` trên NAS runner.
- `public-api`: job `sign` chạy trên `ubuntu-latest` và dùng `signingUrl` (mặc định `https://sign.synclab.com.vn`).

Local endpoint chỉ có ý nghĩa bên trong NAS self-hosted runner container dùng host network.

### `bundle`

| Field | Required | Type | Ghi chú |
| --- | --- | --- | --- |
| `name` | Yes | string | Tên bundle để document/debug. |
| `targets` | Yes | string array | Danh sách target sẽ build/sign/publish. Mỗi item phải tồn tại trong `targets`. |

### `targets.<name>`

| Field | Required | Type | Ghi chú |
| --- | --- | --- | --- |
| `buildCommand` | Yes | string array | Command build chạy trên GitHub-hosted runner. Hỗ trợ placeholder `{{secret.NAME}}` hoặc `{{env.NAME}}`; placeholder được resolve theo từng target trước khi chạy command. |
| `artifactPattern` | Yes | string | Glob tìm APK sau khi build. Phải match đúng 1 APK cho target. |
| `signing` | Yes | object | Signing rule cho target. |
| `assetName` | Yes | string | Tên GitHub Release asset sau verify. |

`assetName` hỗ trợ token:

```text
{project}
{versionName}
{versionCode}
{target}
```

`signing`:

| Field | Required | Type | Giá trị hợp lệ |
| --- | --- | --- | --- |
| `enabled` | Yes | boolean | `true` hoặc `false`. |
| `profile` | Required khi `enabled=true` | string | `preview` hoặc `prod`. |
| `expectedSignerDn` | Required khi `enabled=true` | string | DN dùng để verify APK đã ký. |

Khuyến nghị target:

- `debug`: `signing.enabled=false`.
- `prerelease`: `profile=preview`.
- `release`: `profile=prod`.

Expected signer DN hiện tại:

```text
preview: CN=Synclab Android Preview, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN
prod:    CN=Synclab Android Upload, OU=Synclab Signing, O=Synclab, L=Hanoi, ST=Hanoi, C=VN
```

### `githubRelease`

| Field | Required | Type | Ghi chú |
| --- | --- | --- | --- |
| `tagFormat` | Yes | string | Ví dụ `v{versionName}`. |
| `nameFormat` | Yes | string | Ví dụ `{project} {versionName}`. |
| `prerelease` | No | boolean | `true` tạo prerelease, `false` tạo release stable. |

`tagFormat` và `nameFormat` hỗ trợ token:

```text
{project}
{versionName}
{versionCode}
```

## 5. Artifacts và output

Workflow artifact chính:

| Artifact | Job tạo | Nội dung |
| --- | --- | --- |
| `release-plan` | `prepare` | `release-plan.json`, metadata version/target/release. |
| `unsigned-apks` | `build` | APK unsigned theo target, ví dụ `debug.apk`, `prerelease.apk`, `release.apk`. |
| `build-debug-logs` | `build` | Gradle/build logs để debug. |
| `signed-apks` | `sign` | `debug.apk`, `prerelease-signed.apk`, `release-signed.apk`, signing logs. |
| `sign-debug-logs` | `sign` | Health response, HTTP headers, HTTP code, file tree. |
| `final-artifacts` | `verify_publish` | APK asset cuối, `metadata.json`, `checksum.sha256`. |

GitHub Release assets mặc định theo config Batmon:

```text
batmon-debug-{versionName}.apk
batmon-prerelease-{versionName}.apk
batmon-release-{versionName}.apk
metadata.json
checksum.sha256
```

Khi `dryRun=true`, workflow vẫn build/sign/verify và upload workflow artifacts, nhưng không commit version, không tạo tag, không publish GitHub Release.

Khi `dryRun=false`, job `verify_publish` sẽ:

```text
commit version file -> create tag -> push commit/tag -> create GitHub Release -> upload assets
```

## 6. Debug và lỗi thường gặp

Lỗi config:

```text
[PRE_FLIGHT_FAILED] Config file not found
[PRE_FLIGHT_FAILED] schemaVersion must be 1
[PRE_FLIGHT_FAILED] version.source must be gradle
[PRE_FLIGHT_FAILED] bundle target <name> is not declared in targets
```

Lỗi version:

```text
[PRE_FLIGHT_FAILED] Version name must use a.b.c.d format
[PRE_FLIGHT_FAILED] Current versionCode ... does not match versionName ...
[PRE_FLIGHT_FAILED] Next version ... must be greater than current ...
```

Lỗi build:

```text
[BUILD_FAILED] Target <name> build command failed
[BUILD_FAILED] Expected exactly one APK for target <name>
```

Lỗi signing:

```text
[SIGN_FAILED] signing API key is required for profile: preview
[SIGN_FAILED] unsigned APK not found
HTTP_CODE=401
HTTP_CODE=403
```

- `401`: secret sai hoặc missing.
- `403`: API key đúng nhưng không được phép dùng profile đó.
- Job queued lâu: NAS runner offline, label sai, hoặc repo chưa được allow runner group.
- Với `self-hosted`, job sign fail health check khi signing service trên NAS chưa chạy hoặc runner container không gọi được `https://127.0.0.1:8443`.

Lỗi verify/publish:

```text
[VERIFY_FAILED] signer DN mismatch
[VERIFY_FAILED] versionName/versionCode mismatch
[PUBLISH_FAILED] GitHub release already exists
```

Nếu cần debug nhanh, ưu tiên download các artifacts:

```text
release-plan
build-debug-logs
sign-debug-logs
final-artifacts
```

## 7. Quy trình test release

Test lần đầu trên client repo:

1. Chạy workflow với `dryRun=true`.
2. Xác nhận `prepare`, `build`, `sign`, `verify_publish` đều pass.
3. Xác nhận job `sign` chạy đúng runner theo mode: runner có label `synclab-signing` với `self-hosted`, hoặc `ubuntu-latest` với `public-api`.
4. Download `final-artifacts`.
5. Verify `checksum.sha256`.
6. Verify signer DN của prerelease/release APK bằng `apksigner`.

Test release thật:

1. Dùng tag tạm, ví dụ `cicd-test-v{versionName}`, để tránh trùng release production.
2. Chạy workflow với `dryRun=false`.
3. Kiểm tra GitHub Release, assets, metadata và checksum.
4. Sau khi review xong thì xóa release/tag/branch test nếu đó chỉ là release giả.

Production release:

1. Đảm bảo branch/repo đã merge config đúng.
2. Chạy workflow với `versionName` manual nếu cần chốt version cụ thể, hoặc để trống và dùng `bump`.
3. Dùng `dryRun=true` trước nếu có thay đổi config/build mới.
4. Chạy lại với `dryRun=false` để publish.

## 8. Ship release sang repo khác

Ship workflow dùng để copy một release đã publish từ source repo sang target repo.
Flow này không build lại, không ký lại APK và không dùng NAS self-hosted runner.
Source repo và target repo có thể nằm khác org, miễn token có quyền với cả hai repo.

Reusable workflow:

```text
Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-ship-release.yml@v1
```

Ví dụ client workflow:

```yaml
jobs:
  ship:
    permissions:
      contents: read
    uses: Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-ship-release.yml@v1
    with:
      sourceTag: v1.0.0
      targetRepo: Synclab-VN-dev/batmon-test
      dryRun: true
    secrets:
      RELEASE_GH_TOKEN: ${{ secrets.RELEASE_GH_TOKEN }}
```

Inputs:

| Input | Required | Default | Ý nghĩa |
| --- | --- | --- | --- |
| `sourceTag` | Yes | none | Tag release nguồn cần ship. |
| `sourceRepo` | No | `github.repository` | Repo nguồn, format `OWNER/REPO`. |
| `targetRepo` | Yes | none | Repo đích, format `OWNER/REPO`. |
| `dryRun` | No | `true` | `true` chỉ kiểm tra/download/verify, không tạo release đích. |
| `frameworkRef` | No | `v1` | Ref của framework composite action. Chỉ cần override khi test workflow từ branch framework chưa merge. |

Secret:

| Secret | Required | Ý nghĩa |
| --- | --- | --- |
| `RELEASE_GH_TOKEN` | Yes | Token có quyền đọc source repo và quyền ghi release/contents vào target repo. |

Ship sẽ fail sớm nếu:

- Thiếu token hoặc repo input không đúng format `OWNER/REPO`.
- Token không đọc được source repo.
- Token không có quyền ghi target repo.
- Source release không tồn tại, là draft, hoặc không có asset.
- Source release thiếu `metadata.json` hoặc `checksum.sha256`.
- `checksum.sha256` mismatch hoặc trỏ tới path không an toàn.
- Token không truy cập được target repo.
- Target release cùng tag đã tồn tại.

Khi `dryRun=false`, workflow tạo release ở target repo với cùng tag, title, body,
prerelease flag và assets từ source release.
