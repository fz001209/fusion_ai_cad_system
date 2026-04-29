"""Agent1 connection requirements, frozen semantics, validation, and mechanical closure."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

import yaml

from tools.catalog.bearing_catalog import (
    candidate_series_for_bore,
    find_bearing_by_designation,
    nearest_bearing_by_dims,
    select_bearing_by_series_and_bore,
)

_ALLOWED_FROZEN_CONNECTION_MECHANISMS = {
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

_CONNECTION_PURPOSES_REQUIRING_EXPLICIT_SEMANTICS = {
    "rotation",
    "rotation_support",
    "torque_transfer",
    "structural_fixation",
    "structural_clamping",
    "fastening_mechanism",
    "support_to_structure",
    "load_support",
    "spacing",
}

_GENERIC_INTERFACE_HINTS = {
    "",
    "unspecified",
    "generic_interface",
    "fixation_req",
    "mounting_req",
    "mounting_req_drill_anchor",
    "support_req",
    "rotation_req",
    "torque_transfer_req",
}

def _sanitize_frozen_connection_mechanism(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    aliases = {
        "bolted_rigid": "bolted_mount",
        "bolted_hinged": "bolted_mount",
        "adhesive": "bonded_mount",
        "glued": "bonded_mount",
        "bonded_rigid": "bonded_mount",
        "welded": "welded_mount",
        "interference_fit": "press_fit",
        "bead_seat": "bonded_tread",
        "shaft_bore": "shaft_bore_fit",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _ALLOWED_FROZEN_CONNECTION_MECHANISMS else None

_ALLOWED_CANONICAL_CONNECTION_ANCHOR_KINDS = {
    "component_center",
    "distal_end",
    "proximal_end",
    "radial_mount_perimeter",
    "axial_face_perimeter_max",
    "axial_face_perimeter_min",
    "proximal_mount_face_min",
    "proximal_mount_face_max",
}

_CONNECTION_ANCHOR_STRING_ALIASES = {
    "center": "component_center",
    "centre": "component_center",
    "component_center": "component_center",
    "axis": "component_center",
    "shaft_axis": "component_center",
    "bore_axis": "component_center",
    "bore": "component_center",
}

_GENERIC_CONNECTION_RELATION_TYPES = {"fastening", "fixation", "mounting", "support", "rotation", "rigid", "locked", "attachment", "connection"}

_GENERIC_GEOMETRIC_SEMANTIC_VALUES = {"generic", "unspecified", "unknown", "default", "auto", "automatic", "heuristic", "inferred", "placeholder"}

_PATTERN_POLICIES_REQUIRING_COUNT = {"circular_array", "linear_array"}

def _sanitize_connection_geometric_semantics(raw: Any) -> Dict[str, Any] | None:
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

def _is_generic_connection_relation_type(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    normalized = value.strip().lower()
    return not normalized or normalized in _GENERIC_CONNECTION_RELATION_TYPES

def _connection_geometric_semantics_is_specific(raw: Any, *, mechanism: str | None) -> bool:
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

def _build_connection_geometric_semantics(
    *,
    contact_model: str,
    reference_feature_strategy: str,
    moving_feature_strategy: str,
    pattern_policy: str,
    pattern_count: int | None = None,
    hardware_layout: str | None = None,
    retention_strategy: str | None = None,
    notes: str | None = None,
    support_topology: str | None = None,
    anti_rotation_topology: str | None = None,
    mount_side: str | None = None,
    axial_stack_policy: str | None = None,
    clearance_policy: str | None = None,
    requires_axial_offset: bool | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "contact_model": contact_model,
        "reference_feature_strategy": reference_feature_strategy,
        "moving_feature_strategy": moving_feature_strategy,
        "pattern_policy": pattern_policy,
    }
    if isinstance(pattern_count, int) and pattern_count >= 1:
        out["pattern_count"] = pattern_count
    if isinstance(hardware_layout, str) and hardware_layout.strip():
        out["hardware_layout"] = hardware_layout
    if isinstance(retention_strategy, str) and retention_strategy.strip():
        out["retention_strategy"] = retention_strategy
    if isinstance(notes, str) and notes.strip():
        out["notes"] = notes
    if isinstance(support_topology, str) and support_topology.strip():
        out["support_topology"] = support_topology.strip().lower()
    if isinstance(anti_rotation_topology, str) and anti_rotation_topology.strip():
        out["anti_rotation_topology"] = anti_rotation_topology.strip().lower()
    if isinstance(mount_side, str) and mount_side.strip():
        out["mount_side"] = mount_side.strip().lower()
    if isinstance(axial_stack_policy, str) and axial_stack_policy.strip():
        out["axial_stack_policy"] = axial_stack_policy.strip().lower()
    if isinstance(clearance_policy, str) and clearance_policy.strip():
        out["clearance_policy"] = clearance_policy.strip().lower()
    if isinstance(requires_axial_offset, bool):
        out["requires_axial_offset"] = requires_axial_offset
    return out

_ROTATING_WHEEL_SUPPORT_CONTACT_MODEL = "double_shear_yoke_shaft_support"

_ROTATING_WHEEL_SUPPORT_TOPOLOGY = "double_shear_yoke_support"

_ROTATING_WHEEL_SUPPORT_CLEARANCE = "no_support_member_intrusion_into_wheel_envelope"

_ROTATING_WHEEL_SUPPORT_DEFAULT_INSET_MM = 12.0

def _phase_slot_mount_interface_name(phase_deg: Any) -> str:
    try:
        normalized = int(round(float(phase_deg))) % 360
    except Exception:
        normalized = 0
    return f"slot_mount_face_phase_{normalized}"

def _build_rotating_wheel_support_geometric_semantics(*, notes: str) -> Dict[str, Any]:
    return _build_connection_geometric_semantics(
        contact_model=_ROTATING_WHEEL_SUPPORT_CONTACT_MODEL,
        reference_feature_strategy="plain_bore",
        moving_feature_strategy="shaft_axis",
        pattern_policy="none",
        retention_strategy="axial_capture_with_spacer_stack",
        notes=notes,
        support_topology=_ROTATING_WHEEL_SUPPORT_TOPOLOGY,
        mount_side="centered_z",
        axial_stack_policy="wheel_body_between_support_plates",
        clearance_policy=_ROTATING_WHEEL_SUPPORT_CLEARANCE,
        requires_axial_offset=True,
    )

def _rotating_wheel_support_reference_anchor(*, axis: str = "x", inset_mm: float | None = None) -> Dict[str, Any]:
    inset = float(inset_mm) if isinstance(inset_mm, (int, float)) and float(inset_mm) > 0 else _ROTATING_WHEEL_SUPPORT_DEFAULT_INSET_MM
    return {"kind": "distal_end", "axis": axis, "inset_mm": inset}

def _bearing_seat_side_from_component_id(component_id: Any) -> str | None:
    cid = str(component_id or "").strip().lower()
    match = re.search(r"_bearing_(\d+)$", cid)
    if not match:
        return None
    try:
        index = int(match.group(1))
    except Exception:
        return None
    return "min" if index % 2 == 1 else "max"

def _wheel_root_component_id(component_id: Any) -> str | None:
    cid = str(component_id or "").strip().lower()
    match = re.match(r"^(wheel_\d+)(?:_|$)", cid)
    if not match:
        return None
    return match.group(1)

def _is_centered_single_wheel_bearing_support(
    *,
    host_component_id: Any,
    bearing_component_id: Any,
    component_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    host_id = str(host_component_id or "").strip().lower()
    bearing_id = str(bearing_component_id or "").strip().lower()
    if not host_id.endswith("_hub") or not re.search(r"_bearing_1$", bearing_id):
        return False
    wheel_root = _wheel_root_component_id(host_id)
    if wheel_root is None or wheel_root != _wheel_root_component_id(bearing_id):
        return False
    if not isinstance(component_lookup, Mapping):
        return False

    container = component_lookup.get(wheel_root)
    if isinstance(container, Mapping):
        shape = container.get("shape_semantics") if isinstance(container.get("shape_semantics"), Mapping) else {}
        support_architecture = str(shape.get("support_architecture") or "").strip().lower()
        if support_architecture == "single_bearing_through_bore":
            return True
        if support_architecture == "opposed_bearing_stack":
            return False

    sibling_bearing_id = f"{wheel_root}_bearing_2"
    sibling = component_lookup.get(sibling_bearing_id)
    if isinstance(sibling, Mapping):
        return False

    for comp in component_lookup.values():
        if not isinstance(comp, Mapping):
            continue
        comp_id = str(comp.get("id") or "").strip().lower()
        if comp_id == sibling_bearing_id:
            return False
        if str(comp.get("parent_id") or "").strip().lower() != wheel_root:
            continue
        if comp_id.endswith("_bearing_2"):
            return False

    return True

def _resolve_bearing_seat_side(
    *,
    host_component_id: Any,
    bearing_component_id: Any,
    component_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> str | None:
    if _is_centered_single_wheel_bearing_support(
        host_component_id=host_component_id,
        bearing_component_id=bearing_component_id,
        component_lookup=component_lookup,
    ):
        return None
    return _bearing_seat_side_from_component_id(bearing_component_id)

def _bearing_seat_interface_name(side: str | None) -> str:
    normalized = str(side or "").strip().lower()
    if normalized in {"min", "max"}:
        return f"bearing_seat_{normalized}"
    return "bearing_seat"

def _bearing_seat_entry_face_name(side: str | None) -> str:
    normalized = str(side or "").strip().lower()
    if normalized in {"min", "max"}:
        return f"axial_end_face_{normalized}"
    return "axial_end_face_max"

def _build_bearing_outer_race_seat_contract(
    *,
    host_component_id: str,
    bearing_component_id: str,
    rationale: str,
    component_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    seat_side = _resolve_bearing_seat_side(
        host_component_id=host_component_id,
        bearing_component_id=bearing_component_id,
        component_lookup=component_lookup,
    )
    seat_interface = _bearing_seat_interface_name(seat_side)
    seat_entry_face = _bearing_seat_entry_face_name(seat_side)
    notes = "Agent1 deterministic bearing outer race seat."
    if isinstance(seat_side, str):
        notes = f"{notes} Opposed seat side: {seat_side}."
    else:
        notes = f"{notes} Centered single-bearing seat."
    return {
        "connection_mechanism": "press_fit",
        "relation_type": "bearing_outer_race_seat",
        "reference_component_id": host_component_id,
        "moving_component_id": bearing_component_id,
        "reference_anchor": {"kind": "component_center", "notes": f"seat_side:{seat_side or 'unspecified'}"},
        "moving_anchor": {"kind": "component_center"},
        "reference_interface_hint": seat_interface,
        "moving_interface_hint": "outer_race_od",
        "assembly_reference_interface_hint": seat_interface,
        "assembly_moving_interface_hint": "outer_race_od",
        "orientation_policy": "locked",
        "geometric_semantics": _build_connection_geometric_semantics(
            contact_model="interference_cylindrical_seat",
            reference_feature_strategy="bearing_seat_bore",
            moving_feature_strategy="outer_race_od",
            pattern_policy="none",
            retention_strategy="interference_retained",
            notes=notes,
            mount_side=seat_entry_face,
            axial_stack_policy="opposed_bearing_outer_race_stack" if seat_side in {"min", "max"} else None,
            requires_axial_offset=seat_side in {"min", "max"},
        ),
        "rationale": rationale,
    }

def _infer_connection_geometric_semantics_from_contract(raw: Mapping[str, Any]) -> Dict[str, Any] | None:
    mechanism = _sanitize_frozen_connection_mechanism(raw.get("connection_mechanism"))
    relation_type = str(raw.get("relation_type") or "").strip().lower()
    reference_hint = str(raw.get("reference_interface_hint") or "").strip().lower()
    moving_hint = str(raw.get("moving_interface_hint") or "").strip().lower()
    orientation_policy = str(raw.get("orientation_policy") or "").strip().lower()
    reference_anchor = _sanitize_connection_anchor_contract(raw.get("reference_anchor")) or {}
    moving_anchor = _sanitize_connection_anchor_contract(raw.get("moving_anchor")) or {}
    reference_kind = str(reference_anchor.get("kind") or "").strip().lower()
    moving_kind = str(moving_anchor.get("kind") or "").strip().lower()

    if mechanism == "axial_face_bolted_mount":
        return _build_connection_geometric_semantics(
            contact_model="opposed_planar_clamp",
            reference_feature_strategy="threaded_hole",
            moving_feature_strategy="clearance_hole",
            pattern_policy="single",
            pattern_count=1,
            hardware_layout="thread_in_reference_bolt_head_on_moving",
            retention_strategy="threaded_clamp",
            notes="Agent1 normalized missing axial face bolted-mount geometric semantics.",
            anti_rotation_topology="root_pad_reaction_shoulder",
        )
    if mechanism == "radial_member_bolted_mount":
        return _build_connection_geometric_semantics(
            contact_model="single_station_bolted_mount",
            reference_feature_strategy="threaded_hole",
            moving_feature_strategy="clearance_hole",
            pattern_policy="single",
            pattern_count=1,
            hardware_layout="single_radial_bolt_station",
            retention_strategy="threaded_clamp",
            notes="Agent1 normalized missing radial member bolted-mount geometric semantics.",
        )
    if mechanism == "bolted_mount":
        return _build_connection_geometric_semantics(
            contact_model="through_bolt_clamp",
            reference_feature_strategy="clearance_hole",
            moving_feature_strategy="clearance_hole",
            pattern_policy="single",
            pattern_count=1,
            hardware_layout="through_bolt_with_nut",
            retention_strategy="threaded_clamp",
            notes="Agent1 normalized missing generic bolted-mount geometric semantics.",
        )
    if mechanism == "shaft_bore_fit":
        if relation_type == "support_member_distal_attachment" or "distal_mount" in reference_hint or reference_kind == "distal_end":
            return _build_rotating_wheel_support_geometric_semantics(
                notes="Agent1 normalized missing distal support geometric semantics as a forked dropout support that keeps the wheel clear of the support member."
            )
        if "inner_race" in reference_hint or "inner_race" in moving_hint:
            return _build_connection_geometric_semantics(
                contact_model="bearing_inner_race_revolute_fit",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="inner_race_bore",
                pattern_policy="none",
                retention_strategy="free_rotation_with_inner_race_capture",
                notes="Agent1 normalized missing bearing inner-race revolute-fit semantics.",
            )
        if orientation_policy == "free" or "bore" in reference_hint or "bore" in moving_hint or moving_kind == "component_center":
            return _build_connection_geometric_semantics(
                contact_model="coaxial_revolute_fit",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="through_bore",
                pattern_policy="none",
                retention_strategy="free_rotation_with_axial_capture",
                notes="Agent1 normalized missing shaft-to-bore revolute-fit semantics.",
                axial_stack_policy="preserve_independent_axial_stack",
                clearance_policy="axis_only_alignment_no_center_overlap",
            )
    if mechanism == "companion_rotation_relation":
        reference_feature_strategy = "drive_interface_axis" if "drive" in reference_hint or reference_hint == "axis" else "shaft_axis"
        moving_feature_strategy = "coaxial_drive_bore" if "drive" in moving_hint or "bore" in moving_hint else "shaft_axis"
        return _build_connection_geometric_semantics(
            contact_model="coaxial_locked_drive_coupling",
            reference_feature_strategy=reference_feature_strategy,
            moving_feature_strategy=moving_feature_strategy,
            pattern_policy="none",
            retention_strategy="co_rotating_lock",
            notes="Agent1 normalized missing companion-rotation geometric semantics.",
        )
    if mechanism == "press_fit":
        reference_feature_strategy = "bearing_seat_bore" if "seat" in reference_hint or "bore" in reference_hint else "press_fit_bore"
        moving_feature_strategy = "outer_race_od" if "outer_race" in moving_hint else "interference_od"
        return _build_connection_geometric_semantics(
            contact_model="interference_cylindrical_seat",
            reference_feature_strategy=reference_feature_strategy,
            moving_feature_strategy=moving_feature_strategy,
            pattern_policy="none",
            retention_strategy="interference_retained",
            notes="Agent1 normalized missing press-fit geometric semantics.",
        )
    if mechanism == "axial_stack_locator":
        return _build_connection_geometric_semantics(
            contact_model="axial_face_stackup",
            reference_feature_strategy="spacer_contact_face",
            moving_feature_strategy="datum_plane",
            pattern_policy="none",
            retention_strategy="axial_stack_separation",
            notes="Agent1 normalized missing axial stack locator geometric semantics.",
        )
    if mechanism == "bonded_tread":
        return _build_connection_geometric_semantics(
            contact_model="radial_wrap_bond",
            reference_feature_strategy="rim_tread_seat",
            moving_feature_strategy="tire_inner_tread_surface",
            pattern_policy="none",
            retention_strategy="bonded_wrap",
            notes="Agent1 normalized missing bonded tread geometric semantics.",
        )
    return None

def _is_agent1_deterministic_connection_requirement(cr: Mapping[str, Any]) -> bool:
    if not isinstance(cr, Mapping):
        return False
    cr_id = str(cr.get("id") or "").strip().lower()
    description = str(cr.get("description") or "").strip().lower()
    text = f"{cr_id} {description}"
    if any(token in text for token in ("_auto", "auto-filled", "deterministic", "canonicalized")):
        return True
    if any(
        token in cr_id
        for token in (
            "body_axle_rotation",
            "bearing_1_body_support",
            "bearing_2_body_support",
            "bearing_1_axle_rotation",
            "bearing_2_axle_rotation",
            "spacer_axial",
            "tire_rim_fix",
        )
    ):
        return True
    raw_semantics = cr.get("connection_semantics")
    if isinstance(raw_semantics, Mapping):
        rationale = str(raw_semantics.get("rationale") or "").strip().lower()
        if any(
            token in rationale
            for token in (
                "auto-filled",
                "canonicalized",
                "wheel body rotates around the axle",
                "bearing outer ring seats in the wheel body",
                "tire is retained on the rim",
            )
        ):
            return True
    return False

def _infer_agent1_deterministic_connection_semantics(
    cr: Mapping[str, Any],
    *,
    type_by_id: Mapping[str, str],
) -> Dict[str, Any] | None:
    if not _is_agent1_deterministic_connection_requirement(cr):
        return None

    between_ids = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
    if len(between_ids) < 2:
        return None

    raw_semantics = cr.get("connection_semantics") if isinstance(cr.get("connection_semantics"), Mapping) else {}
    purpose = _normalize_purpose(cr.get("purpose"))
    axle_or_shaft_ids = [cid for cid in between_ids if type_by_id.get(cid) in {"axle", "shaft"}]
    arm_ids = [cid for cid in between_ids if type_by_id.get(cid) == "arm"]
    bearing_ids = [cid for cid in between_ids if type_by_id.get(cid) == "bearing"]
    wheel_body_ids = [cid for cid in between_ids if type_by_id.get(cid) in {"wheel", "hub", "rim", "disc", "body"}]
    drive_interface_ids = [
        cid for cid in between_ids
        if type_by_id.get(cid) in {"interface_block", "motor", "electric_motor", "gearbox", "gear_reducer", "coupling"}
        or "motor_interface" in cid.lower()
    ]
    tire_ids = [cid for cid in between_ids if type_by_id.get(cid) == "tire"]
    rim_ids = [cid for cid in between_ids if type_by_id.get(cid) == "rim"]
    spacer_ids = [cid for cid in between_ids if type_by_id.get(cid) == "spacer"]

    mechanism = _sanitize_frozen_connection_mechanism(raw_semantics.get("connection_mechanism"))
    if bearing_ids and axle_or_shaft_ids and purpose == "rotation_support":
        mechanism = "shaft_bore_fit"
    elif spacer_ids and bearing_ids and purpose == "spacing":
        mechanism = "axial_stack_locator"
    elif bearing_ids and wheel_body_ids and purpose in {"load_support", "support_to_structure"}:
        mechanism = "press_fit"
    elif drive_interface_ids and axle_or_shaft_ids and purpose == "torque_transfer":
        mechanism = "companion_rotation_relation"
    elif mechanism is None:
        if arm_ids and axle_or_shaft_ids and purpose in {"load_support", "support_to_structure", "structural_fixation", "fastening_mechanism"}:
            mechanism = "shaft_bore_fit"
        elif tire_ids and rim_ids and purpose == "structural_fixation":
            mechanism = "bonded_tread"
        elif bearing_ids and wheel_body_ids and purpose in {"load_support", "support_to_structure"}:
            mechanism = "press_fit"
        elif axle_or_shaft_ids and purpose == "rotation":
            mechanism = "shaft_bore_fit"
        elif axle_or_shaft_ids and purpose == "structural_fixation":
            mechanism = "companion_rotation_relation"
        else:
            return None

    existing_reference_anchor = _sanitize_connection_anchor_contract(raw_semantics.get("reference_anchor"))
    existing_moving_anchor = _sanitize_connection_anchor_contract(raw_semantics.get("moving_anchor"))
    existing_reference_hint = raw_semantics.get("reference_interface_hint")
    existing_moving_hint = raw_semantics.get("moving_interface_hint")
    existing_relation_type = raw_semantics.get("relation_type")
    existing_orientation_policy = raw_semantics.get("orientation_policy")
    existing_rationale = raw_semantics.get("rationale")
    existing_confidence = raw_semantics.get("confidence")

    contract: Dict[str, Any] | None = None
    preserve_existing_fields = True

    if (
        arm_ids
        and axle_or_shaft_ids
        and purpose in {"load_support", "support_to_structure", "structural_fixation", "fastening_mechanism"}
        and mechanism in {"shaft_bore_fit", "companion_rotation_relation"}
    ):
        mechanism = "shaft_bore_fit"
        arm_id = arm_ids[0]
        axle_id = axle_or_shaft_ids[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "support_member_distal_attachment",
            "reference_component_id": arm_id,
            "moving_component_id": axle_id,
            "reference_anchor": _rotating_wheel_support_reference_anchor(axis="x"),
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "distal_mount_face",
            "moving_interface_hint": "shaft_axis",
            "orientation_policy": "inherit_reference_yaw",
            "geometric_semantics": _build_rotating_wheel_support_geometric_semantics(
                notes="Agent1 deterministic rotating wheel support keeps the wheel stack clear of the support member by using a forked dropout topology."
            ),
            "rationale": "Deterministic arm-to-axle support must preserve independent wheel rolling and avoid arm intrusion into the wheel envelope.",
        }
        preserve_existing_fields = False
    elif mechanism == "shaft_bore_fit" and bearing_ids and axle_or_shaft_ids and purpose == "rotation_support":
        axle_id = axle_or_shaft_ids[0]
        bearing_id = bearing_ids[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "shaft_axis_to_bore",
            "reference_component_id": axle_id,
            "moving_component_id": bearing_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "shaft_axis",
            "moving_interface_hint": "bore_axis",
            "orientation_policy": "free",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="bearing_inner_race_revolute_fit",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="inner_race_bore",
                pattern_policy="none",
                retention_strategy="free_rotation_with_inner_race_capture",
                notes="Agent1 deterministic bearing inner-race revolute support.",
            ),
            "rationale": "Deterministic bearing rotation support must stay a shaft-to-inner-race revolute fit.",
        }
        preserve_existing_fields = False
    elif mechanism == "shaft_bore_fit" and axle_or_shaft_ids and purpose == "rotation":
        axle_id = axle_or_shaft_ids[0]
        moving_candidates = [cid for cid in between_ids if cid != axle_id]
        if not moving_candidates:
            return None
        moving_id = moving_candidates[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "shaft_axis_to_bore",
            "reference_component_id": axle_id,
            "moving_component_id": moving_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "shaft_axis",
            "moving_interface_hint": "bore_axis",
            "orientation_policy": "free",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="coaxial_revolute_fit",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="through_bore",
                                pattern_policy="single",
                retention_strategy="free_rotation_with_axial_capture",
                notes="Agent1 deterministic shaft-to-bore revolute relation preserves axial stack placement instead of forcing center overlap.",
                axial_stack_policy="preserve_independent_axial_stack",
                clearance_policy="axis_only_alignment_no_center_overlap",
            ),
            "rationale": "Deterministic rotation closure must keep coaxial revolute alignment without collapsing independently supported wheel stacks onto the support plane.",
        }
    elif mechanism == "companion_rotation_relation" and axle_or_shaft_ids:
        shaft_id = axle_or_shaft_ids[0]
        moving_candidates = [cid for cid in between_ids if cid != shaft_id]
        if not moving_candidates:
            return None
        moving_id = moving_candidates[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "coaxial_locked_drive_coupling",
            "reference_component_id": shaft_id,
            "moving_component_id": moving_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "shaft_axis",
            "moving_interface_hint": "drive_bore",
            "orientation_policy": "locked",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="coaxial_locked_coupling",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="coaxial_drive_bore",
                pattern_policy="single",
                retention_strategy="positive_torque_transfer",
                notes="Agent1 deterministic shaft-to-hub locked drive coupling.",
            ),
            "rationale": "Deterministic shaft fixation closure must stay a coaxial locked coupling, not a bolt-pattern mount.",
        }
    elif mechanism == "press_fit" and bearing_ids and wheel_body_ids and purpose in {"load_support", "support_to_structure"}:
        body_id = wheel_body_ids[0]
        bearing_id = bearing_ids[0]
        contract = _build_bearing_outer_race_seat_contract(
            host_component_id=body_id,
            bearing_component_id=bearing_id,
            rationale="Deterministic bearing support closure must stay a bearing outer-race seat in the wheel body.",
        )
    elif mechanism == "axial_stack_locator" and spacer_ids and bearing_ids and purpose == "spacing":
        bearing_id = bearing_ids[0]
        spacer_id = spacer_ids[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "axial_spacer_stack",
            "reference_component_id": bearing_id,
            "moving_component_id": spacer_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "spacer_face",
            "moving_interface_hint": "datum_plane",
            "orientation_policy": "locked",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="axial_face_stackup",
                reference_feature_strategy="spacer_contact_face",
                moving_feature_strategy="datum_plane",
                pattern_policy="none",
                retention_strategy="axial_stack_separation",
                notes="Agent1 deterministic spacer stack separator between bearing faces.",
            ),
            "rationale": "Deterministic spacer relation must stay an axial stack separator, not a bolted mount.",
        }
        preserve_existing_fields = False
    elif mechanism == "bonded_tread" and tire_ids and rim_ids and purpose == "structural_fixation":
        rim_id = rim_ids[0]
        tire_id = tire_ids[0]
        contract = {
            "connection_mechanism": mechanism,
            "relation_type": "bonded_tread_wrap",
            "reference_component_id": rim_id,
            "moving_component_id": tire_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "radial_outer_face",
            "moving_interface_hint": "radial_inner_face",
            "orientation_policy": "locked",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="radial_wrap_bond",
                reference_feature_strategy="rim_tread_seat",
                moving_feature_strategy="tire_inner_tread_surface",
                pattern_policy="single",
                retention_strategy="bonded_wrap",
                notes="Agent1 deterministic tire-to-rim wrap relation.",
            ),
            "rationale": "Deterministic tire retention must stay a bonded or seated tread wrap without through-fasteners.",
        }
        preserve_existing_fields = False

    if contract is None:
        return None

    if preserve_existing_fields and isinstance(existing_relation_type, str) and existing_relation_type.strip() and not _is_generic_connection_relation_type(existing_relation_type):
        contract["relation_type"] = existing_relation_type.strip().lower()
    if preserve_existing_fields and existing_reference_anchor is not None:
        contract["reference_anchor"] = existing_reference_anchor
    if preserve_existing_fields and existing_moving_anchor is not None:
        contract["moving_anchor"] = existing_moving_anchor
    if preserve_existing_fields and isinstance(existing_reference_hint, str) and existing_reference_hint.strip():
        contract["reference_interface_hint"] = existing_reference_hint.strip()
    if preserve_existing_fields and isinstance(existing_moving_hint, str) and existing_moving_hint.strip():
        contract["moving_interface_hint"] = existing_moving_hint.strip()
    if preserve_existing_fields and isinstance(existing_orientation_policy, str) and existing_orientation_policy.strip():
        contract["orientation_policy"] = existing_orientation_policy.strip().lower()
    if isinstance(existing_rationale, str) and existing_rationale.strip():
        contract["rationale"] = existing_rationale.strip()
    if isinstance(existing_confidence, (int, float)):
        contract["confidence"] = float(existing_confidence)
    return contract

def _autofill_agent1_deterministic_connection_semantics(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    repairs: list[dict[str, Any]] = []
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        contract = _infer_agent1_deterministic_connection_semantics(cr, type_by_id=type_by_id)
        if contract is None:
            continue
        between_ids = {cid for cid in cr.get("between", []) if isinstance(cid, str) and cid}
        sanitized = _sanitize_connection_semantics_contract(contract, valid_component_ids=between_ids)
        if sanitized is None:
            continue
        prior = cr.get("connection_semantics")
        prior_relation = prior.get("relation_type") if isinstance(prior, Mapping) else None
        prior_mechanism = prior.get("connection_mechanism") if isinstance(prior, Mapping) else None
        cr["connection_semantics"] = sanitized
        repairs.append(
            {
                "connection_id": cr.get("id"),
                "action": "agent1_deterministic_contract_autofill",
                "mechanism": sanitized.get("connection_mechanism"),
                "relation_type_before": prior_relation,
                "relation_type_after": sanitized.get("relation_type"),
                "mechanism_before": prior_mechanism,
            }
        )

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_log = metadata.get("agent1_deterministic_connection_semantics_repairs")
        if not isinstance(repair_log, list):
            repair_log = []
        repair_log.extend(repairs)
        metadata["agent1_deterministic_connection_semantics_repairs"] = repair_log
        payload["metadata"] = metadata

def _elevate_authoritative_connection_semantics_detail(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    comp_by_id = {
        comp.get("id"): comp
        for comp in components
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str) and comp.get("id")
    }
    repairs: list[dict[str, Any]] = []

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between_ids = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
        if len(between_ids) < 2:
            continue
        semantics = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )
        if semantics is None:
            continue

        purpose = _normalize_purpose(cr.get("purpose"))
        hub_ids = [cid for cid in between_ids if type_by_id.get(cid) == "hub"]
        arm_ids = [cid for cid in between_ids if type_by_id.get(cid) == "arm"]
        axle_ids = [cid for cid in between_ids if type_by_id.get(cid) in {"axle", "shaft"}]
        bearing_ids = [cid for cid in between_ids if type_by_id.get(cid) == "bearing"]
        wheel_body_ids = [cid for cid in between_ids if type_by_id.get(cid) in {"wheel", "hub", "rim", "disc", "body"}]
        drive_interface_ids = [
            cid for cid in between_ids
            if type_by_id.get(cid) in {"interface_block", "motor", "electric_motor", "gearbox", "gear_reducer", "coupling"}
            or "motor_interface" in cid.lower()
        ]
        original = copy.deepcopy(semantics)

        if hub_ids and arm_ids and purpose in {"structural_fixation", "structural_clamping", "fastening_mechanism"}:
            hub_id = hub_ids[0]
            arm_id = arm_ids[0]
            existing_mechanism = str(semantics.get("connection_mechanism") or "").strip().lower()
            existing_relation_type = str(semantics.get("relation_type") or "").strip().lower()
            existing_geo = semantics.get("geometric_semantics") if isinstance(semantics.get("geometric_semantics"), Mapping) else {}
            existing_contact_model = str(existing_geo.get("contact_model") or "").strip().lower()
            existing_support_topology = str(existing_geo.get("support_topology") or "").strip().lower()
            preserve_existing = (
                existing_mechanism == "axial_face_bolted_mount"
                and existing_relation_type == "axial_face_perimeter_mount"
                and existing_contact_model not in {"", "single_station_bolted_mount"}
                and existing_support_topology not in {"", "unspecified"}
            )
            if not preserve_existing:
                ref_anchor = semantics.get("reference_anchor") if isinstance(semantics.get("reference_anchor"), Mapping) else {"kind": "axial_face_perimeter_max"}
                moving_anchor = semantics.get("moving_anchor") if isinstance(semantics.get("moving_anchor"), Mapping) else {"kind": "proximal_end", "axis": "x", "inset_mm": 12.0}
                ref_kind = str(ref_anchor.get("kind") or "axial_face_perimeter_max").strip().lower()
                moving_kind = str(moving_anchor.get("kind") or "proximal_end").strip().lower()
                if ref_kind not in {"axial_face_perimeter_max", "axial_face_perimeter_min"}:
                    ref_kind = "axial_face_perimeter_max"
                if moving_kind not in {"proximal_end", "proximal_mount_face_min", "proximal_mount_face_max"}:
                    moving_kind = "proximal_end"
                face_side = "min" if ref_kind.endswith("_min") else "max"
                insert_depth = moving_anchor.get("inset_mm")
                if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
                    insert_depth = 12.0
                semantics["connection_mechanism"] = "axial_face_bolted_mount"
                semantics["relation_type"] = "axial_face_perimeter_mount"
                semantics["reference_component_id"] = hub_id
                semantics["moving_component_id"] = arm_id
                semantics["reference_anchor"] = {
                    "kind": ref_kind,
                    **({"radius_mm": float(ref_anchor.get("radius_mm"))} if isinstance(ref_anchor.get("radius_mm"), (int, float)) else {}),
                }
                semantics["moving_anchor"] = {
                    "kind": moving_kind,
                    "axis": "x",
                    "inset_mm": float(insert_depth),
                }
                phase_hint = None
                if isinstance(ref_anchor.get("phase_deg"), (int, float)):
                    phase_hint = _phase_slot_mount_interface_name(ref_anchor.get("phase_deg"))
                elif isinstance(ref_anchor.get("phase_rad"), (int, float)):
                    phase_hint = _phase_slot_mount_interface_name(math.degrees(float(ref_anchor.get("phase_rad"))))
                if not isinstance(phase_hint, str) or not phase_hint:
                    phase_hint = _phase_slot_mount_interface_name(0.0 if face_side == "max" else 180.0)
                semantics["reference_interface_hint"] = phase_hint
                semantics["moving_interface_hint"] = "proximal_insert_face"
                semantics["assembly_reference_interface_hint"] = phase_hint
                semantics["assembly_moving_interface_hint"] = "proximal_insert_face"
                semantics["orientation_policy"] = "radial_from_reference_center"
                semantics["geometric_semantics"] = _build_connection_geometric_semantics(
                    contact_model="through_bolt_clamp_in_radial_slot",
                    reference_feature_strategy="radial_slot_pocket",
                    moving_feature_strategy="root_tenon_pad",
                    pattern_policy="single",
                    pattern_count=1,
                    hardware_layout="through_bolt_external_nut_clamp",
                    retention_strategy="through_bolt_clamp",
                    notes="Agent1 elevated hub-to-arm contract to a radial slot insertion mount retained by an external through-bolt clamp across the hub axial face and arm root.",
                    support_topology="hub_radial_slot_mount",
                    anti_rotation_topology="radial_slot_capture",
                    mount_side="centered_z",
                    axial_stack_policy="through_bolt_external_clamp",
                    clearance_policy="radial_slot_clearance",
                    requires_axial_offset=False,
                )
                connection_decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), dict) else {}
                connection_decision["method"] = "bolted_rigid"
                if not isinstance(connection_decision.get("fastener_size"), str) or not connection_decision.get("fastener_size"):
                    connection_decision["fastener_size"] = "M5x12"
                if not isinstance(connection_decision.get("count"), int) or int(connection_decision.get("count")) < 1:
                    connection_decision["count"] = 1
                if not isinstance(connection_decision.get("fit_policy"), str) or not connection_decision.get("fit_policy"):
                    connection_decision["fit_policy"] = "clearance"
                cr["connection_decision"] = connection_decision
        elif arm_ids and axle_ids and purpose in {"load_support", "support_to_structure"} and semantics.get("connection_mechanism") == "shaft_bore_fit":
            arm_id = arm_ids[0]
            axle_id = axle_ids[0]
            semantics["relation_type"] = "support_member_distal_attachment"
            semantics["reference_component_id"] = arm_id
            semantics["moving_component_id"] = axle_id
            semantics["reference_anchor"] = _rotating_wheel_support_reference_anchor(axis="x")
            semantics["moving_anchor"] = {"kind": "component_center"}
            semantics["reference_interface_hint"] = "distal_mount_face"
            semantics["moving_interface_hint"] = "shaft_axis"
            semantics["assembly_reference_interface_hint"] = "distal_bore_axis"
            semantics["assembly_moving_interface_hint"] = "shaft_axis"
            semantics["orientation_policy"] = "inherit_reference_yaw"
            semantics["geometric_semantics"] = _build_rotating_wheel_support_geometric_semantics(
                notes="Agent1 elevated distal arm support contract to a forked dropout topology that keeps the wheel clear of the support member."
            )
        elif bearing_ids and axle_ids and purpose == "rotation_support":
            axle_id = axle_ids[0]
            bearing_id = bearing_ids[0]
            semantics["connection_mechanism"] = "shaft_bore_fit"
            semantics["relation_type"] = "shaft_axis_to_bore"
            semantics["reference_component_id"] = axle_id
            semantics["moving_component_id"] = bearing_id
            semantics["reference_anchor"] = {"kind": "component_center"}
            semantics["moving_anchor"] = {"kind": "component_center"}
            semantics["reference_interface_hint"] = "shaft_axis"
            semantics["moving_interface_hint"] = "bore_axis"
            semantics["orientation_policy"] = "free"
            semantics["geometric_semantics"] = _build_connection_geometric_semantics(
                contact_model="bearing_inner_race_revolute_fit",
                reference_feature_strategy="shaft_axis",
                moving_feature_strategy="inner_race_bore",
                pattern_policy="none",
                retention_strategy="free_rotation_with_inner_race_capture",
                notes="Agent1 elevated bearing rotation support contract.",
            )
        elif bearing_ids and wheel_body_ids and purpose in {"load_support", "support_to_structure"}:
            body_id = wheel_body_ids[0]
            bearing_id = bearing_ids[0]
            semantics.update(
                _build_bearing_outer_race_seat_contract(
                    host_component_id=body_id,
                    bearing_component_id=bearing_id,
                    rationale="Agent1 elevated bearing outer-race support contract.",
                    component_lookup=comp_by_id,
                )
            )
        elif drive_interface_ids and axle_ids and purpose == "torque_transfer":
            interface_id = drive_interface_ids[0]
            shaft_id = axle_ids[0]
            semantics["connection_mechanism"] = "companion_rotation_relation"
            semantics["relation_type"] = "coaxial_locked_drive_coupling"
            semantics["reference_component_id"] = interface_id
            semantics["moving_component_id"] = shaft_id
            semantics["reference_anchor"] = {"kind": "component_center"}
            semantics["moving_anchor"] = {"kind": "component_center"}
            semantics["reference_interface_hint"] = "axis"
            semantics["moving_interface_hint"] = "shaft_axis"
            semantics["orientation_policy"] = "locked"
            semantics["geometric_semantics"] = _build_connection_geometric_semantics(
                contact_model="coaxial_locked_drive_coupling",
                reference_feature_strategy="drive_interface_axis",
                moving_feature_strategy="shaft_axis",
                pattern_policy="none",
                retention_strategy="co_rotating_lock",
                notes="Agent1 elevated drive-interface torque transfer contract.",
            )

        sanitized = _sanitize_connection_semantics_contract(semantics, valid_component_ids=set(between_ids))
        if sanitized is not None and sanitized != original:
            cr["connection_semantics"] = sanitized
            repairs.append({
                "connection_id": cr.get("id"),
                "action": "elevated_authoritative_connection_semantics_detail",
                "relation_type": sanitized.get("relation_type"),
                "mechanism": sanitized.get("connection_mechanism"),
            })

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_log = metadata.get("agent1_connection_semantics_elevations")
        if not isinstance(repair_log, list):
            repair_log = []
        repair_log.extend(repairs)
        metadata["agent1_connection_semantics_elevations"] = repair_log
        payload["metadata"] = metadata

def _normalize_symmetric_wheel_rim_hub_connection_semantics(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)

    def _norm(value: Any) -> str:
        return str(value or "").strip().lower()

    def _signature(semantics: Mapping[str, Any]) -> tuple[str, ...]:
        reference_anchor = semantics.get("reference_anchor") if isinstance(semantics.get("reference_anchor"), Mapping) else {}
        moving_anchor = semantics.get("moving_anchor") if isinstance(semantics.get("moving_anchor"), Mapping) else {}
        geometric = semantics.get("geometric_semantics") if isinstance(semantics.get("geometric_semantics"), Mapping) else {}
        return (
            _norm(semantics.get("connection_mechanism")),
            _norm(semantics.get("relation_type")),
            _norm(reference_anchor.get("kind")),
            _norm(moving_anchor.get("kind")),
            _norm(semantics.get("reference_interface_hint")),
            _norm(semantics.get("moving_interface_hint")),
            _norm(geometric.get("contact_model")),
            _norm(geometric.get("reference_feature_strategy")),
            _norm(geometric.get("moving_feature_strategy")),
            _norm(geometric.get("pattern_policy")),
        )

    def _specificity_score(signature: tuple[str, ...]) -> int:
        mechanism, relation_type, ref_anchor_kind, mov_anchor_kind, ref_hint, mov_hint, contact_model, _ref_strategy, _mov_strategy, pattern_policy = signature
        placeholder_hints = {"", "fixation_req", "mounting_req", "support_req", "generic_interface", "unspecified", "planar_face", "mount_hole"}
        score = 0
        if mechanism not in {"", "generic_mount"}:
            score += 3
        if relation_type not in {"", "radial_member_distal_support", "generic_mount"}:
            score += 2
        if ref_anchor_kind not in {"", "component_center"}:
            score += 1
        if mov_anchor_kind not in {"", "component_center"}:
            score += 1
        if ref_hint not in placeholder_hints:
            score += 1
        if mov_hint not in placeholder_hints:
            score += 1
        if contact_model not in {"", "bonded_wrap", "unspecified"}:
            score += 2
        if pattern_policy not in {"", "none", "unspecified"}:
            score += 1
        return score

    candidates: list[dict[str, Any]] = []
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        between_ids = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
        rim_ids = [cid for cid in between_ids if type_by_id.get(cid) == "rim"]
        hub_ids = [cid for cid in between_ids if type_by_id.get(cid) == "hub"]
        if len(rim_ids) != 1 or len(hub_ids) != 1:
            continue
        rim_id = rim_ids[0]
        hub_id = hub_ids[0]
        rim_match = re.fullmatch(r"wheel_(\d+)_rim", rim_id)
        hub_match = re.fullmatch(r"wheel_(\d+)_hub", hub_id)
        if not rim_match or not hub_match or rim_match.group(1) != hub_match.group(1):
            continue
        semantics = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )
        if semantics is None:
            continue
        sig = _signature(semantics)
        candidates.append(
            {
                "wheel_suffix": rim_match.group(1),
                "connection": cr,
                "between_ids": between_ids,
                "rim_id": rim_id,
                "hub_id": hub_id,
                "semantics": semantics,
                "signature": sig,
            }
        )

    if len(candidates) < 2:
        return

    counts: Dict[tuple[str, ...], int] = {}
    representative: Dict[tuple[str, ...], Mapping[str, Any]] = {}
    for item in candidates:
        sig = item["signature"]
        counts[sig] = counts.get(sig, 0) + 1
        representative.setdefault(sig, item["semantics"])

    ranked_signatures = sorted(counts.keys(), key=lambda sig: (-counts[sig], -_specificity_score(sig), sig))
    if not ranked_signatures:
        return
    top_signature = ranked_signatures[0]
    if counts.get(top_signature, 0) < 2:
        return
    if len(ranked_signatures) > 1 and counts[top_signature] == counts[ranked_signatures[1]]:
        return

    template = representative[top_signature]
    repairs: list[dict[str, Any]] = []
    for item in candidates:
        if item["signature"] == top_signature:
            continue
        normalized = copy.deepcopy(dict(template))
        normalized["reference_component_id"] = item["hub_id"]
        normalized["moving_component_id"] = item["rim_id"]
        sanitized = _sanitize_connection_semantics_contract(
            normalized,
            valid_component_ids=set(item["between_ids"]),
        )
        if sanitized is None:
            continue
        item["connection"]["connection_semantics"] = sanitized
        repairs.append(
            {
                "connection_id": item["connection"].get("id"),
                "wheel_suffix": item["wheel_suffix"],
                "action": "normalized_to_majority_symmetric_wheel_rim_hub_contract",
                "from_signature": list(item["signature"]),
                "to_signature": list(top_signature),
            }
        )

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        audit_log = metadata.get("normalized_symmetric_wheel_rim_hub_connection_semantics")
        if not isinstance(audit_log, list):
            audit_log = []
        audit_log.extend(repairs)
        metadata["normalized_symmetric_wheel_rim_hub_connection_semantics"] = audit_log
        payload["metadata"] = metadata

def _normalize_symmetric_wheel_tire_rim_connection_semantics(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)

    def _norm(value: Any) -> str:
        return str(value or "").strip().lower()

    def _signature(semantics: Mapping[str, Any]) -> tuple[str, ...]:
        reference_anchor = semantics.get("reference_anchor") if isinstance(semantics.get("reference_anchor"), Mapping) else {}
        moving_anchor = semantics.get("moving_anchor") if isinstance(semantics.get("moving_anchor"), Mapping) else {}
        geometric = semantics.get("geometric_semantics") if isinstance(semantics.get("geometric_semantics"), Mapping) else {}
        return (
            _norm(semantics.get("connection_mechanism")),
            _norm(semantics.get("relation_type")),
            _norm(reference_anchor.get("kind")),
            _norm(moving_anchor.get("kind")),
            _norm(semantics.get("reference_interface_hint")),
            _norm(semantics.get("moving_interface_hint")),
            _norm(geometric.get("contact_model")),
            _norm(geometric.get("reference_feature_strategy")),
            _norm(geometric.get("moving_feature_strategy")),
            _norm(geometric.get("pattern_policy")),
        )

    def _specificity_score(signature: tuple[str, ...]) -> int:
        mechanism, relation_type, ref_anchor_kind, mov_anchor_kind, ref_hint, mov_hint, contact_model, _ref_strategy, _mov_strategy, pattern_policy = signature
        placeholder_hints = {"", "fixation_req", "mounting_req", "support_req", "generic_interface", "unspecified", "planar_face", "mount_hole"}
        score = 0
        if mechanism not in {"", "generic_mount"}:
            score += 3
        if relation_type not in {"", "generic_mount"}:
            score += 2
        if ref_anchor_kind not in {"", "component_center"}:
            score += 1
        if mov_anchor_kind not in {"", "component_center"}:
            score += 1
        if ref_hint not in placeholder_hints:
            score += 1
        if mov_hint not in placeholder_hints:
            score += 1
        if contact_model not in {"", "unspecified"}:
            score += 2
        if pattern_policy not in {"", "none", "unspecified"}:
            score += 1
        return score

    candidates: list[dict[str, Any]] = []
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        between_ids = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
        tire_ids = [cid for cid in between_ids if type_by_id.get(cid) == "tire"]
        rim_ids = [cid for cid in between_ids if type_by_id.get(cid) == "rim"]
        if len(tire_ids) != 1 or len(rim_ids) != 1:
            continue
        tire_id = tire_ids[0]
        rim_id = rim_ids[0]
        tire_match = re.fullmatch(r"wheel_(\d+)_tire", tire_id)
        rim_match = re.fullmatch(r"wheel_(\d+)_rim", rim_id)
        if not tire_match or not rim_match or tire_match.group(1) != rim_match.group(1):
            continue
        semantics = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )
        if semantics is None:
            continue
        sig = _signature(semantics)
        candidates.append(
            {
                "wheel_suffix": tire_match.group(1),
                "connection": cr,
                "between_ids": between_ids,
                "tire_id": tire_id,
                "rim_id": rim_id,
                "semantics": semantics,
                "signature": sig,
            }
        )

    if len(candidates) < 2:
        return

    counts: Dict[tuple[str, ...], int] = {}
    representative: Dict[tuple[str, ...], Mapping[str, Any]] = {}
    for item in candidates:
        sig = item["signature"]
        counts[sig] = counts.get(sig, 0) + 1
        representative.setdefault(sig, item["semantics"])

    ranked_signatures = sorted(counts.keys(), key=lambda sig: (-counts[sig], -_specificity_score(sig), sig))
    if not ranked_signatures:
        return
    top_signature = ranked_signatures[0]
    if counts.get(top_signature, 0) < 2:
        return
    if len(ranked_signatures) > 1 and counts[top_signature] == counts[ranked_signatures[1]]:
        return

    template = representative[top_signature]
    repairs: list[dict[str, Any]] = []
    for item in candidates:
        if item["signature"] == top_signature:
            continue
        normalized = copy.deepcopy(dict(template))
        normalized["reference_component_id"] = item["rim_id"]
        normalized["moving_component_id"] = item["tire_id"]
        sanitized = _sanitize_connection_semantics_contract(
            normalized,
            valid_component_ids=set(item["between_ids"]),
        )
        if sanitized is None:
            continue
        item["connection"]["connection_semantics"] = sanitized
        repairs.append(
            {
                "connection_id": item["connection"].get("id"),
                "wheel_suffix": item["wheel_suffix"],
                "action": "normalized_to_majority_symmetric_wheel_tire_rim_contract",
                "from_signature": list(item["signature"]),
                "to_signature": list(top_signature),
            }
        )

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        audit_log = metadata.get("normalized_symmetric_wheel_tire_rim_connection_semantics")
        if not isinstance(audit_log, list):
            audit_log = []
        audit_log.extend(repairs)
        metadata["normalized_symmetric_wheel_tire_rim_connection_semantics"] = audit_log
        payload["metadata"] = metadata

def _sanitize_connection_anchor_contract(raw: Any) -> Dict[str, Any] | None:
    if isinstance(raw, str):
        normalized_kind = _CONNECTION_ANCHOR_STRING_ALIASES.get(raw.strip().lower(), raw.strip().lower())
        if normalized_kind in _ALLOWED_CANONICAL_CONNECTION_ANCHOR_KINDS:
            return {"kind": normalized_kind}
        return None
    if not isinstance(raw, Mapping):
        return None
    kind_raw = raw.get("kind")
    if not isinstance(kind_raw, str) or not kind_raw.strip():
        return None
    normalized_kind = _CONNECTION_ANCHOR_STRING_ALIASES.get(kind_raw.strip().lower(), kind_raw.strip().lower())
    if normalized_kind not in _ALLOWED_CANONICAL_CONNECTION_ANCHOR_KINDS:
        return None
    anchor: Dict[str, Any] = {"kind": normalized_kind}
    axis = raw.get("axis")
    if isinstance(axis, str) and axis.strip():
        axis_value = axis.strip().lower()
        axis_aliases = {
            "central_axis": "z",
            "central_rotation_axis": "z",
            "hub_axis": "z",
            "module_axis": "z",
            "rotation_axis": "z",
            "axial": "z",
            "radial": "x",
            "radial_from_hub": "x",
            "arm_axis": "x",
        }
        normalized_axis = axis_aliases.get(axis_value, axis_value)
        if normalized_axis in {"x", "y", "z"}:
            anchor["axis"] = normalized_axis
    for numeric_key in ("radius_mm", "inset_mm", "phase_deg", "phase_rad"):
        numeric_value = raw.get(numeric_key)
        if isinstance(numeric_value, (int, float)):
            anchor[numeric_key] = float(numeric_value)
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        anchor["notes"] = notes.strip()
    return anchor

def _sanitize_connection_semantics_contract(raw: Any, *, valid_component_ids: set[str]) -> Dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    mechanism = _sanitize_frozen_connection_mechanism(raw.get("connection_mechanism"))
    relation_type = raw.get("relation_type")
    reference_component_id = raw.get("reference_component_id")
    moving_component_id = raw.get("moving_component_id")
    reference_interface_hint = raw.get("reference_interface_hint")
    moving_interface_hint = raw.get("moving_interface_hint")
    assembly_reference_interface_hint = raw.get("assembly_reference_interface_hint")
    assembly_moving_interface_hint = raw.get("assembly_moving_interface_hint")
    orientation_policy = raw.get("orientation_policy")
    geometric_semantics = _sanitize_connection_geometric_semantics(raw.get("geometric_semantics"))
    if geometric_semantics is None or not _connection_geometric_semantics_is_specific(geometric_semantics, mechanism=mechanism):
        inferred_geometric_semantics = _infer_connection_geometric_semantics_from_contract(raw)
        if inferred_geometric_semantics is not None:
            geometric_semantics = inferred_geometric_semantics
    if not mechanism:
        return None
    if not isinstance(relation_type, str) or not relation_type.strip():
        return None
    if not isinstance(reference_component_id, str) or reference_component_id not in valid_component_ids:
        return None
    if not isinstance(moving_component_id, str) or moving_component_id not in valid_component_ids:
        return None
    if not isinstance(reference_interface_hint, str) or not reference_interface_hint.strip():
        return None
    if not isinstance(moving_interface_hint, str) or not moving_interface_hint.strip():
        return None
    if not isinstance(orientation_policy, str) or not orientation_policy.strip():
        return None
    if geometric_semantics is None:
        return None
    reference_anchor = _sanitize_connection_anchor_contract(raw.get("reference_anchor"))
    moving_anchor = _sanitize_connection_anchor_contract(raw.get("moving_anchor"))
    if reference_anchor is None or moving_anchor is None:
        return None
    normalized: Dict[str, Any] = {
        "connection_mechanism": mechanism,
        "relation_type": relation_type.strip().lower(),
        "reference_component_id": reference_component_id,
        "moving_component_id": moving_component_id,
        "reference_anchor": reference_anchor,
        "moving_anchor": moving_anchor,
        "reference_interface_hint": reference_interface_hint.strip(),
        "moving_interface_hint": moving_interface_hint.strip(),
        "orientation_policy": orientation_policy.strip().lower(),
        "geometric_semantics": geometric_semantics,
    }
    if isinstance(assembly_reference_interface_hint, str) and assembly_reference_interface_hint.strip():
        normalized["assembly_reference_interface_hint"] = assembly_reference_interface_hint.strip()
    if isinstance(assembly_moving_interface_hint, str) and assembly_moving_interface_hint.strip():
        normalized["assembly_moving_interface_hint"] = assembly_moving_interface_hint.strip()
    rationale = raw.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        normalized["rationale"] = rationale.strip()
    confidence = raw.get("confidence")
    if isinstance(confidence, (int, float)):
        normalized["confidence"] = float(confidence)
    return normalized

def _purpose_requires_explicit_connection_semantics(purpose: str | None) -> bool:
    return _normalize_purpose(purpose) in _CONNECTION_PURPOSES_REQUIRING_EXPLICIT_SEMANTICS

def _normalize_fastener_bundle_semantics(payload: Dict[str, Any]) -> None:
    """Normalize fastener-family components into structured 'fastener' bundles.

    - Converts legacy component types ('fastener_set'/'bolt_set') to type='fastener'
    - Ensures a fastener bundle has nominal_diameter/length/count
    - Emits engineering semantics: fastener_instances[] + pattern{}

    This keeps downstream planning anchored in semantics (M-size, count, pattern)
    even if execution models them as simple cylinders/discs.
    """

    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue

        raw_type = comp.get("type")
        comp_type = str(raw_type).strip().lower() if isinstance(raw_type, str) else ""
        if comp_type in {"fastener_set", "bolt_set"}:
            comp["type"] = "fastener"
            comp_type = "fastener"

        if comp_type != "fastener":
            continue

        dims = comp.get("dimensions")
        if not isinstance(dims, Mapping):
            dims = {}
            comp["dimensions"] = dims
        dims = dict(dims)

        params = comp.get("parameters")
        if not isinstance(params, Mapping):
            params = {}
            comp["parameters"] = params
        params = dict(params)

        def _num(v: Any) -> float | None:
            return float(v) if isinstance(v, (int, float)) else None

        nominal = _num(dims.get("nominal_diameter")) or _num(dims.get("diameter"))
        if nominal is None:
            nominal = _num(params.get("nominal_diameter")) or _num(params.get("diameter"))
        length = _num(dims.get("length"))
        if length is None:
            length = _num(params.get("length"))
        count_value = dims.get("count")
        if not isinstance(count_value, (int, float)):
            count_value = params.get("count")
        count = int(count_value) if isinstance(count_value, (int, float)) else None

        if nominal is None:
            nominal = 4.0
        if length is None:
            length = max(8.0, round(float(nominal) * 3.0, 2))
        if count is None or count < 1:
            count = 1

        dims.setdefault("nominal_diameter", float(nominal))
        dims.setdefault("length", float(length))
        dims.setdefault("count", int(count))
        params.setdefault("nominal_diameter", float(nominal))
        params.setdefault("length", float(length))
        params.setdefault("count", int(count))

        role_value = comp.get("role")
        role = role_value.lower().strip() if isinstance(role_value, str) else ""
        bundle_style_raw = params.get("bundle_style") if "bundle_style" in params else dims.get("bundle_style")
        bundle_style = bundle_style_raw.lower().strip() if isinstance(bundle_style_raw, str) else ""
        is_nut_only = role in {"axle_retention", "axial_retention"} or bundle_style == "nut_only"

        if is_nut_only:
            if int(count) > 1:
                warnings_list = comp.get("normalization_warnings")
                if not isinstance(warnings_list, list):
                    warnings_list = []
                    comp["normalization_warnings"] = warnings_list
                warnings_list.append(
                    {
                        "code": "nut_only_count_clamped_to_one",
                        "from": int(count),
                        "to": 1,
                        "reason": "axial_retention/nut_only must not generate bolt-circle bundles",
                    }
                )
            count = 1
            dims["count"] = 1
            params["count"] = 1
            params.setdefault("bundle_style", "nut_only")
            params.setdefault("application", "axial_retention")
            dims.setdefault("bundle_style", "nut_only")
            dims.setdefault("application", "axial_retention")

        comp["dimensions"] = dims
        comp["parameters"] = params

        designation = _nearest_fastener_designation(float(nominal), float(length))
        nominal_mm = float(nominal)
        m_size = int(round(nominal_mm))

        if is_nut_only:
            comp["fastener_instances"] = [
                {
                    "kind": "nut",
                    "designation": f"M{m_size}",
                    "quantity": 1,
                    "nominal_diameter_mm": nominal_mm,
                },
                {
                    "kind": "washer",
                    "designation": f"M{m_size}",
                    "quantity": 1,
                    "nominal_diameter_mm": nominal_mm,
                    "notes": "retention washer",
                },
            ]
            hole_d = round(float(nominal) + 0.5, 2)
            comp["pattern"] = {
                "type": "single",
                "count": 1,
                "phase_deg": 0.0,
                "hole_diameter_mm": float(hole_d),
                "notes": "axial retention; no bolt circle",
            }
            continue

        if not isinstance(comp.get("fastener_instances"), list):
            comp["fastener_instances"] = [
                {
                    "kind": "bolt",
                    "designation": designation,
                    "quantity": int(count),
                    "nominal_diameter_mm": nominal_mm,
                    "length_mm": float(length),
                },
                {
                    "kind": "nut",
                    "designation": f"M{m_size}",
                    "quantity": int(count),
                    "nominal_diameter_mm": nominal_mm,
                },
                {
                    "kind": "washer",
                    "designation": f"M{m_size}",
                    "quantity": int(count),
                    "nominal_diameter_mm": nominal_mm,
                    "notes": "Simplest semantic washer; may be modeled as a flat disc.",
                },
            ]

        if not isinstance(comp.get("pattern"), Mapping):
            hole_d = round(float(nominal) + 0.5, 2)
            comp["pattern"] = {
                "type": "bolt_circle" if int(count) > 1 else "single",
                "count": int(count),
                "phase_deg": 0.0,
                "hole_diameter_mm": float(hole_d),
                "notes": "PCD intentionally unspecified in Agent1; downstream may infer feasible placement.",
            }

def _derive_constraint_contract(purpose: str) -> tuple[str, Dict[str, str], list[str]]:
    purpose_key = _normalize_purpose(purpose)
    mapping: Dict[str, tuple[str, Dict[str, str], list[str]]] = {
        "rotation": ("revolute", {"translation": "locked", "rotation": "free"}, ["axis", "seat"]),
        "torque_transfer": ("revolute", {"translation": "locked", "rotation": "limited"}, ["axis", "keyway", "bore"]),
        "structural_fixation": ("rigid", {"translation": "locked", "rotation": "locked"}, ["planar_face", "mount_hole"]),
        "structural_clamping": ("clamping", {"translation": "locked", "rotation": "locked"}, ["clamp_face", "through_hole"]),
        "fastening_mechanism": ("fastened", {"translation": "locked", "rotation": "locked"}, ["through_hole", "thread_feature"]),
        "support_to_structure": ("support", {"translation": "limited", "rotation": "free"}, ["support_face", "seat"]),
        "load_support": ("support", {"translation": "limited", "rotation": "free"}, ["support_face", "contact_surface"]),
        "alignment": ("alignment", {"translation": "limited", "rotation": "limited"}, ["axis", "datum_plane"]),
        "spacing": ("spacing", {"translation": "limited", "rotation": "free"}, ["spacer_face", "datum_plane"]),
    }
    return mapping.get(
        purpose_key,
        ("custom", {"translation": "limited", "rotation": "limited"}, ["generic_interface"]),
    )

def _normalize_connection_contract_fields(kg: Dict[str, Any]) -> None:
    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        purpose = str(cr.get("purpose", ""))
        intent, dof, mating_features = _derive_constraint_contract(purpose)
        if not isinstance(cr.get("constraint_intent"), str) or not str(cr.get("constraint_intent", "")).strip():
            cr["constraint_intent"] = intent
        existing_dof = cr.get("dof")
        if not isinstance(existing_dof, Mapping):
            cr["dof"] = dict(dof)
        else:
            cr["dof"] = {
                "translation": str(existing_dof.get("translation", dof["translation"])),
                "rotation": str(existing_dof.get("rotation", dof["rotation"])),
                **({"notes": existing_dof.get("notes")} if isinstance(existing_dof.get("notes"), str) else {}),
            }
        existing_features = cr.get("mating_features")
        if isinstance(existing_features, list) and any(isinstance(item, str) and item.strip() for item in existing_features):
            cr["mating_features"] = [str(item).strip() for item in existing_features if isinstance(item, str) and str(item).strip()]
        else:
            cr["mating_features"] = list(mating_features)

def _normalize_connection_requirements(kg: Dict[str, Any]) -> None:
    """Normalize purpose/roles in connection_requirements and fill missing roles."""
    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    components = kg.get("components", [])
    type_by_id = _build_type_map(components) if isinstance(components, list) else {}
    generic_fastener_purposes = {"structural_fixation", "connection", "attachment"}

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        purpose = _normalize_purpose(cr.get("purpose"))
        between = cr.get("between")
        between_ids = [cid for cid in between if isinstance(cid, str) and cid] if isinstance(between, list) else []
        has_direct_fastener = any(_is_fastener_family_type(type_by_id.get(cid)) for cid in between_ids)
        if has_direct_fastener and purpose in generic_fastener_purposes:
            purpose = "fastening_mechanism"
        if purpose:
            cr["purpose"] = purpose

        roles_raw = None
        if isinstance(cr.get("roles"), list):
            roles_raw = cr.get("roles")
        elif isinstance(cr.get("role"), str):
            roles_raw = [cr.get("role")]

        roles: list[str] = []
        if roles_raw:
            for role in roles_raw:
                if isinstance(role, str) and role.strip():
                    roles.append(role.strip().lower())

        if not roles:
            roles = _derive_roles_from_purpose(purpose)

        # Normalize order and remove duplicates
        cr["roles"] = sorted(set(roles))

        existing_semantics = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )
        if isinstance(existing_semantics, dict):
            cr["connection_semantics"] = existing_semantics
        else:
            cr.pop("connection_semantics", None)

    _normalize_connection_contract_fields(kg)

def _validate_fastener_usage(kg: Dict[str, Any]) -> None:
    """Validate that every fastener component appears in at least one connection_requirement.
    
    Fasteners are NEVER isolated; they must be central elements of connection requirements.
    
    This validation allows two patterns:
    1. Fastener appears directly in connection_requirement (explicit connection)
    2. Fastener is in subassembly, and subassembly appears in connection_requirement (implicit via grouping)
    
    Both patterns are valid and serve different purposes.
    """
    fasteners = [c["id"] for c in kg.get("components", []) if c.get("type") == "fastener"]
    
    if not fasteners:
        return  # No fasteners, nothing to validate
    
    # Check that every fastener appears in at least one connection_requirement
    # Either directly OR via its parent subassembly OR referenced by connection_decision
    used_directly = set()
    used_via_subassembly = set()
    used_via_decision = set()
    
    # Track direct usage
    for cr in kg.get("connection_requirements", []):
      for cid in cr.get("between", []):
        if cid in fasteners:
          used_directly.add(cid)
      decision = cr.get("connection_decision") if isinstance(cr, Mapping) else None
      if isinstance(decision, Mapping):
        ref_id = decision.get("fastener_ref_component_id")
        if isinstance(ref_id, str) and ref_id in fasteners:
          used_via_decision.add(ref_id)
    
    # Track usage via subassembly
    subassemblies = kg.get("subassemblies", [])
    if isinstance(subassemblies, list):
        # Build map: fastener_id -> subassembly_id
        fastener_to_subassembly = {}
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            component_ids = sa.get("component_ids", [])
            if not isinstance(component_ids, list):
                continue
            for cid in component_ids:
                if isinstance(cid, str) and cid in fasteners:
                    fastener_to_subassembly[cid] = sa_id
        
        # Check if parent subassemblies appear in requirements
        for cr in kg.get("connection_requirements", []):
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            between_set = set([cid for cid in between if isinstance(cid, str)])
            
            for fastener_id, parent_sa_id in fastener_to_subassembly.items():
                if parent_sa_id in between_set:
                    used_via_subassembly.add(fastener_id)
    
    # A fastener is valid if it's used either directly OR via subassembly
    used = used_directly | used_via_subassembly | used_via_decision
    unused = set(fasteners) - used
    
    if unused:
        raise ValueError(
            f"Validation failed: Fasteners must appear in connection_requirements. "
            f"Unused fasteners: {sorted(unused)}. "
            f"Every fastener component MUST be a central element of at least one connection_requirement "
          f"(either directly, via its parent subassembly, or via connection_decision.fastener_ref_component_id)."
        )

def _validate_subassembly_connectivity(kg: Dict[str, Any]) -> None:
    """Validate subassemblies are semantic hubs, not redundant or overreaching.

    Each subassembly MUST appear in at least one connection_requirement as a hub.
    Subassemblies MUST NOT connect to components they don't directly bind.
    """
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list) or not subassemblies:
        return

    used_ids: set[str] = set()
    for cr in kg.get("connection_requirements", []) or []:
        for cid in cr.get("between", []) if isinstance(cr, Mapping) else []:
            if isinstance(cid, str):
                used_ids.add(cid)

    for cr in kg.get("connection_requirements", []) or []:
        between = cr.get("between", []) if isinstance(cr, Mapping) else []
        if not isinstance(between, list):
            continue
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            component_ids = sa.get("component_ids", [])
            if not isinstance(component_ids, list):
                continue
            if sa_id in between and any(cid in between for cid in component_ids):
                member_ids_in_req = [cid for cid in component_ids if cid in between]
                raise ValueError(
                    f"Validation failed: Subassembly '{sa_id}' and its members {member_ids_in_req} appear together in connection_requirement.\n"
                    f"A subassembly represents its members collectively. Do NOT list both the subassembly and its internal components in the same requirement.\n"
                    f"Example (WRONG): {{'between': ['{sa_id}', '{member_ids_in_req[0]}', 'external_comp'], ...}}\n"
                    f"Example (CORRECT): {{'between': ['{sa_id}', 'external_comp'], ...}}"
                )

    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        component_ids = sa.get("component_ids", [])
        
        # Skip validation if subassembly has only 1 component (single-member subassemblies are OK without hub usage)
        if not isinstance(component_ids, list) or len(component_ids) <= 1:
            continue
        
        # Check if subassembly itself appears in a connection_requirement
        if isinstance(sa_id, str) and sa_id in used_ids:
            continue
        
        # Alternative: Check if all members appear in connection_requirements (direct usage pattern)
        # This allows two patterns:
        # Pattern A: Subassembly as hub (semantic grouping)
        # Pattern B: Members used directly (engineering explicit)
        members_used = sum(1 for cid in component_ids if isinstance(cid, str) and cid in used_ids)
        
        # If majority of members are directly used in requirements, that's OK (Pattern B)
        if members_used >= len(component_ids) * 0.5:  # At least 50% of members used
            continue
        
        # Otherwise, subassembly is floating (neither hub nor direct member usage)
        raise ValueError(
            "Validation failed: Subassembly is semantically floating. "
            f"Subassembly '{sa_id}' (with {len(component_ids)} components) must either:\n"
            f"  A) Appear as a hub in connection_requirement, OR\n"
            f"  B) Have its members directly used in connection_requirements.\n"
            f"Currently: subassembly not used as hub, and only {members_used}/{len(component_ids)} members appear in requirements."
        )

    # Check for subassembly semantic overreach
    for cr in kg.get("connection_requirements", []) or []:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        if not isinstance(between, list):
            continue
        between_ids = {cid for cid in between if isinstance(cid, str)}
        
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            component_ids = sa.get("component_ids", [])
            if not isinstance(component_ids, list):
                continue
            member_set = set(component_ids)
            
            # If subassembly appears with external components not in its member list
            if sa_id in between_ids:
                external_ids = between_ids - {sa_id} - member_set
                # Check if any members already connect to those external components
                for ext_id in external_ids:
                    for other_cr in kg.get("connection_requirements", []) or []:
                        if not isinstance(other_cr, Mapping):
                            continue
                        if other_cr.get("id") == cr.get("id"):
                            continue
                        other_between = other_cr.get("between", [])
                        if not isinstance(other_between, list):
                            continue
                        other_set = {cid for cid in other_between if isinstance(cid, str)}
                        if ext_id in other_set and member_set & other_set:
                            raise ValueError(
                                f"Semantic overreach: subassembly '{sa_id}' connects to '{ext_id}', but its members "
                                f"already connect to '{ext_id}'. Remove the redundant subassembly connection."
                            )

def _validate_clamping_subassembly_has_fasteners(kg: Dict[str, Any]) -> None:
    """Validate that clamping/fixation subassemblies include fastener components."""
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list):
        return
    
    components = kg.get("components", [])
    if not isinstance(components, list):
        return
    
    # Build type map
    type_by_id = _build_type_map(components)
    
    # Check each clamping subassembly
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        role = sa.get("role", "")
        component_ids = sa.get("component_ids", [])
        
        if not isinstance(sa_id, str) or not isinstance(component_ids, list):
            continue
        
        # If subassembly has clamping/fixation role
        clamping_roles = {"structural_clamping", "fixation", "binding", "clamping"}
        if role in clamping_roles:
            # Check if any component is a fastener
            has_fastener = any(
                _is_fastener_family_type(type_by_id.get(cid))
                for cid in component_ids
            )
            
            if not has_fastener:
                raise ValueError(
                    f"Validation failed: Subassembly '{sa_id}' has role '{role}' but does NOT include any fastener component. "
                    f"Clamping/fixation subassemblies MUST include the fasteners that realize the clamping. "
                    f"Add a fastener component to component_ids: {component_ids}"
                )

def _validate_fastener_purpose_specificity(kg: Dict[str, Any]) -> None:
    """Validate that connections with fasteners use engineering-specific purpose vocabulary."""
    components = kg.get("components", [])
    if not isinstance(components, list):
        return
    
    # Build type map
    type_by_id = _build_type_map(components)
    
    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return
    
    # Check each connection requirement
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        
        cr_id = cr.get("id", "unknown")
        between = cr.get("between", [])
        purpose = _normalize_purpose(cr.get("purpose", ""))
        
        if not isinstance(between, list) or not isinstance(purpose, str):
            continue
        
        # Check if any component in "between" is a fastener
        has_fastener = any(
            _is_fastener_family_type(type_by_id.get(cid))
            for cid in between
            if isinstance(cid, str)
        )
        
        if has_fastener:
            # Define generic purposes that are NOT allowed with fasteners
            generic_purposes = {
              "structural_fixation",  # Too generic
              "connection",            # Too vague
              "attachment"             # Too vague
            }
            
            # Define acceptable specific purposes
            specific_purposes = {
              "fastening_mechanism",
              "structural_clamping",
              "load_transfer_via_fastener"
            }
            
            if purpose in generic_purposes:
                raise ValueError(
                    f"Validation failed: connection_requirement '{cr_id}' includes a fastener but uses generic purpose '{purpose}'. "
                    f"When fasteners are present, purpose MUST be engineering-specific. "
                    f"Use one of: {', '.join(specific_purposes)}. "
                    f"Generic purposes like '{purpose}' do not reflect the physical implementation mechanism."
                )

def _validate_bearing_and_shaft_completeness(kg: Dict[str, Any]) -> None:
    """Validate bearing/shaft completeness and role separation rules.
    
    Bearing support hierarchy:
    - Direct support: bearing appears directly in connection_requirement with purpose 'support_to_structure'
    - Indirect support: bearing is member of a subassembly that appears in connection_requirement with purpose 'support_to_structure'
    
    Both patterns satisfy the support requirement - bearing does not need to repeat the connection.
    """
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id = _build_type_map(components)

    bearing_ids = {cid for cid, ctype in type_by_id.items() if ctype == "bearing"}
    shaft_ids = {cid for cid, ctype in type_by_id.items() if ctype in {"shaft", "axle"}}
    wheel_ids = {cid for cid, ctype in type_by_id.items() if ctype == "wheel"}
    
    # Build map of bearing membership in subassemblies
    bearing_to_subassemblies: dict[str, set[str]] = {bid: set() for bid in bearing_ids}
    subassemblies = kg.get("subassemblies", []) or []
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        members = sa.get("component_ids", [])
        if isinstance(members, list) and isinstance(sa_id, str):
            for bid in bearing_ids & set(members):
                bearing_to_subassemblies[bid].add(sa_id)

    crs = kg.get("connection_requirements", []) or []
    if not isinstance(crs, list):
        return

    bearing_purposes: dict[str, set[str]] = {bid: set() for bid in bearing_ids}
    shaft_purposes: dict[str, set[str]] = {sid: set() for sid in shaft_ids}

    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        if not isinstance(between, list):
            continue
        purpose = _normalize_purpose(cr.get("purpose") if isinstance(cr.get("purpose"), str) else "")
        between_ids = {cid for cid in between if isinstance(cid, str)}

        # Role separation: do not bundle wheel + bearing + shaft in one requirement
        if (
            between_ids & wheel_ids
            and between_ids & bearing_ids
            and between_ids & shaft_ids
        ):
            raise ValueError(
                "Validation failed: connection_requirement bundles wheel, bearing, and shaft. "
                "Split into separate requirements for rotation and load support."
            )

        for bid in between_ids & bearing_ids:
            if purpose:
                bearing_purposes[bid].add(purpose)
        
        # Also record purposes for bearings whose subassembly is in this connection
        for sa_id in between_ids:
            for bid in bearing_ids:
                if sa_id in bearing_to_subassemblies[bid]:
                    if purpose:
                        bearing_purposes[bid].add(purpose)
        
        for sid in between_ids & shaft_ids:
            if purpose:
                shaft_purposes[sid].add(purpose)

    for bid, purposes in bearing_purposes.items():
        if "load_support" not in purposes:
            raise ValueError(
                "Validation failed: Bearing is missing load_support connection. "
                f"Bearing '{bid}' must appear in a connection_requirement with purpose 'load_support' "
                f"(directly or via subassembly)."
            )
        if "support_to_structure" not in purposes:
            raise ValueError(
                "Validation failed: Bearing is missing support_to_structure connection. "
                f"Bearing '{bid}' must appear in a connection_requirement with purpose 'support_to_structure' "
                f"(directly or via subassembly)."
            )

    for sid, purposes in shaft_purposes.items():
        if not ("rotation" in purposes or "torque_transfer" in purposes):
            raise ValueError(
                "Validation failed: Shaft is missing rotation/torque_transfer connection. "
                f"Shaft '{sid}' must appear in a connection_requirement with purpose 'rotation' or 'torque_transfer'."
            )
        if "structural_fixation" not in purposes:
            raise ValueError(
                "Validation failed: Shaft is missing structural_fixation connection. "
                f"Shaft '{sid}' must appear in a connection_requirement with purpose 'structural_fixation'."
            )

def _sanitize_fastener_bundles(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return
    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id")
    }

    def _to_int(v: Any) -> int | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return int(v)
        return None

    group_stats: Dict[str, Dict[str, Any]] = {}
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        cr_id = cr.get("id") if isinstance(cr.get("id"), str) else ""
        if not cr_id:
            continue
        base_id = cr_id.split("@", 1)[0]
        stem = re.sub(r"_\d+$", "", base_id)
        if stem != "hub_to_arm":
            continue
        purpose = _normalize_purpose(cr.get("purpose") if isinstance(cr.get("purpose"), str) else "")
        if purpose not in {"fastening_mechanism", "structural_fixation"}:
            continue
        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else {}
        if str(decision.get("method") or "") != "bolted_rigid":
            continue
        between = cr.get("between") if isinstance(cr.get("between"), list) else []
        fasteners = [
            cid
            for cid in between
            if isinstance(cid, str) and _is_fastener_family_type(comp_by_id.get(cid, {}).get("type"))
        ]
        if not fasteners:
            continue
        stat = group_stats.setdefault(stem, {"bases": set(), "fastener_ids": set()})
        stat["bases"].add(base_id)
        stat["fastener_ids"].update(fasteners)

    for stem, stat in group_stats.items():
        bases = stat.get("bases") if isinstance(stat.get("bases"), set) else set()
        fastener_ids = stat.get("fastener_ids") if isinstance(stat.get("fastener_ids"), set) else set()
        symmetry_count = len(bases)
        if symmetry_count < 3:
            continue
        if len(fastener_ids) < symmetry_count:
            continue

        for fid in sorted(fastener_ids):
            comp = comp_by_id.get(fid)
            if not isinstance(comp, dict):
                continue
            dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
            params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
            count = _to_int(dims.get("count"))
            if count is None:
                count = _to_int(params.get("count"))
            if count != symmetry_count:
                continue

            dims = dict(dims)
            params = dict(params)
            dims["count"] = 2
            params["count"] = 2
            params["count_rationale"] = "symmetry_count!=fastener_count; adjusted deterministically"

            nominal = dims.get("nominal_diameter")
            if not isinstance(nominal, (int, float)):
                nominal = dims.get("diameter")
            nominal_v = float(nominal) if isinstance(nominal, (int, float)) else 4.0
            hole_d = round(nominal_v + 0.5, 2)

            pattern = comp.get("pattern") if isinstance(comp.get("pattern"), Mapping) else {}
            pattern = dict(pattern)
            pattern["type"] = "unknown"
            pattern["count"] = 2
            pattern["hole_diameter_mm"] = float(pattern.get("hole_diameter_mm")) if isinstance(pattern.get("hole_diameter_mm"), (int, float)) else float(hole_d)
            notes_old = pattern.get("notes") if isinstance(pattern.get("notes"), str) else ""
            note_suffix = "symmetry_count!=fastener_count; adjusted deterministically"
            pattern["notes"] = f"{notes_old}; {note_suffix}" if notes_old else note_suffix

            instances = comp.get("fastener_instances")
            if isinstance(instances, list):
                for inst in instances:
                    if isinstance(inst, dict) and isinstance(inst.get("quantity"), int):
                        inst["quantity"] = 2

            comp["dimensions"] = dims
            comp["parameters"] = params
            comp["pattern"] = pattern

def _build_subassembly_members(kg: Dict[str, Any]) -> dict[str, list[str]]:
    """Return mapping from subassembly id to its string component_ids."""
    subassemblies = kg.get("subassemblies", []) or []
    result: dict[str, list[str]] = {}
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            members = sa.get("component_ids", [])
            if isinstance(sa_id, str) and isinstance(members, list):
                result[sa_id] = [m for m in members if isinstance(m, str)]
    return result

def _has_fastener_involved(
    between_ids: list[str],
    type_by_id: dict[str, str],
    subassembly_members: dict[str, list[str]],
) -> bool:
    """Return True only when a fastener is directly named in the relation."""
    del subassembly_members
    return any(_is_fastener_family_type(type_by_id.get(cid)) for cid in between_ids)

def _purpose_requires_decision(purpose: str | None) -> bool:
    """Return True only for explicit fastening/clamping decisions."""
    purpose_norm = _normalize_purpose(purpose)
    return purpose_norm in {
        "fastening_mechanism",
        "structural_clamping",
    }

def _validate_connection_semantics_contracts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = {str(comp.get("id")): str(comp.get("type") or "").strip().lower() for comp in components if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)}

    missing_ids: list[str] = []
    generic_ids: list[str] = []
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        cr_id = cr.get("id") if isinstance(cr.get("id"), str) else "<unknown_connection>"
        between = cr.get("between")
        between_ids = [cid for cid in between if isinstance(cid, str) and cid] if isinstance(between, list) else []
        purpose = cr.get("purpose") if isinstance(cr.get("purpose"), str) else None
        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
        requires_semantics = _purpose_requires_explicit_connection_semantics(purpose) or isinstance(decision, Mapping)
        if not requires_semantics:
            continue
        contract = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )
        if contract is None:
            missing_ids.append(cr_id)
            continue
        if contract.get("connection_mechanism") == "generic_mount":
            generic_ids.append(f"{cr_id}:generic_mount")
        if _is_generic_connection_relation_type(contract.get("relation_type")):
            generic_ids.append(f"{cr_id}:generic_relation_type")
        if not _connection_geometric_semantics_is_specific(contract.get("geometric_semantics"), mechanism=str(contract.get("connection_mechanism") or "")):
            generic_ids.append(f"{cr_id}:underspecified_geometric_semantics")
        ref_hint = str(contract.get("reference_interface_hint") or "").strip().lower()
        mov_hint = str(contract.get("moving_interface_hint") or "").strip().lower()
        if ref_hint in _GENERIC_INTERFACE_HINTS or mov_hint in _GENERIC_INTERFACE_HINTS:
            generic_ids.append(f"{cr_id}:generic_interface_hint")
        type_set = {type_by_id.get(cid, "") for cid in between_ids if type_by_id.get(cid, "")}
        mechanism_name = str(contract.get("connection_mechanism") or "").strip().lower()
        geometric_semantics = contract.get("geometric_semantics") if isinstance(contract.get("geometric_semantics"), Mapping) else {}
        anti_rotation_topology = str(geometric_semantics.get("anti_rotation_topology") or "").strip().lower()
        if (
            "hub" in type_set
            and "arm" in type_set
            and str(purpose or "").strip().lower() in {"structural_fixation", "structural_clamping", "fastening_mechanism"}
            and mechanism_name in {"bolted_mount", "radial_member_bolted_mount", "axial_face_bolted_mount"}
            and anti_rotation_topology in _GENERIC_GEOMETRIC_SEMANTIC_VALUES.union({""})
        ):
            generic_ids.append(f"{cr_id}:missing_anti_rotation_topology")
    if missing_ids or generic_ids:
        details: list[str] = []
        if missing_ids:
            details.append("missing=" + ", ".join(sorted(missing_ids)))
        if generic_ids:
            details.append("generic=" + ", ".join(sorted(generic_ids)))
        audit = payload.get("agent1_connection_semantics_audit")
        if isinstance(audit, Mapping):
            requested = audit.get("requested_connection_ids")
            resolved = audit.get("resolved_connection_ids")
            missing_after_single = audit.get("missing_after_single")
            if isinstance(requested, list):
                details.append(f"audit_requested={len(requested)}")
            if isinstance(resolved, list):
                details.append(f"audit_resolved={len(resolved)}")
            if isinstance(missing_after_single, list):
                details.append("audit_missing_after_single=" + ", ".join(sorted(str(x) for x in missing_after_single)))
        raise ValueError("Missing explicit connection_semantics for mechanically resolved relations: " + " | ".join(details))

def _validate_connection_decisions(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id = _build_type_map(components)
    subassembly_members = _build_subassembly_members(kg)

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        cr_id = cr.get("id", "unknown")
        between = cr.get("between", [])
        between_ids = [cid for cid in between if isinstance(cid, str)]
        purpose = cr.get("purpose") if isinstance(cr.get("purpose"), str) else ""

        requires_decision = _has_fastener_involved(between_ids, type_by_id, subassembly_members) or _purpose_requires_decision(purpose)
        contract = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=set(between_ids),
        )

        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
        if requires_decision and not decision and contract is None:
            raise ValueError(
            "Missing connection_decision for connection_requirement "
            f"'{cr_id}' (between={between_ids}). "
            "Fastener detected or fastening purpose; auto-fill should have run."
            )

        if not decision:
            continue

        ref_id = decision.get("fastener_ref_component_id")
        if ref_id is not None:
            if not isinstance(ref_id, str) or not _is_fastener_family_type(type_by_id.get(ref_id)):
                raise ValueError(
                    "Invalid fastener_ref_component_id in connection_requirement "
                    f"'{cr_id}' (between={between_ids}). "
                    "Must reference a fastener-family component (fastener/bolt/nut/washer/pin/key...)."
                )

        method = decision.get("method")
        if isinstance(method, str) and method.startswith("bolted"):
            count = decision.get("count")
            if count is not None and (not isinstance(count, int) or count < 1):
                raise ValueError(
                    "Invalid bolted connection_decision.count in connection_requirement "
                    f"'{cr_id}' (between={between_ids})."
                )
            has_size = isinstance(decision.get("fastener_size"), str)
            has_ref = isinstance(decision.get("fastener_ref_component_id"), str)
            if not (has_size or has_ref):
                raise ValueError(
                    "Missing fastener_size or fastener_ref_component_id for bolted connection_requirement "
                    f"'{cr_id}' (between={between_ids})."
                )

def _autofill_missing_connection_decisions(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id: dict[str, str] = {}
    component_by_id: dict[str, Mapping] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and isinstance(ctype, str):
            type_by_id[cid] = ctype
            component_by_id[cid] = comp

    subassembly_members = _build_subassembly_members(kg)

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    fastener_usage: dict[str, list[str]] = {}
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        between_ids = [cid for cid in between if isinstance(cid, str)]
        connection_id = cr.get("id") if isinstance(cr.get("id"), str) else None
        local_fasteners: set[str] = set()
        for cid in between_ids:
            if _is_fastener_family_type(type_by_id.get(cid)):
                local_fasteners.add(cid)
                continue
            for mid in subassembly_members.get(cid, []):
                if _is_fastener_family_type(type_by_id.get(mid)):
                    local_fasteners.add(mid)
        for fastener_id in local_fasteners:
            usage_ids = fastener_usage.setdefault(fastener_id, [])
            if isinstance(connection_id, str) and connection_id not in usage_ids:
                usage_ids.append(connection_id)

    shared_fastener_hints: list[dict[str, Any]] = []

    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
        if decision:
            continue

        between = cr.get("between", [])
        between_ids = [cid for cid in between if isinstance(cid, str)]
        purpose = cr.get("purpose") if isinstance(cr.get("purpose"), str) else ""

        requires_decision = _has_fastener_involved(between_ids, type_by_id, subassembly_members) or _purpose_requires_decision(purpose)
        if not requires_decision:
            continue

        fastener_id: str | None = None
        for cid in between_ids:
            if _is_fastener_family_type(type_by_id.get(cid)):
                fastener_id = cid
                break

        if fastener_id is None:
            for cid in between_ids:
                members = subassembly_members.get(cid, [])
                for mid in members:
                    if _is_fastener_family_type(type_by_id.get(mid)):
                        fastener_id = mid
                        break
                if fastener_id:
                    break

        count: int | None = None
        fastener_size: str | None = None
        inventory_quantity_hint: int | None = None
        if fastener_id:
            comp = component_by_id.get(fastener_id, {})
            dims = comp.get("dimensions") if isinstance(comp, Mapping) else None
            params = comp.get("parameters") if isinstance(comp, Mapping) else None

            if isinstance(dims, Mapping):
                count_value = dims.get("count")
                if isinstance(count_value, int):
                    count = count_value
                    inventory_quantity_hint = count_value
                size_value = dims.get("fastener_size")
                if isinstance(size_value, str):
                    fastener_size = size_value
                if fastener_size is None:
                    nominal = dims.get("nominal_diameter")
                    length = dims.get("length")
                    if isinstance(nominal, (int, float)) and isinstance(length, (int, float)):
                        fastener_size = _nearest_fastener_designation(float(nominal), float(length))
                    elif isinstance(nominal, (int, float)):
                        fastener_size = f"M{int(round(nominal))}"

            if count is None and isinstance(params, Mapping):
                count_value = params.get("count")
                if isinstance(count_value, int):
                    count = count_value

        shared_usage_ids = fastener_usage.get(fastener_id, []) if isinstance(fastener_id, str) else []
        if isinstance(fastener_id, str) and len(shared_usage_ids) > 1:
            shared_fastener_hints.append({
                "fastener_component_id": fastener_id,
                "connection_ids": list(shared_usage_ids),
                "inventory_quantity_hint": inventory_quantity_hint,
                "count_policy": "defer_to_agent2",
            })
            count = None

        constraints = cr.get("constraints") if isinstance(cr.get("constraints"), Mapping) else {}
        purpose_norm = _normalize_purpose(purpose)
        non_fastener_types = [
            type_by_id.get(cid, "").strip().lower()
            for cid in between_ids
            if not _is_fastener_family_type(type_by_id.get(cid))
        ]
        is_axial_retention_autofill = (
            constraints.get("axial_preload") is True
            and purpose_norm in {"fastening_mechanism", "structural_clamping"}
            and any(t in {"axle", "shaft"} for t in non_fastener_types)
        )

        if is_axial_retention_autofill and isinstance(count, int) and count > 1:
            count = 1

        decision_payload: Dict[str, Any] = {
            "method": "bolted_rigid",
            "stackup": "unknown",
            "fit_policy": "unknown",
            "lock": True,
            "rationale": "Auto-filled by Agent1: fastener involved but LLM omitted connection_decision."
        }
        if isinstance(count, int) and count >= 1:
            decision_payload["count"] = count
        else:
            decision_payload["count_policy"] = "defer_to_agent2"
            decision_payload["rationale"] = (
                "Auto-filled by Agent1: fastener involved but LLM omitted connection_decision; "
                "mechanism kept generic; count deferred to Agent2 engineering rules."
            )
        if is_axial_retention_autofill:
            decision_payload["count"] = 1
            decision_payload.pop("count_policy", None)
            decision_payload["axial_retention"] = True
            decision_payload["rationale"] = "Auto-filled: axial retention on shaft; bolt circle forbidden; count forced to 1."
        if fastener_id:
            decision_payload["fastener_ref_component_id"] = fastener_id
        if fastener_size:
            decision_payload["fastener_size"] = fastener_size
        if "fastener_ref_component_id" not in decision_payload and "fastener_size" not in decision_payload:
          decision_payload["fastener_size"] = "M5"

        cr["connection_decision"] = decision_payload

    if shared_fastener_hints:
        deduped_hints: list[dict[str, Any]] = []
        seen_hint_keys: set[tuple[str, tuple[str, ...]]] = set()
        for hint in shared_fastener_hints:
            fastener_component_id = hint.get("fastener_component_id")
            connection_ids = tuple(sorted(cid for cid in hint.get("connection_ids", []) if isinstance(cid, str)))
            if not isinstance(fastener_component_id, str) or not connection_ids:
                continue
            key = (fastener_component_id, connection_ids)
            if key in seen_hint_keys:
                continue
            seen_hint_keys.add(key)
            deduped_hints.append({
                "fastener_component_id": fastener_component_id,
                "connection_ids": list(connection_ids),
                "inventory_quantity_hint": hint.get("inventory_quantity_hint"),
                "count_policy": "defer_to_agent2",
            })
        if deduped_hints:
            metadata = kg.get("metadata") if isinstance(kg.get("metadata"), dict) else {}
            existing = metadata.get("shared_fastener_pool_hints") if isinstance(metadata.get("shared_fastener_pool_hints"), list) else []
            existing.extend(deduped_hints)
            metadata["shared_fastener_pool_hints"] = existing
            kg["metadata"] = metadata

def _drop_agent1_autofilled_connection_decisions_when_semantics_present(payload: Dict[str, Any]) -> None:
    crs = payload.get("connection_requirements", [])
    if not isinstance(crs, list):
        return
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
        if not isinstance(decision, Mapping):
            continue
        between = cr.get("between") if isinstance(cr.get("between"), list) else []
        valid_ids = {cid for cid in between if isinstance(cid, str) and cid}
        contract = _sanitize_connection_semantics_contract(
            cr.get("connection_semantics"),
            valid_component_ids=valid_ids,
        )
        if contract is None:
            continue
        rationale = str(decision.get("rationale") or "").strip().lower()
        if "auto-filled" not in rationale and "autofilled" not in rationale:
            continue
        cr.pop("connection_decision", None)

def _populate_frozen_spec(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        components = []

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        crs = []

    frozen_components = [
        comp.get("id")
        for comp in components
        if isinstance(comp, Mapping)
        and comp.get("type") != "subassembly"
        and isinstance(comp.get("id"), str)
    ]

    frozen_connections = [
        cr.get("id")
        for cr in crs
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    ]

    frozen_payload: Dict[str, Any] = {
        "components": {},
        "connection_requirements": {},
        "standard_parts": {}
    }

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str) or comp.get("type") == "subassembly":
            continue
        frozen_payload["components"][comp_id] = {
            "shape_semantics": comp.get("shape_semantics"),
            "dimensions": comp.get("dimensions"),
            "part_kind": comp.get("part_kind"),
            "modeling_policy": comp.get("modeling_policy"),
        }
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        cr_id = cr.get("id")
        if not isinstance(cr_id, str):
            continue
        frozen_payload["connection_requirements"][cr_id] = {
            "between": cr.get("between"),
            "purpose": cr.get("purpose"),
            "roles": cr.get("roles"),
            "connection_decision": cr.get("connection_decision"),
            "connection_semantics": cr.get("connection_semantics"),
            "constraint_intent": cr.get("constraint_intent"),
            "dof": cr.get("dof"),
            "mating_features": cr.get("mating_features"),
        }

    std_parts = kg.get("standard_parts", [])
    if isinstance(std_parts, list):
        for part in std_parts:
            if not isinstance(part, Mapping):
                continue
            part_id = part.get("id")
            if not isinstance(part_id, str):
                continue
            frozen_payload["standard_parts"][part_id] = {
                "category": part.get("category"),
                "designation": part.get("designation"),
                "quantity": part.get("quantity"),
                "applied_to": part.get("applied_to"),
                "selection_rationale": part.get("selection_rationale")
            }

    frozen_json = json.dumps(frozen_payload, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(frozen_json.encode("utf-8")).hexdigest()

    kg["frozen_spec"] = {
        "frozen_fields": [
            "/components/*/dimensions",
            "/components/*/shape_semantics",
            "/components/*/part_kind",
            "/components/*/modeling_policy",
            "/connection_requirements/*/between",
            "/connection_requirements/*/purpose",
            "/connection_requirements/*/roles",
            "/connection_requirements/*/connection_decision",
            "/connection_requirements/*/connection_semantics",
            "/connection_requirements/*/constraint_intent",
            "/connection_requirements/*/dof",
            "/connection_requirements/*/mating_features",
            "/standard_parts/*/designation",
            "/standard_parts/*/quantity",
            "/standard_parts/*/applied_to"
        ],
        "frozen_components": frozen_components,
        "frozen_connections": frozen_connections,
        "frozen_checksum": checksum,
        "notes": "Auto-generated frozen spec for downstream immutability checks"
    }

def _repair_subassembly_connections(kg: Dict[str, Any]) -> None:
    """Remove subassembly connections that overreach (members already connect to target)."""
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list) or not subassemblies:
        return

    components = kg.get("components", [])
    id_set = {c.get("id") for c in components if isinstance(c, Mapping)}
    id_set = {cid for cid in id_set if isinstance(cid, str)}

    crs = kg.get("connection_requirements")
    if not isinstance(crs, list):
        return

    # Build member map
    member_map: dict[str, set[str]] = {}
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        component_ids = sa.get("component_ids", [])
        if isinstance(sa_id, str) and isinstance(component_ids, list):
            member_map[sa_id] = set(component_ids)

    # Remove redundant subassembly connections
    crs_to_remove = []
    for idx, cr in enumerate(crs):
        if not isinstance(cr, dict):
            continue
        between = cr.get("between", [])
        if not isinstance(between, list):
            continue
        between_ids = {cid for cid in between if isinstance(cid, str)}

        for sa_id, members in member_map.items():
            if sa_id not in between_ids:
                continue
            external_ids = between_ids - {sa_id} - members
            if not external_ids:
                continue
            
            # Check if members already connect to these external IDs
            member_connects_to_external = False
            for ext_id in external_ids:
                for other_cr in crs:
                    if not isinstance(other_cr, dict):
                        continue
                    if other_cr is cr:
                        continue
                    other_between = other_cr.get("between", [])
                    if not isinstance(other_between, list):
                        continue
                    other_set = {cid for cid in other_between if isinstance(cid, str)}
                    if ext_id in other_set and members & other_set:
                        member_connects_to_external = True
                        break
                if member_connects_to_external:
                    break
            
            if member_connects_to_external:
                crs_to_remove.append(idx)
                break

    for idx in sorted(crs_to_remove, reverse=True):
        del crs[idx]

def _prune_redundant_wheel_subassemblies(kg: Dict[str, Any]) -> None:
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list) or not subassemblies:
        return

    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id: Dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id:
            type_by_id[comp_id] = str(comp.get("type") or "").strip().lower()

    used_ids: set[str] = set()
    for cr in kg.get("connection_requirements", []) or []:
        between = cr.get("between", []) if isinstance(cr, Mapping) else []
        if not isinstance(between, list):
            continue
        for cid in between:
            if isinstance(cid, str) and cid:
                used_ids.add(cid)

    removable_ids: set[str] = set()
    audit_rows: list[dict[str, Any]] = []
    wheel_family_types = {"wheel", "hub", "rim", "tire", "axle", "shaft", "bearing", "spacer"}
    protected_roles = {"structural_clamping", "fixation", "binding", "clamping"}

    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        component_ids = sa.get("component_ids", [])
        role = str(sa.get("role") or "").strip().lower()
        if not isinstance(sa_id, str) or not sa_id or not isinstance(component_ids, list) or len(component_ids) <= 1:
            continue
        if sa_id in used_ids or role in protected_roles:
            continue

        member_ids = [cid for cid in component_ids if isinstance(cid, str) and cid]
        if not member_ids:
            continue

        sa_id_l = sa_id.lower()
        explicit_wheel_assembly = sa_id_l.startswith("wheel_assembly_")
        looks_like_wheel_grouping = explicit_wheel_assembly or ("wheel" in sa_id_l and "assembly" in sa_id_l)
        if not looks_like_wheel_grouping and role not in {"rotational_module", "rotating_module", "wheel_module"}:
            continue

        inferred_non_wheel_member = False
        if not explicit_wheel_assembly:
            for member_id in member_ids:
                member_type = type_by_id.get(member_id, "")
                if member_type:
                    if member_type not in wheel_family_types:
                        inferred_non_wheel_member = True
                        break
                    continue
                member_id_l = member_id.lower()
                if any(token in member_id_l for token in ("fastener", "plate", "carrier", "arm", "clamp")):
                    inferred_non_wheel_member = True
                    break
                if not (member_id_l.startswith("wheel") or "wheel_" in member_id_l):
                    inferred_non_wheel_member = True
                    break
        if inferred_non_wheel_member:
            continue

        members_used = sum(1 for cid in member_ids if cid in used_ids)

        removable_ids.add(sa_id)
        audit_rows.append(
            {
                "subassembly_id": sa_id,
                "component_ids": member_ids,
                "members_used": members_used,
                "reason": "floating wheel-family grouping is redundant once wheel members are modeled directly",
            }
        )

    if not removable_ids:
        return

    kg["subassemblies"] = [
        sa for sa in subassemblies
        if not (isinstance(sa, Mapping) and isinstance(sa.get("id"), str) and sa.get("id") in removable_ids)
    ]
    kg["components"] = [
        comp for comp in components
        if not (
            isinstance(comp, Mapping)
            and isinstance(comp.get("id"), str)
            and comp.get("id") in removable_ids
            and str(comp.get("type") or "").strip().lower() in {"subassembly", "assembly", "module"}
        )
    ]
    metadata = kg.get("metadata") if isinstance(kg.get("metadata"), dict) else {}
    metadata["pruned_redundant_wheel_subassemblies"] = audit_rows
    kg["metadata"] = metadata

def _autofill_bearing_and_shaft_closure(kg: Dict[str, Any]) -> None:
    """Deterministically add missing bearing/shaft closure requirements before strict validation."""
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    comp_by_id = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str) and comp.get("id")
    }

    bearing_ids = [cid for cid, ctype in type_by_id.items() if ctype == "bearing"]
    shaft_ids = [cid for cid, ctype in type_by_id.items() if ctype in {"shaft", "axle"}]

    existing_ids = {
        cr.get("id")
        for cr in crs
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    }

    def _next_id(prefix: str) -> str:
        idx = 1
        candidate = f"{prefix}_{idx}"
        while candidate in existing_ids:
            idx += 1
            candidate = f"{prefix}_{idx}"
        existing_ids.add(candidate)
        return candidate

    related_by_id: dict[str, set[str]] = {cid: set() for cid in type_by_id.keys()}
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        if not isinstance(between, list):
            continue
        ids = [cid for cid in between if isinstance(cid, str)]
        for cid in ids:
            for other in ids:
                if other != cid:
                    related_by_id.setdefault(cid, set()).add(other)

    member_to_subassemblies: dict[str, set[str]] = {}
    subassemblies = kg.get("subassemblies", [])
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            members = sa.get("component_ids", [])
            if not isinstance(sa_id, str) or not isinstance(members, list):
                continue
            for member_id in members:
                if isinstance(member_id, str):
                    member_to_subassemblies.setdefault(member_id, set()).add(sa_id)

    structural_tokens = {
        "frame",
        "base",
        "housing",
        "mount",
        "bracket",
        "carrier",
        "hub",
        "structure",
        "plate",
        "chassis",
        "block",
        "body",
        "arm",
    }

    def _choose_structural_anchor(owner_id: str) -> str | None:
        """Choose a structural anchor for closure.

        Prefer *structural* components even if they are not directly connected yet.
        This avoids choosing shafts/bearings as anchors when a plate/frame exists.
        """

        connected = related_by_id.get(owner_id, set())
        universe = {cid for cid in type_by_id.keys() if cid != owner_id}
        owner_subassemblies = member_to_subassemblies.get(owner_id, set())

        def _is_structural_candidate(component_type: str) -> bool:
            if component_type == "subassembly":
                return False
            ctype = component_type.lower()
            return any(token in ctype for token in structural_tokens)

        def _pick_structural(candidates: set[str]) -> str | None:
            structural_candidates = [
                cid
                for cid in candidates
                if not (type_by_id.get(cid) == "subassembly" and cid in owner_subassemblies)
                and _is_structural_candidate(type_by_id.get(cid, ""))
            ]
            if not structural_candidates:
                return None

            preferred_supports = []
            for cid in structural_candidates:
                comp = comp_by_id.get(cid) if isinstance(comp_by_id.get(cid), Mapping) else {}
                cid_lower = cid.lower()
                role_lower = str(comp.get("role") or "").strip().lower() if isinstance(comp, Mapping) else ""
                type_lower = str(type_by_id.get(cid) or "").strip().lower()
                if (
                    "support_housing" in cid_lower
                    or role_lower in {"fixed_support_housing", "support_housing", "carrier", "fixed_bracket"}
                    or (type_lower in {"housing", "bracket", "carrier", "hub"} and any(token in role_lower for token in ("support", "fixed")))
                ):
                    preferred_supports.append(cid)
            if preferred_supports:
                return sorted(preferred_supports)[0]
            return sorted(structural_candidates)[0]

        anchor = _pick_structural(connected)
        if anchor is not None:
            return anchor
        anchor = _pick_structural(universe)
        if anchor is not None:
            return anchor

        # Final fallback: choose a non-fastener, non-bearing, non-wheel component deterministically.
        for cid in sorted(universe):
            if type_by_id.get(cid) == "subassembly" and cid in owner_subassemblies:
                continue
            ctype = type_by_id.get(cid, "")
            if _is_fastener_family_type(ctype):
                continue
            if str(ctype).lower() in {"bearing", "wheel"}:
                continue
            return cid
        return None

    def _has_purpose(component_id: str, purpose_set: set[str]) -> bool:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            purpose = _normalize_purpose(cr.get("purpose") if isinstance(cr.get("purpose"), str) else "")
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            if component_id in between and purpose in purpose_set:
                return True
        return False

    for bid in bearing_ids:
        anchor = _choose_structural_anchor(bid)
        if anchor is None:
            continue
        if not _has_purpose(bid, {"load_support"}):
            crs.append(
                {
                    "id": _next_id(f"req_{bid}_load_support_auto"),
                    "between": [bid, anchor],
                    "purpose": "load_support",
                    "roles": ["support"],
                    "description": "Auto-filled bearing closure requirement",
                }
            )
        if not _has_purpose(bid, {"support_to_structure"}):
            crs.append(
                {
                    "id": _next_id(f"req_{bid}_support_structure_auto"),
                    "between": [bid, anchor],
                    "purpose": "support_to_structure",
                    "roles": ["support"],
                    "description": "Auto-filled bearing closure requirement",
                }
            )

    for sid in shaft_ids:
        anchor = _choose_structural_anchor(sid)
        if anchor is None:
            continue
        if not _has_purpose(sid, {"rotation", "torque_transfer"}):
            crs.append(
                {
                    "id": _next_id(f"req_{sid}_rotation_auto"),
                    "between": [sid, anchor],
                    "purpose": "rotation",
                    "roles": ["rotation"],
                    "description": "Auto-filled shaft closure requirement",
                    "connection_semantics": {
                        "connection_mechanism": "shaft_bore_fit",
                        "relation_type": "rotation",
                        "reference_component_id": sid,
                        "moving_component_id": anchor,
                        "reference_anchor": {"kind": "component_center"},
                        "moving_anchor": {"kind": "component_center"},
                        "reference_interface_hint": "bore_axis",
                        "moving_interface_hint": "bore_axis",
                        "orientation_policy": "free",
                        "rationale": "Auto-filled shaft closure rotation around a shared bore axis.",
                    },
                }
            )
        if not _has_purpose(sid, {"structural_fixation"}):
            anchor_type = str(type_by_id.get(anchor) or "").strip().lower()
            shaft_type = str(type_by_id.get(sid) or "").strip().lower()
            anchor_suffix = _extract_wheel_suffix_for_component(anchor) if anchor_type == "arm" else None
            shaft_suffix = _extract_wheel_suffix_for_component(sid) if shaft_type in {"shaft", "axle"} else None
            if anchor_type == "arm" and shaft_type in {"shaft", "axle"} and anchor_suffix and anchor_suffix == shaft_suffix:
                connection_semantics = {
                    "connection_mechanism": "shaft_bore_fit",
                    "relation_type": "support_member_distal_attachment",
                    "reference_component_id": anchor,
                    "moving_component_id": sid,
                    "reference_anchor": _rotating_wheel_support_reference_anchor(axis="x"),
                    "moving_anchor": {"kind": "component_center"},
                    "reference_interface_hint": "distal_mount_face",
                    "moving_interface_hint": "shaft_axis",
                    "orientation_policy": "inherit_reference_yaw",
                    "geometric_semantics": _build_rotating_wheel_support_geometric_semantics(
                        notes="Auto-filled rotating wheel support closure preserved as a forked dropout axle support."
                    ),
                    "rationale": "Auto-filled shaft closure for rotating wheel support must preserve a support-member distal attachment, not a locked co-rotating coupling.",
                }
            else:
                connection_semantics = {
                    "connection_mechanism": "companion_rotation_relation",
                    "relation_type": "structural_fixation",
                    "reference_component_id": sid,
                    "moving_component_id": anchor,
                    "reference_anchor": {"kind": "component_center"},
                    "moving_anchor": {"kind": "component_center"},
                    "reference_interface_hint": "bore_axis",
                    "moving_interface_hint": "bore_axis",
                    "orientation_policy": "locked",
                    "rationale": "Auto-filled shaft closure as a co-rotating shaft-to-hub coupling without bolt-circle semantics.",
                }
            crs.append(
                {
                    "id": _next_id(f"req_{sid}_fixation_auto"),
                    "between": [sid, anchor],
                    "purpose": "structural_fixation",
                    "roles": ["mounting", "fixation"],
                    "description": "Auto-filled shaft closure requirement",
                    "connection_semantics": connection_semantics,
                }
            )

def _infer_module_drive_chain(requirement_text: str, kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return
    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    text = requirement_text.lower() if isinstance(requirement_text, str) else ""
    trigger_keywords = (
        "主动旋转",
        "自转",
        "驱动",
        "轮组",
        "电机",
        "减速器",
        "drive",
        "torque",
        "motor",
        "gearbox",
        "gear_reducer",
    )
    if not any(k in text for k in trigger_keywords):
        return

    suppress_drive_shaft_keywords = (
        "do not model a central drive shaft inside this module",
        "external drive connection is handled by the higher-level assembly",
        "model the center as support housing and bearings only",
        "central bearing support interface",
        "center bearing support interface",
        "support housing and center bearings only",
        "no central drive shaft inside the module",
        "higher-level assembly handles the drive connection",
        "本模块范围内不建模贯穿中心的 drive shaft",
        "本模块内不建模贯穿中心的 drive shaft",
        "不建模贯穿中心的 drive shaft",
        "模块内不建模贯穿中心的 drive shaft",
        "外部驱动连接留给上层总装",
        "外部驱动连接由上层总装处理",
        "上层总装处理外部驱动连接",
        "本模块内不建模中心传动轴",
        "不建模中心传动轴",
        "不建模贯穿中心的传动轴",
    )
    suppress_module_drive_shaft = any(token in text for token in suppress_drive_shaft_keywords)
    if not suppress_module_drive_shaft:
        mentions_no_internal_drive = (
            ("不建模" in text or "不需要" in text)
            and ("drive shaft" in text or "传动轴" in text)
        )
        mentions_external_drive_owner = "上层总装" in text or "外部驱动" in text or "higher-level assembly" in text
        suppress_module_drive_shaft = mentions_no_internal_drive and mentions_external_drive_owner

    explicit_center_bearing_support_tokens = (
        "model the center as support housing and bearings only",
        "central bearing support interface",
        "center bearing support interface",
        "support housing and center bearings only",
        "模块中心需要有清晰的机械接口",
        "中心需要有清晰的机械接口",
        "用于体现模块中心的旋转核心",
        "体现模块中心的旋转核心",
        "中心旋转核心",
    )
    explicit_center_bearing_support = any(token in text for token in explicit_center_bearing_support_tokens)
    if not explicit_center_bearing_support and suppress_module_drive_shaft:
        mentions_center_interface = "中心" in text and "机械接口" in text
        mentions_center_rotation_core = (
            "旋转核心" in text
            or "绕中心轴" in text
            or ("中心轴" in text and "旋转" in text)
        )
        explicit_center_bearing_support = mentions_center_interface and mentions_center_rotation_core

    comp_by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id"):
            comp_by_id[str(comp["id"])] = comp

    def _next_component_id(base: str) -> str:
        if base not in comp_by_id:
            return base
        idx = 2
        candidate = f"{base}_{idx}"
        while candidate in comp_by_id:
            idx += 1
            candidate = f"{base}_{idx}"
        return candidate

    type_by_id = {
        cid: (str(comp.get("type") or "").strip().lower())
        for cid, comp in comp_by_id.items()
    }

    def _remove_components(component_ids: List[str]) -> None:
        if not component_ids:
            return
        remove_set = {cid for cid in component_ids if isinstance(cid, str) and cid}
        if not remove_set:
            return
        components[:] = [
            comp
            for comp in components
            if not (
                isinstance(comp, Mapping)
                and isinstance(comp.get("id"), str)
                and str(comp.get("id")) in remove_set
            )
        ]
        for cid in list(remove_set):
            comp_by_id.pop(cid, None)
            type_by_id.pop(cid, None)
        crs[:] = [
            cr
            for cr in crs
            if not (
                isinstance(cr, Mapping)
                and isinstance(cr.get("between"), list)
                and any(isinstance(item, str) and item in remove_set for item in cr.get("between", []))
            )
        ]

    if suppress_module_drive_shaft:
        suppressed_ids: List[str] = []
        for cid, comp in list(comp_by_id.items()):
            ctype = str(type_by_id.get(cid) or "").strip().lower()
            cid_l = cid.lower()
            role_l = str(comp.get("role") or "").strip().lower() if isinstance(comp, Mapping) else ""
            params = comp.get("parameters") if isinstance(comp, Mapping) and isinstance(comp.get("parameters"), Mapping) else {}
            inferred_flag = str(params.get("inferred") or "").strip().lower()
            if ctype in {"shaft", "axle"} and (
                "module_drive" in cid_l
                or "central_input" in cid_l
                or role_l == "module_drive_input"
            ):
                suppressed_ids.append(cid)
                continue
            if ctype == "interface_block" and "motor_interface" in cid_l and inferred_flag == "true":
                suppressed_ids.append(cid)
                continue
            if ctype == "bearing" and cid_l.startswith("module_center_bearing"):
                suppressed_ids.append(cid)
                continue
            if "support_housing" in cid_l or role_l in {"fixed_support_housing", "support_housing"}:
                suppressed_ids.append(cid)
        _remove_components(suppressed_ids)

        existing_root = kg.get("root_component_id")
        if isinstance(existing_root, str) and existing_root and existing_root not in comp_by_id:
            fallback_root = None
            for cid, ctype in type_by_id.items():
                if ctype == "hub" and "central" in cid.lower():
                    fallback_root = cid
                    break
            if fallback_root is None:
                for cid, ctype in type_by_id.items():
                    if ctype == "hub":
                        fallback_root = cid
                        break
            if isinstance(fallback_root, str) and fallback_root:
                kg["root_component_id"] = fallback_root
            else:
                kg.pop("root_component_id", None)

    central_hub_id: str | None = None
    if "central_hub" in comp_by_id:
        central_hub_id = "central_hub"
    else:
        for cid, ctype in type_by_id.items():
            if ctype == "hub" and "central" in cid.lower():
                central_hub_id = cid
                break
        if central_hub_id is None:
            for cid, ctype in type_by_id.items():
                if ctype == "hub":
                    central_hub_id = cid
                    break

    if central_hub_id is None:
        return

    def _numeric_dim(comp: Mapping[str, Any], *keys: str) -> float | None:
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
        params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
        for key in keys:
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
            value = params.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        return None

    def _dimension_source_name(comp: Mapping[str, Any], key: str) -> str:
        srcs = comp.get("dimension_sources") if isinstance(comp.get("dimension_sources"), Mapping) else {}
        src = srcs.get(key)
        if isinstance(src, Mapping):
            return str(src.get("source") or "").strip().lower()
        if isinstance(src, str):
            return src.strip().lower()
        return ""

    def _infer_supported_module_drive_shaft_diameter() -> float:
        bore_candidates: List[float] = []
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            cid = str(comp.get("id") or "")
            ctype = str(comp.get("type") or "").strip().lower()
            relevant = ctype == "bearing" or cid == central_hub_id or ctype in {"hub", "coupling", "bushing"}
            if not relevant:
                continue
            bore = _numeric_dim(comp, "bore_diameter", "inner_diameter")
            if not isinstance(bore, (int, float)) or float(bore) <= 0.0:
                continue
            source_name = _dimension_source_name(comp, "bore_diameter") or _dimension_source_name(comp, "inner_diameter")
            if ctype == "bearing" and source_name not in {"standard_catalog", "input", "explicit"}:
                continue
            bore_candidates.append(float(bore))

        if bore_candidates:
            return float(_nearest_option(min(bore_candidates), STANDARD_SHAFT_DIAMETERS))
        return 8.0

    drive_shaft_id: str | None = None
    motor_interface_id: str | None = None
    if not suppress_module_drive_shaft:
        preferred_drive_shaft_diameter = _infer_supported_module_drive_shaft_diameter()

        for cid, ctype in type_by_id.items():
            cid_l = cid.lower()
            if ctype in {"shaft", "axle"} and ("module_drive" in cid_l or "central_input" in cid_l):
                drive_shaft_id = cid
                break

        if drive_shaft_id is None:
            drive_shaft_id = _next_component_id("module_drive_shaft")
            drive_component = {
                "id": drive_shaft_id,
                "type": "shaft",
                "role": "module_drive_input",
                "kind": "part",
                "must_model": True,
                "part_kind": "shaft",
                "modeling_policy": "must_model",
                "parameters": {
                    "diameter": preferred_drive_shaft_diameter,
                    "length": 40.0,
                    "inferred": "true",
                    "critical": "true",
                },
                "dimensions": {
                    "diameter": preferred_drive_shaft_diameter,
                    "length": 40.0,
                },
                "dimension_sources": {
                    "diameter": {
                        "source": "derived",
                        "derived_from": ["available_rotary_support_bores"],
                        "confidence": 0.9,
                    },
                    "length": {"source": "derived", "confidence": 0.6},
                },
                "shape_semantics": {
                    "type": "cylindrical",
                    "cross_section": "circular",
                    "notes": "inferred=true;critical=true;module-level drive chain closure",
                },
            }
            components.append(drive_component)
            comp_by_id[drive_shaft_id] = drive_component
            type_by_id[drive_shaft_id] = "shaft"

        drive_component_ref = comp_by_id.get(drive_shaft_id) if isinstance(drive_shaft_id, str) else None
        if isinstance(drive_component_ref, dict):
            drive_dims = drive_component_ref.get("dimensions") if isinstance(drive_component_ref.get("dimensions"), Mapping) else {}
            drive_params = drive_component_ref.get("parameters") if isinstance(drive_component_ref.get("parameters"), Mapping) else {}
            drive_sources = drive_component_ref.get("dimension_sources") if isinstance(drive_component_ref.get("dimension_sources"), Mapping) else {}
            drive_diameter = drive_dims.get("diameter")
            drive_source = drive_sources.get("diameter") if isinstance(drive_sources.get("diameter"), Mapping) else {}
            drive_source_name = str(drive_source.get("source") or "").strip().lower() if isinstance(drive_source, Mapping) else ""
            authoritative_diameter = drive_source_name in {"input", "explicit", "standard_catalog"}
            if (not isinstance(drive_diameter, (int, float)) or float(drive_diameter) <= 0.0 or not authoritative_diameter) and (
                not isinstance(drive_diameter, (int, float)) or float(drive_diameter) > preferred_drive_shaft_diameter
            ):
                drive_dims = dict(drive_dims)
                drive_params = dict(drive_params)
                drive_sources = dict(drive_sources)
                drive_dims["diameter"] = float(preferred_drive_shaft_diameter)
                drive_params["diameter"] = float(preferred_drive_shaft_diameter)
                drive_sources["diameter"] = {
                    "source": "derived",
                    "derived_from": ["available_rotary_support_bores"],
                    "confidence": 0.9,
                }
                drive_component_ref["dimensions"] = drive_dims
                drive_component_ref["parameters"] = drive_params
                drive_component_ref["dimension_sources"] = drive_sources

        for cid, ctype in type_by_id.items():
            if "motor_interface" in cid.lower() or ctype in {"motor", "electric_motor", "gearbox", "gear_reducer"}:
                motor_interface_id = cid
                break

        if motor_interface_id is None:
            motor_interface_id = _next_component_id("motor_interface")
            motor_component = {
                "id": motor_interface_id,
                "type": "interface_block",
                "role": "drive_source",
                "kind": "part",
                "must_model": False,
                "part_kind": "other",
                "modeling_policy": "reference_only",
                "is_container": False,
                "is_container_only": False,
                "has_geometry": True,
                "parameters": {
                    "length": 20.0,
                    "width": 20.0,
                    "height": 20.0,
                    "inferred": "true",
                    "critical": "true",
                },
                "dimensions": {
                    "length": 20.0,
                    "width": 20.0,
                    "height": 20.0,
                },
                "dimension_sources": {
                    "length": {"source": "derived", "confidence": 0.5},
                    "width": {"source": "derived", "confidence": 0.5},
                    "height": {"source": "derived", "confidence": 0.5},
                },
                "shape_semantics": {
                    "type": "complex",
                    "notes": "inferred=true;critical=true;module-level drive source placeholder",
                },
            }
            components.append(motor_component)
            comp_by_id[motor_interface_id] = motor_component
            type_by_id[motor_interface_id] = "interface_block"

        motor_component_ref = comp_by_id.get(motor_interface_id) if isinstance(motor_interface_id, str) else None
        if isinstance(motor_component_ref, dict):
            motor_component_ref["is_container"] = False
            motor_component_ref["is_container_only"] = False
            if not isinstance(motor_component_ref.get("has_geometry"), bool):
                motor_component_ref["has_geometry"] = True
            policy = motor_component_ref.get("modeling_policy")
            if not isinstance(policy, str) or not policy.strip():
                motor_component_ref["modeling_policy"] = "reference_only"

            existing_dims = motor_component_ref.get("dimensions")
            if not isinstance(existing_dims, Mapping) or len(existing_dims) == 0:
                motor_component_ref["dimensions"] = {
                    "length": 20.0,
                    "width": 20.0,
                    "height": 20.0,
                }
            existing_params = motor_component_ref.get("parameters")
            if not isinstance(existing_params, Mapping) or len(existing_params) == 0:
                motor_component_ref["parameters"] = {
                    "length": 20.0,
                    "width": 20.0,
                    "height": 20.0,
                }
            existing_sources = motor_component_ref.get("dimension_sources")
            if not isinstance(existing_sources, Mapping) or len(existing_sources) == 0:
                motor_component_ref["dimension_sources"] = {
                    "length": {"source": "derived", "confidence": 0.5},
                    "width": {"source": "derived", "confidence": 0.5},
                    "height": {"source": "derived", "confidence": 0.5},
                }

    central_hub_ref = comp_by_id.get(central_hub_id) if isinstance(central_hub_id, str) else None

    if suppress_module_drive_shaft:
        if not isinstance(central_hub_ref, dict):
            return
        kg["root_component_id"] = central_hub_id
        if not explicit_center_bearing_support:
            return

        center_bearing_spec = find_bearing_by_designation("6001") or {"code": "6001", "bore": 12.0, "outer": 28.0, "width": 8.0}
        center_bearing_id = "module_center_bearing"
        center_bearing_component = comp_by_id.get(center_bearing_id) if isinstance(comp_by_id.get(center_bearing_id), dict) else None
        if not isinstance(center_bearing_component, dict):
            center_bearing_component = {
                "id": center_bearing_id,
                "type": "bearing",
                "role": "load_support",
                "kind": "part",
                "must_model": True,
                "part_kind": "bearing",
                "modeling_policy": "simplified_model",
                "parent_id": central_hub_id,
                "position_parent": central_hub_id,
                "parameters": {},
                "dimensions": {},
                "dimension_sources": {},
                "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
            }
            components.append(center_bearing_component)
            comp_by_id[center_bearing_id] = center_bearing_component
            type_by_id[center_bearing_id] = "bearing"

        bearing_dims = dict(center_bearing_component.get("dimensions") or {})
        bearing_dims["bore_diameter"] = float(center_bearing_spec.get("bore", 12.0))
        bearing_dims["outer_diameter"] = float(center_bearing_spec.get("outer", 28.0))
        bearing_dims["width"] = float(center_bearing_spec.get("width", 8.0))
        center_bearing_component["dimensions"] = bearing_dims

        bearing_params = dict(center_bearing_component.get("parameters") or {})
        bearing_params["bore_diameter"] = float(center_bearing_spec.get("bore", 12.0))
        bearing_params["outer_diameter"] = float(center_bearing_spec.get("outer", 28.0))
        bearing_params["width"] = float(center_bearing_spec.get("width", 8.0))
        bearing_params["designation"] = str(center_bearing_spec.get("code") or "6001")
        bearing_params["external_interface_placeholder"] = True
        center_bearing_component["parameters"] = bearing_params

        bearing_sources = dict(center_bearing_component.get("dimension_sources") or {})
        bearing_sources["bore_diameter"] = {"source": "standard_catalog", "confidence": 1.0}
        bearing_sources["outer_diameter"] = {"source": "standard_catalog", "confidence": 1.0}
        bearing_sources["width"] = {"source": "standard_catalog", "confidence": 1.0}
        center_bearing_component["dimension_sources"] = bearing_sources
        center_bearing_component["parent_id"] = central_hub_id
        center_bearing_component["position_parent"] = central_hub_id
        center_bearing_component["role"] = str(center_bearing_component.get("role") or "load_support")
        center_bearing_component["must_model"] = True
        center_bearing_component["part_kind"] = "bearing"
        center_bearing_component["modeling_policy"] = "simplified_model"

        existing_ids = {
            cr.get("id")
            for cr in crs
            if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
        }

        def _next_cr_id(prefix: str) -> str:
            idx = 1
            candidate = f"{prefix}_{idx}"
            while candidate in existing_ids:
                idx += 1
                candidate = f"{prefix}_{idx}"
            existing_ids.add(candidate)
            return candidate

        def _has_requirement(a: str, b: str, purpose: str) -> bool:
            normalized_purpose = _normalize_purpose(purpose)
            for cr in crs:
                if not isinstance(cr, Mapping):
                    continue
                between = cr.get("between")
                if not isinstance(between, list):
                    continue
                ids = {cid for cid in between if isinstance(cid, str)}
                if a in ids and b in ids and _normalize_purpose(cr.get("purpose") if isinstance(cr.get("purpose"), str) else "") == normalized_purpose:
                    return True
            return False

        if not _has_requirement(center_bearing_id, central_hub_id, "load_support"):
            constraint_intent, dof, mating_features = _derive_constraint_contract("load_support")
            crs.append(
                {
                    "id": _next_cr_id(f"req_{center_bearing_id}_{central_hub_id}_load_support_auto"),
                    "between": [center_bearing_id, central_hub_id],
                    "purpose": "load_support",
                    "roles": ["mounting"],
                    "constraint_intent": constraint_intent,
                    "dof": dof,
                    "mating_features": mating_features,
                    "constraints": {
                        "inferred": True,
                        "critical": True,
                        "concentric_required": True,
                        "external_interface_placeholder": True,
                        "rationale": "Deterministic module center-bearing interface retained inside central_hub while the external fixed support remains in the higher-level assembly.",
                    },
                    "description": "Deterministic module center-bearing outer race seat integrated in central_hub; external fixed support remains in higher-level assembly.",
                    "confidence": 0.95,
                    "connection_semantics": _build_bearing_outer_race_seat_contract(
                        host_component_id=central_hub_id,
                        bearing_component_id=center_bearing_id,
                        rationale="The central hub must expose a real bearing interface for module-level rotation, while the mating fixed support is intentionally deferred to the higher-level assembly.",
                    ),
                }
            )
        return

    def _module_support_housing_id() -> str | None:
        for cid, comp in comp_by_id.items():
            if not isinstance(cid, str):
                continue
            cid_lower = cid.lower()
            role_lower = str(comp.get("role") or "").strip().lower() if isinstance(comp, Mapping) else ""
            ctype_lower = str(type_by_id.get(cid) or "").strip().lower()
            if (
                "support_housing" in cid_lower
                or role_lower in {"fixed_support_housing", "support_housing"}
                or ctype_lower in {"housing", "bracket"}
            ):
                return cid
        return None

    hub_outer_diameter = _numeric_dim(central_hub_ref or {}, "diameter", "outer_diameter") or 50.0
    hub_thickness = _numeric_dim(central_hub_ref or {}, "thickness") or 20.0
    center_bearing_spec = find_bearing_by_designation("6001") or {"code": "6001", "bore": 12.0, "outer": 28.0, "width": 8.0}
    center_bearing_designation = str(center_bearing_spec.get("code") or "6001")
    center_bearing_inner_diameter = round(float(center_bearing_spec.get("bore", 12.0)), 1)
    center_bearing_outer_diameter = round(float(center_bearing_spec.get("outer", 28.0)), 1)
    center_bearing_width = round(float(center_bearing_spec.get("width", 8.0)), 1)
    support_housing_inner_diameter = round(center_bearing_inner_diameter + 0.4, 1)
    support_housing_outer_diameter = round(center_bearing_outer_diameter + 16.0, 1)
    support_housing_thickness = round(max(16.0, 2.0 * center_bearing_width + 2.0, 0.8 * float(hub_thickness)), 1)

    support_housing_id = _module_support_housing_id()
    if support_housing_id is None:
        support_housing_id = _next_component_id("module_support_housing")
        support_component = {
            "id": support_housing_id,
            "type": "hub",
            "role": "fixed_support_housing",
            "kind": "part",
            "must_model": True,
            "part_kind": "housing",
            "modeling_policy": "must_model",
            "parameters": {
                "outer_diameter": support_housing_outer_diameter,
                "inner_diameter": support_housing_inner_diameter,
                "thickness": support_housing_thickness,
                "inferred": "true",
                "critical": "true",
            },
            "dimensions": {
                "outer_diameter": support_housing_outer_diameter,
                "inner_diameter": support_housing_inner_diameter,
                "thickness": support_housing_thickness,
            },
            "dimension_sources": {
                "outer_diameter": {"source": "derived", "confidence": 0.85},
                "inner_diameter": {"source": "derived", "confidence": 0.85},
                "thickness": {"source": "derived", "confidence": 0.8},
            },
            "shape_semantics": {
                "type": "annular",
                "cross_section": "annular",
                "notes": "inferred=true;critical=true;fixed support housing for module-level center bearing support",
            },
        }
        components.append(support_component)
        comp_by_id[support_housing_id] = support_component
        type_by_id[support_housing_id] = "hub"

    support_housing_ref = comp_by_id.get(support_housing_id) if isinstance(support_housing_id, str) else None
    if isinstance(support_housing_ref, dict):
        support_housing_ref["role"] = str(support_housing_ref.get("role") or "fixed_support_housing")
        support_housing_ref["type"] = str(support_housing_ref.get("type") or "hub")
        support_housing_ref["kind"] = str(support_housing_ref.get("kind") or "part")
        support_housing_ref["part_kind"] = str(support_housing_ref.get("part_kind") or "housing")
        support_housing_ref["modeling_policy"] = str(support_housing_ref.get("modeling_policy") or "must_model")
        support_housing_ref["must_model"] = True
        support_dims = dict(support_housing_ref.get("dimensions") or {})
        support_dims.setdefault("outer_diameter", support_housing_outer_diameter)
        support_dims.setdefault("inner_diameter", support_housing_inner_diameter)
        support_dims.setdefault("thickness", support_housing_thickness)
        support_housing_ref["dimensions"] = support_dims
        support_params = dict(support_housing_ref.get("parameters") or {})
        support_params.setdefault("outer_diameter", support_housing_outer_diameter)
        support_params.setdefault("inner_diameter", support_housing_inner_diameter)
        support_params.setdefault("thickness", support_housing_thickness)
        support_housing_ref["parameters"] = support_params
        support_sources = dict(support_housing_ref.get("dimension_sources") or {})
        support_sources.setdefault("outer_diameter", {"source": "derived", "confidence": 0.85})
        support_sources.setdefault("inner_diameter", {"source": "derived", "confidence": 0.85})
        support_sources.setdefault("thickness", {"source": "derived", "confidence": 0.8})
        support_housing_ref["dimension_sources"] = support_sources
        support_shape = dict(support_housing_ref.get("shape_semantics") or {})
        support_shape["type"] = "annular"
        support_shape.setdefault("cross_section", "annular")
        support_housing_ref["shape_semantics"] = support_shape

    if isinstance(central_hub_ref, dict) and not isinstance(central_hub_ref.get("position_parent"), str):
        central_hub_ref["position_parent"] = support_housing_id

    existing_root = kg.get("root_component_id")
    if isinstance(support_housing_id, str) and support_housing_id and (
        not isinstance(existing_root, str) or not existing_root or existing_root == central_hub_id
    ):
        kg["root_component_id"] = support_housing_id

    stale_center_bearings = [
        cid
        for cid in list(comp_by_id.keys())
        if isinstance(cid, str) and cid.startswith("module_center_bearing") and cid != "module_center_bearing_1"
    ]
    _remove_components(stale_center_bearings)

    center_bearing_ids: List[str] = ["module_center_bearing_1"]
    bearing_id = center_bearing_ids[0]
    if bearing_id not in comp_by_id:
        bearing_comp = {
            "id": bearing_id,
            "type": "bearing",
            "role": "load_support",
            "kind": "part",
            "must_model": True,
            "part_kind": "bearing",
            "modeling_policy": "simplified_model",
            "parent_id": support_housing_id,
            "position_parent": support_housing_id,
            "parameters": {
                "bore_diameter": center_bearing_inner_diameter,
                "outer_diameter": center_bearing_outer_diameter,
                "width": center_bearing_width,
                "designation": center_bearing_designation,
            },
            "dimensions": {
                "bore_diameter": center_bearing_inner_diameter,
                "outer_diameter": center_bearing_outer_diameter,
                "width": center_bearing_width,
            },
            "dimension_sources": {
                "bore_diameter": {"source": "standard_catalog", "confidence": 1.0},
                "outer_diameter": {"source": "standard_catalog", "confidence": 1.0},
                "width": {"source": "standard_catalog", "confidence": 1.0},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        components.append(bearing_comp)
        comp_by_id[bearing_id] = bearing_comp
        type_by_id[bearing_id] = "bearing"
    bearing_ref = comp_by_id.get(bearing_id)
    if isinstance(bearing_ref, dict):
        bearing_ref["role"] = str(bearing_ref.get("role") or "load_support")
        bearing_ref["kind"] = "part"
        bearing_ref["must_model"] = True
        bearing_ref["part_kind"] = "bearing"
        bearing_ref["modeling_policy"] = "simplified_model"
        bearing_ref["parent_id"] = support_housing_id
        bearing_ref["position_parent"] = support_housing_id
        bearing_dims = dict(bearing_ref.get("dimensions") or {})
        bearing_dims["bore_diameter"] = center_bearing_inner_diameter
        bearing_dims["outer_diameter"] = center_bearing_outer_diameter
        bearing_dims["width"] = center_bearing_width
        bearing_ref["dimensions"] = bearing_dims
        bearing_params = dict(bearing_ref.get("parameters") or {})
        bearing_params["bore_diameter"] = center_bearing_inner_diameter
        bearing_params["outer_diameter"] = center_bearing_outer_diameter
        bearing_params["width"] = center_bearing_width
        bearing_params["designation"] = center_bearing_designation
        bearing_ref["parameters"] = bearing_params
        bearing_sources = dict(bearing_ref.get("dimension_sources") or {})
        bearing_sources["bore_diameter"] = {"source": "standard_catalog", "confidence": 1.0}
        bearing_sources["outer_diameter"] = {"source": "standard_catalog", "confidence": 1.0}
        bearing_sources["width"] = {"source": "standard_catalog", "confidence": 1.0}
        bearing_ref["dimension_sources"] = bearing_sources
        bearing_shape = dict(bearing_ref.get("shape_semantics") or {})
        bearing_shape["type"] = "cylindrical"
        bearing_shape["cross_section"] = "annular"
        bearing_ref["shape_semantics"] = bearing_shape
    existing_ids = {
        cr.get("id")
        for cr in crs
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    }

    def _next_cr_id(prefix: str) -> str:
        idx = 1
        candidate = f"{prefix}_{idx}"
        while candidate in existing_ids:
            idx += 1
            candidate = f"{prefix}_{idx}"
        existing_ids.add(candidate)
        return candidate

    def _has_requirement(a: str, b: str, purpose: str) -> bool:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            cr_purpose = _normalize_purpose(cr.get("purpose") if isinstance(cr.get("purpose"), str) else "")
            if cr_purpose != _normalize_purpose(purpose):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                continue
            ids = {cid for cid in between if isinstance(cid, str)}
            if a in ids and b in ids:
                return True
        return False

    def _append_requirement(a: str, b: str, purpose: str, desc: str) -> None:
        if _has_requirement(a, b, purpose):
            return
        constraint_intent, dof, mating_features = _derive_constraint_contract(purpose)
        crs.append(
            {
                "id": _next_cr_id(f"req_{a}_{b}_{purpose}_auto"),
                "between": [a, b],
                "purpose": purpose,
                "roles": ["torque_transfer"] if purpose == "torque_transfer" else (["rotation"] if purpose == "rotation" else ["mounting"]),
                "constraint_intent": constraint_intent,
                "dof": dof,
                "mating_features": mating_features,
                "constraints": {
                    "inferred": True,
                    "critical": True,
                    "rationale": desc,
                },
                "description": f"{desc}; inferred=true; critical=true",
                "confidence": 0.95,
            }
        )

    def _append_semantic_requirement(
        *,
        a: str,
        b: str,
        purpose: str,
        desc: str,
        roles: List[str],
        connection_semantics: Mapping[str, Any],
        constraints: Mapping[str, Any] | None = None,
    ) -> None:
        if _has_requirement(a, b, purpose):
            return
        constraint_intent, dof, mating_features = _derive_constraint_contract(purpose)
        entry = {
            "id": _next_cr_id(f"req_{a}_{b}_{purpose}_auto"),
            "between": [a, b],
            "purpose": purpose,
            "roles": list(roles),
            "constraint_intent": constraint_intent,
            "dof": dof,
            "mating_features": mating_features,
            "constraints": {
                "inferred": True,
                "critical": True,
                "rationale": desc,
            },
            "description": f"{desc}; inferred=true; critical=true",
            "confidence": 0.95,
            "connection_semantics": dict(connection_semantics),
        }
        if isinstance(constraints, Mapping) and constraints:
            entry["constraints"].update(dict(constraints))
        crs.append(entry)

    for bearing_id in center_bearing_ids:
        _append_semantic_requirement(
            a=bearing_id,
            b=support_housing_id,
            purpose="load_support",
            desc="Deterministic module center-bearing outer race support in the fixed support housing",
            roles=["mounting"],
            constraints={"concentric_required": True},
            connection_semantics=_build_bearing_outer_race_seat_contract(
                host_component_id=support_housing_id,
                bearing_component_id=bearing_id,
                rationale="The fixed support housing captures the center bearing outer race so the whole module can rotate around the central hub.",
            ),
        )
        _append_semantic_requirement(
            a=bearing_id,
            b=central_hub_id,
            purpose="rotation_support",
            desc="Deterministic module center-bearing inner race support on the rotating central hub journal",
            roles=["rotation"],
            constraints={"coaxial_required": True},
            connection_semantics={
                "connection_mechanism": "shaft_bore_fit",
                "relation_type": "shaft_axis_to_bore",
                "reference_component_id": central_hub_id,
                "moving_component_id": bearing_id,
                "reference_anchor": {"kind": "component_center"},
                "moving_anchor": {"kind": "component_center"},
                "reference_interface_hint": "radial_outer_face",
                "moving_interface_hint": "bore_axis",
                "orientation_policy": "free",
                "geometric_semantics": {
                    "contact_model": "bearing_inner_race_revolute_fit",
                    "reference_feature_strategy": "hub_journal_od",
                    "moving_feature_strategy": "inner_race_bore",
                    "pattern_policy": "none",
                    "retention_strategy": "free_rotation_with_inner_race_capture",
                    "notes": "Deterministic center-bearing rotation support between the rotating module hub and the fixed support housing.",
                },
                "rationale": "The center bearing inner race runs on the rotating central hub while the outer race is retained by the fixed support housing.",
            },
        )
    if isinstance(motor_interface_id, str) and isinstance(drive_shaft_id, str):
        _append_requirement(
            motor_interface_id,
            drive_shaft_id,
            "torque_transfer",
            "Deterministic module-drive closure: motor interface drives module input shaft",
        )
        _append_requirement(
            drive_shaft_id,
            central_hub_id,
            "torque_transfer",
            "Deterministic module-drive closure: module input shaft transfers torque to central hub",
        )


__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
