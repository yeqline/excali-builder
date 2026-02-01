"""Sync system: Update positions.json from Excalidraw file."""

import json
from pathlib import Path
from typing import Dict
from .importer import ExcalidrawImporter


class ExcalidrawSync:
    """Synchronizes node positions from Excalidraw file to positions.json."""

    def __init__(self):
        self.importer = ExcalidrawImporter()

    def sync_from_folder(self, folder_path: Path) -> None:
        """Read .excalidraw file and update positions.json with node geometry."""
        # Look for .excalidraw file (could be output.excalidraw or any .excalidraw file)
        excalidraw_files = list(folder_path.glob("*.excalidraw"))
        if not excalidraw_files:
            # Try output.excalidraw specifically
            excalidraw_path = folder_path / "output.excalidraw"
            if not excalidraw_path.exists():
                return
        else:
            # Use the first .excalidraw file found, or prefer output.excalidraw
            output_path = folder_path / "output.excalidraw"
            excalidraw_path = output_path if output_path.exists() else excalidraw_files[0]

        # Import positions from Excalidraw file
        positions = self.importer.import_positions(excalidraw_path)

        if not positions:
            return

        # Load existing positions.json if it exists
        positions_json_path = folder_path / "positions.json"
        existing_positions: Dict[str, Dict[str, float]] = {}
        if positions_json_path.exists():
            with open(positions_json_path, "r", encoding="utf-8") as f:
                existing_positions = json.load(f)

        # Merge: update existing with new positions, keep any that weren't in Excalidraw
        existing_positions.update(positions)

        # Write updated positions.json
        with open(positions_json_path, "w", encoding="utf-8") as f:
            json.dump(existing_positions, f, indent=2)

