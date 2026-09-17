"""Two-dimensional device movement and budgeted references for straight wiring."""

import copy
import random
import time
from collections import Counter, defaultdict

from ..parts import apply_part_geometry
from ..quality import ancestors, measure_quality, overlaps, reference_quality_key, validate_result
from ..references import CrossingOptions, edge_conflicts, select_connectors
from ..routing import route_straight
from .base import Box, LayoutEngine
from .elk import ElkEngine


class CrossingEngine(LayoutEngine):
    """Preserve compound port geometry while searching beyond layered orders."""

    def layout(self, request):
        options = CrossingOptions.read(request)
        if request.edge_routing != "straight":
            raise ValueError("The crossing engine requires wiring.edge_routing: 'straight'")
        ancestors(request)
        deadline = time.monotonic() + request.timeout
        seed = copy.deepcopy(request)
        seed.engine_options = {
            key: value
            for key, value in seed.engine_options.items()
            if not key.startswith("crossing_") and key != "hybrid_candidates"
        }
        # A compound seed preserves terminal banks, dimensions and nested
        # devices that a point-only force layout cannot represent.
        from ..wiring import _breadth_orientation

        _breadth_orientation(seed, {})
        seed.timeout = max(0.001, request.timeout * 0.5)
        result = ElkEngine().layout(seed)
        apply_part_geometry(request, result)
        route_straight(request, result)
        validate_result(request, result)
        initial = measure_quality(request, result)
        search_start = time.monotonic()
        remaining = max(0, deadline - search_start)
        moves = self.refine(request, result, search_start + remaining * 0.55, options.passes)
        select_connectors(request, result, search_start + remaining * 0.8)
        best = copy.deepcopy(result)
        # Once costly spans are referenced, their endpoints can move without
        # recreating those spans. Reconsider the reference set after moving.
        if options.passes and any(route.connectors for route in result.routes.values()):
            moves += self.refine(request, result, deadline, max(1, options.passes // 2))
            if time.monotonic() < deadline:
                select_connectors(request, result, deadline)
            if reference_quality_key(measure_quality(request, best)) < reference_quality_key(
                measure_quality(request, result)
            ):
                result = best
        validate_result(request, result)
        result.metrics.update(measure_quality(request, result))
        result.metrics.update({"crossing_moves": moves, "seed_crossings": initial["crossings"]})
        return result

    @staticmethod
    def refine(request, result, deadline, passes=6):
        """Coordinate descent and whole-device exchanges with shrinking steps.

        Moves translate every descendant together; terminal order, nested
        containment, fixed sizes, and shared part offsets remain invariant.
        Search is deterministic for a seed, bounded by passes and wall time.
        """
        specs = {node.id: node for node in request.nodes}
        roots = sorted(node.id for node in request.nodes if not node.parent_id)
        if len(roots) < 2:
            return 0
        owner, members = {}, defaultdict(list)
        for node in request.nodes:
            key = node.id
            while specs[key].parent_id:
                key = specs[key].parent_id
            owner[node.id] = key
            members[key].append(node.id)
        neighbors = defaultdict(set)
        incident = defaultdict(set)
        for edge in request.edges:
            a, b = owner[edge.source], owner[edge.target]
            incident[a].add(edge.id)
            incident[b].add(edge.id)
            if a != b:
                neighbors[a].add(b)
                neighbors[b].add(a)
        rng = random.Random(request.seed)
        metrics = measure_quality(request, result)
        moves = 0
        scale = max(
            request.node_spacing,
            sum(max(result.boxes[key].width, result.boxes[key].height) for key in roots)
            / len(roots)
            / 2,
        )

        def try_move(translations):
            nonlocal metrics, moves
            if time.monotonic() >= deadline:
                return
            proposed = {}
            for key, (dx, dy) in translations.items():
                for child in members[key]:
                    box = result.boxes[child]
                    proposed[child] = Box(box.x + dx, box.y + dy, box.width, box.height)
            for key in translations:
                for other in roots:
                    if key != other and overlaps(
                        proposed[key],
                        proposed.get(other, result.boxes[other]),
                        request.node_spacing / 2,
                    ):
                        return
            old_boxes, old_routes = dict(result.boxes), copy.deepcopy(result.routes)
            result.boxes.update(proposed)
            affected = set().union(*(incident[key] for key in translations))
            route_straight(request, result, affected)
            candidate = measure_quality(request, result)
            if reference_quality_key(candidate) < reference_quality_key(metrics):
                try:
                    validate_result(request, result)
                except ValueError:
                    pass
                else:
                    metrics = candidate
                    moves += 1
                    return
            result.boxes, result.routes = old_boxes, old_routes

        for index in range(passes):
            if time.monotonic() >= deadline:
                break
            conflicts = edge_conflicts(request, result)
            priority = Counter()
            for edge in request.edges:
                priority[owner[edge.source]] += conflicts[edge.id]
                priority[owner[edge.target]] += conflicts[edge.id]
            active = sorted(roots, key=lambda key: (-priority[key], key))
            if not any(priority.values()):
                break
            step = scale * 0.65 ** (index // 2)
            # Bound work per pass on large diagrams, spending it on the roots
            # currently responsible for the most conflicts.
            for key in active[:32]:
                if time.monotonic() >= deadline:
                    return moves
                offsets = [
                    (dx * step, dy * step)
                    for dx, dy in (
                        (1, 0),
                        (-1, 0),
                        (0, 1),
                        (0, -1),
                        (1, 1),
                        (-1, 1),
                        (1, -1),
                        (-1, -1),
                    )
                ]
                rng.shuffle(offsets)
                origin = copy.copy(result.boxes[key])
                targets = [(origin.x + dx, origin.y + dy) for dx, dy in offsets]
                for other in sorted(neighbors[key])[:4]:
                    box = result.boxes[other]
                    targets.extend(
                        [
                            (box.x - origin.width - request.node_spacing, box.y),
                            (box.x + box.width + request.node_spacing, box.y),
                            (box.x, box.y - origin.height - request.node_spacing),
                            (box.x, box.y + box.height + request.node_spacing),
                        ]
                    )
                for x, y in targets:
                    if time.monotonic() >= deadline:
                        return moves
                    box = result.boxes[key]
                    try_move({key: (x - box.x, y - box.y)})
                for other in (candidate for candidate in active[:6] if candidate != key):
                    a, b = result.boxes[key], result.boxes[other]
                    try_move({key: (b.x - a.x, b.y - a.y), other: (a.x - b.x, a.y - b.y)})
        return moves
