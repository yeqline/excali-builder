import copy
import json
import math
import shutil
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from excali_builder.builder import ExcaliBuilder
from excali_builder.layout.engines import available_engines, get_engine
from excali_builder.layout.engines.base import (
    Box,
    LayoutEdge,
    LayoutNode,
    LayoutRequest,
    LayoutResult,
)
from excali_builder.layout.engines.crossing import CrossingEngine
from excali_builder.layout.engines.elk import RUNTIME, ElkEngine
from excali_builder.layout.operations import OUTPUT_FILES, optimize_folder, restore_folder
from excali_builder.layout.quality import measure_quality, validate_result
from excali_builder.layout.references import CrossingOptions, select_connectors
from excali_builder.layout.routing import route_straight
from excali_builder.layout.state import STATE_FILE, decode_result, load_state, save_state
from excali_builder.serve.server import ServeState


def six_node_fixture(**options):
    request = LayoutRequest(
        [LayoutNode(n, 30, 30) for n in "ABCDEF"],
        [LayoutEdge(a + b, a, b) for a in "ABC" for b in "DEF"],
        node_spacing=30,
        engine_options={"crossing_max_connectors": 1, **options},
    )
    points = [(0, 0), (800, 500), (560, 240), (800, 0), (0, 500), (232, 265)]
    result = LayoutResult(
        {n: Box(x, y, 30, 30) for n, (x, y) in zip("ABCDEF", points)},
        {},
    )
    route_straight(request, result)
    return request, result


def write_device_fixture(folder):
    (folder / "node.csv").write_text(
        "node_id,node_type,node_title,node_text\n"
        "a,device,Supply A,\na_port,port,OUT,\n"
        "b,device,Supply B,\nb_port,port,OUT,\n"
        "c,device,Motor C,\nc_port,port,IN,\n"
        "d,device,Motor D,\nd_port,port,IN,\n"
    )
    (folder / "edge.csv").write_text(
        "from,to,edge_type,label\n"
        "a,a_port,parent_child,\nb,b_port,parent_child,\n"
        "c,c_port,parent_child,\nd,d_port,parent_child,\n"
        "a_port,c_port,wire,Power A\nb_port,d_port,wire,Power B\n"
    )
    (folder / "edge_config.json").write_text(
        json.dumps(
            {
                "parent_child": {"connection_type": "enclosing_group"},
                "wire": {
                    "connection_type": "line",
                    "color": "#123456",
                    "stroke_width": 3,
                    "stroke_style": "dashed",
                    "arrow_start": "circle",
                    "arrow_end": "arrow",
                },
            }
        )
    )
    (folder / "config.json").write_text(
        json.dumps(
            {
                "parser_type": "csv",
                "layout": {
                    "algorithm": "wiring",
                    "engine": "crossing",
                    "wiring": {
                        "candidates": 1,
                        "engine_options": {
                            "crossing_passes": 0,
                            "crossing_max_connectors": 1,
                        },
                    },
                },
            }
        )
    )


def device_seed(request):
    positions = {"a": (0, 0), "b": (0, 700), "c": (1400, 700), "d": (1400, 0)}
    result = LayoutResult({}, {})
    for node in request.nodes:
        if node.parent_id is None:
            x, y = positions[node.id]
            result.boxes[node.id] = Box(x, y, max(400, node.width), max(220, node.height))
    for node in request.nodes:
        if node.parent_id:
            parent = result.boxes[node.parent_id]
            side = "EAST" if node.parent_id in {"a", "b"} else "WEST"
            x = parent.x + (parent.width - 24 - node.width if side == "EAST" else 24)
            result.boxes[node.id] = Box(x, parent.y + 100, node.width, node.height)
            result.port_sides[node.id] = side
    route_straight(request, result)
    return result


class CrossingTests(unittest.TestCase):
    def test_registered_engine_and_strict_options(self):
        self.assertIn("crossing", available_engines())
        self.assertIsInstance(get_engine("crossing"), CrossingEngine)
        for options in (
            {"crossing_max_connectors": -1},
            {"crossing_max_connectors": True},
            {"crossing_max_connectors": 1.5},
            {"crossing_passes": "10"},
            {"crossing_protected_edges": ["missing"]},
            {"crossing_edge_costs": {"AD": math.inf}},
            {"crossing_edge_costs": {"AD": 0}},
        ):
            with self.subTest(options=options):
                request, _ = six_node_fixture(**options)
                with self.assertRaises(ValueError):
                    CrossingOptions.read(request)

    def test_one_reference_eliminates_crossing_and_preserves_all_edges(self):
        request, result = six_node_fixture()
        original = copy.deepcopy(request)
        self.assertEqual(measure_quality(request, result)["crossings"], 1)
        select_connectors(request, result)
        validate_result(request, result)
        metrics = measure_quality(request, result)
        self.assertEqual((metrics["crossings"], metrics["reference_connections"]), (0, 1))
        self.assertEqual(
            (metrics["obstructions"], metrics["label_collisions"], metrics["bends"]), (0, 0, 0)
        )
        self.assertEqual(set(result.routes), {e.id for e in request.edges})
        self.assertEqual(request, original)
        for edge in request.edges:
            connectors = result.routes[edge.id].connectors
            if connectors:
                self.assertEqual([c.target for c in connectors], [edge.target, edge.source])

    def test_budget_protection_and_cost_can_keep_full_wires(self):
        for options in (
            {"crossing_max_connectors": 0},
            {"crossing_protected_edges": ["BF", "CE"]},
            {"crossing_edge_costs": {"BF": 100, "CE": 100}},
        ):
            with self.subTest(options=options):
                request, result = six_node_fixture(**options)
                select_connectors(request, result)
                self.assertFalse(any(route.connectors for route in result.routes.values()))
                self.assertEqual(measure_quality(request, result)["crossings"], 1)

    def test_budget_is_a_ceiling_and_selection_is_deterministic(self):
        request, result = six_node_fixture(crossing_max_connectors=3)
        other = copy.deepcopy(result)
        select_connectors(request, result)
        select_connectors(request, other)
        self.assertEqual(result, other)
        self.assertEqual(measure_quality(request, result)["reference_connections"], 1)

    def test_reselection_restores_unnecessary_reference(self):
        request, result = six_node_fixture()
        select_connectors(request, result)
        request.engine_options["crossing_max_connectors"] = 0
        select_connectors(request, result)
        self.assertEqual(measure_quality(request, result)["crossings"], 1)
        self.assertTrue(all(not route.connectors for route in result.routes.values()))

    def test_per_port_limit_is_enforced_when_many_wires_cross(self):
        request, result = six_node_fixture(
            crossing_max_connectors=5,
            crossing_max_connectors_per_node=1,
        )
        for index, node in enumerate(request.nodes):
            result.boxes[node.id] = Box(1000 * (index // 3), 400 * (index % 3), 30, 30)
        route_straight(request, result)
        select_connectors(request, result)
        validate_result(request, result)
        used = []
        for edge in request.edges:
            if result.routes[edge.id].connectors:
                used.extend((edge.source, edge.target))
        self.assertTrue(used)
        self.assertEqual(len(used), len(set(used)))

    def test_moving_an_endpoint_refreshes_reference_geometry(self):
        request, result = six_node_fixture()
        select_connectors(request, result)
        key = next(key for key, route in result.routes.items() if route.connectors)
        edge = next(e for e in request.edges if e.id == key)
        before = copy.deepcopy(result.routes[key].connectors)
        result.boxes[edge.source].y -= 80
        route_straight(request, result)
        validate_result(request, result)
        self.assertNotEqual(result.routes[key].connectors, before)

    def test_invalid_reference_endpoints_and_geometry_are_rejected(self):
        request, result = six_node_fixture()
        select_connectors(request, result)
        route = next(route for route in result.routes.values() if route.connectors)
        route.connectors[0].target = "wrong-port"
        with self.assertRaisesRegex(ValueError, "Invalid reference"):
            validate_result(request, result)

    def test_saved_references_round_trip_and_old_states_remain_readable(self):
        request, result = six_node_fixture()
        old = asdict(result)
        for route in old["routes"].values():
            del route["connectors"]
        self.assertEqual(decode_result(old), result)
        select_connectors(request, result)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            save_state(folder, "same", result)
            self.assertEqual(load_state(folder, "same"), result)
            stale = load_state(folder, "changed")
            self.assertTrue(all(not route.connectors for route in stale.routes.values()))

    def test_two_dimensional_moves_reduce_crossings_without_references(self):
        request, result = six_node_fixture(crossing_max_connectors=0)
        # A deliberately poor arrangement with multiple x coordinates cannot
        # be fixed only by sifting adjacent devices within one ELK layer.
        for index, node in enumerate(request.nodes):
            result.boxes[node.id] = Box((index % 2) * 700 + index * 25, (index // 2) * 300, 30, 30)
        route_straight(request, result)
        before = measure_quality(request, result)["crossings"]
        original_x = [box.x for box in result.boxes.values()]
        moves = CrossingEngine.refine(request, result, time.monotonic() + 5)
        validate_result(request, result)
        self.assertGreater(moves, 0)
        self.assertLess(measure_quality(request, result)["crossings"], before)
        self.assertNotEqual([box.x for box in result.boxes.values()], original_x)

    def test_orthogonal_request_is_rejected_before_runtime(self):
        request, _ = six_node_fixture()
        request.edge_routing = "orthogonal"
        with patch.object(ElkEngine, "layout") as elk:
            with self.assertRaisesRegex(ValueError, "requires.*straight"):
                CrossingEngine().layout(request)
            elk.assert_not_called()

    def test_expired_reference_budget_does_not_start_search(self):
        request, result = six_node_fixture()
        select_connectors(request, result, time.monotonic() - 1)
        self.assertTrue(all(not route.connectors for route in result.routes.values()))


class ReferenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)
        write_device_fixture(self.folder)
        self.elk = patch.object(ElkEngine, "layout", side_effect=device_seed)
        self.elk_mock = self.elk.start()
        self.addCleanup(self.elk.stop)
        self.addCleanup(self.directory.cleanup)

    def build(self):
        output = ExcaliBuilder().build_from_folder(str(self.folder))
        return json.loads(Path(output).read_text()), json.loads(
            (self.folder / STATE_FILE).read_text()
        )["result"]

    def test_export_preserves_connection_identity_style_and_clickable_port_references(self):
        sources = {name: (self.folder / name).read_bytes() for name in ("node.csv", "edge.csv")}
        scene, result = self.build()
        self.assertEqual(result["metrics"]["reference_connections"], 1)
        self.assertEqual(result["metrics"]["crossings"], 0)
        refs = [e for e in scene["elements"] if e.get("customData", {}).get("reference_side")]
        self.assertEqual(len(refs), 6)
        self.assertEqual(len({e["id"] for e in scene["elements"]}), len(scene["elements"]))
        self.assertTrue(all("node_id" not in e["customData"] for e in refs))
        by_id = {e["id"]: e for e in scene["elements"]}
        for stub in (e for e in refs if e["type"] == "arrow"):
            self.assertEqual(
                (stub["strokeColor"], stub["strokeWidth"], stub["strokeStyle"]),
                ("#123456", 3, "dashed"),
            )
            self.assertEqual(len(stub["points"]), 2)
            for field in ("startBinding", "endBinding"):
                self.assertIn(
                    stub["id"], [e["id"] for e in by_id[stub[field]["elementId"]]["boundElements"]]
                )
            if stub["customData"]["reference_side"] == "source":
                self.assertEqual((stub["startArrowhead"], stub["endArrowhead"]), ("circle", None))
            else:
                self.assertEqual((stub["startArrowhead"], stub["endArrowhead"]), (None, "arrow"))
        for tag in (e for e in refs if e["type"] == "rectangle"):
            target = tag["customData"]["reference_target"]
            self.assertIn(f"/{target}?element=", tag["link"])
        text = " ".join(e["text"] for e in refs if e["type"] == "text")
        self.assertIn("Power", text)
        self.assertIn("_port]", text)
        self.assertIn("Supply", text)
        self.assertIn("Motor", text)
        self.assertEqual(len(result["routes"]), 2)
        for name, contents in sources.items():
            self.assertEqual((self.folder / name).read_bytes(), contents)

    def test_cached_rebuild_preserves_geometry_without_rerunning_engine(self):
        _, before = self.build()
        self.assertEqual(self.elk_mock.call_count, 1)
        with patch("excali_builder.layout.references.select_connectors") as select:
            _, after = self.build()
        select.assert_not_called()
        self.assertEqual(self.elk_mock.call_count, 1)
        self.assertEqual(before["boxes"], after["boxes"])
        self.assertEqual(before["routes"], after["routes"])
        self.assertEqual(
            set(json.loads((self.folder / "positions.json").read_text())), set(after["boxes"])
        )

    def test_moving_device_keeps_positions_and_reroutes_references(self):
        scene, before = self.build()
        selected = {key for key, route in before["routes"].items() if route["connectors"]}
        reference = next(
            element for element in scene["elements"]
            if element.get("customData", {}).get("reference_side") == "source"
        )
        port = reference["customData"]["source_id"]
        device = port[:-len("_port")]
        for element in scene["elements"]:
            if element.get("customData", {}).get("node_id") in {device, port}:
                element["y"] -= 60
        state = ServeState(self.folder, 1)
        with patch("excali_builder.layout.references.select_connectors") as select:
            saved = state.save_layout({"elements": scene["elements"], "revision": 0})
        select.assert_not_called()
        result = json.loads((self.folder / STATE_FILE).read_text())["result"]
        self.assertEqual(self.elk_mock.call_count, 1)
        self.assertEqual(selected, {
            key for key, route in result["routes"].items() if route["connectors"]
        })
        for key, box in before["boxes"].items():
            self.assertEqual(
                result["boxes"][key]["y"], box["y"] - (60 if key in {device, port} else 0)
            )
        edge_id = reference["customData"]["edge_id"]
        self.assertNotEqual(
            before["routes"][edge_id]["connectors"], result["routes"][edge_id]["connectors"]
        )
        self.assertIn("scene", saved)
        self.assertFalse(any(key.startswith("_") for key in result["metrics"]))

    def test_source_change_reselects_references_and_updates_tag_text(self):
        self.build()
        path = self.folder / "node.csv"
        path.write_text(path.read_text().replace("Motor C", "Updated C").replace(
            "Motor D", "Updated D"
        ))
        with patch(
            "excali_builder.layout.references.select_connectors", wraps=select_connectors
        ) as select:
            scene, result = self.build()
        select.assert_called_once()
        self.assertEqual(self.elk_mock.call_count, 1)
        self.assertEqual(result["metrics"]["reference_connections"], 1)
        self.assertIn("Updated", " ".join(
            element["text"] for element in scene["elements"]
            if element["type"] == "text"
            and element.get("customData", {}).get("reference_side")
        ))
        self.assertFalse(any(key.startswith("_") for key in result["metrics"]))

    def test_zero_budget_and_engine_switch_restore_complete_lines(self):
        for update in ("budget", "engine"):
            with self.subTest(update=update):
                write_device_fixture(self.folder)
                self.build()
                config = json.loads((self.folder / "config.json").read_text())
                if update == "budget":
                    config["layout"]["wiring"]["engine_options"]["crossing_max_connectors"] = 0
                else:
                    config["layout"]["engine"] = "elk"
                (self.folder / "config.json").write_text(json.dumps(config))
                scene, result = self.build()
                self.assertEqual(result["metrics"]["reference_connections"], 0)
                self.assertEqual(len([e for e in scene["elements"] if e["type"] == "arrow"]), 2)

    def test_viewer_lists_engine_and_optimization_can_be_restored(self):
        self.build()
        before = {
            name: (self.folder / name).read_bytes() if (self.folder / name).exists() else None
            for name in OUTPUT_FILES
        }
        self.assertIn("crossing", ServeState(self.folder, 1).layout_options()["engines"])
        result = optimize_folder(self.folder, "crossing")
        self.assertEqual(result["metrics"]["reference_connections"], 1)
        restore_folder(self.folder)
        for name, contents in before.items():
            if contents is not None:
                self.assertEqual(
                    json.loads((self.folder / name).read_bytes()), json.loads(contents)
                )

    def test_failed_optimization_keeps_previous_files(self):
        self.build()
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        with patch.object(ElkEngine, "layout", side_effect=RuntimeError("seed unavailable")):
            with self.assertRaisesRegex(ValueError, "seed unavailable"):
                optimize_folder(self.folder, "crossing")
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.folder.iterdir()})


@unittest.skipUnless(
    shutil.which("node") and (RUNTIME / "node_modules/elkjs").exists(),
    "Optional ELK runtime is not installed",
)
class CrossingRuntimeTests(unittest.TestCase):
    def test_real_runtime_preserves_shared_model_port_geometry(self):
        source = Path(__file__).resolve().parents[1] / "examples/shared-parts-diagram"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "diagram"
            shutil.copytree(
                source,
                folder,
                ignore=shutil.ignore_patterns(
                    "*.excalidraw",
                    "positions.json",
                    STATE_FILE,
                    "layout-backup.json",
                ),
            )
            config = json.loads((folder / "config.json").read_text())
            config["layout"].update({"engine": "crossing", "wiring": {"candidates": 1}})
            (folder / "config.json").write_text(json.dumps(config))
            ExcaliBuilder().build_from_folder(str(folder))
            state = json.loads((folder / STATE_FILE).read_text())["result"]
            self.assertEqual(state["metrics"]["engine"], "crossing")
            self.assertTrue(state["metrics"]["part_templates"])
            for role in ("encoder", "phase"):
                offsets = []
                for axis in ("x", "y"):
                    parent, port = (
                        state["boxes"][f"motor_{axis}"],
                        state["boxes"][f"motor_{axis}_{role}"],
                    )
                    offsets.append((port["x"] - parent["x"], port["y"] - parent["y"]))
                for a, b in zip(offsets[0], offsets[1]):
                    self.assertAlmostEqual(a, b)


if __name__ == "__main__":
    unittest.main()
