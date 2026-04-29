"""
Resolve standard parts from knowledge_graph into planning artifacts.

This is a deterministic, rule-based pass. It does not use any AI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from tools.catalog.bearing_catalog import find_bearing_by_designation


FUSION_FASTENER_UI_CATEGORIES: set[str] = {
    "bolt",
    "screw",
    "nut",
    "washer",
    "rivet",
}


def _strict_resolver_enabled() -> bool:
    return any(
        os.getenv(key, "0").strip() == "1"
        for key in ("PIPELINE_STRICT_RESOLVER", "PIPELINE_STRICT", "PIPELINE_STRICT_ASSEMBLY")
    )


def _enforce_unique_component_names(resolved: List[Dict[str, Any]], *, strict_mode: bool) -> None:
    if not strict_mode:
        return
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in resolved:
        if not isinstance(row, Mapping):
            continue
        name = row.get("component_name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized = name.strip()
        if normalized in seen:
            duplicates.add(normalized)
            continue
        seen.add(normalized)
    if duplicates:
        dup_list = ", ".join(sorted(duplicates))
        raise ValueError(f"[Resolver Strict] duplicate resolved component_name(s): {dup_list}")


# === Minimal ISO / Metric fastener interface rules (deterministic) ===
# NOTE: This is intentionally a small, pragmatic table (M2-M12) to avoid
#       generating "nominal+0.5" style guessed diameters downstream.
#       When unknown, the resolver leaves fields as None and downstream falls back.

_METRIC_COARSE_PITCH_MM: dict[float, float] = {
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


# ISO 273 typical clearance holes (close/normal/loose). Values in mm.
_ISO273_CLEARANCE_HOLES_MM: dict[float, dict[str, float]] = {
    2.0: {"close": 2.2, "normal": 2.4, "loose": 2.6},
    2.5: {"close": 2.7, "normal": 2.9, "loose": 3.1},
    3.0: {"close": 3.2, "normal": 3.4, "loose": 3.6},
    4.0: {"close": 4.3, "normal": 4.5, "loose": 4.8},
    5.0: {"close": 5.3, "normal": 5.5, "loose": 5.8},
    6.0: {"close": 6.4, "normal": 6.6, "loose": 7.0},
    8.0: {"close": 8.4, "normal": 9.0, "loose": 10.0},
    10.0: {"close": 10.5, "normal": 11.0, "loose": 12.0},
    12.0: {"close": 13.0, "normal": 13.5, "loose": 14.5},
}


# ISO 4762 socket head cap screw (SHCS) head sizes (approx). Values in mm.
_ISO4762_SOCKET_HEAD_MM: dict[float, dict[str, float]] = {
    3.0: {"head_diameter": 5.5, "head_height": 3.0},
    4.0: {"head_diameter": 7.0, "head_height": 4.0},
    5.0: {"head_diameter": 8.5, "head_height": 5.0},
    6.0: {"head_diameter": 10.0, "head_height": 6.0},
    8.0: {"head_diameter": 13.0, "head_height": 8.0},
    10.0: {"head_diameter": 16.0, "head_height": 10.0},
    12.0: {"head_diameter": 18.0, "head_height": 12.0},
}


_FASTENER_STANDARD_CANDIDATES_BY_CATEGORY: dict[str, list[str]] = {
    "fastener": ["ISO4017", "DIN933", "GB/T5783"],
    "bolt": ["ISO4017", "DIN933", "GB/T5783"],
    "screw": ["ISO4762", "DIN912", "GB/T70.1"],
    "nut": ["ISO4035", "DIN934", "GB/T6170"],
    "washer": ["ISO7089", "DIN125-1", "GB/T97.1"],
    "rivet": ["ISO15977", "DIN7337", "GB/T12615"],
}


def _normalize_standard_token(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().upper().replace(" ", "")
    if not token:
        return None
    aliases = {
        "DIN933": "DIN933",
        "DIN912": "DIN912",
        "DIN934": "DIN934",
        "DIN125": "DIN125-1",
        "ISO4017": "ISO4017",
        "ISO4762": "ISO4762",
        "ISO4032": "ISO4035",
        "ISO4035": "ISO4035",
        "ISO7089": "ISO7089",
        "ISO15977": "ISO15977",
        "GBT5783": "GB/T5783",
        "GBT70.1": "GB/T70.1",
        "GBT6170": "GB/T6170",
        "GBT97.1": "GB/T97.1",
        "GBT12615": "GB/T12615",
    }
    return aliases.get(token, token)


def _resolve_fastener_standard(*, category: str, designation: str, parsed_standard: str | None) -> Dict[str, Any]:
    cat = category.strip().lower()
    candidates = list(_FASTENER_STANDARD_CANDIDATES_BY_CATEGORY.get(cat) or _FASTENER_STANDARD_CANDIDATES_BY_CATEGORY["fastener"])
    parsed_norm = _normalize_standard_token(parsed_standard)
    if parsed_norm:
        if parsed_norm not in candidates:
            candidates = [parsed_norm, *candidates]
        return {
            "standard": parsed_norm,
            "standard_candidates": candidates,
            "standard_confidence": 0.95,
            "standard_source": "designation_prefix",
        }

    text = designation.strip().upper().replace(" ", "")
    inferred = None
    for key in ("ISO4762", "DIN912", "ISO4017", "DIN933", "ISO4032", "DIN934", "ISO7089", "DIN125", "ISO15977", "DIN7337"):
        if key in text:
            inferred = _normalize_standard_token(key)
            break

    if inferred:
        if inferred not in candidates:
            candidates = [inferred, *candidates]
        return {
            "standard": inferred,
            "standard_candidates": candidates,
            "standard_confidence": 0.8,
            "standard_source": "designation_keyword",
        }

    chosen = candidates[0] if candidates else None
    return {
        "standard": chosen,
        "standard_candidates": candidates,
        "standard_confidence": 0.55 if chosen else 0.0,
        "standard_source": "category_default",
    }


def _closest_key(value: float, table: Mapping[float, Any]) -> float:
    return min(table.keys(), key=lambda k: abs(float(k) - float(value)))


def _infer_fastener_head_style(*, standard: str | None, designation: str) -> tuple[str, str]:
    """Infer head style with a deterministic heuristic.

    Returns (head_style, reason).
    """
    text = f"{standard or ''} {designation}".strip().lower()
    if any(tok in text for tok in ("csk", "countersunk", "flat head", "flat-head", "din 7991", "iso 10642")):
        return "countersunk", "inferred_from_designation"
    if any(tok in text for tok in ("hex", "iso4017", "din933", "din 933", "iso 4017")):
        return "hex_head", "inferred_from_standard"
    if any(tok in text for tok in ("socket", "shcs", "iso4762", "din912", "din 912", "iso 4762")):
        return "socket_head_cap_screw", "inferred_from_standard"
    # Default aligns with existing downstream assumption (_head_seat_dimensions in Agent2).
    return "socket_head_cap_screw", "default_assumption"


def _build_fastener_interface(
    *,
    nominal_mm: float,
    standard: str | None,
    designation: str,
) -> Dict[str, Any]:
    pitch = None
    if _METRIC_COARSE_PITCH_MM:
        closest = _closest_key(nominal_mm, _METRIC_COARSE_PITCH_MM)
        pitch = float(_METRIC_COARSE_PITCH_MM[closest])

    clearance = None
    if _ISO273_CLEARANCE_HOLES_MM:
        closest = _closest_key(nominal_mm, _ISO273_CLEARANCE_HOLES_MM)
        clearance = dict(_ISO273_CLEARANCE_HOLES_MM[closest])

    tap_drill = None
    if pitch is not None:
        # Common shop approximation: tap_drill ~= nominal - pitch
        tap_drill = round(float(nominal_mm) - float(pitch), 2)

    head_style, head_reason = _infer_fastener_head_style(standard=standard, designation=designation)
    counterbore = None
    if head_style == "socket_head_cap_screw" and _ISO4762_SOCKET_HEAD_MM:
        closest = _closest_key(nominal_mm, _ISO4762_SOCKET_HEAD_MM)
        dims = _ISO4762_SOCKET_HEAD_MM[closest]
        counterbore = {
            "diameter_mm": float(dims["head_diameter"]),
            "depth_mm": float(dims["head_height"]),
            "standard": "ISO4762",
        }

    return {
        "thread": {
            "series": "M",
            "nominal_diameter_mm": float(nominal_mm),
            "pitch_mm": pitch,
            "hand": "right",
            "note": "coarse_pitch_assumed_when_available",
        },
        "clearance_hole_mm": clearance,
        "tap_drill_mm": tap_drill,
        "head_style": head_style,
        "head_style_reason": head_reason,
        "counterbore": counterbore,
    }


def _normalize_fusion_fastener_category(category: str) -> tuple[str, str | None]:
    cat = category.strip().lower()
    if cat in FUSION_FASTENER_UI_CATEGORIES:
        return cat, None
    # Fusion fastener UI has no explicit pin/stud buckets; map to bolt/screw family.
    if cat in {"pin", "stud"}:
        return "screw", f"normalized_from_{cat}"
    return cat, None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_manifest(path: Path) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_designation: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return by_id, by_designation
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        return by_id, by_designation
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return by_id, by_designation
    for row in parts:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        pid = item.get("id")
        if isinstance(pid, str) and pid.strip():
            by_id[pid.strip()] = item
        des = item.get("designation")
        if isinstance(des, str) and des.strip():
            by_designation[des.strip().lower()] = item
    return by_id, by_designation


def _load_parts_index(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        return []
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in parts:
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def _fmt_num(value: float | None) -> str | None:
    if value is None:
        return None
    if abs(value - int(value)) < 1e-6:
        return str(int(value))
    return f"{value:g}"


def _parse_fastener_designation(text: str) -> Tuple[str | None, float | None, float | None, str | None]:
    pattern = re.compile(r"\bM\s*(\d+(?:\.\d+)?)\s*(?:[xX]\s*(\d+(?:\.\d+)?))?")
    match = pattern.search(text)
    if not match:
        return None, None, None, None

    nominal = float(match.group(1))
    length = float(match.group(2)) if match.group(2) else None
    standard = text[: match.start()].strip() or None

    size = None
    nominal_txt = _fmt_num(nominal)
    if nominal_txt:
        size = f"M{nominal_txt}"
        if length is not None:
            length_txt = _fmt_num(length)
            size = f"{size}x{length_txt}" if length_txt else size

    return standard, nominal, length, size


def _format_metric_size(nominal: float | None, length: float | None) -> str | None:
    if not isinstance(nominal, (int, float)):
        return None
    nominal_s = _fmt_num(float(nominal))
    if not nominal_s:
        return None
    base = f"M{nominal_s}"
    if isinstance(length, (int, float)):
        length_s = _fmt_num(float(length))
        if length_s:
            return f"{base}x{length_s}"
    return base


def _nearest_fastener_rows(
    rows: List[Dict[str, Any]],
    *,
    requested_nominal_mm: float | None,
    requested_length_mm: float | None,
) -> tuple[List[Dict[str, Any]], str]:
    if not rows:
        return [], "no_candidates"

    filtered = list(rows)
    strategy = "family_filtered"

    if isinstance(requested_nominal_mm, (int, float)):
        # 1) Exact nominal match first.
        exact = [
            r
            for r in filtered
            if isinstance(r.get("nominal_diameter_mm"), (int, float))
            and abs(float(r.get("nominal_diameter_mm")) - float(requested_nominal_mm)) <= 0.25
        ]
        if exact:
            filtered = exact
            strategy = "nominal_exact"
        else:
            # 2) Hard nearest nominal (do NOT drop diameter filtering).
            nominal_values = sorted(
                {
                    float(r.get("nominal_diameter_mm"))
                    for r in filtered
                    if isinstance(r.get("nominal_diameter_mm"), (int, float))
                }
            )
            if nominal_values:
                nearest_nominal = min(
                    nominal_values,
                    key=lambda v: abs(float(v) - float(requested_nominal_mm)),
                )
                filtered = [
                    r
                    for r in filtered
                    if isinstance(r.get("nominal_diameter_mm"), (int, float))
                    and abs(float(r.get("nominal_diameter_mm")) - float(nearest_nominal)) <= 1e-6
                ]
                strategy = "nominal_nearest"

    # 3) Length nearest within nominal subset.
    if isinstance(requested_length_mm, (int, float)):
        with_length = [r for r in filtered if isinstance(r.get("length_mm"), (int, float))]
        if with_length:
            nearest_length = min(
                [float(r.get("length_mm")) for r in with_length],
                key=lambda v: abs(float(v) - float(requested_length_mm)),
            )
            filtered = [
                r
                for r in with_length
                if abs(float(r.get("length_mm")) - float(nearest_length)) <= 1e-6
            ]
            strategy = f"{strategy}+length_nearest"

    return filtered, strategy


def _parse_bearing_designation(text: str) -> Tuple[float | None, float | None, float | None]:
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)")
    match = pattern.search(text)
    if match:
        inner = float(match.group(1))
        outer = float(match.group(2))
        width = float(match.group(3))
        return inner, outer, width

    catalog_item = find_bearing_by_designation(text)
    if catalog_item:
        return (
            float(catalog_item["bore"]),
            float(catalog_item["outer"]),
            float(catalog_item["width"]),
        )

    return None, None, None


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except Exception:
        return default


def _coerce_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, (str, int, float))]


def _resolve_standard_parts(
    kg: Mapping[str, Any],
    *,
    parts_index: List[Dict[str, Any]],
    part_library_root: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    resolved: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    parts = kg.get("standard_parts", [])
    if not isinstance(parts, list):
        return resolved, unresolved

    components = kg.get("components", [])
    comp_by_id: Dict[str, Mapping[str, Any]] = {}
    for comp in components:
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str):
            comp_by_id[str(comp["id"])] = comp

    conn_by_id: Dict[str, Mapping[str, Any]] = {}
    for cr in kg.get("connection_requirements", []) or []:
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str):
            conn_by_id[str(cr["id"])] = cr

    type_by_id = {cid: comp_by_id[cid].get("type") for cid in comp_by_id}

    fastener_kind_categories: set[str] = set(FUSION_FASTENER_UI_CATEGORIES)

    # Detect which standard-part categories can be inserted based on capability registry.
    registry_path = Path("functions") / "functions.json"
    supported_insert: set[str] = set()
    supports_fastener_gateway = False
    try:
        reg = _read_json(registry_path)
        if isinstance(reg, Mapping):
            supports_fastener_gateway = "INSERT_FASTENER_R1" in reg
            for name in reg.keys():
                if not isinstance(name, str):
                    continue
                m = re.match(r"^INSERT_([A-Z0-9_]+)_R1$", name)
                if m:
                    supported_insert.add(m.group(1).lower())
    except Exception:
        supported_insert = set()
        supports_fastener_gateway = False

    def _index_by_family(family: str) -> List[Dict[str, Any]]:
        fam = family.strip().lower()
        return [row for row in parts_index if str(row.get("family", "")).strip().lower() == fam]

    def _pick_preferred(rows: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not rows:
            return None
        return sorted(
            rows,
            key=lambda r: (
                0 if str(r.get("lod", "")).strip().lower() == "simplified" else 1,
                str(r.get("part_id", "")),
            ),
        )[0]

    def _to_float(v: Any) -> float | None:
        if isinstance(v, (int, float)):
            return float(v)
        return None

    for part in parts:
        if not isinstance(part, Mapping):
            continue

        part_id = part.get("id")
        category = part.get("category")
        designation = part.get("designation")
        quantity = _coerce_int(part.get("quantity", 1), 1)
        applied_to = _coerce_list(part.get("applied_to"))
        rationale = part.get("selection_rationale")

        explicit_bound_component_ids = _coerce_list(part.get("bound_component_ids"))
        bound_component_ids: List[str] = [cid for cid in explicit_bound_component_ids if isinstance(cid, str) and cid]
        if not bound_component_ids:
            if isinstance(part_id, str) and part_id in comp_by_id:
                bound_component_ids.append(part_id)

            applied_conn_ids = [cid for cid in applied_to if cid in conn_by_id]
            if applied_conn_ids:
                if str(category).strip().lower() == "fastener":
                    for conn_id in applied_conn_ids:
                        cr = conn_by_id.get(conn_id, {})
                        decision = cr.get("connection_decision")
                        if isinstance(decision, Mapping):
                            ref = decision.get("fastener_ref_component_id")
                            if isinstance(ref, str) and type_by_id.get(ref) in {"fastener", "fastener_set"}:
                                bound_component_ids.append(ref)
                if str(category).strip().lower() == "bearing":
                    for conn_id in applied_conn_ids:
                        cr = conn_by_id.get(conn_id, {})
                        between = cr.get("between", [])
                        if isinstance(between, list):
                            for cid in between:
                                if isinstance(cid, str) and type_by_id.get(cid) == "bearing":
                                    bound_component_ids.append(cid)

        bound_component_ids = sorted({cid for cid in bound_component_ids})

        base = {
            "id": part_id,
            "category": category,
            "designation": designation,
            "quantity": quantity,
            "applied_to": applied_to,
            "selection_rationale": rationale,
            "bound_component_ids": bound_component_ids,
        }

        if not isinstance(category, str) or not isinstance(designation, str):
            unresolved.append({**base, "reason": "missing_category_or_designation"})
            continue

        category = category.strip().lower()
        designation = designation.strip()

        if category == "fastener":
            standard, nominal, length, size = _parse_fastener_designation(designation)
            if nominal is None:
                unresolved.append({**base, "reason": "unparsed_fastener_designation"})
                continue
            std_info = _resolve_fastener_standard(
                category=category,
                designation=designation,
                parsed_standard=standard,
            )
            std_value = std_info.get("standard")
            if not isinstance(std_value, str) or not std_value:
                unresolved.append({**base, "reason": "unresolved_fastener_standard", "standard_candidates": std_info.get("standard_candidates", [])})
                continue

            family_candidates = _index_by_family("fastener")
            if not family_candidates:
                unresolved.append({**base, "reason": "no_candidate_in_family"})
                continue

            filtered = list(family_candidates)
            size_token = str(size).strip().upper() if isinstance(size, str) else None
            if size_token:
                matched = [r for r in filtered if str(r.get("size", "")).strip().upper() == size_token]
                if matched:
                    filtered = matched
            std_norm = _normalize_standard_token(std_value)
            if isinstance(std_norm, str) and std_norm:
                matched = [r for r in filtered if _normalize_standard_token(str(r.get("standard", ""))) == std_norm]
                if matched:
                    filtered = matched
            filtered, nearest_strategy = _nearest_fastener_rows(
                filtered,
                requested_nominal_mm=nominal,
                requested_length_mm=length,
            )

            match_strategy = f"family_size_standard+{nearest_strategy}"

            index_item = _pick_preferred(filtered)
            if not isinstance(index_item, Mapping):
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            cad_relpath = index_item.get("cad_relpath")
            index_part_id = index_item.get("part_id") if isinstance(index_item.get("part_id"), str) else None
            if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            library_file_abs_path = str((part_library_root / cad_relpath).resolve())

            resolved_nominal = _to_float(index_item.get("nominal_diameter_mm"))
            resolved_length = _to_float(index_item.get("length_mm"))
            resolved_standard = (
                str(index_item.get("standard")).strip()
                if isinstance(index_item.get("standard"), str) and str(index_item.get("standard")).strip()
                else std_value
            )
            resolved_size = _format_metric_size(resolved_nominal, resolved_length) or str(index_item.get("size") or size or "").strip()
            resolved_designation = (
                f"{resolved_standard} {resolved_size}".strip()
                if isinstance(resolved_standard, str) and resolved_standard and resolved_size
                else (resolved_size or designation)
            )

            resolved.append(
                {
                    **base,
                    "requested_designation": designation,
                    "resolved_designation": resolved_designation,
                    "designation": resolved_designation,
                    "part_id": index_part_id,
                    "cad_relpath": cad_relpath,
                    "library_file_abs_path": library_file_abs_path,
                    "match_strategy": match_strategy,
                    "category": "fastener",
                    "standard": resolved_standard,
                    "standard_candidates": std_info.get("standard_candidates", []),
                    "standard_confidence": std_info.get("standard_confidence"),
                    "standard_source": std_info.get("standard_source"),
                    "size": resolved_size,
                    "fastener": {
                        "nominal_diameter_mm": resolved_nominal,
                        "length_mm": resolved_length,
                    },
                    "fastener_interface": _build_fastener_interface(
                        nominal_mm=float(resolved_nominal if isinstance(resolved_nominal, (int, float)) else nominal),
                        standard=resolved_standard,
                        designation=resolved_designation,
                    ),
                }
            )
            continue

        normalized_category, normalization_note = _normalize_fusion_fastener_category(category)

        if normalized_category in fastener_kind_categories and supports_fastener_gateway:
            standard, nominal, length, size = _parse_fastener_designation(designation)
            std_info = _resolve_fastener_standard(
                category=normalized_category,
                designation=designation,
                parsed_standard=standard,
            )
            std_value = std_info.get("standard")
            if not isinstance(std_value, str) or not std_value:
                unresolved.append({**base, "reason": "unresolved_fastener_standard", "standard_candidates": std_info.get("standard_candidates", [])})
                continue

            family_candidates = _index_by_family("fastener")
            if not family_candidates:
                unresolved.append({**base, "reason": "no_candidate_in_family"})
                continue
            kind_candidates = [r for r in family_candidates if str(r.get("kind", "")).strip().lower() == normalized_category]
            if not kind_candidates:
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            filtered = list(kind_candidates)
            size_token = str(size).strip().upper() if isinstance(size, str) else None
            if size_token:
                matched = [r for r in filtered if str(r.get("size", "")).strip().upper() == size_token]
                if matched:
                    filtered = matched
            std_norm = _normalize_standard_token(std_value)
            if isinstance(std_norm, str) and std_norm:
                matched = [r for r in filtered if _normalize_standard_token(str(r.get("standard", ""))) == std_norm]
                if matched:
                    filtered = matched
            filtered, nearest_strategy = _nearest_fastener_rows(
                filtered,
                requested_nominal_mm=nominal,
                requested_length_mm=length,
            )

            index_item = _pick_preferred(filtered)
            if not isinstance(index_item, Mapping):
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            cad_relpath = index_item.get("cad_relpath")
            index_part_id = index_item.get("part_id") if isinstance(index_item.get("part_id"), str) else None
            if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            library_file_abs_path = str((part_library_root / cad_relpath).resolve())

            resolved_nominal = _to_float(index_item.get("nominal_diameter_mm"))
            resolved_length = _to_float(index_item.get("length_mm"))
            resolved_standard = (
                str(index_item.get("standard")).strip()
                if isinstance(index_item.get("standard"), str) and str(index_item.get("standard")).strip()
                else std_value
            )
            resolved_size = _format_metric_size(resolved_nominal, resolved_length) or str(index_item.get("size") or size or "").strip()
            resolved_designation = (
                f"{resolved_standard} {resolved_size}".strip()
                if isinstance(resolved_standard, str) and resolved_standard and resolved_size
                else (resolved_size or designation)
            )

            payload: Dict[str, Any] = {
                **base,
                "requested_designation": designation,
                "resolved_designation": resolved_designation,
                "designation": resolved_designation,
                "part_id": index_part_id,
                "cad_relpath": cad_relpath,
                "library_file_abs_path": library_file_abs_path,
                "match_strategy": f"family_kind_size_standard+{nearest_strategy}",
                "category": normalized_category,
                "standard": resolved_standard,
                "standard_candidates": std_info.get("standard_candidates", []),
                "standard_confidence": std_info.get("standard_confidence"),
                "standard_source": std_info.get("standard_source"),
                "size": resolved_size,
            }
            if isinstance(normalization_note, str):
                payload["normalization"] = normalization_note
            if resolved_nominal is not None:
                payload["fastener"] = {
                    "nominal_diameter_mm": resolved_nominal,
                    "length_mm": resolved_length,
                }
            resolved.append(payload)
            continue

        if category == "bearing":
            family_candidates = _index_by_family("bearing")
            if not family_candidates:
                unresolved.append({**base, "reason": "no_candidate_in_family"})
                continue
            designation_l = designation.lower()
            exact = [
                r for r in family_candidates
                if str(r.get("designation", "")).strip().lower() == designation_l
            ]
            index_item = _pick_preferred(exact)
            if not isinstance(index_item, Mapping):
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            cad_relpath = index_item.get("cad_relpath")
            index_part_id = index_item.get("part_id") if isinstance(index_item.get("part_id"), str) else None
            if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            library_file_abs_path = str((part_library_root / cad_relpath).resolve())

            inner, outer, width = _parse_bearing_designation(designation)
            resolved.append(
                {
                    **base,
                    "part_id": index_part_id,
                    "cad_relpath": cad_relpath,
                    "library_file_abs_path": library_file_abs_path,
                    "match_strategy": "family_designation_exact",
                    "category": "bearing",
                    "bearing": {
                        "inner_diameter_mm": inner,
                        "outer_diameter_mm": outer,
                        "width_mm": width,
                    },
                }
            )
            continue

        # Generic category: only mark as resolved if an INSERT_<CATEGORY>_R1 capability exists.
        # This keeps the system general without hardcoding per-category logic.
        if category in supported_insert:
            family_candidates = _index_by_family(category)
            if not family_candidates:
                unresolved.append({**base, "reason": "no_candidate_in_family"})
                continue
            index_item = _pick_preferred(family_candidates)
            if not isinstance(index_item, Mapping):
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            cad_relpath = index_item.get("cad_relpath")
            index_part_id = index_item.get("part_id") if isinstance(index_item.get("part_id"), str) else None
            if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                unresolved.append({**base, "reason": "no_index_match"})
                continue
            library_file_abs_path = str((part_library_root / cad_relpath).resolve())
            resolved.append(
                {
                    **base,
                    "part_id": index_part_id,
                    "cad_relpath": cad_relpath,
                    "library_file_abs_path": library_file_abs_path,
                    "match_strategy": "family_default",
                    "category": category,
                }
            )
        else:
            reason = "no_insert_function" if supported_insert else "unsupported_category"
            unresolved.append({**base, "reason": reason})

    return resolved, unresolved


def _expand_resolved_per_bound_component(
    resolved: List[Dict[str, Any]],
    *,
    component_parent_by_id: Mapping[str, str | None],
) -> List[Dict[str, Any]]:
    def _infer_parent(bound_id: str) -> str | None:
        parent = component_parent_by_id.get(bound_id)
        if isinstance(parent, str) and parent:
            return parent
        tokens = bound_id.split("_")
        if len(tokens) < 3:
            return None
        for i in range(len(tokens) - 1, 0, -1):
            candidate = "_".join(tokens[:i])
            if candidate == bound_id:
                continue
            if candidate in component_parent_by_id:
                return candidate
        return None

    expanded: List[Dict[str, Any]] = []
    for row in resolved:
        if not isinstance(row, Mapping):
            continue
        base = dict(row)
        bound_ids_raw = base.get("bound_component_ids")
        bound_ids = [cid for cid in bound_ids_raw if isinstance(cid, str) and cid] if isinstance(bound_ids_raw, list) else []
        if not bound_ids:
            expanded.append(base)
            continue

        if len(bound_ids) == 1:
            only = bound_ids[0]
            base["bound_component_ids"] = [only]
            base["bound_component_id"] = only
            base["component_name"] = only
            base["parent_component_id"] = _infer_parent(only)
            expanded.append(base)
            continue

        for idx, bound_id in enumerate(bound_ids, start=1):
            child = dict(base)
            child["bound_component_ids"] = [bound_id]
            child["bound_component_id"] = bound_id
            child["component_name"] = bound_id
            child["parent_component_id"] = _infer_parent(bound_id)
            rid = child.get("id")
            if isinstance(rid, str) and rid:
                child["id"] = f"{rid}__{bound_id}"
            else:
                child["id"] = f"stdpart_{idx}__{bound_id}"
            child["match_strategy"] = f"{child.get('match_strategy') or 'index'}+bound_component_split"
            expanded.append(child)
    return expanded


def _collapse_resolved_by_bound_component(resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _score(row: Mapping[str, Any]) -> int:
        score = 0
        strategy = row.get("match_strategy")
        if isinstance(strategy, str):
            s = strategy.lower()
            if "exact" in s:
                score += 40
            elif "nearest" in s:
                score += 30
            elif "kind" in s:
                score += 20
            elif "default" in s:
                score += 10
        if isinstance(row.get("part_id"), str) and row.get("part_id"):
            score += 5
        if isinstance(row.get("cad_relpath"), str) and row.get("cad_relpath"):
            score += 5
        return score

    rows_by_bound: Dict[str, List[Dict[str, Any]]] = {}
    passthrough: List[Dict[str, Any]] = []
    for row in resolved:
        if not isinstance(row, dict):
            continue
        bound_id = row.get("bound_component_id")
        if not isinstance(bound_id, str) or not bound_id:
            passthrough.append(dict(row))
            continue
        rows_by_bound.setdefault(bound_id, []).append(dict(row))

    collapsed: List[Dict[str, Any]] = list(passthrough)
    for bound_id in sorted(rows_by_bound.keys()):
        bucket = rows_by_bound.get(bound_id) or []
        if not bucket:
            continue

        best = sorted(bucket, key=lambda r: (_score(r), str(r.get("id") or "")), reverse=True)[0]

        merged_applied: set[str] = set()
        rationale_candidates: List[str] = []
        for row in bucket:
            applied = row.get("applied_to")
            if isinstance(applied, list):
                merged_applied.update([str(v) for v in applied if isinstance(v, str) and v])
            rationale = row.get("selection_rationale")
            if isinstance(rationale, str) and rationale.strip() and rationale.strip() not in rationale_candidates:
                rationale_candidates.append(rationale.strip())

        best["applied_to"] = sorted(merged_applied)
        if rationale_candidates:
            best["selection_rationale"] = rationale_candidates[0]
            if len(rationale_candidates) > 1:
                best["selection_rationale_candidates"] = rationale_candidates
        best["bound_component_ids"] = [bound_id]
        best["bound_component_id"] = bound_id
        best["component_name"] = bound_id

        duplicate_ids = sorted(
            {
                str(row.get("id"))
                for row in bucket
                if isinstance(row.get("id"), str) and row.get("id")
            }
        )
        if len(duplicate_ids) > 1:
            best["collapsed_duplicate_ids"] = duplicate_ids

        collapsed.append(best)

    return collapsed


def run(
    *,
    run_dir: Path,
    kg_path: Path | None = None,
    output_path: Path | None = None,
    unresolved_path: Path | None = None,
) -> None:
    kg_path = kg_path or (run_dir / "knowledge" / "knowledge_graph.json")
    if not kg_path.exists():
        raise SystemExit(f"Knowledge graph not found: {kg_path}")

    output_path = output_path or (run_dir / "planning" / "standard_parts_resolved.json")
    unresolved_path = unresolved_path or (run_dir / "planning" / "standard_parts_unresolved.json")

    kg = _read_json(kg_path)
    if not isinstance(kg, Mapping):
        raise ValueError("knowledge_graph.json must be an object")

    repo_root = Path(__file__).resolve().parents[1]
    part_library_root = repo_root / "part_library"
    index_path = part_library_root / "index" / "parts_index.json"
    parts_index = _load_parts_index(index_path)

    if not parts_index:
        unresolved = []
        parts = kg.get("standard_parts", []) if isinstance(kg, Mapping) else []
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, Mapping):
                    unresolved.append(
                        {
                            "id": part.get("id"),
                            "category": part.get("category"),
                            "designation": part.get("designation"),
                            "reason": "no_candidate_in_family",
                        }
                    )
        resolved = []
    else:
        resolved, unresolved = _resolve_standard_parts(
            kg,
            parts_index=parts_index,
            part_library_root=part_library_root,
        )

    component_parent_by_id: Dict[str, str | None] = {}
    components = kg.get("components") if isinstance(kg, Mapping) else None
    if isinstance(components, list):
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str) or not cid:
                continue
            parent = comp.get("position_parent")
            component_parent_by_id[cid] = parent if isinstance(parent, str) and parent else None

    resolved = _expand_resolved_per_bound_component(
        resolved,
        component_parent_by_id=component_parent_by_id,
    )
    resolved = _collapse_resolved_by_bound_component(resolved)
    _enforce_unique_component_names(resolved, strict_mode=_strict_resolver_enabled())

    payload = {
        "metadata": {
            "source": str(kg_path).replace("\\", "/"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "resolver": "requirement_to_kg.standard_parts_grounding",
        },
        "resolved": resolved,
    }
    _write_json(output_path, payload)

    unresolved_payload = {
        "metadata": {
            "source": str(kg_path).replace("\\", "/"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "resolver": "requirement_to_kg.standard_parts_grounding",
        },
        "unresolved": unresolved,
    }
    _write_json(unresolved_path, unresolved_payload)

    print(f"[OK] Resolved standard parts: {output_path}")
    print(f"[OK] Unresolved standard parts: {unresolved_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve standard parts (run-dir IO).")
    parser.add_argument("--run-dir", dest="run_dir", required=True)
    parser.add_argument("--kg", dest="kg_path", default=None)
    parser.add_argument("--out", dest="output_path", default=None)
    parser.add_argument("--unresolved", dest="unresolved_path", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    kg_path = Path(args.kg_path) if args.kg_path else None
    output_path = Path(args.output_path) if args.output_path else None
    unresolved_path = Path(args.unresolved_path) if args.unresolved_path else None

    run(
        run_dir=run_dir,
        kg_path=kg_path,
        output_path=output_path,
        unresolved_path=unresolved_path,
    )


if __name__ == "__main__":
    main()
