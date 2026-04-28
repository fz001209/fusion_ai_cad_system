"""
Agent3b 闂?Geometry Strategy Compiler

Deterministic compiler that converts shape realization strategies into
geometry function steps without any new geometric inference.
"""

# This agent compiles strategies into executable geometry steps.
# It must not infer design intent.
# Execution parameters are resolved exclusively in Agent3b.

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


def _extract_feature_plan(shape: Mapping[str, Any]) -> Dict[str, Any]:
    parts = shape.get("parts")
    if isinstance(parts, list):
        placements: List[Dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            component_id = part.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue
            features = part.get("features")
            if not isinstance(features, list):
                continue
            for feature in features:
                if not isinstance(feature, Mapping):
                    continue
                feature_type = feature.get("feature_type")
                if not isinstance(feature_type, str) or not feature_type:
                    continue
                geometry_parameters = feature.get("geometry_parameters")
                params = dict(geometry_parameters) if isinstance(geometry_parameters, Mapping) else {}
                derived_change: Dict[str, Any] = {
                    "target_component_id": component_id,
                    "feature": feature_type,
                }
                if params:
                    derived_change["geometry_parameters"] = dict(params)
                derived_change.update(params)

                anchor = feature.get("anchor")
                if isinstance(anchor, Mapping):
                    derived_change["anchor"] = dict(anchor)

                placement: Dict[str, Any] = {
                    "connection_id": feature.get("feature_id") if isinstance(feature.get("feature_id"), str) else None,
                    "derived_changes": [derived_change],
                }

                interface_ref = feature.get("interface_ref")
                if isinstance(interface_ref, Mapping):
                    placement["location"] = {
                        "reference_frame": (
                            feature.get("reference_frame")
                            if isinstance(feature.get("reference_frame"), str)
                            else "component_local"
                        ),
                        "interface_ref": {
                            "name": interface_ref.get("name"),
                            "component_id": interface_ref.get("component_id"),
                        },
                    }

                instances = feature.get("instances")
                if isinstance(instances, list):
                    normalized_instances: List[Dict[str, Any]] = []
                    for inst in instances:
                        if not isinstance(inst, Mapping):
                            continue
                        pos = inst.get("position")
                        if not isinstance(pos, Mapping):
                            continue
                        normalized_instances.append(
                            {
                                "index": int(inst.get("index", len(normalized_instances))),
                                "position": {
                                    "x": float(pos.get("x", 0.0)),
                                    "y": float(pos.get("y", 0.0)),
                                    "z": float(pos.get("z", 0.0)),
                                },
                            }
                        )
                    if normalized_instances:
                        placement["instances"] = normalized_instances

                pattern = feature.get("pattern")
                if isinstance(pattern, Mapping):
                    placement["pattern"] = dict(pattern)

                pattern_axis = feature.get("pattern_axis")
                if isinstance(pattern_axis, str) and pattern_axis:
                    placement["pattern_axis"] = pattern_axis

                seed_point_mm = feature.get("seed_point_mm")
                if isinstance(seed_point_mm, Mapping):
                    placement["seed_point_mm"] = {
                        "x": float(seed_point_mm.get("x", 0.0)),
                        "y": float(seed_point_mm.get("y", 0.0)),
                        "z": float(seed_point_mm.get("z", 0.0)),
                    }

                feature_group_id = feature.get("feature_group_id")
                if isinstance(feature_group_id, str) and feature_group_id:
                    placement["feature_group_id"] = feature_group_id

                connection_mechanism = feature.get("connection_mechanism")
                if isinstance(connection_mechanism, str) and connection_mechanism:
                    placement["connection_mechanism"] = connection_mechanism

                geometric_semantics = feature.get("geometric_semantics")
                if isinstance(geometric_semantics, Mapping):
                    placement["geometric_semantics"] = dict(geometric_semantics)

                feature_flags = feature.get("flags")
                if isinstance(feature_flags, Mapping):
                    placement["flags"] = dict(feature_flags)

                feature_status = feature.get("status")
                if isinstance(feature_status, str) and feature_status:
                    placement["status"] = feature_status

                feature_requires_clarification = feature.get("requires_clarification")
                if isinstance(feature_requires_clarification, bool):
                    placement["requires_clarification"] = feature_requires_clarification

                placements.append(placement)

        return {"connection_placements": placements}

    feature_plan = shape.get("feature_plan")
    if not isinstance(feature_plan, Mapping):
        return {"connection_placements": []}
    placements_raw = feature_plan.get("connection_placements")
    placements: List[Dict[str, Any]] = []
    if isinstance(placements_raw, list):
        for item in placements_raw:
            if isinstance(item, Mapping):
                placements.append(dict(item))
    return {"connection_placements": [p for p in placements if isinstance(p, Mapping)]}


def _extract_realizations(shape: Mapping[str, Any]) -> List[Dict[str, Any]]:
    realizations = shape.get("component_realizations")
    if isinstance(realizations, list):
        return [dict(r) for r in realizations if isinstance(r, Mapping)]

    parts = shape.get("parts")
    if not isinstance(parts, list):
        raise ValueError("shape_realization.parts must be a list")

    normalized: List[Dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        component_id = part.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue

        strategy = part.get("modeling_strategy")
        if not isinstance(strategy, Mapping):
            strategy = {}
        strategy_dict = dict(strategy)

        primary_method = part.get("primary_method")
        if not isinstance(primary_method, str) or not primary_method:
            primary_method = strategy_dict.get("primary_method") if isinstance(strategy_dict.get("primary_method"), str) else None
        if isinstance(primary_method, str) and primary_method:
            strategy_dict["primary_method"] = primary_method.upper()
            if "construction_method" not in strategy_dict:
                strategy_dict["construction_method"] = primary_method.lower()

        normalized.append(
            {
                "component_id": component_id,
                "modeling_strategy": strategy_dict,
                "parameter_resolution": part.get("parameter_resolution", {}),
                "contract_pattern_used": part.get("contract_pattern_used"),
                "contract_pattern_source": part.get("contract_pattern_source"),
                "definition_id": part.get("definition_id"),
                "instance_id": part.get("instance_id"),
                "instanced_from": part.get("instanced_from"),
                "features": part.get("features", []),
            }
        )
    return normalized


def _normalize_definition_id(*, component_id: str, value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return component_id


_DEFINITION_SHARING_BLOCKED_ID_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^wheel_arm_\d+$"),
    re.compile(r"^wheel_\d+_(?:rim|tire|hub|axle|bearing(?:_\d+)?|spacer|fastener_set)$"),
)


def _is_definition_sharing_blocked_component(component_id: str) -> bool:
    if not isinstance(component_id, str) or not component_id:
        return False
    return any(pattern.match(component_id) for pattern in _DEFINITION_SHARING_BLOCKED_ID_PATTERNS)


def _extract_layout_positions(shape: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    layout_plan = shape.get("layout_plan")
    if isinstance(layout_plan, Mapping):
        layout_positions = layout_plan.get("layout_positions")
        if isinstance(layout_positions, Mapping):
            out: Dict[str, Dict[str, float]] = {}
            for cid, pos in layout_positions.items():
                if not isinstance(cid, str) or not isinstance(pos, Mapping):
                    continue
                out[cid] = {
                    "x": float(pos.get("x", 0.0)),
                    "y": float(pos.get("y", 0.0)),
                    "z": float(pos.get("z", 0.0)),
                }
            return out

    parts = shape.get("parts")
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(parts, list):
        return out
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        cid = part.get("component_id")
        if not isinstance(cid, str) or not cid:
            continue
        coordinate_frame = part.get("coordinate_frame")
        if not isinstance(coordinate_frame, Mapping):
            continue
        origin = coordinate_frame.get("origin_mm")
        if not isinstance(origin, Mapping):
            continue
        out[cid] = {
            "x": float(origin.get("x", 0.0)),
            "y": float(origin.get("y", 0.0)),
            "z": float(origin.get("z", 0.0)),
        }
    return out


def _extract_root_transforms(shape: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    transforms: Dict[str, Dict[str, Any]] = {}
    parts = shape.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            component_id = part.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue

            root_transform = part.get("root_transform_mm")
            if isinstance(root_transform, Mapping):
                translation_raw = root_transform.get("translation")
                rotation_raw = root_transform.get("rotation_rpy_deg")
                translation = translation_raw if isinstance(translation_raw, Mapping) else {}
                rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
                transforms[component_id] = {
                    "translation": {
                        "x": float(translation.get("x", 0.0)),
                        "y": float(translation.get("y", 0.0)),
                        "z": float(translation.get("z", 0.0)),
                    },
                    "rotation_rpy_deg": {
                        "roll": float(rotation.get("roll", 0.0)),
                        "pitch": float(rotation.get("pitch", 0.0)),
                        "yaw": float(rotation.get("yaw", 0.0)),
                    },
                }
                continue

            coordinate_frame_raw = part.get("coordinate_frame")
            coordinate_frame = coordinate_frame_raw if isinstance(coordinate_frame_raw, Mapping) else {}
            origin_raw = coordinate_frame.get("origin_mm")
            origin = origin_raw if isinstance(origin_raw, Mapping) else {}
            transforms[component_id] = {
                "translation": {
                    "x": float(origin.get("x", 0.0)),
                    "y": float(origin.get("y", 0.0)),
                    "z": float(origin.get("z", 0.0)),
                },
                "rotation_rpy_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            }

    placements = shape.get("initial_placements")
    if isinstance(placements, list):
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            component_id = placement.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue
            transform_raw = placement.get("transform")
            transform = transform_raw if isinstance(transform_raw, Mapping) else {}
            translation_raw = transform.get("translation")
            rotation_raw = transform.get("rotation_rpy_deg")
            translation = translation_raw if isinstance(translation_raw, Mapping) else {}
            rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
            transforms[component_id] = {
                "translation": {
                    "x": float(translation.get("x", 0.0)),
                    "y": float(translation.get("y", 0.0)),
                    "z": float(translation.get("z", 0.0)),
                },
                "rotation_rpy_deg": {
                    "roll": float(rotation.get("roll", 0.0)),
                    "pitch": float(rotation.get("pitch", 0.0)),
                    "yaw": float(rotation.get("yaw", 0.0)),
                },
            }

    return transforms


def _seed_create_transform(root_transform_mm: Mapping[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(root_transform_mm, Mapping):
        return None
    translation_raw = root_transform_mm.get("translation")
    rotation_raw = root_transform_mm.get("rotation_rpy_deg")
    translation = translation_raw if isinstance(translation_raw, Mapping) else {}
    rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
    return {
        "translation": {
            "x": float(translation.get("x", 0.0)),
            "y": float(translation.get("y", 0.0)),
            "z": float(translation.get("z", 0.0)),
        },
        "rotation_rpy_deg": {
            "roll": float(rotation.get("roll", 0.0)),
            "pitch": float(rotation.get("pitch", 0.0)),
            "yaw": float(rotation.get("yaw", 0.0)),
        },
    }


def _build_interface_name_index(interface_manifest: Mapping[str, Any]) -> Dict[str, set[str]]:
    index: Dict[str, set[str]] = {}
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return index
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        interfaces = comp.get("interfaces")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interfaces, list):
            continue
        names: set[str] = set()
        for iface in interfaces:
            if not isinstance(iface, Mapping):
                continue
            interface_name = iface.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                names.add(interface_name)
        index[component_id] = names
    return index


def _build_interface_recipe_index(
    interface_manifest: Mapping[str, Any],
) -> Dict[tuple[str, str], Dict[str, Any]]:
    index: Dict[tuple[str, str], Dict[str, Any]] = {}
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return index
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        interfaces = comp.get("interfaces")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interfaces, list):
            continue
        for iface in interfaces:
            if not isinstance(iface, Mapping):
                continue
            interface_name = iface.get("interface_name")
            recipe = iface.get("recipe")
            geometry_type = iface.get("geometry_type")
            usage = iface.get("usage")
            recipe_policy = iface.get("recipe_policy")
            if not isinstance(interface_name, str) or not interface_name:
                continue
            if not isinstance(recipe, Mapping):
                continue
            recipe_payload = dict(recipe)
            if not isinstance(recipe_payload.get("geometry_type"), str) and isinstance(geometry_type, str):
                recipe_payload["geometry_type"] = geometry_type
            if isinstance(usage, str) and usage:
                recipe_payload["__usage"] = usage
            if isinstance(recipe_policy, str) and recipe_policy:
                recipe_payload["__recipe_policy"] = recipe_policy
            index[(component_id, interface_name)] = recipe_payload
    return index


def _recipe_usage(face_recipe: Mapping[str, Any], explicit_usage: Any = None) -> str | None:
    if isinstance(explicit_usage, str) and explicit_usage.strip():
        return explicit_usage.strip()
    usage = face_recipe.get("__usage")
    if isinstance(usage, str) and usage.strip():
        return usage.strip()
    return None


def _sanitize_recipe_for_resolve(face_recipe: Mapping[str, Any], usage: str | None) -> Dict[str, Any]:
    recipe: Dict[str, Any] = {
        str(k): v
        for k, v in face_recipe.items()
        if isinstance(k, str) and not k.startswith("__")
    }
    if usage == "drill_anchor":
        selection = recipe.get("selection")
        if isinstance(selection, Mapping):
            selection_payload = dict(selection)
            selection_payload["area_min"] = 0.0
            recipe["selection"] = selection_payload
    return recipe


def _validate_feature_interface_refs(
    *,
    shape: Mapping[str, Any],
    interface_name_index: Mapping[str, set[str]],
) -> List[Dict[str, Any]]:
    violations: List[Dict[str, Any]] = []
    parts = shape.get("parts")
    if not isinstance(parts, list):
        return violations

    for part_idx, part in enumerate(parts):
        if not isinstance(part, Mapping):
            continue
        features = part.get("features")
        if not isinstance(features, list):
            continue
        component_id = part.get("component_id") if isinstance(part.get("component_id"), str) else f"<index:{part_idx}>"

        for feat_idx, feature in enumerate(features):
            if not isinstance(feature, Mapping):
                continue
            path_prefix = f"parts[{part_idx}].features[{feat_idx}]"
            feature_id = feature.get("feature_id") if isinstance(feature.get("feature_id"), str) else f"feature_{feat_idx}"
            interface_ref = feature.get("interface_ref")
            if not isinstance(interface_ref, Mapping):
                violations.append(
                    {
                        "component_id": component_id,
                        "path": f"{path_prefix}.interface_ref",
                        "rule": "feature_interface_ref_required",
                        "message": "Feature must define interface_ref for coordinate-frame ownership",
                        "details": {"feature_id": feature_id},
                    }
                )
                continue

            interface_name = interface_ref.get("name")
            interface_component = interface_ref.get("component_id")
            if not isinstance(interface_name, str) or not interface_name:
                violations.append(
                    {
                        "component_id": component_id,
                        "path": f"{path_prefix}.interface_ref.name",
                        "rule": "feature_interface_name_required",
                        "message": "Feature interface_ref.name must be non-empty",
                        "details": {"feature_id": feature_id},
                    }
                )
                continue
            if not isinstance(interface_component, str) or not interface_component:
                violations.append(
                    {
                        "component_id": component_id,
                        "path": f"{path_prefix}.interface_ref.component_id",
                        "rule": "feature_interface_component_required",
                        "message": "Feature interface_ref.component_id must be non-empty",
                        "details": {"feature_id": feature_id, "interface_name": interface_name},
                    }
                )
                continue

            known = interface_name_index.get(interface_component)
            feature_type = feature.get("feature_type") if isinstance(feature.get("feature_type"), str) else ""
            anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
            anchor_type = anchor.get("type") if isinstance(anchor.get("type"), str) else ""
            if (
                feature_type.lower() == "thread"
                and anchor_type == "cylindrical_face_by_radius"
                and interface_name == "cylindrical_outer"
            ):
                # Thread features may use synthetic cylindrical selectors instead of declared interface names.
                continue
            if not isinstance(known, set) or interface_name not in known:
                violations.append(
                    {
                        "component_id": component_id,
                        "path": f"{path_prefix}.interface_ref",
                        "rule": "feature_interface_not_in_manifest",
                        "message": "Feature interface_ref.name must exist in interface_manifest for referenced component",
                        "details": {
                            "feature_id": feature_id,
                            "interface_component_id": interface_component,
                            "interface_name": interface_name,
                        },
                    }
                )

    return violations


def _extract_component_interfaces_from_assembly_contract(
    contract: Mapping[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    components = contract.get("components")
    if not isinstance(components, list):
        return result
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        interfaces = comp.get("interfaces")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interfaces, list):
            continue
        valid_ifaces: List[Dict[str, Any]] = []
        for iface in interfaces:
            if isinstance(iface, Mapping):
                valid_ifaces.append(dict(iface))
        if valid_ifaces:
            result[component_id] = valid_ifaces
    return result


def _make_interface_manifest(
    *,
    geometry_plan: Mapping[str, Any],
    assembly_contract: Mapping[str, Any],
    modeling_semantics: Mapping[str, Any] | None = None,
    component_definition_by_id: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    steps = geometry_plan.get("steps")
    if not isinstance(steps, list):
        steps = []

    body_var_by_component: Dict[str, str] = {}
    occurrence_var_by_component: Dict[str, str] = {}
    component_var_by_component: Dict[str, str] = {}
    modeled_component_ids: set[str] = set()

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") == "CREATE_COMPONENT":
            inputs = step.get("inputs")
            if isinstance(inputs, Mapping):
                name = inputs.get("name")
                if isinstance(name, str) and name:
                    modeled_component_ids.add(name)
        capture = step.get("capture")
        if not isinstance(capture, Mapping):
            continue
        vars_map = capture.get("vars")
        if not isinstance(vars_map, Mapping):
            continue
        for var_name, source in vars_map.items():
            if not isinstance(var_name, str):
                continue
            if not isinstance(source, str):
                continue
            if var_name.endswith("_component_id") and source == "component_id":
                component_id = var_name[:-len("_component_id")]
                component_var_by_component[component_id] = var_name
            elif var_name.endswith("_occurrence_id") and source == "occurrence_id":
                component_id = var_name[:-len("_occurrence_id")]
                occurrence_var_by_component[component_id] = var_name
            elif var_name.endswith("_body_id") and source == "body_id":
                component_id = var_name[:-len("_body_id")]
                body_var_by_component[component_id] = var_name

    iface_by_component = _extract_component_interfaces_from_assembly_contract(assembly_contract)

    def _prototype_component_id(component_id: str) -> str:
        if not isinstance(component_definition_by_id, Mapping):
            return component_id
        return _normalize_definition_id(component_id=component_id, value=component_definition_by_id.get(component_id))

    def _existing_interface_names(entries: List[Dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            interface_name = entry.get('interface_name')
            if isinstance(interface_name, str) and interface_name:
                names.add(interface_name)
                continue
            interface_id = entry.get('interface_id')
            if isinstance(interface_id, str) and interface_id:
                names.add(interface_id)
        return names

    # Merge in additional interfaces referenced by modeling semantics closure.
    # This is critical because geometry_plan/shape_realization may reference interfaces
    # (e.g. "top_face") that are not part of the assembly contract surface set.
    if isinstance(modeling_semantics, Mapping):
        extra_manifest = modeling_semantics.get("interface_manifest")
        if isinstance(extra_manifest, Mapping):
            comps = extra_manifest.get("components")
            if isinstance(comps, list):
                for comp in comps:
                    if not isinstance(comp, Mapping):
                        continue
                    comp_id = comp.get("component_id")
                    if not isinstance(comp_id, str) or not comp_id:
                        continue
                    ifaces = comp.get("interfaces")
                    if not isinstance(ifaces, list):
                        continue

                    target_component_ids = {comp_id, _prototype_component_id(comp_id)}
                    for target_component_id in target_component_ids:
                        existing = iface_by_component.get(target_component_id, [])
                        existing_ids = _existing_interface_names(existing)

                        for iface in ifaces:
                            if not isinstance(iface, Mapping):
                                continue
                            interface_name = iface.get("interface_name")
                            if not isinstance(interface_name, str) or not interface_name:
                                continue
                            if interface_name in existing_ids:
                                continue
                            semantic_role = iface.get("semantic_role") if isinstance(iface.get("semantic_role"), str) else "mounting"
                            geometry_type = iface.get("geometry_type") if isinstance(iface.get("geometry_type"), str) else (
                                iface.get("geom_type") if isinstance(iface.get("geom_type"), str) else "planar"
                            )
                            existing.append(
                                {
                                    "interface_id": interface_name,
                                    "interface_name": interface_name,
                                    "semantic_role": semantic_role,
                                    "geometry_type": geometry_type,
                                }
                            )
                            existing_ids.add(interface_name)

                        if existing:
                            iface_by_component[target_component_id] = existing

    declaration_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def _iter_interface_declarations(modeling_payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        declarations: List[Dict[str, Any]] = []

        top_level = modeling_payload.get("interface_declarations")
        if isinstance(top_level, list):
            for item in top_level:
                if isinstance(item, Mapping):
                    declarations.append(dict(item))

        parts = modeling_payload.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, Mapping):
                    continue
                per_part = part.get("interface_declarations")
                if isinstance(per_part, list):
                    for item in per_part:
                        if isinstance(item, Mapping):
                            declarations.append(dict(item))

        return declarations

    if isinstance(modeling_semantics, Mapping):
        for item in _iter_interface_declarations(modeling_semantics):
            comp_id = item.get("component_id")
            iface_name = item.get("interface_name")
            if isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name:
                declaration_map[(comp_id, iface_name)] = dict(item)
                prototype_component_id = _prototype_component_id(comp_id)
                if prototype_component_id != comp_id:
                    prototype_item = dict(item)
                    prototype_item["component_id"] = prototype_component_id
                    declaration_map[(prototype_component_id, iface_name)] = prototype_item

    for (component_id, interface_name), decl in declaration_map.items():
        existing = iface_by_component.get(component_id, [])
        existing_ids = _existing_interface_names(existing)
        if interface_name in existing_ids:
            continue
        semantic_role = decl.get("semantic_role") if isinstance(decl.get("semantic_role"), str) else "mounting"
        geometry_type = decl.get("geometry_type") if isinstance(decl.get("geometry_type"), str) else (
            decl.get("geom_type") if isinstance(decl.get("geom_type"), str) else None
        )
        recipe = decl.get("recipe") if isinstance(decl.get("recipe"), Mapping) else None
        recipe_geometry = recipe.get("geometry_type") if isinstance(recipe, Mapping) and isinstance(recipe.get("geometry_type"), str) else None
        existing.append(
            {
                "interface_id": interface_name,
                "interface_name": interface_name,
                "semantic_role": semantic_role,
                "geometry_type": geometry_type or recipe_geometry or "planar",
            }
        )
        iface_by_component[component_id] = existing

    def _fallback_recipe(geometry_type: str) -> Dict[str, Any]:
        if geometry_type == "axis":
            return {
                "version": "1.0",
                "geometry_type": "axis",
                "selection": [
                    {"predicate": "cylindrical"},
                    {"predicate": "axis_parallel", "axis": "Z", "tolerance_deg": 12.0},
                ],
                "deterministic_order": ["radius_proximity", "distance_to_origin"],
            }
        return {
            "version": "1.0",
            "geometry_type": "planar",
            "selection": [
                {"predicate": "planar"},
                {"predicate": "max_area"},
            ],
            "deterministic_order": ["rule_priority", "distance_to_origin"],
        }

    components: List[Dict[str, Any]] = []
    for component_id, iface_defs in iface_by_component.items():
        cid_prefix = _component_prefix(component_id)
        # Include ALL contract components (including deferred standard parts).
        # If a component is not modeled in geometry_plan, its vars will be produced later
        # (e.g., by standard-part injection). Use the stable naming convention as default.
        comp_var = component_var_by_component.get(cid_prefix) or f"{cid_prefix}_component_id"
        occ_var = occurrence_var_by_component.get(cid_prefix) or f"{cid_prefix}_occurrence_id"
        body_var = body_var_by_component.get(cid_prefix) or f"{cid_prefix}_body_id"

        interface_records: List[Dict[str, Any]] = []
        for idx, iface in enumerate(iface_defs, start=1):
            iface_id_raw = iface.get("interface_id")
            interface_id = iface_id_raw if isinstance(iface_id_raw, str) and iface_id_raw else f"iface_{idx}"
            semantic_role = iface.get("semantic_role") if isinstance(iface.get("semantic_role"), str) else "mounting"
            geometry_type_raw = iface.get("geometry_type")
            geometry_type = geometry_type_raw if isinstance(geometry_type_raw, str) and geometry_type_raw else "planar"
            decl = declaration_map.get((component_id, interface_id))
            recipe = None
            if isinstance(decl, Mapping):
                recipe_obj = decl.get("recipe")
                if isinstance(recipe_obj, Mapping):
                    recipe = dict(recipe_obj)

            feature_tag = f"{semantic_role}_interface"
            if semantic_role == "rotation":
                feature_tag = "shaft_axis"
            elif semantic_role in {"mounting", "fixation"}:
                feature_tag = "shoulder_face"
            elif semantic_role == "support":
                feature_tag = "bearing_seat"

            if geometry_type == "axis":
                iface_type = "datum_axis"
                geom_ref = {"kind": "axis", "source": "deferred", "resolver": "CREATE_CONSTRUCTION_AXIS_BY_EDGE"}
            elif geometry_type in {"cylindrical", "cyl_hole", "cyl_shaft"}:
                iface_type = "cyl_shaft"
                geom_ref = {"kind": "face", "source": "deferred", "resolver": "SELECT_CYLINDRICAL_FACE"}
            else:
                iface_type = "planar_mate"
                geom_ref = {"kind": "face", "source": "deferred", "resolver": "SELECT_LARGEST_PLANAR_FACE"}

            native_ref = {
                "component_id": None,
                "body_id": None,
                "entity_kind": geom_ref.get("kind"),
                "entity_id": None,
            }
            occurrence_ref = {
                "occurrence_id": None,
                "entity_kind": geom_ref.get("kind"),
                "entity_id": None,
            }

            interface_records.append(
                {
                    "interface_name": interface_id,
                    "interface_id": f"{component_id}:{interface_id}:{iface_type}",
                    "source_interface_id": interface_id,
                    "semantic_role": semantic_role,
                    "type": iface_type,
                    "feature_tag": feature_tag,
                    "recipe": recipe if isinstance(recipe, dict) else _fallback_recipe(geometry_type),
                    "geom_ref": geom_ref,
                    "frame": {
                        "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
                        "z_axis": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "x_axis": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "source": "deferred",
                    },
                    "dims": {"source": "deferred"},
                    "resolution": {
                        "status": "deferred",
                        "resolved_token": {
                            "token_id": None,
                            "entity_kind": geom_ref.get("kind"),
                            "entity_id": None,
                            "geometry_summary": None,
                        },
                        "native_ref": native_ref,
                        "occurrence_ref": occurrence_ref,
                        "reason": "No execution trace/context available at compile time",
                    },
                }
            )

        components.append(
            {
                "component_id": component_id,
                "execution_refs": {
                    "component_var": comp_var,
                    "occurrence_var": occ_var,
                    "body_var": body_var,
                    "resolved": {
                        "component_id": None,
                        "occurrence_id": None,
                        "body_id": None,
                    },
                },
                "interfaces": interface_records,
            }
        )

    return {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "compile_geometry_plan_3b",
        },
        "components": components,
    }


def _enrich_manifest_with_execution_context(
    *,
    run_dir: Path,
    manifest: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolve component/body/occurrence refs from execution/context.json when available."""
    execution_context_path = run_dir / "execution" / "context.json"
    resolved_interfaces_path = run_dir / "execution" / "resolved_interfaces.json"

    resolved_interface_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if resolved_interfaces_path.exists():
        payload = _read_json(resolved_interfaces_path)
        if isinstance(payload, Mapping):
            rows = payload.get("interfaces")
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    component_id = row.get("component_id")
                    interface_name = row.get("interface_name")
                    if isinstance(component_id, str) and component_id and isinstance(interface_name, str) and interface_name:
                        resolved_interface_map[(component_id, interface_name)] = dict(row)
    if not execution_context_path.exists():
        return manifest, {
            "status": "deferred",
            "reason": "execution/context.json not found",
            "resolved_components": 0,
        }

    payload = _read_json(execution_context_path)
    if not isinstance(payload, Mapping):
        return manifest, {
            "status": "deferred",
            "reason": "execution/context.json invalid",
            "resolved_components": 0,
        }

    components = manifest.get("components")
    if not isinstance(components, list):
        return manifest, {
            "status": "deferred",
            "reason": "manifest.components missing",
            "resolved_components": 0,
        }

    resolved_components = 0
    for comp in components:
        if not isinstance(comp, dict):
            continue
        execution_refs = comp.get("execution_refs")
        if not isinstance(execution_refs, dict):
            continue

        comp_var = execution_refs.get("component_var")
        occ_var = execution_refs.get("occurrence_var")
        body_var = execution_refs.get("body_var")
        resolved = execution_refs.get("resolved")
        if not isinstance(resolved, dict):
            resolved = {"component_id": None, "occurrence_id": None, "body_id": None}
            execution_refs["resolved"] = resolved
        resolved_ref: Dict[str, Any] = resolved

        component_id_val = payload.get(comp_var) if isinstance(comp_var, str) else None
        occurrence_id_val = payload.get(occ_var) if isinstance(occ_var, str) else None
        body_id_val = payload.get(body_var) if isinstance(body_var, str) else None

        if isinstance(component_id_val, str):
            resolved_ref["component_id"] = component_id_val
        if isinstance(occurrence_id_val, str):
            resolved_ref["occurrence_id"] = occurrence_id_val
        if isinstance(body_id_val, str):
            resolved_ref["body_id"] = body_id_val

        if any(isinstance(v, str) and v for v in (component_id_val, occurrence_id_val, body_id_val)):
            resolved_components += 1

        interfaces = comp.get("interfaces")
        if not isinstance(interfaces, list):
            continue
        for iface in interfaces:
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("interface_name")
            resolution = iface.get("resolution")
            if not isinstance(resolution, dict):
                continue

            native_ref = resolution.get("native_ref")
            if isinstance(native_ref, dict):
                if isinstance(component_id_val, str):
                    native_ref["component_id"] = component_id_val
                if isinstance(body_id_val, str):
                    native_ref["body_id"] = body_id_val

            occ_ref = resolution.get("occurrence_ref")
            if isinstance(occ_ref, dict) and isinstance(occurrence_id_val, str):
                occ_ref["occurrence_id"] = occurrence_id_val

            if any(isinstance(v, str) and v for v in (component_id_val, occurrence_id_val, body_id_val)):
                resolution["status"] = "partially_resolved"
                resolution["reason"] = "Resolved component/body/occurrence from execution context"

            if isinstance(iface_name, str) and iface_name:
                comp_id_key = comp.get("component_id")
                resolved_row = (
                    resolved_interface_map.get((comp_id_key, iface_name))
                    if isinstance(comp_id_key, str) and comp_id_key
                    else None
                )
                if isinstance(resolved_row, Mapping):
                    resolved_token = resolution.get("resolved_token")
                    if not isinstance(resolved_token, dict):
                        resolved_token = {
                            "token_id": None,
                            "entity_kind": None,
                            "entity_id": None,
                            "geometry_summary": None,
                        }
                        resolution["resolved_token"] = resolved_token
                    resolved_token_ref: Dict[str, Any] = resolved_token

                    token_id = resolved_row.get("token_id")
                    entity_kind = resolved_row.get("entity_kind")
                    entity_id = resolved_row.get("entity_id")
                    geometry_summary = resolved_row.get("geometry_summary")

                    if isinstance(token_id, str):
                        resolved_token_ref["token_id"] = token_id
                    if isinstance(entity_kind, str):
                        resolved_token_ref["entity_kind"] = entity_kind
                    if isinstance(entity_id, str):
                        resolved_token_ref["entity_id"] = entity_id
                    if isinstance(geometry_summary, Mapping):
                        resolved_token_ref["geometry_summary"] = dict(geometry_summary)

                    resolution["status"] = "resolved"
                    resolution["reason"] = "Resolved via execution/resolved_interfaces.json"

    return manifest, {
        "status": "partially_resolved" if resolved_components > 0 else "deferred",
        "reason": "execution context + resolved interfaces parsed",
        "resolved_components": resolved_components,
        "resolved_interfaces": len(resolved_interface_map),
    }


def _circle_feature_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float | None,
    face_interface_id: str,
    face_recipe: Mapping[str, Any],
    side_hint: str | None,
    allowed: Mapping[str, Any],
    index: int,
    center_mm: Mapping[str, Any] | None = None,
    thread_spec: Mapping[str, Any] | None = None,
    face_geometry_type: str | None = None,
) -> List[Dict[str, Any]]:
    """Create a HOLE_SIMPLE feature anchored to a resolved interface."""
    _require_function(allowed, "ACTIVATE_COMPONENT")
    _require_function(allowed, "RESOLVE_INTERFACE")
    _require_function(allowed, "HOLE_SIMPLE")

    inferred_geometry_type = face_geometry_type
    if not isinstance(inferred_geometry_type, str) or not inferred_geometry_type:
        recipe_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None
        inferred_geometry_type = recipe_geometry_type
    planar_anchor = (
        isinstance(inferred_geometry_type, str)
        and inferred_geometry_type.lower() == "planar"
    )

    normalized_thread: Dict[str, Any] | None = None
    if isinstance(thread_spec, Mapping) and thread_spec:
        normalized_thread = _normalize_thread_spec(thread_spec)

    prefix = _safe_id(component_id)
    face_var = f"{prefix}_{feature_key}_face_{index}"
    face_kind_var = f"{prefix}_{feature_key}_face_kind_{index}"
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    hole_feature_var = f"{prefix}_{feature_key}_feature_{index}"
    hole_cyl_faces_var = f"{prefix}_{feature_key}_hole_cyl_faces_{index}"

    steps: List[Dict[str, Any]] = []
    
    # 濠电姷鏁告慨鐑姐€傛禒瀣；闁规儳顕粻楣冩煠閼圭増纭鹃柛姘愁潐缁绘盯鐓鐐茬ギ閻庢鍠曠划娆忕暦閸洖鐓涢柛鎰典簽閸樻垵鈹?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_activate", index),
            "function": "ACTIVATE_COMPONENT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
        }
    )
    
    # Resolve anchored face via interface recipe (deterministic, contract-driven)
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_resolve_face", index),
            "function": "RESOLVE_INTERFACE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "body_id": f"${{{stable_body_var}}}",
                "interface_name": face_interface_id,
                "recipe": dict(face_recipe),
            },
            "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_activate", index)],
            "metadata": {
                "component_id": component_id,
                "interface_name": face_interface_id,
                "expected_entity_kind": "face",
            },
        }
    )

    # Hole API does not require an explicit sketch center when resolving from a face.
    hole_inputs: Dict[str, Any] = {
        "component_id": _component_var_ref(component_id),
        "diameter_mm": float(diameter),
        "name": f"{component_id}_{feature_key}_{index}",
    }
    hole_inputs["face_id"] = f"${{{face_var}}}"
    if isinstance(center_mm, Mapping) and ("x" in center_mm or "y" in center_mm or "z" in center_mm):
        hole_inputs["center_mm"] = {
            "x": float(center_mm.get("x", 0.0)),
            "y": float(center_mm.get("y", 0.0)),
            "z": float(center_mm.get("z", 0.0)),
        }
    else:
        hole_inputs["center_mm"] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    if depth is None:
        # 闂備浇宕垫慨鐢稿礉閿曞倸鍨傞柟鎯版閻撴ɑ绻涢幋鐐茬劰闁?
        if side_hint == "MAX":
            hole_inputs["extent"] = "through_negative"
        elif side_hint == "MIN":
            hole_inputs["extent"] = "through_positive"
        else:
            hole_inputs["extent"] = "through_positive"
    else:
        # 闂傚倷绀佸﹢閬嶁€﹂崼婢濇椽濡舵径瀣患闂佽鍨奸悘鏃€鎯旈妸銉ь攨闂佺粯鍔曞Ο濠囧船濞差亝鈷戞慨鐟版搐婵″ジ鎮楀鐓庡⒋闁?        hole_inputs["extent"] = "distance"
        hole_inputs["depth_mm"] = float(depth)

    if normalized_thread is not None:
        hole_inputs["thread_spec"] = {
            "is_internal": bool(normalized_thread.get("is_internal", True)),
            "thread_type": normalized_thread["thread_type"],
            "thread_designation": normalized_thread["thread_designation"],
            "thread_class": normalized_thread["thread_class"],
        }
    
    hole_step_id = _make_step_id(prefix, f"{feature_key}_hole", index)
    hole_step: Dict[str, Any] = {
        "id": hole_step_id,
        "function": "HOLE_SIMPLE",
        "inputs": hole_inputs,
        "depends_on": [
            _make_step_id(
                prefix,
                f"{feature_key}_resolve_face",
                index,
            )
        ],
        "capture": {"vars": {hole_feature_var: "feature_id"}},
        "metadata": {
            "anchor": {
                "face_interface_id": face_interface_id,
                "side_hint": side_hint,
                "face_geometry_type": inferred_geometry_type,
            },
            "resolved_face_kind_var": face_kind_var,
        },
    }
    hole_step["capture"] = {
        "vars": {
            hole_feature_var: "feature_id",
            hole_cyl_faces_var: "cyl_face_ids",
        }
    }
    steps.append(hole_step)

    # Every hole modifies BRep topology.  Always emit refresh_body so
    # downstream re_resolve steps reference a current body_id.
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)
    steps.append(
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [hole_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_hole",
            },
        }
    )

    return steps


def _normalize_thread_spec(thread_spec: Mapping[str, Any]) -> Dict[str, Any]:
    thread_type = thread_spec.get("thread_type")
    thread_designation = thread_spec.get("thread_designation")
    thread_class = thread_spec.get("thread_class")

    if not (isinstance(thread_type, str) and thread_type.strip()):
        raise ValueError("thread_spec.thread_type must be a non-empty string")
    if not (isinstance(thread_designation, str) and thread_designation.strip()):
        raise ValueError("thread_spec.thread_designation must be a non-empty string")
    if not (isinstance(thread_class, str) and thread_class.strip()):
        raise ValueError("thread_spec.thread_class must be a non-empty string")

    normalized: Dict[str, Any] = {
        "thread_type": thread_type,
        "thread_designation": thread_designation,
        "thread_class": thread_class,
        "is_internal": bool(thread_spec.get("is_internal", True)),
        "is_modeled": bool(thread_spec.get("is_modeled", False)),
        "is_full_length": bool(thread_spec.get("is_full_length", True)),
    }

    if "thread_length_mm" in thread_spec:
        raw_len = thread_spec.get("thread_length_mm")
        if raw_len is not None and not isinstance(raw_len, (int, float)):
            raise ValueError("thread_spec.thread_length_mm must be a number (mm)")
        normalized["thread_length_mm"] = raw_len
    if "radius_tol_mm" in thread_spec:
        raw_tol = thread_spec.get("radius_tol_mm")
        if raw_tol is not None and not isinstance(raw_tol, (int, float)):
            raise ValueError("thread_spec.radius_tol_mm must be a number (mm)")
        normalized["radius_tol_mm"] = raw_tol

    return normalized


def _compile_hole_simple_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float | None,
    side_hint: str | None,
    face_interface_id: str,
    face_geometry_type: str | None,
    resolved_face_var: str,
    resolved_face_kind_var: str,
    allowed: Mapping[str, Any],
    index: int,
    center_mm: Mapping[str, Any] | None,
    depends_on: List[str],
    hole_mode: str,
    cbore_diameter_mm: float | None = None,
    cbore_depth_mm: float | None = None,
    csink_diameter_mm: float | None = None,
    csink_angle_rad: float | None = None,
    capture_feature_var: str | None = None,
    pattern: Mapping[str, Any] | None = None,
    pattern_axis: str | None = None,
    thread_spec: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    prefix = _safe_id(component_id)
    steps: List[Dict[str, Any]] = []

    if depth is None:
        if side_hint == "MAX":
            extent = "through_negative"
        elif side_hint == "MIN":
            extent = "through_positive"
        else:
            extent = "through_positive"
        depth_mm = None
    else:
        extent = "distance"
        depth_mm = float(depth)

    center_payload = {
        "x": float((center_mm or {}).get("x", 0.0)),
        "y": float((center_mm or {}).get("y", 0.0)),
        "z": float((center_mm or {}).get("z", 0.0)),
    }

    hole_step_id = _make_step_id(prefix, f"{feature_key}_hole", index)
    hole_inputs: Dict[str, Any] = {
        "component_id": _component_var_ref(component_id),
        "face_id": f"${{{resolved_face_var}}}",
        "center_mm": center_payload,
        "name": f"{component_id}_{feature_key}_{index}",
    }

    hole_function = "HOLE_SIMPLE"
    if hole_mode == "counterbore" and isinstance(cbore_diameter_mm, (int, float)) and isinstance(cbore_depth_mm, (int, float)):
        _require_function(allowed, "HOLE_COUNTERBORE")
        hole_function = "HOLE_COUNTERBORE"
        hole_inputs["hole_diameter_mm"] = float(diameter)
        hole_inputs["cbore_diameter_mm"] = float(cbore_diameter_mm)
        hole_inputs["cbore_depth_mm"] = float(cbore_depth_mm)
    elif hole_mode == "countersink" and isinstance(csink_diameter_mm, (int, float)) and isinstance(csink_angle_rad, (int, float)):
        _require_function(allowed, "HOLE_COUNTERSINK")
        hole_function = "HOLE_COUNTERSINK"
        hole_inputs["hole_diameter_mm"] = float(diameter)
        hole_inputs["csink_diameter_mm"] = float(csink_diameter_mm)
        hole_inputs["csink_angle_rad"] = float(csink_angle_rad)
    else:
        _require_function(allowed, "HOLE_SIMPLE")
        hole_inputs["diameter_mm"] = float(diameter)

    normalized_thread: Dict[str, Any] | None = None
    if isinstance(thread_spec, Mapping) and thread_spec:
        normalized_thread = _normalize_thread_spec(thread_spec)

    hole_inputs["extent"] = extent
    if depth_mm is not None:
        hole_inputs["depth_mm"] = depth_mm
    if normalized_thread is not None:
        hole_inputs["thread_spec"] = {
            "is_internal": bool(normalized_thread.get("is_internal", True)),
            "thread_type": normalized_thread["thread_type"],
            "thread_designation": normalized_thread["thread_designation"],
            "thread_class": normalized_thread["thread_class"],
        }

    hole_step: Dict[str, Any] = {
        "id": hole_step_id,
        "function": hole_function,
        "inputs": hole_inputs,
        "depends_on": list(depends_on),
        "metadata": {
            "anchor": {
                "face_interface_id": face_interface_id,
                "side_hint": side_hint,
                "face_geometry_type": face_geometry_type,
            },
            "resolved_face_kind_var": resolved_face_kind_var,
        },
    }
    effective_capture_feature_var = (
        capture_feature_var
        if isinstance(capture_feature_var, str) and capture_feature_var
        else f"{prefix}_{feature_key}_feature_{index}"
    )
    hole_step["capture"] = {"vars": {effective_capture_feature_var: "feature_id"}}

    steps.append(hole_step)
    latest_hole_step_id = hole_step_id

    if isinstance(pattern, Mapping):
        pattern_type = str(pattern.get("type") or "").lower()
        if pattern_type == "circular":
            quantity = pattern.get("count")
            if isinstance(quantity, int) and quantity > 1:
                expand_instances = hole_function == "HOLE_SIMPLE" and normalized_thread is not None
                cx = float(center_payload.get("x", 0.0))
                cy = float(center_payload.get("y", 0.0))
                cz = float(center_payload.get("z", 0.0))
                start_angle = pattern.get("start_angle_rad")
                radius_mm = pattern.get("radius_mm")
                total_angle = pattern.get("total_angle_rad")

                if not isinstance(start_angle, (int, float)):
                    start_angle = math.atan2(cy, cx)
                if not isinstance(radius_mm, (int, float)):
                    radius_mm = math.hypot(cx, cy)
                if not isinstance(total_angle, (int, float)):
                    total_angle = 2.0 * math.pi

                total_angle_f = float(total_angle)
                if abs(total_angle_f - 2.0 * math.pi) < 1e-6:
                    step_angle = total_angle_f / float(quantity)
                else:
                    step_angle = total_angle_f / float(max(quantity - 1, 1))

                if expand_instances and float(radius_mm) > 1e-9:
                    for inst_idx in range(1, int(quantity)):
                        angle_i = float(start_angle) + step_angle * float(inst_idx)
                        center_i = {
                            "x": float(radius_mm) * math.cos(angle_i),
                            "y": float(radius_mm) * math.sin(angle_i),
                            "z": cz,
                        }
                        hole_inputs_i = dict(hole_inputs)
                        hole_inputs_i["center_mm"] = center_i
                        hole_inputs_i["name"] = f"{component_id}_{feature_key}_{index}_{inst_idx}"
                        step_id_i = _make_step_id(prefix, f"{feature_key}_hole_i{inst_idx}", index)
                        steps.append(
                            {
                                "id": step_id_i,
                                "function": hole_function,
                                "inputs": hole_inputs_i,
                                "depends_on": [latest_hole_step_id],
                                "metadata": {
                                    "anchor": {
                                        "face_interface_id": face_interface_id,
                                        "side_hint": side_hint,
                                        "face_geometry_type": face_geometry_type,
                                    },
                                    "resolved_face_kind_var": resolved_face_kind_var,
                                    "pattern_expanded": "circular",
                                    "pattern_index": inst_idx,
                                },
                            }
                        )
                        latest_hole_step_id = step_id_i
                else:
                    _require_function(allowed, "CIRCULAR_PATTERN_FEATURES")
                    pattern_step_inputs: Dict[str, Any] = {
                        "component_id": _component_var_ref(component_id),
                        "feature_ids": [f"${{{effective_capture_feature_var}}}"],
                        "axis": {"face_id": f"${{{resolved_face_var}}}", "axis_hint": pattern_axis or "Z"},
                        "quantity": int(quantity),
                    }
                    pattern_step_inputs["total_angle_rad"] = total_angle_f
                    pattern_step_inputs["is_symmetric"] = False
                    pattern_step_id = _make_step_id(prefix, f"{feature_key}_pattern", index)
                    steps.append(
                        {
                            "id": pattern_step_id,
                            "function": "CIRCULAR_PATTERN_FEATURES",
                            "inputs": pattern_step_inputs,
                            "depends_on": [hole_step_id],
                        }
                    )
                    latest_hole_step_id = pattern_step_id
        elif pattern_type == "rectangular":
            quantity_one = pattern.get("count_x")
            distance_one_mm = pattern.get("spacing_x_mm")
            direction_one = pattern.get("direction_one")
            if (
                isinstance(quantity_one, int)
                and quantity_one > 1
                and isinstance(distance_one_mm, (int, float))
                and isinstance(direction_one, Mapping)
            ):
                _require_function(allowed, "RECTANGULAR_PATTERN_FEATURES")
                pattern_inputs: Dict[str, Any] = {
                    "component_id": _component_var_ref(component_id),
                    "feature_ids": [f"${{{effective_capture_feature_var}}}"],
                    "direction_one": dict(direction_one),
                    "quantity_one": int(quantity_one),
                    "distance_one_mm": float(distance_one_mm),
                    "pattern_distance_type": "spacing",
                }
                if isinstance(pattern.get("count_y"), int) and pattern.get("count_y") > 1:
                    direction_two = pattern.get("direction_two")
                    distance_two_mm = pattern.get("spacing_y_mm")
                    if isinstance(direction_two, Mapping) and isinstance(distance_two_mm, (int, float)):
                        pattern_inputs["direction_two"] = dict(direction_two)
                        pattern_inputs["quantity_two"] = int(pattern.get("count_y"))
                        pattern_inputs["distance_two_mm"] = float(distance_two_mm)
                steps.append(
                    {
                        "id": _make_step_id(prefix, f"{feature_key}_pattern", index),
                        "function": "RECTANGULAR_PATTERN_FEATURES",
                        "inputs": pattern_inputs,
                        "depends_on": [hole_step_id],
                    }
                )
                latest_hole_step_id = _make_step_id(prefix, f"{feature_key}_pattern", index)

    # Every hole modifies BRep topology.  Always emit refresh_body so
    # downstream re_resolve steps reference a current body_id, preventing
    # stale proxy issues in the Fusion API.
    _require_function(allowed, "GET_SINGLE_BODY_ID")
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)
    steps.append(
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [latest_hole_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_hole",
            },
        }
    )

    return steps


def _rectangle_feature_steps(
    *,
    component_id: str,
    feature_key: str,
    width: float,
    height: float,
    depth: float | None,
    allowed: Mapping[str, Any],
    index: int,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "ACTIVATE_COMPONENT")
    _require_function(allowed, "SELECT_LARGEST_PLANAR_FACE")
    _require_function(allowed, "CREATE_SKETCH_ON_FACE")
    _require_function(allowed, "SKETCH_RECTANGLE")

    if depth is None:
        _require_function(allowed, "EXTRUDE_THROUGH_ALL")
    else:
        _require_function(allowed, "EXTRUDE_CUT")

    prefix = _safe_id(component_id)
    sketch_id_var = f"{prefix}_{feature_key}_sketch_{index}"
    face_var = f"{prefix}_{feature_key}_face_{index}"
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")

    steps: List[Dict[str, Any]] = []
    
    # 濠电姷鏁告慨鐑姐€傛禒瀣；闁规儳顕粻楣冩煠閼圭増纭鹃柛姘愁潐缁绘盯鐓鐐茬ギ閻庢鍠曠划娆忕暦閸洖鐓涢柛鎰典簽閸樻垵鈹戦悙宸殶濠殿噣娼ч敃銏㈡喆閸曨収娲搁梺鍦劋濮婂綊宕楀鍕╀簻闁哄啫娲ら崥鍦磼閻樿京鐭欓柡灞剧☉椤繈顢楁担鐟伴棷闂備焦鐪归崹褰掆€﹂悜鐣屽祦婵炲棗娴氶崥瀣煕閺囥劌骞橀柍缁樻礋濮婃椽妫冮埡鍕槹闂佸憡鏌ㄧ粔褰掋€佸Δ鈧…銊╁川椤旂厧骞戞俊鐐€栧濠氬磻閹剧粯鍋╅柣顏冩姉ntext婵犵數鍋為崹鍫曞箹閳哄懎鍌ㄩ柤鎭掑劜濞呯娀鏌ｉ敐鍛拱闁?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_activate", index),
            "function": "ACTIVATE_COMPONENT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
        }
    )
    
    # 闂傚倸鍊风欢锟犲磻閸曨垁鍥箥椤旂懓浜炬慨妯稿劚婵倻鈧鍠氶弫濠氬春閳ь剚銇勯幒宥囶槮缂佸墎鍋熼幉姝岀疀閹绢垱鐏侀梺纭呮彧婵″洤鐣垫笟鈧弻鐔煎箚閺夊晝鎾翠繆濡炵厧濮傛慨濠傤煼瀹曞ジ顢曢敐鍥╃崸缂傚倷娴囨ご鎼佹偡閳哄懎钃熼柛娑卞弾濞尖晜銇勯幒鎴濃偓鎼佹偂閹达附鈷戦柛婵嗗椤忔挳鏌涢妸銉у煟濠碘€崇摠缁绘繈宕堕…鎴烆棃闂備線娼х换鍡涘焵椤掆偓绾绢厽绂掗幇鐗堢厵闁绘挸娴烽幗鐘崇箾閼碱剙鏋庢い顓炴处鐎佃偐鈧稒蓱濞?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_select_face", index),
            "function": "SELECT_LARGEST_PLANAR_FACE",
            "inputs": {
                "body_id": f"${{{stable_body_var}}}",
            },
            "capture": {"vars": {face_var: "face_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_activate", index)],
        }
    )
    
    # 闂傚倷绶氬鑽ゆ嫻閻旂厧绀夐柟杈剧畱閻掑灚銇勯幒鍡椾壕濡炪倧瀵岄崹鍫曞箖閻愵兙鍋呴柛鎰ㄦ櫅閸擃參姊洪崨濠冨闁搞劌宕々濂稿Ω閵夈垺顫嶉梺鐟板⒔椤掓彃顔忛妷鈺傜厱闁靛鍎遍懜瑙勩亜閺囩喓鎳呴柤楦块哺娣囧﹪宕￠幁顡﹉
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_sketch", index),
            "function": "CREATE_SKETCH_ON_FACE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "face_id": f"${{{face_var}}}",
                "name": f"{component_id}_{feature_key}_{index}_sketch",
            },
            "capture": {"vars": {sketch_id_var: "sketch_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_select_face", index)],
        }
    )
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_profile", index),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{sketch_id_var}}}",
                "center": _feature_center(),
                "width": float(width),
                "height": float(height),
            },
            "capture": {"vars": {f"{prefix}_{feature_key}_profile_{index}": "profile_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_sketch", index)],
        }
    )
    if depth is None:
        steps.append(
            {
                "id": _make_step_id(prefix, f"{feature_key}_cut", index),
                "function": "EXTRUDE_THROUGH_ALL",
                "inputs": {
                    "component_id": _component_var_ref(component_id),
                    "profile_id": f"${{{prefix}_{feature_key}_profile_{index}}}",
                    "operation": "cut",
                    "body_id": f"${{{stable_body_var}}}",
                },
                "depends_on": [_make_step_id(prefix, f"{feature_key}_profile", index)],
            }
        )
    else:
        steps.append(
            {
                "id": _make_step_id(prefix, f"{feature_key}_cut", index),
                "function": "EXTRUDE_CUT",
                "inputs": {
                    "component_id": _component_var_ref(component_id),
                    "profile_id": f"${{{prefix}_{feature_key}_profile_{index}}}",
                    "distance": float(depth),
                    "body_id": f"${{{stable_body_var}}}",
                },
                "depends_on": [_make_step_id(prefix, f"{feature_key}_profile", index)],
            }
        )

    return steps


def _collect_fastener_intents(feature_plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    placements = feature_plan.get("connection_placements")
    if not isinstance(placements, list):
        return []

    suppressed_mechanisms = {
        "bonded_tread",
        "bonded_mount",
        "press_fit",
        "companion_rotation_relation",
        "semantic_conflict_direct_rotor_mount",
    }

    intents: List[Dict[str, Any]] = []
    for pidx, placement in enumerate(placements):
        if not isinstance(placement, Mapping):
            continue
        placement_flags = placement.get("flags") if isinstance(placement.get("flags"), Mapping) else {}
        mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
        if bool(placement_flags.get("suppress_hole_generation")) or mechanism_name in suppressed_mechanisms:
            continue
        fastener_spec = placement.get("fastener_spec")
        if not isinstance(fastener_spec, Mapping) or not fastener_spec:
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}

        hole_anchors: List[Dict[str, Any]] = []
        target_ids: set[str] = set()
        derived = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        for cidx, change in enumerate(derived):
            if not isinstance(change, Mapping):
                continue
            feature = str(change.get("feature") or "").lower()
            if feature not in {"hole", "bolt_circle_pattern", "counterbore", "countersink", "clearance_hole", "threaded_hole"}:
                continue
            target_component_id = change.get("target_component_id")
            if isinstance(target_component_id, str) and target_component_id:
                target_ids.add(target_component_id)

            hole_anchors.append(
                {
                    "hole_ref": f"fastener_hole_{pidx}_{cidx}",
                    "target_component_id": target_component_id,
                    "interface_name": interface_ref.get("name"),
                    "interface_component_id": interface_ref.get("component_id"),
                    "anchor": dict(change.get("anchor")) if isinstance(change.get("anchor"), Mapping) else None,
                    "diameter_mm": (
                        float(change.get("diameter"))
                        if isinstance(change.get("diameter"), (int, float))
                        else (
                            float(change.get("hole_diameter"))
                            if isinstance(change.get("hole_diameter"), (int, float))
                            else (
                                float(change.get("bore_diameter"))
                                if isinstance(change.get("bore_diameter"), (int, float))
                                else None
                            )
                        )
                    ),
                    "feature": feature,
                }
            )

        if not hole_anchors:
            continue

        intents.append(
            {
                "intent_id": f"fastener_intent_{pidx}",
                "connection_id": placement.get("connection_id"),
                "fastener_spec": dict(fastener_spec),
                "target_component_ids": sorted(target_ids),
                "hole_anchors": hole_anchors,
                "rationale": "Standard part insertion and assembly sequencing are deferred to Agent5",
            }
        )

    return intents


def _re_resolve_group_face(
    *,
    group_ctx: Dict[str, Any],
    target_id: str,
    feature_group_id: str,
    step_index: int,
    steps: List[Dict[str, Any]],
    face_interface_id: str,
    usage: str | None,
) -> Tuple[str, str, List[str], int]:
    """Return *(face_var, face_kind_var, depends, step_index)* for the next
    hole in a grouped-hole sequence.

    When the group already contains at least one hole (`hole_count > 0`) a
    fresh ``RESOLVE_INTERFACE`` step is appended to *steps* so that the face
    reference is re-resolved after the geometry was modified by the previous
    hole.  Otherwise the original face variables from *group_ctx* are reused
    unchanged.
    """
    face_var = str(group_ctx["face_var"])
    face_kind_var = str(group_ctx["face_kind_var"])
    depends: List[str] = [str(group_ctx["resolve_step_id"])]

    if group_ctx["hole_count"] > 0:
        _grp_prefix = _safe_id(target_id)
        _grp_token = _safe_id(feature_group_id)
        _re_idx = step_index
        step_index += 1
        _re_resolve_id = _make_step_id(_grp_prefix, f"{_grp_token}_re_resolve_face", _re_idx)
        face_var = f"{_grp_prefix}_{_grp_token}_face_{_re_idx}"
        face_kind_var = f"{_grp_prefix}_{_grp_token}_face_kind_{_re_idx}"
        _stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")

        steps.append(
            {
                "id": _re_resolve_id,
                "function": "RESOLVE_INTERFACE",
                "inputs": {
                    "component_id": _component_var_ref(target_id),
                    "body_id": f"${{{_stable_body_var}}}",
                    "interface_name": face_interface_id,
                    "recipe": dict(group_ctx["_resolved_recipe"]),
                },
                "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
                "depends_on": [str(group_ctx["last_step_id"])],
                "metadata": {
                    "component_id": target_id,
                    "interface_name": face_interface_id,
                    "expected_entity_kind": "face",
                    "usage": usage,
                    "reason": "re_resolve_face_after_prior_hole",
                },
            }
        )
        depends = [_re_resolve_id]

    return face_var, face_kind_var, depends, step_index


def _infer_side_entry_slot_capture_mount(
    *,
    placement: Mapping[str, Any],
    change: Mapping[str, Any],
    target_strategy: Mapping[str, Any],
) -> bool:
    mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
    placement_geo = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
    support_topology = str(placement_geo.get("support_topology") or "").strip().lower()
    if mechanism_name == "axial_face_bolted_mount" and support_topology == "hub_radial_slot_mount":
        return True

    location_map = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
    location_interface_ref = location_map.get("interface_ref") if isinstance(location_map.get("interface_ref"), Mapping) else {}
    change_interface_ref = change.get("interface_ref") if isinstance(change.get("interface_ref"), Mapping) else {}
    anchor_map = change.get("anchor") if isinstance(change.get("anchor"), Mapping) else {}

    interface_names: set[str] = set()
    for raw_name in (
        location_interface_ref.get("name"),
        change_interface_ref.get("name"),
        anchor_map.get("face_interface_id"),
    ):
        if isinstance(raw_name, str) and raw_name.strip():
            interface_names.add(raw_name.strip().lower())

    if any(name.startswith("slot_mount_face") for name in interface_names):
        return True

    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    target_profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
    hub_slot_insert_depth = strategy_params.get("hub_slot_insert_depth")
    has_slot_insert_depth = isinstance(hub_slot_insert_depth, (int, float)) and float(hub_slot_insert_depth) > 0.0

    feature_context_tokens: set[str] = set()
    for raw_token in (
        placement.get("feature_group_id"),
        placement.get("connection_id"),
        change.get("feature_group_id"),
    ):
        if isinstance(raw_token, str) and raw_token.strip():
            feature_context_tokens.add(raw_token.strip().lower())

    if (
        "proximal_insert_face" in interface_names
        and target_profile_type == "yoke_profile"
        and (
            has_slot_insert_depth
            or any(token.startswith("central_hub_to_arm_") for token in feature_context_tokens)
        )
    ):
        return True

    return False



def _integrated_axisymmetric_bearing_seat_params(target_strategy: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    seat_diameter = strategy_params.get("opposed_bearing_seat_diameter")
    seat_depth = strategy_params.get("opposed_bearing_seat_depth")
    opposed_width = strategy_params.get("opposed_bearing_width")
    thickness = strategy_params.get("thickness")
    if not isinstance(seat_diameter, (int, float)) or float(seat_diameter) <= 0.0:
        return None
    if not isinstance(seat_depth, (int, float)) or float(seat_depth) <= 0.0:
        return None
    if not isinstance(opposed_width, (int, float)) or float(opposed_width) <= 0.0:
        return None
    if not isinstance(thickness, (int, float)) or float(thickness) <= 0.0:
        return None
    return {
        "seat_diameter": float(seat_diameter),
        "seat_depth": float(seat_depth),
        "opposed_width": float(opposed_width),
        "thickness": float(thickness),
    }


def _should_compile_axisymmetric_bearing_seat_cut(
    *,
    feature_key: str,
    target_strategy: Mapping[str, Any],
    face_interface_id: str | None,
    diameter: Any,
    depth: Any,
    centered: bool = False,
) -> bool:
    if feature_key != "bearing_seat":
        return False
    if _integrated_axisymmetric_bearing_seat_params(target_strategy) is not None:
        return False
    if not centered and (not isinstance(face_interface_id, str) or face_interface_id.lower() not in {"axial_end_face_min", "axial_end_face_max"}):
        return False
    if not isinstance(diameter, (int, float)) or float(diameter) <= 0.0:
        return False
    if not isinstance(depth, (int, float)) or float(depth) <= 0.0:
        return False

    primitive_class = str(target_strategy.get("primitive_class") or "").strip().lower()
    profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
    construction_method = str(target_strategy.get("construction_method") or target_strategy.get("primary_method") or "").strip().lower()
    if construction_method == "revolve":
        return True
    if profile_type == "half_profile" and _is_axisymmetric(primitive_class, profile_type):
        return True
    return False


def _compile_axisymmetric_bearing_seat_cut_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float,
    side_hint: str,
    face_interface_id: str,
    allowed: Mapping[str, Any],
    index: int,
    depends_on: List[str],
    target_strategy: Mapping[str, Any],
    centered: bool = False,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "CREATE_OFFSET_CONSTRUCTION_PLANE")
    _require_function(allowed, "CREATE_SKETCH_ON_PLANE")
    _require_function(allowed, "SKETCH_CIRCLE")
    _require_function(allowed, "EXTRUDE_CUT")
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    thickness = _pick_param(strategy_params, "thickness", "width", "height", "length")
    thickness = _ensure_value(thickness, component_id=component_id, name="thickness")

    normalized_side = side_hint.strip().upper()
    plane_offset = 0.5 * float(thickness)
    cut_direction = "negative"
    seat_compile_mode = "axisymmetric_blind_cut"
    if centered:
        normalized_side = "CENTER"
        plane_offset = -0.5 * float(depth)
        cut_direction = "positive"
        seat_compile_mode = "axisymmetric_centered_cut"
    elif normalized_side == "MIN":
        plane_offset = -plane_offset
        cut_direction = "positive"

    prefix = _safe_id(component_id)
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    plane_var = f"{prefix}_{feature_key}_plane_{index}"
    sketch_var = f"{prefix}_{feature_key}_sketch_{index}"
    profile_var = f"{prefix}_{feature_key}_profile_{index}"
    feature_var = f"{prefix}_{feature_key}_feature_{index}"

    create_plane_step_id = _make_step_id(prefix, f"{feature_key}_plane", index)
    create_sketch_step_id = _make_step_id(prefix, f"{feature_key}_sketch", index)
    create_profile_step_id = _make_step_id(prefix, f"{feature_key}_profile", index)
    cut_step_id = _make_step_id(prefix, f"{feature_key}_cut", index)
    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)

    return [
        {
            "id": create_plane_step_id,
            "function": "CREATE_OFFSET_CONSTRUCTION_PLANE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "base_plane": {"type": "XY"},
                "offset_mm": float(plane_offset),
                "name": f"{component_id}_{feature_key}_{index}_plane",
            },
            "capture": {"vars": {plane_var: "plane_id"}},
            "depends_on": list(depends_on),
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "seat_compile_mode": seat_compile_mode,
                "anchor_face_interface_id": face_interface_id,
                "side_hint": normalized_side,
            },
        },
        {
            "id": create_sketch_step_id,
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "plane": {"type": "OFFSET", "plane_id": f"${{{plane_var}}}"},
                "name": f"{component_id}_{feature_key}_{index}_sketch",
            },
            "capture": {"vars": {sketch_var: "sketch_id"}},
            "depends_on": [create_plane_step_id],
        },
        {
            "id": create_profile_step_id,
            "function": "SKETCH_CIRCLE",
            "inputs": {
                "sketch_id": f"${{{sketch_var}}}",
                "center": {"x": 0.0, "y": 0.0},
                "radius": float(diameter) * 0.5,
            },
            "capture": {"vars": {profile_var: "profile_id"}},
            "depends_on": [create_sketch_step_id],
        },
        {
            "id": cut_step_id,
            "function": "EXTRUDE_CUT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "profile_id": f"${{{profile_var}}}",
                "distance": float(depth),
                "direction": cut_direction,
                "body_id": f"${{{stable_body_var}}}",
            },
            "capture": {"vars": {feature_var: "feature_id"}},
            "depends_on": [create_profile_step_id],
            "metadata": {
                "anchor": {
                    "face_interface_id": face_interface_id,
                    "side_hint": normalized_side,
                    "face_geometry_type": "planar",
                },
                "seat_compile_mode": seat_compile_mode,
            },
        },
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [cut_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_axisymmetric_bearing_seat_cut",
            },
        },
    ]


def _compile_feature_patch(
    *,
    feature_plan: Mapping[str, Any],
    allowed: Mapping[str, Any],
    skip_components: set[str],
    interface_recipe_index: Mapping[tuple[str, str], Mapping[str, Any]],
    component_definition_by_id: Mapping[str, str],
    component_strategy_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    steps: List[Dict[str, Any]] = []
    warnings: List[str] = []
    component_strategy_by_id = component_strategy_by_id if isinstance(component_strategy_by_id, Mapping) else {}

    # Deduplicate identical hole operations. Fusion will error if we try to cut
    # the same hole at the same location multiple times.
    seen_hole_signatures: set[tuple] = set()
    seen_group_seed_hole_signatures: set[tuple] = set()
    seen_thread_signatures: set[tuple] = set()
    seen_hole_intents: Dict[tuple[str, str], Dict[str, Any]] = {}
    grouped_hole_context: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    prototype_family_tokens = _build_prototype_family_tokens(component_definition_by_id)

    placements = feature_plan.get("connection_placements")
    if not isinstance(placements, list):
        return steps, warnings

    step_index = 0
    hole_like_features = {
        "hole",
        "shaft_bore",
        "bearing_seat",
        "alignment_pin_hole",
        "standoff_bore",
        "press_fit_zone",
        "retainer_groove",
        "seal_groove",
        "split_clamp_bore",
        "nut_seat",
        "bolt_circle_pattern",
        "counterbore",
        "countersink",
        "clearance_hole",
        "threaded_hole",
    }
    suppressed_mechanisms = {
        "bonded_tread",
        "bonded_mount",
        "press_fit",
        "companion_rotation_relation",
        "semantic_conflict_direct_rotor_mount",
    }
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        instances = placement.get("instances") if isinstance(placement.get("instances"), list) else None
        derived = placement.get("derived_changes")
        placement_flags = placement.get("flags") if isinstance(placement.get("flags"), Mapping) else {}
        suppress_hole_generation = bool(placement_flags.get("suppress_hole_generation"))
        mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
        placement_geo = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        support_topology = str(placement_geo.get("support_topology") or "").strip().lower()
        if isinstance(derived, list):
            for change in derived:
                if not isinstance(change, Mapping):
                    continue
                target_id = change.get("target_component_id")
                if not isinstance(target_id, str) or not target_id:
                    warnings.append("derived_change missing target_component_id")
                    continue
                source_target_id = target_id
                target_id = component_definition_by_id.get(source_target_id, source_target_id)
                if target_id in skip_components:
                    warnings.append(f"derived_change skipped for standard part {target_id}")
                    continue
                feature = change.get("feature")
                if not isinstance(feature, str):
                    warnings.append(f"derived_change missing feature for {target_id}")
                    continue

                feature_key = feature.lower()
                target_strategy = component_strategy_by_id.get(target_id) if isinstance(component_strategy_by_id.get(target_id), Mapping) else {}
                if _is_standard_part_insert_only_strategy(target_strategy):
                    warnings.append(f"derived_change skipped for insert-only standard part {target_id}")
                    continue
                target_profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
                slot_capture_mount = _infer_side_entry_slot_capture_mount(
                    placement=placement,
                    change=change,
                    target_strategy=target_strategy,
                )

                if (suppress_hole_generation or mechanism_name in suppressed_mechanisms) and feature_key in hole_like_features:
                    warnings.append(f"{feature_key} suppressed by semantic contract for {target_id}")
                    continue
                location_ref = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                interface_ref = location_ref.get("interface_ref") if isinstance(location_ref.get("interface_ref"), Mapping) else {}
                interface_name = str(interface_ref.get("name") or "").strip().lower()
                feature_group_name = str(change.get("feature_group_id") or placement.get("feature_group_id") or "").strip().lower()
                hub_arm_slot_mount_feature = (
                    interface_name.startswith("slot_mount_face_phase_")
                    or interface_name == "proximal_insert_face"
                    or feature_group_name.startswith("central_hub_to_arm_")
                    or feature_group_name.startswith("hub_to_arm_")
                )
                if (
                    slot_capture_mount
                    and feature_key in {"hole", "clearance_hole", "threaded_hole", "counterbore", "countersink", "nut_seat"}
                    and not (
                        (mechanism_name == "axial_face_bolted_mount" and support_topology == "hub_radial_slot_mount")
                        or hub_arm_slot_mount_feature
                    )
                ):
                    warnings.append(f"{feature_key} suppressed for side-entry slot capture mount on {target_id}")
                    continue
                if feature_key == "shaft_bore" and target_profile_type == "yoke_profile":
                    warnings.append(f"shaft_bore compiled in yoke body stage for {target_id}")
                    continue

                if feature_key in {"bolt_circle_pattern", "mounting_face"}:
                    warnings.append(f"{feature_key} treated as semantic marker only for {target_id}")
                    continue

                geometry_parameters_raw = change.get("geometry_parameters")
                geometry_parameters = geometry_parameters_raw if isinstance(geometry_parameters_raw, Mapping) else {}
                diameter = change.get("diameter") or change.get("bore_diameter") or change.get("hole_diameter")
                if not isinstance(diameter, (int, float)):
                    diameter = geometry_parameters.get("diameter") or geometry_parameters.get("bore_diameter") or geometry_parameters.get("hole_diameter")
                depth = change.get("depth")
                if isinstance(depth, str):
                    depth_val = None
                elif isinstance(depth, (int, float)):
                    depth_val = float(depth)
                else:
                    depth_val = None

                if feature_key == "thread":
                    _require_function(allowed, "ACTIVATE_COMPONENT")
                    _require_function(allowed, "SELECT_CYLINDRICAL_FACE")
                    _require_function(allowed, "THREAD_ON_CYLINDRICAL_FACES")

                    anchor = change.get("anchor")
                    anchor_map = anchor if isinstance(anchor, Mapping) else {}

                    radius_mm = anchor_map.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        radius_mm = change.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        radius_mm = geometry_parameters.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        major_diameter = change.get("major_diameter")
                        if not isinstance(major_diameter, (int, float)):
                            major_diameter = geometry_parameters.get("major_diameter")
                        if isinstance(major_diameter, (int, float)):
                            radius_mm = float(major_diameter) / 2.0

                    if not isinstance(radius_mm, (int, float)):
                        warnings.append(f"thread missing radius_mm for {target_id}")
                        continue

                    tol_mm = anchor_map.get("tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = change.get("radius_tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = geometry_parameters.get("radius_tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = 0.05

                    raw_is_internal = change.get("is_internal")
                    if not isinstance(raw_is_internal, bool):
                        raw_is_internal = geometry_parameters.get("is_internal")
                    is_internal = bool(raw_is_internal) if isinstance(raw_is_internal, bool) else False

                    thread_type = change.get("thread_type")
                    if not isinstance(thread_type, str) or not thread_type.strip():
                        thread_type = geometry_parameters.get("thread_type")
                    if not isinstance(thread_type, str) or not thread_type.strip():
                        thread_type = "ISO Metric profile"

                    thread_designation = change.get("thread_designation")
                    if not isinstance(thread_designation, str) or not thread_designation.strip():
                        thread_designation = geometry_parameters.get("thread_designation")
                    if not isinstance(thread_designation, str) or not thread_designation.strip():
                        warnings.append(f"thread missing thread_designation for {target_id}")
                        continue

                    thread_class = change.get("thread_class")
                    if not isinstance(thread_class, str) or not thread_class.strip():
                        thread_class = geometry_parameters.get("thread_class")
                    if not isinstance(thread_class, str) or not thread_class.strip():
                        thread_class = "6H" if is_internal else "6g"

                    raw_is_modeled = change.get("is_modeled")
                    if not isinstance(raw_is_modeled, bool):
                        raw_is_modeled = geometry_parameters.get("is_modeled")
                    is_modeled = bool(raw_is_modeled) if isinstance(raw_is_modeled, bool) else False

                    raw_is_full_length = change.get("is_full_length")
                    if not isinstance(raw_is_full_length, bool):
                        raw_is_full_length = geometry_parameters.get("is_full_length")
                    is_full_length = bool(raw_is_full_length) if isinstance(raw_is_full_length, bool) else True

                    thread_length_mm = change.get("thread_length_mm")
                    if not isinstance(thread_length_mm, (int, float)):
                        thread_length_mm = geometry_parameters.get("thread_length_mm")

                    effective_is_full_length = bool(is_full_length)
                    effective_thread_length = round(float(thread_length_mm), 6) if isinstance(thread_length_mm, (int, float)) else None
                    if effective_is_full_length is False and effective_thread_length is None:
                        effective_is_full_length = True
                    thread_sig = (
                        target_id,
                        round(float(radius_mm), 6),
                        round(float(tol_mm), 6),
                        bool(is_internal),
                        thread_type.strip(),
                        thread_designation.strip(),
                        thread_class.strip(),
                        bool(is_modeled),
                        effective_is_full_length,
                        effective_thread_length,
                    )
                    if thread_sig in seen_thread_signatures:
                        warnings.append(
                            f"Duplicate thread feature skipped for {target_id} ({thread_designation.strip()})"
                        )
                        continue
                    seen_thread_signatures.add(thread_sig)

                    prefix = _safe_id(target_id)
                    stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")
                    face_var = f"{prefix}_{feature_key}_face_{step_index}"

                    activate_step_id = _make_step_id(prefix, f"{feature_key}_activate", step_index)
                    select_step_id = _make_step_id(prefix, f"{feature_key}_select_face", step_index)
                    thread_step_id = _make_step_id(prefix, f"{feature_key}_apply", step_index)

                    steps.append(
                        {
                            "id": activate_step_id,
                            "function": "ACTIVATE_COMPONENT",
                            "inputs": {
                                "component_id": _component_var_ref(target_id),
                            },
                        }
                    )

                    steps.append(
                        {
                            "id": select_step_id,
                            "function": "SELECT_CYLINDRICAL_FACE",
                            "inputs": {
                                "body_id": f"${{{stable_body_var}}}",
                                "radius_mm": float(radius_mm),
                                "tol_mm": float(tol_mm),
                            },
                            "capture": {"vars": {face_var: "face_id"}},
                            "depends_on": [activate_step_id],
                            "metadata": {
                                "component_id": target_id,
                                "source_feature": feature_key,
                            },
                        }
                    )

                    thread_inputs: Dict[str, Any] = {
                        "component_id": _component_var_ref(target_id),
                        "face_ids": [f"${{{face_var}}}"],
                        "is_internal": is_internal,
                        "thread_type": thread_type,
                        "thread_designation": thread_designation,
                        "thread_class": thread_class,
                        "is_modeled": is_modeled,
                        "is_full_length": is_full_length,
                        "name": f"{target_id}_{feature_key}_{step_index}",
                    }
                    if is_full_length is False:
                        if not isinstance(thread_length_mm, (int, float)):
                            warnings.append(
                                f"thread missing thread_length_mm while is_full_length=false for {target_id}; fallback to full_length"
                            )
                            thread_inputs["is_full_length"] = True
                        else:
                            thread_inputs["thread_length_mm"] = float(thread_length_mm)

                    steps.append(
                        {
                            "id": thread_step_id,
                            "function": "THREAD_ON_CYLINDRICAL_FACES",
                            "inputs": thread_inputs,
                            "depends_on": [select_step_id],
                            "metadata": {
                                "component_id": target_id,
                                "source_feature": feature_key,
                            },
                        }
                    )

                    step_index += 1
                    continue

                if feature_key in {
                    "hole",
                    "shaft_bore",
                    "bearing_seat",
                    "alignment_pin_hole",
                    "standoff_bore",
                    "press_fit_zone",
                    "retainer_groove",
                    "seal_groove",
                    "split_clamp_bore",
                    "nut_seat",
                    "bolt_circle_pattern",
                    "counterbore",
                    "countersink",
                }:
                    anchor = change.get("anchor")
                    anchor_map = anchor if isinstance(anchor, Mapping) else {}
                    face_interface_id = anchor_map.get("face_interface_id")
                    if not isinstance(face_interface_id, str) or not face_interface_id:
                        raise ValueError(
                            f"Hole feature '{feature_key}' for component '{target_id}' is missing anchor.face_interface_id"
                        )

                    face_recipe = interface_recipe_index.get((target_id, face_interface_id))
                    if not isinstance(face_recipe, Mapping) and source_target_id != target_id:
                        face_recipe = interface_recipe_index.get((source_target_id, face_interface_id))
                    if not isinstance(face_recipe, Mapping):
                        raise ValueError(
                            f"Missing interface recipe for hole anchor: component='{target_id}', interface='{face_interface_id}'"
                        )
                    face_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None

                    location_map = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                    interface_ref = location_map.get("interface_ref") if isinstance(location_map.get("interface_ref"), Mapping) else {}
                    change_interface_ref = change.get("interface_ref") if isinstance(change.get("interface_ref"), Mapping) else {}
                    centered_bearing_seat = False
                    if feature_key == "bearing_seat":
                        named_interface = change_interface_ref.get("name") if isinstance(change_interface_ref.get("name"), str) else None
                        if not (isinstance(named_interface, str) and named_interface.strip()):
                            named_interface = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
                        named_interface = named_interface.strip().lower() if isinstance(named_interface, str) and named_interface.strip() else ""

                        seat_side = change.get("seat_side") if isinstance(change.get("seat_side"), str) else (placement.get("seat_side") if isinstance(placement.get("seat_side"), str) else None)
                        seat_side = seat_side.strip().lower() if isinstance(seat_side, str) and seat_side.strip() else ""
                        if not seat_side:
                            if named_interface.endswith("_min"):
                                seat_side = "min"
                            elif named_interface.endswith("_max"):
                                seat_side = "max"
                        centered_bearing_seat = not seat_side and named_interface == "bearing_seat"

                        preferred_face_interface_id = None
                        explicit_face_interface_id = geometry_parameters.get("face_interface_id") if isinstance(geometry_parameters.get("face_interface_id"), str) else None
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = change.get("face_interface_id") if isinstance(change.get("face_interface_id"), str) else None
                        geometry_anchor_map = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = geometry_anchor_map.get("face_interface_id") if isinstance(geometry_anchor_map.get("face_interface_id"), str) else None
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = anchor_map.get("face_interface_id") if isinstance(anchor_map.get("face_interface_id"), str) else None
                        if not centered_bearing_seat and isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip():
                            preferred_face_interface_id = explicit_face_interface_id.strip()
                        if not (isinstance(preferred_face_interface_id, str) and preferred_face_interface_id):
                            if seat_side in {"min", "max"}:
                                preferred_face_interface_id = f"axial_end_face_{seat_side}"
                        if isinstance(preferred_face_interface_id, str) and preferred_face_interface_id.strip():
                            face_interface_id = preferred_face_interface_id.strip()
                            face_recipe = interface_recipe_index.get((target_id, face_interface_id))
                            if not isinstance(face_recipe, Mapping) and source_target_id != target_id:
                                face_recipe = interface_recipe_index.get((source_target_id, face_interface_id))
                            if not isinstance(face_recipe, Mapping):
                                raise ValueError(
                                    f"Missing interface recipe for hole anchor: component='{target_id}', interface='{face_interface_id}'"
                                )
                            face_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None
                    usage = _recipe_usage(
                        face_recipe,
                        explicit_usage=(
                            interface_ref.get("usage")
                            if isinstance(interface_ref.get("usage"), str)
                            else (change.get("usage") if isinstance(change.get("usage"), str) else geometry_parameters.get("usage"))
                        ),
                    )
                    resolved_recipe = _sanitize_recipe_for_resolve(face_recipe, usage)

                    side_hint = anchor_map.get("side_hint") if isinstance(anchor_map.get("side_hint"), str) else None
                    if feature_key == "bearing_seat":
                        seat_side = placement.get("seat_side") if isinstance(placement.get("seat_side"), str) else None
                        seat_side = seat_side.strip().upper() if isinstance(seat_side, str) and seat_side.strip() else None
                        interface_seat_side = None
                        if isinstance(face_interface_id, str):
                            if face_interface_id.lower().endswith("_min"):
                                interface_seat_side = "MIN"
                            elif face_interface_id.lower().endswith("_max"):
                                interface_seat_side = "MAX"
                        side_hint = interface_seat_side or seat_side or side_hint
                        if isinstance(face_interface_id, str) and face_interface_id:
                            anchor_map = dict(anchor_map)
                            anchor_map["face_interface_id"] = face_interface_id
                        if isinstance(side_hint, str) and side_hint:
                            anchor_map = dict(anchor_map)
                            anchor_map["side_hint"] = side_hint

                    # Optional: thread spec on hole-like features.
                    # Accept both 'thread_spec' and 'thread' for convenience.
                    thread_spec = None
                    raw_thread = change.get("thread_spec")
                    if isinstance(raw_thread, Mapping):
                        thread_spec = raw_thread
                    else:
                        raw_thread = geometry_parameters.get("thread_spec")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread
                    if thread_spec is None:
                        raw_thread = change.get("thread")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread
                    if thread_spec is None:
                        raw_thread = geometry_parameters.get("thread")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread

                    if not isinstance(diameter, (int, float)):
                        warnings.append(f"{feature_key} missing diameter for {target_id}")
                        continue

                    hole_intent_id = geometry_parameters.get("hole_intent_id")
                    if not isinstance(hole_intent_id, str) or not hole_intent_id.strip():
                        hole_intent_id = change.get("hole_intent_id") if isinstance(change.get("hole_intent_id"), str) else None
                    hole_intent_id = hole_intent_id.strip() if isinstance(hole_intent_id, str) and hole_intent_id.strip() else None
                    if hole_intent_id is not None:
                        hole_intent_id = _canonicalize_prototype_scoped_name(
                            hole_intent_id,
                            prototype_component_id=target_id,
                            prototype_family_tokens=prototype_family_tokens,
                        )

                    hole_type_raw = geometry_parameters.get("hole_type")
                    if not isinstance(hole_type_raw, str) or not hole_type_raw.strip():
                        hole_type_raw = change.get("hole_type") if isinstance(change.get("hole_type"), str) else None
                    hole_type = hole_type_raw.strip().lower() if isinstance(hole_type_raw, str) and hole_type_raw.strip() else feature_key

                    if hole_intent_id is not None:
                        intent_key = (target_id, hole_intent_id)
                        existing = seen_hole_intents.get(intent_key)
                        if isinstance(existing, Mapping):
                            existing_hole_type = str(existing.get("hole_type") or "").lower()
                            existing_diameter = existing.get("diameter")
                            current_diameter = float(diameter)
                            conflict_reasons: List[str] = []

                            if existing_hole_type != hole_type:
                                conflict_reasons.append("hole_type_conflict")
                            if isinstance(existing_diameter, (int, float)) and abs(float(existing_diameter) - current_diameter) > 1e-6:
                                conflict_reasons.append("diameter_conflict")
                            if not conflict_reasons:
                                conflict_reasons.append("duplicate_hole_action")

                            raise ValueError(
                                "Conflicting hole realization in compile stage: "
                                f"component='{target_id}', hole_intent_id='{hole_intent_id}', "
                                f"existing_type='{existing_hole_type}', new_type='{hole_type}', "
                                f"existing_diameter={existing_diameter}, new_diameter={current_diameter}, "
                                f"reasons={conflict_reasons}"
                            )

                        seen_hole_intents[intent_key] = {
                            "hole_type": hole_type,
                            "diameter": float(diameter),
                            "feature_key": feature_key,
                        }

                    feature_group_raw = placement.get("feature_group_id")
                    if not isinstance(feature_group_raw, str) or not feature_group_raw.strip():
                        feature_group_raw = geometry_parameters.get("feature_group_id") if isinstance(geometry_parameters.get("feature_group_id"), str) else None
                    feature_group_id = feature_group_raw.strip() if isinstance(feature_group_raw, str) and feature_group_raw.strip() else feature_key
                    feature_group_id = _canonicalize_prototype_scoped_name(
                        feature_group_id,
                        prototype_component_id=target_id,
                        prototype_family_tokens=prototype_family_tokens,
                    )

                    group_key = (target_id, face_interface_id, feature_group_id)
                    group_ctx = grouped_hole_context.get(group_key)
                    if group_ctx is None:
                        prefix = _safe_id(target_id)
                        group_token = _safe_id(feature_group_id)
                        group_idx = step_index
                        step_index += 1
                        activate_step_id = _make_step_id(prefix, f"{group_token}_activate", group_idx)
                        resolve_step_id = _make_step_id(prefix, f"{group_token}_resolve_face", group_idx)
                        face_var = f"{prefix}_{group_token}_face_{group_idx}"
                        face_kind_var = f"{prefix}_{group_token}_face_kind_{group_idx}"
                        stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")

                        _require_function(allowed, "ACTIVATE_COMPONENT")
                        _require_function(allowed, "RESOLVE_INTERFACE")

                        steps.append(
                            {
                                "id": activate_step_id,
                                "function": "ACTIVATE_COMPONENT",
                                "inputs": {
                                    "component_id": _component_var_ref(target_id),
                                },
                            }
                        )
                        steps.append(
                            {
                                "id": resolve_step_id,
                                "function": "RESOLVE_INTERFACE",
                                "inputs": {
                                    "component_id": _component_var_ref(target_id),
                                    "body_id": f"${{{stable_body_var}}}",
                                    "interface_name": face_interface_id,
                                    "recipe": dict(resolved_recipe),
                                },
                                "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
                                "depends_on": [activate_step_id],
                                "metadata": {
                                    "component_id": target_id,
                                    "interface_name": face_interface_id,
                                    "expected_entity_kind": "face",
                                    "usage": usage,
                                },
                            }
                        )
                        group_ctx = {
                            "resolve_step_id": resolve_step_id,
                            "face_var": face_var,
                            "face_kind_var": face_kind_var,
                            "usage": usage,
                            "hole_count": 0,
                            "last_step_id": resolve_step_id,
                            "_resolved_recipe": dict(resolved_recipe),
                            "_face_interface_id": face_interface_id,
                            "_target_id": target_id,
                            "_feature_group_id": feature_group_id,
                        }
                        grouped_hole_context[group_key] = group_ctx

                    pattern_raw = placement.get("pattern")
                    pattern = pattern_raw if isinstance(pattern_raw, Mapping) else None
                    pattern_axis = placement.get("pattern_axis") if isinstance(placement.get("pattern_axis"), str) else None
                    seed_point_raw = placement.get("seed_point_mm") if isinstance(placement.get("seed_point_mm"), Mapping) else None

                    hole_mode = "simple"
                    if feature_key == "counterbore":
                        hole_mode = "counterbore"
                    elif feature_key == "countersink":
                        hole_mode = "countersink"
                    elif (
                        isinstance(geometry_parameters.get("cbore_diameter_mm"), (int, float))
                        or isinstance(geometry_parameters.get("counterbore_diameter"), (int, float))
                        or isinstance(change.get("cbore_diameter_mm"), (int, float))
                        or isinstance(change.get("counterbore_diameter"), (int, float))
                    ):
                        hole_mode = "counterbore"

                    cbore_diameter_mm = None
                    cbore_depth_mm = None
                    if hole_mode == "counterbore":
                        cbore_diameter_mm = (
                            geometry_parameters.get("cbore_diameter_mm")
                            if isinstance(geometry_parameters.get("cbore_diameter_mm"), (int, float))
                            else geometry_parameters.get("counterbore_diameter")
                        )
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = change.get("cbore_diameter_mm") if isinstance(change.get("cbore_diameter_mm"), (int, float)) else change.get("counterbore_diameter")
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = geometry_parameters.get("counterbore_diameter_mm")
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = change.get("counterbore_diameter_mm")
                        cbore_depth_mm = (
                            geometry_parameters.get("cbore_depth_mm")
                            if isinstance(geometry_parameters.get("cbore_depth_mm"), (int, float))
                            else geometry_parameters.get("counterbore_depth")
                        )
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = change.get("cbore_depth_mm") if isinstance(change.get("cbore_depth_mm"), (int, float)) else change.get("counterbore_depth")
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = geometry_parameters.get("counterbore_depth_mm")
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = change.get("counterbore_depth_mm")

                    csink_diameter_mm = None
                    csink_angle_rad = None
                    if hole_mode == "countersink":
                        csink_diameter_mm = (
                            geometry_parameters.get("csink_diameter_mm")
                            if isinstance(geometry_parameters.get("csink_diameter_mm"), (int, float))
                            else geometry_parameters.get("countersink_diameter")
                        )
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = change.get("csink_diameter_mm") if isinstance(change.get("csink_diameter_mm"), (int, float)) else change.get("countersink_diameter")
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = geometry_parameters.get("countersink_diameter_mm")
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = change.get("countersink_diameter_mm")
                        csink_angle_rad = geometry_parameters.get("csink_angle_rad")
                        if not isinstance(csink_angle_rad, (int, float)):
                            csink_angle_rad = change.get("csink_angle_rad")
                        if not isinstance(csink_angle_rad, (int, float)):
                            csink_angle_deg = geometry_parameters.get("csink_angle_deg")
                            if not isinstance(csink_angle_deg, (int, float)):
                                csink_angle_deg = change.get("csink_angle_deg")
                            if isinstance(csink_angle_deg, (int, float)):
                                csink_angle_rad = float(csink_angle_deg) * math.pi / 180.0

                    if hole_mode == "counterbore" and (not isinstance(cbore_diameter_mm, (int, float)) or not isinstance(cbore_depth_mm, (int, float))):
                        warnings.append(f"counterbore missing cbore geometry for {target_id}; fallback to HOLE_SIMPLE")
                        hole_mode = "simple"
                    if hole_mode == "countersink" and (not isinstance(csink_diameter_mm, (int, float)) or not isinstance(csink_angle_rad, (int, float))):
                        warnings.append(f"countersink missing csink geometry for {target_id}; fallback to HOLE_SIMPLE")
                        hole_mode = "simple"

                    if (not instances) and isinstance(pattern, Mapping) and str(pattern.get("type") or "").lower() in {"circular", "rectangular"}:
                        seed_center = {
                            "x": float((seed_point_raw or {}).get("x", 0.0)),
                            "y": float((seed_point_raw or {}).get("y", 0.0)),
                            "z": float((seed_point_raw or {}).get("z", 0.0)),
                        }
                        if depth_val is None:
                            if side_hint == "MAX":
                                extent_key = "through_negative"
                            elif side_hint == "MIN":
                                extent_key = "through_positive"
                            else:
                                extent_key = "through_positive"
                        else:
                            extent_key = "distance"

                        group_seed_sig = (
                            target_id,
                            feature_group_id,
                            face_interface_id,
                            side_hint,
                            round(seed_center["x"], 6),
                            round(seed_center["y"], 6),
                            round(seed_center["z"], 6),
                            round(float(diameter), 6),
                            extent_key,
                        )
                        if group_seed_sig in seen_group_seed_hole_signatures:
                            warnings.append(
                                f"Duplicate grouped seed hole skipped for {target_id} (feature_group_id={feature_group_id})"
                            )
                            continue

                        hole_sig = (
                            target_id,
                            feature_key,
                            face_interface_id,
                            side_hint,
                            float(diameter),
                            depth_val,
                            extent_key,
                            (round(seed_center["x"], 6), round(seed_center["y"], 6), round(seed_center["z"], 6)),
                            f"pattern:{str(pattern.get('type') or '').lower()}",
                        )
                        if hole_sig in seen_hole_signatures:
                            warnings.append(f"Duplicate patterned {feature_key} skipped for {target_id}")
                            continue
                        seen_group_seed_hole_signatures.add(group_seed_sig)
                        seen_hole_signatures.add(hole_sig)

                        seed_feature_var = f"{_safe_id(target_id)}_{_safe_id(feature_group_id)}_seed_feature_{step_index}"

                        _p_face_var, _p_face_kind_var, _p_depends, step_index = _re_resolve_group_face(
                            group_ctx=group_ctx,
                            target_id=target_id,
                            feature_group_id=feature_group_id,
                            step_index=step_index,
                            steps=steps,
                            face_interface_id=face_interface_id,
                            usage=usage,
                        )

                        _p_hole_steps = _compile_hole_simple_steps(
                            component_id=target_id,
                            feature_key=feature_key,
                            diameter=float(diameter),
                            depth=depth_val,
                            side_hint=side_hint,
                            face_interface_id=face_interface_id,
                            face_geometry_type=face_geometry_type,
                            resolved_face_var=_p_face_var,
                            resolved_face_kind_var=_p_face_kind_var,
                            allowed=allowed,
                            index=step_index,
                            center_mm=seed_center,
                            depends_on=_p_depends,
                            hole_mode=hole_mode,
                            cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                            cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                            csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                            csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                            capture_feature_var=seed_feature_var,
                            pattern=pattern,
                            pattern_axis=pattern_axis,
                            thread_spec=thread_spec,
                        )
                        steps.extend(_p_hole_steps)

                        # Update group context for next hole in group
                        group_ctx["hole_count"] += 1
                        if _p_hole_steps:
                            group_ctx["last_step_id"] = _p_hole_steps[-1]["id"]
                            group_ctx["face_var"] = _p_face_var
                            group_ctx["face_kind_var"] = _p_face_kind_var
                            group_ctx["resolve_step_id"] = _p_depends[0]

                        step_index += 1
                        continue

                    if instances:
                        for inst in instances:
                            if not isinstance(inst, Mapping):
                                continue
                            pos = inst.get("position")
                            if not isinstance(pos, Mapping):
                                continue

                            # Signature: same target + params + center => same hole.
                            extent_key = "through_positive" if depth_val is None else "distance"
                            try:
                                center_key = (
                                    round(float(pos.get("x", 0.0)), 6),
                                    round(float(pos.get("y", 0.0)), 6),
                                    round(float(pos.get("z", 0.0)), 6),
                                )
                            except Exception:
                                center_key = (0.0, 0.0, 0.0)

                            hole_sig = (
                                target_id,
                                feature_key,
                                face_interface_id,
                                side_hint,
                                float(diameter),
                                depth_val,
                                extent_key,
                                center_key,
                            )
                            if hole_sig in seen_hole_signatures:
                                warnings.append(
                                    f"Duplicate {feature_key} skipped for {target_id} at {center_key}"
                                )
                                continue
                            seen_hole_signatures.add(hole_sig)

                            current_face_var, current_face_kind_var, current_depends, step_index = _re_resolve_group_face(
                                group_ctx=group_ctx,
                                target_id=target_id,
                                feature_group_id=feature_group_id,
                                step_index=step_index,
                                steps=steps,
                                face_interface_id=face_interface_id,
                                usage=usage,
                            )

                            hole_steps = _compile_hole_simple_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=depth_val,
                                side_hint=side_hint,
                                face_interface_id=face_interface_id,
                                face_geometry_type=face_geometry_type,
                                resolved_face_var=current_face_var,
                                resolved_face_kind_var=current_face_kind_var,
                                allowed=allowed,
                                index=step_index,
                                center_mm=pos,
                                depends_on=current_depends,
                                hole_mode=hole_mode,
                                cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                                cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                                csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                                csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                                thread_spec=thread_spec,
                            )
                            steps.extend(hole_steps)

                            # Update group context for next hole in group
                            group_ctx["hole_count"] += 1
                            if hole_steps:
                                group_ctx["last_step_id"] = hole_steps[-1]["id"]
                                group_ctx["face_var"] = current_face_var
                                group_ctx["face_kind_var"] = current_face_kind_var
                                group_ctx["resolve_step_id"] = current_depends[0]

                            step_index += 1
                    else:
                        extent_key = "through_positive" if depth_val is None else "distance"
                        hole_sig = (
                            target_id,
                            feature_key,
                            face_interface_id,
                            side_hint,
                            float(diameter),
                            depth_val,
                            extent_key,
                            (0.0, 0.0, 0.0),
                        )
                        if hole_sig in seen_hole_signatures:
                            warnings.append(
                                f"Duplicate {feature_key} skipped for {target_id} at (0,0,0)"
                            )
                            continue
                        seen_hole_signatures.add(hole_sig)

                        _e_face_var, _e_face_kind_var, _e_depends, step_index = _re_resolve_group_face(
                            group_ctx=group_ctx,
                            target_id=target_id,
                            feature_group_id=feature_group_id,
                            step_index=step_index,
                            steps=steps,
                            face_interface_id=face_interface_id,
                            usage=usage,
                        )

                        integrated_axisymmetric_seat = (
                            feature_key == "bearing_seat"
                            and _integrated_axisymmetric_bearing_seat_params(target_strategy) is not None
                        )
                        if integrated_axisymmetric_seat:
                            warnings.append(
                                f"Integrated axisymmetric bearing_seat geometry already baked into profile for {target_id}; compile-time cut skipped"
                            )
                            continue
                        if _should_compile_axisymmetric_bearing_seat_cut(
                            feature_key=feature_key,
                            target_strategy=target_strategy,
                            face_interface_id=face_interface_id,
                            diameter=diameter,
                            depth=depth_val,
                            centered=centered_bearing_seat,
                        ):
                            _e_hole_steps = _compile_axisymmetric_bearing_seat_cut_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=float(depth_val),
                                side_hint=side_hint or "MAX",
                                face_interface_id=face_interface_id,
                                allowed=allowed,
                                index=step_index,
                                depends_on=_e_depends,
                                target_strategy=target_strategy,
                                centered=centered_bearing_seat,
                            )
                        else:
                            _e_hole_steps = _compile_hole_simple_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=depth_val,
                                side_hint=side_hint,
                                face_interface_id=face_interface_id,
                                face_geometry_type=face_geometry_type,
                                resolved_face_var=_e_face_var,
                                resolved_face_kind_var=_e_face_kind_var,
                                allowed=allowed,
                                index=step_index,
                                center_mm=(seed_point_raw if isinstance(seed_point_raw, Mapping) else None),
                                depends_on=_e_depends,
                                hole_mode=hole_mode,
                                cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                                cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                                csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                                csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                                thread_spec=thread_spec,
                            )
                        steps.extend(_e_hole_steps)

                        # Update group context for next hole in group
                        group_ctx["hole_count"] += 1
                        if _e_hole_steps:
                            group_ctx["last_step_id"] = _e_hole_steps[-1]["id"]
                            group_ctx["face_var"] = _e_face_var
                            group_ctx["face_kind_var"] = _e_face_kind_var
                            group_ctx["resolve_step_id"] = _e_depends[0]

                        step_index += 1
                    continue

                if feature_key in {"keyway_slot", "clamp_slot"}:
                    width = change.get("width")
                    height = change.get("height")
                    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                        warnings.append(f"{feature_key} missing width/height for {target_id}")
                        continue
                    steps.extend(
                        _rectangle_feature_steps(
                            component_id=target_id,
                            feature_key=feature_key,
                            width=float(width),
                            height=float(height),
                            depth=depth_val,
                            allowed=allowed,
                            index=step_index,
                        )
                    )
                    step_index += 1
                    continue

                if feature_key in {"local_thickening", "bonding_zone"}:
                    warnings.append(f"{feature_key} ignored (no geometric rule) for {target_id}")
                    continue

                warnings.append(f"Unsupported derived feature '{feature_key}' for {target_id}")

    return steps, warnings


EXTRUDE_DISTANCE_BINDINGS = {
    "axisymmetric": ("length_param", "width_param", "thickness_param", "height_param", "depth_param"),
    "prismatic": ("thickness_param", "height_param", "depth_param", "width_param", "length_param"),
}


def _is_axisymmetric(primitive_class: Any, profile_type: Any) -> bool:
    if isinstance(primitive_class, str):
        normalized = primitive_class.lower()
        if normalized in {"cylindrical", "cylinder", "shaft", "wheel", "pin", "axle", "rod"}:
            return True
    if isinstance(profile_type, str):
        return profile_type in {"circle", "annular", "half_profile"}
    return False


def _pick_extrude_distance(
    execution_params: Mapping[str, Any],
    primitive_class: Any,
    profile_type: Any,
    shape_name: str,
) -> Tuple[Any, Tuple[str, ...]]:
    """Pick a deterministic extrude distance with width/length fallbacks."""
    axisymmetric = _is_axisymmetric(primitive_class, profile_type)
    # Include width/length because some parts use those instead of thickness/height.
    keys = EXTRUDE_DISTANCE_BINDINGS["axisymmetric" if axisymmetric else "prismatic"]
    distance = _pick_param(execution_params, *keys)
    return distance, keys


def _collect_defined_vars(steps: List[Dict[str, Any]]) -> set[str]:
    defined: set[str] = set()
    for step in steps:
        capture = step.get("capture")
        if isinstance(capture, Mapping):
            vars_map = capture.get("vars")
            if isinstance(vars_map, Mapping):
                for var_name in vars_map.keys():
                    if isinstance(var_name, str):
                        defined.add(var_name)
        outputs = step.get("outputs")
        if isinstance(outputs, Mapping):
            for var_name in outputs.keys():
                if isinstance(var_name, str):
                    defined.add(var_name)
    return defined


def _lint_unresolved_placeholders(steps: List[Dict[str, Any]]) -> None:
    import re

    defined = _collect_defined_vars(steps)
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    suffix_re = re.compile(r"_(distance|width|height|thickness|length|radius|outer_radius|inner_radius|diameter|hole_diameter)$")

    def _hint(var_name: str) -> str:
        if "wheel" in var_name and var_name.endswith("_distance"):
            return "Hint: wheels typically map extrude distance to width."
        if "shaft" in var_name and var_name.endswith("_distance"):
            return "Hint: shafts typically map extrude distance to length."
        if "plate" in var_name and var_name.endswith("_distance"):
            return "Hint: plates typically map extrude distance to thickness."
        if var_name.endswith("_radius") or var_name.endswith("_diameter"):
            return "Hint: map radius to radius_param, or diameter to diameter_param (radius = diameter/2)."
        if var_name.endswith("_distance"):
            return "Hint: wheels use width, shafts use length, plates use thickness."
        return "Hint: map this placeholder to a concrete dimension."

    def _scan(obj: Any, path: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_path = f"{path}.{key}" if path else str(key)
                found.extend(_scan(value, key_path))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                found.extend(_scan(value, f"{path}[{idx}]"))
        elif isinstance(obj, str):
            for match in placeholder_re.findall(obj):
                found.append((path, match))
        return found

    for step in steps:
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            continue
        matches = _scan(inputs, "inputs")
        for field_path, var_name in matches:
            if var_name in defined:
                continue
            if not suffix_re.search(var_name):
                continue
            step_id = step.get("id")
            func_name = step.get("function")
            unresolved = f"${{{var_name}}}"
            raise ValueError(
                "Unresolved placeholder detected in geometry plan: "
                f"step='{step_id}', function='{func_name}', field='{field_path}', value='{unresolved}'. "
                f"{_hint(var_name)}"
            )


def _derive_execution_params(
    strategy: Mapping[str, Any],
    resolution: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    # Execution parameters are resolved exclusively in Agent3b.
    profile_type = strategy.get("profile_type")
    if profile_type == "macro_profile":
        sem = strategy.get("parameter_semantics")
        if not isinstance(sem, Mapping):
            return {}
        execution_params: Dict[str, Any] = {}
        if "hub_radius" in sem:
            execution_params["hub_radius"] = float(sem["hub_radius"])
        if "arm_count" in sem:
            execution_params["arm_count"] = int(sem["arm_count"])
        if "arm_length" in sem:
            execution_params["arm_length"] = float(sem["arm_length"])
        if "arm_width" in sem:
            execution_params["arm_width"] = float(sem["arm_width"])
        if "corner_radius" in sem:
            execution_params["corner_radius"] = float(sem["corner_radius"])
        if "thickness" in sem:
            execution_params["thickness_param"] = float(sem["thickness"])
        return execution_params

    values = strategy.get("parameter_values")
    if not isinstance(values, Mapping) or not values:
        values = {}
        source_resolution = resolution
        if source_resolution is None:
            source_resolution = strategy.get("parameter_resolution")
        if isinstance(source_resolution, Mapping):
            for key, entry in source_resolution.items():
                if not isinstance(entry, Mapping):
                    continue
                raw_value = entry.get("value")
                if isinstance(raw_value, (int, float)):
                    values[key] = raw_value
    if not isinstance(values, Mapping) or not values:
        return {}

    execution_params: Dict[str, Any] = {}

    def _num(val: Any) -> Optional[float]:
        if isinstance(val, (int, float)):
            return float(val)
        return None

    def _set(name: str, val: Any) -> None:
        if val is not None:
            execution_params[name] = val

    radius = _num(values.get("radius"))
    outer_radius = _num(values.get("outer_radius"))
    inner_radius = _num(values.get("inner_radius"))
    diameter = _num(values.get("diameter"))
    nominal_diameter = _num(values.get("nominal_diameter"))
    hole_diameter = _num(values.get("hole_diameter"))
    clearance_diameter = _num(values.get("clearance_diameter"))
    hole_radius = _num(values.get("hole_radius"))
    outer_diameter = _num(values.get("outer_diameter"))
    inner_diameter = _num(values.get("inner_diameter"))
    bore_diameter = _num(values.get("bore_diameter"))

    _set("radius_param", radius)
    _set("outer_radius_param", outer_radius)
    _set("inner_radius_param", inner_radius)
    _set("diameter_param", diameter if diameter is not None else nominal_diameter)
    _set("hole_diameter_param", hole_diameter if hole_diameter is not None else clearance_diameter)
    _set("hole_radius_param", hole_radius)
    _set("outer_diameter_param", outer_diameter)
    _set("inner_diameter_param", inner_diameter if inner_diameter is not None else bore_diameter)

    _set("width_param", _num(values.get("width")))
    _set("height_param", _num(values.get("height")))
    _set("depth_param", _num(values.get("depth")))
    _set("thickness_param", _num(values.get("thickness")))
    _set("length_param", _num(values.get("length")))

    for key in (
        "hub_radius",
        "arm_count",
        "arm_length",
        "arm_width",
        "corner_radius",
        "semantic_hub_radius",
        "semantic_arm_count",
        "semantic_arm_length",
        "semantic_arm_width",
        "semantic_corner_radius",
        "fork_slot_width",
        "fork_slot_depth",
        "root_web_thickness",
        "yoke_plate_thickness",
        "yoke_gap_width",
        "yoke_slot_depth",
        "axle_inset_mm",
        "distal_bore_diameter",
        "yoke_profile_origin",
        "hub_slot_insert_depth",
        "radial_slot_specs",
        "radial_slots",
        "opposed_bearing_seat_diameter",
        "opposed_bearing_seat_depth",
    ):
        if key in values:
            execution_params[key] = values[key]

    if "symmetric_about_sketch_plane" in values:
        execution_params["symmetric_about_sketch_plane"] = bool(values.get("symmetric_about_sketch_plane"))

    return execution_params


def _prefer_feature_authored_shaft_bore_base_solid(
    *,
    realization: Mapping[str, Any],
    strategy: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    params = dict(execution_params or {})
    profile_type = str(strategy.get("profile_type") or "").strip().lower()
    construction_method = str(strategy.get("construction_method") or "").strip().lower()
    if profile_type != "half_profile" or construction_method != "revolve":
        return params

    raw_features = realization.get("features")
    features = raw_features if isinstance(raw_features, list) else []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
            continue
        geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
        diameter = feature.get("diameter")
        if not isinstance(diameter, (int, float)):
            diameter = (
                geometry_parameters.get("diameter")
                or geometry_parameters.get("bore_diameter")
                or geometry_parameters.get("hole_diameter")
            )
        if isinstance(diameter, (int, float)) and float(diameter) > 0.0:
            params["inner_radius_param"] = 0.0
            params["inner_diameter_param"] = 0.0
            return params

    return params


def _validate_shape_realization_inputs(shape: Mapping[str, Any]) -> None:
    forbidden_exec_keys = {
        "distance",
        "angle_rad",
        "axis",
        "revolve_axis",
        "axis_type",
        "extrude_distance",
        "revolve_angle",
        "revolve_angle_rad",
        "profile_id",
        "sketch_id",
    }

    violations: List[str] = []

    def _scan(obj: Any, path: str) -> None:
        if isinstance(obj, Mapping):
            for key, val in obj.items():
                if isinstance(key, str):
                    if key.endswith("_param"):
                        violations.append(f"{path}.{key}")
                    if key in forbidden_exec_keys:
                        violations.append(f"{path}.{key}")
                _scan(val, f"{path}.{key}")
        elif isinstance(obj, list):
            for idx, val in enumerate(obj):
                _scan(val, f"{path}[{idx}]")

    payload = shape.get("component_realizations")
    root = "component_realizations"
    if not isinstance(payload, list):
        payload = shape.get("parts")
        root = "parts"
    if not isinstance(payload, list):
        payload = []

    _scan(payload, root)

    if violations:
        sample = ", ".join(violations[:8])
        raise ValueError(
            "Incoming shape_realization contains CAD-execution fields. "
            "Execution parameters are resolved exclusively in Agent3b. "
            f"Violations: {sample}"
        )


def _build_profile_steps(
    *,
    component_id: str,
    profile_type: str,
    strategy: Mapping[str, Any],
    sketch_id_var: str,
    allowed: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
    prefer_placeholders: bool,
) -> Tuple[List[Dict[str, Any]], str]:
    prefix = _component_prefix(component_id)
    steps: List[Dict[str, Any]] = []

    if profile_type == "circle":
        _require_function(allowed, "SKETCH_CIRCLE")
        radius_key, radius = _pick_param_with_key(
            execution_params or {},
            "radius_param",
            "hole_radius_param",
            "outer_radius_param",
            "inner_radius_param",
            "diameter_param",
            "hole_diameter_param",
            "outer_diameter_param",
            "inner_diameter_param",
        )
        radius = _resolve_param_value(
            radius,
            param_names=(
                "radius_param",
                "hole_radius_param",
                "outer_radius_param",
                "inner_radius_param",
                "diameter_param",
                "hole_diameter_param",
                "outer_diameter_param",
                "inner_diameter_param",
            ),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if isinstance(radius, (int, float)) and isinstance(radius_key, str) and radius_key.endswith("diameter_param"):
            radius = radius / 2
        radius = _ensure_value(radius, component_id=component_id, name="radius")
        step_id = _make_step_id(prefix, "sketch_circle")
        steps.append(
            {
                "id": step_id,
                "function": "SKETCH_CIRCLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "radius": radius,
                },
                "capture": {"vars": {_make_capture_var(prefix, "profile_id"): "profile_id"}},
                "description": f"Create circle profile for {component_id}",
            }
        )
        return steps, _make_capture_var(prefix, "profile_id")

    if profile_type == "annular":
        _require_function(allowed, "SKETCH_CIRCLE")
        outer_key, outer = _pick_param_with_key(
            execution_params or {},
            "outer_radius_param",
            "outer_diameter_param",
            "radius_param",
            "diameter_param",
        )
        inner_key, inner = _pick_param_with_key(
            execution_params or {},
            "inner_radius_param",
            "inner_diameter_param",
            "bore_radius_param",
            "hole_radius_param",
            "hole_diameter_param",
        )
        outer = _resolve_param_value(
            outer,
            param_names=("outer_radius_param", "outer_diameter_param", "radius_param", "diameter_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        inner = _resolve_param_value(
            inner,
            param_names=(
                "inner_radius_param",
                "inner_diameter_param",
                "bore_radius_param",
                "hole_radius_param",
                "hole_diameter_param",
                "radius_param",
            ),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if isinstance(outer, (int, float)) and isinstance(outer_key, str) and outer_key.endswith("diameter_param"):
            outer = outer / 2
        if isinstance(inner, (int, float)) and isinstance(inner_key, str) and inner_key.endswith("diameter_param"):
            inner = inner / 2
        outer = _ensure_value(outer, component_id=component_id, name="outer_radius")
        inner = _ensure_value(inner, component_id=component_id, name="inner_radius")

        outer_step_id = _make_step_id(prefix, "sketch_circle_outer")
        steps.append(
            {
                "id": outer_step_id,
                "function": "SKETCH_CIRCLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "radius": outer,
                },
                "description": f"Create annular outer circle for {component_id}",
            }
        )

        inner_step_id = _make_step_id(prefix, "sketch_circle_inner")
        steps.append(
            {
                "id": inner_step_id,
                "function": "SKETCH_CIRCLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "radius": inner,
                },
                "capture": {"vars": {_make_capture_var(prefix, "profile_id"): "profile_id"}},
                "depends_on": [outer_step_id],
                "description": f"Create annular inner circle for {component_id}",
            }
        )
        return steps, _make_capture_var(prefix, "profile_id")

    if profile_type == "tire_profile":
        _require_function(allowed, "SKETCH_POLYLINE")
        outer_key, outer = _pick_param_with_key(
            execution_params or {},
            "outer_radius_param",
            "outer_diameter_param",
            "radius_param",
            "diameter_param",
        )
        inner_key, inner = _pick_param_with_key(
            execution_params or {},
            "inner_radius_param",
            "inner_diameter_param",
            "bore_radius_param",
            "hole_radius_param",
            "hole_diameter_param",
        )
        height = _pick_param(execution_params or {}, "thickness_param", "width_param", "height_param", "length_param")
        outer = _resolve_param_value(
            outer,
            param_names=("outer_radius_param", "outer_diameter_param", "radius_param", "diameter_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        inner = _resolve_param_value(
            inner,
            param_names=("inner_radius_param", "inner_diameter_param", "bore_radius_param", "hole_radius_param", "hole_diameter_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if inner is None:
            inner = 0.0
        height = _resolve_param_value(
            height,
            param_names=("thickness_param", "width_param", "height_param", "length_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if isinstance(outer, (int, float)) and isinstance(outer_key, str) and outer_key.endswith("diameter_param"):
            outer = outer / 2
        if isinstance(inner, (int, float)) and isinstance(inner_key, str) and inner_key.endswith("diameter_param"):
            inner = inner / 2
        outer_val = _ensure_value(outer, component_id=component_id, name="outer_radius")
        inner_val = _ensure_value(inner, component_id=component_id, name="inner_radius")
        height_val = _ensure_value(height, component_id=component_id, name="height")
        outer_radius = float(outer_val)
        inner_radius = float(inner_val)
        tire_height = float(height_val)
        radial_span = max(outer_radius - inner_radius, 0.6)
        shoulder_raw = _pick_param(execution_params or {}, "tire_shoulder_chamfer_mm", "shoulder_chamfer_mm", "edge_chamfer_mm")
        groove_depth_raw = _pick_param(execution_params or {}, "tread_groove_depth_mm", "groove_depth_mm")
        groove_width_raw = _pick_param(execution_params or {}, "tread_groove_width_mm", "groove_width_mm")
        groove_count_raw = _pick_param(execution_params or {}, "tread_groove_count", "groove_count")
        land_margin_raw = _pick_param(execution_params or {}, "tread_land_margin_mm", "land_margin_mm")
        default_shoulder = min(tire_height * 0.18, radial_span * 0.3)
        shoulder = float(shoulder_raw) if isinstance(shoulder_raw, (int, float)) else default_shoulder
        shoulder = max(min(shoulder, tire_height * 0.35, radial_span * 0.45), 0.0)
        if shoulder < 0.25:
            shoulder = 0.0
        default_land_margin = max(shoulder, tire_height * 0.14)
        land_margin = float(land_margin_raw) if isinstance(land_margin_raw, (int, float)) else default_land_margin
        land_margin = max(min(land_margin, tire_height * 0.3), 0.4)
        groove_count = int(round(groove_count_raw)) if isinstance(groove_count_raw, (int, float)) else (3 if tire_height >= 10.0 else 2)
        groove_count = max(min(groove_count, 5), 0)
        groove_band_start = max(land_margin, shoulder)
        groove_band_end = min(tire_height - land_margin, tire_height - shoulder)
        groove_band = max(groove_band_end - groove_band_start, 0.0)
        if groove_count > 0 and groove_band > 0.8:
            slot_pitch = groove_band / groove_count
            default_groove_width = min(max(tire_height * 0.08, 0.6), slot_pitch * 0.45)
            groove_width = float(groove_width_raw) if isinstance(groove_width_raw, (int, float)) else default_groove_width
            groove_width = max(min(groove_width, slot_pitch * 0.6), 0.3)
            default_groove_depth = min(max(radial_span * 0.12, 0.5), radial_span * 0.28)
            groove_depth = float(groove_depth_raw) if isinstance(groove_depth_raw, (int, float)) else default_groove_depth
            groove_depth = max(min(groove_depth, radial_span * 0.35), 0.25)
        else:
            groove_count = 0
            groove_width = 0.0
            groove_depth = 0.0
            slot_pitch = 0.0
        outer_face_radius = outer_radius
        chamfered_face_radius = outer_radius - shoulder if shoulder > 0.0 else outer_radius
        half_height = tire_height / 2.0
        points = [
            {"x": inner_radius, "y": 0.0},
            {"x": chamfered_face_radius, "y": 0.0},
        ]
        if shoulder > 0.0:
            points.append({"x": outer_face_radius, "y": shoulder})
        current_y = shoulder if shoulder > 0.0 else 0.0
        if groove_count > 0:
            for groove_index in range(groove_count):
                groove_center = groove_band_start + slot_pitch * (groove_index + 0.5)
                groove_start = max(current_y, groove_center - (groove_width / 2.0))
                groove_end = min(groove_band_end, groove_center + (groove_width / 2.0))
                if groove_start > current_y:
                    points.append({"x": outer_face_radius, "y": groove_start})
                if groove_end > groove_start:
                    inset_radius = max(inner_radius + 0.2, outer_face_radius - groove_depth)
                    points.extend(
                        [
                            {"x": inset_radius, "y": groove_start},
                            {"x": inset_radius, "y": groove_end},
                            {"x": outer_face_radius, "y": groove_end},
                        ]
                    )
                    current_y = groove_end
        outer_top_y = tire_height - shoulder if shoulder > 0.0 else tire_height
        if outer_top_y > current_y:
            points.append({"x": outer_face_radius, "y": outer_top_y})
        if shoulder > 0.0:
            points.append({"x": chamfered_face_radius, "y": tire_height})
        else:
            points.append({"x": outer_face_radius, "y": tire_height})
        points.append({"x": inner_radius, "y": tire_height})
        poly_step_id = _make_step_id(prefix, "sketch_tire_profile_edges")
        profile_var = _make_capture_var(prefix, "profile_id")
        steps.append(
            {
                "id": poly_step_id,
                "function": "SKETCH_POLYLINE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "points": [
                        {
                            "x": point.get("x"),
                            "y": float(point.get("y", 0.0)) - half_height,
                        }
                        for point in points
                    ],
                    "closed": True,
                },
                "capture": {"vars": {profile_var: "profile_id"}},
                "description": f"Create treaded tire profile for {component_id}",
            }
        )
        return steps, profile_var
    if profile_type == "half_profile":
        outer_key, outer = _pick_param_with_key(
            execution_params or {},
            "outer_radius_param",
            "outer_diameter_param",
            "radius_param",
            "diameter_param",
        )
        inner_key, inner = _pick_param_with_key(
            execution_params or {},
            "inner_radius_param",
            "inner_diameter_param",
            "bore_radius_param",
            "hole_radius_param",
            "hole_diameter_param",
        )
        height = _pick_param(execution_params or {}, "thickness_param", "width_param", "height_param", "length_param")
        outer = _resolve_param_value(
            outer,
            param_names=("outer_radius_param", "outer_diameter_param", "radius_param", "diameter_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        inner = _resolve_param_value(
            inner,
            param_names=("inner_radius_param", "inner_diameter_param", "bore_radius_param", "hole_radius_param", "hole_diameter_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if inner is None:
            inner = 0.0
        height = _resolve_param_value(
            height,
            param_names=("thickness_param", "width_param", "height_param", "length_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if isinstance(outer, (int, float)) and isinstance(outer_key, str) and outer_key.endswith("diameter_param"):
            outer = outer / 2
        if isinstance(inner, (int, float)) and isinstance(inner_key, str) and inner_key.endswith("diameter_param"):
            inner = inner / 2
        outer_val = _ensure_value(outer, component_id=component_id, name="outer_radius")
        inner_val = _ensure_value(inner, component_id=component_id, name="inner_radius")
        height_val = _ensure_value(height, component_id=component_id, name="height")

        integrated_seat_diameter = _pick_param(execution_params or {}, "opposed_bearing_seat_diameter")
        integrated_seat_depth = _pick_param(execution_params or {}, "opposed_bearing_seat_depth", "opposed_bearing_width")
        integrated_profile_ok = (
            isinstance(outer_val, (int, float))
            and isinstance(inner_val, (int, float))
            and isinstance(height_val, (int, float))
            and isinstance(integrated_seat_diameter, (int, float))
            and isinstance(integrated_seat_depth, (int, float))
            and float(integrated_seat_diameter) > 0.0
            and float(integrated_seat_depth) > 0.0
        )
        if integrated_profile_ok:
            seat_radius = float(integrated_seat_diameter) / 2.0
            outer_radius = float(outer_val)
            inner_radius = float(inner_val)
            half_height = float(height_val) / 2.0
            seat_depth = min(float(integrated_seat_depth), max(0.5, half_height - 0.5))
            web_half_height = max(half_height - seat_depth, 0.5)
            if seat_radius > inner_radius + 0.25 and seat_radius < outer_radius - 0.25:
                _require_function(allowed, "SKETCH_POLYLINE")
                profile_var = _make_capture_var(prefix, "profile_id")
                step_id = _make_step_id(prefix, "sketch_half_profile")
                points = [
                    {"x": seat_radius, "y": -half_height},
                    {"x": outer_radius, "y": -half_height},
                    {"x": outer_radius, "y": half_height},
                    {"x": seat_radius, "y": half_height},
                    {"x": seat_radius, "y": web_half_height},
                    {"x": inner_radius, "y": web_half_height},
                    {"x": inner_radius, "y": -web_half_height},
                    {"x": seat_radius, "y": -web_half_height},
                ]
                steps.append(
                    {
                        "id": step_id,
                        "function": "SKETCH_POLYLINE",
                        "inputs": {
                            "sketch_id": f"${{{sketch_id_var}}}",
                            "points": points,
                            "closed": True,
                        },
                        "capture": {"vars": {profile_var: "profile_id"}},
                        "description": (
                            f"Create stepped opposed-bearing half-profile for {component_id} "
                            f"(inner_radius={inner_val}, seat_radius={seat_radius}, outer_radius={outer_val})"
                        ),
                    }
                )
                return steps, profile_var

        _require_function(allowed, "SKETCH_RECTANGLE")
        if isinstance(outer, (int, float)) and isinstance(inner, (int, float)):
            radial_span = max(float(outer) - float(inner), 0.1)
            center_x = float(inner) + (radial_span / 2.0)
        else:
            radial_span = _placeholder(component_id, "half_profile_radial_span")
            center_x = _placeholder(component_id, "half_profile_center_x")
        center_y = 0.0
        step_id = _make_step_id(prefix, "sketch_half_profile")
        steps.append(
            {
                "id": step_id,
                "function": "SKETCH_RECTANGLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": center_x, "y": center_y},
                    "width": radial_span,
                    "height": height_val,
                },
                "capture": {"vars": {_make_capture_var(prefix, "profile_id"): "profile_id"}},
                "description": f"Create annular half-profile for {component_id} (inner_radius={inner_val}, outer_radius={outer_val})",
            }
        )
        return steps, _make_capture_var(prefix, "profile_id")

    if profile_type == "rectangle":
        _require_function(allowed, "SKETCH_RECTANGLE")
        _params = execution_params or {}

        # 闂傚倷绀侀崯鍧楀储濠婂牆纾婚柟鍓х帛閻撳啴鏌涜箛鎿冩Ц濞?Smart dimension selection for prismatic rectangles 闂傚倷绀侀崯鍧楀储濠婂牆纾婚柟鍓х帛閻撳啴鏌涜箛鎿冩Ц濞存粓绠栧娲礃閹绘帒杈呴梺绋款儐閹瑰洭寮诲澶婄濠㈣泛锕ｆ竟鏇㈡⒒娴ｇ鏆遍柛妯荤矒瀹曟垿骞樼紒妯煎帗闂佺绻愰ˇ顖涚妤ｅ啯鈷戦柛鎰絻鐢劑鏌涚€ｎ偅宕岄柡灞界Ч瀹曟寰勬繝浣割棜闂傚倷绀侀崯鍧楀储濠婂牆纾婚柟鍓х帛閻撳啴鏌涜箛鎿冩Ц濞?        # When length_param is available and larger than width_param, the
        # component is elongated (arm, bar, beam 闂?.  The sketch footprint
        # should capture length 闂?width while the extrude takes the thin
        # dimension (thickness/height).  Without this, a 80闂?0闂? arm would
        # be sketched as 20闂?0 and the 80 mm length would be lost entirely.
        _length_v = _params.get("length_param")
        _width_v  = _params.get("width_param")
        _has_length = isinstance(_length_v, (int, float))
        _has_width  = isinstance(_width_v, (int, float))

        if _has_length and _has_width and float(_length_v) > float(_width_v):
            # Elongated prismatic: sketch = length 闂?width
            _sketch_w_keys: Tuple[str, ...] = ("length_param", "width_param", "depth_param")
            _sketch_h_keys: Tuple[str, ...] = ("width_param", "height_param", "depth_param")
        else:
            # Default (plates, walls, compact blocks 闂?
            _sketch_w_keys = ("width_param", "length_param", "depth_param")
            _sketch_h_keys = ("height_param", "length_param", "depth_param")

        width = _pick_param(_params, *_sketch_w_keys)
        height = _pick_param(_params, *_sketch_h_keys)
        width = _resolve_param_value(
            width,
            param_names=_sketch_w_keys,
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        height = _resolve_param_value(
            height,
            param_names=_sketch_h_keys,
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        if height is None and width is not None:
            height = width
        if width is None and height is not None:
            width = height
        width = _ensure_value(width, component_id=component_id, name="width")
        height = _ensure_value(height, component_id=component_id, name="height")
        step_id = _make_step_id(prefix, "sketch_rectangle")
        steps.append(
            {
                "id": step_id,
                "function": "SKETCH_RECTANGLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "width": width,
                    "height": height,
                },
                "capture": {"vars": {_make_capture_var(prefix, "profile_id"): "profile_id"}},
                "description": f"Create rectangle profile for {component_id}",
            }
        )
        return steps, _make_capture_var(prefix, "profile_id")

    if profile_type == "fork_profile":
        _require_function(allowed, "SKETCH_POLYLINE")
        _params = execution_params or {}
        length = _resolve_param_value(
            _pick_param(_params, "length_param", "width_param"),
            param_names=("length_param", "width_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        width = _resolve_param_value(
            _pick_param(_params, "width_param", "height_param", "length_param"),
            param_names=("width_param", "height_param", "length_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        slot_width = _resolve_param_value(
            _pick_param(_params, "fork_slot_width", "hole_diameter_param", "width_param"),
            param_names=("fork_slot_width", "hole_diameter_param", "width_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        slot_depth = _resolve_param_value(
            _pick_param(_params, "fork_slot_depth", "hole_diameter_param", "width_param"),
            param_names=("fork_slot_depth", "hole_diameter_param", "width_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        length = _ensure_value(length, component_id=component_id, name="length")
        width = _ensure_value(width, component_id=component_id, name="width")
        slot_width = _ensure_value(slot_width, component_id=component_id, name="fork_slot_width")
        slot_depth = _ensure_value(slot_depth, component_id=component_id, name="fork_slot_depth")
        half_length = float(length) / 2.0
        half_width = float(width) / 2.0
        slot_half = min(float(slot_width) / 2.0, max(0.5, half_width - 1.0))
        slot_back_x = half_length - min(float(slot_depth), max(1.0, float(length) - 2.0))
        points = [
            {"x": -half_length, "y": -half_width},
            {"x": half_length, "y": -half_width},
            {"x": half_length, "y": -slot_half},
            {"x": slot_back_x, "y": -slot_half},
            {"x": slot_back_x, "y": slot_half},
            {"x": half_length, "y": slot_half},
            {"x": half_length, "y": half_width},
            {"x": -half_length, "y": half_width},
        ]
        poly_step_id = _make_step_id(prefix, "sketch_fork_profile_edges")
        profile_var = _make_capture_var(prefix, "profile_id")
        steps.append(
            {
                "id": poly_step_id,
                "function": "SKETCH_POLYLINE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "points": points,
                    "closed": True,
                },
                "capture": {"vars": {profile_var: "profile_id"}},
                "description": f"Create forked distal support profile for {component_id}",
            }
        )
        return steps, profile_var

    if profile_type == "yoke_profile":
        _require_function(allowed, "SKETCH_RECTANGLE")
        _params = execution_params or {}
        length = _resolve_param_value(
            _pick_param(_params, "length", "length_param", "width_param"),
            param_names=("length", "length_param", "width_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        width = _resolve_param_value(
            _pick_param(_params, "width", "width_param", "height_param", "length_param"),
            param_names=("width", "width_param", "height_param", "length_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        length = _ensure_value(length, component_id=component_id, name="length")
        width = _ensure_value(width, component_id=component_id, name="width")
        step_id = _make_step_id(prefix, "sketch_yoke_blank")
        profile_var = _make_capture_var(prefix, "profile_id")
        steps.append(
            {
                "id": step_id,
                "function": "SKETCH_RECTANGLE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "width": length,
                    "height": width,
                },
                "capture": {"vars": {profile_var: "profile_id"}},
                "description": f"Create yoke blank profile for {component_id}",
            }
        )
        return steps, profile_var

    if profile_type == "macro_profile":
        _require_function(allowed, "SKETCH_ROUNDED_POLYGON")
        hub_radius = _pick_param(execution_params or {}, "hub_radius", "radius_param")
        arm_count = _pick_param(execution_params or {}, "arm_count")
        arm_length = _pick_param(execution_params or {}, "arm_length")
        arm_width = _pick_param(execution_params or {}, "arm_width")
        corner_radius = _pick_param(execution_params or {}, "corner_radius")
        hub_radius = _resolve_param_value(
            hub_radius,
            param_names=("hub_radius", "radius_param"),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        arm_count = _resolve_param_value(
            arm_count,
            param_names=("arm_count",),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        arm_length = _resolve_param_value(
            arm_length,
            param_names=("arm_length",),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        arm_width = _resolve_param_value(
            arm_width,
            param_names=("arm_width",),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        corner_radius = _resolve_param_value(
            corner_radius,
            param_names=("corner_radius",),
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )

        missing = [
            name
            for name, value in (
                ("hub_radius", hub_radius),
                ("arm_count", arm_count),
                ("arm_length", arm_length),
                ("arm_width", arm_width),
                ("corner_radius", corner_radius),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"macro_profile requires numeric parameters; missing: {', '.join(missing)}"
            )

        step_id = _make_step_id(prefix, "sketch_macro_profile")
        steps.append(
            {
                "id": step_id,
                "function": "SKETCH_ROUNDED_POLYGON",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "center": {"x": 0, "y": 0},
                    "hub_radius": hub_radius,
                    "arm_count": arm_count,
                    "arm_length": arm_length,
                    "arm_width": arm_width,
                    "corner_radius": corner_radius,
                },
                "capture": {"vars": {_make_capture_var(prefix, "profile_id"): "profile_id"}},
                "description": f"Create semantic profile for {component_id}",
            }
        )
        return steps, _make_capture_var(prefix, "profile_id")

    raise ValueError(f"Unsupported profile_type '{profile_type}' for component '{component_id}'.")


def _build_feature_step(
    *,
    component_id: str,
    construction_method: str,
    strategy: Mapping[str, Any],
    profile_id_var: str,
    component_id_var: str,
    allowed: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
    axis_spec: Any,
    prefer_placeholders: bool,
) -> Dict[str, Any]:
    prefix = _component_prefix(component_id)

    if construction_method == "extrude":
        distance, param_names = _pick_extrude_distance(
            execution_params or {},
            strategy.get("primitive_class"),
            strategy.get("profile_type"),
            component_id,
        )
        distance = _resolve_param_value(
            distance,
            param_names=param_names,
            component_params=execution_params,
            strategy=strategy,
            prefer_placeholders=prefer_placeholders,
        )
        distance = _ensure_value(distance, component_id=component_id, name="distance")
        if bool((execution_params or {}).get("symmetric_about_sketch_plane")):
            _require_function(allowed, "EXTRUDE_SYMMETRIC")
            return {
                "id": _make_step_id(prefix, "extrude"),
                "function": "EXTRUDE_SYMMETRIC",
                "inputs": {
                    "component_id": f"${{{component_id_var}}}",
                    "profile_id": f"${{{profile_id_var}}}",
                    "distance_mm": max(float(distance), 0.1),
                    "operation": "new_body",
                },
                "capture": {"vars": {_make_capture_var(prefix, "body_id"): "body_id"}},
                "description": f"Symmetric extrude profile for {component_id}",
            }
        _require_function(allowed, "EXTRUDE_NEW_BODY")
        return {
            "id": _make_step_id(prefix, "extrude"),
            "function": "EXTRUDE_NEW_BODY",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{profile_id_var}}}",
                "distance": distance,
            },
            "capture": {"vars": {_make_capture_var(prefix, "body_id"): "body_id"}},
            "description": f"Extrude profile for {component_id}",
        }

    if construction_method == "revolve":
        _require_function(allowed, "REVOLVE_NEW_BODY")
        angle_rad = _pick_param(execution_params or {}, "revolve_angle_rad", "angle_rad")
        angle_rad = angle_rad if isinstance(angle_rad, (int, float)) else 6.283185307179586
        return {
            "id": _make_step_id(prefix, "revolve"),
            "function": "REVOLVE_NEW_BODY",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{profile_id_var}}}",
                "axis": axis_spec,
                "angle_rad": angle_rad,
            },
            "capture": {"vars": {_make_capture_var(prefix, "body_id"): "body_id"}},
            "description": f"Revolve profile for {component_id}",
        }

    raise ValueError(
        f"Unsupported construction_method '{construction_method}' for component '{component_id}'."
    )


def _build_yoke_component_steps(
    *,
    component_id: str,
    strategy: Mapping[str, Any],
    component_id_var: str,
    allowed: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
    prefer_placeholders: bool,
    depends_on_step_id: str,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "CREATE_SKETCH_ON_PLANE")
    _require_function(allowed, "CREATE_OFFSET_CONSTRUCTION_PLANE")
    _require_function(allowed, "SKETCH_RECTANGLE")
    _require_function(allowed, "SKETCH_CIRCLE")
    _require_function(allowed, "EXTRUDE_TWO_SIDES")
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    prefix = _component_prefix(component_id)
    params = execution_params or {}
    length = _resolve_param_value(
        _pick_param(params, "length", "length_param", "width_param"),
        param_names=("length", "length_param", "width_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    width = _resolve_param_value(
        _pick_param(params, "width", "width_param", "height_param", "length_param"),
        param_names=("width", "width_param", "height_param", "length_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    thickness = _resolve_param_value(
        _pick_param(params, "thickness", "thickness_param", "height_param"),
        param_names=("thickness", "thickness_param", "height_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    root_web_thickness = _resolve_param_value(
        _pick_param(params, "root_web_thickness", "root_web_thickness_param", "thickness", "thickness_param"),
        param_names=("root_web_thickness", "root_web_thickness_param", "thickness", "thickness_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    plate_thickness = _resolve_param_value(
        _pick_param(params, "yoke_plate_thickness", "yoke_plate_thickness_param", "plate_thickness", "thickness", "thickness_param"),
        param_names=("yoke_plate_thickness", "yoke_plate_thickness_param", "plate_thickness", "thickness", "thickness_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    gap_width = _resolve_param_value(
        _pick_param(params, "yoke_gap_width", "yoke_gap_width_param", "fork_slot_width", "width", "width_param"),
        param_names=("yoke_gap_width", "yoke_gap_width_param", "fork_slot_width", "width", "width_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    slot_depth = _resolve_param_value(
        _pick_param(params, "yoke_slot_depth", "yoke_slot_depth_param", "fork_slot_depth", "width", "width_param"),
        param_names=("yoke_slot_depth", "yoke_slot_depth_param", "fork_slot_depth", "width", "width_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    axle_inset = _resolve_param_value(
        _pick_param(params, "axle_inset_mm", "axle_inset_mm_param", "axle_inset", "inset_mm"),
        param_names=("axle_inset_mm", "axle_inset_mm_param", "axle_inset", "inset_mm"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    distal_bore_diameter = _resolve_param_value(
        _pick_param(params, "distal_bore_diameter", "distal_bore_diameter_param"),
        param_names=("distal_bore_diameter", "distal_bore_diameter_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )
    hub_slot_insert_depth = _resolve_param_value(
        _pick_param(params, "hub_slot_insert_depth", "hub_slot_insert_depth_param"),
        param_names=("hub_slot_insert_depth", "hub_slot_insert_depth_param"),
        component_params=execution_params,
        strategy=strategy,
        prefer_placeholders=prefer_placeholders,
    )

    length = float(_ensure_value(length, component_id=component_id, name="length"))
    width = float(_ensure_value(width, component_id=component_id, name="width"))
    thickness = float(_ensure_value(thickness, component_id=component_id, name="thickness"))
    root_web_thickness = float(_ensure_value(root_web_thickness, component_id=component_id, name="root_web_thickness"))
    plate_thickness = float(_ensure_value(plate_thickness, component_id=component_id, name="yoke_plate_thickness"))
    gap_width = float(_ensure_value(gap_width, component_id=component_id, name="yoke_gap_width"))
    slot_depth = float(_ensure_value(slot_depth, component_id=component_id, name="yoke_slot_depth"))
    if axle_inset is None:
        axle_inset = max(8.0, 0.5 * slot_depth)
    axle_inset = float(_ensure_value(axle_inset, component_id=component_id, name="axle_inset_mm"))
    if distal_bore_diameter is not None:
        distal_bore_diameter = float(_ensure_value(distal_bore_diameter, component_id=component_id, name="distal_bore_diameter"))
        slot_depth = max(slot_depth, axle_inset + (0.5 * distal_bore_diameter) + 2.0)

    total_thickness = max(thickness, (2.0 * plate_thickness) + gap_width)
    root_web_thickness = min(max(root_web_thickness, 0.5), total_thickness)
    slot_depth = min(slot_depth, max(4.0, length - 2.0))
    half_length = length / 2.0
    gap_half_thickness = max(0.5 * gap_width, 0.5)
    total_half_thickness = max(0.5 * total_thickness, 0.5)
    root_web_half_thickness = max(0.5 * root_web_thickness, 0.25)
    plate_half_thickness = max(0.5 * plate_thickness, 0.25)
    bridge_length = max(4.0, min(max(plate_thickness + 1.0, 4.0), max(4.0, slot_depth - 1.0)))
    if isinstance(hub_slot_insert_depth, (int, float)) and float(hub_slot_insert_depth) > 0.0:
        bridge_length = max(bridge_length, min(slot_depth - 0.5, max(4.0, float(hub_slot_insert_depth) + 1.0)))
    overlap_length = 0.25
    root_web_length = max(4.0, length - slot_depth + overlap_length)
    root_web_center_x = -half_length + (0.5 * root_web_length)
    bridge_center_x = half_length - slot_depth - (0.5 * bridge_length)
    distal_plate_length = max(bridge_length + 2.0, slot_depth + bridge_length + overlap_length)
    distal_plate_center_x = half_length - (0.5 * distal_plate_length)
    top_plate_plane_offset = gap_half_thickness + plate_half_thickness
    bottom_plate_plane_offset = -(gap_half_thickness + plate_half_thickness)

    stable_body_var = _make_capture_var(prefix, "body_id")
    root_web_sketch_var = _make_capture_var(prefix, "yoke_root_web_sketch_id")
    root_web_profile_var = _make_capture_var(prefix, "yoke_root_web_profile_id")
    bridge_sketch_var = _make_capture_var(prefix, "yoke_bridge_sketch_id")
    bridge_profile_var = _make_capture_var(prefix, "yoke_bridge_profile_id")
    top_plate_plane_var = _make_capture_var(prefix, "yoke_top_plate_plane_id")
    top_plate_sketch_var = _make_capture_var(prefix, "yoke_top_plate_sketch_id")
    top_plate_profile_var = _make_capture_var(prefix, "yoke_top_plate_profile_id")
    bottom_plate_plane_var = _make_capture_var(prefix, "yoke_bottom_plate_plane_id")
    bottom_plate_sketch_var = _make_capture_var(prefix, "yoke_bottom_plate_sketch_id")
    bottom_plate_profile_var = _make_capture_var(prefix, "yoke_bottom_plate_profile_id")

    steps: List[Dict[str, Any]] = [
        {
            "id": _make_step_id(prefix, "create_yoke_root_web_sketch"),
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "name": f"{component_id}_yoke_root_web_sketch",
                "plane": {"type": "XY"},
            },
            "capture": {"vars": {root_web_sketch_var: "sketch_id"}},
            "depends_on": [depends_on_step_id],
            "description": f"Create root web sketch for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_root_web_profile"),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{root_web_sketch_var}}}",
                "center": {"x": root_web_center_x, "y": 0.0},
                "width": root_web_length,
                "height": width,
            },
            "capture": {"vars": {root_web_profile_var: "profile_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_root_web_sketch")],
            "description": f"Create root web profile for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_root_web_extrude"),
            "function": "EXTRUDE_TWO_SIDES",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{root_web_profile_var}}}",
                "distance_one_mm": root_web_half_thickness,
                "distance_two_mm": root_web_half_thickness,
                "operation": "new_body",
                "name": f"{component_id}_yoke_root_web",
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [_make_step_id(prefix, "yoke_root_web_profile")],
            "description": f"Create root web body for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "create_yoke_bridge_sketch"),
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "name": f"{component_id}_yoke_bridge_sketch",
                "plane": {"type": "XY"},
            },
            "capture": {"vars": {bridge_sketch_var: "sketch_id"}},
            "depends_on": [_make_step_id(prefix, "yoke_root_web_extrude")],
            "description": f"Create bridge sketch for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_bridge_profile"),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{bridge_sketch_var}}}",
                "center": {"x": bridge_center_x, "y": 0.0},
                "width": bridge_length,
                "height": width,
            },
            "capture": {"vars": {bridge_profile_var: "profile_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_bridge_sketch")],
            "description": f"Create bridge profile for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_bridge_extrude"),
            "function": "EXTRUDE_TWO_SIDES",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{bridge_profile_var}}}",
                "distance_one_mm": total_half_thickness,
                "distance_two_mm": total_half_thickness,
                "operation": "join",
                "name": f"{component_id}_yoke_bridge",
            },
            "depends_on": [_make_step_id(prefix, "yoke_bridge_profile")],
            "description": f"Join distal bridge body for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "create_yoke_top_plate_plane"),
            "function": "CREATE_OFFSET_CONSTRUCTION_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "base_plane": {"type": "XY"},
                "offset_mm": top_plate_plane_offset,
                "name": f"{component_id}_yoke_top_plate_plane",
            },
            "capture": {"vars": {top_plate_plane_var: "plane_id"}},
            "depends_on": [_make_step_id(prefix, "yoke_bridge_extrude")],
            "description": f"Create top plate plane for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "create_yoke_top_plate_sketch"),
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "name": f"{component_id}_yoke_top_plate_sketch",
                "plane": {"type": "OFFSET", "plane_id": f"${{{top_plate_plane_var}}}"},
            },
            "capture": {"vars": {top_plate_sketch_var: "sketch_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_top_plate_plane")],
            "description": f"Create top plate sketch for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_top_plate_profile"),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{top_plate_sketch_var}}}",
                "center": {"x": distal_plate_center_x, "y": 0.0},
                "width": distal_plate_length,
                "height": width,
            },
            "capture": {"vars": {top_plate_profile_var: "profile_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_top_plate_sketch")],
            "description": f"Create top plate profile for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_top_plate_extrude"),
            "function": "EXTRUDE_TWO_SIDES",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{top_plate_profile_var}}}",
                "distance_one_mm": plate_half_thickness,
                "distance_two_mm": plate_half_thickness,
                "operation": "join",
                "name": f"{component_id}_yoke_top_plate",
            },
            "depends_on": [_make_step_id(prefix, "yoke_top_plate_profile")],
            "description": f"Join top yoke plate for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "create_yoke_bottom_plate_plane"),
            "function": "CREATE_OFFSET_CONSTRUCTION_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "base_plane": {"type": "XY"},
                "offset_mm": bottom_plate_plane_offset,
                "name": f"{component_id}_yoke_bottom_plate_plane",
            },
            "capture": {"vars": {bottom_plate_plane_var: "plane_id"}},
            "depends_on": [_make_step_id(prefix, "yoke_top_plate_extrude")],
            "description": f"Create bottom plate plane for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "create_yoke_bottom_plate_sketch"),
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "name": f"{component_id}_yoke_bottom_plate_sketch",
                "plane": {"type": "OFFSET", "plane_id": f"${{{bottom_plate_plane_var}}}"},
            },
            "capture": {"vars": {bottom_plate_sketch_var: "sketch_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_bottom_plate_plane")],
            "description": f"Create bottom plate sketch for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_bottom_plate_profile"),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{bottom_plate_sketch_var}}}",
                "center": {"x": distal_plate_center_x, "y": 0.0},
                "width": distal_plate_length,
                "height": width,
            },
            "capture": {"vars": {bottom_plate_profile_var: "profile_id"}},
            "depends_on": [_make_step_id(prefix, "create_yoke_bottom_plate_sketch")],
            "description": f"Create bottom plate profile for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_bottom_plate_extrude"),
            "function": "EXTRUDE_TWO_SIDES",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "profile_id": f"${{{bottom_plate_profile_var}}}",
                "distance_one_mm": plate_half_thickness,
                "distance_two_mm": plate_half_thickness,
                "operation": "join",
                "name": f"{component_id}_yoke_bottom_plate",
            },
            "depends_on": [_make_step_id(prefix, "yoke_bottom_plate_profile")],
            "description": f"Join bottom yoke plate for {component_id}",
        },
        {
            "id": _make_step_id(prefix, "yoke_body_refresh"),
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {"component_id": f"${{{component_id_var}}}"},
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [_make_step_id(prefix, "yoke_bottom_plate_extrude")],
            "metadata": {
                "component_id": component_id,
                "source_feature": "yoke_additive_build",
                "reason": "refresh_body_after_join",
            },
        },
    ]

    if distal_bore_diameter is not None and distal_bore_diameter > 0.0:
        bore_center_x = half_length - axle_inset
        bore_radius = max(0.5 * distal_bore_diameter, 0.5)
        bore_half_extent = total_half_thickness + 0.5
        bore_sketch_id_var = _make_capture_var(prefix, "yoke_bore_sketch_id")
        bore_profile_var = _make_capture_var(prefix, "yoke_bore_profile_id")
        steps.extend(
            [
                {
                    "id": _make_step_id(prefix, "create_yoke_bore_sketch"),
                    "function": "CREATE_SKETCH_ON_PLANE",
                    "inputs": {
                        "component_id": f"${{{component_id_var}}}",
                        "name": f"{component_id}_yoke_bore_sketch",
                        "plane": {"type": "XY"},
                    },
                    "capture": {"vars": {bore_sketch_id_var: "sketch_id"}},
                    "depends_on": [_make_step_id(prefix, "yoke_body_refresh")],
                    "description": f"Create yoke bore sketch for {component_id}",
                },
                {
                    "id": _make_step_id(prefix, "yoke_bore_profile"),
                    "function": "SKETCH_CIRCLE",
                    "inputs": {
                        "sketch_id": f"${{{bore_sketch_id_var}}}",
                        "center": {"x": bore_center_x, "y": 0.0},
                        "radius": bore_radius,
                    },
                    "capture": {"vars": {bore_profile_var: "profile_id"}},
                    "depends_on": [_make_step_id(prefix, "create_yoke_bore_sketch")],
                    "description": f"Create yoke bore profile for {component_id}",
                },
                {
                    "id": _make_step_id(prefix, "yoke_bore_cut"),
                    "function": "EXTRUDE_TWO_SIDES",
                    "inputs": {
                        "component_id": f"${{{component_id_var}}}",
                        "profile_id": f"${{{bore_profile_var}}}",
                        "distance_one_mm": bore_half_extent,
                        "distance_two_mm": bore_half_extent,
                        "operation": "cut",
                        "body_id": f"${{{stable_body_var}}}",
                        "name": f"{component_id}_yoke_bore_cut",
                    },
                    "depends_on": [_make_step_id(prefix, "yoke_bore_profile")],
                    "description": f"Cut axle bore through yoke plates for {component_id}",
                },
                {
                    "id": _make_step_id(prefix, "yoke_bore_refresh_body"),
                    "function": "GET_SINGLE_BODY_ID",
                    "inputs": {"component_id": f"${{{component_id_var}}}"},
                    "capture": {"vars": {stable_body_var: "body_id"}},
                    "depends_on": [_make_step_id(prefix, "yoke_bore_cut")],
                    "metadata": {
                        "component_id": component_id,
                        "source_feature": "yoke_bore_cut",
                        "reason": "refresh_body_after_cut",
                    },
                },
            ]
        )

    return steps

def _build_hub_radial_slot_steps(
    *,
    component_id: str,
    component_id_var: str,
    allowed: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
    prefer_placeholders: bool,
    depends_on_step_id: str,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "CREATE_OFFSET_CONSTRUCTION_PLANE")
    _require_function(allowed, "CREATE_SKETCH_ON_PLANE")
    _require_function(allowed, "SKETCH_POLYLINE")
    _require_function(allowed, "EXTRUDE_TWO_SIDES")
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    params = execution_params or {}
    radial_slots = params.get("radial_slots") if isinstance(params.get("radial_slots"), list) else []
    if not radial_slots:
        return []

    thickness = _resolve_param_value(
        _pick_param(params, "thickness", "thickness_param", "width_param"),
        param_names=("thickness", "thickness_param", "width_param"),
        component_params=execution_params,
        strategy={"parameter_values": params},
        prefer_placeholders=prefer_placeholders,
    )
    radius = _resolve_param_value(
        _pick_param(params, "radius", "radius_param", "outer_radius", "outer_radius_param"),
        param_names=("radius", "radius_param", "outer_radius", "outer_radius_param"),
        component_params=execution_params,
        strategy={"parameter_values": params},
        prefer_placeholders=prefer_placeholders,
    )
    if radius is None:
        diameter = _resolve_param_value(
            _pick_param(params, "diameter", "diameter_param", "outer_diameter", "outer_diameter_param"),
            param_names=("diameter", "diameter_param", "outer_diameter", "outer_diameter_param"),
            component_params=execution_params,
            strategy={"parameter_values": params},
            prefer_placeholders=prefer_placeholders,
        )
        radius = float(diameter) * 0.5 if isinstance(diameter, (int, float)) else None
    thickness = float(_ensure_value(thickness, component_id=component_id, name="thickness"))
    radius = float(_ensure_value(radius, component_id=component_id, name="radius"))

    prefix = _component_prefix(component_id)
    stable_body_var = _make_capture_var(prefix, "body_id")
    slot_plane_var = _make_capture_var(prefix, "radial_slot_midplane_id")
    slot_plane_step_id = _make_step_id(prefix, "create_radial_slot_midplane")
    steps: List[Dict[str, Any]] = [
        {
            "id": slot_plane_step_id,
            "function": "CREATE_OFFSET_CONSTRUCTION_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "base_plane": {"type": "XY"},
                "offset_mm": 0.5 * thickness,
                "name": f"{component_id}_radial_slot_midplane",
            },
            "capture": {"vars": {slot_plane_var: "plane_id"}},
            "depends_on": [depends_on_step_id],
            "description": f"Create radial slot midplane for {component_id}",
        }
    ]
    previous_dep = slot_plane_step_id

    for slot_index, slot in enumerate(radial_slots, start=1):
        if not isinstance(slot, Mapping):
            continue
        slot_width = float(slot.get("slot_width") or 0.0)
        slot_depth = float(slot.get("slot_depth") or 0.0)
        slot_height = float(slot.get("slot_height") or 0.0)
        angle_deg = float(slot.get("angle_deg") or 0.0)
        if slot_width <= 0.0 or slot_depth <= 0.0:
            continue
        if slot_height <= 0.0:
            cap_thickness = max(2.5, min(4.0, 0.25 * thickness))
            slot_height = max(2.0, min(max(2.0, thickness - 2.0 * cap_thickness), slot_width + 1.0))
        slot_height = min(slot_height, max(1.0, thickness - 0.5))
        theta = math.radians(angle_deg)
        ux, uy = math.cos(theta), math.sin(theta)
        vx, vy = -uy, ux
        center_radius = max(0.0, radius - 0.5 * slot_depth)
        cx = ux * center_radius
        cy = uy * center_radius
        half_depth = 0.5 * slot_depth
        half_width = 0.5 * slot_width
        cut_half_height = max(0.5 * slot_height, 0.5)
        points = [
            {"x": cx - half_depth * ux - half_width * vx, "y": cy - half_depth * uy - half_width * vy},
            {"x": cx + half_depth * ux - half_width * vx, "y": cy + half_depth * uy - half_width * vy},
            {"x": cx + half_depth * ux + half_width * vx, "y": cy + half_depth * uy + half_width * vy},
            {"x": cx - half_depth * ux + half_width * vx, "y": cy - half_depth * uy + half_width * vy},
        ]
        sketch_id_var = _make_capture_var(prefix, f"radial_slot_{slot_index}_sketch_id")
        profile_var = _make_capture_var(prefix, f"radial_slot_{slot_index}_profile_id")
        sketch_step_id = _make_step_id(prefix, f"create_radial_slot_{slot_index}_sketch")
        profile_step_id = _make_step_id(prefix, f"radial_slot_{slot_index}_profile")
        cut_step_id = _make_step_id(prefix, f"radial_slot_{slot_index}_cut")
        refresh_step_id = _make_step_id(prefix, f"radial_slot_{slot_index}_refresh_body")
        steps.extend([
            {
                "id": sketch_step_id,
                "function": "CREATE_SKETCH_ON_PLANE",
                "inputs": {
                    "component_id": f"${{{component_id_var}}}",
                    "name": f"{component_id}_radial_slot_{slot_index}_sketch",
                    "plane": {"type": "OFFSET", "plane_id": f"${{{slot_plane_var}}}"},
                },
                "capture": {"vars": {sketch_id_var: "sketch_id"}},
                "depends_on": [previous_dep],
                "description": f"Create radial slot sketch {slot_index} for {component_id}",
            },
            {
                "id": profile_step_id,
                "function": "SKETCH_POLYLINE",
                "inputs": {
                    "sketch_id": f"${{{sketch_id_var}}}",
                    "points": points,
                    "closed": True,
                },
                "capture": {"vars": {profile_var: "profile_id"}},
                "depends_on": [sketch_step_id],
                "description": f"Create radial slot profile {slot_index} for {component_id}",
            },
            {
                "id": cut_step_id,
                "function": "EXTRUDE_TWO_SIDES",
                "inputs": {
                    "component_id": f"${{{component_id_var}}}",
                    "profile_id": f"${{{profile_var}}}",
                    "distance_one_mm": cut_half_height,
                    "distance_two_mm": cut_half_height,
                    "operation": "cut",
                    "body_id": f"${{{stable_body_var}}}",
                    "name": f"{component_id}_radial_slot_{slot_index}_cut",
                },
                "depends_on": [profile_step_id],
                "description": f"Cut side-entry radial slot {slot_index} into {component_id}",
            },
            {
                "id": refresh_step_id,
                "function": "GET_SINGLE_BODY_ID",
                "inputs": {"component_id": f"${{{component_id_var}}}"},
                "capture": {"vars": {stable_body_var: "body_id"}},
                "depends_on": [cut_step_id],
                "metadata": {
                    "component_id": component_id,
                    "source_feature": f"radial_slot_{slot_index}_cut",
                    "reason": "refresh_body_after_cut",
                },
            },
        ])
        previous_dep = refresh_step_id

    return steps


def _compile_component_steps(
    *,
    component_id: str,
    strategy: Mapping[str, Any],
    allowed: Mapping[str, Any],
    execution_params: Mapping[str, Any] | None,
    prefer_placeholders: bool,
    root_transform_mm: Mapping[str, Any] | None = None,
    parent_component_ref: str | None = None,
) -> List[Dict[str, Any]]:
    prefix = _component_prefix(component_id)
    steps: List[Dict[str, Any]] = []

    _require_function(allowed, "CREATE_COMPONENT")
    _require_function(allowed, "ACTIVATE_COMPONENT")
    _require_function(allowed, "CREATE_SKETCH_ON_PLANE")

    create_step_id = _make_step_id(prefix, "create_component")
    component_id_var = _make_capture_var(prefix, "component_id")
    occurrence_id_var = _make_capture_var(prefix, "occurrence_id")

    create_inputs: Dict[str, Any] = {
        "name": component_id,
        # All components are placed as direct children of root 闂?no nesting.
        # Fusion 360 silently ignores transform2 on nested occurrences,
        # so the plan must keep every component at root level.
        "parent_component_id": None,
    }
    seed_transform = _seed_create_transform(root_transform_mm)
    if isinstance(seed_transform, Mapping):
        create_inputs["transform"] = dict(seed_transform)

    steps.append(
        {
            "id": create_step_id,
            "function": "CREATE_COMPONENT",
            "inputs": create_inputs,
            "capture": {"vars": {component_id_var: "component_id", occurrence_id_var: "occurrence_id"}},
            "description": f"Create component {component_id}",
        }
    )

    activate_step_id = _make_step_id(prefix, "activate_component")
    steps.append(
        {
            "id": activate_step_id,
            "function": "ACTIVATE_COMPONENT",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
            },
            "depends_on": [create_step_id],
            "description": f"Activate component {component_id}",
        }
    )

    profile_type = strategy.get("profile_type")
    primary_method_raw = strategy.get("primary_method")
    construction_method_raw = strategy.get("construction_method")
    if not isinstance(profile_type, str):
        raise ValueError(f"Missing profile_type for component '{component_id}'.")

    method_from_primary: str | None = None
    if isinstance(primary_method_raw, str) and primary_method_raw:
        normalized_primary = primary_method_raw.upper()
        method_from_primary = {
            "EXTRUDE": "extrude",
            "REVOLVE": "revolve",
            "LOFT": "loft",
            "SWEEP": "sweep",
        }.get(normalized_primary)
        if method_from_primary is None:
            raise ValueError(
                f"Unsupported primary_method '{primary_method_raw}' for component '{component_id}'."
            )

    method_from_construction: str | None = None
    if isinstance(construction_method_raw, str) and construction_method_raw:
        method_from_construction = construction_method_raw.strip().lower()

    if method_from_primary and method_from_construction and method_from_primary != method_from_construction:
        raise ValueError(
            f"Method mismatch for component '{component_id}': primary_method='{primary_method_raw}' "
            f"but construction_method='{construction_method_raw}'."
        )

    construction_method = method_from_primary or method_from_construction
    if not isinstance(construction_method, str) or not construction_method:
        raise ValueError(
            f"Missing modeling method for component '{component_id}'. Expected modeling_strategy.primary_method."
        )

    allowed_profiles = {
        "circle",
        "annular",
        "half_profile",
        "tire_profile",
        "rectangle",
        "fork_profile",
        "yoke_profile",
        "macro_profile",
    }
    if profile_type not in allowed_profiles:
        raise ValueError(f"Illegal profile_type for component '{component_id}': {profile_type}")

    if profile_type == "yoke_profile":
        steps.extend(
            _build_yoke_component_steps(
                component_id=component_id,
                strategy=strategy,
                component_id_var=component_id_var,
                allowed=allowed,
                execution_params=execution_params,
                prefer_placeholders=prefer_placeholders,
                depends_on_step_id=activate_step_id,
            )
        )
        return steps

    sketch_plane_type = "XZ" if construction_method == "revolve" else "XY"
    sketch_step_id = _make_step_id(prefix, "create_sketch")
    sketch_id_var = _make_capture_var(prefix, "sketch_id")
    steps.append(
        {
            "id": sketch_step_id,
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": f"${{{component_id_var}}}",
                "name": f"{component_id}_sketch",
                "plane": {"type": sketch_plane_type},
            },
            "capture": {"vars": {sketch_id_var: "sketch_id"}},
            "depends_on": [activate_step_id],
            "description": f"Create sketch for {component_id}",
        }
    )

    profile_steps, profile_id_var = _build_profile_steps(
        component_id=component_id,
        profile_type=profile_type,
        strategy=strategy,
        sketch_id_var=sketch_id_var,
        allowed=allowed,
        execution_params=execution_params,
        prefer_placeholders=prefer_placeholders,
    )

    for step in profile_steps:
        if "depends_on" not in step:
            step["depends_on"] = [sketch_step_id]

    steps.extend(profile_steps)

    axis_spec = {"type": "Z"}

    feature_step = _build_feature_step(
        component_id=component_id,
        construction_method=construction_method,
        strategy=strategy,
        profile_id_var=profile_id_var,
        component_id_var=component_id_var,
        allowed=allowed,
        execution_params=execution_params,
        axis_spec=axis_spec,
        prefer_placeholders=prefer_placeholders,
    )

    feature_step["depends_on"] = [profile_steps[-1]["id"]]
    steps.append(feature_step)

    hub_slot_steps = _build_hub_radial_slot_steps(
        component_id=component_id,
        component_id_var=component_id_var,
        allowed=allowed,
        execution_params=execution_params,
        prefer_placeholders=prefer_placeholders,
        depends_on_step_id=feature_step["id"],
    )
    steps.extend(hub_slot_steps)

    return steps


def _compile_container_component_step(
    *,
    component_id: str,
    parent_component_ref: str | None = None,
    root_transform_mm: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    prefix = _component_prefix(component_id)
    component_id_var = _make_capture_var(prefix, "component_id")
    occurrence_id_var = _make_capture_var(prefix, "occurrence_id")
    create_inputs: Dict[str, Any] = {
        "name": component_id,
        # All components at root 闂?no nesting (Fusion transform2 issue).
        "parent_component_id": None,
    }
    seed_transform = _seed_create_transform(root_transform_mm)
    if isinstance(seed_transform, Mapping):
        create_inputs["transform"] = dict(seed_transform)
    return {
        "id": _make_step_id(prefix, "create_component"),
        "function": "CREATE_COMPONENT",
        "inputs": create_inputs,
        "capture": {"vars": {component_id_var: "component_id", occurrence_id_var: "occurrence_id"}},
        "description": f"Create container component {component_id}",
    }


def run(*, run_dir: Path, round_index: int) -> Dict[str, Any]:
    shape_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    if not shape_path.exists():
        raise FileNotFoundError(f"Shape realization not found: {shape_path}")

    shape = _read_json(shape_path)
    if not isinstance(shape, Mapping):
        raise ValueError("shape_realization must be an object")

    realizations = _extract_realizations(shape)
    if not realizations:
        raise ValueError("shape_realization must provide non-empty parts or component_realizations")

    registry_path = Path("functions") / "functions.json"
    allowed = _load_function_registry(registry_path)

    skip_components = _load_standard_part_bindings(run_dir)

    # Load KG to extract component dimensions and hierarchy
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    kg_dims_by_id: Dict[str, Mapping[str, Any]] = {}
    component_parent_by_id: Dict[str, str | None] = {}
    component_modeling_policy_by_id: Dict[str, str] = {}
    component_definition_by_id: Dict[str, str] = {}
    pattern_definition_fallback_by_id: Dict[str, str] = {}

    def _collect_pattern_fallback(pattern_items: Any) -> None:
        if not isinstance(pattern_items, list):
            return
        for pattern in pattern_items:
            if not isinstance(pattern, Mapping):
                continue
            if pattern.get("type") != "rotational_symmetry":
                continue
            prototype = pattern.get("prototype")
            if not isinstance(prototype, str) or not prototype:
                continue
            component_ids = pattern.get("component_ids")
            if not isinstance(component_ids, list):
                component_ids = pattern.get("instances") if isinstance(pattern.get("instances"), list) else []
            for cid in component_ids:
                if isinstance(cid, str) and cid and not _is_definition_sharing_blocked_component(cid):
                    pattern_definition_fallback_by_id[cid] = prototype

    _collect_pattern_fallback(shape.get("patterns"))

    if kg_path.exists():
        kg = _read_json(kg_path)
        if isinstance(kg, Mapping):
            metadata = kg.get("metadata") if isinstance(kg.get("metadata"), Mapping) else {}
            execution_roles = metadata.get("component_execution_roles") if isinstance(metadata.get("component_execution_roles"), Mapping) else {}
            for comp_id, role in execution_roles.items():
                if isinstance(comp_id, str) and str(role).strip().lower() == "standard_part_insert_only":
                    skip_components.add(comp_id)
            _collect_pattern_fallback(kg.get("patterns"))
            components = kg.get("components")
            if isinstance(components, list):
                for comp in components:
                    if isinstance(comp, Mapping):
                        comp_id = comp.get("id")
                        dims = comp.get("dimensions")
                        if isinstance(comp_id, str) and isinstance(dims, Mapping):
                            kg_dims_by_id[comp_id] = dims
                        if isinstance(comp_id, str):
                            parent_id = comp.get("position_parent")
                            component_parent_by_id[comp_id] = parent_id if isinstance(parent_id, str) and parent_id else None
                            policy = comp.get("modeling_policy")
                            if isinstance(policy, str) and policy.strip():
                                component_modeling_policy_by_id[comp_id] = policy.strip().lower()
                            if _is_definition_sharing_blocked_component(comp_id):
                                definition_id = comp_id
                            else:
                                definition_id = _normalize_definition_id(
                                    component_id=comp_id,
                                    value=(
                                        comp.get("definition_id")
                                        if isinstance(comp.get("definition_id"), str)
                                        else comp.get("instanced_from")
                                    ),
                                )
                            component_definition_by_id[comp_id] = definition_id

    for cid, proto in pattern_definition_fallback_by_id.items():
        if not isinstance(cid, str) or not isinstance(proto, str) or not cid or not proto:
            continue
        if cid not in component_definition_by_id:
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=proto)
            continue
        current = component_definition_by_id.get(cid)
        if not isinstance(current, str) or not current.strip() or current == cid:
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=proto)

    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        if not isinstance(cid, str) or not cid:
            continue
        if _is_definition_sharing_blocked_component(cid):
            item_definition_id = cid
        else:
            item_definition_id = _normalize_definition_id(
                component_id=cid,
                value=(
                    item.get("definition_id")
                    if isinstance(item.get("definition_id"), str)
                    else item.get("instanced_from")
                ),
            )
        fallback_proto = pattern_definition_fallback_by_id.get(cid)
        if cid not in component_definition_by_id:
            if isinstance(fallback_proto, str) and fallback_proto and item_definition_id == cid:
                component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=fallback_proto)
            else:
                component_definition_by_id[cid] = item_definition_id
            continue

        current = component_definition_by_id.get(cid)
        if isinstance(fallback_proto, str) and fallback_proto and (not isinstance(current, str) or current == cid):
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=fallback_proto)

    realization_by_id: Dict[str, Mapping[str, Any]] = {}
    for item in realizations:
        if isinstance(item, Mapping):
            cid = item.get("component_id")
            if isinstance(cid, str) and cid:
                realization_by_id[cid] = item
    component_strategy_by_id: Dict[str, Mapping[str, Any]] = {
        cid: item.get("modeling_strategy")
        for cid, item in realization_by_id.items()
        if isinstance(item.get("modeling_strategy"), Mapping)
    }
    ordered_realization_ids: List[str] = []
    perm_mark: set[str] = set()
    temp_mark: set[str] = set()

    def _dfs_order(cid: str) -> None:
        if cid in perm_mark:
            return
        if cid in temp_mark:
            return
        temp_mark.add(cid)
        parent_id = component_parent_by_id.get(cid)
        if isinstance(parent_id, str) and parent_id in realization_by_id:
            _dfs_order(parent_id)
        temp_mark.remove(cid)
        perm_mark.add(cid)
        ordered_realization_ids.append(cid)

    for cid in sorted(realization_by_id.keys()):
        _dfs_order(cid)

    ordered_realizations: List[Mapping[str, Any]] = [realization_by_id[cid] for cid in ordered_realization_ids if cid in realization_by_id]
    ordered_set = set(ordered_realization_ids)
    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        if isinstance(cid, str) and cid in ordered_set:
            continue
        ordered_realizations.append(item)
    realizations = ordered_realizations

    steps: List[Dict[str, Any]] = []
    emitter = StepEmitter(allowed_registry=allowed, sink=steps)

    _require_function(allowed, "CREATE_COMPONENT")
    root_transforms = _extract_root_transforms(shape)

    container_ids_set: set[str] = set()
    for maybe_parent in component_parent_by_id.values():
        if isinstance(maybe_parent, str) and maybe_parent and maybe_parent not in realization_by_id:
            if component_modeling_policy_by_id.get(maybe_parent) in {"container_only", "reference_only"}:
                continue
            parent_definition_id = component_definition_by_id.get(maybe_parent, maybe_parent)
            if isinstance(parent_definition_id, str) and parent_definition_id and parent_definition_id != maybe_parent:
                continue
            container_ids_set.add(maybe_parent)

    container_ids = sorted(container_ids_set)
    perm_cont: set[str] = set()
    temp_cont: set[str] = set()
    ordered_containers: List[str] = []

    def _dfs_container(cid: str) -> None:
        if cid in perm_cont:
            return
        if cid in temp_cont:
            return
        temp_cont.add(cid)
        parent_id = component_parent_by_id.get(cid)
        if isinstance(parent_id, str) and parent_id in container_ids_set:
            _dfs_container(parent_id)
        temp_cont.remove(cid)
        perm_cont.add(cid)
        ordered_containers.append(cid)

    for cid in container_ids:
        _dfs_container(cid)

    for cid in ordered_containers:
        emitter.emit_step(
            _compile_container_component_step(
                component_id=cid,
                root_transform_mm=root_transforms.get(cid),
            )
        )

    _validate_shape_realization_inputs(shape)

    drift_report = validate_shape_realization_contract(shape)
    preflight_interface_manifest = shape.get("interface_manifest") if isinstance(shape.get("interface_manifest"), Mapping) else None

    if isinstance(preflight_interface_manifest, Mapping):
        name_index = _build_interface_name_index(preflight_interface_manifest)
        interface_violations = _validate_feature_interface_refs(
            shape=shape,
            interface_name_index=name_index,
        )
        filtered_interface_violations: List[Dict[str, Any]] = []
        for violation in interface_violations:
            if not isinstance(violation, Mapping):
                continue
            details = violation.get("details") if isinstance(violation.get("details"), Mapping) else {}
            iface_comp = details.get("interface_component_id")
            if (
                isinstance(iface_comp, str)
                and component_modeling_policy_by_id.get(iface_comp) == "container_only"
                and violation.get("rule") == "feature_interface_not_in_manifest"
            ):
                continue
            filtered_interface_violations.append(dict(violation))
        interface_violations = filtered_interface_violations
        if interface_violations:
            existing = drift_report.get("violations")
            if isinstance(existing, list):
                existing.extend(interface_violations)
            else:
                drift_report["violations"] = interface_violations

            summary = drift_report.get("summary")
            if isinstance(summary, dict):
                current_count = summary.get("violations_count")
                base_count = int(current_count) if isinstance(current_count, int) else 0
                summary["violations_count"] = base_count + len(interface_violations)
    elif isinstance(shape.get("parts"), list):
        missing_manifest_violation = {
            "component_id": "<shape_realization>",
            "path": "shape_realization.interface_manifest",
            "rule": "interface_manifest_unavailable",
            "message": "Cannot validate feature interface references because shape_realization.interface_manifest is missing",
        }
        existing = drift_report.get("violations")
        if isinstance(existing, list):
            existing.append(missing_manifest_violation)
        else:
            drift_report["violations"] = [missing_manifest_violation]

        summary = drift_report.get("summary")
        if isinstance(summary, dict):
            current_count = summary.get("violations_count")
            base_count = int(current_count) if isinstance(current_count, int) else 0
            summary["violations_count"] = base_count + 1

    summary = drift_report.get("summary") if isinstance(drift_report, Mapping) else None
    violation_count = 0
    if isinstance(summary, Mapping):
        count = summary.get("violations_count")
        if isinstance(count, int):
            violation_count = count
    if violation_count == 0:
        violations = drift_report.get("violations") if isinstance(drift_report, Mapping) else None
        if isinstance(violations, list):
            violation_count = len(violations)
    if violation_count > 0:
        drift_path = run_dir / "planning" / "errors" / "contract_drift.json"
        _write_json(drift_path, drift_report)
        raise ValueError(
            f"Shape realization contract drift detected ({violation_count} violations). "
            f"Details written to: {drift_path}"
        )

    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        component_id = item.get("component_id")
        strategy = item.get("modeling_strategy")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(strategy, Mapping):
            raise ValueError(f"Missing modeling_strategy for component '{component_id}'.")

        definition_id = component_definition_by_id.get(component_id, component_id)
        if definition_id != component_id:
            continue

        if component_id in skip_components or _is_standard_part_insert_only_strategy(strategy):
            # Standard parts are inserted exclusively via standard-parts injection.
            # Never compile definition geometry for library-driven insert-only parts.
            continue

        collection_info = strategy.get("collection_info")
        resolution = item.get("parameter_resolution") if isinstance(item, Mapping) else None
        execution_params = _derive_execution_params(
            strategy,
            resolution if isinstance(resolution, Mapping) else None,
        )
        execution_params = _prefer_feature_authored_shaft_bore_base_solid(
            realization=item,
            strategy=strategy,
            execution_params=execution_params,
        )
        
        # Add KG dimensions to execution_params for this component
        # Use standard parameter names (with _param suffix for dimension resolution to work)
        kg_dims = kg_dims_by_id.get(component_id)
        if isinstance(kg_dims, Mapping):
            for dim_key, dim_value in kg_dims.items():
                if isinstance(dim_key, str) and isinstance(dim_value, (int, float)):
                    # KG dimensions are fallback-only. Do not clobber Agent3a's
                    # upgraded realization params (for example hub thickness widened
                    # to accommodate opposed bearing seats).
                    param_name = f"{dim_key}_param"
                    execution_params.setdefault(param_name, float(dim_value))
        
        prefer_placeholders = False
        if isinstance(collection_info, Mapping) and collection_info.get("is_collection"):
            count = collection_info.get("individual_count")
            if isinstance(count, int) and count > 1:
                for i in range(1, count + 1):
                    coll_id = f"{component_id}_{i}"
                    if coll_id in skip_components:
                        continue
                    coll_definition_id = component_definition_by_id.get(coll_id, coll_id)
                    if coll_definition_id != coll_id:
                        continue
                    coll_parent_id = component_parent_by_id.get(coll_id) or component_parent_by_id.get(component_id)
                    coll_parent_ref = None
                    if isinstance(coll_parent_id, str) and coll_parent_id:
                        coll_parent_ref = f"${{{_make_capture_var(_component_prefix(coll_parent_id), 'component_id')}}}"
                    # Also add dimensions for collection members
                    coll_execution_params = dict(execution_params)
                    coll_kg_dims = kg_dims_by_id.get(coll_id)
                    if isinstance(coll_kg_dims, Mapping):
                        for dim_key, dim_value in coll_kg_dims.items():
                            if isinstance(dim_key, str) and isinstance(dim_value, (int, float)):
                                param_name = f"{dim_key}_param"
                                coll_execution_params.setdefault(param_name, float(dim_value))
                    emitter.emit_many(
                        _compile_component_steps(
                            component_id=coll_id,
                            strategy=strategy,
                            allowed=allowed,
                            execution_params=coll_execution_params,
                            prefer_placeholders=True,
                            root_transform_mm=root_transforms.get(coll_id) or root_transforms.get(component_id),
                            parent_component_ref=coll_parent_ref,
                        )
                    )
                continue

        parent_id = component_parent_by_id.get(component_id)
        parent_ref = None
        if isinstance(parent_id, str) and parent_id:
            parent_ref = f"${{{_make_capture_var(_component_prefix(parent_id), 'component_id')}}}"
        emitter.emit_many(
            _compile_component_steps(
                component_id=component_id,
                strategy=strategy,
                allowed=allowed,
                execution_params=execution_params,
                prefer_placeholders=prefer_placeholders,
                root_transform_mm=root_transforms.get(component_id),
                parent_component_ref=parent_ref,
            )
        )

    feature_plan = _extract_feature_plan(shape)
    recipe_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    placements_for_patch = feature_plan.get("connection_placements")
    if isinstance(placements_for_patch, list) and placements_for_patch:
        interface_manifest_for_features = shape.get("interface_manifest") if isinstance(shape.get("interface_manifest"), Mapping) else None
        if not isinstance(interface_manifest_for_features, Mapping):
            raise ValueError("shape_realization.interface_manifest is required for anchored feature compilation")
        recipe_index = _build_interface_recipe_index(interface_manifest_for_features)
    patch_steps, patch_warnings = _compile_feature_patch(
        feature_plan=feature_plan,
        allowed=allowed,
        skip_components=skip_components,
        interface_recipe_index=recipe_index,
        component_definition_by_id=component_definition_by_id,
        component_strategy_by_id=component_strategy_by_id,
    )
    if patch_steps:
        geom_last_id: str | None = None
        for step in reversed(steps):
            sid = step.get("id")
            if isinstance(sid, str) and sid:
                geom_last_id = sid
                break
        if geom_last_id is None:
            raise ValueError("geometry_plan has no valid step id; cannot attach feature patches")
        for step in patch_steps:
            deps = step.get("depends_on")
            if not isinstance(deps, list):
                step["depends_on"] = [geom_last_id]
        emitter.emit_many(patch_steps)

    fastener_intents = _collect_fastener_intents(feature_plan)

    _validate_compiled_step_functions(allowed=allowed, steps=steps)

    steps = inject_standard_parts_steps(
        steps,
        run_dir=run_dir,
        base_dep_step_id=_last_step_id(steps),
    )

    plan_id = "geometry_plan"
    md = shape.get("metadata")
    if isinstance(md, Mapping):
        base = md.get("plan_id")
        if isinstance(base, str) and base:
            plan_id = base.replace("_realization_", "_geometry_plan_")

    plan: Dict[str, Any] = {
        "metadata": {
            "plan_id": plan_id,
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "author": "compile_geometry_plan_3b",
            "capability_registry": {"path": "functions/functions.json"},
            "notes": "Deterministic compilation from shape realization strategies.",
            "fastener_intents": fastener_intents,
        },
        "steps": steps,
        "artifacts": {
            "source_shape_realization": f"planning/shape_realization_round_{round_index}.json",
        },
    }
    if patch_warnings:
        plan["artifacts"]["feature_patch_warnings"] = patch_warnings

    output_path = run_dir / "planning" / f"geometry_plan_round_{round_index}.json"
    _lint_unresolved_placeholders(steps)
    _write_json(output_path, plan)

    assembly_contract_path = run_dir / "planning" / f"geometry_semantics_assembly_round_{round_index}.json"
    modeling_semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    if assembly_contract_path.exists():
        assembly_contract = _read_json(assembly_contract_path)
        if isinstance(assembly_contract, Mapping):
            modeling_semantics: Mapping[str, Any] | None = None
            if modeling_semantics_path.exists():
                payload = _read_json(modeling_semantics_path)
                if isinstance(payload, Mapping):
                    modeling_semantics = payload
            interface_manifest = _make_interface_manifest(
                geometry_plan=plan,
                assembly_contract=assembly_contract,
                modeling_semantics=modeling_semantics,
                component_definition_by_id=component_definition_by_id,
            )
            allow_enrich = os.getenv("FUSION_ALLOW_EXECUTION_CONTEXT_ENRICH", "0").strip() == "1"
            if allow_enrich:
                interface_manifest, resolution_summary = _enrich_manifest_with_execution_context(
                    run_dir=run_dir,
                    manifest=interface_manifest,
                )
            else:
                resolution_summary = {
                    "status": "deferred",
                    "reason": "Execution-context enrichment disabled (set FUSION_ALLOW_EXECUTION_CONTEXT_ENRICH=1 to enable)",
                    "resolved_components": 0,
                }
            metadata = interface_manifest.get("metadata")
            if isinstance(metadata, dict):
                metadata["resolution"] = resolution_summary
            interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
            _write_json(interface_manifest_path, interface_manifest)

    print(f"[OK] Generated geometry plan: {output_path.name}")
    print(f"  - {len(steps)} steps")

    result = {"path": f"planning/geometry_plan_round_{round_index}.json"}
    interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
    if interface_manifest_path.exists():
        result["interface_manifest_path"] = f"planning/interface_manifest_round_{round_index}.json"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile geometry plan from shape realization strategies"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)

    args = parser.parse_args()
    result = run(run_dir=args.run_dir, round_index=args.round_index)
    print(f"Geometry plan: {result['path']}")


if __name__ == "__main__":
    main()








