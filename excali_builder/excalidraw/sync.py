"""Sync system: Update positions.json from Excalidraw file."""

from pathlib import Path

from .importer import ExcalidrawImporter
from .positions import merge_positions


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

        # Merge: update existing with new positions, keep any that weren't in Excalidraw.
        merge_positions(folder_path / "positions.json", positions)
