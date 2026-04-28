
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True, slots=True)
class FunctionSpec:
	"""Declarative contract for a high-level CAD modeling capability.

	This is intentionally CAD-backend-agnostic: it describes *intent* and
	input/output shapes without referencing any specific CAD API types.
	"""

	name: str
	description: str
	inputs: Mapping[str, Any]
	outputs: Mapping[str, Any]
	postconditions: Tuple[str, ...]


def _load_function_registry() -> Dict[str, FunctionSpec]:
	path = Path(__file__).resolve().parent / "functions.json"
	if not path.exists():
		raise RuntimeError(f"functions.json not found at {path}")

	data = json.loads(path.read_text(encoding="utf-8"))
	registry: Dict[str, FunctionSpec] = {}
	for name, spec in data.items():
		registry[name] = FunctionSpec(
			name=str(spec.get("name", name)),
			description=str(spec.get("description", "")),
			inputs=dict(spec.get("inputs", {})),
			outputs=dict(spec.get("outputs", {})),
			postconditions=tuple(spec.get("postconditions", ())),
		)
	return registry


FUNCTION_REGISTRY: Dict[str, FunctionSpec] = _load_function_registry()

