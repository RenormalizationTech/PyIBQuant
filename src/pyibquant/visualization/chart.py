"""HTML export and a localhost-only, read-only live chart server."""

from __future__ import annotations

import json
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Lock

from ..bars import BarSeries
from ..errors import PyIBQuantError


def render_chart(series: BarSeries, *, live_endpoint: bool = False, controls: bool = False) -> str:
    payload = series.payload()
    if not live_endpoint:
        payload["live"] = False
        payload["status"] = "Historical snapshot"
    # JSON is embedded in a script element; escape HTML delimiters even in error text.
    data = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    resources = files("pyibquant.visualization")
    template = resources.joinpath("chart.html").read_text()
    script = (
        resources.joinpath("chart.js")
        .read_text()
        .replace("__LIVE_ENDPOINT__", "true" if live_endpoint else "false")
    )
    script = script.replace("__CONTROLS_ENABLED__", "true" if controls else "false")
    return template.replace("__CHART_SCRIPT__", script).replace("__CHART_DATA__", data)


def write_chart(series: BarSeries, path: str | Path, *, open_browser: bool = True) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_chart(series), encoding="utf-8")
    if open_browser:
        webbrowser.open(target.as_uri())
    return target


class ChartSession:
    """One active chart, with serialized requests and atomic replacement on success."""

    def __init__(
        self,
        series: BarSeries,
        loader: Callable[[str, str, str], BarSeries] | None,
        cancel: Callable[[BarSeries], None] | None,
    ) -> None:
        self.series = series
        self.loader = loader
        self.cancel = cancel
        self._selection_lock = Lock()

    def select(self, symbol: str, interval: str, duration: str) -> dict:
        if self.loader is None:
            raise ValueError("Symbol selection requires a connected Market chart server.")
        if not self._selection_lock.acquire(blocking=False):
            raise BlockingIOError("Another chart is loading. Please wait.")
        try:
            replacement = self.loader(symbol, interval, duration)
            previous = self.series
            self.series = replacement
            if self.cancel is not None:
                self.cancel(previous)
            return replacement.payload()
        finally:
            self._selection_lock.release()


def serve_chart(
    series: BarSeries,
    *,
    port: int = 0,
    open_browser: bool = True,
    loader: Callable[[str, str, str], BarSeries] | None = None,
    cancel: Callable[[BarSeries], None] | None = None,
) -> None:
    session = ChartSession(series, loader, cancel)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, body: bytes, mime: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, payload: dict, code: int = 200) -> None:
            self.respond(json.dumps(payload, allow_nan=False).encode(), "application/json", code)

        def do_GET(self) -> None:
            if self.path == "/":
                active = session.series
                body = render_chart(
                    active, live_endpoint=active.live, controls=loader is not None
                ).encode()
                self.respond(body, "text/html; charset=utf-8")
            elif self.path == "/data":
                self.json_response(session.series.payload())
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != "/chart":
                self.send_error(404)
                return
            origin = self.headers.get("Origin")
            expected = url.rstrip("/")
            if origin not in {None, expected} or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.json_response({"error": "Request must originate from this chart page."}, 403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2048 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Expected a small JSON chart request.")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                fields = [payload.get(key) for key in ("symbol", "interval", "duration")]
                if not all(isinstance(value, str) and value.strip() for value in fields):
                    raise ValueError("Symbol, interval and duration are required.")
                self.json_response(session.select(*(str(value) for value in fields)))
            except BlockingIOError as exc:
                self.json_response({"error": str(exc)}, 409)
            except (ValueError, PyIBQuantError) as exc:
                self.json_response({"error": str(exc)}, 400)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Chart: {url} (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
