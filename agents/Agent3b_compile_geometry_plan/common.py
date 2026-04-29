"""Agent3b shared registry, parameter, naming, and step-emitter helpers."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from agents.Agent3b_compile_geometry_plan.standard_part_compiler import inject_standard_parts_steps
from agents.common_utils import read_json as _read_json, write_json as _write_json
from validation.validate_shape_realization import validate_shape_realization_contract

def _load_function_registry(path: Path) -> Dict[str, Any]:
    return _read_json(path)


def _load_standard_part_bindings(run_dir: Path) -> set[str]:
    path = run_dir / "planning" / "standard_parts_resolved.json"
    if not path.exists():
        return set()
    data = _read_json(path)
    if not isinstance(data, Mapping):
        return set()
    parts = data.get("resolved")
    if not isinstance(parts, list):
        return set()
    bound: set[str] = set()
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        ids = part.get("bound_component_ids")
        if isinstance(ids, list):
            for cid in ids:
                if isinstance(cid, str) and cid:
                    bound.add(cid)
    return bound


def _is_standard_part_insert_only_strategy(strategy: Mapping[str, Any] | None) -> bool:
    if not isinstance(strategy, Mapping):
        return False
    import_strategy = str(strategy.get("import_strategy") or "").strip().lower()
    if import_strategy == "standard_part_library":
        return True
    execution_role = str(strategy.get("execution_role") or "").strip().lower()
    return execution_role == "standard_part_insert_only"


def _last_step_id(steps: List[Dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _require_function(allowed: Mapping[str, Any], name: str) -> None:
    if name not in allowed:
        raise ValueError(
            f"Required function '{name}' not found in registry. "
            "Agent3b must only use functions defined in functions/functions.json."
        )


class StepEmitter:
    def __init__(self, allowed_registry: Mapping[str, Any], sink: List[Dict[str, Any]] | None = None) -> None:
        self.allowed = allowed_registry
        self.steps: List[Dict[str, Any]] = sink if isinstance(sink, list) else []

    def emit(self, function_name: str, **step_fields: Any) -> Dict[str, Any]:
        _require_function(self.allowed, function_name)
        step = dict(step_fields)
        step["function"] = function_name
        self.steps.append(step)
        return step

    def emit_step(self, step: Mapping[str, Any]) -> Dict[str, Any]:
        fn = step.get("function") if isinstance(step, Mapping) else None
        if not isinstance(fn, str) or not fn.strip():
            raise ValueError("Compiled step missing function name")
        _require_function(self.allowed, fn)
        out = dict(step)
        self.steps.append(out)
        return out

    def emit_many(self, step_list: List[Dict[str, Any]]) -> None:
        for step in step_list:
            if isinstance(step, Mapping):
                self.emit_step(step)


def _validate_compiled_step_functions(allowed: Mapping[str, Any], steps: List[Dict[str, Any]]) -> None:
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        function_name = step.get("function")
        if not isinstance(function_name, str) or not function_name.strip():
            raise ValueError(f"Compiled step missing function: {step}")
        _require_function(allowed, function_name)


def _pick_param(execution_params: Mapping[str, Any], *keys: str) -> Optional[Any]:
    if not isinstance(execution_params, Mapping):
        return None
    for key in keys:
        if key in execution_params:
            return execution_params[key]
    return None


def _pick_param_with_key(
    execution_params: Mapping[str, Any],
    *keys: str,
) -> Tuple[str | None, Optional[Any]]:
    if not isinstance(execution_params, Mapping):
        return None, None
    for key in keys:
        if key in execution_params:
            return key, execution_params[key]
    return None, None


def _as_var(value: Any) -> Any:
    # Preserve numeric values; if string, pass through for ${var} templates.
    return value


def _resolve_param_value(
    value: Any,
    *,
    param_names: Tuple[str, ...],
    component_params: Mapping[str, Any] | None,
    strategy: Mapping[str, Any],
    prefer_placeholders: bool,
) -> Any:
    if prefer_placeholders and isinstance(value, str):
        resolved = None
    elif component_params is None:
        resolved = value
    elif isinstance(value, str) and value in component_params:
        resolved = component_params[value]
    elif isinstance(value, str):
        try:
            resolved = float(value)
        except Exception:
            resolved = None
    else:
        resolved = value

    transforms = strategy.get("parameter_transforms")
    if isinstance(transforms, list):
        for t in transforms:
            if not isinstance(t, Mapping):
                continue
            if t.get("parameter_name") not in param_names:
                continue
            action = t.get("required_transformation") or t.get("transformation")
            if action == "divide_by_2" and isinstance(resolved, (int, float)):
                resolved = resolved / 2
    return resolved


def _component_prefix(component_id: str) -> str:
    return component_id.replace("-", "_")


def _make_step_id(prefix: str, name: str, index: int | None = None) -> str:
    if index is None:
        return f"{prefix}_{name}"
    return f"{prefix}_{name}_{index}"


def _make_capture_var(prefix: str, name: str) -> str:
    return f"{prefix}_{name}"


def _placeholder(component_id: str, name: str) -> str:
    return f"${{{_component_prefix(component_id)}_{name}}}"


def _ensure_value(value: Any, *, component_id: str, name: str) -> Any:
    if value is None:
        return _placeholder(component_id, name)
    return _as_var(value)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def _instance_alias_map(token: str) -> Dict[str, str]:
    aliases: Dict[str, str] = {"full": token}
    m = re.match(r"^([A-Za-z]+_[0-9]+)_", token)
    if m:
        aliases["prefix"] = m.group(1)
    parts = [p for p in token.split("_") if p]
    if len(parts) >= 2:
        aliases["suffix"] = "_".join(parts[-2:])
    if len(parts) == 3 and parts[1].isdigit():
        aliases["reordered"] = f"{parts[0]}_{parts[2]}_{parts[1]}"
    return aliases


def _build_prototype_family_tokens(component_definition_by_id: Mapping[str, str]) -> Dict[str, List[str]]:
    families: Dict[str, set[str]] = {}
    for component_id, definition_id in component_definition_by_id.items():
        if not (isinstance(component_id, str) and component_id):
            continue
        prototype_id = definition_id if isinstance(definition_id, str) and definition_id else component_id
        families.setdefault(prototype_id, set()).update({prototype_id, component_id})
    return {prototype: sorted(tokens) for prototype, tokens in families.items()}


def _canonicalize_prototype_scoped_name(
    value: str,
    *,
    prototype_component_id: str,
    prototype_family_tokens: Mapping[str, List[str]],
) -> str:
    if not (isinstance(value, str) and value.strip()):
        return value
    family_tokens = prototype_family_tokens.get(prototype_component_id)
    if not isinstance(family_tokens, list) or len(family_tokens) < 2:
        return value

    out = value
    prototype_aliases = _instance_alias_map(prototype_component_id)
    replacements: List[Tuple[str, str]] = []
    for token in family_tokens:
        if token == prototype_component_id:
            continue
        token_aliases = _instance_alias_map(token)
        for alias_kind, alias_value in token_aliases.items():
            replacement = prototype_aliases.get(alias_kind)
            if alias_value and replacement and alias_value != replacement:
                replacements.append((alias_value, replacement))

    for alias_value, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        out = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(alias_value)}(?![A-Za-z0-9])",
            replacement,
            out,
        )
    return out


def _component_var_ref(component_id: str) -> str:
    return f"${{{_component_prefix(component_id)}_component_id}}"


def _feature_center() -> Dict[str, float]:
    return {"x": 0.0, "y": 0.0}
