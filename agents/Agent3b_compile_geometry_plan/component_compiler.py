"""Agent3b component body compilation, profiles, yokes, hub slots, and container components."""

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
from .shape_inputs import *
from .feature_compiler import *

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
