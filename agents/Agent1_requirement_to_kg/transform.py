"""Agent1: 闂傚洠鍋撴慨鐟板€搁崺宀勬儗閵夈劎妲曢柛銉﹀礃濮樸劍娼浣稿簥 (requirement_to_kg)

闁煎崬鐭侀惌妤呮嚑閸愩劍绾柨?    - 閻熸瑱绲鹃悗浠嬫嚊椤忓棗濮ч悹鍥跺弨閳诲牓妫侀埀顒€效閸岋妇绀夐柣銏㈠枑閸ㄦ岸骞庨崐鐔绘澖閻犲浂鍘虹粻鐔兼儗閵夈劎妲曢柛銉﹀礃濮?        - 閺夊牊鎸搁崵顓熸交閻愭潙澶嶉梻鍥ｅ亾婵懓鍊堕埀顑跨閼镐即鎮╅幆閭﹀殧濞戞柨顦埀顑跨閺勫倻鈧敻鏅茬花銊р偓鍦仒缁楀矂寮介崶褍娅欏ù鐘茬埣閳ь剙顦扮€?        - 濞戞挸绉存禒娑㈠礄閻樿京绉块柛褎鍔栭悥锝夊礃瀹曞洨鎽滈柨娑樼墕濞兼寮介崶銉㈠亾娴ｅ憡缍忛柡宥呮川闁挳濡存担浠嬪彙缂佹崘锟ラ埀顑挎缂嶅懐绱旈鍡欑
        - 濞戞挸绉存禒姹D鐎点倗鍎よ啯婵縿鍎甸鍐晬閸絽纾搁柛?闁瑰嘲顦崙?闁哄啫顑堝ù鍡涙晬?        - 濞戞挸绉风欢顓㈠礄?relations闁挎稑鐗嗛崣褏鍖栭懡銈堫潶闁搞劌顑囬弫杈ㄧ▔鐎ｎ偆鍩楅柛鎰暱閻ｉ箖鏁?
閺夊牊鎸搁崵顓㈠礃閸涱収鍟囬柨?    - components: 闁圭鍋撻柡鍫濐樀濞村倹绂掔拋鍦闁哄嫭鍎崇槐?+ 闁规亽鍔岄閬嶅礄閾忚鐣遍弶鈺冨仦鐢瓨绂?閺夌偛鐡ㄦ竟?閺夌偛顕悺鎴︽晬?    - subassemblies: 閻犲浂鍘虹粻鐔煎礆閸℃瑧鐭?    - connection_requirements: 闁硅泛鈧喕鏉介弶鈺冨仦鐢挳妫侀埀顒€效閸岋妇绀刾urpose + roles + constraints闁?    - standard_parts: 闁哄秴娲ら崳顖涚鐠鸿櫣鈧兘宕ｉ悜瑙ｅ亾婢跺顏ョ紓浣规尰閻?    - patterns: 閻庨潧婀辫ⅷ闁诡儸鍐╁闂佹彃绉撮ˇ鎻捨熼垾宕囩
    - design_intents: 濡ゅ倹锚閻壆鐥敂鑺ュ皢

濡ょ姴鐭侀惁澶愭焻閺勫繒甯嗛柨?  - 缂備焦鎸婚悗顖溾偓鐟版湰閺嗭綁骞€瑜濈槐鐧碼steners/bearings/shafts闊洤鎳橀妴蹇涘礄閾忕懓绠涢柛锔规殙onnection_requirements濞?  - 閻犲浂鍘虹粻鐔兼⒒椤撶偛鐦堕悷娆忓閸垶鏁嶅娓哸ring闂傚洠鍋撻悷鏇氬嬀oad_support + support_to_structure闁挎稒纭瀐aft闂傚洠鍋撻悷鏇氳喘otation/torque_transfer + structural_fixation
    - 婵炲鍔嶉崜浼存晬濮樺墎宕ｉ悹鍥︾瑜把囧磻濮樻剚鍤斿☉鏂款樀濡挳宕?閻庣懓鏈弳锝夊箑瑜庨ˉ鍛村蓟閵夘垳绀夊☉鎾崇Т閸犲懐鈧鑹鹃崵鎴炴媴閺囩偟鏉介柣婊勫缁繘鎳?
濞戞挸顑嗛悥绂攇ent闁?    - Agent2闁挎稒纰嶇敮鍦偓鐢靛帶閸ゆ垶鎷呴弴鈽嗗殧濞戞柨顦粭宀勫礂瀹曞洭鍏囩紒顐ヮ嚙閻庣兘鏁嶇仦鎴掔驳濞戞挴鍋撻柤宄扮摠閳ь儸鍕ⅰ濡?    - Agent4闁挎稒纰嶇敮鍦偓浣冨椤ュ﹪鏌婂鍫悁闁告帗甯槐婵嬪磻濮橆偆顏遍柤宄扮摠閳ь儸鍕ⅰ濡?"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

import yaml
from jsonschema import Draft202012Validator
from agents.common_utils import extract_json_from_llm_response
from tools.catalog.bearing_catalog import (
    candidate_series_for_bore,
    find_bearing_by_designation,
    nearest_bearing_by_dims,
    select_bearing_by_series_and_bore,
)


FASTENER_DIAMETERS = [2, 3, 4, 5, 6, 8, 10, 12]
FASTENER_LENGTHS = [4, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 50]
STANDARD_SHAFT_DIAMETERS = [6, 8, 10, 12]
DECOMPOSITION_CONFIDENCE_THRESHOLD = 0.72
DECOMPOSITION_MAX_ADDED_RATIO = 1.25

FEATURE_LIKE_TYPES = {
    "feature",
    "hole",
    "slot",
    "fillet",
    "chamfer",
    "thread",
    "groove",
    "pocket",
    "boss",
}


def _nearest_option(value: float, options: list[int]) -> int:
    return min(options, key=lambda x: abs(x - value))


def _nearest_fastener_designation(nominal: float, length: float) -> str:
    dia = _nearest_option(float(nominal), FASTENER_DIAMETERS)
    leng = _nearest_option(float(length), FASTENER_LENGTHS)
    return f"M{int(dia)}x{int(leng)}"


def _is_fastener_family_type(component_type: str | None) -> bool:
    if not isinstance(component_type, str):
        return False
    value = component_type.strip().lower()
    return value in {
        "fastener",
        "fastener_set",
        "bolt_set",
        "nut_set",
        "bolt",
        "screw",
        "nut",
        "washer",
        "pin",
        "key",
        "rivet",
        "spacer",
        "standoff_set",
    }


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_purpose(purpose: str | None) -> str:
  if not isinstance(purpose, str):
    return ""
  value = purpose.strip().lower()
  mapping = {
    "support": "support_to_structure",
    "bearing_support": "support_to_structure",
    "bearing_seat": "support_to_structure",
    "support_to_structure": "support_to_structure",
    "load_support": "load_support",
    "load_bearing": "load_support",
    "fixation": "structural_fixation",
    "structural_fixation": "structural_fixation",
    "clamping": "structural_clamping",
    "structural_clamping": "structural_clamping",
    "fastening": "fastening_mechanism",
    "fastening_mechanism": "fastening_mechanism",
    "bolted_joint": "fastening_mechanism",
    "bolted": "fastening_mechanism",
    "rotation": "rotation",
    "torque_transfer": "torque_transfer",
    "alignment": "alignment",
    "spacing": "spacing",
  }
  return mapping.get(value, value)


def _derive_roles_from_purpose(purpose: str) -> list[str]:
    """Derive semantic roles from normalized connection purpose."""
    purpose_to_roles = {
        "rotation": {"rotation"},
        "torque_transfer": {"rotation", "torque_transfer"},
        "structural_fixation": {"mounting", "fixation"},
        "structural_clamping": {"mounting"},
        "fastening_mechanism": {"mounting", "fixation"},
        "support_to_structure": {"support"},
        "load_support": {"support"},
        "alignment": {"mounting"},
        "spacing": {"mounting"},
    }
    roles = purpose_to_roles.get(purpose, {"mounting"})
    return sorted(roles)


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
        anchor["axis"] = axis.strip().lower()
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


def _infer_part_kind_and_policy(component: Mapping[str, Any]) -> tuple[str, str]:
    component_type = str(component.get("type", "")).strip().lower()
    component_id = str(component.get("id", "")).strip().lower()

    if component_type == "subassembly":
        return ("subassembly", "reference_only")
    if component_type in {"bearing"}:
        return ("bearing", "simplified_model")
    if component_type in {"shaft", "axle"}:
        return ("shaft", "must_model")
    if component_type in {"fastener", "fastener_set", "bolt_set"}:
        return ("fastener_bundle", "simplified_model")
    if component_type in {"bolt", "screw"}:
        return ("bolt", "simplified_model")
    if component_type in {"nut", "nut_set"}:
        return ("nut", "simplified_model")
    if component_type in {"washer"}:
        return ("washer", "simplified_model")
    if component_type in {"pin"}:
        return ("pin", "simplified_model")
    if component_type in {"key"}:
        return ("key", "must_model")
    if component_type in {"spacer", "standoff_set"}:
        return ("spacer", "simplified_model")
    if any(tag in component_id for tag in ("fastener", "bolt", "screw", "nut", "washer", "pin", "key", "spacer")):
        return ("connector", "simplified_model")
    if component_type:
        return ("structural", "must_model")
    return ("other", "must_model")


_ASSEMBLY_ONLY_COMPONENT_TYPES = {"subassembly", "assembly", "module"}
_PHYSICAL_PART_TYPES = {
    "arm",
    "axle",
    "bar",
    "base",
    "beam",
    "bearing",
    "block",
    "bolt",
    "body",
    "bracket",
    "bushing",
    "cap",
    "carrier",
    "clamp",
    "cover",
    "disc",
    "flange",
    "frame",
    "gear",
    "handle",
    "housing",
    "hub",
    "key",
    "nut",
    "pin",
    "plate",
    "pulley",
    "rim",
    "ring",
    "rod",
    "roller",
    "screw",
    "seal",
    "shaft",
    "shell",
    "spacer",
    "standoff",
    "tire",
    "washer",
    "wheel_arm",
}


def _has_positive_dimensions(component: Mapping[str, Any]) -> bool:
    dims = component.get("dimensions")
    if not isinstance(dims, Mapping):
        return False
    for value in dims.values():
        if isinstance(value, (int, float)) and float(value) > 0.0:
            return True
    return False


def _shape_semantics_indicates_physical_geometry(component: Mapping[str, Any]) -> bool:
    shape = component.get("shape_semantics")
    if not isinstance(shape, Mapping):
        return False
    shape_type = str(shape.get("type") or "").strip().lower()
    if shape_type and shape_type not in {"assembly_node", "unknown", "logical", "container"}:
        return True
    return any(
        key in shape
        for key in ("cross_section", "geometry_type", "profile_type", "outer_profile", "features")
    )


def _is_physical_part_candidate(component: Mapping[str, Any]) -> bool:
    component_type = str(component.get("type") or "").strip().lower()
    if component_type in _ASSEMBLY_ONLY_COMPONENT_TYPES:
        return False
    if component_type in _PHYSICAL_PART_TYPES:
        return True

    part_kind = str(component.get("part_kind") or "").strip().lower()
    if part_kind in {
        "bearing",
        "bolt",
        "connector",
        "key",
        "nut",
        "pin",
        "shaft",
        "spacer",
        "structural",
        "washer",
    }:
        return True

    return _shape_semantics_indicates_physical_geometry(component) or _has_positive_dimensions(component)


def _normalize_component_contract_fields(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        inferred_kind, inferred_policy = _infer_part_kind_and_policy(comp)
        part_kind = comp.get("part_kind")
        modeling_policy = comp.get("modeling_policy")
        comp["part_kind"] = part_kind if isinstance(part_kind, str) and part_kind.strip() else inferred_kind
        comp["modeling_policy"] = (
            modeling_policy if isinstance(modeling_policy, str) and modeling_policy.strip() else inferred_policy
        )


def _collect_component_hierarchy_candidates(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    components = payload.get("components")
    if not isinstance(components, list):
        return {}, {}

    by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id"):
            by_id[str(comp["id"])] = comp
    if not by_id:
        return {}, {}

    children_by_parent: Dict[str, List[str]] = {}
    for comp_id, comp in by_id.items():
        for parent_field in ("position_parent", "parent_id"):
            parent = comp.get(parent_field)
            if isinstance(parent, str) and parent in by_id and parent != comp_id:
                children_by_parent.setdefault(parent, []).append(comp_id)
                break

    wheel_child_types = {"rim", "tire", "hub", "axle", "bearing", "spacer", "fastener"}
    for parent_id, parent_comp in by_id.items():
        parent_type = str(parent_comp.get("type") or "").strip().lower()
        parent_shape = parent_comp.get("shape_semantics")
        parent_shape_type = (
            str(parent_shape.get("type") or "").strip().lower()
            if isinstance(parent_shape, Mapping)
            else ""
        )
        parent_id_l = parent_id.lower()
        looks_like_wheel_parent = (
            parent_type == "wheel"
            or parent_shape_type == "wheel"
            or bool(re.match(r"^wheel_\d+$", parent_id_l))
        )
        if not looks_like_wheel_parent:
            continue

        inferred_children = set(children_by_parent.get(parent_id, []))
        for cid, comp in by_id.items():
            if cid == parent_id:
                continue
            ctype = str(comp.get("type") or "").strip().lower()
            if ctype not in wheel_child_types:
                continue
            cid_l = cid.lower()
            if parent_id_l in cid_l or cid_l.startswith(f"{parent_id_l}_"):
                inferred_children.add(cid)
        if inferred_children:
            children_by_parent[parent_id] = sorted(inferred_children)

    normalized_children: Dict[str, List[str]] = {}
    for parent_id, children in children_by_parent.items():
        uniq_children = sorted(
            {
                child_id
                for child_id in children
                if isinstance(child_id, str) and child_id in by_id and child_id != parent_id
            }
        )
        if uniq_children:
            normalized_children[parent_id] = uniq_children

    return by_id, normalized_children


def _mark_component_as_container_only(comp: Dict[str, Any], *, note: str | None = None) -> None:
    comp["kind"] = "assembly_node"
    comp["is_container_only"] = True
    comp["is_container"] = True
    comp["has_geometry"] = False
    comp["must_model"] = False
    comp["modeling_policy"] = "container_only"
    comp["dimensions"] = {}
    comp["parameters"] = {}
    comp["dimension_sources"] = {}
    comp["is_modeling_unit"] = False

    shape = comp.get("shape_semantics")
    existing_note = shape.get("notes") if isinstance(shape, Mapping) else None
    final_note = note or (existing_note if isinstance(existing_note, str) and existing_note.strip() else None)
    comp["shape_semantics"] = {"type": "assembly_node"}
    if isinstance(final_note, str) and final_note.strip():
        comp["shape_semantics"]["notes"] = final_note.strip()


def _preserve_hierarchy_parent_as_physical(component: Mapping[str, Any]) -> bool:
    """True when a hierarchy parent still needs its own geometry."""
    component_type = str(component.get("type") or "").strip().lower()
    if component_type in _ASSEMBLY_ONLY_COMPONENT_TYPES or component_type in {"wheel"}:
        return False

    if component_type in _PHYSICAL_PART_TYPES:
        return True

    part_kind = str(component.get("part_kind") or "").strip().lower()
    if part_kind in {
        "bearing",
        "bolt",
        "connector",
        "key",
        "nut",
        "pin",
        "shaft",
        "spacer",
        "structural",
        "washer",
    }:
        return True

    if _has_positive_dimensions(component):
        return True

    shape = component.get("shape_semantics")
    if isinstance(shape, Mapping):
        return any(
            key in shape
            for key in ("cross_section", "geometry_type", "profile_type", "outer_profile", "features")
        )

    return False


def _mark_component_as_physical_part(comp: Dict[str, Any]) -> None:
    inferred_part_kind, inferred_policy = _infer_part_kind_and_policy(comp)
    if inferred_policy == "reference_only":
        inferred_policy = "must_model"
    comp["kind"] = "part"
    comp["part_kind"] = inferred_part_kind
    comp["must_model"] = True
    comp["modeling_policy"] = inferred_policy
    comp["is_container"] = False
    comp["is_container_only"] = False
    comp["has_geometry"] = True
    comp["is_modeling_unit"] = True


def _normalize_component_kind_and_must_model(kg: Dict[str, Any]) -> None:
    """Hard contract for hierarchy vs geometry modeling.

    - kind='assembly_node' => hierarchy-only organizer node, must_model=false
    - kind='part'          => real geometric part (may be simplified), must_model=true

    This intentionally makes downstream filtering deterministic.
    """

    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    meta = kg.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        kg["metadata"] = meta
    warnings_list = meta.get("normalization_warnings")
    if not isinstance(warnings_list, list):
        warnings_list = []
        meta["normalization_warnings"] = warnings_list

    seen_ids: set[str] = set()
    dup_ids: set[str] = set()
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if isinstance(cid, str) and cid:
            if cid in seen_ids:
                dup_ids.add(cid)
            seen_ids.add(cid)
    if dup_ids:
        raise ValueError(f"Duplicate component ids in KG are forbidden: {sorted(dup_ids)}")

    def _looks_like_assembly_node(comp: Mapping[str, Any]) -> bool:
        comp_type = comp.get("type")
        part_kind = comp.get("part_kind")
        modeling_policy = comp.get("modeling_policy")
        is_container = comp.get("is_container")
        is_modeling_unit = comp.get("is_modeling_unit")
        cid = comp.get("id")
        cid_s = cid if isinstance(cid, str) else ""
        type_s = comp_type.strip().lower() if isinstance(comp_type, str) else ""
        pk_s = part_kind.strip().lower() if isinstance(part_kind, str) else ""
        mp_s = modeling_policy.strip().lower() if isinstance(modeling_policy, str) else ""

        if mp_s == "reference_only":
            return True
        if pk_s == "subassembly" or type_s in _ASSEMBLY_ONLY_COMPONENT_TYPES:
            return True
        if _is_physical_part_candidate(comp):
            return False
        if bool(is_container) is True:
            return True
        if bool(is_modeling_unit) is False and is_modeling_unit is not None:
            return True
        if "assembly" in cid_s.lower() or cid_s.lower().endswith("_module"):
            return True
        return False
    for comp in components:
        if not isinstance(comp, dict):
            continue

        cid = comp.get("id")
        comp_id = cid if isinstance(cid, str) else "<unknown>"

        kind_raw = comp.get("kind")
        kind = kind_raw.strip() if isinstance(kind_raw, str) else None
        must_model_raw = comp.get("must_model")
        must_model = must_model_raw if isinstance(must_model_raw, bool) else None

        modeling_policy = comp.get("modeling_policy")
        mp_s = modeling_policy.strip().lower() if isinstance(modeling_policy, str) else ""

        inferred_kind = "assembly_node" if _looks_like_assembly_node(comp) else "part"
        inferred_must_model = inferred_kind == "part" and mp_s != "reference_only"

        if kind not in {"assembly_node", "part"}:
            kind = inferred_kind
        if must_model is None:
            must_model = bool(inferred_must_model)

        # Auto-fix common LLM drift: never block pipeline for mixed intent.
        # If a node looks like a container (e.g. *_module) but explicitly asks to be modeled,
        # treat it as a real part. This preserves references and enables downstream geometry.
        if kind == "assembly_node" and mp_s in {"must_model", "simplified_model"}:
            warnings_list.append(
                {
                    "code": "autofix_mixed_modeling_intent",
                    "component_id": comp_id,
                    "from": {"kind": "assembly_node", "modeling_policy": mp_s},
                    "to": {"kind": "part", "must_model": True},
                    "message": "Auto-fixed mixed modeling intent: coerced assembly_node to part because modeling_policy requires geometry",
                }
            )
            kind = "part"
            must_model = True

        if kind == "assembly_node" and mp_s != "reference_only" and _is_physical_part_candidate(comp):
            inferred_part_kind, inferred_policy = _infer_part_kind_and_policy(comp)
            if inferred_policy == "reference_only":
                inferred_policy = "must_model"
            warnings_list.append(
                {
                    "code": "autofix_physical_part_mislabeled_as_assembly",
                    "component_id": comp_id,
                    "from": {
                        "kind": "assembly_node",
                        "modeling_policy": mp_s or comp.get("modeling_policy"),
                        "is_container": comp.get("is_container"),
                        "is_modeling_unit": comp.get("is_modeling_unit"),
                    },
                    "to": {
                        "kind": "part",
                        "must_model": True,
                        "modeling_policy": inferred_policy,
                        "part_kind": inferred_part_kind,
                    },
                    "message": "Auto-fixed physical component mislabeled as assembly_node because it carries geometric part evidence",
                }
            )
            comp["part_kind"] = inferred_part_kind
            comp["modeling_policy"] = inferred_policy
            mp_s = inferred_policy.lower()
            kind = "part"
            must_model = True

        # Symmetric fix: a part cannot be reference_only; coerce to assembly_node.
        if kind == "part" and mp_s == "reference_only":
            warnings_list.append(
                {
                    "code": "autofix_part_reference_only",
                    "component_id": comp_id,
                    "from": {"kind": "part", "modeling_policy": mp_s},
                    "to": {"kind": "assembly_node", "must_model": False, "modeling_policy": "reference_only"},
                    "message": "Auto-fixed invalid part contract: coerced part to assembly_node because modeling_policy=reference_only",
                }
            )
            kind = "assembly_node"
            must_model = False

        # Hard normalization: assembly_node can never be modeled.
        if kind == "assembly_node":
            comp["kind"] = "assembly_node"
            comp["must_model"] = False
            comp["modeling_policy"] = "reference_only"
            comp["is_container"] = True
            comp["is_container_only"] = True
            comp["has_geometry"] = False
            comp["is_modeling_unit"] = False
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            shape = comp.get("shape_semantics")
            notes = None
            if isinstance(shape, Mapping):
                notes = shape.get("notes")
            comp["shape_semantics"] = {"type": "assembly_node"}
            if isinstance(notes, str) and notes.strip():
                comp["shape_semantics"]["notes"] = notes
            continue

        # kind == 'part'
        if mp_s == "reference_only":
            # Parts that should not be modeled must be expressed as assembly_node.
            # This should have been auto-fixed above, but keep a safe fallback.
            comp["kind"] = "assembly_node"
            comp["must_model"] = False
            comp["modeling_policy"] = "reference_only"
            comp["is_container"] = True
            comp["is_container_only"] = True
            comp["has_geometry"] = False
            comp["is_modeling_unit"] = False
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            comp["shape_semantics"] = {"type": "assembly_node"}
            continue

        comp["kind"] = "part"
        comp["must_model"] = True if must_model is None else bool(must_model)
        comp["is_container"] = False
        comp["is_container_only"] = False
        comp["has_geometry"] = True
        comp["is_modeling_unit"] = True
        if comp["must_model"] is not True:
            warnings_list.append(
                {
                    "code": "autofix_part_must_model_false",
                    "component_id": comp_id,
                    "from": {"kind": "part", "must_model": comp.get("must_model")},
                    "to": {"kind": "part", "must_model": True},
                    "message": "Auto-fixed invalid part contract: coerced must_model to true",
                }
            )
            comp["must_model"] = True



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


def _build_type_map(components: list) -> dict[str, str]:
    """Build {component_id: component_type} mapping from a components list."""
    result: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and isinstance(ctype, str):
            result[cid] = ctype
    return result


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
def _strip_for_agent1(defn: Dict[str, Any]) -> Dict[str, Any]:
    d = copy.deepcopy(defn)
    if isinstance(d, dict) and "properties" in d and isinstance(d["properties"], dict):
        d["properties"].pop("interfaces", None)
        d["properties"].pop("parent_id", None)
    return d


def _ensure_shape_semantics_defaults(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    shape_by_type = {
        "wheel": {"type": "cylindrical", "cross_section": "circular"},
        "hub": {"type": "cylindrical", "cross_section": "circular"},
        "tire": {"type": "cylindrical", "cross_section": "annular"},
        "bearing": {"type": "cylindrical", "cross_section": "annular"},
        "shaft": {"type": "cylindrical", "cross_section": "circular"},
        "axle": {"type": "cylindrical", "cross_section": "circular"},
        "fastener": {"type": "cylindrical", "cross_section": "circular"},
        "spacer": {"type": "cylindrical", "cross_section": "annular"},
        "arm": {"type": "prismatic", "cross_section": "rectangular"},
        "plate": {"type": "prismatic", "cross_section": "rectangular"},
        "carrier_plate": {"type": "radial_plate", "cross_section": "rectangular"},
        "rigid_plate": {"type": "prismatic", "cross_section": "rectangular"},
    }

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        if comp.get("type") == "subassembly":
            continue
        shape = comp.get("shape_semantics")
        comp_type = comp.get("type") if isinstance(comp.get("type"), str) else ""
        defaults = shape_by_type.get(comp_type, {"type": "complex"})

        if not isinstance(shape, Mapping):
            comp["shape_semantics"] = dict(defaults)
            continue

        if not shape.get("type"):
            shape["type"] = defaults.get("type", "complex")
        if "cross_section" not in shape and defaults.get("cross_section"):
            shape["cross_section"] = defaults["cross_section"]


def _component_decomposition_confidence(comp: dict, template: str) -> float:
    comp_type = str(comp.get("type", "")).lower()
    comp_id = str(comp.get("id", "")).lower()
    role = str(comp.get("role", "")).lower()
    shape = comp.get("shape_semantics")
    shape_type = ""
    if isinstance(shape, Mapping):
        shape_type = str(shape.get("type", "")).lower()

    score = 0.0

    if template == "wheel":
        if comp_type == "wheel":
            score += 0.85
        if shape_type == "wheel":
            score += 0.2
        if "wheel" in comp_id or "轮" in comp_id:
            score += 0.12
    elif template == "shaft":
        if comp_type in {"shaft", "axle", "pin"}:
            score += 0.85
        if any(token in comp_id for token in {"shaft", "axle", "pin", "轴", "销"}):
            score += 0.12
    elif template == "bearing_unit":
        if comp_type == "bearing":
            score += 0.88
        if "bearing" in comp_id or "轴承" in comp_id:
            score += 0.1
    elif template == "motor_gearbox":
        if comp_type in {"motor", "electric_motor", "gearbox", "gear_reducer", "减速器"}:
            score += 0.82
        if any(token in comp_id for token in {"motor", "电机", "gearbox", "gear_reducer", "减速器"}):
            score += 0.14
    elif template == "coupling":
        if comp_type == "coupling":
            score += 0.82
        if any(token in comp_id for token in {"coupling", "联轴器", "耦合器"}):
            score += 0.14
    elif template == "plate_assembly":
        if comp_type in {"plate_assembly", "carrier_plate"}:
            score += 0.82
        elif comp_type == "plate":
            score += 0.52
        if any(token in comp_id for token in {"plate_top", "plate_bottom", "carrier_top", "carrier_bottom"}):
            score += 0.25

    if role in {"rotation", "load_support", "mounting", "fastening"}:
        score += 0.05

    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        score -= 0.35
    if comp_type in FEATURE_LIKE_TYPES:
        score -= 0.5

    return max(0.0, min(1.0, score))


def _has_existing_decomposition_signature(parent_id: str, template: str, components: list[dict]) -> bool:
    if not parent_id:
        return False

    child_types = {
        str(c.get("type", "")).lower()
        for c in components
        if isinstance(c, Mapping) and c.get("parent_id") == parent_id
    }

    signatures: dict[str, set[str]] = {
        "wheel": {"hub", "tire", "rim", "axle", "bearing"},
        "shaft": {"retainer", "spacer"},
        "bearing_unit": {"bearing_seat", "retainer"},
        "motor_gearbox": {"shaft", "mounting_flange"},
        "coupling": {"coupling_body", "fastener", "key"},
        "plate_assembly": {"standoff_set", "fastener", "nut_set"},
    }
    required = signatures.get(template, set())
    if not required:
        return False
    return len(required & child_types) >= max(2, len(required) // 2)


def _collect_referenced_component_ids(payload: Dict[str, Any]) -> set[str]:
    referenced: set[str] = set()

    for cr in payload.get("connection_requirements", []) or []:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        if isinstance(between, list):
            referenced.update({cid for cid in between if isinstance(cid, str)})

    for sa in payload.get("subassemblies", []) or []:
        if not isinstance(sa, Mapping):
            continue
        members = sa.get("component_ids", [])
        if isinstance(members, list):
            referenced.update({cid for cid in members if isinstance(cid, str)})

    for sp in payload.get("standard_parts", []) or []:
        if not isinstance(sp, Mapping):
            continue
        applied_to = sp.get("applied_to", [])
        if isinstance(applied_to, list):
            referenced.update({cid for cid in applied_to if isinstance(cid, str)})

    return referenced


def _collapse_semantic_clones(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    referenced = _collect_referenced_component_ids(payload)
    removable_types = {
        "retainer",
        "spacer",
        "bearing_seat",
        "mounting_flange",
        "key",
        "fastener_set",
        "standoff_set",
        "nut_set",
    }

    id_seen: set[str] = set()
    deduped: list[dict] = []
    removed_id_collisions = 0
    clone_bucket_seen: set[tuple[str, str, str]] = set()
    removed_unreferenced_clones = 0

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id in id_seen:
            removed_id_collisions += 1
            continue
        id_seen.add(comp_id)

        comp_type = str(comp.get("type", "")).lower()
        parent_id = str(comp.get("parent_id", ""))
        role = str(comp.get("role", "")).lower()
        bucket = (parent_id, comp_type, role)
        if comp_type in removable_types and comp_id not in referenced and bucket in clone_bucket_seen:
            removed_unreferenced_clones += 1
            continue

        clone_bucket_seen.add(bucket)
        deduped.append(comp)

    payload["components"] = deduped
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["entity_convergence"] = {
            "removed_id_collisions": removed_id_collisions,
            "removed_unreferenced_clones": removed_unreferenced_clones,
            "components_after_convergence": len(deduped),
        }


def _normalize_and_canonicalize_bearings(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    bearing_components = [
        c for c in components
        if isinstance(c, dict) and c.get("type") == "bearing" and isinstance(c.get("id"), str)
    ]
    if not bearing_components:
        return

    canonical_pattern = re.compile(r"^wheel_\d+_bearing_\d+$")
    generic_pattern = re.compile(r"^bearing_\d+$")
    canonical_ids = {
        str(c.get("id"))
        for c in bearing_components
        if canonical_pattern.match(str(c.get("id")))
    }

    removed_generic_ids: set[str] = set()

    for comp in bearing_components:
        raw_dims = comp.get("dimensions")
        dims: dict[str, Any] = dict(raw_dims) if isinstance(raw_dims, dict) else {}
        raw_sources = comp.get("dimension_sources")
        sources: dict[str, Any] = dict(raw_sources) if isinstance(raw_sources, dict) else {}

        if not isinstance(dims.get("bore_diameter"), (int, float)) and isinstance(dims.get("inner_diameter"), (int, float)):
            dims["bore_diameter"] = float(dims["inner_diameter"])
        if not isinstance(dims.get("width"), (int, float)) and isinstance(dims.get("thickness"), (int, float)):
            dims["width"] = float(dims["thickness"])

        if "bore_diameter" not in sources and isinstance(sources.get("inner_diameter"), dict):
            sources["bore_diameter"] = dict(sources["inner_diameter"])
        if "width" not in sources and isinstance(sources.get("thickness"), dict):
            sources["width"] = dict(sources["thickness"])

        dims.pop("inner_diameter", None)
        dims.pop("thickness", None)
        sources.pop("inner_diameter", None)
        sources.pop("thickness", None)

        comp["dimensions"] = dims
        comp["dimension_sources"] = sources

        comp_id = str(comp.get("id"))
        if canonical_ids and generic_pattern.match(comp_id):
            removed_generic_ids.add(comp_id)

    if not removed_generic_ids:
        return

    removed_component_ids: set[str] = set(removed_generic_ids)
    changed = True
    while changed:
        changed = False
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id")
            parent_id = comp.get("parent_id")
            if not isinstance(comp_id, str) or comp_id in removed_component_ids:
                continue
            if isinstance(parent_id, str) and parent_id in removed_component_ids:
                removed_component_ids.add(comp_id)
                changed = True

    payload["components"] = [
        c for c in components
        if not (isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id") in removed_component_ids)
    ]

    crs = payload.get("connection_requirements")
    if isinstance(crs, list):
        filtered_crs: list[dict] = []
        removed_cr_ids: set[str] = set()
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                filtered_crs.append(cr)
                continue
            new_between = [cid for cid in between if isinstance(cid, str) and cid not in removed_component_ids]
            if len(new_between) < 2:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_cr_ids.add(cr_id)
                continue
            cr["between"] = new_between
            filtered_crs.append(cr)
        payload["connection_requirements"] = filtered_crs

        standard_parts = payload.get("standard_parts")
        if isinstance(standard_parts, list):
            filtered_parts: list[dict[str, Any]] = []
            for part in standard_parts:
                if not isinstance(part, dict):
                    continue
                part_id = part.get("id")
                comp_id = part.get("component_id")
                if isinstance(comp_id, str) and comp_id in removed_component_ids:
                    continue
                bound_ids = part.get("bound_component_ids")
                if isinstance(bound_ids, list) and any(
                    isinstance(cid, str) and cid in removed_component_ids for cid in bound_ids
                ):
                    continue
                if isinstance(part_id, str) and any(part_id == f"std_{cid}" for cid in removed_component_ids):
                    continue
                applied_to = part.get("applied_to")
                if isinstance(applied_to, list) and removed_cr_ids:
                    part["applied_to"] = [cid for cid in applied_to if isinstance(cid, str) and cid not in removed_cr_ids]
                filtered_parts.append(part)
            payload["standard_parts"] = filtered_parts

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, dict):
                continue
            comp_ids = sa.get("component_ids")
            if isinstance(comp_ids, list):
                sa["component_ids"] = [cid for cid in comp_ids if isinstance(cid, str) and cid not in removed_component_ids]

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        filtered_patterns: list[dict[str, Any]] = []
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            component_ids = pattern.get("component_ids")
            if isinstance(component_ids, list):
                component_ids = [
                    cid for cid in component_ids if isinstance(cid, str) and cid not in removed_component_ids
                ]
                if len(component_ids) < 2:
                    continue
                pattern["component_ids"] = component_ids
                instances = pattern.get("instances")
                if isinstance(instances, list):
                    pattern["instances"] = [
                        cid for cid in instances if isinstance(cid, str) and cid not in removed_component_ids
                    ]
                prototype = pattern.get("prototype")
                if isinstance(prototype, str) and prototype in removed_component_ids:
                    pattern["prototype"] = component_ids[0]
            filtered_patterns.append(pattern)
        payload["patterns"] = filtered_patterns

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["bearing_canonicalization"] = {
            "canonical_pattern": "wheel_<n>_bearing_<m>",
            "removed_legacy_bearings": sorted(removed_generic_ids),
            "removed_legacy_descendants": sorted(removed_component_ids - removed_generic_ids),
        }


def _canonicalize_wheel_rotor_naming(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    legacy_axle_pattern = re.compile(r"^wheel_axle_(\d+)$")
    legacy_fastener_pattern = re.compile(r"^wheel_fastener_set_(\d+)$")
    canonical_wheel_axle_pattern = re.compile(r"^wheel_(\d+)_axle$")

    id_to_component: dict[str, dict[str, Any]] = {
        str(c.get("id")): c
        for c in components
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }

    rename_map: dict[str, str] = {}
    removed_legacy_components: set[str] = set()

    def _canonical_id(comp_id: str) -> str | None:
        m_axle = legacy_axle_pattern.match(comp_id)
        if m_axle:
            return f"wheel_{m_axle.group(1)}_axle"
        m_fastener = legacy_fastener_pattern.match(comp_id)
        if m_fastener:
            return f"wheel_{m_fastener.group(1)}_fastener_set"
        return None

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        canonical_id = _canonical_id(comp_id)
        if not canonical_id:
            continue

        rename_map[comp_id] = canonical_id
        if canonical_id in id_to_component and canonical_id != comp_id:
            removed_legacy_components.add(comp_id)
            continue

        comp["id"] = canonical_id
        id_to_component[canonical_id] = comp
        if comp_id in id_to_component:
            id_to_component.pop(comp_id, None)

    if removed_legacy_components:
        payload["components"] = [
            c
            for c in payload.get("components", [])
            if not (isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id") in removed_legacy_components)
        ]

    type_by_id = _build_type_map(payload.get("components", []))

    if not rename_map and not removed_legacy_components:
        return

    def _remap_component_id(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return rename_map.get(value, value)

    for comp in payload.get("components", []) if isinstance(payload.get("components", []), list) else []:
        if not isinstance(comp, dict):
            continue
        if isinstance(comp.get("parent_id"), str):
            comp["parent_id"] = _remap_component_id(comp.get("parent_id"))
        if isinstance(comp.get("position_parent"), str):
            comp["position_parent"] = _remap_component_id(comp.get("position_parent"))

    subassemblies = payload.get("subassemblies", [])
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, dict):
                continue
            members = sa.get("component_ids")
            if not isinstance(members, list):
                continue
            remapped = [_remap_component_id(cid) for cid in members if isinstance(cid, str)]
            deduped: list[str] = []
            for cid in remapped:
                if isinstance(cid, str) and cid not in deduped:
                    deduped.append(cid)
            sa["component_ids"] = deduped

    crs = payload.get("connection_requirements", [])
    removed_invalid_cr_ids: set[str] = set()
    if isinstance(crs, list):
        filtered_crs: list[dict[str, Any]] = []
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if isinstance(between, list):
                remapped_between = [_remap_component_id(cid) for cid in between if isinstance(cid, str)]
                deduped_between: list[str] = []
                for cid in remapped_between:
                    if isinstance(cid, str) and cid not in deduped_between:
                        deduped_between.append(cid)
                cr["between"] = deduped_between

            decision = cr.get("connection_decision")
            if isinstance(decision, dict):
                ref_id = decision.get("fastener_ref_component_id")
                if isinstance(ref_id, str):
                    decision["fastener_ref_component_id"] = _remap_component_id(ref_id)

            current_between = cr.get("between")
            if not isinstance(current_between, list):
                filtered_crs.append(cr)
                continue

            has_central_hub = any(
                isinstance(cid, str) and _is_central_hub_component_id(cid, type_by_id)
                for cid in current_between
            )
            has_wheel_axle = any(
                isinstance(cid, str) and canonical_wheel_axle_pattern.match(cid)
                for cid in current_between
            )
            if has_central_hub and has_wheel_axle:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_invalid_cr_ids.add(cr_id)
                continue

            if len([cid for cid in current_between if isinstance(cid, str)]) < 2:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_invalid_cr_ids.add(cr_id)
                continue

            filtered_crs.append(cr)

        payload["connection_requirements"] = filtered_crs

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, dict):
                continue
            comp_id = part.get("component_id")
            if isinstance(comp_id, str):
                part["component_id"] = _remap_component_id(comp_id)
            bound_ids = part.get("bound_component_ids")
            if isinstance(bound_ids, list):
                part["bound_component_ids"] = [
                    _remap_component_id(cid)
                    for cid in bound_ids
                    if isinstance(cid, str)
                ]
            applied_to = part.get("applied_to")
            if isinstance(applied_to, list) and removed_invalid_cr_ids:
                part["applied_to"] = [
                    cr_id for cr_id in applied_to if isinstance(cr_id, str) and cr_id not in removed_invalid_cr_ids
                ]

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["wheel_rotor_canonicalization"] = {
            "renamed_components": {k: v for k, v in sorted(rename_map.items())},
            "removed_legacy_components": sorted(removed_legacy_components),
            "removed_invalid_connections": sorted(removed_invalid_cr_ids),
        }


def _validate_wheel_rotor_naming(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    legacy_axle_pattern = re.compile(r"^wheel_axle_(\d+)$")
    legacy_fastener_pattern = re.compile(r"^wheel_fastener_set_(\d+)$")
    canonical_axle_pattern = re.compile(r"^wheel_(\d+)_axle$")
    canonical_fastener_pattern = re.compile(r"^wheel_(\d+)_fastener_set$")

    legacy_axle_ids: list[str] = []
    legacy_fastener_ids: list[str] = []
    canonical_axle_by_suffix: dict[str, set[str]] = {}
    canonical_fastener_by_suffix: dict[str, set[str]] = {}
    legacy_axle_by_suffix: dict[str, set[str]] = {}
    legacy_fastener_by_suffix: dict[str, set[str]] = {}

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        m = canonical_axle_pattern.match(comp_id)
        if m:
            canonical_axle_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = canonical_fastener_pattern.match(comp_id)
        if m:
            canonical_fastener_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = legacy_axle_pattern.match(comp_id)
        if m:
            legacy_axle_ids.append(comp_id)
            legacy_axle_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = legacy_fastener_pattern.match(comp_id)
        if m:
            legacy_fastener_ids.append(comp_id)
            legacy_fastener_by_suffix.setdefault(m.group(1), set()).add(comp_id)

    mixed_suffixes_axle = sorted(
        s for s in legacy_axle_by_suffix.keys() if s in canonical_axle_by_suffix
    )
    mixed_suffixes_fastener = sorted(
        s for s in legacy_fastener_by_suffix.keys() if s in canonical_fastener_by_suffix
    )

    if mixed_suffixes_axle or mixed_suffixes_fastener:
        raise ValueError(
            "Validation failed: mixed wheel naming schemes detected for axle/fastener_set. "
            f"mixed_axle_suffixes={mixed_suffixes_axle}, mixed_fastener_suffixes={mixed_suffixes_fastener}"
        )

    if legacy_axle_ids or legacy_fastener_ids:
        raise ValueError(
            "Validation failed: legacy wheel naming is not allowed. "
            f"legacy_axle_ids={sorted(legacy_axle_ids)}, legacy_fastener_ids={sorted(legacy_fastener_ids)}"
        )

    type_by_id = _build_type_map(components)

    crs = payload.get("connection_requirements", [])
    if isinstance(crs, list):
        illegal_links: list[str] = []
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                continue
            has_central_hub = any(
                isinstance(cid, str) and _is_central_hub_component_id(cid, type_by_id)
                for cid in between
            )
            if not has_central_hub:
                continue
            axle_hits = [cid for cid in between if isinstance(cid, str) and canonical_axle_pattern.match(cid)]
            if axle_hits:
                cr_id = cr.get("id") if isinstance(cr.get("id"), str) else "<unknown>"
                illegal_links.append(f"{cr_id}:{sorted(axle_hits)}")
        if illegal_links:
            raise ValueError(
                "Validation failed: illegal wheel axle to central hub connection(s) detected. "
                f"violations={illegal_links}"
            )


def _ensure_wheel_subcomponent_instance_patterns(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    allowed_subs = {
        "wheel",
        "rim",
        "tire",
        "hub",
        "axle",
        "bearing_1",
        "bearing_2",
        "spacer",
        "fastener_set",
    }
    id_pattern = re.compile(r"^wheel_(\d+)(?:_(rim|tire|hub|axle|bearing_1|bearing_2|spacer|fastener_set))?$")

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    grouped_ids: Dict[str, Dict[int, str]] = {sub: {} for sub in allowed_subs}
    for comp_id in comp_by_id.keys():
        match = id_pattern.match(comp_id)
        if not match:
            continue
        idx = int(match.group(1))
        sub = match.group(2) or "wheel"
        grouped_ids[sub][idx] = comp_id

    patterns_raw = payload.get("patterns")
    patterns: List[Dict[str, Any]] = [p for p in patterns_raw if isinstance(p, dict)] if isinstance(patterns_raw, list) else []

    def _extract_requirement_text() -> str:
        candidates: list[Any] = [
            payload.get("requirement_text"),
            payload.get("user_requirement"),
            payload.get("prompt"),
        ]
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.extend(
                [
                    metadata.get("requirement_text"),
                    metadata.get("user_requirement"),
                    metadata.get("source_requirement"),
                    metadata.get("prompt"),
                ]
            )
        merged = "\n".join(str(v) for v in candidates if isinstance(v, str) and v.strip())
        return merged.lower()

    requirement_text_lower = _extract_requirement_text()

    def _force_instancing_by_requirement_text() -> bool:
        explicit_hints = [
            "120°",
            "120 degree",
            "三等分",
            "three-fold symmetry",
            "threefold symmetry",
            "三个轮子均布",
            "三个轮子对称分布",
            "three identical wheels",
            "three wheels are identical",
        ]
        return any(token in requirement_text_lower for token in explicit_hints)

    force_instancing = _force_instancing_by_requirement_text()

    def _numeric_dims(comp: Dict[str, Any]) -> Dict[str, float]:
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), dict) else {}
        out: Dict[str, float] = {}
        for key, value in dims.items():
            if not isinstance(key, str):
                continue
            value = dims.get(key)
            if isinstance(value, (int, float)):
                out[key] = float(value)
        return out

    def _dims_compatible(a: Dict[str, float], b: Dict[str, float], tol: float = 1e-3) -> bool:
        common_keys = set(a.keys()) & set(b.keys())
        for key in common_keys:
            if abs(a[key] - b[key]) >= tol:
                return False
        return True

    def _apply_instance_pattern(
        *,
        instances: list[str],
        pattern_id: str,
        description: str,
    ) -> None:
        if len(instances) != 3:
            return

        prototype = instances[0]
        prototype_comp = comp_by_id.get(prototype)
        if not isinstance(prototype_comp, dict):
            return

        expected_type = prototype_comp.get("type") if isinstance(prototype_comp.get("type"), str) else None
        expected_dims = _numeric_dims(prototype_comp)

        is_consistent = True
        mismatch_reason = ""
        for comp_id in instances[1:]:
            comp = comp_by_id.get(comp_id)
            if not isinstance(comp, dict):
                is_consistent = False
                mismatch_reason = "missing_component_payload"
                break
            ctype = comp.get("type") if isinstance(comp.get("type"), str) else None
            if ctype != expected_type:
                is_consistent = False
                mismatch_reason = "type_mismatch"
                break
            if not _dims_compatible(expected_dims, _numeric_dims(comp)):
                is_consistent = False
                mismatch_reason = "dimension_mismatch"
                break

        forced = False
        if not is_consistent and force_instancing and mismatch_reason != "type_mismatch":
            is_consistent = True
            forced = True

        if not is_consistent:
            return

        for comp_id in instances:
            comp = comp_by_id.get(comp_id)
            if isinstance(comp, dict):
                comp["definition_id"] = prototype
                comp["instance_id"] = comp_id
                if comp_id != prototype:
                    comp["instanced_from"] = prototype
                elif "instanced_from" in comp:
                    comp.pop("instanced_from", None)

        created_pattern_ids.add(pattern_id)
        if forced:
            forced_pattern_ids.add(pattern_id)
        pattern_payload = {
            "id": pattern_id,
            "type": "rotational_symmetry",
            "count": len(instances),
            "component_ids": instances,
            "prototype": prototype,
            "instances": instances,
            "axis": "Z",
            "description": description,
        }
        if forced:
            pattern_payload["force_instancing"] = True
            pattern_payload["force_reason"] = "requirement_text_threefold_symmetry_hint"

        replaced = False
        for idx, item in enumerate(patterns):
            if isinstance(item.get("id"), str) and item.get("id") == pattern_id:
                patterns[idx] = pattern_payload
                replaced = True
                break
        if not replaced:
            patterns.append(pattern_payload)

    created_pattern_ids: set[str] = set()
    forced_pattern_ids: set[str] = set()
    for sub in sorted(allowed_subs):
        per_index = grouped_ids.get(sub, {})
        if len(per_index) < 3:
            continue

        indices = sorted(per_index.keys())
        if indices != [1, 2, 3]:
            continue

        instances = [per_index[i] for i in indices]
        _apply_instance_pattern(
            instances=instances,
            pattern_id=f"wheel_{sub}_rotational_symmetry",
            description="Wheel subcomponents are identical instances",
        )

    arm_pattern = re.compile(r"^wheel_arm_(\d+)$")
    arm_group: Dict[int, str] = {}
    for comp_id in comp_by_id.keys():
        match = arm_pattern.match(comp_id)
        if not match:
            continue
        arm_group[int(match.group(1))] = comp_id

    arm_indices = sorted(arm_group.keys())
    if arm_indices == [1, 2, 3]:
        _apply_instance_pattern(
            instances=[arm_group[i] for i in arm_indices],
            pattern_id="wheel_arm_rotational_symmetry",
            description="Wheel arms are identical instances",
        )

    if created_pattern_ids:
        payload["patterns"] = patterns

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["wheel_instance_patterns"] = {
        "created_pattern_ids": sorted(created_pattern_ids),
        "count": len(created_pattern_ids),
        "forced_pattern_ids": sorted(forced_pattern_ids),
        "forced_by_requirement_text": bool(forced_pattern_ids),
        "force_trigger_detected": force_instancing,
    }


def _canonicalize_hub_arm_fastener_components(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    def _is_hub_arm_fastener_connection(conn: Mapping[str, Any], idx: int, fastener_id: str) -> bool:
        between = [cid for cid in conn.get("between", []) if isinstance(cid, str)]
        required = {"central_hub", f"wheel_arm_{idx}", fastener_id}
        if required.issubset(set(between)):
            return True
        decision = conn.get("connection_decision") if isinstance(conn.get("connection_decision"), Mapping) else {}
        ref_id = decision.get("fastener_ref_component_id")
        if isinstance(ref_id, str) and ref_id == fastener_id:
            return True
        return False

    remap: Dict[str, str] = {}
    rename_in_place: Dict[str, str] = {}
    for idx in (1, 2, 3):
        legacy_id = f"wheel_{idx}_fastener_set"
        canonical_id = f"central_hub_to_wheel_arm_{idx}_fastener_set"
        if legacy_id not in comp_by_id:
            continue
        conn = next(
            (
                cr for cr in crs
                if isinstance(cr, Mapping)
                and str(cr.get("id") or "").strip() == f"hub_to_arm_{idx}_connection"
                and _is_hub_arm_fastener_connection(cr, idx, legacy_id)
            ),
            None,
        )
        if conn is None:
            continue
        remap[legacy_id] = canonical_id
        if canonical_id not in comp_by_id:
            rename_in_place[legacy_id] = canonical_id
    if not remap:
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else None
        if isinstance(comp_id, str) and comp_id in rename_in_place:
            comp["id"] = rename_in_place[comp_id]
        for field in ("definition_id", "instance_id", "instanced_from"):
            field_value = comp.get(field)
            if isinstance(field_value, str) and field_value in remap:
                comp[field] = remap[field_value]

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between = cr.get("between")
        if isinstance(between, list):
            remapped_between: list[str] = []
            for cid in between:
                if not isinstance(cid, str):
                    continue
                mapped = remap.get(cid, cid)
                if mapped not in remapped_between:
                    remapped_between.append(mapped)
            cr["between"] = remapped_between
        decision = cr.get("connection_decision")
        if isinstance(decision, dict):
            ref_id = decision.get("fastener_ref_component_id")
            if isinstance(ref_id, str) and ref_id in remap:
                decision["fastener_ref_component_id"] = remap[ref_id]

    referenced_ids = {
        cid
        for cr in crs
        if isinstance(cr, Mapping)
        for cid in cr.get("between", [])
        if isinstance(cid, str)
    }
    removed_component_ids = {
        legacy_id
        for legacy_id, canonical_id in remap.items()
        if legacy_id not in rename_in_place and canonical_id in comp_by_id and legacy_id not in referenced_ids
    }
    if removed_component_ids:
        payload["components"] = [
            comp
            for comp in components
            if not (isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id") in removed_component_ids)
        ]

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, dict):
                continue
            comp_id = part.get("component_id")
            if isinstance(comp_id, str) and comp_id in remap:
                part["component_id"] = remap[comp_id]
            bound_ids = part.get("bound_component_ids")
            if isinstance(bound_ids, list):
                part["bound_component_ids"] = [remap.get(cid, cid) for cid in bound_ids if isinstance(cid, str)]
            bound_component_id = part.get("bound_component_id")
            if isinstance(bound_component_id, str) and bound_component_id in remap:
                part["bound_component_id"] = remap[bound_component_id]

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            prototype = pattern.get("prototype")
            if isinstance(prototype, str) and prototype in remap:
                pattern["prototype"] = remap[prototype]
            component_ids = pattern.get("component_ids")
            if isinstance(component_ids, list):
                pattern["component_ids"] = [remap.get(cid, cid) for cid in component_ids if isinstance(cid, str)]

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        for subassembly in subassemblies:
            if not isinstance(subassembly, dict):
                continue
            component_ids = subassembly.get("component_ids")
            if not isinstance(component_ids, list):
                continue
            remapped_ids: list[str] = []
            for cid in component_ids:
                if not isinstance(cid, str):
                    continue
                mapped = remap.get(cid, cid)
                if mapped not in remapped_ids:
                    remapped_ids.append(mapped)
            subassembly["component_ids"] = remapped_ids

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata["hub_arm_fastener_component_canonicalization"] = {
        "remapped_components": {k: v for k, v in sorted(remap.items())},
        "renamed_legacy_components": sorted(rename_in_place.keys()),
        "removed_legacy_components": sorted(removed_component_ids),
    }
    payload["metadata"] = metadata


def _prune_stale_standard_parts(payload: Dict[str, Any]) -> None:
    standard_parts = payload.get("standard_parts")
    if not isinstance(standard_parts, list):
        _prune_orphan_wheel_fastener_components(payload)
        return

    component_ids = {
        comp.get("id")
        for comp in payload.get("components", [])
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
    }
    connection_by_id = {
        cr.get("id"): cr
        for cr in payload.get("connection_requirements", [])
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    }
    connection_ids = set(connection_by_id.keys())

    filtered: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    for part in standard_parts:
        if not isinstance(part, dict):
            continue
        comp_id = part.get("component_id") if isinstance(part.get("component_id"), str) else None
        has_bound_field = isinstance(part.get("bound_component_ids"), list)
        bound_ids = part.get("bound_component_ids") if has_bound_field else []
        applied_to = part.get("applied_to") if isinstance(part.get("applied_to"), list) else []

        comp_id = comp_id if comp_id in component_ids else None
        bound_ids = [cid for cid in bound_ids if isinstance(cid, str) and cid in component_ids]
        applied_to = [cid for cid in applied_to if isinstance(cid, str) and cid in connection_ids]

        if comp_id is not None:
            part["component_id"] = comp_id
        else:
            part.pop("component_id", None)
        if has_bound_field:
            part["bound_component_ids"] = bound_ids
        part["applied_to"] = applied_to

        has_component_ref = comp_id is not None or (has_bound_field and bool(bound_ids))
        has_connection_ref = bool(applied_to)
        category = str(part.get("category") or "").strip().lower()
        if category == "fastener" and not has_component_ref:
            inferred_refs = {
                str(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id"))
                for conn_id in applied_to
                if isinstance(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id"), str)
                and str(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id")) in component_ids
            }
            has_component_ref = bool(inferred_refs)
        if (not has_component_ref and not has_connection_ref) or (category == "fastener" and not has_component_ref):
            if isinstance(part.get("id"), str):
                removed_ids.append(part["id"])
            continue
        filtered.append(part)

    payload["standard_parts"] = filtered
    if removed_ids:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata["stale_standard_parts_pruned"] = sorted(removed_ids)
        payload["metadata"] = metadata
    _prune_orphan_wheel_fastener_components(payload)



def _prune_orphan_wheel_fastener_components(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list) or not components:
        return

    orphan_pattern = re.compile(r"^(?:wheel_fastener_set(?:_\d+)?|wheel_\d+_fastener_set)$")
    referenced_ids: set[str] = set()

    crs = payload.get("connection_requirements", [])
    if isinstance(crs, list):
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between")
            if isinstance(between, list):
                for cid in between:
                    if isinstance(cid, str) and cid:
                        referenced_ids.add(cid)
            decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else {}
            fastener_ref = decision.get("fastener_ref_component_id")
            if isinstance(fastener_ref, str) and fastener_ref:
                referenced_ids.add(fastener_ref)

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, Mapping):
                continue
            bound_component_id = part.get("bound_component_id")
            if isinstance(bound_component_id, str) and bound_component_id:
                referenced_ids.add(bound_component_id)
            bound_component_ids = part.get("bound_component_ids")
            if isinstance(bound_component_ids, list):
                for cid in bound_component_ids:
                    if isinstance(cid, str) and cid:
                        referenced_ids.add(cid)

    removed_ids: list[str] = []
    kept_components: list[Any] = []
    for comp in components:
        if not isinstance(comp, Mapping):
            kept_components.append(comp)
            continue
        comp_id = comp.get("id")
        comp_type = str(comp.get("type") or "").strip().lower()
        if (
            isinstance(comp_id, str)
            and orphan_pattern.fullmatch(comp_id) is not None
            and comp_type in {"fastener", "fastener_set", "bolt_set"}
            and comp_id not in referenced_ids
        ):
            removed_ids.append(comp_id)
            continue
        kept_components.append(comp)

    if not removed_ids:
        return

    payload["components"] = kept_components

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        payload["patterns"] = [
            pattern
            for pattern in patterns
            if not (
                isinstance(pattern, Mapping)
                and (
                    (
                        isinstance(pattern.get("prototype"), str)
                        and pattern.get("prototype") in removed_ids
                    )
                    or any(
                        isinstance(cid, str) and cid in removed_ids
                        for cid in (
                            pattern.get("component_ids")
                            if isinstance(pattern.get("component_ids"), list)
                            else []
                        )
                    )
                )
            )
        ]

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        filtered_subassemblies: list[Any] = []
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                filtered_subassemblies.append(sa)
                continue
            component_ids = sa.get("component_ids")
            if isinstance(component_ids, list):
                kept_ids = [cid for cid in component_ids if not (isinstance(cid, str) and cid in removed_ids)]
                if not kept_ids:
                    continue
                sa_out = dict(sa)
                sa_out["component_ids"] = kept_ids
                filtered_subassemblies.append(sa_out)
                continue
            filtered_subassemblies.append(sa)
        payload["subassemblies"] = filtered_subassemblies

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    existing = metadata.get("orphan_wheel_fastener_components_pruned")
    pruned = set(existing) if isinstance(existing, list) else set()
    pruned.update(removed_ids)
    metadata["orphan_wheel_fastener_components_pruned"] = sorted(pruned)
    payload["metadata"] = metadata


def _normalize_symmetric_hub_arm_fasteners(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    def _fastener_id_for_index(idx: int) -> str | None:
        for candidate in (
            f"central_hub_to_wheel_arm_{idx}_fastener_set",
            f"wheel_{idx}_fastener_set",
        ):
            if candidate in comp_by_id:
                return candidate
        return None

    fastener_ids = [_fastener_id_for_index(idx) for idx in (1, 2, 3)]
    if any(not isinstance(fid, str) or not fid for fid in fastener_ids):
        return

    for idx, fastener_id in zip((1, 2, 3), fastener_ids):
        conn = next(
            (
                cr for cr in crs
                if isinstance(cr, dict)
                and cr.get("id") == f"hub_to_arm_{idx}_connection"
            ),
            None,
        )
        if not isinstance(conn, dict):
            return
        between = [cid for cid in conn.get("between", []) if isinstance(cid, str)]
        required = {"central_hub", f"wheel_arm_{idx}", fastener_id}
        if not required.issubset(set(between)):
            return

    def _signature(comp: Mapping[str, Any]) -> str:
        payload = {
            "type": comp.get("type"),
            "role": comp.get("role"),
            "dimensions": comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {},
            "parameters": comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {},
            "shape_semantics": comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {},
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    buckets: Dict[str, list[str]] = {}
    for fid in fastener_ids:
        buckets.setdefault(_signature(comp_by_id[fid]), []).append(fid)

    sorted_buckets = sorted(
        buckets.items(),
        key=lambda item: (-len(item[1]), 0 if "wheel_1_fastener_set" in item[1] else 1, sorted(item[1])[0]),
    )
    prototype_id = sorted_buckets[0][1][0]
    prototype = comp_by_id.get(prototype_id)
    if not isinstance(prototype, dict):
        return

    updated_ids: list[str] = []
    copied_fields = (
        "type",
        "role",
        "shape_semantics",
        "dimensions",
        "parameters",
        "dimension_sources",
        "part_kind",
        "modeling_policy",
        "kind",
        "must_model",
        "is_container",
        "is_container_only",
        "has_geometry",
        "is_modeling_unit",
    )
    for fid in fastener_ids:
        if fid == prototype_id:
            continue
        target = comp_by_id.get(fid)
        if not isinstance(target, dict):
            continue
        if _signature(target) == _signature(prototype):
            continue
        for field in copied_fields:
            value = prototype.get(field)
            if isinstance(value, Mapping):
                target[field] = dict(value)
            else:
                target[field] = copy.deepcopy(value)
        target["definition_id"] = prototype_id
        target["instance_id"] = fid
        target["instanced_from"] = prototype_id
        updated_ids.append(fid)

    if updated_ids:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata["hub_arm_fastener_symmetry_normalization"] = {
            "prototype_id": prototype_id,
            "updated_ids": sorted(updated_ids),
        }
        payload["metadata"] = metadata



def _ensure_wheel_rim_tire_position_parent(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }
    if not comp_by_id:
        return

    pattern = re.compile(r"^wheel_(\d+)_(rim|tire)$")
    for cid, comp in comp_by_id.items():
        match = pattern.match(cid)
        if not match:
            continue
        idx = match.group(1)
        hub_id = f"wheel_{idx}_hub"
        wheel_id = f"wheel_{idx}"

        parent = hub_id if hub_id in comp_by_id else (wheel_id if wheel_id in comp_by_id else None)
        if isinstance(parent, str) and parent:
            comp["position_parent"] = parent


def _align_rotational_symmetry_instancing_annotations(payload: Dict[str, Any]) -> None:
    components = payload.get("components")
    patterns = payload.get("patterns")
    if not isinstance(components, list) or not isinstance(patterns, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }
    if not comp_by_id:
        return

    def _numeric_dims(comp: Dict[str, Any]) -> Dict[str, float]:
        dims = comp.get("dimensions")
        if not isinstance(dims, dict):
            return {}
        result: Dict[str, float] = {}
        for key, value in dims.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(key)] = float(value)
        return result

    def _dims_match(a: Dict[str, float], b: Dict[str, float], tol: float = 1e-3) -> bool:
        if set(a.keys()) != set(b.keys()):
            return False
        for key in a.keys():
            if abs(a[key] - b[key]) > tol:
                return False
        return True

    aligned_count = 0
    skipped_pattern_ids: list[str] = []
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        if pattern.get("type") != "rotational_symmetry":
            continue

        raw_ids = pattern.get("component_ids")
        component_ids = [cid for cid in raw_ids if isinstance(cid, str)] if isinstance(raw_ids, list) else []
        pattern_id = pattern.get("id") if isinstance(pattern.get("id"), str) else "rotational_symmetry"
        if len(component_ids) < 2:
            skipped_pattern_ids.append(pattern_id)
            continue

        prototype_id = component_ids[0]
        prototype_comp = comp_by_id.get(prototype_id)
        if not isinstance(prototype_comp, dict):
            skipped_pattern_ids.append(pattern_id)
            continue

        prototype_type = prototype_comp.get("type") if isinstance(prototype_comp.get("type"), str) else None
        prototype_dims = _numeric_dims(prototype_comp)
        consistent = True
        for component_id in component_ids[1:]:
            comp = comp_by_id.get(component_id)
            if not isinstance(comp, dict):
                consistent = False
                break
            comp_type = comp.get("type") if isinstance(comp.get("type"), str) else None
            if comp_type != prototype_type or not _dims_match(prototype_dims, _numeric_dims(comp)):
                consistent = False
                break

        if not consistent:
            skipped_pattern_ids.append(pattern_id)
            continue

        pattern["prototype"] = prototype_id
        pattern["instances"] = component_ids
        for component_id in component_ids:
            comp = comp_by_id.get(component_id)
            if not isinstance(comp, dict):
                continue
            comp["definition_id"] = prototype_id
            comp["instance_id"] = component_id
            if component_id == prototype_id:
                comp.pop("instanced_from", None)
            else:
                comp["instanced_from"] = prototype_id
        aligned_count += 1

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["rotational_pattern_instancing_alignment"] = {
        "aligned_count": aligned_count,
        "skipped_pattern_ids": skipped_pattern_ids,
    }


def _sanitize_instancing_annotations(payload: Dict[str, Any]) -> None:
    components = payload.get("components")
    if not isinstance(components, list):
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str) or not comp_id:
            continue

        instanced_from = comp.get("instanced_from")
        if isinstance(instanced_from, str) and instanced_from == comp_id:
            comp.pop("instanced_from", None)

        definition_id = comp.get("definition_id")
        if not isinstance(definition_id, str) or not definition_id.strip():
            comp["definition_id"] = comp_id

        instance_id = comp.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.strip():
            comp["instance_id"] = comp_id


def _validate_bearing_canonical_schema(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    canonical_pattern = re.compile(r"^wheel_\d+_bearing_\d+$")
    generic_pattern = re.compile(r"^bearing_\d+$")
    canonical_ids: list[str] = []
    generic_ids: list[str] = []
    bad_fields: list[str] = []

    for comp in components:
        if not isinstance(comp, dict) or comp.get("type") != "bearing":
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if canonical_pattern.match(comp_id):
            canonical_ids.append(comp_id)
        if generic_pattern.match(comp_id):
            generic_ids.append(comp_id)

        raw_dims = comp.get("dimensions")
        dims: dict[str, Any] = raw_dims if isinstance(raw_dims, dict) else {}
        if "inner_diameter" in dims or "thickness" in dims:
            bad_fields.append(comp_id)

    if canonical_ids and generic_ids:
        raise ValueError(
            "Validation failed: mixed bearing naming schemes detected. "
            f"canonical={sorted(canonical_ids)}, generic={sorted(generic_ids)}"
        )

    if bad_fields:
        raise ValueError(
            "Validation failed: bearing dimensions must use canonical keys "
            "bore_diameter/outer_diameter/width only. "
            f"Invalid components: {sorted(bad_fields)}"
        )


# ============================================================================
# DETERMINISTIC DECOMPOSITION PASS
# ============================================================================
# Automatically decompose complex components (wheel, shaft, bearing, etc.) into
# sub-components and required connections. Based on strict rules, not LLM inference.
# This ensures structural completeness even if LLM misses decomposition.
# ============================================================================


def _decompose_complex_components(payload: Dict[str, Any]) -> None:
    """Apply deterministic decomposition templates to complex components.
    
    - Does NOT depend on LLM output correctness
    - Uses component.type, shape_semantics.class, and keywords to trigger decomposition
    - Auto-generates sub-components and connection_requirements
    - Must be called AFTER _normalize_connection_requirements, BEFORE _fill_missing_dimensions
    """
    
    components = payload.get("components", [])
    connection_requirements = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(connection_requirements, list):
        return
    
    comp_by_id: dict[str, dict] = {
        c.get("id"): c
        for c in components if isinstance(c, dict) and c.get("id")
    }

    ordered_templates = [
        "wheel",
        "shaft",
        "bearing_unit",
        "motor_gearbox",
        "coupling",
        "plate_assembly",
    ]
    template_predicates: dict[str, Any] = {
        "wheel": _should_decompose_wheel,
        "shaft": _should_decompose_shaft,
        "bearing_unit": _should_decompose_bearing_unit,
        "motor_gearbox": _should_decompose_motor_gearbox,
        "coupling": _should_decompose_coupling,
        "plate_assembly": _should_decompose_plate_assembly,
    }

    decomposition_queue: list[tuple[str, str, dict, float]] = []
    guardrail_report: dict[str, Any] = {
        "threshold": DECOMPOSITION_CONFIDENCE_THRESHOLD,
        "candidates": 0,
        "selected": 0,
        "skipped_low_confidence": 0,
        "skipped_child_component": 0,
        "skipped_existing_signature": 0,
        "skipped_budget": 0,
    }

    for comp in list(components):
        if not isinstance(comp, dict) or not comp.get("id"):
            continue
        if comp.get("type") == "module":
            continue

        comp_id = comp.get("id")
        if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
            guardrail_report["skipped_child_component"] += 1
            continue

        selected_template: str | None = None
        selected_confidence = 0.0
        for template_name in ordered_templates:
            predicate = template_predicates[template_name]
            if not predicate(comp):
                continue
            guardrail_report["candidates"] += 1
            confidence = _component_decomposition_confidence(comp, template_name)
            if confidence < DECOMPOSITION_CONFIDENCE_THRESHOLD:
                guardrail_report["skipped_low_confidence"] += 1
                continue
            if _has_existing_decomposition_signature(str(comp_id), template_name, components):
                guardrail_report["skipped_existing_signature"] += 1
                continue
            selected_template = template_name
            selected_confidence = confidence
            break

        if selected_template:
            decomposition_queue.append((str(comp_id), selected_template, comp, selected_confidence))

    original_count = len([c for c in components if isinstance(c, Mapping)])
    max_added = max(6, int(original_count * DECOMPOSITION_MAX_ADDED_RATIO))
    applied = 0

    for parent_id, template_name, parent_comp, confidence in decomposition_queue:
        before_count = len(components)
        if template_name == "wheel":
            _decompose_wheel_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "shaft":
            _decompose_shaft_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "bearing_unit":
            _decompose_bearing_unit_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "motor_gearbox":
            _decompose_motor_gearbox_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "coupling":
            _decompose_coupling_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "plate_assembly":
            _decompose_plate_assembly_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )

        added = len(components) - before_count
        if added > 0:
            applied += 1
            if len(components) - original_count >= max_added:
                guardrail_report["skipped_budget"] += max(0, len(decomposition_queue) - applied)
                break

    guardrail_report["selected"] = applied
    guardrail_report["components_before"] = original_count
    guardrail_report["components_after"] = len(components)
    guardrail_report["max_added_components"] = max_added

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["decomposition_guardrail"] = guardrail_report


# ============================================================================
# Decomposition Trigger Detection
# ============================================================================


def _should_decompose_wheel(comp: dict) -> bool:
    """Check if component should trigger wheel decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "wheel":
        return True
    
    shape = comp.get("shape_semantics")
    if isinstance(shape, dict) and shape.get("type") == "wheel":
        return True
    
    return False


def _should_decompose_shaft(comp: dict) -> bool:
    """Check if component should trigger shaft decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type in {"shaft", "axle", "pin"}:
        return True

    return False


def _should_decompose_bearing_unit(comp: dict) -> bool:
    """Check if component should trigger bearing unit decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "bearing":
        return True

    return False


def _should_decompose_motor_gearbox(comp: dict) -> bool:
    """Check if component should trigger motor+gearbox decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    is_motor = comp_type in {"motor", "electric_motor"}
    is_gearbox = comp_type in {"gearbox", "gear_reducer", "减速器"}

    return is_motor or is_gearbox


def _should_decompose_coupling(comp: dict) -> bool:
    """Check if component should trigger coupling decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "coupling":
        return True

    return False


def _should_decompose_plate_assembly(comp: dict) -> bool:
    """Check if component is part of plate pair (top+bottom) that should be decomposed."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type not in {"plate_assembly", "carrier_plate"}:
        return False

    return True


# ============================================================================
# Decomposition Template: WHEEL
# ============================================================================


def _wheel_requires_opposed_bearing_stack(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when the wheel explicitly requests a stacked support package."""

    evidence_tokens = {
        "dual_bearing",
        "double_bearing",
        "opposed_bearing",
        "opposed bearing",
        "bearing_pair",
        "pair_of_bearings",
        "two_bearings",
        "second_bearing",
        "spacer_stack",
        "spacer stack",
        "axial_capture_with_spacer_stack",
        "retaining_nut",
        "retaining nut",
        "locknut",
    }
    bearing_count_keys = {
        "bearing_count",
        "support_bearing_count",
        "bearing_quantity",
        "number_of_bearings",
    }
    explicit_child_ids = {
        f"{parent_id}_bearing_2",
        f"{parent_id}_spacer",
    }
    fastener_component_id = f"{parent_id}_fastener_set"
    related_component_ids = {
        parent_id,
        f"{parent_id}_axle",
        f"{parent_id}_hub",
        f"{parent_id}_bearing_1",
        fastener_component_id,
        *explicit_child_ids,
    }

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _parse_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value) > 0:
            return int(round(float(value)))
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = float(candidate)
            except ValueError:
                return None
            if parsed > 0:
                return int(round(parsed))
        return None

    def _contains_stack_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _fastener_requests_axial_stack(comp: Mapping[str, Any]) -> bool:
        role = str(comp.get("role") or "").strip().lower()
        if any(token in role for token in ("axial", "retention", "locknut")):
            return True

        for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
            raw = comp.get(section)
            if not isinstance(raw, Mapping):
                continue
            for item in _walk_scalars(raw):
                if not isinstance(item, str):
                    continue
                normalized = item.strip().lower()
                if any(
                    token in normalized
                    for token in (
                        "axial_retention",
                        "axial retention",
                        "axial_clamping",
                        "axial clamping",
                        "locknut",
                        "retaining_nut",
                        "retaining nut",
                        "threaded_shaft",
                        "nut_on_threaded_shaft",
                        "nut_only",
                        "inner_race_capture",
                    )
                ):
                    return True
        return False

    def _mapping_requests_stack(mapping: Mapping[str, Any]) -> bool:
        for key in bearing_count_keys:
            count = _parse_positive_int(mapping.get(key))
            if count is not None and count >= 2:
                return True
        return any(_contains_stack_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_stack(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_stack(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type == "spacer":
            return True
        if comp_type in {"fastener", "fastener_set", "bolt_set"} and _fastener_requests_axial_stack(comp):
            return True
        if comp_type == "bearing" and isinstance(comp_id, str) and "_bearing_2" in comp_id:
            return True
        if any(_contains_stack_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if str(cr.get("purpose") or "").strip().lower() == "spacing":
            return True
        lower_id = cr_id.lower()
        if any(token in lower_id for token in ("bearing_2", "spacer_axial", "fastener_axial_clamping")):
            return True
        if any(_contains_stack_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_stack_token(item) for item in _walk_scalars(intent)):
                return True

    return False


def _decompose_wheel_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a wheel into rim, tire, hub, axle, and a single default bearing.

    Add a second bearing, spacer, and axial retention hardware only when the
    source payload explicitly requests an opposed bearing stack.
    """

    parent_dims = parent_comp.get("dimensions", {})
    parent_diameter = parent_dims.get("outer_diameter")
    parent_width = parent_dims.get("thickness")
    requires_opposed_bearing_stack = _wheel_requires_opposed_bearing_stack(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    )
    support_architecture = "opposed_bearing_stack" if requires_opposed_bearing_stack else "single_bearing_through_bore"

    parent_comp["kind"] = "assembly_node"
    parent_comp["modeling_policy"] = "container_only"
    parent_comp["must_model"] = False
    parent_comp["is_container"] = True
    parent_comp["is_container_only"] = True
    parent_comp["is_modeling_unit"] = False
    parent_comp["has_geometry"] = False
    parent_comp["dimensions"] = {}
    parent_comp["parameters"] = {}
    parent_comp["dimension_sources"] = {}
    parent_comp["shape_semantics"] = {
        "type": "assembly_node",
        "notes": "decomposed_wheel_container",
        "support_architecture": support_architecture,
    }

    body_id = f"{parent_id}_body"
    rim_id = f"{parent_id}_rim"
    tire_id = f"{parent_id}_tire"
    hub_id = f"{parent_id}_hub"
    axle_id = f"{parent_id}_axle"
    bearing_1_id = f"{parent_id}_bearing_1"
    bearing_2_id = f"{parent_id}_bearing_2"
    spacer_id = f"{parent_id}_spacer"
    fastener_set_id = f"{parent_id}_fastener_set"

    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}

    child_ids = [rim_id, tire_id, hub_id, axle_id, bearing_1_id]
    if requires_opposed_bearing_stack:
        child_ids.extend([bearing_2_id, spacer_id, fastener_set_id])
    child_ids = [cid for cid in child_ids if cid not in existing_ids]

    if not child_ids:
        return

    new_components = []

    if body_id in existing_ids and rim_id not in existing_ids:
        rim_id = body_id
    if rim_id not in existing_ids:
        rim_comp = {
            "id": rim_id,
            "type": "rim",
            "role": "structural",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            rim_outer = round(parent_diameter * 0.72, 2)
            rim_comp["dimensions"]["outer_diameter"] = rim_outer
            rim_comp["dimension_sources"]["outer_diameter"] = {"source": "derived", "derived_from": ["parent.outer_diameter * 0.72"]}
        if parent_width is not None:
            rim_comp["dimensions"]["thickness"] = parent_width
            rim_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(rim_comp)
    if tire_id not in existing_ids:
        tire_comp = {
            "id": tire_id,
            "type": "tire",
            "role": "contact",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            tire_comp["dimensions"]["outer_diameter"] = parent_diameter
            tire_comp["dimension_sources"]["outer_diameter"] = {"source": "derived", "derived_from": ["parent.outer_diameter"]}
            rim_outer = round(parent_diameter * 0.72, 2)
            tire_comp["dimensions"]["inner_diameter"] = rim_outer
            tire_comp["dimension_sources"]["inner_diameter"] = {"source": "derived", "derived_from": ["rim.outer_diameter"]}
        if parent_width is not None:
            tire_comp["dimensions"]["thickness"] = parent_width
            tire_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(tire_comp)
    if hub_id not in existing_ids:
        hub_comp = {
            "id": hub_id,
            "type": "hub",
            "role": "rotation",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            hub_comp["dimensions"]["outer_diameter"] = round(parent_diameter * 0.4, 2)
            hub_comp["dimension_sources"]["outer_diameter"] = {"source": "derived"}
        if parent_width is not None:
            hub_comp["dimensions"]["thickness"] = parent_width
            hub_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(hub_comp)

    if axle_id not in existing_ids:
        axle_comp = {
            "id": axle_id,
            "type": "axle",
            "role": "rotation",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        axle_comp["dimensions"]["diameter"] = 8
        axle_comp["dimension_sources"]["diameter"] = {
            "source": "inferred_default",
            "confidence": 0.4,
        }
        new_components.append(axle_comp)

    if bearing_1_id not in existing_ids:
        bearing_1_comp = {
            "id": bearing_1_id,
            "type": "bearing",
            "role": "load_support",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {"bore_diameter": 8, "outer_diameter": 22, "width": 7},
            "dimension_sources": {
                "bore_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "outer_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "width": {"source": "standard_catalog", "confidence": 0.9},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(bearing_1_comp)

    if requires_opposed_bearing_stack and bearing_2_id not in existing_ids:
        bearing_2_comp = {
            "id": bearing_2_id,
            "type": "bearing",
            "role": "load_support",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {"bore_diameter": 8, "outer_diameter": 22, "width": 7},
            "dimension_sources": {
                "bore_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "outer_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "width": {"source": "standard_catalog", "confidence": 0.9},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(bearing_2_comp)

    if requires_opposed_bearing_stack and spacer_id not in existing_ids:
        spacer_comp = {
            "id": spacer_id,
            "type": "spacer",
            "role": "spacing",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {
                "inner_diameter": 8,
                "outer_diameter": 12,
                "length": 5,
            },
            "dimension_sources": {
                "inner_diameter": {"source": "derived", "confidence": 0.7},
                "outer_diameter": {"source": "derived", "confidence": 0.6},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(spacer_comp)

    if requires_opposed_bearing_stack and fastener_set_id not in existing_ids:
        axle_diameter = 8.0
        axle_comp_existing = comp_by_id.get(axle_id) if isinstance(comp_by_id, dict) else None
        if isinstance(axle_comp_existing, dict):
            axle_dims_existing = axle_comp_existing.get("dimensions")
            if isinstance(axle_dims_existing, dict):
                axle_d = axle_dims_existing.get("diameter")
                if isinstance(axle_d, (int, float)) and float(axle_d) > 0:
                    axle_diameter = float(axle_d)

        for comp in new_components:
            if isinstance(comp, dict) and comp.get("id") == axle_id:
                axle_dims_new = comp.get("dimensions")
                if isinstance(axle_dims_new, dict):
                    axle_d_new = axle_dims_new.get("diameter")
                    if isinstance(axle_d_new, (int, float)) and float(axle_d_new) > 0:
                        axle_diameter = float(axle_d_new)
                break

        count = 1
        nominal_diameter = float(axle_diameter)
        length = max(12.0, round(nominal_diameter * 2.0, 1))
        fastener_comp = {
            "id": fastener_set_id,
            "type": "fastener",
            "role": "axial_retention",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {
                "count": count,
                "nominal_diameter": nominal_diameter,
                "length": length,
                "bundle_style": "nut_only",
                "application": "axial_retention",
            },
            "dimensions": {
                "count": count,
                "nominal_diameter": nominal_diameter,
                "length": length,
                "bundle_style": "nut_only",
                "application": "axial_retention",
            },
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "derived", "confidence": 0.8},
                "length": {"source": "inferred_default", "confidence": 0.4},
                "bundle_style": {"source": "derived", "confidence": 0.8},
                "application": {"source": "derived", "confidence": 0.8},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(fastener_comp)

    components.extend(new_components)

    new_connections = []

    contract_component_lookup = dict(comp_by_id) if isinstance(comp_by_id, Mapping) else {}
    contract_component_lookup[parent_id] = parent_comp

    body_ref_id = hub_id
    rotation_req = {
        "id": f"req_{parent_id}_body_axle_rotation",
        "between": [body_ref_id, axle_id],
        "purpose": "rotation",
        "roles": ["rotation"],
        "constraints": {
            "coaxial_required": True,
            "allow_rotation": True,
            "lock_translation": True,
        },
        "connection_semantics": {
            "connection_mechanism": "shaft_bore_fit",
            "relation_type": "rotation",
            "reference_component_id": axle_id,
            "moving_component_id": body_ref_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "bore_axis",
            "moving_interface_hint": "bore_axis",
            "orientation_policy": "free",
            "rationale": "Wheel body rotates around the axle on a shared bore axis.",
        },
    }
    new_connections.append(rotation_req)

    bearing_support_1 = {
        "id": f"req_{parent_id}_bearing_1_body_support",
        "between": [bearing_1_id, body_ref_id],
        "purpose": "load_support",
        "roles": ["mounting"],
        "constraints": {"concentric_required": True},
        "connection_semantics": _build_bearing_outer_race_seat_contract(
            host_component_id=body_ref_id,
            bearing_component_id=bearing_1_id,
            rationale="Bearing outer ring seats in the wheel body to provide structural radial support.",
            component_lookup=contract_component_lookup,
        ),
    }
    new_connections.append(bearing_support_1)

    bearing_rotation_1 = {
        "id": f"req_{parent_id}_bearing_1_axle_rotation",
        "between": [bearing_1_id, axle_id],
        "purpose": "rotation_support",
        "roles": ["rotation"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(bearing_rotation_1)

    if requires_opposed_bearing_stack:
        bearing_support_2 = {
            "id": f"req_{parent_id}_bearing_2_body_support",
            "between": [bearing_2_id, body_ref_id],
            "purpose": "load_support",
            "roles": ["mounting"],
            "constraints": {"concentric_required": True},
            "connection_semantics": _build_bearing_outer_race_seat_contract(
                host_component_id=body_ref_id,
                bearing_component_id=bearing_2_id,
                rationale="Bearing outer ring seats in the wheel body to provide structural radial support.",
                component_lookup=contract_component_lookup,
            ),
        }
        new_connections.append(bearing_support_2)

        bearing_rotation_2 = {
            "id": f"req_{parent_id}_bearing_2_axle_rotation",
            "between": [bearing_2_id, axle_id],
            "purpose": "rotation_support",
            "roles": ["rotation"],
            "constraints": {"coaxial_required": True},
        }
        new_connections.append(bearing_rotation_2)

        spacer_constraint = {
            "id": f"req_{parent_id}_spacer_axial",
            "between": [spacer_id, bearing_1_id, bearing_2_id],
            "purpose": "spacing",
            "roles": ["spacing"],
            "constraints": {"gap": parent_width if parent_width else 5},
        }
        new_connections.append(spacer_constraint)

        axial_fastener_nominal = 8.0
        axial_fastener_length = 16.0

        existing_fastener_comp = comp_by_id.get(fastener_set_id) if isinstance(comp_by_id, dict) else None
        if isinstance(existing_fastener_comp, dict):
            existing_dims = existing_fastener_comp.get("dimensions")
            if isinstance(existing_dims, dict):
                existing_nominal = existing_dims.get("nominal_diameter")
                if isinstance(existing_nominal, (int, float)) and float(existing_nominal) > 0:
                    axial_fastener_nominal = float(existing_nominal)
                existing_length = existing_dims.get("length")
                if isinstance(existing_length, (int, float)) and float(existing_length) > 0:
                    axial_fastener_length = float(existing_length)

        for comp in new_components:
            if isinstance(comp, dict) and comp.get("id") == fastener_set_id:
                new_dims = comp.get("dimensions")
                if isinstance(new_dims, dict):
                    new_nominal = new_dims.get("nominal_diameter")
                    if isinstance(new_nominal, (int, float)) and float(new_nominal) > 0:
                        axial_fastener_nominal = float(new_nominal)
                    new_length = new_dims.get("length")
                    if isinstance(new_length, (int, float)) and float(new_length) > 0:
                        axial_fastener_length = float(new_length)
                break

        axial_fastener_size = _nearest_fastener_designation(axial_fastener_nominal, axial_fastener_length)
        fastening_req = {
            "id": f"req_{parent_id}_fastener_axial_clamping",
            "between": [fastener_set_id, axle_id],
            "purpose": "fastening_mechanism",
            "roles": ["fixation"],
            "constraints": {
                "axial_preload": True,
                "retention": "nut_on_threaded_shaft",
            },
            "connection_decision": {
                "method": "bolted_rigid",
                "count": 1,
                "fit_policy": "close_fit",
                "lock": True,
                "fastener_ref_component_id": fastener_set_id,
                "fastener_size": axial_fastener_size,
                "rationale": "Axial retention uses a single nut/washer on shaft; bolt circle forbidden.",
            },
        }
        new_connections.append(fastening_req)

    connection_requirements.extend(new_connections)

    if rim_id and hub_id:
        connection_requirements.append({
            "id": f"req_{parent_id}_rim_hub_fix",
            "between": [rim_id, hub_id],
            "purpose": "structural_fixation",
            "roles": ["mounting", "fixation"],
        })
    if tire_id and rim_id:
        connection_requirements.append({
            "id": f"req_{parent_id}_tire_rim_fix",
            "between": [tire_id, rim_id],
            "purpose": "structural_fixation",
            "roles": ["mounting", "fixation"],
            "connection_semantics": {
                "connection_mechanism": "bonded_tread",
                "relation_type": "fixation",
                "reference_component_id": rim_id,
                "moving_component_id": tire_id,
                "reference_anchor": {"kind": "component_center"},
                "moving_anchor": {"kind": "component_center"},
                "reference_interface_hint": "radial_outer_face",
                "moving_interface_hint": "radial_inner_face",
                "orientation_policy": "locked",
                "rationale": "Tire is retained on the rim as a bonded or seated tread, not by through-fasteners.",
            },
        })


# ============================================================================
# Decomposition Template: SHAFT/AXLE
# ============================================================================


def _shaft_requires_auxiliary_retention_stack(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when a shaft explicitly asks for retainers or spacer hardware."""

    evidence_tokens = {
        "retainer",
        "retention",
        "retaining_ring",
        "snap_ring",
        "circlip",
        "locknut",
        "shaft_collar",
        "collar",
        "threaded_end",
        "threaded shaft",
        "axial_preload",
    }
    truthy_keys = {
        "requires_retention_hardware",
        "retention_hardware",
        "requires_retainers",
        "has_threaded_end",
        "threaded_end",
    }
    count_keys = {"retainer_count", "retainer_quantity"}
    explicit_child_ids = {
        f"{parent_id}_retainer_left",
        f"{parent_id}_retainer_right",
        f"{parent_id}_spacer",
    }
    related_component_ids = {parent_id, *explicit_child_ids}

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _parse_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value) > 0:
            return int(round(float(value)))
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = float(candidate)
            except ValueError:
                return None
            if parsed > 0:
                return int(round(parsed))
        return None

    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "required"}
        return False

    def _contains_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _mapping_requests_retention(mapping: Mapping[str, Any]) -> bool:
        for key in truthy_keys:
            if _is_truthy(mapping.get(key)):
                return True
        for key in count_keys:
            count = _parse_positive_int(mapping.get(key))
            if count is not None and count > 0:
                return True
        return any(_contains_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_retention(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_retention(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {"retainer", "spacer", "fastener", "fastener_set", "bolt_set"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if str(cr.get("purpose") or "").strip().lower() in {"spacing", "fastening_mechanism"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_token(item) for item in _walk_scalars(intent)):
                return True

    return False


def _decompose_shaft_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a shaft only when retention hardware is explicitly requested.
    """

    if not _shaft_requires_auxiliary_retention_stack(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    ):
        return

    # Generate child component IDs
    retainer_left_id = f"{parent_id}_retainer_left"
    retainer_right_id = f"{parent_id}_retainer_right"
    spacer_id = f"{parent_id}_spacer"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [retainer_left_id, retainer_right_id, spacer_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    # Get shaft diameter if available
    shaft_dims = parent_comp.get("dimensions", {})
    shaft_diameter = shaft_dims.get("diameter")
    
    new_components = []
    
    # shaft_retainer_left
    if retainer_left_id not in existing_ids:
        retainer_l = {
            "id": retainer_left_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        if shaft_diameter:
            retainer_l["dimensions"]["bore_diameter"] = shaft_diameter
            retainer_l["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(retainer_l)
    
    # shaft_retainer_right
    if retainer_right_id not in existing_ids:
        retainer_r = {
            "id": retainer_right_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        if shaft_diameter:
            retainer_r["dimensions"]["bore_diameter"] = shaft_diameter
            retainer_r["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(retainer_r)
    
    # shaft_spacer (optional but recommended)
    if spacer_id not in existing_ids:
        spacer = {
            "id": spacer_id,
            "type": "spacer",
            "role": "spacing",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {
                "inner_diameter": shaft_diameter if shaft_diameter else 8,
                "outer_diameter": (shaft_diameter + 4) if shaft_diameter else 12,
                "length": 3,
            },
            "dimension_sources": {
                "inner_diameter": {"source": "derived", "confidence": 0.8},
                "outer_diameter": {"source": "derived", "confidence": 0.7},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(spacer)
    
    components.extend(new_components)
    
    # Auto-generate connection_requirements
    new_connections = []
    
    # Retaining
    for retainer_id in [retainer_left_id, retainer_right_id]:
        if retainer_id not in existing_ids:
            req = {
                "id": f"req_{retainer_id}_retention",
                "between": [retainer_id, parent_id],
                "purpose": "fastening_mechanism",
                "roles": ["fixation"],
                "constraints": {"axial_retention": True},
            }
            new_connections.append(req)
    
    connection_requirements.extend(new_connections)


# ============================================================================
# Decomposition Template: BEARING UNIT
# ============================================================================


def _bearing_unit_requires_auxiliary_components(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when a bearing explicitly asks for seat or retainer hardware."""

    evidence_tokens = {
        "bearing_seat",
        "outer_race_seat",
        "retainer",
        "retention",
        "snap_ring",
        "circlip",
        "end_cap",
        "cartridge",
    }
    truthy_keys = {
        "requires_bearing_seat",
        "requires_retainer",
        "requires_housing",
        "cartridge_unit",
    }
    explicit_child_ids = {f"{parent_id}_seat", f"{parent_id}_retainer"}
    related_component_ids = {parent_id, *explicit_child_ids}

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _contains_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "required"}
        return False

    def _mapping_requests_auxiliary_components(mapping: Mapping[str, Any]) -> bool:
        for key in truthy_keys:
            if _is_truthy(mapping.get(key)):
                return True
        return any(_contains_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_auxiliary_components(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_auxiliary_components(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {"bearing_seat", "retainer", "housing"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if any(_contains_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_token(item) for item in _walk_scalars(intent)):
                return True

    return False


def _decompose_bearing_unit_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a bearing only when seat or retainer hardware is explicitly requested.
    """

    if not _bearing_unit_requires_auxiliary_components(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    ):
        return

    seat_id = f"{parent_id}_seat"
    retainer_id = f"{parent_id}_retainer"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    
    # Bearing is typically already decomposed; just add seat and retainer if missing
    new_components = []
    
    # Bearing seat (structural feature, can be virtual)
    if seat_id not in existing_ids:
        seat = {
            "id": seat_id,
            "type": "bearing_seat",
            "role": "mounting",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        # Bearing outer diameter should match seat bore
        bearing_dims = parent_comp.get("dimensions", {})
        if "outer_diameter" in bearing_dims:
            seat["dimensions"]["bore_diameter"] = bearing_dims.get("outer_diameter")
            seat["dimension_sources"]["bore_diameter"] = {"source": "standard_catalog"}
        new_components.append(seat)
    
    # Retainer (cap, e-clip, or snap ring)
    if retainer_id not in existing_ids:
        retainer = {
            "id": retainer_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        new_components.append(retainer)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    if seat_id not in existing_ids:
        req = {
            "id": f"req_{parent_id}_seat_fixation",
            "between": [parent_id, seat_id],
            "purpose": "structural_fixation",
            "roles": ["mounting"],
            "constraints": {"concentric_required": True},
        }
        new_connections.append(req)
    
    if retainer_id not in existing_ids:
        req = {
            "id": f"req_{parent_id}_retainer_fixation",
            "between": [retainer_id, parent_id],
            "purpose": "fastening_mechanism",
            "roles": ["fixation"],
            "constraints": {"axial_retention": True},
        }
        new_connections.append(req)
    
    connection_requirements.extend(new_connections)


# ============================================================================
# Decomposition Template: MOTOR + GEARBOX (with OUTPUT SHAFT)
# ============================================================================


def _decompose_motor_gearbox_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    If component is motor/gearbox, ensure output_shaft is explicit.
    Generate: motor (black-box), gearbox (black-box), output_shaft, mounting_flange
    """
    comp_type = str(parent_comp.get("type", "")).lower()

    # Detect if this is a combined motor+gearbox or separate
    is_motor = "motor" in comp_type or "电机" in parent_id
    is_gearbox = "gearbox" in comp_type or "减速器" in parent_id

    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    
    # If it's already a motor or gearbox separately, check if output_shaft exists
    if is_motor or is_gearbox:
        shaft_id = f"{parent_id}_output_shaft"
        flange_id = f"{parent_id}_mounting_flange"
        
        if shaft_id in existing_ids:
            return  # Already decomposed
        
        new_components = []
        
        # Output shaft
        shaft = {
            "id": shaft_id,
            "type": "shaft",
            "role": "rotation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {"diameter": 6, "length": 20},
            "dimension_sources": {
                "diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(shaft)
        
        # Mounting flange
        flange = {
            "id": flange_id,
            "type": "mounting_flange",
            "role": "mounting",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {"diameter": 40, "thickness": 5},
            "dimension_sources": {
                "diameter": {"source": "inferred_default", "confidence": 0.4},
                "thickness": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "plate", "cross_section": "rectangular"},
        }
        new_components.append(flange)
        
        components.extend(new_components)
        
        # Auto-generate connections
        new_connections = []
        
        # Output shaft 闁?gearbox (torque transfer)
        req = {
            "id": f"req_{parent_id}_output_shaft_connection",
            "between": [shaft_id, parent_id],
            "purpose": "torque_transfer",
            "roles": ["rotation", "torque_transfer"],
            "constraints": {"coaxial_required": True},
        }
        new_connections.append(req)
        
        # Mounting flange 闁?motor/gearbox (structural fixation)
        req = {
            "id": f"req_{parent_id}_mounting_flange",
            "between": [flange_id, parent_id],
            "purpose": "structural_fixation",
            "roles": ["mounting"],
        }
        new_connections.append(req)
        
        connection_requirements.extend(new_connections)


# ============================================================================
# Decomposition Template: COUPLING
# ============================================================================


def _decompose_coupling_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose coupling into: coupling_body, clamp_screw_set, optional key
    """
    
    body_id = f"{parent_id}_body"
    screw_set_id = f"{parent_id}_clamp_screw_set"
    key_id = f"{parent_id}_key"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [body_id, screw_set_id, key_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    coupling_dims = parent_comp.get("dimensions", {})
    bore_diameter = coupling_dims.get("bore_diameter")
    
    new_components = []
    
    # Coupling body
    if body_id not in existing_ids:
        body = {
            "id": body_id,
            "type": "coupling_body",
            "role": "torque_transfer",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if bore_diameter:
            body["dimensions"]["bore_diameter"] = bore_diameter
            body["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(body)
    
    # Clamp screw bundle
    if screw_set_id not in existing_ids:
        count = 2
        screw_set = {
            "id": screw_set_id,
            "type": "fastener",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": count, "nominal_diameter": 4.0, "length": 12.0},
            "dimensions": {"count": count, "nominal_diameter": 4.0, "length": 12.0},
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(screw_set)
    
    # Key (optional but useful)
    if key_id not in existing_ids:
        key = {
            "id": key_id,
            "type": "key",
            "role": "torque_transfer",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {
                "width": bore_diameter / 4 if bore_diameter else 2,
                "height": bore_diameter / 4 if bore_diameter else 2,
                "length": bore_diameter / 2 if bore_diameter else 4,
            },
            "dimension_sources": {
                "width": {"source": "derived", "confidence": 0.6},
                "height": {"source": "derived", "confidence": 0.6},
                "length": {"source": "derived", "confidence": 0.6},
            },
            "shape_semantics": {"type": "prismatic", "cross_section": "rectangular"},
        }
        new_components.append(key)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    # Coupling body 闁?shaft
    req = {
        "id": f"req_{parent_id}_body_shaft",
        "between": [body_id, parent_id],
        "purpose": "torque_transfer",
        "roles": ["torque_transfer"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(req)
    
    # Clamp screw 闁?coupling body
    req = {
        "id": f"req_{parent_id}_screw_fastening",
        "between": [screw_set_id, body_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    # Key (optional, for additional torque transfer)
    req = {
        "id": f"req_{parent_id}_key_shaft",
        "between": [key_id, parent_id],
        "purpose": "torque_transfer",
        "roles": ["torque_transfer"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(req)
    
    connection_requirements.extend(new_connections)


# ============================================================================
# Decomposition Template: PLATE ASSEMBLY (top + bottom with fasteners)
# ============================================================================


def _decompose_plate_assembly_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose plate assembly into: standoff_set, bolt_set, nut_set
    """
    
    standoff_id = f"{parent_id}_standoff_set"
    bolt_id = f"{parent_id}_bolt_set"
    nut_id = f"{parent_id}_nut_set"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [standoff_id, bolt_id, nut_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    plate_dims = parent_comp.get("dimensions", {})
    plate_thickness = plate_dims.get("thickness", 3)
    
    new_components = []
    
    # Standoff set
    if standoff_id not in existing_ids:
        standoff = {
            "id": standoff_id,
            "type": "standoff_set",
            "role": "spacing",
            "parent_id": parent_id,
            "parameters": {"count": 4},
            "dimensions": {
                "inner_diameter": 4,
                "outer_diameter": 6,
                "length": plate_thickness + 5,
            },
            "dimension_sources": {
                "length": {
                    "source": "derived",
                    "derived_from": [f"{parent_id}.thickness"],
                    "confidence": 0.7,
                }
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(standoff)
    
    # Bolt set
    if bolt_id not in existing_ids:
        bolt = {
            "id": bolt_id,
            "type": "fastener",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": 4, "nominal_diameter": 4.0, "length": float(plate_thickness) + 8.0},
            "dimensions": {"count": 4, "nominal_diameter": 4.0, "length": float(plate_thickness) + 8.0},
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {
                    "source": "derived",
                    "derived_from": [f"{parent_id}.thickness"],
                    "confidence": 0.6,
                },
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(bolt)
    
    # Nut set
    if nut_id not in existing_ids:
        nut = {
            "id": nut_id,
            "type": "nut_set",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": 4},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        new_components.append(nut)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    # Standoff 闁?plate (spacing constraint)
    req = {
        "id": f"req_{parent_id}_standoff_spacing",
        "between": [standoff_id, parent_id],
        "purpose": "spacing",
        "roles": ["spacing"],
        "constraints": {"gap": plate_thickness + 5},
    }
    new_connections.append(req)
    
    # Bolt 闁?plate (fastening)
    req = {
        "id": f"req_{parent_id}_bolt_fastening",
        "between": [bolt_id, parent_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    # Nut 闁?bolt (fastening pair)
    req = {
        "id": f"req_{parent_id}_nut_bolt",
        "between": [nut_id, bolt_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    connection_requirements.extend(new_connections)


def _fill_missing_dimensions(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id: dict[str, str] = {}
    comp_by_id: dict[str, Mapping] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and isinstance(ctype, str):
            type_by_id[cid] = ctype
            comp_by_id[cid] = comp

    def _get_dim(dims: Mapping, *keys: str) -> float | None:
        for key in keys:
            value = dims.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _set_dim(
        dims: Dict[str, Any],
        sources: Dict[str, Any],
        key: str,
        value: float,
        derived_from: list[str] | None = None,
        source: str = "derived",
        confidence: float | None = None,
    ) -> None:
        if key in dims:
            return
        dims[key] = float(value)
        sources[key] = {
            "source": source,
            "derived_from": derived_from or [],
        }
        if confidence is not None:
            sources[key]["confidence"] = float(confidence)

    def _related_component_ids(comp_id: str) -> set[str]:
        related: set[str] = set()
        for cr in payload.get("connection_requirements", []) or []:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if isinstance(between, list) and comp_id in between:
                for cid in between:
                    if isinstance(cid, str) and cid != comp_id:
                        related.add(cid)
        return related

    def _find_related_dim(comp_id: str, target_types: set[str], dim_keys: list[str]) -> float | None:
        for other_id in _related_component_ids(comp_id):
            if type_by_id.get(other_id) not in target_types:
                continue
            other = comp_by_id.get(other_id, {})
            dims_other = other.get("dimensions") if isinstance(other, Mapping) else None
            if isinstance(dims_other, Mapping):
                value = _get_dim(dims_other, *dim_keys)
                if isinstance(value, (int, float)):
                    return float(value)
        return None

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        if comp.get("type") == "subassembly":
            continue

        dims = comp.get("dimensions")
        if not isinstance(dims, Mapping):
            dims = {}
            comp["dimensions"] = dims
        dims = dict(dims)
        comp["dimensions"] = dims

        sources = comp.get("dimension_sources")
        if not isinstance(sources, Mapping):
            sources = {}
        sources = dict(sources)
        comp["dimension_sources"] = sources

        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else ""
        comp_type = comp.get("type") if isinstance(comp.get("type"), str) else ""

        if comp_type in {"wheel", "tire", "rim"}:
            radius = _get_dim(dims, "outer_radius", "radius")
            if radius is None:
                diameter = _get_dim(dims, "outer_diameter", "diameter")
                if diameter is not None:
                    radius = diameter / 2.0
                    _set_dim(dims, sources, "outer_radius", radius, ["outer_diameter"])

            # ----------------------------------------------------------
            # Rim / tire differentiation: rim sits inside the tire.
            # When no explicit outer_radius is present, derive from the
            # parent wheel component (already processed earlier in this
            # loop because the parent appears before children in the
            # component list).
            #   tire  -> keeps full parent wheel outer_radius
            #   rim   -> 72 % of parent wheel outer_radius
            # ----------------------------------------------------------
            if radius is None and comp_type in {"tire", "rim"}:
                parent_id = comp.get("parent_id") if isinstance(comp.get("parent_id"), str) else ""
                parent = comp_by_id.get(parent_id)
                if isinstance(parent, Mapping):
                    p_dims = parent.get("dimensions")
                    if isinstance(p_dims, Mapping):
                        parent_radius = _get_dim(p_dims, "outer_radius", "radius")
                        if parent_radius is not None:
                            if comp_type == "rim":
                                radius = round(parent_radius * 0.72, 2)
                                _set_dim(dims, sources, "outer_radius", radius,
                                         ["parent.outer_radius * 0.72"],
                                         source="derived", confidence=0.7)
                            else:  # tire
                                radius = parent_radius
                                _set_dim(dims, sources, "outer_radius", radius,
                                         ["parent.outer_radius"],
                                         source="derived", confidence=0.7)

            if radius is None:
                radius = 30.0
                _set_dim(dims, sources, "outer_radius", radius, ["default"], source="inferred_default", confidence=0.4)
            width = _get_dim(dims, "width", "thickness")
            if width is None:
                width = max(6.0, round(radius * 0.4, 2))
                _set_dim(dims, sources, "width", width, ["outer_radius"], source="derived", confidence=0.6)
            if _get_dim(dims, "thickness") is None and isinstance(width, (int, float)):
                _set_dim(dims, sources, "thickness", float(width), ["width"], source="derived", confidence=0.7)
            if comp_type in {"tire", "rim"}:
                inner_radius = _get_dim(dims, "inner_radius")
                if inner_radius is None and comp_type == "tire":
                    # Tire inner = rim outer; find sibling rim
                    _parent_id = comp.get("parent_id") if isinstance(comp.get("parent_id"), str) else ""
                    for sib in components:
                        if (isinstance(sib, Mapping) and sib.get("parent_id") == _parent_id
                                and sib.get("type") == "rim" and sib.get("id") != comp_id):
                            sib_dims = sib.get("dimensions") if isinstance(sib.get("dimensions"), Mapping) else {}
                            rim_outer = _get_dim(sib_dims, "outer_radius")
                            if rim_outer is not None:
                                inner_radius = rim_outer
                                _set_dim(dims, sources, "inner_radius", inner_radius,
                                         ["sibling_rim.outer_radius"],
                                         source="derived", confidence=0.7)
                            break
                if inner_radius is None and isinstance(radius, (int, float)):
                    inner_radius = max(0.1, round(float(radius) * 0.72, 2))
                    _set_dim(dims, sources, "inner_radius", inner_radius, ["outer_radius"], source="derived", confidence=0.6)
                if _get_dim(dims, "inner_diameter") is None and isinstance(inner_radius, (int, float)):
                    _set_dim(dims, sources, "inner_diameter", round(float(inner_radius) * 2.0, 2), ["inner_radius"], source="derived", confidence=0.7)

        if comp_type in {"hub"}:
            radius = _get_dim(dims, "outer_radius", "radius")
            if radius is None:
                diameter = _get_dim(dims, "outer_diameter", "diameter")
                if diameter is not None:
                    radius = diameter / 2.0
                    _set_dim(dims, sources, "outer_radius", radius, ["outer_diameter"])
            if radius is None:
                radius = 14.0
                _set_dim(dims, sources, "outer_radius", radius, ["default"], source="inferred_default", confidence=0.4)
            thickness = _get_dim(dims, "thickness", "width")
            if thickness is None:
                thickness = max(4.0, round(radius * 0.4, 2))
                _set_dim(dims, sources, "thickness", thickness, ["outer_radius"], source="derived", confidence=0.6)

            bore = _get_dim(dims, "bore_diameter", "inner_diameter")
            if bore is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    bore = shaft_d + 0.2
                    _set_dim(dims, sources, "bore_diameter", bore, ["shaft.diameter"], source="derived", confidence=0.7)
            if isinstance(bore, (int, float)):
                if _get_dim(dims, "inner_diameter") is None:
                    _set_dim(dims, sources, "inner_diameter", float(bore), ["bore_diameter"], source="derived", confidence=0.8)
                if _get_dim(dims, "inner_radius") is None:
                    _set_dim(dims, sources, "inner_radius", round(float(bore) / 2.0, 2), ["bore_diameter"], source="derived", confidence=0.8)

        if comp_type in {"shaft", "axle"}:
            diameter = _get_dim(dims, "diameter")
            if diameter is None:
                diameter = 6.0
                _set_dim(dims, sources, "diameter", diameter, ["default"], source="inferred_default", confidence=0.4)
            length = _get_dim(dims, "length")
            if length is None:
                length = max(20.0, round(diameter * 10.0, 2))
                _set_dim(dims, sources, "length", length, ["diameter"], source="derived", confidence=0.6)

        if comp_type == "bearing":
            bore = _get_dim(dims, "bore_diameter", "inner_diameter")
            if bore is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    bore = shaft_d + 0.2
                    _set_dim(dims, sources, "bore_diameter", bore, ["shaft.diameter"], source="derived", confidence=0.7)
            outer = _get_dim(dims, "outer_diameter")
            if outer is None and bore is not None:
                outer = round(bore * 2.75, 2)
                _set_dim(dims, sources, "outer_diameter", outer, ["bore_diameter"], source="derived", confidence=0.6)
            width = _get_dim(dims, "width", "thickness")
            if width is None and bore is not None:
                width = round(bore * 0.9, 2)
                _set_dim(dims, sources, "width", width, ["bore_diameter"], source="derived", confidence=0.6)

        if comp_type == "fastener":
            nominal = _get_dim(dims, "nominal_diameter", "diameter")
            if nominal is None:
                nominal = 4.0
                _set_dim(dims, sources, "nominal_diameter", nominal, ["default"], source="inferred_default", confidence=0.4)
            length = _get_dim(dims, "length")
            if length is None:
                length = max(8.0, round(nominal * 3.0, 2))
                _set_dim(dims, sources, "length", length, ["nominal_diameter"], source="derived", confidence=0.6)
            count = dims.get("count")
            if not isinstance(count, (int, float)):
                _set_dim(dims, sources, "count", 4, ["default"], source="inferred_default", confidence=0.5)

        if comp_type in {"arm", "wheel_arm"}:
            length = _get_dim(dims, "length")
            if length is None:
                wheel_r = _find_related_dim(comp_id, {"wheel"}, ["outer_radius", "radius"])
                if wheel_r is not None:
                    length = round(wheel_r * 2.5, 2)
                    _set_dim(dims, sources, "length", length, ["wheel.outer_radius"], source="derived", confidence=0.6)
                else:
                    length = 100.0
                    _set_dim(dims, sources, "length", length, ["default"], source="inferred_default", confidence=0.4)
            width = _get_dim(dims, "width")
            if width is None:
                width = round(length * 0.2, 2)
                _set_dim(dims, sources, "width", width, ["length"], source="derived", confidence=0.6)
            thickness = _get_dim(dims, "thickness")
            if thickness is None:
                thickness = round(width * 0.3, 2)
                _set_dim(dims, sources, "thickness", thickness, ["width"], source="derived", confidence=0.6)

        if comp_type == "spacer":
            inner = _get_dim(dims, "inner_diameter")
            if inner is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    inner = shaft_d + 0.3
                    _set_dim(dims, sources, "inner_diameter", inner, ["shaft.diameter"], source="derived", confidence=0.7)
            outer = _get_dim(dims, "outer_diameter")
            if outer is None and inner is not None:
                _set_dim(dims, sources, "outer_diameter", round(inner * 1.6, 2), ["inner_diameter"], source="derived", confidence=0.6)
            thickness = _get_dim(dims, "thickness")
            if thickness is None:
                _set_dim(dims, sources, "thickness", 2.0, ["default"], source="inferred_default", confidence=0.4)

        if not dims:
            if comp_type in {"fastener_set", "bolt_set"}:
                _set_dim(dims, sources, "nominal_diameter", 4.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "length", 12.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "count", 4.0, ["default"], source="inferred_default", confidence=0.5)
            elif comp_type == "nut_set":
                _set_dim(dims, sources, "nominal_diameter", 4.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 3.2, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "count", 4.0, ["default"], source="inferred_default", confidence=0.5)
            elif comp_type == "retainer":
                _set_dim(dims, sources, "bore_diameter", 8.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 1.5, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "bearing_seat":
                _set_dim(dims, sources, "bore_diameter", 22.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 7.0, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "mounting_flange":
                _set_dim(dims, sources, "diameter", 40.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 5.0, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "key":
                _set_dim(dims, sources, "width", 2.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "height", 2.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "length", 6.0, ["default"], source="inferred_default", confidence=0.4)


def _infer_standard_parts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    def _dimension_source(comp: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
        srcs = comp.get("dimension_sources")
        if not isinstance(srcs, Mapping):
            return None
        source = srcs.get(key)
        if isinstance(source, Mapping):
            return source
        return None

    def _is_bore_only_inference(comp: Mapping[str, Any], *, has_outer: bool, has_width: bool) -> bool:
        if not has_outer or not has_width:
            return True
        outer_src = _dimension_source(comp, "outer_diameter")
        width_src = _dimension_source(comp, "thickness") or _dimension_source(comp, "width")

        def _derived_from_bore(src: Mapping[str, Any] | None) -> bool:
            if not isinstance(src, Mapping):
                return False
            if src.get("source") != "derived":
                return False
            from_list = src.get("derived_from")
            if isinstance(from_list, list):
                return any(isinstance(v, str) and "bore_diameter" in v for v in from_list)
            return False

        return _derived_from_bore(outer_src) and _derived_from_bore(width_src)

    def _part_class_for_category(category: str) -> str:
        cat = category.strip().lower()
        if cat in {"fastener", "bolt", "screw", "washer", "nut", "rivet"}:
            return "fasteners"
        if cat == "bearing":
            return "bearings"
        return "others"

    standard_parts = payload.get("standard_parts")
    if not isinstance(standard_parts, list):
        standard_parts = []
        payload["standard_parts"] = standard_parts

    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    unresolved_parts: list[Dict[str, Any]] = []
    unresolved_bearing_component_ids: set[str] = set()

    def _connection_ids_for_component(comp_id: str) -> list[str]:
        ids: list[str] = []
        for cr in payload.get("connection_requirements", []) or []:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if isinstance(between, list) and comp_id in between:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    ids.append(cr_id)
        return ids

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_type = comp.get("type")
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else None
        std_id = f"std_{comp_id}" if comp_id else None
        if std_id and any(isinstance(p, Mapping) and p.get("id") == std_id for p in standard_parts):
            continue

        if comp_type == "fastener":
            nominal = dims.get("nominal_diameter")
            length = dims.get("length")
            if not isinstance(nominal, (int, float)) or not isinstance(length, (int, float)):
                unresolved_parts.append({
                    "id": f"std_{comp_id}" if comp_id else f"std_fastener_unresolved_{len(unresolved_parts) + 1}",
                    "category": "fastener",
                    "part_class": "fasteners",
                    "component_id": comp_id,
                    "reason": "missing_nominal_diameter_or_length",
                    "available": {
                        "nominal_diameter": nominal,
                        "length": length,
                    },
                    "selection_rationale": "Fastener standard selection requires nominal_diameter and length.",
                })
                continue

            designation = _nearest_fastener_designation(float(nominal), float(length))
            quantity = dims.get("count") if isinstance(dims.get("count"), (int, float)) else 1
            applied_to = _connection_ids_for_component(comp_id) if comp_id else []
            standard_parts.append({
                "id": f"std_{comp_id}" if comp_id else f"std_fastener_{len(standard_parts) + 1}",
                "category": "fastener",
                "part_class": "fasteners",
                "designation": designation,
                "quantity": int(quantity),
                "applied_to": applied_to,
                "selection_rationale": "Nearest standard size based on nominal_diameter and length"
            })

        if comp_type == "bearing":
            params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
            bore = dims.get("bore_diameter") if isinstance(dims.get("bore_diameter"), (int, float)) else None
            outer = dims.get("outer_diameter") if isinstance(dims.get("outer_diameter"), (int, float)) else None
            width = dims.get("width") if isinstance(dims.get("width"), (int, float)) else None

            designation_raw = None
            for candidate in (
                comp.get("designation"),
                params.get("designation") if isinstance(params, Mapping) else None,
                params.get("bearing_designation") if isinstance(params, Mapping) else None,
            ):
                if isinstance(candidate, str) and candidate.strip():
                    designation_raw = candidate.strip()
                    break

            series_hint = None
            for candidate in (
                comp.get("iso_series"),
                params.get("iso_series") if isinstance(params, Mapping) else None,
            ):
                if isinstance(candidate, str) and candidate.strip():
                    series_hint = candidate.strip()
                    break

            resolved_item: Dict[str, Any] | None = None
            rationale = ""

            if designation_raw:
                resolved_item = find_bearing_by_designation(designation_raw)
                if resolved_item:
                    rationale = "Catalog lookup by designation"

            has_complete_dims = all(isinstance(v, (int, float)) for v in [bore, outer, width])
            bore_only = isinstance(bore, (int, float)) and not isinstance(outer, (int, float)) and not isinstance(width, (int, float))

            if resolved_item is None and has_complete_dims and not designation_raw and not series_hint:
                if not _is_bore_only_inference(comp, has_outer=True, has_width=True):
                    resolved_item = nearest_bearing_by_dims(float(bore), float(outer), float(width))
                    rationale = "Nearest catalog bearing by d/D/B"

            if resolved_item is None and series_hint and isinstance(bore, (int, float)):
                resolved_item = select_bearing_by_series_and_bore(series_hint, float(bore))
                if resolved_item:
                    rationale = f"Catalog lookup by iso_series={series_hint} and bore"

            if resolved_item:
                designation = str(resolved_item["code"])
                dims["bore_diameter"] = float(resolved_item["bore"])
                dims["outer_diameter"] = float(resolved_item["outer"])
                dims["width"] = float(resolved_item["width"])
                dim_sources = comp.get("dimension_sources") if isinstance(comp.get("dimension_sources"), Mapping) else {}
                dim_sources = dict(dim_sources)
                dim_sources["bore_diameter"] = {"source": "standard_catalog", "confidence": 0.95}
                dim_sources["outer_diameter"] = {"source": "standard_catalog", "confidence": 0.95}
                dim_sources["width"] = {"source": "standard_catalog", "confidence": 0.95}
                comp["dimension_sources"] = dim_sources
            else:
                candidate_series = candidate_series_for_bore(float(bore)) if isinstance(bore, (int, float)) else []
                unresolved_parts.append({
                    "id": f"std_{comp_id}" if comp_id else f"std_bearing_unresolved_{len(unresolved_parts) + 1}",
                    "category": "bearing",
                    "part_class": "bearings",
                    "component_id": comp_id,
                    "reason": "missing_closed_loop_bearing_parameters",
                    "available": {
                        "designation": designation_raw,
                        "iso_series": series_hint,
                        "bore_diameter": bore,
                        "outer_diameter": outer,
                        "width": width,
                    },
                    "candidate_series": candidate_series,
                    "selection_rationale": (
                        "Only bore is not enough to uniquely determine OD/width; "
                        "requires designation or iso_series+bore or complete d/D/B"
                    ),
                })
                if isinstance(comp_id, str):
                    unresolved_bearing_component_ids.add(comp_id)
                continue

            applied_to = _connection_ids_for_component(comp_id) if comp_id else []
            standard_parts.append({
                "id": f"std_{comp_id}" if comp_id else f"std_bearing_{len(standard_parts) + 1}",
                "category": "bearing",
                "part_class": "bearings",
                "designation": designation,
                "quantity": 1,
                "dimensions": {
                    "d_mm": dims.get("bore_diameter"),
                    "D_mm": dims.get("outer_diameter"),
                    "B_mm": dims.get("width"),
                },
                "applied_to": applied_to,
                "selection_rationale": rationale or "Catalog-resolved bearing"
            })

    for part in standard_parts:
        if not isinstance(part, Mapping):
            continue
        category = part.get("category") if isinstance(part.get("category"), str) else "other"
        if "part_class" not in part:
            part["part_class"] = _part_class_for_category(category)

    metadata["standard_parts_unresolved"] = unresolved_parts
    metadata["unresolved_bearing_component_ids"] = sorted(unresolved_bearing_component_ids)
    metadata["bearing_resolution_summary"] = {
        "resolved": len(
            [
                p for p in standard_parts
                if isinstance(p, Mapping)
                and p.get("category") == "bearing"
            ]
        ),
        "unresolved": len(unresolved_parts),
    }


def _validate_no_relations(payload: Dict[str, Any]) -> None:
    if "relations" in payload:
        raise ValueError("Agent1 must not output relations; remove relations[] from KG")


def _sync_dimensions_and_parameters(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    _, children_by_parent = _collect_component_hierarchy_candidates(payload)
    hierarchy_parent_ids = set(children_by_parent.keys())
    for comp in components:
        if not isinstance(comp, Mapping):
            continue

        comp_type = comp.get("type")
        dims = comp.get("dimensions")
        params = comp.get("parameters")

        if dims is None and isinstance(params, Mapping):
            comp["dimensions"] = dict(params)
            dims = comp["dimensions"]
        if params is None and isinstance(dims, Mapping):
            comp["parameters"] = dict(dims)
            params = comp["parameters"]

        if not isinstance(dims, Mapping):
            raise ValueError(
                f"Component '{comp.get('id')}' must include 'dimensions' as an object."
            )
        if not isinstance(params, Mapping):
            raise ValueError(
                f"Component '{comp.get('id')}' must include 'parameters' as an object."
            )

        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else ""
        kind = comp.get("kind")
        policy = comp.get("modeling_policy")
        is_container_only = bool(comp.get("is_container_only"))
        if comp_id and comp_id in hierarchy_parent_ids and isinstance(comp, dict):
            if _preserve_hierarchy_parent_as_physical(comp):
                _mark_component_as_physical_part(comp)
                kind = "part"
                policy = str(comp.get("modeling_policy") or "must_model")
                is_container_only = False
            else:
                _mark_component_as_container_only(
                    comp,
                    note="inferred_hierarchy_container_from_child_components",
                )
                kind = "assembly_node"
                policy = "container_only"
                is_container_only = True
        if isinstance(kind, str) and kind.strip() == "assembly_node":
            is_container_only = True
        if isinstance(policy, str) and policy.strip().lower() in {"container_only", "reference_only"}:
            is_container_only = True

        if is_container_only:
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            continue

        if comp_type != "subassembly" and len(dims) == 0:
            if comp_type in {"fastener", "fastener_set", "bolt_set"}:
                dims = {"nominal_diameter": 4.0, "length": 12.0, "count": 4.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "nut_set":
                dims = {"nominal_diameter": 4.0, "thickness": 3.2, "count": 4.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type in {"retainer", "bearing_seat"}:
                dims = {"bore_diameter": 8.0, "thickness": 2.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "key":
                dims = {"width": 2.0, "height": 2.0, "length": 6.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "mounting_flange":
                dims = {"diameter": 40.0, "thickness": 5.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)

        if comp_type != "subassembly" and len(dims) == 0:
            raise ValueError(
                f"Component '{comp.get('id')}' is missing dimensions. Agent1 must provide full sizes."
            )

        if dims != params:
            comp["parameters"] = dict(dims)
            params = comp["parameters"]

        dim_sources = comp.get("dimension_sources")
        if not isinstance(dim_sources, Mapping):
            comp["dimension_sources"] = {k: {"source": "input", "confidence": 0.9} for k in dims.keys()}
        else:
            source_alias = {
                "explicit": "input",
                "manual": "input",
                "catalog": "standard_catalog",
                "default": "inferred_default",
            }
            normalized_sources: Dict[str, Any] = {}
            for key, value in dim_sources.items():
                if isinstance(value, str):
                    normalized = source_alias.get(value, value)
                    normalized_sources[key] = {"source": normalized, "confidence": 0.9 if normalized == "input" else 0.7}
                elif isinstance(value, Mapping):
                    if "source" in value:
                        normalized_value = dict(value)
                        raw_source = normalized_value.get("source")
                        if isinstance(raw_source, str):
                            normalized_value["source"] = source_alias.get(raw_source, raw_source)
                        normalized_sources[key] = normalized_value
                    else:
                        normalized_sources[key] = {"source": "input", "confidence": 0.9}
                else:
                    normalized_sources[key] = {"source": "input", "confidence": 0.9}
            for dim_key in dims.keys():
                if dim_key not in normalized_sources:
                    normalized_sources[dim_key] = {"source": "input", "confidence": 0.9}
            comp["dimension_sources"] = normalized_sources

        shape_semantics = comp.get("shape_semantics")
        if not isinstance(shape_semantics, Mapping) or not shape_semantics.get("type"):
            raise ValueError(
                f"Component '{comp.get('id')}' must include shape_semantics.type."
            )


def _call_llm_to_generate_kg(requirement_text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """閻犲鍟伴弫?LLM 閻忓繐妫滈崵婊堟倿閹偊鍤旈悷灏佸亾闂傚洠鍋撴慨鐟板€藉ù鍡涘箲椤叀绀嬮柣顓滃劥閻︽垿宕堕幑鎰殤"""

    def _subassembly_of(payload: Dict[str, Any], comp_id: str) -> str | None:
        """Return the parent subassembly ID if this component is a member of one."""
        subassemblies = payload.get("subassemblies", [])
        if not isinstance(subassemblies, list):
            return None
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            members = sa.get("component_ids", [])
            if isinstance(sa_id, str) and isinstance(members, list) and comp_id in members:
                return sa_id
        # Also check parent_id in component itself
        components = payload.get("components", [])
        if isinstance(components, list):
            for comp in components:
                if isinstance(comp, Mapping) and comp.get("id") == comp_id:
                    parent_id = comp.get("parent_id")
                    if isinstance(parent_id, str):
                        return parent_id
        return None

    def _connected_components(payload: Dict[str, Any], comp_id: str) -> set[str]:
        """Return all component IDs that share a connection_requirement with comp_id."""
        result: set[str] = set()
        crs = payload.get("connection_requirements", [])
        if isinstance(crs, list):
            for cr in crs:
                if isinstance(cr, Mapping):
                    between = cr.get("between", [])
                    if isinstance(between, list) and comp_id in between:
                        for other_id in between:
                            if isinstance(other_id, str) and other_id != comp_id:
                                result.add(other_id)
        return result

    def _type_by_id(payload: Dict[str, Any]) -> dict[str, str]:
        """Build component type mapping."""
        result: dict[str, str] = {}
        components = payload.get("components", [])
        if isinstance(components, list):
            for comp in components:
                if isinstance(comp, Mapping):
                    comp_id = comp.get("id")
                    comp_type = comp.get("type")
                    if isinstance(comp_id, str) and isinstance(comp_type, str):
                        result[comp_id] = comp_type
        return result

    def _is_structural_type(ctype: str) -> bool:
        """Check if a component type represents structural/main body components."""
        structural_tokens = {
            "frame", "base", "housing", "mount", "bracket", "carrier",
            "hub", "structure", "plate", "chassis", "block", "body"
        }
        return any(token in ctype.lower() for token in structural_tokens)

    def _choose_structural_host(payload: Dict[str, Any], subject_id: str, candidates: list[str]) -> str | None:
        """
        Select the best structural host for a component using topology-based scoring.
        
        Scoring rules (deterministic, ties broken by component ID lexicographically):
        - Subassembly membership: +3 (same subassembly as subject)
        - Structural type: +2 (is_structural_type)
        - Already connected: +2 (shares existing CR with subject)
        - Fastener penalty: -5 (never select fastener)
        - Wheel penalty: -3 (rotary, avoid as structural host)
        
        Returns: Best scoring candidate, or None if all candidates are disqualified.
        """
        type_map = _type_by_id(payload)
        subject_sa = _subassembly_of(payload, subject_id)
        connected = _connected_components(payload, subject_id)
        
        scored: list[tuple[int, str]] = []
        for cand_id in candidates:
            if cand_id == subject_id:
                continue  # Skip self
            
            ctype = type_map.get(cand_id, "")
            
            # Disqualify fasteners and wheels
            if ctype == "fastener":
                continue
            if ctype == "wheel":
                continue
            
            score = 0
            
            # Scoring
            if subject_sa and _subassembly_of(payload, cand_id) == subject_sa:
                score += 3
            if _is_structural_type(ctype):
                score += 2
            if cand_id in connected:
                score += 2
            
            scored.append((score, cand_id))
        
        if not scored:
            return None
        
        # Sort by: (score desc, id asc) for deterministic tie-breaking
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    def _cleanup_auto_generated_connections(payload: Dict[str, Any]) -> None:
        """
        Remove all previously auto-generated connection requirements.
        This ensures deterministic completion uses latest logic without contamination from old runs.
        """
        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return
        
        # Remove all CRs with "_auto" in their ID
        cleaned_crs = [
            cr for cr in crs
            if not (isinstance(cr, dict) and isinstance(cr.get("id"), str) and "_auto" in cr.get("id"))
        ]
        
        removed_count = len(crs) - len(cleaned_crs)
        if removed_count > 0:
            payload["connection_requirements"] = cleaned_crs

    def _strip_location_intent(payload: Dict[str, Any]) -> None:
        """Remove location_intent from Agent1 output (placement intent is inferred by Agent2)."""
        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return
        for cr in crs:
            if isinstance(cr, dict) and "location_intent" in cr:
                cr.pop("location_intent", None)



    def _enrich_connection_semantics_with_llm(payload: Dict[str, Any]) -> None:
        components = payload.get("components", [])
        crs = payload.get("connection_requirements", [])
        if not isinstance(components, list) or not isinstance(crs, list):
            return

        components_by_id = {
            comp.get("id"): comp
            for comp in components
            if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
        }
        unresolved: list[dict[str, Any]] = []
        valid_ids_by_connection: dict[str, set[str]] = {}
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            purpose = cr.get("purpose") if isinstance(cr.get("purpose"), str) else None
            decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
            if not (_purpose_requires_explicit_connection_semantics(purpose) or isinstance(decision, Mapping)):
                continue
            between = cr.get("between")
            between_ids = [cid for cid in between if isinstance(cid, str) and cid] if isinstance(between, list) else []
            if _sanitize_connection_semantics_contract(
                cr.get("connection_semantics"),
                valid_component_ids=set(between_ids),
            ) is not None:
                continue
            cr_id = cr.get("id") if isinstance(cr.get("id"), str) else None
            if not cr_id:
                continue
            unresolved.append(
                {
                    "connection_id": cr_id,
                    "between": between_ids,
                    "purpose": purpose,
                    "roles": cr.get("roles"),
                    "constraint_intent": cr.get("constraint_intent"),
                    "dof": cr.get("dof"),
                    "mating_features": cr.get("mating_features"),
                    "connection_decision": decision,
                    "component_info": [
                        {
                            "id": cid,
                            "type": (components_by_id.get(cid) or {}).get("type"),
                            "shape_semantics": (components_by_id.get(cid) or {}).get("shape_semantics"),
                            "dimensions": (components_by_id.get(cid) or {}).get("dimensions"),
                        }
                        for cid in between_ids
                    ],
                }
            )
            valid_ids_by_connection[cr_id] = set(between_ids)
        if not unresolved:
            return

        audit: Dict[str, Any] = {
            "requested_connection_ids": [entry["connection_id"] for entry in unresolved],
            "batch_size": 6,
        }
        unresolved_by_id = {entry["connection_id"]: entry for entry in unresolved}

        def _extract_items(obj: Any) -> list[dict[str, Any]]:
            if isinstance(obj, Mapping):
                for key in ("connection_semantics", "items", "connections"):
                    value = obj.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, Mapping)]
                return []
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, Mapping)]
            return []

        def _request_json_object(prompt_text: str) -> Any:
            content_local = _request_llm(prompt_text)
            try:
                return json.loads(content_local)
            except json.JSONDecodeError:
                match = re.search(r"(\{.*\}|\[.*\])", content_local, flags=re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                raise

        canonical_anchor_guidance = (
            "Anchor objects MUST be JSON objects, never bare strings.\n"
            "Allowed reference_anchor kinds: component_center, distal_end, proximal_end, radial_mount_perimeter, axial_face_perimeter_max, axial_face_perimeter_min.\n"
            "Allowed moving_anchor kinds: component_center, distal_end, proximal_end, proximal_mount_face_min, proximal_mount_face_max.\n"
            "Examples:\n"
            "- Wheel rotating on axle: reference_anchor {\"kind\": \"component_center\"}, moving_anchor {\"kind\": \"component_center\"}, interface hints bore_axis / bore_axis, orientation_policy free.\n"
            "- Arm supporting an axle at its outer end: reference_anchor {\"kind\": \"distal_end\", \"axis\": \"x\"}, moving_anchor {\"kind\": \"component_center\"}, interface hints distal_mount_face / bore_axis.\n"
            "- Hub bolted to an arm root: reference_anchor {\"kind\": \"axial_face_perimeter_max\"}, moving_anchor {\"kind\": \"proximal_mount_face_min\", \"axis\": \"x\"}, interface hints axial_end_face_max / proximal_mount_face_min.\n"
            "- Tire fixed to rim: connection_mechanism bonded_tread or press_fit; anchors {\"kind\": \"component_center\"} on both sides; never a bolted hole through the tire.\n"
            "Mechanical grounding rules:\n"
            "- For hub-to-arm fastening, use the arm proximal mount, never the arm distal end or center.\n"
            "- For arm-to-axle support, use the arm distal end / distal mount face.\n"
            "- For wheel or hub rotation about an axle, use bore_axis interface hints with component_center anchors.\n"
            "- For tire-to-rim fixation, choose bonded_tread or press_fit, not bolted_mount.\n"
            "geometric_semantics guidance:\n"
            "- geometric_semantics MUST include contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when using an array.\n"
            "- Hub bolted to an arm root with one screw: geometric_semantics {\"contact_model\": \"opposed_planar_clamp\", \"reference_feature_strategy\": \"threaded_hole\", \"moving_feature_strategy\": \"clearance_hole\", \"pattern_policy\": \"single\", \"hardware_layout\": \"thread_in_hub_bolt_head_on_arm\", \"retention_strategy\": \"threaded_clamp\"}.\n"
            "- Arm supporting an axle: geometric_semantics {\"contact_model\": \"shaft_in_bore_support\", \"reference_feature_strategy\": \"plain_bore\", \"moving_feature_strategy\": \"plain_shaft\", \"pattern_policy\": \"none\", \"retention_strategy\": \"coaxial_support\"}.\n"
            "- Tire fixed to rim: geometric_semantics {\"contact_model\": \"bonded_wrap\", \"reference_feature_strategy\": \"retention_groove\", \"moving_feature_strategy\": \"bonding_zone\", \"pattern_policy\": \"none\", \"retention_strategy\": \"bonded_or_press_fit\"}.\n"
            "- Never infer hole count from fastener bundle quantity; pattern_policy and pattern_count must state it explicitly.\n"
        )

        canonicalized_ids: set[str] = set()

        def _canonicalize_candidate_with_llm(connection_id: str, raw_candidate: Mapping[str, Any]) -> Dict[str, Any] | None:
            entry = unresolved_by_id.get(connection_id)
            if not isinstance(entry, Mapping):
                return None
            prompt_text = (
                "You are Agent1's connection semantics canonicalization layer.\n"
                "The prior candidate captured some mechanical intent but failed the frozen schema.\n"
                "Preserve the intended mechanism and participating components whenever possible.\n"
                "Only repair invalid anchor formatting, invalid anchor kinds, generic interface placeholders, under-specified relation_type/geometric_semantics, or clearly wrong proximal/distal arm-side anchor selection.\n"
                "Do NOT invent coordinates. Do NOT modify unrelated fields.\n\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n\n"
                + "TARGET_CONNECTION_ID: " + json.dumps(connection_id, ensure_ascii=False) + "\n"
                + "ALLOWED_COMPONENT_IDS: " + json.dumps(sorted(valid_ids_by_connection[connection_id]), ensure_ascii=False) + "\n"
                + "ORIGINAL_CONNECTION: " + json.dumps(entry, ensure_ascii=False) + "\n"
                + "FAILED_CANDIDATE: " + json.dumps(raw_candidate, ensure_ascii=False)
            )
            try:
                repaired_obj = _request_json_object(prompt_text)
            except Exception:
                return None
            for repaired_item in _extract_items(repaired_obj):
                candidate_id = repaired_item.get("connection_id") if isinstance(repaired_item.get("connection_id"), str) else None
                if candidate_id != connection_id:
                    continue
                repaired_raw = repaired_item.get("connection_semantics") if isinstance(repaired_item.get("connection_semantics"), Mapping) else repaired_item
                semantics = _sanitize_connection_semantics_contract(
                    repaired_raw,
                    valid_component_ids=valid_ids_by_connection[connection_id],
                )
                if isinstance(semantics, dict):
                    canonicalized_ids.add(connection_id)
                    return semantics
            return None

        def _apply_items(items: list[dict[str, Any]], *, allow_repair: bool = True) -> dict[str, dict[str, Any]]:
            applied: dict[str, dict[str, Any]] = {}
            for item in items:
                connection_id = item.get("connection_id") if isinstance(item.get("connection_id"), str) else None
                if not connection_id or connection_id not in valid_ids_by_connection:
                    continue
                raw_semantics = item.get("connection_semantics") if isinstance(item.get("connection_semantics"), Mapping) else item
                semantics = _sanitize_connection_semantics_contract(
                    raw_semantics,
                    valid_component_ids=valid_ids_by_connection[connection_id],
                )
                if semantics is None and allow_repair and isinstance(raw_semantics, Mapping):
                    semantics = _canonicalize_candidate_with_llm(connection_id, raw_semantics)
                if isinstance(semantics, dict):
                    applied[connection_id] = semantics
            return applied

        semantics_by_id: dict[str, dict[str, Any]] = {}
        batch_size = 6
        for start in range(0, len(unresolved), batch_size):
            batch = unresolved[start:start + batch_size]
            batch_ids = [entry["connection_id"] for entry in batch]
            prompt_contract = (
                "You are Agent1's connection semantics completion layer.\n"
                "Complete frozen connection_semantics for each listed mechanically resolved connection_requirement.\n"
                "These semantics are authoritative for downstream execution. Do NOT invent coordinates. Do NOT modify any existing field outside connection_semantics.\n\n"
                "For EACH listed connection_id you MUST return: connection_mechanism, relation_type, reference_component_id, moving_component_id, reference_anchor, moving_anchor, reference_interface_hint, moving_interface_hint, orientation_policy, geometric_semantics, rationale.\n"
                "connection_mechanism MUST be one of: bolted_mount, radial_member_bolted_mount, axial_face_bolted_mount, axial_stack_locator, bonded_tread, bonded_mount, press_fit, shaft_bore_fit, companion_rotation_relation, welded_mount. generic_mount is forbidden.\n"
                "reference_interface_hint and moving_interface_hint MUST be concrete interface names such as axial_end_face_max, radial_outer_face, bore_axis, bottom_face, side_face_x_min, distal_mount_face.\n"
                "geometric_semantics MUST include contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when pattern_policy implies an array.\n"
                "For structural support or fixation that must avoid interference, geometric_semantics MUST also make support_topology, mount_side, clearance_policy, and requires_axial_offset explicit.\n"
                "relation_type MUST be a concrete geometric relation such as shaft_axis_to_bore, axial_face_single_bolt_mount, radial_member_distal_support; generic values like fastening/fixation/support/rotation are forbidden.\n"
                "Forbidden interface hints: fixation_req, mounting_req, mounting_req_drill_anchor, support_req, generic_interface, unspecified.\n"
                "For hub-to-arm structural fixation on a rotating carrier, single_station_bolted_mount is forbidden unless the contract explicitly describes anti-rotation geometry. Prefer an axial face perimeter mount with a planar root pad when the arm roots mount to a hub face.\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n"
                "Do not omit any connection_id from the batch.\n\n"
                + "BATCH_CONNECTION_IDS: " + json.dumps(batch_ids, ensure_ascii=False) + "\n"
                + "UNRESOLVED_CONNECTIONS: " + json.dumps(batch, ensure_ascii=False)
            )

            obj = _request_json_object(prompt_contract)
            semantics_by_id.update(_apply_items(_extract_items(obj)))

            missing_batch = [cid for cid in batch_ids if cid not in semantics_by_id]
            if missing_batch:
                repair_prompt = (
                    prompt_contract
                    + "\n\nCORRECTION REQUIRED:\n"
                    + "You omitted or malformed these connection_ids: "
                    + json.dumps(missing_batch, ensure_ascii=False)
                    + "\nReturn corrected JSON only."
                )
                repair_obj = _request_json_object(repair_prompt)
                semantics_by_id.update(_apply_items(_extract_items(repair_obj)))

        still_missing = [entry for entry in unresolved if entry["connection_id"] not in semantics_by_id]
        audit["missing_after_batch"] = [entry["connection_id"] for entry in still_missing]
        for entry in still_missing:
            single_prompt = (
                "You are Agent1's connection semantics completion layer.\n"
                "Return frozen connection_semantics for exactly one mechanically resolved connection_requirement.\n"
                "These semantics are authoritative for downstream execution. Do NOT invent coordinates. Do NOT modify fields outside connection_semantics.\n\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n"
                "generic_mount is forbidden. Generic interface hints are forbidden.\n\n"
                + "TARGET_CONNECTION_ID: " + json.dumps(entry["connection_id"], ensure_ascii=False) + "\n"
                + "UNRESOLVED_CONNECTION: " + json.dumps(entry, ensure_ascii=False)
            )

            try:
                single_obj = _request_json_object(single_prompt)
            except Exception:
                continue
            semantics_by_id.update(_apply_items(_extract_items(single_obj)))

        for cr in crs:
            if not isinstance(cr, dict):
                continue
            cr_id = cr.get("id")
            if isinstance(cr_id, str) and cr_id in semantics_by_id:
                cr["connection_semantics"] = semantics_by_id[cr_id]
        audit["resolved_connection_ids"] = sorted(semantics_by_id)
        audit["canonicalized_connection_ids"] = sorted(canonicalized_ids)
        audit["missing_after_single"] = sorted(
            entry["connection_id"] for entry in unresolved if entry["connection_id"] not in semantics_by_id
        )
        payload["agent1_connection_semantics_audit"] = audit


    def _ensure_no_isolated_structural_components(payload: Dict[str, Any]) -> None:
        """Ensure no structural components appear in zero connection_requirements."""
        components = payload.get("components", [])
        if not isinstance(components, list):
            return

        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return

        type_map = _type_by_id(payload)
        
        # Find all structural components
        structural_ids = [
            cid for cid, ctype in type_map.items()
            if _is_structural_type(ctype)
        ]
        if not structural_ids:
            return
        
        # Find structural components that appear in zero CRs
        cid_in_cr: set[str] = set()
        for cr in crs:
            if isinstance(cr, Mapping):
                between = cr.get("between", [])
                if isinstance(between, list):
                    cid_in_cr.update(cid for cid in between if isinstance(cid, str))
        
        isolated = [cid for cid in structural_ids if cid not in cid_in_cr]
        if not isolated:
            return
        
        # For each isolated structural component, find a host and add connection
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
        
        for comp_id in isolated:
            # Find best host among OTHER structural components
            host_candidates = [cid for cid in structural_ids if cid != comp_id]
            if not host_candidates:
                continue
            
            host = _choose_structural_host(payload, comp_id, host_candidates)
            if not host:
                # Fallback: pick the first other structural component (deterministic)
                host = sorted(host_candidates)[0]
            
            crs.append({
                "id": _next_id(f"{comp_id}_isolated_fixation_auto"),
                "between": [comp_id, host],
                "purpose": "structural_fixation",
                "description": "Deterministic isolated structural component fixation",
            })


    # Read LLM client settings from the environment.
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    if not api_key:
        raise ValueError(
            "LLM not configured. Set OPENAI_API_KEY environment variable to enable "
            "natural language requirement understanding. "
            "Alternatively, provide requirements in structured knowledge graph format."
        )
    
    # Import OpenAI lazily so the module remains importable without the package.
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    # Trim the schema payload before sending it to the LLM.
    component_def = _strip_for_agent1(schema.get("$defs", {}).get("component", {}))
    if isinstance(component_def, dict):
        props = component_def.get("properties")
        if isinstance(props, dict):
            props = {
                "id": props.get("id"),
                "type": props.get("type"),
                "role": props.get("role"),
                "parameters": props.get("parameters"),
                "dimensions": props.get("dimensions"),
                "dimension_sources": props.get("dimension_sources"),
                "shape_semantics": props.get("shape_semantics"),
            }
            component_def["properties"] = {k: v for k, v in props.items() if v is not None}

    schema_excerpt = {
        "components": component_def,
        "subassemblies": _strip_for_agent1(schema.get("$defs", {}).get("subassembly", {})),
        "connection_requirements": _strip_for_agent1(schema.get("$defs", {}).get("connection_requirement", {})),
        "standard_parts": _strip_for_agent1(schema.get("$defs", {}).get("standard_part", {})),
        "patterns": _strip_for_agent1(schema.get("$defs", {}).get("pattern", {})),
        "design_intents": _strip_for_agent1(schema.get("$defs", {}).get("design_intent", {})),
        "units": schema.get("properties", {}).get("units", {}),
    }
    schema_excerpt_json = json.dumps(schema_excerpt, indent=2, ensure_ascii=False)
    
    prompt = """You are an engineering requirement interpretation agent for a mechanical CAD synthesis system.

Your task is NOT to generate geometry, coordinates, CAD steps, or layouts.

Your only responsibility is to fully understand the design intent expressed in the requirement file and convert it into a complete, non-simplified, structural knowledge graph suitable for downstream reasoning and planning.

User Requirements (in Chinese):
```yaml
""" + requirement_text + """
```

TASK DEFINITION (Agent 1's Single Responsibility):

Given a YAML requirement file describing a mechanical product or mechanism:

Produce a knowledge_graph.json that represents:
1. All required components (including components not explicitly mentioned but logically necessary)
2. Component properties, shape semantics, and immutable dimensions (sizes, roles, categories)
3. Inter-component relationships and constraints

闁?CRITICAL CONSTRAINTS:
   - Do NOT define any absolute or relative spatial coordinates
   - Do NOT simplify the design by omitting structurally necessary parts
   - Do NOT generate CAD operations, sketches, or manufacturing steps
   - Do NOT make geometry decisions that belong to downstream planning agents

Your job is INTERPRETATION and STRUCTURE, not CAD geometry or manufacturing.

NEW REQUIREMENT:
You MUST output abstract shape semantics and complete, immutable dimensions for every component.
- shape_semantics: type + cross_section + optional axis/notes (semantic only, no coordinates)
- dimensions: all required sizes (must be numeric, inferred using typical proportions when not explicit)
- dimension_sources: source + confidence for each dimension (input/standard_catalog/inferred_default/derived)
- parameters MUST mirror dimensions exactly (legacy compatibility)

RELATIONS RULE:
- Do NOT output relations[] in Agent1.
- Only output connection_requirements (facts + intent).

CONNECTION DECISION REQUIREMENT:
- If a connection involves clamping/fastening OR a fastener component exists, you MUST output connection_decision
- For bolted connections, connection_decision.method + count + fastener_size are REQUIRED
- Output standard_parts[] with catalog designations (e.g., ISO 4762 M4x12, 608ZZ)
- standard_parts MUST be real catalog items (choose closest standard size if needed)
- DO NOT output location_intent; that will be inferred by Agent2 based on Agent1's connection topology

FROZEN CONNECTION SEMANTICS CONTRACT (NEW, REQUIRED FOR MECHANICALLY RESOLVED CONNECTIONS):
- For every connection_requirement whose purpose is rotation / rotation_support / torque_transfer / structural_fixation / structural_clamping / fastening_mechanism / load_support / support_to_structure / spacing, you MUST output connection_semantics
- connection_semantics MUST include: connection_mechanism, relation_type, reference_component_id, moving_component_id, reference_anchor, moving_anchor, reference_interface_hint, moving_interface_hint, orientation_policy, geometric_semantics
- geometric_semantics MUST include: contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when pattern_policy implies an array
- relation_type MUST be geometrically specific; generic values like fastening / fixation / support / rotation are forbidden
- pattern_policy and pattern_count, not fastener bundle quantity, decide whether the mount is single or an array
- reference_anchor and moving_anchor MUST be JSON objects, never bare strings
- Allowed anchor kinds are: component_center, distal_end, proximal_end, radial_mount_perimeter, axial_face_perimeter_max, axial_face_perimeter_min, proximal_mount_face_min, proximal_mount_face_max
- Use concrete interface hints such as bore_axis, axial_end_face_max, distal_mount_face, radial_outer_face; placeholders like fixation_req / mounting_req / unspecified are forbidden
- If an arm connects to a hub, the arm-side anchor is its proximal mount; if an arm supports an axle, the arm-side anchor is its distal end
- If a tire attaches to a rim, use bonded_tread or press_fit semantics; do NOT model that as a bolted hole pattern through the tire
- These are abstract semantic anchors and interface hints, NOT coordinates
- Downstream agents are allowed to execute or reject this contract, but NOT reinterpret it into a different mechanism
- generic_mount is NOT acceptable when a concrete mechanical realization is inferable from the requirement

STANDARD PARTS FORMAT:
- standard_parts[] entries MUST include: category, designation, quantity, applied_to, selection_rationale
- applied_to should reference connection_requirement ids or subassembly ids

CONNECTION PURPOSE & ROLES REQUIREMENT:
- Every connection_requirement MUST include a normalized purpose (e.g., rotation, torque_transfer, structural_fixation, fastening_mechanism)
- Every connection_requirement MUST include roles (array of semantic roles), derived from purpose if not explicitly stated
- connection_requirements MAY include constraints (must_rotate / must_be_rigid / must_support_load / must_limit_axial)
- Roles examples: mounting, rotation, support, fixation, torque_transfer

---

STRICT PROHIBITIONS (DO NOT VIOLATE THESE):

闁?Assign absolute positions, translations, rotations, or coordinates
   - No (x, y, z) coordinates for component placement
   - No angles used for positioning components
   - No layout or spatial decisions of any kind

闁?Generate CAD-oriented abstractions
   - No "sketches" as design elements
   - No "extrusions" or "revolutions"
   - Avoid CAD jargon; use engineering language instead

闁?Reduce the design to "minimal rigid bodies"
   - Do NOT assume wheels, arms, hubs are monolithic solids
   - Do NOT collapse assemblies into single parts
   - Include all structurally and functionally necessary parts

闁?Decide how parts are manufactured or modeled in CAD
   - That decision belongs to downstream agents (plan_geometry_semantic, compile_semantics_to_cad)
   - Your job is STRUCTURE, not MANUFACTURING

---

闁?REQUIRED BEHAVIOR (YOU MUST DO THESE):

1闁挎柨绻嗛崕?Complete Semantic Understanding (no task simplification)

You MUST assume that:
   - The design intent is engineering-realistic, not conceptual
   - If a function or connection cannot exist physically without a component, that component MUST be included
   
Examples:
   - A rotating wheel 闁?implies axle/bearing/spacer
   - A rigid plate-to-plate connection 闁?implies fasteners (bolts, washers, nuts)
   - Load-bearing rotating hub 闁?implies bearing seats or bearing cartridges
   - Repeated symmetric structures 闁?imply patterned subassemblies, NOT copied coordinates

2闁挎柨绻嗛崕?Component Set = Explicit + Inferred (Semantic Closure)

Your output MUST include:

a) Explicitly mentioned components (hub, wheel arm, wheel, carrier plates)

b) Inferred but necessary components:
   - Axles / shafts (if components rotate about an axis)
   - Module input/drive shafts (if the ENTIRE MODULE rotates or receives rotational input)
   - Bearings (if there is rotational motion or load transfer)
   - Spacers / bushings / washers (for spacing and alignment)
   - Fasteners (bolts, nuts, washers, pins, rivets)
   - Structural interfaces (flanges, bearing seats, mounting pads)
   - Alignment components (dowel pins, keys, splines)

妫ｅ啯鏆?**MODULE-LEVEL MOTION INFERENCE (CRITICAL):**

If the requirement describes MODULE-LEVEL rotational motion (e.g., "the entire module rotates"),
you MUST infer a module input shaft or drive axis component.

Examples:
- **"The tri-star wheel module can rotate as a whole"** 
  闁?MUST add: a module input shaft component (e.g., "module_drive_shaft", "central_rotation_input")
  闁?This shaft connects to the central_hub and provides rotational input to the entire assembly
  闁?Connection_requirement: {"between": ["module_drive_shaft", "central_hub"], "purpose": "torque_transfer"}

- **"The assembly spins around its center axis"** 
  闁?MUST add: a central_input_axis component
  闁?This axis passes through the hub and enables module-level rotation

- **Wheels rotate individually BUT the module rotates as a whole**
  闁?Do NOT confuse individual wheel rotation with module rotation
  闁?Both require separate components: wheel_axles (for wheel rotation) AND module_drive_shaft (for module rotation)
  闁?These are two different input mechanisms

妫ｅ啯鏆?**CRITICAL: Without a MODULE INPUT component, module-level rotation is MECHANICALLY IMPOSSIBLE.**

If a requirement says "the module rotates", you MUST create a corresponding component in the KG.
This is NOT optional. It is a structural requirement.

Do NOT confuse module-level rotation with individual wheel rotation.

Each inferred component must have:
   - id: unique identifier
   - type: category (shaft, bearing, fastener, spacer, plate, arm, etc.)
   - role: functional role (load-bearing, rotating_interface, fixation, spacing, alignment)
  - shape_semantics: abstract shape description (type + cross_section, no coordinates)
  - dimensions: complete numeric dimensions (immutable)
  - dimension_sources: per-dimension provenance (explicit or derived)
  - parent_id: which parent component it belongs to (optional)

妫ｅ啯鏆?**COMPLEX COMPONENT DECOMPOSITION (REQUIRED):**

If a component is mechanically composite, you MUST decompose it into subcomponents.
Examples:
- Wheel 闁?tire + hub + fasteners (and possibly bearing seat)
- Track module 闁?rollers + frame + fasteners
- Motorized module 闁?motor + coupling + shaft + fasteners

Use subassemblies to group such composite parts and ensure their internal connections exist.

闁宠法濯寸粭?CONNECTION SEMANTIC CLOSURE (CRITICAL):

When interpreting the requirement file, you MUST assume that any fixed or clamped relationship 
between structural components requires explicit connecting components.

Specifically:
- Any "fixed_to" relationship between load-bearing or structural parts implies the existence 
  of fasteners and/or spacers.
- Fasteners (e.g. bolts, screws, nuts, washers, pins) MUST be explicitly represented as 
  components when they are structurally necessary to realize a constraint.
- Do NOT omit fasteners simply to simplify the model.
- If the requirement describes a mechanically realistic product, assume realistic fastening 
  unless explicitly stated otherwise.

Each inferred fastener component must include:
- type: fastener
- role: fixation / clamping / load_transfer
- parameters: approximate numeric parameter placeholders (e.g. nominal_diameter, count, length) if inferable
  NOTE: All parameter values must be numbers, not strings. Do NOT use string values like "bolt_with_nut".

Example:
```json
{
  "id": "hub_to_arm_fastener_set",
  "type": "fastener",
  "role": "fixation",
  "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
  "dimensions": {
    "nominal_diameter": 3,
    "count": 3,
    "length": 8
  },
  "dimension_sources": {
    "nominal_diameter": {"source": "explicit"},
    "count": {"source": "explicit"},
    "length": {"source": "explicit"}
  },
  "parameters": {
    "nominal_diameter": 3,
    "count": 3,
    "length": 8
  }
}
```

3闁挎柨绻嗛崕?Connection Requirements Instead of Relations (CRITICAL NEW BEHAVIOR)

妫ｅ啯鏆?CRITICAL PROHIBITION:

You are NOT allowed to emit a legacy `relations[]` section with unconstrained CAD-style
labels like `fixed_to`, `rotates_about`, or `supported_by`.

Agent1 MUST still define the mechanical contract in `connection_semantics`
when the requirement is mechanically specific enough to determine it.

Your job is:
- `connection_requirements`: specify WHAT must be connected and WHY
- `connection_semantics`: specify the authoritative abstract mechanical mechanism and anchors

Downstream agents may execute or reject that contract, but they MUST NOT reinterpret it.

闁?YOU MUST NOT generate the `relations` section at all.

Instead, generate ONLY:
- components
- subassemblies
- patterns
- design_intents
- connection_requirements (NEW)

The `connection_requirements` section must describe REQUIRED mechanical connections
in an abstract, non-binding way, without specifying or choosing exact relation types.

Each connection_requirement:
   - id: unique identifier
   - between: array of 2 or more component IDs that must be mechanically connected
   - purpose: semantic description of WHY they must connect (e.g., "load_transfer", "rotation", "fixation", "support", "spacing", "alignment")

HARD RULE:
In a connection_requirement, the "between" array MUST contain only
the minimal set of components that are semantically indispensable
to express the requirement's purpose.

Do NOT include implementation carriers (plates, fasteners, bearings)
unless they are the semantic subject of the requirement.

妫ｅ啯鏆?ROLE SEPARATION RULE (CRITICAL):

NEVER bundle more than one mechanical role into a single connection_requirement.
If multiple roles are implied, you MUST split them into separate requirements.

For any rotating module, enforce the following decomposition:
- Rotation intent ONLY between the rotating part and its immediate interface
- Load support must be expressed as a SEPARATE requirement
- Structural fixation must be expressed as a SEPARATE requirement

Example (CORRECT - decomposed):
```json
{ "id": "wheel_1_rotation", "between": ["wheel_1", "axle_1"], "purpose": "rotation" }
{ "id": "wheel_1_support", "between": ["wheel_1", "bearing_1"], "purpose": "load_support" }
{ "id": "bearing_1_to_arm", "between": ["bearing_1", "arm_1"], "purpose": "support_to_structure" }
{ "id": "axle_1_to_arm", "between": ["axle_1", "arm_1"], "purpose": "structural_fixation" }
```

Example (FORBIDDEN - bundled roles):
```json
{ "id": "wheel_1_bundle", "between": ["wheel_1", "axle_1", "bearing_1"], "purpose": "rotation" }
```

Connection requirements are ABSTRACT and do NOT specify:
  闁?Which relation type (fixed_to, rotates_about, etc.) 闁?that decision belongs to downstream agents
  闁?Direction or order of connection
  闁?Any geometric coordinates or layout
  闁?CAD implementation steps

If the connection involves fastening/clamping (or fasteners are present):
  闁?connection_decision MUST be specified (method/size/count)
  闁斥晝娅㈢粭?location_intent (pattern/symmetry/arrangement) will be inferred by Agent2, not Agent1

Example (CORRECT - abstract, no type):
```json
{
  "id": "hub_to_arms_rigid_connection",
  "between": ["central_hub", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
  "purpose": "rigid fixation and load distribution from hub to all arms"
}
```

Example (WRONG - specifies type):
```json
{
  "id": "hub_to_arm_1",
  "between": ["central_hub", "wheel_arm_1"],
  "type": "fixed_to",  闁?DO NOT specify type!
  "purpose": "fixation"
}
```

Example (WRONG - includes coordinates):
```json
{
  "id": "wheel_to_arm",
  "between": ["wheel_1", "wheel_arm_1"],
  "location": {"x": 10, "y": 0},  闁?DO NOT specify coordinates!
  "purpose": "attachment"
}
```

Example (CORRECT - fastening decision provided by Agent1):
```json
{
  "id": "wheel_to_arm",
  "between": ["wheel_1", "wheel_arm_1", "wheel_fastener_set"],
  "purpose": "structural_clamping",
  "connection_decision": {
    "method": "bolted_rigid",
    "fastener_ref_component_id": "wheel_fastener_set",
    "fastener_size": "M5",
    "count": 4,
    "stackup": "through_nut",
    "fit_policy": "clearance",
    "lock": true,
    "rationale": "Clamp wheel to arm with bolted joint"
  }
}
```
NOTE: location_intent (pattern/symmetry/arrangement) will be inferred by Agent2, not Agent1.


WHY THIS CHANGE?

Connection requirements specify MECHANICAL FACTS (what must connect) and PURPOSE (why).
They do NOT specify relation types or geometry.

Downstream agents (Agent 2/4) will:
- Analyze the abstract requirements
- Decide the specific relation types
- Ensure mechanical completeness and correctness

This separation of concerns allows:
闁?Cleaner semantics
闁?Better error recovery
闁?More flexible downstream processing
闁?Explicit decision tracking

Or define a structural subassembly:
```json
{
  "subassemblies": [
    {
      "id": "carrier_plate_assembly",
      "description": "Carrier plates sandwich and clamp the three wheel arms",
      "component_ids": ["carrier_plate_top", "carrier_plate_bottom", "plate_fastener_set"],
      "role": "structural_clamping"
    }
    ]
}
```

4闁挎柨绻嗛崕?Symmetry Must be Explicit, Not Embedded in Coordinates

If a structure is repeated (e.g., 3 wheel arms):
   - Represent ONE canonical subassembly definition
   - Declare a symmetry or repetition rule EXPLICITLY
   - Do NOT instantiate placement via angles or vectors

Example (CORRECT):
```json
{
  "pattern": {
    "type": "rotational_symmetry",
    "count": 3,
    "axis": "central_hub_axis",
    "applies_to": "wheel_arm_assembly",
    "canonical_instance": "arm_assembly_1"
  }
}
```

NOT:
```json
{
  "arm_1": {"origin": [44, 0, 0], ...},
  "arm_2": {"origin": [-22, 38.1, 0], ...},
  "arm_3": {"origin": [-22, -38.1, 0], ...}
}
```

5闁挎柨绻嗛崕?Knowledge Graph = Conceptual Assembly Graph

Think of the output as:
    闁?A diagram of ellipses (components) connected by labeled lines (connection_requirements)
   闁?NOT a layout, drawing, or geometry plan

6闁挎柨绻嗛崕?Design Intents Must Be Explicit

Declare high-level design constraints and behaviors:
   - "wheels are not independently rotating relative to arms"
   - "module rotates as a whole about the central hub axis"
   - "wheel clearance must prevent self-interference with arm structure"
   - "carrier plates sandwich arm assemblies for structural rigidity"
   - "hub transfers rotational load to wheel arms via rigid attachment"

These are CONSTRAINTS and BEHAVIORS, not geometry decisions.

---

妫ｅ喚娼?MENTAL MODEL YOU MUST FOLLOW:

"I am thinking like a mechanical engineer reading a specification sheet,
not like a CAD operator, not like a geometry planner."

Decision Tree:
   - Want to assign a coordinate? 闁?STOP. Convert to a relationship instead.
   - Want to decide on CAD primitives? 闁?STOP. That's for later agents.
   - Want to omit a component to simplify? 闁?STOP. Include all structurally necessary parts.
   - Want to skip over an inferred part? 闁?STOP. If it's necessary for function, include it.

---

Knowledge Graph Format Requirements:

OUTPUT STRUCTURE (top-level keys):

{
  "components": [...],                    # All individual components (explicit + inferred)
  "subassemblies": [...],                 # Named groupings of related components
  "connection_requirements": [...],       # Abstract required connections (NOT relations!)
  "patterns": [...],                      # Symmetries, repetitions, regularities
  "design_intents": [...],                # High-level constraints and behaviors
  "units": {"length": "mm", "angle": "deg"}
}

CRITICAL REMINDER:
闁?DO NOT include "relations" in the output
闁?DO include "connection_requirements" instead

DETAILED FORMAT:

1. `components` array - MUST include BOTH explicit and inferred parts

Each component:
   - id: unique identifier (lowercase + underscore, e.g. "hub", "wheel_1", "wheel_axle_1")
   - type: category (any reasonable mechanical component type string - NO RESTRICTIONS)
     * Examples: hub, arm, wheel, shaft, bearing, fastener, plate, spacer, bushing, gear, spring, motor, etc.
     * The list above is EXAMPLES ONLY - you may use ANY appropriate component type
     * DO NOT limit yourself to a predefined list
     * Use engineering-appropriate vocabulary for the specific component
   - role: functional role (load_bearing, rotating_interface, fixation, spacing, alignment, structural)
   - shape_semantics: abstract shape description
     * type: cylindrical / prismatic / plate / complex (semantic, NOT CAD)
     * cross_section: circular / annular / rectangular / custom (semantic)
     * axis: optional semantic axis label (no coordinates)
   - dimensions: COMPLETE, immutable numeric dimensions for this component
     * Must include all required sizes, even if inferred from engineering assumptions
     * Use meaningful names: "radius", "thickness", "length", "width", "count"
   - dimension_sources: map of each dimension to "explicit" or "derived"
   - parameters: MUST mirror dimensions exactly (legacy compatibility)
   - parent_id: optional parent component id for product structure nesting
   - interfaces: optional array of semantic interfaces (NOT geometry)

妫ｅ啯鏆?**COMPONENT TYPE FLEXIBILITY (CRITICAL):**

The "type" field accepts ANY reasonable mechanical component category.
There is NO hardcoded list of allowed types.
You MUST use engineering-appropriate vocabulary for the specific component you're describing.

Examples of VALID types (non-exhaustive):
- Standard: hub, arm, wheel, shaft, axle, bearing, fastener, plate, spacer, bushing
- Transmission: gear, pulley, belt, chain, sprocket, coupling
- Actuation: motor, actuator, cylinder, piston
- Structure: frame, bracket, mount, housing, enclosure
- Specialized: spring, damper, joint, hinge, connector, adapter
- Domain-specific: rotor, stator, blade, vane, impeller, propeller, antenna

The validation will check structural completeness (e.g., if type="bearing", it must have load_support connection),
but it will NOT reject unknown types. Feel free to invent appropriate type names for novel components.

Example component:
```json
{
  "id": "wheel_axle_1",
  "type": "shaft",
  "role": "rotating_interface",
  "parameters": {"diameter": 10, "length": 25}
}
```

2. `subassemblies` array (optional but recommended)

妫ｅ啯鏆?**MANDATORY SUBASSEMBLY REQUIREMENT:**

If multiple components are conceptually bound together by plates, frames, or fasteners,
you MUST introduce a subassembly or clamping group.

Subassemblies represent mechanical binding units.
If a subassembly is defined, it MUST participate in at least one connection_requirement as a semantic hub.

If a subassembly exists, at least one connection_requirement MUST include the subassembly ID itself in the between array.

For any subassembly with more than one component, you MUST include the subassembly ID in at least one connection_requirement.

If a subassembly appears in "between", it MUST replace its internal components.
Do NOT list both a subassembly and its member components in the same connection_requirement.
Do NOT connect a subassembly to components it does not physically bind or act upon.

妫ｅ啯鏆?**SUBASSEMBLY SEMANTIC SCOPE (CRITICAL):**

A subassembly may ONLY appear in connection_requirements where it acts as a BINDING MECHANISM.

FORBIDDEN: Connecting a subassembly to external components that are NOT bound by it.

Example (WRONG):
- wheel_assembly_1 (contains wheel, axle, bearing) connected to central_hub
- Problem: wheel_assembly does NOT bind the hub; its members (axle, bearing) connect to arm/structure

Example (CORRECT):
- wheel_axle_1 闁?wheel_arm_1 (structural_fixation)
- bearing_1 闁?wheel_arm_1 (support_to_structure)
- Do NOT create wheel_assembly_1 闁?central_hub connection

Rule: If a subassembly's members already have explicit connections to external components,
the subassembly itself MUST NOT redundantly connect to those same external components.

FAILURE CONDITION:
If a subassembly is defined but its ID never appears in any connection_requirement,
the output will be rejected.

REQUIRED FIX EXAMPLE:
If you define "carrier_plate_assembly", you MUST include a requirement such as:
{"id": "carrier_clamps_arms", "between": ["carrier_plate_assembly", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"], "purpose": "structural_clamping"}

You MUST NOT express such bindings as multiple pairwise connections.

Example (WRONG - no subassembly, just pairwise connections):
```json
{
  "components": [
    {"id": "arm_1", "type": "arm", ...},
    {"id": "arm_2", "type": "arm", ...},
    {"id": "arm_3", "type": "arm", ...},
    {"id": "plate_top", "type": "plate", ...},
    {"id": "plate_bottom", "type": "plate", ...},
    {"id": "fastener_set", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "plate_top_to_arm_1", "between": ["plate_top", "arm_1"], "purpose": "clamping"},
    {"id": "plate_top_to_arm_2", "between": ["plate_top", "arm_2"], "purpose": "clamping"},
    {"id": "plate_top_to_arm_3", "between": ["plate_top", "arm_3"], "purpose": "clamping"}
  ]
}
```
闁?WRONG - three pairwise connections, no semantic grouping

Example (CORRECT - with subassembly):
```json
{
  "components": [...same...],
  "subassemblies": [
    {
      "id": "carrier_plate_assembly",
      "description": "Carrier plates and fasteners that sandwich and clamp the three wheel arms",
      "component_ids": ["plate_top", "plate_bottom", "fastener_set"],
      "role": "structural_clamping"
    }
  ],
  "connection_requirements": [
    {"id": "carrier_clamps_all_arms", "between": ["plate_top", "plate_bottom", "arm_1", "arm_2", "arm_3", "fastener_set"], "purpose": "structural_clamping"},
    ...
  ]
}
```
闁?CORRECT - semantic grouping via subassembly, combined connection requirement

妫ｅ啯鏆?SUBASSEMBLY AS CONNECTION HUB (CRITICAL):

Whenever a subassembly represents a clamping or binding mechanism
(e.g., plates + fasteners + multiple structural members), the subassembly itself
MUST be treated as a semantic connection hub.

Rule:
- DO NOT generate pairwise connection_requirements between subassembly members
- INSTEAD, generate a SINGLE connection_requirement where the subassembly
  semantically binds all involved components

Example (CORRECT - hub connection):
```json
{
  "id": "carrier_clamps_arms",
  "between": ["carrier_plate_assembly", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
  "purpose": "structural_clamping"
}
```

Example (FORBIDDEN - pairwise expansion):
```json
{ "id": "plate_top_arm_1", "between": ["plate_top", "arm_1"], "purpose": "clamping" }
{ "id": "plate_bottom_arm_1", "between": ["plate_bottom", "arm_1"], "purpose": "clamping" }
{ "id": "plate_top_arm_2", "between": ["plate_top", "arm_2"], "purpose": "clamping" }
```

Group related components semantically:
   - id: subassembly identifier (e.g. "wheel_assembly_1", "drive_interface", "carrier_plate_assembly")
   - description: human-readable description
   - component_ids: list of component IDs in this subassembly
   - role: functional role of the subassembly (optional)

妫ｅ啯鏆?**CLAMPING SUBASSEMBLY MUST INCLUDE FASTENERS (CRITICAL):**

If a subassembly has a role of "structural_clamping", "fixation", or "binding",
its component_ids MUST include the fastener component(s) that realize the clamping.

Example (WRONG - plates without fasteners):
```json
{
  "id": "carrier_plate_assembly",
  "component_ids": ["plate_top", "plate_bottom"],  // 闁?Missing fasteners!
  "role": "structural_clamping"
}
```

Example (CORRECT - plates WITH fasteners):
```json
{
  "id": "carrier_plate_assembly",
  "component_ids": ["plate_top", "plate_bottom", "plate_fastener_set"],  // 闁?Includes fasteners
  "role": "structural_clamping"
}
```

Without fasteners, plates CANNOT clamp - they are just loose parts.

Example subassembly:
```json
{
  "id": "wheel_assembly_1",
  "description": "Wheel with support axle and bearings",
  "component_ids": ["wheel_1", "wheel_axle_1", "bearing_1"],
  "role": "rotational_module"
}
```

闁宠法濯寸粭?SUBASSEMBLY FUNCTIONAL COMPLETENESS (CRITICAL):

When defining a subassembly:

- Ensure that all functional interfaces of that subassembly are explicitly described in connection_requirements.
- A subassembly must clearly indicate what connections it requires via abstract connection_requirements.
- Do NOT define subassemblies that are mechanically floating or incompletely constrained.

For rotating modules:
- Wheels and axles must have a connection_requirement between them for rotation.
- Bearings must have BOTH:
  - load_support connection to the rotating part
  - support_to_structure connection to a structural component (arm, housing, plate)
- Shafts/axles must have BOTH:
  - rotation (or torque_transfer) connection to the rotating part
  - structural_fixation connection to a supporting structure

Example (INCORRECT - floating subassembly):
```json
{
  "subassemblies": [
    {
      "id": "wheel_assembly_1",
      "component_ids": ["wheel_1", "axle_1", "bearing_1"]
    }
  ],
  "connection_requirements": [
    {"id": "wheel_to_axle", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
  ]
}
```
闁?Problem: axle_1 has no mount point, bearing_1 has no support requirement

Example (CORRECT - functionally complete):
```json
{
  "subassemblies": [
    {
      "id": "wheel_assembly_1",
      "component_ids": ["wheel_1", "axle_1", "bearing_1"]
    }
  ],
  "connection_requirements": [
    {"id": "wheel_to_axle", "between": ["wheel_1", "axle_1"], "purpose": "rotation"},
    {"id": "bearing_supports_wheel", "between": ["wheel_1", "bearing_1"], "purpose": "load_support"},
    {"id": "axle_to_structure", "between": ["axle_1", "arm_structure"], "purpose": "fixation"},
    {"id": "bearing_to_structure", "between": ["bearing_1", "arm_structure"], "purpose": "support"}
  ]
}
```
闁?All components have clear connection requirements

3. `connection_requirements` array - ABSTRACT required connections (NO types)

Each connection_requirement:
   - id: requirement identifier
   - between: array of 2+ component IDs that must be connected
   - purpose: semantic reason for connection (e.g., "rotation", "load_support", "fixation", "spacing", "alignment")
  - connection_decision: REQUIRED if fastening/clamping or fasteners are involved (method/size/count)
   - NOTE: location_intent is NOT generated by Agent1; Agent2 will infer placement patterns

Example connection_requirement:
```json
{
  "id": "wheel_1_rotation_requirement",
  "between": ["wheel_1", "wheel_axle_1"],
  "purpose": "rotation",
  "description": "Wheel rotates about its axle (coaxial)"
}
```

Example connection_requirement with connection_decision (fastening):
```json
{
  "id": "arm_to_hub_clamp",
  "between": ["wheel_arm_1", "central_hub", "arm_fastener_set"],
  "purpose": "structural_clamping",
  "connection_decision": {
    "method": "bolted_rigid",
    "fastener_ref_component_id": "arm_fastener_set",
    "fastener_size": "M4",
    "count": 6,
    "stackup": "through_nut",
    "fit_policy": "clearance",
    "lock": true,
    "rationale": "Clamp arm to hub with symmetric bolts"
  }
}
```

4. `patterns` array - MUST explicitly declare symmetries (do NOT embed in coordinates)

Each pattern:
   - id: pattern identifier
   - type: pattern type (rotational_symmetry, linear_repetition, radial_repetition, bilateral_symmetry)
   - count: number of instances
   - component_ids: list of components participating in the pattern
   - description: human-readable explanation

Example pattern:
```json
{
  "id": "bilateral_wheels",
  "type": "bilateral_symmetry",
  "count": 2,
  "component_ids": ["wheel_1", "wheel_2"],
  "description": "Two wheels are symmetrically positioned on opposite sides of the hub"
}
```

5. `design_intents` array - MUST explicitly state high-level constraints

Each design intent:
   - id: intent identifier
   - type: intent category (structural_arrangement, motion_constraint, load_path, structural_requirement, etc.)
   - description: semantic description of the design intent (plain English or Chinese)
   - component_ids: components involved in this intent (optional)
   - parameters: additional parameters if needed (optional)

Example design intents:
```json
[
  {
    "id": "bilateral_symmetry",
    "type": "structural_arrangement",
    "description": "Two wheels are symmetrically attached to opposite sides of the hub",
    "component_ids": ["wheel_1", "wheel_2", "hub"]
  },
  {
    "id": "independent_rotation",
    "type": "motion_constraint",
    "description": "Each wheel rotates independently about its own axle",
    "component_ids": ["wheel_1", "wheel_2", "axle_1", "axle_2"]
  }
]
```

妫ｅ啯鏁?ABSTRACT CONNECTIONS VS DOWNSTREAM RELATIONS:

You MUST understand the NEW architecture:

**connection_requirements** (abstract required connections):
- Specify WHAT must connect and WHY (abstract purpose only)
- Examples: "wheel and axle must connect for rotation", "bearing must support the wheel"
- Do NOT specify geometric coordinates or layout
- DO specify connection_decision (method/size/count) when fastening/clamping is involved

**downstream relations** (implemented by Agent2/4):
- Derived from connection_requirements and interface planning

**design_intents** (high-level constraints and preferences):
- Represent engineering objectives, design purposes, or behavioral requirements
- Examples: "module must rotate as whole", "wheels should not interfere with structure"
- These are goals or constraints that GUIDE design, not specific connections

**STRICT RULES FOR CONNECTION_REQUIREMENTS:**

0. If any fastener component is involved OR the purpose implies fastening/clamping, you MUST include:
  - connection_decision (method + size + count for bolted connections)
  - DO NOT include location_intent; that will be inferred by Agent2

1. Connection requirements are ABSTRACT - specify purpose, not mechanism:
   - 闁?CORRECT: {"id": "wheel_1_axle_connection", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
   - 闁?WRONG: {"id": "wheel_1_axle", "type": "rotates_about", "a": "wheel_1", "b": "axle_1"}  (type decision belongs to Agent 2)
   - 闁?WRONG: {"id": "wheel_1_axle", "between": ["wheel_1", "axle_1"], "type": "rotates_about"}  (NO type field!)

2. EVERY physically necessary connection must have a connection_requirement:
   - Include ALL fastener participation
   - Include ALL bearing support connections
   - Include ALL structural fixations
   - "between" array specifies what components must be connected

妫ｅ啯鏆?**CRITICAL: Every fastener MUST appear as a central element of a connection requirement.**

Fasteners are NEVER isolated components. Every fastener must participate in at least one
connection_requirement, and ideally should be central to the connection specification.

妫ｅ啯鏆?FASTENER AS SEMANTIC CARRIER (CRITICAL):

If a fastener is required for a connection, the connection_requirement purpose
MUST explicitly refer to a fastening or clamping mechanism, and the fastener
MUST be included in the "between" array as a central element (not incidental).

妫ｅ啯鏆?**PURPOSE MUST REFLECT IMPLEMENTATION (MANDATORY):**

When a connection_requirement includes a fastener in its "between" array,
the purpose MUST use ENGINEERING-SPECIFIC vocabulary that reflects the implementation.

**Purpose Vocabulary Hierarchy:**

Abstract (use ONLY when implementation is unknown):
- "structural_fixation" (generic, no implementation details known)
- "connection" (too vague, avoid)

Concrete Implementation-Specific (PREFERRED when components are known):
- "fastening_mechanism" (when fastener is present)
- "bolted_joint" (when bolt-type fastener is present)
- "structural_clamping" (when plates + fasteners clamp components together)
- "welded_joint" (when components are welded - no fastener)
- "press_fit" (when components are interference-fitted - no fastener)
- "adhesive_bond" (when components are glued - no fastener)

**MANDATORY RULE:**
- IF "between" array contains a fastener component 闁?purpose MUST be "fastening_mechanism" or more specific
- IF "between" array does NOT contain a fastener 闁?you MAY use "structural_fixation" BUT consider if welding/press_fit is implied

**Example (WRONG - fastener present but purpose too generic):**
```json
{
  "id": "hub_arm_connection",
  "between": ["hub", "arm", "fastener_set"],
  "purpose": "structural_fixation"  // 闁?Too generic! Fastener is present!
}
```

**Example (CORRECT - fastener present with specific purpose):**
```json
{
  "id": "hub_arm_connection",
  "between": ["hub", "arm", "fastener_set"],
  "purpose": "fastening_mechanism"  // 闁?Reflects implementation
}
```

**Example (ALSO CORRECT - no fastener, welding implied):**
```json
{
  "id": "frame_weld",
  "between": ["frame_member_1", "frame_member_2"],
  "purpose": "welded_joint"  // 闁?No fastener, specific implementation
}
```

MANDATORY FASTENER COVERAGE:
If you introduce a fastener component, you MUST create at least one
connection_requirement whose "between" includes that fastener, and whose
purpose explicitly refers to a fastening/clamping mechanism.

Example (WRONG - fastener present but invisible in connection_requirements):
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "arm", "type": "arm", ...},
    {"id": "fastener_set", "type": "fastener", ...}  // 闁?present but...
  ],
  "connection_requirements": [
    {"id": "hub_arm", "between": ["hub", "arm"], "purpose": "fixation"}  // ...not mentioned here!
  ]
}
```
闁?WRONG - fastener_set has no connection requirement

Example (CORRECT - fastener as central element):
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "arm", "type": "arm", ...},
    {"id": "fastener_set", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "hub_arm_fastened", "between": ["hub", "arm", "fastener_set"], "purpose": "fastening_mechanism"}  // 闁?fastener_set is central
  ]
}
```
闁?CORRECT - fastener_set appears in connection_requirement

3. Design intents should NOT restate connection requirements:
   - 闁?WRONG: connection_requirement "wheel rotates about axle" PLUS intent "wheel rotates independently"
   - 闁?CORRECT: Only include the connection_requirement; the intent might be "can be designed/maintained independently"

4. Design intents must NEVER contradict the connection requirements:
   - If contradiction detected, revise intent or connection_requirement
   - 闁?WRONG: Requirement "bearing supports wheel" contradicts intent "bearing is floating"
   - 闁?CORRECT: Fix the contradiction

Example (CORRECT SEPARATION - Abstract vs Concrete):

```json
{
  "connection_requirements": [
    {"id": "hub_arm_1_connection", "between": ["hub", "arm_1"], "purpose": "structural_fixation"},
    {"id": "hub_arm_2_connection", "between": ["hub", "arm_2"], "purpose": "structural_fixation"},
    {"id": "hub_arm_3_connection", "between": ["hub", "arm_3"], "purpose": "structural_fixation"},
    {"id": "wheel_axle_rotation", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
  ],
  "design_intents": [
    {
      "id": "tri_symmetry_load_distribution",
      "type": "structural_arrangement",
      "description": "Three-fold symmetry enables balanced load distribution and rotational motion"
    },
    {
      "id": "independent_wheel_design_freedom",
      "type": "motion_constraint",
      "description": "Each wheel can be designed and replaced independently"
    }
  ]
}
```

Note: Agent 1 (you) generates ONLY connection_requirements + standard_parts. Agent 2/4 will derive relations.

---

6. OLD FORMAT NOTES (still supported for backward compatibility):

   The following old fields are still recognized but OPTIONAL:
   - local_frame: local coordinate system (only if necessary for downstream agents)
   - interfaces: connection interfaces (optional)

CRITICAL REMINDERS:

妫ｅ啯鏆?RELATION TYPES ARE FORBIDDEN IN AGENT 1:
    Do NOT output relations or relation types here.

妫ｅ啯鏆?FASTENERS ARE STRUCTURAL NODES, NOT DECORATIONS:
   Every fastener MUST be a central element in a connection_requirement.
   Fasteners MUST NEVER appear as isolated components with zero connection_requirements.
   When fasteners bind components together, include them explicitly in the connection_requirement's "between" array.

妫ｅ啯鏆?USE SUBASSEMBLIES FOR GROUPED BINDINGS:
   If multiple components are bound together by plates, frames, or fasteners, create a subassembly.
   Do NOT express such bindings as multiple pairwise connections.
   Every design has at least one semantic grouping (subassembly).

- Do NOT generate coordinates or layouts
- Do NOT decide on CAD primitives or manufacturing methods
- Do NOT simplify by omitting necessary components
- MUST include all inferred components (bearings, fasteners, spacers, shafts)
- MUST generate connection_requirements only (no relations)
- MUST include connection_requirements for EVERY fastener component
  * Fasteners must have at least one connection_requirement specifying what they connect
  * Example: {"id": "hub_arm_fastener_req", "between": ["hub", "arm_1", "fastener_set_1"], "purpose": "fastening_mechanism"}
  * EVERY fastener component MUST participate in at least one connection_requirement
- MUST represent structure via connection_requirements, not positions
- MUST explicitly declare symmetries in the `patterns` section
- MUST state design intents clearly in the `design_intents` section
- MUST separate facts (connection_requirements) from intents (design_intents) - no duplication or contradiction

---

闁宠法濯寸粭?STRUCTURAL COMPLETENESS INVARIANT (AGENT 1 ENFORCEMENT):

Before outputting, verify MANDATORY requirements:

1. **Every fastener component MUST have at least one connection_requirement:**
   - Find all components with type="fastener"
   - Verify EVERY fastener appears in at least one connection_requirement's "between" array
   - If a fastener has NO connection_requirement, STOP and add them

2. **Every bearing component MUST have at least one connection_requirement:**
   - Find all components with type="bearing"
   - Verify EVERY bearing appears in at least one connection_requirement's "between" array
   
3. **Every shaft/axle component MUST have at least one connection_requirement:**
   - Find all components with type="shaft" 
   - Verify EVERY shaft appears in at least one connection_requirement's "between" array

This enforcement is AGENT 1's responsibility. If any component of these critical types has zero connection_requirements, the output is INCOMPLETE.

---

LEGACY EXAMPLES (for reference, but new format preferred):

NOTE: Legacy examples below omit shape_semantics/dimensions. In current output, these fields are REQUIRED.

Old (coordinate-based - AVOID):
```json
{
  "components": [...],
    "coordinates": [...]
}
```

New (semantic, connection-requirement-based - PREFERRED):
```json
{
  "components": [...],
  "subassemblies": [...],
  "connection_requirements": [...],
  "patterns": [...],
  "design_intents": [...]
}
```

---

GENERIC EXAMPLE (Simple Rotating Assembly):

Requirement: "A simple rotating assembly with a central hub and two wheels attached at opposite ends via axles."

COMPONENTS (COMPLETE list, including INFERRED parts):
```json
{
  "components": [
    {
      "id": "hub",
      "type": "hub",
      "role": "load_bearing",
      "parameters": {"radius": 10, "thickness": 5}
    },
    {
      "id": "wheel_1",
      "type": "wheel",
      "role": "rotational_interface",
      "parameters": {"radius": 25, "width": 8}
    },
    {
      "id": "wheel_2",
      "type": "wheel",
      "role": "rotational_interface",
      "parameters": {"radius": 25, "width": 8}
    },
    {
      "id": "axle_1",
      "type": "shaft",
      "role": "rotating_interface",
      "parameters": {"diameter": 6, "length": 35}
    },
    {
      "id": "axle_2",
      "type": "shaft",
      "role": "rotating_interface",
      "parameters": {"diameter": 6, "length": 35}
    },
    {
      "id": "bearing_1",
      "type": "bearing",
      "role": "load_support",
      "parameters": {"bore_diameter": 6, "outer_diameter": 16}
    },
    {
      "id": "bearing_2",
      "type": "bearing",
      "role": "load_support",
      "parameters": {"bore_diameter": 6, "outer_diameter": 16}
    },
    {
      "id": "spacer_1",
      "type": "spacer",
      "role": "spacing",
      "parameters": {"inner_diameter": 6, "outer_diameter": 10, "thickness": 2}
    },
    {
      "id": "spacer_2",
      "type": "spacer",
      "role": "spacing",
      "parameters": {"inner_diameter": 6, "outer_diameter": 10, "thickness": 2}
    },
    {
      "id": "axle_to_hub_fastener_set",
      "type": "fastener",
      "role": "fixation",
      "parameters": {
        "nominal_diameter": 3,
        "count": 4,
        "length": 8
      }
    }
  ],
  "subassemblies": [
    {
      "id": "wheel_axle_assembly_1",
      "description": "Wheel with its support axle and bearings",
      "component_ids": ["wheel_1", "axle_1", "bearing_1", "spacer_1"],
      "role": "rotational_module"
    },
    {
      "id": "wheel_axle_assembly_2",
      "description": "Wheel with its support axle and bearings",
      "component_ids": ["wheel_2", "axle_2", "bearing_2", "spacer_2"],
      "role": "rotational_module"
    }
  ],
  "connection_requirements": [
    {
      "id": "axle_1_hub_connection",
      "between": ["axle_1", "hub"],
      "purpose": "structural_fixation"
    },
    {
      "id": "axle_1_fastener_connection",
      "between": ["axle_1", "axle_to_hub_fastener_set"],
      "purpose": "fastening_mechanism"
    },
    {
      "id": "wheel_1_axle_connection",
      "between": ["wheel_1", "axle_1"],
      "purpose": "rotation"
    },
    {
      "id": "bearing_1_wheel_connection",
      "between": ["wheel_1", "bearing_1"],
      "purpose": "load_support"
    },
    {
      "id": "bearing_1_spacer_connection",
      "between": ["bearing_1", "spacer_1"],
      "purpose": "axial_clearance"
    },
    {
      "id": "axle_2_hub_connection",
      "between": ["axle_2", "hub"],
      "purpose": "structural_fixation"
    },
    {
      "id": "wheel_2_axle_connection",
      "between": ["wheel_2", "axle_2"],
      "purpose": "rotation"
    },
    {
      "id": "bearing_2_wheel_connection",
      "between": ["wheel_2", "bearing_2"],
      "purpose": "load_support"
    },
    {
      "id": "bearing_2_spacer_connection",
      "between": ["bearing_2", "spacer_2"],
      "purpose": "axial_clearance"
    }
  ],
  "patterns": [
    {
      "id": "bilateral_wheels",
      "type": "bilateral_symmetry",
      "count": 2,
      "component_ids": ["wheel_1", "wheel_2"],
      "description": "Two wheels are symmetrically positioned on opposite sides of the hub"
    },
    {
      "id": "axle_symmetry",
      "type": "bilateral_symmetry",
      "count": 2,
      "component_ids": ["axle_1", "axle_2"],
      "description": "Two axles are symmetrically attached perpendicular to the hub"
    }
  ],
  "design_intents": [
    {
      "id": "bilateral_load_distribution",
      "type": "structural_arrangement",
      "description": "Bilateral symmetry enables balanced and predictable load distribution across both wheel assemblies"
    },
    {
      "id": "independent_wheel_operation",
      "type": "motion_constraint",
      "description": "Each wheel can be operated, maintained, and replaced independently without affecting the other"
    },
    {
      "id": "smooth_radial_motion",
      "type": "load_path",
      "description": "Bearing-based support ensures smooth, low-friction rotation even under radial load conditions"
    }
  ]
}
```

---

---

闁宠法濯寸粭?FINAL SELF-CHECK BEFORE OUTPUT (MANDATORY):

Before finalizing and outputting the knowledge_graph.json, you MUST verify ALL of the following:

1. **No Relations Output Check**:
    闁?The "relations" section DOES NOT exist in output
    闁?Connection_requirements remain abstract (purpose + roles + constraints)

2. **Physical Realization Check**:
   闁?Every fixation connection_requirement has a corresponding fastener, clamp, or joint component
   闁?Every load-support connection_requirement has explicit bearing, shaft, or support component
   闁?No "magic" connections that don't correspond to physical parts

3. **Completeness Check**:
   闁?No subassembly is mechanically floating or incompletely constrained
   闁?Every rotating component has a connection_requirement to its support
   闁?Every shaft/axle has a connection_requirement to the main structure
   闁?Every load path is traceable through connection_requirements from component to structure

4. **No Geometry Check**:
   闁?NO coordinates, positions, or layout information anywhere
   闁?NO descriptions of "on the left", "at angle 120閹?, "stacked vertically"
   闁?NO CAD primitives or manufacturing process decisions
   闁?NO assumptions about part shapes or arrangements

5. **Connection Requirements Are Abstract Check**:
    闁?Connection_requirements include "between" and "purpose" fields
    闁?NO "type" field in connection_requirements
  闁?Purpose uses semantic language (rotation, load_support, fixation, spacing, alignment)
  闁?If fastening/clamping is involved, include connection_decision (method/size/count)
  闁?NO location_intent in Agent1 output (Agent2 will infer patterns/symmetry)

6. **Relationship Diagram Check**:
   闁?The entire structure can be drawn as an ellipse (component) + arc (purpose) diagram
   闁?Someone could read ONLY the components and connection_requirements and understand mechanical structure
   闁?No "ghost" information that only makes sense with geometry

IF ANY CHECK FAILS:
   - STOP
   - Revise the knowledge graph to fix the issue
   - Recheck until all items pass
   - ONLY then output the final JSON

---

FINAL VALIDATION CHECKLIST:

Before outputting the knowledge graph, verify:

闁?NO "relations" section in output
闁?YES "connection_requirements" section in output with proper structure
闁?All explicit components are included
闁?All inferred components are included (axles, bearings, fasteners, spacers, etc.)
闁?Fasteners are explicitly included and have connection_requirements
闁?All structural connections have corresponding connection_requirements
闁?All rotating connections have corresponding connection_requirements
闁?All support connections have corresponding connection_requirements
闁?All subassemblies are functionally complete (all components have connection_requirements)
闁?NO absolute or relative coordinates anywhere
闁?NO CAD primitives or manufacturing decisions
闁?All symmetries are declared in the `patterns` section
闁?All design intents are stated in the `design_intents` section
闁?All connection_requirements use semantic purposes (no relation types)
闁?Facts (connection_requirements) and intents (design_intents) are strictly separated - no duplication
闁?No design intents contradict the physical connection_requirements
闁?All fixation connection_requirements have physical realization (fastener, clamp, bearing, shaft, etc.)
闁?No subassembly is mechanically floating or incomplete
闁?No spatial coordinates or layout assumptions exist
闁?Structure can be drawn as relationship diagram without geometry
闁?The `intent` field is populated from use_case/module
闁?JSON output is complete and valid
闁?No relations present in Agent1 output

Output format: Complete JSON with sections (components, subassemblies, connection_requirements, standard_parts, patterns, design_intents, units)

---

妫ｅ啯鏆?MANDATORY PRE-OUTPUT VERIFICATION (NON-NEGOTIABLE):

**REMEMBER: You MUST NOT decide relation types in Agent1.**

**BEFORE you output any JSON, perform this check manually:**

1. Extract all fastener components from your generated components list
2. For EACH fastener component, verify it appears in the "between" array of AT LEAST ONE connection_requirement
3. If ANY fastener has ZERO connection_requirements, STOP and add them NOW
4. Same verification for bearings and shafts - each MUST have at least one connection_requirement
5. Verify that NO connection_requirement includes a "type" field (reserved for relations)
6. Verify that all "purpose" fields use semantic language (rotation, load_support, fixation, spacing, alignment)
   - NOT relation type names (fixed_to, rotates_about, supported_by, clamped_by, etc.)

7. For EACH subassembly with more than one component, verify that its subassembly ID appears
  in at least one connection_requirement "between" array. If missing, STOP and add it.

**Example of INCOMPLETE output (REJECT THIS):**
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "fastener_1", "type": "fastener", ...}  // 闁?This fastener...
  ],
  "connection_requirements": [
    {"id": "hub_connection", "between": ["hub", "arm"], "purpose": "fixation"}  // ...is NOT included here!
  ]
}
```
闁?INCOMPLETE - fastener_1 has zero connection_requirements

**Example of CORRECT output (ACCEPT THIS):**
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "fastener_1", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "hub_connection", "between": ["hub", "arm", "fastener_1"], "purpose": "structural_fixation"}  // 闁?fastener_1 included!
  ]
}
```
闁?COMPLETE - fastener_1 participates in connection_requirement

If your output does NOT pass this verification, revise it until it does.

---

妫ｅ啯鏆?DESIGN INTENT PURITY CHECK (CRITICAL):

Before outputting, examine EVERY design_intent and ask:

**Can this intent be rewritten as a mechanical fact?**

Mechanical facts belong in `connection_requirements`, NOT in `design_intents`.

Example (WRONG - mechanical fact disguised as intent):
```json
{
  "id": "wheel_rotation",
  "type": "motion_constraint",
  "description": "wheel rotates about axle"  // 闁?This is a FACT, not an intent!
}
```
闁?REMOVE OR REWRITE - This should be in connection_requirements, not design_intents

Example (CORRECT - actual intent):
```json
{
  "id": "wheel_rotation",
  "type": "motion_constraint",
  "description": "wheel can be rotated freely for operational purposes"  // 闁?PURPOSE, not fact
}
```
闁?KEEP - This states PURPOSE/REQUIREMENT, not mechanical fact

Example (CORRECT - actual intent):
```json
{
  "id": "independent_rotation",
  "type": "motion_constraint",
  "description": "each wheel rotates independently, enabling omnidirectional motion"  // 闁?ENGINEERING PURPOSE
}
```
闁?KEEP - This states ENGINEERING PURPOSE, not mechanical specification

**TEST: Replace with "because"**

- If you can add "because X is fixed to Y" 闁?MECHANICAL FACT 闁?Move to connection_requirements
- If you can only add "because the system needs..." 闁?INTENT 闁?Keep in design_intents

Example:
- "wheel rotates about axle" = Mechanical fact (belongs in connection_requirement with purpose="rotation")
- "wheel rotation enables omnidirectional movement" = Intent (belongs in design_intents)

If any design_intent can be rewritten as a mechanical fact
(e.g., "wheel rotates about axle", "bearing supports wheel", "arm is fixed to hub"),
it MUST be removed or rewritten as a purpose or requirement.

MANDATORY ACTION:
- Review EVERY design_intent in your output
- If it states a mechanical relationship: DELETE IT or REWRITE IT
- Mechanical relationships go in connection_requirements with semantic purpose
- design_intents ONLY contain engineering goals, constraints, and purposes
"""

    def _request_llm(prompt_text: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt_text}],
            temperature=0.0,  # Lower temperature for more consistent output
            max_tokens=8000,  # Increased to accommodate richer KG output
        )

        return (response.choices[0].message.content or "").strip()

    last_error: Exception | None = None
    prompt_to_use = prompt
    content: str = ""
    for attempt in range(2):
        try:
            content = _request_llm(prompt_to_use)
            kg = extract_json_from_llm_response(content)
            if kg is None:
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix="_invalid.json", delete=False, encoding="utf-8"
                ) as f:
                    f.write(content)
                    error_file = f.name
                raise ValueError(
                    "LLM generated invalid JSON payload. "
                    f"Invalid JSON saved to: {error_file}\n"
                    f"Content preview: {content[:500]}..."
                )

            _cleanup_auto_generated_connections(kg)
            _strip_location_intent(kg)
            _normalize_component_contract_fields(kg)
            _normalize_component_kind_and_must_model(kg)
            _ensure_wheel_mounting_requirements(kg)
            _normalize_connection_requirements(kg)

            # Deterministic decomposition of complex components (before dimension filling)
            _decompose_complex_components(kg)
            _collapse_semantic_clones(kg)
            _canonicalize_wheel_rotor_naming(kg)
            _prune_rotating_wheel_support_fastening_conflicts(kg)
            _prune_asymmetric_wheel_support_artifacts(kg)
            _prune_non_explicit_wheel_internal_fastening(kg)
            _prune_asymmetric_wheel_axle_auxiliary_artifacts(kg)
            _repair_illegal_wheel_axle_hub_links(kg)
            _repair_rotating_wheel_hub_axle_fixation_links(kg)
            _canonicalize_rotating_wheel_axle_support_mounts(kg)
            _rewire_rotating_wheel_container_rotation_hosts(kg)
            _ensure_arm_interface_requirements(kg)
            _enforce_central_hub_arm_slot_mounts(kg)
            _canonicalize_hub_arm_fastener_components(kg)
            _normalize_symmetric_hub_arm_fasteners(kg)
            _prune_non_explicit_wheel_internal_fastening(kg)
            _validate_wheel_arm_connection_topology(kg)
            _ensure_wheel_subcomponent_instance_patterns(kg)
            _ensure_wheel_rim_tire_position_parent(kg)
            _align_rotational_symmetry_instancing_annotations(kg)
            _sanitize_instancing_annotations(kg)
            _normalize_and_canonicalize_bearings(kg)

            _ensure_shape_semantics_defaults(kg)
            _fill_missing_dimensions(kg)
            _normalize_and_canonicalize_bearings(kg)
            _prune_stale_standard_parts(kg)
            _infer_standard_parts(kg)
            _prune_stale_standard_parts(kg)
            _validate_no_relations(kg)
            
            # Decomposition templates handle shaft/bearing requirements; no ensure needed
            _ensure_no_isolated_structural_components(kg)
            _ensure_component_hierarchy_contract(kg)
            _sync_dimensions_and_parameters(kg)
            
            _ensure_module_subassembly_interfaces(kg)

            # Validate fastener usage (critical structural constraint)
            _validate_fastener_usage(kg)
            # Validate clamping subassemblies include fasteners
            _validate_clamping_subassembly_has_fasteners(kg)
            # Validate fastener purpose specificity
            _validate_fastener_purpose_specificity(kg)
            # Repair subassembly connections (naming-based)
            _repair_subassembly_connections(kg)
            _prune_redundant_wheel_subassemblies(kg)
            # Auto-fill missing connection decisions when fastening is implied
            _autofill_missing_connection_decisions(kg)
            # Validate subassembly connectivity (prevent floating subassemblies)
            _validate_subassembly_connectivity(kg)
            # Deterministic closure for bearing/shaft required purposes
            _autofill_bearing_and_shaft_closure(kg)
            # Deterministic closure for module-level active rotation drive chain
            _infer_module_drive_chain(requirement_text, kg)
            _sanitize_fastener_bundles(kg)
            _prune_stale_standard_parts(kg)
            _infer_standard_parts(kg)
            _prune_stale_standard_parts(kg)
            # Re-run closure after inferred components are inserted (e.g., module_drive_shaft)
            _autofill_bearing_and_shaft_closure(kg)
            _normalize_connection_requirements(kg)
            _enrich_connection_semantics_with_llm(kg)
            _normalize_connection_requirements(kg)
            _drop_agent1_autofilled_connection_decisions_when_semantics_present(kg)
            _autofill_agent1_deterministic_connection_semantics(kg)
            _elevate_authoritative_connection_semantics_detail(kg)
            _normalize_symmetric_wheel_rim_hub_connection_semantics(kg)
            _normalize_symmetric_wheel_tire_rim_connection_semantics(kg)
            _enforce_central_hub_arm_slot_mounts(kg)
            # Validate bearing/shaft completeness and role separation
            _validate_bearing_and_shaft_completeness(kg)
            _validate_connection_semantics_contracts(kg)
            # Validate frozen connection decisions
            _validate_connection_decisions(kg)
            # Populate frozen spec for immutability checks
            _populate_frozen_spec(kg)
            _validate_wheel_rotor_naming(kg)
            _validate_bearing_canonical_schema(kg)

            return kg
        except ValueError as exc:
            last_error = exc
            if attempt == 0:
                extra_rules = ""
                error_text = str(exc)
                
                if "does not include any fastener" in error_text.lower():
                    extra_rules += (
                        "- Clamping/fixation subassemblies MUST include fastener components in their component_ids. "
                        "Example: If 'carrier_plate_assembly' with role 'structural_clamping' has component_ids=['plate_top', 'plate_bottom', 'plate_fastener_set'], it MUST include the fastener_set.\n"
                    )
                
                if "semantically floating" in error_text.lower() and "carrier" in error_text.lower():
                    extra_rules += (
                        "- Ensure carrier_plate_assembly's component_ids includes the fastener components that physically clamp the plates together.\n"
                        "- If fastener_sets exist in the design, they MUST be members of carrier_plate_assembly.\n"
                    )
                
                if "support_to_structure" in error_text:
                    extra_rules += (
                        "- Add support_to_structure connection_requirements for EVERY bearing. "
                        "Connect each bearing to its supporting structural component (e.g., matching wheel_arm_* or carrier_plate_assembly).\n"
                    )
                
                if "subassembly is semantically floating" in error_text.lower():
                  extra_rules += (
                    "- Subassemblies with multiple components MUST either:\n"
                    "  A) Appear as a hub in at least one connection_requirement, OR\n"
                    "  B) Have at least 50% of their members directly used in connection_requirements.\n"
                    "- Check that all members of the subassembly appear in connection_requirements.\n"
                  )
                
                if "rotation/torque_transfer" in error_text or "structural_fixation" in error_text:
                    extra_rules += (
                        "- Add rotation (or torque_transfer) AND structural_fixation requirements for EVERY shaft/axle. "
                        "Do NOT bundle multiple roles in one requirement.\n"
                    )
                
                if "includes a fastener but uses generic purpose" in error_text.lower():
                    extra_rules += (
                        "- When a connection_requirement includes a fastener in 'between', the purpose MUST be engineering-specific. "
                        "Replace generic purposes like 'structural_fixation' with 'fastening_mechanism' or 'bolted_joint' when fasteners are present.\n"
                    )
                if "connection_semantics" in error_text.lower():
                    extra_rules += (
                        "- For every mechanically resolved connection_requirement, add connection_semantics with mechanism, anchors, interface hints, orientation_policy, and geometric_semantics.\n"
                        "- geometric_semantics MUST specify contact_model, feature strategies on both sides, and explicit pattern_policy/pattern_count when relevant.\n"
                        "- Do NOT use generic_mount, generic relation_type values, or placeholder hints like fixation_req / mounting_req / unspecified.\n"
                    )
                
                if "semantic overreach" in error_text.lower() or "redundant" in error_text.lower():
                    extra_rules += (
                        "- Remove connection_requirements where a subassembly connects to components that its members already connect to. "
                        "A subassembly should only appear as a hub if it adds semantic value (e.g., carrier_plate_assembly connecting to central_hub is valid, but wheel_assembly connecting to wheel_arm is redundant if wheel_axle/bearing already connect there).\n"
                    )
                if extra_rules:
                    extra_rules = "\nREPAIR RULES:\n" + extra_rules
                prompt_to_use = (
                    prompt
                    + "\n\nCORRECTION REQUIRED:\n"
                    + "You must fix the error below and return ONLY corrected JSON.\n"
                    + extra_rules
                    + f"Error: {exc}\n"
                    + "Here is your previous JSON output:\n```json\n"
                    + content
                    + "\n```\n"
                    + "Return corrected JSON only. Do not add explanations."
                )
                continue
            raise
        except Exception as e:
            raise ValueError(f"LLM failed to generate knowledge graph: {e!r}")

    if last_error is not None:
      raise last_error
    raise ValueError("LLM failed to generate knowledge graph.")


def _promote_subassemblies_to_components(kg: Dict[str, Any]) -> None:
    """Promote subassemblies to component nodes.
    
    Each subassembly becomes BOTH:
    - An entry in subassemblies[] (semantic grouping)
    - An entry in components[] with type="subassembly" (connectable node for Agent2)
    
    This ensures Agent2's type map can recognize subassembly nodes and doesn't default to "unknown".
    """
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list) or not subassemblies:
        return
    
    components = kg.get("components", [])
    if not isinstance(components, list):
        components = []
        kg["components"] = components
    
    existing_component_ids = {c.get("id") for c in components if isinstance(c, Mapping)}
    
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        if not isinstance(sa_id, str):
            continue
        
        # Skip if already exists as component
        if sa_id in existing_component_ids:
            continue
        
        # Promote subassembly to component node
        component_entry = {
            "id": sa_id,
            "type": "subassembly",
            "role": sa.get("role", "binding"),
          "parameters": {},
          "dimensions": {},
          "dimension_sources": {},
          "shape_semantics": {"type": "complex", "notes": "subassembly"},
        }
        
        # Copy description if available
        if "description" in sa and isinstance(sa["description"], str):
            # Store description in a way that's compatible with schema
            # Schema doesn't have description field, so we skip it
            pass
        
        components.append(component_entry)
        print(f"[PROMOTE] Subassembly '{sa_id}' added to components[] with type='subassembly'")


# _generate_relations_from_connection_requirements removed
# Agent1 generates connection_requirements; relations are downstream


def _validate_against_schema(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return

    lines = ["Knowledge graph validation failed:"]
    for err in errors[:20]:
        path = ".".join([str(p) for p in err.path]) if err.path else "<root>"
        lines.append(f"- {path}: {err.message}")
    if len(errors) > 20:
        lines.append(f"... (+{len(errors) - 20} more)")

    raise ValueError("\n".join(lines))


def transform_yaml_to_kg(
    requirement_yaml: Any = None,
    schema: Any = None,
    *,
    in_path: Path = None,
    schema_path: Path = None,
) -> Dict[str, Any]:
    """Transform requirements to a validated KG.

    Supports:
    - Legacy structured call: `transform_yaml_to_kg(payload_dict, schema_dict)`
    - Current file-based call: `transform_yaml_to_kg(in_path=..., schema_path=...)`
    """

    requirement_text_context = ""

    if in_path is not None or schema_path is not None:
        if in_path is None or schema_path is None:
            raise TypeError("transform_yaml_to_kg requires both in_path and schema_path in path mode")

        raw = _read_yaml(in_path)
        schema = _read_json(schema_path)

        # If the YAML is already structured as a KG, do not call the LLM.
        if isinstance(raw, dict) and "components" in raw and "connection_requirements" in raw:
            payload = copy.deepcopy(raw)
            requirement_text_context = json.dumps(raw, ensure_ascii=False)
        else:
            requirement_text = in_path.read_text(encoding="utf-8")
            payload = _call_llm_to_generate_kg(requirement_text, schema)
            requirement_text_context = requirement_text
    else:
        if not isinstance(requirement_yaml, dict) or not isinstance(schema, dict):
            raise TypeError(
                "transform_yaml_to_kg legacy mode expects (requirement_yaml: dict, schema: dict)"
            )
        payload = copy.deepcopy(requirement_yaml)
        requirement_text_context = json.dumps(requirement_yaml, ensure_ascii=False)
    
    # Promote subassemblies to component nodes BEFORE validation
    # This ensures Agent2 can recognize them in type map
    _promote_subassemblies_to_components(payload)
    
    # Filter out type="module" components - they are conceptual containers, not geometric entities
    # Agent2 processes geometric components only; modules remain as hierarchical metadata
    components = payload.get("components", [])
    if isinstance(components, list):
        geometric_components = [
            c for c in components 
            if isinstance(c, dict) and c.get("type") != "module"
        ]
        module_ids = {
            c.get("id") for c in components 
            if isinstance(c, dict) and c.get("type") == "module" and isinstance(c.get("id"), str)
        }
        payload["components"] = geometric_components
        
        # Also handle connection_requirements that reference removed module components
        # For bearing support connections, replace module with structural component
        # For other connections, remove them
        crs = payload.get("connection_requirements", [])
        if isinstance(crs, list) and module_ids:
            # Find a suitable structural replacement (hub, base, frame)
            structural_replacement = None
            for c in geometric_components:
                if isinstance(c, dict) and isinstance(c.get("id"), str):
                    ctype = c.get("type", "")
                    if ctype in {"hub", "base", "frame"} or "hub" in c.get("id", "").lower():
                        structural_replacement = c.get("id")
                        break
            
            filtered_crs = []
            for cr in crs:
                if not isinstance(cr, dict):
                    filtered_crs.append(cr)
                    continue
                
                between = cr.get("between", [])
                purpose = cr.get("purpose", "")
                
                if isinstance(between, list):
                    # Check if any component in between is a module
                    has_module = any(cid in module_ids for cid in between if isinstance(cid, str))
                    
                    if has_module:
                        # For bearing support, replace module with structural component
                        if purpose == "support_to_structure" and structural_replacement:
                            new_between = [
                                structural_replacement if cid in module_ids else cid 
                                for cid in between if isinstance(cid, str)
                            ]
                            cr = dict(cr)  # Copy to avoid modifying original
                            cr["between"] = new_between
                            filtered_crs.append(cr)
                        # For other purposes, skip the connection
                        continue
                    else:
                        filtered_crs.append(cr)
                elif isinstance(between, dict):
                    # Skip if any key in between dict is a module
                    if any(cid in module_ids for cid in between.keys()):
                        continue
                    filtered_crs.append(cr)
                else:
                    filtered_crs.append(cr)
            payload["connection_requirements"] = filtered_crs
    
    # Deterministic closure + contract normalization for structured inputs.
    # (LLM path already runs most closures, but these are idempotent and help enforce contract.)
    _normalize_component_contract_fields(payload)
    _normalize_component_kind_and_must_model(payload)
    _ensure_wheel_mounting_requirements(payload)
    _autofill_bearing_and_shaft_closure(payload)
    _infer_module_drive_chain(requirement_text_context, payload)
    _autofill_bearing_and_shaft_closure(payload)
    _normalize_connection_requirements(payload)
    _drop_agent1_autofilled_connection_decisions_when_semantics_present(payload)
    _canonicalize_wheel_rotor_naming(payload)
    _prune_rotating_wheel_support_fastening_conflicts(payload)
    _prune_asymmetric_wheel_support_artifacts(payload)
    _prune_non_explicit_wheel_internal_fastening(payload)
    _prune_asymmetric_wheel_axle_auxiliary_artifacts(payload)
    _repair_illegal_wheel_axle_hub_links(payload)
    _repair_rotating_wheel_hub_axle_fixation_links(payload)
    _canonicalize_rotating_wheel_axle_support_mounts(payload)
    _rewire_rotating_wheel_container_rotation_hosts(payload)
    _ensure_arm_interface_requirements(payload)
    _enforce_central_hub_arm_slot_mounts(payload)
    _canonicalize_hub_arm_fastener_components(payload)
    _normalize_symmetric_hub_arm_fasteners(payload)
    _prune_non_explicit_wheel_internal_fastening(payload)
    _validate_wheel_arm_connection_topology(payload)
    _ensure_wheel_subcomponent_instance_patterns(payload)
    _ensure_wheel_rim_tire_position_parent(payload)
    _ensure_component_hierarchy_contract(payload)
    _sync_dimensions_and_parameters(payload)
    _sanitize_fastener_bundles(payload)
    _prune_stale_standard_parts(payload)
    _infer_standard_parts(payload)
    _prune_stale_standard_parts(payload)
    _autofill_agent1_deterministic_connection_semantics(payload)
    _elevate_authoritative_connection_semantics_detail(payload)
    _normalize_symmetric_wheel_rim_hub_connection_semantics(payload)
    _normalize_symmetric_wheel_tire_rim_connection_semantics(payload)
    _enforce_central_hub_arm_slot_mounts(payload)
    _canonicalize_hub_arm_fastener_components(payload)
    _prune_stale_standard_parts(payload)
    _validate_no_relations(payload)
    _validate_wheel_rotor_naming(payload)
    payload.pop("agent1_connection_semantics_audit", None)

    _validate_against_schema(payload, schema)
    _prune_redundant_wheel_subassemblies(payload)
    _validate_subassembly_connectivity(payload)
    _annotate_component_execution_roles(payload)
    return payload


def _annotate_component_execution_roles(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    role_map: Dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str) or not comp_id:
            continue

        ctype = str(comp.get("type") or "").strip().lower()
        is_container = bool(comp.get("is_container"))
        must_model = bool(comp.get("must_model"))
        modeling_policy = str(comp.get("modeling_policy") or "").strip().lower()

        if ctype in {"subassembly", "assembly", "module"} or is_container or (not must_model and modeling_policy == "reference_only"):
            role_map[comp_id] = "container_only"
            continue

        if ctype in {"fastener", "bearing", "spacer"} or "fastener_set" in comp_id:
            role_map[comp_id] = "standard_part_insert_only"
            continue

        role_map[comp_id] = "model_entity"

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["component_execution_roles"] = role_map


def _infer_role_in_parent(component: Mapping[str, Any]) -> str | None:
    ctype = str(component.get("type") or "").strip().lower()
    cid = str(component.get("id") or "").strip().lower()
    if ctype in {"rim", "tire", "hub", "axle"}:
        return ctype
    for tok in ("rim", "tire", "hub", "axle"):
        if tok in cid:
            return tok
    return None


def _ensure_component_hierarchy_contract(payload: Dict[str, Any]) -> None:
    by_id, children_by_parent = _collect_component_hierarchy_candidates(payload)
    if not by_id:
        return

    hierarchy: List[Dict[str, Any]] = []
    for parent_id, children in sorted(children_by_parent.items()):
        if parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        if _preserve_hierarchy_parent_as_physical(parent):
            _mark_component_as_physical_part(parent)
        else:
            _mark_component_as_container_only(
                parent,
                note="inferred_hierarchy_container_from_child_components",
            )

        uniq_children = sorted({c for c in children if c in by_id})
        if not uniq_children:
            continue
        for child_id in uniq_children:
            child = by_id[child_id]
            child["position_parent"] = parent_id
            role = _infer_role_in_parent(child)
            if role:
                child["role_in_parent"] = role
        hierarchy.append({"id": parent_id, "children": uniq_children})

    if hierarchy:
        payload["component_hierarchy"] = hierarchy

def _rewire_container_connections(kg: dict) -> Tuple[dict, dict]:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return kg, {"rewired_count": 0, "rewired": []}

    connection_requirements = kg.get("connection_requirements", [])
    if not isinstance(connection_requirements, list):
        return kg, {"rewired_count": 0, "rewired": []}

    component_by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id:
            component_by_id[comp_id] = comp

    def _is_container_component(component_id: str) -> bool:
        comp = component_by_id.get(component_id)
        if not isinstance(comp, dict):
            return False
        if bool(comp.get("is_container_only")):
            return True
        if bool(comp.get("is_container")):
            return True
        policy = comp.get("modeling_policy")
        if isinstance(policy, str) and policy.strip().lower() in {"container_only"}:
            return True
        return False

    children_by_parent: Dict[str, List[str]] = {}
    hierarchy = kg.get("component_hierarchy")
    if isinstance(hierarchy, list):
        for node in hierarchy:
            if not isinstance(node, Mapping):
                continue
            parent_id = node.get("id")
            children = node.get("children")
            if not isinstance(parent_id, str) or not parent_id:
                continue
            if not isinstance(children, list):
                continue
            child_ids = sorted({cid for cid in children if isinstance(cid, str) and cid in component_by_id})
            if child_ids:
                children_by_parent[parent_id] = child_ids

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        child_id = comp.get("id")
        parent_id = comp.get("position_parent")
        if isinstance(child_id, str) and child_id and isinstance(parent_id, str) and parent_id in component_by_id:
            children_by_parent.setdefault(parent_id, [])
            if child_id not in children_by_parent[parent_id]:
                children_by_parent[parent_id].append(child_id)

    for parent_id in list(children_by_parent.keys()):
        children_by_parent[parent_id] = sorted(children_by_parent[parent_id])

    rewired: List[Dict[str, Any]] = []

    def _contains_any(values: List[str], needles: set[str]) -> bool:
        for value in values:
            lower_value = value.lower()
            for needle in needles:
                if needle in lower_value:
                    return True
        return False

    def _choose_child(parent_id: str, conn: Mapping[str, Any]) -> str:
        candidates = children_by_parent.get(parent_id, [])
        if not candidates:
            raise ValueError(
                f"Container connection rewiring failed: container '{parent_id}' has no child components"
            )

        purpose = str(conn.get("purpose") or "").strip().lower()
        constraint_intent = str(conn.get("constraint_intent") or "").strip().lower()
        roles = [str(r).strip().lower() for r in conn.get("roles", []) if isinstance(r, str)] if isinstance(conn.get("roles"), list) else []
        mating_features = [str(m).strip().lower() for m in conn.get("mating_features", []) if isinstance(m, str)] if isinstance(conn.get("mating_features"), list) else []

        rotation_like = (
            purpose == "rotation"
            or constraint_intent == "revolute"
            or _contains_any(mating_features, {"axis", "seat"})
        )
        fasten_like = (
            "fasten" in purpose
            or any(role in {"fixation", "mounting"} for role in roles)
            or _contains_any(mating_features, {"through_hole", "thread_feature"})
        )

        preference_tokens: List[str] = []
        if rotation_like:
            preference_tokens = ["hub", "axle"]
        elif fasten_like:
            preference_tokens = ["hub", "spoke", "arm"]

        normalized_candidates = [(cid, cid.lower()) for cid in sorted(candidates)]
        for token in preference_tokens:
            for cid, lower_cid in normalized_candidates:
                if token in lower_cid:
                    return cid

        return sorted(candidates)[0]

    for conn in connection_requirements:
        if not isinstance(conn, dict):
            continue
        between = conn.get("between")
        if not isinstance(between, list) or len(between) < 2:
            continue

        purpose = str(conn.get("purpose") or "").strip().lower()
        if "subassembly" in purpose and "group" in purpose:
            continue

        original_between = [cid for cid in between if isinstance(cid, str)]
        if len(original_between) < 2:
            continue

        connection_semantics = conn.get("connection_semantics") if isinstance(conn.get("connection_semantics"), Mapping) else None
        if isinstance(connection_semantics, Mapping):
            if isinstance(connection_semantics.get("connection_mechanism"), str) and str(connection_semantics.get("connection_mechanism") or "").strip():
                conn.setdefault("metadata", {})["rewire_skipped"] = {
                    "reason": "authoritative_connection_semantics_preserved",
                    "original_between": original_between,
                }
                continue

        new_between = list(original_between)
        changed = False
        for idx, comp_id in enumerate(original_between):
            if not _is_container_component(comp_id):
                continue
            replacement = _choose_child(comp_id, conn)
            if replacement != comp_id:
                new_between[idx] = replacement
                changed = True

        if changed:
            # Prevent self-connections (both sides rewired to same child)
            unique_between = list(dict.fromkeys(new_between))  # preserve order, dedup
            if len(unique_between) < 2:
                # Both endpoints collapsed to the same component -- skip rewiring
                conn["between"] = original_between
                conn.setdefault("metadata", {})["rewire_skipped"] = {
                    "reason": "self_connection_after_rewire",
                    "collapsed_to": unique_between[0] if unique_between else None,
                }
                continue
            conn["between"] = new_between
            conn["rewired_from"] = {
                "original_between": original_between,
                "reason": "container_component_rewired_to_child_for_interface_resolution",
            }
            rewired.append(
                {
                    "connection_id": conn.get("id"),
                    "original_between": original_between,
                    "rewired_between": new_between,
                }
            )

    return kg, {
        "rewired_count": len(rewired),
        "rewired": rewired,
    }


def inject_resolved_standard_parts(*, run_dir: Path) -> Dict[str, Any]:
    """Inject resolved standard parts back into knowledge_graph.json.

    Bridge step used by pipeline after tools/resolve_standard_parts.py.
    It keeps KG and planning artifacts aligned for downstream agents.
    """

    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    resolved_path = run_dir / "planning" / "standard_parts_resolved.json"
    unresolved_path = run_dir / "planning" / "standard_parts_unresolved.json"

    if not kg_path.exists():
        raise FileNotFoundError(f"knowledge_graph.json not found: {kg_path}")
    if not resolved_path.exists():
        return {
            "updated": False,
            "reason": "resolved_file_missing",
            "knowledge_graph": str(kg_path).replace("\\", "/"),
            "resolved_path": str(resolved_path).replace("\\", "/"),
        }

    kg = _read_json(kg_path)
    resolved_payload = _read_json(resolved_path)
    unresolved_payload = _read_json(unresolved_path) if unresolved_path.exists() else {}

    resolved_parts = []
    if isinstance(resolved_payload, Mapping):
        parts = resolved_payload.get("resolved", [])
        if isinstance(parts, list):
            resolved_parts = [p for p in parts if isinstance(p, Mapping)]

    unresolved_parts = []
    if isinstance(unresolved_payload, Mapping):
        parts = unresolved_payload.get("unresolved", [])
        if isinstance(parts, list):
            unresolved_parts = [p for p in parts if isinstance(p, Mapping)]

    if isinstance(kg, Mapping):
        kg = dict(kg)
    else:
        kg = {}

    def _parse_metric_size(value: Any) -> tuple[float | None, float | None]:
        if not isinstance(value, str):
            return None, None
        import re

        m = re.search(r"\bM\s*(\d+(?:\.\d+)?)\s*(?:[xX]\s*(\d+(?:\.\d+)?))?", value)
        if not m:
            return None, None
        nominal = float(m.group(1))
        length = float(m.group(2)) if m.group(2) else None
        return nominal, length

    def _size_from_resolved(row: Mapping[str, Any]) -> str | None:
        candidate = row.get("size")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        resolved_designation = row.get("resolved_designation")
        if isinstance(resolved_designation, str) and resolved_designation.strip():
            nominal, length = _parse_metric_size(resolved_designation)
            if isinstance(nominal, (int, float)):
                nominal_s = str(int(nominal)) if abs(nominal - int(nominal)) < 1e-6 else f"{nominal:g}"
                if isinstance(length, (int, float)):
                    length_s = str(int(length)) if abs(length - int(length)) < 1e-6 else f"{length:g}"
                    return f"M{nominal_s}x{length_s}"
                return f"M{nominal_s}"
        return None

    resolved_fasteners = [
        r
        for r in resolved_parts
        if isinstance(r, Mapping)
        and str(r.get("category") or "").strip().lower() in {"fastener", "bolt", "screw", "nut", "washer", "rivet"}
    ]

    by_bound_component: Dict[str, Dict[str, Any]] = {}
    by_connection_id: Dict[str, Dict[str, Any]] = {}
    for row in resolved_fasteners:
        bound_ids = row.get("bound_component_ids")
        if isinstance(bound_ids, list):
            for cid in bound_ids:
                if isinstance(cid, str) and cid and cid not in by_bound_component:
                    by_bound_component[cid] = dict(row)
        applied = row.get("applied_to")
        if isinstance(applied, list):
            for cr_id in applied:
                if isinstance(cr_id, str) and cr_id and cr_id not in by_connection_id:
                    by_connection_id[cr_id] = dict(row)

    components = kg.get("components")
    if isinstance(components, list):
        for comp in components:
            if not isinstance(comp, dict):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str) or cid not in by_bound_component:
                continue
            row = by_bound_component[cid]
            fastener = row.get("fastener") if isinstance(row.get("fastener"), Mapping) else {}
            nominal = fastener.get("nominal_diameter_mm") if isinstance(fastener.get("nominal_diameter_mm"), (int, float)) else None
            length = fastener.get("length_mm") if isinstance(fastener.get("length_mm"), (int, float)) else None
            dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
            dims = dict(dims)
            if isinstance(nominal, (int, float)):
                dims["nominal_diameter"] = float(nominal)
            if isinstance(length, (int, float)):
                dims["length"] = float(length)
            if dims:
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)

    connection_requirements = kg.get("connection_requirements")
    updated_connection_decisions = 0
    if isinstance(connection_requirements, list):
        for cr in connection_requirements:
            if not isinstance(cr, dict):
                continue
            decision = cr.get("connection_decision")
            if not isinstance(decision, Mapping):
                continue
            decision = dict(decision)

            ref_component_id = decision.get("fastener_ref_component_id")
            resolved_row = None
            if isinstance(ref_component_id, str) and ref_component_id:
                resolved_row = by_bound_component.get(ref_component_id)
            if resolved_row is None:
                cr_id = cr.get("id")
                if isinstance(cr_id, str) and cr_id:
                    resolved_row = by_connection_id.get(cr_id)
            if resolved_row is None:
                continue

            requested_size = decision.get("fastener_size") if isinstance(decision.get("fastener_size"), str) else None
            resolved_size = _size_from_resolved(resolved_row)
            if isinstance(requested_size, str) and requested_size.strip():
                decision["requested_fastener_size"] = requested_size.strip()
            if isinstance(resolved_size, str) and resolved_size:
                decision["fastener_size"] = resolved_size

            resolved_designation = resolved_row.get("resolved_designation")
            if isinstance(resolved_designation, str) and resolved_designation.strip():
                decision["resolved_fastener_designation"] = resolved_designation.strip()

            fastener = resolved_row.get("fastener") if isinstance(resolved_row.get("fastener"), Mapping) else {}
            nominal = fastener.get("nominal_diameter_mm") if isinstance(fastener.get("nominal_diameter_mm"), (int, float)) else None
            length = fastener.get("length_mm") if isinstance(fastener.get("length_mm"), (int, float)) else None
            if isinstance(nominal, (int, float)):
                decision["resolved_nominal_diameter_mm"] = float(nominal)
            if isinstance(length, (int, float)):
                decision["resolved_length_mm"] = float(length)

            cr["connection_decision"] = decision
            updated_connection_decisions += 1

    kg["standard_parts"] = resolved_parts
    kg["standard_parts_resolved"] = {
        "resolved": resolved_parts,
        "injected_at": datetime.now().isoformat(timespec="seconds"),
    }
    if unresolved_parts:
        kg["standard_parts_unresolved"] = {
            "unresolved": unresolved_parts,
            "injected_at": datetime.now().isoformat(timespec="seconds"),
        }

    kg_path.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "updated": True,
        "resolved_count": len(resolved_parts),
        "unresolved_count": len(unresolved_parts),
        "updated_connection_decisions": updated_connection_decisions,
        "knowledge_graph": str(kg_path).replace("\\", "/"),
    }


def run(*, run_dir: Path, schema_path: Path | None = None) -> None:
    """Agent entrypoint (facts-layer I/O only).

    Reads:
    - run_dir/input/anforderungsliste.yaml

    Writes:
    - run_dir/knowledge/knowledge_graph.json

    Does not write anywhere outside run_dir.
    """

    schema_path = schema_path or Path("planning") / "knowledge_graph_schema.json"

    in_path = run_dir / "input" / "anforderungsliste.yaml"
    out_path = run_dir / "knowledge" / "knowledge_graph.json"

    if not in_path.exists():
        raise SystemExit(f"Input YAML not found: {in_path}")
    if not schema_path.exists():
        raise SystemExit(f"Schema not found: {schema_path}")

    kg = transform_yaml_to_kg(in_path=in_path, schema_path=schema_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Requirement-to-KG agent (run-dir IO): input/anforderungsliste.yaml -> knowledge/knowledge_graph.json"
    )
    parser.add_argument(
        "--run-dir",
        dest="run_dir",
        required=True,
        help="Run directory, e.g. execution/runs/<run_id>",
    )
    parser.add_argument(
      "--schema",
      dest="schema_path",
            default="planning/knowledge_graph_schema.json",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    schema_path = Path(args.schema_path)
    run(run_dir=run_dir, schema_path=schema_path)
    print(f"Wrote: {run_dir / 'knowledge' / 'knowledge_graph.json'}")


if __name__ == "__main__":
    main()











