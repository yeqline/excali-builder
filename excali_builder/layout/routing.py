"""Straight and orthogonal routing independent of layout engines."""

import heapq
import time
from itertools import count
from typing import List

from .engines.base import Box, LayoutRequest, LayoutResult, Point, Route, route_segments
from .quality import ancestors, overlaps, segment_hits_box, segment_intersection


def simplify(points: List[Point]) -> List[Point]:
    result = []
    for point in points:
        point = (float(point[0]), float(point[1]))
        if result and point == result[-1]:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            if abs((b[0] - a[0]) * (point[1] - b[1]) - (b[1] - a[1]) * (point[0] - b[0])) > 0.01:
                break
            if ((b[0] - a[0]) * (point[0] - b[0]) + (b[1] - a[1]) * (point[1] - b[1])) < 0:
                break
            result.pop()
        result.append(point)
    return result


def route_straight(request: LayoutRequest, result: LayoutResult, edge_ids=None) -> None:
    """Connect endpoint boundaries with one segment while preserving node positions."""
    requested = set(edge_ids) if edge_ids is not None else {e.id for e in request.edges}
    referenced = {key for key, route in result.routes.items() if route.connectors}
    result.routes = {
        key: route for key, route in result.routes.items() if key not in requested
    }
    for edge in request.edges:
        if edge.id not in requested:
            continue
        source = result.boxes[edge.source]
        target = result.boxes[edge.target]
        source_center = (source.x + source.width / 2, source.y + source.height / 2)
        target_center = (target.x + target.width / 2, target.y + target.height / 2)
        result.routes[edge.id] = Route(
            [
                _box_boundary_toward(source, target_center, 1),
                _box_boundary_toward(target, source_center, -1),
            ]
        )
    if referenced & requested:
        from .references import refresh_connectors

        refresh_connectors(request, result, referenced & requested)
    place_labels(request, result)


def _box_boundary_toward(box: Box, other: Point, coincident_direction: int) -> Point:
    center_x, center_y = box.x + box.width / 2, box.y + box.height / 2
    dx, dy = other[0] - center_x, other[1] - center_y
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return (center_x + coincident_direction * box.width / 2, center_y)
    scale = min(
        box.width / 2 / abs(dx) if abs(dx) >= 0.01 else float("inf"),
        box.height / 2 / abs(dy) if abs(dy) >= 0.01 else float("inf"),
    )
    return (center_x + dx * scale, center_y + dy * scale)


def route_fixed(request: LayoutRequest, result: LayoutResult, edge_ids=None) -> None:
    """Reroute changed connections in the requested style, preserving node positions."""
    if request.edge_routing == "straight":
        route_straight(request, result, edge_ids)
        return
    ancestry = ancestors(request)
    deadline = time.monotonic() + request.timeout
    specs = {node.id: node for node in request.nodes}
    requested = set(edge_ids) if edge_ids is not None else {e.id for e in request.edges}
    retained = {key: route for key, route in result.routes.items() if key not in requested}
    result.routes = retained
    for edge in sorted(request.edges, key=lambda e: (e.role == "annotation", e.id)):
        if edge.id not in requested:
            continue
        allowed = {edge.source, edge.target} | ancestry[edge.source] | ancestry[edge.target]
        shared_ancestors = ancestry[edge.source] & ancestry[edge.target]
        obstacles = [
            box
            for key, box in result.boxes.items()
            if key not in {edge.source, edge.target} | shared_ancestors
            and not (ancestry[key] - allowed)
        ]
        start, start_exit = _anchor(
            edge.source, edge.target, specs, result, ancestry, request.wire_spacing
        )
        end, end_exit = _anchor(
            edge.target, edge.source, specs, result, ancestry, request.wire_spacing
        )
        existing = [
            part for route in result.routes.values() for part in zip(route.points, route.points[1:])
        ]
        # The end stubs deliberately cross their own enclosing frame, but must
        # not pass through another port or device.
        stub_obstacles = [box for key, box in result.boxes.items() if key not in allowed]
        if any(
            segment_hits_box(a, b, box)
            for a, b in ((start, start_exit), (end, end_exit))
            for box in stub_obstacles
        ):
            raise ValueError("A port is blocked by another node. Optimize the wiring layout.")
        middle = _find_path(
            start_exit, end_exit, obstacles, request.wire_spacing, existing, deadline
        )
        result.routes[edge.id] = Route(simplify([start, *middle, end]))
    place_labels(request, result)


def _anchor(node_id, other_id, specs, result, ancestry, spacing):
    box, other = result.boxes[node_id], result.boxes[other_id]
    side = result.port_sides.get(node_id)
    if side is None:
        dx = other.x + other.width / 2 - box.x - box.width / 2
        dy = other.y + other.height / 2 - box.y - box.height / 2
        side = (
            ("EAST" if dx >= 0 else "WEST")
            if abs(dx) >= abs(dy)
            else ("SOUTH" if dy >= 0 else "NORTH")
        )
    # Only leave ancestors not shared by the other endpoint.
    boundary = box
    for parent_id in ancestry[node_id] - ancestry[other_id]:
        parent = result.boxes[parent_id]
        if parent.width >= boundary.width and parent.height >= boundary.height:
            boundary = parent
    if side == "EAST":
        return (box.x + box.width, box.y + box.height / 2), (
            boundary.x + boundary.width + spacing,
            box.y + box.height / 2,
        )
    if side == "WEST":
        return (box.x, box.y + box.height / 2), (boundary.x - spacing, box.y + box.height / 2)
    if side == "SOUTH":
        return (box.x + box.width / 2, box.y + box.height), (
            box.x + box.width / 2,
            boundary.y + boundary.height + spacing,
        )
    return (box.x + box.width / 2, box.y), (box.x + box.width / 2, boundary.y - spacing)


def _find_path(start, end, boxes, spacing, existing, deadline=None):
    """A* on obstacle-boundary coordinates; length, bends and crossings cost effort."""
    xs = sorted(
        {start[0], end[0], *[v for b in boxes for v in (b.x - spacing, b.x + b.width + spacing)]}
    )
    ys = sorted(
        {start[1], end[1], *[v for b in boxes for v in (b.y - spacing, b.y + b.height + spacing)]}
    )
    source, target = (xs.index(start[0]), ys.index(start[1])), (xs.index(end[0]), ys.index(end[1]))
    serial = count()
    queue = [(0, next(serial), source[0], source[1], -1)]
    distance = {(source[0], source[1], -1): 0}
    previous = {}
    cache = {}
    finish = None
    while queue:
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError("Wire routing exceeded the time budget. Optimize the wiring layout.")
        _, _, ix, iy, direction = heapq.heappop(queue)
        state = (ix, iy, direction)
        cost = distance[state]
        if (ix, iy) == target:
            finish = state
            break
        for nx, ny, nd in ((ix - 1, iy, 0), (ix + 1, iy, 0), (ix, iy - 1, 1), (ix, iy + 1, 1)):
            if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                continue
            a, b = (xs[ix], ys[iy]), (xs[nx], ys[ny])
            key = tuple(sorted((a, b)))
            if key not in cache:
                if any(segment_hits_box(a, b, box) for box in boxes):
                    cache[key] = None
                else:
                    penalty = 0
                    for c, d in existing:
                        crossing, shared = segment_intersection(a, b, c, d)
                        penalty += crossing * 80 + shared * 2
                    cache[key] = abs(a[0] - b[0]) + abs(a[1] - b[1]) + penalty
            if cache[key] is None:
                continue
            value = cost + cache[key] + (40 if direction != -1 and direction != nd else 0)
            next_state = (nx, ny, nd)
            if value < distance.get(next_state, float("inf")):
                distance[next_state] = value
                previous[next_state] = state
                heuristic = abs(xs[nx] - end[0]) + abs(ys[ny] - end[1])
                heapq.heappush(queue, (value + heuristic, next(serial), nx, ny, nd))
    if finish is None:
        raise ValueError(
            "A wire cannot leave its port without crossing a device. Optimize the layout."
        )
    points = []
    while finish is not None:
        points.append((xs[finish[0]], ys[finish[1]]))
        finish = previous.get(finish)
    return simplify(list(reversed(points)))


def place_labels(request: LayoutRequest, result: LayoutResult) -> None:
    """Choose labels on route segments with the least interference and ample length."""
    occupied = [c.label for route in result.routes.values() for c in route.connectors]
    all_segments = {
        key: route_segments(route) for key, route in result.routes.items()
    }
    for edge in sorted(request.edges, key=lambda e: e.id):
        route = result.routes[edge.id]
        if route.connectors or not edge.label_width:
            route.label = None
            continue
        candidates = (
            [route.label] if route.label and abs(route.label.width - edge.label_width) < 1 else []
        )
        for a, b in all_segments[edge.id]:
            for t in (0.5, 0.25, 0.75):
                cx, cy = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                dx, dy = b[0] - a[0], b[1] - a[1]
                segment_length = (dx * dx + dy * dy) ** 0.5
                if segment_length < 0.01:
                    continue
                normal_x, normal_y = -dy / segment_length, dx / segment_length
                offset = (
                    abs(normal_x) * edge.label_width
                    + abs(normal_y) * edge.label_height
                ) / 2 + 6
                for sign in (-1, 1):
                    candidates.append(
                        Box(
                            cx + sign * normal_x * offset - edge.label_width / 2,
                            cy + sign * normal_y * offset - edge.label_height / 2,
                            edge.label_width,
                            edge.label_height,
                        )
                    )

        def cost(label):
            return (
                sum(overlaps(label, b, 3) for b in result.boxes.values()),
                sum(overlaps(label, b, 5) for b in occupied),
                sum(
                    segment_hits_box(a, b, label)
                    for key, parts in all_segments.items()
                    if key != edge.id
                    for a, b in parts
                ),
            )

        if candidates:
            route.label = min(candidates, key=cost)
            occupied.append(route.label)
