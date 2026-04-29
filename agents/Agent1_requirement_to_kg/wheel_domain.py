"""Agent1 tri-star wheel, hub, arm, and rotor topology rules."""

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

def _ensure_wheel_mounting_requirements(kg: Dict[str, Any]) -> None:
    """Ensure each wheel has exactly one mounting/fastening requirement when fasteners are present.

    Backward-compat helper used by tests and for deterministic completion:
    - If a wheel participates in rotation but has no fastening/clamping/fixation requirement,
      and a fastener exists in the same subassembly, synthesize ONE fastening_mechanism CR.
    """

    components = kg.get("components", [])
    crs = kg.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)

    wheel_ids = sorted([cid for cid, ctype in type_by_id.items() if ctype == "wheel"])
    if not wheel_ids:
        return

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

    subassemblies = kg.get("subassemblies", [])
    members_by_wheel: dict[str, set[str]] = {}
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            members = sa.get("component_ids", [])
            if not isinstance(members, list):
                continue
            member_ids = [m for m in members if isinstance(m, str) and m]
            member_set = set(member_ids)
            for wheel_id in wheel_ids:
                if wheel_id in member_set:
                    members_by_wheel.setdefault(wheel_id, set()).update(member_set)

    mounting_purposes = {"fastening_mechanism", "structural_fixation", "structural_clamping"}
    rotation_purposes = {"rotation", "torque_transfer"}

    def _has_purpose(*, wheel_id: str, purposes: set[str]) -> bool:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            if wheel_id not in between:
                continue
            p = cr.get("purpose")
            if isinstance(p, str) and _normalize_purpose(p) in purposes:
                return True
        return False

    for wheel_id in wheel_ids:
        if _has_purpose(wheel_id=wheel_id, purposes=mounting_purposes):
            continue

        # Only synthesize if this wheel is actually in a rotation-type requirement.
        if not _has_purpose(wheel_id=wheel_id, purposes=rotation_purposes):
            continue

        members = members_by_wheel.get(wheel_id, set())
        fasteners = sorted([m for m in members if type_by_id.get(m) == "fastener"])
        if not fasteners:
            continue
        fastener_id = fasteners[0]

        shafts = sorted([m for m in members if type_by_id.get(m) in {"shaft", "axle"}])
        shaft_id = shafts[0] if shafts else None

        between: list[str] = [wheel_id]
        if shaft_id:
            between.append(shaft_id)
        between.append(fastener_id)

        crs.append(
            {
                "id": _next_id(f"{wheel_id}_mounting_auto"),
                "between": between,
                "purpose": "fastening_mechanism",
                "description": "Deterministic wheel mounting completion",
            }
        )

def _component_matches_suffix(comp_id: str, suffix: str) -> bool:
    """Check whether *comp_id* contains *suffix* as a delimited token."""
    return bool(re.search(rf"(?:^|_){re.escape(suffix)}(?:_|$)", comp_id))

def _resolve_wheel_container(suffix: str, type_by_id: dict[str, str]) -> str | None:
    """Return the component id of the wheel container for a given numeric *suffix*."""
    preferred = [f"wheel_{suffix}", f"wheel_assembly_{suffix}"]
    for cid in preferred:
        if cid in type_by_id:
            return cid
    for cid, ctype in type_by_id.items():
        if str(ctype).lower() == "wheel" and _component_matches_suffix(cid, suffix):
            return cid
    for cid, ctype in type_by_id.items():
        normalized_type = str(ctype or "").strip().lower()
        if normalized_type in {"arm", "axle", "hub", "bearing", "rim", "tire", "spacer", "fastener"}:
            continue
        if cid.startswith("wheel_arm_") or cid.startswith("wheel_axle_"):
            continue
        if _component_matches_suffix(cid, suffix) and cid.startswith("wheel_"):
            return cid
    return None

def _is_cross_index_target(arm_suffix: str, target_id: str) -> bool:
    """Return True if *target_id* belongs to a different wheel index than *arm_suffix*."""
    for pattern in (
        r"(?:^|_)wheel_(\d+)(?:_|$)",
        r"(?:^|_)wheel_axle_(\d+)$",
        r"(?:^|_)wheel_assembly_(\d+)$",
        r"(?:^|_)bearing_(\d+)$",
    ):
        m = re.search(pattern, target_id)
        if m and m.group(1) != arm_suffix:
            return True
    return False

def _ensure_arm_interface_requirements(payload: Dict[str, Any]) -> None:
    """Ensure each wheel arm satisfies topology constraints (central + distal, no cross-index)."""
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    crs = payload.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    parent_by_id: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        parent_id = comp.get("parent_id")
        if isinstance(cid, str) and isinstance(parent_id, str):
            parent_by_id[cid] = parent_id

    arm_ids = [cid for cid, ctype in type_by_id.items() if ctype == "arm"]
    if not arm_ids:
        return

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

    def _extract_arm_suffix(comp_id: str) -> str | None:
        m = re.search(r"(?:^|_)wheel_arm_(\d+)$", comp_id)
        if m:
            return m.group(1)
        return None

    def _is_container_only(comp_id: str) -> bool:
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            if comp.get("id") == comp_id:
                if bool(comp.get("is_container_only")) or bool(comp.get("is_container")):
                    return True
                if str(comp.get("modeling_policy") or "").lower() == "container_only":
                    return True
                if comp.get("must_model") is False:
                    return True
        return False

    def _distal_candidates(suffix: str) -> list[str]:
        candidates: list[str] = []
        # Prefer axle (always physical) over hub (often a container node)
        for cid in (f"wheel_{suffix}_axle", f"wheel_axle_{suffix}", f"wheel_{suffix}_hub"):
            if cid in type_by_id and cid not in candidates and not _is_container_only(cid):
                candidates.append(cid)

        wheel_container = _resolve_wheel_container(suffix, type_by_id)
        if isinstance(wheel_container, str):
            semantic_children = [
                cid
                for cid, parent_id in parent_by_id.items()
                if parent_id == wheel_container
                and str(type_by_id.get(cid) or "").lower() in {"hub", "axle"}
                and not _is_container_only(cid)
            ]
            # Prefer axle over hub in semantic children too
            semantic_children.sort(key=lambda c: (0 if "axle" in c.lower() else 1, c))
            for cid in semantic_children:
                if cid not in candidates:
                    candidates.append(cid)

        if not candidates and isinstance(wheel_container, str) and wheel_container in type_by_id:
            candidates.append(wheel_container)

        return candidates

    def _is_central_hub_component(comp_id: str) -> bool:
        ctype = str(type_by_id.get(comp_id) or "").strip().lower()
        cid_l = comp_id.lower()
        if comp_id == "central_hub":
            return True
        return ctype == "hub" and "central" in cid_l

    def _connected_targets(arm_id: str) -> set[str]:
        connected: set[str] = set()
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            if arm_id in between:
                for cid in between:
                    if not isinstance(cid, str) or cid == arm_id:
                        continue
                    if type_by_id.get(cid) == "fastener":
                        continue
                    connected.add(cid)
        return connected

    def _central_candidates() -> list[str]:
        candidates = [cid for cid in type_by_id.keys() if _is_central_hub_component(cid)]
        candidates = sorted(set(candidates), key=lambda c: (0 if c == "central_hub" else 1, c))
        return candidates

    def _replace_cross_index_links(arm_id: str, arm_suffix: str, replacement: str | None) -> None:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between")
            if not isinstance(between, list) or arm_id not in between:
                continue
            cross_targets = [
                cid
                for cid in between
                if isinstance(cid, str) and cid != arm_id and _is_cross_index_target(arm_suffix, cid)
            ]
            if not cross_targets:
                continue

            new_between: list[Any] = [cid for cid in between if cid not in cross_targets]
            if isinstance(replacement, str) and replacement and replacement not in new_between:
                new_between.append(replacement)

            if arm_id not in new_between:
                new_between.append(arm_id)

            while len(new_between) >= 2 and not isinstance(new_between[-1], str):
                new_between.pop()

            cr["between"] = new_between
            if isinstance(cr.get("description"), str):
                cr["description"] = str(cr.get("description")) + " | cross-index repaired"

    for arm_id in arm_ids:
        suffix = _extract_arm_suffix(arm_id)
        if not suffix:
            continue

        distals = _distal_candidates(suffix)
        replacement_distal = distals[0] if distals else None
        _replace_cross_index_links(arm_id, suffix, replacement_distal)

        connected = _connected_targets(arm_id)
        central_ok = any(_is_central_hub_component(x) for x in connected)
        strict_distal_set = {
            f"wheel_{suffix}_hub",
            f"wheel_{suffix}_axle",
            f"wheel_axle_{suffix}",
        }
        wheel_container = _resolve_wheel_container(suffix, type_by_id)
        semantic_fallback_distal_ok = False
        if isinstance(wheel_container, str):
            semantic_fallback_distal_ok = any(
                parent_by_id.get(x) == wheel_container and str(type_by_id.get(x) or "").lower() in {"hub", "axle"}
                for x in connected
            )
        distal_ok = any(x in strict_distal_set for x in connected) or semantic_fallback_distal_ok

        if not central_ok:
            central_target = _central_candidates()[0] if _central_candidates() else "central_hub"
            crs.append(
                {
                    "id": _next_id(f"{arm_id}_central_auto"),
                    "between": [arm_id, central_target],
                    "purpose": "structural_fixation",
                    "roles": ["fixation"],
                    "constraint_intent": "rigid",
                    "dof": {"translation": "locked", "rotation": "locked"},
                    "mating_features": ["planar_face"],
                    "description": "Deterministic arm central-link completion",
                }
            )
            connected.add(central_target)

        if not distal_ok:
            distal_target = replacement_distal
            if isinstance(distal_target, str) and distal_target not in connected:
                crs.append(
                    {
                        "id": _next_id(f"{arm_id}_distal_auto"),
                        "between": [arm_id, distal_target],
                        "purpose": "load_support",
                        "roles": ["support"],
                        "constraint_intent": "rigid",
                        "dof": {"translation": "locked", "rotation": "locked"},
                        "mating_features": ["planar_face"],
                        "description": "Deterministic arm distal-link completion",
                        "connection_semantics": {
                            "connection_mechanism": "shaft_bore_fit",
                            "relation_type": "support_member_distal_attachment",
                            "reference_component_id": arm_id,
                            "moving_component_id": distal_target,
                            "reference_anchor": _rotating_wheel_support_reference_anchor(axis="x"),
                            "moving_anchor": {"kind": "component_center"},
                            "reference_interface_hint": "distal_mount_face",
                            "moving_interface_hint": "bore_axis",
                            "orientation_policy": "locked",
                            "rationale": "Auto-filled distal arm support for a wheel axle at the arm outer end.",
                        },
                    }
                )

def _enforce_central_hub_arm_slot_mounts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    arm_ids = sorted(
        cid
        for cid, ctype in type_by_id.items()
        if ctype == "arm" and re.search(r"(?:^|_)wheel_arm_(\d+)$", cid)
    )
    if not arm_ids:
        return

    central_hub_ids = sorted(
        cid
        for cid, ctype in type_by_id.items()
        if ctype == "hub" and (cid == "central_hub" or "central" in cid.lower())
    )
    if not central_hub_ids:
        return
    hub_id = "central_hub" if "central_hub" in central_hub_ids else central_hub_ids[0]

    existing_ids = {
        cr.get("id")
        for cr in crs
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    }
    component_ids = {
        comp.get("id")
        for comp in components
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
    }

    def _next_id(prefix: str) -> str:
        idx = 1
        candidate = f"{prefix}_{idx}"
        while candidate in existing_ids:
            idx += 1
            candidate = f"{prefix}_{idx}"
        existing_ids.add(candidate)
        return candidate

    def _ensure_slot_mount_fastener_component(arm_id: str) -> str:
        fastener_id = f"{hub_id}_to_{arm_id}_fastener_set"
        if fastener_id in component_ids:
            return fastener_id

        fastener_component = {
            "id": fastener_id,
            "type": "fastener",
            "role": "fixation",
            "parent_id": hub_id,
            "position_parent": hub_id,
            "parameters": {
                "count": 1,
                "nominal_diameter": 5.0,
                "length": 25.0,
                "bundle_style": "bolt_with_nut",
                "application": "through_bolt_clamp",
            },
            "dimensions": {
                "count": 1,
                "nominal_diameter": 5.0,
                "length": 25.0,
                "bundle_style": "bolt_with_nut",
                "application": "through_bolt_clamp",
            },
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.8},
                "nominal_diameter": {"source": "inferred_default", "confidence": 0.8},
                "length": {"source": "inferred_default", "confidence": 0.7},
                "bundle_style": {"source": "inferred_default", "confidence": 0.8},
                "application": {"source": "inferred_default", "confidence": 0.8},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        components.append(fastener_component)
        component_ids.add(fastener_id)
        type_by_id[fastener_id] = "fastener"
        return fastener_id

    def _arm_phase_deg(arm_id: str, arm_index: int) -> float:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between")
            if not isinstance(between, list) or hub_id not in between or arm_id not in between:
                continue
            semantics = cr.get("connection_semantics") if isinstance(cr.get("connection_semantics"), Mapping) else {}
            reference_anchor = semantics.get("reference_anchor") if isinstance(semantics.get("reference_anchor"), Mapping) else {}
            for raw_key in ("phase_deg", "phase"):
                raw_val = reference_anchor.get(raw_key)
                if isinstance(raw_val, (int, float)):
                    return float(raw_val)
            raw_val = reference_anchor.get("phase_rad")
            if isinstance(raw_val, (int, float)):
                return math.degrees(float(raw_val))
        return float((arm_index * 120) % 360)

    repairs: list[dict[str, Any]] = []
    drop_indices: set[int] = set()

    for arm_index, arm_id in enumerate(arm_ids):
        phase_deg = _arm_phase_deg(arm_id, arm_index)
        reference_interface_hint = _phase_slot_mount_interface_name(phase_deg)
        constraint_intent, dof, mating_features = _derive_constraint_contract("structural_fixation")
        matching_indices: list[int] = []
        for idx, cr in enumerate(crs):
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                continue
            ids = {cid for cid in between if isinstance(cid, str)}
            if hub_id in ids and arm_id in ids:
                matching_indices.append(idx)

        if matching_indices:
            cr = crs[matching_indices[0]]
            between = cr.get("between") if isinstance(cr.get("between"), list) else []
            fastener_ids = [
                cid
                for cid in between
                if isinstance(cid, str) and type_by_id.get(cid) == "fastener" and cid not in {hub_id, arm_id}
            ]
            fastener_id = fastener_ids[0] if fastener_ids else _ensure_slot_mount_fastener_component(arm_id)
            cr["between"] = [hub_id, arm_id, fastener_id]
            for idx in matching_indices[1:]:
                drop_indices.add(idx)
            repair_action = "rewrote_existing_hub_arm_relation_to_slot_mount"
        else:
            fastener_id = _ensure_slot_mount_fastener_component(arm_id)
            cr = {
                "id": _next_id(f"{hub_id}_to_{arm_id}_slot_mount"),
                "between": [hub_id, arm_id, fastener_id],
            }
            crs.append(cr)
            repair_action = "inserted_missing_hub_arm_slot_mount_relation"

        raw_semantics = {
            "connection_mechanism": "axial_face_bolted_mount",
            "relation_type": "axial_face_perimeter_mount",
            "reference_component_id": hub_id,
            "moving_component_id": arm_id,
            "reference_anchor": {
                "kind": "axial_face_perimeter_max",
                "phase_deg": float(phase_deg),
            },
            "moving_anchor": {
                "kind": "proximal_end",
                "axis": "x",
                "inset_mm": 12.0,
            },
            "reference_interface_hint": reference_interface_hint,
            "moving_interface_hint": "proximal_insert_face",
            "assembly_reference_interface_hint": reference_interface_hint,
            "assembly_moving_interface_hint": "proximal_insert_face",
            "orientation_policy": "radial_from_reference_center",
            "geometric_semantics": _build_connection_geometric_semantics(
                contact_model="through_bolt_clamp_in_radial_slot",
                reference_feature_strategy="radial_slot_pocket",
                moving_feature_strategy="root_tenon_pad",
                pattern_policy="single",
                pattern_count=1,
                hardware_layout="through_bolt_external_nut_clamp",
                retention_strategy="through_bolt_clamp",
                notes="Deterministic repair: wheel arm roots must insert into central hub radial slots and be clamped by a dedicated through-bolt normal to the hub axial face.",
                support_topology="hub_radial_slot_mount",
                anti_rotation_topology="radial_slot_capture",
                mount_side="centered_z",
                axial_stack_policy="through_bolt_external_clamp",
                clearance_policy="radial_slot_clearance",
                requires_axial_offset=False,
            ),
            "rationale": "Wheel arm roots are structurally fixed to the central hub via radial slot insertion and a dedicated through-bolt clamp that passes through the hub axial face and the inserted arm root.",
        }
        sanitized = _sanitize_connection_semantics_contract(
            raw_semantics,
            valid_component_ids={hub_id, arm_id, fastener_id},
        )
        if sanitized is None:
            raise ValueError(f"Failed to sanitize repaired central hub slot mount for '{arm_id}'")

        cr["purpose"] = "fastening_mechanism"
        cr["roles"] = ["mounting", "fixation", "clamping"]
        cr["constraint_intent"] = constraint_intent
        cr["dof"] = dof
        cr["mating_features"] = mating_features
        cr["description"] = "Deterministic central hub radial slot mount with through-bolt clamp retention for the wheel arm root."
        cr["connection_semantics"] = sanitized
        cr["connection_decision"] = {
            "method": "bolted_rigid",
            "fastener_size": "M5x25",
            "count": 1,
            "fastener_ref_component_id": fastener_id,
            "stackup": "through_nut",
            "fit_policy": "clearance",
            "lock": True,
        }
        cr.pop("requires_rotation", None)
        repairs.append(
            {
                "connection_id": cr.get("id"),
                "arm_id": arm_id,
                "phase_deg": float(phase_deg),
                "action": repair_action,
                "fastener_id": fastener_id,
            }
        )

    if drop_indices:
        payload["connection_requirements"] = [
            cr for idx, cr in enumerate(crs) if idx not in drop_indices
        ]

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("central_hub_arm_slot_mount_repairs") if isinstance(metadata.get("central_hub_arm_slot_mount_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["central_hub_arm_slot_mount_repairs"] = repair_list
        payload["metadata"] = metadata

def _extract_wheel_suffix_for_component(component_id: str) -> str | None:
    if not isinstance(component_id, str) or not component_id:
        return None
    for pattern in (
        r"^wheel_arm_(\d+)$",
        r"^wheel_(\d+)_axle$",
        r"^wheel_axle_(\d+)$",
        r"^wheel_(\d+)_hub$",
        r"^wheel_(\d+)$",
    ):
        match = re.match(pattern, component_id)
        if match:
            return match.group(1)
    return None

def _is_central_hub_component_id(comp_id: str, type_by_id: Mapping[str, Any]) -> bool:
    if not isinstance(comp_id, str) or not comp_id:
        return False
    ctype = str(type_by_id.get(comp_id) or "").strip().lower()
    return comp_id == "central_hub" or (ctype == "hub" and "central" in comp_id.lower())

def _prune_rotating_wheel_support_fastening_conflicts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    rotating_pairs: set[tuple[str, str]] = set()
    support_pairs: set[tuple[str, str]] = set()

    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        wheel_ids = [cid for cid in between if type_by_id.get(cid) == "wheel"]
        hub_ids = [cid for cid in between if type_by_id.get(cid) == "hub" and _extract_wheel_suffix_for_component(cid)]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        arm_ids = [cid for cid in between if type_by_id.get(cid) == "arm"]
        if purpose == "rotation":
            for rotor_id in [*wheel_ids, *hub_ids]:
                for axle_id in axle_ids:
                    rotating_pairs.add((rotor_id, axle_id))
        if purpose in {"load_support", "support_to_structure"}:
            for arm_id in arm_ids:
                for axle_id in axle_ids:
                    support_pairs.add((arm_id, axle_id))

    kept: list[dict] = []
    repairs: list[dict] = []
    for cr in crs:
        if not isinstance(cr, dict):
            kept.append(cr)
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        if purpose not in {"fastening_mechanism", "structural_fixation"}:
            kept.append(cr)
            continue
        wheel_ids = [cid for cid in between if type_by_id.get(cid) == "wheel"]
        arm_ids = [cid for cid in between if type_by_id.get(cid) == "arm"]
        drop = False
        for wheel_id in wheel_ids:
            for arm_id in arm_ids:
                suffix = _extract_wheel_suffix_for_component(wheel_id)
                if not suffix or suffix != _extract_wheel_suffix_for_component(arm_id):
                    continue
                axle_candidates = [f"wheel_{suffix}_axle", f"wheel_axle_{suffix}"]
                rotor_candidates = [wheel_id, f"wheel_{suffix}_hub"]
                has_rotating_support_chain = any(
                    (rotor_id, axle_id) in rotating_pairs
                    for rotor_id in rotor_candidates
                    for axle_id in axle_candidates
                ) and any((arm_id, axle_id) in support_pairs for axle_id in axle_candidates)
                if has_rotating_support_chain:
                    repairs.append({
                        "connection_id": cr.get("id"),
                        "action": "dropped_direct_wheel_arm_fastening_in_rotating_support_chain",
                        "dropped_connection_id": cr.get("id"),
                    })
                    drop = True
                    break
            if drop:
                break
        if not drop:
            kept.append(cr)

    if repairs:
        payload["connection_requirements"] = kept
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("rotating_wheel_support_conflict_repairs") if isinstance(metadata.get("rotating_wheel_support_conflict_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["rotating_wheel_support_conflict_repairs"] = repair_list
        payload["metadata"] = metadata

def _prune_asymmetric_wheel_support_artifacts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    wheel_indices: set[str] = set()
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        match = re.match(r"^wheel_(\d+)$", comp_id)
        if match:
            wheel_indices.add(match.group(1))
    if len(wheel_indices) < 2:
        return

    asymmetric_wheel_indices: set[str] = set()
    for suffix in ("bearing_2", "spacer"):
        present_on: set[str] = set()
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            comp_id = comp.get("id")
            if not isinstance(comp_id, str):
                continue
            match = re.match(rf"^wheel_(\d+)_{suffix}$", comp_id)
            if match:
                present_on.add(match.group(1))
        if present_on and len(present_on) < len(wheel_indices):
            asymmetric_wheel_indices.update(present_on)

    if not asymmetric_wheel_indices:
        return

    removed_component_ids: set[str] = set()
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        match = re.match(r"^wheel_(\d+)_(bearing_2|spacer)$", comp_id)
        if match and match.group(1) in asymmetric_wheel_indices:
            removed_component_ids.add(comp_id)

    kept_crs: list[dict] = []
    removed_connection_ids: list[str] = []
    for cr in crs:
        if not isinstance(cr, dict):
            kept_crs.append(cr)
            continue
        cr_id = cr.get("id") if isinstance(cr.get("id"), str) else ""
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        drop = any(cid in removed_component_ids for cid in between)
        if not drop:
            for suffix in asymmetric_wheel_indices:
                if (
                    cr_id.startswith(f"req_wheel_{suffix}_bearing_2_")
                    or cr_id == f"req_wheel_{suffix}_spacer_axial"
                    or cr_id == f"req_wheel_{suffix}_fastener_axial_clamping"
                ):
                    drop = True
                    break
        if drop:
            if cr_id:
                removed_connection_ids.append(cr_id)
            continue
        kept_crs.append(cr)

    if not removed_component_ids and not removed_connection_ids:
        return

    payload["components"] = [
        comp
        for comp in components
        if not (isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id") in removed_component_ids)
    ]
    payload["connection_requirements"] = kept_crs

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    repairs = metadata.get("wheel_support_symmetry_repairs") if isinstance(metadata.get("wheel_support_symmetry_repairs"), list) else []
    repairs.append({
        "action": "dropped_asymmetric_wheel_support_artifacts",
        "wheel_indices": sorted(asymmetric_wheel_indices),
        "removed_component_ids": sorted(removed_component_ids),
        "removed_connection_ids": sorted(removed_connection_ids),
    })
    metadata["wheel_support_symmetry_repairs"] = repairs
    payload["metadata"] = metadata

def _prune_non_explicit_wheel_internal_fastening(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    kept_crs: list[dict] = []
    removed_connection_ids: list[str] = []
    candidate_fastener_ids: set[str] = set()

    def _matching_internal_fasteners(*, between_ids: list[str], wheel_suffix: str | None) -> list[str]:
        matches: list[str] = []
        for cid in between_ids:
            if type_by_id.get(cid) not in {"fastener", "fastener_set"}:
                continue
            if cid == "wheel_fastener_set":
                matches.append(cid)
                continue
            match = re.match(r"^wheel_(\d+)_fastener_set$", cid)
            if match and (wheel_suffix is None or match.group(1) == wheel_suffix):
                matches.append(cid)
                continue
            match = re.match(r"^central_hub_to_wheel_arm_(\d+)_fastener_set$", cid)
            if match and (wheel_suffix is None or match.group(1) == wheel_suffix):
                matches.append(cid)
        return matches

    for cr in crs:
        if not isinstance(cr, dict):
            kept_crs.append(cr)
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        if purpose not in {"fastening_mechanism", "structural_fixation"}:
            kept_crs.append(cr)
            continue

        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        wheel_ids = [cid for cid in between if type_by_id.get(cid) == "wheel"]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        wheel_suffix = next((
            _extract_wheel_suffix_for_component(cid)
            for cid in [*wheel_ids, *axle_ids]
            if _extract_wheel_suffix_for_component(cid)
        ), None)
        fastener_ids = _matching_internal_fasteners(between_ids=between, wheel_suffix=wheel_suffix)
        has_arm_or_hub_host = any(
            _is_central_hub_component_id(cid, type_by_id) or type_by_id.get(cid) in {"arm", "hub"}
            for cid in between
        )
        other_ids = [
            cid
            for cid in between
            if cid not in set(wheel_ids) and cid not in set(axle_ids) and cid not in set(fastener_ids)
        ]
        if len(fastener_ids) != 1 or has_arm_or_hub_host or other_ids:
            kept_crs.append(cr)
            continue

        fastener_id = fastener_ids[0]
        drop = False
        if len(wheel_ids) == 1 and wheel_suffix:
            compatible_fasteners = {"wheel_fastener_set", f"wheel_{wheel_suffix}_fastener_set", f"central_hub_to_wheel_arm_{wheel_suffix}_fastener_set"}
            if fastener_id in compatible_fasteners:
                if axle_ids:
                    matching_axle_id = f"wheel_{wheel_suffix}_axle"
                    if any(axle_id != matching_axle_id for axle_id in axle_ids):
                        kept_crs.append(cr)
                        continue
                drop = True
        elif not wheel_ids and len(axle_ids) == 1 and wheel_suffix:
            compatible_fasteners = {"wheel_fastener_set", f"wheel_{wheel_suffix}_fastener_set", f"central_hub_to_wheel_arm_{wheel_suffix}_fastener_set"}
            if fastener_id in compatible_fasteners:
                drop = True

        if not drop:
            kept_crs.append(cr)
            continue

        cr_id = cr.get("id") if isinstance(cr.get("id"), str) else None
        if isinstance(cr_id, str) and cr_id:
            removed_connection_ids.append(cr_id)
        candidate_fastener_ids.add(fastener_id)

    if not removed_connection_ids:
        return

    payload["connection_requirements"] = kept_crs
    surviving_refs = {
        cid
        for cr in kept_crs
        if isinstance(cr, Mapping)
        for cid in cr.get("between", [])
        if isinstance(cid, str)
    }
    removed_component_ids = {cid for cid in candidate_fastener_ids if cid not in surviving_refs}
    if removed_component_ids:
        payload["components"] = [
            comp
            for comp in components
            if not (isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id") in removed_component_ids)
        ]

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    repairs = metadata.get("wheel_internal_fastening_repairs") if isinstance(metadata.get("wheel_internal_fastening_repairs"), list) else []
    repairs.append({
        "action": "dropped_non_explicit_wheel_internal_fastening",
        "removed_connection_ids": sorted(removed_connection_ids),
        "removed_component_ids": sorted(removed_component_ids),
    })
    metadata["wheel_internal_fastening_repairs"] = repairs
    payload["metadata"] = metadata

def _prune_asymmetric_wheel_axle_auxiliary_artifacts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    wheel_indices: set[str] = set()
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        match = re.match(r"^wheel_(\d+)_axle$", comp_id)
        if match:
            wheel_indices.add(match.group(1))
    if len(wheel_indices) < 2:
        return

    def _aux_match(comp_id: str) -> tuple[str, str] | None:
        match = re.match(r"^wheel_(\d+)_axle_(retainer_left|retainer_right|spacer)$", comp_id)
        if match:
            return match.group(1), match.group(2)
        match = re.match(r"^wheel_axle_(\d+)_(retainer_left|retainer_right|spacer)$", comp_id)
        if match:
            return match.group(1), match.group(2)
        return None

    present_on: set[str] = set()
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        parsed = _aux_match(comp_id)
        if parsed is not None:
            present_on.add(parsed[0])

    if not present_on or len(present_on) == len(wheel_indices):
        return

    removed_component_ids: set[str] = set()
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        parsed = _aux_match(comp_id)
        if parsed is not None and parsed[0] in present_on:
            removed_component_ids.add(comp_id)

    kept_crs: list[dict] = []
    removed_connection_ids: list[str] = []
    for cr in crs:
        if not isinstance(cr, dict):
            kept_crs.append(cr)
            continue
        cr_id = cr.get("id") if isinstance(cr.get("id"), str) else ""
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        drop = any(cid in removed_component_ids for cid in between)
        if not drop:
            for suffix in present_on:
                if (
                    cr_id.startswith(f"req_wheel_axle_{suffix}_retainer_")
                    or cr_id.startswith(f"req_wheel_{suffix}_axle_retainer_")
                    or cr_id == f"req_wheel_axle_{suffix}_spacer"
                    or cr_id == f"req_wheel_{suffix}_axle_spacer"
                ):
                    drop = True
                    break
        if drop:
            if cr_id:
                removed_connection_ids.append(cr_id)
            continue
        kept_crs.append(cr)

    payload["components"] = [
        comp
        for comp in components
        if not (isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id") in removed_component_ids)
    ]
    payload["connection_requirements"] = kept_crs

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    repairs = metadata.get("wheel_axle_auxiliary_repairs") if isinstance(metadata.get("wheel_axle_auxiliary_repairs"), list) else []
    repairs.append({
        "action": "dropped_asymmetric_wheel_axle_auxiliary_artifacts",
        "wheel_indices": sorted(present_on),
        "removed_component_ids": sorted(removed_component_ids),
        "removed_connection_ids": sorted(removed_connection_ids),
    })
    metadata["wheel_axle_auxiliary_repairs"] = repairs
    payload["metadata"] = metadata

def _repair_illegal_wheel_axle_hub_links(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)

    def _is_central_hub_component(comp_id: str) -> bool:
        ctype = str(type_by_id.get(comp_id) or "").strip().lower()
        return comp_id == "central_hub" or (ctype == "hub" and "central" in comp_id.lower())

    repairs: list[dict] = []
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        if not between:
            continue
        central_ids = [cid for cid in between if _is_central_hub_component(cid)]
        arm_ids = [cid for cid in between if type_by_id.get(cid) == "arm"]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        if central_ids and arm_ids and axle_ids:
            cr["between"] = [cid for cid in between if cid not in axle_ids]
            repairs.append({
                "connection_id": cr.get("id"),
                "action": "removed_wheel_axle_from_central_hub_arm_relation",
                "removed_component_ids": axle_ids,
            })
            continue
        if central_ids and axle_ids and not arm_ids:
            axle_id = axle_ids[0]
            suffix = _extract_wheel_suffix_for_component(axle_id)
            matching_arm = f"wheel_arm_{suffix}" if suffix else None
            if isinstance(matching_arm, str) and type_by_id.get(matching_arm) == "arm":
                extras = [cid for cid in between if cid not in central_ids and cid not in axle_ids]
                new_between = [axle_id, matching_arm]
                for cid in extras:
                    if cid not in new_between:
                        new_between.append(cid)
                cr["between"] = new_between
                repairs.append({
                    "connection_id": cr.get("id"),
                    "action": "rewired_central_hub_wheel_axle_relation_to_matching_wheel_arm",
                    "replacement_component_id": matching_arm,
                })

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("illegal_wheel_axle_hub_link_repairs") if isinstance(metadata.get("illegal_wheel_axle_hub_link_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["illegal_wheel_axle_hub_link_repairs"] = repair_list
        payload["metadata"] = metadata

def _repair_rotating_wheel_hub_axle_fixation_links(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    rotating_axle_suffixes: set[str] = set()
    for cr in crs:
        if not isinstance(cr, Mapping) or str(cr.get("purpose") or "").strip().lower() != "rotation":
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        for cid in between:
            if type_by_id.get(cid) == "axle":
                suffix = _extract_wheel_suffix_for_component(cid)
                if suffix:
                    rotating_axle_suffixes.add(suffix)

    repairs: list[dict] = []
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        if purpose not in {"structural_fixation", "fastening_mechanism"}:
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        hub_ids = [cid for cid in between if type_by_id.get(cid) == "hub" and cid.startswith("wheel_")]
        if not axle_ids or not hub_ids:
            continue
        axle_id = axle_ids[0]
        suffix = _extract_wheel_suffix_for_component(axle_id)
        if not suffix or suffix not in rotating_axle_suffixes:
            continue
        matching_arm = f"wheel_arm_{suffix}"
        if type_by_id.get(matching_arm) != "arm":
            continue
        extras = [cid for cid in between if cid not in hub_ids and cid != axle_id]
        new_between = [axle_id, matching_arm]
        for cid in extras:
            if cid not in new_between:
                new_between.append(cid)
        cr["between"] = new_between
        repairs.append({
            "connection_id": cr.get("id"),
            "action": "rewired_rotating_wheel_hub_axle_fixation_to_support_arm",
            "replacement_component_id": matching_arm,
        })

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("rotating_wheel_hub_axle_fixation_repairs") if isinstance(metadata.get("rotating_wheel_hub_axle_fixation_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["rotating_wheel_hub_axle_fixation_repairs"] = repair_list
        payload["metadata"] = metadata

def _canonicalize_rotating_wheel_axle_support_mounts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    rotating_axle_ids: set[str] = set()
    for cr in crs:
        if not isinstance(cr, Mapping) or str(cr.get("purpose") or "").strip().lower() != "rotation":
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        wheel_ids = [cid for cid in between if type_by_id.get(cid) == "wheel"]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        if wheel_ids and axle_ids:
            rotating_axle_ids.update(axle_ids)

    repairs: list[dict] = []
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        axle_ids = [cid for cid in between if cid in rotating_axle_ids]
        arm_ids = [cid for cid in between if type_by_id.get(cid) == "arm"]
        if not axle_ids or not arm_ids:
            continue
        axle_id = axle_ids[0]
        arm_id = arm_ids[0]
        if _extract_wheel_suffix_for_component(axle_id) != _extract_wheel_suffix_for_component(arm_id):
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        if purpose not in {"structural_fixation", "fastening_mechanism", "load_support"}:
            continue
        cr["between"] = [axle_id, arm_id]
        cr["purpose"] = "load_support"
        cr["mating_features"] = ["axis", "seat"]
        cr.pop("connection_decision", None)
        cr["connection_semantics"] = {
            "connection_mechanism": "shaft_bore_fit",
            "relation_type": "support_member_distal_attachment",
            "reference_component_id": arm_id,
            "moving_component_id": axle_id,
            "reference_anchor": _rotating_wheel_support_reference_anchor(axis="x"),
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "distal_mount_face",
            "moving_interface_hint": "shaft_axis",
            "orientation_policy": "inherit_reference_yaw",
            "geometric_semantics": _build_rotating_wheel_support_geometric_semantics(
                notes="Canonicalized rotating wheel axle support to a forked dropout support contract."
            ),
            "rationale": "Canonicalized rotating wheel axle support must keep the wheel body outboard of the support arm while preserving free wheel rotation.",
        }
        repairs.append({
            "connection_id": cr.get("id"),
            "action": "canonicalized_rotating_wheel_axle_support_to_shaft_seat",
        })

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("rotating_wheel_axle_support_mount_repairs") if isinstance(metadata.get("rotating_wheel_axle_support_mount_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["rotating_wheel_axle_support_mount_repairs"] = repair_list
        payload["metadata"] = metadata

def _rewire_rotating_wheel_container_rotation_hosts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    parent_by_id: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        parent_id = comp.get("parent_id")
        if not isinstance(parent_id, str) or not parent_id:
            parent_id = comp.get("position_parent") if isinstance(comp.get("position_parent"), str) else None
        if isinstance(parent_id, str) and parent_id:
            parent_by_id[cid] = parent_id

    repairs: list[dict[str, Any]] = []
    for cr in crs:
        if not isinstance(cr, dict):
            continue
        purpose = str(cr.get("purpose") or "").strip().lower()
        if purpose != "rotation":
            continue

        between = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
        wheel_ids = [cid for cid in between if type_by_id.get(cid) == "wheel"]
        axle_ids = [cid for cid in between if type_by_id.get(cid) == "axle"]
        if not wheel_ids or not axle_ids:
            continue

        wheel_id = wheel_ids[0]
        axle_id = axle_ids[0]
        suffix = _extract_wheel_suffix_for_component(wheel_id) or _extract_wheel_suffix_for_component(axle_id)
        if not suffix:
            continue

        hub_candidates: list[str] = []
        preferred_hub = f"wheel_{suffix}_hub"
        if type_by_id.get(preferred_hub) == "hub":
            hub_candidates.append(preferred_hub)
        for cid, parent_id in sorted(parent_by_id.items()):
            if parent_id == wheel_id and type_by_id.get(cid) == "hub" and cid not in hub_candidates:
                hub_candidates.append(cid)
        if not hub_candidates:
            continue

        hub_id = hub_candidates[0]
        new_between = [hub_id if cid == wheel_id else cid for cid in between]
        unique_between = list(dict.fromkeys(new_between))
        if len(unique_between) < 2:
            continue
        cr["between"] = unique_between

        contract = {
            "connection_mechanism": "shaft_bore_fit",
            "relation_type": "shaft_axis_to_bore",
            "reference_component_id": axle_id,
            "moving_component_id": hub_id,
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
                notes="Canonicalized wheel rotation host from container node to physical hub.",
            ),
            "rationale": "Rotating wheel closure must terminate on the physical wheel hub, not a hierarchy-only wheel container.",
        }
        sanitized = _sanitize_connection_semantics_contract(contract, valid_component_ids=set(unique_between))
        if sanitized is not None:
            cr["connection_semantics"] = sanitized

        repairs.append(
            {
                "connection_id": cr.get("id"),
                "action": "rewired_rotating_wheel_container_rotation_to_physical_hub",
                "original_container_id": wheel_id,
                "replacement_component_id": hub_id,
            }
        )

    if repairs:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        repair_list = metadata.get("rotating_wheel_container_rotation_repairs") if isinstance(metadata.get("rotating_wheel_container_rotation_repairs"), list) else []
        repair_list.extend(repairs)
        metadata["rotating_wheel_container_rotation_repairs"] = repair_list
        payload["metadata"] = metadata

def _validate_wheel_arm_connection_topology(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    crs = kg.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)
    parent_by_id: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        parent_id = comp.get("parent_id")
        if isinstance(cid, str) and isinstance(parent_id, str):
            parent_by_id[cid] = parent_id

    arm_ids: list[str] = []
    for cid, ctype in type_by_id.items():
        if ctype != "arm":
            continue
        m = re.search(r"(?:^|_)wheel_arm_(\d+)$", cid)
        if m:
            arm_ids.append(cid)
    if not arm_ids:
        return

    central_hub_ids = {
        cid
        for cid, ctype in type_by_id.items()
        if ctype == "hub" and (cid == "central_hub" or "central" in cid.lower())
    }

    if "central_hub" in type_by_id:
        central_hub_ids.add("central_hub")

    def _distal_candidates(suffix: str) -> list[str]:
        candidates: list[str] = []
        for cid in (f"wheel_{suffix}_hub", f"wheel_{suffix}_axle", f"wheel_axle_{suffix}"):
            if cid in type_by_id and cid not in candidates:
                candidates.append(cid)

        wheel_container = _resolve_wheel_container(suffix, type_by_id)
        if isinstance(wheel_container, str):
            semantic_children = [
                cid
                for cid, parent_id in parent_by_id.items()
                if parent_id == wheel_container and str(type_by_id.get(cid) or "").lower() in {"hub", "axle"}
            ]
            for cid in sorted(semantic_children):
                if cid not in candidates:
                    candidates.append(cid)
        return candidates

    issues: list[str] = []
    warnings: list[str] = []

    for arm_id in sorted(arm_ids):
        suffix_match = re.search(r"(?:^|_)wheel_arm_(\d+)$", arm_id)
        if not suffix_match:
            continue
        suffix = suffix_match.group(1)
        required_distals = set(_distal_candidates(suffix))
        wheel_container = _resolve_wheel_container(suffix, type_by_id)
        enforce_distal = bool(isinstance(wheel_container, str) and required_distals)

        has_central = False
        has_required_distal = False
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if not isinstance(between, list) or arm_id not in between:
                continue

            for other in between:
                if not isinstance(other, str) or other == arm_id:
                    continue
                if other in central_hub_ids:
                    has_central = True
                if other in required_distals:
                    has_required_distal = True

                if _is_cross_index_target(suffix, other):
                    cr_id = cr.get("id") if isinstance(cr.get("id"), str) else "<unknown>"
                    issues.append(
                        f"Cross-index wheel-arm link detected: {arm_id} -> {other} in connection_requirement '{cr_id}'"
                    )

        if not has_central:
            issues.append(f"Missing required central hub link: {arm_id} must connect to central_hub")
        if enforce_distal and not has_required_distal:
            issues.append(
                f"Missing required distal link: {arm_id} must connect to one of {sorted(required_distals)}"
            )
        if not enforce_distal:
            warnings.append(
                f"Distal enforcement downgraded to warning for {arm_id}: wheel container or hub/axle child candidates not found"
            )

    metadata = kg.get("metadata") if isinstance(kg.get("metadata"), Mapping) else {}
    metadata_mut = dict(metadata)
    metadata_mut["wheel_arm_topology_warnings"] = warnings
    kg["metadata"] = metadata_mut

    if issues:
        raise ValueError(
            "Validation failed: wheel-arm topology constraint violation. "
            + " ".join(issues)
        )

def _ensure_module_subassembly_interfaces(payload: Dict[str, Any]) -> None:
    """
    Ensure module-level subassemblies have at least one external connection_requirement
    so downstream interface generation cannot produce zero interfaces.
    This adds NO coordinates and does NOT list subassembly members together with the subassembly.
    """
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    subassemblies = payload.get("subassemblies", [])
    if not isinstance(subassemblies, list):
        subassemblies = []

    crs = payload.get("connection_requirements", [])
    if not isinstance(crs, list):
        return

    type_by_id = _build_type_map(components)

    members_by_sa_id: dict[str, set[str]] = {}
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        members = sa.get("component_ids", [])
        if isinstance(sa_id, str) and isinstance(members, list):
            members_by_sa_id[sa_id] = {m for m in members if isinstance(m, str)}

    # Also infer members from parent_id in components[]
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        parent_id = comp.get("parent_id")
        if isinstance(comp_id, str) and isinstance(parent_id, str):
            if parent_id not in members_by_sa_id:
                members_by_sa_id[parent_id] = set()
            members_by_sa_id[parent_id].add(comp_id)

    module_sa_ids = []
    # Check subassemblies[] for true top-level modules.
    # NOTE: Do not treat role strings like "rotational_module" as module-level;
    # wheel_*_assembly subassemblies should not get synthetic external interfaces.
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        if not isinstance(sa_id, str):
            continue
        sa_id_lower = sa_id.lower()
        if ("module" in sa_id_lower) or sa_id_lower.endswith("_module"):
            module_sa_ids.append(sa_id)

    # Check components[] for type="module" (and only subassemblies that explicitly
    # declare themselves as modules via naming/role conventions).
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        comp_type = comp.get("type")
        if not isinstance(comp_id, str):
            continue
        if comp_type == "module" and comp_id not in module_sa_ids:
            module_sa_ids.append(comp_id)
            continue

        if comp_type == "subassembly":
            comp_id_lower = comp_id.lower()
            if ("module" in comp_id_lower or comp_id_lower.endswith("_module")) and comp_id not in module_sa_ids:
                module_sa_ids.append(comp_id)

    def has_external_connection(sa_id: str) -> bool:
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if not isinstance(between, list):
                continue
            if sa_id in between:
                return True
        return False

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

    for sa_id in module_sa_ids:
        if has_external_connection(sa_id):
            continue

        members = members_by_sa_id.get(sa_id, set())
        
        # For top-level modules (type="module"), also consider all subassemblies as indirect members
        comp_type = type_by_id.get(sa_id, "")
        if comp_type == "module":
            # Include all components with parent_id = sa_id (already in members)
            # Also include all subassemblies as they conceptually belong to the module
            sa_ids_set = {sa.get("id") for sa in subassemblies if isinstance(sa, Mapping) and isinstance(sa.get("id"), str)}
            # Include all components within those subassemblies
            for sa in subassemblies:
                if not isinstance(sa, Mapping):
                    continue
                sa_members = sa.get("component_ids", [])
                if isinstance(sa_members, list):
                    members.update(m for m in sa_members if isinstance(m, str))
            # Include subassembly IDs themselves
            members.update(sa_ids_set)
        
        all_component_ids = {cid for cid in type_by_id.keys()}
        external_ids = all_component_ids - members - {sa_id}

        # Find target component for external interface
        target_id: str | None = None
        
        # Priority 1: Drive/input shaft outside the module
        if external_ids:
            for cid in external_ids:
                cid_lower = cid.lower()
                if ("drive" in cid_lower or "input" in cid_lower) and type_by_id.get(cid) in {
                    "shaft",
                    "axle",
                }:
                    target_id = cid
                    break

        # Priority 2: Structural/frame components outside the module
        if target_id is None and external_ids:
            for cid in external_ids:
                ctype = type_by_id.get(cid, "")
                if any(
                    token in ctype.lower()
                    for token in ["frame", "base", "housing", "mount", "bracket", "structure"]
                ):
                    target_id = cid
                    break

        # Priority 3: Any external component (excluding fasteners)
        if target_id is None and external_ids:
            for cid in sorted(external_ids):  # Deterministic: sorted by ID
                if type_by_id.get(cid) != "fastener":  # Never pick fastener as target
                    target_id = cid
                    break
        
        # Fallback: use external component even if fastener (shouldn't happen often)
        if target_id is None and external_ids:
            target_id = next(iter(sorted(external_ids)), None)

        # Fallback for top-level modules: use core component that's NOT a direct member
        # This handles cases where module encompasses entire KG with no genuine external components
        # Must select a component that's logically part of the module but not a direct member (no parent_id)
        if target_id is None:
            original_members = members_by_sa_id.get(sa_id, set())
            # Search all components for hub/central that's NOT in direct members
            # (central_hub often has no parent_id but is the core of the module)
            for cid in all_component_ids:
                if cid == sa_id or cid in original_members:
                    continue
                if type_by_id.get(cid) == "fastener":
                    continue  # Skip fasteners
                if "hub" in cid.lower() or "central" in cid.lower():
                    target_id = cid
                    break
            # By type: hub/base/frame not in direct members
            if target_id is None:
                for cid in all_component_ids:
                    if cid == sa_id or cid in original_members:
                        continue
                    if type_by_id.get(cid) == "fastener":
                        continue  # Skip fasteners
                    if type_by_id.get(cid) in {"hub", "base", "frame"}:
                        target_id = cid
                        break
            # Last resort: any component not in direct members (and not fastener)
            if target_id is None:
                for cid in sorted(all_component_ids):  # Deterministic: sorted
                    if cid != sa_id and cid not in original_members:
                        if type_by_id.get(cid) != "fastener":
                            target_id = cid
                            break

        if target_id is None:
            continue

        is_drive_shaft = ("drive" in target_id.lower() or "input" in target_id.lower()) and type_by_id.get(
            target_id
        ) in {"shaft", "axle"}
        purpose = "torque_transfer" if is_drive_shaft else "structural_fixation"

        crs.append(
            {
                "id": _next_id(f"{sa_id}_external_interface_auto"),
                "between": [sa_id, target_id],
                "purpose": purpose,
                "description": "Deterministic module external interface completion",
            }
        )


__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
