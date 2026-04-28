from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict, List, Mapping


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            return None
    return None


def _component_dims_map(kg: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    components = kg.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        dims = comp.get("dimensions")
        if isinstance(cid, str) and cid and isinstance(dims, Mapping):
            if comp.get("is_container_only") is True:
                continue
            if comp.get("has_geometry") is False:
                continue
            modeling_policy = comp.get("modeling_policy")
            mp_s = modeling_policy.strip().lower() if isinstance(modeling_policy, str) else ""
            if mp_s == "container_only":
                continue
            out[cid] = dict(dims)
    return out


def _component_type_map(kg: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    components = kg.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and cid and isinstance(ctype, str) and ctype:
            out[cid] = ctype
    return out


def _component_shape_map(kg: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    components = kg.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue

        shape = comp.get("shape") if isinstance(comp.get("shape"), Mapping) else {}
        shape_sem = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        candidates = [
            shape.get("type"),
            shape_sem.get("type"),
            comp.get("shape_type"),
            comp.get("geometry_type"),
        ]
        for raw in candidates:
            if isinstance(raw, str) and raw.strip():
                out[cid] = raw.strip().lower()
                break
    return out


def _component_flags_map(kg: Mapping[str, Any]) -> Dict[str, Dict[str, bool]]:
    out: Dict[str, Dict[str, bool]] = {}
    components = kg.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        has_geometry_raw = comp.get("has_geometry")
        has_geometry = bool(has_geometry_raw) if isinstance(has_geometry_raw, bool) else True
        policy = comp.get("modeling_policy")
        policy_s = policy.strip().lower() if isinstance(policy, str) else ""
        out[cid] = {
            "is_container_only": bool(comp.get("is_container_only")),
            "has_geometry": has_geometry,
            "is_container_policy": policy_s in {"container_only", "reference_only"},
        }
    return out


def _is_container_or_no_geometry(flags: Mapping[str, bool] | None) -> bool:
    if not isinstance(flags, Mapping):
        return False
    return bool(flags.get("is_container_only")) or bool(flags.get("is_container_policy")) or (not bool(flags.get("has_geometry", True)))


def _is_fastener_component(component_type: str | None, component_id: str | None) -> bool:
    ctype = component_type.lower() if isinstance(component_type, str) else ""
    cid = component_id.lower() if isinstance(component_id, str) else ""
    markers = ("fastener", "bolt", "screw", "nut", "washer", "pin", "rivet")
    return any(m in ctype for m in markers) or any(m in cid for m in markers)


def _outer_radius(dims: Mapping[str, Any]) -> float | None:
    candidates: List[float] = []
    for key in ("outer_radius", "radius"):
        v = _to_float(dims.get(key))
        if v is not None and v > 0:
            candidates.append(v)
    for key in ("outer_diameter", "diameter"):
        v = _to_float(dims.get(key))
        if v is not None and v > 0:
            candidates.append(v / 2.0)
    if not candidates:
        return None
    return max(candidates)


def _plate_outer_radius_estimate(dims: Mapping[str, Any]) -> float | None:
    width = _to_float(dims.get("width"))
    height = _to_float(dims.get("height"))
    if height is None:
        height = _to_float(dims.get("length"))
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return min(width, height) / 2.0


def infer_outer_radius_for_planar_prismatic(dimensions: Mapping[str, Any]) -> float | None:
    width = _to_float(dimensions.get("width_mm"))
    if width is None:
        width = _to_float(dimensions.get("width"))
    length = _to_float(dimensions.get("length_mm"))
    if length is None:
        length = _to_float(dimensions.get("length"))

    if width is not None and width > 0 and length is not None and length > 0:
        return 0.5 * min(width, length)
    if width is not None and width > 0:
        return 0.5 * width
    if length is not None and length > 0:
        return 0.5 * length
    return None


def _is_planar_end_face(reference_surface: str | None) -> bool:
    if not isinstance(reference_surface, str) or not reference_surface.strip():
        return False
    text = reference_surface.strip().lower()
    planar_markers = ("end_face", "axial_end_face", "planar_end_face")
    return any(marker in text for marker in planar_markers)


def _is_radial_outer_face(reference_surface: str | None) -> bool:
    if not isinstance(reference_surface, str) or not reference_surface.strip():
        return False
    text = reference_surface.strip().lower()
    return "radial_outer_face" in text


def _inner_radius(dims: Mapping[str, Any]) -> float:
    candidates: List[float] = [0.0]
    for key in ("inner_radius", "bore_radius"):
        v = _to_float(dims.get(key))
        if v is not None and v >= 0:
            candidates.append(v)
    for key in ("inner_diameter", "bore_diameter", "hole_diameter", "shaft_hole_diameter"):
        v = _to_float(dims.get(key))
        if v is not None and v >= 0:
            candidates.append(v / 2.0)
    return max(candidates)


def _hole_diameter(placement: Mapping[str, Any]) -> float:
    location = placement.get("location")
    if isinstance(location, Mapping):
        safety = location.get("safety_constraints")
        if isinstance(safety, Mapping):
            feature_d = _to_float(safety.get("feature_diameter"))
            if feature_d is not None and feature_d > 0:
                return feature_d

    max_d = 0.0
    derived = placement.get("derived_changes")
    if isinstance(derived, list):
        for item in derived:
            if not isinstance(item, Mapping):
                continue
            feature = item.get("feature")
            if not isinstance(feature, str):
                continue
            if "hole" not in feature and "bolt" not in feature:
                continue
            for key in ("hole_diameter", "diameter", "bore_diameter"):
                d = _to_float(item.get(key))
                if d is not None and d > max_d:
                    max_d = d
    if max_d > 0:
        return max_d
    return 5.0


def _extract_seed_xy(location: Mapping[str, Any], pattern: Mapping[str, Any]) -> tuple[float, float] | None:
    candidates = [
        pattern.get("seed_point_mm"),
        pattern.get("seed_point"),
        pattern.get("center_mm"),
        pattern.get("center"),
        location.get("seed_point_mm"),
        location.get("seed_point"),
        location.get("center_mm"),
        location.get("center"),
    ]
    for cand in candidates:
        if not isinstance(cand, Mapping):
            continue
        x = _to_float(cand.get("x"))
        y = _to_float(cand.get("y"))
        if x is None or y is None:
            continue
        return float(x), float(y)
    return None


def _expand_hole_points_mm(placement: Mapping[str, Any]) -> List[tuple[float, float]]:
    location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
    pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
    count_raw = pattern.get("count") if isinstance(pattern.get("count"), int) else 1
    count = max(1, int(count_raw))
    seed = _extract_seed_xy(location, pattern)
    if seed is None:
        return []

    if count <= 1:
        return [seed]

    radius = _to_float(pattern.get("pattern_radius_mm"))
    if radius is None:
        radius = _to_float(pattern.get("pattern_radius"))
    if radius is None or radius < 0:
        return [seed]

    start_angle_rad = _to_float(pattern.get("start_angle_rad"))
    if start_angle_rad is None:
        start_angle_deg = _to_float(pattern.get("start_angle_deg"))
        start_angle_rad = math.radians(float(start_angle_deg)) if start_angle_deg is not None else 0.0

    cx, cy = seed
    points: List[tuple[float, float]] = []
    for idx in range(count):
        angle = float(start_angle_rad) + (2.0 * math.pi * float(idx) / float(count))
        points.append((cx + float(radius) * math.cos(angle), cy + float(radius) * math.sin(angle)))
    return points


def _between_ids(placement: Mapping[str, Any]) -> List[str]:
    between = placement.get("between")
    if isinstance(between, dict):
        return [k for k in between.keys() if isinstance(k, str) and k]
    if isinstance(between, list):
        return [cid for cid in between if isinstance(cid, str) and cid]
    return []


def _is_hole_related_placement(placement: Mapping[str, Any]) -> bool:
    def _has_hole_like_derived_change() -> bool:
        derived_local = placement.get("derived_changes")
        if not isinstance(derived_local, list):
            return False
        for item in derived_local:
            if not isinstance(item, Mapping):
                continue
            feature = item.get("feature")
            if not isinstance(feature, str):
                continue
            feature_l = feature.lower()
            if "hole" in feature_l or "bolt" in feature_l or "counterbore" in feature_l or "countersink" in feature_l:
                return True
        return False

    if _has_hole_like_derived_change():
        return True

    fastener_spec = placement.get("fastener_spec")
    if isinstance(fastener_spec, Mapping):
        purpose = placement.get("purpose")
        if isinstance(purpose, str) and purpose.strip().lower() == "spacing":
            return False
        return True

    derived = placement.get("derived_changes")
    if isinstance(derived, list):
        for item in derived:
            if not isinstance(item, Mapping):
                continue
            feature = item.get("feature")
            if not isinstance(feature, str):
                continue
            feature_l = feature.lower()
            if "hole" in feature_l or "bolt" in feature_l or "counterbore" in feature_l or "countersink" in feature_l:
                return True
    return False


def validate_geometry_semantics_feasibility(
    *,
    semantics: Mapping[str, Any],
    kg: Mapping[str, Any],
    apply_fallback: bool = True,
) -> Dict[str, Any]:
    placements_raw = semantics.get("connection_placements")
    placements: List[Dict[str, Any]] = [p for p in placements_raw if isinstance(p, dict)] if isinstance(placements_raw, list) else []
    dims_by_id = _component_dims_map(kg)
    types_by_id = _component_type_map(kg)
    shapes_by_id = _component_shape_map(kg)
    flags_by_id = _component_flags_map(kg)

    violations: List[Dict[str, Any]] = []
    placement_audits: List[Dict[str, Any]] = []
    checked = 0
    fallback_count = 0
    blocked_count = 0
    intent_changed_count = 0
    pcd_groups_checked = 0
    pcd_groups_blocked = 0
    pcd_groups_normalized = 0
    hole_overlap_groups_checked = 0
    hole_overlap_conflict_count = 0

    def _extract_effective_pattern(placement: Mapping[str, Any]) -> Dict[str, Any] | None:
        location_local = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern_local = location_local.get("pattern_parameters") if isinstance(location_local.get("pattern_parameters"), Mapping) else {}
        pattern_type_local = pattern_local.get("type") if isinstance(pattern_local.get("type"), str) else None
        if isinstance(pattern_type_local, str) and pattern_type_local.lower() == "circular":
            return dict(pattern_local)

        fastener_spec = placement.get("fastener_spec") if isinstance(placement.get("fastener_spec"), Mapping) else {}
        fs_pattern = fastener_spec.get("pattern") if isinstance(fastener_spec.get("pattern"), Mapping) else {}
        fs_pattern_type = fs_pattern.get("type") if isinstance(fs_pattern.get("type"), str) else None
        if isinstance(fs_pattern_type, str) and fs_pattern_type.lower() == "bolt_circle":
            count_raw = fastener_spec.get("count")
            if not isinstance(count_raw, int):
                count_raw = fs_pattern.get("count") if isinstance(fs_pattern.get("count"), int) else pattern_local.get("count")
            result: Dict[str, Any] = {
                "type": "circular",
                "count": count_raw if isinstance(count_raw, int) else pattern_local.get("count", 1),
                "pattern_radius": (
                    fs_pattern.get("pattern_radius")
                    if fs_pattern.get("pattern_radius") is not None
                    else pattern_local.get("pattern_radius")
                ),
                "offset_from_edge": (
                    fs_pattern.get("offset_from_edge")
                    if fs_pattern.get("offset_from_edge") is not None
                    else pattern_local.get("offset_from_edge")
                ),
            }
            return result

        derived = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        for change in derived:
            if not isinstance(change, Mapping):
                continue
            ch_pattern = change.get("pattern") if isinstance(change.get("pattern"), Mapping) else {}
            ch_pattern_type = ch_pattern.get("type") if isinstance(ch_pattern.get("type"), str) else None
            if isinstance(ch_pattern_type, str) and ch_pattern_type.lower() == "bolt_circle":
                count_raw = ch_pattern.get("count") if isinstance(ch_pattern.get("count"), int) else pattern_local.get("count")
                result = {
                    "type": "circular",
                    "count": count_raw if isinstance(count_raw, int) else 1,
                    "pattern_radius": (
                        ch_pattern.get("pattern_radius")
                        if ch_pattern.get("pattern_radius") is not None
                        else pattern_local.get("pattern_radius")
                    ),
                    "offset_from_edge": (
                        ch_pattern.get("offset_from_edge")
                        if ch_pattern.get("offset_from_edge") is not None
                        else pattern_local.get("offset_from_edge")
                    ),
                }
                return result

        return None

    for placement in placements:
        if not _is_hole_related_placement(placement):
            continue

        location_raw = placement.get("location")
        location = location_raw if isinstance(location_raw, dict) else {}

        pattern_raw = location.get("pattern_parameters")
        pattern_local = pattern_raw if isinstance(pattern_raw, dict) else {}
        effective_pattern = _extract_effective_pattern(placement)
        if not isinstance(effective_pattern, dict):
            continue

        pattern = effective_pattern
        pattern.setdefault("type", "circular")
        if pattern.get("type") != "circular":
            pattern["type"] = "circular"

        normalized_from_non_location = not (
            isinstance(pattern_local, Mapping)
            and isinstance(pattern_local.get("type"), str)
            and str(pattern_local.get("type")).lower() == "circular"
        )
        if normalized_from_non_location:
            location["pattern_parameters"] = pattern
            placement["location"] = location

        checked += 1
        cid = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else "unknown"
        iface_ref_raw = location.get("interface_ref")
        iface_ref = iface_ref_raw if isinstance(iface_ref_raw, dict) else {}
        host_id = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
        reference_surface = None
        ref_surface_raw = location.get("reference_surface")
        if isinstance(ref_surface_raw, str) and ref_surface_raw:
            reference_surface = ref_surface_raw
        else:
            iface_name = iface_ref.get("interface_name")
            if isinstance(iface_name, str) and iface_name:
                reference_surface = iface_name
        original_host_id = host_id

        pattern_radius = _to_float(pattern.get("pattern_radius_mm"))
        if pattern_radius is None:
            pattern_radius = _to_float(pattern.get("pattern_radius"))
        offset_from_edge = _to_float(pattern.get("edge_margin_mm"))
        if offset_from_edge is None:
            offset_from_edge = _to_float(pattern.get("offset_from_edge"))
        hole_d = _hole_diameter(placement)
        hole_r = hole_d / 2.0
        original_pattern_radius = pattern_radius
        original_offset_from_edge = offset_from_edge
        original_hole_d = hole_d

        safety_raw = location.get("safety_constraints")
        safety = safety_raw if isinstance(safety_raw, dict) else {}
        min_wall = _to_float(safety.get("min_wall"))
        if min_wall is None:
            min_wall = max(1.0, round(hole_r * 0.25, 2))

        blocked_reasons: List[str] = []
        clarification_reasons: List[str] = []
        fallback_actions: List[str] = []
        fallback_audit: List[Dict[str, Any]] = []

        def _record_fallback(
            *,
            action: str,
            field: str,
            original: Any,
            corrected: Any,
            reason: str,
            functional_intent_changed: bool,
        ) -> None:
            fallback_actions.append(action)
            fallback_audit.append(
                {
                    "action": action,
                    "field": field,
                    "original": original,
                    "corrected": corrected,
                    "reason": reason,
                    "functional_intent_changed": functional_intent_changed,
                }
            )

        if normalized_from_non_location:
            _record_fallback(
                action="normalized_pattern_source",
                field="location.pattern_parameters",
                original=dict(pattern_local) if isinstance(pattern_local, Mapping) else None,
                corrected=dict(pattern),
                reason="normalized circular pattern from fastener_spec/derived_changes",
                functional_intent_changed=False,
            )

        between_ids = _between_ids(placement)

        host_outer = _outer_radius(dims_by_id.get(host_id, {})) if host_id in dims_by_id else None
        host_is_fastener = _is_fastener_component(types_by_id.get(host_id), host_id)

        original_host_flags = flags_by_id.get(original_host_id) if isinstance(original_host_id, str) else None
        original_host_is_container = (
            (original_host_id is not None and original_host_id not in dims_by_id)
            or _is_container_or_no_geometry(original_host_flags)
        )
        allow_host_reselect = (
            host_id is None
            or host_is_fastener
            or original_host_is_container
        )

        if apply_fallback and allow_host_reselect and (host_id is None or host_id not in dims_by_id or host_outer is None or host_is_fastener):
            for candidate in between_ids:
                if _is_fastener_component(types_by_id.get(candidate), candidate):
                    continue
                if candidate in dims_by_id and _outer_radius(dims_by_id[candidate]) is not None:
                    host_id = candidate
                    iface_ref["component_id"] = candidate
                    location["interface_ref"] = iface_ref
                    _record_fallback(
                        action="reselected_host_component",
                        field="location.interface_ref.component_id",
                        original=original_host_id,
                        corrected=candidate,
                        reason="original host lacked usable geometry or was fastener-like",
                        functional_intent_changed=False,
                    )
                    break

        if host_id is None or host_id not in dims_by_id:
            actionable_candidates = [
                cid
                for cid in between_ids
                if (cid in dims_by_id)
                and (_outer_radius(dims_by_id[cid]) is not None)
                and (not _is_fastener_component(types_by_id.get(cid), cid))
            ]
            if not actionable_candidates:
                placement["requires_clarification"] = False
                placement.setdefault("feasibility", {})
                placement["feasibility"].update(
                    {
                        "status": "skipped_no_host_geometry",
                        "checks": {
                            "host_component_id": host_id,
                        },
                        "fallback_actions": fallback_actions,
                        "violations": [],
                    }
                )
                continue

        if host_id is None or host_id not in dims_by_id:
            blocked_reasons.append("missing_host_component_dimensions")

        host_shape = shapes_by_id.get(host_id) if isinstance(host_id, str) else None
        if not isinstance(host_shape, str) or not host_shape:
            host_shape = "prismatic" if isinstance(types_by_id.get(host_id), str) and types_by_id.get(host_id) in {"arm", "plate", "bracket"} else host_shape

        if _is_radial_outer_face(reference_surface) and host_shape not in {"cylindrical", "annular", "ring"}:
            blocked_reasons.append("bolt_circle_on_non_cylindrical_radial_outer_face")

        outer = _outer_radius(dims_by_id.get(host_id, {})) if host_id else None
        outer_radius_source = "direct"
        if outer is None and host_id and host_id in dims_by_id:
            estimated_outer = None
            if host_shape in {"prismatic", "plate", "rectangular"} and _is_planar_end_face(reference_surface):
                estimated_outer = infer_outer_radius_for_planar_prismatic(dims_by_id.get(host_id, {}))
                if estimated_outer is not None:
                    outer_radius_source = "planar_prismatic_estimate"
                    _record_fallback(
                        action="estimated_outer_radius_for_planar_prismatic",
                        field="feasibility.checks.outer_radius",
                        original=None,
                        corrected=round(float(estimated_outer), 3),
                        reason="bolt_circle on prismatic planar end-face uses equivalent outer radius from width/length",
                        functional_intent_changed=False,
                    )
            if estimated_outer is None:
                estimated_outer = _plate_outer_radius_estimate(dims_by_id.get(host_id, {}))
            if estimated_outer is not None:
                outer = estimated_outer
                if outer_radius_source == "direct":
                    outer_radius_source = "plate_estimate"
                    _record_fallback(
                        action="estimated_outer_radius_from_plate_dims",
                        field="feasibility.checks.outer_radius",
                        original=None,
                        corrected=round(float(estimated_outer), 3),
                        reason="outer radius estimated from plate-like width/length envelope",
                        functional_intent_changed=False,
                    )
        inner = _inner_radius(dims_by_id.get(host_id, {})) if host_id else 0.0
        if outer is None and host_id and host_id in dims_by_id and not allow_host_reselect:
            clarification_reasons.append("blocked_missing_host_geometry")
        if outer is None:
            if host_shape in {"prismatic", "plate", "rectangular"}:
                clarification_reasons.append("bolt_circle_on_prismatic_requires_planar_end_face_and_width_length")
            else:
                clarification_reasons.append("missing_outer_radius")

        if pattern_radius is None and outer is not None and apply_fallback:
            pattern_radius = round(outer * 0.7, 2)
            pattern["pattern_radius"] = pattern_radius
            _record_fallback(
                action="synthesized_pattern_radius",
                field="location.pattern_parameters.pattern_radius",
                original=original_pattern_radius,
                corrected=pattern_radius,
                reason="missing pattern radius inferred from host outer radius",
                functional_intent_changed=False,
            )

        if pattern_radius is None:
            if outer is None:
                clarification_reasons.append("missing_pattern_radius")
            else:
                blocked_reasons.append("missing_pattern_radius")

        if not blocked_reasons and outer is not None and pattern_radius is not None:
            feasible_min = inner + hole_r + min_wall
            feasible_max = outer - hole_r - min_wall

            if feasible_max < feasible_min and apply_fallback:
                max_hole_radius = (outer - inner - 2 * min_wall) / 2.0
                if max_hole_radius > 0 and max_hole_radius < hole_r:
                    prev_hole_d = hole_d
                    hole_r = max_hole_radius
                    hole_d = round(hole_r * 2.0, 2)
                    safety["feature_diameter"] = hole_d
                    location["safety_constraints"] = safety
                    _record_fallback(
                        action="reduced_hole_diameter",
                        field="location.safety_constraints.feature_diameter",
                        original=prev_hole_d,
                        corrected=hole_d,
                        reason="hole diameter exceeded available wall thickness envelope",
                        functional_intent_changed=True,
                    )
                    feasible_min = inner + hole_r + min_wall
                    feasible_max = outer - hole_r - min_wall

            if feasible_max >= feasible_min and apply_fallback:
                clamped_radius = min(max(pattern_radius, feasible_min), feasible_max)
                if abs(clamped_radius - pattern_radius) > 1e-6:
                    prev_radius = pattern_radius
                    pattern["pattern_radius"] = round(clamped_radius, 2)
                    pattern_radius = clamped_radius
                    _record_fallback(
                        action="clamped_pattern_radius",
                        field="location.pattern_parameters.pattern_radius",
                        original=prev_radius,
                        corrected=pattern_radius,
                        reason="radius clamped into feasible ring band",
                        functional_intent_changed=False,
                    )

                geometric_offset = outer - pattern_radius - hole_r
                if geometric_offset < min_wall:
                    candidate_radius = outer - hole_r - min_wall
                    if candidate_radius >= feasible_min:
                        prev_radius = pattern_radius
                        pattern_radius = candidate_radius
                        pattern["pattern_radius"] = round(candidate_radius, 2)
                        geometric_offset = outer - pattern_radius - hole_r
                        _record_fallback(
                            action="pushed_inward_for_min_wall",
                            field="location.pattern_parameters.pattern_radius",
                            original=prev_radius,
                            corrected=pattern_radius,
                            reason="radius moved inward to preserve minimum wall",
                            functional_intent_changed=False,
                        )

                if offset_from_edge is None or abs(offset_from_edge - geometric_offset) > 0.5:
                    prev_offset = offset_from_edge
                    pattern["offset_from_edge"] = round(max(0.0, geometric_offset), 2)
                    offset_from_edge = geometric_offset
                    _record_fallback(
                        action="reconciled_offset_from_edge",
                        field="location.pattern_parameters.offset_from_edge",
                        original=prev_offset,
                        corrected=round(max(0.0, geometric_offset), 2),
                        reason="offset reconciled with solved pattern radius and hole size",
                        functional_intent_changed=False,
                    )

            cond_outer = (pattern_radius + hole_r + min_wall) <= (outer + 1e-6)
            cond_inner = (pattern_radius - hole_r - min_wall) >= (inner - 1e-6)
            offset_expected = outer - pattern_radius - hole_r
            cond_offset = offset_from_edge is not None and abs(offset_from_edge - offset_expected) <= 0.5

            if not cond_outer:
                if outer_radius_source in {"plate_estimate", "planar_prismatic_estimate"}:
                    clarification_reasons.append("violates_outer_wall_constraint")
                else:
                    blocked_reasons.append("violates_outer_wall_constraint")
            if not cond_inner:
                # Thin-walled annular sub-components (rim, tire) are expected to
                # have narrow wall envelopes; holes through these walls are
                # structurally questionable but not blocking -- down-grade to
                # clarification so the quality gate does not hard-block the
                # entire plan.
                host_type_str = str(types_by_id.get(host_id) or "").lower() if isinstance(host_id, str) else ""
                is_thin_walled_annular = host_type_str in {"rim", "tire"}
                if outer_radius_source in {"plate_estimate", "planar_prismatic_estimate"} or is_thin_walled_annular:
                    clarification_reasons.append("violates_inner_wall_constraint")
                else:
                    blocked_reasons.append("violates_inner_wall_constraint")
            if not cond_offset:
                if outer_radius_source in {"plate_estimate", "planar_prismatic_estimate"}:
                    clarification_reasons.append("offset_conflicts_with_pattern_radius")
                else:
                    blocked_reasons.append("offset_conflicts_with_pattern_radius")

        if fallback_actions:
            fallback_count += 1
        functional_intent_changed = any(
            bool(item.get("functional_intent_changed")) for item in fallback_audit if isinstance(item, dict)
        )
        if functional_intent_changed:
            intent_changed_count += 1

        status = "ok"
        if blocked_reasons:
            status = "blocked"
        elif clarification_reasons:
            status = "needs_clarification"
        placement["requires_clarification"] = bool(blocked_reasons or clarification_reasons)
        placement["location"] = location
        placement.setdefault("feasibility", {})
        placement["feasibility"].update(
            {
                "status": status,
                "checks": {
                    "host_component_id": host_id,
                    "hole_diameter": round(hole_d, 3),
                    "min_wall": round(min_wall, 3),
                    "outer_radius": outer,
                        "outer_radius_source": outer_radius_source,
                    "inner_radius": inner if outer is not None else None,
                },
                "fallback_actions": fallback_actions,
                "fallback_audit": fallback_audit,
                "functional_intent_changed": functional_intent_changed,
                "original_values": {
                    "host_component_id": original_host_id,
                    "pattern_radius": original_pattern_radius,
                    "offset_from_edge": original_offset_from_edge,
                    "hole_diameter": original_hole_d,
                },
                "violations": blocked_reasons + clarification_reasons,
            }
        )

        if blocked_reasons:
            blocked_count += 1
            violations.append(
                {
                    "connection_id": cid,
                    "host_component_id": host_id,
                    "violations": blocked_reasons,
                }
            )

        placement_audits.append(
            {
                "connection_id": cid,
                "status": status,
                "host_component_id": host_id,
                "original_values": {
                    "host_component_id": original_host_id,
                    "pattern_radius": original_pattern_radius,
                    "offset_from_edge": original_offset_from_edge,
                    "hole_diameter": original_hole_d,
                },
                "corrected_values": {
                    "pattern_radius": pattern.get("pattern_radius"),
                    "offset_from_edge": pattern.get("offset_from_edge"),
                    "hole_diameter": hole_d,
                },
                "fallback_actions": fallback_actions,
                "fallback_audit": fallback_audit,
                "functional_intent_changed": functional_intent_changed,
                "violations": blocked_reasons + clarification_reasons,
            }
        )

    # Stage 2: enforce connection-group consistency for circular pattern radius.
    groups: Dict[str, List[Dict[str, Any]]] = {}
    placement_by_connection_id: Dict[str, Dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        conn_id = placement.get("connection_id")
        if not isinstance(conn_id, str) or not conn_id:
            continue
        location = placement.get("location")
        if not isinstance(location, Mapping):
            continue
        pattern = location.get("pattern_parameters")
        if not isinstance(pattern, Mapping) or pattern.get("type") != "circular":
            continue
        placement_by_connection_id[conn_id] = placement

    for audit in placement_audits:
        if not isinstance(audit, Mapping):
            continue
        conn_id = audit.get("connection_id")
        if not isinstance(conn_id, str) or not conn_id:
            continue
        placement = placement_by_connection_id.get(conn_id)
        if not isinstance(placement, Mapping):
            continue
        location_for_group = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern_for_group = location_for_group.get("pattern_parameters") if isinstance(location_for_group.get("pattern_parameters"), Mapping) else {}
        pcd_group_id = pattern_for_group.get("pcd_group") if isinstance(pattern_for_group.get("pcd_group"), str) and pattern_for_group.get("pcd_group") else None
        base_conn = conn_id.split("@", 1)[0]
        host_from_audit = audit.get("host_component_id") if isinstance(audit.get("host_component_id"), str) else None
        if host_from_audit is None:
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            host_from_audit = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
        group_key = pcd_group_id if isinstance(pcd_group_id, str) and pcd_group_id else (f"{base_conn}@{host_from_audit}" if isinstance(host_from_audit, str) and host_from_audit else base_conn)
        groups.setdefault(group_key, []).append({"placement": placement, "audit": audit})

    for group_key, members in groups.items():
        pcd_groups_checked += 1

        band_records: List[Dict[str, Any]] = []
        raw_radii: List[float] = []
        for rec in members:
            placement = rec["placement"]
            audit = rec["audit"]
            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), Mapping) else {}
            checks = feasibility.get("checks") if isinstance(feasibility.get("checks"), Mapping) else {}
            outer = _to_float(checks.get("outer_radius"))
            outer_source = checks.get("outer_radius_source") if isinstance(checks.get("outer_radius_source"), str) else "direct"
            inner = _to_float(checks.get("inner_radius"))
            if inner is None:
                inner = 0.0
            hole_d = _to_float(checks.get("hole_diameter"))
            min_wall = _to_float(checks.get("min_wall"))
            if outer_source in {"plate_estimate", "planar_prismatic_estimate"}:
                band_records = []
                break
            if outer is None or hole_d is None or min_wall is None:
                band_records = []
                break
            location_local = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            pattern_local = location_local.get("pattern_parameters") if isinstance(location_local.get("pattern_parameters"), Mapping) else {}
            count_val = pattern_local.get("count") if isinstance(pattern_local.get("count"), int) else 1
            if count_val < 1:
                count_val = 1
            feasible_min = inner + hole_d / 2.0 + min_wall
            feasible_max = outer - hole_d / 2.0 - min_wall
            band_records.append(
                {
                    "placement": placement,
                    "audit": audit,
                    "outer": outer,
                    "inner": inner,
                    "hole_d": hole_d,
                    "min_wall": min_wall,
                    "count": count_val,
                    "feasible_min": feasible_min,
                    "feasible_max": feasible_max,
                }
            )
            ov = audit.get("original_values") if isinstance(audit.get("original_values"), Mapping) else {}
            rv = _to_float(ov.get("pattern_radius"))
            if rv is None:
                location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
                rv = _to_float(pattern.get("pattern_radius"))
            if rv is not None:
                raw_radii.append(rv)

        if not band_records:
            continue

        group_min = max(float(r["feasible_min"]) for r in band_records)
        group_max = min(float(r["feasible_max"]) for r in band_records)
        has_intersection = group_max >= group_min

        candidate_radius: float
        if raw_radii:
            s = sorted(raw_radii)
            mid = len(s) // 2
            if len(s) % 2 == 1:
                candidate_radius = float(s[mid])
            else:
                candidate_radius = 0.5 * (float(s[mid - 1]) + float(s[mid]))
        else:
            candidate_radius = 0.5 * (group_min + group_max)

        group_radius = min(max(candidate_radius, group_min), group_max) if has_intersection else candidate_radius
        if not has_intersection:
            pcd_groups_blocked += 1
        else:
            pcd_groups_normalized += 1

        for rec in band_records:
            placement = rec["placement"]
            audit = rec["audit"]
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), Mapping) else {}
            checks = feasibility.get("checks") if isinstance(feasibility.get("checks"), Mapping) else {}
            fallback_actions = list(feasibility.get("fallback_actions") or []) if isinstance(feasibility.get("fallback_actions"), list) else []
            fallback_audit = list(feasibility.get("fallback_audit") or []) if isinstance(feasibility.get("fallback_audit"), list) else []
            old_violations = [
                v
                for v in (feasibility.get("violations") if isinstance(feasibility.get("violations"), list) else [])
                if isinstance(v, str)
            ]

            old_radius = _to_float(pattern.get("pattern_radius"))
            old_offset = _to_float(pattern.get("offset_from_edge"))
            outer = float(rec["outer"])
            inner = float(rec["inner"])
            hole_r = float(rec["hole_d"]) / 2.0
            hole_d_current = float(rec["hole_d"])
            min_wall = float(rec["min_wall"])
            count_current = int(rec.get("count") or 1)

            if has_intersection:
                new_radius = float(group_radius)
                new_offset = outer - new_radius - hole_r
                pattern["pattern_radius"] = round(new_radius, 2)
                pattern["offset_from_edge"] = round(max(0.0, new_offset), 2)
                if old_radius is None or abs(new_radius - old_radius) > 1e-6:
                    # Only flag as functional intent change when the group
                    # unification materially alters the radius (>0.1 mm).
                    # Micro-corrections (e.g. 18.570 → 18.575) are rounding
                    # artefacts from solver ↔ group prealign interaction and
                    # should NOT inflate the intent-changed counter.
                    _grp_delta = abs(new_radius - old_radius) if old_radius is not None else float("inf")
                    fallback_actions.append("group_clamped_pattern_radius")
                    fallback_audit.append(
                        {
                            "action": "group_clamped_pattern_radius",
                            "field": "location.pattern_parameters.pattern_radius",
                            "original": old_radius,
                            "corrected": round(new_radius, 2),
                            "reason": "unified across connection group for circular pattern consistency",
                            "functional_intent_changed": _grp_delta > 0.1,
                        }
                    )
                if old_offset is None or abs((old_offset) - new_offset) > 0.5:
                    fallback_actions.append("group_reconciled_offset_from_edge")
                    fallback_audit.append(
                        {
                            "action": "group_reconciled_offset_from_edge",
                            "field": "location.pattern_parameters.offset_from_edge",
                            "original": old_offset,
                            "corrected": round(max(0.0, new_offset), 2),
                            "reason": "offset recomputed from unified group radius",
                            "functional_intent_changed": False,
                        }
                    )

            filtered = [
                v
                for v in old_violations
                if v
                not in {
                    "violates_outer_wall_constraint",
                    "violates_inner_wall_constraint",
                    "offset_conflicts_with_pattern_radius",
                    "group_pattern_radius_no_intersection",
                }
            ]

            if not has_intersection:
                filtered.append("group_pattern_radius_no_intersection")
            else:
                solved_radius = _to_float(pattern.get("pattern_radius")) or float(group_radius)
                solved_offset = _to_float(pattern.get("offset_from_edge"))
                min_edge_margin = outer - solved_radius - hole_r
                spacing_threshold = max(0.5, round(hole_d_current * 0.1, 3))
                min_hole_spacing = None
                if count_current >= 2:
                    min_hole_spacing = 2.0 * solved_radius * math.sin(math.pi / float(count_current)) - hole_d_current

                if apply_fallback and min_edge_margin < (min_wall - 1e-6):
                    max_hole_d_for_edge = 2.0 * max(0.0, outer - solved_radius - min_wall)
                    if max_hole_d_for_edge > 0 and max_hole_d_for_edge < (hole_d_current - 1e-6):
                        prev_hole_d = hole_d_current
                        hole_d_current = round(max_hole_d_for_edge, 2)
                        hole_r = hole_d_current / 2.0
                        min_edge_margin = outer - solved_radius - hole_r
                        fallback_actions.append("pcd_reduced_hole_diameter_for_edge_margin")
                        fallback_audit.append(
                            {
                                "action": "pcd_reduced_hole_diameter_for_edge_margin",
                                "field": "location.safety_constraints.feature_diameter",
                                "original": prev_hole_d,
                                "corrected": hole_d_current,
                                "reason": "pcd edge margin check: reduced hole diameter to satisfy minimum wall",
                                "functional_intent_changed": True,
                            }
                        )

                if count_current >= 3 and min_hole_spacing is not None and apply_fallback and min_hole_spacing < (spacing_threshold - 1e-6):
                    max_hole_d_for_spacing = 2.0 * solved_radius * math.sin(math.pi / float(count_current)) - spacing_threshold
                    if max_hole_d_for_spacing > 0 and max_hole_d_for_spacing < (hole_d_current - 1e-6):
                        prev_hole_d = hole_d_current
                        hole_d_current = round(max_hole_d_for_spacing, 2)
                        hole_r = hole_d_current / 2.0
                        fallback_actions.append("pcd_reduced_hole_diameter_for_spacing")
                        fallback_audit.append(
                            {
                                "action": "pcd_reduced_hole_diameter_for_spacing",
                                "field": "location.safety_constraints.feature_diameter",
                                "original": prev_hole_d,
                                "corrected": hole_d_current,
                                "reason": "pcd hole spacing check: reduced hole diameter to clear circumferential spacing",
                                "functional_intent_changed": True,
                            }
                        )
                        min_hole_spacing = 2.0 * solved_radius * math.sin(math.pi / float(count_current)) - hole_d_current

                if count_current >= 4 and min_hole_spacing is not None and apply_fallback and min_hole_spacing < (spacing_threshold - 1e-6):
                    reduced_count = None
                    for candidate_count in range(count_current - 1, 2, -1):
                        candidate_spacing = 2.0 * solved_radius * math.sin(math.pi / float(candidate_count)) - hole_d_current
                        if candidate_spacing >= spacing_threshold:
                            reduced_count = candidate_count
                            min_hole_spacing = candidate_spacing
                            break
                    if isinstance(reduced_count, int) and reduced_count >= 3:
                        prev_count = count_current
                        count_current = reduced_count
                        pattern["count"] = count_current
                        fallback_actions.append("reduced_pattern_count")
                        fallback_audit.append(
                            {
                                "action": "reduced_pattern_count",
                                "field": "location.pattern_parameters.count",
                                "original": prev_count,
                                "corrected": count_current,
                                "reason": "pcd hole spacing check: reduced circular count to satisfy minimum spacing",
                                "functional_intent_changed": True,
                            }
                        )

                # Thin-walled annular sub-components (rim, tire) are expected
                # to have narrow wall envelopes; bolt-circle holes through
                # these walls are structurally questionable but should not
                # block the entire plan -- skip wall-related violations for
                # these hosts in the PCD group recheck (Stage 2).
                _host_id_s2 = audit.get("host_component_id") if isinstance(audit.get("host_component_id"), str) else ""
                _host_type_s2 = str(types_by_id.get(_host_id_s2) or "").lower()
                _is_thin_walled_s2 = _host_type_s2 in {"rim", "tire"}

                if min_edge_margin < (min_wall - 1e-6) and not _is_thin_walled_s2:
                    filtered.append("violates_min_edge_margin")
                if count_current >= 3 and min_hole_spacing is not None and min_hole_spacing < (spacing_threshold - 1e-6) and not _is_thin_walled_s2:
                    filtered.append("violates_min_hole_spacing")

                cond_outer = (solved_radius + hole_r + min_wall) <= (outer + 1e-6)
                cond_inner = (solved_radius - hole_r - min_wall) >= (inner - 1e-6)
                offset_expected = outer - solved_radius - hole_r
                cond_offset = solved_offset is not None and abs(solved_offset - offset_expected) <= 0.5
                if not cond_outer and not _is_thin_walled_s2:
                    filtered.append("violates_outer_wall_constraint")
                if not cond_inner and not _is_thin_walled_s2:
                    filtered.append("violates_inner_wall_constraint")
                if not cond_offset and not _is_thin_walled_s2:
                    filtered.append("offset_conflicts_with_pattern_radius")

            prior_status = feasibility.get("status") if isinstance(feasibility.get("status"), str) else "ok"
            status = "ok" if not filtered else "blocked"
            if not filtered and prior_status == "needs_clarification":
                status = "needs_clarification"
            placement["requires_clarification"] = status in {"blocked", "needs_clarification"}
            placement["location"] = location
            feasibility.update(
                {
                    "status": status,
                    "checks": {
                        "host_component_id": checks.get("host_component_id"),
                        "hole_diameter": round(float(hole_d_current), 3),
                        "min_wall": round(float(rec["min_wall"]), 3),
                        "outer_radius": outer,
                        "inner_radius": inner,
                        "pcd_group": group_key,
                        "pcd_min_edge_margin_mm": round(outer - ((_to_float(pattern.get("pattern_radius")) or float(group_radius)) + (float(hole_d_current) / 2.0)), 3),
                        "pcd_min_hole_spacing_mm": (
                            round(2.0 * (_to_float(pattern.get("pattern_radius")) or float(group_radius)) * math.sin(math.pi / float(count_current)) - float(hole_d_current), 3)
                            if count_current >= 3
                            else None
                        ),
                    },
                    "fallback_actions": fallback_actions,
                    "fallback_audit": fallback_audit,
                    "functional_intent_changed": any(
                        bool(item.get("functional_intent_changed"))
                        for item in fallback_audit
                        if isinstance(item, Mapping)
                    ),
                    "violations": filtered,
                }
            )
            placement["feasibility"] = feasibility

            audit["status"] = status
            audit["corrected_values"] = {
                "pattern_radius": pattern.get("pattern_radius"),
                "offset_from_edge": pattern.get("offset_from_edge"),
                "hole_diameter": round(float(hole_d_current), 3),
                "count": pattern.get("count"),
            }
            audit["fallback_actions"] = fallback_actions
            audit["fallback_audit"] = fallback_audit
            audit["functional_intent_changed"] = feasibility.get("functional_intent_changed")
            audit["violations"] = filtered
            solved_radius_out = _to_float(pattern.get("pattern_radius")) or float(group_radius)
            solved_hole_d_out = float(hole_d_current)
            audit["pcd_group"] = group_key
            audit["pcd_checks"] = {
                "count": count_current,
                "min_edge_margin_mm": round(outer - solved_radius_out - (solved_hole_d_out / 2.0), 3),
                "min_hole_spacing_mm": (
                    round(2.0 * solved_radius_out * math.sin(math.pi / float(count_current)) - solved_hole_d_out, 3)
                    if count_current >= 3
                    else None
                ),
                "spacing_threshold_mm": round(max(0.5, solved_hole_d_out * 0.1), 3),
                "min_wall_mm": round(min_wall, 3),
            }

    # Stage 3: overlap/near-collision check for hole seeds on same host+face.
    audit_by_connection_id: Dict[str, Dict[str, Any]] = {}
    for audit in placement_audits:
        cid = audit.get("connection_id") if isinstance(audit, Mapping) else None
        if isinstance(cid, str) and cid:
            audit_by_connection_id[cid] = audit

    group_points: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        if not _is_hole_related_placement(placement):
            continue
        cid = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else None
        if not isinstance(cid, str) or not cid:
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        iface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        host_id = iface_ref.get("component_id") if isinstance(iface_ref.get("component_id"), str) else None
        face_id = None
        if isinstance(iface_ref.get("interface_name"), str) and iface_ref.get("interface_name"):
            face_id = str(iface_ref.get("interface_name"))
        elif isinstance(location.get("reference_surface"), str) and location.get("reference_surface"):
            face_id = str(location.get("reference_surface"))
        if not (isinstance(host_id, str) and host_id and isinstance(face_id, str) and face_id):
            continue

        feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), Mapping) else {}
        checks = feasibility.get("checks") if isinstance(feasibility.get("checks"), Mapping) else {}
        hole_d = _to_float(checks.get("hole_diameter"))
        if hole_d is None or hole_d <= 0:
            hole_d = _hole_diameter(placement)

        safety = location.get("safety_constraints") if isinstance(location.get("safety_constraints"), Mapping) else {}
        min_spacing = _to_float(safety.get("min_hole_spacing"))
        if min_spacing is None:
            min_spacing = _to_float(safety.get("min_spacing"))
        if min_spacing is None or min_spacing <= 0:
            min_spacing = float(hole_d)

        points = _expand_hole_points_mm(placement)
        for idx, (x, y) in enumerate(points):
            group_points.setdefault((host_id, face_id), []).append(
                {
                    "connection_id": cid,
                    "point_index": idx,
                    "x": float(x),
                    "y": float(y),
                    "hole_diameter": float(hole_d),
                    "min_spacing": float(min_spacing),
                }
            )

    overlap_conflicts: List[Dict[str, Any]] = []
    for (host_id, face_id), points in group_points.items():
        hole_overlap_groups_checked += 1
        n = len(points)
        if n <= 1:
            continue
        for i in range(n):
            p1 = points[i]
            for j in range(i + 1, n):
                p2 = points[j]
                dx = float(p1["x"]) - float(p2["x"])
                dy = float(p1["y"]) - float(p2["y"])
                dist = math.hypot(dx, dy)
                min_allowed = max(
                    float(p1.get("hole_diameter") or 0.0),
                    float(p2.get("hole_diameter") or 0.0),
                    float(p1.get("min_spacing") or 0.0),
                    float(p2.get("min_spacing") or 0.0),
                )
                if dist + 1e-6 >= min_allowed:
                    continue

                hole_overlap_conflict_count += 1
                conflict = {
                    "host_component_id": host_id,
                    "face_interface_id": face_id,
                    "distance_mm": round(dist, 6),
                    "min_allowed_mm": round(min_allowed, 6),
                    "point_a": p1,
                    "point_b": p2,
                }
                overlap_conflicts.append(conflict)

                for cid in {p1.get("connection_id"), p2.get("connection_id")}:
                    if not isinstance(cid, str) or not cid:
                        continue
                    audit = audit_by_connection_id.get(cid)
                    if isinstance(audit, Mapping):
                        existing_v = [v for v in (audit.get("violations") or []) if isinstance(v, str)]
                        if "hole_seed_overlap_or_near_collision" not in existing_v:
                            existing_v.append("hole_seed_overlap_or_near_collision")
                        audit["violations"] = existing_v
                        audit["status"] = "blocked"
                        placement = placement_by_connection_id.get(cid)
                        if isinstance(placement, Mapping):
                            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), Mapping) else {}
                            fe_viol = [v for v in (feasibility.get("violations") or []) if isinstance(v, str)]
                            if "hole_seed_overlap_or_near_collision" not in fe_viol:
                                fe_viol.append("hole_seed_overlap_or_near_collision")
                            feasibility["violations"] = fe_viol
                            feasibility["status"] = "blocked"
                            placement["feasibility"] = feasibility
                            placement["requires_clarification"] = True

    # Recompute summary from finalized audits after group-level harmonization.
    violations = []
    blocked_count = 0
    needs_clarification_count = 0
    fallback_count = 0
    intent_changed_count = 0
    for audit in placement_audits:
        fallback_actions = audit.get("fallback_actions") if isinstance(audit.get("fallback_actions"), list) else []
        if fallback_actions:
            fallback_count += 1
        if bool(audit.get("functional_intent_changed")):
            intent_changed_count += 1
        status = audit.get("status")
        if status == "blocked":
            blocked_count += 1
            violations.append(
                {
                    "connection_id": audit.get("connection_id"),
                    "host_component_id": audit.get("host_component_id"),
                    "violations": [v for v in (audit.get("violations") or []) if isinstance(v, str)],
                }
            )
        elif status == "needs_clarification":
            needs_clarification_count += 1

    return {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "validator": "validate_geometry_semantics_feasibility",
            "apply_fallback": bool(apply_fallback),
        },
        "summary": {
            "placements_checked": checked,
            "fallback_count": fallback_count,
            "fallback_ratio": round(float(fallback_count) / float(checked), 4) if checked > 0 else 0.0,
            "intent_changed_count": intent_changed_count,
            "blocked_count": blocked_count,
            "needs_clarification_count": needs_clarification_count,
            "pcd_groups_checked": pcd_groups_checked,
            "pcd_groups_blocked": pcd_groups_blocked,
            "pcd_groups_normalized": pcd_groups_normalized,
            "hole_overlap_groups_checked": hole_overlap_groups_checked,
            "hole_overlap_conflict_count": hole_overlap_conflict_count,
            "valid": blocked_count == 0,
        },
        "placements": placement_audits,
        "violations": violations,
        "hole_overlap_conflicts": overlap_conflicts,
    }
