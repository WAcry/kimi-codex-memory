"""One bounded unauthenticated release-metadata read, only in a separate process."""

import time
from datetime import datetime
from pathlib import Path

from .errors import BusyError
from .files import file_lock, write_json
from .http import JsonHttp
from .update_notices import REPOSITORY, check_due, enabled, version_key

RELEASE_API = "https://api.github.com/repos/WAcry/kimi-codex-memory/releases/latest"


def release_version(raw: object) -> str:
    if (
        not isinstance(raw, dict)
        or raw.get("draft") is not False
        or raw.get("prerelease") is not False
    ):
        raise ValueError("Not a public stable release")
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or version_key(tag[1:]) is None:
        raise ValueError("Invalid stable version")
    if raw.get("html_url") != f"{REPOSITORY}/releases/tag/{tag}":
        raise ValueError("Unexpected release origin")
    published = raw.get("published_at")
    if (
        not isinstance(published, str)
        or datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None
    ):
        raise ValueError("Release is not published")
    assets = raw.get("assets")
    if not isinstance(assets, list) or not any(
        isinstance(asset, dict)
        and asset.get("name") == "kimi-codex-memory.zip"
        and asset.get("state") == "uploaded"
        and asset.get("browser_download_url")
        == f"{REPOSITORY}/releases/download/{tag}/kimi-codex-memory.zip"
        for asset in assets
    ):
        raise ValueError("Installable release archive is not available")
    return tag[1:]


def check_updates(home: Path) -> dict:
    if not enabled(home):
        return {"state": "disabled"}
    try:
        with file_lock(home / "updates/check.lock"):
            now = time.time()
            if not check_due(home, now):
                return {"state": "not_due"}
            cache = {"format": 1, "attempted_at": now, "state": "checking"}
            write_json(home / "updates/cache.json", cache)
            try:
                raw = JsonHttp(timeout=5, max_bytes=128 * 1024, use_proxy=True).request(
                    RELEASE_API,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "kimi-codex-memory-update-check",
                    },
                )
                cache.update(state="ready", latest=release_version(raw), checked_at=time.time())
            except Exception:
                # No credential fallback, requests to a different server, body logs,
                # retries, update download, or disruption of generation/reading.
                cache["state"] = "unavailable"
            write_json(home / "updates/cache.json", cache)
            return {key: value for key, value in cache.items() if key != "format"}
    except BusyError:
        return {"state": "busy"}
    except (OSError, ValueError):
        return {"state": "unavailable"}
