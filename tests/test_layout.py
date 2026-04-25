import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from excali_builder.builder import ExcaliBuilder
from excali_builder.config.loader import ConfigLoader
from excali_builder.config.schema import EdgeTypeConfig, GlobalConfig, LayoutConfig, NodeTypeConfig
from excali_builder.core.edge import ConnectionType, Edge
from excali_builder.core.graph import Graph
from excali_builder.core.node import Node
from excali_builder.excalidraw.exporter import ExcalidrawExporter
from excali_builder.parsers.markdown import MarkdownParser


def _write_png(path: Path, width: int, height: int) -> None:
    """Write a small RGBA PNG for image-export tests."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def build_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(chunk_data))
            + chunk_type
            + chunk_data
            + struct.pack(">I", checksum)
        )

    row = b"\x00" + (b"\x33\x66\x99\xff" * width)
    payload = zlib.compress(row * height)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + build_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + build_chunk(b"IDAT", payload)
        + build_chunk(b"IEND", b"")
    )
    path.write_bytes(png_bytes)


def _build_explicit_config(node_types=None, edge_types=None, layout=None) -> GlobalConfig:
    """Return a config with fully explicit node and edge entries for tests."""
    explicit_node_types = {}
    for node_type in node_types or []:
        explicit_node_types[node_type] = NodeTypeConfig(
            **ConfigLoader._get_node_type_template(node_type)
        )

    explicit_edge_types = {}
    for edge_type in edge_types or []:
        explicit_edge_types[edge_type] = EdgeTypeConfig(
            **ConfigLoader._get_edge_type_template(edge_type)
        )

    config_kwargs = {
        "node_types": explicit_node_types,
        "edge_types": explicit_edge_types,
    }
    if layout is not None:
        config_kwargs["layout"] = layout
    return GlobalConfig(**config_kwargs)


class LayoutRegressionTests(unittest.TestCase):
    def test_markdown_directive_syntax_sets_meta_and_explicit_edges(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Review Pane {#review-pane}",
                        "> type: concept",
                        "> edge.related: review-pane-mirrors-git",
                        "> edge.contrasts: ide-approval-loop",
                        "",
                        "The review pane reflects the repository state.",
                        "",
                        "## Git Review {#review-pane-mirrors-git}",
                        "Body.",
                        "",
                        "## IDE Approval Loop {#ide-approval-loop}",
                        "Body.",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        review_pane = graph.nodes["review-pane"]
        edge_pairs = sorted(
            (edge.edge_type, edge.source_id, edge.target_id)
            for edge in graph.edges
        )

        self.assertEqual(review_pane.type, "concept")
        self.assertEqual(
            review_pane.metadata["content"],
            "The review pane reflects the repository state.",
        )
        self.assertEqual(
            edge_pairs,
            [
                ("contrasts", "review-pane", "ide-approval-loop"),
                ("related", "review-pane", "review-pane-mirrors-git"),
            ],
        )

    def test_markdown_comment_node_gets_default_comment_edge_to_parent(self):
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
                        "### Reviewer Note {#reviewer-note}",
                        "> type: comment",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(graph.edges[0].edge_type, "comment")
        self.assertEqual(
            (graph.edges[0].source_id, graph.edges[0].target_id),
            ("topic", "reviewer-note"),
        )
        self.assertEqual(
            [node.id for node in graph.get_hierarchy_children("topic")],
            ["reviewer-note"],
        )

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
                        "> type: link",
                        "> target: #topic",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(graph.nodes["jump"].metadata["target"], "#topic")

    def test_markdown_link_node_bare_internal_target_is_validated(self):
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
                        "> type: link",
                        "> target: topic",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(graph.nodes["jump"].metadata["target"], "topic")

    def test_markdown_inline_image_becomes_attachment_and_is_removed_from_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            image_path = folder / "media" / "flow.png"
            _write_png(image_path, width=40, height=20)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Topic {#topic}",
                        "",
                        "Before ![Flow](media/flow.png) after.",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        topic = graph.nodes["topic"]
        image_node = graph.nodes["topic-image-media-flow-png-1"]
        image_edges = [edge for edge in graph.edges if edge.target_id == image_node.id]

        self.assertEqual(topic.metadata["content"], "Before after.")
        self.assertEqual(image_node.type, "image")
        self.assertEqual(image_node.label, "Flow")
        self.assertEqual(image_node.metadata["src"], "media/flow.png")
        self.assertEqual(image_node.metadata["natural_width"], 40)
        self.assertEqual(image_node.metadata["natural_height"], 20)
        self.assertEqual(len(image_edges), 1)
        self.assertEqual(image_edges[0].edge_type, "attachment")
        self.assertEqual(image_edges[0].connection_type, ConnectionType.CONTAINER)

    def test_parse_bootstraps_missing_used_types_into_config_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            image_path = folder / "media" / "flow.png"
            _write_png(image_path, width=24, height=12)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Topic {#topic}",
                        "",
                        "Body ![Flow](media/flow.png)",
                        "",
                        "### Note {#note}",
                        "> type: comment",
                    ]
                ),
                encoding="utf-8",
            )

            MarkdownParser().parse(folder, {})

            node_config = json.loads((folder / "node_config.json").read_text(encoding="utf-8"))
            edge_config = json.loads((folder / "edge_config.json").read_text(encoding="utf-8"))

        self.assertIn("concept", node_config)
        self.assertIn("image", node_config)
        self.assertIn("comment", node_config)
        self.assertEqual(node_config["image"]["borderRadius"], 12)
        self.assertIn("attachment", edge_config)
        self.assertIn("comment", edge_config)
        self.assertEqual(edge_config["attachment"]["connection_type"], "container")

    def test_parse_reads_attachment_connection_type_from_written_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            image_path = folder / "media" / "flow.png"
            _write_png(image_path, width=24, height=12)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Topic {#topic}",
                        "",
                        "Body ![Flow](media/flow.png)",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})
            attachment_edge = next(edge for edge in graph.edges if edge.edge_type == "attachment")
            self.assertEqual(attachment_edge.connection_type, ConnectionType.CONTAINER)

            edge_config_path = folder / "edge_config.json"
            edge_config = json.loads(edge_config_path.read_text(encoding="utf-8"))
            edge_config["attachment"]["connection_type"] = "line"
            edge_config_path.write_text(json.dumps(edge_config, indent=2) + "\n", encoding="utf-8")

            reparsed_graph = MarkdownParser().parse(folder, {})

        reparsed_attachment_edge = next(
            edge for edge in reparsed_graph.edges if edge.edge_type == "attachment"
        )
        self.assertEqual(reparsed_attachment_edge.connection_type, ConnectionType.LINE)

    def test_markdown_parent_can_have_normal_children_and_a_procedure_child(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Release Management {#release-management}",
                        "",
                        "### Monitoring {#monitoring}",
                        "> type: concept",
                        "",
                        "### Deploy Service {#deploy-service}",
                        "> type: procedure",
                        "",
                        "#### Check Secrets {#deploy-check-secrets}",
                        "> type: step",
                        "> edge.next: deploy-build-image",
                        "",
                        "#### Build Image {#deploy-build-image}",
                        "> type: step",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(
            [node.id for node in graph.get_hierarchy_children("release-management")],
            ["monitoring", "deploy-service"],
        )
        self.assertEqual(
            [node.id for node in graph.get_hierarchy_children("deploy-service")],
            ["deploy-check-secrets", "deploy-build-image"],
        )

        procedure_edges = [
            edge
            for edge in graph.edges
            if edge.edge_type == "procedure_step"
        ]
        self.assertEqual(len(procedure_edges), 2)
        self.assertTrue(
            all(edge.connection_type == ConnectionType.CONTAINER for edge in procedure_edges)
        )
        self.assertEqual(
            [
                (edge.source_id, edge.target_id)
                for edge in graph.edges
                if edge.edge_type == "next"
            ],
            [("deploy-check-secrets", "deploy-build-image")],
        )

    def test_markdown_next_edge_must_stay_within_one_procedure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "doc.md").write_text(
                "\n".join(
                    [
                        "## Root {#root}",
                        "",
                        "### Procedure A {#procedure-a}",
                        "> type: procedure",
                        "",
                        "#### Step A {#step-a}",
                        "> type: step",
                        "> edge.next: step-b",
                        "",
                        "### Procedure B {#procedure-b}",
                        "> type: procedure",
                        "",
                        "#### Step B {#step-b}",
                        "> type: step",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must stay within one procedure"):
                MarkdownParser().parse(folder, {})

    def test_legacy_meta_and_edges_forms_are_treated_as_content(self):
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
                        "> [!meta]",
                        "> type: warning",
                        "",
                        "```edges",
                        "related: other-node",
                        "```",
                        "",
                        "## Other {#other-node}",
                        "Body.",
                    ]
                ),
                encoding="utf-8",
            )

            graph = MarkdownParser().parse(folder, {})

        self.assertEqual(graph.nodes["topic"].type, "concept")
        self.assertFalse(
            any(edge.source_id == "topic" and edge.target_id == "other-node" for edge in graph.edges)
        )
        self.assertIn("> [!meta]", graph.nodes["topic"].metadata["content"])

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

        config = _build_explicit_config(
            node_types=["default"],
            edge_types=["parent_child"],
            layout=LayoutConfig(
                direction="left-right",
                level_spacing=150,
                sibling_spacing=20,
                root_spacing=80,
                start_x=100,
                start_y=100,
            ),
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

        config = _build_explicit_config(
            node_types=["default"],
            edge_types=["parent_child"],
            layout=LayoutConfig(
                direction="left-right",
                level_spacing=140,
                sibling_spacing=20,
                start_x=100,
                start_y=100,
            ),
        )
        config.edge_types["parent_child"] = EdgeTypeConfig(
            **{
                **ConfigLoader._get_edge_type_template("parent_child"),
                "connection_type": "container",
            }
        )

        ExcaliBuilder()._apply_layout_to_new_nodes(graph, config)

        self.assertEqual((root.x, root.y), (40, 60))
        self.assertEqual((child.x, child.y), (300, 70))

    def test_procedure_layout_orders_steps_by_next_chain(self):
        graph = Graph()
        procedure = Node(
            id="deploy-service",
            label="Deploy Service",
            type="procedure",
            width=100,
            height=50,
        )
        step_b = Node(
            id="build-image",
            label="Build Image",
            type="step",
            width=100,
            height=50,
            metadata={"hierarchy_parent_id": "deploy-service", "source_order": 1},
        )
        step_c = Node(
            id="push-image",
            label="Push Image",
            type="step",
            width=100,
            height=50,
            metadata={"hierarchy_parent_id": "deploy-service", "source_order": 2},
        )
        step_a = Node(
            id="check-secrets",
            label="Check Secrets",
            type="step",
            width=100,
            height=50,
            metadata={"hierarchy_parent_id": "deploy-service", "source_order": 3},
        )

        for node in [procedure, step_b, step_c, step_a]:
            graph.add_node(node)

        for step_id in ["build-image", "push-image", "check-secrets"]:
            graph.add_edge(
                Edge(
                    source_id="deploy-service",
                    target_id=step_id,
                    connection_type=ConnectionType.CONTAINER,
                    edge_type="procedure_step",
                )
            )

        graph.add_edge(
            Edge(
                source_id="check-secrets",
                target_id="build-image",
                connection_type=ConnectionType.LINE,
                edge_type="next",
            )
        )
        graph.add_edge(
            Edge(
                source_id="build-image",
                target_id="push-image",
                connection_type=ConnectionType.LINE,
                edge_type="next",
            )
        )

        config = _build_explicit_config(
            node_types=["procedure", "step"],
            edge_types=["procedure_step", "next"],
            layout=LayoutConfig(
                direction="left-right",
                level_spacing=150,
                sibling_spacing=20,
                root_spacing=80,
                start_x=100,
                start_y=100,
            )
        )

        ExcaliBuilder()._apply_layout_to_new_nodes(graph, config)

        self.assertEqual((procedure.x, procedure.y), (100, 170))
        self.assertEqual((step_a.x, step_a.y), (350, 100))
        self.assertEqual((step_b.x, step_b.y), (350, 170))
        self.assertEqual((step_c.x, step_c.y), (350, 240))

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
            type="concept",
            width=160,
            height=80,
            metadata={"text": " ".join(["body"] * 25)},
        )
        graph.add_node(node)

        config = _build_explicit_config(node_types=["concept"])
        config.node_types["concept"] = NodeTypeConfig(
            **{
                **ConfigLoader._get_node_type_template("concept"),
                "font_family": "Arial",
            }
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

        config = _build_explicit_config(node_types=["concept"])
        config.node_types["concept"] = NodeTypeConfig(
            **{
                **ConfigLoader._get_node_type_template("concept"),
                "padding": 14,
            }
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

    def test_sync_preserves_resized_bound_text_wrap_on_rebuild(self):
        full_text = (
            "Git Review Model\n"
            "The app's review experience is a Git workflow, not a pre-edit approval workflow."
        )
        wrapped_text = (
            "Git Review Model\n"
            "The app's review experience is a\n"
            "Git workflow, not a pre-edit\n"
            "approval workflow."
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "diagram.md").write_text(
                "\n".join(
                    [
                        "## Git Review Model {#git-review-model}",
                        "",
                        "The app's review experience is a Git workflow, not a pre-edit approval workflow.",
                    ]
                ),
                encoding="utf-8",
            )
            (folder / "output.excalidraw").write_text(
                json.dumps(
                    {
                        "type": "excalidraw",
                        "version": 2,
                        "source": "test",
                        "elements": [
                            {
                                "id": "shape",
                                "type": "rectangle",
                                "x": 50,
                                "y": 60,
                                "width": 300,
                                "height": 80,
                                "customData": {"node_id": "git-review-model"},
                            },
                            {
                                "id": "text",
                                "type": "text",
                                "x": 70,
                                "y": 65,
                                "width": 260,
                                "height": 60,
                                "text": wrapped_text,
                                "originalText": full_text,
                                "fontSize": 22,
                                "textAlign": "center",
                                "verticalAlign": "top",
                                "customData": {"node_id": "git-review-model"},
                            },
                        ],
                        "appState": {},
                        "files": {},
                    }
                ),
                encoding="utf-8",
            )

            builder = ExcaliBuilder()
            builder.sync_from_folder(str(folder))

            positions = json.loads((folder / "positions.json").read_text(encoding="utf-8"))
            self.assertEqual(
                positions["git-review-model"]["wrapped_text"],
                wrapped_text,
            )
            self.assertEqual(
                positions["git-review-model"]["wrapped_original_text"],
                full_text,
            )
            self.assertEqual(positions["git-review-model"]["fontSize"], 22)

            output_path = builder.build_from_folder(str(folder))
            data = json.loads(Path(output_path).read_text(encoding="utf-8"))

        text_element = next(
            element
            for element in data["elements"]
            if element["type"] == "text"
            and element["customData"]["node_id"] == "git-review-model"
        )
        shape_element = next(
            element
            for element in data["elements"]
            if element["type"] == "rectangle"
            and element["customData"]["node_id"] == "git-review-model"
        )

        self.assertEqual(text_element["text"], wrapped_text)
        self.assertEqual(text_element["originalText"], full_text)
        self.assertEqual(text_element["fontSize"], 22)
        self.assertEqual((shape_element["width"], shape_element["height"]), (300, 80))

    def test_build_recomputes_text_layout_when_source_text_changes(self):
        stale_wrapped_text = "Title\nOld body text"

        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "config.json").write_text(
                json.dumps({"parser_type": "md"}),
                encoding="utf-8",
            )
            (folder / "diagram.md").write_text(
                "\n".join(
                    [
                        "## Title {#title}",
                        "",
                        "Updated body text that should wrap differently once the source changes.",
                    ]
                ),
                encoding="utf-8",
            )
            (folder / "positions.json").write_text(
                json.dumps(
                    {
                        "title": {
                            "x": 50,
                            "y": 60,
                            "width": 220,
                            "height": 80,
                            "text_x": 999,
                            "text_y": 999,
                            "text_width": 1,
                            "text_height": 1,
                            "wrapped_text": stale_wrapped_text,
                            "wrapped_original_text": "Title\nOld body text",
                        }
                    }
                ),
                encoding="utf-8",
            )

            output_path = ExcaliBuilder().build_from_folder(str(folder))
            data = json.loads(Path(output_path).read_text(encoding="utf-8"))

        text_element = next(
            element
            for element in data["elements"]
            if element["type"] == "text" and element["customData"]["node_id"] == "title"
        )

        self.assertNotEqual(text_element["text"], stale_wrapped_text)
        self.assertEqual(
            text_element["originalText"],
            "Title\nUpdated body text that should wrap differently once the source changes.",
        )
        self.assertNotEqual(text_element["x"], 999)
        self.assertNotEqual(text_element["y"], 999)
        self.assertNotEqual(text_element["width"], 1)
        self.assertNotEqual(text_element["height"], 1)

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

        config = _build_explicit_config(
            node_types=["default"],
            edge_types=["parent_child"],
        )
        config.edge_types["parent_child"] = EdgeTypeConfig(
            **{
                **ConfigLoader._get_edge_type_template("parent_child"),
                "connection_type": "line",
                "color": "#000000",
                "arrow_end": "arrow",
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(graph, config, str(output_path))
            data = json.loads(output_path.read_text(encoding="utf-8"))

        arrows = [element for element in data["elements"] if element["type"] == "arrow"]
        self.assertEqual(len(arrows), 1)

    def test_comment_edges_use_built_in_annotation_style(self):
        graph = Graph()
        root = Node(id="root", label="Root", x=100, y=100, width=120, height=60)
        note = Node(
            id="note",
            label="Reviewer Note",
            type="comment",
            x=320,
            y=100,
            width=160,
            height=70,
        )
        graph.add_node(root)
        graph.add_node(note)
        graph.add_edge(
            Edge(
                source_id="root",
                target_id="note",
                connection_type=ConnectionType.LINE,
                edge_type="comment",
            )
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(
                graph,
                _build_explicit_config(node_types=["default", "comment"], edge_types=["comment"]),
                str(output_path),
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shape = next(
            element
            for element in data["elements"]
            if element["type"] == "rectangle"
            and element["customData"]["node_id"] == "note"
        )
        arrow = next(element for element in data["elements"] if element["type"] == "arrow")

        self.assertEqual(shape["strokeColor"], "#57534E")
        self.assertEqual(shape["backgroundColor"], "#FAF7F2")
        self.assertEqual(arrow["strokeColor"], "#78716C")
        self.assertEqual(arrow["strokeStyle"], "dashed")
        self.assertIsNone(arrow["endArrowhead"])

    def test_exporter_writes_image_elements_and_binary_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            image_path = folder / "media" / "flow.png"
            _write_png(image_path, width=40, height=20)

            graph = Graph()
            topic = Node(id="topic", label="Topic", x=100, y=100, width=180, height=80)
            image_node = Node(
                id="topic-image-media-flow-png-1",
                label="Flow",
                type="image",
                x=340,
                y=120,
                metadata={
                    "src": "media/flow.png",
                    "mime_type": "image/png",
                    "natural_width": 40,
                    "natural_height": 20,
                    "hierarchy_parent_id": "topic",
                },
            )
            graph.add_node(topic)
            graph.add_node(image_node)
            graph.add_edge(
                Edge(
                    source_id="topic",
                    target_id=image_node.id,
                    connection_type=ConnectionType.CONTAINER,
                    edge_type="attachment",
                )
            )

            output_path = folder / "output.excalidraw"
            ExcalidrawExporter().export(
                graph,
                _build_explicit_config(node_types=["default", "image"], edge_types=["attachment"]),
                str(output_path),
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        image_element = next(
            element
            for element in data["elements"]
            if element["type"] == "image"
            and element["customData"]["node_id"] == "topic-image-media-flow-png-1"
        )
        topic_text = [
            element
            for element in data["elements"]
            if element["type"] == "text" and element["customData"]["node_id"] == "topic"
        ]
        image_text = [
            element
            for element in data["elements"]
            if element["type"] == "text"
            and element["customData"]["node_id"] == "topic-image-media-flow-png-1"
        ]

        self.assertEqual((image_element["width"], image_element["height"]), (40, 20))
        self.assertEqual(image_element["status"], "saved")
        self.assertTrue(topic_text)
        self.assertFalse(image_text)
        self.assertIn(image_element["fileId"], data["files"])
        self.assertEqual(data["files"][image_element["fileId"]]["mimeType"], "image/png")
        self.assertTrue(
            data["files"][image_element["fileId"]]["dataURL"].startswith("data:image/png;base64,")
        )

    def test_procedure_and_step_use_built_in_defaults_and_next_edge_style(self):
        graph = Graph()
        procedure = Node(
            id="deploy-service",
            label="Deploy Service",
            type="procedure",
            x=100,
            y=100,
            width=180,
            height=70,
        )
        step_a = Node(
            id="check-secrets",
            label="Check Secrets",
            type="step",
            x=360,
            y=80,
            width=160,
            height=60,
        )
        step_b = Node(
            id="build-image",
            label="Build Image",
            type="step",
            x=360,
            y=180,
            width=160,
            height=60,
        )
        for node in [procedure, step_a, step_b]:
            graph.add_node(node)

        graph.add_edge(
            Edge(
                source_id="deploy-service",
                target_id="check-secrets",
                connection_type=ConnectionType.CONTAINER,
                edge_type="procedure_step",
            )
        )
        graph.add_edge(
            Edge(
                source_id="deploy-service",
                target_id="build-image",
                connection_type=ConnectionType.CONTAINER,
                edge_type="procedure_step",
            )
        )
        graph.add_edge(
            Edge(
                source_id="check-secrets",
                target_id="build-image",
                connection_type=ConnectionType.LINE,
                edge_type="next",
            )
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(
                graph,
                _build_explicit_config(
                    node_types=["procedure", "step"],
                    edge_types=["procedure_step", "next"],
                ),
                str(output_path),
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shapes = {
            element["customData"]["node_id"]: element
            for element in data["elements"]
            if element["type"] == "rectangle"
        }
        arrows = [element for element in data["elements"] if element["type"] == "arrow"]

        self.assertEqual(shapes["deploy-service"]["strokeColor"], "#92400E")
        self.assertEqual(shapes["deploy-service"]["backgroundColor"], "#FEF3C7")
        self.assertEqual(shapes["check-secrets"]["strokeColor"], "#1F2937")
        self.assertEqual(shapes["check-secrets"]["backgroundColor"], "#F9FAFB")
        self.assertEqual(len(arrows), 1)
        self.assertEqual(arrows[0]["strokeColor"], "#2563EB")
        self.assertEqual(arrows[0]["endArrowhead"], "arrow")

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
            ExcalidrawExporter().export(
                graph,
                _build_explicit_config(node_types=["default", "link"]),
                str(output_path),
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shapes = {
            element["customData"]["node_id"]: element
            for element in data["elements"]
            if element["type"] in {"rectangle", "ellipse", "diamond"}
        }

        self.assertEqual(shapes["ext"]["link"], "https://docs.snowflake.com/")
        self.assertEqual(
            shapes["jump"]["link"],
            f"https://excalidraw.com/topic?element={shapes['topic']['id']}",
        )

    def test_link_node_exports_bare_internal_target_as_excalidraw_jump(self):
        graph = Graph()
        topic = Node(id="topic", label="Topic", x=100, y=100, width=180, height=80)
        jump = Node(
            id="jump",
            label="Jump",
            type="link",
            x=360,
            y=180,
            width=150,
            height=60,
            metadata={"target": "topic"},
        )
        for node in [topic, jump]:
            graph.add_node(node)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.excalidraw"
            ExcalidrawExporter().export(
                graph,
                _build_explicit_config(node_types=["default", "link"]),
                str(output_path),
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        shapes = {
            element["customData"]["node_id"]: element
            for element in data["elements"]
            if element["type"] in {"rectangle", "ellipse", "diamond"}
        }

        self.assertEqual(
            shapes["jump"]["link"],
            f"https://excalidraw.com/topic?element={shapes['topic']['id']}",
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
