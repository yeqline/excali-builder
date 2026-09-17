"""Engine factories, including installed Python entry-point extensions."""

from importlib import metadata
from typing import Callable, Dict, List

from .base import LayoutEngine

_factories: Dict[str, Callable[[], LayoutEngine]] = {}
_discovered = False


def register_engine(name: str, factory: Callable[[], LayoutEngine]) -> None:
    """Register a factory without changing the builder, exporter, or UI."""
    if not name or not callable(factory):
        raise ValueError("An engine needs a nonempty name and callable factory")
    _factories[name] = factory


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    from .elk import ElkEngine
    from .hybrid import HybridEngine

    _factories.setdefault("elk", ElkEngine)
    _factories.setdefault("hybrid", HybridEngine)
    entries = metadata.entry_points()
    entries = (
        entries.select(group="excali_builder.layout_engines")
        if hasattr(entries, "select")
        else entries.get("excali_builder.layout_engines", [])
    )
    for entry in entries:

        def load_factory(entry=entry):
            return entry.load()()

        _factories.setdefault(entry.name, load_factory)
    _discovered = True


def available_engines() -> List[str]:
    _discover()
    return sorted(_factories)


def get_engine(name: str) -> LayoutEngine:
    _discover()
    if name not in _factories:
        raise ValueError(
            f"Unknown wiring engine '{name}'. Available: {', '.join(available_engines())}"
        )
    engine = _factories[name]()
    if not callable(getattr(engine, "layout", None)):
        raise TypeError(f"Layout engine '{name}' must implement layout(request)")
    return engine
