"""Layered DAG layout for dependency-oriented diagrams."""

from collections import defaultdict, deque
from typing import Dict, Iterable, List, Set

from ..core.edge import ConnectionType
from ..core.graph import Graph
from ..core.node import Node
from .base import BaseLayout


class DagLayout(BaseLayout):
    """Place nodes in dependency ranks while preserving saved geometry."""

    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Apply a layered DAG layout to graph nodes."""
        direction = config.get("direction", "left-right")
        level_spacing = config.get("level_spacing", 220)
        sibling_spacing = config.get("sibling_spacing", 60)
        root_spacing = config.get("root_spacing", 120)
        start_x = config.get("start_x", 120)
        start_y = config.get("start_y", 120)
        rank_edge_types = set(config.get("rank_edge_types") or ["lineage"])

        group_node_ids = {
            node.id
            for node in graph.nodes.values()
            if (node.metadata or {}).get("dbt_overlay_kind") == "group"
        }
        local_node_ids = self._get_local_node_ids(graph)
        ranked_node_ids = set(graph.nodes) - group_node_ids - local_node_ids

        ranks = self._rank_nodes(graph, ranked_node_ids, rank_edge_types)
        self._place_ranked_nodes(
            graph,
            ranks,
            direction,
            level_spacing,
            sibling_spacing,
            start_x,
            start_y,
        )
        self._place_group_nodes(
            graph,
            group_node_ids,
            direction,
            sibling_spacing,
        )
        self._place_local_nodes(graph, local_node_ids, direction, sibling_spacing)
        self._place_remaining_nodes(
            graph,
            direction,
            root_spacing,
            start_x,
            start_y,
        )

    def _get_local_node_ids(self, graph: Graph) -> Set[str]:
        """Return nodes that should stay visually attached to a parent."""
        local_types = {"comment", "image"}
        return {
            node.id
            for node in graph.nodes.values()
            if node.type in local_types
            and (node.metadata or {}).get("hierarchy_parent_id") in graph.nodes
        }

    def _rank_nodes(
        self,
        graph: Graph,
        node_ids: Set[str],
        rank_edge_types: Set[str],
    ) -> Dict[str, int]:
        """Assign each node to the longest upstream dependency rank."""
        outgoing: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
        incoming_count: Dict[str, int] = {node_id: 0 for node_id in node_ids}

        for edge in graph.edges:
            if edge.edge_type not in rank_edge_types:
                continue
            if edge.source_id not in node_ids or edge.target_id not in node_ids:
                continue
            outgoing[edge.source_id].append(edge.target_id)
            incoming_count[edge.target_id] += 1

        ranks = {node_id: 0 for node_id in node_ids}
        queue = deque(sorted(node_id for node_id in node_ids if incoming_count[node_id] == 0))
        visited: Set[str] = set()

        while queue:
            node_id = queue.popleft()
            visited.add(node_id)
            for target_id in sorted(outgoing[node_id]):
                ranks[target_id] = max(ranks[target_id], ranks[node_id] + 1)
                incoming_count[target_id] -= 1
                if incoming_count[target_id] == 0:
                    queue.append(target_id)

        if len(visited) == len(node_ids):
            return ranks

        remaining = sorted(node_ids - visited)
        fallback_rank = max(ranks.values(), default=0) + 1
        for node_id in remaining:
            ranks[node_id] = fallback_rank
            fallback_rank += 1
        return ranks

    def _place_ranked_nodes(
        self,
        graph: Graph,
        ranks: Dict[str, int],
        direction: str,
        level_spacing: float,
        sibling_spacing: float,
        start_x: float,
        start_y: float,
    ) -> None:
        layers: Dict[int, List[Node]] = defaultdict(list)
        for node_id, rank in ranks.items():
            layers[rank].append(graph.nodes[node_id])

        for nodes in layers.values():
            nodes.sort(key=self._node_sort_key)

        rank_offsets = self._rank_offsets(layers, direction, level_spacing)
        horizontal = direction in {"left-right", "right-left"}

        for rank in sorted(layers):
            offset = rank_offsets[rank]
            sibling_offset = start_y if horizontal else start_x
            for node in layers[rank]:
                width = node.width or 100
                height = node.height or 50
                if node.x is None or node.y is None:
                    if direction == "right-left":
                        node.x = start_x - offset
                        node.y = sibling_offset
                    elif direction == "bottom-up":
                        node.x = sibling_offset
                        node.y = start_y - offset
                    elif direction == "top-down":
                        node.x = sibling_offset
                        node.y = start_y + offset
                    else:
                        node.x = start_x + offset
                        node.y = sibling_offset

                sibling_offset += (height if horizontal else width) + sibling_spacing

    def _rank_offsets(
        self,
        layers: Dict[int, List[Node]],
        direction: str,
        level_spacing: float,
    ) -> Dict[int, float]:
        horizontal = direction in {"left-right", "right-left"}
        offsets: Dict[int, float] = {}
        current_offset = 0.0

        for rank in sorted(layers):
            offsets[rank] = current_offset
            layer_span = max(
                (
                    (node.width or 100) if horizontal else (node.height or 50)
                    for node in layers[rank]
                ),
                default=0,
            )
            current_offset += layer_span + level_spacing

        return offsets

    def _place_group_nodes(
        self,
        graph: Graph,
        group_node_ids: Set[str],
        direction: str,
        sibling_spacing: float,
    ) -> None:
        group_children: Dict[str, List[str]] = defaultdict(list)
        for edge in graph.edges:
            if (
                edge.connection_type == ConnectionType.GROUP
                and edge.edge_type == "group_member"
                and edge.source_id in group_node_ids
            ):
                group_children[edge.source_id].append(edge.target_id)

        positioned: Set[str] = set()

        def place_group(group_id: str, visiting: Set[str]) -> None:
            if group_id in positioned or group_id in visiting:
                return
            visiting.add(group_id)

            for child_id in sorted(group_children.get(group_id, [])):
                if child_id in group_node_ids:
                    place_group(child_id, visiting)

            group = graph.nodes[group_id]
            if group.x is None or group.y is None:
                children = [
                    graph.nodes[child_id]
                    for child_id in group_children.get(group_id, [])
                    if child_id in graph.nodes
                    and graph.nodes[child_id].x is not None
                    and graph.nodes[child_id].y is not None
                ]
                if children:
                    min_x = min(child.x or 0 for child in children)
                    min_y = min(child.y or 0 for child in children)
                    width = group.width or 100
                    height = group.height or 50
                    if direction in {"top-down", "bottom-up"}:
                        group.x = min_x - width - sibling_spacing
                        group.y = min_y
                    else:
                        group.x = min_x
                        group.y = min_y - height - sibling_spacing

            visiting.remove(group_id)
            positioned.add(group_id)

        for group_id in sorted(group_node_ids):
            place_group(group_id, set())

    def _place_local_nodes(
        self,
        graph: Graph,
        local_node_ids: Set[str],
        direction: str,
        sibling_spacing: float,
    ) -> None:
        children_by_parent: Dict[str, List[Node]] = defaultdict(list)
        for node_id in local_node_ids:
            node = graph.nodes[node_id]
            parent_id = (node.metadata or {}).get("hierarchy_parent_id")
            if parent_id in graph.nodes:
                children_by_parent[parent_id].append(node)

        horizontal = direction in {"left-right", "right-left"}
        for parent_id, children in children_by_parent.items():
            parent = graph.nodes[parent_id]
            if parent.x is None or parent.y is None:
                continue
            children.sort(key=self._node_sort_key)
            offset = 0.0
            for child in children:
                if child.x is None or child.y is None:
                    if horizontal:
                        child.x = parent.x
                        child.y = parent.y + (parent.height or 50) + sibling_spacing + offset
                        offset += (child.height or 50) + sibling_spacing
                    else:
                        child.x = parent.x + (parent.width or 100) + sibling_spacing + offset
                        child.y = parent.y
                        offset += (child.width or 100) + sibling_spacing

    def _place_remaining_nodes(
        self,
        graph: Graph,
        direction: str,
        root_spacing: float,
        start_x: float,
        start_y: float,
    ) -> None:
        unplaced = [
            node
            for node in graph.nodes.values()
            if node.x is None or node.y is None
        ]
        unplaced.sort(key=self._node_sort_key)
        if not unplaced:
            return

        next_offset = self._next_remaining_offset(graph.nodes.values(), direction, start_x, start_y)
        for node in unplaced:
            if direction in {"left-right", "right-left"}:
                node.x = start_x
                node.y = next_offset
                next_offset += (node.height or 50) + root_spacing
            else:
                node.x = next_offset
                node.y = start_y
                next_offset += (node.width or 100) + root_spacing

    def _next_remaining_offset(
        self,
        nodes: Iterable[Node],
        direction: str,
        start_x: float,
        start_y: float,
    ) -> float:
        horizontal = direction in {"left-right", "right-left"}
        next_offset = start_y if horizontal else start_x
        for node in nodes:
            if node.x is None or node.y is None:
                continue
            if horizontal:
                next_offset = max(next_offset, (node.y or 0) + (node.height or 50))
            else:
                next_offset = max(next_offset, (node.x or 0) + (node.width or 100))
        return next_offset

    def _node_sort_key(self, node: Node):
        metadata = node.metadata or {}
        return (
            str(metadata.get("dbt_project") or ""),
            str(metadata.get("dbt_resource_type") or ""),
            str(metadata.get("dbt_schema") or ""),
            str(metadata.get("dbt_name") or node.label or node.id),
            metadata.get("source_order", 0),
            node.id,
        )
