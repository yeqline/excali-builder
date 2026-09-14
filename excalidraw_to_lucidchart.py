#!/usr/bin/env python3
"""Convert Excalidraw JSON to a Lucidchart-compatible CSV or Draw.io file.

Usage:
    python excalidraw_to_lucidchart.py input.excalidraw output.csv
    python excalidraw_to_lucidchart.py input.excalidraw output.drawio
"""

import argparse
import base64
import csv
import html
import json
import math
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


CSV_COLUMNS = [
    "Id",
    "Name",
    "Shape Library",
    "Page ID",
    "Contained By",
    "Text Area 1",
    "Line Source",
    "Line Destination",
    "Source Arrow",
    "Destination Arrow",
    "x",
    "y",
]

PAGE_ID = "lucid-page-1"
SHAPE_LIBRARY = "Flowchart Shapes"
SHAPE_TYPES = {
    "rectangle": "Process",
    "diamond": "Decision",
    "ellipse": "Terminator",
}
CONNECTOR_TYPES = {"arrow", "line"}
DRAWIO_OUTPUT_SUFFIXES = {".drawio", ".xml"}
MIN_NODE_WIDTH = 120.0
MIN_NODE_HEIGHT = 60.0
MAX_CALCULATED_WIDTH = 600.0
MAX_TEXT_LINE_CHARACTERS = 64
HORIZONTAL_TEXT_PADDING = 32.0
VERTICAL_TEXT_PADDING = 28.0

Element = Dict[str, Any]
ElementRecord = Tuple[Element, str, Optional[str]]


def _element_type(element: Mapping[str, Any]) -> str:
    value = element.get("type", "")
    return value.lower() if isinstance(value, str) else ""


def _text_value(element: Mapping[str, Any]) -> str:
    original_text = element.get("originalText")
    if isinstance(original_text, str):
        return original_text
    value = element.get("text", "")
    return value if isinstance(value, str) else ""


def _layout_text_value(element: Mapping[str, Any]) -> str:
    """Return Excalidraw's wrapped text when it is available."""
    value = element.get("text")
    return value if isinstance(value, str) else _text_value(element)


def _position_value(element: Mapping[str, Any], key: str) -> Any:
    value = element.get(key)
    return "" if value is None else value


def _prepare_elements(elements: Iterable[Mapping[str, Any]]) -> List[ElementRecord]:
    """Filter deleted entries and assign a unique output ID to every element."""
    records: List[ElementRecord] = []
    used_ids: Set[str] = {PAGE_ID}

    for index, raw_element in enumerate(elements, start=1):
        if not isinstance(raw_element, dict) or raw_element.get("isDeleted") is True:
            continue

        element = raw_element
        raw_id = element.get("id")
        source_id = raw_id if isinstance(raw_id, str) and raw_id else None
        base_id = source_id or "element-{}".format(index)
        output_id = base_id
        suffix = 2

        while output_id in used_ids:
            output_id = "{}-{}".format(base_id, suffix)
            suffix += 1

        used_ids.add(output_id)
        records.append((element, output_id, source_id))

    return records


def _append_once(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _collect_bindings(
    records: Sequence[ElementRecord],
) -> Tuple[Dict[str, List[str]], Set[str], Dict[str, str], Set[str]]:
    """Resolve bound text and source IDs to their emitted CSV IDs."""
    source_to_output: Dict[str, str] = {}
    text_source_to_output: Dict[str, str] = {}
    text_by_output: Dict[str, Element] = {}
    container_output_ids: Set[str] = set()

    for element, output_id, source_id in records:
        element_type = _element_type(element)
        if source_id is not None and source_id not in source_to_output:
            source_to_output[source_id] = output_id
        if element_type == "text":
            text_by_output[output_id] = element
            if source_id is not None and source_id not in text_source_to_output:
                text_source_to_output[source_id] = output_id
        else:
            container_output_ids.add(output_id)

    bound_text_by_container: Dict[str, List[str]] = {}
    bound_text_output_ids: Set[str] = set()

    def bind(container_output_id: str, text_output_id: str) -> None:
        if (
            container_output_id not in container_output_ids
            or text_output_id not in text_by_output
        ):
            return
        container_bindings = bound_text_by_container.setdefault(container_output_id, [])
        _append_once(container_bindings, text_output_id)
        bound_text_output_ids.add(text_output_id)

    for element, output_id, _source_id in records:
        if _element_type(element) == "text":
            continue
        bound_elements = element.get("boundElements", [])
        if not isinstance(bound_elements, list):
            continue
        for binding in bound_elements:
            if not isinstance(binding, dict):
                continue
            binding_id = binding.get("id")
            if isinstance(binding_id, str):
                text_output_id = text_source_to_output.get(binding_id)
                if text_output_id is not None:
                    bind(output_id, text_output_id)

    for element, text_output_id, _source_id in records:
        if _element_type(element) != "text":
            continue
        container_id = element.get("containerId")
        if isinstance(container_id, str):
            container_output_id = source_to_output.get(container_id)
            if container_output_id is not None:
                bind(container_output_id, text_output_id)

    return (
        bound_text_by_container,
        bound_text_output_ids,
        source_to_output,
        container_output_ids,
    )


def _label_for_element(
    element: Mapping[str, Any],
    output_id: str,
    bound_text_by_container: Mapping[str, Sequence[str]],
    text_by_output: Mapping[str, Mapping[str, Any]],
) -> str:
    labels: List[str] = []
    direct_text = _text_value(element)
    if direct_text:
        labels.append(direct_text)

    for text_output_id in bound_text_by_container.get(output_id, []):
        label = _text_value(text_by_output[text_output_id])
        if label:
            _append_once(labels, label)

    return "\n".join(labels)


def _bound_endpoint(
    element: Mapping[str, Any],
    binding_name: str,
    source_to_output: Mapping[str, str],
    node_output_ids: Set[str],
) -> str:
    binding = element.get(binding_name)
    if not isinstance(binding, dict):
        return ""

    source_id = binding.get("elementId")
    if not isinstance(source_id, str):
        return ""

    output_id = source_to_output.get(source_id, "")
    return output_id if output_id in node_output_ids else ""


def _arrow_style(element: Mapping[str, Any], key: str, default: str) -> str:
    """Map an Excalidraw arrowhead to a supported Lucidchart endpoint style."""
    if key not in element:
        return default

    arrowhead = element.get(key)
    if arrowhead is None:
        return "None"
    if arrowhead == "triangle":
        return "Hollow Arrow"
    return "Arrow"


def _page_row(title: str) -> Dict[str, Any]:
    return {
        "Id": PAGE_ID,
        "Name": "Page",
        "Shape Library": "",
        "Page ID": "",
        "Contained By": "",
        "Text Area 1": title,
        "Line Source": "",
        "Line Destination": "",
        "Source Arrow": "",
        "Destination Arrow": "",
        "x": "",
        "y": "",
    }


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric_value = float(value)
        if math.isfinite(numeric_value):
            return numeric_value
    return default


def _format_number(value: float) -> str:
    return "{:.3f}".format(value).rstrip("0").rstrip(".") or "0"


def _font_size(element: Mapping[str, Any]) -> float:
    return max(8.0, _number(element.get("fontSize"), 16.0))


def _wrapped_lines(text: str) -> List[str]:
    lines: List[str] = []
    for source_line in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            source_line,
            width=MAX_TEXT_LINE_CHARACTERS,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        lines.extend(wrapped or [""])
    return lines


def _calculated_dimensions(
    element: Mapping[str, Any],
    layout_text: str,
    font_size: float,
) -> Tuple[float, float]:
    """Calculate a padded shape size from wrapped text and source geometry."""
    lines = _wrapped_lines(layout_text)
    longest_line = max((len(line) for line in lines), default=0)
    calculated_width = longest_line * font_size * 0.6 + HORIZONTAL_TEXT_PADDING
    calculated_width = min(calculated_width, MAX_CALCULATED_WIDTH)
    calculated_height = len(lines) * font_size * 1.25 + VERTICAL_TEXT_PADDING

    source_width = abs(_number(element.get("width")))
    source_height = abs(_number(element.get("height")))
    width = max(MIN_NODE_WIDTH, source_width, calculated_width)
    height = max(MIN_NODE_HEIGHT, source_height, calculated_height)
    return width, height


def _drawio_label(text: str) -> str:
    escaped_text = html.escape(text, quote=False)
    return escaped_text.replace("\n", "<br>")


def _drawio_color(value: Any, default: str) -> str:
    if not isinstance(value, str) or not value:
        return default
    if value == "transparent":
        return "none"
    return value


def _drawio_shape_style(
    element: Mapping[str, Any],
    element_type: str,
    font_size: float,
) -> str:
    if element_type == "ellipse":
        shape_style = "ellipse;"
    elif element_type == "diamond":
        shape_style = "rhombus;"
    elif element_type == "text":
        shape_style = "text;strokeColor=none;fillColor=none;"
    else:
        rounded = "1" if element.get("roundness") else "0"
        shape_style = "rounded={};".format(rounded)

    stroke_color = _drawio_color(element.get("strokeColor"), "#1b1b1f")
    fill_color = _drawio_color(element.get("backgroundColor"), "#ffffff")
    stroke_width = max(1.0, _number(element.get("strokeWidth"), 1.0))
    opacity = min(100.0, max(0.0, _number(element.get("opacity"), 100.0)))
    stroke_style = element.get("strokeStyle")
    dashed = "1" if stroke_style in {"dashed", "dotted"} else "0"
    dash_pattern = "1 4" if stroke_style == "dotted" else "8 8"

    return (
        shape_style
        + "whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
        + "spacing=8;fontSize={};strokeColor={};fillColor={};"
        .format(_format_number(font_size), stroke_color, fill_color)
        + "strokeWidth={};opacity={};dashed={};dashPattern={};"
        .format(
            _format_number(stroke_width),
            _format_number(opacity),
            dashed,
            dash_pattern,
        )
    )


def _drawio_arrowhead(value: Any, default: str) -> Tuple[str, str]:
    if value is None:
        return "none", "0"
    if value == "dot":
        return "oval", "1"
    if value == "bar":
        return "dash", "0"
    if value == "triangle":
        return "block", "0"
    if value == "arrow" or value is not None:
        return "block", "1"
    return default, "1"


def _drawio_line_style(element: Mapping[str, Any], element_type: str) -> str:
    start_value = element.get("startArrowhead")
    if "endArrowhead" in element:
        end_value = element.get("endArrowhead")
    else:
        end_value = "arrow" if element_type == "arrow" else None

    start_arrow, start_fill = _drawio_arrowhead(start_value, "none")
    end_arrow, end_fill = _drawio_arrowhead(end_value, "none")
    stroke_color = _drawio_color(element.get("strokeColor"), "#1b1b1f")
    stroke_width = max(1.0, _number(element.get("strokeWidth"), 1.0))
    opacity = min(100.0, max(0.0, _number(element.get("opacity"), 100.0)))
    stroke_style = element.get("strokeStyle")
    dashed = "1" if stroke_style in {"dashed", "dotted"} else "0"
    dash_pattern = "1 4" if stroke_style == "dotted" else "8 8"

    return (
        "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;"
        + "rounded=0;html=1;"
        + "startArrow={};startFill={};endArrow={};endFill={};"
        .format(start_arrow, start_fill, end_arrow, end_fill)
        + "strokeColor={};strokeWidth={};opacity={};dashed={};dashPattern={};"
        .format(
            stroke_color,
            _format_number(stroke_width),
            _format_number(opacity),
            dashed,
            dash_pattern,
        )
    )


def _edge_points(element: Mapping[str, Any]) -> List[Tuple[float, float]]:
    origin_x = _number(element.get("x"))
    origin_y = _number(element.get("y"))
    raw_points = element.get("points")
    points: List[Tuple[float, float]] = []

    if isinstance(raw_points, list):
        for raw_point in raw_points:
            if not isinstance(raw_point, list) or len(raw_point) < 2:
                continue
            points.append(
                (
                    origin_x + _number(raw_point[0]),
                    origin_y + _number(raw_point[1]),
                )
            )

    if points:
        return points

    return [
        (origin_x, origin_y),
        (
            origin_x + _number(element.get("width")),
            origin_y + _number(element.get("height")),
        ),
    ]


def build_drawio_document(
    elements: Iterable[Mapping[str, Any]],
    title: str = "Excalidraw Import",
) -> ET.Element:
    """Build an editable Draw.io document with text-aware shape geometry."""
    records = _prepare_elements(elements)
    (
        bound_text_by_container,
        bound_text_output_ids,
        source_to_output,
        _container_output_ids,
    ) = _collect_bindings(records)
    text_by_output = {
        output_id: element
        for element, output_id, _source_id in records
        if _element_type(element) == "text"
    }
    node_output_ids = {
        output_id
        for element, output_id, _source_id in records
        if _element_type(element) not in CONNECTOR_TYPES
        and output_id not in bound_text_output_ids
    }
    drawio_ids = {
        output_id: "element-{}".format(output_id)
        for _element, output_id, _source_id in records
    }

    emitted_nodes = [
        element
        for element, output_id, _source_id in records
        if output_id in node_output_ids
    ]
    min_x = min((_number(element.get("x")) for element in emitted_nodes), default=0.0)
    min_y = min((_number(element.get("y")) for element in emitted_nodes), default=0.0)
    offset_x = 40.0 - min_x
    offset_y = 40.0 - min_y

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "excalidraw_to_lucidchart.py",
            "version": "24.7.17",
            "type": "device",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "excalidraw-import", "name": title})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "0",
            "pageScale": "1",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    for element, output_id, _source_id in records:
        if output_id not in node_output_ids:
            continue

        element_type = _element_type(element)
        label = _label_for_element(
            element,
            output_id,
            bound_text_by_container,
            text_by_output,
        )
        bound_text_elements = [
            text_by_output[text_output_id]
            for text_output_id in bound_text_by_container.get(output_id, [])
        ]
        sizing_elements = bound_text_elements or [element]
        layout_text = "\n".join(
            text
            for text in (_layout_text_value(text_element) for text_element in sizing_elements)
            if text
        )
        font_size = max(
            (_font_size(text_element) for text_element in sizing_elements),
            default=16.0,
        )
        width, height = _calculated_dimensions(
            element,
            layout_text or label,
            font_size,
        )
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": drawio_ids[output_id],
                "value": _drawio_label(label),
                "style": _drawio_shape_style(element, element_type, font_size),
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": _format_number(_number(element.get("x")) + offset_x),
                "y": _format_number(_number(element.get("y")) + offset_y),
                "width": _format_number(width),
                "height": _format_number(height),
                "as": "geometry",
            },
        )

    for element, output_id, _source_id in records:
        element_type = _element_type(element)
        if element_type not in CONNECTOR_TYPES:
            continue

        label = _label_for_element(
            element,
            output_id,
            bound_text_by_container,
            text_by_output,
        )
        source_output_id = _bound_endpoint(
            element,
            "startBinding",
            source_to_output,
            node_output_ids,
        )
        target_output_id = _bound_endpoint(
            element,
            "endBinding",
            source_to_output,
            node_output_ids,
        )
        attributes = {
            "id": drawio_ids[output_id],
            "value": _drawio_label(label),
            "style": _drawio_line_style(element, element_type),
            "edge": "1",
            "parent": "1",
        }
        if source_output_id:
            attributes["source"] = drawio_ids[source_output_id]
        if target_output_id:
            attributes["target"] = drawio_ids[target_output_id]

        cell = ET.SubElement(root, "mxCell", attributes)
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        points = _edge_points(element)
        if not source_output_id:
            ET.SubElement(
                geometry,
                "mxPoint",
                {
                    "x": _format_number(points[0][0] + offset_x),
                    "y": _format_number(points[0][1] + offset_y),
                    "as": "sourcePoint",
                },
            )
        if not target_output_id:
            ET.SubElement(
                geometry,
                "mxPoint",
                {
                    "x": _format_number(points[-1][0] + offset_x),
                    "y": _format_number(points[-1][1] + offset_y),
                    "as": "targetPoint",
                },
            )
        if len(points) > 2:
            point_array = ET.SubElement(geometry, "Array", {"as": "points"})
            for point_x, point_y in points[1:-1]:
                ET.SubElement(
                    point_array,
                    "mxPoint",
                    {
                        "x": _format_number(point_x + offset_x),
                        "y": _format_number(point_y + offset_y),
                    },
                )

    return mxfile


def compress_drawio_document(document: ET.Element) -> ET.Element:
    """Encode an uncompressed Draw.io document using its native save format."""
    diagram = document.find("diagram")
    if diagram is None:
        raise ValueError("Draw.io document is missing its diagram element")
    model = diagram.find("mxGraphModel")
    if model is None:
        raise ValueError("Draw.io document is missing its graph model")

    model_xml = ET.tostring(model, encoding="unicode")
    encoded_xml = urllib.parse.quote(
        model_xml,
        safe="~()*!.'-_",
    ).encode("utf-8")
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    compressed_xml = compressor.compress(encoded_xml) + compressor.flush()

    diagram.remove(model)
    diagram.text = base64.b64encode(compressed_xml).decode("ascii")
    document.set("compressed", "true")
    document.set("pages", "1")
    return document


def convert_elements(elements: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Excalidraw elements into Lucidchart CSV row dictionaries."""
    records = _prepare_elements(elements)
    (
        bound_text_by_container,
        bound_text_output_ids,
        source_to_output,
        _container_output_ids,
    ) = _collect_bindings(records)
    text_by_output = {
        output_id: element
        for element, output_id, _source_id in records
        if _element_type(element) == "text"
    }
    node_output_ids = {
        output_id
        for element, output_id, _source_id in records
        if _element_type(element) not in CONNECTOR_TYPES
        and output_id not in bound_text_output_ids
    }

    rows: List[Dict[str, Any]] = []
    for element, output_id, _source_id in records:
        element_type = _element_type(element)

        if element_type == "text" and output_id in bound_text_output_ids:
            continue

        label = _label_for_element(
            element,
            output_id,
            bound_text_by_container,
            text_by_output,
        )
        row: Dict[str, Any] = {
            "Id": output_id,
            "Name": SHAPE_TYPES.get(element_type, "Process"),
            "Shape Library": SHAPE_LIBRARY,
            "Page ID": PAGE_ID,
            "Contained By": "",
            "Text Area 1": label,
            "Line Source": "",
            "Line Destination": "",
            "Source Arrow": "",
            "Destination Arrow": "",
            "x": _position_value(element, "x"),
            "y": _position_value(element, "y"),
        }

        if element_type in CONNECTOR_TYPES:
            row["Name"] = "Line"
            row["Shape Library"] = ""
            row["Line Source"] = _bound_endpoint(
                element,
                "startBinding",
                source_to_output,
                node_output_ids,
            )
            row["Source Arrow"] = _arrow_style(element, "startArrowhead", "None")
            destination_default = "Arrow" if element_type == "arrow" else "None"
            row["Destination Arrow"] = _arrow_style(
                element,
                "endArrowhead",
                destination_default,
            )
            row["Line Destination"] = _bound_endpoint(
                element,
                "endBinding",
                source_to_output,
                node_output_ids,
            )

        rows.append(row)

    return rows


def convert_file(input_path: Path, output_path: Path) -> None:
    """Read Excalidraw JSON and write CSV or editable Draw.io output."""
    with input_path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    if not isinstance(data, dict):
        raise ValueError("Excalidraw input must be a JSON object")
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise ValueError("Excalidraw input must contain a top-level 'elements' array")

    if output_path.suffix.lower() in DRAWIO_OUTPUT_SUFFIXES:
        document = compress_drawio_document(
            build_drawio_document(elements, input_path.stem)
        )
        ET.ElementTree(document).write(
            output_path,
            encoding="utf-8",
            xml_declaration=True,
        )
        return

    rows = [_page_row(input_path.stem)]
    rows.extend(convert_elements(elements))
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Excalidraw JSON to Lucidchart process CSV or editable Draw.io XML."
        )
    )
    parser.add_argument("input_file", type=Path, help="Path to the input .excalidraw file")
    parser.add_argument(
        "output_file",
        type=Path,
        help="Path for the output .csv, .drawio, or .xml file",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        convert_file(args.input_file, args.output_file)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.exit(1, "error: {}\n".format(error))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
