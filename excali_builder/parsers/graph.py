"""Parser for the direct ``graph.json`` graph representation."""

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ..config.loader import ConfigLoader
from ..core.edge import ConnectionType, Edge
from ..core.graph import Graph
from ..core.node import Node
from .base import BaseParser


class GraphNodeInput(BaseModel):
    """One node declared in ``graph.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    label: Optional[str] = None
    text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "type")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class GraphEdgeInput(BaseModel):
    """One edge declared in ``graph.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    type: str
    label: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "source", "target", "type")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class GraphDocument(BaseModel):
    """Versioned direct graph source document."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    nodes: List[GraphNodeInput] = Field(default_factory=list)
    edges: List[GraphEdgeInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> "GraphDocument":
        node_ids = [node.id for node in self.nodes]
        duplicate_node_ids = _duplicates(node_ids)
        if duplicate_node_ids:
            raise ValueError(
                "duplicate node IDs: " + ", ".join(duplicate_node_ids)
            )

        edge_ids = [edge.id for edge in self.edges]
        duplicate_edge_ids = _duplicates(edge_ids)
        if duplicate_edge_ids:
            raise ValueError(
                "duplicate edge IDs: " + ", ".join(duplicate_edge_ids)
            )

        known_node_ids = set(node_ids)
        dangling = []
        for edge in self.edges:
            if edge.source not in known_node_ids:
                dangling.append(f"edge '{edge.id}' source '{edge.source}'")
            if edge.target not in known_node_ids:
                dangling.append(f"edge '{edge.id}' target '{edge.target}'")
        if dangling:
            raise ValueError("unknown node references: " + "; ".join(dangling))

        return self


class GraphJsonParser(BaseParser):
    """Parse ``graph.json`` without inferring graph structure."""

    def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
        """Read the direct graph source and return its declared nodes and edges."""
        source_path = path / "graph.json"
        if not source_path.exists():
            raise ValueError(f"Missing graph source: {source_path}")

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                source_data = json.load(f)
            document = GraphDocument.model_validate(source_data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {source_path}: {exc}") from exc
        except ValidationError as exc:
            raise ValueError(f"Invalid graph source {source_path}: {exc}") from exc

        graph = Graph()
        for source_node in document.nodes:
            metadata = dict(source_node.metadata)
            if source_node.text is not None:
                metadata["text"] = source_node.text
            label = (source_node.label or "").strip() or source_node.id
            graph.add_node(
                Node(
                    id=source_node.id,
                    label=label,
                    type=source_node.type,
                    metadata=metadata,
                )
            )

        for source_edge in document.edges:
            graph.add_edge(
                Edge(
                    id=source_edge.id,
                    source_id=source_edge.source,
                    target_id=source_edge.target,
                    connection_type=ConnectionType.LINE,
                    edge_type=source_edge.type,
                    label=source_edge.label,
                    metadata=dict(source_edge.metadata),
                )
            )

        ConfigLoader.ensure_graph_config(path, graph)
        config = ConfigLoader.load_from_folder(path)
        ConfigLoader.apply_config_to_graph(graph, config)
        return graph

    def get_supported_formats(self) -> List[str]:
        """Return the direct graph source extension."""
        return ["json"]


def _duplicates(values: List[str]) -> List[str]:
    """Return sorted values that occur more than once."""
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
