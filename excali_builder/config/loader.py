"""Configuration loader for JSON config files."""

import json
from pathlib import Path
from typing import Optional

from .schema import (
    EdgeTypeConfig,
    GlobalConfig,
    LayoutConfig,
    LineConnectionConfig,
    NodeTypeConfig,
)


class ConfigLoader:
    """Loads and validates configuration from JSON files."""

    @staticmethod
    def load_from_folder(folder_path: Path) -> GlobalConfig:
        """Load configuration from a folder (node_config.json, edge_config.json, config.json)."""
        config = GlobalConfig()

        node_config_path = folder_path / "node_config.json"
        if node_config_path.exists():
            with open(node_config_path, "r", encoding="utf-8") as f:
                node_config_data = json.load(f)
                for node_type, node_config in node_config_data.items():
                    config.node_types[node_type] = NodeTypeConfig(**node_config)

        edge_config_path = folder_path / "edge_config.json"
        if edge_config_path.exists():
            with open(edge_config_path, "r", encoding="utf-8") as f:
                edge_config_data = json.load(f)
                for edge_type, edge_config in edge_config_data.items():
                    config.edge_types[edge_type] = EdgeTypeConfig(**edge_config)

        main_config_path = folder_path / "config.json"
        if main_config_path.exists():
            with open(main_config_path, "r", encoding="utf-8") as f:
                main_config_data = json.load(f)
                if "layout" in main_config_data:
                    config.layout = LayoutConfig(**main_config_data["layout"])

        return config

    @staticmethod
    def get_node_config(config: GlobalConfig, node_type: str) -> NodeTypeConfig:
        """Get node configuration for a type, with defaults."""
        if node_type in config.node_types:
            return config.node_types[node_type]
        if node_type == "link":
            return NodeTypeConfig(
                color="#1D4ED8",
                backgroundColor="#DBEAFE",
                shape="rectangle",
                font_size=13,
                padding=10,
                borderRadius=12,
            )
        return NodeTypeConfig()

    @staticmethod
    def get_edge_type_config(config: GlobalConfig, edge_type: str) -> Optional[EdgeTypeConfig]:
        """Get edge type configuration, or None if not found."""
        return config.edge_types.get(edge_type)

    @staticmethod
    def get_connection_type(config: GlobalConfig, edge_type: str) -> str:
        """Get connection type (container or line) for an edge type."""
        edge_config = config.edge_types.get(edge_type)
        if edge_config:
            return edge_config.connection_type
        return "line"

    @staticmethod
    def get_line_config(config: GlobalConfig, edge_type: str) -> LineConnectionConfig:
        """Get line connection configuration for an edge type, with defaults."""
        edge_config = config.edge_types.get(edge_type)
        if edge_config and edge_config.connection_type == "line":
            return LineConnectionConfig(
                connection_type="line",
                color=edge_config.color or "#000000",
                stroke_width=edge_config.stroke_width or 2,
                stroke_style=edge_config.stroke_style or "solid",
                arrow_start=edge_config.arrow_start,
                arrow_end=edge_config.arrow_end,
            )
        if edge_type == "link":
            return LineConnectionConfig(
                connection_type="line",
                color="#2563EB",
                stroke_width=2,
                stroke_style="dashed",
                arrow_start=None,
                arrow_end=None,
            )
        return LineConnectionConfig()
