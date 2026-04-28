"""
Agent3a 闂?Deterministic Shape Realization Planner (Semantic 闂?Parametric)
"""

# INVARIANT: Agent3a outputs only numeric, engineering-meaningful parameters.
# It must not introduce or depend on CAD-execution concepts (e.g., extrude_distance,
# *_param bindings, or sketch primitive assumptions). CAD binding lives in Agent3b.
# Agent3a may derive geometry-complete parameters, but must not introduce CAD-execution bindings.

# This agent resolves semantic parameters into numeric dimensions and outputs
# only executable, geometry-ready strategies.

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


def _llm_infer_feature_instances(
    *,
    placement: Dict[str, Any],
    kg: Dict[str, Any],
    layout_positions: Dict[str, Dict[str, float]]
) -> Optional[List[Dict[str, Any]]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = {
            "task": "infer_feature_instances",
            "output_contract": "Return ONLY a JSON array: [{index:int, position:{x:float,y:float,z:float}}]",
            "rules": [
                "All units are millimeters (mm)",
                "Do not invent CAD API function names or parameters",
                "If count is missing, output a single instance at the target component origin",
                "Use placement.location/reference_surface hints if present",
                "Use layout_positions as the source of component origins",
            ],
            "placement": placement,
            "layout_positions": layout_positions,
            "components": kg.get("components", []),
        }
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            temperature=0.0,
            timeout=120.0,
        )
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1].strip()
        instances = json.loads(content)
        if not isinstance(instances, list):
            return None
        normalized = []
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            pos = inst.get("position")
            if not isinstance(pos, dict):
                continue
            try:
                normalized.append({
                    "index": int(inst.get("index", 0)),
                    "position": {
                        "x": float(pos.get("x", 0.0)),
                        "y": float(pos.get("y", 0.0)),
                        "z": float(pos.get("z", 0.0)),
                    },
                })
            except Exception:
                continue
        return normalized or None
    except Exception:
        return None


def _extract_feature_plan(
    semantics: Dict[str, Any],
    kg: Dict[str, Any],
    layout_positions: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    import math
    placements = semantics.get("connection_placements")
    if not isinstance(placements, list):
        placements = []
    normalized = []
    component_dims: Dict[str, Dict[str, Any]] = {}
    component_type_by_id: Dict[str, str] = {}
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        dims = comp.get("dimensions")
        if isinstance(cid, str) and cid and isinstance(dims, Mapping):
            component_dims[cid] = dict(dims)
        ctype = comp.get("type")
        if isinstance(cid, str) and cid and isinstance(ctype, str):
            component_type_by_id[cid] = ctype.strip().lower()

    rotational_component_ids = set(_extract_rotational_pattern_component_ids(kg))
    component_yaw_rad: Dict[str, float] = {}
    for component_id, pos in (layout_positions or {}).items():
        if not isinstance(component_id, str) or not isinstance(pos, Mapping):
            continue
        x_val = float(pos.get("x", 0.0) or 0.0)
        y_val = float(pos.get("y", 0.0) or 0.0)
        if abs(x_val) < 1e-9 and abs(y_val) < 1e-9:
            component_yaw_rad[component_id] = 0.0
        else:
            component_yaw_rad[component_id] = float(math.atan2(y_val, x_val))

    def _is_fastener_like(component_id: str) -> bool:
        ctype = component_type_by_id.get(component_id, "")
        return ctype in {"fastener", "bolt", "screw", "nut", "washer", "pin"}

    def _between_component_ids(placement: Mapping[str, Any]) -> List[str]:
        between = placement.get("between")
        if isinstance(between, list):
            return [cid for cid in between if isinstance(cid, str) and cid]
        if isinstance(between, Mapping):
            return [cid for cid in between.keys() if isinstance(cid, str) and cid]
        return []

    def _resolve_connection_instance_yaw(
        placement: Mapping[str, Any],
        *,
        host_component_id: str | None,
    ) -> tuple[float, str | None]:
        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else ""
        suffix_candidate = None
        if "@" in connection_id:
            suffix_candidate = connection_id.split("@", 1)[0]

        candidates: List[str] = []
        if isinstance(suffix_candidate, str) and suffix_candidate:
            for cid in rotational_component_ids:
                if cid != host_component_id and cid in suffix_candidate:
                    candidates.append(cid)

        for cid in _between_component_ids(placement):
            if cid == host_component_id or _is_fastener_like(cid):
                continue
            if cid in rotational_component_ids:
                candidates.append(cid)

        seen: set[str] = set()
        deduped = []
        for cid in candidates:
            if cid in seen:
                continue
            seen.add(cid)
            deduped.append(cid)

        for cid in deduped:
            yaw = component_yaw_rad.get(cid)
            if isinstance(yaw, (int, float)):
                return float(yaw), cid

        return 0.0, None

    def _infer_hole_diameter_from_placement(placement: Mapping[str, Any], primary_change: Mapping[str, Any]) -> float:
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), Mapping) else {}
        feature_d = safety.get("feature_diameter")
        if isinstance(feature_d, (int, float)) and float(feature_d) > 0:
            return float(feature_d)

        for key in ("diameter", "hole_diameter", "bore_diameter"):
            value = primary_change.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)

        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), Mapping) else {}
        size = fastener_spec.get("size") if isinstance(fastener_spec.get("size"), str) else ""
        m = re.search(r"m\s*(\d+(?:\.\d+)?)", size.lower()) if isinstance(size, str) else None
        if m:
            try:
                return float(m.group(1)) + 0.5
            except Exception:
                pass

        return 5.0

    def _component_length_mm(component_id: str) -> float:
        dims = component_dims.get(component_id, {})
        for key in ("length", "span", "outer_diameter", "diameter", "width"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
        return 0.0

    def _component_thickness_mm(component_id: str) -> float:
        dims = component_dims.get(component_id, {})
        for key in ("thickness", "height", "width"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
        return 0.0

    def _component_radius_mm(component_id: str) -> float:
        dims = component_dims.get(component_id, {})
        for key in ("outer_radius", "radius"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
        for key in ("outer_diameter", "diameter"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value) * 0.5
        return 0.0

    def _seed_slot_mount_overlap_instance(placement: Mapping[str, Any], target_component_id: str) -> Dict[str, Any] | None:
        geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        if str(geometric_semantics.get("support_topology") or "").strip().lower() != "hub_radial_slot_mount":
            return None

        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        reference_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
        moving_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
        moving_anchor = anchor_semantics.get("moving_anchor") if isinstance(anchor_semantics.get("moving_anchor"), Mapping) else {}
        insert_depth = moving_anchor.get("inset_mm")
        if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
            return None

        if target_component_id == reference_id:
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            radius = pattern.get("pattern_radius_mm") if isinstance(pattern.get("pattern_radius_mm"), (int, float)) else pattern.get("pattern_radius")
            if not isinstance(radius, (int, float)) or float(radius) <= 0.0:
                radius = max(0.0, _component_radius_mm(target_component_id) - (0.5 * float(insert_depth)))
            reference_anchor = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), Mapping) else {}
            phase_rad = reference_anchor.get("phase_rad")
            if not isinstance(phase_rad, (int, float)):
                phase_deg = reference_anchor.get("phase_deg")
                if not isinstance(phase_deg, (int, float)):
                    phase_deg = pattern.get("start_angle") if isinstance(pattern.get("start_angle"), (int, float)) else pattern.get("phase_deg")
                phase_rad = math.radians(float(phase_deg)) if isinstance(phase_deg, (int, float)) else 0.0
            return {
                "index": 0,
                "position": {
                    "x": round(float(radius) * math.cos(float(phase_rad)), 4),
                    "y": round(float(radius) * math.sin(float(phase_rad)), 4),
                    "z": 0.0,
                },
            }

        if target_component_id == moving_id:
            axis = str(moving_anchor.get("axis") or "x").strip().lower()
            half_length = 0.5 * _component_length_mm(target_component_id)
            if half_length <= 0.0:
                return None
            center_offset = min(0.5 * float(insert_depth), half_length)
            coord = -half_length + center_offset
            return {
                "index": 0,
                "position": {
                    "x": round(coord if axis != "y" else 0.0, 4),
                    "y": round(coord if axis == "y" else 0.0, 4),
                    "z": 0.0,
                },
            }

        return None

    def _seed_single_feature_instance_from_anchor(placement: Mapping[str, Any], primary_change: Mapping[str, Any]) -> Dict[str, Any] | None:
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else None
        if not isinstance(anchor_semantics, Mapping):
            return None

        target_component_id = primary_change.get("target_component_id") if isinstance(primary_change.get("target_component_id"), str) else None
        if not isinstance(target_component_id, str) or not target_component_id:
            return None

        slot_mount_seeded = _seed_slot_mount_overlap_instance(placement, target_component_id)
        if slot_mount_seeded is not None:
            return slot_mount_seeded

        reference_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
        moving_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
        if target_component_id == moving_id:
            anchor_def = anchor_semantics.get("moving_anchor") if isinstance(anchor_semantics.get("moving_anchor"), Mapping) else None
        elif target_component_id == reference_id:
            anchor_def = anchor_semantics.get("reference_anchor") if isinstance(anchor_semantics.get("reference_anchor"), Mapping) else None
        else:
            return None
        if not isinstance(anchor_def, Mapping):
            return None

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
        kind = str(anchor_def.get("kind") or "component_center").strip().lower()
        axis = str(anchor_def.get("axis") or "x").strip().lower()
        offset = 0.0
        for value in (anchor_def.get("inset_mm"), pattern.get("offset_from_edge"), pattern.get("edge_margin_mm")):
            if isinstance(value, (int, float)) and float(value) > 0:
                offset = float(value)
                break

        if kind in {"proximal_mount_face_min", "proximal_mount_face_max"}:
            half_length = 0.5 * _component_length_mm(target_component_id)
            thickness = _component_thickness_mm(target_component_id)
            if half_length <= 0:
                return None
            coord = -half_length + offset
            x_val = coord if axis != "y" else 0.0
            y_val = coord if axis == "y" else 0.0
            z_val = 0.0 if kind.endswith("_min") else thickness
            return {"index": 0, "position": {"x": round(x_val, 4), "y": round(y_val, 4), "z": round(z_val, 4)}}

        if kind in {"distal_end", "proximal_end"}:
            half_length = 0.5 * _component_length_mm(target_component_id)
            if half_length <= 0:
                return None
            sign = 1.0 if kind == "distal_end" else -1.0
            coord = sign * max(0.0, half_length - offset)
            x_val = coord if axis != "y" else 0.0
            y_val = coord if axis == "y" else 0.0
            return {"index": 0, "position": {"x": round(x_val, 4), "y": round(y_val, 4), "z": 0.0}}

        if kind in {"axial_face_perimeter_max", "axial_face_perimeter_min", "radial_mount_perimeter"}:
            radius = 0.0
            for value in (anchor_def.get("radius_mm"), pattern.get("pattern_radius_mm"), pattern.get("pattern_radius")):
                if isinstance(value, (int, float)) and float(value) > 0:
                    radius = float(value)
                    break
            if radius <= 0:
                radius = _component_radius_mm(target_component_id)
            if radius <= 0:
                return None
            phase_rad = None
            for value in (anchor_def.get("phase_rad"), pattern.get("start_angle_rad")):
                if isinstance(value, (int, float)):
                    phase_rad = float(value)
                    break
            if phase_rad is None:
                for value in (anchor_def.get("phase_deg"), pattern.get("start_angle"), pattern.get("phase_deg")):
                    if isinstance(value, (int, float)):
                        phase_rad = math.radians(float(value))
                        break
            if phase_rad is None:
                phase_rad = 0.0
            z_val = 0.0
            if kind in {"axial_face_perimeter_max", "axial_face_perimeter_min"}:
                thickness = _component_thickness_mm(target_component_id)
                z_val = thickness if kind.endswith("_max") else 0.0
            return {
                "index": 0,
                "position": {
                    "x": round(radius * math.cos(phase_rad), 4),
                    "y": round(radius * math.sin(phase_rad), 4),
                    "z": round(z_val, 4),
                },
            }

        return None

    for p in placements:
        if not isinstance(p, dict):
            continue
        pattern = p.get("location", {}).get("pattern_parameters", {})
        derived_raw = p.get("derived_changes")
        derived_list = derived_raw if isinstance(derived_raw, list) else []
        primary = derived_list[0] if derived_list else {}
        feature_group_id = f"{p.get('connection_id') or 'unknown_connection'}:{str(primary.get('feature') or 'hole').lower()}"
        # 闂傚倷绀侀幉锟犳偡椤栨稓顩叉繝濠傜吇閸ヮ剙鐓涢柛娑卞枛娴犫晠姊虹化鏇炲⒉妞ゃ劌鐗撻獮妤呭即閵忥紕鍘藉┑掳鍊曢崯顖炲吹閳ь剛绱撴担钘夌厫闁烩晩鍨跺顐㈩吋婢跺﹪鍞跺┑鐘绘涧濡粓顢欐径鎰拺闁革富鍙庨弳顖炴煛閸涱喚娲撮柟顖氱墕椤撳吋寰勭€ｎ偅鐝?
        if pattern.get("type") == "circular":
            count_val = pattern.get("count") or primary.get("pattern", {}).get("count")
            try:
                count = int(count_val)
            except Exception:
                count = 0

            location = p.get("location") if isinstance(p.get("location"), Mapping) else {}
            iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            host_component_id = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
            host_dims = component_dims.get(host_component_id, {}) if isinstance(host_component_id, str) else {}

            preferred_radius = pattern.get("pattern_radius_mm")
            if not isinstance(preferred_radius, (int, float)):
                preferred_radius = pattern.get("pattern_radius")

            hole_diameter = _infer_hole_diameter_from_placement(p, primary)
            safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), Mapping) else {}
            min_wall = safety.get("min_wall") if isinstance(safety.get("min_wall"), (int, float)) else max(1.0, round(hole_diameter * 0.125, 2))

            solved = solve_circular_pattern(
                host_dims=host_dims,
                hole_diameter=hole_diameter,
                min_wall=float(min_wall),
                preferred_radius_mm=float(preferred_radius) if isinstance(preferred_radius, (int, float)) else None,
            )

            p = dict(p)
            realization_audit = p.get("realization_audit") if isinstance(p.get("realization_audit"), dict) else {}
            existing_actions = realization_audit.get("fallback_actions") if isinstance(realization_audit.get("fallback_actions"), list) else []
            existing_actions.extend([a for a in solved.get("fallback_actions", []) if isinstance(a, str)])
            realization_audit["fallback_actions"] = existing_actions
            realization_audit["circular_solver"] = {
                "status": solved.get("status"),
                "r_min": solved.get("r_min"),
                "r_max": solved.get("r_max"),
                "radius_mm": solved.get("radius_mm"),
            }
            p["realization_audit"] = realization_audit

            solved_radius = solved.get("radius_mm") if isinstance(solved.get("radius_mm"), (int, float)) else None
            if solved.get("status") != "ok" or solved_radius is None:
                p["requires_clarification"] = True
                p["seed_point_mm"] = {"x": 0.0, "y": 0.0, "z": 0.0}
                p["feature_group_id"] = feature_group_id
                p["feature_strategy"] = {
                    "feature_type": "hole",
                    "hole_kind": "simple",
                }
                normalized.append(p)
                continue

            start_angle_rad = pattern.get("start_angle_rad")
            if isinstance(start_angle_rad, (int, float)):
                base_start_angle = float(start_angle_rad)
            else:
                base_start_angle = math.radians(float(pattern.get("start_angle", 0) or 0))
            phase_offset_rad, phase_component_id = _resolve_connection_instance_yaw(
                p,
                host_component_id=host_component_id,
            )
            start_angle = float(base_start_angle + phase_offset_rad)
            if count > 0:
                target_component_id = primary.get("target_component_id") if isinstance(primary.get("target_component_id"), str) else None
                slot_mount_seeded = (
                    _seed_slot_mount_overlap_instance(p, target_component_id)
                    if isinstance(target_component_id, str)
                    else None
                )
                if slot_mount_seeded is not None and int(count) == 1:
                    seed_x = float(slot_mount_seeded["position"].get("x", 0.0))
                    seed_y = float(slot_mount_seeded["position"].get("y", 0.0))
                    seed_z = float(slot_mount_seeded["position"].get("z", 0.0))
                    solved_radius = math.hypot(seed_x, seed_y)
                    instances = [slot_mount_seeded]
                else:
                    seed_x = float(solved_radius) * math.cos(start_angle)
                    seed_y = float(solved_radius) * math.sin(start_angle)
                    seed_z = 0.0
                    instances = []
                    step_angle = (2.0 * math.pi) / float(count)
                    for idx in range(int(count)):
                        angle_i = float(start_angle) + step_angle * float(idx)
                        instances.append(
                            {
                                "index": int(idx),
                                "position": {
                                    "x": round(float(solved_radius) * math.cos(angle_i), 4),
                                    "y": round(float(solved_radius) * math.sin(angle_i), 4),
                                    "z": 0.0,
                                },
                            }
                        )
                p["pattern"] = {
                    "type": "circular",
                    "count": int(count),
                    "radius_mm": float(round(float(solved_radius), 6)),
                    "start_angle_rad": float(start_angle),
                    "total_angle_rad": float(2.0 * math.pi),
                }
                p["pattern_axis"] = "Z"
                p["seed_point_mm"] = {"x": round(seed_x, 4), "y": round(seed_y, 4), "z": round(seed_z, 4)}
                p["instances"] = instances
                if abs(phase_offset_rad) > 1e-9:
                    realization_audit = p.get("realization_audit") if isinstance(p.get("realization_audit"), dict) else {}
                    realization_audit["symmetry_phase_offset_rad"] = float(round(phase_offset_rad, 8))
                    realization_audit["symmetry_phase_component_id"] = phase_component_id
                    p["realization_audit"] = realization_audit
                p["feature_group_id"] = feature_group_id
                p["feature_strategy"] = {
                    "feature_type": "hole",
                    "hole_kind": "simple",
                }
                hole_diam = primary.get("diameter") or primary.get("bore_diameter") or primary.get("hole_diameter")
                hole_depth = primary.get("depth")
                dims = {}
                if isinstance(hole_diam, (int, float)):
                    dims["diameter_mm"] = float(hole_diam)
                if isinstance(hole_depth, (int, float)):
                    dims["depth_mm"] = float(hole_depth)
                if dims:
                    p["feature_dimensions_mm"] = dims
        elif pattern.get("type") == "rectangular":
            count_x_raw = pattern.get("count_x")
            count_y_raw = pattern.get("count_y")
            spacing_x_raw = pattern.get("spacing_x_mm") if isinstance(pattern.get("spacing_x_mm"), (int, float)) else pattern.get("spacing_x")
            spacing_y_raw = pattern.get("spacing_y_mm") if isinstance(pattern.get("spacing_y_mm"), (int, float)) else pattern.get("spacing_y")
            try:
                count_x = int(count_x_raw) if count_x_raw is not None else 0
            except Exception:
                count_x = 0
            try:
                count_y = int(count_y_raw) if count_y_raw is not None else 1
            except Exception:
                count_y = 1
            if count_x > 0 and isinstance(spacing_x_raw, (int, float)):
                p = dict(p)
                p["pattern"] = {
                    "type": "rectangular",
                    "count_x": int(count_x),
                    "count_y": int(max(1, count_y)),
                    "spacing_x_mm": float(spacing_x_raw),
                    "spacing_y_mm": float(spacing_y_raw) if isinstance(spacing_y_raw, (int, float)) else 0.0,
                }
                p["pattern_axis"] = "Z"
                p["seed_point_mm"] = {"x": 0.0, "y": 0.0, "z": 0.0}
                p["feature_group_id"] = feature_group_id
                p["feature_strategy"] = {
                    "feature_type": "hole",
                    "hole_kind": "simple",
                }
        if "instances" not in p and pattern.get("type") == "single" and derived_list:
            seeded_instance = _seed_single_feature_instance_from_anchor(p, primary)
            if seeded_instance is not None:
                p = dict(p)
                p["instances"] = [seeded_instance]
                p["seed_point_mm"] = dict(seeded_instance["position"])
                p["feature_group_id"] = feature_group_id
                p["feature_strategy"] = {
                    "feature_type": "hole",
                    "hole_kind": "simple",
                }

        if "instances" not in p and derived_list:
            feature = primary.get("feature")
            if isinstance(feature, str) and feature.lower() in {"hole", "bolt_circle_pattern"}:
                inferred = _llm_infer_feature_instances(
                    placement=p,
                    kg=kg,
                    layout_positions=layout_positions,
                )
                if inferred:
                    p = dict(p)
                    p["instances"] = inferred
                    p["feature_strategy"] = {
                        "feature_type": "hole",
                        "hole_kind": "simple",
                    }
        normalized.append(p)
    return {"connection_placements": normalized}


def _build_part_feature_map(
    *,
    semantics: Dict[str, Any],
    kg: Dict[str, Any],
    layout_positions: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    metric_thread_designation_map: Dict[str, str] = {
        "m3": "M3x0.5",
        "m4": "M4x0.7",
        "m5": "M5x0.8",
        "m6": "M6x1.0",
        "m8": "M8x1.25",
        "m10": "M10x1.5",
    }

    def _safe_float(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _normalize_metric_size(size_value: Any) -> str | None:
        if not isinstance(size_value, str):
            return None
        raw = size_value.strip().lower()
        if not raw:
            return None
        match = re.search(r"m\s*(\d+(?:\.\d+)?)", raw)
        if not match:
            return None
        numeric = match.group(1)
        if numeric.endswith(".0"):
            numeric = numeric[:-2]
        return f"m{numeric}"

    def _thread_major_diameter_from_designation(thread_designation: Any) -> float | None:
        if not isinstance(thread_designation, str):
            return None
        match = re.search(r"m\s*(\d+(?:\.\d+)?)", thread_designation.strip().lower())
        if not match:
            return None
        return float(match.group(1))

    def _extract_intent_diameter(intent: Mapping[str, Any]) -> float | None:
        hole_spec_raw = intent.get("hole_spec")
        hole_spec = hole_spec_raw if isinstance(hole_spec_raw, Mapping) else {}
        for candidate in (
            hole_spec.get("diameter_mm"),
            hole_spec.get("diameter"),
            intent.get("diameter_mm"),
            intent.get("diameter"),
            intent.get("hole_diameter"),
            intent.get("bore_diameter"),
        ):
            numeric = _safe_float(candidate)
            if numeric is not None:
                return numeric
        return None

    def _resolve_hole_intent_id(
        *,
        feature_type: str,
        geometry_parameters: Mapping[str, Any],
        hole_intents: List[Any],
    ) -> str | None:
        if not _is_hole_like_feature_type(feature_type):
            return None

        raw_intent_id = geometry_parameters.get("hole_intent_id")
        if isinstance(raw_intent_id, str) and raw_intent_id.strip():
            return raw_intent_id.strip()

        valid_intents = [intent for intent in hole_intents if isinstance(intent, Mapping)]
        if len(valid_intents) == 1:
            only_id = valid_intents[0].get("id")
            if isinstance(only_id, str) and only_id.strip():
                return only_id.strip()

        diameter_value = None
        for candidate in (
            geometry_parameters.get("diameter"),
            geometry_parameters.get("hole_diameter"),
            geometry_parameters.get("bore_diameter"),
        ):
            numeric = _safe_float(candidate)
            if numeric is not None:
                diameter_value = numeric
                break

        if diameter_value is None:
            return None

        best_intent_id: str | None = None
        best_delta: float | None = None
        for intent in valid_intents:
            intent_id = intent.get("id")
            if not isinstance(intent_id, str) or not intent_id.strip():
                continue
            intent_diameter = _extract_intent_diameter(intent)
            if intent_diameter is None:
                continue
            delta = abs(intent_diameter - diameter_value)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_intent_id = intent_id.strip()

        return best_intent_id

    def _classify_hole_type(feature_type_lower: str, geometry_parameters: Mapping[str, Any]) -> str:
        raw_hole_type = geometry_parameters.get("hole_type")
        if isinstance(raw_hole_type, str) and raw_hole_type.strip():
            return raw_hole_type.strip().lower()
        return feature_type_lower

    normalized_plan = _extract_feature_plan(semantics, kg, layout_positions)
    placements = normalized_plan.get("connection_placements")
    if not isinstance(placements, list):
        return {}

    feature_map: Dict[str, Any] = {}
    anchor_errors: List[Dict[str, Any]] = []
    thread_warnings: List[Dict[str, Any]] = []
    hole_arbitration_kept: List[Dict[str, Any]] = []
    hole_arbitration_dropped: List[Dict[str, Any]] = []
    pending_features: List[Dict[str, Any]] = []

    dims_by_component: Dict[str, Dict[str, Any]] = {}
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        dims = comp.get("dimensions")
        if isinstance(cid, str) and cid and isinstance(dims, dict):
            dims_by_component[cid] = dims

    # Build (component_id, interface_id) 闂?geometry_type index from semantics
    # so we can redirect hole anchors away from cylindrical faces.
    _iface_geom_index: Dict[tuple[str, str], str] = {}
    _planar_ifaces_by_comp: Dict[str, List[str]] = {}

    def _register_iface_geom(cid: str, iname: str, gt: str) -> None:
        gt_lower = gt.strip().lower()
        _iface_geom_index[(cid, iname)] = gt_lower
        if gt_lower == "planar":
            existing = _planar_ifaces_by_comp.setdefault(cid, [])
            if iname not in existing:
                existing.append(iname)

    # Source 1: semantics.components[].interfaces[]
    for _sem_comp in semantics.get("components", []) or []:
        if not isinstance(_sem_comp, Mapping):
            continue
        _sem_cid = _sem_comp.get("component_id")
        if not isinstance(_sem_cid, str) or not _sem_cid:
            continue
        for _sem_iface in _sem_comp.get("interfaces", []) or []:
            if not isinstance(_sem_iface, Mapping):
                continue
            _sem_iname = _sem_iface.get("interface_id") or _sem_iface.get("interface_name")
            if not isinstance(_sem_iname, str) or not _sem_iname:
                continue
            _sem_gt = None
            _sem_recipe = _sem_iface.get("recipe")
            if isinstance(_sem_recipe, Mapping) and isinstance(_sem_recipe.get("geometry_type"), str):
                _sem_gt = _sem_recipe["geometry_type"]
            elif isinstance(_sem_iface.get("geometry_type"), str):
                _sem_gt = _sem_iface["geometry_type"]
            if isinstance(_sem_gt, str) and _sem_gt:
                _register_iface_geom(_sem_cid, _sem_iname, _sem_gt)

    # Source 2: semantics.interface_manifest.components[].interfaces[]
    _inherited_manifest = semantics.get("interface_manifest")
    if isinstance(_inherited_manifest, Mapping):
        for _mf_comp in _inherited_manifest.get("components", []) or []:
            if not isinstance(_mf_comp, Mapping):
                continue
            _mf_cid = _mf_comp.get("component_id")
            if not isinstance(_mf_cid, str) or not _mf_cid:
                continue
            for _mf_iface in _mf_comp.get("interfaces", []) or []:
                if not isinstance(_mf_iface, Mapping):
                    continue
                _mf_iname = _mf_iface.get("interface_name") or _mf_iface.get("interface_id")
                if not isinstance(_mf_iname, str) or not _mf_iname:
                    continue
                _mf_gt = None
                _mf_recipe = _mf_iface.get("recipe")
                if isinstance(_mf_recipe, Mapping) and isinstance(_mf_recipe.get("geometry_type"), str):
                    _mf_gt = _mf_recipe["geometry_type"]
                elif isinstance(_mf_iface.get("geometry_type"), str):
                    _mf_gt = _mf_iface["geometry_type"]
                if isinstance(_mf_gt, str) and _mf_gt:
                    _register_iface_geom(_mf_cid, _mf_iname, _mf_gt)

    def _redirect_hole_anchor_if_cylindrical(
        component_id: str, interface_name: str, placement_geom_type: str = "",
    ) -> str:
        """If the anchor interface is cylindrical, redirect to a planar face.

        Fusion 360 HOLE_SIMPLE requires a planar face for placement.
        Preference order: axial_end_face_min 闂?axial_end_face_max 闂?axial_end_face
        闂?mounting_req_drill_anchor 闂?first available planar face.
        """
        # Use placement-level geometry type first, then fallback to semantics index.
        geom = placement_geom_type.strip().lower() if placement_geom_type else ""
        if not geom:
            geom = _iface_geom_index.get((component_id, interface_name), "")
        if geom not in ("cylindrical", "axis", "complex"):
            return interface_name  # already planar or unknown 闂?keep as-is

        planar_candidates = _planar_ifaces_by_comp.get(component_id, [])
        if not planar_candidates:
            return interface_name  # no planar alternative; keep and let validator catch it

        # Preference order for drill-anchor redirection
        for preferred in (
            "axial_end_face_min",
            "axial_end_face_max",
            "axial_end_face",
            "mounting_req_drill_anchor",
            "fixation_req",
            "mounting_req",
        ):
            if preferred in planar_candidates:
                return preferred

        return planar_candidates[0]

    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        location = placement.get("location")
        location_map = location if isinstance(location, Mapping) else {}
        interface_ref_raw = location_map.get("interface_ref")
        interface_ref = interface_ref_raw if isinstance(interface_ref_raw, Mapping) else {}
        interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
        interface_component = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else None
        reference_frame = location_map.get("reference_frame") if isinstance(location_map.get("reference_frame"), str) else "component_local"
        connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else "unknown_connection"
        pattern_payload = placement.get("pattern") if isinstance(placement.get("pattern"), Mapping) else None
        pattern_axis = placement.get("pattern_axis") if isinstance(placement.get("pattern_axis"), str) else None
        seed_point_raw = placement.get("seed_point_mm") if isinstance(placement.get("seed_point_mm"), Mapping) else None
        feature_group_id = placement.get("feature_group_id") if isinstance(placement.get("feature_group_id"), str) else None

        instances_raw = placement.get("instances")
        instances: List[Dict[str, Any]] = []
        if isinstance(instances_raw, list):
            for inst in instances_raw:
                if not isinstance(inst, Mapping):
                    continue
                pos = inst.get("position")
                if not isinstance(pos, Mapping):
                    continue
                instances.append(
                    {
                        "index": int(inst.get("index", len(instances))),
                        "position": {
                            "x": float(pos.get("x", 0.0)),
                            "y": float(pos.get("y", 0.0)),
                            "z": float(pos.get("z", 0.0)),
                        },
                    }
                )

        derived_changes = placement.get("derived_changes")
        if not isinstance(derived_changes, list):
            continue

        hole_intents_raw = placement.get("hole_intents")
        hole_intents = hole_intents_raw if isinstance(hole_intents_raw, list) else []
        fastener_spec_raw = placement.get("fastener_spec")
        fastener_spec = fastener_spec_raw if isinstance(fastener_spec_raw, Mapping) else {}
        iface_geom_type = interface_ref.get("geometry_type") or interface_ref.get("geom_type")
        iface_geom_type_s = str(iface_geom_type).strip().lower() if isinstance(iface_geom_type, str) else ""

        for idx, change in enumerate(derived_changes):
            if not isinstance(change, Mapping):
                continue
            target_component_id = change.get("target_component_id")
            feature_type = change.get("feature")
            if not isinstance(target_component_id, str) or not target_component_id:
                continue
            if not isinstance(feature_type, str) or not feature_type:
                continue

            feature_type_lower = feature_type.lower()
            effective_target_component_id = target_component_id

            geometry_parameters: Dict[str, Any] = {}
            for key, value in change.items():
                if key in {"target_component_id", "feature", "source"}:
                    continue
                geometry_parameters[key] = value

            if feature_type_lower == "thread":
                target_dims = dims_by_component.get(effective_target_component_id, {})
                raw_is_internal = geometry_parameters.get("is_internal")
                is_internal = bool(raw_is_internal) if isinstance(raw_is_internal, bool) else False
                thread_designation = geometry_parameters.get("thread_designation")
                designation_major_diameter = _thread_major_diameter_from_designation(thread_designation)

                target_outer_diameter = _safe_float(target_dims.get("diameter"))
                if target_outer_diameter is None:
                    target_outer_diameter = _safe_float(target_dims.get("outer_diameter"))
                if target_outer_diameter is None:
                    outer_radius = _safe_float(target_dims.get("outer_radius"))
                    if outer_radius is None:
                        outer_radius = _safe_float(target_dims.get("radius"))
                    if outer_radius is not None:
                        target_outer_diameter = float(outer_radius) * 2.0

                major_diameter = designation_major_diameter
                if major_diameter is None:
                    major_diameter = _safe_float(geometry_parameters.get("major_diameter"))
                if major_diameter is None:
                    major_diameter = _safe_float(geometry_parameters.get("diameter"))
                if major_diameter is None and designation_major_diameter is None:
                    major_diameter = target_outer_diameter

                if (
                    not is_internal
                    and designation_major_diameter is not None
                    and isinstance(target_outer_diameter, (int, float))
                ):
                    diameter_tol_mm = max(0.1, round(float(designation_major_diameter) * 0.03, 6))
                    if abs(float(target_outer_diameter) - float(designation_major_diameter)) > diameter_tol_mm:
                        thread_warnings.append(
                            {
                                "connection_id": connection_id,
                                "target_component_id": effective_target_component_id,
                                "feature_type": feature_type,
                                "reason": "external_thread_host_diameter_mismatch",
                                "thread_designation": thread_designation,
                                "thread_major_diameter_mm": round(float(designation_major_diameter), 6),
                                "host_outer_diameter_mm": round(float(target_outer_diameter), 6),
                            }
                        )

                if major_diameter is not None:
                    major_diameter = float(major_diameter)
                    radius_mm = round(major_diameter / 2.0, 6)
                    geometry_parameters["major_diameter"] = major_diameter
                    geometry_parameters["radius_mm"] = radius_mm
                else:
                    geometry_parameters["requires_clarification"] = True
                    geometry_parameters.setdefault("clarification_reason", "missing_thread_major_diameter")
                    radius_mm = None

                geometry_parameters.setdefault("is_modeled", False)
                geometry_parameters.setdefault("is_full_length", True)
                geometry_parameters["radius_tol_mm"] = 0.05
                thread_feature_record: Dict[str, Any] = {
                    "feature_id": f"{connection_id}:thread:{idx}",
                    "feature_type": "thread",
                    "interface_ref": {
                        "component_id": effective_target_component_id,
                        "name": "cylindrical_outer",
                        "geometry_type": "cylindrical",
                    },
                    "reference_frame": "component_local",
                    "geometry_parameters": geometry_parameters,
                    "anchor": {
                        "type": "cylindrical_face_by_radius",
                        "radius_mm": radius_mm,
                        "tol_mm": 0.05,
                    },
                }

                if isinstance(pattern_payload, Mapping):
                    thread_feature_record["pattern"] = dict(pattern_payload)
                if isinstance(pattern_axis, str) and pattern_axis:
                    thread_feature_record["pattern_axis"] = pattern_axis
                if isinstance(seed_point_raw, Mapping):
                    thread_feature_record["seed_point_mm"] = {
                        "x": float(seed_point_raw.get("x", 0.0)),
                        "y": float(seed_point_raw.get("y", 0.0)),
                        "z": float(seed_point_raw.get("z", 0.0)),
                    }
                if isinstance(feature_group_id, str) and feature_group_id:
                    thread_feature_record["feature_group_id"] = feature_group_id

                if instances:
                    thread_feature_record["instances"] = instances

                pending_features.append(
                    {
                        "target_component_id": effective_target_component_id,
                        "feature_record": thread_feature_record,
                        "feature_type_lower": feature_type_lower,
                        "hole_intent_id": None,
                        "hole_type": None,
                        "is_hole_like": False,
                        "is_aux_hole": False,
                    }
                )
                continue

            hole_type = _classify_hole_type(feature_type_lower, geometry_parameters)
            if hole_type == "threaded_hole":
                fastener_size = fastener_spec.get("size")
                normalized_size = _normalize_metric_size(fastener_size)
                designation = metric_thread_designation_map.get(normalized_size) if isinstance(normalized_size, str) else None

                pilot_diameter = _safe_float(geometry_parameters.get("pilot_diameter"))
                major_diameter = _safe_float(geometry_parameters.get("diameter"))
                if pilot_diameter is not None:
                    if major_diameter is None:
                        major_diameter = _safe_float(geometry_parameters.get("major_diameter"))
                    if major_diameter is not None:
                        geometry_parameters["major_diameter"] = float(major_diameter)
                    geometry_parameters["diameter"] = float(pilot_diameter)

                if isinstance(designation, str):
                    geometry_parameters["thread_spec"] = {
                        "is_internal": True,
                        "thread_type": "ISO Metric profile",
                        "thread_designation": designation,
                        "thread_class": "6H",
                        "is_modeled": False,
                        "is_full_length": True,
                        "radius_tol_mm": 0.05,
                    }
                    geometry_parameters.pop("requires_clarification", None)
                else:
                    geometry_parameters["requires_clarification"] = True
                    geometry_parameters.pop("thread_spec", None)
                    thread_warnings.append(
                        {
                            "connection_id": connection_id,
                            "target_component_id": effective_target_component_id,
                            "feature_type": feature_type,
                            "hole_type": hole_type,
                            "reason": "missing_or_unsupported_fastener_size_for_thread_spec",
                            "fastener_size": fastener_size,
                        }
                    )

            base_feature_record: Dict[str, Any] = {
                "feature_id": f"{connection_id}:{feature_type}:{idx}",
                "feature_type": feature_type,
                "interface_ref": {
                    **(dict(interface_ref) if isinstance(interface_ref, Mapping) else {}),
                    "name": interface_name,
                    "component_id": interface_component,
                },
                "reference_frame": reference_frame,
                "geometry_parameters": geometry_parameters,
            }

            if isinstance(pattern_payload, Mapping):
                base_feature_record["pattern"] = dict(pattern_payload)
            if isinstance(pattern_axis, str) and pattern_axis:
                base_feature_record["pattern_axis"] = pattern_axis
            if isinstance(seed_point_raw, Mapping):
                base_feature_record["seed_point_mm"] = {
                    "x": float(seed_point_raw.get("x", 0.0)),
                    "y": float(seed_point_raw.get("y", 0.0)),
                    "z": float(seed_point_raw.get("z", 0.0)),
                }
            if isinstance(feature_group_id, str) and feature_group_id:
                base_feature_record["feature_group_id"] = feature_group_id

            # Contract: every hole feature must carry a face+direction+side anchor.
            if _is_hole_like_feature_type(feature_type):
                if not isinstance(interface_name, str) or not interface_name or interface_name == "unspecified":
                    anchor_errors.append(
                        {
                            "feature_id": base_feature_record.get("feature_id"),
                            "target_component_id": effective_target_component_id,
                            "reason": "missing_interface_ref.name_for_hole",
                            "interface_ref": base_feature_record.get("interface_ref"),
                        }
                    )
                else:
                    # Redirect cylindrical/axis anchors to a planar face (Fusion HOLE_SIMPLE requires planar).
                    anchor_face_name = _redirect_hole_anchor_if_cylindrical(
                        effective_target_component_id, interface_name,
                        placement_geom_type=iface_geom_type_s,
                    )
                    anchor = _build_hole_anchor(interface_name=anchor_face_name)
                    base_feature_record["anchor"] = anchor

                    # Ensure the hole center lies on the anchored end-face plane when possible.
                    # Convention: for extruded solids, MIN face at z=0, MAX face at z=thickness.
                    if instances:
                        dims = dims_by_component.get(effective_target_component_id, {})
                        thickness = dims.get("thickness")
                        if isinstance(thickness, (int, float)) and float(thickness) > 0:
                            side_hint = anchor.get("side_hint")
                            if side_hint == "MAX":
                                z_val = float(thickness)
                            elif side_hint == "MIN":
                                z_val = 0.0
                            else:
                                z_val = None

                            if z_val is not None:
                                for inst in instances:
                                    pos = inst.get("position")
                                    if isinstance(pos, dict):
                                        pos["z"] = float(z_val)
            if instances:
                base_feature_record["instances"] = instances

            resolved_hole_intent_id = _resolve_hole_intent_id(
                feature_type=feature_type,
                geometry_parameters=base_feature_record.get("geometry_parameters", {}),
                hole_intents=hole_intents,
            )

            pending_features.append(
                {
                    "target_component_id": effective_target_component_id,
                    "feature_record": base_feature_record,
                    "feature_type_lower": feature_type_lower,
                    "hole_intent_id": resolved_hole_intent_id,
                    "hole_type": _classify_hole_type(feature_type_lower, base_feature_record.get("geometry_parameters", {})),
                    "is_hole_like": _is_hole_like_feature_type(feature_type),
                    "is_aux_hole": feature_type_lower in {"counterbore", "countersink"},
                }
            )

    grouped_holes: Dict[tuple[str, str], List[int]] = {}
    for pending_index, entry in enumerate(pending_features):
        if not isinstance(entry, Mapping):
            continue
        if not bool(entry.get("is_hole_like")):
            continue
        hole_intent_id = entry.get("hole_intent_id")
        target_component_id = entry.get("target_component_id")
        if not isinstance(hole_intent_id, str) or not hole_intent_id:
            continue
        if not isinstance(target_component_id, str) or not target_component_id:
            continue
        grouped_holes.setdefault((target_component_id, hole_intent_id), []).append(pending_index)

    kept_indices = set(range(len(pending_features)))

    def _drop_feature(*, index: int, reason: str) -> None:
        if index not in kept_indices:
            return
        kept_indices.remove(index)
        entry = pending_features[index]
        feature_record: Mapping[str, Any] = {}
        if isinstance(entry, Mapping):
            candidate_record = entry.get("feature_record")
            if isinstance(candidate_record, Mapping):
                feature_record = candidate_record
        hole_arbitration_dropped.append(
            {
                "target_component_id": entry.get("target_component_id") if isinstance(entry, Mapping) else None,
                "hole_intent_id": entry.get("hole_intent_id") if isinstance(entry, Mapping) else None,
                "feature_id": feature_record.get("feature_id") if isinstance(feature_record, Mapping) else None,
                "feature_type": feature_record.get("feature_type") if isinstance(feature_record, Mapping) else None,
                "hole_type": entry.get("hole_type") if isinstance(entry, Mapping) else None,
                "reason": reason,
            }
        )

    for (target_component_id, hole_intent_id), indices in grouped_holes.items():
        if len(indices) <= 1:
            continue

        main_indices: List[int] = []
        aux_indices: List[int] = []
        threaded_indices: List[int] = []
        clearance_indices: List[int] = []

        for pending_index in indices:
            entry = pending_features[pending_index]
            if bool(entry.get("is_aux_hole")):
                aux_indices.append(pending_index)
                continue

            main_indices.append(pending_index)
            hole_type = entry.get("hole_type")
            if isinstance(hole_type, str):
                normalized_hole_type = hole_type.lower()
                if normalized_hole_type == "threaded_hole":
                    threaded_indices.append(pending_index)
                elif normalized_hole_type == "clearance_hole":
                    clearance_indices.append(pending_index)

        if threaded_indices:
            keep_main = threaded_indices[0]
            for pending_index in main_indices:
                if pending_index != keep_main:
                    _drop_feature(index=pending_index, reason="same_hole_intent_conflict_prefers_threaded_hole")
            for pending_index in aux_indices:
                _drop_feature(index=pending_index, reason="counter_feature_requires_clearance_hole_parent")
        elif clearance_indices:
            keep_main = clearance_indices[0]
            for pending_index in main_indices:
                if pending_index != keep_main:
                    _drop_feature(index=pending_index, reason="same_hole_intent_conflict_prefers_single_clearance_hole")
        elif main_indices:
            keep_main = main_indices[0]
            for pending_index in main_indices[1:]:
                _drop_feature(index=pending_index, reason="same_hole_intent_conflict_prefers_first_hole")
            for pending_index in aux_indices:
                _drop_feature(index=pending_index, reason="counter_feature_requires_clearance_hole_parent")
        else:
            for pending_index in aux_indices:
                _drop_feature(index=pending_index, reason="counter_feature_without_primary_hole")

        for kept_index in [idx for idx in indices if idx in kept_indices]:
            entry = pending_features[kept_index]
            feature_record: Mapping[str, Any] = {}
            if isinstance(entry, Mapping):
                candidate_record = entry.get("feature_record")
                if isinstance(candidate_record, Mapping):
                    feature_record = candidate_record
            hole_arbitration_kept.append(
                {
                    "target_component_id": target_component_id,
                    "hole_intent_id": hole_intent_id,
                    "feature_id": feature_record.get("feature_id") if isinstance(feature_record, Mapping) else None,
                    "feature_type": feature_record.get("feature_type") if isinstance(feature_record, Mapping) else None,
                    "hole_type": entry.get("hole_type") if isinstance(entry, Mapping) else None,
                }
            )

    for pending_index, entry in enumerate(pending_features):
        if pending_index not in kept_indices:
            continue
        target_component_id = entry.get("target_component_id") if isinstance(entry, Mapping) else None
        selected_feature_record: Mapping[str, Any] = {}
        if isinstance(entry, Mapping):
            maybe_record = entry.get("feature_record")
            if isinstance(maybe_record, Mapping):
                selected_feature_record = maybe_record
        if not isinstance(target_component_id, str) or not target_component_id:
            continue
        if not selected_feature_record:
            continue
        feature_map.setdefault(target_component_id, []).append(dict(selected_feature_record))

    if anchor_errors:
        # Attach for downstream fail-fast; run() will materialize as a file under planning/errors.
        feature_map["__anchor_errors__"] = anchor_errors  # type: ignore[assignment]

    if thread_warnings:
        feature_map["__thread_warnings__"] = thread_warnings  # type: ignore[assignment]

    if hole_arbitration_kept or hole_arbitration_dropped:
        feature_map["__hole_arbitration__"] = {
            "kept": hole_arbitration_kept,
            "dropped": hole_arbitration_dropped,
        }  # type: ignore[assignment]

    return feature_map


def _build_coordinate_frame(
    *,
    component_id: str,
    layout_positions: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    _ = component_id
    _ = layout_positions
    return {
        "reference_frame": "component_local",
        "origin_mm": {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        },
        "axes": {
            "x_axis": {"x": 1.0, "y": 0.0, "z": 0.0},
            "y_axis": {"x": 0.0, "y": 1.0, "z": 0.0},
            "z_axis": {"x": 0.0, "y": 0.0, "z": 1.0},
        },
    }


def _registry_supports_construction_method(
    registry: Dict[str, Any],
    method: str,
) -> bool:
    if not isinstance(registry, dict):
        return False
    names = set(registry.keys())
    if method == "extrude":
        return any(n.startswith("EXTRUDE_") for n in names)
    if method == "revolve":
        return "REVOLVE_NEW_BODY" in names
    return False


def _extract_position_hints(kg: Dict[str, Any]) -> Dict[str, str]:
    """
    婵犵數鍋涢顓熸叏閹绢喖绀冮柣婵囧缁绘盯骞嬮悙瀛樺剮闂佸憡锚閳ь剛鍠嗘禍鐟般€掑锝呬壕閻庤娲╃紞浣割嚕鐠轰警鐎堕柡鍛焽tion_offset闂傚倷鑳堕、濠囶敋瑜忛幑銏犖旈崨顓㈠敹濡炪倕绻愰悧濠囧疾椤掑嫭鍊堕柣鎰硾娴滃湱绱掔€ｎ亷宸ラ柍钘夘樀楠炴﹢宕滄担鍓愨啓M闂傚倷娴囬～澶嬬娴犲绀夐煫鍥ㄤ緱閺佸﹪鏌熸潏楣冩闁稿骸绉归弻娑㈠即閵娿儲鐝梺鎼炲€栭弻銊╁煡婢舵劕妫樻繛鍡欏亾鏁堥柣鐔哥矒椤ｏ箓鎳楅崜浣稿灊闁割偁鍎辩粻鎺楁煙閸濆嫭顥滃ù?
    
    Returns: {component_id: "semantic position hint" or ""}
    """
    hints = {}
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        
        # Extract position_offset description if available
        offset = comp.get("position_offset")
        if isinstance(offset, dict):
            desc = offset.get("description", "")
            along_axis = offset.get("along_axis", "")
            if desc:
                hints[comp_id] = f"{desc} (along {along_axis})" if along_axis else desc
        
    return hints


def _build_position_parent_constraints(kg: Dict[str, Any]) -> str:
    """
    闂傚倷绀侀幖顐︻敄閸涱垪鍋撳鐓庡缂佽鲸鎹囬獮鏍х暋閻ョそtion_parent闂傚倷绀侀幖顐ょ矓閻㈢鍨傞柣鐔稿閺嬫棃鏌熺€电啸婵☆偒鍨堕弻銊╁籍閸ヮ灝鎾绘倶韫囨挻顥滈懣鎰版煕閵夘垳鍒板褎褰冮湁闁绘挸瀛╅崵鍥煛娴ｅ摜孝闁伙絾绻堥崺鈧い鎺戝閺嬩線鏌曢崼婵囶棤妞も晞灏欓埀顒€绠嶉崕鎶藉箯閻?prompt闂?
    
    Returns: 闂傚倷绀侀幖顐ょ矓閸洖鍌ㄧ憸蹇撐ｉ幇鐗堟櫢闁绘灏欓ˇ閬嶆⒑閸濆嫮鈻夐柛瀣嚇閹偓娼忛埡鍐紲闂佽鍎抽幊妯侯瀶椤旂晫绠剧痪鏉垮船娴滄壆鈧鍣崜鐔风暦閸洖惟闁挎棁妫勯浼存⒒娴ｄ警鏀版い鏇嗗懏宕叉俊銈呮噹闁?    """
    components = kg.get("components", []) or []
    ground_root_id = _select_ground_root_id(kg)

    roots = [c for c in components if isinstance(c, dict) and not c.get("position_parent")]
    
    tree_lines = ["ASSEMBLY HIERARCHY (position_parent tree):"]
    
    for root in roots:
        root_id = root.get("id")
        if not isinstance(root_id, str):
            continue
        
        if root_id == ground_root_id:
            tree_lines.append(f"  {root_id} (ROOT - must be at origin 0,0,0)")
        else:
            tree_lines.append(f"  {root_id} (UNPARENTED - NOT grounded; free placement allowed)")
        
        def traverse(parent_id, indent=4):
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                if comp.get("position_parent") != parent_id:
                    continue
                child_id = comp.get("id")
                if not isinstance(child_id, str):
                    continue
                comp_type = comp.get("type", "")
                tree_lines.append(f"{'  ' * (indent // 2)}{child_id} (type: {comp_type})")
                traverse(child_id, indent + 4)
        
        traverse(root_id)
    
    return "\n".join(tree_lines)


def _detect_radial_symmetry_pattern(kg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    濠电姷顣藉Σ鍛村磻閳ь剟鏌涚€ｎ偅灏扮紒缁樼洴瀵爼骞嬮鐐插婵犵鈧啿绾ч柟顔煎€搁悾鐑藉Ψ閳哄倹娅囬梺閫炲苯澧撮柟顔芥そ婵℃悂鍩℃担鐟扮ザ闂備線娼ч…鍫ュ磿瀹曞洨鐜婚柣鎰劋閻撴洘鎱ㄥ鍡楀箹闁诲繈鍎查妵鍕即閵娿儲鐏撶紓渚囧枟濡啴骞冭瀹曟椽顢栫捄顭戞М濡炪倖娲╃紞鈧紒鐘崇洴婵＄柉顦存い锔规櫊濮婃椽宕崟顓夈儲銇勯銏╂Ц闁伙絽鐏氱粙濠勬婵紴闂傚倷绀侀幉锛勫垝瀹€鍕垫晩濠靛婀糴nt闂傚倷鐒︾€笛呯矙閹次诲洭顢橀姀鐘靛姦?
    
    Returns: {parent_id: [component_ids]} 闂?None
    """
    components = kg.get("components", []) or []
    
    # Group by parent
    by_parent = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        parent = comp.get("position_parent")
        if parent not in by_parent:
            by_parent[parent] = []
        by_parent[parent].append(comp)
    
    # Check for radial symmetry: components with same type under same parent
    patterns = {}
    for parent_id, sibs in by_parent.items():
        if parent_id is None:
            continue
        types = {}
        for comp in sibs:
            ctype = comp.get("type")
            if ctype not in types:
                types[ctype] = []
            cid = comp.get("id")
            if isinstance(cid, str):
                types[ctype].append(cid)
        
        # If 3+ siblings of same type, likely radial symmetric
        for ctype, ids in types.items():
            if len(ids) >= 3:
                patterns[parent_id] = {
                    "type": ctype,
                    "count": len(ids),
                    "components": ids
                }
    
    return patterns if patterns else None


def _select_ground_root_id(kg: Dict[str, Any]) -> str:
    components = [c for c in (kg.get("components") or []) if isinstance(c, dict)]
    if not components:
        return "root"

    def _is_fixed_support_component(comp: Dict[str, Any]) -> bool:
        cid = str(comp.get("id") or "").strip()
        if not cid:
            return False
        cid_lower = cid.lower()
        role_lower = str(comp.get("role") or "").strip().lower()
        type_lower = str(comp.get("type") or "").strip().lower()
        if "support_housing" in cid_lower:
            return True
        if role_lower in {"fixed_support_housing", "support_housing", "carrier", "fixed_bracket"}:
            return True
        return type_lower in {"housing", "bracket", "carrier"} and any(token in role_lower for token in ("support", "fixed"))

    support_candidates = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c.get("id"), str) and c.get("id") and _is_fixed_support_component(c)
        ]
    )
    if support_candidates:
        return support_candidates[0]

    ids = sorted(
        [str(c.get("id")) for c in components if isinstance(c.get("id"), str) and c.get("id")]
    )
    if "central_hub" in ids:
        return "central_hub"

    hub_candidates = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c.get("id"), str)
            and c.get("id")
            and str(c.get("type", "")).strip().lower() in {"hub", "center", "central"}
        ]
    )
    if hub_candidates:
        return hub_candidates[0]

    parent_ref_count: Dict[str, int] = {}
    for comp in components:
        parent = comp.get("position_parent")
        if isinstance(parent, str) and parent:
            parent_ref_count[parent] = parent_ref_count.get(parent, 0) + 1
    if parent_ref_count:
        best = sorted(parent_ref_count.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if isinstance(best, str) and best:
            return best

    first = components[0].get("id")
    if isinstance(first, str) and first:
        return first
    return "root"


def _extract_rotational_pattern_component_ids(kg: Dict[str, Any]) -> List[str]:
    out: set[str] = set()
    patterns = kg.get("patterns")
    if not isinstance(patterns, list):
        return []
    for pat in patterns:
        if not isinstance(pat, dict):
            continue
        ptype = pat.get("type")
        if not isinstance(ptype, str):
            continue
        if ptype.strip().lower() not in {"rotational_symmetry", "radial_symmetry", "rotational"}:
            continue
        comp_ids = pat.get("component_ids")
        if isinstance(comp_ids, list):
            for cid in comp_ids:
                if isinstance(cid, str) and cid:
                    out.add(cid)
    return sorted(out)


def _validate_llm_positions(
    positions: Dict[str, Dict[str, Any]],
    kg: Dict[str, Any],
    parent_chains: Dict[str, List[str]],
    warnings: List[str],
    *,
    ground_root_id: str,
    llm_target_ids: List[str],
) -> bool:
    """
    婵犲痉鏉库偓妤佹叏閹绢喗鍎楀〒姘ｅ亾闁诡垯鐒︾换鍛節閻ф洟姊洪崫鍕垫Ц闁绘锕獮鎰板箹娴ｇ鎯炲銈嗘尪閸ㄦ椽宕曞澶嬬厱闁哄洢鍔屾禍婵嬫煕婵炲灝鈧繈寮婚敐澶嬪€烽柛娆忣樈濡繝姊洪柅鐐茶嫰閸旑垰霉閿濆棗绲诲ù婊堢畺閺屾稓浠﹂崣銉х箒濠殿喖锕粻鏍蓟閿涘嫪娌悹鍥ㄥ絻婵绱?    1. 闂傚倷绀佸﹢閬嶃€傛禒瀣；闁瑰墽绮悡娑㈡煕椤愶絿绠ユ俊鑼舵缁辨帡顢欓懖鈹絿绱掗崒娑樻诞鐎规洖銈稿鎾倷閹绘帞顓洪梻浣藉吹閸嬬偤宕欒ぐ鎺戠；闁告稒娼欏Λ妯好归敐鍫燁仩缁惧墽鍋撻妵鍕籍閸パ冩優闂佸摜鍠庨敃顏堝蓟濞戞﹩娼╂い鎾楀嫷鍚呯紓?    2. Root缂傚倸鍊搁崐椋庣矆娴ｈ　鍋撳闂寸盎闁宠閰ｆ慨鈧柕鍫濇噺瀹撳秹姊洪棃娑辩劸闁稿酣浜跺顒冾樄闁哄矉缍侀獮鍥敊閽樺鐣梻浣筋嚃閸燁偊宕堕妸锔界彨?
    3. 闂佽楠搁悘姘熆濡皷鍋撳鐓庡⒋妤犵偛鍟…銊╁川椤忓嫪澹曢梻鍌氱墛缁嬫帞鎷归敍鍕仏闁靛ň鏅滈悡娆愩亜閹搭厼澧俊顐幖椤洨鎹勯崨闈涢叄瀹曞爼濡歌閻ｅジ姊洪崫鍕棏闁稿鎸荤换娑氣偓娑欘焽閻﹥淇婇锝庢疁妤犵偛鍟抽ˇ褰掓煛?
    
    Returns: True if valid, False otherwise (濠德板€楁慨鐑藉磻閻樿鏄ラ柡宥庡幖闁裤倕鈹戦悩鍙夋悙缂佲偓婢舵劖鐓熸俊顖滎攰椤掔喖鏌涢弬鎸庡殗闁哄本绋戦埥澶婎潨閸噥鏆┑鐑囩到濞层倝鏁冮鍫㈠祦?
    """
    components = kg.get("components", []) or []
    
    # Check 1: Grounded root must be present in output.
    root_pos = positions.get(ground_root_id)
    if not root_pos or not isinstance(root_pos, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} missing in LLM output")
        return False

    # Check 2: All target components placed?
    all_ids = {cid for cid in llm_target_ids if isinstance(cid, str) and cid}
    placed_ids = set(positions.keys())
    missing = all_ids - placed_ids
    
    if missing:
        warnings.append(f"LLM validation FAILED: Missing target components not placed: {missing}")
        return False

    # Check 3: Grounded root anchored at origin (with normalization pass)
    pos = positions.get(ground_root_id)
    if not isinstance(pos, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} has invalid position payload")
        return False

    gx = float(pos.get("x", 0.0) or 0.0)
    gy = float(pos.get("y", 0.0) or 0.0)
    gz = float(pos.get("z", 0.0) or 0.0)

    if abs(gx) > 0.1 or abs(gy) > 0.1 or abs(gz) > 0.1:
        dx, dy, dz = -gx, -gy, -gz
        for cid, p in positions.items():
            if not isinstance(p, dict):
                continue
            px = float(p.get("x", 0.0) or 0.0)
            py = float(p.get("y", 0.0) or 0.0)
            pz = float(p.get("z", 0.0) or 0.0)
            p["x"] = px + dx
            p["y"] = py + dy
            p["z"] = pz + dz
        warnings.append(
            f"LLM validation normalized global offset by delta=({dx:.3f}, {dy:.3f}, {dz:.3f}) to anchor {ground_root_id} at origin"
        )

    pos2 = positions.get(ground_root_id)
    if not pos2 or not isinstance(pos2, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} missing after normalization")
        return False
    gx2 = float(pos2.get("x", 0.0) or 0.0)
    gy2 = float(pos2.get("y", 0.0) or 0.0)
    gz2 = float(pos2.get("z", 0.0) or 0.0)
    if abs(gx2) > 0.1 or abs(gy2) > 0.1 or abs(gz2) > 0.1:
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} not at origin after normalization: {pos2}")
        return False
    
    # Check 4: Radial symmetry preserved?
    sym_patterns = _detect_radial_symmetry_pattern(kg)
    if sym_patterns:
        for parent_id, pattern in sym_patterns.items():
            comp_positions = [positions.get(cid) for cid in pattern["components"] if isinstance(cid, str)]
            comp_positions = [p for p in comp_positions if p and isinstance(p, dict)]
            
            if len(comp_positions) != pattern["count"]:
                warnings.append(f"LLM validation WARNING: Radial pattern under {parent_id} incomplete")
                continue
            
            # Check if distances from parent are roughly equal
            parent_pos = positions.get(parent_id)
            if parent_pos:
                distances = []
                for pos in comp_positions:
                    dx = float(pos.get("x", 0)) - float(parent_pos.get("x", 0))
                    dy = float(pos.get("y", 0)) - float(parent_pos.get("y", 0))
                    dz = float(pos.get("z", 0)) - float(parent_pos.get("z", 0))
                    dist = (dx**2 + dy**2 + dz**2)**0.5
                    distances.append(dist)
                
                # All distances should be roughly equal (within 5% tolerance)
                if distances and max(distances) > 0:
                    variance = max(distances) / min(d for d in distances if d > 0)
                    if variance > 1.05:
                        warnings.append(
                            f"LLM validation WARNING: Radial pattern under {parent_id} "
                            f"has uneven spacing (variance {variance:.2f}x)"
                        )
    
    return True


def _infer_layout_positions(kg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic + LLM-assisted layout position inference (improved version).
    
    Four-phase approach:
    1. **Deterministic**: Recognize equal-spacing patterns
    2. **Constraint Generation**: Extract position hints and hierarchy info
    3. **Improved LLM**: Call with stronger constraints and validation
    4. **Fallback**: If LLM fails validation, use deterministic-only result
    
    Returns:
        {
            "layout_positions": {
                "component_id": {"x": float, "y": float, "z": float},
                ...
            },
            "inference_mode": "deterministic_equal_spacing" | "llm_hierarchical" | "hybrid" | "fallback_origin_only",
            "warnings": [str...],
            "parent_chains": {...}  # Debug info
        }
    """
    import math
    import os
    import json
    
    positions: Dict[str, Dict[str, float]] = {}
    warnings: List[str] = []
    inference_mode = "unknown"
    parent_chains: Dict[str, List[str]] = {}
    
    components = kg.get("components", [])
    if not components:
        return {
            "layout_positions": positions,
            "inference_mode": "empty_kg",
            "warnings": ["No components in KG"],
            "parent_chains": {}
        }
    
    # Build lookup tables
    by_id: Dict[str, Dict[str, Any]] = {}
    by_prefix: Dict[str, List[tuple[str, int, Dict[str, Any]]]] = {}
    
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        by_id[comp_id] = comp
        
        # Try to match pattern: "prefix_N"
        match = re.match(r"^([a-z_]+?)_(\d+)$", comp_id)
        if match:
            prefix = match.group(1)
            index = int(match.group(2))
            if prefix not in by_prefix:
                by_prefix[prefix] = []
            by_prefix[prefix].append((comp_id, index, comp))
    
    # ===== PHASE 1: Deterministic Equal Spacing =====
    for prefix, items in by_prefix.items():
        if len(items) < 3:
            continue
        
        types = {comp.get("type") for _, _, comp in items}
        roles = {comp.get("role") for _, _, comp in items}
        
        if len(types) != 1 or len(roles) != 1:
            continue
        
        radial_dist = None
        first_comp = items[0][2]
        comp_type = first_comp.get("type", "")
        dims = first_comp.get("dimensions", {})
        
        if comp_type == "arm" and "length" in dims:
            radial_dist = float(dims.get("length", 60))
        
        if radial_dist is None:
            radial_dist = 60.0
        
        n = len(items)
        angle_step = 2 * math.pi / n
        
        for idx, (comp_id, _, _) in enumerate(sorted(items, key=lambda x: x[1])):
            angle = idx * angle_step
            x = radial_dist * math.cos(angle)
            y = radial_dist * math.sin(angle)
            z = 0.0
            
            positions[comp_id] = {
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(z, 4)
            }
        
        inference_mode = f"deterministic_equal_spacing_{n}way"
    
    # ===== PHASE 2: Build position parent hierarchy =====
    ground_root_id = _select_ground_root_id(kg)
    position_hints = _extract_position_hints(kg)
    hierarchy_constraints = _build_position_parent_constraints(kg)
    
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id in positions:
            continue  # Already handled by deterministic phase
        
        # Trace position_parent chain
        chain: List[str] = [comp_id]
        current_id = comp_id
        visited: set[str] = {comp_id}
        
        while True:
            current_comp = by_id.get(current_id)
            if not current_comp:
                break
            
            parent_id = current_comp.get("position_parent")
            if not isinstance(parent_id, str):
                break
            
            if parent_id in visited:
                warnings.append(f"Circular position_parent chain detected: {comp_id}")
                break
            
            chain.append(parent_id)
            visited.add(parent_id)
            current_id = parent_id
        
        parent_chains[comp_id] = chain
    
    # Ensure single grounded root at origin
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id == ground_root_id and comp_id not in positions:
            positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}

    total_count = len([c for c in components if isinstance(c, dict) and isinstance(c.get("id"), str)])
    root_count = len([c for c in components if isinstance(c, dict) and not c.get("position_parent")])
    root_ratio = (float(root_count) / float(total_count)) if total_count > 0 else 1.0
    rotational_ids = _extract_rotational_pattern_component_ids(kg)
    has_rotational_pattern = bool(rotational_ids)

    parented_ids = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c, dict)
            and isinstance(c.get("id"), str)
            and isinstance(c.get("position_parent"), str)
            and c.get("position_parent")
        ]
    )
    llm_target_ids = sorted(
        {
            cid
            for cid in (parented_ids + rotational_ids + [ground_root_id])
            if isinstance(cid, str) and cid
        }
    )
    
    # ===== PHASE 3: Improved LLM inference with constraints + validation =====
    has_position_parents = len(parented_ids) > 0
    llm_eligible = len(llm_target_ids) > 0 and (has_position_parents or has_rotational_pattern)
    if llm_eligible and ((root_ratio > 0.6) or (root_count > 5)) and (not has_rotational_pattern):
        llm_eligible = False
        warnings.append(
            f"LLM layout gate disabled: root_ratio={root_ratio:.2f}, root_count={root_count}; using deterministic_only"
        )
        if not inference_mode.startswith("deterministic"):
            inference_mode = "deterministic_only"
    
    llm_call_succeeded = False
    llm_attempted = False
    
    if llm_eligible:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                llm_attempted = True
                
                # Build improved LLM prompt with STRONG constraints
                prompt = f"""You are a mechanical assembly positioning expert. Your task is to infer ABSOLUTE global coordinates for the requested target components.

GROUNDED ROOT ID (the only true ROOT):
{ground_root_id}

STRUCTURAL CONSTRAINT - IMMUTABLE:
The following position_parent relationships form the assembly hierarchy. You MUST respect this tree structure exactly:

{hierarchy_constraints}

CRITICAL RULES:
1. Only component {ground_root_id} is ROOT and MUST be positioned exactly at (0, 0, 0).
2. Other components with position_parent null/None are NOT ROOT and are NOT constrained to origin.
3. For each component with a position_parent, calculate its absolute position by:
   a. Getting the parent's absolute position
   b. Adding the child's relative offset (from position_offset description)
   c. Store the result as absolute global coordinates
4. Return coordinates ONLY for target component ids listed below.
5. Grounded root {ground_root_id} MUST be included in the output and MUST be exactly (0, 0, 0).

LLM TARGET COMPONENT IDS (output only these):
{json.dumps(llm_target_ids, ensure_ascii=False)}

SEMANTIC HINTS (use these to infer relative offsets):
{json.dumps(position_hints, ensure_ascii=False, indent=2) if position_hints else "No position_offset hints available; use engineering defaults."}

SYMMETRY DETECTION:
If multiple components have the same type and same position_parent (where position_parent is a concrete component id), they likely form radial symmetry. Distribute them evenly around the parent.
Do NOT apply symmetry grouping for components whose position_parent is null/None.

Knowledge Graph Components Details:
{json.dumps([dict(comp, id=c.get('id'), type=c.get('type'), position_parent=c.get('position_parent'), position_offset=c.get('position_offset'), dimensions=c.get('dimensions')) for c in components if isinstance(c, dict)], indent=2, ensure_ascii=False)}

OUTPUT REQUIREMENT:
Return ONLY valid JSON (no explanation, no markdown formatting):
{{
    "target_component_id": {{"x": number, "y": number, "z": number}}
}}

Coordinate conventions:
- x, y, z are absolute global coordinates
- Unit: mm (consistent with dimensions in KG)
- Grounded root {ground_root_id}: (0, 0, 0)
- Other coordinates: calculated from position_parent chain
"""
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }],
                    temperature=0.0,
                    timeout=180.0  # 3闂傚倷绀侀幉锛勬暜閹烘嚦娑樷攽鐎ｎ亞顔囬梺鐟板⒔缁垶寮查浣瑰弿婵妫楁晶缁樹繆閺屻儰鎲鹃柡?00+缂傚倸鍊搁崐椋庣矆娴ｈ　鍋撳闂寸盎闁宠閰ｆ慨鈧柕鍫濇閸?D婵犵數鍋犻幓顏嗗緤閻ｅ瞼鐭撻柛顐ｆ礃閸嬵亪鏌涢埄鍐槈缂佺姵濞婇弻鏇熺節韫囨稒顎嶉梺缁樺笂缁瑥顫忔繝姘倞闁挎繂鎳嶆竟鏇㈡⒑閼姐倕鏋戞繛鍙夊灴閹偤鏁冮埀顒傚弲闂佺鍕垫畷闁抽攱鍔欓弻鐔虹矙閸噮鍔夊銇礁娲﹂埛?
                )
                
                try:
                    llm_output = response.choices[0].message.content.strip()
                    
                    # Try to extract JSON if it's wrapped in markdown
                    if "```json" in llm_output:
                        llm_output = llm_output.split("```json")[1].split("```")[0].strip()
                    elif "```" in llm_output:
                        llm_output = llm_output.split("```")[1].split("```")[0].strip()
                    
                    llm_positions = json.loads(llm_output)
                    
                    if not isinstance(llm_positions, dict):
                        warnings.append(f"LLM returned non-dict output: {type(llm_positions)}")
                        llm_call_succeeded = False
                    else:
                        # Validate LLM output before accepting
                        if _validate_llm_positions(
                            llm_positions,
                            kg,
                            parent_chains,
                            warnings,
                            ground_root_id=ground_root_id,
                            llm_target_ids=llm_target_ids,
                        ):
                            # Validation passed - accept LLM positions
                            for comp_id in llm_target_ids:
                                pos = llm_positions.get(comp_id)
                                if isinstance(pos, dict) and "x" in pos and "y" in pos and "z" in pos:
                                    positions[comp_id] = {
                                        "x": float(pos["x"]),
                                        "y": float(pos["y"]),
                                        "z": float(pos["z"])
                                    }
                            llm_call_succeeded = True
                            inference_mode = "hybrid" if "deterministic" in inference_mode else "llm_hierarchical"
                            warnings.append("LLM inference completed and validated successfully")
                        else:
                            # Validation failed - will fallback to deterministic only
                            llm_call_succeeded = False
                            warnings.append("LLM output failed validation; will use fallback")
                
                except json.JSONDecodeError as e:
                    warnings.append(f"LLM position inference failed to parse JSON: {str(e)}")
                    llm_call_succeeded = False
                
            except Exception as e:
                warnings.append(f"LLM position inference error: {str(e)}")
                llm_call_succeeded = False
        else:
            warnings.append("LLM not configured; will use deterministic inference only")
            llm_call_succeeded = False
            llm_attempted = False
            if not inference_mode.startswith("deterministic"):
                inference_mode = "deterministic_only"
    else:
        if not inference_mode.startswith("deterministic"):
            inference_mode = "deterministic_only"
        if not llm_target_ids:
            warnings.append("LLM layout skipped: no target components require LLM positioning")
    
    # ===== PHASE 4: Fallback if LLM failed or not available =====
    if llm_attempted and not llm_call_succeeded:
        # LLM was attempted but failed validation or threw error
        # Fall back to deterministic: root at origin, others at origin too (conservative)
        warnings.append("Using fallback mode: only explicitly positioned components placed, others at origin")
        inference_mode = "fallback_origin_only"
        
        # Ensure all unplaced components are at least at origin with their parent
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id")
            if comp_id and comp_id not in positions:
                positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    
    # Final fallback: ensure all components have at least a position
    if not positions:
        warnings.append("No layout positions inferred; all components at origin (fallback)")
        inference_mode = "fallback_origin_only"
    
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str):
            comp_id = comp.get("id")
            if comp_id not in positions:
                positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    return {
        "layout_positions": positions,
        "inference_mode": inference_mode,
        "warnings": warnings,
        "parent_chains": parent_chains,
        "ground_root_id": ground_root_id,
        "llm_target_ids": llm_target_ids,
        "root_ratio": round(root_ratio, 4),
        "root_count": root_count,
    }

# LLM utilities removed: Agent3a is deterministic by design.

# LLM utilities removed: Agent3a is deterministic by design.


# Canonical Fusion 360 modeling patterns (deterministic vocabulary)
FUSION_MODELING_PATTERNS = {
    "ROTATIONAL_REVOLVE",      # Symmetric cylindrical parts (wheels, pulleys)
    "AXIAL_EXTRUSION",         # Linear cylindrical parts (shafts, pins)
    "PLANAR_PLATE_EXTRUSION",  # Flat plates with uniform thickness
    "PROFILE_EXTRUSION",       # Custom profile parts (arms, brackets)
    "RADIAL_PLATE_EXTRUSION"   # Radial plates with spoke patterns
}

# EXPLICIT CONTRACT: Modeling Pattern 闂?Fusion 360 Official Paradigm
# This is the AUTHORITATIVE mapping from abstract patterns to concrete Fusion strategies.
# Pattern selection (WHAT), this contract defines Fusion execution (HOW).
FUSION_PARADIGM_CONTRACT = {
    "ROTATIONAL_REVOLVE": {
        "primitive_class": "cylindrical",
        "construction_method": "revolve",
        "profile_variants": ["half_profile", "annular"],
        "fusion_best_practice": "Use revolve for rotationally symmetric parts to ensure balanced mass distribution",
        "applicable_to": ["wheel", "pulley", "bearing", "hub", "disk"]
    },
    "AXIAL_EXTRUSION": {
        "primitive_class": "cylindrical",
        "construction_method": "extrude",
        "profile_variants": ["circle", "annular"],
        "fusion_best_practice": "Use extrude for linear cylindrical parts to control axial direction",
        "applicable_to": ["shaft", "axle", "pin", "rod", "fastener"]
    },
    "PLANAR_PLATE_EXTRUSION": {
        "primitive_class": "prismatic",
        "construction_method": "extrude",
        "profile_variants": ["rectangle"],
        "fusion_best_practice": "Use extrude with rectangular profile for uniform thickness plates",
        "applicable_to": ["plate", "panel", "sheet"]
    },
    "PROFILE_EXTRUSION": {
        "primitive_class": "prismatic",
        "construction_method": "extrude",
        "profile_variants": ["rectangle", "fork_profile", "yoke_profile"],
        "fusion_best_practice": "Use extrude with a deterministic prismatic profile that preserves required support topology without inventing a different mechanism.",
        "applicable_to": ["arm", "bracket", "beam", "strut", "fork"]
    },
    "RADIAL_PLATE_EXTRUSION": {
        "primitive_class": "plate",
        "construction_method": "extrude",
        "profile_variants": ["macro_profile"],
        "fusion_best_practice": "Use extrude with semantic profile for radial plates with spoke patterns",
        "applicable_to": ["carrier_plate", "star_plate", "spoke_wheel"]
    }
}

ALLOWED_PROFILE_TYPES = {
    "circle",
    "annular",
    "half_profile",
    "tire_profile",
    "rectangle",
    "fork_profile",
    "yoke_profile",
    "macro_profile",
}

# Deterministic parameter rule library (component intent 闂?parameter rules)
PARAM_RULES: Dict[str, Dict[str, Any]] = {
    "hub": {
        "outer_radius": {"default": 14.0, "min": 6.0, "max": 60.0},
        "thickness": {"default": 8.0, "min": 3.0, "max": 20.0},
    },
    "arm": {
        "length": {"default": 60.0, "min": 20.0, "max": 200.0},
        "width": {"default": 14.0, "min": 6.0, "max": 60.0},
        "thickness": {"default": 6.0, "min": 3.0, "max": 20.0},
        "proportions": {
            "length_to_width": {"min": 2.0, "max": 8.0}
        },
    },
    "wheel": {
        "outer_radius": {"default": 30.0, "min": 10.0, "max": 200.0},
        "width": {"default": 12.0, "min": 4.0, "max": 50.0},
        "proportions": {
            "width_to_radius": {"min": 0.1, "max": 0.6}
        },
        "clearance": {
            "hub": {"min_radial_gap": 1.0}
        }
    },
    "carrier_plate": {
        "thickness": {"default": 6.0, "min": 3.0, "max": 15.0},
        "fillet_radius": {"default": 2.0, "min": 0.5, "max_ratio": 0.3},
        "clearance": {
            "arm": {"min_radial_gap": 1.0}
        }
    },
    "rigid_plate": {
        "thickness": {"default": 6.0, "min": 3.0, "max": 15.0},
    },
    "shaft": {
        "diameter": {"default": 4.0, "min": 2.0, "max": 20.0},
        "length": {"default": 60.0, "min": 10.0, "max": 300.0},
    },
    "bearing": {
        "bore_diameter": {"default": 4.0, "min": 2.0, "max": 200.0},
        "outer_diameter": {"default": 10.0, "min": 4.0, "max": 300.0},
        "width": {"default": 6.0, "min": 2.0, "max": 100.0},
        "thickness": {"default": 6.0, "min": 2.0, "max": 100.0},
        "proportions": {
            "outer_to_bore": {"min": 1.05, "max": 3.5}
        },
        "clearance": {
            "shaft": {"min_bore_diameter_over_shaft": 0.2}
        }
    },
    "fastener": {
        "nominal_diameter": {"default": 3.0, "min": 2.0, "max": 12.0},
        "length": {"default": 8.0, "min": 4.0, "max": 50.0},
        "count": {"default": 3, "min": 1.0, "max": 20.0}
    }
}

EXECUTION_MODES = {
    "deterministic": {
        "description": "Rule-based semantic-to-parametric realization",
        "decision_authority": "Deterministic rules only (no LLM)",
        "use_case": "Always-on deterministic planning",
        "guarantees": "Fully reproducible, no AI variability"
    }
}


def _is_modeling_pattern_allowed(
    comp_type: str,
    pattern: str,
    shape_type: str | None = None,
) -> bool:
    """
    Engineering legality check: is this modeling_pattern allowed for this component type?
    
    This enforces Fusion 360 best practices and physical constraints.
    
    Rules:
    - Rotational parts (wheel, pulley, bearing, hub) 闂?ALLOW ROTATIONAL_REVOLVE
    - Linear cylindrical parts (shaft, axle, fastener) 闂?ALLOW AXIAL_EXTRUSION, DISALLOW ROTATIONAL_REVOLVE
    - Plate parts 闂?ALLOW PLANAR_PLATE_EXTRUSION, RADIAL_PLATE_EXTRUSION
    - Prismatic parts (arm, bracket) 闂?ALLOW PROFILE_EXTRUSION
    
    Args:
        comp_type: Component type from KG
        pattern: Proposed modeling pattern from LLM
        shape_type: Optional normalized shape type hint (cylindrical/prismatic/radial_plate)
    
    Returns:
        True if pattern is allowed for comp_type, False otherwise
    """
    comp_type_lower = comp_type.lower() if comp_type else ""

    allowlist = {
        "wheel": {"ROTATIONAL_REVOLVE"},
        "pulley": {"ROTATIONAL_REVOLVE"},
        "bearing": {"ROTATIONAL_REVOLVE"},
        "hub": {"ROTATIONAL_REVOLVE"},
        "rim": {"ROTATIONAL_REVOLVE"},
        "tire": {"ROTATIONAL_REVOLVE"},
        "shaft": {"AXIAL_EXTRUSION"},
        "axle": {"AXIAL_EXTRUSION"},
        "fastener": {"AXIAL_EXTRUSION"},
        "bolt": {"AXIAL_EXTRUSION"},
        "screw": {"AXIAL_EXTRUSION"},
        "pin": {"AXIAL_EXTRUSION"},
        "arm": {"PROFILE_EXTRUSION"},
        "bracket": {"PROFILE_EXTRUSION"},
        "plate": {"PLANAR_PLATE_EXTRUSION", "RADIAL_PLATE_EXTRUSION"},
        "panel": {"PLANAR_PLATE_EXTRUSION"},
        "sheet": {"PLANAR_PLATE_EXTRUSION"},
        "carrier_plate": {"RADIAL_PLATE_EXTRUSION"},
        "rigid_plate": {"PLANAR_PLATE_EXTRUSION"}
    }
    tokens = set()
    if comp_type_lower:
        tokens.add(comp_type_lower)
        tokens |= {t for t in re.split(r"[^a-zA-Z0-9]+", comp_type_lower) if t}

    for key, allowed in allowlist.items():
        if key in tokens:
            return pattern in allowed

    # Unknown component types: allow patterns consistent with shape_type
    if shape_type == "cylindrical":
        return pattern in {"ROTATIONAL_REVOLVE", "AXIAL_EXTRUSION"}
    if shape_type == "prismatic":
        return pattern in {"PROFILE_EXTRUSION", "PLANAR_PLATE_EXTRUSION"}
    if shape_type == "radial_plate":
        return pattern in {"RADIAL_PLATE_EXTRUSION"}
    return pattern == "PROFILE_EXTRUSION"


def _map_pattern_to_strategy(
    pattern: str,
    shape_semantics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Map accepted modeling_pattern to deterministic strategy fields.
    
    This is a FIXED lookup table aligned with Fusion API best practices.
    LLM selects the pattern, this function translates it to execution parameters.
    
    Args:
        pattern: Validated modeling pattern from LLM
        shape_semantics: Shape semantics from Agent2
    
    Returns:
        Strategy dict with primitive_class, construction_method
    """
    # Fixed mapping: modeling_pattern 闂?strategy fields (no CAD-execution details)
    if pattern == "ROTATIONAL_REVOLVE":
        return {
            "primitive_class": "cylindrical",
            "construction_method": "revolve",
            "selection_rationale": "pattern_rotational_revolve"
        }

    elif pattern == "AXIAL_EXTRUSION":
        return {
            "primitive_class": "cylindrical",
            "construction_method": "extrude",
            "selection_rationale": "pattern_axial_extrusion"
        }

    elif pattern == "PLANAR_PLATE_EXTRUSION":
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "pattern_planar_plate"
        }

    elif pattern == "PROFILE_EXTRUSION":
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "pattern_profile_extrusion"
        }

    elif pattern == "RADIAL_PLATE_EXTRUSION":
        return {
            "primitive_class": "plate",
            "construction_method": "extrude",
            "selection_rationale": "pattern_radial_plate"
        }

    else:
        # Fallback (should never happen if validation works)
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "unknown_pattern_fallback"
        }


class ShapeRealizationPlanner:
    """
    Agent3a 闂?Deterministic Shape Realization Planner (Semantic 闂?Parametric)
    """
    
    def __init__(self, kg: Dict[str, Any], *, function_registry: Dict[str, Any] | None = None):
        self.kg = kg
        self.function_registry = function_registry or {}
        self.components = {c["id"]: c for c in kg.get("components", [])}
        self.components_by_type: Dict[str, List[Dict[str, Any]]] = {}
        self.resolved_param_values: Dict[str, Dict[str, float]] = {}
        self.resolved_param_records: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.fallback_reasons: List[Dict[str, Any]] = []
        for comp in kg.get("components", []):
            ctype = comp.get("type")
            if isinstance(ctype, str):
                self.components_by_type.setdefault(ctype, []).append(comp)

    def _normalize_shape_type(self, shape: Dict[str, Any], comp_type: str) -> str:
        raw = shape.get("type", "prismatic") if isinstance(shape, dict) else "prismatic"
        raw_lower = raw.lower() if isinstance(raw, str) else "prismatic"
        comp_lower = comp_type.lower() if isinstance(comp_type, str) else ""
        if raw_lower in {"cylindrical", "cylinder", "annular", "annulus", "ring"}:
            return "cylindrical"
        if raw_lower in {"radial_plate", "radial", "spoke_plate"}:
            return "radial_plate"
        if raw_lower in {"plate", "planar_plate", "planar"}:
            if comp_lower in {"carrier_plate", "star_plate", "spoke_wheel"}:
                return "radial_plate"
            return "prismatic"
        if raw_lower in {"prismatic", "rectangular"}:
            return "prismatic"
        return "prismatic"

    def _profile_type_from_shape(self, shape: Dict[str, Any], shape_type: str) -> str | None:
        """
        Return a semantic hint only. Final profile_type is normalized later.
        """
        if not isinstance(shape, dict):
            return None

        candidate = shape.get("cross_section") or shape.get("profile_type")
        token = candidate.lower().strip() if isinstance(candidate, str) else None
        if shape_type == "radial_plate":
            return "radial_hint"
        if token in {"circle", "circular", "round"}:
            return "circle_hint"
        if token in {"annular", "annulus", "ring"}:
            return "annular_hint"
        if token in {"rectangle", "rectangular"}:
            return "rectangle_hint"
        if token in {"radial", "semantic_profile", "polygon", "rounded_polygon"}:
            return "radial_hint"
        return None

    def _is_modeling_component(self, component_id: str, part: Dict[str, Any]) -> bool:
        if not isinstance(component_id, str) or not component_id:
            return False

        kind = part.get("kind")
        if not isinstance(kind, str):
            component_obj = self.components.get(component_id, {})
            kind = component_obj.get("kind") if isinstance(component_obj, dict) else None
        if isinstance(kind, str) and kind.strip() == "assembly_node":
            return False

        policy = part.get("modeling_policy")
        if not isinstance(policy, str):
            component_obj = self.components.get(component_id, {})
            policy = component_obj.get("modeling_policy") if isinstance(component_obj, dict) else None
        if isinstance(policy, str) and policy.strip().lower() in {"container_only", "reference_only"}:
            return False

        must_model = part.get("must_model")
        if not isinstance(must_model, bool):
            component_obj = self.components.get(component_id, {})
            if isinstance(component_obj, dict):
                must_model = component_obj.get("must_model")
        if must_model is False:
            return False

        shape = part.get("shape_semantics")
        if isinstance(shape, dict):
            shape_type = shape.get("type")
            if isinstance(shape_type, str) and shape_type.strip().lower() == "assembly_node":
                return False

        return True

    def _select_cylindrical_construction_method(
        self,
        component_id: str,
        shape: Dict[str, Any],
    ) -> str:
        """
        Decide construction method for cylindrical components
        based on applicability domain and feasibility constraints.

        Returns:
            "extrude" or "revolve"
        """
        axial_profile = shape.get("axial_profile") if isinstance(shape, dict) else None
        rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
        axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
        profile_type_hint = shape.get("profile_type") or shape.get("cross_section") if isinstance(shape, dict) else None

        rotational_solid = rotational_profile is True or axial_shape_variation is True
        non_constant_axial = axial_profile not in (None, "constant")
        half_profile_ok = profile_type_hint in {"half_profile", "half-profile", "halfprofile"}

        inner_radius = None
        if isinstance(shape, dict):
            inner_radius = shape.get("inner_radius")
            if inner_radius is None:
                inner_radius = shape.get("bore_radius")
        inner_radius_val = self._numeric_value(inner_radius)
        touches_axis = inner_radius_val is not None and inner_radius_val <= 0

        if rotational_solid and non_constant_axial and half_profile_ok and not touches_axis:
            return "revolve"
        return "extrude"
    
    def plan(self, semantics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main planning entry point.
        
        DECISION AUTHORITY MODEL:
        - LLM proposes modeling_pattern (WHAT paradigm to use)
        - Deterministic rules validate and enforce (CAN be used)
        - Execution parameters are mapped deterministically (HOW to execute)
        
        Returns shape_realization plan with modeling_strategy for each component.
        """
        parts = semantics.get("parts", [])
        self.fallback_reasons = []
        self._resolve_parameters(parts)
        realizations = []
        for part in parts:
            component_id = part.get("component_id")
            if not component_id:
                continue
            if not self._is_modeling_component(component_id, part if isinstance(part, dict) else {}):
                continue
            realization = self._plan_component(part)
            realizations.append(realization)
        execution_mode = "deterministic"

        self._validate_feasibility(parts, realizations)
        # Bearing seat upgrades can widen the realized wheel hub envelope.
        # Size yoke supports only after those host dimensions are finalized.
        self._upgrade_opposed_bearing_seat_realizations(realizations, semantics)
        self._suppress_bearing_backed_wheel_hub_bores(realizations, semantics)
        self._upgrade_rotating_wheel_support_realizations(realizations, semantics)
        self._upgrade_hub_slot_mount_realizations(realizations, semantics)
        self._rewrite_hub_slot_mount_fastener_features(realizations)
        self._enforce_numeric_output(realizations)
        self._final_validate(realizations)
        
        metadata = {
            "plan_id": semantics["metadata"]["plan_id"].replace("_semantics_", "_realization_"),
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "shape_realization_planner",
            "source_semantics_id": semantics["metadata"]["plan_id"],
            "execution_mode": execution_mode,
            "execution_mode_definition": EXECUTION_MODES.get(execution_mode, {}),
            "fusion_paradigm_contract_version": "1.0",
            "fusion_paradigm_contract": {
                k: {
                    "primitive_class": v.get("primitive_class"),
                    "construction_method": v.get("construction_method"),
                }
                for k, v in FUSION_PARADIGM_CONTRACT.items()
            },
        }

        if self.fallback_reasons:
            metadata["fallbacks"] = {
                "count": len(self.fallback_reasons),
                "records": self.fallback_reasons
            }
        
        return {
            "metadata": metadata,
            "component_realizations": realizations
        }

    def _plan_component(
        self,
        part: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select deterministic modeling strategy for one component and resolve
        semantic parameters into numeric dimensions.

        Contract strategy is authoritative and replaces the shape-based strategy entirely.
        """
        component_id = part["component_id"]
        shape = part.get("shape_semantics", {})
        shape_type = self._normalize_shape_type(shape, self.components.get(component_id, {}).get("type", ""))
        comp_type = self.components.get(component_id, {}).get("type", "")

        contract_pattern, contract_source = self._determine_contract_pattern(part, shape_type, comp_type)
        if contract_pattern and not _is_modeling_pattern_allowed(comp_type, contract_pattern, shape_type):
            self._log_fallback(
                component_id=component_id,
                param_name="modeling_pattern",
                reason="pattern_not_allowed_fallback",
                old_value=contract_pattern,
                new_value=None,
                stage="pattern",
            )
            contract_pattern = None
            contract_source = "fallback"
        if shape_type == "cylindrical":
            strategy = self._select_cylindrical_strategy(component_id, shape)
        elif shape_type == "prismatic":
            strategy = self._select_prismatic_strategy(component_id, shape)
        elif shape_type == "radial_plate":
            strategy = self._select_radial_plate_strategy(component_id, shape)
        else:
            raise ValueError(f"Unsupported shape type '{shape_type}' for component '{component_id}'.")

        if contract_pattern:
            contract_strategy = _map_pattern_to_strategy(contract_pattern, shape)
            if not self._is_contract_compatible(contract_strategy, shape_type):
                self._log_fallback(
                    component_id=component_id,
                    param_name="modeling_pattern",
                    reason="contract_shape_mismatch",
                    old_value=contract_pattern,
                    new_value=None,
                    stage="pattern",
                )
                contract_pattern = None
                contract_source = "fallback"
            else:
                contract_rationale = contract_strategy.get("selection_rationale")
                strategy = {**strategy, **contract_strategy}
                rationale_parts = []
                if contract_rationale:
                    rationale_parts.append(contract_rationale)
                rationale_parts.append("contract_pattern_alignment")
                strategy["selection_rationale"] = ";".join(rationale_parts)

        kg_component = self.components.get(component_id, {})
        component_type = str(kg_component.get("type") or "").strip().lower()
        linear_cylindrical_types = {"shaft", "axle", "pin", "fastener", "bolt", "screw", "nut", "washer", "spacer", "standoff", "bushing"}

        # Execution policy: only truly linear cylindrical members are forced back to extrude.
        if (
            shape_type == "cylindrical"
            and isinstance(strategy, dict)
            and component_type in linear_cylindrical_types
            and (shape.get("cross_section") if isinstance(shape, dict) else None) != "annular"
        ):
            current = strategy.get("construction_method")
            cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
            if current != "extrude":
                self._log_fallback(
                    component_id=component_id,
                    param_name="construction_method",
                    reason="extrude_only_execution_policy",
                    old_value=current,
                    new_value="extrude",
                    stage="strategy_selection",
                )
                strategy["construction_method"] = "extrude"
                strategy["profile_type"] = "annular" if cross_section == "annular" else "circle"
                strategy["selection_rationale"] = "extrude_only_execution_policy"
        
        # Add collection info if present in KG
        count = None
        if "parameters" in kg_component:
            count = kg_component["parameters"].get("count")
        
        if count is not None:
            strategy["collection_info"] = {
                "is_collection": True,
                "individual_count": count
            }

        self._normalize_profile_type(strategy)

        comp_type_norm = str(comp_type).strip().lower() if isinstance(comp_type, str) else ""
        if comp_type_norm in {"bearing", "fastener", "fastener_set"}:
            strategy["import_strategy"] = "standard_part_library"
            strategy["import_source"] = "parts_index"

        # NOTE: parameter_resolution is explanatory, not authoritative.
        # Execution uses modeling_strategy.parameter_values (non-macro) or parameter_semantics (macro).
        profile_type = strategy.get("profile_type")
        if profile_type == "macro_profile":
            strategy.pop("parameter_values", None)
        else:
            strategy["parameter_values"] = dict(
                self.resolved_param_values.get(component_id, {})
            )

        construction_method = strategy.get("construction_method")
        if isinstance(construction_method, str) and construction_method:
            strategy["primary_method"] = construction_method.upper()

        realization_class = _infer_realization_class(
            component_type=component_type,
            modeling_strategy=strategy,
            part_payload=part,
        )
        strategy["realization_class"] = realization_class

        effective_contract_pattern = contract_pattern
        primary_method = strategy.get("primary_method")
        if isinstance(effective_contract_pattern, str) and isinstance(primary_method, str):
            expected_contract = FUSION_PARADIGM_CONTRACT.get(effective_contract_pattern)
            expected_method = (
                expected_contract.get("construction_method")
                if isinstance(expected_contract, dict)
                else None
            )
            if isinstance(expected_method, str) and expected_method.upper() != primary_method.upper():
                remapped_pattern = None
                if primary_method.upper() == "EXTRUDE" and shape_type == "cylindrical":
                    remapped_pattern = "AXIAL_EXTRUSION"

                self._log_fallback(
                    component_id=component_id,
                    param_name="contract_pattern_used",
                    reason="contract_pattern_method_mismatch_after_strategy_override",
                    old_value=effective_contract_pattern,
                    new_value=remapped_pattern,
                    stage="contract_alignment",
                )
                effective_contract_pattern = remapped_pattern
                contract_source = "aligned_with_primary_method"

        return {
            "component_id": component_id,
            "modeling_strategy": strategy,
            "parameter_resolution": self.resolved_param_records.get(component_id, {}),
            "contract_pattern_used": effective_contract_pattern,
            "contract_pattern_source": contract_source,
            "realization_class": realization_class,
        }

    def _determine_contract_pattern(
        self,
        part: Dict[str, Any],
        shape_type: str,
        comp_type: str,
    ) -> tuple[Optional[str], str]:
        proposed = None
        if isinstance(part, dict):
            proposed = part.get("modeling_pattern") or part.get("pattern")
        if isinstance(proposed, str) and proposed in FUSION_MODELING_PATTERNS:
            return proposed, "proposed"
        pattern_intent = part.get("pattern_intent") if isinstance(part, dict) else None
        if pattern_intent == "rotational_symmetry":
            return "ROTATIONAL_REVOLVE", "intent"
        if shape_type == "radial_plate":
            return "RADIAL_PLATE_EXTRUSION", "shape_type"
        if shape_type == "prismatic":
            return "PROFILE_EXTRUSION", "shape_type"
        if shape_type == "cylindrical":
            comp_lower = comp_type.lower() if isinstance(comp_type, str) else ""
            shape = part.get("shape_semantics") if isinstance(part, dict) else {}
            cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
            rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
            axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
            if comp_lower in {"wheel", "pulley", "bearing", "rim", "tire"}:
                return "ROTATIONAL_REVOLVE", "component_type"
            if comp_lower == "hub":
                if cross_section == "annular" or rotational_profile is True or axial_shape_variation is True:
                    return "ROTATIONAL_REVOLVE", "component_type"
                return "AXIAL_EXTRUSION", "component_type"
            return "AXIAL_EXTRUSION", "component_type"
        return None, "none"

    def _is_contract_compatible(self, contract_strategy: Dict[str, Any], shape_type: str) -> bool:
        primitive_class = contract_strategy.get("primitive_class")
        construction_method = contract_strategy.get("construction_method")
        shape_map = {
            "cylindrical": "cylindrical",
            "prismatic": "prismatic",
            "radial_plate": "plate",
        }
        expected = shape_map.get(shape_type)
        if expected is None:
            return False
        if primitive_class != expected:
            return False
        if shape_type == "cylindrical":
            return construction_method in {"revolve", "extrude"}
        if shape_type == "prismatic":
            return construction_method == "extrude"
        if shape_type == "radial_plate":
            return construction_method == "extrude"
        return False

    def _numeric_value(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict) and "value" in value:
            try:
                return float(value["value"])
            except Exception:
                return None
        if isinstance(value, str):
            try:
                return float(value)
            except Exception:
                return None
        return None

    def _component_params_raw(self, component_id: str) -> Dict[str, Any]:
        comp = self.components.get(component_id, {})
        params = comp.get("parameters")
        if isinstance(params, dict):
            return params
        return {}

    def _component_params(self, component_id: str) -> Dict[str, Any]:
        if component_id in self.resolved_param_values:
            return self.resolved_param_values[component_id]
        return self._component_params_raw(component_id)

    def _log_fallback(
        self,
        *,
        component_id: str,
        param_name: str,
        reason: str,
        old_value: Any,
        new_value: Any,
        stage: str,
    ) -> None:
        self.fallback_reasons.append(
            {
                "component_id": component_id,
                "param": param_name,
                "reason": reason,
                "old_value": old_value,
                "new_value": new_value,
                "stage": stage,
            }
        )

    def _convert_to_mm(self, value: float, unit: Optional[str]) -> float:
        if not unit:
            return value
        unit_lower = unit.lower()
        factors = {
            "mm": 1.0,
            "cm": 10.0,
            "m": 1000.0,
            "in": 25.4,
            "ft": 304.8,
        }
        factor = factors.get(unit_lower, 1.0)
        return value * factor

    def _default_value(self, component_type: str, param_name: str) -> float:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if isinstance(rule, dict) and "default" in rule:
            return float(rule["default"])
        p = param_name.lower()
        c = component_type.lower() if component_type else ""
        if "thickness" in p or p == "height":
            if "plate" in c or "arm" in c:
                return 6.0
            if "wheel" in c:
                return 8.0
            if "bearing" in c:
                return 6.0
            return 5.0
        if "width" in p:
            if "wheel" in c:
                return 12.0
            if "arm" in c:
                return 14.0
            return 8.0
        if "length" in p or "depth" in p:
            if "arm" in c or "shaft" in c:
                return 60.0
            return 30.0
        if "radius" in p or "diameter" in p:
            if "wheel" in c:
                return 30.0
            if "bearing" in c:
                return 5.0
            if "shaft" in c or "axle" in c:
                return 2.0
            if "hub" in c:
                return 10.0
            return 5.0
        if "arm_count" in p or "count" == p:
            return 3
        return 5.0

    def _is_dimensionless_param(self, param_name: str) -> bool:
        name = param_name.lower()
        return name in {"count", "arm_count"} or name.endswith("_count")

    def _unit_for_param(self, param_name: str) -> str:
        name = param_name.lower() if param_name else ""
        if name.endswith("_param"):
            name = name[: -len("_param")]
        if name in {"count", "arm_count"} or name.endswith("_count"):
            return "count"
        return "mm"

    def _bounds_for(self, value: float, bounds_source: str, param_name: str) -> tuple[float, float]:
        # bounds_source controls envelope tightness; value source is tracked separately.
        is_rule = bounds_source == "rule"
        if self._is_dimensionless_param(param_name):
            base = int(round(value))
            if is_rule:
                return max(1, base - 1), base + 1
            return max(1, base - 2), base + 2
        if is_rule:
            return value * 0.9, value * 1.1
        return value * 0.8, value * 1.2

    def _bounds_source_for(self, component_type: str, param_name: str) -> str:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if isinstance(rule, dict) and ("min" in rule or "max" in rule or "max_ratio" in rule):
            return "rule"
        return "heuristic"

    def _normalize_type_tokens(self, comp_type: str) -> set[str]:
        tokens = {comp_type.lower()} if comp_type else set()
        tokens |= {t for t in re.split(r"[^a-zA-Z0-9]+", comp_type.lower()) if t}
        return tokens

    def _apply_bounds_from_rules(
        self,
        component_type: str,
        param_name: str,
        value: float,
    ) -> float:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if not isinstance(rule, dict):
            return value
        min_v = rule.get("min")
        max_v = rule.get("max")
        if isinstance(min_v, (int, float)):
            value = max(value, float(min_v))
        if isinstance(max_v, (int, float)):
            value = min(value, float(max_v))
        return value

    def _apply_proportions(
        self,
        component_id: str,
        component_type: str,
        resolved: Dict[str, float]
    ) -> None:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        proportions = rules.get("proportions") if isinstance(rules, dict) else None
        if not isinstance(proportions, dict):
            return

        if "length_to_width" in proportions and "length" in resolved and "width" in resolved:
            spec = proportions["length_to_width"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            length = resolved["length"]
            width = resolved["width"]
            ratio = length / width if width > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = width * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="length",
                        reason="proportion_min_length_to_width",
                        old_value=resolved["length"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["length"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = width * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="length",
                        reason="proportion_max_length_to_width",
                        old_value=resolved["length"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["length"] = new_val

        if "width_to_radius" in proportions and "width" in resolved and "outer_radius" in resolved:
            spec = proportions["width_to_radius"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            width = resolved["width"]
            radius = resolved["outer_radius"]
            ratio = width / radius if radius > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = radius * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="width",
                        reason="proportion_min_width_to_radius",
                        old_value=resolved["width"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["width"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = radius * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="width",
                        reason="proportion_max_width_to_radius",
                        old_value=resolved["width"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["width"] = new_val

        if "outer_to_bore" in proportions and "outer_diameter" in resolved and "bore_diameter" in resolved:
            spec = proportions["outer_to_bore"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            outer = resolved["outer_diameter"]
            bore = resolved["bore_diameter"]
            ratio = outer / bore if bore > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = bore * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="outer_diameter",
                        reason="proportion_min_outer_to_bore",
                        old_value=resolved["outer_diameter"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["outer_diameter"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = bore * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="outer_diameter",
                        reason="proportion_max_outer_to_bore",
                        old_value=resolved["outer_diameter"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["outer_diameter"] = new_val

    def _apply_clearance_rules(self, component_id: str, resolved: Dict[str, float]) -> None:
        comp = self.components.get(component_id, {})
        comp_type = comp.get("type", "")
        rules = PARAM_RULES.get(comp_type.lower() if comp_type else "", {})
        clearance = rules.get("clearance") if isinstance(rules, dict) else None
        if not isinstance(clearance, dict):
            return

        if "hub" in clearance:
            gap = clearance["hub"].get("min_radial_gap")
            hub = self._infer_hub_component()
            if isinstance(gap, (int, float)) and hub:
                hub_params = hub.get("parameters", {}) if isinstance(hub.get("parameters"), dict) else {}
                hub_radius = self._numeric_value(hub_params.get("outer_radius"))
                if hub_radius is not None and "outer_radius" in resolved:
                    min_radius = hub_radius + float(gap)
                    if resolved["outer_radius"] < min_radius:
                        self._log_fallback(
                            component_id=component_id,
                            param_name="outer_radius",
                            reason="clearance_hub_min_radial_gap",
                            old_value=resolved["outer_radius"],
                            new_value=min_radius,
                            stage="clearance",
                        )
                        resolved["outer_radius"] = min_radius

        # NOTE: arm clearance for semantic profiles is enforced in feasibility

        if "shaft" in clearance:
            gap = clearance["shaft"].get("min_bore_diameter_over_shaft")
            shafts = self.components_by_type.get("shaft", [])
            kg_component = self.components.get(component_id, {}) if isinstance(self.components, dict) else {}
            dim_sources = kg_component.get("dimension_sources", {}) if isinstance(kg_component.get("dimension_sources"), dict) else {}
            bore_source = dim_sources.get("bore_diameter", {}) if isinstance(dim_sources.get("bore_diameter"), dict) else {}
            component_type = str(kg_component.get("type") or "").strip().lower()
            bore_is_catalog_authority = (
                component_type in {"bearing", "bushing", "seal"}
                or str(bore_source.get("source") or "").strip().lower() == "standard_catalog"
            )
            if isinstance(gap, (int, float)) and shafts and "bore_diameter" in resolved and not bore_is_catalog_authority:
                shaft_params = shafts[0].get("parameters", {}) if isinstance(shafts[0].get("parameters"), dict) else {}
                shaft_d = self._numeric_value(shaft_params.get("diameter"))
                if shaft_d is not None:
                    min_bore = shaft_d + float(gap)
                    if resolved["bore_diameter"] < min_bore:
                        self._log_fallback(
                            component_id=component_id,
                            param_name="bore_diameter",
                            reason="clearance_shaft_min_bore",
                            old_value=resolved["bore_diameter"],
                            new_value=min_bore,
                            stage="clearance",
                        )
                        resolved["bore_diameter"] = min_bore

    def _resolve_semantic_value(
        self,
        component_id: str,
        param_name: str,
        semantic: str | None,
        *,
        known: Dict[str, float],
    ) -> tuple[Optional[float], str]:
        comp_type = self.components.get(component_id, {}).get("type", "")
        base = self._default_value(comp_type, param_name)
        if semantic is None:
            return base, "rule"
        text = semantic.lower().strip()

        if "balanced" in text or "proportion" in text:
            if "width" in param_name and "length" in known:
                return max(4.0, known["length"] * 0.25), "rule"
            if "length" in param_name and "width" in known:
                return max(20.0, known["width"] * 3.0), "rule"
            if "radius" in param_name and "diameter" in known:
                return known["diameter"] / 2.0, "inferred"
            return base, "rule"

        if "thin" in text or "slim" in text:
            return base * 0.6, "rule"
        if "thick" in text or "robust" in text:
            return base * 1.5, "rule"
        if "light" in text:
            return base * 0.5, "rule"
        if "compact" in text:
            return base * 0.8, "rule"
        if "reasonable" in text or "default" in text:
            return base, "rule"

        return base, "rule"

    def _resolve_parameters(self, parts: List[Dict[str, Any]]) -> None:
        self.resolved_param_values = {}
        self.resolved_param_records = {}
        # NOTE: `source` reflects the last authoritative resolution stage, not original provenance.
        for part in parts:
            component_id = part.get("component_id")
            if not component_id:
                continue
            comp_type = self.components.get(component_id, {}).get("type", "")
            shape = part.get("shape_semantics", {})
            raw_params = self._component_params_raw(component_id)

            expected: set[str] = set()
            rule_params = PARAM_RULES.get(comp_type.lower() if comp_type else "", {})
            bound_names: set[str] = set()
            shape_bindings: Dict[str, str] = {}

            def is_numeric_like(val: Any) -> bool:
                if isinstance(val, dict) and "value" in val:
                    return self._numeric_value(val) is not None
                if isinstance(val, (int, float)):
                    return True
                if isinstance(val, str):
                    return self._numeric_value(val) is not None
                return False

            if isinstance(rule_params, dict):
                for key in rule_params.keys():
                    if key not in {"proportions", "clearance"}:
                        expected.add(key)
            for key, value in shape.items():
                if key.endswith("_param") and isinstance(value, str):
                    base = key[: -len("_param")]
                    shape_bindings[base] = value
                    expected.add(base)
                    bound_names.add(value)

            resolved: Dict[str, float] = {}
            records: Dict[str, Dict[str, Any]] = {}
            passthrough_param_names = {
                "diameter",
                "outer_diameter",
                "inner_diameter",
                "bore_diameter",
                "radius",
                "outer_radius",
                "inner_radius",
                "bore_radius",
                "thickness",
                "width",
                "length",
                "height",
            }
            derivable_param_sources = {
                "radius": ("diameter", "outer_diameter", "outer_radius"),
                "outer_radius": ("outer_diameter", "diameter", "radius"),
                "inner_radius": ("inner_diameter", "bore_diameter", "bore_radius"),
            }

            # Record unbound numeric parameters for audit (do not use for strategy)
            for key, val in raw_params.items():
                if key in expected or key in bound_names:
                    continue
                if not is_numeric_like(val):
                    continue
                numeric = None
                if isinstance(val, dict) and "value" in val:
                    numeric = self._numeric_value(val)
                    numeric = self._convert_to_mm(numeric, val.get("unit")) if numeric is not None else None
                elif isinstance(val, (int, float)):
                    numeric = float(val)
                elif isinstance(val, str):
                    numeric = self._numeric_value(val)
                if numeric is None:
                    continue
                if self._is_dimensionless_param(key):
                    numeric = int(round(numeric))
                bounds_source = self._bounds_source_for(comp_type, key)
                min_v, max_v = self._bounds_for(numeric, bounds_source, key)
                note = "unbound_extra_param"
                if key in passthrough_param_names and key not in resolved:
                    resolved[key] = numeric
                    note = "unbound_passthrough_param"
                records[key] = {
                    "value": numeric,
                    "unit": self._unit_for_param(key),
                    "min": min_v,
                    "max": max_v,
                    "bounds_source": bounds_source,
                    "source": "input",
                    "note": note,
                }

            # Pass 1: numeric parameters
            for name in expected:
                raw = raw_params.get(name)
                if raw is None and name in shape_bindings:
                    raw = raw_params.get(shape_bindings[name], shape_bindings[name])
                numeric = None
                source = "input"
                if isinstance(raw, dict) and "value" in raw:
                    numeric = self._numeric_value(raw)
                    numeric = self._convert_to_mm(numeric, raw.get("unit")) if numeric is not None else None
                elif isinstance(raw, (int, float)):
                    numeric = float(raw)
                elif isinstance(raw, str):
                    numeric = self._numeric_value(raw)

                if numeric is not None:
                    if self._is_dimensionless_param(name):
                        numeric = int(round(numeric))
                    if numeric <= 0:
                        fallback = self._default_value(comp_type, name)
                        self._log_fallback(
                            component_id=component_id,
                            param_name=name,
                            reason="non_positive_defaulted",
                            old_value=numeric,
                            new_value=fallback,
                            stage="resolve",
                        )
                        numeric = fallback
                    clamped = self._apply_bounds_from_rules(comp_type, name, numeric)
                    if clamped != numeric:
                        self._log_fallback(
                            component_id=component_id,
                            param_name=name,
                            reason="clamped_to_bounds",
                            old_value=numeric,
                            new_value=clamped,
                            stage="bounds",
                        )
                    numeric = clamped
                    resolved[name] = numeric
                    bounds_source = self._bounds_source_for(comp_type, name)
                    min_v, max_v = self._bounds_for(numeric, bounds_source, name)
                    records[name] = {
                        "value": numeric,
                        "unit": self._unit_for_param(name),
                        "min": min_v,
                        "max": max_v,
                        "bounds_source": bounds_source,
                        "source": source,
                    }

            # Pass 2: semantic or missing parameters
            for name in expected:
                if name in resolved:
                    continue
                derivable_from = derivable_param_sources.get(name, ())
                if any(isinstance(resolved.get(src), (int, float)) and float(resolved.get(src)) > 0 for src in derivable_from):
                    continue
                raw = raw_params.get(name)
                if raw is None and name in shape_bindings:
                    raw = raw_params.get(shape_bindings[name], shape_bindings[name])
                semantic = raw if isinstance(raw, str) else None
                value, source = self._resolve_semantic_value(
                    component_id, name, semantic, known=resolved
                )
                if value is None:
                    continue
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                if semantic is None:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="missing_param_defaulted",
                        old_value=None,
                        new_value=value,
                        stage="resolve",
                    )
                else:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="semantic_resolved_to_rule",
                        old_value=semantic,
                        new_value=value,
                        stage="resolve",
                    )
                clamped = self._apply_bounds_from_rules(comp_type, name, value)
                if clamped != value:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="clamped_to_bounds",
                        old_value=value,
                        new_value=clamped,
                        stage="bounds",
                    )
                value = clamped
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                resolved[name] = value
                bounds_source = self._bounds_source_for(comp_type, name)
                min_v, max_v = self._bounds_for(value, bounds_source, name)
                records[name] = {
                    "value": value,
                    "unit": self._unit_for_param(name),
                    "min": min_v,
                    "max": max_v,
                    "bounds_source": bounds_source,
                    "source": source,
                }

            bearing_like = str(comp_type or "").strip().lower() in {"bearing", "bushing", "seal"}
            if bearing_like:
                width_value = resolved.get("width")
                thickness_value = resolved.get("thickness")
                thickness_record = records.get("thickness") if isinstance(records.get("thickness"), dict) else {}
                width_record = records.get("width") if isinstance(records.get("width"), dict) else {}
                if isinstance(width_value, (int, float)) and (
                    not isinstance(thickness_value, (int, float))
                    or str(thickness_record.get("source") or "").strip().lower() != "input"
                ):
                    resolved["thickness"] = float(width_value)
                    records["thickness"] = {
                        "value": float(width_value),
                        "unit": self._unit_for_param("thickness"),
                        "min": None,
                        "max": None,
                        "bounds_source": self._bounds_source_for(comp_type, "thickness"),
                        "source": "derived",
                        "note": "aliased_from_width",
                    }
                elif isinstance(thickness_value, (int, float)) and (
                    not isinstance(width_value, (int, float))
                    or str(width_record.get("source") or "").strip().lower() != "input"
                ):
                    resolved["width"] = float(thickness_value)
                    records["width"] = {
                        "value": float(thickness_value),
                        "unit": self._unit_for_param("width"),
                        "min": None,
                        "max": None,
                        "bounds_source": self._bounds_source_for(comp_type, "width"),
                        "source": "derived",
                        "note": "aliased_from_thickness",
                    }

            # Pass 3: proportional constraints
            self._apply_proportions(component_id, comp_type, resolved)

            # Pass 4: clearance constraints
            self._apply_clearance_rules(component_id, resolved)

            # Re-apply bounds after adjustments
            for name, value in list(resolved.items()):
                clamped = self._apply_bounds_from_rules(comp_type, name, value)
                if clamped != value:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="clamped_to_bounds",
                        old_value=value,
                        new_value=clamped,
                        stage="bounds",
                    )
                value = clamped
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                resolved[name] = value
                bounds_source = self._bounds_source_for(comp_type, name)
                min_v, max_v = self._bounds_for(value, bounds_source, name)
                if name in records:
                    records[name]["value"] = value
                    records[name]["min"] = min_v
                    records[name]["max"] = max_v
                    records[name]["bounds_source"] = bounds_source
                    if records[name].get("source") == "default":
                        records[name]["source"] = "rule"
                else:
                    records[name] = {
                        "value": value,
                        "unit": self._unit_for_param(name),
                        "min": min_v,
                        "max": max_v,
                        "bounds_source": bounds_source,
                        "source": "rule",
                    }

            # Pass 5: derive cylindrical parameters (radius/inner/outer) in Agent3a
            self._derive_cylindrical_params(component_id, comp_type, resolved, records)

            # Pass 6: derive corner_radius for macro_profile (radial plate) in Agent3a
            profile_hint = self._profile_type_from_shape(shape, self._normalize_shape_type(shape, comp_type))
            is_macro_profile = self._normalize_shape_type(shape, comp_type) == "radial_plate" or profile_hint == "radial_hint"
            if is_macro_profile and "corner_radius" not in resolved:
                arm_width = resolved.get("arm_width")
                hub_radius = resolved.get("hub_radius")
                if isinstance(arm_width, (int, float)) and isinstance(hub_radius, (int, float)):
                    corner_radius = min(float(arm_width) * 0.25, float(hub_radius) * 0.25)
                    corner_radius = max(corner_radius, 0.5)
                    resolved["corner_radius"] = float(corner_radius)
                    bounds_source = self._bounds_source_for(comp_type, "corner_radius")
                    min_v, max_v = self._bounds_for(float(corner_radius), bounds_source, "corner_radius")
                    records["corner_radius"] = {
                        "value": float(corner_radius),
                        "unit": self._unit_for_param("corner_radius"),
                        "min": float(min_v),
                        "max": float(max_v),
                        "bounds_source": bounds_source,
                        "source": "derived",
                        "note": "radial_plate_corner_radius",
                    }

            self.resolved_param_values[component_id] = resolved
            self.resolved_param_records[component_id] = records

    def _derive_cylindrical_params(
        self,
        component_id: str,
        comp_type: str,
        resolved: Dict[str, float],
        records: Dict[str, Dict[str, Any]],
    ) -> None:
        """Derive radius/diameter invariants (geometry-only, not CAD binding)."""
        def _record(param_key: str, value: float, *, reason: str) -> None:
            bounds_source = self._bounds_source_for(comp_type, param_key)
            min_v, max_v = self._bounds_for(float(value), bounds_source, param_key)
            records[param_key] = {
                "value": float(value),
                "unit": self._unit_for_param(param_key),
                "min": float(min_v),
                "max": float(max_v),
                "bounds_source": bounds_source,
                "source": "derived",
                "note": reason,
            }

        radius = resolved.get("radius")
        outer_radius = resolved.get("outer_radius")
        inner_radius = resolved.get("inner_radius")
        diameter = resolved.get("diameter")
        outer_diameter = resolved.get("outer_diameter")
        inner_diameter = resolved.get("inner_diameter")
        bore_radius = resolved.get("bore_radius")
        bore_diameter = resolved.get("bore_diameter")

        if radius is None:
            if isinstance(diameter, (int, float)) and diameter > 0:
                radius = diameter / 2
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_diameter",
                    old_value=diameter,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_diameter")
            elif isinstance(outer_diameter, (int, float)) and outer_diameter > 0:
                radius = outer_diameter / 2
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_outer_diameter",
                    old_value=outer_diameter,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_outer_diameter")
            elif isinstance(outer_radius, (int, float)) and outer_radius > 0:
                radius = outer_radius
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_outer_radius",
                    old_value=outer_radius,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_outer_radius")

        if outer_radius is None and isinstance(outer_diameter, (int, float)) and outer_diameter > 0:
            outer_radius = outer_diameter / 2
            resolved["outer_radius"] = outer_radius
            self._log_fallback(
                component_id=component_id,
                param_name="outer_radius",
                reason="derived_from_outer_diameter",
                old_value=outer_diameter,
                new_value=outer_radius,
                stage="derive",
            )
            _record("outer_radius", outer_radius, reason="derived_from_outer_diameter")

        if inner_radius is None:
            if isinstance(inner_diameter, (int, float)) and inner_diameter > 0:
                inner_radius = inner_diameter / 2
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_inner_diameter",
                    old_value=inner_diameter,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_inner_diameter")
            elif isinstance(bore_radius, (int, float)) and bore_radius > 0:
                inner_radius = bore_radius
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_bore_radius",
                    old_value=bore_radius,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_bore_radius")
            elif isinstance(bore_diameter, (int, float)) and bore_diameter > 0:
                inner_radius = bore_diameter / 2
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_bore_diameter",
                    old_value=bore_diameter,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_bore_diameter")

    def _validate_feasibility(
        self,
        parts: List[Dict[str, Any]],
        realizations: List[Dict[str, Any]],
    ) -> None:
        part_map = {p.get("component_id"): p for p in parts if isinstance(p, dict)}

        for realization in realizations:
            component_id = realization.get("component_id")
            if not component_id:
                continue
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            comp = self.components.get(component_id, {})
            comp_type = comp.get("type", "")
            resolved_values = self.resolved_param_values.setdefault(component_id, {})

            def _update_param(param_key: str, value: float) -> None:
                resolved_values[param_key] = float(value)
                bounds_source = self._bounds_source_for(comp_type, param_key)
                min_v, max_v = self._bounds_for(float(value), bounds_source, param_key)
                recs = self.resolved_param_records.setdefault(component_id, {})
                recs[param_key] = {
                    "value": float(value),
                    "unit": self._unit_for_param(param_key),
                    "source": "feasibility",
                    "min": float(min_v),
                    "max": float(max_v),
                    "bounds_source": bounds_source,
                }

            # 2) No dimension violates declared bounds
            bounds = self.resolved_param_records.get(component_id, {})
            if isinstance(bounds, dict):
                for name, record in list(bounds.items()):
                    if not isinstance(record, dict):
                        continue
                    value = record.get("value")
                    min_v = record.get("min")
                    max_v = record.get("max")
                    rule_key = record.get("rule_key") if isinstance(record.get("rule_key"), str) else None
                    if not isinstance(rule_key, str):
                        rule_key = name
                    if not isinstance(value, (int, float)):
                        continue
                    clamped = float(value)
                    if isinstance(min_v, (int, float)) and clamped < min_v:
                        clamped = float(min_v)
                    if isinstance(max_v, (int, float)) and clamped > max_v:
                        clamped = float(max_v)
                    if clamped != float(value):
                        self._log_fallback(
                            component_id=component_id,
                            param_name=rule_key,
                            reason="bounds_violation",
                            old_value=value,
                            new_value=clamped,
                            stage="feasibility",
                        )
                        _update_param(rule_key, float(clamped))
                        record["value"] = float(clamped)

            # 3) Symmetry constraints are numerically consistent
            part = part_map.get(component_id, {})
            pattern_intent = part.get("pattern_intent") if isinstance(part, dict) else None
            resolved = self.resolved_param_values.get(component_id, {})
            arm_count = None
            for key in ("arm_count", "count"):
                if key in resolved:
                    arm_count = resolved.get(key)
                    break
            if pattern_intent == "rotational_symmetry":
                if not isinstance(arm_count, (int, float)) or int(round(arm_count)) < 2:
                    fallback = 3
                    self._log_fallback(
                        component_id=component_id,
                        param_name="arm_count",
                        reason="invalid_symmetry_count_defaulted",
                        old_value=arm_count,
                        new_value=fallback,
                        stage="feasibility",
                    )
                    self.resolved_param_records.setdefault(component_id, {})["arm_count"] = {
                        "value": fallback,
                        "unit": "count",
                        "min": 2,
                        "max": 20,
                        "bounds_source": "rule",
                        "source": "feasibility",
                    }
                    _update_param("arm_count", fallback)

            # 4) Clearance between repeated components is non-negative
            kg_comp = self.components.get(component_id, {})
            count = None
            if isinstance(kg_comp, dict):
                params = kg_comp.get("parameters")
                if isinstance(params, dict):
                    count = params.get("count")
            if isinstance(count, int) and count > 1:
                clearance_value = None
                for key in ("clearance", "gap", "spacing", "pitch"):
                    if key in resolved:
                        clearance_value = resolved.get(key)
                        break
                if clearance_value is not None and (
                    not isinstance(clearance_value, (int, float)) or clearance_value < 0
                ):
                    self._log_fallback(
                        component_id=component_id,
                        param_name="clearance",
                        reason="negative_clearance_defaulted",
                        old_value=clearance_value,
                        new_value=0.0,
                        stage="feasibility",
                    )
                    self.resolved_param_records.setdefault(component_id, {})["clearance"] = {
                        "value": 0.0,
                        "unit": "mm",
                        "min": 0.0,
                        "max": 1000.0,
                        "bounds_source": "rule",
                        "source": "feasibility",
                    }

            profile_type = strategy.get("profile_type")
            if profile_type == "macro_profile":
                strategy.pop("parameter_values", None)
                resolved = self.resolved_param_values.get(component_id, {})
                hub_radius = resolved.get("hub_radius")
                arm_count = resolved.get("arm_count")
                arm_length = resolved.get("arm_length")
                arm_width = resolved.get("arm_width")
                thickness = resolved.get("thickness")
                corner_radius = resolved.get("corner_radius")

                missing = [
                    name
                    for name, value in (
                        ("hub_radius", hub_radius),
                        ("arm_count", arm_count),
                        ("arm_length", arm_length),
                        ("arm_width", arm_width),
                        ("thickness", thickness),
                        ("corner_radius", corner_radius),
                    )
                    if not isinstance(value, (int, float))
                ]
                if missing:
                    raise ValueError(
                        f"macro_profile requires numeric parameters; missing: {', '.join(missing)}"
                    )

                if arm_width <= 0 or hub_radius <= 0:
                    raise ValueError(
                        "macro_profile requires positive hub_radius and arm_width"
                    )

                strategy["parameter_semantics"] = {
                    "hub_radius": float(hub_radius),
                    "arm_count": int(round(arm_count)),
                    "arm_length": float(arm_length),
                    "arm_width": float(arm_width),
                    "thickness": float(thickness),
                    "corner_radius": float(corner_radius),
                }
                strategy["macro_kind"] = "rounded_polygon_radial_plate"
            else:
                strategy["parameter_values"] = dict(resolved_values)

    def _upgrade_rotating_wheel_support_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        def _wheel_stack_width_mm(axle_id: str, fallback_width: float, axle_diameter: float) -> float:
            prefix = axle_id.rsplit("_axle", 1)[0] if "_axle" in axle_id else axle_id
            max_width = 0.0
            for cid, comp in self.components.items():
                if not isinstance(cid, str) or not cid:
                    continue
                if cid != prefix and not cid.startswith(prefix + "_"):
                    continue
                if not isinstance(comp, Mapping):
                    continue
                ctype = str(comp.get("type") or "").strip().lower()
                if ctype not in {"wheel", "hub", "rim", "tire", "bearing", "spacer"}:
                    continue
                dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
                for key in ("thickness", "width", "height"):
                    value = dims.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0:
                        max_width = max(max_width, float(value))
                        break
            if max_width > 0:
                return max_width
            return max(axle_diameter + 4.0, min(max(fallback_width, axle_diameter + 2.0), 24.0))

        def _wheel_outer_radius_mm(axle_id: str, fallback_width: float, axle_diameter: float) -> float:
            prefix = axle_id.rsplit("_axle", 1)[0] if "_axle" in axle_id else axle_id
            max_radius = 0.0
            for cid, comp in self.components.items():
                if not isinstance(cid, str) or not cid:
                    continue
                if cid != prefix and not cid.startswith(prefix + "_"):
                    continue
                if not isinstance(comp, Mapping):
                    continue
                ctype = str(comp.get("type") or "").strip().lower()
                if ctype not in {"wheel", "hub", "rim", "tire"}:
                    continue
                dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
                radius = None
                for key in ("outer_radius", "radius"):
                    value = dims.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0.0:
                        radius = float(value)
                        break
                if radius is None:
                    for key in ("outer_diameter", "diameter"):
                        value = dims.get(key)
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            radius = 0.5 * float(value)
                            break
                if isinstance(radius, (int, float)) and float(radius) > 0.0:
                    max_radius = max(max_radius, float(radius))
            if max_radius > 0.0:
                return max_radius
            return max(0.5 * max(fallback_width, axle_diameter + 6.0), 0.75 * axle_diameter)

        support_by_arm: Dict[str, Dict[str, Any]] = {}
        yoke_supported_axles: set[str] = set()
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            if str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "support_member_distal_attachment":
                continue
            support_topology = str(geometric.get("support_topology") or "").strip().lower()
            axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
            is_yoke = support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates"
            is_fork = support_topology in {"distal_fork_dropout_support", "outboard_single_shear"} or axial_stack_policy == "wheel_body_outboard_of_support_plane"
            if not is_yoke and not is_fork:
                continue
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(arm_id, str) or not isinstance(axle_id, str):
                continue
            arm_comp = self.components.get(arm_id) if isinstance(self.components.get(arm_id), Mapping) else {}
            arm_type = str(arm_comp.get("type") or "").strip().lower()
            if arm_type not in {"arm", "fork", "bracket", "support", "link"}:
                continue
            axle_comp = self.components.get(axle_id) if isinstance(self.components.get(axle_id), Mapping) else {}
            axle_dims = axle_comp.get("dimensions") if isinstance(axle_comp.get("dimensions"), Mapping) else {}
            axle_diameter = axle_dims.get("diameter") or axle_dims.get("outer_diameter") or axle_dims.get("nominal_diameter") or 8.0
            try:
                axle_diameter = float(axle_diameter)
            except Exception:
                axle_diameter = 8.0
            resolved = self.resolved_param_values.get(arm_id, {})
            arm_width = float(resolved.get("width") or arm_comp.get("dimensions", {}).get("width") or 20.0)
            arm_length = float(resolved.get("length") or arm_comp.get("dimensions", {}).get("length") or 60.0)
            arm_thickness = float(resolved.get("thickness") or arm_comp.get("dimensions", {}).get("thickness") or 6.0)
            ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
            inset = ref_anchor.get("inset_mm")
            if not isinstance(inset, (int, float)) or float(inset) <= 0:
                inset = max(axle_diameter + 4.0, min(arm_width * 0.6, arm_length * 0.2), 10.0)
            slot_depth = min(max(float(inset), axle_diameter + 4.0), max(8.0, arm_length * 0.3))
            wheel_stack_width = _wheel_stack_width_mm(axle_id, arm_width, axle_diameter)
            wheel_outer_radius = _wheel_outer_radius_mm(axle_id, arm_width, axle_diameter)
            if is_yoke:
                clearance_mm = 2.0
                plate_thickness = max(2.5, min(max(0.5 * arm_thickness, 2.5), max(4.0, 0.75 * axle_diameter)))
                gap_width = max(wheel_stack_width + 2.0 * clearance_mm, axle_diameter + 4.0)
                total_thickness = (2.0 * plate_thickness) + gap_width
                slot_depth = max(
                    float(slot_depth),
                    float(inset) + float(wheel_outer_radius) + float(clearance_mm),
                    float(inset) + (0.5 * float(axle_diameter)) + 2.0,
                )
                root_web_thickness = max(
                    float(plate_thickness),
                    min(float(arm_thickness), max(8.0, float(plate_thickness) * 2.0)),
                )
                support_params = {
                    "axle_inset_mm": float(inset),
                    "thickness": float(total_thickness),
                    "root_web_thickness": float(root_web_thickness),
                    "distal_bore_diameter": float(axle_diameter),
                    "yoke_plate_thickness": float(plate_thickness),
                    "yoke_gap_width": float(gap_width),
                    "yoke_slot_depth": float(slot_depth),
                    "yoke_profile_origin": "midplane",
                }
                support_by_arm[arm_id] = {
                    "profile_type": "yoke_profile",
                    "rationale_suffix": "double_shear_yoke_support_profile",
                    "params": support_params,
                }
                arm_entry = self.components.get(arm_id)
                if isinstance(arm_entry, dict):
                    arm_param_map = arm_entry.get("parameters")
                    if not isinstance(arm_param_map, dict):
                        arm_param_map = {}
                        arm_entry["parameters"] = arm_param_map
                    arm_param_map.update(support_params)
                yoke_supported_axles.add(axle_id)
                continue
            slot_width = min(max(axle_diameter + 2.0, axle_diameter * 1.25), max(0.5, arm_width - 6.0))
            slot_width = max(4.0, slot_width)
            support_by_arm[arm_id] = {
                "profile_type": "fork_profile",
                "rationale_suffix": "fork_dropout_support_profile",
                "params": {
                    "axle_inset_mm": float(inset),
                    "fork_slot_width": float(slot_width),
                    "fork_slot_depth": float(slot_depth),
                },
            }

        if support_by_arm:
            for realization in realizations:
                if not isinstance(realization, Mapping):
                    continue
                component_id = realization.get("component_id")
                if not isinstance(component_id, str) or component_id not in support_by_arm:
                    continue
                strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
                if not isinstance(strategy, dict):
                    continue
                if str(strategy.get("construction_method") or "").strip().lower() != "extrude":
                    continue
                params = dict(strategy.get("parameter_values") or {})
                resolved = self.resolved_param_values.get(component_id, {})
                if "length" not in params and isinstance(resolved.get("length"), (int, float)):
                    params["length"] = float(resolved.get("length"))
                if "width" not in params and isinstance(resolved.get("width"), (int, float)):
                    params["width"] = float(resolved.get("width"))
                if "thickness" not in params and isinstance(resolved.get("thickness"), (int, float)):
                    params["thickness"] = float(resolved.get("thickness"))

                support = support_by_arm[component_id]
                params.update(support["params"])
                strategy["profile_type"] = support["profile_type"]
                rationale = str(strategy.get("selection_rationale") or "")
                strategy["selection_rationale"] = (rationale + ";" + support["rationale_suffix"]).strip(";")
                strategy["parameter_values"] = params

                comp_entry = self.components.get(component_id)
                if isinstance(comp_entry, dict):
                    dims = comp_entry.get("dimensions")
                    if not isinstance(dims, dict):
                        dims = {}
                        comp_entry["dimensions"] = dims
                    for key in ("length", "width", "thickness"):
                        value = params.get(key)
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            dims[key] = float(value)
                    comp_params = comp_entry.get("parameters")
                    if not isinstance(comp_params, dict):
                        comp_params = {}
                        comp_entry["parameters"] = comp_params
                    for key, value in support["params"].items():
                        if isinstance(value, (int, float)):
                            comp_params[key] = float(value)
                            self.resolved_param_values.setdefault(component_id, {})[key] = float(value)
                    if isinstance(params.get("thickness"), (int, float)):
                        self.resolved_param_values.setdefault(component_id, {})["thickness"] = float(params["thickness"])

                inset = float(support["params"]["axle_inset_mm"])
                half_length = 0.5 * float(params.get("length") or resolved.get("length") or 60.0)
                seed_x = round(max(0.0, half_length - inset), 4)
                for feature in realization.get("features", []) if isinstance(realization.get("features"), list) else []:
                    if not isinstance(feature, dict):
                        continue
                    if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
                        continue
                    interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                    interface_name = str(interface_ref.get("name") or "").strip().lower()
                    if support["profile_type"] != "yoke_profile" and interface_name and interface_name != "distal_mount_face":
                        continue
                    seed_z = 0.0
                    if support["profile_type"] == "yoke_profile":
                        plate_thickness = float(support["params"].get("yoke_plate_thickness") or 0.0)
                        gap_width = float(support["params"].get("yoke_gap_width") or 0.0)
                        seed_z = 0.0
                        interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                        interface_ref["name"] = "axial_end_face_max"
                        interface_ref["component_id"] = component_id
                        feature["interface_ref"] = interface_ref
                        anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
                        anchor["face_interface_id"] = "axial_end_face_max"
                        anchor["side_hint"] = "MAX"
                        anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                        feature["anchor"] = anchor
                        geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
                        geometry_parameters["face_interface_id"] = "axial_end_face_max"
                        nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                        nested_anchor["face_interface_id"] = "axial_end_face_max"
                        nested_anchor["side_hint"] = "MAX"
                        nested_anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                        geometry_parameters["anchor"] = nested_anchor
                        feature["geometry_parameters"] = geometry_parameters
                    feature["seed_point_mm"] = {"x": seed_x, "y": 0.0, "z": seed_z}
                    instances = feature.get("instances") if isinstance(feature.get("instances"), list) else []
                    for instance in instances:
                        if isinstance(instance, dict):
                            instance["position"] = {"x": seed_x, "y": 0.0, "z": seed_z}

        for realization in realizations:
            if not isinstance(realization, Mapping):
                continue
            strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
            if not isinstance(strategy, dict):
                continue
            if str(strategy.get("profile_type") or "").strip().lower() != "yoke_profile":
                continue
            params = dict(strategy.get("parameter_values") or {})
            length = float(params.get("length") or 60.0)
            axle_inset = float(params.get("axle_inset_mm") or 12.0)
            plate_thickness = float(params.get("yoke_plate_thickness") or 3.0)
            gap_width = float(params.get("yoke_gap_width") or 10.0)
            seed_x = round(max(0.0, (0.5 * length) - axle_inset), 4)
            seed_z = 0.0
            for feature in realization.get("features", []) if isinstance(realization.get("features"), list) else []:
                if not isinstance(feature, dict):
                    continue
                if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
                    continue
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                interface_ref["name"] = "axial_end_face_max"
                interface_ref["component_id"] = component_id
                feature["interface_ref"] = interface_ref
                anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
                anchor["face_interface_id"] = "axial_end_face_max"
                anchor["side_hint"] = "MAX"
                anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                feature["anchor"] = anchor
                geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
                geometry_parameters["face_interface_id"] = "axial_end_face_max"
                nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                nested_anchor["face_interface_id"] = "axial_end_face_max"
                nested_anchor["side_hint"] = "MAX"
                nested_anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                geometry_parameters["anchor"] = nested_anchor
                feature["geometry_parameters"] = geometry_parameters
                feature["seed_point_mm"] = {"x": seed_x, "y": 0.0, "z": seed_z}
                instances = feature.get("instances") if isinstance(feature.get("instances"), list) else []
                for instance in instances:
                    if isinstance(instance, dict):
                        instance["position"] = {"x": seed_x, "y": 0.0, "z": seed_z}

        if yoke_supported_axles:
            for realization in realizations:
                if not isinstance(realization, Mapping):
                    continue
                component_id = realization.get("component_id")
                if not isinstance(component_id, str) or component_id not in yoke_supported_axles:
                    continue
                strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
                if not isinstance(strategy, dict):
                    continue
                if str(strategy.get("construction_method") or "").strip().lower() != "extrude":
                    continue
                params = dict(strategy.get("parameter_values") or {})
                params["symmetric_about_sketch_plane"] = True
                strategy["parameter_values"] = params

    def _upgrade_opposed_bearing_seat_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        realization_by_id: Dict[str, Dict[str, Any]] = {}
        for item in realizations:
            if isinstance(item, dict) and isinstance(item.get("component_id"), str):
                realization_by_id[str(item["component_id"])] = item

        host_to_bearings: Dict[str, Dict[str, str]] = {}
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "press_fit":
                continue
            anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            if str(anchor_semantics.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "bearing_outer_race_seat":
                continue
            host_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
            bearing_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
            if not isinstance(host_id, str) or not isinstance(bearing_id, str):
                continue
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            interface_name = str(interface_ref.get("name") or placement.get("seat_side") or "").strip().lower()
            side = "min" if interface_name.endswith("_min") or interface_name == "min" else ("max" if interface_name.endswith("_max") or interface_name == "max" else "")
            if side:
                host_to_bearings.setdefault(host_id, {})[bearing_id] = side

        for host_id, bearing_sides in host_to_bearings.items():
            if len(bearing_sides) < 2:
                continue
            host_realization = realization_by_id.get(host_id)
            if not isinstance(host_realization, dict):
                continue
            strategy = host_realization.get("modeling_strategy") if isinstance(host_realization.get("modeling_strategy"), dict) else None
            if not isinstance(strategy, dict):
                continue
            params = dict(strategy.get("parameter_values") or {})
            host_comp = self.components.get(host_id) if isinstance(self.components.get(host_id), Mapping) else {}
            host_dims = host_comp.get("dimensions") if isinstance(host_comp.get("dimensions"), Mapping) else {}
            widths: List[float] = []
            for bearing_id in bearing_sides.keys():
                bearing_comp = self.components.get(bearing_id) if isinstance(self.components.get(bearing_id), Mapping) else {}
                bearing_dims = bearing_comp.get("dimensions") if isinstance(bearing_comp.get("dimensions"), Mapping) else {}
                width = bearing_dims.get("width") or bearing_dims.get("thickness")
                if isinstance(width, (int, float)) and float(width) > 0.0:
                    widths.append(float(width))
            max_width = max(widths) if widths else 7.0
            shoulder_mm = 1.0
            current_thickness = params.get("thickness")
            if not isinstance(current_thickness, (int, float)) or float(current_thickness) <= 0.0:
                current_thickness = host_dims.get("thickness") or self.resolved_param_values.get(host_id, {}).get("thickness") or (2.0 * max_width + 2.0 * shoulder_mm)
            desired_thickness = max(float(current_thickness), 2.0 * max_width + 2.0 * shoulder_mm)
            params["thickness"] = float(desired_thickness)
            params["opposed_bearing_width"] = float(max_width)
            params["opposed_bearing_shoulder"] = float(shoulder_mm)
            strategy["parameter_values"] = params
            rationale = str(strategy.get("selection_rationale") or "")
            if "opposed_bearing_outer_race_stack" not in rationale:
                strategy["selection_rationale"] = (rationale + ';opposed_bearing_outer_race_stack').strip(';')

            if isinstance(host_comp, dict):
                dims = host_comp.get("dimensions") if isinstance(host_comp.get("dimensions"), dict) else {}
                dims["thickness"] = float(desired_thickness)
                host_comp["dimensions"] = dims
                comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                comp_params["opposed_bearing_width"] = float(max_width)
                comp_params["opposed_bearing_shoulder"] = float(shoulder_mm)
                host_comp["parameters"] = comp_params
            self.resolved_param_values.setdefault(host_id, {})["thickness"] = float(desired_thickness)
            self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_width"] = float(max_width)
            self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_shoulder"] = float(shoulder_mm)

            desired_sides = sorted({side for side in bearing_sides.values() if side in {"min", "max"}}, key=lambda value: 0 if value == "min" else 1)
            seat_features = []
            for feature in host_realization.get("features", []) if isinstance(host_realization.get("features"), list) else []:
                if isinstance(feature, dict) and str(feature.get("feature_type") or "").strip().lower() == "bearing_seat":
                    seat_features.append(feature)
            seat_features.sort(key=lambda item: str(item.get("feature_id") or ""))
            seat_diameters: List[float] = []
            seat_depths: List[float] = []
            for seat_feature in seat_features:
                geometry_parameters = seat_feature.get("geometry_parameters") if isinstance(seat_feature.get("geometry_parameters"), dict) else {}
                seat_diameter = geometry_parameters.get("bore_diameter")
                seat_depth = geometry_parameters.get("depth")
                if isinstance(seat_diameter, (int, float)) and float(seat_diameter) > 0.0:
                    seat_diameters.append(float(seat_diameter))
                if isinstance(seat_depth, (int, float)) and float(seat_depth) > 0.0:
                    seat_depths.append(float(seat_depth))
            if seat_diameters:
                seat_diameter_value = float(max(seat_diameters))
                params["opposed_bearing_seat_diameter"] = seat_diameter_value
                if isinstance(host_comp, dict):
                    comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                    comp_params["opposed_bearing_seat_diameter"] = seat_diameter_value
                    host_comp["parameters"] = comp_params
                self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_seat_diameter"] = seat_diameter_value
            if seat_depths:
                seat_depth_value = float(max(seat_depths))
                params["opposed_bearing_seat_depth"] = seat_depth_value
                if isinstance(host_comp, dict):
                    comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                    comp_params["opposed_bearing_seat_depth"] = seat_depth_value
                    host_comp["parameters"] = comp_params
                self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_seat_depth"] = seat_depth_value
            strategy["parameter_values"] = params
            for side, feature in zip(desired_sides, seat_features):
                interface_name = f"bearing_seat_{side}"
                start_face_interface_id = f"axial_end_face_{side}"
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), dict) else {}
                interface_ref["name"] = interface_name
                feature["interface_ref"] = interface_ref
                geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), dict) else {}
                geometry_parameters["face_interface_id"] = start_face_interface_id
                geometry_parameters["side_hint"] = side.upper()
                nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), dict) else {}
                nested_anchor["face_interface_id"] = start_face_interface_id
                nested_anchor["side_hint"] = side.upper()
                geometry_parameters["anchor"] = nested_anchor
                feature["geometry_parameters"] = geometry_parameters
                anchor = feature.get("anchor") if isinstance(feature.get("anchor"), dict) else {}
                anchor["face_interface_id"] = start_face_interface_id
                anchor["side_hint"] = side.upper()
                feature["anchor"] = anchor
                feature["seat_side"] = side

    def _suppress_bearing_backed_wheel_hub_bores(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        hub_to_bearings: Dict[str, Set[str]] = {}
        axle_to_bearings: Dict[str, Set[str]] = {}
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
            contact_model = str(geometric.get("contact_model") or "").strip().lower()
            if mechanism == "press_fit" and relation_type == "bearing_outer_race_seat":
                hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
                bearing_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
                if isinstance(hub_id, str) and isinstance(bearing_id, str):
                    hub_to_bearings.setdefault(hub_id, set()).add(bearing_id)
                continue
            if mechanism == "shaft_bore_fit" and contact_model == "bearing_inner_race_revolute_fit":
                axle_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
                bearing_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
                if isinstance(axle_id, str) and isinstance(bearing_id, str):
                    axle_to_bearings.setdefault(axle_id, set()).add(bearing_id)

        bearing_backed_hubs: Set[str] = set()
        for hub_id, bearing_ids in hub_to_bearings.items():
            match = re.match(r"^wheel_(\d+)_hub$", str(hub_id), flags=re.IGNORECASE)
            if not match:
                continue
            axle_id = f"wheel_{match.group(1)}_axle"
            if bearing_ids & axle_to_bearings.get(axle_id, set()):
                bearing_backed_hubs.add(hub_id)

        if not bearing_backed_hubs:
            return

        for realization in realizations:
            if not isinstance(realization, dict):
                continue
            component_id = realization.get("component_id")
            if not isinstance(component_id, str) or component_id not in bearing_backed_hubs:
                continue

            features = realization.get("features") if isinstance(realization.get("features"), list) else []
            rewritten_features: List[Dict[str, Any]] = []
            removed_shaft_bore = False
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                feature_type = str(feature.get("feature_type") or "").strip().lower()
                if feature_type == "shaft_bore":
                    interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                    interface_name = str(interface_ref.get("name") or "").strip().lower()
                    if interface_name == "bore_axis" or "rotation@" in str(feature.get("feature_id") or ""):
                        removed_shaft_bore = True
                        continue
                rewritten_features.append(feature)

            if features:
                realization["features"] = rewritten_features
            strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else {}
            params = dict(strategy.get("parameter_values") or {})
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                if key in params:
                    params[key] = 0.0
            strategy["parameter_values"] = params
            realization["modeling_strategy"] = strategy

            parameter_resolution = realization.get("parameter_resolution") if isinstance(realization.get("parameter_resolution"), dict) else {}
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                entry = parameter_resolution.get(key) if isinstance(parameter_resolution.get(key), dict) else None
                if entry is None:
                    continue
                entry["value"] = 0.0
                entry["source"] = "derived"
                entry["note"] = "suppressed_for_bearing_backed_wheel_hub"
                parameter_resolution[key] = entry
            realization["parameter_resolution"] = parameter_resolution

            comp_entry = self.components.get(component_id) if isinstance(self.components.get(component_id), dict) else None
            if isinstance(comp_entry, dict):
                dims = comp_entry.get("dimensions") if isinstance(comp_entry.get("dimensions"), dict) else {}
                for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                    if key in dims:
                        dims[key] = 0.0
                comp_entry["dimensions"] = dims
                comp_params = comp_entry.get("parameters") if isinstance(comp_entry.get("parameters"), dict) else {}
                for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                    if key in comp_params:
                        comp_params[key] = 0.0
                comp_entry["parameters"] = comp_params

            resolved = self.resolved_param_values.setdefault(component_id, {})
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                if key in resolved:
                    resolved[key] = 0.0

    def _upgrade_hub_slot_mount_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        realization_by_id: Dict[str, Dict[str, Any]] = {}
        for item in realizations:
            if isinstance(item, dict) and isinstance(item.get("component_id"), str):
                realization_by_id[str(item["component_id"])] = item

        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric.get("support_topology") or "").strip().lower()
            if support_topology != "hub_radial_slot_mount":
                continue
            hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            arm_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(hub_id, str) or not isinstance(arm_id, str):
                continue
            hub_realization = realization_by_id.get(hub_id)
            arm_realization = realization_by_id.get(arm_id)
            if not isinstance(hub_realization, dict) or not isinstance(arm_realization, dict):
                continue

            hub_strategy = hub_realization.get("modeling_strategy") if isinstance(hub_realization.get("modeling_strategy"), dict) else None
            arm_strategy = arm_realization.get("modeling_strategy") if isinstance(arm_realization.get("modeling_strategy"), dict) else None
            if not isinstance(hub_strategy, dict) or not isinstance(arm_strategy, dict):
                continue

            arm_params = dict(arm_strategy.get("parameter_values") or {})
            resolved_arm = self.resolved_param_values.get(arm_id, {})
            arm_comp = self.components.get(arm_id) if isinstance(self.components.get(arm_id), Mapping) else {}
            arm_width = float(arm_params.get("width") or resolved_arm.get("width") or arm_comp.get("dimensions", {}).get("width") or 20.0)
            arm_thickness = float(arm_params.get("thickness") or resolved_arm.get("thickness") or arm_comp.get("dimensions", {}).get("thickness") or 6.0)
            root_web_thickness = float(
                arm_params.get("root_web_thickness")
                or resolved_arm.get("root_web_thickness")
                or arm_thickness
            )

            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
            insert_depth = moving_anchor.get("inset_mm")
            if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
                insert_depth = 12.0
            slot_depth = max(float(insert_depth) + 2.0, min(max(8.0, arm_width * 0.6), 18.0))
            slot_width = arm_width + 1.0
            slot_height = max(2.0, root_web_thickness + 1.0)

            arm_params["hub_slot_insert_depth"] = float(insert_depth)
            arm_strategy["parameter_values"] = arm_params

            arm_entry = self.components.get(arm_id)
            if isinstance(arm_entry, dict):
                arm_params_map = arm_entry.get("parameters")
                if not isinstance(arm_params_map, dict):
                    arm_params_map = {}
                    arm_entry["parameters"] = arm_params_map
                arm_params_map["hub_slot_insert_depth"] = float(insert_depth)

            hub_params = dict(hub_strategy.get("parameter_values") or {})
            hub_entry = self.components.get(hub_id) if isinstance(self.components.get(hub_id), dict) else {}
            hub_dims = hub_entry.get("dimensions") if isinstance(hub_entry.get("dimensions"), dict) else {}
            hub_thickness = float(hub_params.get("thickness") or self.resolved_param_values.get(hub_id, {}).get("thickness") or hub_dims.get("thickness") or 20.0)
            desired_hub_thickness = max(hub_thickness, root_web_thickness + 4.0)
            hub_params["thickness"] = float(desired_hub_thickness)
            radial_slot_specs = hub_params.get("radial_slot_specs") if isinstance(hub_params.get("radial_slot_specs"), list) else []
            slot_specs_by_arm: Dict[str, Dict[str, float]] = {}
            for existing_spec in radial_slot_specs:
                if not isinstance(existing_spec, Mapping):
                    continue
                existing_arm_id = existing_spec.get("arm_id") if isinstance(existing_spec.get("arm_id"), str) else None
                if not isinstance(existing_arm_id, str) or not existing_arm_id:
                    continue
                slot_specs_by_arm[existing_arm_id] = {
                    "arm_id": existing_arm_id,
                    "slot_width": float(existing_spec.get("slot_width") or 0.0),
                    "slot_depth": float(existing_spec.get("slot_depth") or 0.0),
                    "slot_height": float(existing_spec.get("slot_height") or 0.0),
                    "insert_depth": float(existing_spec.get("insert_depth") or 0.0),
                }
            merged_slot_spec = slot_specs_by_arm.get(
                arm_id,
                {"arm_id": arm_id, "slot_width": 0.0, "slot_depth": 0.0, "slot_height": 0.0, "insert_depth": 0.0},
            )
            merged_slot_spec["slot_width"] = max(float(merged_slot_spec.get("slot_width") or 0.0), float(slot_width))
            merged_slot_spec["slot_depth"] = max(float(merged_slot_spec.get("slot_depth") or 0.0), float(slot_depth))
            merged_slot_spec["slot_height"] = max(float(merged_slot_spec.get("slot_height") or 0.0), float(slot_height))
            merged_slot_spec["insert_depth"] = max(float(merged_slot_spec.get("insert_depth") or 0.0), float(insert_depth))
            slot_specs_by_arm[arm_id] = merged_slot_spec
            hub_params["radial_slot_specs"] = list(slot_specs_by_arm.values())
            hub_strategy["parameter_values"] = hub_params

            if isinstance(hub_entry, dict):
                hub_dims = hub_entry.get("dimensions")
                if not isinstance(hub_dims, dict):
                    hub_dims = {}
                    hub_entry["dimensions"] = hub_dims
                hub_dims["thickness"] = float(desired_hub_thickness)
                hub_params_map = hub_entry.get("parameters")
                if not isinstance(hub_params_map, dict):
                    hub_params_map = {}
                    hub_entry["parameters"] = hub_params_map
                hub_params_map["radial_slot_specs"] = list(slot_specs_by_arm.values())
                hub_params_map["thickness"] = float(desired_hub_thickness)
            self.resolved_param_values.setdefault(hub_id, {})["thickness"] = float(desired_hub_thickness)

    def _rewrite_hub_slot_mount_fastener_features(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            if not isinstance(realization, dict):
                continue
            component_id = realization.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue
            component_entry = self.components.get(component_id) if isinstance(self.components.get(component_id), Mapping) else {}
            component_type = str(component_entry.get("type") or "").strip().lower()
            features = realization.get("features")
            if not isinstance(features, list) or not features:
                continue

            rewritten_features: List[Dict[str, Any]] = []
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                feature_type = str(feature.get("feature_type") or "").strip().lower()
                feature_group_id = str(feature.get("feature_group_id") or feature.get("feature_id") or "").strip().lower()
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                interface_name = str(interface_ref.get("name") or "").strip().lower()
                is_semantic_slot_mount_feature = (
                    interface_name.startswith("slot_mount_face_phase_")
                    or interface_name == "proximal_insert_face"
                )
                if (
                    not is_semantic_slot_mount_feature
                    and "hub_to_arm" not in feature_group_id
                    and "central_hub_to_arm" not in feature_group_id
                    and "central_hub_to_wheel_arm" not in feature_group_id
                ):
                    rewritten_features.append(feature)
                    continue

                if component_type == "arm" and feature_type == "nut_seat":
                    continue

                if feature_type != "hole":
                    rewritten_features.append(feature)
                    continue

                if component_id == "central_hub" or component_type == "arm":
                    updated_feature = dict(feature)
                    interface_ref = updated_feature.get("interface_ref") if isinstance(updated_feature.get("interface_ref"), dict) else {}
                    updated_interface_ref = dict(interface_ref)
                    target_face = "axial_end_face_max"
                    updated_interface_ref["name"] = target_face
                    updated_interface_ref["geometry_type"] = "planar"
                    updated_interface_ref["geom_type"] = "planar"
                    updated_feature["interface_ref"] = updated_interface_ref

                    anchor = updated_feature.get("anchor") if isinstance(updated_feature.get("anchor"), dict) else {}
                    updated_anchor = dict(anchor)
                    updated_anchor["face_interface_id"] = target_face
                    updated_anchor["side_hint"] = "MAX"
                    normal_hint = updated_anchor.get("normal_hint") if isinstance(updated_anchor.get("normal_hint"), dict) else {}
                    updated_anchor["normal_hint"] = {"mode": str(normal_hint.get("mode") or "FACE_NORMAL")}
                    updated_feature["anchor"] = updated_anchor
                    rewritten_features.append(updated_feature)
                    continue

                rewritten_features.append(feature)

            realization["features"] = rewritten_features

    def _enforce_numeric_output(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            component_id = realization.get("component_id")
            if not component_id:
                continue
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            profile_type = strategy.get("profile_type")
            if profile_type == "macro_profile":
                if "parameter_values" in strategy:
                    raise ValueError(
                        f"Macro profile '{profile_type}' must not include parameter_values"
                    )
                allowed_keys = {
                    "hub_radius",
                    "arm_count",
                    "arm_length",
                    "arm_width",
                    "thickness",
                    "corner_radius",
                }
                for k, v in strategy.get("parameter_semantics", {}).items():
                    if k not in allowed_keys:
                        raise ValueError(
                            f"Macro profile parameter '{k}' is not allowed"
                        )
                    if not isinstance(v, (int, float)):
                        raise ValueError(
                            f"Macro profile parameter '{k}' must be numeric, got {v}"
                        )
                    if k.endswith("_param"):
                        raise ValueError(
                            f"Macro profile parameter '{k}' must not end with _param"
                        )
                    if k == "arm_count" and not isinstance(v, int):
                        raise ValueError(
                            f"Macro profile parameter 'arm_count' must be int, got {v}"
                        )
                    if k in {"hub_radius", "arm_length", "arm_width", "thickness", "corner_radius"}:
                        if v <= 0:
                            raise ValueError(
                                f"Macro profile parameter '{k}' must be > 0, got {v}"
                            )
            else:
                if "parameter_values" not in strategy:
                    raise ValueError(
                        f"Non-semantic profile requires parameter_values but none provided"
                    )
                strategy.pop("parameter_semantics", None)

    def _normalize_profile_type(self, strategy: Dict[str, Any]) -> None:
        pt = strategy.get("profile_type")
        alias = {
            "circle_hint": "circle",
            "annular_hint": "annular",
            "rectangle_hint": "rectangle",
            "radial_hint": "macro_profile",
            "circular": "circle",
            "rectangular": "rectangle",
            "radial": "macro_profile",
            "rounded_polygon": "macro_profile",
            "polygon": "macro_profile",
            "semantic_profile": "macro_profile",
            "unspecified": None,
            "unknown": None,
        }
        pt = alias.get(pt, pt)
        if pt in {None, ""}:
            primitive_class = strategy.get("primitive_class")
            if primitive_class == "cylindrical":
                pt = "circle"
            elif primitive_class in {"prismatic", "plate"}:
                pt = "rectangle"
        if pt not in ALLOWED_PROFILE_TYPES:
            raise ValueError(f"Illegal profile_type emitted by Agent3a: {pt}")
        strategy["profile_type"] = pt

    def _assert_no_param_keys(self, obj: Any, *, path: str = "strategy") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if isinstance(key, str) and key.endswith("_param"):
                    raise ValueError(f"Illegal key ending with _param in {path}: {key}")
                next_path = f"{path}.{key}" if isinstance(key, str) else path
                self._assert_no_param_keys(val, path=next_path)
        elif isinstance(obj, list):
            for idx, val in enumerate(obj):
                self._assert_no_param_keys(val, path=f"{path}[{idx}]")

    def _final_validate(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            self._assert_no_param_keys(strategy)
            if strategy.get("construction_method") not in {"extrude", "revolve"}:
                raise ValueError(
                    f"Illegal construction_method emitted by Agent3a: {strategy.get('construction_method')}"
                )
            # Hard constraint: only choose methods supported by the function registry.
            # This prevents drift / fabrication when downstream execution functions are limited.
            method = strategy.get("construction_method")
            if isinstance(method, str) and self.function_registry:
                if not _registry_supports_construction_method(self.function_registry, method):
                    # Prefer sketch+extrude as a conservative fallback.
                    self._log_fallback(
                        component_id=realization.get("component_id", ""),
                        param_name="construction_method",
                        reason="method_not_supported_by_registry",
                        old_value=method,
                        new_value="extrude",
                        stage="final_validate",
                    )
                    strategy["construction_method"] = "extrude"
            if strategy.get("primitive_class") not in {"cylindrical", "prismatic", "plate"}:
                raise ValueError(
                    f"Illegal primitive_class emitted by Agent3a: {strategy.get('primitive_class')}"
                )
            profile_type = strategy.get("profile_type")
            if method == "revolve" and profile_type not in {"half_profile", "tire_profile"}:
                fallback_profile = "annular" if profile_type == "annular" else "circle"
                self._log_fallback(
                    component_id=realization.get("component_id", ""),
                    param_name="construction_method",
                    reason="revolve_requires_half_profile_execution_profile",
                    old_value=f"revolve/{profile_type}",
                    new_value=f"extrude/{fallback_profile}",
                    stage="final_validate",
                )
                strategy["construction_method"] = "extrude"
                strategy["primary_method"] = "EXTRUDE"
                strategy["profile_type"] = fallback_profile
                method = "extrude"
                profile_type = fallback_profile
            if profile_type not in ALLOWED_PROFILE_TYPES:
                raise ValueError(f"Illegal profile_type emitted by Agent3a: {profile_type}")
            if profile_type == "macro_profile":
                for v in strategy.get("parameter_semantics", {}).values():
                    if not isinstance(v, (int, float)):
                        raise ValueError(
                            "Macro profile parameters must be numeric in final validation"
                        )

    def _resolve_param_by_candidates(
        self,
        component_id: str,
        raw: Any,
        *,
        candidates: List[str],
        expect: str = "scalar",
    ) -> Optional[float]:
        params = self._component_params(component_id)
        search_names: List[str] = []
        if isinstance(raw, str):
            search_names.append(raw)
        for c in candidates:
            if c not in search_names:
                search_names.append(c)

        for name in search_names:
            if name in params:
                val = self._numeric_value(params[name])
                if val is None:
                    continue
                if expect == "radius" and "diameter" in name:
                    return val / 2
                return val

        val = self._numeric_value(raw)
        if val is not None:
            return val
        return None

    def _ensure_positive(self, component_id: str, name: str, value: Any) -> float:
        if not isinstance(value, (int, float)) or value <= 0:
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="infeasible_non_positive",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return float(fallback)
        return float(value)

    def _ensure_integer(self, component_id: str, name: str, value: Any) -> int:
        if not isinstance(value, (int, float)):
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="missing_integer_defaulted",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return int(round(fallback))
        iv = int(round(value))
        if iv <= 0:
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="non_positive_integer_defaulted",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return int(round(fallback))
        return iv

    def _infer_arm_components(self) -> List[Dict[str, Any]]:
        arms = list(self.components_by_type.get("arm", []))
        if arms:
            return arms
        for comp in self.components.values():
            cid = comp.get("id", "")
            if isinstance(cid, str) and "arm" in cid:
                arms.append(comp)
        return arms

    def _infer_hub_component(self) -> Optional[Dict[str, Any]]:
        hubs = self.components_by_type.get("hub", [])
        if hubs:
            return hubs[0]
        for comp in self.components.values():
            cid = comp.get("id", "")
            if isinstance(cid, str) and "hub" in cid:
                return comp
        return None
    
    def _select_cylindrical_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for cylindrical components.
        
        CONSTRAINT: Only use binding semantic classifications (no CAD-execution assumptions).
        
        NOTE: Do NOT introduce sketch/profile primitives or *_param bindings here.
        """
        axial_profile = shape.get("axial_profile") if isinstance(shape, dict) else None
        rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
        axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
        profile_type_hint = shape.get("profile_type") or shape.get("cross_section") if isinstance(shape, dict) else None
        cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
        kg_component = self.components.get(component_id, {}) if isinstance(self.components, Mapping) else {}
        component_type = str(kg_component.get("type") or "").strip().lower()

        rotational_solid = rotational_profile is True or axial_shape_variation is True
        non_constant_axial = axial_profile not in (None, "constant")
        half_profile_ok = profile_type_hint in {"half_profile", "half-profile", "halfprofile"}

        inner_radius = None
        if isinstance(shape, dict):
            inner_radius = shape.get("inner_radius")
            if inner_radius is None:
                inner_radius = shape.get("bore_radius")
        inner_radius_val = self._numeric_value(inner_radius)
        touches_axis = inner_radius_val is not None and inner_radius_val <= 0

        annular_rotational_types = {"bearing", "rim", "tire", "hub", "wheel", "roller", "pulley", "sheave"}
        prefer_annular_revolve = cross_section == "annular" and not touches_axis and component_type in annular_rotational_types
        explicit_revolve = rotational_solid and non_constant_axial and not touches_axis

        if prefer_annular_revolve or explicit_revolve:
            rationale = "annular_rotational_body_prefer_revolve" if prefer_annular_revolve else "non_constant_axial_profile_require_revolve"
            resolved_profile_type = "tire_profile" if component_type == "tire" else "half_profile"
            strategy: Dict[str, Any] = {
                "primitive_class": "cylindrical",
                "construction_method": "revolve",
                "profile_type": resolved_profile_type,
                "selection_rationale": rationale,
            }
            return strategy

        if rotational_solid and not non_constant_axial:
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_requires_non_constant_axial_profile",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )
        if rotational_solid and not half_profile_ok and cross_section != "annular":
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_requires_half_profile",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )
        if touches_axis:
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_profile_touches_axis",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )

        rationale = "constant_axial_profile_prefer_extrude"
        profile_type = "annular" if cross_section == "annular" else "circle"
        strategy = {
            "primitive_class": "cylindrical",
            "construction_method": "extrude",
            "profile_type": profile_type,
            "selection_rationale": rationale,
        }
        return strategy
    
    def _select_prismatic_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for prismatic components.
        
        Always extrude for prismatic solids.
        """
        rationale = "standard_prismatic_part"
        strategy: Dict[str, Any] = {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "profile_type": self._profile_type_from_shape(shape, "prismatic"),
            "selection_rationale": rationale
        }
        return strategy
    
    def _select_radial_plate_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for radial plate components.
        
        Radial plates use extrude; detailed profile binding is handled in Agent3b.
        """
        profile_type = self._profile_type_from_shape(shape, "radial_plate")

        strategy: Dict[str, Any] = {
            "primitive_class": "plate",
            "construction_method": "extrude",
            "profile_type": profile_type,
            "selection_rationale": "plate_profile_from_semantics"
        }
        return strategy


def _build_connectivity_graph(kg: Dict[str, Any]) -> Dict[str, set[str]]:
    graph: Dict[str, set[str]] = {}
    reqs = kg.get("connection_requirements")
    if not isinstance(reqs, list):
        return graph
    for req in reqs:
        if not isinstance(req, dict):
            continue
        between = req.get("between")
        if not isinstance(between, list) or len(between) < 2:
            continue
        a = between[0] if isinstance(between[0], str) else None
        b = between[1] if isinstance(between[1], str) else None
        if not a or not b:
            continue
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    return graph


def _infer_aabb_size_mm(*, component_id: str, kg: Dict[str, Any]) -> tuple[float, float, float]:
    comps = kg.get("components")
    dims: dict[str, Any] = {}
    comp_type = ""
    shape_type = ""

    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            if c.get("id") != component_id:
                continue
            comp_type = c.get("type") if isinstance(c.get("type"), str) else ""
            shape = c.get("shape_semantics") if isinstance(c.get("shape_semantics"), dict) else {}
            shape_type = shape.get("type") if isinstance(shape.get("type"), str) else ""
            params = c.get("parameters")
            if isinstance(params, dict):
                dims = dict(params)
            else:
                raw_dims = c.get("dimensions")
                if isinstance(raw_dims, dict):
                    dims = dict(raw_dims)
            break

    def _num(key: str) -> float | None:
        v = dims.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        return None

    radius = _num("outer_radius")
    if radius is None:
        diameter = _num("diameter")
        if diameter is None:
            diameter = _num("outer_diameter")
        if diameter is not None:
            radius = diameter / 2.0
    if radius is None:
        nominal = _num("nominal_diameter")
        if nominal is not None:
            radius = max(1.0, nominal / 2.0)

    thickness = _num("thickness")
    if thickness is None:
        thickness = _num("width")
    if radius is not None and thickness is not None:
        d = max(1.0, float(radius) * 2.0)
        t = max(1.0, float(thickness))
        return (d, d, t)

    length = _num("length")
    width = _num("width")
    height = _num("height")
    if height is None:
        height = _num("thickness")
    if length is not None and width is not None and height is not None:
        return (max(1.0, float(length)), max(1.0, float(width)), max(1.0, float(height)))

    if comp_type == "plate" or shape_type == "radial_plate":
        hub_radius = _num("hub_radius")
        arm_length = _num("arm_length")
        t = height if height is not None else 6.0
        if hub_radius is not None or arm_length is not None:
            hr = float(hub_radius or 20.0)
            al = float(arm_length or 60.0)
            span = max(1.0, 2.0 * (hr + al))
            return (span, span, max(1.0, float(t)))

    return (30.0, 30.0, 30.0)


def _compute_initial_placements(
    *,
    kg: Dict[str, Any],
    component_ids: List[str],
    semantics: Mapping[str, Any] | None = None,
    margin_mm: float = 5.0,
    ground_component_id_override: str | None = None,
) -> Dict[str, Any]:
    import math
    import re

    graph = _build_connectivity_graph(kg)
    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id")): c
        for c in (kg.get("components") or [])
        if isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id")
    }
    component_type_by_id: Dict[str, str] = {
        component_id: str(component.get("type") or "")
        for component_id, component in comp_by_id.items()
        if isinstance(component, Mapping)
    }

    def _is_executable_placement_component(component_id: str) -> bool:
        comp = comp_by_id.get(component_id)
        if not isinstance(comp, Mapping):
            return True
        kind = str(comp.get("kind") or "").strip().lower()
        if kind == "assembly_node":
            return False
        policy = str(comp.get("modeling_policy") or "").strip().lower()
        if policy in {"container_only", "reference_only"}:
            return False
        if comp.get("must_model") is False:
            return False
        if comp.get("has_geometry") is False:
            return False
        shape = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        shape_type = str(shape.get("type") or "").strip().lower()
        if shape_type == "assembly_node":
            return False
        return True

    candidates = [
        cid
        for cid in component_ids
        if isinstance(cid, str) and cid and _is_executable_placement_component(cid)
    ]
    if not candidates:
        return {"initial_placements": [], "summary": {"component_count": 0}}
    candidate_set = set(candidates)

    requested_ground: str | None = None
    if isinstance(ground_component_id_override, str) and ground_component_id_override.strip():
        requested_ground = ground_component_id_override.strip()

    reqs = kg.get("connection_requirements")
    req_list = reqs if isinstance(reqs, list) else []
    synthetic_rigid_pairs: set[tuple[str, str]] = set()

    def _edge_kind(a: str, b: str) -> str:
        # Deterministic, best-effort classification for placement pre-assembly.
        key = tuple(sorted((a, b)))
        if key in synthetic_rigid_pairs:
            return "rigid"
        for req in req_list:
            if not isinstance(req, dict):
                continue
            between = req.get("between")
            if not isinstance(between, list) or len(between) < 2:
                continue
            aa = between[0] if isinstance(between[0], str) else None
            bb = between[1] if isinstance(between[1], str) else None
            if not aa or not bb:
                continue
            if tuple(sorted((aa, bb))) != key:
                continue
            intent = req.get("constraint_intent")
            purpose = req.get("purpose")
            roles = req.get("roles")
            intent_s = str(intent).lower() if isinstance(intent, str) else ""
            purpose_s = str(purpose).lower() if isinstance(purpose, str) else ""
            roles_s = " ".join([str(r).lower() for r in roles]) if isinstance(roles, list) else ""

            if intent_s in {"revolute", "coaxial", "hinge"} or purpose_s in {"rotation", "revolute", "hinge"} or "rotation" in roles_s:
                return "coaxial"
            # Planar mates should be treated as rigid for initial placement grouping,
            # so overlap resolution cannot shear them apart.
            if (
                intent_s in {"planar_mate", "planar", "planar_joint"}
                or purpose_s in {"planar_mate", "planar", "coplanar", "face_alignment"}
                or "planar" in roles_s
                or "coplanar" in roles_s
            ):
                return "rigid"
            if (
                intent_s in {"rigid", "fixed", "bolted", "fastening_mechanism", "bearing_fit"}
                or purpose_s in {"structural_fixation", "load_support", "fastening_mechanism", "bolted", "bearing_fit"}
            ):
                return "rigid"
            return "generic"
        return "generic"

    def _build_allow_overlap_group_lookup() -> Dict[str, str]:
        coax_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        for a in candidates:
            for b in graph.get(a, set()):
                if b not in candidates or a == b:
                    continue
                if _edge_kind(a, b) == "coaxial":
                    coax_adj[a].add(b)

        lookup: Dict[str, str] = {}
        seen: set[str] = set()
        for start in sorted(candidates):
            if start in seen or not coax_adj.get(start):
                continue
            stack = [start]
            seen.add(start)
            members: List[str] = []
            while stack:
                cur = stack.pop()
                members.append(cur)
                for nb in coax_adj.get(cur, set()):
                    if nb in seen:
                        continue
                    seen.add(nb)
                    stack.append(nb)
            if len(members) < 2:
                continue
            chain_set = set(members)
            extended = True
            while extended:
                extended = False
                for cid in candidates:
                    if cid in chain_set:
                        continue
                    comp = comp_by_id.get(cid, {})
                    parent_id = comp.get("position_parent")
                    if isinstance(parent_id, str) and parent_id in chain_set:
                        chain_set.add(cid)
                        extended = True
            group_key = f"coaxial::{sorted(chain_set)[0]}"
            for cid in chain_set:
                lookup[cid] = group_key
        return lookup

    def _is_hierarchy_overlap_candidate(component_id: str) -> bool:
        comp = comp_by_id.get(component_id, {})
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {
            "wheel", "hub", "rim", "tire", "axle", "shaft", "bearing",
            "spacer", "sleeve", "bushing", "roller", "pulley",
        }:
            return True
        shape = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        shape_type = str(shape.get("type") or "").strip().lower()
        return shape_type in {"cylindrical", "annular"}

    def _augment_allow_overlap_lookup_from_hierarchy(lookup: Dict[str, str]) -> Dict[str, str]:
        root_to_members: Dict[str, List[str]] = {}
        for cid in candidates:
            current = cid
            visited_local: set[str] = {cid}
            while True:
                parent = comp_by_id.get(current, {}).get("position_parent")
                if not isinstance(parent, str) or parent not in candidates or parent in visited_local:
                    break
                visited_local.add(parent)
                current = parent
            root_to_members.setdefault(current, []).append(cid)

        for root_id, members in sorted(root_to_members.items(), key=lambda item: item[0]):
            eligible = [
                cid for cid in sorted(set(members))
                if cid == root_id or _is_hierarchy_overlap_candidate(cid)
            ]
            descendant_eligible = [cid for cid in eligible if cid != root_id]
            anchored = [cid for cid in eligible if cid in lookup]
            if len(descendant_eligible) < 2 and not anchored:
                continue
            group_key = lookup.get(anchored[0]) if anchored else f"hierarchy_overlap::{root_id}"
            for cid in eligible:
                lookup.setdefault(cid, group_key)
        return lookup

    allow_overlap_group_by_component = _augment_allow_overlap_lookup_from_hierarchy(
        _build_allow_overlap_group_lookup()
    )

    def _shared_allow_overlap_group(a: str, b: str) -> bool:
        ga = allow_overlap_group_by_component.get(a)
        return bool(ga) and ga == allow_overlap_group_by_component.get(b)

    def degree(cid: str) -> int:
        return len(graph.get(cid, set()))

    def _select_grounded_root() -> str:
        if isinstance(ground_component_id_override, str) and ground_component_id_override.strip():
            ov = ground_component_id_override.strip()
            if ov in candidates:
                return ov
        # Prefer obvious structural roots to keep assembly near-origin.
        for preferred in (
            "module_support_housing",
            "support_housing",
            "fixed_support_housing",
            "central_hub",
            "hub",
            "base",
            "frame",
            "carrier",
            "root",
        ):
            if preferred in candidates:
                return preferred
        # Fallback: highest degree.
        return max(candidates, key=lambda cid: (degree(cid), cid))

    grounded = _select_grounded_root()
    applied_override = bool(requested_ground and grounded == requested_ground)

    sizes = {cid: _infer_aabb_size_mm(component_id=cid, kg=kg) for cid in candidates}
    placed: Dict[str, Dict[str, float]] = {grounded: {"x": 0.0, "y": 0.0, "z": 0.0}}
    yaw_by_cid: Dict[str, float] = {grounded: 0.0}
    orientation_unknown: Dict[str, bool] = {}
    preplaced_wheel_arms: set[str] = set()

    from collections import deque

    q: deque[str] = deque([grounded])
    visited: set[str] = {grounded}

    # Special-case array layout for wheel_arm_<n> to avoid deterministic overlap.
    wheel_arm_pattern = re.compile(r"wheel_arm_(\d+)$", re.IGNORECASE)
    wheel_arm_candidates: List[tuple[int, str]] = []
    for cid in candidates:
        match = wheel_arm_pattern.fullmatch(cid)
        if not match:
            continue
        try:
            idx = int(match.group(1))
        except Exception:
            continue
        wheel_arm_candidates.append((idx, cid))

    if len(wheel_arm_candidates) >= 3:
        wheel_arm_candidates = sorted(wheel_arm_candidates, key=lambda item: (item[0], item[1]))
        arm_size_x = max(float(sizes.get(cid, (30.0, 30.0, 30.0))[0]) for _, cid in wheel_arm_candidates)
        radius_mm = max(float(arm_size_x), 80.0) + float(margin_mm)
        center = placed.get(grounded, {"x": 0.0, "y": 0.0, "z": 0.0})
        cx, cy, cz = float(center.get("x", 0.0)), float(center.get("y", 0.0)), float(center.get("z", 0.0))
        arm_count = len(wheel_arm_candidates)
        for order, (_, cid) in enumerate(wheel_arm_candidates):
            angle_deg = 360.0 * (float(order) / float(arm_count))
            angle_rad = math.radians(angle_deg)
            z_val = float(placed.get(cid, {}).get("z", cz if isinstance(cz, (int, float)) else 0.0))
            placed[cid] = {
                "x": cx + radius_mm * math.cos(angle_rad),
                "y": cy + radius_mm * math.sin(angle_rad),
                "z": z_val,
            }
            yaw_by_cid[cid] = float(angle_deg)
            preplaced_wheel_arms.add(cid)
            if cid not in visited:
                visited.add(cid)
                q.append(cid)

    def _radial_distance_mm(a: str, b: str) -> float:
        asx, asy, _ = sizes.get(a, (30.0, 30.0, 30.0))
        bsx, bsy, _ = sizes.get(b, (30.0, 30.0, 30.0))
        ar = 0.5 * max(float(asx), float(asy))
        br = 0.5 * max(float(bsx), float(bsy))
        return max(10.0, ar + br + float(margin_mm))

    def _axial_distance_mm(a: str, b: str) -> float:
        _, _, az = sizes.get(a, (30.0, 30.0, 30.0))
        _, _, bz = sizes.get(b, (30.0, 30.0, 30.0))
        return max(10.0, 0.5 * float(az) + 0.5 * float(bz) + float(margin_mm))

    def _place_near(parent: str, child: str, *, slot_index: int, sibling_count: int) -> None:
        if child in placed or parent not in placed:
            return
        base = placed[parent]
        kind = _edge_kind(parent, child)

        px, py, pz = float(base.get("x", 0.0)), float(base.get("y", 0.0)), float(base.get("z", 0.0))

        if kind == "coaxial":
            if _shared_allow_overlap_group(parent, child):
                placed[child] = {"x": px, "y": py, "z": pz}
            else:
                dz = _axial_distance_mm(parent, child)
                placed[child] = {"x": px, "y": py, "z": pz + dz}
            yaw_by_cid[child] = 0.0
            orientation_unknown[child] = True
            return


        if kind == "rigid":
            dx = _radial_distance_mm(parent, child)
            sign = -1.0 if (slot_index % 2 == 1) else 1.0
            placed[child] = {"x": px + sign * dx, "y": py, "z": pz}
            yaw_by_cid[child] = 0.0
            return

        # Generic fallback: small offset in X.
        dx = max(10.0, float(sizes.get(child, (30.0, 30.0, 30.0))[0]) + float(margin_mm))
        placed[child] = {"x": px + dx, "y": py, "z": pz}

        yaw_by_cid[child] = 0.0

    while q:
        cur = q.popleft()
        nbs_raw = [nb for nb in graph.get(cur, set()) if nb in candidates]

        def _prio(nb: str) -> tuple[int, str]:
            k = _edge_kind(cur, nb)
            if k == "coaxial":
                return (0, nb)
            if k == "rigid":
                return (1, nb)
            return (2, nb)

        nbs = sorted(nbs_raw, key=_prio)
        for idx, nb in enumerate(nbs):
            if nb not in visited:
                visited.add(nb)
                q.append(nb)
            if nb not in placed:
                _place_near(cur, nb, slot_index=idx, sibling_count=len(nbs))

    # Place disconnected components on an outer ring.
    unplaced = [cid for cid in candidates if cid not in placed]
    if unplaced:
        base_r = 0.0
        for cid in placed:
            if cid == grounded:
                continue
            base_r = max(base_r, math.hypot(float(placed[cid]["x"]), float(placed[cid]["y"])))
        base_r = max(50.0, base_r + 50.0)
        for i, cid in enumerate(sorted(unplaced)):
            ang = 2.0 * math.pi * (float(i) / float(max(1, len(unplaced))))
            r = base_r + _radial_distance_mm(grounded, cid)
            placed[cid] = {"x": r * math.cos(ang), "y": r * math.sin(ang), "z": 0.0}
            yaw_by_cid[cid] = float(math.degrees(ang))

    # Parent-follow pass: enforce position_parent hierarchy deterministically.
    # Children inherit parent frame with small role-based offset.
    role_offsets_mm: Dict[str, Dict[str, float]] = {
        "rim": {"x": 0.0, "y": 0.0, "z": 0.0},
        "tire": {"x": 0.0, "y": 0.0, "z": 1.0},
        "hub": {"x": 0.0, "y": 0.0, "z": 0.0},
        "axle": {"x": 0.0, "y": 0.0, "z": 1.0},
    }

    def _role_of(comp: Mapping[str, Any]) -> str:
        role = comp.get("role_in_parent")
        if isinstance(role, str) and role.strip():
            return role.strip().lower()
        ctype = str(comp.get("type") or "").strip().lower()
        if ctype:
            return ctype
        cid = str(comp.get("id") or "").strip().lower()
        for tok in ("rim", "tire", "hub", "axle"):
            if tok in cid:
                return tok
        return ""

    children_by_parent: Dict[str, List[str]] = {}
    roots: List[str] = []
    for cid in candidates:
        comp = comp_by_id.get(cid, {})
        parent = comp.get("position_parent")
        if isinstance(parent, str) and parent in candidates:
            children_by_parent.setdefault(parent, []).append(cid)
        else:
            roots.append(cid)

    from collections import deque as _dq
    q2: _dq[str] = _dq(sorted(set(roots)))
    seen2: set[str] = set()
    while q2:
        parent = q2.popleft()
        if parent in seen2:
            continue
        seen2.add(parent)
        parent_pos = placed.get(parent, {"x": 0.0, "y": 0.0, "z": 0.0})
        for child in sorted(children_by_parent.get(parent, [])):
            if child in preplaced_wheel_arms:
                q2.append(child)
                continue
            comp = comp_by_id.get(child, {})
            role = _role_of(comp)
            if _shared_allow_overlap_group(parent, child):
                off = {"x": 0.0, "y": 0.0, "z": 0.0}
            else:
                off = role_offsets_mm.get(role, {"x": 0.0, "y": 0.0, "z": 0.0})
            placed[child] = {
                "x": float(parent_pos.get("x", 0.0)) + float(off.get("x", 0.0)),
                "y": float(parent_pos.get("y", 0.0)) + float(off.get("y", 0.0)),
                "z": float(parent_pos.get("z", 0.0)) + float(off.get("z", 0.0)),
            }
            yaw_by_cid[child] = float(yaw_by_cid.get(parent, 0.0))
            q2.append(child)

    def _base_connection_id(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        base = value.split("@", 1)[0].strip()
        return base or None

    def _collect_anchor_semantics() -> List[Dict[str, Any]]:
        placements_src = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements_src, list):
            return []
        deduped: Dict[str, Dict[str, Any]] = {}
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            status = str(placement.get("status") or "").strip().lower()
            if placement.get("requires_clarification") is True or status in {"requires_clarification", "unresolved", "blocked", "rejected"}:
                continue
            anchor = placement.get("anchor_semantics")
            if not isinstance(anchor, Mapping):
                continue
            base_id = _base_connection_id(placement.get("connection_id"))
            if not base_id or base_id in deduped:
                continue
            reference_component_id = anchor.get("reference_component_id")
            moving_component_id = anchor.get("moving_component_id")
            if reference_component_id not in candidates or moving_component_id not in candidates:
                continue
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            anchor_copy = dict(anchor)
            reference_anchor = dict(anchor_copy.get("reference_anchor") or {}) if isinstance(anchor_copy.get("reference_anchor"), Mapping) else {}
            moving_anchor = dict(anchor_copy.get("moving_anchor") or {}) if isinstance(anchor_copy.get("moving_anchor"), Mapping) else {}
            if reference_anchor:
                if not isinstance(reference_anchor.get("radius_mm"), (int, float)):
                    for value in (pattern.get("pattern_radius_mm"), pattern.get("pattern_radius")):
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            reference_anchor["radius_mm"] = float(value)
                            break
                if not isinstance(reference_anchor.get("phase_rad"), (int, float)):
                    start_angle_rad = pattern.get("start_angle_rad")
                    if isinstance(start_angle_rad, (int, float)):
                        reference_anchor["phase_rad"] = float(start_angle_rad)
                if not isinstance(reference_anchor.get("phase_deg"), (int, float)):
                    for value in (pattern.get("start_angle"), pattern.get("phase_deg")):
                        if isinstance(value, (int, float)):
                            reference_anchor["phase_deg"] = float(value)
                            break
                anchor_copy["reference_anchor"] = reference_anchor
            if moving_anchor:
                if not isinstance(moving_anchor.get("inset_mm"), (int, float)):
                    for value in (pattern.get("offset_from_edge"), pattern.get("edge_margin_mm")):
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            moving_anchor["inset_mm"] = float(value)
                            break
                anchor_copy["moving_anchor"] = moving_anchor
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            if isinstance(geometric_semantics, Mapping) and geometric_semantics:
                anchor_copy["geometric_semantics"] = dict(geometric_semantics)
            mechanism_name = placement.get("connection_mechanism") if isinstance(placement.get("connection_mechanism"), str) else None
            if isinstance(mechanism_name, str) and mechanism_name.strip():
                anchor_copy["connection_mechanism"] = mechanism_name.strip().lower()
            deduped[base_id] = anchor_copy
        return [deduped[key] for key in sorted(deduped.keys())]

    subtree_cache: Dict[str, List[str]] = {}

    def _root_component_id(component_id: str) -> str:
        current = component_id
        seen: set[str] = set()
        while current not in seen:
            seen.add(current)
            parent = comp_by_id.get(current, {}).get("position_parent")
            if not isinstance(parent, str) or parent not in candidates:
                break
            current = parent
        return current

    def _subtree_members(root_id: str) -> List[str]:
        cached = subtree_cache.get(root_id)
        if cached is not None:
            return list(cached)
        members: List[str] = []
        stack = [root_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in candidates:
                members.append(current)
            for child in children_by_parent.get(current, []):
                if child not in seen:
                    stack.append(child)
        members = sorted(members)
        subtree_cache[root_id] = members
        return list(members)

    def _component_dims(component_id: str) -> Mapping[str, Any]:
        comp = comp_by_id.get(component_id, {})
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
        params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
        merged: Dict[str, Any] = {}
        if dims:
            merged.update(dims)
        if params:
            for key, value in params.items():
                if key not in merged:
                    merged[key] = value
        return merged

    def _component_length_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("length", "arm_length", "depth"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        return max(1.0, float(sizes.get(component_id, (30.0, 30.0, 30.0))[0]))

    def _component_radius_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("outer_radius", "radius"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        for key in ("diameter", "outer_diameter", "nominal_diameter"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value) / 2.0
        size = sizes.get(component_id, (30.0, 30.0, 30.0))
        return max(1.0, 0.5 * max(float(size[0]), float(size[1])))

    def _component_thickness_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("thickness", "width", "height"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        return max(1.0, float(sizes.get(component_id, (30.0, 30.0, 30.0))[2]))

    def _rotate_xy(dx: float, dy: float, yaw_deg: float) -> Dict[str, float]:
        angle = math.radians(float(yaw_deg))
        c = math.cos(angle)
        s = math.sin(angle)
        return {
            "x": float(dx) * c - float(dy) * s,
            "y": float(dx) * s + float(dy) * c,
        }

    def _anchor_world_point(
        component_id: str,
        anchor_def: Mapping[str, Any],
        *,
        counterpart_id: str | None = None,
    ) -> Dict[str, float] | None:
        if component_id not in placed:
            return None
        center = placed.get(component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        cx = float(center.get("x", 0.0))
        cy = float(center.get("y", 0.0))
        cz = float(center.get("z", 0.0))
        kind = str(anchor_def.get("kind") or "component_center").strip().lower()
        axis = str(anchor_def.get("axis") or "x").strip().lower()
        yaw_deg = float(yaw_by_cid.get(component_id, 0.0))

        if kind == "component_center":
            return {"x": cx, "y": cy, "z": cz}

        if kind in {"distal_end", "proximal_end"}:
            half_length = 0.5 * _component_length_mm(component_id)
            sign = 1.0 if kind == "distal_end" else -1.0
            if axis == "z":
                return {"x": cx, "y": cy, "z": cz + sign * half_length}
            local_dx = sign * half_length if axis != "y" else 0.0
            local_dy = sign * half_length if axis == "y" else 0.0
            rotated = _rotate_xy(local_dx, local_dy, yaw_deg)
            return {"x": cx + rotated["x"], "y": cy + rotated["y"], "z": cz}

        if kind == "radial_mount_perimeter":
            radius = _component_radius_mm(component_id)
            vx = 0.0
            vy = 0.0
            if isinstance(counterpart_id, str) and counterpart_id in placed:
                counterpart_pos = placed.get(counterpart_id, {"x": 0.0, "y": 0.0, "z": 0.0})
                vx = float(counterpart_pos.get("x", 0.0)) - cx
                vy = float(counterpart_pos.get("y", 0.0)) - cy
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                base = _rotate_xy(1.0, 0.0, yaw_deg)
                vx = float(base["x"])
                vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                return {"x": cx, "y": cy, "z": cz}
            return {
                "x": cx + radius * (vx / mag),
                "y": cy + radius * (vy / mag),
                "z": cz,
            }

        if kind in {"axial_face_perimeter_max", "axial_face_perimeter_min"}:
            radius_value = anchor_def.get("radius_mm")
            radius = float(radius_value) if isinstance(radius_value, (int, float)) and float(radius_value) > 0.0 else _component_radius_mm(component_id)
            thickness_half = 0.5 * _component_thickness_mm(component_id)
            z_sign = 1.0 if kind.endswith("_max") else -1.0
            phase_rad_value = anchor_def.get("phase_rad")
            if isinstance(phase_rad_value, (int, float)):
                phase_rad = float(phase_rad_value)
            else:
                phase_deg_value = anchor_def.get("phase_deg")
                phase_rad = math.radians(float(phase_deg_value)) if isinstance(phase_deg_value, (int, float)) else None
            if isinstance(phase_rad, (int, float)):
                return {
                    "x": cx + radius * math.cos(float(phase_rad)),
                    "y": cy + radius * math.sin(float(phase_rad)),
                    "z": cz + z_sign * thickness_half,
                }
            vx = 0.0
            vy = 0.0
            if isinstance(counterpart_id, str) and counterpart_id in placed:
                counterpart_pos = placed.get(counterpart_id, {"x": 0.0, "y": 0.0, "z": 0.0})
                vx = float(counterpart_pos.get("x", 0.0)) - cx
                vy = float(counterpart_pos.get("y", 0.0)) - cy
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                base = _rotate_xy(1.0, 0.0, yaw_deg)
                vx = float(base["x"])
                vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                return {"x": cx, "y": cy, "z": cz + z_sign * thickness_half}
            return {
                "x": cx + radius * (vx / mag),
                "y": cy + radius * (vy / mag),
                "z": cz + z_sign * thickness_half,
            }

        if kind in {"proximal_mount_face_min", "proximal_mount_face_max"}:
            half_length = 0.5 * _component_length_mm(component_id)
            half_thickness = 0.5 * _component_thickness_mm(component_id)
            inset_value = anchor_def.get("inset_mm")
            inset = float(inset_value) if isinstance(inset_value, (int, float)) and float(inset_value) > 0.0 else 0.0
            local_dx = (-half_length + inset) if axis != "y" else 0.0
            local_dy = (-half_length + inset) if axis == "y" else 0.0
            rotated = _rotate_xy(local_dx, local_dy, yaw_deg)
            z_sign = -1.0 if kind.endswith("_min") else 1.0
            return {
                "x": cx + rotated["x"],
                "y": cy + rotated["y"],
                "z": cz + z_sign * half_thickness,
            }

        return {"x": cx, "y": cy, "z": cz}

    def _apply_translation_to_members(members: List[str], dx: float, dy: float, dz: float) -> None:
        for member in members:
            if member not in placed:
                continue
            placed[member] = {
                "x": float(placed[member].get("x", 0.0)) + float(dx),
                "y": float(placed[member].get("y", 0.0)) + float(dy),
                "z": float(placed[member].get("z", 0.0)) + float(dz),
            }

    def _anchor_requires_axis_only_alignment(anchor: Mapping[str, Any]) -> bool:
        mechanism_name = str(anchor.get("connection_mechanism") or "").strip().lower()
        if mechanism_name != "shaft_bore_fit":
            return False
        geometric_semantics = anchor.get("geometric_semantics") if isinstance(anchor.get("geometric_semantics"), Mapping) else {}
        contact_model = str(geometric_semantics.get("contact_model") or "").strip().lower()
        axial_stack_policy = str(geometric_semantics.get("axial_stack_policy") or "").strip().lower()
        return (
            contact_model in {"coaxial_revolute_fit", "bearing_inner_race_revolute_fit"}
            or axial_stack_policy == "preserve_independent_axial_stack"
        )

    def _wheel_group_members_for_axle(axle_id: str) -> List[str]:
        match = re.match(r"^wheel_(\d+)_axle$", axle_id, flags=re.IGNORECASE)
        if not match:
            return []
        suffix = match.group(1)
        root_id = f"wheel_{suffix}"
        prefix = root_id + "_"
        members: List[str] = []

        def _is_wheel_fastener_like(component_id: str) -> bool:
            comp = comp_by_id.get(component_id, {}) if isinstance(comp_by_id.get(component_id), Mapping) else {}
            comp_type = str(comp.get("type") or "").strip().lower()
            part_kind = str(comp.get("part_kind") or "").strip().lower()
            if comp_type in {"fastener", "bolt", "nut", "washer", "screw"}:
                return True
            if part_kind in {"fastener", "fastener_bundle", "hardware", "hardware_bundle"}:
                return True
            component_id_l = component_id.strip().lower()
            return any(token in component_id_l for token in ("fastener", "bolt", "nut", "washer", "screw"))

        for cid in candidates:
            if cid == axle_id:
                continue
            if _is_wheel_fastener_like(cid):
                continue
            if cid == root_id or (cid.startswith(prefix) and not cid.startswith(f"wheel_arm_{suffix}")):
                members.append(cid)
        return sorted(set(members))

    def _wheel_rotating_stack_members_for_axle(axle_id: str) -> List[str]:
        rotating_types = {
            "wheel",
            "hub",
            "rim",
            "tire",
            "bearing",
            "spacer",
            "sleeve",
            "bushing",
            "roller",
            "pulley",
        }
        members: List[str] = []
        for cid in _wheel_group_members_for_axle(axle_id):
            comp = comp_by_id.get(cid, {}) if isinstance(comp_by_id.get(cid), Mapping) else {}
            comp_type = str(comp.get("type") or "").strip().lower()
            if comp_type in rotating_types:
                members.append(cid)
                continue
            cid_l = cid.strip().lower()
            if any(token in cid_l for token in ("hub", "rim", "tire", "bearing", "spacer", "sleeve", "bushing", "roller", "pulley")):
                members.append(cid)
        return sorted(set(members))

    def _wheel_group_width_mm(member_ids: List[str]) -> float:
        widths: List[float] = []
        for member_id in member_ids:
            dims = _component_dims(member_id)
            for key in ("width", "thickness", "height"):
                value = dims.get(key)
                if isinstance(value, (int, float)) and float(value) > 0.0:
                    widths.append(float(value))
                    break
        return max(widths) if widths else 12.0

    anchor_adjustments: List[Dict[str, Any]] = []
    anchor_semantics_list = _collect_anchor_semantics()
    anchor_coupled_pairs: set[tuple[str, str]] = set()
    for anchor in anchor_semantics_list:
        if not isinstance(anchor, Mapping):
            continue
        reference_component_id = anchor.get("reference_component_id")
        moving_component_id = anchor.get("moving_component_id")
        if (
            isinstance(reference_component_id, str)
            and isinstance(moving_component_id, str)
            and reference_component_id in candidates
            and moving_component_id in candidates
            and reference_component_id != moving_component_id
        ):
            anchor_coupled_pairs.add(tuple(sorted((reference_component_id, moving_component_id))))
    if anchor_semantics_list:
        for _pass_index in range(max(1, len(anchor_semantics_list))):
            moved_any = False
            for anchor in anchor_semantics_list:
                reference_component_id = anchor.get("reference_component_id")
                moving_component_id = anchor.get("moving_component_id")
                reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
                moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
                if reference_component_id not in candidates or moving_component_id not in candidates:
                    continue

                moving_root = _root_component_id(str(moving_component_id))
                reference_root = _root_component_id(str(reference_component_id))
                if moving_root == reference_root:
                    continue

                moving_members = _subtree_members(moving_root)
                if reference_component_id in moving_members:
                    continue

                reference_point = _anchor_world_point(
                    str(reference_component_id),
                    reference_anchor,
                    counterpart_id=str(moving_component_id),
                )
                moving_point = _anchor_world_point(
                    str(moving_component_id),
                    moving_anchor,
                    counterpart_id=str(reference_component_id),
                )
                if not isinstance(reference_point, Mapping) or not isinstance(moving_point, Mapping):
                    continue

                dx = float(reference_point.get("x", 0.0)) - float(moving_point.get("x", 0.0))
                dy = float(reference_point.get("y", 0.0)) - float(moving_point.get("y", 0.0))
                dz = float(reference_point.get("z", 0.0)) - float(moving_point.get("z", 0.0))
                if _anchor_requires_axis_only_alignment(anchor):
                    dz = 0.0

                orientation_policy = str(anchor.get("orientation_policy") or "preserve").strip().lower()
                desired_yaw: float | None = None
                if orientation_policy == "inherit_reference_yaw":
                    desired_yaw = float(yaw_by_cid.get(str(reference_component_id), yaw_by_cid.get(reference_root, 0.0)))
                elif orientation_policy == "radial_from_reference_center":
                    ref_center = placed.get(str(reference_component_id), {"x": 0.0, "y": 0.0, "z": 0.0})
                    vx = float(reference_point.get("x", 0.0)) - float(ref_center.get("x", 0.0))
                    vy = float(reference_point.get("y", 0.0)) - float(ref_center.get("y", 0.0))
                    if abs(vx) >= 1e-9 or abs(vy) >= 1e-9:
                        desired_yaw = float(math.degrees(math.atan2(vy, vx)))

                current_root_yaw = float(yaw_by_cid.get(moving_root, 0.0))
                translation_needed = abs(dx) > 1e-6 or abs(dy) > 1e-6 or abs(dz) > 1e-6
                yaw_needed = desired_yaw is not None and abs(float(desired_yaw) - current_root_yaw) > 1e-6
                if not translation_needed and not yaw_needed:
                    continue

                _apply_translation_to_members(moving_members, dx, dy, dz)
                if desired_yaw is not None:
                    for member in moving_members:
                        yaw_by_cid[member] = float(desired_yaw)

                anchor_adjustments.append(
                    {
                        "reference_component_id": str(reference_component_id),
                        "moving_component_id": str(moving_component_id),
                        "moving_root_component_id": moving_root,
                        "relation_type": str(anchor.get("relation_type") or "unknown"),
                        "delta_mm": {"x": dx, "y": dy, "z": dz},
                        "pass_index": int(_pass_index),
                    }
                )
                moved_any = True
            if not moved_any:
                break

    hub_slot_mount_offsets: List[Dict[str, Any]] = []
    outboard_support_offsets: List[Dict[str, Any]] = []
    placements_src = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
    arm_to_axle: Dict[str, str] = {}
    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            if str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "support_member_distal_attachment":
                continue
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if isinstance(arm_id, str) and isinstance(axle_id, str):
                arm_to_axle[arm_id] = axle_id

    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
            if support_topology != "hub_radial_slot_mount":
                continue
            hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            arm_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(hub_id, str) or not isinstance(arm_id, str):
                continue
            if hub_id not in placed or arm_id not in placed:
                continue
            hub_pos = placed.get(hub_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            arm_pos = placed.get(arm_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            vx = float(arm_pos.get("x", 0.0)) - float(hub_pos.get("x", 0.0))
            vy = float(arm_pos.get("y", 0.0)) - float(hub_pos.get("y", 0.0))
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
                phase_deg = ref_anchor.get("phase_deg")
                if isinstance(phase_deg, (int, float)):
                    ang = math.radians(float(phase_deg))
                    vx = math.cos(ang)
                    vy = math.sin(ang)
                else:
                    base = _rotate_xy(1.0, 0.0, float(yaw_by_cid.get(arm_id, 0.0)))
                    vx = float(base["x"])
                    vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                continue
            ux = vx / mag
            uy = vy / mag
            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
            insert_depth = moving_anchor.get("inset_mm")
            if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
                insert_depth = 12.0
            hub_radius = _component_radius_mm(hub_id)
            arm_length = _component_length_mm(arm_id)
            hub_thickness = _component_thickness_mm(hub_id)
            arm_thickness = _component_thickness_mm(arm_id)
            arm_dims = _component_dims(arm_id)
            desired_arm_x = float(hub_pos.get("x", 0.0)) + ux * (hub_radius + 0.5 * arm_length - float(insert_depth))
            desired_arm_y = float(hub_pos.get("y", 0.0)) + uy * (hub_radius + 0.5 * arm_length - float(insert_depth))
            if isinstance(arm_dims.get("root_web_thickness"), (int, float)) and float(arm_dims.get("root_web_thickness")) > 0.0:
                desired_arm_z = float(hub_pos.get("z", 0.0)) + (0.5 * hub_thickness)
            else:
                desired_arm_z = float(hub_pos.get("z", 0.0)) + max(0.0, 0.5 * (hub_thickness - arm_thickness))
            dx = desired_arm_x - float(arm_pos.get("x", 0.0))
            dy = desired_arm_y - float(arm_pos.get("y", 0.0))
            dz = desired_arm_z - float(arm_pos.get("z", 0.0))
            members = [arm_id]
            axle_id = arm_to_axle.get(arm_id)
            if isinstance(axle_id, str) and axle_id:
                members.append(axle_id)
                members.extend(_wheel_group_members_for_axle(axle_id))
            members = sorted(set(member for member in members if member in placed))
            if abs(dx) > 1e-6 or abs(dy) > 1e-6 or abs(dz) > 1e-6:
                _apply_translation_to_members(members, dx, dy, dz)
            yaw_by_cid[arm_id] = float(math.degrees(math.atan2(uy, ux)))
            hub_slot_mount_offsets.append(
                {
                    "hub_component_id": hub_id,
                    "arm_component_id": arm_id,
                    "insert_depth_mm": float(insert_depth),
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                    "yaw_deg": float(yaw_by_cid.get(arm_id, 0.0)),
                    "support_topology": support_topology,
                }
            )

    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
            axial_stack_policy = str(geometric_semantics.get("axial_stack_policy") or "").strip().lower()
            is_yoke = support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates"
            is_outboard = support_topology in {"outboard_single_shear", "distal_fork_dropout_support"} or axial_stack_policy == "wheel_body_outboard_of_support_plane"
            if not is_yoke and not is_outboard:
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(arm_id, str) or not isinstance(axle_id, str):
                continue
            if arm_id not in placed:
                continue
            current_members = [member_id for member_id in _wheel_group_members_for_axle(axle_id) if member_id in placed]
            if is_yoke:
                current_members = [axle_id] + [member_id for member_id in current_members if member_id != axle_id]
            if not current_members:
                continue
            arm_pos = placed.get(arm_id, {}) if isinstance(placed.get(arm_id), Mapping) else {}
            arm_x = float(arm_pos.get("x", 0.0))
            arm_y = float(arm_pos.get("y", 0.0))
            arm_z = float(arm_pos.get("z", 0.0))
            arm_dims = _component_dims(arm_id)
            arm_thickness = _component_thickness_mm(arm_id)
            wheel_width = _wheel_group_width_mm([member_id for member_id in current_members if member_id != axle_id])
            clearance_mm = 1.0
            mount_side = str(geometric_semantics.get("mount_side") or ("centered_z" if is_yoke else "positive_z")).strip().lower()
            arm_length = _component_length_mm(arm_id)
            ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
            inset_value = arm_dims.get("axle_inset_mm")
            if not isinstance(inset_value, (int, float)) or float(inset_value) <= 0.0:
                inset_value = ref_anchor.get("inset_mm")
            if not isinstance(inset_value, (int, float)) or float(inset_value) <= 0.0:
                inset_value = 12.0
            bore_local_x = max(0.0, 0.5 * float(arm_length) - float(inset_value))
            yaw_deg = yaw_by_cid.get(arm_id)
            if not isinstance(yaw_deg, (int, float)):
                axle_pos = placed.get(axle_id, {}) if isinstance(placed.get(axle_id), Mapping) else {}
                dx_guess = float(axle_pos.get("x", arm_x)) - arm_x
                dy_guess = float(axle_pos.get("y", arm_y)) - arm_y
                yaw_deg = math.degrees(math.atan2(dy_guess, dx_guess)) if abs(dx_guess) > 1e-9 or abs(dy_guess) > 1e-9 else 0.0
            yaw_rad = math.radians(float(yaw_deg))
            ux = math.cos(yaw_rad)
            uy = math.sin(yaw_rad)
            desired_x = arm_x + (ux * bore_local_x)
            desired_y = arm_y + (uy * bore_local_x)
            if is_yoke:
                plate_thickness_value = arm_dims.get("yoke_plate_thickness")
                gap_width_value = arm_dims.get("yoke_gap_width")
                plate_thickness = float(plate_thickness_value) if isinstance(plate_thickness_value, (int, float)) and float(plate_thickness_value) > 0.0 else max(3.0, 0.25 * arm_thickness)
                gap_width = float(gap_width_value) if isinstance(gap_width_value, (int, float)) and float(gap_width_value) > 0.0 else max(wheel_width + 2.0 * clearance_mm, 2.0 * plate_thickness)
                if str(arm_dims.get("yoke_profile_origin") or "").strip().lower() == "midplane":
                    desired_z = arm_z
                else:
                    desired_z = arm_z + plate_thickness + (0.5 * gap_width)
            else:
                sign = -1.0 if mount_side == "negative_z" else 1.0
                desired_z = arm_z + sign * (0.5 * arm_thickness + 0.5 * wheel_width + clearance_mm)
            axle_pos = placed.get(axle_id, {}) if isinstance(placed.get(axle_id), Mapping) else {}
            if axle_pos:
                current_x = float(axle_pos.get("x", desired_x))
                current_y = float(axle_pos.get("y", desired_y))
            else:
                current_x = sum(float(placed.get(member_id, {}).get("x", 0.0)) for member_id in current_members) / float(len(current_members))
                current_y = sum(float(placed.get(member_id, {}).get("y", 0.0)) for member_id in current_members) / float(len(current_members))
            current_z = sum(float(placed.get(member_id, {}).get("z", 0.0)) for member_id in current_members) / float(len(current_members))
            dx = desired_x - current_x
            dy = desired_y - current_y
            dz = desired_z - current_z
            if abs(dx) <= 1e-6 and abs(dy) <= 1e-6 and abs(dz) <= 1e-6:
                continue
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                _apply_translation_to_members(current_members, dx, dy, 0.0)
            if is_yoke:
                for member_id in current_members:
                    if member_id in placed:
                        placed[member_id]["z"] = float(desired_z)
            else:
                if abs(dz) > 1e-6:
                    _apply_translation_to_members(current_members, 0.0, 0.0, dz)
            outboard_support_offsets.append(
                {
                    "arm_component_id": arm_id,
                    "axle_component_id": axle_id,
                    "wheel_members": list(current_members),
                    "mount_side": mount_side,
                    "support_topology": support_topology or ("double_shear_yoke_support" if is_yoke else "distal_fork_dropout_support"),
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                }
            )

    rotating_stack_snaps: List[Dict[str, Any]] = []
    for axle_id in sorted(cid for cid in candidates if re.match(r"^wheel_\d+_axle$", cid, flags=re.IGNORECASE)):
        if axle_id not in placed:
            continue
        rotating_members = [member_id for member_id in _wheel_rotating_stack_members_for_axle(axle_id) if member_id in placed]
        if not rotating_members:
            continue
        shared_rotating_gid = f"rotating_stack::{axle_id}"
        allow_overlap_group_by_component[axle_id] = shared_rotating_gid
        for member_id in rotating_members:
            allow_overlap_group_by_component[member_id] = shared_rotating_gid
        axle_center = placed.get(axle_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        target_x = float(axle_center.get("x", 0.0))
        target_y = float(axle_center.get("y", 0.0))
        target_z = float(axle_center.get("z", 0.0))
        axle_yaw = float(yaw_by_cid.get(axle_id, 0.0))
        moved_members: List[Dict[str, Any]] = []
        for member_id in rotating_members:
            current = placed.get(member_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            dx = target_x - float(current.get("x", 0.0))
            dy = target_y - float(current.get("y", 0.0))
            dz = target_z - float(current.get("z", 0.0))
            if abs(dx) <= 1e-6 and abs(dy) <= 1e-6 and abs(dz) <= 1e-6:
                yaw_by_cid[member_id] = axle_yaw
                continue
            placed[member_id] = {"x": target_x, "y": target_y, "z": target_z}
            yaw_by_cid[member_id] = axle_yaw
            moved_members.append(
                {
                    "component_id": member_id,
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                }
            )
        if moved_members:
            rotating_stack_snaps.append(
                {
                    "axle_component_id": axle_id,
                    "target_mm": {"x": target_x, "y": target_y, "z": target_z},
                    "moved_members": moved_members,
                }
            )


    def _collect_fastener_bindings() -> Dict[str, Dict[str, Any]]:
        reqs_src = kg.get("connection_requirements")
        if not isinstance(reqs_src, list):
            return {}

        bindings: Dict[str, Dict[str, Any]] = {}
        for req in reqs_src:
            if not isinstance(req, Mapping):
                continue
            req_id = req.get("id")
            if not isinstance(req_id, str) or not req_id:
                continue
            base_req_id = _base_connection_id(req_id) or req_id
            between = [cid for cid in req.get("between", []) if isinstance(cid, str) and cid]
            decision = req.get("connection_decision") if isinstance(req.get("connection_decision"), Mapping) else {}
            semantics_req = req.get("connection_semantics") if isinstance(req.get("connection_semantics"), Mapping) else {}

            preferred_components: List[str] = []
            for key in ("reference_component_id", "moving_component_id"):
                cid = semantics_req.get(key)
                if isinstance(cid, str) and cid and cid not in preferred_components:
                    preferred_components.append(cid)

            fastener_ids: List[str] = []
            ref_fastener_id = decision.get("fastener_ref_component_id")
            if isinstance(ref_fastener_id, str) and ref_fastener_id:
                fastener_ids.append(ref_fastener_id)

            for cid in between:
                lowered = cid.lower()
                if cid in preferred_components or cid in fastener_ids:
                    continue
                if any(token in lowered for token in ("fastener", "bolt", "nut", "washer", "screw")):
                    fastener_ids.append(cid)
                    continue
                if cid not in preferred_components:
                    preferred_components.append(cid)

            for fastener_id in fastener_ids:
                if not isinstance(fastener_id, str) or not fastener_id:
                    continue
                bindings.setdefault(
                    fastener_id,
                    {
                        "connection_id": base_req_id,
                        "preferred_components": list(preferred_components),
                    },
                )

        return bindings

    def _placement_pattern_phase_rad(
        placement: Mapping[str, Any],
        reference_anchor: Mapping[str, Any],
        reference_component_id: str,
        moving_component_id: str | None,
    ) -> float | None:
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
        for key in ("start_angle_rad", "phase_rad"):
            value = pattern.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for key in ("start_angle", "phase_deg"):
            value = pattern.get(key)
            if isinstance(value, (int, float)):
                return math.radians(float(value))

        phase_rad_value = reference_anchor.get("phase_rad")
        if isinstance(phase_rad_value, (int, float)):
            return float(phase_rad_value)
        phase_deg_value = reference_anchor.get("phase_deg")
        if isinstance(phase_deg_value, (int, float)):
            return math.radians(float(phase_deg_value))

        if isinstance(moving_component_id, str) and moving_component_id in placed:
            ref_center = placed.get(reference_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            moving_center = placed.get(moving_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            vx = float(moving_center.get("x", 0.0)) - float(ref_center.get("x", 0.0))
            vy = float(moving_center.get("y", 0.0)) - float(ref_center.get("y", 0.0))
            if abs(vx) >= 1e-9 or abs(vy) >= 1e-9:
                return math.atan2(vy, vx)

        return math.radians(float(yaw_by_cid.get(reference_component_id, 0.0)))

    def _resolve_fastener_mount_z(
        *,
        placement: Mapping[str, Any],
        anchor: Mapping[str, Any],
        reference_component_id: str,
        reference_center: Mapping[str, Any],
        reference_anchor: Mapping[str, Any],
        default_z: float,
    ) -> float:
        relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        mechanism_name = str(placement.get("connection_mechanism") or anchor.get("connection_mechanism") or "").strip().lower()
        if relation_type != "axial_face_perimeter_mount" and mechanism_name != "axial_face_bolted_mount":
            return float(default_z)

        center_z = float(reference_center.get("z", 0.0))
        thickness = _component_thickness_mm(reference_component_id)
        half_thickness = 0.5 * thickness
        reference_kind = str(reference_anchor.get("kind") or "").strip().lower()
        if reference_kind.endswith("_min"):
            return center_z - half_thickness
        if reference_kind.endswith("_center") or reference_kind.endswith("_mid"):
            return center_z
        return center_z + half_thickness

    def _resolve_fastener_world_point(placement: Mapping[str, Any]) -> Dict[str, float] | None:
        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        reference_component_id = anchor.get("reference_component_id")
        moving_component_id = anchor.get("moving_component_id")
        if not isinstance(reference_component_id, str) or reference_component_id not in placed:
            return None

        reference_center = placed.get(reference_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}

        radius_mm: float | None = None
        for value in (
            pattern.get("pattern_radius_mm"),
            pattern.get("pattern_radius"),
            reference_anchor.get("radius_mm"),
        ):
            if isinstance(value, (int, float)) and float(value) > 0.0:
                radius_mm = float(value)
                break

        resolved: Dict[str, float] | None = None
        if isinstance(radius_mm, float) and radius_mm > 0.0:
            phase_rad = _placement_pattern_phase_rad(
                placement,
                reference_anchor,
                reference_component_id,
                moving_component_id if isinstance(moving_component_id, str) else None,
            )
            if not isinstance(phase_rad, (int, float)):
                return None
            resolved = {
                "x": float(reference_center.get("x", 0.0)) + radius_mm * math.cos(float(phase_rad)),
                "y": float(reference_center.get("y", 0.0)) + radius_mm * math.sin(float(phase_rad)),
                "z": float(reference_center.get("z", 0.0)),
            }
        else:
            point = _anchor_world_point(
                reference_component_id,
                reference_anchor,
                counterpart_id=moving_component_id if isinstance(moving_component_id, str) else None,
            )
            if not isinstance(point, Mapping):
                return None
            resolved = {
                "x": float(point.get("x", 0.0)),
                "y": float(point.get("y", 0.0)),
                "z": float(point.get("z", 0.0)),
            }

        resolved["z"] = _resolve_fastener_mount_z(
            placement=placement,
            anchor=anchor,
            reference_component_id=reference_component_id,
            reference_center=reference_center,
            reference_anchor=reference_anchor,
            default_z=float(resolved.get("z", 0.0)),
        )
        return resolved

    fastener_anchor_offsets: List[Dict[str, Any]] = []
    fastener_bindings = _collect_fastener_bindings()
    if fastener_bindings and isinstance(placements_src, list):
        placements_by_connection: Dict[str, List[Mapping[str, Any]]] = {}
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            base_connection_id = _base_connection_id(placement.get("connection_id"))
            if isinstance(base_connection_id, str) and base_connection_id:
                placements_by_connection.setdefault(base_connection_id, []).append(placement)

        def _placement_score(placement: Mapping[str, Any], binding: Mapping[str, Any]) -> int:
            score = 0
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}

            if isinstance(pattern.get("pattern_radius_mm"), (int, float)) or isinstance(pattern.get("pattern_radius"), (int, float)):
                score += 100
            if isinstance(interface_ref.get("component_id"), str) and interface_ref.get("component_id") == anchor.get("reference_component_id"):
                score += 40
            preferred_components = binding.get("preferred_components") if isinstance(binding.get("preferred_components"), list) else []
            if anchor.get("reference_component_id") in preferred_components:
                score += 20
            if str(placement.get("purpose") or "").strip().lower() == "fastening_mechanism":
                score += 10
            if "through_bolt" in str(geometric.get("hardware_layout") or "").strip().lower():
                score += 10
            return score

        for fastener_id, binding in sorted(fastener_bindings.items()):
            if fastener_id not in placed:
                continue
            connection_id = binding.get("connection_id")
            if not isinstance(connection_id, str) or not connection_id:
                continue
            placement_candidates = placements_by_connection.get(connection_id, [])
            if not placement_candidates:
                continue

            best_placement: Mapping[str, Any] | None = None
            best_score = -1
            for placement in placement_candidates:
                score = _placement_score(placement, binding)
                if score > best_score:
                    best_score = score
                    best_placement = placement
            if not isinstance(best_placement, Mapping):
                continue

            target_point = _resolve_fastener_world_point(best_placement)
            if not isinstance(target_point, Mapping):
                continue

            current_point = placed.get(fastener_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            anchor = best_placement.get("anchor_semantics") if isinstance(best_placement.get("anchor_semantics"), Mapping) else {}
            reference_component_id = anchor.get("reference_component_id")
            if isinstance(reference_component_id, str) and reference_component_id in yaw_by_cid:
                yaw_by_cid[fastener_id] = float(yaw_by_cid.get(reference_component_id, 0.0))
                synthetic_rigid_pairs.add(tuple(sorted((fastener_id, reference_component_id))))
                graph.setdefault(fastener_id, set()).add(reference_component_id)
                graph.setdefault(reference_component_id, set()).add(fastener_id)

            placed[fastener_id] = {
                "x": float(target_point.get("x", 0.0)),
                "y": float(target_point.get("y", 0.0)),
                "z": float(target_point.get("z", 0.0)),
            }
            fastener_anchor_offsets.append(
                {
                    "fastener_component_id": fastener_id,
                    "connection_id": connection_id,
                    "reference_component_id": reference_component_id,
                    "delta_mm": {
                        "x": float(target_point.get("x", 0.0)) - float(current_point.get("x", 0.0)),
                        "y": float(target_point.get("y", 0.0)) - float(current_point.get("y", 0.0)),
                        "z": float(target_point.get("z", 0.0)) - float(current_point.get("z", 0.0)),
                    },
                    "target_mm": dict(placed[fastener_id]),
                }
            )

    opposed_bearing_offsets: List[Dict[str, Any]] = []
    if isinstance(placements_src, list):
        host_to_bearings: Dict[str, Dict[str, str]] = {}
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "press_fit":
                continue
            anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            if str(anchor_semantics.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "bearing_outer_race_seat":
                continue
            host_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
            bearing_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
            if not isinstance(host_id, str) or not isinstance(bearing_id, str):
                continue
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            interface_name = str(interface_ref.get("name") or placement.get("seat_side") or "").strip().lower()
            side = "min" if interface_name.endswith("_min") or interface_name == "min" else ("max" if interface_name.endswith("_max") or interface_name == "max" else "")
            if side:
                host_to_bearings.setdefault(host_id, {})[bearing_id] = side

        for host_id, bearing_sides in host_to_bearings.items():
            if len(bearing_sides) < 2 or host_id not in placed:
                continue
            host_z = float(placed.get(host_id, {}).get("z", 0.0))
            host_dims = _component_dims(host_id)
            host_thickness = float(host_dims.get("thickness") or _component_thickness_mm(host_id))
            shoulder_mm = float(host_dims.get("opposed_bearing_shoulder") or 1.0)
            for bearing_id, side in bearing_sides.items():
                if bearing_id not in placed:
                    continue
                bearing_dims = _component_dims(bearing_id)
                bearing_width = float(bearing_dims.get("width") or bearing_dims.get("thickness") or 7.0)
                center_offset = max(0.0, 0.5 * host_thickness - 0.5 * bearing_width - shoulder_mm)
                desired_z = host_z + (-center_offset if side == "min" else center_offset)
                current = placed.get(bearing_id, {}) if isinstance(placed.get(bearing_id), Mapping) else {}
                current_z = float(current.get("z", host_z))
                dz = desired_z - current_z
                if abs(dz) <= 1e-6:
                    continue
                placed[bearing_id]["z"] = float(desired_z)
                opposed_bearing_offsets.append(
                    {
                        "host_component_id": host_id,
                        "bearing_component_id": bearing_id,
                        "seat_side": side,
                        "delta_z_mm": dz,
                    }
                )

    # -----------------
    # Placement groups
    # -----------------
    def _build_groups() -> List[Dict[str, Any]]:
        class_priority = {
            "rigid_cluster": 300,
            "coaxial_chain": 200,
            "free": 100,
        }
        # Build coaxial connected components first.
        coax_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        rigid_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        for a in candidates:
            for b in graph.get(a, set()):
                if b not in candidates or a == b:
                    continue
                k = _edge_kind(a, b)
                if k == "coaxial":
                    coax_adj[a].add(b)
                elif k == "rigid":
                    rigid_adj[a].add(b)

        groups: List[Dict[str, Any]] = []
        assigned: set[str] = set()

        def _cc(adj: Dict[str, set[str]]) -> List[List[str]]:
            comps: List[List[str]] = []
            seen: set[str] = set()
            for start in candidates:
                if start in seen:
                    continue
                stack = [start]
                cur: List[str] = []
                seen.add(start)
                while stack:
                    x = stack.pop()
                    cur.append(x)
                    for y in adj.get(x, set()):
                        if y in seen:
                            continue
                        seen.add(y)
                        stack.append(y)
                comps.append(sorted(cur))
            return comps

        for members in _cc(coax_adj):
            if len(members) < 2:
                continue
            # ---- Extend coaxial chain: include components whose
            # position_parent chain leads to a chain member.  This ensures
            # rim, tire, spacer etc. that are parented to a hub/axle in the
            # chain stay coaxial and don't get pushed away by overlap
            # resolution.
            chain_set = set(members)
            extended = True
            while extended:
                extended = False
                for cid in list(candidates):
                    if cid in chain_set:
                        continue
                    comp = comp_by_id.get(cid, {})
                    pp = comp.get("position_parent")
                    if isinstance(pp, str) and pp in chain_set:
                        chain_set.add(cid)
                        extended = True
            members = sorted(chain_set)
            for m in members:
                assigned.add(m)
            gid = f"coaxial_{members[0]}"
            groups.append(
                {
                    "group_id": gid,
                    "class": "coaxial_chain",
                    "members": members,
                    "primary_axis_world": [0.0, 0.0, 1.0],
                    "allow_overlap": True,
                    "priority": class_priority["coaxial_chain"],
                }
            )

        overlap_group_members: Dict[str, List[str]] = {}
        for cid in candidates:
            if cid in assigned:
                continue
            overlap_gid = allow_overlap_group_by_component.get(cid)
            if overlap_gid:
                overlap_group_members.setdefault(overlap_gid, []).append(cid)

        for _, members in sorted(overlap_group_members.items(), key=lambda item: item[0]):
            members = sorted(set(members))
            if len(members) < 2:
                continue
            for m in members:
                assigned.add(m)
            groups.append(
                {
                    "group_id": f"overlap::{members[0]}",
                    "class": "coaxial_chain",
                    "members": members,
                    "primary_axis_world": [0.0, 0.0, 1.0],
                    "allow_overlap": True,
                    "priority": class_priority["coaxial_chain"],
                }
            )

        remaining = [cid for cid in candidates if cid not in assigned]
        # Rigid clusters among remaining.
        if remaining:
            rigid_sub_adj = {cid: set([n for n in rigid_adj.get(cid, set()) if n in remaining]) for cid in remaining}
            seen2: set[str] = set()
            for start in sorted(remaining):
                if start in seen2:
                    continue
                stack = [start]
                seen2.add(start)
                members: List[str] = []
                while stack:
                    x = stack.pop()
                    members.append(x)
                    for y in rigid_sub_adj.get(x, set()):
                        if y in seen2:
                            continue
                        seen2.add(y)
                        stack.append(y)
                members = sorted(members)
                if len(members) >= 2:
                    for m in members:
                        assigned.add(m)
                    gid = f"rigid_{members[0]}"
                    groups.append(
                        {
                            "group_id": gid,
                            "class": "rigid_cluster",
                            "members": members,
                            "allow_overlap": False,
                            "priority": class_priority["rigid_cluster"],
                        }
                    )

        # Free singletons.
        for cid in sorted(candidates):
            if cid in assigned:
                continue
            groups.append(
                {
                    "group_id": f"free_{cid}",
                    "class": "free",
                    "members": [cid],
                    "allow_overlap": False,
                    "priority": class_priority["free"],
                }
            )
        return groups

    placement_groups = _build_groups()

    # -----------------
    # Group-based overlap resolution
    # -----------------
    before_pos = {cid: dict(placed.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})) for cid in candidates}
    after_pos = {cid: dict(before_pos[cid]) for cid in candidates}

    def _aabb_minmax(center: Dict[str, float], size: tuple[float, float, float]) -> Dict[str, float]:
        cx, cy, cz = float(center.get("x", 0.0)), float(center.get("y", 0.0)), float(center.get("z", 0.0))
        sx, sy, sz = size
        return {
            "min_x": cx - sx / 2.0,
            "max_x": cx + sx / 2.0,
            "min_y": cy - sy / 2.0,
            "max_y": cy + sy / 2.0,
            "min_z": cz - sz / 2.0,
            "max_z": cz + sz / 2.0,
        }

    def _merge_minmax(mm_list: List[Dict[str, float]]) -> Dict[str, float]:
        out = dict(mm_list[0])
        for mm in mm_list[1:]:
            out["min_x"] = min(out["min_x"], mm["min_x"])
            out["max_x"] = max(out["max_x"], mm["max_x"])
            out["min_y"] = min(out["min_y"], mm["min_y"])
            out["max_y"] = max(out["max_y"], mm["max_y"])
            out["min_z"] = min(out["min_z"], mm["min_z"])
            out["max_z"] = max(out["max_z"], mm["max_z"])
        return out

    def _group_aabb(g: Mapping[str, Any]) -> Dict[str, float]:
        mms: List[Dict[str, float]] = []
        for cid in g.get("members", []) or []:
            if cid not in after_pos:
                continue
            mms.append(_aabb_minmax(after_pos[cid], sizes.get(cid, (30.0, 30.0, 30.0))))
        if not mms:
            return {"min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0, "min_z": 0.0, "max_z": 0.0}
        return _merge_minmax(mms)

    def _minmax_overlaps(a: Mapping[str, float], b: Mapping[str, float], *, margin: float) -> bool:
        if float(a["max_x"]) + margin <= float(b["min_x"]) or float(b["max_x"]) + margin <= float(a["min_x"]):
            return False
        if float(a["max_y"]) + margin <= float(b["min_y"]) or float(b["max_y"]) + margin <= float(a["min_y"]):
            return False
        if float(a["max_z"]) + margin <= float(b["min_z"]) or float(b["max_z"]) + margin <= float(a["min_z"]):
            return False
        return True

    def _center_from_minmax(mm: Mapping[str, float]) -> Dict[str, float]:
        return {
            "x": 0.5 * (float(mm["min_x"]) + float(mm["max_x"])),
            "y": 0.5 * (float(mm["min_y"]) + float(mm["max_y"])),
            "z": 0.5 * (float(mm["min_z"]) + float(mm["max_z"])),
        }

    def _apply_group_translation(g: Mapping[str, Any], vec: Dict[str, float]) -> None:
        for cid in g.get("members", []) or []:
            if cid not in after_pos:
                continue
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)) + float(vec.get("x", 0.0)),
                "y": float(after_pos[cid].get("y", 0.0)) + float(vec.get("y", 0.0)),
                "z": float(after_pos[cid].get("z", 0.0)) + float(vec.get("z", 0.0)),
            }

    # Stage A: group-internal handling (do NOT push coaxial members in X/Y)
    axial_jitters: List[Dict[str, Any]] = []
    for g in placement_groups:
        if g.get("class") != "coaxial_chain":
            continue
        if bool(g.get("allow_overlap")):
            continue
        axis = g.get("primary_axis_world")
        if not (isinstance(axis, list) and len(axis) == 3):
            axis = [0.0, 0.0, 1.0]
        ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
        # Only support axis-aligned jitter for now.
        if abs(az) < 0.9:
            continue
        members = [m for m in (g.get("members") or []) if isinstance(m, str) and m in after_pos]
        z_seen: Dict[float, int] = {}
        for m in members:
            z = float(after_pos[m].get("z", 0.0))
            key = round(z, 6)
            z_seen[key] = z_seen.get(key, 0) + 1
        if all(v <= 1 for v in z_seen.values()):
            continue
        # Apply small +/- jitter in Z to break exact co-planarity.
        for i, m in enumerate(sorted(members)):
            if m == grounded:
                continue
            dz = (1.0 if (i % 2 == 0) else -1.0) * float((i // 2) + 1)
            _apply_group_translation({"members": [m]}, {"x": 0.0, "y": 0.0, "z": dz})
            axial_jitters.append({"component_id": m, "delta_mm": {"x": 0.0, "y": 0.0, "z": dz}})

    # Stage B: group-level separation only (translate whole groups)
    group_by_id = {str(g.get("group_id")): g for g in placement_groups if isinstance(g, Mapping) and g.get("group_id")}
    grounded_groups: set[str] = set()
    for gid, g in group_by_id.items():
        members = g.get("members") or []
        if isinstance(members, list) and grounded in members:
            grounded_groups.add(gid)
    applied_translations: List[Dict[str, Any]] = []
    conflict_resolutions: List[Dict[str, Any]] = []
    invalidated_assumptions: Dict[str, Dict[str, Any]] = {}

    def _priority_of(g: Mapping[str, Any]) -> int:
        p = g.get("priority")
        if isinstance(p, int):
            return p
        cls = g.get("class") if isinstance(g.get("class"), str) else "free"
        if cls == "rigid_cluster":
            return 300
        if cls == "coaxial_chain":
            return 200
        return 100

    def _groups_directly_structurally_coupled(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
        m1 = [cid for cid in (g1.get("members") or []) if isinstance(cid, str)]
        m2 = [cid for cid in (g2.get("members") or []) if isinstance(cid, str)]
        if not m1 or not m2:
            return False

        # If there is any rigid or anchor-coupled edge between groups, they belong to the same semantic support cluster.
        for a in m1:
            for b in m2:
                if a == b:
                    continue
                if _edge_kind(a, b) == "rigid":
                    return True
                if tuple(sorted((a, b))) in anchor_coupled_pairs:
                    return True
        return False

    def _build_structural_group_clusters() -> Dict[str, str]:
        adjacency: Dict[str, set[str]] = {gid: set() for gid in group_by_id}
        gids_local = sorted(adjacency.keys())
        for i in range(len(gids_local)):
            gid_a = gids_local[i]
            ga = group_by_id[gid_a]
            for j in range(i + 1, len(gids_local)):
                gid_b = gids_local[j]
                gb = group_by_id[gid_b]
                if not _groups_directly_structurally_coupled(ga, gb):
                    continue
                adjacency[gid_a].add(gid_b)
                adjacency[gid_b].add(gid_a)

        cluster_by_gid: Dict[str, str] = {}
        seen: set[str] = set()
        cluster_index = 0
        for start_gid in gids_local:
            if start_gid in seen:
                continue
            stack = [start_gid]
            seen.add(start_gid)
            members: List[str] = []
            while stack:
                current_gid = stack.pop()
                members.append(current_gid)
                for neighbor_gid in sorted(adjacency.get(current_gid, set())):
                    if neighbor_gid in seen:
                        continue
                    seen.add(neighbor_gid)
                    stack.append(neighbor_gid)
            cluster_id = f"structural_cluster_{cluster_index}"
            for member_gid in members:
                cluster_by_gid[member_gid] = cluster_id
            cluster_index += 1
        return cluster_by_gid

    structural_cluster_by_group = _build_structural_group_clusters()

    def _groups_structurally_coupled(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
        gid1 = str(g1.get("group_id")) if g1.get("group_id") else ""
        gid2 = str(g2.get("group_id")) if g2.get("group_id") else ""
        if not gid1 or not gid2:
            return False
        if gid1 == gid2:
            return True
        cluster1 = structural_cluster_by_group.get(gid1)
        cluster2 = structural_cluster_by_group.get(gid2)
        return isinstance(cluster1, str) and cluster1 == cluster2

    def _choose_movable(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
        gid1 = str(g1.get("group_id"))
        gid2 = str(g2.get("group_id"))
        if gid1 in grounded_groups and gid2 not in grounded_groups:
            return g2, "grounded_group_pinned"
        if gid2 in grounded_groups and gid1 not in grounded_groups:
            return g1, "grounded_group_pinned"

        p1 = _priority_of(g1)
        p2 = _priority_of(g2)
        if p1 > p2:
            return g2, "lower_priority_group_moves"
        if p2 > p1:
            return g1, "lower_priority_group_moves"

        # Prefer moving non-coaxial groups away from coaxial chains.
        a_overlap = bool(g1.get("allow_overlap"))
        b_overlap = bool(g2.get("allow_overlap"))
        if a_overlap and not b_overlap:
            return g2, "coaxial_anchor_preserved"
        if b_overlap and not a_overlap:
            return g1, "coaxial_anchor_preserved"
        # Otherwise deterministic: move lexicographically later group_id
        return (g2, "lexicographic_tie_break") if gid2 >= gid1 else (g1, "lexicographic_tie_break")

    def _compute_push(static_mm: Mapping[str, float], move_mm: Mapping[str, float], *, prefer_xy: bool) -> Dict[str, float]:
        axes = ["x", "y", "z"] if not prefer_xy else ["x", "y", "z"]
        # prefer_xy currently means: try X/Y first (already ordered).
        s_center = _center_from_minmax(static_mm)
        m_center = _center_from_minmax(move_mm)

        best_vec: Dict[str, float] | None = None
        best_mag = float("inf")
        for axname in axes:
            if axname == "x":
                if float(m_center["x"]) >= float(s_center["x"]):
                    delta = (float(static_mm["max_x"]) + float(margin_mm)) - float(move_mm["min_x"])
                else:
                    delta = (float(static_mm["min_x"]) - float(margin_mm)) - float(move_mm["max_x"])
                vec = {"x": float(delta), "y": 0.0, "z": 0.0}
                mag = abs(float(delta))
            elif axname == "y":
                if float(m_center["y"]) >= float(s_center["y"]):
                    delta = (float(static_mm["max_y"]) + float(margin_mm)) - float(move_mm["min_y"])
                else:
                    delta = (float(static_mm["min_y"]) - float(margin_mm)) - float(move_mm["max_y"])
                vec = {"x": 0.0, "y": float(delta), "z": 0.0}
                mag = abs(float(delta))
            else:
                if float(m_center["z"]) >= float(s_center["z"]):
                    delta = (float(static_mm["max_z"]) + float(margin_mm)) - float(move_mm["min_z"])
                else:
                    delta = (float(static_mm["min_z"]) - float(margin_mm)) - float(move_mm["max_z"])
                vec = {"x": 0.0, "y": 0.0, "z": float(delta)}
                mag = abs(float(delta))

            if mag < best_mag:
                best_mag = mag
                best_vec = vec

        return best_vec or {"x": float(margin_mm), "y": 0.0, "z": 0.0}

    # Iteratively resolve group overlaps.
    for _ in range(200):
        any_moved = False
        group_aabbs = {gid: _group_aabb(g) for gid, g in group_by_id.items()}
        gids = sorted(group_aabbs.keys())
        for i in range(len(gids)):
            for j in range(i + 1, len(gids)):
                ga = group_by_id[gids[i]]
                gb = group_by_id[gids[j]]
                a_mm = group_aabbs[gids[i]]
                b_mm = group_aabbs[gids[j]]
                if not _minmax_overlaps(a_mm, b_mm, margin=float(margin_mm)):
                    continue

                if _groups_structurally_coupled(ga, gb):
                    conflict_resolutions.append(
                        {
                            "group_a": str(ga.get("group_id")),
                            "group_b": str(gb.get("group_id")),
                            "moved_group_id": None,
                            "preserved_group_id": None,
                            "moved_group_class": None,
                            "preserved_group_class": None,
                            "moved_group_priority": None,
                            "preserved_group_priority": None,
                            "decision_reason": "structurally_coupled_groups_overlap_allowed",
                            "delta_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
                        }
                    )
                    continue

                movable, decision_reason = _choose_movable(ga, gb)
                static = gb if movable is ga else ga
                movable_id = str(movable.get("group_id"))
                static_id = str(static.get("group_id"))

                prefer_xy = (movable.get("class") == "coaxial_chain") or (static.get("class") == "coaxial_chain")
                static_mm = group_aabbs[static_id]
                move_mm = group_aabbs[movable_id]
                vec = _compute_push(static_mm, move_mm, prefer_xy=prefer_xy)
                _apply_group_translation(movable, vec)
                applied_translations.append(
                    {
                        "moved_group_id": movable_id,
                        "static_group_id": static_id,
                        "delta_mm": vec,
                        "decision_reason": decision_reason,
                    }
                )
                movable_priority = _priority_of(movable)
                static_priority = _priority_of(static)
                conflict_resolutions.append(
                    {
                        "group_a": str(ga.get("group_id")),
                        "group_b": str(gb.get("group_id")),
                        "moved_group_id": movable_id,
                        "preserved_group_id": static_id,
                        "moved_group_class": movable.get("class"),
                        "preserved_group_class": static.get("class"),
                        "moved_group_priority": movable_priority,
                        "preserved_group_priority": static_priority,
                        "decision_reason": decision_reason,
                        "delta_mm": vec,
                    }
                )
                if static_priority > movable_priority:
                    invalidated_assumptions[movable_id] = {
                        "group_id": movable_id,
                        "constraint_status": "relaxed_due_conflict",
                        "sacrificed_to": static_id,
                        "decision_reason": decision_reason,
                        "group_priority": movable_priority,
                        "counterparty_priority": static_priority,
                    }
                any_moved = True
                # Recompute in next outer iteration.
                break
            if any_moved:
                break
        if not any_moved:
            break

    # Deterministic de-dup pass: if multiple components share the same rounded translation,
    # jitter later IDs along +Y to guarantee non-overlapping initial placements.
    dedup_jitters: List[Dict[str, Any]] = []
    bucket_to_ids: Dict[tuple[float, float, float], List[str]] = {}
    for cid in sorted(candidates):
        pos = after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})
        key = (
            round(float(pos.get("x", 0.0)), 3),
            round(float(pos.get("y", 0.0)), 3),
            round(float(pos.get("z", 0.0)), 3),
        )
        bucket_to_ids.setdefault(key, []).append(cid)

    dedup_step = max(10.0, float(margin_mm) + 5.0)

    def _bucket_is_intentionally_coupled(ids: List[str]) -> bool:
        if len(ids) <= 1:
            return False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = ids[i]
                b = ids[j]
                if tuple(sorted((a, b))) in anchor_coupled_pairs:
                    continue
                if _edge_kind(a, b) == "rigid" and _is_hierarchy_overlap_candidate(a) and _is_hierarchy_overlap_candidate(b):
                    continue
                return False
        return True

    for key in sorted(bucket_to_ids.keys()):
        ids = sorted(bucket_to_ids[key])
        if len(ids) <= 1:
            continue
        if _bucket_is_intentionally_coupled(ids):
            continue
        protected_ids = [cid for cid in ids if allow_overlap_group_by_component.get(cid)]
        if protected_ids:
            shared_gid = allow_overlap_group_by_component.get(protected_ids[0])
            if shared_gid and all(allow_overlap_group_by_component.get(cid) == shared_gid for cid in ids):
                continue
        if grounded in ids or protected_ids:
            movable_ids = [cid for cid in ids if cid != grounded and cid not in protected_ids]
            for k, cid in enumerate(movable_ids, start=1):
                delta_y = float(k) * dedup_step
                after_pos[cid] = {
                    "x": float(after_pos[cid].get("x", 0.0)),
                    "y": float(after_pos[cid].get("y", 0.0)) + delta_y,
                    "z": float(after_pos[cid].get("z", 0.0)),
                }
                dedup_jitters.append(
                    {
                        "component_id": cid,
                        "bucket_key": key,
                        "delta_mm": {"x": 0.0, "y": delta_y, "z": 0.0},
                    }
                )
            continue
        for k, cid in enumerate(ids):
            if k == 0:
                continue
            delta_y = float(k) * dedup_step
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)),
                "y": float(after_pos[cid].get("y", 0.0)) + delta_y,
                "z": float(after_pos[cid].get("z", 0.0)),
            }
            dedup_jitters.append(
                {
                    "component_id": cid,
                    "bucket_key": key,
                    "delta_mm": {"x": 0.0, "y": delta_y, "z": 0.0},
                }
            )

    # Final normalization: keep grounded component at origin for deterministic global frame.
    grounded_pos = after_pos.get(grounded, {"x": 0.0, "y": 0.0, "z": 0.0})
    norm_offset = {
        "x": float(grounded_pos.get("x", 0.0)),
        "y": float(grounded_pos.get("y", 0.0)),
        "z": float(grounded_pos.get("z", 0.0)),
    }
    if abs(norm_offset["x"]) > 1e-9 or abs(norm_offset["y"]) > 1e-9 or abs(norm_offset["z"]) > 1e-9:
        for cid in candidates:
            if cid not in after_pos:
                continue
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)) - norm_offset["x"],
                "y": float(after_pos[cid].get("y", 0.0)) - norm_offset["y"],
                "z": float(after_pos[cid].get("z", 0.0)) - norm_offset["z"],
            }

    # Collect final conflicts for diagnostics.
    final_conflicts: List[Dict[str, Any]] = []
    group_aabbs = {gid: _group_aabb(g) for gid, g in group_by_id.items()}
    gids = sorted(group_aabbs.keys())
    for i in range(len(gids)):
        for j in range(i + 1, len(gids)):
            ga = group_by_id[gids[i]]
            gb = group_by_id[gids[j]]
            if _groups_structurally_coupled(ga, gb):
                continue
            a_mm = group_aabbs[gids[i]]
            b_mm = group_aabbs[gids[j]]
            if _minmax_overlaps(a_mm, b_mm, margin=float(margin_mm)):
                final_conflicts.append({"group_a": gids[i], "group_b": gids[j]})

    # Invariants: coaxial members must not be sheared (xy delta must be uniform within group).
    coaxial_invariants: List[Dict[str, Any]] = []
    for g in placement_groups:
        if g.get("class") != "coaxial_chain":
            continue
        members = [m for m in (g.get("members") or []) if isinstance(m, str) and m in before_pos and m in after_pos]
        deltas = set()
        for m in members:
            dx = float(after_pos[m]["x"]) - float(before_pos[m]["x"])
            dy = float(after_pos[m]["y"]) - float(before_pos[m]["y"])
            deltas.add((round(dx, 9), round(dy, 9)))
        coaxial_invariants.append(
            {
                "group_id": g.get("group_id"),
                "xy_translation_unique_count": len(deltas),
                "ok_uniform_xy_translation": len(deltas) <= 1,
            }
        )

    initial_placements: List[Dict[str, Any]] = []
    for cid in candidates:
        pos = after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})
        yaw = float(yaw_by_cid.get(cid, 0.0))
        parent_comp = comp_by_id.get(cid, {}).get("position_parent")
        parent_assembly = parent_comp if isinstance(parent_comp, str) and parent_comp in candidate_set else "root"
        initial_placements.append(
            {
                "component_id": cid,
                "occurrence_name": cid,
                "parent_assembly": parent_assembly,
                "transform": {
                    "translation": {
                        "x": float(pos.get("x", 0.0)),
                        "y": float(pos.get("y", 0.0)),
                        "z": float(pos.get("z", 0.0)),
                    },
                    "rotation_rpy_deg": {"roll": 0.0, "pitch": 0.0, "yaw": yaw},
                },
                "ground": bool(cid == grounded),
                "orientation_unknown": bool(orientation_unknown.get(cid, False)),
            }
        )

    placement_groups_out: List[Dict[str, Any]] = []
    for g in placement_groups:
        g_out = dict(g) if isinstance(g, Mapping) else {}
        gid = g_out.get("group_id") if isinstance(g_out.get("group_id"), str) else None
        if isinstance(gid, str) and gid in invalidated_assumptions:
            g_out["constraint_status"] = "relaxed_due_conflict"
            g_out["constraint_relaxation"] = dict(invalidated_assumptions[gid])
        else:
            g_out["constraint_status"] = "active"
        placement_groups_out.append(g_out)

    return {
        "initial_placements": initial_placements,
        "placement_groups": placement_groups_out,
        "diagnostics": {
            "before": [
                {
                    "component_id": cid,
                    "translation_mm": dict(before_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})),
                }
                for cid in candidates
            ],
            "after": [
                {
                    "component_id": cid,
                    "translation_mm": dict(after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})),
                    "yaw_deg": float(yaw_by_cid.get(cid, 0.0)),
                }
                for cid in candidates
            ],
            "group_conflicts": final_conflicts,
            "conflict_resolutions": conflict_resolutions,
            "invalidated_assumptions": [
                dict(v) for _, v in sorted(invalidated_assumptions.items(), key=lambda item: item[0])
            ],
            "applied_group_translations": applied_translations,
            "axial_jitters": axial_jitters,
            "anchor_adjustments": anchor_adjustments,
            "hub_slot_mount_offsets": hub_slot_mount_offsets,
            "outboard_support_offsets": outboard_support_offsets,
            "rotating_stack_snaps": rotating_stack_snaps,
            "fastener_anchor_offsets": fastener_anchor_offsets,
            "opposed_bearing_offsets": opposed_bearing_offsets,
            "dedup_jitters": dedup_jitters,
            "coaxial_invariants": coaxial_invariants,
            "normalization_offset_mm": norm_offset,
            "grounded_groups": sorted(grounded_groups),
            "structural_group_clusters": [
                {"group_id": gid, "cluster_id": structural_cluster_by_group.get(gid)}
                for gid in sorted(structural_cluster_by_group.keys())
            ],
        },
        "summary": {
            "strategy": "preassembly_graph_bfs_v2",
            "component_count": len(candidates),
            "ground_component_id": grounded,
            "requested_ground_component_id": requested_ground,
            "ground_override_applied": applied_override,
            "anchor_semantics_count": len(anchor_semantics_list),
            "margin_mm": float(margin_mm),
        },
    }



def _sync_axisymmetric_bearing_profile_params(parts: List[Dict[str, Any]]) -> None:
    for part_record in parts:
        if not isinstance(part_record, dict):
            continue
        strategy = part_record.get("modeling_strategy") if isinstance(part_record.get("modeling_strategy"), dict) else None
        if not isinstance(strategy, dict):
            continue
        profile_type = str(strategy.get("profile_type") or "").strip().lower()
        construction_method = str(strategy.get("construction_method") or strategy.get("primary_method") or "").strip().lower()
        if profile_type != "half_profile" and construction_method != "revolve":
            continue
        features = part_record.get("features") if isinstance(part_record.get("features"), list) else []
        seat_sides = set()
        seat_diameters: List[float] = []
        seat_depths: List[float] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            if str(feature.get("feature_type") or "").strip().lower() != "bearing_seat":
                continue
            interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), dict) else {}
            interface_name = str(interface_ref.get("name") or "").strip().lower()
            if interface_name.endswith("_min"):
                seat_sides.add("min")
            elif interface_name.endswith("_max"):
                seat_sides.add("max")
            geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), dict) else {}
            seat_diameter = geometry_parameters.get("bore_diameter")
            seat_depth = geometry_parameters.get("depth")
            if isinstance(seat_diameter, (int, float)) and float(seat_diameter) > 0.0:
                seat_diameters.append(float(seat_diameter))
            if isinstance(seat_depth, (int, float)) and float(seat_depth) > 0.0:
                seat_depths.append(float(seat_depth))
        if seat_sides == {"min", "max"} and seat_diameters and seat_depths:
            params = strategy.get("parameter_values") if isinstance(strategy.get("parameter_values"), dict) else {}
            params["opposed_bearing_seat_diameter"] = float(max(seat_diameters))
            params["opposed_bearing_seat_depth"] = float(max(seat_depths))
            strategy["parameter_values"] = params


def _rewrite_yoke_support_shaft_bore_features(parts: List[Dict[str, Any]]) -> None:
    for part_record in parts:
        if not isinstance(part_record, dict):
            continue
        strategy = part_record.get("modeling_strategy") if isinstance(part_record.get("modeling_strategy"), dict) else None
        if not isinstance(strategy, dict):
            continue
        if str(strategy.get("profile_type") or "").strip().lower() != "yoke_profile":
            continue
        params = strategy.get("parameter_values") if isinstance(strategy.get("parameter_values"), dict) else {}
        length = float(params.get("length") or 60.0)
        axle_inset = float(params.get("axle_inset_mm") or 12.0)
        plate_thickness = float(params.get("yoke_plate_thickness") or 3.0)
        gap_width = float(params.get("yoke_gap_width") or 10.0)
        seed_x = round(max(0.0, (0.5 * length) - axle_inset), 4)
        seed_z = 0.0
        for feature in part_record.get("features", []) if isinstance(part_record.get("features"), list) else []:
            if not isinstance(feature, dict):
                continue
            if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
                continue
            interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
            interface_ref["name"] = "axial_end_face_max"
            interface_ref["component_id"] = part_record.get("component_id")
            feature["interface_ref"] = interface_ref
            anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
            anchor["face_interface_id"] = "axial_end_face_max"
            anchor["side_hint"] = "MAX"
            anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
            feature["anchor"] = anchor
            geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
            geometry_parameters["face_interface_id"] = "axial_end_face_max"
            nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
            nested_anchor["face_interface_id"] = "axial_end_face_max"
            nested_anchor["side_hint"] = "MAX"
            nested_anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
            geometry_parameters["anchor"] = nested_anchor
            feature["geometry_parameters"] = geometry_parameters
            feature["seed_point_mm"] = {"x": seed_x, "y": 0.0, "z": seed_z}
            instances = feature.get("instances") if isinstance(feature.get("instances"), list) else []
            for instance in instances:
                if isinstance(instance, dict):
                    instance["position"] = {"x": seed_x, "y": 0.0, "z": seed_z}


def _project_hub_radial_slot_geometry(
    realization: Mapping[str, Any],
    initial_placements: List[Dict[str, Any]],
) -> None:
    component_realizations = realization.get("component_realizations")
    if not isinstance(component_realizations, list) or not isinstance(initial_placements, list):
        return

    realization_by_id: Dict[str, Dict[str, Any]] = {}
    for item in component_realizations:
        if isinstance(item, dict) and isinstance(item.get("component_id"), str):
            realization_by_id[str(item.get("component_id"))] = item

    placement_by_id: Dict[str, Dict[str, float]] = {}
    for item in initial_placements:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        transform = item.get("transform") if isinstance(item.get("transform"), Mapping) else {}
        translation = transform.get("translation") if isinstance(transform.get("translation"), Mapping) else {}
        if isinstance(cid, str):
            placement_by_id[cid] = {
                "x": float(translation.get("x", 0.0)),
                "y": float(translation.get("y", 0.0)),
                "z": float(translation.get("z", 0.0)),
            }

    for component_id, item in realization_by_id.items():
        strategy = item.get("modeling_strategy") if isinstance(item.get("modeling_strategy"), dict) else None
        if not isinstance(strategy, dict):
            continue
        params = dict(strategy.get("parameter_values") or {})
        slot_specs = params.pop("radial_slot_specs", None)
        if not isinstance(slot_specs, list) or not slot_specs:
            strategy["parameter_values"] = params
            continue
        hub_pos = placement_by_id.get(component_id)
        if not isinstance(hub_pos, dict):
            strategy["parameter_values"] = params
            continue
        radial_slots_by_arm: Dict[str, Dict[str, Any]] = {}
        for spec in slot_specs:
            if not isinstance(spec, Mapping):
                continue
            arm_id = spec.get("arm_id") if isinstance(spec.get("arm_id"), str) else None
            arm_pos = placement_by_id.get(arm_id) if isinstance(arm_id, str) else None
            if not isinstance(arm_id, str) or not arm_id or not isinstance(arm_pos, dict):
                continue
            vx = float(arm_pos.get("x", 0.0)) - float(hub_pos.get("x", 0.0))
            vy = float(arm_pos.get("y", 0.0)) - float(hub_pos.get("y", 0.0))
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                continue
            angle_deg = round(math.degrees(math.atan2(vy, vx)), 4)
            merged_slot = radial_slots_by_arm.get(arm_id, {
                "arm_id": arm_id,
                "angle_deg": angle_deg,
                "slot_width": 0.0,
                "slot_depth": 0.0,
                "slot_height": 0.0,
                "insert_depth": 0.0,
            })
            merged_slot["angle_deg"] = angle_deg
            merged_slot["slot_width"] = max(float(merged_slot.get("slot_width") or 0.0), float(spec.get("slot_width") or 0.0))
            merged_slot["slot_depth"] = max(float(merged_slot.get("slot_depth") or 0.0), float(spec.get("slot_depth") or 0.0))
            merged_slot["slot_height"] = max(float(merged_slot.get("slot_height") or 0.0), float(spec.get("slot_height") or 0.0))
            merged_slot["insert_depth"] = max(float(merged_slot.get("insert_depth") or 0.0), float(spec.get("insert_depth") or 0.0))
            radial_slots_by_arm[arm_id] = merged_slot
        radial_slots = list(radial_slots_by_arm.values())
        if radial_slots:
            params["radial_slots"] = radial_slots
        strategy["parameter_values"] = params

def run(
    *,
    run_dir: Path,
    round_index: int
) -> Dict[str, Any]:
    """
    Plan shape realization strategies.
    
    Args:
        run_dir: Run directory
        round_index: Planning round number
    
    Returns:
        Dict with output path
    """
    semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    
    if not semantics_path.exists():
        raise FileNotFoundError(f"Geometry semantics not found: {semantics_path}")
    if not kg_path.exists():
        raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
    
    # Load inputs
    semantics = _read_json(semantics_path)
    kg = _read_json(kg_path)
    
    # Plan
    function_registry = _load_function_registry()
    planner = ShapeRealizationPlanner(kg, function_registry=function_registry)
    realization = planner.plan(semantics)

    # Infer layout positions (deterministic + LLM)
    layout_plan = _infer_layout_positions(kg)
    layout_positions = layout_plan.get("layout_positions", {})
    if not isinstance(layout_positions, dict):
        layout_positions = {}

    feature_map = _build_part_feature_map(
        semantics=semantics,
        kg=kg,
        layout_positions=layout_positions,
    )

    anchor_errors = feature_map.pop("__anchor_errors__", []) if isinstance(feature_map, dict) else []
    if isinstance(anchor_errors, list) and anchor_errors:
        error_path = run_dir / "planning" / "errors" / "shape_realization_missing_anchor.json"
        _write_json(
            error_path,
            {
                "metadata": {
                    "source": "Agent3a_shape_realization_planner",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                "errors": anchor_errors,
            },
        )
        raise ValueError(
            f"Hole anchoring contract violated. See: planning/errors/{error_path.name}"
        )

    hole_arbitration = feature_map.pop("__hole_arbitration__", {}) if isinstance(feature_map, dict) else {}
    thread_warnings = feature_map.pop("__thread_warnings__", []) if isinstance(feature_map, dict) else []

    component_realizations = realization.get("component_realizations")
    if not isinstance(component_realizations, list):
        component_realizations = []

    component_type_by_id: Dict[str, str] = {}
    for comp in kg.get("components", []) if isinstance(kg.get("components"), list) else []:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and cid and isinstance(ctype, str):
            component_type_by_id[cid] = ctype

    parts: List[Dict[str, Any]] = []
    for item in component_realizations:
        if not isinstance(item, dict):
            continue
        component_id = item.get("component_id")
        strategy = item.get("modeling_strategy")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(strategy, dict):
            continue
        primary_method = strategy.get("primary_method")
        if not isinstance(primary_method, str) or not primary_method:
            construction_method = strategy.get("construction_method")
            if isinstance(construction_method, str) and construction_method:
                primary_method = construction_method.upper()
            else:
                primary_method = "EXTRUDE"

        coordinate_frame = _build_coordinate_frame(
            component_id=component_id,
            layout_positions=layout_positions,
        )
        origin_raw = coordinate_frame.get("origin_mm")
        origin_mm = origin_raw if isinstance(origin_raw, dict) else {}

        realization_features = item.get("features") if isinstance(item.get("features"), list) else None
        if realization_features is None:
            selected_features = feature_map.get(component_id, [])
        else:
            selected_features = realization_features

        part_record: Dict[str, Any] = {
            "component_id": component_id,
            "realization_class": (
                item.get("realization_class")
                if isinstance(item.get("realization_class"), str)
                else _infer_realization_class(
                    component_type=component_type_by_id.get(component_id, ""),
                    modeling_strategy=strategy,
                    part_payload=item,
                )
            ),
            "primary_method": primary_method,
            "modeling_strategy": strategy,
            "parameter_resolution": item.get("parameter_resolution", {}),
            "contract_pattern_used": item.get("contract_pattern_used"),
            "contract_pattern_source": item.get("contract_pattern_source"),
            "coordinate_frame": coordinate_frame,
            "root_transform_mm": {
                "translation": {
                    "x": float(origin_mm.get("x", 0.0)),
                    "y": float(origin_mm.get("y", 0.0)),
                    "z": float(origin_mm.get("z", 0.0)),
                },
                "rotation_rpy_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            },
            "features": selected_features,
        }
        parts.append(part_record)

    planner._suppress_bearing_backed_wheel_hub_bores(parts, semantics)
    planner._rewrite_hub_slot_mount_fastener_features(parts)
    _rewrite_yoke_support_shaft_bore_features(parts)
    _sync_axisymmetric_bearing_profile_params(parts)

    inherited_interface_manifest = semantics.get("interface_manifest")
    if not isinstance(inherited_interface_manifest, dict):
        inherited_interface_manifest = {
            "metadata": {
                "schema_version": "1.0",
                "source": "agent3a_shape_realization_inherited",
                "warning": "missing interface_manifest in geometry semantics",
            },
            "components": [],
        }

    def _load_ground_component_override() -> str | None:
        env_id = os.getenv("FUSION_GROUND_COMPONENT_ID", "").strip()
        if env_id:
            return env_id

        kg_root = kg.get("root_component_id")
        if isinstance(kg_root, str) and kg_root.strip():
            return kg_root.strip()

        input_dir = run_dir / "input"
        if not input_dir.exists():
            return None
        try:
            import yaml  # type: ignore
        except Exception:
            return None

        def _extract(obj: Any) -> str | None:
            if isinstance(obj, dict):
                v = obj.get("ground_component_id")
                if isinstance(v, str) and v.strip():
                    return v.strip()
                for key in ("placement", "assembly", "constraints", "planner"):
                    out = _extract(obj.get(key))
                    if out:
                        return out
            return None

        for p in sorted(input_dir.glob("*.yml")) + sorted(input_dir.glob("*.yaml")):
            try:
                payload = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out = _extract(payload)
            if out:
                return out
        return None

    all_component_ids: List[str] = []
    seen_component_ids: set[str] = set()
    for comp in (kg.get("components") or []):
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid in seen_component_ids:
            continue
        seen_component_ids.add(cid)
        all_component_ids.append(cid)

    for p in parts:
        if not isinstance(p, Mapping):
            continue
        cid = p.get("component_id")
        if not isinstance(cid, str) or not cid or cid in seen_component_ids:
            continue
        seen_component_ids.add(cid)
        all_component_ids.append(cid)

    placement_plan = _compute_initial_placements(
        kg=kg,
        component_ids=all_component_ids,
        semantics=semantics,
        margin_mm=5.0,
        ground_component_id_override=_load_ground_component_override(),
    )
    initial_placements = placement_plan.get("initial_placements")
    if not isinstance(initial_placements, list):
        initial_placements = []

    _project_hub_radial_slot_geometry(realization, initial_placements)

    placement_groups = placement_plan.get("placement_groups")
    if not isinstance(placement_groups, list):
        placement_groups = []

    # Always write diagnostics (one per run; last round wins).
    try:
        diag = placement_plan.get("diagnostics")
        if not isinstance(diag, dict):
            diag = {}
        _write_json(
            run_dir / "placement_diagnostics.json",
            {
                "metadata": {
                    "source": "Agent3a_shape_realization_planner",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "round_index": int(round_index),
                },
                "summary": placement_plan.get("summary", {}),
                "placement_groups": placement_groups,
                # Explicit, easy-to-assert aliases for DoD:
                # - conflicts: overlap detections (group-level)
                # - corrections: the applied translations/jitters to resolve overlaps
                # - final_placements: resulting poses
                "conflicts": diag.get("group_conflicts", []),
                "corrections": {
                    "applied_group_translations": diag.get("applied_group_translations", []),
                    "axial_jitters": diag.get("axial_jitters", []),
                },
                "final_placements": diag.get("after", []),
                "diagnostics": diag,
            },
        )
    except Exception:
        pass

    realization_output = {
        "metadata": realization.get("metadata", {}),
        "parts": parts,
        "interface_manifest": inherited_interface_manifest,
        "initial_placements": initial_placements,
        "placement_groups": placement_groups,
    }

    meta = realization_output.get("metadata")
    if isinstance(meta, dict):
        meta["layout_inference"] = {
            "mode": layout_plan.get("inference_mode"),
            "warnings": layout_plan.get("warnings", []),
        }
        manifest_components = inherited_interface_manifest.get("components") if isinstance(inherited_interface_manifest, dict) else []
        meta["interface_manifest"] = {
            "component_count": len(manifest_components) if isinstance(manifest_components, list) else 0,
        }
        meta["initial_placements"] = placement_plan.get("summary", {})
        realization_counts: Dict[str, int] = {
            REALIZATION_CLASS_NATIVE: 0,
            REALIZATION_CLASS_HOSTED_STANDARD: 0,
            REALIZATION_CLASS_KINEMATIC_IMPORTED: 0,
        }
        realization_by_component: Dict[str, str] = {}
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            cid = part.get("component_id") if isinstance(part.get("component_id"), str) else None
            rc = part.get("realization_class") if isinstance(part.get("realization_class"), str) else None
            if not isinstance(cid, str) or not cid or not isinstance(rc, str) or not rc:
                continue
            realization_by_component[cid] = rc
            if rc in realization_counts:
                realization_counts[rc] = int(realization_counts.get(rc, 0)) + 1
            else:
                realization_counts[rc] = 1
        meta["realization_classes"] = {
            "counts": realization_counts,
            "by_component": realization_by_component,
        }
        if isinstance(hole_arbitration, Mapping):
            meta["hole_arbitration"] = {
                "kept": hole_arbitration.get("kept", []),
                "dropped": hole_arbitration.get("dropped", []),
            }
        if isinstance(thread_warnings, list) and thread_warnings:
            meta["threading_warnings"] = thread_warnings

    # Write output
    output_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    _write_json(output_path, realization_output)
    
    print(f"[OK] Generated shape realization plan: {output_path.name}")
    print(f"  - {len(parts)} parts")
    if layout_plan.get("layout_positions"):
        print(f"  - {len(layout_plan['layout_positions'])} component positions ({layout_plan['inference_mode']})")
    if layout_plan.get("warnings"):
        for warning in layout_plan["warnings"]:
            print(f"  - [layout] {warning}")
    
    return {"path": f"planning/shape_realization_round_{round_index}.json"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan shape realization strategies"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)
    
    args = parser.parse_args()
    
    result = run(
        run_dir=args.run_dir,
        round_index=args.round_index
    )
    
    print(f"Shape realization plan: {result['path']}")


if __name__ == "__main__":
    main()









