import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import serve

from kimi_memory.files import read_json, write_json
from kimi_memory.oauth import native_auth

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"),
    reason="opt-in native Kimi authentication runtime",
)


def token(expires=1):
    return {
        "access_token": "synthetic-expired-access",
        "refresh_token": "synthetic-refresh",
        "expires_at": expires,
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "",
    }


def test_original_native_oauth_refresh_and_shared_file_key(tmp_path):
    home = tmp_path / "kimi"
    path = home / "credentials/kimi-code.json"
    write_json(path, token())

    def refresh(method, route, body, _headers):
        assert route == "/api/oauth/token" and method == "POST"
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "synthetic-refresh"
        return 200, {
            "access_token": "synthetic-new-access",
            "refresh_token": "synthetic-rotated-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    with serve(refresh) as (origin, requests):
        ref = {"storage": "file", "key": "oauth/kimi-code", "oauth_host": origin}
        command = (os.environ["KIMI_MEMORY_NATIVE_KIMI"],)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: native_auth(home, ref, command=command), range(2)))
        assert len(requests) == 1
        assert all(item["access_token"] == "synthetic-new-access" for item in results)
        assert read_json(path)["refresh_token"] == "synthetic-rotated-refresh"
        assert "kimi-codex-memory" in results[0]["headers"]["User-Agent"]


def test_still_valid_subscription_does_not_call_oauth_endpoint(tmp_path):
    home = tmp_path / "kimi"
    path = home / "credentials/kimi-code.json"
    write_json(path, token(time.time() + 7200))
    before = path.read_bytes()
    with serve(lambda *_: (500, {})) as (origin, requests):
        result = native_auth(
            home,
            {"storage": "file", "key": "oauth/kimi-code", "oauth_host": origin},
            command=(os.environ["KIMI_MEMORY_NATIVE_KIMI"],),
        )
    assert result["access_token"] == "synthetic-expired-access"
    assert not requests and path.read_bytes() == before


def test_forced_subscription_refresh_refuses_redirect(tmp_path):
    from kimi_memory.errors import ConfigurationError

    home = tmp_path / "kimi"
    path = home / "credentials/kimi-code.json"
    write_json(path, token(time.time() + 7200))
    with serve(lambda *_: (302, {}, {"Location": "https://example.test/never-follow"})) as (
        origin,
        requests,
    ):
        with pytest.raises(ConfigurationError):
            native_auth(
                home,
                {"storage": "file", "key": "oauth/kimi-code", "oauth_host": origin},
                force=True,
                command=(os.environ["KIMI_MEMORY_NATIVE_KIMI"],),
            )
    assert requests
    assert read_json(path)["refresh_token"] == "synthetic-refresh"
