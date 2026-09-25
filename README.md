# Synclab CICD Framework

Internal Android CI/CD framework for `Synclab-VN-dev`.

## Repo này giải quyết vấn đề gì

Repo này chuẩn hóa quy trình release Android cho các project nội bộ Synclab.
Thay vì mỗi client repo tự viết workflow build, bump version, ký APK, verify và
publish release, client repo chỉ cần khai báo reusable workflow và một file
`synclab-release.json`.

Framework chịu trách nhiệm:

- Đọc release contract từ `synclab-release.json`.
- Tính version mới theo chuẩn `a.b.c.d` và tự derive `versionCode`.
- Build Android artifacts theo target, hỗ trợ `apk` và `aab`.
- Ký APK/AAB bằng Synclab signing service mà không đưa signing key lên GitHub (AAB hiện dùng public API signing path).
- Verify artifact version, signer, checksum và publish GitHub Release.
- Ship một release đã publish từ repo nguồn sang repo đích mà không build/ký lại.

## Kiến trúc tổng thể

```text
Client Android repo
  -> reusable workflow: .github/workflows/android-release.yml
  -> composite action: action.yml
  -> Python CLI/package: synclab_release/
  -> unsigned Android artifacts (APK/AAB)
  -> signing job
       -> self-hosted: NAS runner -> https://127.0.0.1:8443
       -> public-api: ubuntu-latest -> https://sign.synclab.com.vn
  -> signed Android artifacts
  -> verify/publish GitHub Release
  -> optional ship release to another repo
```

Các thành phần chính:

- **Client repo**: chứa source Android, Gradle config, `synclab-release.json` và workflow gọi framework.
- **Reusable workflow**: chia release thành các job `prepare`, `build`, `sign`, `verify_publish`.
- **Composite action**: cài Python package từ repo này và gọi CLI `synclab-release`.
- **Python package**: xử lý config, version, build, artifact, verify và publish.
- **Signing job**: hỗ trợ `self-hosted` (NAS runner + local signing service) và `public-api` (GitHub-hosted runner + public signing endpoint).
- **Synclab signing service**: giữ signing key, ký APK/AAB bằng profile `preview` hoặc `prod`, rồi trả signed artifact.

Ranh giới quan trọng:

- GitHub-hosted runner luôn chạy `prepare`, `build`, `verify_publish`; với `public-api`, job `sign` cũng chạy trên GitHub-hosted runner.
- Với mode mặc định `self-hosted`, NAS self-hosted runner chỉ dùng cho signing.
- Không chạy Gradle build, test hoặc publish trên NAS.
- Client repo không copy release logic, chỉ cấu hình contract.

## Tài liệu chi tiết

- [Synclab Android Release Process](docs/android-release-process.md): quy trình Android release, workflow inputs/secrets, contract `synclab-release.json`, artifacts và debug.

## Usage

Client repositories call the reusable workflow:

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
      # Optional. Default: self-hosted
      # signingMode: public-api
      # signingUrl: https://sign.synclab.com.vn
    secrets: inherit
```

Configure framework signing/publish secrets and any build-command secrets referenced
by `{{secret.NAME}}` in `synclab-release.json` as repository secrets in each
Android client repository.

## Version rule

Version names must use `a.b.c.d`. The framework derives `versionCode` with:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Example: `10.3.5.6 -> 1003050006`.

## Artifact types

Mỗi target trong `synclab-release.json` có thể khai báo:

```json
{
  "artifactType": "apk"
}
```

hoặc:

```json
{
  "artifactType": "aab"
}
```

`artifactType` mặc định là `apk` để giữ backward compatibility. AAB signing dùng
endpoint `POST /v1/sign/android/aab`, multipart field `aab`, và được verify bằng
`jarsigner` + `bundletool` trước khi publish. Signed AAB targets phải khai báo
`signing.expectedSignerSha256`; framework reject unsigned ZIP entries và verify
certificate fingerprint bằng `keytool`, không chỉ dựa trên Subject DN.

## Signing modes

Reusable Android release workflow hỗ trợ hai mode:

- `self-hosted` (mặc định): giữ nguyên APK flow hiện tại, job `sign` chạy trên NAS self-hosted runner và gọi `https://127.0.0.1:8443`. Signed AAB targets bị reject sớm ở mode này.
- `public-api`: job `sign` chạy trên `ubuntu-latest`, reuse composite action `command: sign` và gọi endpoint truyền qua `signingUrl` (mặc định `https://sign.synclab.com.vn`). AAB signing hiện yêu cầu mode này.

Ví dụ caller sử dụng public API signing:

```yaml
jobs:
  release:
    uses: Synclab-VN-dev/synclab-CICD-framework/.github/workflows/android-release.yml@v1
    with:
      configFile: synclab-release.json
      signingMode: public-api
      signingUrl: https://sign.synclab.com.vn
      dryRun: true
    secrets: inherit
```

`synclab-release.json` của caller vẫn quyết định `tlsVerify` và profile signing.

## Ship release

Ship workflow copy một GitHub Release đã publish từ source repo sang target repo.
Workflow này không build, không ký lại APK và không dùng NAS runner. Nó kiểm tra
release nguồn, download assets, verify `checksum.sha256`, rồi tạo release tương
ứng ở repo đích. Source repo và target repo có thể nằm khác org, miễn
`RELEASE_GH_TOKEN` có quyền đọc source repo và quyền ghi release vào target repo.

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
