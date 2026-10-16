"""Compound wiring layout, candidate selection, and preservation of manual placement."""

import copy
import heapq
import math
import textwrap
import time
from collections import Counter
from dataclasses import asdict
from typing import Dict, Optional

from ..core.edge import ConnectionType
from .engines import get_engine
from .engines.base import Box, LayoutEdge, LayoutNode, LayoutRequest, LayoutResult, route_segments
from .parts import apply_part_geometry, describe_parts, optimize_parts, prepare_parts, restore_parts
from .quality import (
    ancestors,
    crossing_quality_key,
    measure_quality,
    overlaps,
    quality_key,
    reference_quality_key,
    segment_hits_box,
    validate_result,
)
from .routing import place_labels, route_straight, simplify


def make_request(graph, config) -> LayoutRequest:
    settings = config.layout.wiring
    parents = {}
    for edge in graph.edges:
        if edge.connection_type != ConnectionType.ENCLOSING_GROUP:
            continue
        if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
            raise ValueError("A containment relationship references a missing node")
        if edge.target_id in parents and parents[edge.target_id] != edge.source_id:
            raise ValueError(f"'{edge.target_id}' belongs to more than one container")
        parents[edge.target_id] = edge.source_id
    orders = {}
    for parent, ports in settings.port_order.items():
        if len(ports) != len(set(ports)):
            raise ValueError(f"Duplicate port in port_order for '{parent}'")
        for index, port in enumerate(ports):
            if parents.get(port) != parent:
                raise ValueError(f"Port '{port}' does not belong to '{parent}'")
            orders[port] = index
    unknown = set(settings.port_sides) - set(parents)
    if unknown:
        raise ValueError(f"Unknown contained ports in port_sides: {sorted(unknown)}")
    nodes = []
    edges = []
    outgoing, incoming = Counter(), Counter()
    for edge in graph.edges:
        if edge.connection_type != ConnectionType.LINE:
            continue
        if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
            raise ValueError(f"Wire '{edge.id}' references a missing node")
        from ..config.loader import ConfigLoader

        style = ConfigLoader.get_line_config(config, edge.edge_type)
        label = edge.label if style.show_label else None
        label_lines = []
        if label:
            characters = max(8, int(settings.label_max_width / (style.label_font_size * 0.6)))
            label_lines = [
                line
                for paragraph in label.splitlines()
                for line in (textwrap.wrap(paragraph, characters) or [""])
            ]
            edge.metadata["layout_label_text"] = "\n".join(label_lines)
        role = settings.edge_roles.get(edge.edge_type, "flow")
        edges.append(
            LayoutEdge(
                edge.id,
                edge.source_id,
                edge.target_id,
                max(30, max(map(len, label_lines)) * style.label_font_size * 0.6) if label else 0,
                style.label_font_size * 1.25 * len(label_lines) if label else 0,
                role,
                source_reference=_reference_name(graph, parents, edge.source_id),
                target_reference=_reference_name(graph, parents, edge.target_id),
                label_text="\n".join(label_lines),
                font_size=style.label_font_size,
            )
        )
        weight = 3 if role == "flow" else 1
        outgoing[edge.source_id] += weight
        incoming[edge.target_id] += weight
    owners = set(parents.values())
    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        is_port = node.id in parents and node.type in settings.port_types and node.id not in owners
        side = settings.port_sides.get(node.id)
        if is_port and side is None:
            right = outgoing[node.id] > incoming[node.id]
            if config.layout.direction == "right-left":
                right = not right
            side = "EAST" if right else "WEST"
        fixed = settings.fixed_sizes.get(node.id)
        if fixed and (len(fixed) != 2 or min(fixed) <= 0 or not all(map(math.isfinite, fixed))):
            raise ValueError(f"fixed_sizes['{node.id}'] must contain a positive width and height")
        nodes.append(
            LayoutNode(
                node.id,
                fixed[0] if fixed else node.width or 100,
                fixed[1] if fixed else node.height or 50,
                parents.get(node.id),
                is_port,
                (node.metadata or {}).get("layout_header_height", 0) if node.id in owners else 0,
                side,
                orders.get(node.id),
                size_locked=bool(fixed),
                side_locked=node.id in settings.port_sides,
            )
        )
    request = LayoutRequest(
        nodes,
        edges,
        config.layout.direction,
        settings.node_spacing,
        config.layout.level_spacing,
        settings.wire_spacing,
        settings.port_spacing,
        settings.padding,
        timeout=settings.timeout_seconds,
        engine_options=settings.engine_options,
        edge_routing=settings.edge_routing,
        label_max_width=settings.label_max_width,
    )
    ancestors(request)
    # Opposing port banks must fit beside one another inside the device.
    for node in nodes:
        ports = [port for port in nodes if port.is_port and port.parent_id == node.id]
        if ports:
            bank_width = max(p.width for p in ports)
            minimum_width = 2 * bank_width + settings.padding * 3
            minimum_height = (
                node.header_height + max(p.height for p in ports) + settings.padding * 2
            )
            if node.size_locked and (node.width < minimum_width or node.height < minimum_height):
                raise ValueError(
                    f"Fixed size for '{node.id}' is too small for its ports and header"
                )
            node.width = max(node.width, minimum_width)
            node.height = max(node.height, minimum_height)
    prepare_parts(request, settings, graph)
    return request


def _reference_name(graph, parents, node_id):
    names = [graph.nodes[node_id].label]
    seen = {node_id}
    parent = parents.get(node_id)
    while parent and parent not in seen:
        seen.add(parent)
        names.insert(0, graph.nodes[parent].label)
        parent = parents.get(parent)
    return f"{' / '.join(names)} [{node_id}]"


def optimize(
    request: LayoutRequest, engine_name: str, candidates: int, fixed_sides: Dict[str, str]
) -> LayoutResult:
    """Compare deterministic candidates, including a pass aimed at remote neighbors."""
    engine = get_engine(engine_name)
    deadline = time.monotonic() + request.timeout
    best = None
    failures = []
    attempted = 0
    candidate_key = (
        reference_quality_key if engine_name == "crossing"
        else crossing_quality_key if engine_name == "hybrid" else quality_key
    )
    for index in range(candidates):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        candidate_request = copy.deepcopy(request)
        if best is not None:
            restore_parts(candidate_request, best.metrics)
        candidate_request.seed = index + 1
        candidate_request.timeout = remaining
        candidate_deadline = deadline
        if engine_name == "crossing":
            share = remaining / (candidates - index)
            candidate_request.timeout = share * .8
            candidate_deadline = time.monotonic() + share
        # The hybrid engine performs its own orientation search so that its
        # crossing score uses the same endpoint order as the final straight
        # routes. Avoid reversing edges twice around that engine.
        reversed_edges = (
            _breadth_orientation(candidate_request, fixed_sides)
            if engine_name not in {"hybrid", "crossing"} and index % 4 in {1, 2}
            else set()
        )
        if best is not None and index % 4 in {2, 3}:
            _face_neighbors(candidate_request, best, fixed_sides)
        attempted += 1
        try:
            result = engine.layout(candidate_request)
            scoring_request = copy.deepcopy(candidate_request)
            scoring_request.edges = copy.deepcopy(request.edges)
            moved_ports = apply_part_geometry(scoring_request, result)
            if request.edge_routing == "straight":
                route_straight(request, result)
            else:
                for edge_id in reversed_edges:
                    result.routes[edge_id].points.reverse()
                for route in result.routes.values():
                    route.points = simplify(route.points)
                if moved_ports:
                    from .routing import route_fixed

                    routing_request = copy.copy(scoring_request)
                    routing_request.timeout = max(0.001, deadline - time.monotonic())
                    route_fixed(routing_request, result)
            validate_result(request, result)
            if request.edge_routing != "straight":
                place_labels(request, result)
            template_trials = optimize_parts(
                scoring_request, result, candidate_key, candidate_deadline
            )
            if engine_name == "crossing":
                from .references import select_connectors

                # Template search can change both the conflicts and the space
                # available for reference tags; choose again on final geometry.
                previous = copy.deepcopy(result)
                select_connectors(scoring_request, result, candidate_deadline)
                if candidate_key(measure_quality(scoring_request, previous)) < candidate_key(
                    measure_quality(scoring_request, result)
                ):
                    result = previous
            validate_result(request, result)
            result.metrics.update(measure_quality(request, result))
            if request.part_templates:
                result.metrics["part_templates"] = describe_parts(scoring_request, result)
                result.metrics["part_template_trials"] = template_trials
            if best is None or candidate_key(result.metrics) < candidate_key(best.metrics):
                best = result
        except (ValueError, RuntimeError) as exc:
            failures.append(str(exc))
    if best is None:
        raise ValueError(
            f"No valid wiring layout: {failures[0] if failures else 'time budget exhausted'}"
        )
    best.metrics["candidates"] = attempted
    best.metrics["engine"] = engine_name
    if failures:
        best.metrics["rejected_candidates"] = len(failures)
    return best


def _breadth_orientation(request, fixed_sides):
    """Try a compact undirected reading order without changing electrical endpoints."""
    specs = {node.id: node for node in request.nodes}

    def owner(key):
        while specs[key].parent_id:
            key = specs[key].parent_id
        return key

    neighbors = {node.id: [] for node in request.nodes if not node.parent_id}
    incoming, outgoing = Counter(), Counter()
    for edge in request.edges:
        a, b = owner(edge.source), owner(edge.target)
        if a == b or edge.role == "annotation":
            continue
        weight = 1 if edge.role == "flow" else 3
        neighbors[a].append((b, weight))
        neighbors[b].append((a, weight))
        if edge.role == "flow":
            incoming[b] += 1
            outgoing[a] += 1
    roots = sorted(neighbors, key=lambda key: (incoming[key] != 0, -outgoing[key], key))
    ranks = {}
    for root in roots:
        if root in ranks:
            continue
        ranks[root] = 0
        queue = [(0, root)]
        while queue:
            distance, key = heapq.heappop(queue)
            if distance != ranks[key]:
                continue
            for other, weight in neighbors[key]:
                if distance + weight < ranks.get(other, float("inf")):
                    ranks[other] = distance + weight
                    heapq.heappush(queue, (distance + weight, other))
    reversed_edges = set()
    ins, outs = Counter(), Counter()
    for edge in request.edges:
        a, b = owner(edge.source), owner(edge.target)
        if a != b and (ranks[a], a) > (ranks[b], b):
            edge.source, edge.target = edge.target, edge.source
            reversed_edges.add(edge.id)
        outs[edge.source] += 1
        ins[edge.target] += 1
    for node in request.nodes:
        if (node.is_port and not node.side_locked and node.fixed_position is None
                and node.id not in fixed_sides and node.order is None):
            node.side = "EAST" if outs[node.id] > ins[node.id] else "WEST"
            if request.direction == "right-left":
                node.side = "WEST" if node.side == "EAST" else "EAST"
    return reversed_edges


def _face_neighbors(request, result, fixed_sides):
    neighbors = {}
    for edge in request.edges:
        weight = 3 if edge.role == "flow" else 1
        neighbors.setdefault(edge.source, []).append((edge.target, weight))
        neighbors.setdefault(edge.target, []).append((edge.source, weight))
    for node in request.nodes:
        if (not node.is_port or node.side_locked or node.fixed_position is not None
                or node.id in fixed_sides or node.order is not None):
            continue
        connected = neighbors.get(node.id, [])
        if not connected:
            continue
        center = sum(
            (result.boxes[key].x + result.boxes[key].width / 2) * weight
            for key, weight in connected
        ) / sum(weight for _, weight in connected)
        parent = result.boxes[node.parent_id]
        node.side = "WEST" if center < parent.x + parent.width / 2 else "EAST"


def existing_layout(graph, request, saved: Optional[LayoutResult]) -> LayoutResult:
    """Recover geometry and reference choices, marking affected references for rerouting."""
    boxes = {
        node.id: Box(node.x, node.y, node.width, node.height)
        for node in graph.nodes.values()
        if node.x is not None and node.y is not None
    }
    sides = {}
    for node in request.nodes:
        if node.is_port and node.id in boxes and node.parent_id in boxes:
            box, parent = boxes[node.id], boxes[node.parent_id]
            sides[node.id] = (
                "WEST" if box.x + box.width / 2 < parent.x + parent.width / 2 else "EAST"
            )
    result = LayoutResult(boxes, {}, sides)
    restored = restore_parts(request, saved.metrics) if saved else set()
    result.metrics["part_template_search_required"] = any(
        template.optimize and template.instances and name not in restored
        for name, template in request.part_templates.items()
    )
    apply_part_geometry(request, result, resize_containers=True)
    if saved:
        changed = {
            key
            for key, box in boxes.items()
            if key not in saved.boxes
            or not all(
                abs(a - b) < 0.01
                for a, b in zip(asdict(box).values(), asdict(saved.boxes[key]).values())
            )
        }
        ancestry = ancestors(request)
        for edge in request.edges:
            route = saved.routes.get(edge.id)
            if not route:
                continue
            allowed = {edge.source, edge.target} | ancestry[edge.source] | ancestry[edge.target]
            if route.connectors:
                # Keep the selected wire even when its endpoint moves. Its
                # hidden full span is irrelevant to obstacle checks.
                result.routes[edge.id] = copy.deepcopy(route)
                if changed & allowed or any(
                    overlaps(connector.label, boxes[key], 6)
                    for connector in route.connectors
                    for key in changed
                ) or any(
                    segment_hits_box(a, b, boxes[key])
                    for key in changed - allowed
                    for a, b in route_segments(route)
                ):
                    result.metrics.setdefault("_routes_to_refresh", []).append(edge.id)
                continue
            if edge.source in changed or edge.target in changed:
                continue
            if request.edge_routing == "straight" and len(route.points) != 2:
                continue
            if request.edge_routing == "orthogonal" and any(
                abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
                for a, b in zip(route.points, route.points[1:])
            ):
                continue
            if any(
                segment_hits_box(a, b, boxes[key])
                for key in changed - allowed
                for a, b in zip(route.points, route.points[1:])
            ):
                continue
            result.routes[edge.id] = route
    return result


def _cannot_grow_parent(request, result, specs, ancestry, parent_id, grown):
    relatives = (
        ancestry[parent_id]
        | {parent_id}
        | {child for child in specs if parent_id in ancestry[child]}
    )
    blocked = any(
        overlaps(grown, other, request.node_spacing / 2)
        for child, other in result.boxes.items()
        if child not in relatives
    )
    enclosing = specs[parent_id].parent_id
    if enclosing:
        outer = result.boxes[enclosing]
        blocked = blocked or grown.y + grown.height > outer.y + outer.height - request.padding
        blocked = blocked or grown.x + grown.width > outer.x + outer.width - request.padding
    return blocked or specs[parent_id].size_locked


def place_additions(request: LayoutRequest, result: LayoutResult, candidate: LayoutResult) -> None:
    """Place new devices in free space and new ports inside their existing owners."""
    specs = {node.id: node for node in request.nodes}
    ancestry = ancestors(request)
    missing = set(specs) - set(result.boxes)
    roots = sorted(key for key in missing if specs[key].parent_id not in missing)
    for key in roots:
        node = specs[key]
        descendants = {child for child in missing if key in ancestry[child]} | {key}
        if node.parent_id and node.fixed_position is not None:
            parent = result.boxes[node.parent_id]
            x, y = node.fixed_position
            position = Box(parent.x + x, parent.y + y, node.width, node.height)
        elif node.parent_id and node.is_port:
            parent = result.boxes[node.parent_id]
            siblings = [
                box
                for child, box in result.boxes.items()
                if specs[child].parent_id == node.parent_id
            ]
            width, height = candidate.boxes[key].width, candidate.boxes[key].height
            position = None
            for y in range(
                math.ceil(parent.y + specs[node.parent_id].header_height + request.padding),
                int(parent.y + parent.height - height - request.padding + 1),
                max(1, int(height + request.port_spacing)),
            ):
                bank_x = {
                    "WEST": parent.x + request.padding,
                    "EAST": parent.x + parent.width - width - request.padding,
                }
                side = node.side or "WEST"
                choices = [bank_x[side]]
                if not node.side_locked:
                    choices.append(bank_x["WEST" if side == "EAST" else "EAST"])
                for x in choices:
                    box = Box(x, y, width, height)
                    if not any(
                        overlaps(box, other, request.port_spacing / 2) for other in siblings
                    ):
                        position = box
                        break
                if position:
                    break
            if position is None:
                grown = Box(
                    parent.x,
                    parent.y,
                    max(parent.width, width + request.padding * 2),
                    parent.height + height + request.port_spacing + request.padding,
                )
                if _cannot_grow_parent(request, result, specs, ancestry, node.parent_id, grown):
                    raise ValueError(
                        f"No room for new port '{key}' in '{node.parent_id}'. "
                        "Run Optimize wiring layout."
                    )
                result.boxes[node.parent_id] = grown
                position = Box(
                    grown.x + request.padding
                    if node.side == "WEST"
                    else grown.x + grown.width - request.padding - width,
                    parent.y + parent.height + request.port_spacing,
                    width,
                    height,
                )
        elif node.parent_id:
            parent = result.boxes[node.parent_id]
            origin = candidate.boxes[key]
            siblings = [
                box
                for child, box in result.boxes.items()
                if specs[child].parent_id == node.parent_id
            ]
            inner_left = parent.x + request.padding
            inner_top = parent.y + specs[node.parent_id].header_height + request.padding
            inner_right = parent.x + parent.width - request.padding
            inner_bottom = parent.y + parent.height - request.padding
            cand_parent = candidate.boxes.get(node.parent_id)
            preferred = Box(
                parent.x + (origin.x - cand_parent.x) if cand_parent else inner_left,
                parent.y + (origin.y - cand_parent.y) if cand_parent else inner_top,
                origin.width,
                origin.height,
            )

            def nested_fits(box):
                if (
                    box.x < inner_left - 0.01
                    or box.y < inner_top - 0.01
                    or box.x + box.width > inner_right + 0.01
                    or box.y + box.height > inner_bottom + 0.01
                ):
                    return False
                return not any(overlaps(box, other, request.node_spacing / 2) for other in siblings)

            position = preferred if nested_fits(preferred) else None
            if position is None:
                step = max(1, int(request.node_spacing))
                y = math.ceil(inner_top)
                while y <= int(inner_bottom - origin.height + 1):
                    x = math.ceil(inner_left)
                    while x <= int(inner_right - origin.width + 1):
                        trial = Box(x, y, origin.width, origin.height)
                        if nested_fits(trial):
                            position = trial
                            break
                        x += step
                    if position:
                        break
                    y += step
            if position is None:
                grown = Box(
                    parent.x,
                    parent.y,
                    max(parent.width, origin.width + request.padding * 2),
                    parent.height + origin.height + request.node_spacing + request.padding,
                )
                if _cannot_grow_parent(request, result, specs, ancestry, node.parent_id, grown):
                    raise ValueError(
                        f"No room for new node '{key}' in '{node.parent_id}'. "
                        "Run Optimize wiring layout."
                    )
                result.boxes[node.parent_id] = grown
                position = Box(
                    grown.x + request.padding,
                    parent.y + parent.height + request.node_spacing,
                    origin.width,
                    origin.height,
                )
        else:
            box = candidate.boxes[key]
            neighbors = [
                result.boxes[other]
                for edge in request.edges
                for own, other in ((edge.source, edge.target), (edge.target, edge.source))
                if own in descendants and other in result.boxes
            ]
            x = sum(b.x for b in neighbors) / len(neighbors) if neighbors else 120
            y = sum(b.y + b.height for b in neighbors) / len(neighbors) if neighbors else 120
            position = Box(x, y + request.node_spacing, box.width, box.height)
            existing_roots = [b for other, b in result.boxes.items() if not specs[other].parent_id]
            while any(overlaps(position, other, request.node_spacing) for other in existing_roots):
                position.y += request.node_spacing + 40
        origin = candidate.boxes[key]
        for child in sorted(descendants, key=lambda item: (len(ancestry[item]), item)):
            box = candidate.boxes[child]
            result.boxes[child] = Box(
                position.x + box.x - origin.x,
                position.y + box.y - origin.y,
                box.width,
                box.height,
            )
            if child in candidate.port_sides:
                parent = result.boxes[specs[child].parent_id]
                placed = result.boxes[child]
                result.port_sides[child] = (
                    "WEST" if placed.x + placed.width / 2 < parent.x + parent.width / 2 else "EAST"
                )


def apply_result(graph, result: LayoutResult) -> None:
    for key, box in result.boxes.items():
        node = graph.nodes[key]
        node.x, node.y, node.width, node.height = box.x, box.y, box.width, box.height
    for edge in graph.edges:
        if edge.id in result.routes:
            edge.metadata["layout_route"] = asdict(result.routes[edge.id])
