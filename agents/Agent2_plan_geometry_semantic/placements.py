"""Agent2 ??????????????LLM placement????????? placement ???."""

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
