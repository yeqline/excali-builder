"""Budgeted wire references with explicit endpoint identity and visible geometry."""

import copy
import math
import textwrap
import time
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .engines.base import Box, Connector, route_segments
from .quality import (
    ancestors,
    measure_quality,
    overlaps,
    reference_quality_key,
    segment_hits_box,
    segment_intersection,
)
from .routing import _anchor, _box_boundary_toward, place_labels


@dataclass
class CrossingOptions:
    max_connectors: int
    per_node: int
    passes: int
    protected: set
    costs: dict

    @classmethod
    def read(cls, request):
        options = request.engine_options

        def integer(name, default, low, high):
            value = options.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
            return value

        budget = integer("crossing_max_connectors", 3, 0, 100)
        per_node = integer("crossing_max_connectors_per_node", 2, 1, 100)
        passes = integer("crossing_passes", 6, 0, 50)
        protected = options.get("crossing_protected_edges", [])
        costs = options.get("crossing_edge_costs", {})
        if not isinstance(protected, list) or any(not isinstance(e, str) for e in protected):
            raise ValueError("crossing_protected_edges must be a list of edge IDs")
        if not isinstance(costs, dict) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for key, value in costs.items()
        ):
            raise ValueError("crossing_edge_costs must map edge IDs to positive finite costs")
        unknown = (set(protected) | set(costs)) - {edge.id for edge in request.edges}
        if unknown:
            raise ValueError(f"Unknown wire IDs in crossing options: {sorted(unknown)}")
        return cls(budget, per_node, passes, set(protected), costs)


def edge_conflicts(request, result):
    """Count marginal visible conflicts; rebuild after each replacement or move."""
    ancestry = ancestors(request)
    edges = {edge.id: edge for edge in request.edges}
    segments = {key: route_segments(route) for key, route in result.routes.items()}
    scores = Counter()
    for key, parts in segments.items():
        edge = edges[key]
        allowed = {edge.source, edge.target} | ancestry[edge.source] | ancestry[edge.target]
        scores[key] += 2 * sum(
            segment_hits_box(a, b, box)
            for a, b in parts
            for node_id, box in result.boxes.items()
            if node_id not in allowed
        )
    for first, second in combinations(segments, 2):
        common = {edges[first].source, edges[first].target} & {
            edges[second].source,
            edges[second].target,
        }
        for a, b in segments[first]:
            for c, d in segments[second]:
                crossing, shared = segment_intersection(a, b, c, d)
                weight = crossing + (0 if common else shared / 80)
                scores[first] += weight
                scores[second] += weight
    for node in request.nodes:
        if node.header_height:
            box = result.boxes[node.id]
            header = Box(
                box.x + request.padding, box.y, box.width - request.padding * 2, node.header_height
            )
            for key, parts in segments.items():
                scores[key] += 2 * sum(segment_hits_box(a, b, header) for a, b in parts)
    return scores


def make_connectors(request, result, edge):
    """Place two nonoverlapping reference tags outside the endpoint devices.

    The leaders are straight and attached to the actual ports. Candidate tags
    and leaders must clear device bodies, unrelated ports, and device headings.
    If no pair fits, keep the full wire rather than hide its connection.
    """
    specs = {node.id: node for node in request.nodes}
    ancestry = ancestors(request)
    occupied = [
        connector.label
        for key, route in result.routes.items()
        if key != edge.id
        for connector in route.connectors
    ]
    wires = [
        segment
        for key, route in result.routes.items()
        if key != edge.id
        for segment in route_segments(route)
    ]
    headers = [
        Box(
            result.boxes[node.id].x + request.padding,
            result.boxes[node.id].y,
            result.boxes[node.id].width - request.padding * 2,
            node.header_height,
        )
        for node in request.nodes
        if node.header_height
    ]
    connectors = []
    for local, remote, reference in (
        (edge.source, edge.target, edge.target_reference),
        (edge.target, edge.source, edge.source_reference),
    ):
        paragraphs = [f"↔ {reference or remote}"]
        if edge.label_text:
            paragraphs.extend(edge.label_text.splitlines())
        chars = max(8, int((request.label_max_width - 12) / (edge.font_size * 0.6)))
        lines = [line for text in paragraphs for line in (textwrap.wrap(text, chars) or [""])]
        width = max(60, max(map(len, lines)) * edge.font_size * 0.6 + 12)
        height = len(lines) * edge.font_size * 1.25 + 12
        start, exit_point = _anchor(local, remote, specs, result, ancestry, request.wire_spacing)
        own = result.boxes[local]
        center = (own.x + own.width / 2, own.y + own.height / 2)
        dx, dy = exit_point[0] - center[0], exit_point[1] - center[1]
        horizontal = abs(dx) >= abs(dy)
        sign = 1 if (dx if horizontal else dy) >= 0 else -1
        allowed = {local} | ancestry[local]
        obstacles = [box for key, box in result.boxes.items() if key not in allowed] + headers
        candidates = []
        for distance in (
            request.wire_spacing,
            request.wire_spacing + 40,
            request.wire_spacing + 100,
        ):
            for offset in (0, -1, 1, -2, 2, -3, 3):
                if horizontal:
                    label = Box(
                        exit_point[0] + sign * distance - (width if sign < 0 else 0),
                        exit_point[1] - height / 2 + offset * (height + 12),
                        width,
                        height,
                    )
                else:
                    label = Box(
                        exit_point[0] - width / 2 + offset * (width + 12),
                        exit_point[1] + sign * distance - (height if sign < 0 else 0),
                        width,
                        height,
                    )
                if any(overlaps(label, box, 6) for box in [*result.boxes.values(), *occupied]):
                    continue
                # Anchor on the port bank, so a reference never exits through
                # the back of a port just to shorten its leader.
                end = _box_boundary_toward(label, start, -1)
                if any(segment_hits_box(start, end, box) for box in obstacles + occupied):
                    continue
                penalty = sum(segment_hits_box(a, b, label) for a, b in wires)
                penalty += sum(segment_intersection(start, end, a, b)[0] for a, b in wires)
                candidates.append((penalty, math.dist(start, end), label, end))
        if not candidates:
            return []
        _, _, label, end = min(candidates, key=lambda item: item[:2])
        connectors.append(Connector([start, end], label, "\n".join(lines), remote))
        occupied.append(label)
        wires.append((start, end))
    return connectors


def refresh_connectors(request, result, edge_ids):
    for edge in sorted(request.edges, key=lambda item: item.id):
        if edge.id in edge_ids:
            result.routes[edge.id].connectors = make_connectors(request, result, edge)


def select_connectors(request, result, deadline=None):
    """Greedy conflict coverage, accepting only improvements in rendered quality."""
    options = CrossingOptions.read(request)
    if deadline is not None and time.monotonic() >= deadline:
        return measure_quality(request, result)
    for route in result.routes.values():
        route.connectors = []
    place_labels(request, result)
    metrics = measure_quality(request, result)
    before = dict(metrics)
    usage = Counter()
    for _ in range(options.max_connectors):
        if deadline is not None and time.monotonic() >= deadline:
            break
        conflicts = edge_conflicts(request, result)
        choices = sorted(
            (
                edge
                for edge in request.edges
                if conflicts[edge.id] > 0
                and edge.id not in options.protected
                and not result.routes[edge.id].connectors
                and edge.source != edge.target
                and max(usage[edge.source], usage[edge.target]) < options.per_node
            ),
            key=lambda edge: (-conflicts[edge.id] / options.costs.get(edge.id, 1), edge.id),
        )
        winner, best_routes, best_metrics = None, None, metrics
        # Bound annotation placement work on dense diagrams, independently of
        # the replacement budget. Recompute marginal conflicts next iteration.
        for edge in choices[:16]:
            if deadline is not None and time.monotonic() >= deadline:
                break
            connectors = make_connectors(request, result, edge)
            if not connectors:
                continue
            original = copy.deepcopy(result.routes)
            result.routes[edge.id].connectors = connectors
            place_labels(request, result)
            candidate = measure_quality(request, result)
            if reference_quality_key(candidate) < reference_quality_key(best_metrics):
                winner, best_routes, best_metrics = edge, copy.deepcopy(result.routes), candidate
            result.routes = original
        if winner is None:
            break
        result.routes, metrics = best_routes, best_metrics
        usage.update((winner.source, winner.target))
    result.metrics.update(metrics)
    result.metrics["crossings_before_references"] = before["crossings"]
    result.metrics["obstructions_before_references"] = before["obstructions"]
    return metrics
