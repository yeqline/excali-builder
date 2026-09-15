"""Transactional optimization and restore operations for CLI and local viewer."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from ..excalidraw.positions import extract_positions_from_elements, merge_positions
from .engines import get_engine
from .state import STATE_FILE, atomic_json

BACKUP_FILE = "layout-backup.json"
OUTPUT_FILES = (
    "config.json",
    "node_config.json",
    "edge_config.json",
    "positions.json",
    "output.excalidraw",
    STATE_FILE,
)


def can_optimize_wiring(config):
    """CSV diagrams and diagrams already on the wiring algorithm may be optimized."""
    config = config or {}
    parser_type = config.get("parser_type") or "csv"
    algorithm = (config.get("layout") or {}).get("algorithm")
    return parser_type == "csv" or algorithm == "wiring"


def _source_digest(folder):
    digest = hashlib.sha256()
    for path in sorted(folder.iterdir()):
        if path.is_file() and (
            path.suffix in {".csv", ".md"}
            or path.name
            in {
                "config.json",
                "node_config.json",
                "edge_config.json",
                "graph.json",
            }
        ):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def optimize_folder(folder: Path, engine=None, elements=None):
    """Build in a temporary copy, then publish a complete validated layout."""
    from ..builder import ExcaliBuilder

    folder = Path(folder).resolve()
    original = {
        name: json.loads((folder / name).read_text()) if (folder / name).exists() else None
        for name in OUTPUT_FILES
    }
    config = original["config.json"] or {}
    if not can_optimize_wiring(config):
        raise ValueError(
            "Optimize wiring layout is for CSV diagrams, "
            "or diagrams already using the wiring algorithm"
        )
    engine = engine or config.get("layout", {}).get("engine", "elk")
    get_engine(engine)
    source_digest = _source_digest(folder)
    with tempfile.TemporaryDirectory(prefix="excali-optimize-") as directory:
        stage = Path(directory) / "diagram"
        shutil.copytree(
            folder,
            stage,
            symlinks=False,
            ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", BACKUP_FILE),
        )
        if elements is not None:
            baseline = original["output.excalidraw"] or {}
            known_ids = {
                e.get("customData", {}).get("node_id") for e in baseline.get("elements", [])
            }
            positions = extract_positions_from_elements(
                elements, known_node_ids=known_ids, baseline_elements=baseline.get("elements", [])
            )
            merge_positions(stage / "positions.json", positions)
            original["positions.json"] = json.loads((stage / "positions.json").read_text())
            original["output.excalidraw"] = {**baseline, "elements": elements}
        else:
            ExcaliBuilder().sync_from_folder(str(stage))
        config = json.loads(json.dumps(config))
        config.setdefault("layout", {}).update({"algorithm": "wiring", "engine": engine})
        atomic_json(stage / "config.json", config)
        builder = ExcaliBuilder()
        builder.build_from_folder(str(stage), optimize_layout=True)
        if _source_digest(folder) != source_digest:
            raise ValueError("Diagram sources changed during optimization. Run it again.")
        generated = {
            name: json.loads((stage / name).read_text())
            for name in OUTPUT_FILES
            if (stage / name).exists()
        }
        try:
            for name, content in generated.items():
                atomic_json(folder / name, content)
            atomic_json(
                folder / BACKUP_FILE,
                {
                    "version": 1,
                    "source_digest": _source_digest(folder),
                    "files": original,
                },
            )
        except Exception:
            _restore_files(folder, original)
            raise
    return {"metrics": builder.last_layout_metrics, "engine": engine, "can_restore": True}


def restore_folder(folder: Path):
    """Restore the preceding layout only while its source graph is unchanged."""
    folder = Path(folder)
    path = folder / BACKUP_FILE
    if not path.exists():
        raise ValueError("There is no previous optimized layout to restore")
    backup = json.loads(path.read_text())
    if backup.get("version") != 1 or set(backup.get("files", {})) != set(OUTPUT_FILES):
        raise ValueError("The layout backup has an unsupported format")
    if backup.get("source_digest") != _source_digest(folder):
        raise ValueError(
            "Sources changed since optimization; the previous layout cannot be restored safely"
        )
    _restore_files(folder, backup["files"])
    path.unlink()
    return {"restored": True, "can_restore": False}


def _restore_files(folder, files):
    for name in OUTPUT_FILES:
        content = files[name]
        path = folder / name
        if content is None:
            if path.exists():
                path.unlink()
        else:
            atomic_json(path, content)
