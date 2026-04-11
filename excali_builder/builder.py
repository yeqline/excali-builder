"""Main builder class for creating Excalidraw diagrams from source files."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config.loader import ConfigLoader
from .config.schema import GlobalConfig
from .core.graph import Graph
from .excalidraw.exporter import ExcalidrawExporter
from .excalidraw.sync import ExcalidrawSync
from .layout.tree import TreeLayout
from .parsers.csv import CSVParser
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
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                parser_type = config_data.get("parser_type", "csv")

        # 2. Parse input files -> Graph
        parser_class = self.parser_registry.get_parser(parser_type)
        if not parser_class:
            raise ValueError(f"Unknown parser type: {parser_type}")

        parser = parser_class()
        graph = parser.parse(folder, {})

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

        if all(node.x is not None and node.y is not None for node in graph.nodes.values()):
            return

        TreeLayout().apply_layout(
            graph,
            {
                "direction": config.layout.direction,
                "level_spacing": config.layout.level_spacing,
                "sibling_spacing": config.layout.sibling_spacing,
                "root_spacing": config.layout.root_spacing,
                "start_x": config.layout.start_x,
                "start_y": config.layout.start_y,
            },
        )
