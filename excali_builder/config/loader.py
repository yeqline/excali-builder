"""Configuration loader for JSON config files."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..core.edge import ConnectionType
from .schema import (
    EdgeTypeConfig,
    GlobalConfig,
    LayoutConfig,
    LineConnectionConfig,
    NodeTypeConfig,
)


class ConfigLoader:
    """Loads and validates configuration from JSON files."""

    DEFAULT_NODE_TEMPLATE = {
        "color": "#000000",
        "backgroundColor": "#ffffff",
        "shape": "rectangle",
        "font_size": 14,
        "font_family": "Arial",
        "padding": 10,
        "borderRadius": 0,
    }
    NODE_TYPE_TEMPLATES = {
        "comment": {
            "color": "#57534E",
            "backgroundColor": "#FAF7F2",
            "shape": "rectangle",
            "font_size": 13,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 12,
        },
        "image": {
            "color": "#475569",
            "backgroundColor": "#F8FAFC",
            "shape": "rectangle",
            "font_size": 13,
            "font_family": "Arial",
            "padding": 8,
            "borderRadius": 12,
        },
        "link": {
            "color": "#1D4ED8",
            "backgroundColor": "#DBEAFE",
            "shape": "rectangle",
            "font_size": 13,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 12,
        },
        "procedure": {
            "color": "#92400E",
            "backgroundColor": "#FEF3C7",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 12,
            "borderRadius": 16,
        },
        "step": {
            "color": "#1F2937",
            "backgroundColor": "#F9FAFB",
            "shape": "rectangle",
            "font_size": 13,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 12,
        },
        "dbt_group": {
            "color": "#334155",
            "backgroundColor": "#F1F5F9",
            "shape": "rectangle",
            "font_size": 15,
            "font_family": "Arial",
            "padding": 12,
            "borderRadius": 12,
        },
        "dbt_model": {
            "color": "#1E3A8A",
            "backgroundColor": "#DBEAFE",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 10,
        },
        "dbt_source": {
            "color": "#065F46",
            "backgroundColor": "#D1FAE5",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 10,
        },
        "dbt_seed": {
            "color": "#7C2D12",
            "backgroundColor": "#FFEDD5",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 10,
        },
        "dbt_snapshot": {
            "color": "#581C87",
            "backgroundColor": "#F3E8FF",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 10,
        },
        "dbt_exposure": {
            "color": "#991B1B",
            "backgroundColor": "#FEE2E2",
            "shape": "rectangle",
            "font_size": 14,
            "font_family": "Arial",
            "padding": 10,
            "borderRadius": 10,
        },
    }
    DEFAULT_EDGE_TEMPLATE = {
        "connection_type": "line",
        "color": "#000000",
        "stroke_width": 2,
        "stroke_style": "solid",
        "arrow_start": None,
        "arrow_end": None,
        "show_label": True,
        "label_color": None,
        "label_font_size": 14,
    }
    EDGE_TYPE_TEMPLATES = {
        "attachment": {
            "connection_type": "group",
            "color": "#6B7280",
            "stroke_width": 2,
            "stroke_style": "dashed",
            "arrow_start": None,
            "arrow_end": None,
        },
        "comment": {
            "connection_type": "line",
            "color": "#78716C",
            "stroke_width": 2,
            "stroke_style": "dashed",
            "arrow_start": None,
            "arrow_end": None,
        },
        "link": {
            "connection_type": "line",
            "color": "#2563EB",
            "stroke_width": 2,
            "stroke_style": "dashed",
            "arrow_start": None,
            "arrow_end": None,
        },
        "next": {
            "connection_type": "line",
            "color": "#2563EB",
            "stroke_width": 2,
            "stroke_style": "solid",
            "arrow_start": None,
            "arrow_end": "arrow",
        },
        "procedure_step": {
            "connection_type": "group",
            "color": "#2563EB",
            "stroke_width": 2,
            "stroke_style": "solid",
            "arrow_start": None,
            "arrow_end": "arrow",
        },
        "group_member": {
            "connection_type": "enclosing_group",
            "color": "#64748B",
            "stroke_width": 2,
            "stroke_style": "solid",
            "arrow_start": None,
            "arrow_end": None,
            "group_padding": 48,
        },
        "lineage": {
            "connection_type": "line",
            "color": "#2563EB",
            "stroke_width": 2,
            "stroke_style": "solid",
            "arrow_start": None,
            "arrow_end": "arrow",
        },
    }

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
    def ensure_graph_config(folder_path: Path, graph) -> Dict[str, Any]:
        """Ensure every used node and edge type exists explicitly in config files."""
        node_config_path = folder_path / "node_config.json"
        edge_config_path = folder_path / "edge_config.json"

        node_config_data = ConfigLoader._load_json_dict(node_config_path)
        edge_config_data = ConfigLoader._load_json_dict(edge_config_path)

        report = {
            "added_node_types": [],
            "completed_node_types": [],
            "added_edge_types": [],
            "completed_edge_types": [],
        }

        node_changed = False
        for node_type in sorted({node.type for node in graph.nodes.values()}):
            template = ConfigLoader._get_node_type_template(node_type)
            merged, was_added, had_missing_fields = ConfigLoader._merge_template(
                node_config_data.get(node_type),
                template,
            )
            if was_added:
                report["added_node_types"].append(node_type)
                node_changed = True
            elif had_missing_fields:
                report["completed_node_types"].append(node_type)
                node_changed = True
            node_config_data[node_type] = merged

        edge_changed = False
        for edge_type in sorted({edge.edge_type for edge in graph.edges}):
            template = ConfigLoader._get_edge_type_template(edge_type)
            merged, was_added, had_missing_fields = ConfigLoader._merge_template(
                edge_config_data.get(edge_type),
                template,
            )
            if was_added:
                report["added_edge_types"].append(edge_type)
                edge_changed = True
            elif had_missing_fields:
                report["completed_edge_types"].append(edge_type)
                edge_changed = True
            edge_config_data[edge_type] = merged

        if node_changed:
            ConfigLoader._write_json_dict(node_config_path, node_config_data)
        if edge_changed:
            ConfigLoader._write_json_dict(edge_config_path, edge_config_data)

        return report

    @staticmethod
    def apply_config_to_graph(graph, config: GlobalConfig) -> None:
        """Resolve edge connection types from explicit config entries."""
        for edge in graph.edges:
            edge.connection_type = ConfigLoader.get_connection_type(config, edge.edge_type)

    @staticmethod
    def get_node_config(config: GlobalConfig, node_type: str) -> NodeTypeConfig:
        """Get node configuration for a type."""
        if node_type not in config.node_types:
            raise ValueError(f"Missing node config for type '{node_type}'")
        return config.node_types[node_type]

    @staticmethod
    def get_edge_type_config(config: GlobalConfig, edge_type: str) -> Optional[EdgeTypeConfig]:
        """Get edge type configuration, or None if not found."""
        return config.edge_types.get(edge_type)

    @staticmethod
    def get_connection_type(config: GlobalConfig, edge_type: str) -> ConnectionType:
        """Get connection type for an edge type."""
        edge_config = config.edge_types.get(edge_type)
        if not edge_config:
            raise ValueError(f"Missing edge config for type '{edge_type}'")
        try:
            return ConnectionType(edge_config.connection_type)
        except ValueError as exc:
            raise ValueError(
                f"Edge type '{edge_type}' has invalid connection_type "
                f"'{edge_config.connection_type}'"
            ) from exc

    @staticmethod
    def get_line_config(config: GlobalConfig, edge_type: str) -> LineConnectionConfig:
        """Get line connection configuration for an edge type."""
        edge_config = config.edge_types.get(edge_type)
        if not edge_config:
            raise ValueError(f"Missing edge config for type '{edge_type}'")
        if edge_config.connection_type != "line":
            raise ValueError(
                f"Edge type '{edge_type}' is configured as '{edge_config.connection_type}', not 'line'"
            )
        return LineConnectionConfig(
            connection_type="line",
            color=edge_config.color,
            stroke_width=edge_config.stroke_width,
            stroke_style=edge_config.stroke_style,
            arrow_start=edge_config.arrow_start,
            arrow_end=edge_config.arrow_end,
            show_label=edge_config.show_label,
            label_color=edge_config.label_color,
            label_font_size=edge_config.label_font_size,
        )

    @staticmethod
    def _get_node_type_template(node_type: str) -> Dict[str, Any]:
        """Return the explicit config template for a node type."""
        template = ConfigLoader.NODE_TYPE_TEMPLATES.get(
            node_type,
            ConfigLoader.DEFAULT_NODE_TEMPLATE,
        )
        return dict(template)

    @staticmethod
    def _get_edge_type_template(edge_type: str) -> Dict[str, Any]:
        """Return the explicit config template for an edge type."""
        template = ConfigLoader.EDGE_TYPE_TEMPLATES.get(
            edge_type,
            ConfigLoader.DEFAULT_EDGE_TEMPLATE,
        )
        result = dict(template)
        result.setdefault("show_label", result.get("connection_type") == "line")
        result.setdefault("label_color", None)
        result.setdefault("label_font_size", 14)
        return result

    @staticmethod
    def _load_json_dict(path: Path) -> Dict[str, Any]:
        """Load a JSON object from disk, or return an empty dict if missing."""
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write_json_dict(path: Path, data: Dict[str, Any]) -> None:
        """Write a JSON object with stable indentation."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    @staticmethod
    def _merge_template(
        existing: Optional[Dict[str, Any]],
        template: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool, bool]:
        """Merge a template into an existing config entry."""
        if existing is None:
            return dict(template), True, False

        merged = dict(existing)
        had_missing_fields = False
        for key, value in template.items():
            if key not in merged:
                merged[key] = value
                had_missing_fields = True
        return merged, False, had_missing_fields
