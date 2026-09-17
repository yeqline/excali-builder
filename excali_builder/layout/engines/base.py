"""Engine-neutral layout contract. Coordinates are absolute scene coordinates."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]


@dataclass
class Box:
    x: float
    y: float
    width: float
    height: float


@dataclass
class LayoutNode:
    id: str
    width: float
    height: float
    parent_id: Optional[str] = None
    is_port: bool = False
    header_height: float = 0
    side: Optional[str] = None
    order: Optional[int] = None
    group: Optional[str] = None
    size_locked: bool = False
    side_locked: bool = False
    part_template: Optional[str] = None
    port_role: Optional[str] = None
    fixed_position: Optional[Point] = None


@dataclass
class PartTemplate:
    roles: List[str]
    instances: Dict[str, Dict[str, str]]
    optimize: bool = True
    locked_sides: Dict[str, str] = field(default_factory=dict)
    locked_orders: List[List[str]] = field(default_factory=list)


@dataclass
class LayoutEdge:
    id: str
    source: str
    target: str
    label_width: float = 0
    label_height: float = 0
    role: str = "flow"
    source_reference: str = ""
    target_reference: str = ""
    label_text: str = ""
    font_size: float = 14


@dataclass
class LayoutRequest:
    nodes: List[LayoutNode]
    edges: List[LayoutEdge]
    direction: str = "left-right"
    node_spacing: float = 80
    layer_spacing: float = 160
    wire_spacing: float = 18
    port_spacing: float = 16
    padding: float = 24
    seed: int = 1
    timeout: float = 30
    engine_options: Dict[str, Any] = field(default_factory=dict)
    edge_routing: str = "straight"
    part_templates: Dict[str, PartTemplate] = field(default_factory=dict)
    label_max_width: float = 220


@dataclass
class Connector:
    """One outward stub and a clickable reference to the remote endpoint."""

    points: List[Point]
    label: Box
    text: str
    target: str


@dataclass
class Route:
    points: List[Point]
    label: Optional[Box] = None
    connectors: List[Connector] = field(default_factory=list)


def route_segments(route: Route):
    """The visible segments; the logical span of a referenced wire is not drawn."""
    paths = [connector.points for connector in route.connectors] or [route.points]
    return [segment for points in paths for segment in zip(points, points[1:])]


@dataclass
class LayoutResult:
    boxes: Dict[str, Box]
    routes: Dict[str, Route]
    port_sides: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)


class LayoutEngine(ABC):
    """Produce geometry without modifying source data or writing diagram files.

    Engines return every requested node and edge, preserve IDs, and keep ports
    inside their owners. Edge points follow the original source-to-target order.
    Adapters translate their own option names; callers use this neutral contract.
    """

    @abstractmethod
    def layout(self, request: LayoutRequest) -> LayoutResult:
        pass
