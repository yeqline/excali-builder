"""Importer: Parse Excalidraw JSON and extract node positions."""

import json
from pathlib import Path
from typing import Dict, Any


class ExcalidrawImporter:
    """Imports geometry data from Excalidraw JSON files."""

    def import_positions(self, excalidraw_path: Path) -> Dict[str, Dict[str, Any]]:
        """Extract node positions, sizes, and text alignment from Excalidraw file by matching node_id in customData."""
        positions: Dict[str, Dict[str, Any]] = {}

        if not excalidraw_path.exists():
            return positions

        with open(excalidraw_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        elements = data.get("elements", [])
        
        # First pass: extract geometry from shape elements
        for element in elements:
            # Only extract geometry from elements with node_id in customData
            custom_data = element.get("customData", {})
            node_id = custom_data.get("node_id")

            if not node_id:
                continue

            # Skip text elements for geometry - we'll handle them separately
            element_type = element.get("type")
            if element_type == "text":
                continue

            # Extract geometry from shape elements
            x = element.get("x", 0)
            y = element.get("y", 0)
            width = element.get("width", 0)
            height = element.get("height", 0)

            # Only store if we have valid dimensions
            if width > 0 and height > 0:
                positions[node_id] = {
                    "x": float(x),
                    "y": float(y),
                    "width": float(width),
                    "height": float(height),
                }
        
        # Second pass: extract text alignment and geometry from text elements
        for element in elements:
            custom_data = element.get("customData", {})
            node_id = custom_data.get("node_id")
            element_type = element.get("type")
            
            if not node_id or element_type != "text":
                continue
            
            # Extract text alignment properties
            text_align = element.get("textAlign")
            vertical_align = element.get("verticalAlign")
            
            # Extract text element geometry (Excalidraw calculates this when containerId is set)
            text_x = element.get("x")
            text_y = element.get("y")
            text_width = element.get("width")
            text_height = element.get("height")
            
            # Add text alignment and geometry to the node's position data
            if node_id in positions:
                if text_align:
                    positions[node_id]["textAlign"] = text_align
                if vertical_align:
                    positions[node_id]["verticalAlign"] = vertical_align
                # Store text element geometry (Excalidraw-calculated values)
                if text_x is not None:
                    positions[node_id]["text_x"] = float(text_x)
                if text_y is not None:
                    positions[node_id]["text_y"] = float(text_y)
                if text_width is not None and text_width > 0:
                    positions[node_id]["text_width"] = float(text_width)
                if text_height is not None and text_height > 0:
                    positions[node_id]["text_height"] = float(text_height)

        return positions

