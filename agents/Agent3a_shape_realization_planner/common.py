"""Agent3a basic helpers, realization classes, registry loading, and low-level feature utilities."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Mapping

from planning.pattern_solver import solve_circular_pattern
from agents.common_utils import read_json as _read_json, write_json as _write_json



REALIZATION_CLASS_NATIVE = "native_functional_part"
REALIZATION_CLASS_HOSTED_STANDARD = "hosted_standard_part"
REALIZATION_CLASS_KINEMATIC_IMPORTED = "kinematic_imported_part"

_HOSTED_STANDARD_COMPONENT_TYPES = {
    "bearing",
    "fastener",
    "fastener_set",
    "bolt",
    "screw",
    "nut",
    "washer",
}


def _infer_realization_class(
    *,
    component_type: str,
    modeling_strategy: Mapping[str, Any] | None,
    part_payload: Mapping[str, Any] | None,
) -> str:
    comp_type = str(component_type or "").strip().lower()
    if comp_type in _HOSTED_STANDARD_COMPONENT_TYPES:
        return REALIZATION_CLASS_HOSTED_STANDARD

    strategy = modeling_strategy if isinstance(modeling_strategy, Mapping) else {}
    import_strategy = str(strategy.get("import_strategy") or "").strip().lower()
    execution_role = str(strategy.get("execution_role") or "").strip().lower()

    if import_strategy in {"standard_part_library", "standard_part_import", "standard_library"}:
        return REALIZATION_CLASS_HOSTED_STANDARD

    if import_strategy in {"kinematic_imported", "kinematic_imported_part"}:
        return REALIZATION_CLASS_KINEMATIC_IMPORTED

    if execution_role in {"kinematic_imported_part", "kinematic_import"}:
        return REALIZATION_CLASS_KINEMATIC_IMPORTED

    if execution_role in {"standard_part_insert_only", "hosted_standard_part"}:
        return REALIZATION_CLASS_HOSTED_STANDARD

    part = part_payload if isinstance(part_payload, Mapping) else {}
    declared = str(part.get("realization_class") or "").strip()
    if declared in {
        REALIZATION_CLASS_NATIVE,
        REALIZATION_CLASS_HOSTED_STANDARD,
        REALIZATION_CLASS_KINEMATIC_IMPORTED,
    }:
        return declared

    return REALIZATION_CLASS_NATIVE


def _infer_side_hint_from_interface_name(interface_name: str) -> str:
    lower = interface_name.lower()
    if any(tok in lower for tok in ("_max", "top", "upper", "up")):
        return "MAX"
    if any(tok in lower for tok in ("_min", "bottom", "lower", "down", "base")):
        return "MIN"
    return "AUTO"


def _build_hole_anchor(*, interface_name: str) -> Dict[str, Any]:
    return {
        "face_interface_id": interface_name,
        "normal_hint": {"mode": "FACE_NORMAL"},
        "side_hint": _infer_side_hint_from_interface_name(interface_name),
    }


def _is_hole_like_feature_type(feature_type: str) -> bool:
    ft = feature_type.lower()
    if "hole" in ft:
        return True
    return ft in {
        "bolt_circle_pattern",
        "counterbore",
        "countersink",
        "shaft_bore",
        "bearing_seat",
        "standoff_bore",
        "press_fit_zone",
        "retainer_groove",
        "seal_groove",
        "split_clamp_bore",
        "nut_seat",
    }


def _repo_root() -> Path:
    # agents/Agent3a_shape_realization_planner/transform.py -> agents -> repo root
    return Path(__file__).resolve().parents[2]


def _load_function_registry() -> Dict[str, Any]:
    path = _repo_root() / "functions" / "functions.json"
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
