from __future__ import annotations

from typing import Any, Dict, Mapping


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            return None
    return None


def estimate_outer_radius(host_dims: Mapping[str, Any]) -> float | None:
    for key in ("outer_radius", "radius"):
        val = _to_float(host_dims.get(key))
        if val is not None and val > 0:
            return val
    for key in ("outer_diameter", "diameter"):
        val = _to_float(host_dims.get(key))
        if val is not None and val > 0:
            return val / 2.0

    width = _to_float(host_dims.get("width") or host_dims.get("arm_width"))
    length = _to_float(
        host_dims.get("length") or host_dims.get("arm_length") or host_dims.get("height") or host_dims.get("depth")
    )
    if width is not None and width > 0 and length is not None and length > 0:
        return min(width, length) / 2.0
    return None


def estimate_inner_radius(host_dims: Mapping[str, Any]) -> float:
    candidates = [0.0]
    for key in ("inner_radius", "bore_radius"):
        val = _to_float(host_dims.get(key))
        if val is not None and val >= 0:
            candidates.append(val)
    for key in ("inner_diameter", "bore_diameter", "hole_diameter", "shaft_hole_diameter"):
        val = _to_float(host_dims.get(key))
        if val is not None and val >= 0:
            candidates.append(val / 2.0)
    return max(candidates)


def _planar_span(host_dims: Mapping[str, Any]) -> float | None:
    width = _to_float(host_dims.get("width") or host_dims.get("arm_width"))
    length = _to_float(
        host_dims.get("length") or host_dims.get("arm_length") or host_dims.get("height") or host_dims.get("depth")
    )
    valid = [v for v in (width, length) if isinstance(v, (int, float)) and v > 0]
    if not valid:
        return None
    return max(valid)


def solve_circular_pattern(
    host_dims: Mapping[str, Any],
    hole_diameter: float,
    min_wall: float,
    preferred_radius_mm: float | None,
) -> Dict[str, Any]:
    fallback_actions: list[str] = []

    hole_d = float(hole_diameter) if isinstance(hole_diameter, (int, float)) and hole_diameter > 0 else 5.0
    wall = float(min_wall) if isinstance(min_wall, (int, float)) and min_wall >= 0 else max(1.0, round(hole_d * 0.125, 2))

    outer = estimate_outer_radius(host_dims)
    inner = estimate_inner_radius(host_dims)
    if outer is None:
        return {
            "status": "needs_clarification",
            "radius_mm": None,
            "r_min": None,
            "r_max": None,
            "outer_radius_mm": None,
            "inner_radius_mm": inner,
            "edge_margin_mm": None,
            "hole_diameter_mm": hole_d,
            "fallback_actions": ["requires_mounting_pad"],
        }

    hole_r = hole_d / 2.0
    r_min = inner + hole_r + wall
    r_max = outer - hole_r - wall

    if r_max < r_min:
        max_hole_r = (outer - inner - 2.0 * wall) / 2.0
        if max_hole_r > 0 and max_hole_r < hole_r:
            hole_r = max_hole_r
            hole_d = round(hole_r * 2.0, 2)
            fallback_actions.append("reduced_hole_diameter")
            r_min = inner + hole_r + wall
            r_max = outer - hole_r - wall

    if r_max < r_min:
        return {
            "status": "needs_clarification",
            "radius_mm": None,
            "r_min": round(r_min, 3),
            "r_max": round(r_max, 3),
            "outer_radius_mm": round(outer, 3),
            "inner_radius_mm": round(inner, 3),
            "edge_margin_mm": None,
            "hole_diameter_mm": hole_d,
            "fallback_actions": fallback_actions + ["requires_mounting_pad"],
        }

    preferred = _to_float(preferred_radius_mm)
    if preferred is None:
        radius = (r_min + r_max) / 2.0
        fallback_actions.append("synthesized_pattern_radius")
    else:
        radius = preferred

    clamped = min(max(radius, r_min), r_max)
    if abs(clamped - radius) > 1e-6:
        fallback_actions.append("clamped_pattern_radius")
    radius = clamped

    return {
        "status": "ok",
        "radius_mm": round(radius, 3),
        "r_min": round(r_min, 3),
        "r_max": round(r_max, 3),
        "outer_radius_mm": round(outer, 3),
        "inner_radius_mm": round(inner, 3),
        "edge_margin_mm": round(max(0.0, outer - radius - hole_r), 3),
        "hole_diameter_mm": hole_d,
        "fallback_actions": fallback_actions,
    }


def solve_linear_pattern(
    host_dims: Mapping[str, Any],
    hole_diameter: float,
    min_wall: float,
    count: int,
) -> Dict[str, Any]:
    fallback_actions: list[str] = []

    hole_d = float(hole_diameter) if isinstance(hole_diameter, (int, float)) and hole_diameter > 0 else 5.0
    wall = float(min_wall) if isinstance(min_wall, (int, float)) and min_wall >= 0 else max(1.0, round(hole_d * 0.125, 2))
    cnt = int(count) if isinstance(count, int) and count > 0 else 1

    span = _planar_span(host_dims)
    if span is None:
        return {
            "status": "needs_clarification",
            "pitch_mm": None,
            "count": cnt,
            "span_mm": None,
            "edge_margin_mm": None,
            "hole_diameter_mm": hole_d,
            "fallback_actions": ["requires_host_planar_span"],
        }

    edge_margin = max(5.0, hole_d * 2.5, wall)
    min_pitch = max(hole_d + 2.0 * wall, 1.0)
    denom = max(cnt - 1, 1)
    raw_pitch = (span - 2.0 * edge_margin) / float(denom)
    pitch = max(raw_pitch, min_pitch)

    if raw_pitch < min_pitch:
        fallback_actions.append("raised_pitch_to_minimum")

    return {
        "status": "ok",
        "pitch_mm": round(pitch, 3),
        "count": cnt,
        "span_mm": round(span, 3),
        "edge_margin_mm": round(edge_margin, 3),
        "hole_diameter_mm": hole_d,
        "fallback_actions": fallback_actions,
    }
