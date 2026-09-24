"""Borrow a compatible Kimi server or own one short-lived loopback helper."""

import os
import signal
import subprocess
import time
from pathlib import Path

from .config import ApiConfig
from .errors import CompatibilityError, ConfigurationError, TransportError
from .files import read_bounded, read_json
from .kimi import KimiClient


def kimi_home() -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME", "~/.kimi-code")).expanduser().resolve()


def live_instances(home: Path) -> list[dict]:
    instances = []
    for path in sorted((home / "server/instances").glob("*.json")):
        try:
            data = read_json(path, 16_384)
            if not isinstance(data, dict):
                continue
            pid, port = data.get("pid"), data.get("port")
            if type(pid) is not int or pid <= 1 or type(port) is not int or not 1 <= port <= 65535:
                continue
            if data.get("host") not in {"127.0.0.1", "::1", "localhost"}:
                continue
            if not isinstance(data.get("server_id"), str):
                continue
            os.kill(pid, 0)
            instances.append(data)
        except (OSError, ValueError):
            continue
    return sorted(instances, key=lambda item: item.get("started_at", 0), reverse=True)


class ServerManager:
    def __init__(self, config: ApiConfig, *, home: Path | None = None):
        self.config = config
        self.home = home or kimi_home()
        self.child: subprocess.Popen | None = None
        self.client: KimiClient | None = None
        self.borrowed = False

    def token(self) -> str:
        path = self.home / "server.token"
        try:
            if path.stat().st_mode & 0o077:
                raise TransportError("Kimi server token file permissions must be private")
            return read_bounded(path, 8192).strip()
        except OSError as exc:
            raise TransportError("Kimi server token file is unavailable") from exc

    def installed_version(self) -> str | None:
        if not self.config.kimi_command:
            return None
        try:
            result = subprocess.run(
                [*self.config.kimi_command, "--version"],
                capture_output=True,
                timeout=10,
                check=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConfigurationError("Cannot identify the configured Kimi executable") from exc
        import re

        match = re.search(r"(?<![\w.])\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", result.stdout[:4096])
        if match is None:
            raise ConfigurationError("The configured Kimi command did not report a product version")
        return match.group()

    def _connect(self, origin: str, expected_id: str | None = None) -> KimiClient:
        client = KimiClient(origin, self.token, self.config)
        client.handshake(expected_id)
        return client

    def _connect_instance(self, item: dict) -> KimiClient:
        host = item["host"]
        host = f"[{host}]" if ":" in host else host
        client = self._connect(f"http://{host}:{item['port']}")
        # Native registry server_id and /meta server_id are independently generated.
        # The registry is written before listen(); a busy candidate port may still
        # belong to an older peer while this child is booting. Check its boot time.
        if client.started_at < item.get("started_at", 0) / 1000 - 0.001:
            raise TransportError("Registered Kimi instance has not bound its listener yet")
        if item.get("host_version") and item["host_version"] != client.server_version:
            raise CompatibilityError("Registered and responding Kimi product versions differ")
        if not any(
            current["server_id"] == item["server_id"]
            and current["pid"] == item["pid"]
            and current["port"] == item["port"]
            for current in live_instances(self.home)
        ):
            raise TransportError("Kimi registration changed during connection")
        return client

    def connect(self) -> KimiClient:
        if self.config.server_url:
            self.client = self._connect(self.config.server_url)
            self.borrowed = True
            return self.client
        desired = self.installed_version()
        rejected = False
        for item in live_instances(self.home):
            if desired and item.get("host_version") != desired:
                continue
            try:
                self.client = self._connect_instance(item)
                self.borrowed = True
                return self.client
            except CompatibilityError:
                rejected = True
            except (TransportError, ConfigurationError):
                continue
        if not self.config.auto_start:
            if rejected:
                raise CompatibilityError("No compatible existing Kimi server")
            raise TransportError("No reachable Kimi server and helper auto-start is disabled")
        if not self.config.kimi_command:
            raise ConfigurationError("Set api.kimi_command or api.server_url in worker.toml")
        if desired not in self.config.allowed_versions and not self.config.allow_unverified_version:
            raise CompatibilityError("Installed Kimi version is unverified; helper was not started")
        env = {**os.environ, "KIMI_CODE_HOME": str(self.home), "KIMI_MEMORY_INTERNAL": "1"}
        try:
            self.child = subprocess.Popen(
                [
                    *self.config.kimi_command,
                    "web",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.config.port),
                    "--no-open",
                    "--web-title",
                    "Kimi Memory Helper",
                ],
                env=env,
                cwd=self.home,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            deadline = time.monotonic() + self.config.startup_timeout_seconds
            while time.monotonic() < deadline:
                if self.child.poll() is not None:
                    raise TransportError("Kimi helper exited before becoming ready")
                for item in live_instances(self.home):
                    if item["pid"] != self.child.pid:
                        continue
                    try:
                        client = self._connect_instance(item)
                        if desired and client.server_version != desired:
                            raise CompatibilityError(
                                "Kimi installation changed while starting the helper"
                            )
                        self.client = client
                        return client
                    except TransportError:
                        pass
                time.sleep(0.1)
            raise TransportError("Kimi helper startup timed out")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        child, self.child = self.child, None
        if child is None or child.poll() is not None:
            return
        # Only this Popen handle owns this new process group; never stop a borrowed server.
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()
