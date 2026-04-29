"""Agent3a feature extraction and feature cleanup for buildable part records."""

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

from .common import *

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
