import json
import tempfile
import unittest
from pathlib import Path

from excali_builder.builder import ExcaliBuilder
from excali_builder.parsers.graph import GraphJsonParser
from excali_builder.serve.watcher import FolderWatchState


def _write_graph(folder: Path, nodes, edges) -> None:
    (folder / "graph.json").write_text(
        json.dumps({"version": 1, "nodes": nodes, "edges": edges}),
        encoding="utf-8",
    )


def _write_graph_config(folder: Path, layout=None) -> None:
    config = {"parser_type": "graph"}
    if layout is not None:
        config["layout"] = layout
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")


class GraphJsonParserTests(unittest.TestCase):
    def test_parser_preserves_declared_nodes_edges_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(
                folder,
                nodes=[
                    {
                        "id": "api",
                        "type": "service",
                        "label": "API",
                        "text": "Public interface",
                        "metadata": {"owner": "platform"},
                    },
                    {"id": "database", "type": "storage"},
                ],
                edges=[
                    {
                        "id": "api-reads-database",
                        "source": "api",
                        "target": "database",
                        "type": "reads",
                        "label": "reads from",
                        "metadata": {"protocol": "SQL"},
                    }
                ],
            )

            graph = GraphJsonParser().parse(folder, {})

            self.assertEqual(sorted(graph.nodes), ["api", "database"])
            self.assertEqual(graph.nodes["api"].metadata["text"], "Public interface")
            self.assertEqual(graph.nodes["api"].metadata["owner"], "platform")
            self.assertEqual(graph.nodes["database"].label, "database")
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.edges[0].id, "api-reads-database")
            self.assertEqual(graph.edges[0].edge_type, "reads")
            self.assertEqual(graph.edges[0].metadata["protocol"], "SQL")
            self.assertTrue((folder / "node_config.json").exists())
            self.assertTrue((folder / "edge_config.json").exists())

    def test_parser_allows_cycles_self_loops_parallel_edges_and_isolated_nodes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(
                folder,
                nodes=[
                    {"id": "a", "type": "concept"},
                    {"id": "b", "type": "concept"},
                    {"id": "isolated", "type": "concept"},
                ],
                edges=[
                    {"id": "a-b-1", "source": "a", "target": "b", "type": "calls"},
                    {"id": "a-b-2", "source": "a", "target": "b", "type": "reads"},
                    {"id": "b-a", "source": "b", "target": "a", "type": "returns"},
                    {"id": "a-self", "source": "a", "target": "a", "type": "retry"},
                ],
            )

            graph = GraphJsonParser().parse(folder, {})

        self.assertEqual(len(graph.edges), 4)
        self.assertIn("isolated", graph.nodes)

    def test_parser_rejects_duplicate_ids_dangling_edges_and_geometry(self):
        cases = [
            (
                [
                    {"id": "a", "type": "concept"},
                    {"id": "a", "type": "concept"},
                ],
                [],
                "duplicate node IDs",
            ),
            (
                [{"id": "a", "type": "concept"}],
                [
                    {
                        "id": "missing-target",
                        "source": "a",
                        "target": "missing",
                        "type": "calls",
                    }
                ],
                "unknown node references",
            ),
            (
                [{"id": "a", "type": "concept", "x": 10}],
                [],
                "Extra inputs are not permitted",
            ),
        ]

        for nodes, edges, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp_dir:
                folder = Path(tmp_dir)
                _write_graph_config(folder)
                _write_graph(folder, nodes, edges)
                with self.assertRaisesRegex(ValueError, message):
                    GraphJsonParser().parse(folder, {})


class GraphBuildTests(unittest.TestCase):
    def test_empty_graph_still_creates_required_positions_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(folder, nodes=[], edges=[])

            ExcaliBuilder().build_from_folder(str(folder))

            saved = json.loads(
                (folder / "positions.json").read_text(encoding="utf-8")
            )

        self.assertEqual(saved, {})

    def test_first_build_persists_positions_and_exports_stable_labeled_edges(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(
                folder,
                nodes=[
                    {"id": "a", "type": "concept", "label": "A"},
                    {"id": "b", "type": "concept", "label": "B"},
                    {"id": "isolated", "type": "concept", "label": "Isolated"},
                ],
                edges=[
                    {
                        "id": "a-b-calls",
                        "source": "a",
                        "target": "b",
                        "type": "calls",
                        "label": "calls",
                    },
                    {
                        "id": "a-b-reads",
                        "source": "a",
                        "target": "b",
                        "type": "reads",
                        "label": "reads",
                    },
                    {
                        "id": "a-self",
                        "source": "a",
                        "target": "a",
                        "type": "retry",
                        "label": "retry",
                    },
                ],
            )

            builder = ExcaliBuilder()
            output_path = Path(builder.build_from_folder(str(folder)))
            first_output = json.loads(output_path.read_text(encoding="utf-8"))
            first_positions = json.loads(
                (folder / "positions.json").read_text(encoding="utf-8")
            )
            builder.build_from_folder(str(folder))
            second_output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(sorted(first_positions), ["a", "b", "isolated"])
        for geometry in first_positions.values():
            self.assertTrue(
                {
                    "x",
                    "y",
                    "width",
                    "height",
                    "textAlign",
                    "verticalAlign",
                    "fontSize",
                    "text_x",
                    "text_y",
                    "text_width",
                    "text_height",
                    "wrapped_text",
                    "wrapped_original_text",
                }.issubset(geometry)
            )

        first_arrows = {
            element["customData"]["edge_id"]: element
            for element in first_output["elements"]
            if element["type"] == "arrow"
        }
        second_arrows = {
            element["customData"]["edge_id"]: element
            for element in second_output["elements"]
            if element["type"] == "arrow"
        }
        self.assertEqual(sorted(first_arrows), ["a-b-calls", "a-b-reads", "a-self"])
        self.assertEqual(
            {edge_id: arrow["id"] for edge_id, arrow in first_arrows.items()},
            {edge_id: arrow["id"] for edge_id, arrow in second_arrows.items()},
        )

        edge_labels = {
            element["customData"]["edge_id"]: element
            for element in first_output["elements"]
            if element["type"] == "text" and element.get("customData", {}).get("edge_id")
        }
        self.assertEqual(
            {edge_id: label["text"] for edge_id, label in edge_labels.items()},
            {
                "a-b-calls": "calls",
                "a-b-reads": "reads",
                "a-self": "retry",
            },
        )
        for edge_id, label in edge_labels.items():
            self.assertEqual(label["containerId"], first_arrows[edge_id]["id"])

    def test_new_nodes_use_neighbour_and_live_context_without_moving_saved_nodes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(
                folder,
                nodes=[{"id": "anchor", "type": "concept", "label": "Anchor"}],
                edges=[],
            )
            builder = ExcaliBuilder()
            builder.build_from_folder(str(folder))

            saved = json.loads((folder / "positions.json").read_text(encoding="utf-8"))
            anchor_geometry = {
                "x": 100.0,
                "y": 200.0,
                "width": saved["anchor"]["width"],
                "height": saved["anchor"]["height"],
            }
            (folder / "positions.json").write_text(
                json.dumps({"anchor": anchor_geometry}),
                encoding="utf-8",
            )
            _write_graph(
                folder,
                nodes=[
                    {"id": "anchor", "type": "concept", "label": "Anchor"},
                    {"id": "connected", "type": "concept", "label": "Connected"},
                    {"id": "loose", "type": "concept", "label": "Loose"},
                ],
                edges=[
                    {
                        "id": "anchor-connected",
                        "source": "anchor",
                        "target": "connected",
                        "type": "related",
                    }
                ],
            )

            builder.build_from_folder(
                str(folder),
                placement_context={"x": 900.0, "y": 700.0},
            )
            positions = json.loads(
                (folder / "positions.json").read_text(encoding="utf-8")
            )

        self.assertEqual(positions["anchor"], anchor_geometry)
        connected_center = (
            positions["connected"]["x"] + positions["connected"]["width"] / 2,
            positions["connected"]["y"] + positions["connected"]["height"] / 2,
        )
        anchor_center = (
            anchor_geometry["x"] + anchor_geometry["width"] / 2,
            anchor_geometry["y"] + anchor_geometry["height"] / 2,
        )
        self.assertLess(abs(connected_center[0] - anchor_center[0]), 400)
        self.assertLess(abs(connected_center[1] - anchor_center[1]), 400)

        loose_center = (
            positions["loose"]["x"] + positions["loose"]["width"] / 2,
            positions["loose"]["y"] + positions["loose"]["height"] / 2,
        )
        self.assertAlmostEqual(loose_center[0], 900.0)
        self.assertAlmostEqual(loose_center[1], 700.0)

    def test_line_labels_can_be_hidden_and_group_edges_never_render_labels(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            _write_graph_config(folder)
            _write_graph(
                folder,
                nodes=[
                    {"id": "a", "type": "concept"},
                    {"id": "b", "type": "concept"},
                ],
                edges=[
                    {
                        "id": "hidden-line",
                        "source": "a",
                        "target": "b",
                        "type": "hidden",
                        "label": "hidden label",
                    },
                    {
                        "id": "group-edge",
                        "source": "a",
                        "target": "b",
                        "type": "membership",
                        "label": "group label",
                    },
                ],
            )
            (folder / "edge_config.json").write_text(
                json.dumps(
                    {
                        "hidden": {
                            "connection_type": "line",
                            "show_label": False,
                        },
                        "membership": {
                            "connection_type": "group",
                            "show_label": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            output_path = Path(ExcaliBuilder().build_from_folder(str(folder)))
            output = json.loads(output_path.read_text(encoding="utf-8"))

        edge_label_ids = {
            element.get("customData", {}).get("edge_id")
            for element in output["elements"]
            if element["type"] == "text" and element.get("customData", {}).get("edge_id")
        }
        self.assertEqual(edge_label_ids, set())


class GraphWatcherTests(unittest.TestCase):
    def test_watcher_tracks_graph_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            graph_path = folder / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            watch_state = FolderWatchState(folder)

            graph_path.write_text('{"version": 1}', encoding="utf-8")
            changes = watch_state.collect_changes()

        self.assertEqual(changes.source_paths, [graph_path.resolve()])


if __name__ == "__main__":
    unittest.main()
