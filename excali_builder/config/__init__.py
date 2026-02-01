"""Configuration system for styling and layout."""

from .schema import (
    NodeTypeConfig,
    ContainerConnectionConfig,
    LineConnectionConfig,
    EdgeTypeConfig,
    GlobalConfig,
)
from .loader import ConfigLoader

__all__ = [
    "NodeTypeConfig",
    "ContainerConnectionConfig",
    "LineConnectionConfig",
    "EdgeTypeConfig",
    "GlobalConfig",
    "ConfigLoader",
]

