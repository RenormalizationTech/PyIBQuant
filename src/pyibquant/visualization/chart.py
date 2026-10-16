"""HTML export and a localhost-only, read-only live chart server."""

from __future__ import annotations

import json
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

from ..bars import BarSeries
from ..errors import PyIBQuantError


def render_chart(
    series: BarSeries,
    *,
    live_endpoint: bool = False,
    controls: bool = False,
    history: bool = False,
    selection_id: str | None = None,
) -> str:
    payload = series.payload()
    payload["selection_id"] = selection_id
    if not live_endpoint:
        payload["live"] = False
        payload["status"] = (
            f"Historical snapshot (cached {series.cache_created_at})"
            if series.cache_hit else "Historical snapshot"
        )
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
    script = script.replace("__HISTORY_ENABLED__", "true" if history else "false")
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
        loader: Callable[[str, str, str, bool], BarSeries] | None,
        cancel: Callable[[BarSeries], None] | None,
        history_loader: Callable[[BarSeries], int] | None = None,
    ) -> None:
        self.series = series
        self.loader = loader
        self.cancel = cancel
        self._selection_lock = Lock()
        self._state_lock = Lock()
        self.selection_id = uuid4().hex
        self.history_loader = history_loader
        self._history_at = float("-inf")

    def payload(self) -> dict:
        with self._state_lock:
            return {**self.series.payload(), "selection_id": self.selection_id}

    def select(
        self, symbol: str, interval: str, duration: str, regular_hours: bool | None = None
    ) -> dict:
        if regular_hours is not None and not isinstance(regular_hours, bool):
            raise ValueError("Trading hours must be a boolean regular_hours value.")
        if self.loader is None:
            raise ValueError("Symbol selection requires a connected Market chart server.")
        if not self._selection_lock.acquire(blocking=False):
            raise BlockingIOError("Another chart is loading. Please wait.")
        try:
            hours = self.series.regular_hours if regular_hours is None else regular_hours
            replacement = self.loader(symbol, interval, duration, hours)
            with self._state_lock:
                previous = self.series
                self.series = replacement
                self.selection_id = uuid4().hex
                self._history_at = float("-inf")
            if self.cancel is not None:
                self.cancel(previous)
            return self.payload()
        finally:
            self._selection_lock.release()

    def older(self, selection_id: str, before: int | str) -> dict:
        if self.history_loader is None:
            raise ValueError("Older history requires a connected Market chart server.")
        if not self._selection_lock.acquire(blocking=False):
            raise BlockingIOError("Another chart request is in progress; retry shortly.")
        try:
            if selection_id != self.selection_id:
                raise BlockingIOError("The active chart changed; wait for it to refresh.")
            bars = self.series.snapshot()
            # Another tab may already have fetched this boundary. Return its result.
            if not bars or before != bars[0].chart_data()["time"] or self.series.history_exhausted:
                return self.payload()
            now = monotonic()
            if now - self._history_at < 2:
                raise BlockingIOError("Wait two seconds before requesting more history.")
            self._history_at = now
            self.history_loader(self.series)
            return self.payload()
        finally:
            self._selection_lock.release()


def serve_chart(
    series: BarSeries,
    *,
    port: int = 0,
    open_browser: bool = True,
    loader: Callable[[str, str, str, bool], BarSeries] | None = None,
    cancel: Callable[[BarSeries], None] | None = None,
    history_loader: Callable[[BarSeries], int] | None = None,
) -> None:
    session = ChartSession(series, loader, cancel, history_loader)

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
                with session._state_lock:
                    active = session.series
                    body = render_chart(
                        active,
                        live_endpoint=active.live,
                        controls=loader is not None,
                        history=history_loader is not None,
                        selection_id=session.selection_id,
                    ).encode()
                self.respond(body, "text/html; charset=utf-8")
            elif self.path == "/data":
                self.json_response(session.payload())
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path not in {"/chart", "/older"}:
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
                if self.path == "/older":
                    selection_id, before = payload.get("selection_id"), payload.get("before")
                    if (
                        not isinstance(selection_id, str) or not selection_id
                        or not isinstance(before, str | int) or isinstance(before, bool)
                    ):
                        raise ValueError("Chart selection and earliest bar timestamp are required.")
                    self.json_response(session.older(selection_id, before))
                    return
                fields = [payload.get(key) for key in ("symbol", "interval", "duration")]
                if not all(isinstance(value, str) and value.strip() for value in fields):
                    raise ValueError("Symbol, interval and duration are required.")
                hours = payload.get("regular_hours")
                if "regular_hours" in payload and not isinstance(hours, bool):
                    raise ValueError("Trading hours must be a boolean regular_hours value.")
                self.json_response(session.select(
                    str(fields[0]), str(fields[1]), str(fields[2]), regular_hours=hours
                ))
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
