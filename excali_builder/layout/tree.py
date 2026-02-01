"""Tree layout algorithm for hierarchical graphs."""

from typing import Dict
from ..core.graph import Graph
from ..core.node import Node
from .base import BaseLayout


class TreeLayout(BaseLayout):
    """Tree layout: traditional hierarchical tree structure."""

    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Apply tree layout to graph nodes."""
        direction = config.get("direction", "top-down")  # top-down, left-right, right-left, bottom-up
        node_spacing_x = config.get("node_spacing_x", 200)
        node_spacing_y = config.get("node_spacing_y", 150)

        # Find root nodes
        root_nodes = [
            node
            for node in graph.nodes.values()
            if not graph.get_container_parents(node.id)
        ]

        if not root_nodes:
            root_nodes = [list(graph.nodes.values())[0]] if graph.nodes else []

        start_x = config.get("start_x", 400)
        start_y = config.get("start_y", 100)

        for root in root_nodes:
            if root.x is None or root.y is None:
                root.x = start_x
                root.y = start_y
            self._layout_subtree_tree(
                graph, root, direction, node_spacing_x, node_spacing_y, 0
            )

    def _layout_subtree_tree(
        self,
        graph: Graph,
        parent: Node,
        direction: str,
        spacing_x: float,
        spacing_y: float,
        level: int,
    ):
        """Recursively layout children in tree structure."""
        children = graph.get_container_children(parent.id)
        if not children:
            return

        parent_x = parent.x or 0
        parent_y = parent.y or 0

        # Calculate positions based on direction
        if direction == "top-down":
            child_y = parent_y + spacing_y
            # Arrange children horizontally
            total_width = (len(children) - 1) * spacing_x
            start_x = parent_x - total_width / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = start_x + i * spacing_x
                    child.y = child_y
        elif direction == "left-right":
            child_x = parent_x + spacing_x
            total_height = (len(children) - 1) * spacing_y
            start_y = parent_y - total_height / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = child_x
                    child.y = start_y + i * spacing_y
        elif direction == "right-left":
            child_x = parent_x - spacing_x
            total_height = (len(children) - 1) * spacing_y
            start_y = parent_y - total_height / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = child_x
                    child.y = start_y + i * spacing_y
        else:  # bottom-up
            child_y = parent_y - spacing_y
            total_width = (len(children) - 1) * spacing_x
            start_x = parent_x - total_width / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = start_x + i * spacing_x
                    child.y = child_y

        # Recursively layout children
        for child in children:
            self._layout_subtree_tree(
                graph, child, direction, spacing_x, spacing_y, level + 1
            )

