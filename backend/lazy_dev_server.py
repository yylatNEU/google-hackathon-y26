from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from env_bootstrap import load_backend_env


load_backend_env()

from main import app


_ASGI_LOOP: asyncio.AbstractEventLoop | None = None
_ASGI_LOOP_THREAD: threading.Thread | None = None


def _asgi_loop() -> asyncio.AbstractEventLoop:
    global _ASGI_LOOP, _ASGI_LOOP_THREAD
    if _ASGI_LOOP is None:
        _ASGI_LOOP = asyncio.new_event_loop()
        _ASGI_LOOP_THREAD = threading.Thread(target=_ASGI_LOOP.run_forever, name="parkpulse-asgi-loop", daemon=True)
        _ASGI_LOOP_THREAD.start()
    return _ASGI_LOOP


class LazyThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LazyAsgiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:
        self._run_asgi()

    def do_GET(self) -> None:
        self._run_asgi()

    def do_POST(self) -> None:
        self._run_asgi()

    def do_PUT(self) -> None:
        self._run_asgi()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _run_asgi(self) -> None:
        parsed = urlsplit(self.path)
        body = self.rfile.read(int(self.headers.get("content-length", "0") or 0))
        messages = [
            {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        ]
        response: dict[str, Any] = {"status": 500, "headers": [], "body": bytearray()}
        stream_started = False

        async def receive() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal stream_started
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                response["headers"] = message.get("headers", [])
                content_type = next(
                    (
                        value.decode("latin-1") if isinstance(value, bytes) else str(value)
                        for key, value in response["headers"]
                        if (key.decode("latin-1") if isinstance(key, bytes) else str(key)).lower() == "content-type"
                    ),
                    "",
                )
                if "text/event-stream" in content_type:
                    self.send_response(int(response["status"]))
                    for key, value in response["headers"]:
                        header = key.decode("latin-1") if isinstance(key, bytes) else str(key)
                        if header.lower() == "content-length":
                            continue
                        header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                        self.send_header(header, header_value)
                    self.end_headers()
                    stream_started = True
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if stream_started:
                    if body:
                        try:
                            self.wfile.write(body)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            return
                else:
                    response["body"].extend(body)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self.command,
            "scheme": "http",
            "path": parsed.path,
            "raw_path": parsed.path.encode("utf-8"),
            "query_string": parsed.query.encode("utf-8"),
            "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in self.headers.items()],
            "client": self.client_address,
            "server": self.server.server_address,
        }

        try:
            future = asyncio.run_coroutine_threadsafe(app(scope, receive, send), _asgi_loop())
            future.result()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            if stream_started:
                error_body = f"event: run.error\ndata: {json.dumps({'message': str(error)})}\n\n".encode("utf-8")
                try:
                    self.wfile.write(error_body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            response = {"status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")], "body": bytearray(str(error).encode("utf-8"))}

        if stream_started:
            return

        body_bytes = bytes(response["body"])
        try:
            self.send_response(int(response["status"]))
            sent_content_length = False
            for key, value in response["headers"]:
                header = key.decode("latin-1") if isinstance(key, bytes) else str(key)
                header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                if header.lower() == "content-length":
                    sent_content_length = True
                self.send_header(header, header_value)
            if not sent_content_length:
                self.send_header("content-length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    try:
        import uvicorn

        uvicorn.run(app, host=host, port=port, log_level="info")
        return
    except Exception as error:
        print(f"uvicorn startup failed, falling back to lazy ASGI bridge: {error}")
    server = LazyThreadingHTTPServer((host, port), LazyAsgiHandler)
    print(f"ParkPulse lazy dev server running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
