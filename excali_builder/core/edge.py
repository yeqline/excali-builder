"""Edge data model for graph connections."""

from typing import Optional, Any, Dict
from pydantic import BaseModel
from enum import Enum


class ConnectionType(str, Enum):
    """Type of connection between nodes."""

    GROUP = "group"  # Excalidraw grouping without a visible arrow
    ENCLOSING_GROUP = "enclosing_group"  # Grouping where the parent encloses children
    LINE = "line"  # Relationship (arrow/line with arrowheads)


class Edge(BaseModel):
    """Typed connection between nodes."""

    id: Optional[str] = None  # Optional ID for tracking/debugging (not used for sync)
    source_id: str
    target_id: str
    connection_type: ConnectionType
    edge_type: str  # Subtype for styling lookup (e.g., "link", "directional_link")
    label: Optional[str] = None
    metadata: Dict[str, Any] = {}
