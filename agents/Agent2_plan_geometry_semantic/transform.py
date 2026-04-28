"""
plan_geometry_semantic agent (闁告垹濮崇紞宥囨嫚椤撴繄鐤呴悷娆忓閸?

闁哄牏寰唃ent閺夊牊鎸搁崵顓㈠礄閻樿京绉块悹鍥跺幒缁犵喓鎷嬮垾鍐茬亰 - 闁告艾娴烽顒勫籍閻樻彃褰犻柣銊ュ殝AD閻熸瑥瀚€垫牠濡?
濞寸姴鎳愰弫鎾诲箣閹邦剝鍩岄柣妯诲劶椤曘垺绋婃径濠冨闁规亽鍎辫ぐ娑氣偓瑙勭煯缁犵喖鏁嶇仦鑲╃憹闁告牕鎳庨幆鍫ュ几閸曨垪鍋撻悩渚綈闁告帗鐟ｉ埀?
"""

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


PLACEMENT_PURPOSES = {
    "fastening_mechanism", "structural_fixation", "structural_clamping",
    "support_to_structure", "load_support", "torque_transfer", "rotation_support",
    "rotation",  # Direct rotation connection (e.g., wheel-axle fit)
    "spacing",   # Spacer/washer positioning (e.g., bearing-spacer clearance)
}

ALLOWED_CONNECTION_MECHANISMS = {
    "bolted_mount",
    "radial_member_bolted_mount",
    "axial_face_bolted_mount",
    "axial_stack_locator",
    "bonded_tread",
    "bonded_mount",
    "press_fit",
    "shaft_bore_fit",
    "companion_rotation_relation",
    "welded_mount",
    "generic_mount",
}

SUPPRESSED_HOLE_FEATURES = {
    "hole",
    "alignment_pin_hole",
    "bolt_circle_pattern",
    "counterbore",
    "countersink",
    "fastener_head_seat",
    "mounting_face",
    "nut_seat",
}

GENERIC_FASTENER_MOUNT_PURPOSES = {
    "fastening_mechanism",
    "structural_fixation",
    "structural_clamping",
    "support_to_structure",
}

SEMANTIC_AUTHORITY_FALLBACK_ACTIONS = {
    "anchor_semantics_specialized_from_generic_placeholder",
    "anchor_semantics_overridden_by_deterministic_solver",
    "anchor_semantics_inferred_from_missing_upstream_semantics",
}


def _sanitize_connection_mechanism(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    aliases = {
        "bolted_rigid": "bolted_mount",
        "bolted_hinged": "bolted_mount",
        "bonded_rigid": "bonded_mount",
        "adhesive": "bonded_mount",
        "glued": "bonded_mount",
        "welded": "welded_mount",
        "interference_fit": "press_fit",
        "bead_seat": "bonded_tread",
        "shaft_bore": "shaft_bore_fit",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in ALLOWED_CONNECTION_MECHANISMS else None


def _sanitize_placement_flags(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    flags: Dict[str, Any] = {}
    if isinstance(value.get("suppress_hole_generation"), bool):
        flags["suppress_hole_generation"] = value.get("suppress_hole_generation")
    return flags


def _infer_geometry_type_from_interface_id(interface_id: str, semantic_role: str | None = None) -> str:
    """Infer geometry type from interface name patterns (stable, deterministic).

    This complements role-based inference to avoid mismatches like:
    - radial_outer_face incorrectly treated as planar.
    """
    lower = interface_id.lower() if isinstance(interface_id, str) else ""

    if any(tok in lower for tok in ("shaft_axis", "axis", "bore_axis")):
        return "axis"

    if any(tok in lower for tok in (
        "radial_outer_face", "radial_inner_face", "outer_cylinder", "outer_cyl", "cylindrical",
        "outer_radius", "inner_radius", "bore_radius", "radius_face",
        "bearing_seat", "press_fit_zone", "outer_race_od", "retainer_groove",
        "seal_groove", "standoff_bore",
    )):
        return "cylindrical"

    if any(
        tok in lower
        for tok in (
            "axial_end_face",
            "end_face",
            "mounting_face",
            "top_face",
            "bottom_face",
            "flange_face",
            "side_face",
            "x_face",
            "y_face",
            "z_face",
            "face_x",
            "face_y",
            "face_z",
            "datum_plane",
            "spacing_req",
            "spacer_face",
        )
    ):
        return "planar"

    if semantic_role:
        return _infer_geometry_type_from_role(semantic_role)
    return "complex"


def _infer_interface_role_from_purpose(purpose: str | None) -> str:
    if purpose in {"rotation", "rotation_support", "torque_transfer"}:
        return "rotation"
    if purpose in {"load_support", "support_to_structure"}:
        return "support"
    return "mounting"


# 闁冲厜鍋撻柍鍏夊亾 Shared pattern-parameter helpers 闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋?

def _build_comp_by_id(kg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Component-ID -> component lookup from knowledge graph."""
    return {c["id"]: c for c in (kg.get("components", []) or [])
            if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]}


def _build_frozen_echo(kg: Dict[str, Any]) -> Dict[str, Any]:
    """Compact echo of frozen Agent1 authority used by downstream audit trails."""
    components = []
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, Mapping):
            continue
        component_entry = {
            "id": comp.get("id"),
            "type": comp.get("type"),
            "shape_semantics": copy.deepcopy(comp.get("shape_semantics")),
            "dimensions": copy.deepcopy(comp.get("dimensions")),
            "parameters": copy.deepcopy(comp.get("parameters")),
        }
        for key in ("must_model", "modeling_policy", "kind", "parent_id", "position_parent", "definition_id", "instanced_from"):
            if key in comp:
                component_entry[key] = copy.deepcopy(comp.get(key))
        components.append(component_entry)

    connection_requirements = []
    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, Mapping):
            continue
        connection_entry = {
            "id": cr.get("id"),
            "between": copy.deepcopy(cr.get("between")),
            "purpose": cr.get("purpose"),
            "roles": copy.deepcopy(cr.get("roles")),
            "connection_semantics": copy.deepcopy(cr.get("connection_semantics")),
            "connection_decision": copy.deepcopy(cr.get("connection_decision")),
        }
        connection_requirements.append(connection_entry)

    return {
        "components": components,
        "connection_requirements": connection_requirements,
        "root_component_id": kg.get("root_component_id"),
    }


def _assert_frozen_unchanged(agent1_kg: Dict[str, Any], agent2_output: Dict[str, Any]) -> None:
    """Ensure Agent2 output preserved Agent1-owned frozen fields."""
    metadata = agent2_output.get("metadata") if isinstance(agent2_output.get("metadata"), dict) else {}
    frozen_echo = metadata.get("frozen_echo")
    if not isinstance(frozen_echo, dict):
        raise ValueError("Frozen echo missing from Agent2 output.")

    def _map_components(source: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for comp in source.get("components", []) or []:
            if not isinstance(comp, dict):
                continue
            cid = comp.get("id")
            if isinstance(cid, str):
                result[cid] = comp
        return result

    def _map_connections(source: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for cr in source.get("connection_requirements", []) or []:
            if not isinstance(cr, dict):
                continue
            cid = cr.get("id")
            if isinstance(cid, str):
                result[cid] = cr
        return result

    agent1_components = _map_components({"components": agent1_kg.get("components", [])})
    echo_components = _map_components({"components": frozen_echo.get("components", [])})
    agent1_connections = _map_connections({"connection_requirements": agent1_kg.get("connection_requirements", [])})
    echo_connections = _map_connections({"connection_requirements": frozen_echo.get("connection_requirements", [])})

    for cid, comp in agent1_components.items():
        echo = echo_components.get(cid)
        if not echo:
            raise ValueError(f"Frozen data modified: component '{cid}' missing in frozen_echo")
        if comp.get("dimensions") != echo.get("dimensions"):
            raise ValueError(
                f"Frozen data modified: component '{cid}' dimensions changed\n"
                f"  old: {str(comp.get('dimensions'))[:120]}\n"
                f"  new: {str(echo.get('dimensions'))[:120]}"
            )
        if comp.get("shape_semantics") != echo.get("shape_semantics"):
            raise ValueError(
                f"Frozen data modified: component '{cid}' shape_semantics changed\n"
                f"  old: {str(comp.get('shape_semantics'))[:120]}\n"
                f"  new: {str(echo.get('shape_semantics'))[:120]}"
            )

    for cr_id, cr in agent1_connections.items():
        echo = echo_connections.get(cr_id)
        if not echo:
            raise ValueError(f"Frozen data modified: connection_requirement '{cr_id}' missing in frozen_echo")
        for field in ("between", "purpose", "roles", "connection_decision", "connection_semantics"):
            if cr.get(field) != echo.get(field):
                raise ValueError(
                    f"Frozen data modified: connection_requirement '{cr_id}' {field} changed\n"
                    f"  old: {str(cr.get(field))[:120]}\n"
                    f"  new: {str(echo.get(field))[:120]}"
                )
    return None

def _to_float(v: Any) -> float | None:
    """Safe numeric conversion (bool-proof, string-tolerant)."""
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


def _compute_edge_constraints(
    hole_diameter: float, host_plate: bool, thickness: float | None,
) -> tuple[float, float]:
    """Return *(min_edge_distance, offset_from_edge)* per DIN edge-safety rules."""
    min_edge = round(hole_diameter * 2.5, 2)
    if host_plate and isinstance(thickness, (int, float)) and thickness > 0:
        min_edge = max(min_edge, round(float(thickness) * 2.0, 2))
    offset = max(min_edge, 5.0)
    if host_plate and isinstance(thickness, (int, float)) and thickness > 0:
        offset = max(offset, round(float(thickness) * 2.0, 2))
    return min_edge, offset


def _compute_min_wall(hole_diameter: float) -> float:
    """Minimum wall thickness around a hole (quarter of hole radius, 闁?1 mm)."""
    return max(1.0, round((hole_diameter / 2.0) * 0.25, 2))


def _resolve_rectangular_spacing(
    host_dims: dict, offset_from_edge: float,
) -> dict | None:
    """Rectangular bolt-pattern spacing from host dims and edge offset."""
    width = host_dims.get("width") or host_dims.get("arm_width")
    length = host_dims.get("length") or host_dims.get("arm_length") or host_dims.get("depth")
    if not (isinstance(width, (int, float)) and isinstance(length, (int, float))
            and width > 0 and length > 0):
        return None
    return {
        "x": round(max(float(width) - 2 * offset_from_edge, offset_from_edge * 2.0), 2),
        "y": round(max(float(length) - 2 * offset_from_edge, offset_from_edge * 2.0), 2),
    }

# 闁冲厜鍋撻柍鍏夊亾 End shared pattern-parameter helpers 闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾闁冲厜鍋撻柍鍏夊亾


def _ensure_parent_role_closure(kg: Dict[str, Any]) -> None:
    """Ensure wheel/subassembly parents carry role-level connections for child semantics."""
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id: Dict[str, str] = {}
    children_by_parent: Dict[str, set[str]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        parent_id = comp.get("parent_id")
        if isinstance(cid, str) and isinstance(ctype, str):
            type_by_id[cid] = ctype
        if isinstance(cid, str) and isinstance(parent_id, str):
            children_by_parent.setdefault(parent_id, set()).add(cid)

    subassemblies = kg.get("subassemblies", [])
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, dict):
                continue
            sa_id = sa.get("id")
            members = sa.get("component_ids", [])
            if isinstance(sa_id, str) and isinstance(members, list):
                children_by_parent.setdefault(sa_id, set()).update(
                    m for m in members if isinstance(m, str)
                )

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    def _role_from_purpose(purpose: str) -> set[str]:
        if purpose in {"rotation", "rotation_support", "torque_transfer"}:
            return {"rotation"}
        if purpose in {"load_support", "support_to_structure"}:
            return {"support"}
        if purpose in {"structural_fixation", "structural_clamping", "fastening_mechanism"}:
            return {"mounting"}
        return set()

    existing_roles_by_parent: Dict[str, set[str]] = {pid: set() for pid in children_by_parent}
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between = cr.get("between", [])
        if not isinstance(between, list):
            continue
        purpose_raw = cr.get("purpose")
        purpose = purpose_raw if isinstance(purpose_raw, str) else ""
        roles = {r for r in cr.get("roles", []) if isinstance(r, str)}
        for pid in children_by_parent:
            if pid in between:
                existing_roles_by_parent[pid].update(_role_from_purpose(purpose))
                if "mounting" in roles:
                    existing_roles_by_parent[pid].add("mounting")

    existing_ids = {cr.get("id") for cr in crs if isinstance(cr, dict)}

    def _next_id(prefix: str) -> str:
        idx = 1
        candidate = f"{prefix}_{idx}"
        while candidate in existing_ids:
            idx += 1
            candidate = f"{prefix}_{idx}"
        existing_ids.add(candidate)
        return candidate

    def _add_role_connection(parent_id: str, child_id: str, role: str) -> None:
        purpose = f"role_closure_{role}"
        crs.append(
            {
                "id": _next_id(f"req_{parent_id}_{role}_closure"),
                "between": [parent_id, child_id],
                "purpose": purpose,
                "roles": [role],
                "constraints": {"role_closure": True},
                "confidence": 0.6,
                "description": "Role-closure requirement to expose parent semantics",
            }
        )

    for parent_id, child_ids in children_by_parent.items():
        if type_by_id.get(parent_id) not in {"wheel", "subassembly"}:
            continue
        if not child_ids:
            continue

        child_set = set(child_ids)
        role_hits: set[str] = set()
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            between_ids = {cid for cid in between if isinstance(cid, str)}
            if not between_ids or not between_ids.issubset(child_set):
                continue
            purpose_raw = cr.get("purpose")
            purpose = purpose_raw if isinstance(purpose_raw, str) else ""
            role_hits.update(_role_from_purpose(purpose))
            if "mounting" in {r for r in cr.get("roles", []) if isinstance(r, str)}:
                role_hits.add("mounting")

        missing_roles = role_hits - existing_roles_by_parent.get(parent_id, set())
        if not missing_roles:
            continue
        anchor_id = sorted(child_ids)[0]
        for role in sorted(missing_roles):
            _add_role_connection(parent_id, anchor_id, role)


def _load_existing_geometry_semantics(output_path: str) -> dict | None:
    """If output_path exists, load and return JSON dict, else None."""
    if not os.path.exists(output_path):
        return None
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize_placement_connection_id(item: Dict[str, Any]) -> str | None:
    cid = item.get("connection_id")
    if isinstance(cid, str):
        return cid
    legacy = item.get("for_connection_requirement_id")
    if isinstance(legacy, str):
        return legacy
    return None


def _sanitize_anchor_semantics(
    raw: Any,
    *,
    valid_component_ids: set[str],
) -> Dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None

    reference_component_id = raw.get("reference_component_id")
    moving_component_id = raw.get("moving_component_id")
    if (
        not isinstance(reference_component_id, str)
        or not reference_component_id
        or reference_component_id not in valid_component_ids
    ):
        return None
    if (
        not isinstance(moving_component_id, str)
        or not moving_component_id
        or moving_component_id not in valid_component_ids
    ):
        return None

    def _normalize_anchor(anchor_raw: Any) -> Dict[str, Any] | None:
        if not isinstance(anchor_raw, Mapping):
            return None
        kind = anchor_raw.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            return None
        anchor: Dict[str, Any] = {"kind": kind.strip().lower()}
        axis = anchor_raw.get("axis")
        if isinstance(axis, str) and axis.strip():
            anchor["axis"] = axis.strip().lower()
        for numeric_key in ("radius_mm", "inset_mm", "phase_deg", "phase_rad"):
            numeric_value = anchor_raw.get(numeric_key)
            if isinstance(numeric_value, (int, float)):
                anchor[numeric_key] = float(numeric_value)
        return anchor

    reference_anchor = _normalize_anchor(raw.get("reference_anchor"))
    moving_anchor = _normalize_anchor(raw.get("moving_anchor"))
    if not reference_anchor or not moving_anchor:
        return None

    relation_type_raw = raw.get("relation_type")
    orientation_policy_raw = raw.get("orientation_policy")
    confidence_raw = raw.get("confidence")
    source_raw = raw.get("source")

    normalized: Dict[str, Any] = {
        "reference_component_id": reference_component_id,
        "moving_component_id": moving_component_id,
        "reference_anchor": reference_anchor,
        "moving_anchor": moving_anchor,
    }
    if isinstance(relation_type_raw, str) and relation_type_raw.strip():
        normalized["relation_type"] = relation_type_raw.strip().lower()
    if isinstance(orientation_policy_raw, str) and orientation_policy_raw.strip():
        normalized["orientation_policy"] = orientation_policy_raw.strip().lower()
    if isinstance(confidence_raw, str) and confidence_raw.strip():
        normalized["confidence"] = confidence_raw.strip().lower()
    if isinstance(source_raw, str) and source_raw.strip():
        normalized["source"] = source_raw.strip()
    return normalized


_AUTHORITATIVE_INTERFACE_REF_SOURCE = "agent1_connection_semantics"

_GENERIC_GEOMETRIC_SEMANTIC_VALUES = {"generic", "unspecified", "unknown", "default", "auto", "automatic", "heuristic", "inferred", "placeholder"}
_PATTERN_POLICIES_REQUIRING_COUNT = {"circular_array", "linear_array"}


def _sanitize_contract_geometric_semantics(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    out: Dict[str, Any] = {}
    for key in ("contact_model", "reference_feature_strategy", "moving_feature_strategy", "pattern_policy"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        out[key] = value.strip().lower()
    pattern_count = raw.get("pattern_count")
    if isinstance(pattern_count, int) and pattern_count >= 1:
        out["pattern_count"] = int(pattern_count)
    for key in ("hardware_layout", "retention_strategy", "notes", "support_topology", "anti_rotation_topology", "mount_side", "axial_stack_policy", "clearance_policy"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip() if key == "notes" else value.strip().lower()
    requires_axial_offset = raw.get("requires_axial_offset")
    if isinstance(requires_axial_offset, bool):
        out["requires_axial_offset"] = requires_axial_offset
    return out


def _contract_geometric_semantics_is_specific(raw: Any, *, mechanism: str | None) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for key in ("contact_model", "reference_feature_strategy", "moving_feature_strategy", "pattern_policy"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return False
        if value.strip().lower() in _GENERIC_GEOMETRIC_SEMANTIC_VALUES:
            return False
    pattern_policy = str(raw.get("pattern_policy") or "").strip().lower()
    if pattern_policy in _PATTERN_POLICIES_REQUIRING_COUNT:
        if not isinstance(raw.get("pattern_count"), int) or int(raw.get("pattern_count")) < 1:
            return False
    mechanism_name = str(mechanism or "").strip().lower()
    if mechanism_name in {"bolted_mount", "radial_member_bolted_mount", "axial_face_bolted_mount"}:
        for key in ("reference_feature_strategy", "moving_feature_strategy"):
            if str(raw.get(key) or "").strip().lower() in {"none", "plain_surface", "bonding_zone"}:
                return False
    return True


def _seed_pattern_parameters_from_geometric_semantics(contract: Mapping[str, Any]) -> Dict[str, Any] | None:
    geometric_semantics = contract.get("geometric_semantics") if isinstance(contract.get("geometric_semantics"), Mapping) else None
    mechanism = str(contract.get("connection_mechanism") or "").strip().lower()
    if not _contract_geometric_semantics_is_specific(geometric_semantics, mechanism=mechanism):
        return None
    pattern_policy = str(geometric_semantics.get("pattern_policy") or "").strip().lower()
    if pattern_policy in {"single", "shared_single", "none"}:
        return {"type": "single", "count": 1, "offset_from_edge": 0.0}
    if pattern_policy == "circular_array":
        pattern_count = geometric_semantics.get("pattern_count")
        if isinstance(pattern_count, int) and pattern_count >= 1:
            return {"type": "circular", "count": int(pattern_count), "offset_from_edge": 0.0}
    return None



def _sanitize_connection_semantics_contract(
    raw: Any,
    *,
    valid_component_ids: set[str],
) -> Dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    mechanism = _sanitize_connection_mechanism(raw.get("connection_mechanism"))
    if not mechanism:
        return None
    anchor_semantics = _sanitize_anchor_semantics(raw, valid_component_ids=valid_component_ids)
    if not isinstance(anchor_semantics, dict):
        return None
    geometric_semantics = _sanitize_contract_geometric_semantics(raw.get("geometric_semantics"))
    if not isinstance(geometric_semantics, dict):
        return None
    reference_interface_hint = raw.get("reference_interface_hint")
    moving_interface_hint = raw.get("moving_interface_hint")
    assembly_reference_interface_hint = raw.get("assembly_reference_interface_hint")
    assembly_moving_interface_hint = raw.get("assembly_moving_interface_hint")
    if not isinstance(reference_interface_hint, str) or not reference_interface_hint.strip():
        return None
    if not isinstance(moving_interface_hint, str) or not moving_interface_hint.strip():
        return None
    contract = dict(anchor_semantics)
    contract["connection_mechanism"] = mechanism
    contract["reference_interface_hint"] = reference_interface_hint.strip()
    contract["moving_interface_hint"] = moving_interface_hint.strip()
    if isinstance(assembly_reference_interface_hint, str) and assembly_reference_interface_hint.strip():
        contract["assembly_reference_interface_hint"] = assembly_reference_interface_hint.strip()
    if isinstance(assembly_moving_interface_hint, str) and assembly_moving_interface_hint.strip():
        contract["assembly_moving_interface_hint"] = assembly_moving_interface_hint.strip()
    contract["geometric_semantics"] = geometric_semantics
    rationale = raw.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        contract["rationale"] = rationale.strip()
    confidence = raw.get("confidence")
    if isinstance(confidence, (int, float)):
        contract["confidence"] = float(confidence)
    return contract



def _contract_to_anchor_semantics(contract: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "reference_component_id": contract.get("reference_component_id"),
        "moving_component_id": contract.get("moving_component_id"),
        "reference_anchor": copy.deepcopy(contract.get("reference_anchor")),
        "moving_anchor": copy.deepcopy(contract.get("moving_anchor")),
        "source": _AUTHORITATIVE_INTERFACE_REF_SOURCE,
    }
    for key in ("assembly_reference_interface_hint", "assembly_moving_interface_hint"):
        value = contract.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in ("relation_type", "orientation_policy", "confidence"):
        value = contract.get(key)
        if value is not None:
            result[key] = copy.deepcopy(value)
    return result



def _build_authoritative_interface_ref(
    contract: Mapping[str, Any],
    *,
    purpose: str | None,
) -> Dict[str, Any]:
    interface_name = str(contract.get("reference_interface_hint") or "").strip() or "unspecified"
    component_id = str(contract.get("reference_component_id") or "").strip() or "unspecified"
    semantic_role = _infer_interface_role_from_purpose(purpose if isinstance(purpose, str) else None)
    geometry_type = _infer_geometry_type_from_interface_id(interface_name, semantic_role)
    return {
        "name": interface_name,
        "component_id": component_id,
        "semantic_role": semantic_role,
        "geometry_type": geometry_type,
        "geom_type": geometry_type,
        "source": _AUTHORITATIVE_INTERFACE_REF_SOURCE,
        "frozen_authority": True,
    }



def _seed_pattern_parameters_from_contract(
    connection_decision: Mapping[str, Any] | None,
    contract: Mapping[str, Any],
) -> Dict[str, Any]:
    seeded = _seed_pattern_parameters_from_geometric_semantics(contract)
    if isinstance(seeded, dict):
        return seeded
    mechanism = str(contract.get("connection_mechanism") or "").strip().lower()
    if mechanism in {"bolted_mount", "radial_member_bolted_mount", "axial_face_bolted_mount"}:
        return {"type": "single", "count": 1, "offset_from_edge": 0.0}
    return {"type": "single", "count": 1, "offset_from_edge": 0.0}



def _build_authoritative_placement_from_contract(
    connection: Mapping[str, Any],
    *,
    fastener_component: Mapping[str, Any] | None = None,
) -> Dict[str, Any] | None:
    between_ids = _between_to_ids(connection.get("between"))
    contract = _sanitize_connection_semantics_contract(
        connection.get("connection_semantics"),
        valid_component_ids={cid for cid in between_ids if isinstance(cid, str)},
    )
    if not isinstance(contract, dict):
        return None
    purpose = connection.get("purpose") if isinstance(connection.get("purpose"), str) else None
    decision = connection.get("connection_decision") if isinstance(connection.get("connection_decision"), Mapping) else None
    pattern_parameters = _seed_pattern_parameters_from_contract(decision, contract)
    return {
        "connection_id": connection.get("id"),
        "between": connection.get("between"),
        "purpose": purpose,
        "placement_intent": {
            "pattern_type": pattern_parameters.get("type", "single"),
            "symmetry": "radial" if pattern_parameters.get("type") == "circular" else "single",
            "reference": contract.get("reference_component_id"),
            "preference": {"aesthetic": "contract_authority", "performance": "contract_authority"},
            "notes": "Seeded from Agent1 frozen connection_semantics contract",
        },
        "location": {
            "reference_frame": "component_local",
            "interface_ref": _build_authoritative_interface_ref(contract, purpose=purpose),
            "pattern_parameters": pattern_parameters,
            "functional_context": {
                "near_contact_area": purpose in {"fastening_mechanism", "structural_fixation", "load_support", "support_to_structure", "structural_clamping"},
                "load_bearing": purpose in {"fastening_mechanism", "structural_fixation", "load_support", "support_to_structure", "torque_transfer", "structural_clamping"},
                "accessible": True,
            },
            "rationale": str(contract.get("rationale") or "Seeded from Agent1 frozen connection_semantics contract"),
        },
        "authoritative_interface_hints": {
            str(contract.get("reference_component_id") or ""): str(contract.get("reference_interface_hint") or "").strip(),
            str(contract.get("moving_component_id") or ""): str(contract.get("moving_interface_hint") or "").strip(),
        },
        "derived_changes": [],
        "fastener_spec": _infer_fastener_spec(
            decision if isinstance(decision, dict) else None,
            fastener_component=fastener_component if isinstance(fastener_component, Mapping) else None,
            purpose=purpose,
        ),
        "connection_mechanism": contract.get("connection_mechanism"),
        "anchor_semantics": _contract_to_anchor_semantics(contract),
        "geometric_semantics": copy.deepcopy(contract.get("geometric_semantics")),
        "status": "authoritative_contract_seed",
        "authoritative_contract": True,
    }



def _merge_location_with_authoritative_interface(
    location: Any,
    contract: Mapping[str, Any],
    *,
    purpose: str | None,
) -> Dict[str, Any]:
    location_dict = dict(location) if isinstance(location, Mapping) else {}
    location_dict.setdefault("reference_frame", "component_local")
    location_dict["interface_ref"] = _build_authoritative_interface_ref(contract, purpose=purpose)
    seeded_pattern = _seed_pattern_parameters_from_geometric_semantics(contract)
    if isinstance(seeded_pattern, dict):
        location_dict["pattern_parameters"] = seeded_pattern
    return location_dict


def _anchor_semantics_matches_expected(
    existing: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    for key in ("reference_component_id", "moving_component_id"):
        if str(existing.get(key) or "") != str(expected.get(key) or ""):
            return False

    for key in ("reference_anchor", "moving_anchor"):
        existing_anchor = existing.get(key) if isinstance(existing.get(key), Mapping) else {}
        expected_anchor = expected.get(key) if isinstance(expected.get(key), Mapping) else {}
        if str(existing_anchor.get("kind") or "") != str(expected_anchor.get("kind") or ""):
            return False
        expected_axis = expected_anchor.get("axis")
        if isinstance(expected_axis, str) and expected_axis:
            if str(existing_anchor.get("axis") or "") != expected_axis:
                return False
        for numeric_key in ("radius_mm", "inset_mm", "phase_deg", "phase_rad"):
            expected_value = expected_anchor.get(numeric_key)
            if isinstance(expected_value, (int, float)):
                existing_value = existing_anchor.get(numeric_key)
                if not isinstance(existing_value, (int, float)):
                    return False
                if abs(float(existing_value) - float(expected_value)) > 1e-6:
                    return False

    expected_orientation = expected.get("orientation_policy")
    if isinstance(expected_orientation, str) and expected_orientation:
        if str(existing.get("orientation_policy") or "") != expected_orientation:
            return False

    return True



def _anchor_semantics_is_generic_placeholder(anchor_semantics: Mapping[str, Any]) -> bool:
    strict_generic_kinds = {"component_center", "proximal_end", "distal_end"}
    weak_generic_kinds = {
        "proximal_mount_face_min",
        "proximal_mount_face_max",
        "distal_mount_face_min",
        "distal_mount_face_max",
        "axial_face_min",
        "axial_face_max",
        "axial_face_perimeter_min",
        "axial_face_perimeter_max",
        "radial_mount_perimeter",
    }

    def _anchor(anchor_key: str) -> Mapping[str, Any]:
        anchor = anchor_semantics.get(anchor_key)
        return anchor if isinstance(anchor, Mapping) else {}

    def _is_generic(anchor_key: str) -> bool:
        anchor = _anchor(anchor_key)
        kind = str(anchor.get("kind") or "").strip().lower()
        if kind in strict_generic_kinds:
            return True
        if kind in weak_generic_kinds:
            return not any(isinstance(anchor.get(key), (int, float)) for key in ("radius_mm", "inset_mm", "phase_deg", "phase_rad"))
        return False

    return _is_generic("reference_anchor") and _is_generic("moving_anchor")


def _anchor_semantics_can_be_specialized(
    existing: Mapping[str, Any],
    inferred: Mapping[str, Any],
) -> bool:
    if not _anchor_semantics_is_generic_placeholder(existing):
        return False
    existing_pair = {
        str(existing.get("reference_component_id") or "").strip(),
        str(existing.get("moving_component_id") or "").strip(),
    }
    inferred_pair = {
        str(inferred.get("reference_component_id") or "").strip(),
        str(inferred.get("moving_component_id") or "").strip(),
    }
    return "" not in existing_pair and existing_pair == inferred_pair


def _authoritative_anchor_semantics_can_absorb_numeric_refinement(existing: Mapping[str, Any], inferred: Mapping[str, Any]) -> bool:
    for key in ("reference_component_id", "moving_component_id", "relation_type", "orientation_policy"):
        existing_value = str(existing.get(key) or "").strip().lower()
        inferred_value = str(inferred.get(key) or "").strip().lower()
        if existing_value and inferred_value and existing_value != inferred_value:
            return False
    for key in ("reference_anchor", "moving_anchor"):
        existing_anchor = existing.get(key) if isinstance(existing.get(key), Mapping) else {}
        inferred_anchor = inferred.get(key) if isinstance(inferred.get(key), Mapping) else {}
        existing_kind = str(existing_anchor.get("kind") or "").strip().lower()
        inferred_kind = str(inferred_anchor.get("kind") or "").strip().lower()
        if existing_kind and inferred_kind and existing_kind != inferred_kind:
            return False
        existing_axis = str(existing_anchor.get("axis") or "").strip().lower()
        inferred_axis = str(inferred_anchor.get("axis") or "").strip().lower()
        if existing_axis and inferred_axis and existing_axis != inferred_axis:
            return False
    return True


def _merge_authoritative_anchor_numeric_refinement(existing: Mapping[str, Any], inferred: Mapping[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(existing)
    for key in ("reference_anchor", "moving_anchor"):
        merged_anchor = merged.get(key) if isinstance(merged.get(key), dict) else {}
        inferred_anchor = inferred.get(key) if isinstance(inferred.get(key), Mapping) else {}
        if not merged_anchor.get("axis") and isinstance(inferred_anchor.get("axis"), str) and inferred_anchor.get("axis").strip():
            merged_anchor["axis"] = inferred_anchor.get("axis").strip().lower()
        for numeric_key in ("radius_mm", "inset_mm", "phase_deg", "phase_rad"):
            if numeric_key not in merged_anchor and isinstance(inferred_anchor.get(numeric_key), (int, float)):
                merged_anchor[numeric_key] = float(inferred_anchor.get(numeric_key))
        merged[key] = merged_anchor
    return merged


def _normalize_placement_schema(placements: list[dict]) -> list[dict]:
    """Migrate legacy placement schema fields to interface_ref-based location schema."""
    normalized: list[dict] = []
    for placement in placements or []:
        if not isinstance(placement, dict):
            continue
        location_raw = placement.get("location")
        location = dict(location_raw) if isinstance(location_raw, dict) else {}

        reference_surface_raw = location.pop("reference_surface", None)
        reference_surface = (
            reference_surface_raw
            if isinstance(reference_surface_raw, str) and reference_surface_raw
            else None
        )

        interface_ref_raw = location.get("interface_ref")
        interface_ref = dict(interface_ref_raw) if isinstance(interface_ref_raw, dict) else {}

        iface_name_raw = interface_ref.get("name")
        iface_component_raw = interface_ref.get("component_id")
        iface_name = iface_name_raw if isinstance(iface_name_raw, str) and iface_name_raw else None
        iface_component = (
            iface_component_raw
            if isinstance(iface_component_raw, str) and iface_component_raw
            else None
        )

        if iface_name is None:
            iface_name = reference_surface or "unspecified"
        if iface_component is None:
            between = placement.get("between")
            if isinstance(between, dict):
                for key in between.keys():
                    if isinstance(key, str) and key:
                        iface_component = key
                        break
            elif isinstance(between, list):
                for cid in between:
                    if isinstance(cid, str) and cid:
                        iface_component = cid
                        break
        if iface_component is None:
            iface_component = "unspecified"

        geometry_type = interface_ref.get("geometry_type")
        if not isinstance(geometry_type, str) or not geometry_type:
            geometry_type = interface_ref.get("geom_type")
        if not isinstance(geometry_type, str) or not geometry_type:
            geometry_type = _infer_geometry_type_from_interface_id(iface_name)

        semantic_role = interface_ref.get("semantic_role")
        if not isinstance(semantic_role, str) or not semantic_role:
            semantic_role = "mounting"

        normalized_interface_ref = {
            "name": iface_name,
            "component_id": iface_component,
            "semantic_role": semantic_role,
            "geometry_type": geometry_type,
            "geom_type": geometry_type,
        }
        usage = interface_ref.get("usage")
        if isinstance(usage, str) and usage.strip():
            normalized_interface_ref["usage"] = usage.strip()
        source = interface_ref.get("source")
        if isinstance(source, str) and source.strip():
            normalized_interface_ref["source"] = source.strip()
        if isinstance(interface_ref.get("frozen_authority"), bool):
            normalized_interface_ref["frozen_authority"] = bool(interface_ref.get("frozen_authority"))
        location["interface_ref"] = normalized_interface_ref
        placement["location"] = location
        normalized.append(placement)
    return normalized


def _build_interface_index_for_selection(semantics: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    by_component: Dict[str, List[Dict[str, Any]]] = {}

    declarations = semantics.get("interface_declarations")
    if isinstance(declarations, list):
        for decl in declarations:
            if not isinstance(decl, Mapping):
                continue
            component_id = decl.get("component_id")
            interface_name = decl.get("interface_name")
            if not isinstance(component_id, str) or not component_id:
                continue
            if not isinstance(interface_name, str) or not interface_name:
                continue
            role = decl.get("semantic_role") if isinstance(decl.get("semantic_role"), str) else "mounting"
            geometry_type = decl.get("geometry_type")
            if not isinstance(geometry_type, str) or not geometry_type:
                geometry_type = decl.get("geom_type") if isinstance(decl.get("geom_type"), str) else "planar"
            by_component.setdefault(component_id, []).append(
                {
                    "name": interface_name,
                    "semantic_role": role,
                    "geometry_type": geometry_type,
                }
            )

    parts = semantics.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            component_id = part.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue
            interfaces = part.get("interfaces")
            if not isinstance(interfaces, list):
                continue
            for iface in interfaces:
                if not isinstance(iface, Mapping):
                    continue
                interface_name = iface.get("interface_id")
                if not isinstance(interface_name, str) or not interface_name:
                    continue
                role = iface.get("semantic_role") if isinstance(iface.get("semantic_role"), str) else "mounting"
                geometry_type = iface.get("geometry_type")
                if not isinstance(geometry_type, str) or not geometry_type:
                    geometry_type = iface.get("geom_type") if isinstance(iface.get("geom_type"), str) else "planar"
                by_component.setdefault(component_id, []).append(
                    {
                        "name": interface_name,
                        "semantic_role": role,
                        "geometry_type": geometry_type,
                    }
                )

    for component_id in list(by_component.keys()):
        unique: Dict[str, Dict[str, Any]] = {}
        for iface in by_component[component_id]:
            name = iface.get("name")
            if isinstance(name, str) and name and name not in unique:
                unique[name] = dict(iface)
        by_component[component_id] = [unique[name] for name in sorted(unique.keys())]

    return by_component


def _select_interface_for_target(
    *,
    target_id: str,
    original_interface: Mapping[str, Any],
    original_interface_component_id: str,
    interface_index: Mapping[str, List[Dict[str, Any]]],
    desired_interface_name: str | None = None,
) -> Dict[str, Any]:
    original_name = original_interface.get("name") if isinstance(original_interface.get("name"), str) else "unspecified"
    original_role = original_interface.get("semantic_role") if isinstance(original_interface.get("semantic_role"), str) else "mounting"
    original_geometry = original_interface.get("geometry_type") if isinstance(original_interface.get("geometry_type"), str) else (
        original_interface.get("geom_type") if isinstance(original_interface.get("geom_type"), str) else "planar"
    )
    desired_name = desired_interface_name.strip() if isinstance(desired_interface_name, str) and desired_interface_name.strip() else None

    if target_id == original_interface_component_id and desired_name is None:
        result = {
            "name": original_name,
            "semantic_role": original_role,
            "geometry_type": original_geometry,
            "geom_type": original_geometry,
        }
        usage = original_interface.get("usage") if isinstance(original_interface.get("usage"), str) else None
        source = original_interface.get("source") if isinstance(original_interface.get("source"), str) else None
        if usage:
            result["usage"] = usage
        if source:
            result["source"] = source
        if isinstance(original_interface.get("frozen_authority"), bool):
            result["frozen_authority"] = bool(original_interface.get("frozen_authority"))
        return result

    candidates = interface_index.get(target_id, [])

    def _normalize_desired_name(name: str | None) -> str | None:
        if not (isinstance(name, str) and name.strip()):
            return None
        if not candidates:
            return name.strip()
        normalized = name.strip().lower()
        candidate_names = {
            candidate_name.lower(): candidate_name
            for candidate in candidates
            for candidate_name in [candidate.get("name") if isinstance(candidate.get("name"), str) else None]
            if isinstance(candidate_name, str) and candidate_name
        }
        if normalized in candidate_names:
            return candidate_names[normalized]
        alias_preferences = {
            "proximal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "proximal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "distal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "distal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "axial_face_perimeter_min": ("axial_end_face_min", "axial_end_face", "planar_face"),
            "axial_face_perimeter_max": ("axial_end_face_max", "axial_end_face", "planar_face"),
            "axial_face_min": ("axial_end_face_min", "axial_end_face", "planar_face"),
            "axial_face_max": ("axial_end_face_max", "axial_end_face", "planar_face"),
            "radial_mount_perimeter": ("radial_outer_face", "radial_inner_face"),
        }
        for alias in alias_preferences.get(normalized, ()): 
            if alias in candidate_names:
                return candidate_names[alias]
        return name.strip()

    desired_name = _normalize_desired_name(desired_name)

    if not candidates:
        if desired_name:
            desired_geometry = _infer_geometry_type_from_interface_id(desired_name, original_role)
            return {
                "name": desired_name,
                "semantic_role": original_role,
                "geometry_type": desired_geometry,
                "geom_type": desired_geometry,
                "source": _AUTHORITATIVE_INTERFACE_REF_SOURCE,
                "frozen_authority": True,
            }
        raise ValueError(f"No interface declarations found for target component '{target_id}' during placement split")

    ranked: List[Tuple[int, str, Dict[str, Any]]] = []
    for candidate in candidates:
        name = candidate.get("name") if isinstance(candidate.get("name"), str) else ""
        role = candidate.get("semantic_role") if isinstance(candidate.get("semantic_role"), str) else "mounting"
        geometry_type = candidate.get("geometry_type") if isinstance(candidate.get("geometry_type"), str) else "planar"
        score = 0
        role_lower = role.lower()
        name_lower = name.lower()
        geometry_lower = geometry_type.lower()

        if desired_name and name_lower == desired_name.lower():
            score += 1000
        if role_lower in {"mounting", "fixation", "support", "rotation"}:
            score += 100
        if geometry_lower == "planar" and name_lower.startswith("side_face_"):
            score += 60
        if "mounting_req" in name_lower:
            score += 40
        if "mount" in name_lower:
            score += 20

        result = {"name": name, "semantic_role": role, "geometry_type": geometry_type, "geom_type": geometry_type}
        usage = candidate.get("usage") if isinstance(candidate.get("usage"), str) else None
        source = candidate.get("source") if isinstance(candidate.get("source"), str) else None
        if usage:
            result["usage"] = usage
        if source:
            result["source"] = source
        if isinstance(candidate.get("frozen_authority"), bool):
            result["frozen_authority"] = bool(candidate.get("frozen_authority"))
        ranked.append((score, name, result))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    best = ranked[0][2]
    if desired_name and str(best.get("name") or "").strip().lower() != desired_name.lower():
        desired_geometry = _infer_geometry_type_from_interface_id(desired_name, original_role)
        return {
            "name": desired_name,
            "semantic_role": original_role,
            "geometry_type": desired_geometry,
            "geom_type": desired_geometry,
            "source": _AUTHORITATIVE_INTERFACE_REF_SOURCE,
            "frozen_authority": True,
        }
    return best


def _split_connection_placements_per_target(
    *,
    semantics: Dict[str, Any],
    placements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    interface_index = _build_interface_index_for_selection(semantics)
    split_placements: List[Dict[str, Any]] = []

    for placement in placements:
        if not isinstance(placement, Mapping):
            continue

        derived_changes = placement.get("derived_changes")
        if not isinstance(derived_changes, list) or not derived_changes:
            split_placements.append(copy.deepcopy(dict(placement)))
            continue

        target_groups: Dict[str, List[Dict[str, Any]]] = {}
        for change in derived_changes:
            if not isinstance(change, Mapping):
                continue
            target_id = change.get("target_component_id")
            if not isinstance(target_id, str) or not target_id:
                raise ValueError("derived_change is missing target_component_id during per-target placement split")
            target_groups.setdefault(target_id, []).append(copy.deepcopy(dict(change)))

        location_raw = placement.get("location")
        location = copy.deepcopy(location_raw) if isinstance(location_raw, Mapping) else {}
        interface_ref_raw = location.get("interface_ref")
        interface_ref = copy.deepcopy(interface_ref_raw) if isinstance(interface_ref_raw, Mapping) else {}
        original_component_id = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else ""
        authoritative_interface_hints = placement.get("authoritative_interface_hints") if isinstance(placement.get("authoritative_interface_hints"), Mapping) else {}
        normalized_authoritative_interface_hints: Dict[str, str] = {}
        for hinted_target_id, hinted_name in authoritative_interface_hints.items():
            if not (isinstance(hinted_target_id, str) and hinted_target_id and isinstance(hinted_name, str) and hinted_name.strip()):
                continue
            normalized_hint = _select_interface_for_target(
                target_id=hinted_target_id,
                original_interface=interface_ref,
                original_interface_component_id=original_component_id,
                interface_index=interface_index,
                desired_interface_name=hinted_name,
            ).get("name")
            if isinstance(normalized_hint, str) and normalized_hint:
                normalized_authoritative_interface_hints[hinted_target_id] = normalized_hint
        authoritative_interface_hints = normalized_authoritative_interface_hints
        base_connection_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else "unknown_connection"

        for target_id in sorted(target_groups.keys()):
            desired_interface_name = authoritative_interface_hints.get(target_id) if isinstance(authoritative_interface_hints.get(target_id), str) else None
            target_interface = _select_interface_for_target(
                target_id=target_id,
                original_interface=interface_ref,
                original_interface_component_id=original_component_id,
                interface_index=interface_index,
                desired_interface_name=desired_interface_name,
            )

            new_location = copy.deepcopy(location)
            new_interface_ref = {
                "name": target_interface.get("name"),
                "component_id": target_id,
                "semantic_role": target_interface.get("semantic_role"),
                "geometry_type": target_interface.get("geometry_type"),
                "geom_type": target_interface.get("geom_type"),
            }
            if isinstance(target_interface.get("usage"), str) and target_interface.get("usage"):
                new_interface_ref["usage"] = target_interface.get("usage")
            if isinstance(target_interface.get("source"), str) and target_interface.get("source"):
                new_interface_ref["source"] = target_interface.get("source")
            if isinstance(target_interface.get("frozen_authority"), bool):
                new_interface_ref["frozen_authority"] = bool(target_interface.get("frozen_authority"))
            new_location["interface_ref"] = new_interface_ref

            new_placement = copy.deepcopy(dict(placement))
            if base_connection_id.endswith(f"@{target_id}"):
                new_placement["connection_id"] = base_connection_id
            else:
                new_placement["connection_id"] = f"{base_connection_id}@{target_id}"
            new_placement["location"] = new_location
            new_placement["derived_changes"] = target_groups[target_id]
            if authoritative_interface_hints:
                new_placement["authoritative_interface_hints"] = copy.deepcopy(authoritative_interface_hints)

            hole_intents = placement.get("hole_intents")
            if isinstance(hole_intents, list):
                copied_hole_intents: List[Dict[str, Any]] = []
                for intent in hole_intents:
                    if not isinstance(intent, Mapping):
                        continue
                    copied_intent = copy.deepcopy(dict(intent))

                    target_surface = copied_intent.get("target_surface")
                    target_surface_obj = dict(target_surface) if isinstance(target_surface, Mapping) else {}
                    target_surface_obj["interface"] = target_interface.get("name")
                    copied_intent["target_surface"] = target_surface_obj

                    orientation = copied_intent.get("orientation")
                    orientation_obj = dict(orientation) if isinstance(orientation, Mapping) else {}
                    orientation_type = orientation_obj.get("type") if isinstance(orientation_obj.get("type"), str) else None
                    known_orientation_types = {"face_normal", "normal_to_face", "axis", "axis_interface"}
                    if target_id != original_component_id and orientation_type not in known_orientation_types:
                        orientation_obj["requires_clarification"] = True
                    copied_intent["orientation"] = orientation_obj

                    copied_hole_intents.append(copied_intent)
                new_placement["hole_intents"] = copied_hole_intents

            split_placements.append(new_placement)

    return split_placements


def _placement_authority_score(placement: Mapping[str, Any]) -> int:
    connection_id = str(placement.get("connection_id") or "")
    score = 0
    if connection_id and "_auto_" not in connection_id:
        score += 20
    if "body_support" in connection_id:
        score += 8
    if "support_structure_auto" in connection_id:
        score -= 4
    source = str(placement.get("semantic_contract_source") or placement.get("source") or "").strip().lower()
    if "connection_semantics" in source or "authoritative" in source:
        score += 4
    return score


def _dedupe_duplicate_authoritative_placements(placements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed: List[tuple[int, Dict[str, Any], tuple[Any, ...], int]] = []
    for idx, placement in enumerate(placements):
        if not isinstance(placement, dict):
            continue
        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        ref_comp = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
        mov_comp = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
        mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
        relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        interface_name = str(interface_ref.get("name") or "").strip().lower()
        side_hint = str(placement.get("seat_side") or "").strip().lower()
        if not side_hint:
            ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
            side_hint = str(ref_anchor.get("side_hint") or "").strip().lower()
        pair = tuple(sorted(cid for cid in (ref_comp, mov_comp) if isinstance(cid, str) and cid))
        if len(pair) != 2 or not mechanism or not relation_type:
            indexed.append((idx, placement, (), _placement_authority_score(placement)))
            continue
        signature = (pair, mechanism, relation_type, interface_name, side_hint)
        indexed.append((idx, placement, signature, _placement_authority_score(placement)))

    best_by_signature = {}
    passthrough = []
    for idx, placement, signature, score in indexed:
        if not signature:
            passthrough.append((idx, placement))
            continue
        current = best_by_signature.get(signature)
        if current is None or score > current[1] or (score == current[1] and idx < current[0]):
            best_by_signature[signature] = (idx, score, placement)

    kept = passthrough + [(idx, placement) for idx, _score, placement in best_by_signature.values()]
    kept.sort(key=lambda item: item[0])
    return [placement for _idx, placement in kept]


def _validate_per_target_placement_consistency(placements: List[Dict[str, Any]]) -> None:
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        location = placement.get("location")
        if not isinstance(location, Mapping):
            raise ValueError("placement.location must be an object")

        interface_ref = location.get("interface_ref")
        if not isinstance(interface_ref, Mapping):
            raise ValueError("placement.location.interface_ref must be an object")

        interface_component_id = interface_ref.get("component_id")
        if not isinstance(interface_component_id, str) or not interface_component_id:
            raise ValueError("placement.location.interface_ref.component_id must be non-empty")

        derived_changes = placement.get("derived_changes")
        if not isinstance(derived_changes, list):
            continue

        target_ids = sorted(
            {
                change.get("target_component_id")
                for change in derived_changes
                if isinstance(change, Mapping) and isinstance(change.get("target_component_id"), str)
            }
        )
        if not target_ids:
            continue

        if len(target_ids) != 1 or target_ids[0] != interface_component_id:
            raise ValueError(
                "Placement target consistency violated: "
                f"connection_id='{placement.get('connection_id')}', "
                f"interface_component_id='{interface_component_id}', "
                f"derived_targets={target_ids}"
            )

def _missing_placement_connection_ids(kg, existing_semantics) -> list[str]:
    """
    Return connection_ids that should have placement but are missing in existing_semantics["connection_placements"].
    """
    all_crs = [cr for cr in kg.get("connection_requirements", []) or [] if cr.get("purpose") in PLACEMENT_PURPOSES]
    all_ids = {cr.get("id") for cr in all_crs if isinstance(cr.get("id"), str)}
    existing = set()
    if existing_semantics and "connection_placements" in existing_semantics:
        for item in existing_semantics["connection_placements"]:
            cid = _normalize_placement_connection_id(item)
            if cid:
                existing.add(cid)
    return sorted(list(all_ids - existing))


def _ensure_placement_completeness(
    kg: dict,
    placements: list[dict],
    *,
    candidate_purposes: set[str],
) -> list[dict]:
    """
    Ensure every candidate connection_requirement id has a placement record.
    Deterministic fallback: add placeholder placement_intent/location/derived_changes with no coordinates.
    """
    components_by_id = {
        c.get("id"): c
        for c in kg.get("components", []) or []
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    candidates: Dict[str, Dict[str, Any]] = {}
    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, dict):
            continue
        purpose = cr.get("purpose")
        cr_id = cr.get("id")
        if purpose in candidate_purposes and isinstance(cr_id, str):
            candidates[cr_id] = cr

    existing_ids = set()
    normalized_placements: list[dict] = []
    for item in placements or []:
        if not isinstance(item, dict):
            continue
        cid = _normalize_placement_connection_id(item)
        if cid:
            existing_ids.add(cid)
            if "connection_id" not in item:
                item["connection_id"] = cid
        normalized_placements.append(item)

    for cr_id, cr in candidates.items():
        if cr_id in existing_ids:
            continue
        decision = cr.get("connection_decision")
        fastener_component = None
        if isinstance(decision, dict):
            fastener_ref_id = decision.get("fastener_ref_component_id")
            if isinstance(fastener_ref_id, str) and fastener_ref_id:
                fastener_component = components_by_id.get(fastener_ref_id)
        authoritative_placement = _build_authoritative_placement_from_contract(
            cr,
            fastener_component=fastener_component,
        )
        if isinstance(authoritative_placement, dict):
            normalized_placements.append(authoritative_placement)
            continue
        # Revolute joints (axis/seat) are bearing or press-fit interfaces,
        # NOT bolted connections.  Skip placeholder creation so downstream
        # processors do not synthesise meaningless bolt-circle patterns on
        # undersized hosts (e.g. 4 holes on an 8 mm axle).
        _ci = cr.get("constraint_intent")
        _mf = cr.get("mating_features") if isinstance(cr.get("mating_features"), list) else []
        if (
            _ci == "revolute"
            and set(_mf) <= {"axis", "seat", "bore", "journal"}
            and _mf  # non-empty
        ):
            continue
        normalized_placements.append({
            "connection_id": cr_id,
            "between": cr.get("between"),
            "purpose": cr.get("purpose"),
            "placement_intent": {
                "pattern_type": "unspecified",
                "symmetry": "unspecified",
                "reference": "unspecified",
                "preference": "unspecified",
                "notes": "Placeholder: will be inferred by deterministic fallback"
            },
            "location": {
                "reference_frame": "component_local",
                "interface_ref": {
                    "name": "unspecified",
                    "component_id": "unspecified"
                },
                "pattern_parameters": {
                    "type": "unspecified",
                    "offset_from_edge": 0.0,
                },
                "functional_context": {
                    "near_contact_area": False,
                    "load_bearing": False,
                    "accessible": True,
                },
                "rationale": "Placeholder: pending deterministic inference"
            },
            "derived_changes": [],
            "fastener_spec": _infer_fastener_spec(
                decision,
                fastener_component=fastener_component,
                purpose=cr.get("purpose") if isinstance(cr.get("purpose"), str) else None,
            ),
            "status": "missing_filled_placeholder"
        })

    return normalized_placements


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


def _call_llm(prompt: str) -> str | None:
    """Call OpenAI for text generation."""
    # NOTE: tests monkeypatch this function; keep the signature stable.

    global _LLM_CALL_HISTORY
    audit: Dict[str, Any] = {
        "attempted": False,
        "api_key_present": False,
        "base_url": None,
        "model": None,
        "prompt_chars": len(prompt) if isinstance(prompt, str) else None,
        "response_chars": None,
        "timeout_seconds": None,
        "max_attempts": None,
        "attempts": 0,
        "errors": [],
        "ok": False,
        "error": None,
    }

    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        audit["api_key_present"] = bool(api_key)
        if not api_key:
            _LLM_CALL_HISTORY.append(audit)
            return None

        import socket
        import time
        import urllib.error
        import urllib.parse
        import urllib.request

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip().rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        url = f"{base_url}/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

        audit["base_url"] = base_url
        audit["model"] = model
        audit["attempted"] = True

        timeout_raw = os.getenv(
            "AGENT2_OPENAI_TIMEOUT_SECONDS",
            os.getenv("OPENAI_TIMEOUT_SECONDS", "60"),
        )
        retries_raw = os.getenv(
            "AGENT2_OPENAI_MAX_RETRIES",
            os.getenv("OPENAI_MAX_RETRIES", "0"),
        )

        timeout_s = int(str(timeout_raw).strip() or "60")
        retries = int(str(retries_raw).strip() or "0")

        timeout_s = max(15, timeout_s)
        retries = max(0, retries)
        max_attempts = max(1, 1 + max(0, retries))
        audit["timeout_seconds"] = timeout_s
        audit["max_attempts"] = max_attempts

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

        parsed_url = urllib.parse.urlparse(url)
        host = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        preflight_timeout_s = min(max(3, timeout_s // 10), 8)
        if isinstance(host, str) and host:
            try:
                probe = socket.create_connection((host, int(port)), timeout=preflight_timeout_s)
                probe.close()
            except OSError as e:
                last_error = f"network_preflight_failed: {type(e).__name__}: {e}"
                audit["errors"].append(last_error)
                audit["error"] = last_error
                _LLM_CALL_HISTORY.append(audit)
                return None

        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            audit["attempts"] = attempt
            try:
                req = urllib.request.Request(
                    url=url,
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )

                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    raw = resp.read().decode("utf-8")

                obj = json.loads(raw)
                content = obj["choices"][0]["message"]["content"]
                content_s = content.strip() if isinstance(content, str) else ""
                audit["response_chars"] = len(content_s)
                audit["ok"] = bool(content_s)
                if content_s:
                    _LLM_CALL_HISTORY.append(audit)
                    return content_s

                last_error = "Empty response content"
                audit["errors"].append(last_error)
                if attempt < max_attempts:
                    time.sleep(min(2.0 * attempt, 6.0))
                    continue
                break

            except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
                last_error = f"{type(e).__name__}: {e}"
                audit["errors"].append(last_error)
                if attempt < max_attempts:
                    time.sleep(min(2.0 * attempt, 6.0))
                    continue
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                audit["errors"].append(last_error)
                break

        audit["error"] = last_error
        _LLM_CALL_HISTORY.append(audit)
        return None

    except Exception as e:
        audit["error"] = f"{type(e).__name__}: {e}"
        _LLM_CALL_HISTORY.append(audit)
        return None



# NOTE: module-level history, reset per Agent2 run().
_LLM_CALL_HISTORY: list[Dict[str, Any]] = []


def _extract_json(text: str) -> Dict[str, Any] | None:
    """Extract a JSON object from direct text or fenced-code LLM output."""
    if not isinstance(text, str) or not text.strip():
        return None

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    match = re.search(r"`(?:json)?\s*(\{.*?\})\s*`", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None

def _infer_connection_placements_llm(
    kg: Dict[str, Any],
    *,
    only_connection_ids: set[str] | None = None
) -> list[Dict[str, Any]]:
    """Infer placement intent, location, and derived changes for connections via LLM."""
    if only_connection_ids is not None and not only_connection_ids:
        return []
    # 闁哄倹澹嗗▓?purpose 閺夆晛娲﹂幎銈囨喆閸曨偄鐏?
    placement_purposes = PLACEMENT_PURPOSES
    components_by_id = {c.get("id"): c for c in kg.get("components", []) or [] if isinstance(c, dict)}
    connection_reqs = []
    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, dict):
            continue
        purpose = cr.get("purpose")
        if purpose not in placement_purposes:
            continue
        # rotation 濮掓稒顭堥鑽ゆ崉鐎圭姷绠?
        if purpose == "rotation":
            continue
        # 闁告瑯浜ｉ々锕傚嫉椤忓懏绠?placement_intent 閻庢稒顨嗛宀勫础閸愭彃璁查柨娑樼墔缁楀宕樺鍕穿閻?location_intent闁?
        if cr.get("placement_intent"):
            continue
        cr_id = cr.get("id")
        if only_connection_ids is not None and cr_id not in only_connection_ids:
            continue
        connection_reqs.append(cr)

    if not connection_reqs:
        return []

    payload = []
    for cr in connection_reqs:
        cr_id = cr.get("id")
        between = cr.get("between", [])
        if not isinstance(cr_id, str) or not (isinstance(between, list) or isinstance(between, dict)):
            continue
        # 闁衡偓椤栨稑鐦?between 濞?dict 闁?list
        between_ids = list(between.values()) if isinstance(between, dict) else between
        comp_info = []
        for cid in between_ids:
            comp = components_by_id.get(cid, {})
            comp_info.append({
                "id": cid,
                "type": comp.get("type"),
                "dimensions": comp.get("dimensions")
            })
        payload.append({
            "connection_id": cr_id,
            "purpose": cr.get("purpose"),
            "between": between,
            "component_info": comp_info,
            "connection_decision": cr.get("connection_decision"),
            "connection_semantics": cr.get("connection_semantics"),
        })

    if not payload:
        return []

    prompt = (
        "You are Agent2, a mechanical design agent. Infer detailed spatial placement for mechanical connections.\n\n"
        "CRITICAL: You must reason about WHERE features should be located, not just WHAT features are needed.\n\n"
        "For each connection, analyze:\n"
        "1. Which SURFACE/FACE the feature should be on (e.g., 'radial_outer_face', 'axial_end_face', 'mounting_flange')\n"
        "2. PATTERN POLICY ONLY: output pattern type/count and policy, DO NOT output solved numeric geometry\n"
        "3. EDGE POLICY ONLY: output edge margin policy, DO NOT output exact offset values\n"
        "4. FUNCTIONAL CONTEXT: near contact area? load bearing? accessible?\n"
        "5. AESTHETIC & PERFORMANCE: justify your placement reasoning\n\n"
        "Do NOT modify frozen fields (component dimensions/shape_semantics or connection_decision/between/connection_semantics).\nIf connection_semantics is present, it is authoritative. You MUST preserve its mechanism, anchors, and interface hints. You may only elaborate pattern policy and derived feature implications consistent with it.\n\n"
        "If connection_semantics.geometric_semantics already specifies support_topology, mount_side, clearance_policy, or requires_axial_offset, preserve those semantics exactly. Do not collapse them to a generic face or a center-mounted hole.\n"
        "When a wheel must rotate independently, do not place support members through the wheel envelope. Choose placements consistent with double-shear yoke support, fork support, or other non-interfering support topology already described upstream. Prefer double-shear yoke support when no stronger upstream topology conflicts.\n\n"
        "FORBIDDEN in LLM output (will be removed/overridden):\n"
        "- location.pattern_parameters.pattern_radius\n"
        "- location.pattern_parameters.pattern_radius_mm\n"
        "- location.pattern_parameters.offset_from_edge\n"
        "- any other solved numeric radius/edge distance\n\n"
        "Return JSON with 'placements' array. Each item must include:\n"
        "- connection_id\n"
        "- connection_mechanism (REQUIRED when connection_semantics is present; it must match frozen connection_semantics.connection_mechanism)\n"
        "- placement_intent: {pattern_type, symmetry, reference, preference:{aesthetic, performance}}\n"
        "- anchor_semantics (optional but preferred when the connection implies attachment semantics): {\n"
        "    reference_component_id: '<existing component id>',\n"
        "    moving_component_id: '<existing component id>',\n"
        "    reference_anchor: {kind: 'component_center' | 'distal_end' | 'proximal_end' | 'radial_mount_perimeter' | 'axial_face_perimeter_max' | 'axial_face_perimeter_min', axis?: 'x' | 'y' | 'z', radius_mm?: <number>, phase_deg?: <number>},\n"
        "    moving_anchor: {kind: 'component_center' | 'distal_end' | 'proximal_end' | 'proximal_mount_face_min' | 'proximal_mount_face_max', axis?: 'x' | 'y' | 'z', inset_mm?: <number>},\n"
        "    orientation_policy?: 'preserve' | 'inherit_reference_yaw' | 'radial_from_reference_center'\n"
        "  }\n"
        "- location: {\n"
        "    reference_frame: 'component_local',\n"
        "    reference_surface: '<describe which surface/face>',\n"
        "    pattern_parameters: {\n"
        "      type: 'single' | 'circular' | 'rectangular' | 'linear',\n"
        "      count: <int>,\n"
        "      radius_policy?: 'max_feasible_with_margin' | 'fraction_of_host' | 'unspecified',\n"
        "      edge_margin_policy?: 'standard' | 'min_wall_only' | 'unspecified'\n"
        "    },\n"
        "    functional_context: {\n"
        "      near_contact_area: <boolean>,\n"
        "      load_bearing: <boolean>,\n"
        "      accessible: <boolean>\n"
        "    },\n"
        "    rationale: '<explain placement reasoning>'\n"
        "  }\n"
        "- derived_changes: list of feature modifications, each with:\n"
        "    {target_component_id, feature, key_dimensions, purpose, location_note (optional)}\n\n"
        "Example for bolt circle on hub:\n"
        "{\n"
        "  \"connection_id\": \"req_fastener_hub\",\n"
        "  \"location\": {\n"
        "    \"reference_frame\": \"component_local\",\n"
        "    \"reference_surface\": \"axial_end_face_max\",\n"
        "    \"pattern_parameters\": {\n"
        "      \"type\": \"circular\",\n"
        "      \"count\": 4,\n"
        "      \"radius_policy\": \"fraction_of_host\",\n"
        "      \"edge_margin_policy\": \"standard\"\n"
        "    },\n"
        "    \"functional_context\": {\n"
        "      \"near_contact_area\": true,\n"
        "      \"load_bearing\": true,\n"
        "      \"accessible\": true\n"
        "    },\n"
        "    \"rationale\": \"Holes placed at 0.35*diameter from center for structural integrity, avoiding edge stress\"\n"
        "  }\n"
        "}\n\n"
        "Only include connection_ids provided. Use mm for all dimensions.\n\n"
        f"CONNECTIONS: {json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        response = _call_llm(prompt)
    except Exception as exc:
        print(f"WARNING: placement LLM inference failed, fallback to deterministic-only path: {exc}")
        return []
    if not isinstance(response, str):
        return []
    obj = _extract_json(response)
    if not obj:
        return []

    raw_list = obj.get("placements") or obj.get("connections") or obj.get("items")
    if not isinstance(raw_list, list):
        return []

    # 缂備焦鎸婚悗顖滅矙閸愯尙鏆伴柛鏍ㄧ壄缁变即骞嶉埀顒勫嫉婢跺﹦鎽熸繛鍫㈡暬缂嶅牓宕楅…鎺旂between/purpose 闊洤鎳橀妴蹇涘嫉婢舵稓绀塸lacement_intent/location/derived_changes 閻庢稒顨嗛宀冪疀閸涙番鈧繒鈧稒锚濠€?
    cr_map = {cr.get("id"): cr for cr in kg.get("connection_requirements", []) if isinstance(cr, dict)}
    valid_component_ids = {
        c.get("id")
        for c in kg.get("components", []) or []
        if isinstance(c, dict)
        and isinstance(c.get("id"), str)
        and not _is_subassembly_component(c)
    }
    results: list[Dict[str, Any]] = []
    valid_ids = {item["connection_id"] for item in payload}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        cid = item.get("connection_id")
        if cid not in valid_ids:
            continue
        cr = cr_map.get(cid, {})
        decision = cr.get("connection_decision")
        fastener_component = None
        if isinstance(decision, dict):
            fastener_ref_id = decision.get("fastener_ref_component_id")
            if isinstance(fastener_ref_id, str) and fastener_ref_id:
                fastener_component = components_by_id.get(fastener_ref_id)
        # 缂備焦鎸婚悗顖滄偘閵夈儱寮?
        between_ids = _between_to_ids(cr.get("between"))
        raw_changes = item.get("derived_changes") if item.get("derived_changes") is not None else []
        if not isinstance(raw_changes, list):
            raw_changes = []
        valid_anchor_component_ids = (set(between_ids) & valid_component_ids)
        contract = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=valid_anchor_component_ids,
        )
        anchor_semantics = _sanitize_anchor_semantics(
            item.get("anchor_semantics"),
            valid_component_ids=valid_anchor_component_ids,
        )
        if isinstance(contract, Mapping):
            expected_anchor = _contract_to_anchor_semantics(contract)
            if not isinstance(anchor_semantics, Mapping) or not _anchor_semantics_matches_expected(anchor_semantics, expected_anchor):
                anchor_semantics = expected_anchor
        location = item.get("location") if item.get("location") is not None else {}
        if isinstance(contract, Mapping):
            location = _merge_location_with_authoritative_interface(
                location,
                contract,
                purpose=cr.get("purpose") if isinstance(cr.get("purpose"), str) else None,
            )
        connection_mechanism = _sanitize_connection_mechanism(item.get("connection_mechanism"))
        if isinstance(contract, Mapping):
            connection_mechanism = str(contract.get("connection_mechanism") or connection_mechanism or "")
        record = {
            "connection_id": cid,
            "between": cr.get("between"),
            "purpose": cr.get("purpose"),
            "placement_intent": item.get("placement_intent") if item.get("placement_intent") is not None else {},
            "location": location,
            "derived_changes": _filter_derived_changes(
                raw_changes,
                allowed_component_ids=set(between_ids) & valid_component_ids,
            ),
            "fastener_spec": _infer_fastener_spec(
                decision,
                fastener_component=fastener_component,
                purpose=cr.get("purpose") if isinstance(cr.get("purpose"), str) else None,
            ),
            **({"anchor_semantics": anchor_semantics} if isinstance(anchor_semantics, dict) else {}),
            **({"geometric_semantics": copy.deepcopy(contract.get("geometric_semantics"))} if isinstance(contract, Mapping) and isinstance(contract.get("geometric_semantics"), Mapping) else {}),
            **({"connection_mechanism": connection_mechanism} if isinstance(connection_mechanism, str) and connection_mechanism else {}),
        }
        if isinstance(contract, Mapping):
            record["authoritative_contract"] = True
            record["semantic_contract_source"] = _AUTHORITATIVE_INTERFACE_REF_SOURCE
        results.append(record)

    return results


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


def _rank_host_component(comp: Dict[str, Any]) -> int:
    """Rank component suitability as feature host (lower = higher priority)."""
    comp_id = comp.get("id")
    comp_type = comp.get("type")
    if not isinstance(comp_type, str):
        return 100
    if comp_type.lower() == "subassembly" or (
        isinstance(comp_id, str) and "assembly" in comp_id.lower()
    ):
        # Subassemblies are containers; do not place hole features on them.
        return 2000
    if _is_fastener_type(comp_type) or (
        isinstance(comp_id, str)
        and any(tok in comp_id.lower() for tok in ("fastener", "bolt", "screw", "nut", "washer", "pin"))
    ):
        return 1000
    t = comp_type.lower()
    priority = [
        "hub",
        "housing",
        "frame",
        "carrier_plate",
        "plate",
        "arm",
        "bracket",
        "mounting_flange",
        "wheel_body",
        "wheel",
        "coupling_body",
        "gear",
        "pulley",
    ]
    for idx, key in enumerate(priority):
        if key in t:
            return idx
    if _is_plate_like_component(comp):
        return 20
    return 50


def _choose_feature_host(components: Dict[str, Dict[str, Any]], candidate_ids: list[str]) -> str | None:
    candidates = []
    for cid in candidate_ids:
        comp = components.get(cid)
        if not isinstance(comp, dict):
            continue
        candidates.append((cid, _rank_host_component(comp)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[1])
    return candidates[0][0]


def _is_modelable_execution_component(comp: Mapping[str, Any]) -> bool:
    if not isinstance(comp, Mapping):
        return False
    ctype = comp.get("type")
    if isinstance(ctype, str) and _is_fastener_type(ctype):
        return False
    return not _is_subassembly_component(dict(comp))



def _build_component_children_index(components: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[str]]:
    children: Dict[str, List[str]] = {}
    for cid, comp in components.items():
        if not isinstance(cid, str) or not cid:
            continue
        if not isinstance(comp, Mapping):
            continue
        parent_id = comp.get("parent_id")
        if isinstance(parent_id, str) and parent_id:
            children.setdefault(parent_id, []).append(cid)
    return children



def _collect_descendant_component_ids(
    components: Mapping[str, Mapping[str, Any]],
    root_id: str,
    *,
    max_depth: int = 3,
) -> list[str]:
    if not isinstance(root_id, str) or not root_id:
        return []
    children_index = _build_component_children_index(components)
    seen: set[str] = set()
    ordered: list[str] = []
    frontier: list[tuple[str, int]] = [(root_id, 0)]
    while frontier:
        current_id, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for child_id in children_index.get(current_id, []):
            if child_id in seen:
                continue
            seen.add(child_id)
            ordered.append(child_id)
            frontier.append((child_id, depth + 1))
    return ordered



def _is_authoritative_host_candidate(
    comp: Mapping[str, Any],
    *,
    mechanism: str,
    moving_component_id: str | None,
) -> bool:
    if not _is_modelable_execution_component(comp):
        return False
    cid = comp.get("id")
    if isinstance(cid, str) and isinstance(moving_component_id, str) and cid == moving_component_id:
        return False
    ctype = str(comp.get("type") or "").strip().lower()
    if not ctype:
        return False
    if mechanism == "press_fit":
        if ctype in {"bearing", "tire", "spacer", "washer", "bushing"}:
            return False
        if any(tok in ctype for tok in ("shaft", "axle", "fastener", "bolt", "screw", "nut", "washer", "pin")):
            return False
    return True



def _resolve_authoritative_modeling_host_component(
    *,
    comp_by_id: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> str | None:
    reference_id = str(contract.get("reference_component_id") or "").strip()
    moving_id = str(contract.get("moving_component_id") or "").strip() or None
    mechanism = _sanitize_connection_mechanism(contract.get("connection_mechanism")) or ""
    relation_type = str(contract.get("relation_type") or "").strip().lower()
    reference_comp = comp_by_id.get(reference_id) if isinstance(reference_id, str) and reference_id else None
    moving_comp = comp_by_id.get(moving_id) if isinstance(moving_id, str) and moving_id else None
    reference_type = str(reference_comp.get("type") or "").strip().lower() if isinstance(reference_comp, Mapping) else ""
    moving_type = str(moving_comp.get("type") or "").strip().lower() if isinstance(moving_comp, Mapping) else ""

    prefer_moving_host = (
        mechanism == "shaft_bore_fit"
        and reference_type in {"shaft", "axle"}
        and moving_type not in {"shaft", "axle", "bearing", "spacer", "washer", "bushing"}
        and relation_type not in {"support_member_distal_attachment", "bearing_inner_race_revolute_fit"}
    )
    if prefer_moving_host:
        if isinstance(moving_comp, Mapping) and _is_authoritative_host_candidate(moving_comp, mechanism=mechanism, moving_component_id=reference_id):
            return moving_id
        moving_candidate_ids = _collect_descendant_component_ids(comp_by_id, moving_id, max_depth=3)
        moving_candidates: list[str] = []
        for cid in moving_candidate_ids:
            comp = comp_by_id.get(cid)
            if not isinstance(comp, Mapping):
                continue
            if not _is_authoritative_host_candidate(comp, mechanism=mechanism, moving_component_id=reference_id):
                continue
            moving_candidates.append(cid)
        resolved = _choose_feature_host(dict(comp_by_id), moving_candidates) if moving_candidates else None
        if isinstance(resolved, str) and resolved:
            return resolved

    if isinstance(reference_comp, Mapping) and _is_authoritative_host_candidate(reference_comp, mechanism=mechanism, moving_component_id=moving_id):
        return reference_id

    candidate_ids = _collect_descendant_component_ids(comp_by_id, reference_id, max_depth=3)
    candidates: list[str] = []
    for cid in candidate_ids:
        comp = comp_by_id.get(cid)
        if not isinstance(comp, Mapping):
            continue
        if not _is_authoritative_host_candidate(comp, mechanism=mechanism, moving_component_id=moving_id):
            continue
        ctype = str(comp.get("type") or "").strip().lower()
        shape = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        shape_type = str(shape.get("type") or "").strip().lower()
        if mechanism == "press_fit" and str(contract.get("relation_type") or "").strip().lower() == "bearing_outer_race_seat":
            if ctype not in {"rim", "hub", "housing", "body", "wheel_body", "wheel", "carrier_plate", "plate", "arm", "bracket"} and shape_type not in {"annular", "cylindrical", "prismatic"}:
                continue
            if ctype == "tire":
                continue
        candidates.append(cid)

    return _choose_feature_host(dict(comp_by_id), candidates) if candidates else None



def _resolve_authoritative_execution_interface_ref(
    *,
    contract: Mapping[str, Any],
    purpose: str | None,
    comp_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    reference_id = str(contract.get("reference_component_id") or "").strip() or "unspecified"
    moving_id = str(contract.get("moving_component_id") or "").strip() or "unspecified"
    mechanism = _sanitize_connection_mechanism(contract.get("connection_mechanism")) or ""
    interface_name = str(contract.get("reference_interface_hint") or "").strip() or "unspecified"
    component_id = reference_id
    audit: Dict[str, Any] = {"source": "authoritative_contract_execution_mapping"}

    reference_comp = comp_by_id.get(reference_id) if isinstance(reference_id, str) and reference_id else None
    moving_comp = comp_by_id.get(moving_id) if isinstance(moving_id, str) and moving_id else None
    reference_type = str(reference_comp.get("type") or "").strip().lower() if isinstance(reference_comp, Mapping) else ""
    moving_type = str(moving_comp.get("type") or "").strip().lower() if isinstance(moving_comp, Mapping) else ""

    if (
        mechanism == "shaft_bore_fit"
        and reference_type in {"shaft", "axle"}
        and _is_modelable_execution_component(moving_comp)
        and moving_type not in {"shaft", "axle", "bearing", "spacer", "washer", "bushing"}
    ):
        component_id = moving_id
        interface_name = str(contract.get("moving_interface_hint") or "bore_axis").strip() or "bore_axis"
        audit.update({
            "source": "authoritative_shaft_host_resolution",
            "semantic_reference_component_id": reference_id,
            "execution_component_id": moving_id,
        })
    elif mechanism == "companion_rotation_relation" and not _is_modelable_execution_component(reference_comp):
        if _is_modelable_execution_component(moving_comp):
            component_id = moving_id
            interface_name = str(contract.get("moving_interface_hint") or "shaft_axis").strip() or "shaft_axis"
            audit.update({
                "source": "authoritative_external_counterpart_resolution",
                "semantic_reference_component_id": reference_id,
                "execution_component_id": moving_id,
            })
    elif not _is_modelable_execution_component(reference_comp):
        resolved_host = _resolve_authoritative_modeling_host_component(comp_by_id=comp_by_id, contract=contract)
        if isinstance(resolved_host, str) and resolved_host:
            component_id = resolved_host
            audit.update({
                "source": "authoritative_reference_host_resolution",
                "semantic_reference_component_id": reference_id,
                "execution_component_id": resolved_host,
            })

    semantic_role = _infer_interface_role_from_purpose(purpose if isinstance(purpose, str) else None)
    geometry_type = _infer_geometry_type_from_interface_id(interface_name, semantic_role)
    return {
        "name": interface_name,
        "component_id": component_id,
        "semantic_role": semantic_role,
        "geometry_type": geometry_type,
        "geom_type": geometry_type,
        "source": _AUTHORITATIVE_INTERFACE_REF_SOURCE,
        "frozen_authority": True,
    }, audit



def _retarget_authoritative_host_side_features(
    placement: Dict[str, Any],
    *,
    mechanism_name: str,
    host_component_id: str | None,
) -> None:
    if not isinstance(host_component_id, str) or not host_component_id:
        return
    features_by_mechanism = {
        "press_fit": {"bearing_seat", "press_fit_zone", "retainer_groove", "seal_groove"},
        "shaft_bore_fit": {"shaft_bore", "press_fit_zone", "standoff_bore"},
        "axial_stack_locator": {"standoff_bore"},
    }
    host_features = features_by_mechanism.get(mechanism_name)
    if not isinstance(host_features, set):
        return
    derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
    for change in derived_changes:
        if not isinstance(change, dict):
            continue
        feature = str(change.get("feature") or "").strip().lower()
        if feature in host_features:
            change["target_component_id"] = host_component_id
    placement["derived_changes"] = derived_changes



def _append_authoritative_execution_mapping_audit(
    placement: Dict[str, Any],
    *,
    action: str,
    detail: Mapping[str, Any],
) -> None:
    feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
    existing_actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
    existing_audit = feasibility.get("fallback_audit") if isinstance(feasibility.get("fallback_audit"), list) else []
    if action not in existing_actions:
        feasibility["fallback_actions"] = existing_actions + [action]
    feasibility["fallback_audit"] = existing_audit + [{
        "action": action,
        **dict(detail),
        "functional_intent_changed": False,
    }]
    placement["feasibility"] = feasibility



def _enforce_authoritative_contract_execution_mapping(kg: Dict[str, Any], placements: list[dict]) -> None:
    comp_by_id = _build_comp_by_id(kg)
    connection_by_id: Dict[str, Dict[str, Any]] = {
        cr["id"]: cr
        for cr in kg.get("connection_requirements", []) or []
        if isinstance(cr, dict) and isinstance(cr.get("id"), str)
    }

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        connection_id = _normalize_placement_connection_id(placement)
        if not isinstance(connection_id, str) or not connection_id:
            continue
        connection = connection_by_id.get(connection_id)
        if not isinstance(connection, Mapping):
            continue

        contract_between_ids = _between_to_ids(connection.get("between"))
        contract = _sanitize_connection_semantics_contract(
            connection.get("connection_semantics"),
            valid_component_ids={cid for cid in contract_between_ids if isinstance(cid, str)},
        )
        if not isinstance(contract, Mapping):
            continue

        mechanism_name = _sanitize_connection_mechanism(contract.get("connection_mechanism")) or ""
        placement["authoritative_contract"] = True
        placement["semantic_contract_source"] = _AUTHORITATIVE_INTERFACE_REF_SOURCE
        placement["connection_mechanism"] = mechanism_name
        placement["anchor_semantics"] = _contract_to_anchor_semantics(contract)
        if isinstance(contract.get("geometric_semantics"), Mapping):
            placement["geometric_semantics"] = copy.deepcopy(contract.get("geometric_semantics"))

        purpose = connection.get("purpose") if isinstance(connection.get("purpose"), str) else placement.get("purpose")
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref, audit = _resolve_authoritative_execution_interface_ref(
            contract=contract,
            purpose=purpose if isinstance(purpose, str) else None,
            comp_by_id=comp_by_id,
        )
        location = copy.deepcopy(location)
        location["reference_frame"] = "component_local"
        location["interface_ref"] = interface_ref
        pattern_params = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if mechanism_name in {"press_fit", "shaft_bore_fit", "companion_rotation_relation", "axial_stack_locator"}:
            pattern_params["type"] = "single"
            pattern_params["count"] = 1
            for key in (
                "pattern_radius",
                "pattern_radius_mm",
                "spacing",
                "radius_policy",
                "edge_margin_policy",
                "preserve_single_circular",
                "start_angle_rad",
                "start_angle",
                "phase_deg",
                "pcd_group",
            ):
                pattern_params.pop(key, None)
            flags = _sanitize_placement_flags(placement.get("flags"))
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            placement.pop("fastener_spec", None)
        location["pattern_parameters"] = pattern_params
        placement["location"] = location

        host_component_id = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else None
        _retarget_authoritative_host_side_features(
            placement,
            mechanism_name=mechanism_name,
            host_component_id=host_component_id,
        )
        if mechanism_name == "axial_stack_locator":
            placement["derived_changes"] = [
                change
                for change in (placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else [])
                if isinstance(change, dict) and str(change.get("feature") or "").strip().lower() not in {"bearing_seat", "press_fit_zone", "standoff_bore", "hole", "bolt_circle_pattern"}
            ]

        audit_source = str(audit.get("source") or "")
        if audit_source and audit_source != "authoritative_contract_execution_mapping":
            _append_authoritative_execution_mapping_audit(
                placement,
                action="authoritative_execution_mapping_resolved",
                detail=dict(audit),
            )




def _specialize_opposed_bearing_seat_placements(kg: Dict[str, Any], placements: list[dict]) -> None:
    def _seat_side_from_bearing_id(component_id: Any) -> str | None:
        cid = str(component_id or "").strip().lower()
        match = re.search(r"_bearing_(\d+)$", cid)
        if not match:
            return None
        try:
            index = int(match.group(1))
        except Exception:
            return None
        return "min" if index % 2 == 1 else "max"

    def _seat_sort_key(component_id: str) -> tuple[int, str]:
        match = re.search(r"_bearing_(\d+)$", str(component_id or "").strip().lower())
        if match:
            try:
                return (int(match.group(1)), str(component_id))
            except Exception:
                pass
        return (9999, str(component_id))

    grouped: Dict[str, Dict[str, list[dict]]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        mechanism_name = _sanitize_connection_mechanism(placement.get("connection_mechanism")) or ""
        if mechanism_name != "press_fit":
            continue
        anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        relation_type = str(anchor_semantics.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        if relation_type != "bearing_outer_race_seat":
            continue
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        host_component_id = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else anchor_semantics.get("reference_component_id")
        bearing_component_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
        if not isinstance(host_component_id, str) or not host_component_id or not isinstance(bearing_component_id, str) or not bearing_component_id:
            continue
        grouped.setdefault(host_component_id, {}).setdefault(bearing_component_id, []).append(placement)

    for host_component_id, placements_by_bearing in grouped.items():
        bearing_ids = sorted(placements_by_bearing.keys(), key=_seat_sort_key)
        if len(bearing_ids) < 2:
            continue
        fallback_sides = {bearing_ids[0]: "min", bearing_ids[1]: "max"}
        for bearing_component_id, bearing_placements in placements_by_bearing.items():
            seat_side = _seat_side_from_bearing_id(bearing_component_id) or fallback_sides.get(bearing_component_id)
            if seat_side not in {"min", "max"}:
                continue
            interface_name = f"bearing_seat_{seat_side}"
            face_interface_id = f"axial_end_face_{seat_side}"
            side_hint = seat_side.upper()
            for placement in bearing_placements:
                location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
                semantic_role = str(interface_ref.get("semantic_role") or _infer_interface_role_from_purpose(placement.get("purpose") if isinstance(placement.get("purpose"), str) else None)).strip() or "support"
                geometry_type = _infer_geometry_type_from_interface_id(interface_name, semantic_role)
                interface_ref["name"] = interface_name
                interface_ref["component_id"] = host_component_id
                interface_ref["semantic_role"] = semantic_role
                interface_ref["geometry_type"] = geometry_type
                interface_ref["geom_type"] = geometry_type
                location["interface_ref"] = interface_ref
                placement["location"] = location

                anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
                anchor_semantics["reference_interface_hint"] = interface_name
                anchor_semantics["assembly_reference_interface_hint"] = interface_name
                placement["reference_interface_hint"] = interface_name
                placement["assembly_reference_interface_hint"] = interface_name
                placement["anchor_semantics"] = anchor_semantics

                geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
                geometric_semantics["mount_side"] = face_interface_id
                geometric_semantics["requires_axial_offset"] = True
                placement["geometric_semantics"] = geometric_semantics
                placement["seat_side"] = seat_side

                derived_changes = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
                for change in derived_changes:
                    if not isinstance(change, dict):
                        continue
                    feature = str(change.get("feature") or "").strip().lower()
                    if feature not in {"bearing_seat", "press_fit_zone", "retainer_groove", "seal_groove"}:
                        continue
                    change["target_component_id"] = host_component_id
                    change["face_interface_id"] = face_interface_id
                    change["side_hint"] = side_hint
                    anchor = change.get("anchor") if isinstance(change.get("anchor"), dict) else {}
                    anchor["face_interface_id"] = face_interface_id
                    anchor["side_hint"] = side_hint
                    change["anchor"] = anchor
                placement["derived_changes"] = derived_changes

def _expand_host_candidates_with_parents(
    components: Dict[str, Dict[str, Any]],
    candidate_ids: list[str],
    *,
    max_depth: int = 2,
) -> list[str]:
    """Deterministically expand host candidates with parent chain.

    This is a closure step to avoid choosing connector-only children (e.g. fastener_set)
    or overly small shaft-like children (e.g. axle) as the only host when a parent
    provides the actual modelable mounting surface.
    """

    seen: set[str] = set()
    expanded: list[str] = []

    def _add(cid: str) -> None:
        if cid in seen:
            return
        seen.add(cid)
        expanded.append(cid)

    for cid in candidate_ids:
        if isinstance(cid, str) and cid:
            _add(cid)

    for cid in list(expanded):
        cur = cid
        depth = 0
        while depth < max_depth:
            comp = components.get(cur)
            if not isinstance(comp, dict):
                break
            parent = comp.get("parent_id")
            if not isinstance(parent, str) or not parent:
                break
            if parent not in components:
                break
            _add(parent)
            cur = parent
            depth += 1

    return expanded


def _apply_deterministic_placement_intents(kg: Dict[str, Any], placements: list[dict]) -> None:
    comp_by_id = _build_comp_by_id(kg)
    connection_map = {
        cr.get("id"): cr
        for cr in kg.get("connection_requirements", []) or []
        if isinstance(cr, dict) and isinstance(cr.get("id"), str)
    }
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        # Preserve non-placeholder placement_intent/location, but still validate anchor semantics.
        existing_intent = placement.get("placement_intent")
        preserve_existing_intent = False
        if existing_intent and isinstance(existing_intent, dict):
            pattern_type = existing_intent.get("pattern_type")
            if pattern_type and pattern_type != "unspecified":
                preserve_existing_intent = True
        between = placement.get("between", [])
        if isinstance(between, dict):
            between_ids = [cid for cid in between.keys() if isinstance(cid, str)]
        elif isinstance(between, list):
            between_ids = [cid for cid in between if isinstance(cid, str)]
        else:
            continue
        host_candidates = _expand_host_candidates_with_parents(comp_by_id, between_ids, max_depth=2)
        host_id = _choose_feature_host(comp_by_id, host_candidates)
        host = comp_by_id.get(host_id, {}) if host_id else {}
        host_dims = host.get("dimensions") if isinstance(host.get("dimensions"), dict) else {}
        host_plate = _is_plate_like_component(host)
        default_count = 4
        conn = connection_map.get(placement.get("connection_id"), {})
        placement_purpose = placement.get("purpose") if isinstance(placement.get("purpose"), str) else None
        purpose = conn.get("purpose") if isinstance(conn.get("purpose"), str) and conn.get("purpose") else (placement_purpose or "unknown")
        connection_decision = conn.get("connection_decision") if isinstance(conn.get("connection_decision"), dict) else {}
        bundle_count = None
        fastener_ref_id = connection_decision.get("fastener_ref_component_id") if isinstance(connection_decision, dict) else None
        fastener_component = comp_by_id.get(fastener_ref_id) if isinstance(fastener_ref_id, str) else None
        if isinstance(fastener_component, dict):
            bundle_pattern = fastener_component.get("pattern")
            if isinstance(bundle_pattern, dict):
                bundle_pattern_count = bundle_pattern.get("count")
                if isinstance(bundle_pattern_count, int) and bundle_pattern_count >= 1:
                    bundle_count = int(bundle_pattern_count)
        if not isinstance(placement.get("fastener_spec"), dict):
            inferred_fastener_spec = _infer_fastener_spec(
                connection_decision,
                fastener_component=fastener_component,
                purpose=purpose if isinstance(purpose, str) else None,
            )
            if isinstance(inferred_fastener_spec, dict):
                placement["fastener_spec"] = inferred_fastener_spec
        inferred_count, inferred_pattern_type, engineering_rule = infer_bolt_count_and_pattern(
            purpose=purpose if isinstance(purpose, str) else None,
            method=connection_decision.get("method") if isinstance(connection_decision, dict) else None,
            decision_count=connection_decision.get("count") if isinstance(connection_decision, dict) else None,
            bundle_count=bundle_count,
        )
        pattern_count = int(inferred_count) if isinstance(inferred_count, int) else default_count
        is_single_pattern = pattern_count <= 1
        fastener_size = connection_decision.get("fastener_size")
        nominal, _ = _parse_fastener_size(fastener_size) if isinstance(fastener_size, str) else (None, None)
        
        # Infer feature diameter based on purpose and fastener size
        if nominal:  # Fastening with known size
            hole_diameter = round(nominal + 0.5, 2)
        elif purpose in {"fastening_mechanism", "structural_fixation"}:
            hole_diameter = 5.0  # Default M4-M5 range
        elif purpose == "load_support":
            hole_diameter = 8.0  # Bearing seats typically larger
        elif purpose == "rotation_support":
            hole_diameter = 10.0  # Shaft bores
        else:
            hole_diameter = 6.0  # Generic feature
        
        thickness = host_dims.get("thickness") if host_dims else None
        
        min_edge_distance, offset_from_edge = _compute_edge_constraints(hole_diameter, host_plate, thickness)
        
        pattern_radius = None
        spacing = None
        interface_name = "unspecified"
        existing_location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        existing_interface_ref = existing_location.get("interface_ref") if isinstance(existing_location.get("interface_ref"), dict) else {}
        existing_interface_name = existing_interface_ref.get("name") if isinstance(existing_interface_ref.get("name"), str) else None
        existing_interface_component_id = existing_interface_ref.get("component_id") if isinstance(existing_interface_ref.get("component_id"), str) else None
        preserve_semantic_interface_ref = (
            (
                _is_semantic_placeholder_interface_name(existing_interface_name)
                or existing_interface_ref.get("frozen_authority") is True
            )
            and isinstance(existing_interface_component_id, str)
            and existing_interface_component_id in {
                cid
                for cid in between_ids
                if isinstance(cid, str)
                and cid in comp_by_id
                and not _is_fastener_type(comp_by_id[cid].get("type"))
            }
        )
        
        if host_dims:
            radius = host_dims.get("outer_radius") or host_dims.get("radius")
            diameter = host_dims.get("outer_diameter") or host_dims.get("diameter")
            width = host_dims.get("width") or host_dims.get("arm_width")
            length = host_dims.get("length") or host_dims.get("arm_length") or host_dims.get("depth")
            
            # Infer reference surface based on component shape
            host_shape = host.get("shape_semantics", {})
            shape_type = host_shape.get("type") if isinstance(host_shape, dict) else None
            
            if shape_type in {"cylindrical", "annular"}:
                if purpose in {"fastening_mechanism", "structural_fixation", "structural_clamping", "support_to_structure"}:
                    interface_name = "axial_end_face_max"
                else:
                    interface_name = "radial_outer_face"
            elif shape_type == "prismatic":
                interface_name = "top_face"
            elif host_plate:
                interface_name = "mounting_face"
            
            if (not is_single_pattern) and diameter:
                # Circular pattern: pick the largest feasible radius not exceeding a reasonable ideal.
                max_radius = float(diameter) / 2 - offset_from_edge
                ideal_radius = float(diameter) * 0.35
                pattern_radius = round(min(ideal_radius, max_radius), 2) if max_radius > 0 else None
            elif (not is_single_pattern) and radius:
                max_radius = float(radius) - offset_from_edge
                ideal_radius = float(radius) * 0.7
                pattern_radius = round(min(ideal_radius, max_radius), 2) if max_radius > 0 else None
            
            if (not is_single_pattern) and host_plate:
                spacing = _resolve_rectangular_spacing(host_dims, offset_from_edge)
        
        if is_single_pattern:
            pattern_type = "single"
        else:
            pattern_type = "rectangular" if host_plate else "circular"
        if inferred_pattern_type == "single":
            pattern_type = "single"
        elif inferred_pattern_type == "bolt_circle" and pattern_type != "rectangular":
            pattern_type = "circular"

        symmetry = "single" if pattern_type == "single" else ("bilateral" if pattern_type == "rectangular" else "radial")
        
        placement_intent = {
            "pattern_type": pattern_type,
            "symmetry": symmetry,
            "reference": host_id or "component_center",
            "preference": {"aesthetic": "balanced", "performance": "stiff"},
        }
        
        # Determine functional context based on purpose
        functional_context = {
            "near_contact_area": purpose in {"fastening_mechanism", "structural_fixation", "load_support"},
            "load_bearing": purpose in {"load_support", "fastening_mechanism", "structural_fixation", "support_to_structure"},
            "accessible": True,
        }
        
        # Generate rationale
        if pattern_type == "single":
            geo_desc = "single feature"
        elif pattern_radius:
            geo_desc = f"{pattern_type} pattern at R={pattern_radius}mm"
        elif spacing:
            geo_desc = f"{pattern_type} pattern with {spacing.get('x')}x{spacing.get('y')}mm spacing"
        else:
            geo_desc = f"{pattern_type} pattern (dimensions pending)"
        
        purpose_desc = {
            "fastening_mechanism": "fastening connection",
            "structural_fixation": "structural fixation",
            "load_support": "load support interface",
            "rotation_support": "rotation support interface",
            "support_to_structure": "structural support",
        }.get(purpose, purpose)
        
        interface_role = _infer_interface_role_from_purpose(purpose if isinstance(purpose, str) else None)
        interface_name_for_location = existing_interface_name if preserve_semantic_interface_ref else interface_name
        interface_component_for_location = existing_interface_component_id if preserve_semantic_interface_ref else (host_id or "unspecified")
        interface_geo = _infer_geometry_type_from_interface_id(interface_name_for_location, interface_role)
        rationale = f"Deterministic: {geo_desc} on {interface_name_for_location} for {purpose_desc}. Edge safety: {offset_from_edge}mm (>= {min_edge_distance}mm min)"

        location_interface_ref = dict(existing_interface_ref) if preserve_semantic_interface_ref else {}
        location_interface_ref["name"] = interface_name_for_location
        location_interface_ref["component_id"] = interface_component_for_location
        if not isinstance(location_interface_ref.get("semantic_role"), str) or not location_interface_ref.get("semantic_role"):
            location_interface_ref["semantic_role"] = interface_role
        location_interface_ref["geometry_type"] = interface_geo
        location_interface_ref["geom_type"] = interface_geo

        location = {
            "reference_frame": "component_local",
            "interface_ref": location_interface_ref,
            "pattern_parameters": {
                "type": pattern_type,
                "count": pattern_count,
                **({"pattern_radius": pattern_radius} if pattern_radius else {}),
                **({"spacing": spacing} if spacing else {}),
                "start_angle": 0.0,
                "offset_from_edge": offset_from_edge,
                **({"engineering_rule": engineering_rule} if isinstance(engineering_rule, dict) else {}),
            },
            "functional_context": functional_context,
            "safety_constraints": {
                "min_edge_distance": min_edge_distance,
                "feature_diameter": hole_diameter,
            },
            "rationale": rationale,
        }

        valid_anchor_component_ids = {
            cid
            for cid in between_ids
            if isinstance(cid, str)
            and cid in comp_by_id
            and not _is_fastener_type(comp_by_id[cid].get("type"))
        }
        anchor_semantics = _sanitize_anchor_semantics(
            placement.get("anchor_semantics"),
            valid_component_ids=valid_anchor_component_ids,
        )
        inferred_anchor_semantics = _infer_anchor_semantics_for_placement(
            placement=placement,
            comp_by_id=comp_by_id,
        )
        if anchor_semantics is None:
            if isinstance(inferred_anchor_semantics, dict):
                feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
                existing_actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
                existing_audit = feasibility.get("fallback_audit") if isinstance(feasibility.get("fallback_audit"), list) else []
                feasibility["fallback_actions"] = existing_actions + ["anchor_semantics_inferred_from_missing_upstream_semantics"]
                feasibility["fallback_audit"] = existing_audit + [
                    {
                        "action": "anchor_semantics_inferred_from_missing_upstream_semantics",
                        "inferred": dict(inferred_anchor_semantics),
                        "reason": "upstream placement omitted anchor semantics; deterministic solver filled a geometric placeholder",
                        "functional_intent_changed": False,
                    }
                ]
                placement["feasibility"] = feasibility
            anchor_semantics = inferred_anchor_semantics
        elif (
            isinstance(inferred_anchor_semantics, dict)
            and not _anchor_semantics_matches_expected(anchor_semantics, inferred_anchor_semantics)
        ):
            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
            existing_actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
            existing_audit = feasibility.get("fallback_audit") if isinstance(feasibility.get("fallback_audit"), list) else []
            if placement.get("authoritative_contract") is True and isinstance(placement.get("geometric_semantics"), Mapping):
                if _authoritative_anchor_semantics_can_absorb_numeric_refinement(anchor_semantics, inferred_anchor_semantics):
                    refined_anchor_semantics = _merge_authoritative_anchor_numeric_refinement(anchor_semantics, inferred_anchor_semantics)
                    if refined_anchor_semantics != anchor_semantics:
                        feasibility["fallback_actions"] = existing_actions + ["authoritative_anchor_numeric_fields_completed"]
                        feasibility["fallback_audit"] = existing_audit + [{
                            "action": "authoritative_anchor_numeric_fields_completed",
                            "original": dict(anchor_semantics),
                            "completed": dict(refined_anchor_semantics),
                            "reason": "deterministic solver only supplied missing numeric anchor fields; authoritative relation semantics were preserved",
                            "functional_intent_changed": False,
                        }]
                        anchor_semantics = refined_anchor_semantics
                else:
                    support_topology = str(placement.get("geometric_semantics", {}).get("support_topology") or "").strip().lower()
                    contact_model = str(placement.get("geometric_semantics", {}).get("contact_model") or "").strip().lower()
                    mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
                    if (
                        mechanism_name == "axial_face_bolted_mount"
                        and support_topology == "hub_radial_slot_mount"
                        and contact_model in {"slot_insert_with_bolted_retention", "through_bolt_clamp_in_radial_slot"}
                    ):
                        feasibility["fallback_actions"] = existing_actions + ["authoritative_slot_mount_anchor_semantics_preserved"]
                        feasibility["fallback_audit"] = existing_audit + [{
                            "action": "authoritative_slot_mount_anchor_semantics_preserved",
                            "original": dict(anchor_semantics),
                            "deterministic_candidate": dict(inferred_anchor_semantics),
                            "reason": "authoritative slot-mount anchor semantics were preserved because the deterministic solver only proposed an alternate proximal-face anchor for the same rigid slot capture relation",
                            "functional_intent_changed": False,
                        }]
                        flags = _sanitize_placement_flags(placement.get("flags"))
                        flags.pop("suppress_hole_generation", None)
                        placement["flags"] = flags
                        placement["requires_clarification"] = False
                        placement.pop("clarification_reason", None)
                        if str(placement.get("status") or "").strip().lower() == "requires_clarification":
                            placement["status"] = "ok"
                    else:
                        feasibility["fallback_actions"] = existing_actions + ["authoritative_anchor_semantics_conflict_with_deterministic_solver"]
                        feasibility["fallback_audit"] = existing_audit + [{
                            "action": "authoritative_anchor_semantics_conflict_with_deterministic_solver",
                            "original": dict(anchor_semantics),
                            "deterministic_candidate": dict(inferred_anchor_semantics),
                            "reason": "authoritative upstream anchor semantics were more specific than deterministic inference; rewrite was blocked",
                            "functional_intent_changed": False,
                        }]
                        flags = _sanitize_placement_flags(placement.get("flags"))
                        flags["suppress_hole_generation"] = True
                        placement["flags"] = flags
                        placement["requires_clarification"] = True
                        placement["clarification_reason"] = "authoritative_anchor_semantics_conflict_with_deterministic_solver"
                        placement["status"] = "requires_clarification"
                placement["feasibility"] = feasibility
            elif _anchor_semantics_can_be_specialized(anchor_semantics, inferred_anchor_semantics):
                feasibility["fallback_actions"] = existing_actions + ["anchor_semantics_specialized_from_generic_placeholder"]
                feasibility["fallback_audit"] = existing_audit + [{
                    "action": "anchor_semantics_specialized_from_generic_placeholder",
                    "original": dict(anchor_semantics),
                    "specialized": dict(inferred_anchor_semantics),
                    "reason": "generic anchor semantics lacked sufficient geometric specificity",
                    "functional_intent_changed": False,
                }]
                placement["feasibility"] = feasibility
                anchor_semantics = inferred_anchor_semantics
            else:
                feasibility["fallback_actions"] = existing_actions + ["anchor_semantics_overridden_by_deterministic_solver"]
                feasibility["fallback_audit"] = existing_audit + [{
                    "action": "anchor_semantics_overridden_by_deterministic_solver",
                    "original": dict(anchor_semantics),
                    "corrected": dict(inferred_anchor_semantics),
                    "reason": "existing anchor semantics conflicted with deterministic geometric relation inference",
                    "functional_intent_changed": False,
                }]
                placement["feasibility"] = feasibility
                anchor_semantics = inferred_anchor_semantics

        if _placement_requires_explicit_fastener_mount_clarification(placement=placement, connection=conn):
            _force_single_pattern_layout(location, placement_intent)
            feasibility = placement.get("feasibility") if isinstance(placement.get("feasibility"), dict) else {}
            existing_actions = feasibility.get("fallback_actions") if isinstance(feasibility.get("fallback_actions"), list) else []
            existing_audit = feasibility.get("fallback_audit") if isinstance(feasibility.get("fallback_audit"), list) else []
            action_name = "generic_fastener_mount_requires_explicit_anchor_semantics"
            if action_name not in existing_actions:
                feasibility["fallback_actions"] = existing_actions + [action_name]
                feasibility["fallback_audit"] = existing_audit + [
                    {
                        "action": action_name,
                        "reason": "auto-filled fastener decision lacked explicit anchor semantics; deterministic hole or mount generation is disallowed",
                        "functional_intent_changed": False,
                    }
                ]
            placement["feasibility"] = feasibility
            flags = _sanitize_placement_flags(placement.get("flags"))
            flags["suppress_hole_generation"] = True
            placement["flags"] = flags
            placement["requires_clarification"] = True
            placement["clarification_reason"] = action_name
            placement["status"] = "requires_clarification"
            placement.pop("fastener_spec", None)

        placement_geo = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        placement_support_topology = str(placement_geo.get("support_topology") or "").strip().lower()
        placement_contact_model = str(placement_geo.get("contact_model") or "").strip().lower()
        placement_mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
        if (
            placement.get("authoritative_contract") is True
            and placement_mechanism_name == "axial_face_bolted_mount"
            and placement_support_topology == "hub_radial_slot_mount"
            and placement_contact_model in {"slot_insert_with_bolted_retention", "through_bolt_clamp_in_radial_slot"}
            and placement.get("requires_clarification") is not True
        ):
            flags = _sanitize_placement_flags(placement.get("flags"))
            flags.pop("suppress_hole_generation", None)
            placement["flags"] = flags
            if str(placement.get("status") or "").strip().lower() == "requires_clarification":
                placement["status"] = "ok"
            if placement.get("clarification_reason") in {None, "", "authoritative_anchor_semantics_conflict_with_deterministic_solver"}:
                placement.pop("clarification_reason", None)
            placement["requires_clarification"] = False

        if not preserve_existing_intent:
            placement["placement_intent"] = placement_intent
        else:
            preserved_intent = placement.get("placement_intent") if isinstance(placement.get("placement_intent"), dict) else placement_intent
            if placement.get("requires_clarification") is True and placement.get("clarification_reason") == "generic_fastener_mount_requires_explicit_anchor_semantics":
                _force_single_pattern_layout(location, preserved_intent)
            placement["placement_intent"] = preserved_intent
        placement["location"] = location
        if isinstance(anchor_semantics, dict):
            placement["anchor_semantics"] = anchor_semantics


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


def _validate_no_world_coordinates(placements: list[dict]):
    """缂佸倷鐒﹂?location 閻庢稒顨嗛宀勫礄閾忕懓绠?world 闁秆勫姈閻栵綁鏁嶉崸?y/z 闁轰焦澹嗙划宥夊箣?x/y/z 閻庢稒顨嗛宀勬晬婢舵稓绀夐梺顐ｅ笒缂嶅﹤螞閳ь剟寮婚妷锕€顣查柡鍫濐槸閻壆鐥閳?
    
    濞撴艾顑呴ˇ濠氭晬濮濈浛ttern_parameters.spacing.x/y 闁哄嫷鍨伴崢鎴犳媼閸濄儲鐣遍柨娑樼墢濞村鈧潧缍婂Λ璺ㄦ崉濠垫挾绀夊☉鎾崇У濡插憡绋夐弽顐ｆ珪闁秆勫姈閻栵綁鏁?
    """
    def _check_recursive(obj, path: str, p_id: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                # 濞撴艾顑呴ˇ? spacing闁告劕鎳愬▓鎲?y闁哄嫷鍨冲ù澶屸偓闈涚秺濡法鎹勫┑鍡楁闁?
                if "spacing" in path and k in ("x", "y"):
                    continue
                # 婵☆偀鍋撻柡?x/y/z key 濞戞挻鏌ㄩ埀顒勬？鐠愮喖寮弶搴撳亾?
                if k in ("x", "y", "z") and isinstance(v, (int, float)):
                    raise ValueError(
                        f"Placement {p_id} location 缂佸倷鐒﹂娑㈠礄閾忕懓绠?world 闁秆勫姈閻栵絿鈧稒顨嗛?{k} (閻犱警鍨扮欢? {path}.{k}): {v}"
                    )
                _check_recursive(v, f"{path}.{k}", p_id)
        elif isinstance(obj, (list, tuple)):
            # 婵☆偀鍋撻柡灞诲劙缁椾線宕楅崘鈺傛闁稿﹤鍚嬮弳鐔虹磼?
            if len(obj) == 3 and all(isinstance(x, (int, float)) for x in obj):
                raise ValueError(
                    f"Placement {p_id} location 缂佸倷鐒﹂娑㈠礄閾忕懓绠?world 闁秆勫姈閻栵綁寮幍顔剧煁 (閻犱警鍨扮欢? {path}): {obj}"
                )
            for i, item in enumerate(obj):
                _check_recursive(item, f"{path}[{i}]", p_id)
    
    for p in placements:
        loc = p.get("location", {})
        if loc:
            _check_recursive(loc, "location", p.get("connection_id", "unknown"))


def _annotate_pcd_groups(placements: list[dict]) -> None:
    """Annotate circular hole patterns with deterministic pcd_group.

    Group rule: same base connection id + same host component id.
    """
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if not isinstance(pattern, dict):
            continue
        pattern_type = pattern.get("type") if isinstance(pattern.get("type"), str) else None
        if not isinstance(pattern_type, str) or pattern_type.lower() != "circular":
            continue

        conn_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else None
        base_conn = conn_id.split("@", 1)[0] if isinstance(conn_id, str) and conn_id else "unknown_connection"

        iface = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        host_id = iface.get("component_id") if isinstance(iface.get("component_id"), str) and iface.get("component_id") else "unknown_host"
        pcd_group = f"{base_conn}@{host_id}"

        pattern["pcd_group"] = pcd_group
        location["pattern_parameters"] = pattern
        placement["location"] = location


def _canon_type(t: str) -> str:
    """Normalize component type names to canonical forms"""
    if t in {"plate", "rigid_plate"}:
        return "carrier_plate"
    return t


def _is_subassembly_component(comp: Dict[str, Any]) -> bool:
    """Return True if component should be skipped for geometry modeling.
    
    Skips:
    - type="subassembly" (logical grouping only)
    - is_modeling_unit=false (semantic presence but no independent geometry)
    
    Design: These remain in KG for connection semantics, but don't require geometry planning.
    """
    # New hard contract (preferred): kind + modeling_policy
    kind = comp.get("kind")
    if isinstance(kind, str) and kind.strip() == "assembly_node":
        return True

    mp = comp.get("modeling_policy")
    if isinstance(mp, str) and mp.strip():
        policy = mp.strip().lower()
        if policy in {"container_only", "reference_only"}:
            return True
        if policy == "must_model":
            return False

    # Backward-compat fallback when modeling_policy is missing.
    must_model = comp.get("must_model")
    if must_model is False:
        return True

    # Legacy/backward-compat fallbacks
    return comp.get("type") == "subassembly" or comp.get("is_modeling_unit") is False


def _normalize_angles_to_360(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_normalize_angles_to_360(x) for x in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, (int, float)) and isinstance(k, str) and "angle" in k.lower():
                out[k] = float(v) % 360.0
            else:
                out[k] = _normalize_angles_to_360(v)
        return out
    return obj


def generate_geometry_semantics(
    kg: Dict[str, Any],
    *,
    placement_only_ids: set[str] | None = None,
    placement_enabled: bool = True
) -> Dict[str, Any]:
    """
    Generate Geometry Semantics Plan from Knowledge Graph.
    
    DECISION AUTHORITY MODEL:
    - Agent 1 freezes shape_semantics and dimensions
    - Agent 2 only expands frozen connection requirements into interfaces
    - Engineering constraints are enforced and fail-fast on conflicts
    
    AGENT 2 RESPONSIBILITY (This agent):
    - Validate frozen shape_semantics and dimensions
    - Expand required semantic roles into interface declarations
    - Interface semantic roles (mounting, rotation, support, etc.)
    - Interface geometry types (planar, axis, cylindrical, etc.)
    
    DEFERRED TO AGENT 3 (compile_semantics_to_cad):
    - TODO_AGENT3: Spatial positioning (world origin, relative placement, coordinates)
    - TODO_AGENT3: Construction methods (sketch闁愁偅濮€xtrude, revolve, pattern, etc.)
    - TODO_AGENT3: Growth directions (axial, radial, normal)
    - TODO_AGENT3: Dependency ordering (which part builds first)
    - TODO_AGENT3: CAD API selection (Fusion 360 vs other backends)
    
    DEFERRED TO AGENT 4 (plan_assembly):
    - TODO_AGENT4: Assembly sequence (which components assemble first)
    - TODO_AGENT4: Mate constraints (rigid, revolute, slider)
    - TODO_AGENT4: Spatial relationships (distance, angle, offset)
    - TODO_AGENT4: Collision detection and avoidance
    - TODO_AGENT4: Kinematic closure validation
    
    This agent outputs PURE SEMANTICS - no implementation details.
    """
    components_all = kg.get("components", [])
    components = [c for c in components_all if not _is_subassembly_component(c)]
    component_ids = {c.get("id") for c in components if isinstance(c, dict)}

    connection_semantic_repairs: Dict[str, Any] = {
        "agent": "Agent2_plan_geometry_semantic",
        "rewire_report": {"rewired_count": 0, "rewired": []},
    }

    _normalize_fastener_bundle_semantics(kg)
    _sanitize_fastener_bundles(kg)
    _sanitize_instancing_annotations(kg)
    kg, rewired_report = _rewire_container_connections(kg)
    connection_semantic_repairs["rewire_report"] = rewired_report
    _ensure_arm_interface_requirements(kg)
    _validate_wheel_arm_connection_topology(kg)

    # Ensure parent-level role closure before extracting roles and freezing echo
    _ensure_parent_role_closure(kg)

    frozen_echo = _build_frozen_echo(kg)

    # Parse connection_requirements to extract required semantic roles per component
    # Also get interface_intents for enriched interface generation
    required_roles, interface_intents = _extract_required_roles_from_connections(kg)
    
    # Append required roles to prompt for LLM context
    required_roles_text = ""
    if required_roles:
        required_roles_text = "\nREQUIRED SEMANTIC ROLES (from connection_requirements):\n"
        for comp_id, roles in sorted(required_roles.items()):
            if comp_id in component_ids:
                required_roles_text += f"  - {comp_id}: {', '.join(sorted(roles))}\n"
    
    llm_decisions: Dict[str, Dict[str, Any]] = {}
    llm_audit: Dict[str, Any] | None = None

    # Deterministic execution layer: always build semantics from engineering rules
    semantics, all_overrides = _generate_fallback_semantics(
        kg,
        required_roles,
        interface_intents,
        llm_decisions
    )

    # LLM placement inference for connection requirements (non-binding to frozen fields)
    if placement_enabled:
        placements = _infer_connection_placements_llm(kg, only_connection_ids=placement_only_ids)
        if placements:
            _validate_no_world_coordinates(placements)
            semantics["connection_placements"] = placements

    semantics.setdefault("metadata", {})["frozen_echo"] = frozen_echo
    semantics.setdefault("metadata", {})["connection_semantic_repairs"] = connection_semantic_repairs

    # Bind shape overrides to corresponding LLM decisions (for full audit trail)
    if llm_decisions:
        semantics.setdefault("metadata", {})["llm_decisions"] = {
            "components": list(llm_decisions.values()),
            "audit": llm_audit
        }

    # Record NON-BINDING interface intents (intent only, no constraints)
    interface_intent_index = {}
    for part in semantics.get("parts", []):
        comp_id = part.get("component_id")
        if not comp_id:
            continue
        for iface in part.get("interfaces", []) or []:
            interface_id = iface.get("interface_id")
            semantic_role = iface.get("semantic_role")
            if not interface_id or not semantic_role:
                continue
            intent = _collect_interface_intent_summary(
                comp_id, interface_id, semantic_role, interface_intents
            )
            if intent:
                interface_intent_index.setdefault(comp_id, {})[interface_id] = intent
    if interface_intent_index:
        semantics.setdefault("metadata", {})["interface_intents"] = interface_intent_index
        semantics["metadata"]["intent_binding"] = "non-binding"

    # Record subassemblies (for structural awareness, not for geometric modeling)
    # Subassemblies are declared at KG top-level, not as component nodes
    # We record their existence and member relationships for downstream agents
    # This is the ONLY place where assembly structure should be declared
    kg_subassemblies = kg.get("subassemblies", [])
    if kg_subassemblies:
        subassembly_records = []
        for sa in kg_subassemblies:
            subassembly_records.append({
                "subassembly_id": sa.get("id"),
                "type": "subassembly",
                "description": sa.get("description", f"Assembly group: {sa.get('id')}"),
                "component_ids": sa.get("component_ids", []),
                "role": sa.get("role"),
                "note": "Assembly-only node (not a geometric part). Members should be modeled individually."
            })
        semantics["subassemblies"] = subassembly_records

    _assert_frozen_unchanged(kg, semantics)

    return semantics


def _extract_required_roles_from_connections(kg: Dict[str, Any]) -> tuple[Dict[str, set], Dict[str, Dict[str, list]]]:
    """
    Extract required semantic roles and interface intents from connection_requirements in KG.
    
    Generates two outputs:
    1. required_roles: Maps component_id -> set of required semantic roles
    2. interface_intents: Maps component_id -> interface_id -> list of intent objects
    
    Interface intent object structure:
    {
        "purpose": "rotation",              # connection purpose from KG
        "semantic_role": "rotation",        # inferred semantic role
        "counterpart_ids": ["shaft_1"],     # other components in this connection
        "counterpart_types": ["shaft"]      # types of counterpart components
    }
    
    Role inference rules:
    - "rotation" purpose 闁?"rotation" role
    - "structural_fixation" purpose 闁?"mounting" role
    - "load_support" / "support_to_structure" purpose 闁?"support" role
    - "structural_clamping" purpose 闁?"mounting" role
    
    Args:
        kg: Knowledge graph containing connection_requirements
    
    Returns:
        Tuple of (required_roles dict, interface_intents dict)
    """
    required_roles = {}  # component_id -> set of roles
    interface_intents = {}  # component_id -> interface_id -> list of intent objects
    
    # Build component type lookup
    comp_types = {c["id"]: c.get("type", "component") for c in kg.get("components", [])}
    
    # Purpose to semantic roles mapping (now supports multiple roles)
    purpose_to_roles = {
        "rotation": {"rotation"},
        "torque_transfer": {"rotation", "torque_transfer"},
        "structural_fixation": {"mounting", "fixation"},
        "load_support": {"support"},
        "support_to_structure": {"support"},
        "rotation_support": {"support", "rotation"},  # Bearings: combines support + rotation
        "structural_clamping": {"mounting"},
        "fastening_mechanism": {"mounting", "fixation"},
        "role_closure_rotation": {"rotation"},
        "role_closure_mounting": {"mounting"},
        "role_closure_support": {"support"},
    }
    
    # Parse connection requirements
    for conn_req in kg.get("connection_requirements", []):
        if not isinstance(conn_req, dict):
            continue
        
        purpose = conn_req.get("purpose", "")
        roles_raw = conn_req.get("roles")
        if isinstance(roles_raw, list):
            semantic_roles = {r.strip().lower() for r in roles_raw if isinstance(r, str) and r.strip()}
            if not semantic_roles:
                semantic_roles = purpose_to_roles.get(purpose, {"mounting"})
        else:
            semantic_roles = purpose_to_roles.get(purpose, {"mounting"})
        
        # Extract components and interfaces involved in this connection
        between = conn_req.get("between", {})
        
        # Handle two formats:
        # 1. Dict: {component_id_1: interface_id_1, component_id_2: interface_id_2, ...}
        # 2. List: [component_id_1, component_id_2, ...] - use __auto__ for interface_id
        if isinstance(between, dict):
            # between has structure: {component_id_1: interface_id_1, component_id_2: interface_id_2, ...}
            # Filter out subassembly IDs
            items = [(cid, iface_id) for cid, iface_id in between.items() if cid and "_sa" not in cid]
            comp_ids = [cid for cid, _ in items]
            # For each component in the connection, record its interface intent
            for i, (comp_id, interface_id) in enumerate(items):
                # Find counterpart components (other components in this connection)
                counterpart_ids = [cid for j, cid in enumerate(comp_ids) if j != i]
                counterpart_types = sorted(set(
                    comp_types.get(cid, "component") 
                    for cid in counterpart_ids
                ))
                counterpart_types = [t for t in counterpart_types if t != "component"]
                for semantic_role in semantic_roles:
                    # Create interface intent object
                    intent = {
                        "purpose": purpose,
                        "semantic_role": semantic_role,
                        "counterpart_ids": counterpart_ids,
                        "counterpart_types": counterpart_types
                    }
                    # Record the intent per interface
                    interface_intents.setdefault(comp_id, {}).setdefault(interface_id, []).append(intent)
                    # Also record the required role for this component
                    required_roles.setdefault(comp_id, set()).add(semantic_role)
        elif isinstance(between, list):
            # between is a list of component_ids: use __auto__ as interface_id
            comp_ids = between
            for comp_id in comp_ids:
                # Find counterpart components (other components in this connection)
                counterpart_ids = [cid for cid in comp_ids if cid != comp_id]
                counterpart_types = sorted(set(
                    comp_types.get(cid, "component") 
                    for cid in counterpart_ids
                ))
                counterpart_types = [t for t in counterpart_types if t != "component"]
                for semantic_role in semantic_roles:
                    # Create interface intent object
                    intent = {
                        "purpose": purpose,
                        "semantic_role": semantic_role,
                        "counterpart_ids": counterpart_ids,
                        "counterpart_types": counterpart_types
                    }
                    # Record the intent per __auto__ interface
                    interface_intents.setdefault(comp_id, {}).setdefault("__auto__", []).append(intent)
                    # Also record the required role for this component
                    required_roles.setdefault(comp_id, set()).add(semantic_role)
    
    return required_roles, interface_intents


def _extract_patterns_from_components(
    components: List[Dict[str, Any]],
    pattern_intents_by_comp: Dict[str, str] | None = None
) -> List[Dict[str, Any]]:
    """
    Extract geometric patterns from component definitions.
    
    Detects rotational symmetry by analyzing component IDs and types.
    
    PATTERN DETECTION RULES:
    1. Identify components with the same type
    2. Check if their IDs follow a numbered pattern (e.g., "wheel_arm_1", "wheel_arm_2", "wheel_arm_3")
    3. If pattern found, declare rotational_symmetry with count and component_ids
    
    AGENT 2 RESPONSIBILITY (this function):
    - Declare patterns that exist based on ID analysis
    
    AGENT 3 RESPONSIBILITY:
    - Decide whether to use circular_pattern, linear_pattern, or other construction methods
    - This function only makes semantic declarations, not implementation decisions
    
    Args:
        components: List of component definitions from KG
    
    Returns:
        List of pattern objects with structure:
        {
            "type": "rotational_symmetry",
            "count": 3,
            "component_ids": ["wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
            "base_name": "wheel_arm"  (common prefix)
        }
    """
    import re
    
    patterns = []
    
    # Group components by type
    by_type = {}
    for comp in components:
        comp_type = comp.get("type", "component")
        comp_id = comp.get("id")
        if comp_id:
            by_type.setdefault(comp_type, []).append(comp_id)
    
    # For each type, check if components follow a numbered pattern
    for comp_type, comp_ids in by_type.items():
        if len(comp_ids) < 2:
            continue  # Need at least 2 components for a pattern
        
        # Try to extract base name and numbers
        # Pattern: "base_name_N" where N is a digit
        pattern_dict = {}  # base_name -> list of (number, full_id)
        
        for comp_id in comp_ids:
            # Try to match pattern: anything ending with _digit(s)
            m = re.match(r'^(.+?)_(\d+)$', comp_id)
            if m:
                base_name = m.group(1)
                number = int(m.group(2))
                pattern_dict.setdefault(base_name, []).append((number, comp_id))
        
        # For each potential pattern, check if it's valid
        for base_name, numbered_list in pattern_dict.items():
            # Check if this is a valid pattern (sequential or at least multiple)
            if len(numbered_list) >= 2:
                # Sort by number
                numbered_list.sort(key=lambda x: x[0])
                numbers = [n for n, _ in numbered_list]
                comp_ids_sorted = [cid for _, cid in numbered_list]
                
                # Check if numbers form a sequence (consecutive or regular spacing)
                # For now, just require at least 2 components with same base name
                
                # Determine pattern type based on LLM intents
                pattern_type = "rotational_symmetry"  # Default
                if pattern_intents_by_comp:
                    llm_intents_for_pattern = {}
                    for comp_id in comp_ids_sorted:
                        if comp_id in pattern_intents_by_comp:
                            intent = pattern_intents_by_comp[comp_id]
                            llm_intents_for_pattern[comp_id] = intent
                    
                    if llm_intents_for_pattern:
                        # Use majority vote for pattern type
                        intent_counts = {}
                        for intent in llm_intents_for_pattern.values():
                            intent_counts[intent] = intent_counts.get(intent, 0) + 1
                        
                        # Find most common intent
                        if intent_counts:
                            majority_intent = max(intent_counts.items(), key=lambda x: x[1])[0]
                            if majority_intent in ["linear_symmetry", "mirror_symmetry", "rotational_symmetry"]:
                                pattern_type = majority_intent
                
                pattern = {
                    "type": pattern_type,
                    "count": len(comp_ids_sorted),
                    "component_ids": comp_ids_sorted,
                    "base_name": base_name,
                    "component_type": comp_type,
                    "detection_method": "id_analysis"  # Deterministic detection
                }
                
                # Record LLM's pattern_intent for comparison
                if pattern_intents_by_comp:
                    llm_intents = {}
                    for comp_id in comp_ids_sorted:
                        if comp_id in pattern_intents_by_comp:
                            intent = pattern_intents_by_comp[comp_id]
                            llm_intents[comp_id] = intent
                    
                    if llm_intents:
                        pattern["llm_pattern_intents"] = llm_intents
                        # Check if LLM agrees with deterministic detection
                        intents_set = set(llm_intents.values())
                        if pattern_type in intents_set:
                            pattern["llm_agreement"] = "agrees"
                        elif intents_set == {"none"}:
                            pattern["llm_agreement"] = "disagrees"
                        else:
                            pattern["llm_agreement"] = "partial"
                
                patterns.append(pattern)
    
    return patterns


def _infer_interfaces_from_component(
    comp: Dict[str, Any],
    required_roles: set | None = None,
    interface_intents: Dict[str, Dict[str, list]] | None = None,
    llm_decision: Dict[str, Any] | None = None
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Infer semantic interfaces from component definition.
    
    Returns:
        Tuple of (interfaces, overrides)
        - interfaces: List of interface definitions
        - overrides: List of override records (supplements, auto-fixes)
    
    Override record structure:
    {
        "component_id": str,
        "override_type": "interface_supplement" | "interface_auto_fix",
        "added_interfaces": [interface_id, ...],
        "reason": str
    }
    
    AUTHORITY MODEL FOR INTERFACES:
    - Connection scheme is frozen by Agent 1
    - Agent 2 only expands required roles into interfaces
    - Engineering constraints are MANDATORY and fail-fast when violated
    
    TWO-STEP PROCESS:
    
    Step 1: Expand required roles
    - Use explicit interfaces from KG if present
    - Add any missing roles from connection_requirements
    
    Step 2: Enforce engineering constraints (fail-fast)
    - Arm must have >= 2 interfaces
    - Wheel must have mounting + rotation
    - Bearing must have support + rotation
    - If missing, raise error instead of auto-adding
    
    Returns pure semantic declarations - no spatial data, no implementation details.
    
    OUTPUT (Agent 2 responsibility):
    - interface_id: unique identifier
    - description: human-readable purpose
    - semantic_role: mounting, rotation, support, etc.
    - geometry_type: planar, axis, cylindrical, etc.
    - NOTE: Intent signals are stored in metadata.interface_intents (non-binding)
    
    EXCLUDED (deferred to Agent 3):
    - reference_frame: coordinate system (origin, x/y/z axes)
    - constraint_type: rigid, pivot, slider
    - geometry_source: face IDs, edge IDs, vertex IDs
    
    Agent 3 will convert these semantic declarations into concrete geometric entities.
    
    Args:
        comp: Component definition from KG
        required_roles: Set of required semantic roles from connection_requirements
        interface_intents: Dict mapping component_id -> interface_id -> list of intent objects
        llm_decision: Unused placeholder (LLM decisions are disabled for interfaces)
    """
    if required_roles is None:
        required_roles = set()
    if interface_intents is None:
        interface_intents = {}
    
    interfaces = []
    overrides = []  # Collect all override records
    comp_type = _canon_type(comp.get("type", "component"))
    comp_id = comp.get("id")
    
    # Helper function to create interface (pure semantics only)
    def _make_interface(interface_id: str, description: str, semantic_role: str, geometry_type: str) -> Dict[str, Any]:
        geo = _infer_geometry_type_from_interface_id(interface_id, semantic_role)
        # Preserve explicit geometry_type only when it's non-empty and compatible.
        if isinstance(geometry_type, str) and geometry_type:
            geo = geometry_type
        return {
            "interface_id": interface_id,
            "description": description,
            "semantic_role": semantic_role,
            "geometry_type": geo,
            "geom_type": geo,
        }
    
    # First, check if explicit interfaces exist in KG
    explicit_interfaces = comp.get("interfaces", [])
    if explicit_interfaces:
        for iface in explicit_interfaces:
            interface_id = iface.get("interface_id")
            inferred_role = _infer_interface_role(comp_type, interface_id)
            interfaces.append(_make_interface(
                interface_id,
                iface.get("description", f"Interface: {interface_id}"),
                inferred_role,
                _infer_geometry_type_from_interface_id(interface_id, inferred_role)
            ))
        # Don't return early - still need to validate with required_roles and constraints
        # Fall through to Step 2 and Step 3
    
    # Step 1: Augment with required roles from connection_requirements
    existing_roles = {iface["semantic_role"] for iface in interfaces}
    missing_roles = required_roles - existing_roles

    if missing_roles:
        added_interface_ids = []
        reasons_per_role = {}  # Track reason for each role

        for role in sorted(missing_roles):
            geo_type = _infer_geometry_type_from_role(role)
            interface_id = f"{role}_req"
            interfaces.append(_make_interface(
                interface_id,
                f"Required {role} interface (from connection_requirements)",
                role,
                geo_type
            ))
            added_interface_ids.append(interface_id)

            # Collect which connections require this role
            role_sources = []
            if comp_id and interface_intents:
                intents_map = interface_intents.get(comp_id, {})
                for iface_id, intent_list in intents_map.items():
                    for intent in intent_list:
                        if intent.get("semantic_role") == role:
                            role_sources.append(f"{intent.get('purpose')}")
            reasons_per_role[role] = ", ".join(set(role_sources)) if role_sources else "unknown connection"

        # Record supplement from frozen connection requirements
        overrides.append({
            "component_id": comp_id,
            "override_type": "interface_supplement",
            "added_interfaces": added_interface_ids,
            "reason": f"Added required roles from connection_requirements: {', '.join(sorted(missing_roles))}",
            "role_sources": reasons_per_role
        })

    # Step 2: Enforce engineering constraints (fail-fast)
    # Step 1.5: Add standard geometric interfaces for stable anchoring/assembly.
    # These are pure semantic declarations (no CAD ids) and help downstream
    # RESOLVE_INTERFACE for holes and joints.
    shape_semantics = comp.get("shape_semantics")
    shape_type: Optional[str] = None
    if isinstance(shape_semantics, dict):
        shape_type_val = shape_semantics.get("type")
        if isinstance(shape_type_val, str):
            shape_type = shape_type_val

    existing_iface_ids = {iface.get("interface_id") for iface in interfaces if isinstance(iface, dict)}
    added_std: List[str] = []

    def _add_std(interface_id: str, description: str, semantic_role: str, geometry_type: str) -> None:
        if interface_id in existing_iface_ids:
            return
        interfaces.append(_make_interface(interface_id, description, semantic_role, geometry_type))
        existing_iface_ids.add(interface_id)
        added_std.append(interface_id)

    # Global standard interfaces: always provide a stable pair of end faces.
    # These are the most commonly referenced anchors by downstream planners.
    _add_std("axial_end_face", "Axial end face (default)", "mounting", "planar")
    _add_std("axial_end_face_max", "Axial end face (max)", "mounting", "planar")
    _add_std("axial_end_face_min", "Axial end face (min)", "mounting", "planar")

    if shape_type in {"cylindrical", "annular"}:
        _add_std("radial_outer_face", "Outer cylindrical face", "mounting", "cylindrical")
        _add_std("radial_inner_face", "Inner cylindrical face", "mounting", "cylindrical")
        _add_std("shaft_axis", "Primary axis of rotation", "rotation", "axis")

    if shape_type in {"prismatic", "box", "plate", "radial_plate"}:
        _add_std("side_face_x_max", "Side face (max X)", "mounting", "planar")
        _add_std("side_face_x_min", "Side face (min X)", "mounting", "planar")
        _add_std("side_face_y_max", "Side face (max Y)", "mounting", "planar")
        _add_std("side_face_y_min", "Side face (min Y)", "mounting", "planar")

    if comp_type == "arm":
        _add_std("proximal_insert_face", "Proximal insert face for hub-slot mounting", "mounting", "planar")
        _add_std("distal_mount_face", "Distal support pad face", "mounting", "planar")
        _add_std("distal_bore_axis", "Distal bore axis for wheel axle support", "rotation", "axis")

    if added_std:
        overrides.append(
            {
                "component_id": comp_id,
                "override_type": "interface_auto_fix",
                "added_interfaces": added_std,
                "reason": "Added standard geometric interfaces (global set)",
            }
        )

    final_roles = {iface["semantic_role"] for iface in interfaces}

    # Validate component-specific constraints only when relevant
    if comp_type == "arm" and len(interfaces) < 2:
        raise ValueError(
            f"Component '{comp_id}' type=arm requires >= 2 interfaces."
        )

    # wheel: only validate if connection_requirements specify mounting+rotation
    if comp_type == "wheel" and required_roles and not {"mounting", "rotation"}.issubset(final_roles):
        # Only raise error if these roles were actually required but not fulfilled
        missing = {"mounting", "rotation"} - final_roles
        if missing & required_roles:  # At least one missing role was required
            raise ValueError(
                f"Component '{comp_id}' type=wheel requires mounting + rotation roles. "
                f"Missing: {missing & required_roles}, found: {final_roles}"
            )

    # bearing: DO NOT enforce hardcoded role requirements
    # Different bearings serve different functions (rotating, fixed, load-bearing only, etc.)
    # Trust connection_requirements to specify the actual needed roles
    
    # General validation: if required_roles specified but not met, that's an error
    if required_roles and not required_roles.issubset(final_roles):
        raise ValueError(
            f"Component '{comp_id}' missing required roles from connections: "
            f"required={required_roles}, found={final_roles}, missing={required_roles - final_roles}"
        )

    if not interfaces and comp_type not in {"module", "subassembly"}:
        raise ValueError(
            f"Component '{comp_id}' has no interfaces after applying connection_requirements."
        )
    
    return (interfaces, overrides)


def _collect_interface_intent_summary(
    comp_id: str,
    interface_id: str,
    semantic_role: str,
    interface_intents: Dict[str, Dict[str, list]] | None
) -> Dict[str, Any] | None:
    """Collect NON-BINDING intent signals for an interface."""
    if not comp_id or not interface_id or not semantic_role or not interface_intents:
        return None

    intents_map = interface_intents.get(comp_id, {})
    direct = intents_map.get(interface_id, [])
    auto = intents_map.get("__auto__", [])
    auto_filtered = [it for it in auto if it.get("semantic_role") == semantic_role]
    intents = direct + auto_filtered

    if not intents:
        return None

    purposes = []
    seen = set()
    for it in intents:
        p = it.get("purpose")
        if p and p not in seen:
            seen.add(p)
            purposes.append(p)

    counterpart_types = sorted(set(
        t for it in intents for t in it.get("counterpart_types", [])
    ))

    return {
        "purposes": purposes,
        "counterpart_types": counterpart_types,
        "binding": False
    }


def _infer_interface_role(comp_type: str | None, interface_id: str) -> str:
    """Infer semantic role from component type and interface name"""
    if "rotate" in interface_id.lower() or "axis" in interface_id.lower():
        return "rotation"
    elif "mount" in interface_id.lower():
        return "mounting"
    elif "support" in interface_id.lower():
        return "support"
    elif "fix" in interface_id.lower() or "clamp" in interface_id.lower() or "fastener" in interface_id.lower():
        return "fixation"
    else:
        return "mounting"


def _infer_geometry_type_from_role(semantic_role: str) -> str:
    """
    Infer geometry type from semantic role.
    
    Maps canonical semantic roles to geometry types:
    - rotation: axis (rotational interface)
    - mounting: planar (surface-based connection)
    - support: planar (load-bearing surface)
    - fixation: planar (permanent attachment surface)
    """
    role_to_geometry = {
        "rotation": "axis",
        "torque_transfer": "axis",
        "mounting": "planar",
        "support": "planar",
        "fixation": "planar",
        "spacing": "planar",
        "datum": "planar",
    }
    return role_to_geometry.get(semantic_role, "complex")


def _generate_fallback_semantics(
    kg: Dict[str, Any],
    required_roles: Dict[str, set] | None = None,
    interface_intents: Dict[str, Dict[str, list]] | None = None,
    llm_decisions: Dict[str, Dict[str, Any]] | None = None
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Generate deterministic geometry semantics (LLM decisions optional).
    
    CRITICAL: This generator ONLY produces semantic declarations.
    NO construction rules, NO spatial relationships - those are Agent 3's job.
    
    Returns:
        Tuple of (semantics dict, all_overrides list)
    
    Args:
        kg: Knowledge graph
        required_roles: Dict mapping component_id to set of required semantic roles
        interface_intents: Dict mapping component_id -> interface_id -> list of intent objects
        llm_decisions: Optional abstract decisions per component from LLM layer
    """
    if required_roles is None:
        required_roles = {}
    if interface_intents is None:
        interface_intents = {}
    if llm_decisions is None:
        llm_decisions = {}
    
    components_all = kg.get("components", [])
    components = [c for c in components_all if not _is_subassembly_component(c)]
    parts = []
    all_overrides = []  # Collect all override records
    
    # Generate parts (pure semantic declarations)
    # TODO_AGENT3: Spatial positioning will be added by compile_semantics_to_cad
    # TODO_AGENT4: Assembly constraints will be added by plan_assembly
    
    # Build pattern_intent lookup from LLM decisions
    pattern_intents_by_comp = {}
    for comp_id, decision in llm_decisions.items():
        if decision.get("pattern_intent"):
            pattern_intents_by_comp[comp_id] = decision.get("pattern_intent")
    
    for comp in components:
        comp_id = comp["id"]

        dims = _get_component_dimensions(comp)
        shape_semantics = _get_component_shape_semantics(comp, dims)

        # Infer geometric features (if any)
        features = _infer_features_from_component(comp)

        # MANDATORY: Infer interfaces from component WITH required roles and interface intents
        comp_required_roles = required_roles.get(comp_id, set())
        interfaces, interface_overrides = _infer_interfaces_from_component(
            comp,
            comp_required_roles,
            interface_intents,
            None
        )
        if interface_overrides:
            all_overrides.extend(interface_overrides)
        
        part = {
            "component_id": comp_id,
            "shape_semantics": shape_semantics,
            "dimensions": dims,
            "interfaces": interfaces
            # INTENTIONALLY EXCLUDED (deferred to Agent 3):
            # - "anchor": spatial positioning strategy
            # - "construction_rule": how to build the geometry
            # - "depends_on": build order dependencies
            # - "reference_frame": coordinate system definitions
        }
        
        # Add features if present
        if features:
            part["features"] = features
        
        # Add pattern_intent if LLM provided one
        if comp_id in pattern_intents_by_comp:
            part["pattern_intent"] = pattern_intents_by_comp[comp_id]
        
        parts.append(part)
    
    # Determine execution mode based on LLM usage and overrides
    if not llm_decisions:
        execution_mode = "type_based"  # Purely deterministic, no LLM
    elif all_overrides:
        execution_mode = "hybrid"  # LLM + engineering constitution enforcement
    else:
        execution_mode = "llm_guided"  # LLM decisions fully accepted
    
    metadata: Dict[str, Any] = {
        "plan_id": f"geometry_semantics_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "schema_version": "2.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "execution_mode": execution_mode  # type_based | llm_guided | hybrid
    }
    
    # Add overrides to metadata if any occurred
    if all_overrides:
        metadata["overrides"] = {
            "count": len(all_overrides),
            "records": all_overrides
        }
    
    return {
        "metadata": metadata,
        "parts": parts,
        "patterns": _extract_patterns_from_components(
            kg.get("components", []),
            pattern_intents_by_comp
        )
    }, all_overrides


def _infer_features_from_component(comp: Dict[str, Any]) -> List[Dict[str, str]] | None:
    """
    Infer geometric features (bore, fillet, chamfer, etc.) from component type and parameters.
    
    Features are optional. Only return if component type typically has features.
    
    AGENT 2 DECLARES: feature_type and parameter names ONLY
    AGENT 3 HANDLES: construction method (sketch, extrude, chamfer operation, etc.)
    """
    comp_type = comp.get("type", "component")
    dims = _get_component_dimensions(comp)
    features = []
    
    # Hubs and wheels often have bore/hole
    if comp_type in ["hub", "wheel"]:
        hole_key = next((k for k in dims if any(h in k.lower() for h in ["hole", "bore", "shaft_hole"])), None)
        if hole_key:
            features.append({
                "feature_type": "bore",
                "diameter_param": hole_key
            })
    
    # Arms might have fillets at corners
    if comp_type == "arm":
        fillet_key = next((k for k in dims if "fillet" in k.lower()), None)
        if fillet_key:
            features.append({
                "feature_type": "fillet",
                "radius_param": fillet_key
            })
    
    # Carrier plates might have corner fillets
    if comp_type == "carrier_plate":
        fillet_key = next((k for k in dims if "fillet" in k.lower() or "corner" in k.lower()), None)
        if fillet_key:
            features.append({
                "feature_type": "fillet",
                "radius_param": fillet_key
            })
    
    # Return None if no features found (optional field)
    return features if features else None


def _generate_geometry_assembly_contract(
    semantics: Dict[str, Any],
    kg: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate formal contract between geometry planning and assembly planning.
    
    This contract is MANDATORY for assembly planning. Assembly planning agent
    MUST NOT reference any components, interfaces, or attachment types not
    explicitly listed in this contract.
    
    CONTRACT CONTENTS (Agent 2 provides):
    - components: list of component IDs and types
    - interfaces: semantic roles and geometry types
    - allowable_attachment_types: rigid, revolute, slider, etc.
    
    CONTRACT OMISSIONS (Agent 3 will add):
    - TODO_AGENT3: Actual geometric entities (faces, edges, axes)
    - TODO_AGENT3: Coordinate frames for each interface
    - TODO_AGENT3: CAD body references
    
    CONTRACT USAGE (Agent 4 consumes):
    - TODO_AGENT4: Use semantic_role + geometry_type to select mate types
    - TODO_AGENT4: Use allowed_mate_roles to validate connections
    - TODO_AGENT4: Use allowable_attachment_types for assembly strategy
    
    Args:
        semantics: Geometry semantics plan with interface declarations
        kg: Knowledge graph with design intent
    
    Returns:
        Geometry-Assembly contract conforming to geometry_assembly_contract_schema.json
    """
    parts = semantics.get("parts", [])
    kg_components = {c["id"]: c for c in kg.get("components", [])}
    
    # Extract component contracts from semantics
    components = []
    for part in parts:
        part_id = part["component_id"]
        kg_comp = kg_components.get(part_id, {})
        comp_type = kg_comp.get("type", "component")
        
        # Get declared interfaces from part
        interfaces = part.get("interfaces", [])
        if not interfaces:
            raise ValueError(
                f"Component '{part_id}' has no interfaces declared. "
                "Geometry planning MUST declare at least one interface per component."
            )
        
        # Convert interfaces to contract format
        # NOTE: This contract contains SEMANTIC information only
        # Agent 3 will enrich this with actual geometric references
        contract_interfaces = []
        for iface in interfaces:
            semantic_role = iface.get("semantic_role", "connection")
            allowed_mate_roles = _infer_allowed_mate_roles(semantic_role)
            
            contract_iface = {
                "interface_id": iface["interface_id"],
                "description": iface.get("description", f"Interface: {iface['interface_id']}"),
                "semantic_role": semantic_role,
                "allowed_mate_roles": allowed_mate_roles,
                "geometry_type": iface.get("geometry_type", "complex")
                # INTENTIONALLY EXCLUDED (Agent 3 will add):
                # - "cad_entity_reference": actual face/edge/vertex from CAD model
                # - "reference_frame": concrete coordinate system with origin and axes
                #
                # INTENTIONALLY EXCLUDED (Intent signals, not binding constraints):
                # - "intended_connections": stored in metadata.interface_intents
                # - "counterpart_types": stored in metadata.interface_intents
                # These are semantic hints for Agent 4, not rigid constraints for Agent 3
            }
            
            contract_interfaces.append(contract_iface)
        
        components.append({
            "component_id": part_id,
            "component_type": comp_type,
            "description": kg_comp.get("description", f"Component: {part_id}"),
            "interfaces": contract_interfaces
        })
    
    # Determine allowable attachment types based on interfaces
    allowable_attachment_types = _infer_allowable_attachment_types(components)
    
    # Extract design intent from KG
    design_intent = kg.get("design_intent", {}).get("description", "")
    
    contract = {
        "contract_version": "1.0.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_plan_id": semantics.get("metadata", {}).get("plan_id", "unknown"),
        "components": components,
        "allowable_attachment_types": allowable_attachment_types,
        "prohibited_degrees_of_freedom": {
            "no_translation_x": False,
            "no_translation_y": False,
            "no_translation_z": False,
            "no_rotation_x": False,
            "no_rotation_y": False,
            "no_rotation_z": False,
            "custom_constraints": []
        },
        "assembly_rules": {
            "require_ground_component": True,
            "allow_self_collision": False,
            "require_kinematic_closure": True
        },
        "metadata": {
            "geometry_agent_version": "2.0.0",
            "knowledge_graph_id": kg.get("metadata", {}).get("kg_id", "unknown"),
            "design_intent": design_intent
        }
    }
    
    # Validate contract against schema
    schema_path = Path("planning") / "geometry_assembly_contract_schema.json"
    if schema_path.exists():
        try:
            schema = _read_json(schema_path)
            validator = Draft202012Validator(schema)
            errors = list(validator.iter_errors(contract))
            if errors:
                print(f"WARNING: Contract validation failed with {len(errors)} errors:")
                for err in errors[:5]:
                    print(f"  - {err.message} at {'/'.join(str(p) for p in err.path)}")
        except Exception as e:
            print(f"WARNING: Could not validate contract: {e}")
    
    return contract


def _infer_allowed_mate_roles(semantic_role: str) -> List[str]:
    """
    Infer which semantic roles are allowed to mate with this interface.
    
    CANONICAL SEMANTIC ROLES (Agent 2 only uses these):
    - mounting: surface-based connections (mounting plates, flanges)
    - rotation: rotational connections (axes, shafts)
    - support: load-bearing connections (supports, bases)
    - fixation: permanent connections (fastening, welding, clamping)
    
    Empty list means no restrictions.
    """
    # Define compatibility matrix for the four canonical roles
    compatibility = {
        "mounting": ["mounting", "support", "fixation"],
        "rotation": ["rotation"],
        "support": ["mounting", "support"],
        "fixation": ["fixation", "mounting"]
    }
    
    return compatibility.get(semantic_role, [])


def _infer_allowable_attachment_types(components: List[Dict[str, Any]]) -> List[str]:
    """
    Infer allowable joint/attachment types from component interfaces.
    
    Returns sorted list of allowed attachment types based on semantic roles.
    """
    attachment_types = set()
    
    # Scan all interfaces to determine what types of joints are possible
    for comp in components:
        for iface in comp.get("interfaces", []):
            role = iface.get("semantic_role", "")
            
            if role in ["mounting", "support", "connection", "fastening"]:
                attachment_types.add("rigid")
            
            if role in ["rotation", "bearing", "motion_transfer"]:
                attachment_types.add("revolute")
            
            if role in ["sliding", "guide"]:
                attachment_types.add("slider")
            
            if role == "rotation" and "cylindrical" in iface.get("geometry_type", ""):
                attachment_types.add("cylindrical")
    
    # Always include rigid as fallback
    attachment_types.add("rigid")
    
    # Sort for deterministic output
    return sorted(list(attachment_types))



def run(*, run_dir: Path, round_index: int) -> Dict[str, Any]:
    """
    Generate Geometry Semantics Plan from Knowledge Graph.
    
    AGENT 2 OUTPUT (this agent):
    - geometry_semantics_modeling_round_{N}.json: Modeling-only semantics for Agent3a
    - geometry_semantics_assembly_round_{N}.json: Assembly semantics contract for Agent4
    
    DOWNSTREAM CONSUMPTION:
    - Agent 3a (shape_realization_planner) reads modeling semantics
    - Agent 4 (plan_assembly) reads assembly semantics contract
    
    DESIGN PHILOSOPHY:
    This agent is CAD-backend agnostic. It describes WHAT to build, not HOW.
    Construction strategies are deferred to Agent 3, which knows CAD specifics.
    """
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    
    if not kg_path.exists():
        raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
    
    kg = _read_json(kg_path)
    
    # 闁衡偓椤栨稑鐦悹?rerun 濠㈣泛绉堕弫?connection_placements
    modeling_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    force_reinfer = os.environ.get("FORCE_REINFER_PLACEMENT", "0") == "1"
    existing_semantics = None
    if modeling_path.exists() and not force_reinfer:
        existing_semantics = _load_existing_geometry_semantics(str(modeling_path))

    # 閻犱緤绱曢悾鑽ょ磽閸濆嫨浜奸柣?connection_id
    missing_ids = _missing_placement_connection_ids(kg, existing_semantics)
    placement_enabled = True
    placement_only_ids: set[str] | None = None
    if force_reinfer:
        # 闊洨鏅弳鎰啅閸欏绠?placements闁挎稑鑻崣蹇涙焾閵娿儮鍋撳▎鎾亾婢舵劕娅㈤柟?
        placement_only_ids = set(_missing_placement_connection_ids(kg, None))
    else:
        if not missing_ids:
            placement_enabled = False
        else:
            placement_only_ids = set(missing_ids)

    # 闁汇垻鍠愰崹姘跺棘閹殿喗鐣遍悹鍥跺幒缁?
    semantics = generate_geometry_semantics(
        kg,
        placement_only_ids=placement_only_ids,
        placement_enabled=placement_enabled
    )
    semantics = _normalize_angles_to_360(semantics)

    # 濠㈣泛绉堕弫銈夊籍瑜忓▓?connection_placements闁挎稑鐗婂Λ顐︽儍閸曨亞鍠橀柛蹇撶墳缁?
    if existing_semantics and "connection_placements" in existing_semantics and not force_reinfer:
        old_placements = existing_semantics["connection_placements"]
        new_placements = semantics.get("connection_placements", [])
        existing_ids = {_normalize_placement_connection_id(p) for p in old_placements}
        merged = list(old_placements)
        merged.extend([p for p in new_placements if _normalize_placement_connection_id(p) not in existing_ids])
        semantics["connection_placements"] = merged

    # 濞存粌鏈鑲╂偘閵夛箑鑵归柣鐐叉４缁辩増绂掗崨顓у殸缂傚倸鎼妵?id闁挎稑鑻崯鈧悹瀣暟閺併倖绋夐埀顒€鈻?LLM闁挎稑鐗呯粭澶屾啺閸℃瑦纾扮€圭寮跺﹢渚€鏁?
    second_pass = os.environ.get("PLACEMENT_SECOND_PASS_LLM", "0") == "1"
    if second_pass and not force_reinfer:
        current = semantics.get("connection_placements", [])
        missing_ids = _missing_placement_connection_ids(kg, {"connection_placements": current})
        if missing_ids:
            second_new = _infer_connection_placements_llm(kg, only_connection_ids=set(missing_ids))
            if second_new:
                existing_ids = {_normalize_placement_connection_id(p) for p in current}
                current.extend([p for p in second_new if _normalize_placement_connection_id(p) not in existing_ids])
                semantics["connection_placements"] = current

    # 閻炴稏鍎电紞鍫㈢磽閸濆嫨浜奸柣?placement闁挎稑鐗嗗畷鐗堟媴瀹ュ浂鍎婇柨?
    placements = semantics.get("connection_placements", [])
    placements = _ensure_placement_completeness(
        kg,
        placements,
        candidate_purposes=PLACEMENT_PURPOSES
    )
    placements = _normalize_placement_schema(placements)
    if placements:
        _apply_deterministic_placement_intents(kg, placements)
        _apply_deterministic_derived_changes(kg, placements)
        _enforce_authoritative_contract_execution_mapping(kg, placements)
        _specialize_opposed_bearing_seat_placements(kg, placements)
        _ensure_holes_for_fasteners(kg, placements)  # 閻炴稏鍎遍崣蹇曠磽閸濆嫨浜奸柣銊ュ閻＄喓鈧鐭粻?
        placements = _split_connection_placements_per_target(semantics=semantics, placements=placements)
        placements = _dedupe_duplicate_authoritative_placements(placements)
        _validate_per_target_placement_consistency(placements)
        mechanism_rewrite_audit = _rewrite_connection_feature_mechanisms(kg, placements)
        if mechanism_rewrite_audit:
            semantics.setdefault("metadata", {})["agent2_connection_mechanism_audit"] = mechanism_rewrite_audit
        _rewrite_axial_retention_on_shaft(kg, placements)
        thread_geometry_audit = _sanitize_thread_features_against_host_geometry(kg, placements)
        if thread_geometry_audit:
            semantics.setdefault("metadata", {})["agent2_thread_geometry_audit"] = thread_geometry_audit
        _ensure_circular_hole_host_is_valid(kg, placements)
        _seed_missing_pattern_parameters(kg, placements)
        _ensure_pattern_parameters_complete(kg, placements)
        _enforce_solved_pattern_parameters(kg, placements)
        _annotate_pcd_groups(placements)
        _prealign_group_circular_patterns(placements)
        _distribute_single_circular_mount_phases(placements)
        _synchronize_pattern_sources_with_location(placements)
        _validate_no_world_coordinates(placements)
        alignment_policy_audit = _normalize_alignment_pin_hole_policy(kg, placements)
        if alignment_policy_audit:
            semantics.setdefault("metadata", {})["agent2_alignment_pin_policy_audit"] = alignment_policy_audit
        semantics["connection_placements"] = placements

    feasibility_report = validate_geometry_semantics_feasibility(
        semantics=semantics,
        kg=kg,
        apply_fallback=True,
    )
    policy_audit = semantics.get("metadata", {}).get("agent2_alignment_pin_policy_audit")
    if isinstance(policy_audit, list) and policy_audit:
        existing_policy_audit = feasibility_report.get("agent2_policy_audit")
        if isinstance(existing_policy_audit, list):
            feasibility_report["agent2_policy_audit"] = existing_policy_audit + [a for a in policy_audit if isinstance(a, dict)]
        else:
            feasibility_report["agent2_policy_audit"] = [a for a in policy_audit if isinstance(a, dict)]
    semantics.setdefault("metadata", {})["placement_feasibility"] = feasibility_report.get("summary", {})
    feasibility_report_path = run_dir / "planning" / "errors" / "geometry_semantics_feasibility.json"
    _write_json(feasibility_report_path, feasibility_report)

    summary = feasibility_report.get("summary")
    blocked_count = 0
    needs_clarification_count = 0
    if isinstance(summary, dict):
        blocked_raw = summary.get("blocked_count")
        if isinstance(blocked_raw, int):
            blocked_count = blocked_raw
        needs_raw = summary.get("needs_clarification_count")
        if isinstance(needs_raw, int):
            needs_clarification_count = needs_raw

    if blocked_count > 0 or needs_clarification_count > 0:
        append_event(
            run_dir=run_dir,
            event_type="warning.geometry_semantics_feasibility",
            data={
                "blocked_count": blocked_count,
                "needs_clarification_count": needs_clarification_count,
                "report": str(feasibility_report_path.relative_to(run_dir)).replace("\\", "/"),
            },
        )

    # Validate against schema if available
    schema_path = Path("planning") / "geometry_semantics_schema.json"
    if schema_path.exists():
        try:
            schema = _read_json(schema_path)
            validator = Draft202012Validator(schema)
            errors = list(validator.iter_errors(semantics))
            if errors:
                print(f"WARNING: Geometry semantics validation failed with {len(errors)} errors")
                for err in errors[:5]:
                    print(f"  - {err.message}")
        except Exception as e:
            print(f"WARNING: Could not validate semantics: {e}")

    # Write modeling-only semantics (for Agent3a)
    modeling_semantics = _build_modeling_semantics(semantics)
    _write_json(modeling_path, modeling_semantics)

    # Generate Geometry-Assembly Contract (MANDATORY for assembly planning)
    contract = _generate_geometry_assembly_contract(semantics, kg)
    assembly_path = run_dir / "planning" / f"geometry_semantics_assembly_round_{round_index}.json"
    _write_json(assembly_path, contract)

    print(f"[OK] Generated geometry-assembly contract: {assembly_path.name}")
    print(f"  - {len(contract['components'])} components with {sum(len(c['interfaces']) for c in contract['components'])} interfaces")
    print(f"  - Allowable attachment types: {', '.join(contract['allowable_attachment_types'])}")

    return {
        "modeling_path": f"planning/geometry_semantics_modeling_round_{round_index}.json",
        "assembly_path": f"planning/geometry_semantics_assembly_round_{round_index}.json"
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate geometry semantics plan")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)
    
    args = parser.parse_args()
    
    result = run(run_dir=args.run_dir, round_index=args.round_index)
    print(f"Generated modeling semantics: {result['modeling_path']}")


if __name__ == "__main__":
    main()



















