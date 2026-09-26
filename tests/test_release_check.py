"""The updater only fetches public metadata, not executable code or user information."""

import copy
import json
import time

import pytest
from conftest import serve

from kimi_memory import release_check
from kimi_memory.files import atomic_write, file_lock, read_json
from kimi_memory.update_notices import CHECK_INTERVAL, REPOSITORY, prepare_notice


def release(version="9.8.7"):
    return {
        "tag_name": "v" + version,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-20T00:00:00Z",
        "html_url": f"{REPOSITORY}/releases/tag/v{version}",
        "body": "DO NOT FORWARD OR PERSIST THIS REMOTE RELEASE BODY",
        "assets": [
            {
                "name": "kimi-codex-memory.zip",
                "state": "uploaded",
                "browser_download_url": f"{REPOSITORY}/releases/download/v{version}/kimi-codex-memory.zip",
            }
        ],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", True),
        ("draft", None),
        ("prerelease", True),
        ("prerelease", 0),
        ("tag_name", "v1.2.3-alpha"),
        ("tag_name", "v1.2.3; echo bad"),
        ("tag_name", "v1.2.3\nINJECTION"),
        ("html_url", "https://evil.invalid/"),
        ("published_at", None),
        ("published_at", "yesterday"),
        ("published_at", "2026-09-20T00:00:00"),
        ("assets", []),
        ("assets", {}),
    ],
)
def test_only_published_installable_stable_releases_are_candidates(field, value):
    raw = release()
    raw[field] = value
    with pytest.raises((ValueError, TypeError)):
        release_check.release_version(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "new"),
        ("browser_download_url", "https://evil.invalid/memory.zip"),
        ("browser_download_url", REPOSITORY + "/releases/latest/download/kimi-codex-memory.zip"),
        ("name", "source.zip"),
    ],
)
def test_available_asset_is_bound_to_exact_repository_and_version(field, value):
    raw = release()
    raw["assets"][0][field] = value
    with pytest.raises(ValueError):
        release_check.release_version(raw)


def test_check_is_public_metadata_only_once_per_day_and_remote_text_is_discarded(home, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "synthetic-must-not-be-sent")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-model-key")
    monkeypatch.setenv("KIMI_CODE_CUSTOM_HEADERS", "Authorization: Bearer synthetic")
    with serve(lambda *_: (200, release())) as (origin, requests):
        monkeypatch.setattr(
            release_check, "RELEASE_API", origin + "/repos/WAcry/kimi-codex-memory/releases/latest"
        )
        result = release_check.check_updates(home)
        assert result["state"] == "ready" and result["latest"] == "9.8.7"
        assert release_check.check_updates(home) == {"state": "not_due"}
        assert len(requests) == 1
        method, path, body, headers = requests[0]
        assert method == "GET" and body is None and path.endswith("/releases/latest")
        assert "Authorization" not in headers and "Cookie" not in headers
        assert "synthetic" not in json.dumps(headers)
        assert "User-Agent" in headers
    cache = read_json(home / "updates/cache.json")
    assert set(cache) == {"format", "state", "attempted_at", "checked_at", "latest"}
    assert "REMOTE RELEASE BODY" not in json.dumps(cache)
    assert not (home / "state.sqlite").exists()


@pytest.mark.parametrize(
    "response",
    [
        (403, {"secret": "rate limit"}),
        (404, {}),
        (429, {}),
        (500, {}),
        (200, {"draft": True}),
        (200, {"huge": "x" * 140000}),
    ],
)
def test_network_api_and_protocol_failure_is_quiet_and_daily_backoff_applies(
    home, monkeypatch, response
):
    with serve(lambda *_: copy.deepcopy(response)) as (origin, requests):
        monkeypatch.setattr(release_check, "RELEASE_API", origin)
        assert release_check.check_updates(home)["state"] == "unavailable"
        assert release_check.check_updates(home)["state"] == "not_due"
        assert len(requests) == 1
    assert prepare_notice("s", "hello", home) == ""
    assert set(read_json(home / "updates/cache.json")) == {"format", "state", "attempted_at"}


def test_next_day_retries_but_does_not_poll_without_events(home, monkeypatch):
    with serve(lambda *_: (200, release())) as (origin, requests):
        monkeypatch.setattr(release_check, "RELEASE_API", origin)
        release_check.check_updates(home)
        next_day = time.time() + CHECK_INTERVAL + 1
        monkeypatch.setattr(release_check.time, "time", lambda: next_day)
        assert release_check.check_updates(home)["state"] == "ready"
        assert len(requests) == 2


def test_disabled_or_locked_checker_never_attempts_network(home, monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("Should not make a request")

    monkeypatch.setattr(release_check.JsonHttp, "request", forbidden)
    with file_lock(home / "updates/check.lock"):
        assert release_check.check_updates(home) == {"state": "busy"}
    atomic_write(home / "updates.toml", "enabled = false\n")
    assert release_check.check_updates(home) == {"state": "disabled"}


def test_transport_has_short_timeout_fixed_size_and_no_redirect_support(home, monkeypatch):
    seen = []

    class LocalProbe:
        def __init__(self, **kw):
            seen.append(kw)

        def request(self, url, **kw):
            seen.append((url, kw))
            raise TimeoutError("not written to state")

    monkeypatch.setattr(release_check, "JsonHttp", LocalProbe)
    assert release_check.check_updates(home)["state"] == "unavailable"
    assert seen[0] == {"timeout": 5, "max_bytes": 128 * 1024, "use_proxy": True}
    assert seen[1][0] == "https://api.github.com/repos/WAcry/kimi-codex-memory/releases/latest"
    assert "not written" not in json.dumps(read_json(home / "updates/cache.json"))


def test_metadata_redirect_is_not_followed(home, monkeypatch):
    with serve(lambda *_: (200, release())) as (target, received):
        with serve(lambda *_: (302, {}, {"Location": target + "/collect"})) as (origin, requests):
            monkeypatch.setattr(release_check, "RELEASE_API", origin)
            assert release_check.check_updates(home)["state"] == "unavailable"
            assert len(requests) == 1
        assert received == []


def test_failed_refresh_never_keeps_advertising_a_stale_release(home, monkeypatch):
    with serve(lambda *_: (200, release())) as (origin, _):
        monkeypatch.setattr(release_check, "RELEASE_API", origin)
        assert release_check.check_updates(home)["state"] == "ready"
    next_day = time.time() + CHECK_INTERVAL + 1
    monkeypatch.setattr(release_check.time, "time", lambda: next_day)
    with serve(lambda *_: (404, {})) as (origin, _):
        monkeypatch.setattr(release_check, "RELEASE_API", origin)
        assert release_check.check_updates(home)["state"] == "unavailable"
    assert "latest" not in read_json(home / "updates/cache.json")
    assert prepare_notice("s", "hello", home) == ""
