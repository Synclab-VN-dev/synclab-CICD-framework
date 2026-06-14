# Synclab CICD Framework

Internal Android CI/CD framework for `Synclab-VN-dev`.

Detailed Android release process and `synclab-release.json` contract:

- [Synclab Android Release Process](docs/android-release-process.md)

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

Version names must use `a.b.c.d`. The framework derives `versionCode` with:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Example: `10.3.5.6 -> 1003050006`.

The production workflow uses a NAS self-hosted runner only for signing. The signing
job does not run Python, checkout source, build Android, or execute the framework
CLI. It downloads unsigned APK artifacts and calls the local signing appliance at
`https://127.0.0.1:8443`.
