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
- Build các APK target như `debug`, `prerelease`, `release`.
- Ký APK bằng NAS signing appliance mà không đưa signing key lên GitHub.
- Verify APK, signer, checksum và publish GitHub Release.
- Ship một release đã publish từ repo nguồn sang repo đích mà không build/ký lại.

## Kiến trúc tổng thể

```text
Client Android repo
  -> reusable workflow: .github/workflows/android-release.yml
  -> composite action: action.yml
  -> Python CLI/package: synclab_release/
  -> unsigned APK artifacts
  -> NAS self-hosted signing job
  -> signed APK artifacts
  -> verify/publish GitHub Release
  -> optional ship release to another repo
```

Các thành phần chính:

- **Client repo**: chứa source Android, Gradle config, `synclab-release.json` và workflow gọi framework.
- **Reusable workflow**: chia release thành các job `prepare`, `build`, `sign`, `verify_publish`.
- **Composite action**: cài Python package từ repo này và gọi CLI `synclab-release`.
- **Python package**: xử lý config, version, build, artifact, verify và publish.
- **NAS self-hosted runner**: chỉ chạy job `sign`, download unsigned APK và gọi signing service local bằng shell/curl.
- **NAS signing service**: giữ signing key, ký APK bằng profile `preview` hoặc `prod`, rồi trả signed APK.

Ranh giới quan trọng:

- GitHub-hosted runner chạy `prepare`, `build`, `verify_publish`.
- NAS self-hosted runner chỉ dùng cho signing.
- Không chạy Python framework, Gradle build, test hoặc publish trên NAS.
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
    secrets:
      SYNCLAB_SIGNING_API_KEY_PREVIEW: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PREVIEW }}
      SYNCLAB_SIGNING_API_KEY_PROD: ${{ secrets.SYNCLAB_SIGNING_API_KEY_PROD }}
      RELEASE_GH_TOKEN: ${{ secrets.RELEASE_GH_TOKEN }}
```

Configure those values as repository secrets in each Android client repository.

## Version rule

Version names must use `a.b.c.d`. The framework derives `versionCode` with:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Example: `10.3.5.6 -> 1003050006`.

## Signing boundary

The production workflow uses a NAS self-hosted runner only for signing. The signing
job does not run Python, checkout source, build Android, or execute the framework
CLI. It downloads unsigned APK artifacts and calls the local signing appliance at
`https://127.0.0.1:8443`.

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
