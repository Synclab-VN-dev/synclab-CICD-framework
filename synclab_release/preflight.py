from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from .builder import validate_build_placeholders
from .command import run_command
from .errors import BuildError, PreflightError
from .models import ReleaseConfig, ResolvedVersion


def _http_get_json_or_text(url: str, headers: dict[str, str] | None = None, tls_verify: bool = True) -> str:
    context = None if tls_verify else ssl._create_unverified_context()
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise PreflightError(f"HTTP {exc.code} from {url}") from exc
    except OSError as exc:
        raise PreflightError(f"Cannot reach {url}: {exc}") from exc


def run_preflight(repo_root: Path, config: ReleaseConfig, resolved: ResolvedVersion, dry_run: bool) -> None:
    try:
        validate_build_placeholders([config.targets[name] for name in config.bundle_targets])
    except BuildError as exc:
        raise PreflightError(exc.message) from exc

    gradlew = repo_root / "gradlew"
    if not gradlew.exists():
        raise PreflightError("Gradle wrapper not found")

    tag = config.github_release.tag_format.format(versionName=resolved.next.version_name)
    tag_check = run_command(["git", "rev-parse", "--verify", f"refs/tags/{tag}"], repo_root, check=False)
    if tag_check.returncode == 0:
        raise PreflightError(f"Git tag already exists: {tag}")

    remote_tag = run_command(["git", "ls-remote", "--tags", "origin", tag], repo_root, check=False)
    if remote_tag.returncode == 0 and remote_tag.stdout.strip():
        raise PreflightError(f"Remote Git tag already exists: {tag}")

    if not dry_run:
        token = os.getenv("RELEASE_GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        if not token:
            raise PreflightError("RELEASE_GH_TOKEN or GITHUB_TOKEN is required for publish")

    signing_targets = [target for target in config.targets.values() if target.signing.enabled]
    if signing_targets:
        signing_url = os.getenv(config.signing_service.url_env)
        if not signing_url:
            raise PreflightError(f"{config.signing_service.url_env} is required")
        _http_get_json_or_text(f"{signing_url.rstrip('/')}/health", tls_verify=config.signing_service.tls_verify)

        profiles_seen: set[str] = set()
        for target in signing_targets:
            env_name = f"SYNCLAB_SIGNING_API_KEY_{target.signing.profile.upper()}"
            api_key = os.getenv(env_name)
            if not api_key:
                raise PreflightError(f"{env_name} is required")
            body = _http_get_json_or_text(
                f"{signing_url.rstrip('/')}/v1/profiles",
                headers={"X-Synclab-Api-Key": api_key},
                tls_verify=config.signing_service.tls_verify,
            )
            try:
                parsed = json.loads(body)
                profile_names = {str(item.get("name", item)) for item in parsed} if isinstance(parsed, list) else set()
            except json.JSONDecodeError:
                profile_names = set()
            if target.signing.profile not in body and target.signing.profile not in profile_names:
                raise PreflightError(f"API key not allowed for profile {target.signing.profile}")
            profiles_seen.add(target.signing.profile)

        if not profiles_seen:
            raise PreflightError("No signing profiles validated")
