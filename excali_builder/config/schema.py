"""Configuration schemas for node and edge styling."""

from pydantic import BaseModel
from typing import Dict, Any, Optional


class NodeTypeConfig(BaseModel):
    """Styling configuration for a node type."""

    color: str = "#000000"
    backgroundColor: str = "#ffffff"
    shape: str = "rectangle"  # rectangle, ellipse, diamond
    font_size: int = 14
    font_family: str = "Arial"
    padding: int = 10
    borderRadius: int = 0


class ContainerConnectionConfig(BaseModel):
    """Styling for container-based connections (grouping/hierarchy)."""

    connection_type: str = "container"  # Always "container" for this type
    placement: str = "outside"  # "inside" or "outside" - whether children are inside parent bounds or positioned outside it
    direction: str = "bottom"  # "top", "bottom", "left", "right", "radial", "center_h", "center_v" - direction children are arranged relative to parent
    child_offset: int = 20  # Spacing between parent and children
    group_padding: int = 15  # Padding around grouped children


class LineConnectionConfig(BaseModel):
    """Styling for line-based connections (arrows/relationships)."""

    connection_type: str = "line"  # Always "line" for this type
    color: str = "#000000"
    stroke_width: int = 2
    stroke_style: str = "solid"  # solid, dashed, dotted
    arrow_start: Optional[str] = None  # "arrow", "circle", None
    arrow_end: Optional[str] = None  # "arrow", "circle", None (defaults to None, can be set to "arrow" if needed)


class EdgeTypeConfig(BaseModel):
    """Unified edge type configuration that can be either container or line."""

    connection_type: str  # "container" or "line"
    # Container-specific fields (optional, only for container connections)
    placement: Optional[str] = None  # "inside" or "outside"
    direction: Optional[str] = None  # "top", "bottom", "left", "right", "radial", "center_h", "center_v"
    child_offset: Optional[int] = None  # Spacing between parent and children
    group_padding: Optional[int] = None  # Padding around grouped children
    # Line-specific fields (optional, only for line connections)
    color: Optional[str] = None
    stroke_width: Optional[int] = None
    stroke_style: Optional[str] = None  # solid, dashed, dotted
    arrow_start: Optional[str] = None  # "arrow", "circle", None
    arrow_end: Optional[str] = None  # "arrow", "circle", None


class GlobalConfig(BaseModel):
    """Global configuration with node types and connection styles."""

    node_types: Dict[str, NodeTypeConfig] = {}
    edge_types: Dict[str, EdgeTypeConfig] = {}  # Unified edge type configs
    default_layout: str = "radial"

