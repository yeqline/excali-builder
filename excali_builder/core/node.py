"""Node data model for graph representation."""

from typing import Dict, Optional, Any
from pydantic import BaseModel


class Node(BaseModel):
    """Graph node with stable ID, label, type, and geometry."""

    id: str  # Stable, unique ID from source
    label: str
    type: str = "default"
    # Geometry (authoritative if present in positions.json)
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    metadata: Dict[str, Any] = {}

