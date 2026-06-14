# Synclab Release Framework

Internal Android release framework for `Synclab-VN-dev`.

Client repositories call the reusable workflow:

```yaml
jobs:
  release:
    permissions:
      contents: write
      id-token: write
    uses: Synclab-VN-dev/synclab-release-framework/.github/workflows/android-release.yml@v1
    with:
      configFile: synclab-release.json
      bump: ${{ inputs.bump }}
      versionName: ${{ inputs.versionName }}
      dryRun: ${{ inputs.dryRun }}
    secrets:
      TS_OAUTH_CLIENT_ID: ${{ secrets.TS_OAUTH_CLIENT_ID }}
      TS_AUDIENCE: ${{ secrets.TS_AUDIENCE }}
      SYNCLAB_SIGNING_URL: ${{ secrets.SYNCLAB_SIGNING_URL }}
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

The reusable workflow joins Synclab Tailscale before calling the NAS signing API at
`SYNCLAB_SIGNING_URL`.
