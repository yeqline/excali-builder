"""CLI entrypoint for excali-builder commands."""

import argparse
import sys
from pathlib import Path

from .builder import ExcaliBuilder


def confirm_full_refresh() -> bool:
    """Ask for confirmation before rebuilding the layout from scratch."""
    prompt = (
        "Full refresh will rebuild the layout from scratch and overwrite the current "
        "output.excalidraw while keeping saved node sizes. Continue? [y/N]: "
    )
    try:
        response = input(prompt)
    except EOFError:
        return False
    return response.strip().lower() in {"y", "yes"}


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Build Excalidraw diagrams from source files (syncs positions then builds)"
    )
    parser.add_argument("folder", type=str, help="Path to folder with source files")
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help=(
            "Rebuild layout from scratch while preserving saved node sizes. "
            "Useful when you want a fresh initial layout without losing resized boxes."
        ),
    )

    args = parser.parse_args()

    folder_path = Path(args.folder).expanduser().resolve()

    if not folder_path.exists():
        print(f"Error: Folder does not exist: {folder_path}")
        sys.exit(1)

    if not folder_path.is_dir():
        print(f"Error: Path is not a directory: {folder_path}")
        sys.exit(1)

    if args.full_refresh and not confirm_full_refresh():
        print("Cancelled full refresh.")
        sys.exit(0)

    builder = ExcaliBuilder()

    try:
        # Sync positions first (if Excalidraw file exists), then build.
        # Full refresh still syncs first so saved widths/heights are preserved.
        builder.sync_from_folder(str(folder_path))
        output_path = builder.build_from_folder(
            str(folder_path),
            full_refresh=args.full_refresh,
        )
        if args.full_refresh:
            # Persist the new layout immediately so positions.json matches the rebuilt output.
            builder.sync_from_folder(str(folder_path))
        print(f"✓ Built diagram: {output_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
