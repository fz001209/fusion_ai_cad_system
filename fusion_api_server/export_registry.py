
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .registry import FUNCTION_REGISTRY


def _spec_to_jsonable(spec: Any) -> Dict[str, Any]:
	"""Convert a FunctionSpec-like object into a JSON-serializable dict.

	Intentionally avoids CAD/runtime execution. This is a pure data export.
	"""

	return {
		"name": str(getattr(spec, "name")),
		"description": str(getattr(spec, "description")),
		"inputs": dict(getattr(spec, "inputs")),
		"outputs": dict(getattr(spec, "outputs")),
		"postconditions": list(getattr(spec, "postconditions")),
	}


def export_functions_json(output_path: Path | None = None) -> Path:
	"""Export FUNCTION_REGISTRY to a stable JSON file.

	Output is deterministic via sorted function keys + JSON sort_keys.
	"""

	if output_path is None:
		output_path = Path(__file__).resolve().parent / "functions.json"

	exported: Dict[str, Any] = {
		name: _spec_to_jsonable(FUNCTION_REGISTRY[name])
		for name in sorted(FUNCTION_REGISTRY.keys())
	}

	# Ensure stable and readable output.
	payload = json.dumps(exported, ensure_ascii=False, indent=2, sort_keys=True)
	output_path.write_text(payload + "\n", encoding="utf-8")
	return output_path


def main() -> None:
	path = export_functions_json()
	print(str(path))


if __name__ == "__main__":
	main()

