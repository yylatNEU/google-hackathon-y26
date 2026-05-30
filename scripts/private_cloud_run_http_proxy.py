#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar


try:
    import certifi
except Exception:  # pragma: no cover - depends on local Python install
    certifi = None


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class TokenCache:
    token: str | None = None
    expires_at: float = 0

    @classmethod
    def get(cls) -> str:
        now = time.time()
        if cls.token and now < cls.expires_at:
            return cls.token
        cls.token = subprocess.check_output(["gcloud", "auth", "print-identity-token"], text=True).strip()
        cls.expires_at = now + 45 * 60
        return cls.token


def ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl._create_unverified_context()


class CloudRunProxy(BaseHTTPRequestHandler):
    cloud_run_url: ClassVar[str]

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def do_PUT(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", self.headers.get("Access-Control-Request-Headers", "*"))

    def _proxy(self) -> None:
        target = urllib.parse.urljoin(self.cloud_run_url.rstrip("/") + "/", self.path.lstrip("/"))
        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            body = self.rfile.read(int(content_length))

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {"host", "authorization"}
        }
        headers["Authorization"] = f"Bearer {TokenCache.get()}"

        request = urllib.request.Request(target, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(request, timeout=120, context=ssl_context()) as response:
                payload = response.read()
                self.send_response(response.status)
                self._send_cors_headers()
                for key, value in response.headers.items():
                    if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {"content-length"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    return
        except urllib.error.HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            self._send_cors_headers()
            for key, value in error.headers.items():
                if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {"content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return
        except Exception as error:
            payload = json.dumps({"error": str(error)}).encode("utf-8")
            self.send_response(502)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return


def resolve_cloud_run_url(project: str, region: str, service: str) -> str:
    return subprocess.check_output(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            "--project",
            project,
            "--region",
            region,
            "--format=value(status.url)",
        ],
        text=True,
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local authenticated proxy for a private Cloud Run service.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service", default="parkpulse-private-api")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--url", default="")
    args = parser.parse_args()

    CloudRunProxy.cloud_run_url = args.url or resolve_cloud_run_url(args.project, args.region, args.service)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), CloudRunProxy)
    server.daemon_threads = True
    print(f"Proxying http://127.0.0.1:{args.port} to {CloudRunProxy.cloud_run_url}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
