"""Bidirectional graph data structure."""

from typing import Dict, List

from .edge import ConnectionType, Edge
from .node import Node


class Graph:
    """Bidirectional graph with nodes and edges."""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []

    def add_node(self, node: Node):
        """Add a node to the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge):
        """Add an edge to the graph."""
        self.edges.append(edge)

    def get_container_children(self, parent_id: str) -> List[Node]:
        """Get nodes that are container-connected to parent (grouped rendering)."""
        return [
            self.nodes[edge.target_id]
            for edge in self.edges
            if edge.connection_type == ConnectionType.CONTAINER
            and edge.source_id == parent_id
            and edge.target_id in self.nodes
        ]

    def get_hierarchy_children(self, parent_id: str) -> List[Node]:
        """Get structural children connected by parent_child edges."""
        child_ids = []

        for node in self.nodes.values():
            if node.metadata.get("hierarchy_parent_id") == parent_id:
                child_ids.append(node.id)

        for edge in self.edges:
            if (
                edge.edge_type == "parent_child"
                and edge.source_id == parent_id
                and edge.target_id in self.nodes
                and edge.target_id not in child_ids
            ):
                child_ids.append(edge.target_id)

        return [self.nodes[node_id] for node_id in child_ids]

    def get_line_connections(self, node_id: str) -> List[Edge]:
        """Get line-based edges connected to node (arrow relationships)."""
        return [
            edge
            for edge in self.edges
            if edge.connection_type == ConnectionType.LINE
            and (edge.source_id == node_id or edge.target_id == node_id)
        ]

    def get_container_parents(self, child_id: str) -> List[Node]:
        """Get parent nodes that contain this child via container connections."""
        return [
            self.nodes[edge.source_id]
            for edge in self.edges
            if edge.connection_type == ConnectionType.CONTAINER
            and edge.target_id == child_id
            and edge.source_id in self.nodes
        ]

    def get_hierarchy_parents(self, child_id: str) -> List[Node]:
        """Get structural parents connected by parent_child edges."""
        parents = []
        node = self.nodes.get(child_id)
        hierarchy_parent_id = node.metadata.get("hierarchy_parent_id") if node else None
        if hierarchy_parent_id and hierarchy_parent_id in self.nodes:
            parents.append(self.nodes[hierarchy_parent_id])

        for edge in self.edges:
            if (
                edge.edge_type == "parent_child"
                and edge.target_id == child_id
                and edge.source_id in self.nodes
                and self.nodes[edge.source_id] not in parents
            ):
                parents.append(self.nodes[edge.source_id])

        return parents
