import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from excali_builder.serve.layout import save_viewer_layout
from excali_builder.serve.server import QuietThreadingHTTPServer
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
            "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/dev/index.css",
            index_html,
        )
        self.assertIn('"react": "https://esm.sh/react@18.2.0"', index_html)
        self.assertIn('"react-dom/client": "https://esm.sh/react-dom@18.2.0/client"', index_html)
        self.assertIn(
            "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/dev/index.js"
            "?external=react,react-dom",
            viewer_js,
        )
        self.assertNotIn("@excalidraw/excalidraw@0.18.0/index.css", index_html)


if __name__ == "__main__":
    unittest.main()
