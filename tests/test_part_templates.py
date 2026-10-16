import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from excali_builder.builder import ExcaliBuilder
from excali_builder.config.schema import GlobalConfig
from excali_builder.core.edge import ConnectionType, Edge
from excali_builder.core.graph import Graph
from excali_builder.core.node import Node
from excali_builder.layout.engines import register_engine
from excali_builder.layout.engines.base import Box, LayoutEngine, LayoutResult
from excali_builder.layout.engines.elk import RUNTIME
from excali_builder.layout.parts import apply_part_geometry, describe_parts
from excali_builder.layout.quality import measure_quality, validate_result
from excali_builder.layout.routing import route_straight
from excali_builder.layout.state import load_state, topology_signature
from excali_builder.layout.wiring import apply_result, existing_layout, make_request, optimize
from excali_builder.parsers.csv import CSVParser


def part_fixture(locked=False):
    graph = Graph()
    for part in ("a", "b"):
        graph.add_node(
            Node(
                id=part,
                label=part,
                width=300,
                height=240,
                metadata={"layout_header_height": 40, "model_number": "stepper"},
            )
        )
        for role in ("phase", "encoder"):
            port_id = f"{part}_{role}"
            graph.add_node(Node(id=port_id, label=role, type="port", width=60, height=30))
            graph.add_edge(
                Edge(
                    id=f"contains_{port_id}",
                    source_id=part,
                    target_id=port_id,
                    edge_type="parent_child",
                    connection_type=ConnectionType.ENCLOSING_GROUP,
                )
            )
            source_id = f"source_{port_id}"
            graph.add_node(Node(id=source_id, label=source_id, width=60, height=30))
            # Part a has four connections and part b has two. Their preferred
            # orders conflict; the shared winner should favor the whole graph.
            for index in range(2 if part == "a" else 1):
                graph.add_edge(
                    Edge(
                        id=f"wire_{port_id}_{index}",
                        source_id=source_id,
                        target_id=port_id,
                        edge_type="wire",
                        connection_type=ConnectionType.LINE,
                    )
                )
    config = GlobalConfig.model_validate(
        {
            "node_types": {"default": {}, "port": {}},
            "edge_types": {
                "wire": {
                    "connection_type": "line",
                    "color": "#000000",
                    "stroke_width": 2,
                    "stroke_style": "solid",
                }
            },
            "layout": {
                "algorithm": "wiring",
                "wiring": {
                    "part_templates": {
                        "stepper": {
                            "optimize": not locked,
                            "port_sides": {"phase": "WEST", "encoder": "WEST"},
                        },
                    },
                },
            },
        }
    )
    return graph, config


class PartPlacementEngine(LayoutEngine):
    """Place the conflicting fixture, intentionally ignoring port arrangement."""

    def layout(self, request):
        result = LayoutResult({}, {})
        for node in request.nodes:
            if node.parent_id:
                continue
            if node.id in ("a", "b"):
                x, y = 500, 0 if node.id == "a" else 400
            else:
                x = 0
                # Encoder above phase for a; below phase for b.
                y = {
                    "source_a_encoder": 64,
                    "source_a_phase": 110,
                    "source_b_encoder": 510,
                    "source_b_phase": 464,
                }[node.id]
            result.boxes[node.id] = Box(x, y, node.width, node.height)
        for node in request.nodes:
            if node.parent_id:
                parent = result.boxes[node.parent_id]
                result.boxes[node.id] = Box(parent.x + 24, parent.y + 100, node.width, node.height)
                result.port_sides[node.id] = "WEST"
        route_straight(request, result)
        return result


class PartTemplateTests(unittest.TestCase):
    def setUp(self):
        register_engine("test-parts", PartPlacementEngine)

    def assert_shared(self, request, result):
        template = request.part_templates["stepper"]
        for role in template.roles:
            local = []
            for parent_id, ports in template.instances.items():
                parent, port = result.boxes[parent_id], result.boxes[ports[role]]
                local.append(
                    (
                        port.x - parent.x,
                        port.y - parent.y,
                        port.width,
                        port.height,
                        result.port_sides[ports[role]],
                    )
                )
            self.assertEqual(local[0], local[1])

    def test_collective_search_uses_global_score_and_keeps_instances_equal(self):
        graph, config = part_fixture()
        request = make_request(graph, config)
        seed = PartPlacementEngine().layout(request)
        apply_part_geometry(request, seed)
        route_straight(request, seed)
        before = measure_quality(request, seed)
        result = optimize(request, "test-parts", 1, {})
        self.assertLess(result.metrics["crossings"], before["crossings"])
        self.assert_shared(request, result)
        self.assertEqual(result.metrics["part_templates"]["stepper"]["WEST"], ["encoder", "phase"])
        # The minority instance keeps the group winner rather than its own
        # preferred order, even though that leaves one crossing.
        self.assertEqual(result.metrics["crossings"], 1)
        validate_result(request, result)

    def test_locked_template_is_not_reordered_by_optimization(self):
        graph, config = part_fixture(locked=True)
        request = make_request(graph, config)
        result = optimize(request, "test-parts", 1, {})
        self.assertEqual(result.metrics["part_templates"]["stepper"]["WEST"], ["phase", "encoder"])
        self.assertEqual(result.metrics["part_template_trials"], 0)
        self.assert_shared(request, result)

    def test_winner_is_restored_when_rebuilding_or_moving_one_device(self):
        graph, config = part_fixture()
        request = make_request(graph, config)
        saved = optimize(request, "test-parts", 1, {})
        apply_result(graph, saved)
        graph.nodes["b"].x += 150
        graph.nodes["b_encoder"].y += 70
        rebuilt_request = make_request(graph, config)
        current = existing_layout(graph, rebuilt_request, saved)
        route_straight(rebuilt_request, current)
        self.assertEqual(describe_parts(rebuilt_request, current), saved.metrics["part_templates"])
        self.assertEqual(current.boxes["b"].x, saved.boxes["b"].x + 150)
        self.assert_shared(rebuilt_request, current)
        validate_result(rebuilt_request, current)

    def test_validator_rejects_instance_specific_port_swaps(self):
        graph, config = part_fixture()
        request = make_request(graph, config)
        result = optimize(request, "test-parts", 1, {})
        a, b = result.boxes["b_encoder"], result.boxes["b_phase"]
        a.y, b.y = b.y, a.y
        route_straight(request, result)
        with self.assertRaisesRegex(ValueError, "shared geometry"):
            validate_result(request, result)

    def test_template_geometry_accounts_for_all_headings_and_port_labels(self):
        graph, config = part_fixture()
        graph.nodes["b"].metadata["layout_header_height"] = 80
        graph.nodes["b_encoder"].width = 110
        request = make_request(graph, config)
        result = optimize(request, "test-parts", 1, {})
        self.assert_shared(request, result)
        self.assertEqual(result.boxes["a_encoder"].width, 110)
        self.assertGreaterEqual(result.boxes["a_encoder"].y - result.boxes["a"].y, 104)

    def test_bad_role_mappings_and_conflicting_locks_are_rejected(self):
        graph, base = part_fixture()
        for mutation, error in (
            (lambda g: setattr(g.nodes["b_encoder"], "label", ""), "non-empty title"),
            (lambda g: setattr(g.nodes["b_encoder"], "label", "other"), "same port titles"),
            (lambda g: setattr(g.nodes["b_encoder"], "label", "phase"), "Duplicate port title"),
            (lambda g: g.nodes["b"].metadata.update(model_number=42), "non-empty string"),
        ):
            with self.subTest(error=error):
                changed = copy.deepcopy(graph)
                mutation(changed)
                with self.assertRaisesRegex(ValueError, error):
                    make_request(changed, base)
        for mutation, error in (
            (lambda c: c.layout.wiring.port_sides.update(b_encoder="EAST"), "Conflicting side"),
            (
                lambda c: c.layout.wiring.port_order.update(
                    a=["a_encoder", "a_phase"], b=["b_phase", "b_encoder"]
                ),
                "Conflicting port orders",
            ),
        ):
            with self.subTest(error=error):
                config = copy.deepcopy(base)
                mutation(config)
                with self.assertRaisesRegex(ValueError, error):
                    make_request(graph, config)

    def test_grouping_is_automatic_and_model_not_node_type_defines_identity(self):
        graph, config = part_fixture()
        config.layout.wiring.part_templates.clear()
        graph.nodes["b"].metadata["model_number"] = "different-stepper"
        request = make_request(graph, config)
        self.assertEqual(set(request.part_templates), {"stepper", "different-stepper"})
        self.assertEqual(
            request.part_templates["stepper"].instances,
            {"a": {"phase": "a_phase", "encoder": "a_encoder"}},
        )

    def test_model_number_changes_layout_signature(self):
        graph, config = part_fixture()
        initial = topology_signature(graph, config)
        graph.nodes["b"].metadata["model_number"] = "different-stepper"
        self.assertNotEqual(initial, topology_signature(graph, config))

    def test_partial_port_order_is_a_group_constraint(self):
        graph, config = part_fixture()
        config.layout.wiring.port_order["b"] = ["b_phase"]
        request = make_request(graph, config)
        result = optimize(request, "test-parts", 1, {})
        self.assertEqual(result.metrics["part_templates"]["stepper"]["WEST"], ["phase", "encoder"])

    def test_no_model_numbers_means_no_implicit_grouping(self):
        graph, config = part_fixture()
        config.layout.wiring.part_templates.clear()
        for part in ("a", "b"):
            graph.nodes[part].metadata.pop("model_number")
        self.assertFalse(make_request(graph, config).part_templates)

    def test_csv_preserves_model_number_and_legacy_csv_still_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "node.csv").write_text(
                "node_id,node_type,node_title,node_text,model_number\n"
                "a,device,Motor X,Model details, STEPPER \n"
                "a_enc,port,ENCODER,,\n"
                "b,device,Motor Y,,STEPPER\n"
                "b_enc,port, ENCODER ,,\n"
            )
            (folder / "edge.csv").write_text(
                "from,to,edge_type\na,a_enc,parent_child\nb,b_enc,parent_child\n"
            )
            (folder / "edge_config.json").write_text(
                '{"parent_child":{"connection_type":"enclosing_group"}}'
            )
            graph = CSVParser().parse(folder, {})
            request = make_request(graph, GlobalConfig())
            self.assertEqual(len(request.part_templates["STEPPER"].instances), 2)
            self.assertEqual(graph.nodes["a"].metadata["text"], "Model details")
            (folder / "node.csv").write_text(
                "node_id,node_type,node_title,node_text\na,device,Legacy,Details\n"
            )
            (folder / "edge.csv").write_text("from,to,edge_type\n")
            graph = CSVParser().parse(folder, {})
            self.assertFalse(make_request(graph, GlobalConfig()).part_templates)


@unittest.skipUnless(
    shutil.which("node") and (RUNTIME / "node_modules/elkjs").exists(),
    "Optional ELK runtime is not installed",
)
class PartTemplateIntegrationTests(unittest.TestCase):
    assert_shared = PartTemplateTests.assert_shared

    def test_built_in_engines_preserve_shared_geometry_in_both_routing_modes(self):
        for engine in ("elk", "hybrid"):
            for routing in ("straight", "orthogonal"):
                with self.subTest(engine=engine, routing=routing):
                    graph, config = part_fixture()
                    config.layout.wiring.edge_routing = routing
                    request = make_request(graph, config)
                    request.timeout = 10
                    result = optimize(request, engine, 1, {})
                    self.assert_shared(request, result)
                    validate_result(request, result)

    def test_csv_example_rebuild_preserves_the_winning_arrangements(self):
        example = Path(__file__).resolve().parents[1] / "examples/shared-parts-diagram"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "diagram"
            shutil.copytree(example, folder)
            builder = ExcaliBuilder()
            builder.build_from_folder(str(folder), optimize_layout=True)
            winner = copy.deepcopy(builder.last_layout_metrics["part_templates"])
            before = load_state(folder, "unused")
            builder.build_from_folder(str(folder))
            rebuilt = load_state(folder, "unused")
            self.assertEqual(rebuilt.metrics["part_templates"], winner)
            self.assertEqual(rebuilt.boxes, before.boxes)


if __name__ == "__main__":
    unittest.main()
