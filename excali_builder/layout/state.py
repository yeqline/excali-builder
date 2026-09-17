"""Versioned geometry and route persistence shared by every wiring engine."""

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .engines.base import Box, LayoutResult, Route

STATE_FILE = "wiring-layout.json"


def atomic_json(path: Path, value) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def topology_signature(graph, config) -> str:
    from ..config.loader import ConfigLoader

    payload = {
        "nodes": [
            (
                n.id,
                n.label,
                n.type,
                n.metadata.get("model_number"),
                n.metadata.get("text"),
                n.metadata.get("content"),
                n.metadata.get("font_size")
                or ConfigLoader.get_node_config(config, n.type).font_size,
            )
            for n in sorted(graph.nodes.values(), key=lambda n: n.id)
        ],
        "edges": [
            (e.id, e.source_id, e.target_id, e.edge_type, e.label)
            for e in sorted(graph.edges, key=lambda e: e.id or "")
        ],
        "config": config.model_dump(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_state(folder: Path, signature: str):
    path = folder / STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return None
        result = decode_result(data["result"])
        if data.get("signature") != signature:
            for route in result.routes.values():
                route.label = None
        return result
    except (ValueError, TypeError, KeyError):
        return None


def decode_result(data) -> LayoutResult:
    return LayoutResult(
        {key: Box(**value) for key, value in data["boxes"].items()},
        {
            key: Route(
                [tuple(point) for point in value["points"]],
                Box(**value["label"]) if value.get("label") else None,
            )
            for key, value in data["routes"].items()
        },
        data.get("port_sides", {}),
        data.get("metrics", {}),
    )


def save_state(folder: Path, signature: str, result: LayoutResult) -> None:
    atomic_json(
        folder / STATE_FILE,
        {
            "version": 1,
            "signature": signature,
            "result": asdict(result),
        },
    )


def capture_edited_routes(folder: Path, elements, baseline_elements) -> None:
    """Keep manual bends when the scene's node geometry and bindings are unchanged."""
    path = folder / STATE_FILE
    if not path.exists():
        return
    from ..excalidraw.positions import extract_positions_from_elements

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        return
    result = decode_result(data["result"])
    positions = extract_positions_from_elements(elements, known_node_ids=set(result.boxes))
    if set(positions) != set(result.boxes) or any(
        abs(positions[key][field] - getattr(box, field)) > 0.01
        for key, box in result.boxes.items()
        for field in ("x", "y", "width", "height")
    ):
        return
    baseline = {e["id"]: e for e in baseline_elements}
    for element in elements:
        if element.get("type") != "arrow" or element.get("isDeleted") or element.get("angle", 0):
            continue
        edge_id = element.get("customData", {}).get("edge_id")
        old = baseline.get(element.get("id"))
        if edge_id not in result.routes or not old:
            continue
        if any(
            (element.get(key) or {}).get("elementId") != (old.get(key) or {}).get("elementId")
            for key in ("startBinding", "endBinding")
        ):
            continue
        try:
            points = [
                (element["x"] + point[0], element["y"] + point[1]) for point in element["points"]
            ]
            if len(points) < 2 or not all(math.isfinite(v) for point in points for v in point):
                continue
            if any(
                abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
                for a, b in zip(points, points[1:])
            ):
                continue
            # Moving a bend preserves the existing endpoint anchors.
            original = result.routes[edge_id].points
            if any(
                math.dist(a, b) > 2
                for a, b in ((points[0], original[0]), (points[-1], original[-1]))
            ):
                continue
            if points != original:
                result.routes[edge_id] = Route(points)
        except (KeyError, TypeError, IndexError):
            continue
    save_state(folder, data["signature"], result)
