from __future__ import annotations

import json
import threading
from uuid import uuid4
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from apm_bridge.core import CONNECTORS, create_pack, validate_pack

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def stage_dropped_source(*, destination: Path, name: str, content: str) -> Path:
    filename = Path(name).name
    if not filename.lower().endswith(".md"):
        raise ValueError("drop a Markdown source file such as SKILL.md, AGENTS.md, or agent.md")
    if not content.strip():
        raise ValueError("dropped source file is empty")
    if len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("dropped source file exceeds the 1 MB local Studio limit")
    imports = destination.resolve() / ".studio-imports"
    imports.mkdir(parents=True, exist_ok=True)
    source = imports / f"{uuid4().hex}-{filename}"
    source.write_text(content, encoding="utf-8")
    return source


class StudioHandler(SimpleHTTPRequestHandler):
    output = Path("./apm-workspace")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _json(self, status: HTTPStatus, body: dict) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/api/catalog":
            self._json(HTTPStatus.OK, {"connectors": CONNECTORS})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route not in {"/api/create", "/api/import"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if route == "/api/import":
                source = stage_dropped_source(
                    destination=self.output,
                    name=str(payload["name"]),
                    content=str(payload["content"]),
                )
                self._json(HTTPStatus.OK, {"ok": True, "source": str(source), "name": source.name})
                return
            source = Path(payload["source"]).expanduser() if payload.get("source") else None
            pack = create_pack(
                destination=self.output,
                name=str(payload["name"]),
                purpose=str(payload["purpose"]),
                model=str(payload["model"]),
                connectors=list(payload["connectors"]),
                source=source,
            )
            result = validate_pack(pack)
            self._json(
                HTTPStatus.OK if result.ok else HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "ok": result.ok,
                    "messages": result.messages,
                    "pack": str(pack),
                    "artifact": str(result.artifact) if result.artifact else None,
                },
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})


def run_studio(*, host: str, port: int, output: Path, open_browser: bool) -> None:
    StudioHandler.output = output.resolve()
    server = ThreadingHTTPServer((host, port), StudioHandler)
    url = f"http://{host}:{port}"
    print(f"APM Studio: {url}")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPM Studio stopped.")
    finally:
        server.server_close()
