"""Helpers for extracting durable node layout from Excalidraw elements."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set


SHAPE_ELEMENT_TYPES = {"rectangle", "ellipse", "diamond", "image"}


def extract_positions_from_elements(
    elements: Iterable[Dict[str, Any]],
    known_node_ids: Optional[Set[str]] = None,
    baseline_elements: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Extract layout data for generated nodes only.

    ``baseline_elements`` is used by the live viewer path to avoid persisting text
    edits as wrapped text. If the bound text's original text no longer matches the
    generated output, only layout-adjacent text fields are kept.
    """
    positions: Dict[str, Dict[str, Any]] = {}
    element_list = list(elements)
    baseline_text = _baseline_text_by_node_id(baseline_elements or [])

    for element in element_list:
        if element.get("isDeleted"):
            continue

        node_id = _get_node_id(element)
        if not _is_known_node(node_id, known_node_ids):
            continue
        if element.get("type") not in SHAPE_ELEMENT_TYPES:
            continue

        x = _number(element.get("x"))
        y = _number(element.get("y"))
        width = _positive_number(element.get("width"))
        height = _positive_number(element.get("height"))
        if x is None or y is None or width is None or height is None:
            continue

        positions[node_id] = {
            "x": float(x),
            "y": float(y),
            "width": float(width),
            "height": float(height),
        }

    for element in element_list:
        if element.get("isDeleted"):
            continue

        node_id = _get_node_id(element)
        if node_id not in positions:
            continue
        if element.get("type") != "text":
            continue

        text_align = element.get("textAlign")
        vertical_align = element.get("verticalAlign")
        font_size = _positive_number(element.get("fontSize"))
        text_x = _number(element.get("x"))
        text_y = _number(element.get("y"))
        text_width = _positive_number(element.get("width"))
        text_height = _positive_number(element.get("height"))

        if text_align:
            positions[node_id]["textAlign"] = text_align
        if vertical_align:
            positions[node_id]["verticalAlign"] = vertical_align
        if font_size is not None:
            positions[node_id]["fontSize"] = font_size
        if text_x is not None:
            positions[node_id]["text_x"] = float(text_x)
        if text_y is not None:
            positions[node_id]["text_y"] = float(text_y)
        if text_width is not None:
            positions[node_id]["text_width"] = float(text_width)
        if text_height is not None:
            positions[node_id]["text_height"] = float(text_height)

        if _can_persist_wrapped_text(element, baseline_text.get(node_id)):
            if element.get("text") is not None:
                positions[node_id]["wrapped_text"] = element["text"]
            if element.get("originalText") is not None:
                positions[node_id]["wrapped_original_text"] = element["originalText"]

    return positions


def load_positions(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load a positions file, returning an empty mapping when it is absent."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def merge_positions(path: Path, positions: Dict[str, Dict[str, Any]]) -> None:
    """Merge node layout into positions.json with an atomic replace."""
    if not positions:
        return

    existing_positions = load_positions(path)
    existing_positions.update(positions)
    _atomic_json_dump(path, existing_positions)


def _atomic_json_dump(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON to ``path`` without leaving a partial file on interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _baseline_text_by_node_id(
    elements: Iterable[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    baseline_text: Dict[str, Dict[str, Any]] = {}
    for element in elements:
        if element.get("type") != "text":
            continue
        node_id = _get_node_id(element)
        if node_id:
            baseline_text[node_id] = element
    return baseline_text


def _can_persist_wrapped_text(
    element: Dict[str, Any],
    baseline: Optional[Dict[str, Any]],
) -> bool:
    if baseline is None:
        return True

    baseline_original = baseline.get("originalText")
    if baseline_original is None:
        baseline_original = baseline.get("text")

    current_original = element.get("originalText")
    if current_original is None:
        current_original = element.get("text")

    return current_original == baseline_original


def _get_node_id(element: Dict[str, Any]) -> Optional[str]:
    custom_data = element.get("customData")
    if not isinstance(custom_data, dict):
        return None
    node_id = custom_data.get("node_id")
    return node_id if isinstance(node_id, str) and node_id else None


def _is_known_node(node_id: Optional[str], known_node_ids: Optional[Set[str]]) -> bool:
    if not node_id:
        return False
    if known_node_ids is None:
        return True
    return node_id in known_node_ids


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _positive_number(value: Any) -> Optional[float]:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return number
