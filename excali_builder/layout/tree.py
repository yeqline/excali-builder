"""Tree layout algorithm driven by parent_child hierarchy."""

from typing import Dict, List

from ..core.graph import Graph
from ..core.node import Node
from .base import BaseLayout


class TreeLayout(BaseLayout):
    """Tree layout: a simple hierarchy arranged in one consistent direction."""

    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Apply tree layout to graph nodes."""
        direction = config.get("direction", "left-right")
        level_spacing = config.get("level_spacing", 180)
        sibling_spacing = config.get("sibling_spacing", 40)
        root_spacing = config.get("root_spacing", 100)
        start_x = config.get("start_x", 120)
        start_y = config.get("start_y", 120)

        root_nodes = [
            node
            for node in graph.nodes.values()
            if not graph.get_hierarchy_parents(node.id)
        ]
        if not root_nodes and graph.nodes:
            root_nodes = [list(graph.nodes.values())[0]]

        spans = {
            root.id: self._estimate_subtree_span(graph, root, direction, sibling_spacing)
            for root in root_nodes
        }

        positioned_roots = [
            root for root in root_nodes if root.x is not None and root.y is not None
        ]
        unpositioned_roots = [
            root for root in root_nodes if root.x is None or root.y is None
        ]

        next_offset = self._next_root_offset(
            positioned_roots,
            spans,
            direction,
            start_x,
            start_y,
            root_spacing,
        )

        for root in positioned_roots:
            self._layout_subtree(graph, root, direction, level_spacing, sibling_spacing)

        for root in unpositioned_roots:
            span = spans[root.id]
            node_width = root.width or 100
            node_height = root.height or 50

            if direction in {"left-right", "right-left"}:
                root.x = start_x
                root.y = next_offset + (span - node_height) / 2
            else:
                root.x = next_offset + (span - node_width) / 2
                root.y = start_y

            next_offset += span + root_spacing
            self._layout_subtree(graph, root, direction, level_spacing, sibling_spacing)

    def _layout_subtree(
        self,
        graph: Graph,
        parent: Node,
        direction: str,
        level_spacing: float,
        sibling_spacing: float,
    ) -> None:
        """Recursively position descendants around an already-positioned parent."""
        children = self._get_layout_children(graph, parent)
        if not children:
            return

        child_spans = [
            self._estimate_subtree_span(graph, child, direction, sibling_spacing)
            for child in children
        ]
        total_span = sum(child_spans) + sibling_spacing * (len(children) - 1)

        parent_x = parent.x if parent.x is not None else 0
        parent_y = parent.y if parent.y is not None else 0
        parent_width = parent.width or 100
        parent_height = parent.height or 50
        parent_center_x = parent_x + parent_width / 2
        parent_center_y = parent_y + parent_height / 2
        current_offset = (
            parent_center_y - total_span / 2
            if direction in {"left-right", "right-left"}
            else parent_center_x - total_span / 2
        )

        for child, span in zip(children, child_spans):
            child_width = child.width or 100
            child_height = child.height or 50

            if child.x is None or child.y is None:
                if direction == "left-right":
                    child.x = parent_x + parent_width + level_spacing
                    child.y = current_offset + (span - child_height) / 2
                elif direction == "right-left":
                    child.x = parent_x - level_spacing - child_width
                    child.y = current_offset + (span - child_height) / 2
                elif direction == "bottom-up":
                    child.x = current_offset + (span - child_width) / 2
                    child.y = parent_y - level_spacing - child_height
                else:  # top-down
                    child.x = current_offset + (span - child_width) / 2
                    child.y = parent_y + parent_height + level_spacing

            current_offset += span + sibling_spacing
            self._layout_subtree(
                graph,
                child,
                direction,
                level_spacing,
                sibling_spacing,
            )

    def _estimate_subtree_span(
        self,
        graph: Graph,
        node: Node,
        direction: str,
        sibling_spacing: float,
    ) -> float:
        """Estimate the span this subtree occupies on the sibling axis."""
        node_span = (
            node.height or 50
            if direction in {"left-right", "right-left"}
            else node.width or 100
        )
        children = self._get_layout_children(graph, node)
        if not children:
            return node_span

        child_spans = [
            self._estimate_subtree_span(graph, child, direction, sibling_spacing)
            for child in children
        ]
        return max(
            node_span,
            sum(child_spans) + sibling_spacing * (len(child_spans) - 1),
        )

    def _next_root_offset(
        self,
        positioned_roots: List[Node],
        spans: Dict[str, float],
        direction: str,
        start_x: float,
        start_y: float,
        root_spacing: float,
    ) -> float:
        """Find the next available root offset after any already-positioned roots."""
        if not positioned_roots:
            return start_y if direction in {"left-right", "right-left"} else start_x

        furthest_edge = (
            start_y if direction in {"left-right", "right-left"} else start_x
        )
        for root in positioned_roots:
            span = spans[root.id]
            if direction in {"left-right", "right-left"}:
                center = (root.y if root.y is not None else 0) + (root.height or 50) / 2
            else:
                center = (root.x if root.x is not None else 0) + (root.width or 100) / 2
            furthest_edge = max(furthest_edge, center + span / 2)

        return furthest_edge + root_spacing

    def _get_layout_children(self, graph: Graph, parent: Node) -> List[Node]:
        """Return structural children in the order this layout should place them."""
        children = graph.get_hierarchy_children(parent.id)
        if parent.type != "procedure":
            return children

        step_children = graph.get_sequence_children(
            parent.id,
            child_type="step",
            edge_type="next",
        )
        if not step_children:
            return children

        step_ids = {child.id for child in step_children}
        other_children = [child for child in children if child.id not in step_ids]
        return step_children + other_children
