"""Main builder class for creating Excalidraw diagrams from source files."""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from .core.graph import Graph
from .core.node import Node
from .core.edge import ConnectionType
from .parsers.registry import ParserRegistry
from .parsers.csv import CSVParser
from .parsers.markdown import MarkdownParser
from .layout.radial import RadialLayout
from .layout.tree import TreeLayout
from .layout.positioner import Positioner
from .config.loader import ConfigLoader
from .config.schema import GlobalConfig
from .excalidraw.exporter import ExcalidrawExporter
from .excalidraw.sync import ExcalidrawSync


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

    def build_from_folder(self, folder_path: str) -> str:
        """Build Excalidraw diagram from source files in folder."""
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
        positions_path = folder / "positions.json"
        if positions_path.exists():
            with open(positions_path, "r", encoding="utf-8") as f:
                positions_data = json.load(f)
                # Apply geometry and text alignment to matching nodes
                for node_id, geometry in positions_data.items():
                    if node_id in graph.nodes:
                        node = graph.nodes[node_id]
                        node.x = geometry.get("x")
                        node.y = geometry.get("y")
                        node.width = geometry.get("width")
                        node.height = geometry.get("height")
                        # Store text alignment and geometry in metadata (always update from positions.json)
                        if node.metadata is None:
                            node.metadata = {}
                        if "textAlign" in geometry:
                            node.metadata["text_align"] = geometry["textAlign"]
                        if "verticalAlign" in geometry:
                            node.metadata["vertical_align"] = geometry["verticalAlign"]
                        # Store text element geometry (Excalidraw-calculated values)
                        if "text_x" in geometry:
                            node.metadata["text_x"] = geometry["text_x"]
                        if "text_y" in geometry:
                            node.metadata["text_y"] = geometry["text_y"]
                        if "text_width" in geometry:
                            node.metadata["text_width"] = geometry["text_width"]
                        if "text_height" in geometry:
                            node.metadata["text_height"] = geometry["text_height"]

        # 5. For new nodes (without positions), apply deterministic layout
        self._apply_layout_to_new_nodes(graph, config)

        # 6. Export to Excalidraw JSON
        output_path = folder / "output.excalidraw"
        self.exporter.export(graph, config, str(output_path))

        return str(output_path)

    def sync_from_folder(self, folder_path: str) -> None:
        """Sync positions from Excalidraw file to positions.json."""
        folder = Path(folder_path)
        self.sync.sync_from_folder(folder)

    def _apply_layout_to_new_nodes(self, graph: Graph, config: GlobalConfig) -> None:
        """Apply layout algorithm to nodes that don't have positions yet."""
        # First, ensure all nodes have default dimensions if missing
        # This is needed for proper positioning calculations
        for node in graph.nodes.values():
            if node.width is None:
                node.width = 100
            if node.height is None:
                node.height = 50

        # Separate nodes with and without positions
        nodes_with_positions = [
            node for node in graph.nodes.values() if node.x is not None and node.y is not None
        ]
        nodes_without_positions = [
            node for node in graph.nodes.values() if node.x is None or node.y is None
        ]

        if not nodes_without_positions:
            return

        # Use positioner for container-based connections
        # Extract container connections from unified edge_types config
        container_connections = {}
        for edge_type, edge_config in config.edge_types.items():
            if edge_config.connection_type == "container":
                container_connections[edge_type] = ConfigLoader.get_container_config(
                    config, edge_type
                )
        positioner = Positioner(container_connections)

        # First, handle container-based positioning
        # Process parents that already have positions
        for node in nodes_with_positions:
            # Find container edges from this node
            container_edges = [
                edge
                for edge in graph.edges
                if edge.connection_type == ConnectionType.CONTAINER
                and edge.source_id == node.id
            ]

            for edge in container_edges:
                parent = graph.nodes.get(edge.source_id)
                if parent and (parent.x is not None and parent.y is not None):
                    parent_node_config = ConfigLoader.get_node_config(config, parent.type)
                    positioner.position_container_children(graph, parent, edge.edge_type, parent_node_config)
        
        # Also process any container parents that might have been positioned by layout
        # This handles cases where parent was unpositioned but got positioned by general layout
        all_positioned_nodes = [
            node for node in graph.nodes.values() if node.x is not None and node.y is not None
        ]
        for node in all_positioned_nodes:
            # Find container edges from this node
            container_edges = [
                edge
                for edge in graph.edges
                if edge.connection_type == ConnectionType.CONTAINER
                and edge.source_id == node.id
            ]
            for edge in container_edges:
                parent = graph.nodes.get(edge.source_id)
                if parent:
                    parent_node_config = ConfigLoader.get_node_config(config, parent.type)
                    positioner.position_container_children(graph, parent, edge.edge_type, parent_node_config)

        # Then apply general layout for remaining unpositioned nodes
        remaining_unpositioned = [
            node for node in graph.nodes.values() if node.x is None or node.y is None
        ]

        if remaining_unpositioned:
            layout_type = config.default_layout
            layout_config: Dict[str, Any] = {}

            if layout_type == "tree":
                layout = TreeLayout()
                layout_config = {"direction": "top-down", "node_spacing_x": 200, "node_spacing_y": 150}
            else:  # radial (default)
                layout = RadialLayout()
                layout_config = {"radius_step": 150, "angle_step": 60}

            # Create a temporary graph with only unpositioned nodes for layout
            temp_graph = Graph()
            for node in remaining_unpositioned:
                temp_graph.add_node(node)
                # Add edges that connect unpositioned nodes
                for edge in graph.edges:
                    if (
                        edge.source_id in [n.id for n in remaining_unpositioned]
                        and edge.target_id in [n.id for n in remaining_unpositioned]
                    ):
                        temp_graph.add_edge(edge)

            layout.apply_layout(temp_graph, layout_config)

            # After layout, try container positioning again for newly positioned nodes
            newly_positioned = [
                node for node in graph.nodes.values()
                if node.x is not None and node.y is not None
                and node.id in [n.id for n in remaining_unpositioned]
            ]

            for node in newly_positioned:
                container_edges = [
                    edge
                    for edge in graph.edges
                    if edge.connection_type == ConnectionType.CONTAINER
                    and edge.source_id == node.id
                ]
                for edge in container_edges:
                    parent_node_config = ConfigLoader.get_node_config(config, node.type)
                    positioner.position_container_children(graph, node, edge.edge_type, parent_node_config)

