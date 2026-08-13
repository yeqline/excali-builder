"""Local HTTP server for auto-refreshing Excalidraw diagrams."""

import json
import math
import mimetypes
import queue
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..builder import ExcaliBuilder
from ..parsers.dbt import get_dbt_input_paths
from .layout import save_viewer_layout
from .watcher import FolderWatchState


MAX_LAYOUT_POST_BYTES = 25 * 1024 * 1024
PLACEMENT_POINTER_MAX_AGE_SECONDS = 10.0
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server that ignores expected browser disconnect noise."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc_type, _exc, _tb = sys.exc_info()
        if exc_type is not None and issubclass(exc_type, CLIENT_DISCONNECT_ERRORS):
            return
        super().handle_error(request, client_address)


class ServeState:
    """Mutable state shared by HTTP handlers and the watcher thread."""

    def __init__(self, folder: Path, poll_interval: float):
        self.folder = folder
        self.poll_interval = poll_interval
        self.builder = ExcaliBuilder()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.watch_state: Optional[FolderWatchState] = None
        self._subscribers = []
        self._watch_thread: Optional[threading.Thread] = None
        self._pointer: Optional[Dict[str, float]] = None
        self._pointer_updated_at: Optional[float] = None
        self._viewport_center: Optional[Dict[str, float]] = None

    @property
    def output_path(self) -> Path:
        return self.folder / "output.excalidraw"

    def initial_build(self) -> None:
        """Run the same sync-then-build sequence as the normal CLI."""
        self._build(reason="initial", sync_first=True)
        self.watch_state = FolderWatchState(
            self.folder,
            extra_paths=self._get_extra_watch_paths(),
        )

    def start_watcher(self) -> None:
        """Start the background polling watcher."""
        if self.watch_state is None:
            self.watch_state = FolderWatchState(self.folder)
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="excali-builder-serve-watch",
            daemon=True,
        )
        self._watch_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2)

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        subscriber: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: "queue.Queue[Dict[str, Any]]") -> None:
        try:
            self._subscribers.remove(subscriber)
        except ValueError:
            pass

    def notify(self, message: Dict[str, Any]) -> None:
        stale = []
        for subscriber in list(self._subscribers):
            try:
                subscriber.put_nowait(message)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            self.unsubscribe(subscriber)

    def save_layout(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a viewer layout update and regenerate output from source."""
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise ValueError("layout payload must include an elements array")

        self.notify({"type": "saving-layout"})
        with self.lock:
            positions = save_viewer_layout(self.folder, elements)
            if positions:
                self.builder.build_from_folder(
                    str(self.folder),
                    placement_context=self.get_placement_anchor(),
                )
                if self.watch_state is not None:
                    self.watch_state.set_extra_paths(self._get_extra_watch_paths())
                    self.watch_state.mark_internal_write(self.output_path)
                    self.watch_state.refresh()

        result = {
            "type": "layout-saved",
            "saved_nodes": sorted(positions),
            "saved_count": len(positions),
        }
        self.notify(result)
        if positions:
            self.notify({"type": "built", "reason": "layout"})
        return result

    def update_placement_context(self, payload: Dict[str, Any]) -> None:
        """Keep transient cursor and viewport anchors for placing new nodes."""
        pointer = _optional_point(payload.get("pointer"), "pointer")
        viewport_center = _optional_point(
            payload.get("viewport_center"),
            "viewport_center",
        )
        if pointer is None and viewport_center is None:
            raise ValueError(
                "placement context must include pointer or viewport_center"
            )

        with self.lock:
            if pointer is not None:
                self._pointer = pointer
                self._pointer_updated_at = time.monotonic()
            if viewport_center is not None:
                self._viewport_center = viewport_center

    def get_placement_anchor(self) -> Optional[Dict[str, float]]:
        """Return a recent cursor or the current viewport center."""
        with self.lock:
            if (
                self._pointer is not None
                and self._pointer_updated_at is not None
                and time.monotonic() - self._pointer_updated_at
                <= PLACEMENT_POINTER_MAX_AGE_SECONDS
            ):
                return dict(self._pointer)
            if self._viewport_center is not None:
                return dict(self._viewport_center)
        return None

    def sync_external_output(self) -> None:
        """Sync positions from an externally saved output.excalidraw file."""
        with self.lock:
            self.builder.sync_from_folder(str(self.folder))
        self.notify({"type": "built", "reason": "external-output"})

    def _build(self, reason: str, sync_first: bool) -> None:
        self.notify({"type": "rebuilding", "reason": reason})
        with self.lock:
            if sync_first:
                self.builder.sync_from_folder(str(self.folder))
            output_path = Path(
                self.builder.build_from_folder(
                    str(self.folder),
                    placement_context=self.get_placement_anchor(),
                )
            )
            if self.watch_state is not None:
                self.watch_state.set_extra_paths(self._get_extra_watch_paths())
                self.watch_state.mark_internal_write(output_path)
                self.watch_state.refresh()
        self.notify({"type": "built", "reason": reason})

    def _get_extra_watch_paths(self) -> List[Path]:
        config_path = self.folder / "config.json"
        if not config_path.exists():
            return []

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        if config.get("parser_type") != "dbt":
            return []

        parser_options = config.get("parser_options", {})
        if not isinstance(parser_options, dict):
            return []
        try:
            return get_dbt_input_paths(self.folder, parser_options)
        except ValueError:
            return []

    def _watch_loop(self) -> None:
        while not self.stop_event.wait(self.poll_interval):
            if self.watch_state is None:
                continue
            changes = self.watch_state.collect_changes()
            if not changes.has_changes:
                continue

            try:
                if changes.source_paths:
                    self._build(reason="source", sync_first=True)
                elif changes.output_changed:
                    self.sync_external_output()
            except Exception as exc:
                self.notify({"type": "error", "message": str(exc)})
                traceback.print_exc(file=sys.stderr)


def serve_folder(
    folder: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    poll_interval: float = 1.0,
    open_browser: bool = True,
) -> None:
    """Run the local viewer server until interrupted."""
    state = ServeState(folder=folder, poll_interval=poll_interval)
    state.initial_build()

    handler_class = _make_handler(state)
    httpd = QuietThreadingHTTPServer((host, port), handler_class)
    actual_port = httpd.server_address[1]
    display_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    url = f"http://{display_host}:{actual_port}/"

    state.start_watcher()

    print(f"Serving {folder}", flush=True)
    print(f"Viewer: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        state.stop()
        httpd.server_close()


def _make_handler(state: ServeState):
    static_root = Path(__file__).parent / "static"

    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_static(static_root / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/diagram":
                self._serve_diagram()
                return
            if parsed.path == "/events":
                self._serve_events()
                return
            if parsed.path.startswith("/static/"):
                relative_path = parsed.path[len("/static/"):]
                self._serve_static(static_root / relative_path)
                return
            if parsed.path == "/health":
                self._send_json({"ok": True})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in {"/layout", "/placement-context"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            try:
                payload = self._read_json_body()
                if parsed.path == "/placement-context":
                    state.update_placement_context(payload)
                    result = {"ok": True}
                else:
                    result = state.save_layout(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:
                state.notify({"type": "error", "message": str(exc)})
                traceback.print_exc(file=sys.stderr)
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._send_json(result)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _serve_diagram(self) -> None:
            if not state.output_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "output.excalidraw has not been built")
                return
            self._serve_static(state.output_path, "application/json; charset=utf-8")

        def _serve_static(self, path: Path, content_type: Optional[str] = None) -> None:
            try:
                resolved = path.resolve()
                is_static = _is_relative_to(resolved, static_root.resolve())
                is_diagram = resolved == state.output_path.resolve()
                if not is_static and not is_diagram:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                data = resolved.read_bytes()
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            if content_type is None:
                content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_events(self) -> None:
            subscriber = state.subscribe()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            try:
                while not state.stop_event.is_set():
                    try:
                        message = subscriber.get(timeout=15)
                        payload = json.dumps(message)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except CLIENT_DISCONNECT_ERRORS:
                pass
            finally:
                state.unsubscribe(subscriber)

        def _read_json_body(self) -> Dict[str, Any]:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length > MAX_LAYOUT_POST_BYTES:
                raise ValueError("layout payload is too large")
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON payload") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            return payload

        def _send_json(self, payload: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return ViewerHandler


def _optional_point(value: Any, field_name: str) -> Optional[Dict[str, float]]:
    """Validate an optional finite two-dimensional point."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    x = value.get("x")
    y = value.get("y")
    if not _is_finite_number(x) or not _is_finite_number(y):
        raise ValueError(f"{field_name} must include finite x and y values")
    return {"x": float(x), "y": float(y)}


def _is_finite_number(value: Any) -> bool:
    """Return whether a value is a finite JSON number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
