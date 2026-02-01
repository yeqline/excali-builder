"""Radial layout algorithm for hierarchical graphs."""

import math
from typing import Dict, List
from ..core.graph import Graph
from ..core.node import Node
from .base import BaseLayout


class RadialLayout(BaseLayout):
    """Radial layout: root at center, children in circular patterns."""

    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Apply radial layout to graph nodes."""
        # Find root nodes (nodes with no container parents)
        root_nodes = [
            node
            for node in graph.nodes.values()
            if not graph.get_container_parents(node.id)
        ]

        if not root_nodes:
            # If no clear roots, use first node
            root_nodes = [list(graph.nodes.values())[0]] if graph.nodes else []

        # Default spacing
        radius_step = config.get("radius_step", 150)
        angle_step = config.get("angle_step", 60)

        # Position root nodes
        if len(root_nodes) == 1:
            root = root_nodes[0]
            if root.x is None or root.y is None:
                root.x = 400
                root.y = 400
            self._layout_subtree_radial(graph, root, radius_step, angle_step, 0, 0)
        else:
            # Multiple roots: arrange them in a circle
            center_x, center_y = 400, 400
            root_radius = 200
            angle_per_root = 360 / len(root_nodes) if root_nodes else 0
            for i, root in enumerate(root_nodes):
                angle = math.radians(i * angle_per_root)
                if root.x is None or root.y is None:
                    root.x = center_x + root_radius * math.cos(angle)
                    root.y = center_y + root_radius * math.sin(angle)
                self._layout_subtree_radial(
                    graph, root, radius_step, angle_step, root.x, root.y
                )

    def _layout_subtree_radial(
        self,
        graph: Graph,
        parent: Node,
        radius_step: float,
        angle_step: float,
        center_x: float,
        center_y: float,
    ):
        """Recursively layout children in radial pattern around parent."""
        children = graph.get_container_children(parent.id)
        if not children:
            return

        # Calculate positions for children
        num_children = len(children)
        if num_children == 1:
            angles = [0]
        else:
            total_angle = min(num_children * angle_step, 360)
            start_angle = -total_angle / 2
            angles = [
                start_angle + (i * total_angle / (num_children - 1))
                if num_children > 1
                else start_angle
                for i in range(num_children)
            ]

        parent_x = parent.x or center_x
        parent_y = parent.y or center_y

        for i, child in enumerate(children):
            if child.x is None or child.y is None:
                angle_rad = math.radians(angles[i])
                child.x = parent_x + radius_step * math.cos(angle_rad)
                child.y = parent_y + radius_step * math.sin(angle_rad)

            # Recursively layout children of this child
            self._layout_subtree_radial(
                graph, child, radius_step, angle_step, child.x, child.y
            )

