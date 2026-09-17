"""Readability measurements on engine-neutral boxes and routed segments."""

import math
from itertools import combinations
from typing import Dict, Tuple

from .engines.base import Box, LayoutRequest, LayoutResult, Point, route_segments

EPSILON = 0.01


def overlaps(a: Box, b: Box, margin: float = 0) -> bool:
    return (
        a.x < b.x + b.width + margin - EPSILON
        and b.x < a.x + a.width + margin - EPSILON
        and a.y < b.y + b.height + margin - EPSILON
        and b.y < a.y + a.height + margin - EPSILON
    )


def segment_hits_box(a: Point, b: Point, box: Box) -> bool:
    """Whether the open interior of a rectangle intersects a line segment."""
    x0, y0 = box.x + EPSILON, box.y + EPSILON
    x1, y1 = box.x + box.width - EPSILON, box.y + box.height - EPSILON
    lo, hi = 0.0, 1.0
    for start, delta, minimum, maximum in (
        (a[0], b[0] - a[0], x0, x1),
        (a[1], b[1] - a[1], y0, y1),
    ):
        if abs(delta) < EPSILON:
            if not minimum < start < maximum:
                return False
        else:
            t0, t1 = (minimum - start) / delta, (maximum - start) / delta
            lo, hi = max(lo, min(t0, t1)), min(hi, max(t0, t1))
            if lo >= hi:
                return False
    return hi > lo


def segment_intersection(a: Point, b: Point, c: Point, d: Point) -> Tuple[int, float]:
    """Return proper crossing count and collinear overlap length."""
    ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    determinant = ux * vy - uy * vx
    if abs(determinant) > EPSILON:
        t = ((c[0] - a[0]) * vy - (c[1] - a[1]) * vx) / determinant
        s = ((c[0] - a[0]) * uy - (c[1] - a[1]) * ux) / determinant
        return (int(EPSILON < t < 1 - EPSILON and EPSILON < s < 1 - EPSILON), 0)
    if abs((c[0] - a[0]) * uy - (c[1] - a[1]) * ux) > EPSILON:
        return (0, 0)
    axis = 0 if abs(ux) >= abs(uy) else 1
    length = max(
        0,
        min(max(a[axis], b[axis]), max(c[axis], d[axis]))
        - max(min(a[axis], b[axis]), min(c[axis], d[axis])),
    )
    return (0, length)


def ancestors(request: LayoutRequest) -> Dict[str, set]:
    specs = {node.id: node for node in request.nodes}
    result = {}
    for node in request.nodes:
        seen = set()
        parent = node.parent_id
        while parent:
            if parent == node.id or parent in seen:
                raise ValueError(f"Containment cycle at '{node.id}'")
            if parent not in specs:
                raise ValueError(f"Missing container '{parent}'")
            seen.add(parent)
            parent = specs[parent].parent_id
        result[node.id] = seen
    return result


def validate_result(request: LayoutRequest, result: LayoutResult) -> None:
    """Reject incomplete, nonfinite, overlapping, or structurally invalid output."""
    if set(result.boxes) != {n.id for n in request.nodes}:
        raise ValueError("Layout engine must return exactly the requested node IDs")
    if set(result.routes) != {e.id for e in request.edges}:
        raise ValueError("Layout engine must return exactly the requested edge IDs")
    ancestry = ancestors(request)
    specs = {node.id: node for node in request.nodes}
    for node in request.nodes:
        box = result.boxes[node.id]
        if not all(math.isfinite(v) for v in (box.x, box.y, box.width, box.height)):
            raise ValueError("Layout engine returned nonfinite geometry")
        if box.width <= 0 or box.height <= 0:
            raise ValueError("Layout engine returned an empty node")
        if node.size_locked and (
            abs(box.width - node.width) > EPSILON or abs(box.height - node.height) > EPSILON
        ):
            raise ValueError(f"Layout changed the fixed size of '{node.id}'")
        if node.side_locked and result.port_sides.get(node.id) != node.side:
            raise ValueError(f"Layout changed the fixed port side of '{node.id}'")
        if node.parent_id:
            parent = result.boxes[node.parent_id]
            header_height = specs[node.parent_id].header_height
            if header_height and box.y < parent.y + header_height + request.padding - EPSILON:
                raise ValueError(f"Layout placed '{node.id}' inside its container heading")
            if (
                box.x < parent.x - EPSILON
                or box.y < parent.y - EPSILON
                or box.x + box.width > parent.x + parent.width + EPSILON
                or box.y + box.height > parent.y + parent.height + EPSILON
            ):
                raise ValueError(f"Layout placed '{node.id}' outside its container")
            template = request.part_templates.get(node.part_template)
            if node.fixed_position is not None and (template is None or not template.optimize):
                x, y = node.fixed_position
                if abs(box.x - parent.x - x) > EPSILON or abs(box.y - parent.y - y) > EPSILON:
                    raise ValueError(f"Layout changed the fixed port position of '{node.id}'")
            if node.is_port and node.side_locked:
                side = result.port_sides[node.id]
                delta = box.x + box.width / 2 - parent.x - parent.width / 2
                if (side == "WEST" and delta > EPSILON) or (side == "EAST" and delta < -EPSILON):
                    raise ValueError(f"Layout placed '{node.id}' in the wrong port bank")
    # Per-instance orders are constraints too, even for third-party adapters.
    for a, b in combinations((n for n in request.nodes if n.is_port), 2):
        if a.parent_id != b.parent_id or a.part_template or b.part_template:
            continue
        if result.port_sides.get(a.id) != result.port_sides.get(b.id):
            continue
        if a.order is None and b.order is None:
            continue
        first, second = sorted((a, b), key=lambda n: n.order if n.order is not None else math.inf)
        if result.boxes[first.id].y >= result.boxes[second.id].y - EPSILON:
            raise ValueError(f"Layout changed the port order of '{first.parent_id}'")
    for name, template in request.part_templates.items():
        reference = {}
        for parent_id, ports in template.instances.items():
            parent = result.boxes[parent_id]
            for role, port_id in ports.items():
                box = result.boxes[port_id]
                side = result.port_sides.get(port_id)
                if side not in {"WEST", "EAST"}:
                    raise ValueError(f"Layout omitted the bank for '{port_id}'")
                if role in template.locked_sides and side != template.locked_sides[role]:
                    raise ValueError(f"Layout changed the fixed port side of '{port_id}'")
                local = (box.x - parent.x, box.y - parent.y, box.width, box.height)
                if role in reference:
                    expected_side, expected = reference[role]
                    if side != expected_side or any(
                        abs(a - b) > EPSILON for a, b in zip(local, expected)
                    ):
                        raise ValueError(
                            f"Layout changed shared geometry for '{name}' role '{role}'"
                        )
                reference[role] = side, local
                delta = box.x + box.width / 2 - parent.x - parent.width / 2
                if (side == "WEST" and delta > EPSILON) or (side == "EAST" and delta < -EPSILON):
                    raise ValueError(f"Layout placed '{port_id}' in the wrong port bank")
            for order in template.locked_orders:
                for first, second in combinations(order, 2):
                    a, b = ports[first], ports[second]
                    if result.port_sides[a] == result.port_sides[b] and (
                        result.boxes[a].y >= result.boxes[b].y - EPSILON
                    ):
                        raise ValueError(f"Layout changed the fixed order for '{name}'")
    for a, b in combinations(result.boxes, 2):
        if a in ancestry[b] or b in ancestry[a]:
            continue
        if overlaps(result.boxes[a], result.boxes[b]):
            raise ValueError(f"Layout overlaps '{a}' and '{b}'")
    for edge in request.edges:
        route = result.routes[edge.id]
        if len(route.points) < 2 or not all(
            len(point) == 2 and all(math.isfinite(v) for v in point) for point in route.points
        ):
            raise ValueError(f"Layout returned an invalid route for '{edge.id}'")
        for point, node_id in ((route.points[0], edge.source), (route.points[-1], edge.target)):
            box = result.boxes[node_id]
            if not (
                box.x - 2 <= point[0] <= box.x + box.width + 2
                and box.y - 2 <= point[1] <= box.y + box.height + 2
            ):
                raise ValueError(f"Route '{edge.id}' is detached from '{node_id}'")
        if route.label is not None and (
            not all(
                math.isfinite(v)
                for v in (route.label.x, route.label.y, route.label.width, route.label.height)
            )
            or route.label.width <= 0
            or route.label.height <= 0
        ):
            raise ValueError(f"Layout returned an invalid label for '{edge.id}'")
        if route.connectors:
            if len(route.connectors) != 2 or request.edge_routing != "straight":
                raise ValueError(f"Route '{edge.id}' needs two straight reference connectors")
            for connector, local, remote in zip(
                route.connectors, (edge.source, edge.target), (edge.target, edge.source)
            ):
                label = connector.label
                if (
                    connector.target != remote or not connector.text
                    or len(connector.points) != 2
                    or not all(
                        len(p) == 2 and all(math.isfinite(v) for v in p)
                        for p in connector.points
                    )
                    or not all(math.isfinite(v) for v in (
                        label.x, label.y, label.width, label.height
                    ))
                    or min(label.width, label.height) <= 0
                ):
                    raise ValueError(f"Invalid reference connector for '{edge.id}'")
                for point, box in zip(connector.points, (result.boxes[local], label)):
                    if not (
                        box.x - 2 <= point[0] <= box.x + box.width + 2
                        and box.y - 2 <= point[1] <= box.y + box.height + 2
                    ):
                        raise ValueError(f"Detached reference connector for '{edge.id}'")
                if any(overlaps(label, box) for box in result.boxes.values()):
                    raise ValueError(f"Reference connector for '{edge.id}' overlaps a node")


def measure_quality(request: LayoutRequest, result: LayoutResult) -> Dict[str, float]:
    ancestry = ancestors(request)
    edges = {edge.id: edge for edge in request.edges}
    segments = {
        key: route_segments(route) for key, route in result.routes.items()
    }
    obstructions = crossings = label_collisions = 0
    shared_length = common_terminal_length = length = 0.0
    bends = 0
    labels = [(key, route.label) for key, route in result.routes.items() if route.label]
    labels.extend(
        (key, connector.label)
        for key, route in result.routes.items() for connector in route.connectors
    )
    for key, parts in segments.items():
        edge = edges[key]
        allowed = {edge.source, edge.target} | ancestry[edge.source] | ancestry[edge.target]
        if not result.routes[key].connectors:
            bends += max(0, len(parts) - 1)
        else:
            for (a, b), (c, d) in combinations(parts, 2):
                count, shared = segment_intersection(a, b, c, d)
                crossings += count
                shared_length += shared
        for a, b in parts:
            length += math.dist(a, b)
            obstructions += sum(
                segment_hits_box(a, b, box)
                for node_id, box in result.boxes.items()
                if node_id not in allowed
            )
    for first, second in combinations(segments, 2):
        for a, b in segments[first]:
            for c, d in segments[second]:
                count, shared = segment_intersection(a, b, c, d)
                crossings += count
                if {edges[first].source, edges[first].target} & {
                    edges[second].source,
                    edges[second].target,
                }:
                    common_terminal_length += shared
                else:
                    shared_length += shared
    for key, label in labels:
        label_collisions += sum(overlaps(label, box) for box in result.boxes.values())
        label_collisions += sum(
            segment_hits_box(a, b, label)
            for other, parts in segments.items()
            if other != key or result.routes[key].connectors
            for a, b in parts
        )
    label_collisions += sum(overlaps(a, b) for (_, a), (_, b) in combinations(labels, 2))
    boxes = list(result.boxes.values()) + [
        connector.label for route in result.routes.values() for connector in route.connectors
    ]
    # Headers are obstacles even to wires connected to ports in the same device.
    for node in request.nodes:
        if node.header_height:
            box = result.boxes[node.id]
            header = Box(
                box.x + request.padding, box.y, box.width - request.padding * 2, node.header_height
            )
            obstructions += sum(
                segment_hits_box(a, b, header) for parts in segments.values() for a, b in parts
            )
    width = max((b.x + b.width for b in boxes), default=0) - min((b.x for b in boxes), default=0)
    height = max((b.y + b.height for b in boxes), default=0) - min((b.y for b in boxes), default=0)
    return {
        "obstructions": obstructions,
        "crossings": crossings,
        "shared_length": round(shared_length, 1),
        "label_collisions": label_collisions,
        "common_terminal_length": round(common_terminal_length, 1),
        "bends": bends,
        "wire_length": round(length, 1),
        "width": round(width, 1),
        "height": round(height, 1),
        "aspect_ratio": round(max(width, height) / max(1, min(width, height)), 2),
        "reference_connections": sum(bool(route.connectors) for route in result.routes.values()),
        "reference_cost": sum(
            request.engine_options.get("crossing_edge_costs", {}).get(key, 1)
            for key, route in result.routes.items() if route.connectors
        ),
    }


def quality_key(metrics: Dict[str, float]) -> tuple:
    return (
        metrics["obstructions"],
        metrics["label_collisions"],
        metrics["crossings"] + metrics["shared_length"] / 80,
        metrics["aspect_ratio"],
        metrics["bends"] + metrics["wire_length"] / 100,
    )


def crossing_quality_key(metrics: Dict[str, float]) -> tuple:
    """Rank layouts for engines whose primary objective is uncrossed wires."""
    return (
        metrics["crossings"] + metrics["shared_length"] / 80,
        metrics["obstructions"],
        metrics["label_collisions"],
        metrics["aspect_ratio"],
        metrics["bends"] + metrics["wire_length"] / 100,
    )


def reference_quality_key(metrics: Dict[str, float]) -> tuple:
    """Charge for lost visual continuity as well as the geometry actually drawn."""
    return (
        20 * (metrics["obstructions"] + metrics["label_collisions"])
        + 10 * metrics["crossings"] + metrics["shared_length"] / 8
        + 3 * metrics.get("reference_cost", 0),
        metrics.get("reference_connections", 0),
        metrics["aspect_ratio"],
        metrics["wire_length"],
    )
