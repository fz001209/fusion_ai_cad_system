"""
Fusion-side postprocess module.

This keeps the orchestrator import stable and provides a no-op
implementation when export is disabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json
import re


def _collect_standard_parts(execution_context: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(execution_context, dict):
        return None

    pattern = re.compile(r"^stdpart_(.+)_(component_id|verify_status|replace_action|used_placeholder)$")
    parts: Dict[str, Dict[str, Any]] = {}

    for key, value in execution_context.items():
        match = pattern.match(key)
        if not match:
            continue
        part_id = match.group(1)
        field = match.group(2)
        entry = parts.setdefault(part_id, {"id": part_id})
        entry[field] = value

    if not parts:
        return None

    return {
        "count": len(parts),
        "parts": sorted(parts.values(), key=lambda p: p.get("id", "")),
    }


def run_all(
    run_dir: str | None,
    ui: Any,
    enable_export: bool = False,
    execution_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run postprocess steps (currently no-op).

    Args:
        run_dir: Execution run directory or None.
        ui: Fusion UI object (optional for logging).
        enable_export: Whether export is enabled (currently ignored).

    Returns:
        A dict of generated artifact paths (empty for now).
    """
    try:
        if run_dir:
            Path(run_dir).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    try:
        if hasattr(ui, "messageBox"):
            # Keep quiet by default; Fusion scripts can be noisy.
            pass
    except Exception:
        pass

    artifacts: Dict[str, Any] = {}
    if run_dir and execution_context:
        report = _collect_standard_parts(execution_context)
        if report:
            out_path = Path(run_dir) / "fusion_standard_parts_report.json"
            try:
                out_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                artifacts["standard_parts_report"] = str(out_path)
            except Exception:
                pass

    return artifacts
