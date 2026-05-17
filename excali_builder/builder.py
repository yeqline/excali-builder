"""Main builder class for creating Excalidraw diagrams from source files."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config.loader import ConfigLoader
from .config.schema import GlobalConfig
from .core.edge import ConnectionType
from .core.graph import Graph
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

        # 6. Export to Excalidraw JSON
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
