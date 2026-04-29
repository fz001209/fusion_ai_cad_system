"""Agent2 ??????????????????."""

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

def _parse_fastener_size(size_text: str) -> tuple[float | None, float | None]:
    if not isinstance(size_text, str):
        return None, None
    text = size_text.strip().lower()
    if not text:
        return None, None
    m = re.search(r"m(\d+(?:\.\d+)?)", text)
    if not m:
        return None, None
    nominal = float(m.group(1))
    length = None
    m_len = re.search(r"x(\d+(?:\.\d+)?)", text)
    if m_len:
        length = float(m_len.group(1))
    return nominal, length


def _parse_thread_designation_nominal_mm(thread_designation: Any) -> float | None:
    if not isinstance(thread_designation, str):
        return None
    text = thread_designation.strip().lower()
    if not text:
        return None
    match = re.search(r"m\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def _infer_fastener_spec(
    connection_decision: Mapping[str, Any] | None,
    *,
    fastener_component: Mapping[str, Any] | None = None,
    purpose: str | None = None,
) -> Dict[str, Any] | None:
    decision = dict(connection_decision) if isinstance(connection_decision, Mapping) else {}
    fastener = dict(fastener_component) if isinstance(fastener_component, Mapping) else {}

    def _pattern_count_from_component(component: Mapping[str, Any]) -> int | None:
        pattern = component.get("pattern") if isinstance(component.get("pattern"), Mapping) else {}
        count = pattern.get("count") if isinstance(pattern, Mapping) else None
        if isinstance(count, int) and count > 0:
            return int(count)
        dims = component.get("dimensions") if isinstance(component.get("dimensions"), Mapping) else {}
        params = component.get("parameters") if isinstance(component.get("parameters"), Mapping) else {}
        for source in (dims, params):
            value = source.get("count")
            if isinstance(value, int) and value > 0:
                return int(value)
        return None

    size = None
    for candidate in (
        decision.get("resolved_fastener_designation"),
        decision.get("fastener_size"),
        fastener.get("fastener_size"),
        (fastener.get("dimensions") if isinstance(fastener.get("dimensions"), Mapping) else {}).get("fastener_size"),
        (fastener.get("parameters") if isinstance(fastener.get("parameters"), Mapping) else {}).get("fastener_size"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            size = candidate.strip()
            break

    nominal = None
    length = None
    if isinstance(size, str) and size:
        nominal, length = _parse_fastener_size(size)

    if nominal is None:
        for candidate in (
            decision.get("resolved_nominal_diameter_mm"),
            (fastener.get("dimensions") if isinstance(fastener.get("dimensions"), Mapping) else {}).get("nominal_diameter"),
            (fastener.get("parameters") if isinstance(fastener.get("parameters"), Mapping) else {}).get("nominal_diameter"),
        ):
            if isinstance(candidate, (int, float)) and float(candidate) > 0.0:
                nominal = float(candidate)
                break

    if length is None:
        for candidate in (
            decision.get("resolved_length_mm"),
            (fastener.get("dimensions") if isinstance(fastener.get("dimensions"), Mapping) else {}).get("length"),
            (fastener.get("parameters") if isinstance(fastener.get("parameters"), Mapping) else {}).get("length"),
        ):
            if isinstance(candidate, (int, float)) and float(candidate) > 0.0:
                length = float(candidate)
                break

    if not size and isinstance(nominal, (int, float)) and nominal > 0.0:
        nominal_label = f"{float(nominal):g}"
        if isinstance(length, (int, float)) and float(length) > 0.0:
            size = f"M{nominal_label}x{float(length):g}"
        else:
            size = f"M{nominal_label}"

    bundle_count = _pattern_count_from_component(fastener)
    count, pattern_type, _engineering_rule = infer_bolt_count_and_pattern(
        purpose=purpose,
        method=decision.get("method") if isinstance(decision.get("method"), str) else None,
        decision_count=decision.get("count"),
        bundle_count=bundle_count,
    )
    if not isinstance(count, int) or count <= 0:
        count = bundle_count if isinstance(bundle_count, int) and bundle_count > 0 else 1

    normalized_pattern_type = "single" if count <= 1 else (pattern_type or "bolt_circle")
    pattern_payload: Dict[str, Any] = {
        "type": "single" if normalized_pattern_type == "single" else ("rectangular" if normalized_pattern_type == "rectangular" else "circular"),
        "count": int(count),
    }
    source_pattern = fastener.get("pattern") if isinstance(fastener.get("pattern"), Mapping) else {}
    for key in ("hole_diameter_mm", "pattern_radius", "pattern_radius_mm", "spacing", "pcd_mm"):
        if key in source_pattern:
            pattern_payload[key] = copy.deepcopy(source_pattern.get(key))

    spec: Dict[str, Any] = {
        "count": int(count),
        "pattern_type": normalized_pattern_type,
        "pattern": pattern_payload,
        "fit_policy": str(decision.get("fit_policy") or "close_fit"),
        "instances": [{"index": index, "quantity": 1} for index in range(int(count))],
    }
    if isinstance(size, str) and size:
        spec["size"] = size
    if isinstance(nominal, (int, float)) and nominal > 0.0:
        spec["nominal_diameter"] = float(nominal)
        spec["hole_diameter"] = round(float(nominal) + 0.5, 2)
    if isinstance(length, (int, float)) and length > 0.0:
        spec["length"] = float(length)
    return spec

def _component_outer_diameter_mm(component: Mapping[str, Any]) -> float | None:
    dims = component.get("dimensions") if isinstance(component.get("dimensions"), Mapping) else {}
    for key in ("diameter", "outer_diameter", "nominal_diameter"):
        value = dims.get(key)
        if isinstance(value, (int, float)) and float(value) > 0.0:
            return float(value)
    outer_radius = dims.get("outer_radius")
    if not isinstance(outer_radius, (int, float)):
        outer_radius = dims.get("radius")
    if isinstance(outer_radius, (int, float)) and float(outer_radius) > 0.0:
        return float(outer_radius) * 2.0
    return None


def _resolve_hole_diameter(placement: Dict[str, Any]) -> float | None:
    """Unified lookup for the effective hole diameter of a placement.

    Sources checked in priority order:
      1. location.safety_constraints.feature_diameter
      2. derived_changes items whose feature contains 'hole' or 'bolt'
      3. fastener_spec.size  (nominal + 0.5 mm clearance)

    Returns the first positive value found, or ``None``.
    """
    if not isinstance(placement, dict):
        return None

    # 1. safety_constraints.feature_diameter
    location = placement.get("location")
    if isinstance(location, dict):
        safety = location.get("safety_constraints")
        if isinstance(safety, dict):
            fd = safety.get("feature_diameter")
            if isinstance(fd, (int, float)) and float(fd) > 0:
                return float(fd)

    # 2. derived_changes 闁?best diameter among hole/bolt features
    best = 0.0
    derived = placement.get("derived_changes")
    if isinstance(derived, list):
        for item in derived:
            if not isinstance(item, dict):
                continue
            feature = item.get("feature")
            if not isinstance(feature, str):
                continue
            if "hole" not in feature and "bolt" not in feature:
                continue
            for key in ("hole_diameter", "diameter", "bore_diameter"):
                v = item.get(key)
                if isinstance(v, (int, float)) and float(v) > best:
                    best = float(v)
    if best > 0:
        return best

    # 3. fastener_spec.size
    fastener_spec = placement.get("fastener_spec")
    if isinstance(fastener_spec, dict):
        size = fastener_spec.get("size")
        if isinstance(size, str) and size:
            nominal, _ = _parse_fastener_size(size)
            if isinstance(nominal, (int, float)) and nominal > 0:
                return round(float(nominal) + 0.5, 2)

    return None


def infer_bolt_count_and_pattern(
    *,
    purpose: str | None,
    method: str | None,
    decision_count: Any,
    bundle_count: int | None = None,
) -> tuple[int | None, str | None, Dict[str, Any] | None]:
    normalized_method = method.strip().lower() if isinstance(method, str) else None
    normalized_purpose = purpose.strip().lower() if isinstance(purpose, str) else None

    requested_count = None
    if isinstance(decision_count, int) and decision_count > 0:
        requested_count = int(decision_count)
    elif isinstance(bundle_count, int) and bundle_count > 0:
        requested_count = int(bundle_count)

    is_structural_bolted_rigid = (
        normalized_method == "bolted_rigid"
        and normalized_purpose in {"structural_fixation", "structural_clamping", "fastening_mechanism"}
    )
    if is_structural_bolted_rigid:
        final_count = max(3, requested_count if isinstance(requested_count, int) else 4)
        return (
            final_count,
            "bolt_circle",
            {
                "rule": "bolted_rigid_structural_min_count",
                "minimum": 3,
                "requested_count": requested_count,
                "enforced_count": final_count,
            },
        )

    if isinstance(requested_count, int):
        return requested_count, ("bolt_circle" if requested_count > 1 else "single"), None
    return None, None, None


def _normalize_fit_policy(value: Any) -> str:
    """Normalize fit policy into one of: close | normal | loose."""
    if not isinstance(value, str):
        return "normal"
    v = value.strip().lower()
    if v in {"tight", "close", "snug", "interference"}:
        return "close"
    if v in {"loose", "large"}:
        return "loose"
    if v in {"clearance", "normal", "unknown", ""}:
        return "normal"
    return "normal"


def _build_fastener_interface_rules_by_size(kg: Dict[str, Any]) -> dict[str, dict]:
    rules: dict[str, dict] = {}
    parts = kg.get("standard_parts", [])
    if not isinstance(parts, list):
        return rules
    for item in parts:
        if not isinstance(item, dict):
            continue
        if str(item.get("category", "")).strip().lower() != "fastener":
            continue
        size = item.get("size")
        iface = item.get("fastener_interface")
        if not isinstance(size, str) or not size.strip():
            continue
        if not isinstance(iface, dict) or not iface:
            continue
        size_key = size.strip().lower()
        rules[size_key] = iface

        # Also index by base size without length (e.g. "M5x10" -> "m5")
        try:
            nominal, _ = _parse_fastener_size(size)
        except Exception:
            nominal = None
        if isinstance(nominal, (int, float)) and float(nominal) > 0:
            nominal_f = float(nominal)
            if abs(nominal_f - round(nominal_f)) < 1e-6:
                nominal_txt = str(int(round(nominal_f)))
            else:
                nominal_txt = (f"{nominal_f:g}").rstrip("0").rstrip(".")
            base_key = f"m{nominal_txt}".lower()
            # Only set if not already present to keep deterministic preference.
            rules.setdefault(base_key, iface)
    return rules


def _resolve_fastener_clearance_diameter(
    *,
    nominal_mm: float,
    fit_policy: Any,
    fastener_size: str,
    interface_rules_by_size: dict[str, dict] | None,
    fallback_diameter_mm: float | None,
) -> float:
    """Resolve clearance hole diameter deterministically.

    Precedence:
    1) standard_parts fastener_interface.clearance_hole_mm (by fit_policy)
    2) fallback_diameter_mm (e.g. fastener bundle pattern.hole_diameter_mm)
    3) legacy default nominal+0.5
    """
    fit = _normalize_fit_policy(fit_policy)
    if interface_rules_by_size is not None:
        iface = interface_rules_by_size.get(fastener_size.strip().lower())
        if isinstance(iface, dict):
            clearance = iface.get("clearance_hole_mm")
            if isinstance(clearance, dict):
                v = clearance.get(fit)
                if isinstance(v, (int, float)) and float(v) > 0:
                    return round(float(v), 2)
                v = clearance.get("normal")
                if isinstance(v, (int, float)) and float(v) > 0:
                    return round(float(v), 2)

    if isinstance(fallback_diameter_mm, (int, float)) and float(fallback_diameter_mm) > 0:
        return round(float(fallback_diameter_mm), 2)

    return round(float(nominal_mm) + 0.5, 2)


def _resolve_fastener_tap_drill_diameter(
    *,
    nominal_mm: float,
    fastener_size: str,
    interface_rules_by_size: dict[str, dict] | None,
) -> float:
    if interface_rules_by_size is not None:
        iface = interface_rules_by_size.get(fastener_size.strip().lower())
        if isinstance(iface, dict):
            v = iface.get("tap_drill_mm")
            if isinstance(v, (int, float)) and float(v) > 0:
                return round(float(v), 2)
    return _tap_drill_diameter(float(nominal_mm))


def _resolve_fastener_head_seat(
    *,
    nominal_mm: float,
    fastener_size: str,
    interface_rules_by_size: dict[str, dict] | None,
) -> tuple[float, float, dict | None]:
    """Return (head_dia, head_height, counterbore_rule_or_none)."""
    if interface_rules_by_size is not None:
        iface = interface_rules_by_size.get(fastener_size.strip().lower())
        if isinstance(iface, dict):
            cb = iface.get("counterbore")
            if isinstance(cb, dict):
                d = cb.get("diameter_mm")
                h = cb.get("depth_mm")
                if isinstance(d, (int, float)) and isinstance(h, (int, float)):
                    return round(float(d), 2), round(float(h), 2), cb
    head_dia, head_height = _head_seat_dimensions(float(nominal_mm))
    return head_dia, head_height, None


def _tap_drill_diameter(nominal: float) -> float:
    # Coarse pitch approximations for M2-M12 (ISO metric)
    table = {
        2.0: 1.6,
        2.5: 2.05,
        3.0: 2.5,
        4.0: 3.3,
        5.0: 4.2,
        6.0: 5.0,
        8.0: 6.8,
        10.0: 8.5,
        12.0: 10.2,
    }
    closest = min(table.keys(), key=lambda k: abs(k - nominal))
    return table[closest]


def _head_seat_dimensions(nominal: float) -> tuple[float, float]:
    # Approximate ISO 4762 socket head cap screw: head_dia ~ 1.5d, head_height ~ 1.0d
    return round(nominal * 1.5, 2), round(nominal * 1.0, 2)


def _is_fastener_type(comp_type: str | None) -> bool:
    if not isinstance(comp_type, str):
        return False
    value = comp_type.lower()
    return value in {
        "fastener",
        "fastener_set",
        "bolt_set",
        "bolt",
        "screw",
        "nut",
        "washer",
        "pin",
    }


def _is_plate_like_component(comp: Dict[str, Any]) -> bool:
    """Check if component is plate-like. Used only for parameter optimization, NOT as gate for hole generation."""
    comp_type = comp.get("type")
    if isinstance(comp_type, str):
        t = comp_type.lower()
        if t in {"plate", "carrier_plate", "mounting_flange", "bracket", "panel", "cover"}:
            return True
        if "plate" in t or "arm" in t:
            return True
    shape = comp.get("shape_semantics")
    if isinstance(shape, dict):
        stype = shape.get("type")
        if stype in {"radial_plate", "plate"}:
            return True
    return False


def _component_primary_length_mm(comp: Dict[str, Any]) -> float | None:
    dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), dict) else {}
    for key in ("length", "arm_length", "depth"):
        value = dims.get(key)
        if isinstance(value, (int, float)) and float(value) > 0.0:
            return float(value)
    return None


def _component_span_mm(comp: Dict[str, Any]) -> float:
    dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), dict) else {}
    candidates: list[float] = []
    for key in ("width", "thickness", "height", "diameter", "outer_diameter"):
        value = dims.get(key)
        if isinstance(value, (int, float)) and float(value) > 0.0:
            candidates.append(float(value))
    radius = dims.get("outer_radius") if isinstance(dims.get("outer_radius"), (int, float)) else dims.get("radius")
    if isinstance(radius, (int, float)) and float(radius) > 0.0:
        candidates.append(float(radius) * 2.0)
    return max(candidates) if candidates else 1.0


def _is_cylindrical_like_component(comp: Dict[str, Any]) -> bool:
    comp_type = comp.get("type")
    if isinstance(comp_type, str):
        lower = comp_type.lower()
        if lower in {"hub", "wheel", "rim", "tire", "bearing", "axle", "shaft", "roller", "pulley"}:
            return True
    shape = comp.get("shape_semantics")
    if isinstance(shape, dict):
        shape_type = shape.get("type")
        if isinstance(shape_type, str) and shape_type.lower() in {"cylindrical", "annular"}:
            return True
    return False


def _is_linear_support_member(comp: Dict[str, Any]) -> bool:
    comp_type = str(comp.get("type") or "").strip().lower()
    if comp_type in {
        "axle", "shaft", "spindle", "pin", "bolt", "screw", "fastener",
        "bearing", "roller", "wheel", "rim", "tire", "hub", "pulley", "gear",
    }:
        return False
    length = _component_primary_length_mm(comp)
    if length is None:
        return False
    if _is_plate_like_component(comp):
        return True
    span = _component_span_mm(comp)
    return float(length) >= max(20.0, 1.5 * max(1.0, float(span)))


def _infer_anchor_semantics_for_placement(
    *,
    placement: Mapping[str, Any],
    comp_by_id: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any] | None:
    between_ids = [
        cid for cid in _between_to_ids(placement.get("between"))
        if isinstance(cid, str)
        and cid in comp_by_id
        and not _is_fastener_type(comp_by_id[cid].get("type"))
    ]
    if len(between_ids) != 2:
        return None

    purpose = placement.get("purpose") if isinstance(placement.get("purpose"), str) else ""
    comp_a = comp_by_id.get(between_ids[0], {})
    comp_b = comp_by_id.get(between_ids[1], {})

    linear_members = [cid for cid, comp in ((between_ids[0], comp_a), (between_ids[1], comp_b)) if _is_linear_support_member(comp)]
    if purpose in {"load_support", "support_to_structure"} and len(linear_members) == 1:
        reference_id = linear_members[0]
        moving_id = between_ids[1] if reference_id == between_ids[0] else between_ids[0]
        return {
            "relation_type": "support_member_distal_attachment",
            "reference_component_id": reference_id,
            "moving_component_id": moving_id,
            "reference_anchor": {"kind": "distal_end", "axis": "x"},
            "moving_anchor": {"kind": "component_center"},
            "orientation_policy": "inherit_reference_yaw",
            "confidence": "heuristic",
            "source": "agent2_deterministic_anchor_solver",
        }

    if purpose in {"structural_fixation", "structural_clamping", "fastening_mechanism"} and len(linear_members) == 1:
        support_id = linear_members[0]
        counterpart_id = between_ids[1] if support_id == between_ids[0] else between_ids[0]
        counterpart_comp = comp_by_id.get(counterpart_id, {})
        counterpart_type = str(counterpart_comp.get("type") or "").strip().lower()
        if counterpart_type in {"shaft", "axle"}:
            return {
                "relation_type": "support_member_distal_attachment",
                "reference_component_id": support_id,
                "moving_component_id": counterpart_id,
                "reference_anchor": {"kind": "distal_end", "axis": "x"},
                "moving_anchor": {"kind": "component_center"},
                "orientation_policy": "inherit_reference_yaw",
                "confidence": "heuristic",
                "source": "agent2_deterministic_anchor_solver",
            }

        reference_id = counterpart_id
        reference_comp = counterpart_comp
        if not _is_cylindrical_like_component(reference_comp):
            return None
        moving_comp = comp_by_id.get(support_id, {})
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        interface_name = str(interface_ref.get("name") or "").strip().lower()
        pattern_params = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
        pattern_radius = pattern_params.get("pattern_radius_mm") if isinstance(pattern_params.get("pattern_radius_mm"), (int, float)) else pattern_params.get("pattern_radius")
        inset_mm = pattern_params.get("offset_from_edge") if isinstance(pattern_params.get("offset_from_edge"), (int, float)) else pattern_params.get("edge_margin_mm")
        if interface_name in {"axial_end_face_max", "axial_end_face_min"} or _is_plate_like_component(moving_comp):
            face_side = "max" if interface_name.endswith("_max") or interface_name not in {"axial_end_face_min", "axial_end_face_max"} else "min"
            reference_anchor = {"kind": f"axial_face_perimeter_{face_side}"}
            if isinstance(pattern_radius, (int, float)) and float(pattern_radius) > 0.0:
                reference_anchor["radius_mm"] = float(pattern_radius)
            moving_anchor = {"kind": "proximal_mount_face_min" if face_side == "max" else "proximal_mount_face_max", "axis": "x"}
            if isinstance(inset_mm, (int, float)) and float(inset_mm) > 0.0:
                moving_anchor["inset_mm"] = float(inset_mm)
            return {
                "relation_type": "axial_face_perimeter_mount",
                "reference_component_id": reference_id,
                "moving_component_id": support_id,
                "reference_anchor": reference_anchor,
                "moving_anchor": moving_anchor,
                "orientation_policy": "radial_from_reference_center",
                "confidence": "heuristic",
                "source": "agent2_deterministic_anchor_solver",
            }
        return {
            "relation_type": "radial_member_proximal_mount",
            "reference_component_id": reference_id,
            "moving_component_id": support_id,
            "reference_anchor": {"kind": "radial_mount_perimeter"},
            "moving_anchor": {"kind": "proximal_end", "axis": "x"},
            "orientation_policy": "radial_from_reference_center",
            "confidence": "heuristic",
            "source": "agent2_deterministic_anchor_solver",
        }

    return None


def _build_connection_pair_purpose_index(
    kg: Dict[str, Any],
    *,
    comp_by_id: Mapping[str, Dict[str, Any]],
) -> Dict[tuple[str, ...], set[str]]:
    index: Dict[tuple[str, ...], set[str]] = {}
    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, Mapping):
            continue
        key = _connection_pair_key(_between_to_ids(cr.get("between")), comp_by_id=comp_by_id)
        if len(key) < 2:
            continue
        purpose = cr.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            continue
        index.setdefault(key, set()).add(purpose.strip().lower())
    return index


def _connection_pair_key(
    component_ids: List[str],
    *,
    comp_by_id: Mapping[str, Dict[str, Any]],
) -> tuple[str, ...]:
    filtered: List[str] = []
    for cid in component_ids:
        comp = comp_by_id.get(cid, {})
        if _is_fastener_type(comp.get("type")) or _is_subassembly_component(comp):
            continue
        filtered.append(cid)
    return tuple(sorted(set(filtered)))


def _connection_pair_type_set(
    component_ids: tuple[str, ...],
    *,
    comp_by_id: Mapping[str, Dict[str, Any]],
) -> set[str]:
    types: set[str] = set()
    for cid in component_ids:
        ctype = comp_by_id.get(cid, {}).get("type")
        if isinstance(ctype, str) and ctype.strip():
            types.add(ctype.strip().lower())
    return types



def _connection_semantic_type_set(
    component_ids: List[str],
    *,
    comp_by_id: Mapping[str, Dict[str, Any]],
) -> set[str]:
    types: set[str] = set()
    for cid in component_ids:
        comp = comp_by_id.get(cid, {})
        ctype = comp.get("type") if isinstance(comp, Mapping) else None
        if _is_fastener_type(ctype):
            continue
        if isinstance(ctype, str) and ctype.strip():
            types.add(ctype.strip().lower())
    return types


def _connection_mechanism_plausible(
    mechanism: str,
    *,
    type_set: set[str],
    anchor_semantics: Mapping[str, Any] | None,
) -> bool:
    if mechanism == "bonded_tread":
        return "tire" in type_set and bool(type_set.intersection({"rim", "wheel", "hub"}))
    if mechanism == "shaft_bore_fit":
        return bool(type_set.intersection({"shaft", "axle"})) and bool(type_set.intersection({"hub", "rim", "wheel", "gear", "pulley", "coupling", "body", "arm", "plate", "carrier_plate", "bracket", "frame", "housing", "bearing"}))
    if mechanism == "axial_stack_locator":
        return "spacer" in type_set and bool(type_set.intersection({"bearing", "washer", "bushing"}))
    if mechanism == "companion_rotation_relation":
        return bool(type_set.intersection({"shaft", "axle"})) and bool(type_set.intersection({"hub", "rim", "wheel", "gear", "pulley", "coupling", "body", "interface_block", "motor", "electric_motor", "gearbox", "gear_reducer", "actuator"}))
    if mechanism == "radial_member_bolted_mount":
        return isinstance(anchor_semantics, Mapping) and anchor_semantics.get("relation_type") == "radial_member_proximal_mount"
    if mechanism == "axial_face_bolted_mount":
        return isinstance(anchor_semantics, Mapping) and anchor_semantics.get("relation_type") == "axial_face_perimeter_mount"
    if mechanism == "bolted_mount":
        return "tire" not in type_set
    return True


def _infer_connection_feature_mechanism(
    *,
    placement: Mapping[str, Any],
    connection: Mapping[str, Any],
    comp_by_id: Mapping[str, Dict[str, Any]],
    pair_purposes_by_key: Mapping[tuple[str, ...], set[str]] | None = None,
) -> tuple[str, Dict[str, Any]]:
    placement_between_ids = _between_to_ids(placement.get("between")) if placement.get("between") is not None else []
    connection_between_ids = _between_to_ids(connection.get("between"))
    between_ids = placement_between_ids or connection_between_ids
    mechanism_context_ids = list(dict.fromkeys(connection_between_ids + placement_between_ids)) or between_ids
    pair_key = _connection_pair_key(mechanism_context_ids, comp_by_id=comp_by_id)
    type_set = _connection_pair_type_set(pair_key, comp_by_id=comp_by_id)
    semantic_type_set = _connection_semantic_type_set(mechanism_context_ids, comp_by_id=comp_by_id)
    purpose = placement.get("purpose") if isinstance(placement.get("purpose"), str) else connection.get("purpose")
    purpose_norm = purpose.strip().lower() if isinstance(purpose, str) else ""
    decision = connection.get("connection_decision") if isinstance(connection.get("connection_decision"), Mapping) else {}
    anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else None
    contract = _sanitize_connection_semantics_contract(
        connection.get("connection_semantics"),
        valid_component_ids={cid for cid in (connection_between_ids or between_ids) if isinstance(cid, str)},
    )
    if isinstance(contract, Mapping):
        contract_mechanism = _sanitize_connection_mechanism(contract.get("connection_mechanism"))
        contract_anchor = _contract_to_anchor_semantics(contract)
        if contract_mechanism and _connection_mechanism_plausible(contract_mechanism, type_set=semantic_type_set, anchor_semantics=contract_anchor):
            return contract_mechanism, {"source": "connection_semantics.contract"}

    llm_mechanism = _sanitize_connection_mechanism(placement.get("connection_mechanism"))
    if llm_mechanism and _connection_mechanism_plausible(llm_mechanism, type_set=semantic_type_set, anchor_semantics=anchor_semantics):
        return llm_mechanism, {"source": "placement.connection_mechanism"}

    if _placement_requires_explicit_fastener_mount_clarification(placement=placement, connection=connection):
        return "generic_mount", {
            "source": "semantic_authority_guard",
            "reason": "autofilled_fastener_decision_without_explicit_anchor_semantics",
        }

    pair_purposes = pair_purposes_by_key.get(pair_key, set()) if isinstance(pair_purposes_by_key, Mapping) else set()
    has_companion_rotation = any(
        candidate in {"rotation", "rotation_support", "torque_transfer"}
        for candidate in pair_purposes
        if candidate != purpose_norm
    )

    if "tire" in type_set and bool(type_set.intersection({"rim", "wheel", "hub"})):
        return "bonded_tread", {"source": "deterministic_component_pair"}

    if bool(type_set.intersection({"shaft", "axle"})) and bool(type_set.intersection({"hub", "rim", "wheel", "gear", "pulley", "coupling", "body", "bearing"})):
        if purpose_norm in {"structural_fixation", "structural_clamping"} and has_companion_rotation:
            return "companion_rotation_relation", {"source": "pair_purpose_companion_rotation"}
        if purpose_norm in {"rotation", "rotation_support", "torque_transfer"}:
            return "shaft_bore_fit", {"source": "rotary_pair_geometry"}

    if bool(type_set.intersection({"shaft", "axle"})) and bool(type_set.intersection({"interface_block", "motor", "electric_motor", "gearbox", "gear_reducer", "actuator", "coupling"})):
        if purpose_norm in {"torque_transfer", "rotation"} or has_companion_rotation:
            return "companion_rotation_relation", {"source": "drive_interface_torque_pair"}

    if "spacer" in type_set and bool(type_set.intersection({"bearing", "washer", "bushing"})) and purpose_norm == "spacing":
        return "axial_stack_locator", {"source": "deterministic_component_pair"}

    if bool(type_set.intersection({"shaft", "axle"})) and bool(type_set.intersection({"arm", "plate", "carrier_plate", "bracket", "frame", "housing"})):
        if purpose_norm in {"structural_fixation", "structural_clamping", "load_support", "support_to_structure", "rotation", "rotation_support", "torque_transfer"}:
            return "shaft_bore_fit", {"source": "support_member_shaft_pair"}

    if isinstance(anchor_semantics, Mapping) and purpose_norm in {"structural_fixation", "structural_clamping", "fastening_mechanism", "load_support", "support_to_structure"}:
        relation_type = anchor_semantics.get("relation_type")
        if relation_type == "support_member_distal_attachment" and bool(type_set.intersection({"shaft", "axle"})):
            return "shaft_bore_fit", {"source": "anchor_semantics"}
        if relation_type == "radial_member_proximal_mount":
            return "radial_member_bolted_mount", {"source": "anchor_semantics"}
        if relation_type == "axial_face_perimeter_mount":
            return "axial_face_bolted_mount", {"source": "anchor_semantics"}

    method_raw = decision.get("method") if isinstance(decision.get("method"), str) else None
    method_mechanism = _sanitize_connection_mechanism(method_raw)
    if method_mechanism and _connection_mechanism_plausible(method_mechanism, type_set=type_set, anchor_semantics=anchor_semantics):
        return method_mechanism, {"source": "connection_decision.method"}

    if isinstance(method_raw, str) and method_raw.strip().lower().startswith("bolted"):
        return "bolted_mount", {"source": "connection_decision.method_prefix"}
    if isinstance(decision.get("fastener_ref_component_id"), str) and decision.get("fastener_ref_component_id"):
        return "bolted_mount", {"source": "connection_decision.fastener_ref_component_id"}

    return "generic_mount", {"source": "deterministic_fallback"}


def _resolve_split_target_component_id(placement: Mapping[str, Any]) -> str | None:
    connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else ""
    if "@" in connection_id:
        suffix = connection_id.split("@", 1)[1].strip()
        if suffix:
            return suffix
    derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
    derived_targets = {
        item.get("target_component_id")
        for item in derived_changes
        if isinstance(item, Mapping) and isinstance(item.get("target_component_id"), str)
    }
    if len(derived_targets) == 1:
        return next(iter(derived_targets))
    location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
    interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
    component_id = interface_ref.get("component_id")
    return component_id if isinstance(component_id, str) and component_id else None


def _face_interface_for_end_anchor(anchor_def: Mapping[str, Any]) -> str | None:
    kind = str(anchor_def.get("kind") or "").strip().lower()
    axis = str(anchor_def.get("axis") or "x").strip().lower()
    if kind not in {"proximal_end", "distal_end"}:
        return None
    is_proximal = kind == "proximal_end"
    if axis == "z":
        return "axial_end_face_min" if is_proximal else "axial_end_face_max"
    if axis == "y":
        return "side_face_y_min" if is_proximal else "side_face_y_max"
    return "side_face_x_min" if is_proximal else "side_face_x_max"


def _is_semantic_placeholder_interface_name(name: Any) -> bool:
    if not isinstance(name, str):
        return False
    normalized = name.strip().lower()
    if not normalized:
        return False
    return (
        normalized.endswith("_req")
        or "_req_" in normalized
        or normalized.endswith("_drill_anchor")
        or normalized in {"fixation_req", "mounting_req", "support_req", "rotation_req", "torque_transfer_req"}
    )


def _connection_decision_is_agent1_autofill(decision: Mapping[str, Any] | None) -> bool:
    if not isinstance(decision, Mapping):
        return False
    rationale = str(decision.get("rationale") or "").strip().lower()
    return "auto-filled by agent1" in rationale


def _connection_uses_generic_autofilled_fastener_mount(connection: Mapping[str, Any]) -> bool:
    if not isinstance(connection, Mapping):
        return False
    decision = connection.get("connection_decision") if isinstance(connection.get("connection_decision"), Mapping) else None
    if not _connection_decision_is_agent1_autofill(decision):
        return False
    purpose_raw = connection.get("purpose") if isinstance(connection.get("purpose"), str) else None
    purpose = str(purpose_raw).strip().lower() if isinstance(purpose_raw, str) else ""
    return purpose in GENERIC_FASTENER_MOUNT_PURPOSES


def _placement_has_deterministically_invented_anchor_semantics(placement: Mapping[str, Any]) -> bool:
    feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), Mapping) else {}
    actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
    return any(
        isinstance(action, str) and action in SEMANTIC_AUTHORITY_FALLBACK_ACTIONS
        for action in actions
    )


def _placement_requires_explicit_fastener_mount_clarification(
    *,
    placement: Mapping[str, Any],
    connection: Mapping[str, Any],
) -> bool:
    if not _connection_uses_generic_autofilled_fastener_mount(connection):
        return False
    if _sanitize_connection_mechanism(placement.get("connection_mechanism")):
        return False
    location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
    interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
    interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
    if _is_semantic_placeholder_interface_name(interface_name):
        return True
    anchor_semantics = placement.get("anchor_semantics")
    if not isinstance(anchor_semantics, Mapping):
        return True
    return _placement_has_deterministically_invented_anchor_semantics(placement)


def _force_single_pattern_layout(location: Dict[str, Any], placement_intent: Dict[str, Any] | None = None) -> None:
    pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
    pattern["type"] = "single"
    pattern["count"] = 1
    for key in (
        "pattern_radius",
        "pattern_radius_mm",
        "spacing",
        "preserve_single_circular",
        "start_angle",
        "start_angle_rad",
        "phase_deg",
        "phase_rad",
    ):
        pattern.pop(key, None)
    location["pattern_parameters"] = pattern
    if isinstance(placement_intent, dict):
        placement_intent["pattern_type"] = "single"
        placement_intent["symmetry"] = "single"


def _align_fastener_spec_instances_with_count(fastener_spec: Dict[str, Any]) -> Dict[str, Any]:
    count = fastener_spec.get("count") if isinstance(fastener_spec.get("count"), int) and fastener_spec.get("count") > 0 else 1
    instances = fastener_spec.get("instances")
    normalized_instances: list[Any] = []
    if isinstance(instances, list):
        for item in instances[:int(count)]:
            if isinstance(item, Mapping):
                inst = copy.deepcopy(dict(item))
            else:
                inst = {"index": len(normalized_instances), "quantity": 1}
            inst["index"] = len(normalized_instances)
            inst["quantity"] = 1
            normalized_instances.append(inst)
    while len(normalized_instances) < int(count):
        normalized_instances.append({"index": len(normalized_instances), "quantity": 1})
    fastener_spec["instances"] = normalized_instances
    return fastener_spec


def _normalize_fastener_spec_single_instance(fastener_spec: Dict[str, Any]) -> Dict[str, Any]:
    fastener_spec["count"] = 1
    fastener_spec["pattern_type"] = "single"
    fastener_spec["pattern"] = {"type": "single", "count": 1}
    return _align_fastener_spec_instances_with_count(fastener_spec)


def _infer_carrier_target_sides(
    compA: Dict[str, Any],
    compB: Dict[str, Any],
    decision: Dict[str, Any],
) -> tuple[str | None, str | None, str]:
    """
    Determine carrier (clearance hole side) vs target (threaded hole side).
    Returns: (carrier_id, target_id, confidence)
    
    Confidence levels: explicit | inferred_from_method | inferred_from_type | unknown
    """
    # 1. Explicit carrier/target in decision
    if decision.get("carrier_side") and decision.get("target_side"):
        return decision["carrier_side"], decision["target_side"], "explicit"
    
    method = decision.get("method")
    idA = compA.get("id")
    idB = compB.get("id")
    
    # 2. Method-based inference
    if method == "bolt_through_nut":
        # Both sides get clearance holes, carrier is arbitrary (choose first)
        return idA, idB, "inferred_from_method"
    
    if method in {"screw_into_thread", "set_screw_radial"}:
        # Target side has threads, carrier side has clearance
        # Infer: hub/housing/axle/shaft are typically threaded targets
        typeA = compA.get("type", "").lower()
        typeB = compB.get("type", "").lower()
        
        target_keywords = {"hub", "housing", "axle", "shaft", "frame", "body"}
        carrier_keywords = {"arm", "plate", "bracket", "flange", "retainer"}
        
        scoreA_target = sum(1 for kw in target_keywords if kw in typeA)
        scoreB_target = sum(1 for kw in target_keywords if kw in typeB)
        scoreA_carrier = sum(1 for kw in carrier_keywords if kw in typeA)
        scoreB_carrier = sum(1 for kw in carrier_keywords if kw in typeB)
        
        # A is target if it has more target keywords and fewer carrier keywords
        if scoreA_target > scoreB_target or (scoreA_target == scoreB_target and scoreA_carrier < scoreB_carrier):
            return idB, idA, "inferred_from_type"
        else:
            return idA, idB, "inferred_from_type"
    
    # 3. Type-based fallback (default to screw_into_thread logic)
    typeA = compA.get("type", "").lower()
    typeB = compB.get("type", "").lower()
    target_keywords = {"hub", "housing", "axle", "shaft", "frame", "body"}
    
    if any(kw in typeB for kw in target_keywords):
        return idA, idB, "inferred_from_type"
    if any(kw in typeA for kw in target_keywords):
        return idB, idA, "inferred_from_type"
    
    # Default: first is carrier, second is target
    return idA, idB, "unknown"


def _plan_fastener_holes(
    connection: Dict[str, Any],
    comp_by_id: Dict[str, Dict[str, Any]],
    decision: Dict[str, Any],
    *,
    interface_rules_by_size: dict[str, dict] | None = None,
    unresolved_bearing_ids: set[str] | None = None,
) -> list[dict]:
    """
    Generate hole features based on connection decision semantics, NOT component type.
    
    Hole type taxonomy:
    - clearance_hole: Through-hole for bolt passage
    - threaded_hole: Tapped hole for screw engagement
    - pilot_hole / tap_drill: Pre-drill for threading (same as threaded_hole with smaller diameter)
    - counterbore / countersink: Existing head seat features
    - fastener_head_seat: Existing head seat feature
    - nut_seat: Nut retention pocket
    """
    changes = []
    
    # Extract connection participants
    between = connection.get("between", {})
    between_ids = _between_to_ids(between)
    if not between_ids:
        return []
    
    # Filter out fastener components - we generate holes for non-fastener components only
    unresolved_bearing_ids = unresolved_bearing_ids or set()
    non_fastener_ids = [
        cid for cid in between_ids
        if not _is_fastener_type(comp_by_id.get(cid, {}).get("type"))
        and not _is_subassembly_component(comp_by_id.get(cid, {}))
        and cid not in unresolved_bearing_ids
    ]
    
    # Need at least 1 non-fastener component to receive holes
    if not non_fastener_ids:
        return []
    
    # Pull fastener bundle semantics when available (Agent1 fastener bundle).
    fastener_bundle: Dict[str, Any] | None = None
    ref_id = decision.get("fastener_ref_component_id")
    if isinstance(ref_id, str):
        candidate = comp_by_id.get(ref_id)
        if isinstance(candidate, dict):
            fastener_bundle = candidate

    bundle_pattern = fastener_bundle.get("pattern") if isinstance(fastener_bundle, dict) else None
    bundle_hole_diameter = None
    bundle_count = None
    if isinstance(bundle_pattern, dict):
        hd = bundle_pattern.get("hole_diameter_mm")
        if isinstance(hd, (int, float)) and float(hd) > 0:
            bundle_hole_diameter = float(hd)
        pc = bundle_pattern.get("count")
        if isinstance(pc, int) and pc >= 1:
            bundle_count = pc

    # Parse / infer fastener size
    fastener_size = decision.get("fastener_size")
    if not isinstance(fastener_size, str) or not fastener_size.strip():
        inferred_size = None
        if isinstance(fastener_bundle, dict):
            instances = fastener_bundle.get("fastener_instances")
            if isinstance(instances, list):
                for inst in instances:
                    if not isinstance(inst, dict):
                        continue
                    if inst.get("kind") not in {"bolt", "screw"}:
                        continue
                    designation = inst.get("designation")
                    if isinstance(designation, str) and designation.strip():
                        inferred_size = designation.strip()
                        break
            if inferred_size is None:
                dims = fastener_bundle.get("dimensions") if isinstance(fastener_bundle.get("dimensions"), dict) else {}
                nominal_d = dims.get("nominal_diameter")
                length_d = dims.get("length")
                if isinstance(nominal_d, (int, float)) and isinstance(length_d, (int, float)):
                    inferred_size = f"M{int(round(float(nominal_d)))}x{int(round(float(length_d)))}"
                elif isinstance(nominal_d, (int, float)):
                    inferred_size = f"M{int(round(float(nominal_d)))}"
        if inferred_size is None:
            return []
        fastener_size = inferred_size

    nominal, _ = _parse_fastener_size(fastener_size)
    if not nominal and isinstance(fastener_bundle, dict):
        dims = fastener_bundle.get("dimensions") if isinstance(fastener_bundle.get("dimensions"), dict) else {}
        nominal_d = dims.get("nominal_diameter") or dims.get("diameter")
        if isinstance(nominal_d, (int, float)):
            nominal = float(nominal_d)
    if not nominal:
        return []
    
    # Get connection parameters
    purpose = connection.get("purpose") if isinstance(connection.get("purpose"), str) else None
    method = decision.get("method") or "screw_into_thread"  # Default to screw_into_thread
    connection_semantics = connection.get("connection_semantics") if isinstance(connection.get("connection_semantics"), Mapping) else {}
    connection_geometric = connection_semantics.get("geometric_semantics") if isinstance(connection_semantics.get("geometric_semantics"), Mapping) else {}
    support_topology = str(connection_geometric.get("support_topology") or "").strip().lower()
    contact_model = str(connection_geometric.get("contact_model") or "").strip().lower()
    hardware_layout = str(connection_geometric.get("hardware_layout") or "").strip().lower()
    external_nut_clamp = contact_model == "through_bolt_clamp_in_radial_slot" or hardware_layout == "through_bolt_external_nut_clamp"
    if support_topology == "hub_radial_slot_mount":
        method = "bolt_through_nut"
        decision["method"] = "bolt_through_nut"
        decision["stackup"] = "through_nut"
        decision["requires_clearance"] = True
        decision["requires_thread"] = False
    fastener_axis = decision.get("fastener_axis")
    count, pattern_type, engineering_rule = infer_bolt_count_and_pattern(
        purpose=purpose,
        method=method if isinstance(method, str) else None,
        decision_count=decision.get("count"),
        bundle_count=bundle_count,
    )
    requires_clearance = decision.get("requires_clearance", True)
    requires_thread = decision.get("requires_thread", True)
    
    # Calculate hole dimensions (prefer standard_parts fastener_interface rules)
    clearance_dia = _resolve_fastener_clearance_diameter(
        nominal_mm=nominal,
        fit_policy=decision.get("fit_policy"),
        fastener_size=fastener_size,
        interface_rules_by_size=interface_rules_by_size,
        fallback_diameter_mm=bundle_hole_diameter,
    )
    tap_drill_dia = _resolve_fastener_tap_drill_diameter(
        nominal_mm=nominal,
        fastener_size=fastener_size,
        interface_rules_by_size=interface_rules_by_size,
    )
    head_dia, head_height, counterbore_rule = _resolve_fastener_head_seat(
        nominal_mm=nominal,
        fastener_size=fastener_size,
        interface_rules_by_size=interface_rules_by_size,
    )
    pattern = {"type": pattern_type or ("bolt_circle" if (count and count > 1) else "single"), "count": count} if count else None
    if pattern and isinstance(engineering_rule, dict):
        pattern["engineering_rule"] = engineering_rule
    
    if len(non_fastener_ids) == 1:
        # Case 1: fastener 闁?single component (e.g., fastener 闁?hub)
        # Single component gets appropriate hole type based on method
        target_id = non_fastener_ids[0]
        comp = comp_by_id.get(target_id, {})
        comp_type = comp.get("type", "").lower()
        
        # Determine hole type based on component type and method
        if method in {"bolted_rigid", "bolted_hinged"}:
            # Bolted connection: hub/housing/frame gets threaded, arm/plate gets clearance
            if any(kw in comp_type for kw in ["hub", "housing", "frame", "body", "axle", "shaft"]):
                # Structural components: threaded hole
                changes.append({
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "threaded_hole",
                    "diameter": nominal,
                    "pilot_diameter": tap_drill_dia,
                    "depth": round(nominal * 2.0, 2),  # Blind hole, 2x diameter depth
                    "purpose": "fastener_thread_engagement",
                    "source": f"connection_decision.method={method}",
                    "confidence": "inferred_from_type",
                    **({"pattern": pattern} if pattern else {}),
                })
            else:
                # Plate-like components: clearance hole
                changes.append({
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "clearance_hole",
                    "diameter": clearance_dia,
                    "depth": "through",
                    "purpose": "fastener_pass",
                    "source": f"connection_decision.method={method}",
                    "confidence": "inferred_from_type",
                    **({"pattern": pattern} if pattern else {}),
                })
                
                # Add counterbore/countersink for plate-like components
                comp_dims = comp.get("dimensions", {})
                comp_thickness = comp_dims.get("thickness")
                if isinstance(comp_thickness, (int, float)) and _is_plate_like_component(comp):
                    if counterbore_rule is not None or comp_thickness >= nominal * 1.2:
                        changes.append({
                            "target_component_id": target_id,
                            "feature": "counterbore",
                            "diameter": head_dia,
                            "depth": round(min(comp_thickness * 0.6, head_height), 2),
                            "purpose": "fastener_head_seat",
                            "source": f"connection_decision.method={method}",
                            "confidence": "inferred_from_type",
                            **({"pattern": pattern} if pattern else {}),
                        })
        
        elif method in {"screw_into_thread", "set_screw_radial"}:
            # Always threaded for screw/set_screw
            depth = round(nominal * 1.5, 2) if method == "set_screw_radial" else round(nominal * 2.0, 2)
            changes.append({
                "target_component_id": target_id,
                "feature": "hole",
                "hole_type": "threaded_hole",
                "diameter": nominal,
                "pilot_diameter": tap_drill_dia,
                "depth": depth,
                "purpose": "fastener_thread_engagement",
                "source": f"connection_decision.method={method}",
                "confidence": "inferred_from_method",
                **({"pattern": pattern} if pattern else {}),
                **({"orientation": "radial"} if method == "set_screw_radial" else {}),
            })
        
        return changes
    
    elif len(non_fastener_ids) == 2:
        # Case 2: fastener connecting two components (e.g., fastener 闁?arm + hub)
        compA_id, compB_id = non_fastener_ids[0], non_fastener_ids[1]
        compA = comp_by_id.get(compA_id, {})
        compB = comp_by_id.get(compB_id, {})
        
        # Determine carrier and target sides
        carrier_id, target_id, confidence = _infer_carrier_target_sides(compA, compB, decision)
        
        # === Hole Generation Based on Method ===
        
        if method == "bolt_through_nut":
            # Both sides get clearance holes on a shared clamp axis.
            for cid in [carrier_id, target_id]:
                if cid:
                    hole_change = {
                        "target_component_id": cid,
                        "feature": "hole",
                        "hole_type": "clearance_hole",
                        "diameter": clearance_dia,
                        "depth": "through",
                        "purpose": "fastener_pass",
                        "source": f"connection_decision.method={method}",
                        "confidence": confidence,
                        **({"pattern": pattern} if pattern else {}),
                    }
                    if support_topology == "hub_radial_slot_mount":
                        hole_change["face_interface_id"] = "axial_end_face_max"
                        hole_change["side_hint"] = "MAX"
                        hole_change["anchor"] = {
                            "face_interface_id": "axial_end_face_max",
                            "side_hint": "MAX",
                            "normal_hint": {"mode": "FACE_NORMAL"},
                        }
                    changes.append(hole_change)

            # External nut clamp semantics should not create embedded nut pockets.
            if target_id and not external_nut_clamp:
                changes.append({
                    "target_component_id": target_id,
                    "feature": "nut_seat",
                    "diameter": head_dia * 1.1,
                    "depth": nominal * 0.8,
                    "purpose": "nut_retention",
                    "source": f"connection_decision.method={method}",
                    "confidence": confidence,
                    **({"pattern": pattern} if pattern else {}),
                })
        
        elif method in {"screw_into_thread", "bolted_rigid", "bolted_hinged", "unknown", None}:
            # Carrier: clearance hole
            if carrier_id and requires_clearance:
                comp_carrier = comp_by_id.get(carrier_id, {})
                comp_dims = comp_carrier.get("dimensions", {})
                comp_thickness = comp_dims.get("thickness")
                
                changes.append({
                    "target_component_id": carrier_id,
                    "feature": "hole",
                    "hole_type": "clearance_hole",
                    "diameter": clearance_dia,
                    "depth": "through",
                    "purpose": "fastener_pass",
                    "source": f"connection_decision.method={method}",
                    "confidence": confidence if method not in {"unknown", None} else "inferred_default",
                    **({"pattern": pattern} if pattern else {}),
                })
                
                # Add counterbore/countersink if carrier is plate-like
                if isinstance(comp_thickness, (int, float)) and _is_plate_like_component(comp_carrier):
                    if counterbore_rule is not None or comp_thickness >= nominal * 1.2:
                        changes.append({
                            "target_component_id": carrier_id,
                            "feature": "counterbore",
                            "diameter": head_dia,
                            "depth": round(min(comp_thickness * 0.6, head_height), 2),
                            "purpose": "fastener_head_seat",
                            "source": f"connection_decision.method={method}",
                            "confidence": confidence if method not in {"unknown", None} else "inferred_default",
                            **({"pattern": pattern} if pattern else {}),
                        })
                    else:
                        changes.append({
                            "target_component_id": carrier_id,
                            "feature": "countersink",
                            "diameter": head_dia,
                            "angle": 90,
                            "purpose": "fastener_head_seat",
                            "source": f"connection_decision.method={method}",
                            "confidence": confidence if method not in {"unknown", None} else "inferred_default",
                            **({"pattern": pattern} if pattern else {}),
                        })
            
            # Target: threaded hole
            if target_id and requires_thread:
                comp_target = comp_by_id.get(target_id, {})
                
                # For radial connections, use blind hole
                depth = "through"
                if fastener_axis == "radial":
                    depth = round(nominal * 2.0, 2)
                
                changes.append({
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "threaded_hole",
                    "diameter": nominal,
                    "pilot_diameter": tap_drill_dia,
                    "depth": depth,
                    "purpose": "fastener_thread_engagement",
                    "source": f"connection_decision.method={method}",
                    "confidence": confidence if method not in {"unknown", None} else "inferred_default",
                    **({"pattern": pattern} if pattern else {}),
                })
        
        elif method == "set_screw_radial":
            # Only target gets threaded hole (radial)
            if target_id:
                changes.append({
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "threaded_hole",
                    "diameter": nominal,
                    "pilot_diameter": tap_drill_dia,
                    "depth": round(nominal * 1.5, 2),
                    "purpose": "set_screw_clamping",
                    "source": f"connection_decision.method={method}",
                    "confidence": confidence,
                    "orientation": "radial",
                    **({"pattern": pattern} if pattern else {}),
                })
        
        elif method == "pinned":
            # Both sides get pin holes
            pin_clearance = round(nominal + 0.02, 2)
            for cid in [carrier_id, target_id]:
                if cid:
                    changes.append({
                        "target_component_id": cid,
                        "feature": "hole",
                        "hole_type": "pin_hole",
                        "diameter": pin_clearance,
                        "depth": "through",
                        "purpose": "pin_alignment",
                        "source": f"connection_decision.method={method}",
                        "confidence": confidence,
                        **({"pattern": pattern} if pattern else {}),
                    })
    
    return changes

def _ensure_pattern_parameters_complete(kg: Dict[str, Any], placements: list[dict]) -> None:
    """Fill missing location.pattern_parameters (pattern_radius/spacing) deterministically.

    This is a contract-closure step executed before feasibility validation.
    It does NOT reselect hosts or change functional intent; it only fills missing
    numeric pattern parameters when they can be derived from Agent1 dimensions.
    """

    comp_by_id = _build_comp_by_id(kg)

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location")
        if not isinstance(location, dict):
            continue
        pattern_params = location.get("pattern_parameters")
        if not isinstance(pattern_params, dict):
            continue

        pattern_type = pattern_params.get("type")
        if not isinstance(pattern_type, str) or not pattern_type:
            continue

        count_value = None
        if isinstance(pattern_params.get("count"), int):
            count_value = int(pattern_params.get("count"))
        elif isinstance(placement.get("fastener_spec"), dict) and isinstance(placement["fastener_spec"].get("count"), int):
            count_value = int(placement["fastener_spec"].get("count"))

        preserve_single_circular = pattern_type == "circular" and pattern_params.get("preserve_single_circular") is True
        if isinstance(count_value, int) and count_value <= 1 and not preserve_single_circular:
            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            pattern_params.pop("pattern_radius", None)
            pattern_params.pop("spacing", None)
            continue

        interface_ref = location.get("interface_ref")
        host_id = None
        if isinstance(interface_ref, dict) and isinstance(interface_ref.get("component_id"), str):
            host_id = interface_ref.get("component_id")
        if not host_id or host_id not in comp_by_id:
            continue

        host = comp_by_id.get(host_id, {})
        host_dims = host.get("dimensions") if isinstance(host.get("dimensions"), dict) else {}
        host_plate = _is_plate_like_component(host)
        host_type = host.get("type") if isinstance(host.get("type"), str) else ""
        host_type_l = host_type.lower() if isinstance(host_type, str) else ""

        if pattern_type == "circular" and any(tok in host_type_l for tok in ("shaft", "axle")):
            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            pattern_params.pop("pattern_radius", None)
            pattern_params.pop("spacing", None)
            continue

        safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), dict) else {}
        hole_diameter = _resolve_hole_diameter(placement)
        if not isinstance(hole_diameter, (int, float)) or float(hole_diameter) <= 0:
            continue

        thickness = host_dims.get("thickness") if isinstance(host_dims, dict) else None
        min_edge_distance, _ = _compute_edge_constraints(float(hole_diameter), host_plate, thickness)

        hole_r = float(hole_diameter) / 2.0

        safety_min_wall = None
        if isinstance(safety.get("min_wall"), (int, float)):
            safety_min_wall = float(safety.get("min_wall"))
        min_wall = safety_min_wall if safety_min_wall is not None else _compute_min_wall(float(hole_diameter))

        if pattern_type == "circular":
            # Solve/clamp radius and reconcile offset to match feasibility expectations.
            outer = host_dims.get("outer_radius") or host_dims.get("radius")
            diameter = host_dims.get("outer_diameter") or host_dims.get("diameter")
            if outer is None and isinstance(diameter, (int, float)) and diameter > 0:
                outer = float(diameter) / 2.0
            outer = float(outer) if isinstance(outer, (int, float)) and float(outer) > 0 else None

            inner = host_dims.get("inner_radius") or host_dims.get("bore_radius")
            if inner is None:
                inner_d = host_dims.get("inner_diameter") or host_dims.get("bore_diameter")
                if isinstance(inner_d, (int, float)) and inner_d >= 0:
                    inner = float(inner_d) / 2.0
            inner = float(inner) if isinstance(inner, (int, float)) and float(inner) >= 0 else 0.0

            if outer is not None:
                feasible_min = inner + hole_r + min_wall
                feasible_max = outer - hole_r - min_wall

                existing_offset = pattern_params.get("offset_from_edge")
                offset_value = float(existing_offset) if isinstance(existing_offset, (int, float)) else None

                existing_radius = pattern_params.get("pattern_radius")
                radius_value = float(existing_radius) if isinstance(existing_radius, (int, float)) else None

                # Prefer preserving offset intent (edge margin) when provided.
                candidate_radius = None
                if offset_value is not None:
                    candidate_radius = outer - hole_r - offset_value
                elif radius_value is not None:
                    candidate_radius = radius_value
                else:
                    if isinstance(diameter, (int, float)) and diameter > 0:
                        candidate_radius = float(diameter) * 0.35
                    else:
                        candidate_radius = outer * 0.7

                if feasible_max >= feasible_min:
                    solved_radius = min(max(float(candidate_radius), feasible_min), feasible_max)
                    pattern_params["pattern_radius"] = round(float(solved_radius), 2)

                    offset_expected = outer - float(solved_radius) - hole_r
                    pattern_params["offset_from_edge"] = round(max(0.0, float(offset_expected)), 2)

        if pattern_type == "rectangular" and not isinstance(pattern_params.get("spacing"), dict):
            existing_offset = pattern_params.get("offset_from_edge")
            _, default_offset = _compute_edge_constraints(float(hole_diameter), host_plate, thickness)
            eff_offset = float(existing_offset) if isinstance(existing_offset, (int, float)) and existing_offset > 0 else default_offset
            rect_spacing = _resolve_rectangular_spacing(host_dims, eff_offset)
            if rect_spacing is not None:
                pattern_params["offset_from_edge"] = eff_offset
                pattern_params["spacing"] = rect_spacing


def _resolve_slot_mount_overlap_pattern(
    *,
    placement: Mapping[str, Any],
    host_id: str | None,
    host_dims: Mapping[str, Any],
    hole_diameter: float,
) -> Dict[str, Any] | None:
    if not isinstance(host_id, str) or not host_id:
        return None

    geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
    if str(geometric_semantics.get("support_topology") or "").strip().lower() != "hub_radial_slot_mount":
        return None

    anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
    reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
    moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
    if host_id not in {reference_component_id, moving_component_id}:
        return None

    moving_anchor = anchor_semantics.get("moving_anchor") if isinstance(anchor_semantics.get("moving_anchor"), Mapping) else {}
    insert_depth = moving_anchor.get("inset_mm")
    if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
        return None

    overlap_midspan = float(insert_depth) * 0.5
    hole_r = max(float(hole_diameter), 0.0) * 0.5

    if host_id == reference_component_id:
        outer = estimate_outer_radius(host_dims) if isinstance(host_dims, Mapping) else None
        if not isinstance(outer, (int, float)) or float(outer) <= 0.0:
            return None
        inner = estimate_inner_radius(host_dims) if isinstance(host_dims, Mapping) else 0.0
        min_wall = max(1.0, round(hole_r * 0.25, 2))
        r_min = float(inner) + hole_r + min_wall
        r_max = float(outer) - hole_r - min_wall
        if r_max < r_min:
            return None
        target_radius = min(max(float(outer) - overlap_midspan, r_min), r_max)
        edge_margin = max(0.0, float(outer) - target_radius - hole_r)
        return {
            "type": "circular",
            "count": 1,
            "preserve_single_circular": True,
            "pattern_radius": round(float(target_radius), 2),
            "pattern_radius_mm": round(float(target_radius), 2),
            "offset_from_edge": round(float(edge_margin), 2),
            "edge_margin_mm": round(float(edge_margin), 2),
            "source": "agent2_slot_mount_overlap_seed",
        }

    span = 0.0
    for key in ("length", "arm_length", "height", "depth"):
        value = host_dims.get(key)
        if isinstance(value, (int, float)) and float(value) > 0.0:
            span = float(value)
            break
    max_offset = max(0.0, (0.5 * span) - hole_r) if span > 0.0 else overlap_midspan
    target_offset = min(overlap_midspan, max_offset) if max_offset > 0.0 else overlap_midspan
    return {
        "type": "single",
        "count": 1,
        "offset_from_edge": round(float(target_offset), 2),
        "edge_margin_mm": round(float(target_offset), 2),
        "source": "agent2_slot_mount_overlap_seed",
    }


def _seed_missing_pattern_parameters(kg: Dict[str, Any], placements: list[dict]) -> None:
    comp_by_id = _build_comp_by_id(kg)

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        pattern_type = pattern.get("type") if isinstance(pattern.get("type"), str) and pattern.get("type") else None
        preserve_single_circular = pattern_type == "circular" and pattern.get("preserve_single_circular") is True
        has_radius = isinstance(pattern.get("pattern_radius"), (int, float)) or isinstance(pattern.get("pattern_radius_mm"), (int, float))
        if isinstance(pattern_type, str) and pattern_type and ((pattern_type != "circular" and not preserve_single_circular) or has_radius):
            continue

        derived = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        has_hole_like = any(
            isinstance(item, dict)
            and isinstance(item.get("feature"), str)
            and ("hole" in item.get("feature") or "bolt" in item.get("feature"))
            for item in derived
        )
        if not has_hole_like:
            continue

        iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        host_id = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
        host = comp_by_id.get(host_id, {}) if isinstance(host_id, str) else {}
        host_type = str(host.get("type") or "").lower()
        host_dims = host.get("dimensions") if isinstance(host.get("dimensions"), dict) else {}

        fastener = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), dict) else {}
        count_raw = fastener.get("count")
        count = int(count_raw) if isinstance(count_raw, int) and count_raw > 0 else 1
        hole_d = _resolve_hole_diameter(placement) or 5.0
        hole_r = hole_d / 2.0

        slot_mount_pattern = _resolve_slot_mount_overlap_pattern(
            placement=placement,
            host_id=host_id,
            host_dims=host_dims,
            hole_diameter=hole_d,
        )
        if isinstance(slot_mount_pattern, dict):
            location["pattern_parameters"] = slot_mount_pattern
            placement["location"] = location
            continue

        if host_type in {"shaft", "axle", "arm", "plate", "bracket"}:
            location["pattern_parameters"] = {
                "type": "single",
                "count": 1,
                "offset_from_edge": round(max(2.0, hole_d * 1.2), 2),
                "source": "agent2_preseed_non_circular_host",
            }
            placement["location"] = location
            continue

        outer = estimate_outer_radius(host_dims) if isinstance(host_dims, Mapping) else None
        if not isinstance(outer, (int, float)) or outer <= 0:
            outer = 20.0
        min_margin = max(1.0, round(hole_r * 0.25, 2))
        radius_max = max(1.0, float(outer) - hole_r - min_margin)
        seeded_radius = max(1.0, min(radius_max, float(outer) * 0.65))
        offset = max(0.0, float(outer) - seeded_radius - hole_r)
        location["pattern_parameters"] = {
            "type": "circular" if (count >= 2 or preserve_single_circular) else "single",
            "count": count if count >= 2 else 1,
            "pattern_radius": round(seeded_radius, 2),
            "pattern_radius_mm": round(seeded_radius, 2),
            "offset_from_edge": round(offset, 2),
            "edge_margin_mm": round(offset, 2),
            "source": "agent2_preseed_pattern",
            **({"preserve_single_circular": True} if preserve_single_circular else {}),
        }
        placement["location"] = location


def _solve_pattern_parameters(placement: dict, kg: dict) -> dict:
    def _num(v: Any) -> float | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except Exception:
                return None
        return None

    def _infer_outer_radius(dims: Mapping[str, Any]) -> float | None:
        for key in ("outer_radius", "radius"):
            val = _num(dims.get(key))
            if val is not None and val > 0:
                return float(val)
        for key in ("outer_diameter", "diameter"):
            val = _num(dims.get(key))
            if val is not None and val > 0:
                return float(val) / 2.0
        width = _num(dims.get("width") or dims.get("arm_width"))
        length = _num(dims.get("length") or dims.get("arm_length") or dims.get("height") or dims.get("depth"))
        if width is not None and width > 0 and length is not None and length > 0:
            return min(width, length) / 2.0
        return None

    def _infer_inner_radius(dims: Mapping[str, Any]) -> float:
        vals: list[float] = [0.0]
        for key in ("inner_radius", "bore_radius"):
            val = _num(dims.get(key))
            if val is not None and val >= 0:
                vals.append(float(val))
        for key in ("inner_diameter", "bore_diameter", "hole_diameter", "shaft_hole_diameter"):
            val = _num(dims.get(key))
            if val is not None and val >= 0:
                vals.append(float(val) / 2.0)
        return max(vals)

    components = kg.get("components") if isinstance(kg.get("components"), list) else []
    comp_by_id: Dict[str, Dict[str, Any]] = {
        c["id"]: c for c in components if isinstance(c, dict) and isinstance(c.get("id"), str)
    }

    location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
    iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
    between = placement.get("between")
    between_ids = [cid for cid in between if isinstance(cid, str)] if isinstance(between, list) else []

    host_id = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
    if not host_id or host_id not in comp_by_id:
        for cid in between_ids:
            comp = comp_by_id.get(cid)
            if not isinstance(comp, dict):
                continue
            ctype = comp.get("type") if isinstance(comp.get("type"), str) else ""
            cid_l = cid.lower()
            ctype_l = ctype.lower()
            if any(tok in ctype_l for tok in ("fastener", "bolt", "nut", "screw", "washer")):
                continue
            if any(tok in cid_l for tok in ("fastener", "bolt", "nut", "screw", "washer")):
                continue
            host_id = cid
            break

    host = comp_by_id.get(host_id, {}) if isinstance(host_id, str) else {}
    host_dims = host.get("dimensions") if isinstance(host.get("dimensions"), dict) else {}
    host_plate = _is_plate_like_component(host)

    pattern_in = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
    mechanism_name = _sanitize_connection_mechanism(placement.get("connection_mechanism")) or ""

    count = pattern_in.get("count")
    if not isinstance(count, int) or count <= 0:
        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), dict) else {}
        fs_count = fastener_spec.get("count")
        count = int(fs_count) if isinstance(fs_count, int) and fs_count > 0 else 1

    default_pattern_type = "circular" if count > 1 else "single"
    pattern_type_raw = pattern_in.get("type") if isinstance(pattern_in.get("type"), str) else default_pattern_type
    pattern_type = pattern_type_raw if pattern_type_raw in {"single", "linear", "rectangular", "circular"} else default_pattern_type
    preserve_single_circular = pattern_type == "circular" and pattern_in.get("preserve_single_circular") is True

    radius_policy = pattern_in.get("radius_policy") if isinstance(pattern_in.get("radius_policy"), str) else "unspecified"
    if radius_policy not in {"max_feasible_with_margin", "fraction_of_host", "unspecified"}:
        radius_policy = "unspecified"
    edge_policy = pattern_in.get("edge_margin_policy") if isinstance(pattern_in.get("edge_margin_policy"), str) else "unspecified"
    if edge_policy not in {"standard", "min_wall_only", "unspecified"}:
        edge_policy = "unspecified"

    hole_d = _resolve_hole_diameter(placement) or 5.0
    hole_r = hole_d / 2.0
    thickness = _num(host_dims.get("thickness")) if isinstance(host_dims, Mapping) else None
    min_wall = max(1.0, round(hole_r * 0.25, 2))
    standard_margin = max(5.0, round(hole_d * 2.5, 2))
    if isinstance(thickness, (int, float)) and thickness > 0 and host_plate:
        standard_margin = max(standard_margin, round(float(thickness) * 2.0, 2))
    edge_margin = min_wall if edge_policy == "min_wall_only" else standard_margin

    fallback_actions: list[str] = []
    fallback_audit: list[dict] = []

    def _audit(action: str, field: str, original: Any, corrected: Any, reason: str) -> None:
        fallback_actions.append(action)
        fallback_audit.append(
            {
                "action": action,
                "field": field,
                "original": original,
                "corrected": corrected,
                "reason": reason,
                "functional_intent_changed": action in {"reduced_hole_diameter", "reduced_pattern_count", "changed_pattern_type", "requires_mounting_pad"},
            }
        )

    solved: Dict[str, Any] = {
        "type": "circular" if (count <= 1 and preserve_single_circular) else ("single" if count <= 1 else pattern_type),
        "count": 1 if count <= 1 else count,
        "radius_policy": radius_policy,
        "edge_margin_policy": edge_policy,
    }
    if count <= 1 and preserve_single_circular:
        solved["preserve_single_circular"] = True
    solved["_solver_status"] = "ok"
    solved["_solver_fallback_actions"] = fallback_actions
    solved["_solver_fallback_audit"] = fallback_audit

    slot_mount_pattern = _resolve_slot_mount_overlap_pattern(
        placement=placement,
        host_id=host_id,
        host_dims=host_dims if isinstance(host_dims, Mapping) else {},
        hole_diameter=hole_d,
    )
    if isinstance(slot_mount_pattern, dict):
        solved.update(slot_mount_pattern)
        solved["_solver_feature_diameter"] = float(hole_d)
        return solved

    if mechanism_name == "shaft_bore_fit":
        solved["type"] = "single"
        solved["count"] = 1
        solved["edge_margin_mm"] = 0.0
        solved["offset_from_edge"] = 0.0
        solved["_solver_feature_diameter"] = float(hole_d)
        return solved

    if count <= 1 and not preserve_single_circular:
        solved["edge_margin_mm"] = round(edge_margin, 2)
        solved["offset_from_edge"] = round(edge_margin, 2)
        return solved

    if solved["type"] == "circular":
        existing_r = _num(pattern_in.get("pattern_radius_mm"))
        if existing_r is None:
            existing_r = _num(pattern_in.get("pattern_radius"))

        if radius_policy == "max_feasible_with_margin":
            preferred_radius = estimate_outer_radius(host_dims) if isinstance(host_dims, Mapping) else None
        elif radius_policy == "fraction_of_host":
            outer_for_policy = estimate_outer_radius(host_dims) if isinstance(host_dims, Mapping) else None
            preferred_radius = (outer_for_policy * 0.35) if isinstance(outer_for_policy, (int, float)) else None
        else:
            preferred_radius = existing_r

        circular = solve_circular_pattern(
            host_dims=host_dims if isinstance(host_dims, Mapping) else {},
            hole_diameter=hole_d,
            min_wall=min_wall,
            preferred_radius_mm=preferred_radius,
        )

        for action in circular.get("fallback_actions", []):
            if action == "reduced_hole_diameter":
                _audit("reduced_hole_diameter", "location.safety_constraints.feature_diameter", hole_d, circular.get("hole_diameter_mm"), "hole diameter exceeded feasible annular bandwidth")
            elif action == "clamped_pattern_radius":
                _audit("clamped_pattern_radius", "location.pattern_parameters.pattern_radius_mm", existing_r, circular.get("radius_mm"), "radius clamped into feasible band")
            elif action == "synthesized_pattern_radius":
                _audit("synthesized_pattern_radius", "location.pattern_parameters.pattern_radius_mm", None, circular.get("radius_mm"), "missing radius synthesized deterministically")
            elif action == "requires_mounting_pad":
                _audit("requires_mounting_pad", "location.pattern_parameters", None, None, "host geometry cannot satisfy circular pattern; needs clarification")

        status = circular.get("status")
        if status == "needs_clarification":
            solved["_solver_status"] = "needs_clarification"
            return solved

        solved_radius = _num(circular.get("radius_mm"))
        if solved_radius is None:
            solved["_solver_status"] = "needs_clarification"
            return solved

        solved["pattern_radius_mm"] = round(float(solved_radius), 2)
        solved["pattern_radius"] = round(float(solved_radius), 2)
        solved["edge_margin_mm"] = round(float(circular.get("edge_margin_mm") or 0.0), 2)
        solved["offset_from_edge"] = solved["edge_margin_mm"]
        solved["_solver_feature_diameter"] = float(circular.get("hole_diameter_mm") or hole_d)
        return solved

    linear = solve_linear_pattern(
        host_dims=host_dims if isinstance(host_dims, Mapping) else {},
        hole_diameter=hole_d,
        min_wall=min_wall,
        count=int(solved["count"]),
    )
    for action in linear.get("fallback_actions", []):
        if action == "requires_host_planar_span":
            _audit("requires_mounting_pad", "location.pattern_parameters", None, None, "linear/rectangular pattern needs host planar dimensions")
        elif action == "raised_pitch_to_minimum":
            _audit("raised_pitch_to_minimum", "location.pattern_parameters.pitch", None, linear.get("pitch_mm"), "pitch raised to satisfy geometric minimum")

    if linear.get("status") == "needs_clarification":
        solved["_solver_status"] = "needs_clarification"
        return solved

    solved["edge_margin_mm"] = round(float(linear.get("edge_margin_mm") or edge_margin), 2)
    solved["offset_from_edge"] = solved["edge_margin_mm"]
    if solved["type"] == "rectangular":
        width = _num(host_dims.get("width") or host_dims.get("arm_width")) if isinstance(host_dims, Mapping) else None
        length = _num(host_dims.get("length") or host_dims.get("arm_length") or host_dims.get("height") or host_dims.get("depth")) if isinstance(host_dims, Mapping) else None
        pitch_mm = float(linear.get("pitch_mm") or 1.0)
        solved["spacing"] = {
            "x": round(max(pitch_mm, float(width) - 2.0 * solved["edge_margin_mm"]) if isinstance(width, (int, float)) else pitch_mm, 2),
            "y": round(max(pitch_mm, float(length) - 2.0 * solved["edge_margin_mm"]) if isinstance(length, (int, float)) else pitch_mm, 2),
        }
    else:
        solved["pitch"] = round(float(linear.get("pitch_mm") or 1.0), 2)

    solved["_solver_feature_diameter"] = float(linear.get("hole_diameter_mm") or hole_d)
    return solved


def _enforce_solved_pattern_parameters(kg: Dict[str, Any], placements: list[dict]) -> None:
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}

        old_pattern = dict(pattern)
        solved_raw = _solve_pattern_parameters(placement, kg)
        if not isinstance(solved_raw, dict):
            continue

        solver_status = solved_raw.get("_solver_status") if isinstance(solved_raw.get("_solver_status"), str) else "ok"
        solver_actions = solved_raw.get("_solver_fallback_actions") if isinstance(solved_raw.get("_solver_fallback_actions"), list) else []
        solver_audit = solved_raw.get("_solver_fallback_audit") if isinstance(solved_raw.get("_solver_fallback_audit"), list) else []
        solved_feature_diameter = solved_raw.get("_solver_feature_diameter")

        solved_pattern = {k: v for k, v in solved_raw.items() if not str(k).startswith("_solver_")}
        functional_intent_changed = any(
            isinstance(entry, dict) and entry.get("functional_intent_changed") is True
            for entry in solver_audit
        )

        location["pattern_parameters"] = solved_pattern
        if isinstance(location.get("pattern_parameters"), dict):
            location["pattern_parameters"]["source"] = "agent2_deterministic_solver"
        placement["location"] = location

        safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), dict) else {}
        if isinstance(solved_feature_diameter, (int, float)) and solved_feature_diameter > 0:
            old_fd = safety.get("feature_diameter")
            if not isinstance(old_fd, (int, float)) or abs(float(old_fd) - float(solved_feature_diameter)) > 1e-6:
                solver_actions.append("agent2_prevalidated_feature_diameter")
                solver_audit.append(
                    {
                        "action": "agent2_prevalidated_feature_diameter",
                        "field": "location.safety_constraints.feature_diameter",
                        "original": old_fd,
                        "corrected": round(float(solved_feature_diameter), 2),
                        "reason": "feature diameter aligned to deterministic feasibility envelope before validator",
                        "functional_intent_changed": False,
                    }
                )
            safety["feature_diameter"] = round(float(solved_feature_diameter), 2)
            location["safety_constraints"] = safety

        forbidden_incoming = ["pattern_radius", "pattern_radius_mm", "offset_from_edge"]
        if any(k in old_pattern for k in forbidden_incoming):
            solver_actions.append("solver_overrode_llm_numeric_pattern_fields")
            solver_audit.append(
                {
                    "action": "solver_overrode_llm_numeric_pattern_fields",
                    "field": "location.pattern_parameters",
                    "original": {k: old_pattern.get(k) for k in forbidden_incoming if k in old_pattern},
                    "corrected": {
                        k: solved_pattern.get(k)
                        for k in ("pattern_radius_mm", "pattern_radius", "edge_margin_mm", "offset_from_edge", "spacing", "pitch")
                        if k in solved_pattern
                    },
                    "reason": "hard numeric pattern fields are deterministic-only",
                    "functional_intent_changed": False,
                }
            )

        feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
        existing_actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
        existing_audit = feasibility.get("fallback_audit") if isinstance(feasibility.get("fallback_audit"), list) else []
        feasibility["fallback_actions"] = existing_actions + [a for a in solver_actions if isinstance(a, str)]
        feasibility["fallback_audit"] = existing_audit + [a for a in solver_audit if isinstance(a, dict)]
        if functional_intent_changed:
            solver_status = "needs_clarification"
        if solver_status in {"needs_fallback", "needs_clarification"}:
            feasibility["status"] = solver_status
            placement["requires_clarification"] = solver_status == "needs_clarification"
        placement["feasibility"] = feasibility


def _prealign_group_circular_patterns(placements: list[dict]) -> None:
    groups: Dict[str, List[dict]] = {}

    def _to_float(v: Any) -> float | None:
        if isinstance(v, (int, float)):
            return float(v)
        return None

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        conn_id = placement.get("connection_id")
        if not isinstance(conn_id, str) or not conn_id:
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if pattern.get("type") != "circular":
            continue
        pcd_group = pattern.get("pcd_group") if isinstance(pattern.get("pcd_group"), str) and pattern.get("pcd_group") else None
        iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        host = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) and iface_ref.get("component_id") else "unknown"
        base_conn = conn_id.split("@", 1)[0]
        key = pcd_group if isinstance(pcd_group, str) and pcd_group else f"{base_conn}@{host}"
        groups.setdefault(key, []).append(placement)

    for _, members in groups.items():
        if len(members) < 2:
            continue

        radii: list[float] = []
        for placement in members:
            location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
            r = _to_float(pattern.get("pattern_radius_mm"))
            if r is None:
                r = _to_float(pattern.get("pattern_radius"))
            if isinstance(r, float) and r > 0:
                radii.append(r)
        if not radii:
            continue

        radii_sorted = sorted(radii)
        mid = len(radii_sorted) // 2
        target_radius = radii_sorted[mid] if len(radii_sorted) % 2 == 1 else (radii_sorted[mid - 1] + radii_sorted[mid]) / 2.0

        for placement in members:
            location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
            safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), dict) else {}
            fd = _to_float(safety.get("feature_diameter"))
            if fd is None or fd <= 0:
                fd = 5.0
            hole_r = float(fd) / 2.0

            outer = None
            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
            checks = feasibility.get("checks") if isinstance(feasibility.get("checks"), dict) else {}
            outer = _to_float(checks.get("outer_radius"))
            if outer is None:
                outer = target_radius + hole_r + 2.0

            pattern["pattern_radius_mm"] = round(float(target_radius), 2)
            pattern["pattern_radius"] = round(float(target_radius), 2)
            pattern["offset_from_edge"] = round(max(0.0, float(outer) - float(target_radius) - hole_r), 2)
            pattern["edge_margin_mm"] = pattern["offset_from_edge"]
            pattern["source"] = "agent2_group_prealign"
            location["pattern_parameters"] = pattern
            placement["location"] = location


def _connection_group_sort_key(value: str) -> tuple[Any, ...]:
    parts = re.split(r"(\d+)", value or "")
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return tuple(key)


def _canonicalize_connection_stem(connection_id: str) -> str:
    base = (connection_id or "").split("@", 1)[0].strip().lower()
    if not base:
        return "unknown_connection"
    collapsed = re.sub(r"(?<=_|-)\d+(?=_|$)", "*", base)
    collapsed = re.sub(r"[*]+", "*", collapsed)
    return collapsed


def _single_circular_phase_group_key(placement: Mapping[str, Any]) -> tuple[str, str, str] | None:
    geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
    support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
    mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
    anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
    reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
    moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
    if not (isinstance(reference_component_id, str) and isinstance(moving_component_id, str) and mechanism):
        return None
    if support_topology == "hub_radial_slot_mount":
        return (reference_component_id, mechanism, "hub_radial_slot_mount")
    return (reference_component_id, mechanism, _canonicalize_connection_stem(str(placement.get("connection_id") or "")))


def _sync_anchor_semantics_with_pattern_parameters(placements: list[dict]) -> None:
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), dict) else None
        location = placement.get("location") if isinstance(placement.get("location"), dict) else None
        pattern = location.get("pattern_parameters") if isinstance(location, dict) and isinstance(location.get("pattern_parameters"), dict) else None
        if not isinstance(anchor_semantics, dict) or not isinstance(pattern, dict):
            continue

        target_id = _resolve_split_target_component_id(placement)
        reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
        moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None

        pattern_radius = pattern.get("pattern_radius_mm")
        if not isinstance(pattern_radius, (int, float)):
            pattern_radius = pattern.get("pattern_radius")
        inset_mm = pattern.get("offset_from_edge")
        if not isinstance(inset_mm, (int, float)):
            inset_mm = pattern.get("edge_margin_mm")
        phase_rad = pattern.get("start_angle_rad")
        phase_deg = pattern.get("start_angle")
        if not isinstance(phase_deg, (int, float)):
            phase_deg = pattern.get("phase_deg")

        reference_anchor = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), dict) else None
        if isinstance(reference_anchor, dict) and (
            not isinstance(target_id, str) or target_id == reference_component_id
        ):
            reference_kind = str(reference_anchor.get("kind") or "").strip().lower()
            if reference_kind in {"axial_face_perimeter_max", "axial_face_perimeter_min", "radial_mount_perimeter"}:
                if isinstance(pattern_radius, (int, float)) and float(pattern_radius) > 0.0:
                    reference_anchor["radius_mm"] = float(pattern_radius)
                if isinstance(phase_rad, (int, float)):
                    reference_anchor["phase_rad"] = float(phase_rad)
                if isinstance(phase_deg, (int, float)):
                    reference_anchor["phase_deg"] = float(phase_deg)
                anchor_semantics["reference_anchor"] = reference_anchor

        moving_anchor = anchor_semantics.get("moving_anchor") if isinstance(anchor_semantics.get("moving_anchor"), dict) else None
        if isinstance(moving_anchor, dict) and (
            not isinstance(target_id, str) or target_id == moving_component_id
        ):
            moving_kind = str(moving_anchor.get("kind") or "").strip().lower()
            if moving_kind in {"proximal_mount_face_min", "proximal_mount_face_max"} and isinstance(inset_mm, (int, float)) and float(inset_mm) > 0.0:
                moving_anchor["inset_mm"] = float(inset_mm)
                anchor_semantics["moving_anchor"] = moving_anchor

        placement["anchor_semantics"] = anchor_semantics


def _distribute_single_circular_mount_phases(placements: list[dict]) -> None:
    _sync_anchor_semantics_with_pattern_parameters(placements)

    groups: Dict[tuple[str, str, str], List[dict]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if str(pattern.get("type") or "").strip().lower() != "circular":
            continue
        count_value = pattern.get("count")
        if isinstance(count_value, int) and count_value > 1:
            continue
        if pattern.get("preserve_single_circular") is not True:
            continue

        mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
        if mechanism not in {"axial_face_bolted_mount", "radial_member_bolted_mount"}:
            continue

        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), dict) else {}
        reference_component_id = anchor_semantics.get("reference_component_id")
        moving_component_id = anchor_semantics.get("moving_component_id")
        if not isinstance(reference_component_id, str) or not isinstance(moving_component_id, str):
            continue

        key = _single_circular_phase_group_key(placement)
        if key is None:
            continue
        groups.setdefault(key, []).append(placement)

    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(
            key=lambda item: _connection_group_sort_key(
                str(((item.get("anchor_semantics") or {}).get("moving_component_id")) or item.get("connection_id") or "")
            )
        )

        seed_angle_rad = 0.0
        for member in members:
            location = member.get("location") if isinstance(member.get("location"), dict) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
            candidate_rad = pattern.get("start_angle_rad")
            if isinstance(candidate_rad, (int, float)):
                seed_angle_rad = float(candidate_rad)
                break
            candidate_deg = pattern.get("start_angle")
            if isinstance(candidate_deg, (int, float)):
                seed_angle_rad = math.radians(float(candidate_deg))
                break

        step_angle_rad = (2.0 * math.pi) / float(len(members))
        for index, member in enumerate(members):
            phase_rad = seed_angle_rad + step_angle_rad * float(index)
            phase_deg = math.degrees(phase_rad)
            phase_interface_name = f"slot_mount_face_phase_{int(round(float(phase_deg))) % 360}"

            location = member.get("location") if isinstance(member.get("location"), dict) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
            pattern["start_angle_rad"] = float(phase_rad)
            pattern["start_angle"] = float(phase_deg)
            pattern["phase_deg"] = float(phase_deg)
            geometric_semantics = member.get("geometric_semantics") if isinstance(member.get("geometric_semantics"), dict) else {}
            support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else None
            if isinstance(interface_ref, dict):
                iface_name = str(interface_ref.get("name") or "").strip().lower()
                iface_component_id = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else None
                if support_topology == "hub_radial_slot_mount":
                    if iface_component_id == reference_component_id:
                        interface_ref["name"] = phase_interface_name
                    elif iface_component_id == moving_component_id:
                        interface_ref["name"] = "proximal_insert_face"
                    elif iface_name.startswith("slot_mount_face_phase_"):
                        interface_ref["name"] = phase_interface_name
                elif iface_name.startswith("slot_mount_face_phase_"):
                    interface_ref["name"] = phase_interface_name
                location["interface_ref"] = interface_ref
            location["pattern_parameters"] = pattern
            member["location"] = location

            anchor_semantics = member.get("anchor_semantics") if isinstance(member.get("anchor_semantics"), dict) else None
            if isinstance(anchor_semantics, dict):
                reference_anchor = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), dict) else None
                if isinstance(reference_anchor, dict):
                    reference_anchor["phase_rad"] = float(phase_rad)
                    reference_anchor["phase_deg"] = float(phase_deg)
                    pattern_radius = pattern.get("pattern_radius_mm")
                    if not isinstance(pattern_radius, (int, float)):
                        pattern_radius = pattern.get("pattern_radius")
                    if isinstance(pattern_radius, (int, float)) and float(pattern_radius) > 0.0:
                        reference_anchor["radius_mm"] = float(pattern_radius)
                    anchor_semantics["reference_anchor"] = reference_anchor
                if support_topology == "hub_radial_slot_mount":
                    anchor_semantics["reference_interface_hint"] = phase_interface_name
                    anchor_semantics["assembly_reference_interface_hint"] = phase_interface_name
                    anchor_semantics["moving_interface_hint"] = "proximal_insert_face"
                    anchor_semantics["assembly_moving_interface_hint"] = "proximal_insert_face"
                else:
                    for hint_key in ("reference_interface_hint", "assembly_reference_interface_hint"):
                        hint_value = str(anchor_semantics.get(hint_key) or "").strip().lower()
                        if hint_value.startswith("slot_mount_face_phase_"):
                            anchor_semantics[hint_key] = phase_interface_name
                member["anchor_semantics"] = anchor_semantics

            connection_semantics = member.get("connection_semantics") if isinstance(member.get("connection_semantics"), dict) else None
            if isinstance(connection_semantics, dict):
                if support_topology == "hub_radial_slot_mount":
                    connection_semantics["reference_interface_hint"] = phase_interface_name
                    connection_semantics["assembly_reference_interface_hint"] = phase_interface_name
                    connection_semantics["moving_interface_hint"] = "proximal_insert_face"
                    connection_semantics["assembly_moving_interface_hint"] = "proximal_insert_face"
                else:
                    for hint_key in ("reference_interface_hint", "assembly_reference_interface_hint"):
                        hint_value = str(connection_semantics.get(hint_key) or "").strip().lower()
                        if hint_value.startswith("slot_mount_face_phase_"):
                            connection_semantics[hint_key] = phase_interface_name
                member["connection_semantics"] = connection_semantics

            fastener_spec = member.get("fastener_spec") if isinstance(member.get("fastener_spec"), dict) else None
            if isinstance(fastener_spec, dict):
                pattern_spec = fastener_spec.get("pattern") if isinstance(fastener_spec.get("pattern"), dict) else {}
                pattern_spec["phase_deg"] = float(phase_deg)
                fastener_spec["pattern"] = pattern_spec
                member["fastener_spec"] = fastener_spec

            derived_changes = member.get("derived_changes") if isinstance(member.get("derived_changes"), list) else []
            for change in derived_changes:
                if not isinstance(change, dict):
                    continue
                change_pattern = change.get("pattern") if isinstance(change.get("pattern"), dict) else None
                if not isinstance(change_pattern, dict):
                    continue
                change_pattern["start_angle_rad"] = float(phase_rad)
                change_pattern["start_angle"] = float(phase_deg)
                change_pattern["phase_deg"] = float(phase_deg)
                change["pattern"] = change_pattern


    phase_by_connection: dict[tuple[str, str, str, str], tuple[float, float, str]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), dict) else {}
        if str(geometric_semantics.get("support_topology") or "").strip().lower() != "hub_radial_slot_mount":
            continue
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), dict) else {}
        reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
        moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
        mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
        key = _single_circular_phase_group_key(placement)
        if key is None:
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        if interface_ref.get("component_id") != reference_component_id:
            continue
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        phase_deg = pattern.get("phase_deg")
        if not isinstance(phase_deg, (int, float)):
            phase_deg = pattern.get("start_angle")
        if not isinstance(phase_deg, (int, float)):
            continue
        phase_rad = pattern.get("start_angle_rad")
        if not isinstance(phase_rad, (int, float)):
            phase_rad = math.radians(float(phase_deg))
        phase_interface_name = f"slot_mount_face_phase_{int(round(float(phase_deg))) % 360}"
        phase_by_connection[key + (moving_component_id,)] = (float(phase_rad), float(phase_deg), phase_interface_name)

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), dict) else {}
        if str(geometric_semantics.get("support_topology") or "").strip().lower() != "hub_radial_slot_mount":
            continue
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), dict) else {}
        reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
        moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
        key_base = _single_circular_phase_group_key(placement)
        if key_base is None or not isinstance(moving_component_id, str):
            continue
        key = key_base + (moving_component_id,)
        if key not in phase_by_connection:
            continue
        phase_rad, phase_deg, phase_interface_name = phase_by_connection[key]
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        if interface_ref.get("component_id") == moving_component_id:
            interface_ref["name"] = "proximal_insert_face"
            location["interface_ref"] = interface_ref
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
            pattern["start_angle_rad"] = float(phase_rad)
            pattern["start_angle"] = float(phase_deg)
            pattern["phase_deg"] = float(phase_deg)
            location["pattern_parameters"] = pattern
            placement["location"] = location
            anchor_semantics["reference_interface_hint"] = phase_interface_name
            anchor_semantics["assembly_reference_interface_hint"] = phase_interface_name
            anchor_semantics["moving_interface_hint"] = "proximal_insert_face"
            anchor_semantics["assembly_moving_interface_hint"] = "proximal_insert_face"
            reference_anchor = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), dict) else {}
            reference_anchor["phase_rad"] = float(phase_rad)
            reference_anchor["phase_deg"] = float(phase_deg)
            anchor_semantics["reference_anchor"] = reference_anchor
            placement["anchor_semantics"] = anchor_semantics
            connection_semantics = placement.get("connection_semantics") if isinstance(placement.get("connection_semantics"), dict) else {}
            connection_semantics["reference_interface_hint"] = phase_interface_name
            connection_semantics["assembly_reference_interface_hint"] = phase_interface_name
            connection_semantics["moving_interface_hint"] = "proximal_insert_face"
            connection_semantics["assembly_moving_interface_hint"] = "proximal_insert_face"
            placement["connection_semantics"] = connection_semantics



def _ensure_circular_hole_host_is_valid(kg: Dict[str, Any], placements: list[dict]) -> None:
    """Deterministically reselect invalid hosts for circular hole-related placements.

    Strict-mode contract: we do not rely on validator fallback. If an LLM-produced
    placement picks an unsuitable host (e.g. axle/shaft when a hub exists in between),
    we deterministically choose the best host from the explicit connection context.
    """

    comp_by_id: Dict[str, Dict[str, Any]] = {}
    for c in kg.get("components", []) or []:
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            comp_by_id[c["id"]] = c

    def _outer_from_dims(dims: Dict[str, Any]) -> float | None:
        v = dims.get("outer_radius") or dims.get("radius")
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v)
        d = dims.get("outer_diameter") or dims.get("diameter")
        if isinstance(d, (int, float)) and float(d) > 0:
            return float(d) / 2.0
        return None

    def _connection_target_suffix(connection_id: Any) -> str | None:
        if not isinstance(connection_id, str) or "@" not in connection_id:
            return None
        suffix = connection_id.split("@", 1)[1].strip()
        return suffix or None

    for placement in placements:
        if not isinstance(placement, dict):
            continue

        location = placement.get("location")
        if not isinstance(location, dict):
            continue
        pattern_params = location.get("pattern_parameters")
        if not isinstance(pattern_params, dict) or pattern_params.get("type") != "circular":
            continue

        derived = placement.get("derived_changes")
        if not isinstance(derived, list) or not any(
            isinstance(it, dict)
            and isinstance(it.get("feature"), str)
            and "hole" in it.get("feature")
            for it in derived
        ):
            continue

        interface_ref = location.get("interface_ref")
        iface = dict(interface_ref) if isinstance(interface_ref, dict) else {}
        host_id = iface.get("component_id") if isinstance(iface.get("component_id"), str) else None

        between_ids = _between_to_ids(placement.get("between"))
        if not between_ids:
            continue

        expected_target = _connection_target_suffix(placement.get("connection_id"))
        target_locked = isinstance(expected_target, str) and expected_target in between_ids
        if target_locked:
            if host_id != expected_target:
                host_id = expected_target
                iface["component_id"] = expected_target

            if not isinstance(iface.get("name"), str) or iface.get("name") in {"", "unspecified"}:
                comp = comp_by_id.get(expected_target)
                shape = comp.get("shape_semantics") if isinstance(comp, dict) else {}
                shape_type = shape.get("type") if isinstance(shape, dict) else None
                iface["name"] = "axial_end_face_max" if shape_type in {"cylindrical", "annular"} else "radial_outer_face"

            purpose = placement.get("purpose")
            iface_role = _infer_interface_role_from_purpose(purpose if isinstance(purpose, str) else None)
            iface_name = iface.get("name")
            iface_name_str = iface_name if isinstance(iface_name, str) else ""
            iface_geo = _infer_geometry_type_from_interface_id(iface_name_str, iface_role)
            iface["semantic_role"] = iface_role
            iface["geometry_type"] = iface_geo
            iface["geom_type"] = iface_geo
            location["interface_ref"] = iface
            placement["location"] = location

        hole_d = _resolve_hole_diameter(placement) or 5.0
        hole_r = float(hole_d) / 2.0

        def _host_is_suitable(cid: str) -> bool:
            comp = comp_by_id.get(cid)
            if not isinstance(comp, dict):
                return False
            ctype = comp.get("type")
            if not isinstance(ctype, str):
                return False
            if _is_fastener_type(ctype) or ctype.lower() == "subassembly":
                return False
            if any(tok in ctype.lower() for tok in ("shaft", "axle")):
                return False
            dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), dict) else {}
            outer = _outer_from_dims(dims)
            return outer is not None and outer > (hole_r + 1.0)

        if isinstance(host_id, str) and host_id and _host_is_suitable(host_id):
            continue

        if target_locked:
            continue

        host_candidates = _expand_host_candidates_with_parents(comp_by_id, between_ids, max_depth=2)
        viable = [cid for cid in host_candidates if _host_is_suitable(cid)]
        if not viable:
            continue

        new_host = _choose_feature_host(comp_by_id, viable)
        if not new_host or new_host == host_id:
            continue

        iface["component_id"] = new_host
        if not isinstance(iface.get("name"), str) or iface.get("name") in {"", "unspecified"}:
            comp = comp_by_id.get(new_host)
            shape = comp.get("shape_semantics") if isinstance(comp, dict) else {}
            shape_type = shape.get("type") if isinstance(shape, dict) else None
            if shape_type in {"cylindrical", "annular"}:
                iface["name"] = "axial_end_face_max"
            else:
                iface["name"] = "radial_outer_face"

        purpose = placement.get("purpose")
        iface_role = _infer_interface_role_from_purpose(purpose if isinstance(purpose, str) else None)
        iface_name = iface.get("name")
        iface_name_str = iface_name if isinstance(iface_name, str) else ""
        iface_geo = _infer_geometry_type_from_interface_id(iface_name_str, iface_role)
        iface["semantic_role"] = iface_role
        iface["geometry_type"] = iface_geo
        iface["geom_type"] = iface_geo
        location["interface_ref"] = iface
        placement["location"] = location


def _build_nested_pattern_payload_from_location(pattern: Mapping[str, Any]) -> Dict[str, Any]:
    pattern_type = str(pattern.get("type") or "").strip().lower()
    count = pattern.get("count") if isinstance(pattern.get("count"), int) and pattern.get("count") > 0 else 1
    preserve_single_circular = pattern_type == "circular" and pattern.get("preserve_single_circular") is True

    nested_type = "single"
    if pattern_type == "rectangular":
        nested_type = "rectangular"
    elif pattern_type == "circular" and (count > 1 or preserve_single_circular):
        nested_type = "circular"

    nested: Dict[str, Any] = {
        "type": nested_type,
        "count": int(count),
    }
    if preserve_single_circular:
        nested["preserve_single_circular"] = True

    radius = pattern.get("pattern_radius_mm") if isinstance(pattern.get("pattern_radius_mm"), (int, float)) else pattern.get("pattern_radius")
    if nested_type == "circular" and isinstance(radius, (int, float)) and float(radius) > 0.0:
        radius_value = round(float(radius), 2)
        nested["pattern_radius"] = radius_value
        nested["pattern_radius_mm"] = radius_value

    spacing = pattern.get("spacing")
    if nested_type == "rectangular" and isinstance(spacing, Mapping):
        nested["spacing"] = copy.deepcopy(dict(spacing))

    offset = pattern.get("edge_margin_mm") if isinstance(pattern.get("edge_margin_mm"), (int, float)) else pattern.get("offset_from_edge")
    if isinstance(offset, (int, float)):
        nested["offset_from_edge"] = round(float(offset), 2)

    for key in ("start_angle", "start_angle_rad", "phase_deg", "phase_rad"):
        value = pattern.get(key)
        if isinstance(value, (int, float)):
            nested[key] = round(float(value), 6)

    return nested


def _refresh_resolved_location_contract(placement: dict) -> None:
    location = placement.get("location") if isinstance(placement.get("location"), dict) else None
    if not isinstance(location, dict):
        return
    pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else None
    if not isinstance(pattern, dict):
        return

    interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
    interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) and interface_ref.get("name") else "unspecified"
    purpose = placement.get("purpose") if isinstance(placement.get("purpose"), str) else None
    purpose_desc = {
        "fastening_mechanism": "fastening connection",
        "structural_fixation": "structural fixation",
        "load_support": "load support interface",
        "rotation_support": "rotation support interface",
        "support_to_structure": "structural support",
    }.get(purpose, purpose or "connection")

    pattern_type = str(pattern.get("type") or "").strip().lower()
    preserve_single_circular = pattern_type == "circular" and pattern.get("preserve_single_circular") is True
    radius = pattern.get("pattern_radius_mm") if isinstance(pattern.get("pattern_radius_mm"), (int, float)) else pattern.get("pattern_radius")
    radius_value = round(float(radius), 2) if isinstance(radius, (int, float)) and float(radius) > 0.0 else None
    offset = pattern.get("edge_margin_mm") if isinstance(pattern.get("edge_margin_mm"), (int, float)) else pattern.get("offset_from_edge")
    offset_value = round(float(offset), 2) if isinstance(offset, (int, float)) and float(offset) >= 0.0 else None
    if offset_value is not None:
        pattern["edge_margin_mm"] = offset_value
        pattern["offset_from_edge"] = offset_value
    if radius_value is not None and (pattern_type == "circular" or preserve_single_circular):
        pattern["pattern_radius_mm"] = radius_value
        pattern["pattern_radius"] = radius_value
    location["pattern_parameters"] = pattern

    safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), dict) else {}
    geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), dict) else {}
    support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
    target_id = _resolve_split_target_component_id(placement)
    anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), dict) else {}
    reference_component_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
    moving_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None

    if support_topology == "hub_radial_slot_mount" and offset_value is not None:
        safety["min_edge_distance"] = offset_value
        safety["edge_rule_basis"] = "slot_overlap_midline"
    location["safety_constraints"] = safety

    if support_topology == "hub_radial_slot_mount":
        if target_id == reference_component_id and radius_value is not None and offset_value is not None:
            location["rationale"] = (
                f"Deterministic: overlap-resolved circular anchor at R={radius_value:g}mm on {interface_name} "
                f"for {purpose_desc}. Remaining outer wall: {offset_value:g}mm."
            )
        elif target_id == moving_component_id and offset_value is not None:
            location["rationale"] = (
                f"Deterministic: overlap-resolved single anchor {offset_value:g}mm from {interface_name} "
                f"for {purpose_desc}, centered in the shared hub-arm overlap."
            )
        else:
            location["rationale"] = (
                f"Deterministic: overlap-resolved slot-mount anchor on {interface_name} for {purpose_desc}."
            )
        placement["location"] = location
        return

    if pattern_type == "single" and not preserve_single_circular:
        geo_desc = "single feature"
    elif (pattern_type == "circular" or preserve_single_circular) and radius_value is not None:
        geo_desc = f"circular pattern at R={radius_value:g}mm"
    elif pattern_type == "rectangular" and isinstance(pattern.get("spacing"), Mapping):
        spacing = pattern.get("spacing")
        geo_desc = f"rectangular pattern with {spacing.get('x')}x{spacing.get('y')}mm spacing"
    elif pattern_type:
        geo_desc = f"{pattern_type} pattern (dimensions pending)"
    else:
        geo_desc = "pattern (dimensions pending)"

    min_edge_distance = safety.get("min_edge_distance") if isinstance(safety.get("min_edge_distance"), (int, float)) else None
    if offset_value is not None and isinstance(min_edge_distance, (int, float)):
        location["rationale"] = (
            f"Deterministic: {geo_desc} on {interface_name} for {purpose_desc}. "
            f"Edge safety: {offset_value:g}mm (>= {float(min_edge_distance):g}mm min)"
        )
    elif offset_value is not None:
        location["rationale"] = (
            f"Deterministic: {geo_desc} on {interface_name} for {purpose_desc}. "
            f"Edge safety: {offset_value:g}mm"
        )
    else:
        location["rationale"] = f"Deterministic: {geo_desc} on {interface_name} for {purpose_desc}."
    placement["location"] = location


def _synchronize_pattern_sources_with_location(placements: list[dict]) -> None:
    for placement in placements:
        if not isinstance(placement, dict):
            continue

        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        pattern_type = pattern.get("type") if isinstance(pattern.get("type"), str) else None
        if not isinstance(pattern_type, str) or not pattern_type:
            continue

        _refresh_resolved_location_contract(placement)
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        count = pattern.get("count") if isinstance(pattern.get("count"), int) and pattern.get("count") > 0 else 1
        nested_pattern = _build_nested_pattern_payload_from_location(pattern)

        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), dict) else None
        if isinstance(fastener_spec, dict):
            if count == 1:
                fastener_spec = _normalize_fastener_spec_single_instance(fastener_spec)
            else:
                fastener_spec["count"] = int(count)
                fastener_spec["pattern_type"] = "rectangular" if nested_pattern.get("type") == "rectangular" else ("bolt_circle" if nested_pattern.get("type") == "circular" else "single")
                fastener_spec = _align_fastener_spec_instances_with_count(fastener_spec)
            fastener_spec["pattern"] = copy.deepcopy(nested_pattern)
            placement["fastener_spec"] = fastener_spec

        derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        for change in derived_changes:
            if not isinstance(change, dict):
                continue
            ch_pattern = change.get("pattern") if isinstance(change.get("pattern"), dict) else None
            if not isinstance(ch_pattern, dict):
                continue
            change["pattern"] = copy.deepcopy(nested_pattern)

def _merge_derived_changes(
    base: list[dict],
    extra: list[dict],
) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()

    def _key(item: dict) -> str:
        geometry_parameters = item.get("geometry_parameters") if isinstance(item.get("geometry_parameters"), Mapping) else {}
        pattern_sig = json.dumps(item.get("pattern"), sort_keys=True, ensure_ascii=False) if isinstance(item.get("pattern"), Mapping) else ""
        anchor_sig = json.dumps(item.get("anchor"), sort_keys=True, ensure_ascii=False) if isinstance(item.get("anchor"), Mapping) else ""
        return "|".join([
            str(item.get("target_component_id")),
            str(item.get("feature")),
            str(item.get("hole_type")),
            str(item.get("bore_diameter")),
            str(item.get("diameter")),
            str(item.get("width")),
            str(item.get("depth")),
            str(item.get("purpose")),
            str(item.get("thread_designation") or geometry_parameters.get("thread_designation")),
            str(item.get("thread_class") or geometry_parameters.get("thread_class")),
            str(item.get("thread_type") or geometry_parameters.get("thread_type")),
            str(item.get("is_internal") if isinstance(item.get("is_internal"), bool) else geometry_parameters.get("is_internal")),
            str(item.get("thread_length_mm") or geometry_parameters.get("thread_length_mm")),
            pattern_sig,
            anchor_sig,
        ])
    for item in base + extra:
        if not isinstance(item, dict):
            continue
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _between_to_ids(between: Any) -> list[str]:
    if isinstance(between, dict):
        return [cid for cid in between.keys() if isinstance(cid, str)]
    if isinstance(between, list):
        return [cid for cid in between if isinstance(cid, str)]
    return []


def _filter_derived_changes(
    derived_changes: list[dict],
    *,
    allowed_component_ids: set[str],
) -> list[dict]:
    filtered: list[dict] = []
    for item in derived_changes:
        if not isinstance(item, dict):
            continue
        target_id = item.get("target_component_id")
        feature = item.get("feature")
        if not isinstance(target_id, str) or target_id not in allowed_component_ids:
            continue
        if not isinstance(feature, str) or not feature:
            continue
        filtered.append(item)
    return filtered


def _normalize_alignment_pin_hole_policy(
    kg: Dict[str, Any],
    placements: list[dict],
) -> list[dict]:
    """Enforce explicit alignment-pin policy and hole-strategy exclusivity per feature group."""
    connection_by_id: Dict[str, Dict[str, Any]] = {}
    for cr in kg.get("connection_requirements", []) or []:
        if isinstance(cr, dict) and isinstance(cr.get("id"), str):
            connection_by_id[cr["id"]] = cr

    def _is_true(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value) != 0.0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    audit_entries: list[dict] = []

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        derived_changes = placement.get("derived_changes")
        if not isinstance(derived_changes, list) or not derived_changes:
            continue

        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else ""
        base_connection_id = connection_id.split("@", 1)[0] if "@" in connection_id else connection_id
        connection = connection_by_id.get(base_connection_id, {})
        decision = connection.get("connection_decision") if isinstance(connection.get("connection_decision"), dict) else {}
        constraints = connection.get("constraints") if isinstance(connection.get("constraints"), dict) else {}

        method = decision.get("method") if isinstance(decision.get("method"), str) else connection.get("method")
        explicit_alignment = (
            (isinstance(method, str) and method == "pinned")
            or _is_true(decision.get("needs_alignment"))
            or _is_true(connection.get("needs_alignment"))
            or _is_true(constraints.get("needs_alignment"))
        )

        sanitized: list[dict] = []
        suppressed_default = 0
        for change in derived_changes:
            if not isinstance(change, dict):
                sanitized.append(change)
                continue
            feature = change.get("feature") if isinstance(change.get("feature"), str) else ""
            if feature == "alignment_pin_hole" and not explicit_alignment:
                suppressed_default += 1
                continue
            sanitized.append(change)

        if suppressed_default > 0:
            audit_entries.append(
                {
                    "rule": "alignment_pin_explicit_only",
                    "connection_id": connection_id,
                    "base_connection_id": base_connection_id,
                    "method": method,
                    "suppressed_count": suppressed_default,
                    "reason": "alignment pin hole not explicitly requested (requires method='pinned' or needs_alignment=true)",
                }
            )

        grouped_original: Dict[str, list[dict]] = {}
        for change in derived_changes:
            if not isinstance(change, dict):
                continue
            feature_group_id = change.get("feature_group_id")
            if isinstance(feature_group_id, str) and feature_group_id:
                grouped_original.setdefault(feature_group_id, []).append(change)

        suppressed_group = 0
        if not explicit_alignment:
            for feature_group_id, items in grouped_original.items():
                has_hole_strategy = any(
                    isinstance(item.get("feature"), str)
                    and item.get("feature") == "hole"
                    and item.get("hole_type") in {"threaded_hole", "clearance_hole"}
                    for item in items
                )
                if not has_hole_strategy:
                    continue
                for item in items:
                    if isinstance(item.get("feature"), str) and item.get("feature") == "alignment_pin_hole":
                        suppressed_group += 1

            if suppressed_group > 0:
                audit_entries.append(
                    {
                        "rule": "hole_strategy_exclusive_per_feature_group",
                        "connection_id": connection_id,
                        "base_connection_id": base_connection_id,
                        "method": method,
                        "suppressed_count": suppressed_group,
                        "reason": "alignment_pin_hole removed because feature_group already contains threaded_hole/clearance_hole without explicit alignment request",
                    }
                )

        placement["derived_changes"] = sanitized

    return audit_entries


def _infer_deterministic_derived_changes(kg: Dict[str, Any]) -> Dict[str, list[dict]]:
    comp_by_id: Dict[str, Dict[str, Any]] = {}
    for c in kg.get("components", []) or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if isinstance(cid, str) and cid:
            comp_by_id[cid] = c
    type_by_id = {
        cid: comp.get("type")
        for cid, comp in comp_by_id.items()
    }

    unresolved_bearing_ids: set[str] = set()
    metadata = kg.get("metadata") if isinstance(kg.get("metadata"), dict) else {}
    unresolved_raw = metadata.get("unresolved_bearing_component_ids") if isinstance(metadata, dict) else []
    if isinstance(unresolved_raw, list):
        unresolved_bearing_ids = {cid for cid in unresolved_raw if isinstance(cid, str)}

    derived_by_connection: Dict[str, list[dict]] = {}

    interface_rules_by_size = _build_fastener_interface_rules_by_size(kg)
    pair_purposes_by_key = _build_connection_pair_purpose_index(kg, comp_by_id=comp_by_id)

    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, dict):
            continue
        cr_id = cr.get("id")
        if not isinstance(cr_id, str):
            continue
        between = cr.get("between", [])
        if isinstance(between, dict):
            between_ids = [cid for cid in between.keys() if isinstance(cid, str)]
        elif isinstance(between, list):
            between_ids = [cid for cid in between if isinstance(cid, str)]
        else:
            continue

        purpose = cr.get("purpose")
        constraints = cr.get("constraints") if isinstance(cr.get("constraints"), dict) else {}
        connection_decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), dict) else {}

        changes: list[dict] = []

        bearing_ids = [
            cid for cid in between_ids
            if type_by_id.get(cid) == "bearing" and cid not in unresolved_bearing_ids
        ]
        shaft_ids = [cid for cid in between_ids if type_by_id.get(cid) in {"shaft", "axle"}]
        key_ids = [cid for cid in between_ids if type_by_id.get(cid) == "key"]
        non_fastener_ids = [
            cid for cid in between_ids
            if not _is_fastener_type(type_by_id.get(cid))
            and not _is_subassembly_component(comp_by_id.get(cid, {}))
            and cid not in unresolved_bearing_ids
        ]
        preferred_host = _choose_feature_host(comp_by_id, non_fastener_ids)
        contract = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids={cid for cid in _between_to_ids(cr.get("between")) if isinstance(cid, str)},
        )
        authoritative_host = None
        if isinstance(contract, Mapping):
            authoritative_host = _resolve_authoritative_modeling_host_component(
                comp_by_id=comp_by_id,
                contract=contract,
            )
        mechanism_name, mechanism_meta = _infer_connection_feature_mechanism(
            placement={"between": between_ids, "purpose": purpose},
            connection=cr,
            comp_by_id=comp_by_id,
            pair_purposes_by_key=pair_purposes_by_key,
        )
        requires_mount_clarification = _connection_uses_generic_autofilled_fastener_mount(cr)
        geometric_contract = contract.get("geometric_semantics") if isinstance(contract, Mapping) and isinstance(contract.get("geometric_semantics"), Mapping) else {}
        slot_bolted_retention = (
            mechanism_name == "axial_face_bolted_mount"
            and str(geometric_contract.get("contact_model") or "").strip().lower() in {"slot_insert_with_bolted_retention", "through_bolt_clamp_in_radial_slot"}
            and str(geometric_contract.get("support_topology") or "").strip().lower() == "hub_radial_slot_mount"
        )
        allow_fastener_geometry = (mechanism_name in {"bolted_mount", "radial_member_bolted_mount"} or slot_bolted_retention) and not requires_mount_clarification

        # === NEW: Semantic hole generation based on connection_decision ===
        # Generate holes using carrier/target determination, NOT plate-like component gate
        if purpose in {"fastening_mechanism", "structural_fixation", "structural_clamping"} and allow_fastener_geometry:
            fastener_holes = _plan_fastener_holes(
                cr,
                comp_by_id,
                connection_decision,
                interface_rules_by_size=interface_rules_by_size,
                unresolved_bearing_ids=unresolved_bearing_ids,
            )
            changes.extend(fastener_holes)
        
        # === Legacy fastener_head_seat and related features (preserved for backward compatibility) ===
        fastener_size = connection_decision.get("fastener_size")
        if isinstance(fastener_size, str):
            nominal, _ = _parse_fastener_size(fastener_size)
        else:
            nominal = None
        method = connection_decision.get("method")
        stackup = connection_decision.get("stackup")
        count = connection_decision.get("count") if isinstance(connection_decision.get("count"), int) else None
        contact_model = str(geometric_contract.get("contact_model") or "").strip().lower()
        hardware_layout = str(geometric_contract.get("hardware_layout") or "").strip().lower()
        external_nut_clamp = contact_model == "through_bolt_clamp_in_radial_slot" or hardware_layout == "through_bolt_external_nut_clamp"
        
        if nominal and mechanism_name in {"bolted_mount", "radial_member_bolted_mount", "axial_face_bolted_mount"} and not requires_mount_clarification:
            clearance = round(nominal + 0.5, 2)
            head_dia, head_height = _head_seat_dimensions(nominal)

            if preferred_host and method in {"bolted_rigid", "bolted_hinged"} and not external_nut_clamp:
                changes.append({
                    "target_component_id": preferred_host,
                    "feature": "fastener_head_seat",
                    "diameter": head_dia,
                    "depth": head_height,
                    "purpose": "fastener_head_clearance",
                    "source": "connection_decision.method",
                })
            if preferred_host and stackup in {"through_nut", "insert"} and not external_nut_clamp:
                changes.append({
                    "target_component_id": preferred_host,
                    "feature": "nut_seat",
                    "diameter": round(nominal * 1.6, 2),
                    "depth": round(nominal * 0.8, 2),
                    "purpose": "nut_clearance",
                    "source": "connection_decision.stackup",
                })

            if purpose == "structural_clamping" and preferred_host:
                changes.append({
                    "target_component_id": preferred_host,
                    "feature": "clamp_slot",
                    "width": round(clearance * 1.2, 2),
                    "purpose": "clamping_compliance",
                    "source": "structural_clamping",
                })
                host = comp_by_id.get(preferred_host, {})
                host_shape = host.get("shape_semantics") if isinstance(host.get("shape_semantics"), dict) else {}
                if host_shape.get("type") == "cylindrical":
                    changes.append({
                        "target_component_id": preferred_host,
                        "feature": "split_clamp_bore",
                        "diameter": round(clearance * 1.1, 2),
                        "purpose": "clamping_compliance",
                        "source": "structural_clamping",
                    })

        # Bearing seat and retention features
        if bearing_ids and (purpose in {"load_support", "support_to_structure"} or mechanism_name == "press_fit"):
            for bearing_id in bearing_ids:
                bearing = comp_by_id.get(bearing_id, {})
                bdims = bearing.get("dimensions") if isinstance(bearing.get("dimensions"), dict) else {}
                bore_outer = bdims.get("outer_diameter")
                width = bdims.get("width") or bdims.get("thickness")
                host_id = authoritative_host or preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
                if host_id and bore_outer:
                    seat = {
                        "target_component_id": host_id,
                        "feature": "bearing_seat",
                        "bore_diameter": bore_outer,
                        "depth": width if width else "match_bearing_width",
                        "fit": "press" if connection_decision.get("fit_policy") == "press" or method == "press_fit" else "clearance",
                        "purpose": "outer_race_support",
                        "source": f"bearing.{bearing_id}",
                    }
                    changes.append(seat)
                    if constraints.get("must_limit_axial"):
                        changes.append({
                            "target_component_id": host_id,
                            "feature": "retainer_groove",
                            "diameter": bore_outer,
                            "purpose": "axial_retention",
                            "source": "constraints.must_limit_axial",
                        })
                        changes.append({
                            "target_component_id": host_id,
                            "feature": "seal_groove",
                            "diameter": bore_outer,
                            "purpose": "seal_lip",
                            "source": "bearing_retention",
                        })
                    if method == "press_fit":
                        changes.append({
                            "target_component_id": host_id,
                            "feature": "press_fit_zone",
                            "diameter": bore_outer,
                            "length": width if width else "match_bearing_width",
                            "purpose": "interference_fit",
                            "source": "connection_decision.method",
                        })

        # Shaft bores for rotation or torque transfer
        if shaft_ids and (purpose in {"rotation", "rotation_support", "torque_transfer"} or mechanism_name == "shaft_bore_fit"):
            for shaft_id in shaft_ids:
                shaft = comp_by_id.get(shaft_id, {})
                sdims = shaft.get("dimensions") if isinstance(shaft.get("dimensions"), dict) else {}
                shaft_d = sdims.get("diameter")
                if not shaft_d:
                    continue
                host_id = authoritative_host or preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
                if host_id and type_by_id.get(host_id) not in {"bearing", "shaft", "axle"}:
                    changes.append({
                        "target_component_id": host_id,
                        "feature": "shaft_bore",
                        "diameter": shaft_d,
                        "fit": "press" if connection_decision.get("fit_policy") == "press" or method == "press_fit" else "clearance",
                        "purpose": "shaft_support",
                        "source": f"shaft.{shaft_id}",
                    })
                    if method == "press_fit":
                        changes.append({
                            "target_component_id": host_id,
                            "feature": "press_fit_zone",
                            "diameter": shaft_d,
                            "length": "match_shaft_contact",
                            "purpose": "interference_fit",
                            "source": "connection_decision.method",
                        })

        # Keyway or spline for torque transfer
        if purpose == "torque_transfer" and (key_ids or connection_decision.get("method") == "keyed"):
            key_dims = {}
            if key_ids:
                key = comp_by_id.get(key_ids[0], {})
                key_dims = key.get("dimensions") if isinstance(key.get("dimensions"), dict) else {}
            shaft_d = None
            if shaft_ids:
                shaft = comp_by_id.get(shaft_ids[0], {})
                sdims = shaft.get("dimensions") if isinstance(shaft.get("dimensions"), dict) else {}
                shaft_d = sdims.get("diameter")
            key_width = key_dims.get("width") or (shaft_d / 4 if shaft_d else None)
            key_height = key_dims.get("height") or (shaft_d / 4 if shaft_d else None)
            key_length = key_dims.get("length")
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id and type_by_id.get(host_id) not in {"shaft", "axle", "bearing"}:
                changes.append({
                    "target_component_id": host_id,
                    "feature": "keyway_slot",
                    "width": key_width,
                    "height": key_height,
                    "length": key_length,
                    "purpose": "torque_transfer",
                    "source": "torque_transfer",
                })

        # Alignment pin holes only when explicitly requested.
        needs_alignment = connection_decision.get("needs_alignment") is True or constraints.get("needs_alignment") is True
        if purpose in {"structural_fixation", "structural_clamping"} and (
            connection_decision.get("method") == "pinned" or needs_alignment
        ):
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id:
                changes.append({
                    "target_component_id": host_id,
                    "feature": "alignment_pin_hole",
                    "diameter": nominal or 3,
                    "purpose": "alignment",
                    "source": "explicit_alignment_request",
                })

        # Mounting face and bolt circle for rigid fixation
        if purpose in {"structural_fixation", "structural_clamping"} and allow_fastener_geometry:
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id:
                host_dims = comp_by_id.get(host_id, {}).get("dimensions") if isinstance(comp_by_id.get(host_id, {}), dict) else {}
                host_diameter = None
                if isinstance(host_dims, dict):
                    host_diameter = host_dims.get("outer_diameter") or host_dims.get("diameter")
                changes.append({
                    "target_component_id": host_id,
                    "feature": "mounting_face",
                    "purpose": "mounting",
                    "source": "structural_fixation",
                })
                if nominal:
                    changes.append({
                        "target_component_id": host_id,
                        "feature": "bolt_circle_pattern",
                        "count": count or 4,
                        "pattern_radius": round(float(host_diameter) * 0.35, 2) if isinstance(host_diameter, (int, float)) else None,
                        "hole_diameter": round(nominal + 0.5, 2),
                        "purpose": "fastener_pattern",
                        "source": "connection_decision.fastener_size",
                    })

        # Local thickening around high-load fixes
        if constraints.get("must_be_rigid") or constraints.get("must_support_load"):
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id:
                changes.append({
                    "target_component_id": host_id,
                    "feature": "local_thickening",
                    "purpose": "stiffness",
                    "source": "constraints",
                })

        # Spacing-related standoff or sleeve bore
        if purpose == "spacing" and mechanism_name in {"bolted_mount", "radial_member_bolted_mount", "axial_face_bolted_mount"}:
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id and nominal:
                changes.append({
                    "target_component_id": host_id,
                    "feature": "standoff_bore",
                    "diameter": round(nominal + 0.5, 2),
                    "purpose": "spacing",
                    "source": "spacing",
                })

        # Bonding or welding zones
        if method in {"welded", "adhesive", "glued", "bonded_rigid"} or mechanism_name in {"bonded_tread", "bonded_mount"}:
            host_id = preferred_host or _choose_feature_host(comp_by_id, non_fastener_ids)
            if host_id:
                changes.append({
                    "target_component_id": host_id,
                    "feature": "bonding_zone",
                    "purpose": "join_surface",
                    "source": "connection_decision.method",
                })

        if changes:
            derived_by_connection.setdefault(cr_id, []).extend(changes)

    return derived_by_connection


def _apply_deterministic_derived_changes(
    kg: Dict[str, Any],
    placements: list[dict]
) -> None:
    derived_by_connection = _infer_deterministic_derived_changes(kg)
    if not derived_by_connection:
        return
    valid_component_ids = {
        c.get("id")
        for c in kg.get("components", []) or []
        if isinstance(c, dict)
        and isinstance(c.get("id"), str)
        and c.get("type") not in {"subassembly", "module"}
    }
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        cid = placement.get("connection_id")
        if cid not in derived_by_connection:
            continue
        between_ids = _between_to_ids(placement.get("between"))
        existing = placement.get("derived_changes")
        if not isinstance(existing, list):
            existing = []
        merged = _merge_derived_changes(existing, derived_by_connection[cid])
        placement["derived_changes"] = _filter_derived_changes(
            merged,
            allowed_component_ids=set(between_ids) & valid_component_ids,
        )


def _ensure_holes_for_fasteners(kg: Dict[str, Any], placements: list[dict]) -> None:
    """
    闂侇偅姘ㄩ弫銈団偓娑欐钘熼柛蹇嬪妼閸ら亶寮敮顔剧獥缁绢収鍠曠换姘跺箥閳ь剟寮垫径瀣畳fastener_spec闁汇劌鍩acement闂侇喛濮ゅ﹢浣衡偓鐢垫嚀缁ㄦ煡鎯冮崟顐ゆ憰閻庤鐭粻鐔煎Υ?
    
    閻犱焦宕橀鎼佸储閻斿嘲鐏熼柨?
    - 閺夆晜鐟﹀Σ鎼佸极閻楀牆绁﹂悗鐟版湰閺嗭綁骞€瑜岀换姘舵⒕濠婃劗绀夊☉鎾崇У濡叉悂鏌﹂崼婵愬殸闁绘鎳撻悾鐐亜閸︻厽绐楅柣銊ュ钘熷☉?
    - 濠碘€冲€归悘澶愬嫉婵夌敘stener_spec濞达絽鎽糴rived_changes濞戞搩鍘藉Λ銈団偓娑欐缁辨繈鎳涢鍕楅柣銏㈠枑閸ㄦ碍顪€濡鍚囬悗娑欐煥閻ｇ偓绋?
    - 闁糕晞妗ㄧ花鐞璦stener閻熸瑥瀚悧鎼佸椽瀹€鈧划宥嗙閸撲浇顫﹂柛銊ヮ儐鐢綊寮鐐垫憰闁告瑥鍊归弳鐔兼晬閸垺绾€垫澘瀚ㄩ埀顑胯兌鐞氼偊宕圭€ｃ劉鍋撴担瑙勬闂佹彃楠忕槐?
    
    Args:
        kg: Knowledge graph
        placements: Connection placements闁告帗顨夐妴鍐晬閸粎绐楅柛妯煎枎濠€瀛樼┍椤旇姤鏆柨?
    """
    # 闁哄瀚紓鎾剁磼閸曨亝顐介柡鍕Т閻?
    comp_by_id: Dict[str, Dict[str, Any]] = {}
    for c in kg.get("components", []) or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if isinstance(cid, str) and cid:
            comp_by_id[cid] = c

    unresolved_bearing_ids: set[str] = set()
    metadata = kg.get("metadata") if isinstance(kg.get("metadata"), dict) else {}
    unresolved_raw = metadata.get("unresolved_bearing_component_ids") if isinstance(metadata, dict) else []
    if isinstance(unresolved_raw, list):
        unresolved_bearing_ids = {cid for cid in unresolved_raw if isinstance(cid, str)}

    interface_rules_by_size = _build_fastener_interface_rules_by_size(kg)
    
    for placement in placements:
        if not isinstance(placement, dict):
            continue

        flags_raw = placement.get("flags")
        flags = flags_raw if isinstance(flags_raw, dict) else {}
        if flags.get("suppress_hole_generation") is True:
            continue
        
        # 婵☆偀鍋撻柡灞诲劜濡叉悂宕ラ敂鑺ョ畳fastener_spec
        fastener_spec = placement.get("fastener_spec")
        if not fastener_spec or not isinstance(fastener_spec, dict):
            continue

        mechanism_name = _sanitize_connection_mechanism(placement.get("connection_mechanism"))
        if mechanism_name == "shaft_bore_fit":
            continue

        # 婵☆偀鍋撻柡宀婃珨erived_changes濞戞搩鍘藉Σ鎼佸触閿曗偓閸戯繝寮垫径濠勬憰
        derived_changes = placement.get("derived_changes", [])
        if not isinstance(derived_changes, list):
            derived_changes = []
            placement["derived_changes"] = derived_changes
        
        has_holes = False
        for change in derived_changes:
            if isinstance(change, dict):
                feature = change.get("feature", "").lower()
                if "hole" in feature or "bolt" in feature or "countersink" in feature or "counterbore" in feature:
                    has_holes = True
                    break
        
        # 濠碘€冲€归悘澶婎啅閸欏绠掗悗娑欐煥閻ｇ偓绋婃径娑氱閻犲搫鐤囩换?
        if has_holes:
            continue
        
        # === 闁汇垻鍠愰崹姘渶濡鍚囬悗娑欐煥閻ｇ偓绋?===
        
        # 閻熸瑱绲鹃悗绲漚stener閻熸瑥瀚悧?
        fastener_size = fastener_spec.get("size")
        if not isinstance(fastener_size, str):
            continue
        
        nominal, _ = _parse_fastener_size(fastener_size)
        if not nominal:
            continue
        
        # 闁兼儳鍢茶ぐ鍥ㄦ交閻愭潙澶嶉柣銊ュ缁秵绂?
        between = placement.get("between", [])
        if not isinstance(between, list) or len(between) == 0:
            continue
        
        # 閺夆晛娲﹂幎銈夊箳婵夌敘stener缂侇偉顕ч悗鐑芥儍閸曨厾鐭嬪ù?
        target_components = [
            cid for cid in between
            if not _is_fastener_type(comp_by_id.get(cid, {}).get("type"))
            and not _is_subassembly_component(comp_by_id.get(cid, {}))
            and cid not in unresolved_bearing_ids
        ]
        
        if not target_components:
            continue
        
        # 閻犱緤绱曢悾鑽も偓娑欐⒒濞插灝顕ラ崟鍓佺clearance闁? 濞村吋锚閸樻稒鎷呯捄銊︽殢闁哄秴娲ら崳顖涚閼搁潧澶嶉柛娆欑秬椤宕氬▎娆戠ISO273闁?
        clearance_dia = _resolve_fastener_clearance_diameter(
            nominal_mm=nominal,
            fit_policy=fastener_spec.get("fit_policy"),
            fastener_size=fastener_size,
            interface_rules_by_size=interface_rules_by_size,
            fallback_diameter_mm=fastener_spec.get("hole_diameter"),
        )
        
        # 闁兼儳鍢茶ぐ鍣乤stener闁轰椒鍗抽崳?
        fastener_count = fastener_spec.get("count", 1)
        pattern = None
        if fastener_count and isinstance(fastener_count, int) and fastener_count > 1:
            pattern = {"type": "circular", "count": fastener_count}
        
        # 濞戞挾鍎ら惁鈩冪▔椤忓棙绐楅柡宥呮川缁秵绂掗崜浣规櫢闁瑰瓨鍔曢悺鐔衡偓瑙勭煯缁?
        # 缂佹稒鐗滈弳鎰版晬濮樿鲸鏅搁柟瀛樹邯learance hole濞达絾绮堢拹鐔兼焻濮樿鲸鏆忓娑欘焾椤撳鏁嶉崼銉㈠亾閸屾粍鏆忓ù婊冮閵囧洦寰勫顓熸bolted閺夆晝鍋炵敮鎾晬?
        for target_id in target_components:
            comp = comp_by_id.get(target_id, {})
            comp_type = comp.get("type", "").lower()
            
            # 闁糕晞妗ㄧ花顒傜磼閸曨亝顐界紒顐ヮ嚙閻庣兘骞掗妸锔界劷閻庢稒姊荤悮顐﹀垂?
            # 缂備焦鎸婚悗顖滅尵鐠囪尙鈧兘鏁嶉崸鏀梑/housing/frame闁挎稑顦崯?闁告瑯鍨甸崗姗€妫侀埀顒傛啺娑旂撤readed hole
            # 闁哄娉曠悮顐︽晬閸ь湶ate/arm闁挎稑顦崯?clearance hole
            is_structural = any(kw in comp_type for kw in ["hub", "housing", "frame", "body", "axle", "shaft"])
            is_plate = _is_plate_like_component(comp)
            
            # 濮掓稒顭堥鑽ょ驳閺嶎偅娈ｉ柨娑欐皑椤戝洦绋夐埀顒佺▔椤忓棛鐭嬪ù鐘殿瀳learance闁挎稑鑻幃妤冪磼椤撶姷鐭嬪ù鐘殿潫hreaded闁挎稑鐗嗛々褔寮稿鍕︾紓浣规尰閻庮垱绂掔拋鍦
            if target_components.index(target_id) == 0 or is_plate:
                # Carrier side: clearance hole
                hole_def = {
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "clearance_hole",
                    "diameter": clearance_dia,
                    "depth": "through",
                    "purpose": "fastener_pass",
                    "source": "auto_inferred_from_fastener_spec",
                    "confidence": "default_clearance"
                }
                if pattern:
                    hole_def["pattern"] = pattern
                derived_changes.append(hole_def)

            elif is_structural:
                # Target side: threaded hole for structural components
                tap_drill_dia = _resolve_fastener_tap_drill_diameter(
                    nominal_mm=nominal,
                    fastener_size=fastener_size,
                    interface_rules_by_size=interface_rules_by_size,
                )
                hole_def = {
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "threaded_hole",
                    "diameter": nominal,
                    "pilot_diameter": tap_drill_dia,
                    "depth": round(nominal * 2.0, 2),  # Blind hole, 2x nominal depth
                    "purpose": "fastener_thread_engagement",
                    "source": "auto_inferred_from_fastener_spec",
                    "confidence": "inferred_from_component_type"
                }
                if pattern:
                    hole_def["pattern"] = pattern
                derived_changes.append(hole_def)
            else:
                # Fallback: clearance hole
                hole_def = {
                    "target_component_id": target_id,
                    "feature": "hole",
                    "hole_type": "clearance_hole",
                    "diameter": clearance_dia,
                    "depth": "through",
                    "purpose": "fastener_pass",
                    "source": "auto_inferred_from_fastener_spec",
                    "confidence": "default_clearance"
                }
                if pattern:
                    hole_def["pattern"] = pattern
                derived_changes.append(hole_def)


def _thread_designation_from_fastener_size(fastener_size: Any) -> str:
    nominal, _ = _parse_fastener_size(fastener_size if isinstance(fastener_size, str) else None)
    if not isinstance(nominal, (int, float)):
        return "M8x1.25"

    pitch_table = {
        2.0: 0.4,
        2.5: 0.45,
        3.0: 0.5,
        4.0: 0.7,
        5.0: 0.8,
        6.0: 1.0,
        8.0: 1.25,
        10.0: 1.5,
        12.0: 1.75,
    }
    closest = min(pitch_table.keys(), key=lambda k: abs(float(k) - float(nominal)))
    nominal_label = str(int(closest)) if abs(float(closest) - int(float(closest))) < 1e-9 else str(closest)
    pitch = pitch_table[closest]
    pitch_label = str(int(pitch)) if abs(float(pitch) - int(float(pitch))) < 1e-9 else str(pitch)
    return f"M{nominal_label}x{pitch_label}"


def _detect_rotating_wheel_support_mount_conflict(
    *,
    placement: Mapping[str, Any],
    connection: Mapping[str, Any],
    connection_by_id: Mapping[str, Mapping[str, Any]],
    comp_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any] | None:
    between_raw = placement.get("between") if isinstance(placement.get("between"), list) else connection.get("between")
    between_ids = [cid for cid in between_raw if isinstance(cid, str) and cid] if isinstance(between_raw, list) else []
    if len(between_ids) < 2:
        return None

    purpose_raw = connection.get("purpose") if isinstance(connection.get("purpose"), str) and connection.get("purpose") else placement.get("purpose")
    purpose_norm = str(purpose_raw).strip().lower() if isinstance(purpose_raw, str) else None
    if purpose_norm not in {"fastening_mechanism", "structural_fixation", "structural_clamping"}:
        return None

    def _ctype(component_id: str) -> str:
        comp = comp_by_id.get(component_id, {}) if isinstance(comp_by_id, Mapping) else {}
        ctype = comp.get("type") if isinstance(comp, Mapping) else None
        return str(ctype).strip().lower() if isinstance(ctype, str) else ""

    wheel_ids = [cid for cid in between_ids if _ctype(cid) == "wheel"]
    support_ids = [cid for cid in between_ids if _ctype(cid) in {"arm", "fork", "bracket", "carrier", "frame", "support", "link"}]
    if not wheel_ids or not support_ids:
        return None

    rotating_supports_by_wheel: Dict[str, set[str]] = {}
    for other in connection_by_id.values():
        if not isinstance(other, Mapping):
            continue
        other_purpose_raw = other.get("purpose")
        other_purpose = str(other_purpose_raw).strip().lower() if isinstance(other_purpose_raw, str) else None
        if other_purpose not in {"rotation", "torque_transfer"}:
            continue
        other_between = [cid for cid in other.get("between", []) if isinstance(cid, str) and cid]
        if len(other_between) < 2:
            continue
        other_wheels = [cid for cid in other_between if _ctype(cid) == "wheel"]
        rotor_support_ids = [cid for cid in other_between if _ctype(cid) in {"axle", "shaft"}]
        if not other_wheels or not rotor_support_ids:
            continue
        for wheel_id in other_wheels:
            rotating_supports_by_wheel.setdefault(wheel_id, set()).update(rotor_support_ids)

    conflicting_wheels = sorted([cid for cid in wheel_ids if rotating_supports_by_wheel.get(cid)])
    if not conflicting_wheels:
        return None

    return {
        "conflicting_wheels": conflicting_wheels,
        "support_component_ids": sorted(set(support_ids)),
        "rotating_support_ids": sorted(
            {support_id for wheel_id in conflicting_wheels for support_id in rotating_supports_by_wheel.get(wheel_id, set())}
        ),
        "reason": "direct_wheel_to_support_mount_conflicts_with_independent_wheel_rotation",
    }


def _rewrite_connection_feature_mechanisms(kg: Dict[str, Any], placements: list[dict]) -> list[dict]:
    comp_by_id = _build_comp_by_id(kg)
    connection_by_id: Dict[str, Dict[str, Any]] = {
        cr["id"]: cr
        for cr in kg.get("connection_requirements", []) or []
        if isinstance(cr, dict) and isinstance(cr.get("id"), str)
    }
    pair_purposes_by_key = _build_connection_pair_purpose_index(kg, comp_by_id=comp_by_id)
    audit_entries: list[dict] = []

    for placement in placements:
        if not isinstance(placement, dict):
            continue

        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else ""
        base_connection_id = connection_id.split("@", 1)[0] if "@" in connection_id else connection_id
        connection = connection_by_id.get(base_connection_id, {})
        mechanism_name, mechanism_meta = _infer_connection_feature_mechanism(
            placement=placement,
            connection=connection,
            comp_by_id=comp_by_id,
            pair_purposes_by_key=pair_purposes_by_key,
        )
        placement["connection_mechanism"] = mechanism_name
        if mechanism_meta:
            placement.setdefault("mechanism_audit", mechanism_meta)

        target_id = _resolve_split_target_component_id(placement)
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern_params = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        flags = _sanitize_placement_flags(placement.get("flags"))

        def _strip_features(features: set[str]) -> list[str]:
            removed: list[str] = []
            kept: list[dict] = []
            for change in derived_changes:
                if not isinstance(change, dict):
                    kept.append(change)
                    continue
                feature = change.get("feature") if isinstance(change.get("feature"), str) else ""
                if feature in features:
                    removed.append(feature)
                    continue
                kept.append(change)
            placement["derived_changes"] = kept
            return removed

        rotation_conflict = _detect_rotating_wheel_support_mount_conflict(
            placement=placement,
            connection=connection,
            connection_by_id=connection_by_id,
            comp_by_id=comp_by_id,
        )
        if isinstance(rotation_conflict, Mapping):
            removed = _strip_features(SUPPRESSED_HOLE_FEATURES)
            placement["derived_changes"] = []
            placement.pop("fastener_spec", None)
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            placement["connection_mechanism"] = "semantic_conflict_direct_rotor_mount"
            placement["mechanism_audit"] = {
                "source": "semantic_contract_guard",
                "reason": "direct_wheel_to_support_mount_conflicts_with_rotation_chain",
            }
            placement["requires_clarification"] = True
            placement["clarification_reason"] = "conflicting_direct_rotating_wheel_mount"
            placement["status"] = "requires_clarification"
            audit_entries.append(
                {
                    "connection_id": connection_id,
                    "mechanism": "semantic_conflict_direct_rotor_mount",
                    "action": "suppressed_conflicting_rotating_wheel_mount",
                    "removed_features": removed,
                    **dict(rotation_conflict),
                }
            )
            continue

        if mechanism_name == "generic_mount" and _placement_requires_explicit_fastener_mount_clarification(placement=placement, connection=connection):
            removed = _strip_features(SUPPRESSED_HOLE_FEATURES)
            placement.pop("fastener_spec", None)
            _force_single_pattern_layout(location, placement.get("placement_intent") if isinstance(placement.get("placement_intent"), dict) else None)
            placement["location"] = location
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            placement["requires_clarification"] = True
            placement["clarification_reason"] = "generic_fastener_mount_requires_explicit_anchor_semantics"
            placement["status"] = "requires_clarification"
            placement["mechanism_audit"] = {
                "source": "semantic_authority_guard",
                "reason": "autofilled_fastener_decision_without_explicit_anchor_semantics",
            }
            audit_entries.append(
                {
                    "connection_id": connection_id,
                    "mechanism": mechanism_name,
                    "action": "suppressed_ambiguous_generic_fastener_mount",
                    "removed_features": removed,
                    "reason": "auto-filled fastener decision lacked explicit anchor semantics",
                }
            )
            continue

        if mechanism_name in {"bonded_tread", "bonded_mount", "press_fit", "companion_rotation_relation", "axial_stack_locator"}:
            removed = _strip_features(SUPPRESSED_HOLE_FEATURES)
            placement.pop("fastener_spec", None)
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            if pattern_params:
                pattern_params["type"] = "single"
                pattern_params["count"] = 1
                pattern_params.pop("pattern_radius", None)
                pattern_params.pop("spacing", None)
                pattern_params.pop("preserve_single_circular", None)
                location["pattern_parameters"] = pattern_params
                placement["location"] = location
            if removed:
                audit_entries.append(
                    {
                        "connection_id": connection_id,
                        "mechanism": mechanism_name,
                        "action": "suppressed_hole_features",
                        "removed_features": removed,
                    }
                )
            continue

        if mechanism_name == "shaft_bore_fit":
            removed = _strip_features(SUPPRESSED_HOLE_FEATURES | {"bearing_seat", "press_fit_zone", "retainer_groove", "seal_groove", "standoff_bore"})
            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            pattern_params.pop("pattern_radius", None)
            pattern_params.pop("pattern_radius_mm", None)
            pattern_params.pop("spacing", None)
            pattern_params.pop("preserve_single_circular", None)
            location["pattern_parameters"] = pattern_params
            placement["location"] = location
            placement.pop("fastener_spec", None)
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            placement_intent = placement.get("placement_intent") if isinstance(placement.get("placement_intent"), dict) else {}
            if placement_intent:
                placement_intent["pattern_type"] = "single"
                placement_intent["symmetry"] = "single"
                placement["placement_intent"] = placement_intent
            audit_entries.append(
                {
                    "connection_id": connection_id,
                    "mechanism": mechanism_name,
                    "action": "single_center_bore",
                    "removed_features": removed,
                }
            )
            continue

        if mechanism_name not in {"radial_member_bolted_mount", "axial_face_bolted_mount"} or not isinstance(anchor_semantics, Mapping) or not isinstance(target_id, str):
            continue

        reference_id = anchor_semantics.get("reference_component_id")
        moving_id = anchor_semantics.get("moving_component_id")
        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), dict) else None

        if target_id == reference_id:
            removed = _strip_features({"bolt_circle_pattern", "mounting_face", "fastener_head_seat"})
            pattern_params["type"] = "circular"
            pattern_params["count"] = 1
            pattern_params["preserve_single_circular"] = True
            pattern_params.setdefault("radius_policy", "fraction_of_host")
            pattern_params.setdefault("start_angle", 0.0)
            location["pattern_parameters"] = pattern_params
            placement["location"] = location
            placement_intent = placement.get("placement_intent") if isinstance(placement.get("placement_intent"), dict) else {}
            if placement_intent:
                placement_intent["pattern_type"] = "circular"
                placement_intent["symmetry"] = "single"
                placement["placement_intent"] = placement_intent
            if fastener_spec is not None:
                placement["fastener_spec"] = _normalize_fastener_spec_single_instance(fastener_spec)
            if removed:
                audit_entries.append(
                    {
                        "connection_id": connection_id,
                        "mechanism": mechanism_name,
                        "action": "reference_side_single_radial_mount",
                        "removed_features": removed,
                    }
                )
            continue

        if target_id == moving_id:
            removed = _strip_features({"bolt_circle_pattern", "mounting_face"})
            moving_anchor = anchor_semantics.get("moving_anchor") if isinstance(anchor_semantics.get("moving_anchor"), Mapping) else {}
            if mechanism_name == "axial_face_bolted_mount":
                moving_kind = str(moving_anchor.get("kind") or "").strip().lower()
                derived_interface_name = "bottom_face" if moving_kind.endswith("_min") else "top_face"
            else:
                derived_interface_name = _face_interface_for_end_anchor(moving_anchor)

            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
            current_interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
            preserved_semantic_interface = _is_semantic_placeholder_interface_name(current_interface_name)
            if preserved_semantic_interface:
                interface_ref["component_id"] = target_id
                if not isinstance(interface_ref.get("semantic_role"), str) or not interface_ref.get("semantic_role"):
                    interface_ref["semantic_role"] = "mounting"
                location["interface_ref"] = interface_ref
                applied_interface_name = current_interface_name
            elif derived_interface_name:
                interface_ref["name"] = derived_interface_name
                interface_ref["component_id"] = target_id
                interface_ref["semantic_role"] = "mounting"
                interface_geo = _infer_geometry_type_from_interface_id(derived_interface_name, "mounting")
                interface_ref["geometry_type"] = interface_geo
                interface_ref["geom_type"] = interface_geo
                location["interface_ref"] = interface_ref
                applied_interface_name = derived_interface_name
            else:
                applied_interface_name = current_interface_name

            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            pattern_params.pop("pattern_radius", None)
            pattern_params.pop("spacing", None)
            pattern_params.pop("preserve_single_circular", None)
            location["pattern_parameters"] = pattern_params
            placement["location"] = location
            placement_intent = placement.get("placement_intent") if isinstance(placement.get("placement_intent"), dict) else {}
            if placement_intent:
                placement_intent["pattern_type"] = "single"
                placement_intent["symmetry"] = "single"
                placement["placement_intent"] = placement_intent
            if fastener_spec is not None:
                placement["fastener_spec"] = _normalize_fastener_spec_single_instance(fastener_spec)
            if removed or applied_interface_name:
                audit_entries.append(
                    {
                        "connection_id": connection_id,
                        "mechanism": mechanism_name,
                        "action": "moving_side_end_face_mount",
                        "removed_features": removed,
                        "interface_name": applied_interface_name,
                        "preserved_semantic_interface": preserved_semantic_interface,
                    }
                )
    return audit_entries


def _rewrite_axial_retention_on_shaft(kg: Dict[str, Any], placements: list[dict]) -> None:
    comp_type_by_id: Dict[str, str] = {}
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and cid and isinstance(ctype, str):
            comp_type_by_id[cid] = ctype.lower()

    connection_by_id: Dict[str, Dict[str, Any]] = {}
    for cr in kg.get("connection_requirements", []) or []:
        if isinstance(cr, dict) and isinstance(cr.get("id"), str):
            connection_by_id[cr["id"]] = cr

    removable_features = {"hole", "fastener_head_seat", "counterbore", "countersink", "bolt_circle_pattern"}

    for placement in placements:
        if not isinstance(placement, dict):
            continue

        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else ""
        base_connection_id = connection_id.split("@", 1)[0] if "@" in connection_id else connection_id
        connection = connection_by_id.get(base_connection_id, {})

        between_ids = _between_to_ids(placement.get("between"))
        non_fastener_targets = [
            cid for cid in between_ids
            if not _is_fastener_type(comp_type_by_id.get(cid))
            and not _is_subassembly_component({"type": comp_type_by_id.get(cid)})
        ]

        target_id: str | None = None
        if "@" in connection_id:
            suffix = connection_id.split("@", 1)[1]
            if suffix in non_fastener_targets:
                target_id = suffix
        if target_id is None and len(non_fastener_targets) == 1:
            target_id = non_fastener_targets[0]

        if not isinstance(target_id, str) or not target_id:
            continue

        target_type = comp_type_by_id.get(target_id, "")
        if target_type not in {"axle", "shaft"}:
            continue

        placement_purpose = placement.get("purpose") if isinstance(placement.get("purpose"), str) else ""
        purpose = placement_purpose or (connection.get("purpose") if isinstance(connection.get("purpose"), str) else "")

        placement_constraints = placement.get("constraints") if isinstance(placement.get("constraints"), dict) else {}
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        location_constraints = location.get("constraints") if isinstance(location.get("constraints"), dict) else {}
        connection_constraints = connection.get("constraints") if isinstance(connection.get("constraints"), dict) else {}

        axial_preload = any(
            c.get("axial_preload") is True
            for c in (placement_constraints, location_constraints, connection_constraints)
            if isinstance(c, dict)
        )

        is_axial = (
            ("axial_clamping" in connection_id.lower())
            or (purpose == "fastening_mechanism" and axial_preload)
        )
        if not is_axial:
            continue

        flags = placement.get("flags") if isinstance(placement.get("flags"), dict) else {}
        flags["suppress_hole_generation"] = True
        placement["flags"] = flags

        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), dict) else {}
        fastener_size = fastener_spec.get("size") if isinstance(fastener_spec.get("size"), str) and fastener_spec.get("size") else None
        if not fastener_size:
            conn_decision = connection.get("connection_decision") if isinstance(connection.get("connection_decision"), dict) else {}
            fastener_size = conn_decision.get("fastener_size") if isinstance(conn_decision.get("fastener_size"), str) else "M8"

        nominal, _ = _parse_fastener_size(fastener_size)
        nominal_mm = float(nominal) if isinstance(nominal, (int, float)) else 8.0
        thread_length = max(10.0, round(nominal_mm * 2.0, 2))

        fastener_spec["count"] = 1
        fastener_spec["pattern"] = {
            "type": "single",
            "count": 1,
            "phase_deg": 0.0,
            "hole_diameter_mm": round(nominal_mm + 0.5, 2),
            "notes": "axial retention; no bolt circle",
        }
        if isinstance(fastener_size, str):
            fastener_spec["size"] = fastener_size
        placement["fastener_spec"] = fastener_spec

        derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        rewritten_changes: List[Dict[str, Any]] = []
        for change in derived_changes:
            if not isinstance(change, dict):
                continue
            feature = change.get("feature")
            feature_s = feature.lower() if isinstance(feature, str) else ""
            if feature_s in removable_features:
                continue
            rewritten_changes.append(change)

        thread_designation = _thread_designation_from_fastener_size(fastener_size)
        thread_change = {
            "target_component_id": target_id,
            "feature": "thread",
            "thread_role": "external",
            "is_internal": False,
            "thread_designation": thread_designation,
            "thread_type": "ISO Metric profile",
            "thread_class": "6g",
            "thread_length_mm": thread_length,
            "radius_tol_mm": 0.05,
        }
        thread_nominal_mm = _parse_thread_designation_nominal_mm(thread_designation)
        if isinstance(thread_nominal_mm, (int, float)):
            thread_change["major_diameter"] = round(float(thread_nominal_mm), 6)
            thread_change["radius_mm"] = round(float(thread_nominal_mm) / 2.0, 6)
        rewritten_changes.append(thread_change)
        placement["derived_changes"] = rewritten_changes

        pattern_params = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if isinstance(pattern_params, dict):
            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            pattern_params.pop("pattern_radius", None)
            pattern_params.pop("spacing", None)
            location["pattern_parameters"] = pattern_params
            placement["location"] = location


def _sanitize_thread_features_against_host_geometry(
    kg: Dict[str, Any],
    placements: list[dict],
) -> list[dict]:
    comp_by_id: Dict[str, Dict[str, Any]] = {}
    for comp in kg.get("components", []) or []:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id"):
            comp_by_id[str(comp["id"])] = comp

    audit_entries: list[dict] = []
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        derived_changes = placement.get("derived_changes")
        if not isinstance(derived_changes, list) or not derived_changes:
            continue

        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else None
        sanitized: list[dict] = []
        for change in derived_changes:
            if not isinstance(change, dict):
                sanitized.append(change)
                continue
            feature = str(change.get("feature") or "").lower()
            if feature != "thread":
                sanitized.append(change)
                continue

            is_internal = change.get("is_internal")
            if isinstance(is_internal, bool) and is_internal:
                sanitized.append(change)
                continue

            target_id = change.get("target_component_id")
            if not isinstance(target_id, str) or not target_id:
                sanitized.append(change)
                continue

            thread_designation = change.get("thread_designation")
            nominal_mm = _parse_thread_designation_nominal_mm(thread_designation)
            if nominal_mm is None:
                major_diameter = change.get("major_diameter")
                if isinstance(major_diameter, (int, float)) and float(major_diameter) > 0.0:
                    nominal_mm = float(major_diameter)
            if nominal_mm is None:
                audit_entries.append(
                    {
                        "rule": "external_thread_requires_nominal_diameter",
                        "connection_id": connection_id,
                        "target_component_id": target_id,
                        "feature": "thread",
                        "reason": "suppressed external thread because no nominal diameter could be resolved from designation or major_diameter",
                    }
                )
                continue

            host_comp = comp_by_id.get(target_id, {})
            host_diameter_mm = _component_outer_diameter_mm(host_comp)
            if isinstance(host_diameter_mm, (int, float)):
                diameter_tol_mm = max(0.1, round(float(nominal_mm) * 0.03, 6))
                if abs(float(host_diameter_mm) - float(nominal_mm)) > diameter_tol_mm:
                    audit_entries.append(
                        {
                            "rule": "external_thread_host_diameter_mismatch",
                            "connection_id": connection_id,
                            "target_component_id": target_id,
                            "thread_designation": thread_designation,
                            "thread_major_diameter_mm": round(float(nominal_mm), 6),
                            "host_outer_diameter_mm": round(float(host_diameter_mm), 6),
                            "reason": "suppressed external thread because host OD does not match thread major diameter; stepped journal is required before threading",
                        }
                    )
                    continue

            change_copy = dict(change)
            change_copy["major_diameter"] = round(float(nominal_mm), 6)
            change_copy["radius_mm"] = round(float(nominal_mm) / 2.0, 6)
            sanitized.append(change_copy)

        placement["derived_changes"] = sanitized

    return audit_entries
