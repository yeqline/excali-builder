import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from excali_builder.serve.layout import save_viewer_layout
from excali_builder.serve.server import QuietThreadingHTTPServer, ServeState
from excali_builder.serve.watcher import FolderWatchState


SERVE_STATIC_DIR = Path(__file__).resolve().parents[1] / "excali_builder" / "serve" / "static"


def _write_scene(folder: Path) -> None:
    (folder / "output.excalidraw").write_text(
        json.dumps(
            {
                "type": "excalidraw",
                "version": 2,
                "source": "test",
                "elements": [
                    {
                        "id": "shape-known",
                        "type": "rectangle",
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 50,
                        "customData": {"node_id": "known"},
                    },
                    {
                        "id": "text-known",
                        "type": "text",
                        "x": 15,
                        "y": 25,
                        "width": 90,
                        "height": 40,
                        "text": "Known\nBody",
                        "originalText": "Known\nBody",
                        "textAlign": "center",
                        "verticalAlign": "top",
                        "fontSize": 14,
                        "customData": {"node_id": "known"},
                    },
                    {
                        "id": "arrow",
                        "type": "arrow",
                        "x": 0,
                        "y": 0,
                        "width": 10,
                        "height": 10,
                    },
                ],
                "appState": {},
                "files": {},
            }
        ),
        encoding="utf-8",
    )


class ServeLayoutTests(unittest.TestCase):
    def test_save_viewer_layout_persists_known_node_layout_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_scene(folder)

            positions = save_viewer_layout(
                folder,
                [
                    {
                        "id": "shape-known",
                        "type": "rectangle",
                        "x": 120,
                        "y": 140,
                        "width": 220,
                        "height": 90,
                        "strokeColor": "#ff0000",
                        "customData": {"node_id": "known"},
                    },
                    {
                        "id": "text-known",
                        "type": "text",
                        "x": 130,
                        "y": 150,
                        "width": 180,
                        "height": 55,
                        "text": "Known\nBody",
                        "originalText": "Known\nBody",
                        "textAlign": "left",
                        "verticalAlign": "middle",
                        "fontSize": 18,
                        "customData": {"node_id": "known"},
                    },
                    {
                        "id": "shape-new",
                        "type": "rectangle",
                        "x": 500,
                        "y": 500,
                        "width": 100,
                        "height": 100,
                        "customData": {"node_id": "new-node"},
                    },
                    {
                        "id": "arrow",
                        "type": "arrow",
                        "x": 20,
                        "y": 20,
                        "width": 30,
                        "height": 30,
                        "customData": {"node_id": "known"},
                    },
                ],
            )

            saved = json.loads((folder / "positions.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(positions), ["known"])
        self.assertEqual(saved["known"]["x"], 120)
        self.assertEqual(saved["known"]["y"], 140)
        self.assertEqual(saved["known"]["width"], 220)
        self.assertEqual(saved["known"]["height"], 90)
        self.assertEqual(saved["known"]["textAlign"], "left")
        self.assertEqual(saved["known"]["verticalAlign"], "middle")
        self.assertEqual(saved["known"]["fontSize"], 18)
        self.assertEqual(saved["known"]["text_x"], 130)
        self.assertEqual(saved["known"]["text_y"], 150)
        self.assertEqual(saved["known"]["text_width"], 180)
        self.assertEqual(saved["known"]["text_height"], 55)
        self.assertEqual(saved["known"]["wrapped_text"], "Known\nBody")
        self.assertNotIn("new-node", saved)
        self.assertNotIn("strokeColor", saved["known"])

    def test_save_viewer_layout_ignores_text_content_edits_for_wrapped_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_scene(folder)

            positions = save_viewer_layout(
                folder,
                [
                    {
                        "id": "shape-known",
                        "type": "rectangle",
                        "x": 120,
                        "y": 140,
                        "width": 220,
                        "height": 90,
                        "customData": {"node_id": "known"},
                    },
                    {
                        "id": "text-known",
                        "type": "text",
                        "x": 130,
                        "y": 150,
                        "width": 180,
                        "height": 55,
                        "text": "Edited title",
                        "originalText": "Edited title",
                        "textAlign": "right",
                        "verticalAlign": "bottom",
                        "customData": {"node_id": "known"},
                    },
                ],
            )

        self.assertEqual(sorted(positions), ["known"])
        self.assertEqual(positions["known"]["textAlign"], "right")
        self.assertEqual(positions["known"]["verticalAlign"], "bottom")
        self.assertNotIn("wrapped_text", positions["known"])
        self.assertNotIn("wrapped_original_text", positions["known"])

    def test_save_viewer_layout_ignores_deleted_nodes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_scene(folder)
            (folder / "positions.json").write_text(
                json.dumps(
                    {
                        "known": {
                            "x": 10,
                            "y": 20,
                            "width": 100,
                            "height": 50,
                        }
                    }
                ),
                encoding="utf-8",
            )

            positions = save_viewer_layout(
                folder,
                [
                    {
                        "id": "shape-known",
                        "type": "rectangle",
                        "isDeleted": True,
                        "x": 120,
                        "y": 140,
                        "width": 220,
                        "height": 90,
                        "customData": {"node_id": "known"},
                    }
                ],
            )
            saved = json.loads((folder / "positions.json").read_text(encoding="utf-8"))

        self.assertEqual(positions, {})
        self.assertEqual(saved["known"]["x"], 10)

    def test_layout_save_rebuilds_output_without_requesting_a_scene_reload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_scene(folder)
            state = ServeState(folder=folder, poll_interval=1.0)
            state.builder = MagicMock()
            subscriber = state.subscribe()

            result = state.save_layout(
                {
                    "elements": [
                        {
                            "id": "shape-known",
                            "type": "rectangle",
                            "x": 120,
                            "y": 140,
                            "width": 220,
                            "height": 90,
                            "customData": {"node_id": "known"},
                        },
                        {
                            "id": "text-known",
                            "type": "text",
                            "x": 130,
                            "y": 150,
                            "width": 180,
                            "height": 55,
                            "text": "Known\nBody",
                            "originalText": "Known\nBody",
                            "textAlign": "center",
                            "verticalAlign": "top",
                            "fontSize": 14,
                            "customData": {"node_id": "known"},
                        },
                    ]
                }
            )
            messages = []
            while not subscriber.empty():
                messages.append(subscriber.get_nowait())

        state.builder.build_from_folder.assert_called_once_with(
            str(folder),
            placement_context=None,
        )
        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(
            [message["type"] for message in messages],
            ["saving-layout", "layout-saved"],
        )
        self.assertNotIn(
            {"type": "built", "reason": "layout"},
            messages,
        )

    def test_source_and_external_output_changes_still_request_a_scene_reload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_scene(folder)
            state = ServeState(folder=folder, poll_interval=1.0)
            state.builder = MagicMock()
            state.builder.build_from_folder.return_value = str(
                folder / "output.excalidraw"
            )
            subscriber = state.subscribe()

            state._build(reason="source", sync_first=True)
            state.sync_external_output()
            messages = []
            while not subscriber.empty():
                messages.append(subscriber.get_nowait())

        self.assertIn({"type": "built", "reason": "source"}, messages)
        self.assertIn({"type": "built", "reason": "external-output"}, messages)


class WatcherTests(unittest.TestCase):
    def test_watcher_ignores_recorded_internal_output_write_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            output_path = folder / "output.excalidraw"
            output_path.write_text("initial", encoding="utf-8")
            watch_state = FolderWatchState(folder)

            output_path.write_text("internal write", encoding="utf-8")
            watch_state.mark_internal_write(output_path)
            internal_changes = watch_state.collect_changes()

            output_path.write_text("external write", encoding="utf-8")
            external_changes = watch_state.collect_changes()

        self.assertFalse(internal_changes.has_changes)
        self.assertTrue(external_changes.output_changed)
        self.assertEqual(external_changes.source_paths, [])


class PlacementContextTests(unittest.TestCase):
    def test_recent_pointer_precedes_viewport_and_then_expires(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = ServeState(folder=Path(tmp_dir), poll_interval=1.0)
            with patch(
                "excali_builder.serve.server.time.monotonic",
                return_value=100.0,
            ):
                state.update_placement_context(
                    {
                        "pointer": {"x": 10, "y": 20},
                        "viewport_center": {"x": 300, "y": 400},
                    }
                )
            with patch(
                "excali_builder.serve.server.time.monotonic",
                return_value=105.0,
            ):
                recent_anchor = state.get_placement_anchor()
            with patch(
                "excali_builder.serve.server.time.monotonic",
                return_value=111.0,
            ):
                expired_anchor = state.get_placement_anchor()

        self.assertEqual(recent_anchor, {"x": 10.0, "y": 20.0})
        self.assertEqual(expired_anchor, {"x": 300.0, "y": 400.0})

    def test_placement_context_rejects_non_finite_points(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = ServeState(folder=Path(tmp_dir), poll_interval=1.0)
            with self.assertRaisesRegex(ValueError, "finite x and y"):
                state.update_placement_context(
                    {"viewport_center": {"x": float("nan"), "y": 20}}
                )


class QuietServerTests(unittest.TestCase):
    def test_client_disconnect_does_not_print_traceback(self):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), object)
        stderr = io.StringIO()

        try:
            with redirect_stderr(stderr):
                try:
                    raise ConnectionResetError("browser closed preconnect")
                except ConnectionResetError:
                    server.handle_error(None, ("127.0.0.1", 12345))
        finally:
            server.server_close()

        self.assertEqual(stderr.getvalue(), "")

    def test_unexpected_handler_error_still_prints_traceback(self):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), object)
        stderr = io.StringIO()

        try:
            with redirect_stderr(stderr):
                try:
                    raise RuntimeError("real handler failure")
                except RuntimeError:
                    server.handle_error(None, ("127.0.0.1", 12345))
        finally:
            server.server_close()

        self.assertIn("RuntimeError: real handler failure", stderr.getvalue())


class StaticViewerTests(unittest.TestCase):
    def test_viewer_declares_svg_favicon(self):
        index_html = (SERVE_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        favicon = (SERVE_STATIC_DIR / "favicon.svg").read_text(encoding="utf-8")

        self.assertIn(
            '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />',
            index_html,
        )
        self.assertIn('stroke="#2563EB"', favicon)
        self.assertIn("M10 32h38", favicon)

    def test_viewer_uses_excalidraw_browser_import_paths(self):
        index_html = (SERVE_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        viewer_js = (SERVE_STATIC_DIR / "viewer.js").read_text(encoding="utf-8")

        self.assertIn(
            "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/prod/index.css",
            index_html,
        )
        self.assertIn('"react": "https://esm.sh/react@18.2.0"', index_html)
        self.assertIn('"react-dom/client": "https://esm.sh/react-dom@18.2.0/client"', index_html)
        self.assertIn(
            "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/prod/index.js"
            "?external=react,react-dom",
            viewer_js,
        )
        self.assertNotIn("/dist/dev/", index_html)
        self.assertNotIn("/dist/dev/", viewer_js)
        self.assertNotIn("@excalidraw/excalidraw@0.18.0/index.css", index_html)
        self.assertIn('fetch("/placement-context"', viewer_js)
        self.assertIn("onPointerUpdate: handlePointerUpdate", viewer_js)
        self.assertIn("onPointerDown: handleCanvasPointer", viewer_js)
        self.assertIn("onPointerMove: handleCanvasPointer", viewer_js)
        self.assertIn("onScrollChange: handleScrollChange", viewer_js)
        self.assertIn("onWheelCapture: handleCanvasWheel", viewer_js)
        self.assertIn("event.shiftKey", viewer_js)
        self.assertIn("event.ctrlKey", viewer_js)
        self.assertIn("event.metaKey", viewer_js)
        self.assertIn("zoom: { value: nextZoom }", viewer_js)


if __name__ == "__main__":
    unittest.main()
