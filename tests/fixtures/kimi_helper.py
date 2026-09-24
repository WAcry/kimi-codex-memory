"""Synthetic mutable Kimi installation for process/upgrade tests; no user data or models."""

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import urlsplit

installation = Path(sys.argv[1])
if "--version" in sys.argv:
    (installation / "version-probed").touch()
    raise SystemExit(23)

home = Path(os.environ["KIMI_CODE_HOME"])
version = (installation / "version").read_text().strip()
started = time.time()
server_id = uuid.uuid4().hex
token = (home / "server.token").read_text().strip()
(installation / "child-auto-update").write_text(os.environ.get("KIMI_CODE_NO_AUTO_UPDATE", ""))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + token:
            self.send_error(401)
            return
        path = urlsplit(self.path).path
        if path == "/openapi.json":
            value = {
                "paths": {
                    "/api/v1/sessions": {"get": {}},
                    "/api/v1/sessions/{session_id}/transcript": {"get": {}},
                }
            }
        else:
            if path == "/api/v1/meta":
                data = {
                    "server_id": server_id,
                    "server_version": version,
                    "backend": "v2",
                    "dangerous_bypass_auth": False,
                    "started_at": datetime.fromtimestamp(started, UTC).isoformat(),
                }
            elif path == "/api/v1/sessions":
                data = {"items": [], "has_more": False}
            elif path == "/api/v1/config":
                data = {}
            else:
                self.send_error(404)
                return
            value = {"code": 0, "data": data}
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LoopbackServer(HTTPServer):
    def server_bind(self):
        # HTTPServer's reverse-DNS lookup is irrelevant to this local fixture and
        # can stall on hosted runner DNS, outside the lifecycle being exercised.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


with LoopbackServer(("127.0.0.1", 0), Handler) as server:
    directory = home / "server/instances"
    directory.mkdir(parents=True, exist_ok=True)
    entry = directory / f"{os.getpid()}.json"
    entry.write_text(
        json.dumps(
            {
                "server_id": "registry-" + server_id,
                "pid": os.getpid(),
                "host": "127.0.0.1",
                "port": server.server_port,
                "host_version": version,
                "started_at": started * 1000,
            }
        )
    )
    server.serve_forever(poll_interval=0.01)
