"""Assumption-free placement for graph nodes without saved positions."""

import math
from typing import Dict, List, Set, Tuple

from ..core.graph import Graph
from ..core.node import Node
from .base import BaseLayout


class FreeformLayout(BaseLayout):
    """Place only new nodes without assigning meaning to any edge type."""

    DEFAULT_GAP = 64.0
    COLLISION_MARGIN = 24.0

    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Place unpositioned nodes near positioned neighbours or a neutral anchor."""
        pending: Set[str] = {
            node.id
            for node in graph.nodes.values()
            if node.x is None or node.y is None
        }
        if not pending:
            return

        adjacency = self._build_adjacency(graph)
        gap = max(
            float(config.get("sibling_spacing", self.DEFAULT_GAP)),
            self.DEFAULT_GAP,
        )

        while True:
            anchored = [
                node_id
                for node_id in pending
                if self._positioned_neighbours(graph, adjacency, node_id)
            ]
            if not anchored:
                break

            anchored.sort(
                key=lambda node_id: (
                    -len(self._positioned_neighbours(graph, adjacency, node_id)),
                    node_id,
                )
            )
            node_id = anchored[0]
            neighbours = self._positioned_neighbours(graph, adjacency, node_id)
            anchor = self._average_center(neighbours)
            self._place_near(
                graph,
                graph.nodes[node_id],
                anchor,
                gap,
                include_anchor=False,
            )
            pending.remove(node_id)

        neutral_anchor = self._neutral_anchor(graph, config)
        while pending:
            component = self._pending_component(adjacency, min(pending), pending)
            root_id = min(component)
            self._place_near(
                graph,
                graph.nodes[root_id],
                neutral_anchor,
                gap,
                include_anchor=True,
            )
            pending.remove(root_id)

            component_pending = component - {root_id}
            while component_pending:
                candidates = [
                    node_id
                    for node_id in component_pending
                    if self._positioned_neighbours(graph, adjacency, node_id)
                ]
                node_id = min(candidates or component_pending)
                neighbours = self._positioned_neighbours(graph, adjacency, node_id)
                anchor = self._average_center(neighbours) if neighbours else neutral_anchor
                self._place_near(
                    graph,
                    graph.nodes[node_id],
                    anchor,
                    gap,
                    include_anchor=False,
                )
                component_pending.remove(node_id)
                pending.remove(node_id)

    def _build_adjacency(self, graph: Graph) -> Dict[str, Set[str]]:
        adjacency = {node_id: set() for node_id in graph.nodes}
        for edge in graph.edges:
            if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
                continue
            if edge.source_id == edge.target_id:
                continue
            adjacency[edge.source_id].add(edge.target_id)
            adjacency[edge.target_id].add(edge.source_id)
        return adjacency

    def _positioned_neighbours(
        self,
        graph: Graph,
        adjacency: Dict[str, Set[str]],
        node_id: str,
    ) -> List[Node]:
        return [
            graph.nodes[neighbour_id]
            for neighbour_id in sorted(adjacency.get(node_id, set()))
            if graph.nodes[neighbour_id].x is not None
            and graph.nodes[neighbour_id].y is not None
        ]

    def _average_center(self, nodes: List[Node]) -> Tuple[float, float]:
        centers = [self._node_center(node) for node in nodes]
        return (
            sum(center[0] for center in centers) / len(centers),
            sum(center[1] for center in centers) / len(centers),
        )

    def _neutral_anchor(self, graph: Graph, config: Dict) -> Tuple[float, float]:
        placement_anchor = config.get("placement_anchor")
        if isinstance(placement_anchor, dict):
            x = placement_anchor.get("x")
            y = placement_anchor.get("y")
            if self._is_number(x) and self._is_number(y):
                return float(x), float(y)

        positioned = [
            node
            for node in graph.nodes.values()
            if node.x is not None and node.y is not None
        ]
        if positioned:
            return self._average_center(positioned)

        return (
            float(config.get("start_x", 120)),
            float(config.get("start_y", 120)),
        )

    def _pending_component(
        self,
        adjacency: Dict[str, Set[str]],
        start_id: str,
        pending: Set[str],
    ) -> Set[str]:
        component: Set[str] = set()
        queue = [start_id]
        while queue:
            node_id = queue.pop(0)
            if node_id in component or node_id not in pending:
                continue
            component.add(node_id)
            queue.extend(sorted(adjacency.get(node_id, set()) - component))
        return component

    def _place_near(
        self,
        graph: Graph,
        node: Node,
        anchor: Tuple[float, float],
        gap: float,
        include_anchor: bool,
    ) -> None:
        width = node.width or 100
        height = node.height or 50
        step = max(width, height) + gap

        for center_x, center_y in self._candidate_centers(anchor, step, include_anchor):
            x = center_x - width / 2
            y = center_y - height / 2
            if not self._overlaps_positioned(graph, node.id, x, y, width, height):
                node.x = x
                node.y = y
                return

        raise ValueError(f"Unable to place node '{node.id}' without overlap")

    def _candidate_centers(
        self,
        anchor: Tuple[float, float],
        step: float,
        include_anchor: bool,
    ):
        if include_anchor:
            yield anchor

        diagonal = math.sqrt(0.5)
        directions = [
            (1.0, 0.0),
            (0.0, 1.0),
            (-1.0, 0.0),
            (0.0, -1.0),
            (diagonal, diagonal),
            (-diagonal, diagonal),
            (-diagonal, -diagonal),
            (diagonal, -diagonal),
        ]
        for ring in range(1, 257):
            radius = step * ring
            for unit_x, unit_y in directions:
                yield anchor[0] + unit_x * radius, anchor[1] + unit_y * radius

    def _overlaps_positioned(
        self,
        graph: Graph,
        node_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> bool:
        margin = self.COLLISION_MARGIN
        left = x - margin
        top = y - margin
        right = x + width + margin
        bottom = y + height + margin

        for other in graph.nodes.values():
            if other.id == node_id or other.x is None or other.y is None:
                continue
            other_left = other.x
            other_top = other.y
            other_right = other.x + (other.width or 100)
            other_bottom = other.y + (other.height or 50)
            if (
                left < other_right
                and right > other_left
                and top < other_bottom
                and bottom > other_top
            ):
                return True
        return False

    def _node_center(self, node: Node) -> Tuple[float, float]:
        return (
            (node.x or 0) + (node.width or 100) / 2,
            (node.y or 0) + (node.height or 50) / 2,
        )

    def _is_number(self, value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
