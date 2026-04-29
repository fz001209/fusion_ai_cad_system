"""Agent2 ??????????."""

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
