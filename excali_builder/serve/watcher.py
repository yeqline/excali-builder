"""Polling file watcher used by local serve mode."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set


SOURCE_SUFFIXES = {".md", ".csv"}
WATCHED_FILENAMES = {
    "config.json",
    "node_config.json",
    "edge_config.json",
    "output.excalidraw",
}
OUTPUT_FILENAME = "output.excalidraw"


@dataclass(frozen=True)
class FileSignature:
    """Small signature for detecting top-level map file changes."""

    mtime_ns: int
    size: int


@dataclass
class FolderChanges:
    """Changes collected from one polling pass."""

    source_paths: List[Path]
    output_changed: bool

    @property
    def has_changes(self) -> bool:
        return bool(self.source_paths) or self.output_changed


class FolderWatchState:
    """Track watched files and ignore writes made by this process."""

    def __init__(self, folder: Path, extra_paths: Optional[List[Path]] = None):
        self.folder = folder
        self.extra_paths: Set[Path] = set()
        self.set_extra_paths(extra_paths or [])
        self.snapshot = self.scan()
        self._internal_writes: Dict[Path, FileSignature] = {}

    def set_extra_paths(self, extra_paths: List[Path]) -> None:
        """Set additional files watched outside the top-level diagram folder."""
        self.extra_paths = {path.resolve() for path in extra_paths}

    def scan(self) -> Dict[Path, FileSignature]:
        """Return signatures for watched top-level files."""
        signatures: Dict[Path, FileSignature] = {}
        for path in self._watched_paths():
            signature = file_signature(path)
            if signature is not None:
                signatures[path.resolve()] = signature
        return signatures

    def refresh(self) -> None:
        """Replace the baseline snapshot with the current folder state."""
        self.snapshot = self.scan()

    def mark_internal_write(self, path: Path) -> None:
        """Record a file signature that should be ignored once by the watcher."""
        signature = file_signature(path)
        if signature is not None:
            self._internal_writes[path.resolve()] = signature

    def collect_changes(self) -> FolderChanges:
        """Return externally meaningful changes since the previous snapshot."""
        current = self.scan()
        changed_paths = self._changed_paths(current)
        source_paths: List[Path] = []
        output_changed = False

        for path in sorted(changed_paths):
            current_signature = current.get(path)
            if self._internal_writes.get(path) == current_signature:
                self._internal_writes.pop(path, None)
                continue

            if path.name == OUTPUT_FILENAME:
                output_changed = True
            else:
                source_paths.append(path)

        self.snapshot = current
        return FolderChanges(source_paths=source_paths, output_changed=output_changed)

    def _changed_paths(self, current: Dict[Path, FileSignature]) -> Set[Path]:
        paths = set(self.snapshot) | set(current)
        return {path for path in paths if self.snapshot.get(path) != current.get(path)}

    def _watched_paths(self) -> List[Path]:
        paths = []
        for path in self.folder.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in SOURCE_SUFFIXES or path.name in WATCHED_FILENAMES:
                paths.append(path)
        paths.extend(sorted(self.extra_paths, key=str))
        return paths


def file_signature(path: Path) -> Optional[FileSignature]:
    """Return a signature for a file, or None if it is absent."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    return FileSignature(mtime_ns=stat.st_mtime_ns, size=stat.st_size)
