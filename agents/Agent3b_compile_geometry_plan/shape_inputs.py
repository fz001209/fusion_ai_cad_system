"""Agent3b shape-realization input extraction, interface validation, and interface manifest generation."""

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

from .common import *

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
