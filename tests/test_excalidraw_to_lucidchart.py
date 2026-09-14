import base64
import csv
import json
import tempfile
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

from excalidraw_to_lucidchart import (
    CSV_COLUMNS,
    PAGE_ID,
    build_drawio_document,
    convert_elements,
    main,
)


class ExcalidrawToLucidchartTests(unittest.TestCase):
    def test_converts_shapes_bound_text_connectors_and_standalone_text(self):
        elements = [
            {
                "id": "rect-1",
                "type": "rectangle",
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
                "boundElements": [{"id": "label-1", "type": "text"}],
                "groupIds": ["group-1"],
            },
            {
                "id": "label-1",
                "type": "text",
                "x": 25,
                "y": 35,
                "text": "Start",
                "containerId": "rect-1",
                "groupIds": ["group-1"],
            },
            {
                "id": "decision-1",
                "type": "diamond",
                "x": 200,
                "y": 20,
                "boundElements": [{"id": "label-2", "type": "text"}],
            },
            {
                "id": "label-2",
                "type": "text",
                "x": 220,
                "y": 35,
                "text": "Ready?",
            },
            {
                "id": "ellipse-1",
                "type": "ellipse",
                "x": 400,
                "y": 20,
                "text": "Done",
            },
            {
                "id": "arrow-1",
                "type": "arrow",
                "x": 110,
                "y": 45,
                "startBinding": {"elementId": "rect-1"},
                "endBinding": {"elementId": "decision-1"},
            },
            {
                "id": "line-1",
                "type": "line",
                "x": 300,
                "y": 45,
                "startBinding": {"elementId": "decision-1"},
                "endBinding": None,
            },
            {
                "id": "note-1",
                "type": "text",
                "x": 10,
                "y": 150,
                "text": "Standalone note",
                "groupIds": ["group-1"],
            },
        ]

        rows = convert_elements(elements)
        rows_by_id = {row["Id"]: row for row in rows}

        self.assertEqual(
            set(rows_by_id),
            {
                "rect-1",
                "decision-1",
                "ellipse-1",
                "arrow-1",
                "line-1",
                "note-1",
            },
        )
        self.assertEqual(rows_by_id["rect-1"]["Text Area 1"], "Start")
        self.assertEqual(rows_by_id["rect-1"]["Name"], "Process")
        self.assertEqual(rows_by_id["rect-1"]["Shape Library"], "Flowchart Shapes")
        self.assertEqual(rows_by_id["rect-1"]["Page ID"], PAGE_ID)
        self.assertEqual(rows_by_id["rect-1"]["Contained By"], "")
        self.assertEqual(rows_by_id["rect-1"]["x"], 10)
        self.assertEqual(rows_by_id["rect-1"]["y"], 20)
        self.assertEqual(rows_by_id["decision-1"]["Name"], "Decision")
        self.assertEqual(rows_by_id["decision-1"]["Text Area 1"], "Ready?")
        self.assertEqual(rows_by_id["ellipse-1"]["Name"], "Terminator")
        self.assertEqual(rows_by_id["arrow-1"]["Name"], "Line")
        self.assertEqual(rows_by_id["arrow-1"]["Line Source"], "rect-1")
        self.assertEqual(rows_by_id["arrow-1"]["Line Destination"], "decision-1")
        self.assertEqual(rows_by_id["arrow-1"]["Source Arrow"], "None")
        self.assertEqual(rows_by_id["arrow-1"]["Destination Arrow"], "Arrow")
        self.assertEqual(rows_by_id["line-1"]["Name"], "Line")
        self.assertEqual(rows_by_id["line-1"]["Line Source"], "decision-1")
        self.assertEqual(rows_by_id["line-1"]["Line Destination"], "")
        self.assertEqual(rows_by_id["line-1"]["Destination Arrow"], "None")
        self.assertEqual(rows_by_id["note-1"]["Name"], "Process")
        self.assertEqual(rows_by_id["note-1"]["Text Area 1"], "Standalone note")

    def test_connector_can_bind_to_a_standalone_text_box(self):
        elements = [
            {"id": "shape", "type": "rectangle"},
            {"id": "note", "type": "text", "text": "Note"},
            {
                "id": "edge",
                "type": "arrow",
                "startBinding": {"elementId": "shape"},
                "endBinding": {"elementId": "note"},
            },
        ]

        rows_by_id = {row["Id"]: row for row in convert_elements(elements)}

        self.assertEqual(rows_by_id["edge"]["Line Source"], "shape")
        self.assertEqual(rows_by_id["edge"]["Line Destination"], "note")

    def test_bound_connector_text_becomes_the_connector_label(self):
        elements = [
            {"id": "a", "type": "rectangle"},
            {"id": "b", "type": "rectangle"},
            {
                "id": "edge",
                "type": "arrow",
                "boundElements": [{"id": "edge-label", "type": "text"}],
                "startBinding": {"elementId": "a"},
                "endBinding": {"elementId": "b"},
            },
            {"id": "edge-label", "type": "text", "text": "Yes"},
        ]

        rows = convert_elements(elements)
        rows_by_id = {row["Id"]: row for row in rows}

        self.assertNotIn("edge-label", rows_by_id)
        self.assertEqual(rows_by_id["edge"]["Text Area 1"], "Yes")

    def test_main_writes_the_expected_csv_columns(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            input_path = Path(temp_directory) / "input.excalidraw"
            output_path = Path(temp_directory) / "output.csv"
            input_path.write_text(
                json.dumps(
                    {
                        "type": "excalidraw",
                        "elements": [
                            {"id": "shape-1", "type": "rectangle", "x": 0, "y": 0}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(main([str(input_path), str(output_path)]), 0)

            with output_path.open("r", encoding="utf-8", newline="") as output_file:
                reader = csv.DictReader(output_file)
                self.assertEqual(reader.fieldnames, CSV_COLUMNS)
                rows = list(reader)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["Id"], PAGE_ID)
            self.assertEqual(rows[0]["Name"], "Page")
            self.assertEqual(rows[0]["Text Area 1"], "input")
            self.assertEqual(rows[1]["Id"], "shape-1")
            self.assertEqual(rows[1]["Page ID"], PAGE_ID)
            self.assertEqual(rows[1]["x"], "0")

    def test_page_id_cannot_collide_with_an_element_id(self):
        elements = [
            {"id": PAGE_ID, "type": "rectangle"},
            {
                "id": "edge",
                "type": "arrow",
                "startBinding": {"elementId": PAGE_ID},
            },
        ]

        rows_by_id = {row["Id"]: row for row in convert_elements(elements)}

        self.assertIn(PAGE_ID + "-2", rows_by_id)
        self.assertEqual(rows_by_id["edge"]["Line Source"], PAGE_ID + "-2")

    def test_drawio_output_calculates_geometry_from_text_and_preserves_connections(self):
        elements = [
            {
                "id": "short",
                "type": "rectangle",
                "x": -20,
                "y": 10,
                "width": 40,
                "height": 20,
                "boundElements": [{"id": "short-label", "type": "text"}],
            },
            {
                "id": "short-label",
                "type": "text",
                "text": "Short",
                "originalText": "Short",
                "fontSize": 16,
                "containerId": "short",
            },
            {
                "id": "long",
                "type": "diamond",
                "x": 200,
                "y": 10,
                "width": 40,
                "height": 20,
                "boundElements": [{"id": "long-label", "type": "text"}],
            },
            {
                "id": "long-label",
                "type": "text",
                "text": "A much longer line of text\nwith several\nexplicit lines",
                "originalText": "A much longer line of text\nwith several\nexplicit lines",
                "fontSize": 16,
                "containerId": "long",
            },
            {
                "id": "edge",
                "type": "arrow",
                "x": 20,
                "y": 20,
                "points": [[0, 0], [100, 0], [180, 0]],
                "startBinding": {"elementId": "short"},
                "endBinding": {"elementId": "long"},
            },
        ]

        document = build_drawio_document(elements, "Test")
        cells = {cell.get("id"): cell for cell in document.findall(".//mxCell")}
        short_cell = cells["element-short"]
        long_cell = cells["element-long"]
        edge_cell = cells["element-edge"]
        short_geometry = short_cell.find("mxGeometry")
        long_geometry = long_cell.find("mxGeometry")

        self.assertIsNotNone(short_geometry)
        self.assertIsNotNone(long_geometry)
        self.assertGreaterEqual(float(short_geometry.get("width")), 120)
        self.assertGreater(float(long_geometry.get("width")), float(short_geometry.get("width")))
        self.assertGreater(float(long_geometry.get("height")), float(short_geometry.get("height")))
        self.assertIn("rhombus", long_cell.get("style"))
        self.assertEqual(edge_cell.get("source"), "element-short")
        self.assertEqual(edge_cell.get("target"), "element-long")
        self.assertIsNotNone(edge_cell.find("mxGeometry/Array"))

    def test_main_writes_parseable_drawio_xml(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            input_path = Path(temp_directory) / "input.excalidraw"
            output_path = Path(temp_directory) / "output.drawio"
            input_path.write_text(
                json.dumps(
                    {
                        "type": "excalidraw",
                        "elements": [
                            {
                                "id": "shape-1",
                                "type": "ellipse",
                                "text": "Editable",
                                "x": 0,
                                "y": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(main([str(input_path), str(output_path)]), 0)

            document = ET.parse(output_path).getroot()
            diagram = document.find("diagram")
            compressed_model = base64.b64decode(diagram.text)
            encoded_model = zlib.decompress(compressed_model, wbits=-15)
            model_xml = urllib.parse.unquote(encoded_model.decode("utf-8"))
            model = ET.fromstring(model_xml)
            shape = model.find(".//mxCell[@id='element-shape-1']")

            self.assertEqual(document.get("compressed"), "true")
            self.assertIsNotNone(shape)
            self.assertIn("ellipse", shape.get("style"))


if __name__ == "__main__":
    unittest.main()
