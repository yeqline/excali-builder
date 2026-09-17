"""Shared part geometry and collective port-arrangement search for wiring engines."""

import copy
import time
from collections import Counter
from itertools import permutations
from typing import Dict, List, Optional, Tuple

from .engines.base import Box, LayoutRequest, LayoutResult, PartTemplate
from .quality import EPSILON, measure_quality, validate_result
from .routing import route_fixed

Arrangement = Dict[str, Tuple[str, ...]]
SIDES = ("WEST", "EAST")


def _valid_arrangement(template: PartTemplate, arrangement: Arrangement) -> bool:
    roles = arrangement["WEST"] + arrangement["EAST"]
    if len(roles) != len(template.roles) or set(roles) != set(template.roles):
        return False
    if any(role not in arrangement[side] for role, side in template.locked_sides.items()):
        return False
    for order in template.locked_orders:
        for bank in arrangement.values():
            requested = [role for role in order if role in bank]
            if requested != sorted(requested, key=bank.index):
                return False
    return True


def _respect_orders(template: PartTemplate, arrangement: Arrangement) -> Optional[Arrangement]:
    ordered = {}
    for side, bank in arrangement.items():
        predecessors = {role: set() for role in bank}
        for order in template.locked_orders:
            restricted = [role for role in order if role in bank]
            for before, after in zip(restricted, restricted[1:]):
                predecessors[after].add(before)
        sequence = []
        while predecessors:
            role = next(
                (role for role in bank if role in predecessors and not predecessors[role]), None
            )
            if role is None:
                return None
            sequence.append(role)
            del predecessors[role]
            for remaining in predecessors.values():
                remaining.discard(role)
        ordered[side] = tuple(sequence)
    return ordered if _valid_arrangement(template, ordered) else None


def set_arrangement(
    request: LayoutRequest,
    name: str,
    arrangement: Arrangement,
    result: Optional[LayoutResult] = None,
) -> None:
    """Set each instance's role to the same bank, slot, and dimensions."""
    template = request.part_templates[name]
    specs = {node.id: node for node in request.nodes}
    for parent_id, ports in template.instances.items():
        parent = specs[parent_id]
        for side, roles in arrangement.items():
            y = parent.header_height + request.padding
            for index, role in enumerate(roles):
                port = specs[ports[role]]
                x = (
                    request.padding
                    if side == "WEST"
                    else (parent.width - request.padding - port.width)
                )
                port.side, port.order, port.fixed_position = side, index, (x, y)
                y += port.height + request.port_spacing
    if result is not None:
        apply_part_geometry(request, result)


def _add_order(template: PartTemplate, order: List[str]) -> None:
    template.locked_orders.append(order)
    # Listed ports precede unlisted ports without freezing the unlisted order.
    for role in order:
        template.locked_orders.extend(
            [role, other] for other in template.roles if other not in order
        )


def prepare_parts(request: LayoutRequest, settings, graph) -> None:
    """Discover models and matching port titles, then reserve shared geometry."""
    specs = {node.id: node for node in request.nodes}
    children = {}
    identities = {}
    for source in graph.nodes.values():
        value = source.metadata.get("model_number")
        if value is not None and value != "":
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"'{source.id}' model_number must be a non-empty string")
            identities[source.id] = value.strip()
        node = specs[source.id]
        if node.parent_id:
            children.setdefault(node.parent_id, []).append(node)
    for parent_id, name in identities.items():
        ports = children.get(parent_id, [])
        if not ports:
            continue  # Identity is also useful on ordinary parts without ports.
        if any(not port.is_port for port in ports):
            raise ValueError(f"Part '{parent_id}' must be a container containing only ports")
        mapping = {" ".join(graph.nodes[port.id].label.split()): port.id for port in ports}
        if "" in mapping:
            raise ValueError(f"Part '{parent_id}' requires a non-empty title on every port")
        if len(mapping) != len(ports):
            raise ValueError(
                f"Duplicate port title in part '{parent_id}'; name each connector uniquely"
            )
        template = request.part_templates.setdefault(name, PartTemplate(list(mapping), {}))
        if set(mapping) != set(template.roles):
            raise ValueError(
                f"Instances of model_number '{name}' must have the same port titles; "
                f"'{parent_id}' differs. Correct the CSV or use distinct model numbers for variants"
            )
        template.instances[parent_id] = mapping
        inverse = {port_id: role for role, port_id in mapping.items()}
        if parent_id in settings.port_order:
            _add_order(template, [inverse[p] for p in settings.port_order[parent_id]])
        for role, port_id in mapping.items():
            side = settings.port_sides.get(port_id)
            if side:
                if role in template.locked_sides and template.locked_sides[role] != side:
                    raise ValueError(f"Conflicting side for '{name}' role '{role}'")
                template.locked_sides[role] = side
    for name, config in settings.part_templates.items():
        if name not in request.part_templates:
            raise ValueError(f"Part constraints reference unknown source model_number '{name}'")
        template = request.part_templates[name]
        roles = template.roles
        if set(config.port_sides) - set(roles):
            raise ValueError(f"Unknown port role in part template '{name}' port_sides")
        if len(config.port_order) != len(set(config.port_order)) or (
            set(config.port_order) - set(roles)
        ):
            raise ValueError(f"Invalid port_order in part template '{name}'")
        template.optimize = config.optimize
        if config.port_order:
            _add_order(template, list(config.port_order))
        for role, side in config.port_sides.items():
            if role in template.locked_sides and template.locked_sides[role] != side:
                raise ValueError(f"Conflicting side for '{name}' role '{role}'")
            template.locked_sides[role] = side

    for name, template in request.part_templates.items():
        if not template.instances:
            continue
        parents = [specs[parent_id] for parent_id in template.instances]
        header = max(parent.header_height for parent in parents)
        dimensions = {}
        for role in template.roles:
            ports = [specs[mapping[role]] for mapping in template.instances.values()]
            fixed = {(port.width, port.height) for port in ports if port.size_locked}
            if len(fixed) > 1:
                raise ValueError(f"Conflicting fixed sizes for '{name}' role '{role}'")
            dimensions[role] = (
                next(iter(fixed))
                if fixed
                else (max(port.width for port in ports), max(port.height for port in ports))
            )
            for port in ports:
                port.width, port.height = dimensions[role]
                port.size_locked = True
                port.side_locked = role in template.locked_sides
                port.part_template, port.port_role = name, role
        # Reserve both banks and the largest possible single bank, so changing
        # a shared arrangement cannot resize devices or overlap their neighbors.
        minimum_width = 2 * max(size[0] for size in dimensions.values()) + request.padding * 3
        minimum_height = (
            header
            + request.padding * 2
            + sum(size[1] for size in dimensions.values())
            + request.port_spacing * (len(dimensions) - 1)
        )
        fixed = {(parent.width, parent.height) for parent in parents if parent.size_locked}
        if len(fixed) > 1:
            raise ValueError(f"Conflicting fixed sizes for part template '{name}'")
        width, height = (
            next(iter(fixed))
            if fixed
            else (
                max(minimum_width, max(parent.width for parent in parents)),
                max(minimum_height, max(parent.height for parent in parents)),
            )
        )
        if width < minimum_width or height < minimum_height:
            raise ValueError(
                f"Fixed size for '{name}' cannot contain its template ports and heading"
            )
        for parent in parents:
            parent.width, parent.height, parent.header_height = width, height, header
            parent.size_locked, parent.part_template = True, name
        sides = {}
        for role in template.roles:
            votes = Counter(specs[mapping[role]].side for mapping in template.instances.values())
            sides[role] = template.locked_sides.get(role) or max(
                SIDES, key=lambda side: (votes[side], side == "WEST")
            )
        initial = {
            side: tuple(role for role in template.roles if sides[role] == side) for side in SIDES
        }
        if not _valid_arrangement(template, initial):
            # Start with an arrangement respecting explicit partial orders.
            initial = _respect_orders(template, initial) or next(
                (
                    ordered
                    for item in _proposals(template, initial)
                    if (ordered := _respect_orders(template, item)) is not None
                ),
                None,
            )
            if initial is None:
                raise ValueError(f"Conflicting port orders for part template '{name}'")
        set_arrangement(request, name, initial)


def apply_part_geometry(
    request: LayoutRequest, result: LayoutResult, resize_containers: bool = False
) -> set:
    """Restore shared internals while keeping each device's placement."""
    changed = set()
    if resize_containers:
        for node in request.nodes:
            if node.part_template and not node.is_port and node.id in result.boxes:
                box = result.boxes[node.id]
                if (box.width, box.height) != (node.width, node.height):
                    result.boxes[node.id] = Box(box.x, box.y, node.width, node.height)
                    changed.add(node.id)
    for node in request.nodes:
        if node.fixed_position is None or node.id not in result.boxes:
            continue
        parent = result.boxes.get(node.parent_id)
        if parent is None:
            continue
        x, y = node.fixed_position
        box = Box(parent.x + x, parent.y + y, node.width, node.height)
        old = result.boxes[node.id]
        if any(
            abs(getattr(box, field) - getattr(old, field)) > EPSILON
            for field in ("x", "y", "width", "height")
        ):
            changed.add(node.id)
        result.boxes[node.id] = box
        result.port_sides[node.id] = node.side
    return changed


def describe_parts(request: LayoutRequest, result: LayoutResult) -> Dict[str, Dict[str, List[str]]]:
    arrangements = {}
    for name, template in request.part_templates.items():
        if not template.instances:
            continue
        ports = next(iter(template.instances.values()))
        if not set(ports.values()) <= set(result.boxes):
            continue
        arrangements[name] = {
            side: sorted(
                (role for role, port_id in ports.items() if result.port_sides.get(port_id) == side),
                key=lambda role: result.boxes[ports[role]].y,
            )
            for side in SIDES
        }
    return arrangements


def restore_parts(request: LayoutRequest, metrics: dict) -> set:
    """Seed a rebuild or placement candidate with the persisted shared winner."""
    saved = metrics.get("part_templates", {})
    restored = set()
    if not isinstance(saved, dict):
        return restored
    for name, template in request.part_templates.items():
        if not template.instances or not template.optimize:
            continue
        banks = saved.get(name)
        if not isinstance(banks, dict) or any(
            not isinstance(banks.get(side), list) for side in SIDES
        ):
            continue
        arrangement = {side: tuple(banks[side]) for side in SIDES}
        if any(not isinstance(role, str) for bank in arrangement.values() for role in bank):
            continue
        if _valid_arrangement(template, arrangement):
            set_arrangement(request, name, arrangement)
            restored.add(name)
    return restored


def _proposals(template: PartTemplate, current: Arrangement):
    if len(template.roles) <= 3:
        for order in permutations(template.roles):
            for split in range(len(order) + 1):
                yield {"WEST": order[:split], "EAST": order[split:]}
        return
    yield {"WEST": current["EAST"], "EAST": current["WEST"]}
    for side in SIDES:
        yield {bank: tuple(template.roles) if bank == side else () for bank in SIDES}
    for side in SIDES:
        for role in current[side]:
            removed = {
                bank: tuple(item for item in current[bank] if item != role) for bank in SIDES
            }
            for target in SIDES:
                for slot in range(len(removed[target]) + 1):
                    candidate = dict(removed)
                    bank = list(candidate[target])
                    bank.insert(slot, role)
                    candidate[target] = tuple(bank)
                    yield candidate


def optimize_parts(request: LayoutRequest, result: LayoutResult, key, deadline: float) -> int:
    """Search shared arrangements against the full drawing, never per instance.

    Small parts enumerate every bank/order arrangement. Larger parts use
    collective port sifting and bank switches, with coordinate descent across
    templates. Device placements stay fixed during this pass; subsequent outer
    placement candidates start from the best shared arrangement found so far.
    """
    if not any(
        template.optimize and template.instances for template in request.part_templates.values()
    ):
        return 0
    trials = 0
    metrics = measure_quality(request, result)
    for _ in range(3):
        improved = False
        for name, template in sorted(request.part_templates.items()):
            if not template.instances or not template.optimize:
                continue
            banks = describe_parts(request, result)[name]
            current = {side: tuple(banks[side]) for side in SIDES}
            winner, best = current, copy.deepcopy(result)
            seen = {(current["WEST"], current["EAST"])}
            for arrangement in _proposals(template, current):
                signature = (arrangement["WEST"], arrangement["EAST"])
                if signature in seen or not _valid_arrangement(template, arrangement):
                    continue
                seen.add(signature)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                set_arrangement(request, name, arrangement, result)
                probe = copy.copy(request)
                probe.timeout = remaining
                trials += 1
                try:
                    route_fixed(probe, result)
                    validate_result(request, result)
                    candidate = measure_quality(request, result)
                except (ValueError, RuntimeError):
                    continue
                if key(candidate) < key(metrics):
                    metrics, winner, best = candidate, arrangement, copy.deepcopy(result)
            set_arrangement(request, name, winner)
            result.boxes, result.routes, result.port_sides = (
                best.boxes,
                best.routes,
                best.port_sides,
            )
            improved = improved or winner != current
            if time.monotonic() >= deadline:
                return trials
        if not improved:
            break
    return trials
