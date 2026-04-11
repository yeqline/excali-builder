"""Configuration schemas for node, edge, and layout settings."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class NodeTypeConfig(BaseModel):
    """Styling configuration for a node type."""

    color: str = "#000000"
    backgroundColor: str = "#ffffff"
    shape: str = "rectangle"  # rectangle, ellipse, diamond
    font_size: int = 14
    font_family: str = "Arial"
    padding: int = 10
    borderRadius: int = 0


class LineConnectionConfig(BaseModel):
    """Styling for line-based connections (arrows/relationships)."""

    connection_type: str = "line"  # Always "line" for this type
    color: str = "#000000"
    stroke_width: int = 2
    stroke_style: str = "solid"  # solid, dashed, dotted
    arrow_start: Optional[str] = None  # "arrow", "circle", None
    arrow_end: Optional[str] = None  # "arrow", "circle", None


class EdgeTypeConfig(BaseModel):
    """Edge configuration controlling rendering behavior."""

    connection_type: str  # "container" or "line"
    color: Optional[str] = None
    stroke_width: Optional[int] = None
    stroke_style: Optional[str] = None  # solid, dashed, dotted
    arrow_start: Optional[str] = None  # "arrow", "circle", None
    arrow_end: Optional[str] = None  # "arrow", "circle", None


class LayoutConfig(BaseModel):
    """Tree layout settings used for initial placement."""

    direction: str = "left-right"  # left-right, right-left, top-down, bottom-up
    level_spacing: int = 180
    sibling_spacing: int = 40
    root_spacing: int = 100
    start_x: int = 120
    start_y: int = 120


class GlobalConfig(BaseModel):
    """Global configuration with node types, edge styles, and layout."""

    node_types: Dict[str, NodeTypeConfig] = Field(default_factory=dict)
    edge_types: Dict[str, EdgeTypeConfig] = Field(default_factory=dict)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
