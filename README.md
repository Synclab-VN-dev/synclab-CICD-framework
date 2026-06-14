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
    secrets: inherit
```

Version names must use `a.b.c.d`. The framework derives `versionCode` with:

```text
versionCode = a * 100000000 + b * 1000000 + c * 10000 + d
```

Example: `10.3.5.6 -> 1003050006`.

The reusable workflow joins Synclab Tailscale before calling the NAS signing API at
`SYNCLAB_SIGNING_URL`.
