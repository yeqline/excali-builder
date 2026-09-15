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


@dataclass
class LayoutEdge:
    id: str
    source: str
    target: str
    label_width: float = 0
    label_height: float = 0
    role: str = "flow"


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


@dataclass
class Route:
    points: List[Point]
    label: Optional[Box] = None


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
