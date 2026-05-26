"""Main builder class for creating Excalidraw diagrams from source files."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .config.loader import ConfigLoader
from .config.schema import GlobalConfig
from .core.edge import ConnectionType, Edge
from .core.graph import Graph
from .core.node import Node
from .excalidraw.exporter import ExcalidrawExporter
from .excalidraw.sync import ExcalidrawSync
from .layout.dag import DagLayout
from .layout.tree import TreeLayout
from .parsers.csv import CSVParser
from .parsers.dbt import DbtManifestParser
from .parsers.markdown import MarkdownParser
from .parsers.registry import ParserRegistry


class ExcaliBuilder:
    """Main builder class for creating and syncing Excalidraw diagrams."""

    def __init__(self, global_config_path: Optional[str] = None):
        """Initialize the builder with parser registry and exporter."""
        self.parser_registry = ParserRegistry()
        self.exporter = ExcalidrawExporter()
        self.sync = ExcalidrawSync()

        # Register default parsers
        self.parser_registry.register("csv", CSVParser)
        self.parser_registry.register("dbt", DbtManifestParser)
        self.parser_registry.register("manifest", DbtManifestParser)
        self.parser_registry.register("md", MarkdownParser)
        self.parser_registry.register("markdown", MarkdownParser)

    def build_from_folder(self, folder_path: str, full_refresh: bool = False) -> str:
        """Build Excalidraw diagram from source files in folder.

        Args:
            folder_path: Source folder containing config and content files.
            full_refresh: When True, ignore saved x/y positions and rebuild layout
                from scratch while still reusing saved sizes and text alignment.
        """
        folder = Path(folder_path)

        # 1. Detect input format from config.json
        config_path = folder / "config.json"
        parser_type = "csv"  # default
        parser_options: Dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                parser_type = config_data.get("parser_type", "csv")
                parser_options = config_data.get("parser_options", {})
                if not isinstance(parser_options, dict):
                    raise ValueError("config.json field 'parser_options' must be an object")

        # 2. Parse input files -> Graph
        parser_class = self.parser_registry.get_parser(parser_type)
        if not parser_class:
            raise ValueError(f"Unknown parser type: {parser_type}")

        parser = parser_class()
        graph = parser.parse(folder, parser_options)

        # 3. Load configuration
        config = ConfigLoader.load_from_folder(folder)

        # 4. Load positions.json from folder if exists
        positions_data = self._load_positions_data(folder)
        self._apply_saved_geometry(graph, positions_data, full_refresh=full_refresh)

        # 5. For new nodes (without positions), apply deterministic tree layout
        self._apply_layout_to_new_nodes(graph, config)

        # 6. Replace configured overlong line edges with local jump links.
        generated_link_node_ids = self._replace_long_line_edges_with_link_nodes(graph, config)
        if generated_link_node_ids:
            ConfigLoader.ensure_graph_config(folder, graph)
            config = ConfigLoader.load_from_folder(folder)
            ConfigLoader.apply_config_to_graph(graph, config)
            self._apply_saved_geometry_to_nodes(
                graph,
                positions_data,
                generated_link_node_ids,
                full_refresh=full_refresh,
            )
            self._position_long_line_link_nodes(graph, config, generated_link_node_ids)

        # 7. Export to Excalidraw JSON
        output_path = folder / "output.excalidraw"
        self.exporter.export(graph, config, str(output_path))

        return str(output_path)

    def sync_from_folder(self, folder_path: str) -> None:
        """Sync positions from Excalidraw file to positions.json."""
        folder = Path(folder_path)
        self.sync.sync_from_folder(folder)

    def _load_positions_data(self, folder: Path) -> Dict[str, Dict[str, Any]]:
        """Load saved node geometry from positions.json if it exists."""
        positions_path = folder / "positions.json"
        if not positions_path.exists():
            return {}

        with open(positions_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _apply_saved_geometry(
        self,
        graph: Graph,
        positions_data: Dict[str, Dict[str, Any]],
        full_refresh: bool = False,
    ) -> None:
        """Apply saved geometry to matching nodes.

        In full refresh mode, widths and heights are reused but x/y positions are
        intentionally ignored so layout starts from scratch.
        """
        for node_id, geometry in positions_data.items():
            if node_id not in graph.nodes:
                continue

            node = graph.nodes[node_id]
            self._apply_saved_geometry_to_node(node, geometry, full_refresh=full_refresh)

    def _apply_saved_geometry_to_nodes(
        self,
        graph: Graph,
        positions_data: Dict[str, Dict[str, Any]],
        node_ids: Sequence[str],
        full_refresh: bool = False,
    ) -> None:
        """Apply saved geometry to a subset of graph nodes."""
        for node_id in node_ids:
            if node_id not in graph.nodes or node_id not in positions_data:
                continue
            self._apply_saved_geometry_to_node(
                graph.nodes[node_id],
                positions_data[node_id],
                full_refresh=full_refresh,
            )

    def _apply_saved_geometry_to_node(
        self,
        node: Node,
        geometry: Dict[str, Any],
        full_refresh: bool = False,
    ) -> None:
        """Apply saved geometry to one graph node."""
        if not full_refresh:
            node.x = geometry.get("x")
            node.y = geometry.get("y")
        node.width = geometry.get("width")
        node.height = geometry.get("height")

        if node.metadata is None:
            node.metadata = {}
        if "textAlign" in geometry:
            node.metadata["text_align"] = geometry["textAlign"]
        if "verticalAlign" in geometry:
            node.metadata["vertical_align"] = geometry["verticalAlign"]
        if "fontSize" in geometry:
            node.metadata["font_size"] = geometry["fontSize"]
        if "wrapped_text" in geometry:
            node.metadata["saved_wrapped_text"] = geometry["wrapped_text"]
        if "wrapped_original_text" in geometry:
            node.metadata["saved_wrapped_original_text"] = geometry["wrapped_original_text"]
        if not full_refresh:
            if "text_x" in geometry:
                node.metadata["text_x"] = geometry["text_x"]
            if "text_y" in geometry:
                node.metadata["text_y"] = geometry["text_y"]
            if "text_width" in geometry:
                node.metadata["text_width"] = geometry["text_width"]
            if "text_height" in geometry:
                node.metadata["text_height"] = geometry["text_height"]

    def _apply_layout_to_new_nodes(self, graph: Graph, config: GlobalConfig) -> None:
        """Apply tree layout to nodes that do not already have positions."""
        for node in graph.nodes.values():
            if node.width is None or node.height is None:
                node_config = ConfigLoader.get_node_config(config, node.type)
                measured_width, measured_height = self.exporter.measure_node(
                    node,
                    node_config,
                )
                if node.width is None:
                    node.width = measured_width
                if node.height is None:
                    node.height = measured_height

        if not all(node.x is not None and node.y is not None for node in graph.nodes.values()):
            layout_config = {
                "direction": config.layout.direction,
                "level_spacing": config.layout.level_spacing,
                "sibling_spacing": config.layout.sibling_spacing,
                "root_spacing": config.layout.root_spacing,
                "start_x": config.layout.start_x,
                "start_y": config.layout.start_y,
                "rank_edge_types": config.layout.rank_edge_types,
            }

            algorithm = (config.layout.algorithm or "tree").strip().lower()
            if algorithm == "tree":
                TreeLayout().apply_layout(graph, layout_config)
            elif algorithm == "dag":
                DagLayout().apply_layout(graph, layout_config)
            else:
                raise ValueError(f"Unknown layout algorithm: {config.layout.algorithm}")

        self._apply_enclosing_group_layout(graph, config)

    def _apply_enclosing_group_layout(self, graph: Graph, config: GlobalConfig) -> None:
        """Resize enclosing group parents around their positioned children."""
        children_by_parent: Dict[str, List[str]] = {}
        padding_by_parent: Dict[str, int] = {}
        for edge in graph.edges:
            if edge.connection_type != ConnectionType.ENCLOSING_GROUP:
                continue
            if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
                continue

            children_by_parent.setdefault(edge.source_id, []).append(edge.target_id)
            edge_config = ConfigLoader.get_edge_type_config(config, edge.edge_type)
            padding = (
                edge_config.group_padding
                if edge_config and edge_config.group_padding is not None
                else 48
            )
            padding_by_parent[edge.source_id] = max(
                padding_by_parent.get(edge.source_id, 0),
                padding,
            )

        if not children_by_parent:
            return

        positioned: Set[str] = set()
        visiting: Set[str] = set()

        def place_parent(parent_id: str) -> None:
            if parent_id in positioned or parent_id in visiting:
                return
            visiting.add(parent_id)

            for child_id in sorted(children_by_parent.get(parent_id, [])):
                if child_id in children_by_parent:
                    place_parent(child_id)

            parent = graph.nodes[parent_id]
            children = [
                graph.nodes[child_id]
                for child_id in children_by_parent.get(parent_id, [])
                if child_id in graph.nodes
                and graph.nodes[child_id].x is not None
                and graph.nodes[child_id].y is not None
            ]
            if children:
                min_x = min(child.x or 0 for child in children)
                min_y = min(child.y or 0 for child in children)
                max_x = max((child.x or 0) + (child.width or 100) for child in children)
                max_y = max((child.y or 0) + (child.height or 50) for child in children)

                padding = padding_by_parent.get(parent_id, 48)
                node_config = ConfigLoader.get_node_config(config, parent.type)
                header_height = max(node_config.font_size + node_config.padding * 2, 48)
                min_width = parent.width or 100
                min_height = parent.height or header_height

                parent.x = min_x - padding
                parent.y = min_y - padding - header_height
                parent.width = max(min_width, (max_x - min_x) + padding * 2)
                parent.height = max(
                    min_height,
                    (max_y - min_y) + padding * 2 + header_height,
                )
                if parent.metadata is None:
                    parent.metadata = {}
                for metadata_key in (
                    "saved_wrapped_text",
                    "saved_wrapped_original_text",
                    "text_x",
                    "text_y",
                    "text_width",
                    "text_height",
                ):
                    parent.metadata.pop(metadata_key, None)

            visiting.remove(parent_id)
            positioned.add(parent_id)

        for parent_id in sorted(children_by_parent):
            place_parent(parent_id)

    def _replace_long_line_edges_with_link_nodes(
        self,
        graph: Graph,
        config: GlobalConfig,
    ) -> List[str]:
        """Replace configured overlong line edges with two internal link nodes."""
        generated_node_ids: List[str] = []
        retained_edges: List[Edge] = []

        for edge in graph.edges:
            if not self._should_replace_line_edge(graph, config, edge):
                retained_edges.append(edge)
                continue

            source_node = graph.nodes[edge.source_id]
            target_node = graph.nodes[edge.target_id]
            source_link_id, target_link_id = self._get_long_line_link_node_ids(edge)
            self._add_long_line_link_node(
                graph,
                source_link_id,
                anchor_node=source_node,
                target_node=target_node,
                edge=edge,
                side="source",
            )
            self._add_long_line_link_node(
                graph,
                target_link_id,
                anchor_node=target_node,
                target_node=source_node,
                edge=edge,
                side="target",
            )
            generated_node_ids.extend([source_link_id, target_link_id])

        graph.edges = retained_edges
        return generated_node_ids

    def _should_replace_line_edge(
        self,
        graph: Graph,
        config: GlobalConfig,
        edge: Edge,
    ) -> bool:
        """Return whether a line edge exceeds its configured maximum length."""
        if edge.connection_type != ConnectionType.LINE:
            return False
        if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
            return False

        edge_config = ConfigLoader.get_edge_type_config(config, edge.edge_type)
        if not edge_config or edge_config.max_length is None:
            return False
        if edge_config.max_length <= 0:
            return False

        source_node = graph.nodes[edge.source_id]
        target_node = graph.nodes[edge.target_id]
        if source_node.x is None or source_node.y is None:
            return False
        if target_node.x is None or target_node.y is None:
            return False

        return self._center_distance(source_node, target_node) > edge_config.max_length

    def _add_long_line_link_node(
        self,
        graph: Graph,
        node_id: str,
        anchor_node: Node,
        target_node: Node,
        edge: Edge,
        side: str,
    ) -> None:
        """Add one generated internal-link node for an overlong line edge."""
        if node_id in graph.nodes:
            return

        graph.add_node(
            Node(
                id=node_id,
                label=f"To {target_node.label}",
                type="link",
                metadata={
                    "target": f"#{target_node.id}",
                    "long_line_anchor_id": anchor_node.id,
                    "long_line_target_id": target_node.id,
                    "long_line_edge_type": edge.edge_type,
                    "long_line_side": side,
                    "source_order": len(graph.nodes),
                },
            )
        )

    def _position_long_line_link_nodes(
        self,
        graph: Graph,
        config: GlobalConfig,
        node_ids: Sequence[str],
    ) -> None:
        """Measure and place generated long-line link nodes that lack positions."""
        for node_id in node_ids:
            node = graph.nodes.get(node_id)
            if not node:
                continue

            if node.width is None or node.height is None:
                node_config = ConfigLoader.get_node_config(config, node.type)
                measured_width, measured_height = self.exporter.measure_node(node, node_config)
                if node.width is None:
                    node.width = measured_width
                if node.height is None:
                    node.height = measured_height

            if node.x is not None and node.y is not None:
                continue

            anchor_id = (node.metadata or {}).get("long_line_anchor_id")
            target_id = (node.metadata or {}).get("long_line_target_id")
            if anchor_id not in graph.nodes or target_id not in graph.nodes:
                continue

            anchor_node = graph.nodes[anchor_id]
            target_node = graph.nodes[target_id]
            node.x, node.y = self._default_long_line_link_position(
                node,
                anchor_node,
                target_node,
            )

    def _default_long_line_link_position(
        self,
        link_node: Node,
        anchor_node: Node,
        target_node: Node,
    ) -> Tuple[float, float]:
        """Place a generated link node near the anchor, facing the remote node."""
        anchor_center_x, anchor_center_y = self._node_center(anchor_node)
        target_center_x, target_center_y = self._node_center(target_node)
        dx = target_center_x - anchor_center_x
        dy = target_center_y - anchor_center_y
        distance = math.hypot(dx, dy) or 1.0
        unit_x = dx / distance
        unit_y = dy / distance

        anchor_width = anchor_node.width or 100
        anchor_height = anchor_node.height or 50
        link_width = link_node.width or 100
        link_height = link_node.height or 50
        offset = max(anchor_width, anchor_height) / 2 + 48

        center_x = anchor_center_x + unit_x * offset
        center_y = anchor_center_y + unit_y * offset
        return center_x - link_width / 2, center_y - link_height / 2

    def _center_distance(self, source_node: Node, target_node: Node) -> float:
        """Return center-to-center distance between two positioned nodes."""
        source_x, source_y = self._node_center(source_node)
        target_x, target_y = self._node_center(target_node)
        return math.hypot(target_x - source_x, target_y - source_y)

    def _node_center(self, node: Node) -> Tuple[float, float]:
        """Return node center using current geometry."""
        return (
            (node.x or 0) + (node.width or 100) / 2,
            (node.y or 0) + (node.height or 50) / 2,
        )

    def _get_long_line_link_node_ids(self, edge: Edge) -> Tuple[str, str]:
        """Return stable generated node IDs for one overlong line edge."""
        key = f"{edge.edge_type}\n{edge.source_id}\n{edge.target_id}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return (
            f"long_line_link.{digest}.source",
            f"long_line_link.{digest}.target",
        )
