"""Configuration schemas for node, edge, and layout settings."""

from typing import Any, Dict, List, Literal, Optional

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
    show_label: bool = True
    label_color: Optional[str] = None
    label_font_size: int = 14


class EdgeTypeConfig(BaseModel):
    """Edge configuration controlling rendering behavior."""

    connection_type: str  # line, group, enclosing_group
    color: Optional[str] = None
    stroke_width: Optional[int] = None
    stroke_style: Optional[str] = None  # solid, dashed, dotted
    arrow_start: Optional[str] = None  # "arrow", "circle", None
    arrow_end: Optional[str] = None  # "arrow", "circle", None
    group_padding: Optional[int] = None
    max_length: Optional[float] = None
    show_label: bool = True
    label_color: Optional[str] = None
    label_font_size: int = 14


class WiringConfig(BaseModel):
    """Engine-independent readability settings and explicit schematic constraints."""

    candidates: int = Field(default=4, ge=1, le=16)
    timeout_seconds: float = Field(default=40, gt=0, le=300)
    node_spacing: float = Field(default=90, gt=0)
    wire_spacing: float = Field(default=18, gt=0)
    port_spacing: float = Field(default=16, gt=0)
    padding: float = Field(default=24, gt=0)
    label_max_width: float = Field(default=220, ge=60)
    port_types: List[str] = Field(default_factory=lambda: ["port"])
    edge_roles: Dict[str, Literal["flow", "distribution", "annotation"]] = Field(
        default_factory=lambda: {"annotation": "annotation"}
    )
    port_sides: Dict[str, Literal["WEST", "EAST"]] = Field(default_factory=dict)
    port_order: Dict[str, List[str]] = Field(default_factory=dict)
    fixed_sizes: Dict[str, List[float]] = Field(default_factory=dict)
    engine_options: Dict[str, Any] = Field(default_factory=dict)


class LayoutConfig(BaseModel):
    """Layout settings used for initial placement."""

    algorithm: str = "tree"  # tree, dag, freeform, wiring
    engine: str = "elk"
    wiring: WiringConfig = Field(default_factory=WiringConfig)
    direction: str = "left-right"  # left-right, right-left, top-down, bottom-up
    level_spacing: int = 180
    sibling_spacing: int = 40
    root_spacing: int = 100
    start_x: int = 120
    start_y: int = 120
    rank_edge_types: List[str] = Field(default_factory=lambda: ["lineage"])


class GlobalConfig(BaseModel):
    """Global configuration with node types, edge styles, and layout."""

    node_types: Dict[str, NodeTypeConfig] = Field(default_factory=dict)
    edge_types: Dict[str, EdgeTypeConfig] = Field(default_factory=dict)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
