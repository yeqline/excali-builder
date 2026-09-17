"""Crossing-aware wiring placement built on an ELK seed layout.

The engine keeps ELK's compound and port placement, then searches the discrete
choices that matter most for straight-line readability: port sides and the
vertical order of top-level devices.  The refinement scores the final straight
segments, rather than ELK's intermediate polyline routes.
"""

import copy
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..parts import apply_part_geometry
from ..quality import (
    ancestors,
    crossing_quality_key,
    overlaps,
    segment_hits_box,
    segment_intersection,
    validate_result,
)
from ..routing import _box_boundary_toward, place_labels, route_straight, simplify
from .base import Box, LayoutEngine, LayoutRequest, LayoutResult
from .elk import ElkEngine


class HybridEngine(LayoutEngine):
    """Use ELK for a seed, then reduce crossings with deterministic sifting."""

    def layout(self, request: LayoutRequest) -> LayoutResult:
        deadline = time.monotonic() + request.timeout
        candidates = self._candidate_count(request)
        elk = ElkEngine()
        fixed_sides = {
            node.id: node.side
            for node in request.nodes
            if node.is_port and node.side_locked and node.side
        }
        rng = random.Random(request.seed)
        best: Optional[LayoutResult] = None
        best_metrics = None
        failures: List[str] = []
        attempted = 0

        for index in range(candidates):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            candidate = copy.deepcopy(request)
            candidate.seed = request.seed + index
            candidate.timeout = remaining
            # Keep hybrid-only controls out of ELK's option namespace.
            candidate.engine_options = {
                key: value
                for key, value in request.engine_options.items()
                if key != "hybrid_candidates"
            }
            reversed_edges = set()
            try:
                # Start every hybrid run with the broad orientation pass. The
                # outer wiring pipeline may provide additional seeds, but a
                # direct call to this engine should still get a useful seed.
                from ..wiring import _breadth_orientation

                reversed_edges = _breadth_orientation(candidate, fixed_sides)
                if best is not None and index % 4 == 2:
                    from ..wiring import _face_neighbors

                    _face_neighbors(candidate, best, fixed_sides)
                if index >= 3:
                    self._randomize_port_sides(candidate, rng, index)

                result = elk.layout(candidate)
                moved_ports = apply_part_geometry(request, result)
                if request.edge_routing == "straight":
                    self._sift(result, request, deadline)
                    route_straight(request, result)
                else:
                    for edge_id in reversed_edges:
                        result.routes[edge_id].points.reverse()
                    for route in result.routes.values():
                        route.points = simplify(route.points)
                    if moved_ports:
                        from ..routing import route_fixed

                        route_fixed(request, result)
                    place_labels(request, result)
                validate_result(request, result)
                from ..quality import measure_quality

                metrics = measure_quality(request, result)
                if best is None or crossing_quality_key(metrics) < crossing_quality_key(
                    best_metrics
                ):
                    best = result
                    best_metrics = metrics
                attempted += 1
            except (RuntimeError, ValueError) as exc:
                failures.append(str(exc))

        if best is None:
            raise ValueError(
                "No valid hybrid wiring layout: "
                f"{failures[0] if failures else 'time budget exhausted'}"
            )
        best.metrics = dict(best_metrics or {})
        best.metrics["hybrid_candidates"] = attempted
        if failures:
            best.metrics["hybrid_rejected_candidates"] = len(failures)
        return best

    @staticmethod
    def _candidate_count(request: LayoutRequest) -> int:
        value = request.engine_options.get("hybrid_candidates", 1)
        try:
            return max(1, min(8, int(value)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _randomize_port_sides(request: LayoutRequest, rng: random.Random, index: int) -> None:
        """Try a reproducible subset of unconstrained west/east assignments."""
        probability = 0.18 + min(0.22, index * 0.02)
        for node in request.nodes:
            if (
                not node.is_port
                or node.side_locked
                or node.fixed_position is not None
                or node.order is not None
            ):
                continue
            if rng.random() < probability:
                node.side = "WEST" if node.side == "EAST" else "EAST"

    @staticmethod
    def _sift(
        result: LayoutResult, request: LayoutRequest, deadline: Optional[float] = None
    ) -> None:
        """Sift adjacent top-level devices when the rendered straight score improves."""
        specs = {node.id: node for node in request.nodes}
        roots = [node.id for node in request.nodes if not node.parent_id]
        if len(roots) < 2:
            return

        def root(node_id: str) -> str:
            while specs[node_id].parent_id:
                node_id = specs[node_id].parent_id
            return node_id

        members = {
            node_id: [node.id for node in request.nodes if root(node.id) == node_id]
            for node_id in roots
        }
        layers = HybridEngine._layers(roots, result.boxes, request.layer_spacing)
        ancestry = ancestors(request)
        edges = request.edges

        def translate(node_id: str, delta_y: float) -> None:
            for member in members[node_id]:
                box = result.boxes[member]
                result.boxes[member] = Box(box.x, box.y + delta_y, box.width, box.height)

        def valid_positions() -> bool:
            for index, first in enumerate(roots):
                for second in roots[index + 1 :]:
                    if overlaps(
                        result.boxes[first], result.boxes[second], request.node_spacing / 2
                    ):
                        return False
            return True

        def score() -> Tuple[float, float, float]:
            """Score the same endpoint segments that the final router emits.

            The first version of this pass scored only root-to-root segments.
            That was cheap, but it could accept a swap that improved the proxy
            while making a port-level crossing worse.  Keep the refinement's
            objective aligned with ``measure_quality``: every edge, every
            endpoint, every non-ancestor obstacle, and every proper crossing.
            """
            segments = []
            obstructions = 0.0
            for edge in edges:
                source = result.boxes[edge.source]
                target = result.boxes[edge.target]
                source_center = (source.x + source.width / 2, source.y + source.height / 2)
                target_center = (target.x + target.width / 2, target.y + target.height / 2)
                start = _box_boundary_toward(source, target_center, 1)
                end = _box_boundary_toward(target, source_center, -1)
                segments.append((edge, start, end))
                allowed = {edge.source, edge.target} | ancestry[edge.source] | ancestry[edge.target]
                obstructions += sum(
                    segment_hits_box(start, end, box)
                    for node_id, box in result.boxes.items()
                    if node_id not in allowed
                )
            # Headers are obstacles even to wires connected to ports in the
            # same device, matching the final quality report.
            for node in request.nodes:
                if not node.header_height:
                    continue
                box = result.boxes[node.id]
                header = Box(
                    box.x + request.padding,
                    box.y,
                    box.width - request.padding * 2,
                    node.header_height,
                )
                obstructions += sum(
                    segment_hits_box(start, end, header) for _, start, end in segments
                )
            crossings = 0.0
            for index, (edge, start, end) in enumerate(segments):
                for other_edge, other_start, other_end in segments[index + 1 :]:
                    if {edge.source, edge.target} & {other_edge.source, other_edge.target}:
                        continue
                    crossing, _ = segment_intersection(start, end, other_start, other_end)
                    crossings += crossing
            # Obstructions are more damaging than crossings, but a crossing
            # reduction is still worthwhile when it does not hit many devices.
            return obstructions * 20 + crossings * 10, obstructions, crossings

        for _ in range(4):
            improved = False
            for layer in layers:
                if deadline is not None and time.monotonic() >= deadline:
                    return
                order = sorted(layer, key=lambda node_id: result.boxes[node_id].y)
                for first, second in zip(order, order[1:]):
                    if deadline is not None and time.monotonic() >= deadline:
                        return
                    before = score()[0]
                    first_y, second_y = result.boxes[first].y, result.boxes[second].y
                    translate(first, second_y - first_y)
                    translate(second, first_y - second_y)
                    if not valid_positions() or score()[0] >= before - 1e-6:
                        translate(first, first_y - second_y)
                        translate(second, second_y - first_y)
                    else:
                        improved = True
            if not improved:
                break

    @staticmethod
    def _layers(
        roots: Sequence[str], boxes: Dict[str, Box], layer_spacing: float
    ) -> List[List[str]]:
        tolerance = max(50.0, min(250.0, layer_spacing * 0.75))
        layers: List[List[str]] = []
        layer_x: List[float] = []
        for node_id in sorted(roots, key=lambda key: boxes[key].x):
            x = boxes[node_id].x
            if not layers or x - layer_x[-1] > tolerance:
                layers.append([])
                layer_x.append(x)
            layers[-1].append(node_id)
            layer_x[-1] = (layer_x[-1] + x) / 2
        return layers
