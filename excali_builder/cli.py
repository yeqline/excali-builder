"""CLI entrypoint for excali-builder commands."""

import sys
import argparse
from pathlib import Path
from .builder import ExcaliBuilder


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Build Excalidraw diagrams from source files (syncs positions then builds)"
    )
    parser.add_argument("folder", type=str, help="Path to folder with source files")

    args = parser.parse_args()

    folder_path = Path(args.folder).expanduser().resolve()

    if not folder_path.exists():
        print(f"Error: Folder does not exist: {folder_path}")
        sys.exit(1)

    if not folder_path.is_dir():
        print(f"Error: Path is not a directory: {folder_path}")
        sys.exit(1)

    builder = ExcaliBuilder()

    try:
        # Sync positions first (if Excalidraw file exists), then build
        builder.sync_from_folder(str(folder_path))
        output_path = builder.build_from_folder(str(folder_path))
        print(f"✓ Built diagram: {output_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

