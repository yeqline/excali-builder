import json
import tempfile
import unittest
from pathlib import Path

from excali_builder.builder import ExcaliBuilder
from excali_builder.config.schema import EdgeTypeConfig, GlobalConfig, LayoutConfig, NodeTypeConfig
from excali_builder.core.edge import ConnectionType, Edge
from excali_builder.core.graph import Graph
from excali_builder.core.node import Node
from excali_builder.excalidraw.exporter import ExcalidrawExporter
from excali_builder.parsers.markdown import MarkdownParser


class LayoutRegressionTests(unittest.TestCase):
    def test_markdown_link_node_gets_default_link_edge_to_parent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Topic {#topic}",
                        "",
                        "### Snowflake Docs {#snowflake-docs}",
                        "",
                        "> [!meta]",
                        "> type: link",
                        "> target: https://docs.snowflake.com/",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        link_edges = [
            edge for edge in graph.edges if edge.edge_type == "link"
        ]
        self.assertEqual(len(link_edges), 1)
        self.assertEqual((link_edges[0].source_id, link_edges[0].target_id), ("topic", "snowflake-docs"))
        self.assertEqual(graph.nodes["snowflake-docs"].metadata["target"], "https://docs.snowflake.com/")

    def test_markdown_link_node_internal_target_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Topic {#topic}",
                        "",
                        "### Jump {#jump}",
                        "",
                        "> [!meta]",
                        "> type: link",
                        "> target: #topic",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(graph.nodes["jump"].metadata["target"], "#topic")

    def test_tree_layout_uses_parent_child_hierarchy_even_for_line_edges(self):
        graph = Graph()
        root = Node(id="root", label="Root", width=100, height=50)
        child_a = Node(id="child-a", label="Child A", width=100, height=50)
        child_b = Node(id="child-b", label="Child B", width=100, height=50)

        for node in [root, child_a, child_b]:
            graph.add_node(node)

        for child_id in ["child-a", "child-b"]:
            graph.add_edge(
                Edge(
                    source_id="root",
                    target_id=child_id,
                    connection_type=ConnectionType.LINE,
                    edge_type="parent_child",
                )
            )

        config = GlobalConfig(
            layout=LayoutConfig(
                direction="left-right",
                level_spacing=150,
                sibling_spacing=20,
                root_spacing=80,
                start_x=100,
                start_y=100,
            ),
            edge_types={"parent_child": EdgeTypeConfig(connection_type="line")},
        )

        ExcaliBuilder()._apply_layout_to_new_nodes(graph, config)

        self.assertEqual((root.x, root.y), (100, 135))
        self.assertEqual((child_a.x, child_a.y), (350, 100))
        self.assertEqual((child_b.x, child_b.y), (350, 170))

    def test_tree_layout_respects_saved_parent_position_for_new_children(self):
        graph = Graph()
        root = Node(id="root", label="Root", x=40, y=60, width=120, height=70)
        child = Node(id="child", label="Child", width=90, height=50)
        graph.add_node(root)
        graph.add_node(child)
        graph.add_edge(
            Edge(
                source_id="root",
                target_id="child",
                connection_type=ConnectionType.CONTAINER,
                edge_type="parent_child",
            )
        )

        config = GlobalConfig(
            layout=LayoutConfig(
                direction="left-right",
                level_spacing=140,
                sibling_spacing=20,
                start_x=100,
                start_y=100,
            ),
            edge_types={"parent_child": EdgeTypeConfig(connection_type="container")},
        )

        ExcaliBuilder()._apply_layout_to_new_nodes(graph, config)

        self.assertEqual((root.x, root.y), (40, 60))
        self.assertEqual((child.x, child.y), (300, 70))

    def test_exporter_uses_markdown_content_as_rendered_text(self):
        node = Node(
            id="node",
            label="Title",
            metadata={"content": "Full markdown body text."},
        )

        full_text = ExcalidrawExporter().get_node_full_text(node)

        self.assertEqual(full_text, "Title\nFull markdown body text.")

    def test_initial_node_measurement_is_capped_for_long_text(self):
        node = Node(
            id="node",
            label="Title",
            metadata={"text": " ".join(["body"] * 500)},
        )
        exporter = ExcalidrawExporter()
        width, height = exporter.measure_node(node, NodeTypeConfig())

        self.assertLessEqual(width, exporter.MAX_INITIAL_NODE_WIDTH)
        self.assertEqual(height, exporter.MAX_INITIAL_NODE_HEIGHT)

    def test_exporter_wraps_display_text_but_preserves_original_text(self):
        graph = Graph()
        node = Node(
            id="node",
            label="Title",
            width=160,
            height=80,
            metadata={"text": " ".join(["body"] * 25)},
        )
        graph.add_node(node)

        config = GlobalConfig(
            node_types={"concept": NodeTypeConfig(font_family="Arial")}
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(graph, config, str(output_path))

            data = json.loads(output_path.read_text(encoding="utf-8"))

        text_element = next(
            element for element in data["elements"] if element["type"] == "text"
        )

        self.assertEqual(text_element["fontFamily"], 2)
        self.assertEqual(
            text_element["originalText"],
            ExcalidrawExporter().get_node_full_text(node),
        )
        self.assertNotEqual(text_element["text"], text_element["originalText"])
        self.assertGreater(
            text_element["text"].count("\n"),
            text_element["originalText"].count("\n"),
        )

    def test_exporter_offsets_initial_text_box_by_padding(self):
        graph = Graph()
        node = Node(
            id="node",
            label="Title",
            type="concept",
            width=220,
            height=120,
            metadata={"text": "Body text"},
        )
        graph.add_node(node)

        config = GlobalConfig(
            node_types={"concept": NodeTypeConfig(padding=14)}
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(graph, config, str(output_path))
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shape = next(
            element
            for element in data["elements"]
            if element["type"] in {"rectangle", "ellipse", "diamond"}
        )
        text_element = next(
            element for element in data["elements"] if element["type"] == "text"
        )

        self.assertEqual(
            text_element["x"],
            shape["x"] + (shape["width"] - text_element["width"]) / 2,
        )
        self.assertEqual(text_element["y"], shape["y"] + 5)

    def test_parent_child_line_edges_render_as_arrows(self):
        graph = Graph()
        root = Node(id="root", label="Root", x=100, y=100, width=120, height=60)
        child = Node(id="child", label="Child", x=320, y=100, width=120, height=60)
        graph.add_node(root)
        graph.add_node(child)
        graph.add_edge(
            Edge(
                source_id="root",
                target_id="child",
                connection_type=ConnectionType.LINE,
                edge_type="parent_child",
            )
        )

        config = GlobalConfig(
            edge_types={
                "parent_child": EdgeTypeConfig(
                    connection_type="line",
                    color="#000000",
                    arrow_end="arrow",
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(graph, config, str(output_path))
            data = json.loads(output_path.read_text(encoding="utf-8"))

        arrows = [element for element in data["elements"] if element["type"] == "arrow"]
        self.assertEqual(len(arrows), 1)

    def test_link_node_exports_external_and_internal_links(self):
        graph = Graph()
        topic = Node(id="topic", label="Topic", x=100, y=100, width=180, height=80)
        external = Node(
            id="ext",
            label="Docs",
            type="link",
            x=360,
            y=80,
            width=150,
            height=60,
            metadata={"target": "https://docs.snowflake.com/"},
        )
        internal = Node(
            id="jump",
            label="Jump",
            type="link",
            x=360,
            y=180,
            width=150,
            height=60,
            metadata={"target": "#topic"},
        )
        for node in [topic, external, internal]:
            graph.add_node(node)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(graph, GlobalConfig(), str(output_path))
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shapes = {
            element["customData"]["node_id"]: element
            for element in data["elements"]
            if element["type"] in {"rectangle", "ellipse", "diamond"}
        }

        self.assertEqual(shapes["ext"]["link"], "https://docs.snowflake.com/")
        self.assertEqual(
            shapes["jump"]["link"],
            f"https://excalidraw.com/?element={shapes['topic']['id']}",
        )

    def test_full_refresh_rebuilds_tree_layout_but_keeps_saved_sizes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps(
                    {
                        "parser_type": "md",
                        "layout": {
                            "direction": "left-right",
                            "level_spacing": 140,
                            "sibling_spacing": 20,
                            "root_spacing": 80,
                            "start_x": 100,
                            "start_y": 100,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (folder / "node_config.json").write_text("{}", encoding="utf-8")
            (folder / "edge_config.json").write_text(
                json.dumps(
                    {
                        "parent_child": {
                            "connection_type": "line",
                            "arrow_end": "arrow",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (folder / "diagram.md").write_text(
                "## Root {#root}\n\n### Child {#child}\n",
                encoding="utf-8",
            )
            (folder / "positions.json").write_text(
                json.dumps(
                    {
                        "root": {
                            "x": 50,
                            "y": 60,
                            "width": 300,
                            "height": 80,
                            "text_x": 999,
                            "text_y": 999,
                            "text_width": 1,
                            "text_height": 1,
                        },
                        "child": {
                            "x": 400,
                            "y": 500,
                            "width": 200,
                            "height": 40,
                            "text_x": 999,
                            "text_y": 999,
                            "text_width": 1,
                            "text_height": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )

            output_path = ExcaliBuilder().build_from_folder(str(folder), full_refresh=True)

            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            shapes = {
                element["customData"]["node_id"]: element
                for element in data["elements"]
                if element["type"] in {"rectangle", "ellipse", "diamond"}
            }

            root = shapes["root"]
            child = shapes["child"]

            self.assertEqual((root["width"], root["height"]), (300, 80))
            self.assertEqual((child["width"], child["height"]), (200, 40))
            self.assertEqual((root["x"], root["y"]), (100, 100))
            self.assertEqual((child["x"], child["y"]), (540, 120))

            text_elements = {
                element["customData"]["node_id"]: element
                for element in data["elements"]
                if element["type"] == "text"
            }
            self.assertNotEqual(text_elements["root"]["x"], 999)
            self.assertNotEqual(text_elements["root"]["y"], 999)


if __name__ == "__main__":
    unittest.main()
