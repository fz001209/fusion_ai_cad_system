"""Agent2 ??????????????."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from jsonschema import Draft202012Validator
from planning.pattern_solver import estimate_inner_radius, estimate_outer_radius, solve_circular_pattern, solve_linear_pattern
from tools.event_log import append_event
from validation.validate_geometry_semantics import validate_geometry_semantics_feasibility
from agents.common_utils import read_json as _read_json, write_json as _write_json
from agents.Agent1_requirement_to_kg.transform import (
    _ensure_arm_interface_requirements,
    _normalize_fastener_bundle_semantics,
    _rewire_container_connections,
    _sanitize_fastener_bundles,
    _sanitize_instancing_annotations,
    _validate_wheel_arm_connection_topology,
)

from .common import *

def _get_component_dimensions(comp: Dict[str, Any]) -> Dict[str, Any]:
    dims = comp.get("dimensions")
    params = comp.get("parameters")

    if dims is None and params is None:
        raise ValueError(f"Component '{comp.get('id')}' is missing dimensions.")

    if dims is None and isinstance(params, dict):
        dims = params
    if params is None and isinstance(dims, dict):
        params = dims

    if not isinstance(dims, dict) or not isinstance(params, dict):
        raise ValueError(
            f"Component '{comp.get('id')}' must provide dimensions/parameters as objects."
        )

    if dims != params:
        raise ValueError(
            f"Component '{comp.get('id')}' has mismatched dimensions vs parameters."
        )

    return dims


def _get_component_shape_semantics(comp: Dict[str, Any], dims: Dict[str, Any]) -> Dict[str, Any]:
    shape_semantics = comp.get("shape_semantics")
    comp_id = comp.get("id")

    if not isinstance(shape_semantics, dict) or not shape_semantics:
        raise ValueError(f"Component '{comp_id}' is missing shape_semantics.")

    for key, value in shape_semantics.items():
        if not key.endswith("_param"):
            continue
        if not isinstance(value, str) or value not in dims:
            raise ValueError(
                f"Component '{comp_id}' shape_semantics.{key} references missing dimension '{value}'."
            )

    return shape_semantics

def _build_interface_recipe(part: Dict[str, Any], iface: Dict[str, Any]) -> Dict[str, Any]:
    shape_raw = part.get("shape_semantics")
    shape: Dict[str, Any] = dict(shape_raw) if isinstance(shape_raw, dict) else {}
    dims_raw = part.get("dimensions")
    dims: Dict[str, Any] = dict(dims_raw) if isinstance(dims_raw, dict) else {}
    params_raw = part.get("parameters")
    if isinstance(params_raw, dict):
        for key, value in params_raw.items():
            if key not in dims and isinstance(value, (int, float)):
                dims[key] = float(value)
    role = iface.get("semantic_role") if isinstance(iface.get("semantic_role"), str) else "mounting"
    geometry_type = iface.get("geometry_type") if isinstance(iface.get("geometry_type"), str) else "planar"
    interface_name_value = iface.get("interface_id")
    interface_name = interface_name_value if isinstance(interface_name_value, str) else ""

    def _feature_target_radius(name: str) -> float | None:
        if not isinstance(name, str) or not name:
            return None
        features = part.get("features")
        if not isinstance(features, list):
            return None
        lowered = name.strip().lower()
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            feature_type = str(feature.get("feature_type") or "").strip().lower()
            iface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
            feature_iface = str(iface_ref.get("name") or "").strip().lower()
            if lowered != feature_iface:
                if not (lowered.startswith("bearing_seat") and feature_type == "bearing_seat"):
                    continue
            geom = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
            bore_diameter = geom.get("bore_diameter")
            if isinstance(bore_diameter, (int, float)) and float(bore_diameter) > 0.0:
                return float(bore_diameter) * 0.5
            diameter = geom.get("diameter")
            if isinstance(diameter, (int, float)) and float(diameter) > 0.0:
                return float(diameter) * 0.5
        return None

    def _infer_usage(name: str, semantic_role: str) -> str:
        explicit = iface.get("usage")
        if isinstance(explicit, str) and explicit in {"drill_anchor", "mate_surface"}:
            return explicit
        n = name.lower()
        if any(tok in n for tok in ("mounting_req", "drill", "hole", "counterbore", "countersink", "bolt")):
            return "drill_anchor"
        return "mate_surface"

    def _num(*keys: str) -> float | None:
        for key in keys:
            value = dims.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    outer_d = _num("outer_diameter", "diameter")
    inner_d = _num("inner_diameter", "bore_diameter")
    outer_r = _num("outer_radius", "radius")
    if outer_r is None and isinstance(outer_d, (int, float)):
        outer_r = float(outer_d) / 2.0
    inner_r = _num("inner_radius")
    if inner_d is None and isinstance(inner_r, (int, float)):
        inner_d = float(inner_r) * 2.0
    explicit_target_radius = iface.get("target_radius_mm")
    if isinstance(explicit_target_radius, (int, float)) and float(explicit_target_radius) > 0.0:
        interface_target_radius = float(explicit_target_radius)
    else:
        interface_target_radius = _feature_target_radius(interface_name)

    explicit_target_point_raw = iface.get("target_point_mm")
    explicit_target_point = None
    if isinstance(explicit_target_point_raw, Mapping):
        try:
            explicit_target_point = {
                "x": float(explicit_target_point_raw.get("x", 0.0)),
                "y": float(explicit_target_point_raw.get("y", 0.0)),
                "z": float(explicit_target_point_raw.get("z", 0.0)),
            }
        except Exception:
            explicit_target_point = None

    lower_name = interface_name.lower()
    phase_match = re.search(r"slot_mount_face_phase_(\d+)", lower_name)
    slot_phase_deg = float(phase_match.group(1)) if phase_match else None

    def _infer_axis(name: str) -> str:
        # Default to Z because the pipeline models most parts in a Z-up local frame.
        n = name.lower()
        if any(tok in n for tok in ("proximal_", "distal_", "insert_face", "mount_face")):
            return "X"
        if "side_face_x" in n or "face_x" in n or "x_face" in n:
            return "X"
        if "side_face_y" in n or "face_y" in n or "y_face" in n:
            return "Y"
        # axial/end/top/bottom are treated as Z-normal faces.
        return "Z"

    def _infer_prefer(name: str, *, default_from_role: str) -> str:
        n = name.lower()
        if "distal" in n:
            return "max"
        if "proximal" in n:
            return "min"
        if any(tok in n for tok in ("_max", "max_", "max")):
            return "max"
        if any(tok in n for tok in ("_min", "min_", "min")):
            return "min"
        if any(k in n for k in {"top", "upper", "up"}):
            return "max"
        if any(k in n for k in {"bottom", "lower", "base", "down"}):
            return "min"
        return default_from_role

    axis = _infer_axis(lower_name)
    usage = _infer_usage(lower_name, role)
    default_pref = "any"
    if role in {"support"}:
        default_pref = "min"
    elif role in {"mounting", "fixation"}:
        default_pref = "max"
    centroid_pref = _infer_prefer(lower_name, default_from_role=default_pref)

    min_area = None
    if isinstance(outer_r, (int, float)):
        min_area = round(3.14159 * max(1.0, outer_r * 0.15) ** 2, 2)

    width_dim = _num("width", "width_mm")
    height_dim = _num("height", "height_mm")
    if height_dim is None:
        height_dim = _num("length", "length_mm")

    rect_radial_max = None
    if not isinstance(outer_r, (int, float)) and isinstance(width_dim, (int, float)) and isinstance(height_dim, (int, float)):
        half_w = float(width_dim) / 2.0
        half_h = float(height_dim) / 2.0
        rect_radial_max = round(math.hypot(half_w, half_h) * 1.05, 3)
        min_area = round(float(width_dim) * float(height_dim) * 0.2, 2)

    expected_geometry: Dict[str, Any] = {
        "target_normal_axis": axis,
        "normal_tolerance_deg": 12.0,
        "centroid_axis": axis,
        "centroid_axis_preference": centroid_pref,
    }

    recipe: Dict[str, Any] = {
        "version": "1.0",
        "geometry_type": geometry_type,
        "usage": usage,
        "selection": [],
        "deterministic_order": ["predicate_score", "distance_to_origin"],
        "expected_geometry": expected_geometry,
    }

    if geometry_type == "planar":
        if isinstance(slot_phase_deg, (int, float)):
            target_radius = outer_r
            if not isinstance(target_radius, (int, float)):
                target_radius = _num("radius", "hub_radius")
            if not isinstance(target_radius, (int, float)) and isinstance(outer_d, (int, float)):
                target_radius = float(outer_d) * 0.5
            if not isinstance(target_radius, (int, float)):
                target_radius = max(float(width_dim or 0.0), float(height_dim or 0.0), 10.0) * 0.5

            slot_radial_max = round(float(target_radius) * 1.05, 3)
            slot_radial_min = round(max(2.0, float(target_radius) * 0.45), 3)
            selection = [
                {"predicate": "planar"},
                {
                    "predicate": "bbox_contains_axis_projection",
                    "axis": "Z",
                    "radial_min_mm": slot_radial_min,
                    "radial_max_mm": slot_radial_max,
                },
                {
                    "predicate": "centroid_polar_angle_deg",
                    "target_deg": round(float(slot_phase_deg), 3),
                    "tolerance_deg": 35.0,
                },
                {"predicate": "area_min", "min_area_mm2": 4.0},
            ]
            recipe["selection"] = selection
            recipe["deterministic_order"] = [
                "polar_angle_proximity",
                "bbox_contains_axis_projection",
                "area_score",
                "distance_to_origin",
            ]
            expected_geometry.update(
                {
                    "centroid_axis": "Z",
                    "centroid_axis_preference": "any",
                    "target_polar_angle_deg": round(float(slot_phase_deg), 3),
                    "polar_tolerance_deg": 35.0,
                    "radial_min_mm": slot_radial_min,
                    "radial_max_mm": slot_radial_max,
                    "min_area_mm2": 4.0,
                }
            )
            return recipe

        selection: List[Dict[str, Any]] = [
            {"predicate": "planar"},
            {"predicate": "normal_parallel", "axis": axis, "tolerance_deg": 12.0},
            {"predicate": "centroid_axis_rank", "axis": axis, "prefer": centroid_pref},
        ]

        bbox_clause: Dict[str, Any] = {
            "predicate": "bbox_contains_axis_projection",
            "axis": axis,
        }
        if isinstance(outer_r, (int, float)):
            bbox_clause["radial_max_mm"] = round(float(outer_r) * 1.05, 3)
        elif isinstance(rect_radial_max, (int, float)):
            bbox_clause["radial_max_mm"] = float(rect_radial_max)
        if isinstance(inner_d, (int, float)):
            bbox_clause["radial_min_mm"] = round(max(0.0, float(inner_d) / 2.0 * 0.8), 3)
        selection.append(bbox_clause)

        if isinstance(min_area, (int, float)):
            if usage == "drill_anchor":
                selection.append({"predicate": "area_min", "min_area_mm2": 1.0})
                expected_geometry["min_area_mm2"] = 1.0
            else:
                selection.append({"predicate": "area_min", "min_area_mm2": min_area})
                expected_geometry["min_area_mm2"] = min_area
        else:
            if usage != "drill_anchor":
                selection.append({"predicate": "max_area"})

        expected_geometry["centroid_axis_preference"] = centroid_pref
        recipe["selection"] = selection
        if usage == "drill_anchor":
            recipe["recipe_policy"] = "top_plane_any_patch_ok"
            recipe["deterministic_order"] = [
                "normal_alignment",
                "bbox_contains_axis_projection",
                "centroid_axis_rank",
            ]
        else:
            recipe["deterministic_order"] = [
                "normal_alignment",
                "bbox_contains_axis_projection",
                "area_score",
                "centroid_axis_rank",
            ]
        return recipe

    if geometry_type in {"axis", "cylindrical"}:
        if lower_name == "distal_bore_axis":
            selection = [
                {"predicate": "cylindrical"},
                {"predicate": "axis_parallel", "axis": "Z", "tolerance_deg": 12.0},
                {"predicate": "distance_to_origin", "axis": "X", "prefer": "max"},
            ]
            target_radius = None
            for key in ("hole_radius", "inner_radius", "radius", "outer_radius"):
                value = dims.get(key)
                if isinstance(value, (int, float)) and float(value) > 0.0:
                    target_radius = float(value)
                    break
            if target_radius is None:
                for key in ("hole_diameter", "diameter", "inner_diameter", "outer_diameter"):
                    value = dims.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0.0:
                        target_radius = float(value) * 0.5
                        break
            if isinstance(target_radius, (int, float)):
                selection.insert(
                    2,
                    {
                        "predicate": "radius_proximity",
                        "target_radius_mm": round(float(target_radius), 3),
                        "tolerance_mm": 0.3,
                    },
                )
                expected_geometry["target_radius_mm"] = round(float(target_radius), 3)
                expected_geometry["radius_tolerance_mm"] = 0.3
            recipe["selection"] = selection
            recipe["deterministic_order"] = [
                "axis_alignment",
                "radius_proximity",
                "distance_to_origin",
            ]
            return recipe

        selection: List[Dict[str, Any]] = [
            {"predicate": "cylindrical"},
            {"predicate": "axis_parallel", "axis": "Z", "tolerance_deg": 12.0},
        ]

        radius_param = None
        for key in ("radius_param", "outer_radius_param", "inner_radius_param"):
            value = shape.get(key)
            if isinstance(value, str) and value:
                radius_param = value
                break

        if radius_param is not None:
            selection.append(
                {
                    "predicate": "radius_from_param",
                    "param": radius_param,
                    "tolerance_mm": 0.1,
                }
            )
            expected_geometry["target_radius_param"] = radius_param
        component_type = str(part.get("type") or part.get("component_type") or "").strip().lower()
        component_name = str(part.get("component_id") or part.get("id") or "").strip().lower()
        shaft_like_types = {"shaft", "axle", "pin", "fastener", "bolt", "screw", "stud"}
        is_shaft_like_component = component_type in shaft_like_types or any(token in component_name for token in shaft_like_types)
        prefer_inner_rotation_radius = (
            not is_shaft_like_component
            and (
                role == "rotation"
                or lower_name in {"rotation_req", "rotation_axis", "shaft_axis", "bore_axis"}
                or "bearing_seat" in lower_name
            )
        )

        target_radius = None
        if isinstance(interface_target_radius, (int, float)):
            target_radius = float(interface_target_radius)
        elif any(tok in lower_name for tok in ("inner", "bore")) or prefer_inner_rotation_radius:
            if isinstance(inner_r, (int, float)):
                target_radius = float(inner_r)
            elif isinstance(inner_d, (int, float)):
                target_radius = float(inner_d) / 2.0
            elif isinstance(outer_r, (int, float)):
                target_radius = float(outer_r)
            elif isinstance(outer_d, (int, float)):
                target_radius = float(outer_d) / 2.0
        elif any(tok in lower_name for tok in ("outer", "od")):
            if isinstance(outer_r, (int, float)):
                target_radius = float(outer_r)
            elif isinstance(outer_d, (int, float)):
                target_radius = float(outer_d) / 2.0
        elif isinstance(outer_r, (int, float)):
            target_radius = float(outer_r)
        elif isinstance(outer_d, (int, float)):
            target_radius = float(outer_d) / 2.0
        if target_radius is None and isinstance(inner_d, (int, float)):
            target_radius = float(inner_d) / 2.0
        if isinstance(target_radius, (int, float)):
            selection.append(
                {
                    "predicate": "radius_proximity",
                    "target_radius_mm": round(float(target_radius), 3),
                    "tolerance_mm": 0.2,
                }
            )
            expected_geometry["target_radius_mm"] = round(float(target_radius), 3)
            expected_geometry["radius_tolerance_mm"] = 0.2

        if explicit_target_point is not None:
            selection.append(
                {
                    "predicate": "closest_to_point",
                    "target_point_mm": explicit_target_point,
                }
            )
            expected_geometry["target_point_mm"] = dict(explicit_target_point)

        if centroid_pref in {"min", "max"}:
            selection.append(
                {
                    "predicate": "closest_to_interface_plane",
                    "axis": "Z",
                    "plane_preference": centroid_pref,
                }
            )
            expected_geometry["interface_plane_preference"] = centroid_pref
        else:
            selection.append({"predicate": "distance_to_origin", "axis": "Z", "prefer": "min"})

        recipe["selection"] = selection
        recipe["deterministic_order"] = [
            "axis_alignment",
            "radius_proximity",
            "point_proximity",
            "distance_to_interface_plane",
            "distance_to_origin",
        ]
        return recipe

    recipe["selection"] = [{"predicate": "best_match"}]
    return recipe


def _infer_interface_target_radius_mm_from_placement(interface_name: str, placement: Mapping[str, Any]) -> float | None:
    lowered = interface_name.strip().lower()
    if not lowered:
        return None
    if lowered.startswith("bearing_seat") or lowered == "bearing_seat":
        derived_changes = placement.get("derived_changes")
        if isinstance(derived_changes, list):
            for change in derived_changes:
                if not isinstance(change, Mapping):
                    continue
                if str(change.get("feature") or "").strip().lower() != "bearing_seat":
                    continue
                bore_diameter = change.get("bore_diameter")
                if isinstance(bore_diameter, (int, float)) and float(bore_diameter) > 0.0:
                    return float(bore_diameter) * 0.5
    if lowered in {"bore_axis", "shaft_axis", "rotation_req", "distal_bore_axis"}:
        derived_changes = placement.get("derived_changes")
        if isinstance(derived_changes, list):
            for change in derived_changes:
                if not isinstance(change, Mapping):
                    continue
                feature_name = str(change.get("feature") or "").strip().lower()
                if not feature_name:
                    continue
                if (
                    feature_name not in {"shaft_bore", "through_bore", "plain_bore", "standoff_bore", "hole", "through_hole"}
                    and "bore" not in feature_name
                    and "hole" not in feature_name
                ):
                    continue
                for key in ("diameter", "hole_diameter", "bore_diameter"):
                    value = change.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0.0:
                        return float(value) * 0.5
        location = placement.get("location")
        if isinstance(location, Mapping):
            safety = location.get("safety_constraints")
            if isinstance(safety, Mapping):
                feature_diameter = safety.get("feature_diameter")
                if isinstance(feature_diameter, (int, float)) and float(feature_diameter) > 0.0:
                    return float(feature_diameter) * 0.5
    return None


def _collect_used_interfaces(connection_placements: Any) -> Dict[tuple[str, str], Dict[str, Any]]:
    used: Dict[tuple[str, str], Dict[str, Any]] = {}
    if not isinstance(connection_placements, list):
        return used

    def _record_interface(
        *,
        component_id: Any,
        interface_name: Any,
        semantic_role: str = "mounting",
        geometry_type: str | None = None,
        usage: str | None = None,
        target_radius_mm: float | None = None,
        source: str,
        connection_id: Any,
    ) -> None:
        if not isinstance(component_id, str) or not component_id:
            return
        if not isinstance(interface_name, str) or not interface_name:
            return
        key = (component_id, interface_name)
        geo = geometry_type if isinstance(geometry_type, str) and geometry_type else _infer_geometry_type_from_interface_id(interface_name, semantic_role)
        resolved_usage = usage if usage in {"drill_anchor", "mate_surface"} else "mate_surface"
        candidate = {
            "component_id": component_id,
            "interface_name": interface_name,
            "semantic_role": semantic_role,
            "geometry_type": geo,
            "geom_type": geo,
            "usage": resolved_usage,
            "target_radius_mm": float(target_radius_mm) if isinstance(target_radius_mm, (int, float)) and float(target_radius_mm) > 0.0 else None,
            "source": source,
            "connection_id": connection_id if isinstance(connection_id, str) else None,
        }
        existing = used.get(key)
        if not isinstance(existing, dict):
            used[key] = candidate
            return

        priority = {
            "connection_placements.anchor_semantics.interface_hint": 1,
            "connection_placements.location.interface_ref": 2,
        }
        existing_priority = priority.get(str(existing.get("source") or ""), 0)
        candidate_priority = priority.get(str(candidate.get("source") or ""), 0)

        if candidate_priority > existing_priority:
            merged = dict(existing)
            merged.update({k: v for k, v in candidate.items() if v is not None})
            used[key] = merged
            return

        merged = dict(existing)
        if merged.get("target_radius_mm") is None and candidate.get("target_radius_mm") is not None:
            merged["target_radius_mm"] = candidate["target_radius_mm"]
        if candidate_priority == existing_priority and not merged.get("connection_id") and candidate.get("connection_id"):
            merged["connection_id"] = candidate["connection_id"]
        used[key] = merged

    for placement in connection_placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location")
        if isinstance(location, dict):
            interface_ref = location.get("interface_ref")
            if isinstance(interface_ref, dict):
                component_id = interface_ref.get("component_id")
                interface_name = interface_ref.get("name")
                role = interface_ref.get("semantic_role") if isinstance(interface_ref.get("semantic_role"), str) else "mounting"
                usage = interface_ref.get("usage") if isinstance(interface_ref.get("usage"), str) else None
                if usage not in {"drill_anchor", "mate_surface"}:
                    if any(tok in str(interface_name).lower() for tok in ("mounting_req", "drill", "hole", "bolt")):
                        usage = "drill_anchor"
                    else:
                        usage = "mate_surface"
                if isinstance(interface_name, str) and interface_name.lower().endswith("_drill_anchor"):
                    usage = "drill_anchor"
                geo = interface_ref.get("geometry_type")
                if not isinstance(geo, str) or not geo:
                    geo = interface_ref.get("geom_type")
                if not isinstance(geo, str) or not geo:
                    geo = _infer_geometry_type_from_interface_id(str(interface_name or ""), role)
                _record_interface(
                    component_id=component_id,
                    interface_name=interface_name,
                    semantic_role=role,
                    geometry_type=geo,
                    usage=usage,
                    target_radius_mm=_infer_interface_target_radius_mm_from_placement(str(interface_name or ""), placement),
                    source="connection_placements.location.interface_ref",
                    connection_id=placement.get("connection_id"),
                )

        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        hint_specs = (
            (
                anchor.get("reference_component_id") or placement.get("reference_component_id"),
                anchor.get("assembly_reference_interface_hint")
                or placement.get("assembly_reference_interface_hint")
                or anchor.get("reference_interface_hint")
                or placement.get("reference_interface_hint"),
            ),
            (
                anchor.get("moving_component_id") or placement.get("moving_component_id"),
                anchor.get("assembly_moving_interface_hint")
                or placement.get("assembly_moving_interface_hint")
                or anchor.get("moving_interface_hint")
                or placement.get("moving_interface_hint"),
            ),
        )
        for hinted_component_id, hinted_interface_name in hint_specs:
            hinted_role = _infer_interface_role(None, str(hinted_interface_name or ""))
            _record_interface(
                component_id=hinted_component_id,
                interface_name=hinted_interface_name,
                semantic_role=hinted_role,
                geometry_type=_infer_geometry_type_from_interface_id(str(hinted_interface_name or ""), hinted_role),
                usage="mate_surface",
                target_radius_mm=None,
                source="connection_placements.anchor_semantics.interface_hint",
                connection_id=placement.get("connection_id"),
            )

    return used

def _index_declared_interfaces(interface_declarations: Any) -> Dict[tuple[str, str], Dict[str, Any]]:
    index: Dict[tuple[str, str], Dict[str, Any]] = {}
    if not isinstance(interface_declarations, list):
        return index

    for item in interface_declarations:
        if not isinstance(item, dict):
            continue
        component_id = item.get("component_id")
        interface_name = item.get("interface_name")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interface_name, str) or not interface_name:
            continue
        index[(component_id, interface_name)] = item
    return index


def _synthesize_recipe_for_missing_interface(
    *,
    component_id: str,
    interface_name: str,
    part_by_component: Dict[str, Dict[str, Any]],
    semantic_role: str | None,
    geometry_type: str | None,
    usage: str | None,
    target_radius_mm: float | None = None,
) -> Dict[str, Any] | None:
    part = part_by_component.get(component_id)
    if not isinstance(part, dict):
        return None

    role = semantic_role if isinstance(semantic_role, str) and semantic_role else "mounting"
    geometry = geometry_type if isinstance(geometry_type, str) and geometry_type else "planar"
    pseudo_iface = {
        "interface_id": interface_name,
        "semantic_role": role,
        "geometry_type": geometry,
        "geom_type": geometry,
        "usage": usage if isinstance(usage, str) and usage in {"drill_anchor", "mate_surface"} else "mate_surface",
    }
    if isinstance(target_radius_mm, (int, float)) and float(target_radius_mm) > 0.0:
        pseudo_iface["target_radius_mm"] = float(target_radius_mm)
    recipe = _build_interface_recipe(part, pseudo_iface)
    return {
        "component_id": component_id,
        "interface_name": interface_name,
        "semantic_role": role,
        "geometry_type": geometry,
        "geom_type": geometry,
        "usage": pseudo_iface["usage"],
        "recipe_policy": recipe.get("recipe_policy") if isinstance(recipe.get("recipe_policy"), str) else None,
        "recipe": recipe,
        "source": "closure_synthesized",
    }


def _hole_axis_interface_name(connection_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(connection_id or "").strip()).strip("_")
    if not token:
        token = "connection"
    return f"{token}_hole_axis"


def _extract_connection_hole_axis_declarations(
    *,
    parts: List[Dict[str, Any]],
    connection_placements: Any,
) -> List[Dict[str, Any]]:
    if not isinstance(connection_placements, list):
        return []

    part_by_component: Dict[str, Dict[str, Any]] = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        component_id = part.get("component_id")
        if isinstance(component_id, str) and component_id:
            part_by_component[component_id] = part

    declarations: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _append_decl(component_id: str, interface_name: str, recipe: Dict[str, Any]) -> None:
        key = (component_id, interface_name)
        if key in seen:
            return
        seen.add(key)
        declarations.append(
            {
                "component_id": component_id,
                "interface_name": interface_name,
                "semantic_role": "rotation",
                "geometry_type": "axis",
                "geom_type": "axis",
                "usage": "mate_surface",
                "recipe_policy": recipe.get("recipe_policy") if isinstance(recipe.get("recipe_policy"), str) else None,
                "recipe": recipe,
                "source": "connection_hole_axis_synthesized",
            }
        )

    for placement in connection_placements:
        if not isinstance(placement, dict):
            continue
        if not isinstance(placement.get("fastener_spec"), Mapping):
            continue

        connection_id = placement.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id:
            continue

        base_connection_id = connection_id.split("@", 1)[0]
        interface_name = _hole_axis_interface_name(base_connection_id)

        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        host_component_id = anchor_semantics.get("reference_component_id") or placement.get("reference_component_id")
        if not isinstance(host_component_id, str) or not host_component_id:
            continue
        host_part = part_by_component.get(host_component_id)
        if not isinstance(host_part, dict):
            continue

        hole_radius_mm = None
        derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        for change in derived_changes:
            if not isinstance(change, Mapping):
                continue
            if change.get("target_component_id") != host_component_id:
                continue
            feature_name = str(change.get("feature") or "").strip().lower()
            if "hole" not in feature_name and "bore" not in feature_name:
                continue
            diameter = change.get("diameter") or change.get("hole_diameter") or change.get("bore_diameter")
            if isinstance(diameter, (int, float)) and float(diameter) > 0.0:
                hole_radius_mm = float(diameter) * 0.5
                break
        if hole_radius_mm is None:
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), Mapping) else {}
            feature_diameter = safety.get("feature_diameter")
            if isinstance(feature_diameter, (int, float)) and float(feature_diameter) > 0.0:
                hole_radius_mm = float(feature_diameter) * 0.5
        if hole_radius_mm is None:
            fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), Mapping) else {}
            hole_diameter = fastener_spec.get("hole_diameter")
            if isinstance(hole_diameter, (int, float)) and float(hole_diameter) > 0.0:
                hole_radius_mm = float(hole_diameter) * 0.5
        if hole_radius_mm is None or hole_radius_mm <= 0.0:
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
        phase_rad = pattern.get("start_angle_rad")
        if not isinstance(phase_rad, (int, float)):
            phase_deg = pattern.get("phase_deg")
            if isinstance(phase_deg, (int, float)):
                phase_rad = math.radians(float(phase_deg))
        if not isinstance(phase_rad, (int, float)):
            phase_deg = pattern.get("start_angle")
            if isinstance(phase_deg, (int, float)):
                phase_rad = math.radians(float(phase_deg))

        pattern_radius_mm = pattern.get("pattern_radius_mm")
        if not isinstance(pattern_radius_mm, (int, float)):
            pattern_radius_mm = pattern.get("pattern_radius")
        if not isinstance(pattern_radius_mm, (int, float)):
            reference_anchor = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), Mapping) else {}
            pattern_radius_mm = reference_anchor.get("radius_mm")

        if not isinstance(phase_rad, (int, float)) or not isinstance(pattern_radius_mm, (int, float)):
            continue

        target_point_mm = {
            "x": round(float(pattern_radius_mm) * math.cos(float(phase_rad)), 6),
            "y": round(float(pattern_radius_mm) * math.sin(float(phase_rad)), 6),
            "z": 0.0,
        }
        pseudo_iface = {
            "interface_id": interface_name,
            "semantic_role": "rotation",
            "geometry_type": "axis",
            "geom_type": "axis",
            "usage": "mate_surface",
            "target_radius_mm": float(hole_radius_mm),
            "target_point_mm": target_point_mm,
        }
        recipe = _build_interface_recipe(host_part, pseudo_iface)
        _append_decl(host_component_id, interface_name, recipe)

    return declarations


def _ensure_interface_closure(
    *,
    parts: List[Dict[str, Any]],
    interface_declarations: List[Dict[str, Any]],
    connection_placements: Any,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    used = _collect_used_interfaces(connection_placements)
    index = _index_declared_interfaces(interface_declarations)
    declared_before = len(index)

    part_by_component: Dict[str, Dict[str, Any]] = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        component_id = part.get("component_id")
        if isinstance(component_id, str) and component_id:
            part_by_component[component_id] = part

    synthesized: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    for key, used_entry in used.items():
        if key in index:
            continue
        component_id, interface_name = key
        synthesized_decl = _synthesize_recipe_for_missing_interface(
            component_id=component_id,
            interface_name=interface_name,
            part_by_component=part_by_component,
            semantic_role=used_entry.get("semantic_role") if isinstance(used_entry, dict) else None,
            geometry_type=used_entry.get("geometry_type") if isinstance(used_entry, dict) else None,
            usage=used_entry.get("usage") if isinstance(used_entry, dict) else None,
            target_radius_mm=used_entry.get("target_radius_mm") if isinstance(used_entry, dict) else None,
        )
        if isinstance(synthesized_decl, dict):
            synthesized.append(synthesized_decl)
            interface_declarations.append(synthesized_decl)
            index[(component_id, interface_name)] = synthesized_decl
        else:
            unresolved.append(
                {
                    "component_id": component_id,
                    "interface_name": interface_name,
                    "reason": "component_not_found_in_modeling_parts",
                    "source": used_entry.get("source") if isinstance(used_entry, dict) else None,
                    "connection_id": used_entry.get("connection_id") if isinstance(used_entry, dict) else None,
                }
            )

    by_component: Dict[str, List[Dict[str, Any]]] = {}
    for decl in interface_declarations:
        if not isinstance(decl, dict):
            continue
        component_id = decl.get("component_id")
        interface_name = decl.get("interface_name")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interface_name, str) or not interface_name:
            continue
        iface_rec = {
            "interface_name": interface_name,
            "semantic_role": decl.get("semantic_role") if isinstance(decl.get("semantic_role"), str) else "mounting",
            "geometry_type": decl.get("geometry_type") if isinstance(decl.get("geometry_type"), str) else "planar",
            "geom_type": decl.get("geom_type") if isinstance(decl.get("geom_type"), str) else (
                decl.get("geometry_type") if isinstance(decl.get("geometry_type"), str) else "planar"
            ),
            "usage": decl.get("usage") if isinstance(decl.get("usage"), str) else "mate_surface",
            "recipe_policy": decl.get("recipe_policy") if isinstance(decl.get("recipe_policy"), str) else None,
            "recipe": decl.get("recipe") if isinstance(decl.get("recipe"), dict) else {},
            "source": decl.get("source") if isinstance(decl.get("source"), str) else "declared",
        }
        by_component.setdefault(component_id, []).append(iface_rec)

    manifest_components: List[Dict[str, Any]] = []
    for component_id in sorted(by_component.keys()):
        interfaces = by_component[component_id]
        interfaces.sort(key=lambda item: str(item.get("interface_name", "")))
        manifest_components.append(
            {
                "component_id": component_id,
                "interfaces": interfaces,
            }
        )

    closure_report: Dict[str, Any] = {
        "used_interface_refs": len(used),
        "declared_before_closure": declared_before,
        "declared_after_closure": len(index),
        "synthesized_count": len(synthesized),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }

    interface_manifest: Dict[str, Any] = {
        "metadata": {
            "schema_version": "1.0",
            "source": "Agent2_interface_closure",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "closure": {
                "synthesized_count": len(synthesized),
                "unresolved_count": len(unresolved),
            },
        },
        "components": manifest_components,
    }

    return interface_declarations, interface_manifest, closure_report


def _build_modeling_semantics(semantics: Dict[str, Any]) -> Dict[str, Any]:
    """Extract modeling-only semantics for Agent3a consumption."""
    parts = []
    interface_declarations: List[Dict[str, Any]] = []
    part_map: Dict[str, Dict[str, Any]] = {}
    declared_keys: set[tuple[str, str]] = set()

    for part in semantics.get("parts", []):
        if not isinstance(part, dict):
            continue
        part_kind = part.get("kind")
        if isinstance(part_kind, str) and part_kind.strip() == "assembly_node":
            continue
        part_policy = part.get("modeling_policy")
        if isinstance(part_policy, str) and part_policy.strip().lower() in {"container_only", "reference_only"}:
            continue
        part_must_model = part.get("must_model")
        if part_must_model is False:
            continue
        modeling_part: Dict[str, Any] = {
            "component_id": part.get("component_id"),
            "shape_semantics": part.get("shape_semantics"),
            "dimensions": part.get("dimensions"),
        }
        if "pattern_intent" in part:
            modeling_part["pattern_intent"] = part.get("pattern_intent")

        component_id = part.get("component_id")
        declarations_for_part: List[Dict[str, Any]] = []
        interfaces = part.get("interfaces")
        if isinstance(component_id, str) and component_id and isinstance(interfaces, list):
            for iface in interfaces:
                if not isinstance(iface, dict):
                    continue
                interface_name = iface.get("interface_id")
                if not isinstance(interface_name, str) or not interface_name:
                    continue
                recipe = _build_interface_recipe(part, iface)
                usage = iface.get("usage") if isinstance(iface.get("usage"), str) else (recipe.get("usage") if isinstance(recipe.get("usage"), str) else None)

                def _append_decl(
                    *,
                    decl_interface_name: str,
                    decl_usage: str,
                    decl_recipe: Dict[str, Any],
                    source: str,
                ) -> None:
                    key = (component_id, decl_interface_name)
                    if key in declared_keys:
                        return
                    declaration = {
                        "component_id": component_id,
                        "interface_name": decl_interface_name,
                        "semantic_role": iface.get("semantic_role"),
                        "geometry_type": iface.get("geometry_type"),
                        "geom_type": iface.get("geom_type") if isinstance(iface.get("geom_type"), str) else iface.get("geometry_type"),
                        "usage": decl_usage,
                        "recipe": decl_recipe,
                        "source": source,
                    }
                    if isinstance(declaration.get("recipe"), dict):
                        recipe_policy = declaration["recipe"].get("recipe_policy")
                        if isinstance(recipe_policy, str):
                            declaration["recipe_policy"] = recipe_policy
                    declarations_for_part.append(declaration)
                    interface_declarations.append(declaration)
                    declared_keys.add(key)

                if usage == "drill_anchor":
                    drill_name = interface_name if interface_name.lower().endswith("_drill_anchor") else f"{interface_name}_drill_anchor"
                    drill_iface = dict(iface)
                    drill_iface["interface_id"] = drill_name
                    drill_iface["usage"] = "drill_anchor"
                    drill_recipe = _build_interface_recipe(part, drill_iface)
                    _append_decl(
                        decl_interface_name=drill_name,
                        decl_usage="drill_anchor",
                        decl_recipe=drill_recipe,
                        source="declared",
                    )

                    base_name = interface_name[:-13] if interface_name.lower().endswith("_drill_anchor") else interface_name
                    if isinstance(base_name, str) and base_name:
                        mate_iface = dict(iface)
                        mate_iface["interface_id"] = base_name
                        mate_iface["usage"] = "mate_surface"
                        mate_recipe = _build_interface_recipe(part, mate_iface)
                        _append_decl(
                            decl_interface_name=base_name,
                            decl_usage="mate_surface",
                            decl_recipe=mate_recipe,
                            source="declared_split_from_drill_anchor",
                        )
                else:
                    _append_decl(
                        decl_interface_name=interface_name,
                        decl_usage="mate_surface" if usage != "drill_anchor" else "drill_anchor",
                        decl_recipe=recipe,
                        source="declared",
                    )

        modeling_part["interface_declarations"] = declarations_for_part
        parts.append(modeling_part)
        if isinstance(component_id, str) and component_id:
            part_map[component_id] = modeling_part

    interface_declarations.extend(
        _extract_connection_hole_axis_declarations(
            parts=parts,
            connection_placements=semantics.get("connection_placements"),
        )
    )

    closure_declarations, interface_manifest, closure_report = _ensure_interface_closure(
        parts=parts,
        interface_declarations=interface_declarations,
        connection_placements=semantics.get("connection_placements"),
    )

    by_component: Dict[str, List[Dict[str, Any]]] = {}
    for declaration in closure_declarations:
        if not isinstance(declaration, dict):
            continue
        component_id = declaration.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue
        by_component.setdefault(component_id, []).append(declaration)

    for component_id, declarations in by_component.items():
        if component_id in part_map:
            part_map[component_id]["interface_declarations"] = declarations

    declaration_usage_map: Dict[tuple[str, str], str] = {}
    for declaration in closure_declarations:
        if not isinstance(declaration, dict):
            continue
        decl_component_id = declaration.get("component_id")
        decl_interface_name = declaration.get("interface_name")
        decl_usage = declaration.get("usage")
        if not isinstance(decl_component_id, str) or not decl_component_id:
            continue
        if not isinstance(decl_interface_name, str) or not decl_interface_name:
            continue
        if not isinstance(decl_usage, str) or not decl_usage:
            continue
        declaration_usage_map[(decl_component_id, decl_interface_name)] = decl_usage

    connection_placements = semantics.get("connection_placements")
    if isinstance(connection_placements, list):
        for placement in connection_placements:
            if not isinstance(placement, dict):
                continue
            location = placement.get("location")
            if not isinstance(location, dict):
                continue
            interface_ref = location.get("interface_ref")
            if not isinstance(interface_ref, dict):
                continue
            component_id = interface_ref.get("component_id")
            interface_name = interface_ref.get("name")
            usage = interface_ref.get("usage")
            if not isinstance(component_id, str) or not component_id:
                continue
            if not isinstance(interface_name, str) or not interface_name:
                continue
            if usage == "drill_anchor" and not interface_name.lower().endswith("_drill_anchor"):
                drill_name = f"{interface_name}_drill_anchor"
                if declaration_usage_map.get((component_id, drill_name)) == "drill_anchor":
                    interface_ref["name"] = drill_name
            elif usage == "mate_surface" and interface_name.lower().endswith("_drill_anchor"):
                base_name = interface_name[:-13]
                if declaration_usage_map.get((component_id, base_name)) == "mate_surface":
                    interface_ref["name"] = base_name

    metadata = semantics.get("metadata", {})
    metadata_obj = dict(metadata) if isinstance(metadata, dict) else {}
    metadata_obj["interface_closure"] = closure_report

    modeling: Dict[str, Any] = {
        "metadata": metadata_obj,
        "parts": parts,
        "interface_declarations": closure_declarations,
        "interface_manifest": interface_manifest,
    }
    if "connection_placements" in semantics:
        modeling["connection_placements"] = semantics.get("connection_placements")
    return modeling
