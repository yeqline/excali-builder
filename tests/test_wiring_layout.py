import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from excali_builder.builder import ExcaliBuilder
from excali_builder.cli import parse_args
from excali_builder.layout.engines import register_engine
from excali_builder.layout.engines.base import (
    Box,
    LayoutEdge,
    LayoutEngine,
    LayoutNode,
    LayoutRequest,
    LayoutResult,
    Route,
)
from excali_builder.layout.engines.elk import RUNTIME, ElkEngine
from excali_builder.layout.operations import OUTPUT_FILES, optimize_folder, restore_folder
from excali_builder.layout.quality import measure_quality, validate_result
from excali_builder.layout.routing import route_fixed
from excali_builder.layout.state import STATE_FILE
from excali_builder.layout.wiring import place_additions
from excali_builder.serve.server import ServeState


class AlternateEngine(LayoutEngine):
    """An independent adapter used to exercise the public engine contract."""

    calls = 0

    def layout(self, request):
        AlternateEngine.calls += 1
        result = LayoutResult({}, {})
        for index, node in enumerate(n for n in request.nodes if not n.parent_id):
            result.boxes[node.id] = Box(100 + index * 850, 100, node.width, max(240, node.height))
        for node in request.nodes:
            if not node.parent_id:
                continue
            parent = result.boxes[node.parent_id]
            x = (
                parent.x + request.padding
                if node.side == "WEST"
                else parent.x + parent.width - request.padding - node.width
            )
            result.boxes[node.id] = Box(x, parent.y + 100, node.width, node.height)
            result.port_sides[node.id] = node.side
        for edge in request.edges:
            a, b = result.boxes[edge.source], result.boxes[edge.target]
            start = (a.x + a.width, a.y + a.height / 2)
            end = (b.x, b.y + b.height / 2)
            mid = (start[0] + end[0]) / 2
            result.routes[edge.id] = Route([start, (mid, start[1]), (mid, end[1]), end])
        return result


def write_fixture(folder, algorithm="tree", engine="elk"):
    (folder / "node.csv").write_text(
        "node_id,node_type,node_title,node_text\n"
        "a,device,Supply,Source device\n"
        "ap,port,OUT,Positive supply\n"
        "b,device,Controller,Destination device\n"
        "bp,port,IN,Power input\n"
    )
    (folder / "edge.csv").write_text(
        "from,to,edge_type,label\n"
        "a,ap,parent_child,\n"
        "b,bp,parent_child,\n"
        "ap,bp,wire,Positive supply connection with a label that must wrap\n"
    )
    (folder / "config.json").write_text(
        json.dumps(
            {
                "parser_type": "csv",
                "layout": {"algorithm": algorithm, "engine": engine, "wiring": {"candidates": 1}},
            }
        )
    )
    (folder / "edge_config.json").write_text(
        json.dumps(
            {
                "parent_child": {"connection_type": "enclosing_group"},
                "wire": {"connection_type": "line", "arrow_end": "arrow"},
            }
        )
    )


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        register_engine("test-alternate", AlternateEngine)
        AlternateEngine.calls = 0

    def tearDown(self):
        self.temp.cleanup()

    def test_alternative_engine_supports_initial_layout_and_cached_rebuild(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        builder = ExcaliBuilder()
        output = Path(builder.build_from_folder(str(self.folder)))
        state = json.loads((self.folder / STATE_FILE).read_text())
        scene = json.loads(output.read_text())
        arrow = next(e for e in scene["elements"] if e["type"] == "arrow")
        self.assertIsNotNone(arrow["startBinding"])
        self.assertEqual(len(state["result"]["boxes"]), 4)
        self.assertEqual(len(state["result"]["routes"]), 1)
        self.assertEqual(AlternateEngine.calls, 1)
        builder.build_from_folder(str(self.folder))
        self.assertEqual(AlternateEngine.calls, 1)
        self.assertEqual(
            state["result"]["boxes"],
            json.loads((self.folder / STATE_FILE).read_text())["result"]["boxes"],
        )

    def test_optimize_and_restore_round_trip(self):
        write_fixture(self.folder)
        ExcaliBuilder().build_from_folder(str(self.folder))
        before = {
            name: json.loads((self.folder / name).read_text())
            if (self.folder / name).exists()
            else None
            for name in OUTPUT_FILES
        }
        result = optimize_folder(self.folder, "test-alternate")
        self.assertTrue(result["can_restore"])
        self.assertEqual(
            json.loads((self.folder / "config.json").read_text())["layout"]["engine"],
            "test-alternate",
        )
        restore_folder(self.folder)
        after = {
            name: json.loads((self.folder / name).read_text())
            if (self.folder / name).exists()
            else None
            for name in OUTPUT_FILES
        }
        self.assertEqual(before, after)

    def test_failed_engine_leaves_all_original_files_unchanged(self):
        write_fixture(self.folder)
        ExcaliBuilder().build_from_folder(str(self.folder))
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        with patch.object(AlternateEngine, "layout", side_effect=RuntimeError("unavailable")):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                optimize_folder(self.folder, "test-alternate")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_restore_refuses_changed_source_graph(self):
        write_fixture(self.folder)
        optimize_folder(self.folder, "test-alternate")
        with (self.folder / "node.csv").open("a") as handle:
            handle.write("new,device,New device,\n")
        with self.assertRaisesRegex(ValueError, "Sources changed"):
            restore_folder(self.folder)

    def test_stale_save_cannot_overwrite_optimization(self):
        write_fixture(self.folder)
        state = ServeState(self.folder, 1)
        state.initial_build()
        elements = json.loads(state.output_path.read_text())["elements"]
        revision = state.layout_revision
        state.optimize_layout(
            {
                "engine": "test-alternate",
                "elements": elements,
                "revision": revision,
            }
        )
        optimized = state.output_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "diagram changed"):
            state.save_layout({"elements": elements, "revision": revision})
        self.assertEqual(optimized, state.output_path.read_bytes())

    def test_existing_geometry_survives_routing_after_moving_device(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        builder = ExcaliBuilder()
        builder.build_from_folder(str(self.folder))
        positions = json.loads((self.folder / "positions.json").read_text())
        for key in ("b", "bp"):
            positions[key]["y"] += 200
        (self.folder / "positions.json").write_text(json.dumps(positions))
        builder.build_from_folder(str(self.folder))
        after = json.loads((self.folder / "positions.json").read_text())
        for key in positions:
            self.assertEqual(
                (positions[key]["x"], positions[key]["y"]), (after[key]["x"], after[key]["y"])
            )
        self.assertEqual(AlternateEngine.calls, 1)
        state = json.loads((self.folder / STATE_FILE).read_text())["result"]
        route = next(iter(state["routes"].values()))
        self.assertGreaterEqual(len(route["points"]), 4)

    def test_invalid_containment_rejected_before_engine_runs(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        with (self.folder / "edge.csv").open("a") as handle:
            handle.write("ap,a,parent_child,\n")
        with self.assertRaisesRegex(ValueError, "Containment cycle"):
            ExcaliBuilder().build_from_folder(str(self.folder))
        self.assertEqual(AlternateEngine.calls, 0)

    def test_route_crosses_neither_obstacle_nor_its_own_device_body(self):
        request = LayoutRequest(
            [
                LayoutNode("a", 100, 100),
                LayoutNode("b", 100, 100),
                LayoutNode("obstacle", 100, 140),
            ],
            [LayoutEdge("wire", "a", "b")],
        )
        result = LayoutResult(
            {
                "a": Box(0, 0, 100, 100),
                "b": Box(500, 0, 100, 100),
                "obstacle": Box(250, -20, 100, 140),
            },
            {},
        )
        route_fixed(request, result)
        self.assertTrue(
            all(
                a[0] == b[0] or a[1] == b[1]
                for a, b in zip(result.routes["wire"].points, result.routes["wire"].points[1:])
            )
        )
        self.assertEqual(measure_quality(request, result)["obstructions"], 0)

    def test_engine_result_must_preserve_endpoint_ids_and_containment(self):
        request = LayoutRequest([LayoutNode("a", 100, 100), LayoutNode("p", 20, 20, "a", True)], [])
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_result(
                request, LayoutResult({"a": Box(0, 0, 100, 100), "p": Box(150, 0, 20, 20)}, {})
            )
        with self.assertRaisesRegex(ValueError, "exactly"):
            validate_result(request, LayoutResult({"a": Box(0, 0, 100, 100)}, {}))

    def test_internal_elk_edge_uses_reported_coordinate_container(self):
        raw = {
            "id": "root",
            "children": [
                {
                    "id": "device",
                    "x": 100,
                    "y": 200,
                    "width": 200,
                    "height": 150,
                    "edges": [
                        {
                            "id": "wire",
                            "container": "root",
                            "sections": [
                                {
                                    "startPoint": {"x": 110, "y": 220},
                                    "endPoint": {"x": 180, "y": 240},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        result = ElkEngine()._from_elk(raw)
        self.assertEqual(result.routes["wire"].points[0], (110, 220))

    def test_optimize_cli_selects_registered_engine(self):
        args = parse_args(["optimize", "/diagram", "--engine", "custom"])
        self.assertEqual((args.command, args.engine), ("optimize", "custom"))
        self.assertEqual(parse_args(["restore-layout", "/diagram"]).command, "restore-layout")

    def test_new_device_preserves_all_existing_positions(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        builder = ExcaliBuilder()
        builder.build_from_folder(str(self.folder))
        before = json.loads((self.folder / "positions.json").read_text())
        with (self.folder / "node.csv").open("a") as handle:
            handle.write("extra,device,Extra device,\n")
        builder.build_from_folder(str(self.folder))
        after = json.loads((self.folder / "positions.json").read_text())
        self.assertIn("extra", after)
        for key in before:
            self.assertEqual(
                (before[key]["x"], before[key]["y"]), (after[key]["x"], after[key]["y"])
            )

    def test_manual_orthogonal_bends_survive_viewer_save_and_reload(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        state = ServeState(self.folder, 1)
        state.initial_build()
        elements = json.loads(state.output_path.read_text())["elements"]
        arrow = next(e for e in elements if e["type"] == "arrow")
        ex, ey = arrow["points"][-1]
        points = [[0, 0], [80, 0], [80, 100], [ex - 80, 100], [ex - 80, ey], [ex, ey]]
        arrow["points"] = points
        state.save_layout({"elements": elements, "revision": state.layout_revision})
        output = json.loads(state.output_path.read_text())
        saved = next(e for e in output["elements"] if e["type"] == "arrow")
        self.assertEqual(saved["points"], points)
        state.initial_build()
        saved = next(
            e for e in json.loads(state.output_path.read_text())["elements"] if e["type"] == "arrow"
        )
        self.assertEqual(saved["points"], points)

    def test_failed_viewer_rebuild_rolls_back_saved_geometry(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        state = ServeState(self.folder, 1)
        state.initial_build()
        before = json.loads((self.folder / "positions.json").read_text())
        elements = json.loads(state.output_path.read_text())["elements"]
        elements[0]["x"] += 100
        with patch.object(
            state.builder, "build_from_folder", side_effect=ValueError("invalid layout")
        ):
            with self.assertRaisesRegex(ValueError, "invalid layout"):
                state.save_layout({"elements": elements, "revision": state.layout_revision})
        self.assertEqual(before, json.loads((self.folder / "positions.json").read_text()))

    def test_stale_save_cannot_overwrite_source_rebuild(self):
        write_fixture(self.folder, "wiring", "test-alternate")
        state = ServeState(self.folder, 1)
        state.initial_build()
        elements = json.loads(state.output_path.read_text())["elements"]
        revision = state.layout_revision
        with (self.folder / "node.csv").open("a") as handle:
            handle.write("extra,device,Extra device,\n")
        state._build(reason="source", sync_first=True)
        rebuilt = state.output_path.read_bytes()
        self.assertNotEqual(revision, state.layout_revision)
        with self.assertRaisesRegex(ValueError, "diagram changed"):
            state.save_layout({"elements": elements, "revision": revision})
        with self.assertRaisesRegex(ValueError, "diagram changed"):
            state.save_layout({"elements": elements})
        self.assertEqual(rebuilt, state.output_path.read_bytes())

    def test_optimize_refuses_non_csv_diagrams_until_already_wiring(self):
        (self.folder / "config.json").write_text(json.dumps({"parser_type": "md"}))
        with self.assertRaisesRegex(ValueError, "CSV diagrams"):
            optimize_folder(self.folder, "test-alternate")
        self.assertFalse(ServeState(self.folder, 1).layout_options()["can_optimize"])

    def test_new_nested_device_keeps_interior_candidate_position(self):
        request = LayoutRequest(
            [
                LayoutNode("enclosure", 600, 400, header_height=50),
                LayoutNode("existing", 120, 80, "enclosure"),
                LayoutNode("nested", 120, 80, "enclosure"),
                LayoutNode("nested_port", 40, 20, "nested", True, side="EAST"),
            ],
            [],
        )
        result = LayoutResult(
            {
                "enclosure": Box(0, 0, 600, 400),
                "existing": Box(40, 80, 120, 80),
            },
            {},
        )
        candidate = LayoutResult(
            {
                "enclosure": Box(0, 0, 600, 400),
                "existing": Box(40, 80, 120, 80),
                "nested": Box(400, 80, 120, 80),
                "nested_port": Box(480, 110, 40, 20),
            },
            {},
            {"nested_port": "EAST"},
        )
        place_additions(request, result, candidate)
        self.assertEqual((result.boxes["nested"].x, result.boxes["nested"].y), (400, 80))
        self.assertNotEqual(
            result.boxes["nested"].x,
            600 - request.padding - 120,
        )
        self.assertEqual((result.boxes["nested_port"].x, result.boxes["nested_port"].y), (480, 110))

    def test_new_port_uses_requested_bank(self):
        request = LayoutRequest(
            [
                LayoutNode("device", 400, 300, header_height=40),
                LayoutNode("old", 80, 30, "device", True, side="WEST"),
                LayoutNode("extra", 80, 30, "device", True, side="EAST"),
            ],
            [],
        )
        result = LayoutResult(
            {"device": Box(0, 0, 400, 300), "old": Box(24, 80, 80, 30)},
            {},
            {"old": "WEST"},
        )
        candidate = LayoutResult(
            {
                "device": Box(0, 0, 400, 300),
                "old": Box(24, 80, 80, 30),
                "extra": Box(100, 80, 80, 30),
            },
            {},
            {"extra": "EAST"},
        )
        place_additions(request, result, candidate)
        extra = result.boxes["extra"]
        self.assertAlmostEqual(extra.x, 400 - request.padding - 80)
        self.assertGreater(extra.y, 40)


@unittest.skipUnless(
    shutil.which("node") and (RUNTIME / "node_modules/elkjs").exists(),
    "Optional ELK runtime is not installed",
)
class ElkIntegrationTests(unittest.TestCase):
    def test_new_port_keeps_existing_nodes_and_uses_its_requested_side(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_fixture(folder, "wiring")
            builder = ExcaliBuilder()
            builder.build_from_folder(str(folder))
            before = json.loads((folder / "positions.json").read_text())
            with (folder / "node.csv").open("a") as handle:
                handle.write("extra,port,Spare,\n")
            with (folder / "edge.csv").open("a") as handle:
                handle.write("a,extra,parent_child,\n")
            config = json.loads((folder / "config.json").read_text())
            config["layout"]["wiring"]["port_sides"] = {"extra": "EAST"}
            (folder / "config.json").write_text(json.dumps(config))
            builder.build_from_folder(str(folder))
            after = json.loads((folder / "positions.json").read_text())
            for key in before:
                self.assertEqual(
                    (before[key]["x"], before[key]["y"]), (after[key]["x"], after[key]["y"])
                )
            self.assertGreater(after["extra"]["x"], after["a"]["x"] + after["a"]["width"] / 2)

    def test_dense_port_bank_reserves_complete_header_and_port_spacing(self):
        request = LayoutRequest(
            [LayoutNode("controller", 400, 200, header_height=140)]
            + [LayoutNode(f"p{i}", 120, 44, "controller", True, side="EAST") for i in range(16)],
            [],
            port_spacing=20,
            padding=24,
        )
        result = ElkEngine().layout(request)
        validate_result(request, result)
        top = result.boxes["controller"].y
        ports = sorted((result.boxes[f"p{i}"] for i in range(16)), key=lambda b: b.y)
        self.assertGreaterEqual(ports[0].y - top, 164)
        self.assertTrue(all(b.y - a.y - a.height >= 20 for a, b in zip(ports, ports[1:])))

    def test_nested_device_and_cross_hierarchy_edges(self):
        request = LayoutRequest(
            [
                LayoutNode("enclosure", 500, 400, header_height=60),
                LayoutNode("controller", 300, 200, "enclosure", header_height=50),
                LayoutNode("out", 100, 40, "controller", True, side="EAST"),
                LayoutNode("motor", 300, 200, header_height=50),
                LayoutNode("in", 100, 40, "motor", True, side="WEST"),
            ],
            [LayoutEdge("wire", "out", "in")],
        )
        result = ElkEngine().layout(request)
        validate_result(request, result)
        self.assertEqual(measure_quality(request, result)["obstructions"], 0)

    def test_fixed_port_order_and_size_are_respected(self):
        request = LayoutRequest(
            [
                LayoutNode("device", 400, 400, header_height=60, size_locked=True),
                LayoutNode("a", 100, 40, "device", True, side="WEST", order=0),
                LayoutNode("b", 100, 40, "device", True, side="WEST", order=1),
            ],
            [],
        )
        result = ElkEngine().layout(request)
        validate_result(request, result)
        self.assertLess(result.boxes["a"].y, result.boxes["b"].y)


if __name__ == "__main__":
    unittest.main()
