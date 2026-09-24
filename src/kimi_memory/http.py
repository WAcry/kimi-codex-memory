"""Bounded JSON HTTP without credential-bearing redirects or implicit proxies."""

import ipaddress
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .errors import ConfigurationError, TransportError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_origin(value: str) -> str:
    parts = urlsplit(value)
    host = parts.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if (
        not loopback
        or parts.scheme not in {"http", "https"}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ConfigurationError(
            "Kimi API must use an authenticated loopback origin without a path"
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise ConfigurationError("Invalid API port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("Invalid API port")
    return value.rstrip("/")


def model_origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
        raise ConfigurationError("Model base_url must not contain credentials, query, or fragment")
    if parts.scheme != "https":
        local_origin(f"{parts.scheme}://{parts.netloc}")
    return value.rstrip("/")


class JsonHttp:
    def __init__(self, *, timeout: int = 20, max_bytes: int = 32 * 1024 * 1024):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, url: str, *, headers: dict | None = None, body: dict | None = None):
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(
            url,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    raise TransportError("HTTP response exceeds configured byte limit")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Never expose provider errors: their bodies may echo prompts or credentials.
            error = TransportError(f"HTTP request failed with status {exc.code}")
            error.status = exc.code
            raise error from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError("HTTP service unavailable or timed out") from exc
        except (ValueError, UnicodeError) as exc:
            raise TransportError("HTTP service returned invalid JSON") from exc
