"""Wire Agent2 modules into one legacy-compatible namespace."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


MODULE_NAMES = [
    "common",
    "placements",
    "interfaces",
    "features",
    "outputs",
]

_WIRED = False
_NAMESPACE: dict[str, Any] = {}


def _exportable_items(module: ModuleType) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("__") and name not in {"annotations"}
    }


def wire_agent2_modules() -> dict[str, Any]:
    """Return a merged namespace and patch split modules for cross-module helper calls."""
    global _WIRED, _NAMESPACE
    if _WIRED:
        return dict(_NAMESPACE)
    package = __package__
    modules = [importlib.import_module(f"{package}.{name}") for name in MODULE_NAMES]
    namespace: dict[str, Any] = {}
    for module in modules:
        namespace.update(_exportable_items(module))
    for module in modules:
        module.__dict__.update(namespace)
    _NAMESPACE = namespace
    _WIRED = True
    return dict(namespace)
