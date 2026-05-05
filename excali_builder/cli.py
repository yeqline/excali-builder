"""CLI entrypoint for excali-builder commands."""

import argparse
import sys
from pathlib import Path

from .builder import ExcaliBuilder
from .serve import serve_folder


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


def create_build_parser() -> argparse.ArgumentParser:
    """Create the backward-compatible build command parser."""
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

    return parser


def create_serve_parser() -> argparse.ArgumentParser:
    """Create the serve subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="excali-builder serve",
        description="Serve a local auto-refreshing Excalidraw viewer",
    )
    parser.add_argument("folder", type=str, help="Path to folder with source files")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind, or 0 for an ephemeral port (default: 8765)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds for source file changes (default: 1.0)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the viewer URL without opening a browser",
    )
    return parser


def parse_args(argv=None):
    """Parse CLI arguments while preserving the original positional build form."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        args = create_serve_parser().parse_args(argv[1:])
        args.command = "serve"
        return args

    args = create_build_parser().parse_args(argv)
    args.command = "build"
    return args


def validate_folder(folder: str) -> Path:
    """Validate and resolve a build folder path."""
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.exists():
        print(f"Error: Folder does not exist: {folder_path}")
        sys.exit(1)

    if not folder_path.is_dir():
        print(f"Error: Path is not a directory: {folder_path}")
        sys.exit(1)

    return folder_path


def main():
    """Main CLI entrypoint."""
    args = parse_args()
    folder_path = validate_folder(args.folder)

    if args.command == "serve":
        if args.port < 0 or args.port > 65535:
            print("Error: --port must be between 0 and 65535", file=sys.stderr)
            sys.exit(1)
        if args.poll_interval <= 0:
            print("Error: --poll-interval must be greater than 0", file=sys.stderr)
            sys.exit(1)
        try:
            serve_folder(
                folder_path,
                host=args.host,
                port=args.port,
                poll_interval=args.poll_interval,
                open_browser=not args.no_open,
            )
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
        return

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
