"""CSV parser for loading node and edge data."""

import csv
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..core.graph import Graph
from ..core.node import Node
from ..core.edge import Edge, ConnectionType
from ..config.loader import ConfigLoader
from ..config.schema import GlobalConfig
from .base import BaseParser


class CSVParser(BaseParser):
    """Parser for CSV-based graph data (node.csv and edge.csv)."""

    def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
        """Parse CSV files in the given folder and return a Graph."""
        graph = Graph()

        # Load nodes from node.csv
        node_csv_path = path / "node.csv"
        if node_csv_path.exists():
            with open(node_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    node_id = (row.get("node_id") or "").strip()
                    if not node_id:
                        continue

                    # Use node_title as label, fallback to node_id
                    label = (row.get("node_title") or "").strip() or node_id
                    node_type = (row.get("node_type") or "default").strip()
                    node_text = (row.get("node_text") or "").strip()

                    node = Node(
                        id=node_id,
                        label=label,
                        type=node_type,
                        metadata={"text": node_text} if node_text else {},
                    )
                    graph.add_node(node)

        # Load config to look up connection_type from edge_type
        config = ConfigLoader.load_from_folder(path)

        # Load edges from edge.csv
        edge_csv_path = path / "edge.csv"
        if edge_csv_path.exists():
            with open(edge_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    source_id = (row.get("from") or "").strip()
                    target_id = (row.get("to") or "").strip()
                    edge_type = (row.get("edge_type") or "link").strip()

                    if not source_id or not target_id:
                        continue

                    # Look up connection_type from config based on edge_type
                    connection_type_str = ConfigLoader.get_connection_type(config, edge_type)
                    
                    # Map connection_type string to enum
                    if connection_type_str == "container":
                        connection_type = ConnectionType.CONTAINER
                    else:
                        connection_type = ConnectionType.LINE

                    edge = Edge(
                        source_id=source_id,
                        target_id=target_id,
                        connection_type=connection_type,
                        edge_type=edge_type,
                        label=(row.get("label") or "").strip() or None,
                    )
                    graph.add_edge(edge)

        return graph

    def get_supported_formats(self) -> List[str]:
        """Return list of supported file extensions."""
        return ["csv"]

