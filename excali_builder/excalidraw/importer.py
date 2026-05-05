"""Importer: Parse Excalidraw JSON and extract node positions."""

import json
from pathlib import Path
from typing import Any, Dict

from .positions import extract_positions_from_elements


class ExcalidrawImporter:
    """Imports geometry data from Excalidraw JSON files."""

    def import_positions(self, excalidraw_path: Path) -> Dict[str, Dict[str, Any]]:
        """Extract node layout by matching ``customData.node_id``."""
        if not excalidraw_path.exists():
            return {}

        with open(excalidraw_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return extract_positions_from_elements(data.get("elements", []))
