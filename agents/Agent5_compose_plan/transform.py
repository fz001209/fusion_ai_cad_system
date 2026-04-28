"""
Agent5: compose_plan闁挎稑鐗愰鎼佸礆閹烘挻娈婚柛姘墕濞呮帡鏁?

缂侇垵宕电划铏规喆閹烘洖顥忛柨?
- 閻忓繐妫楅崵鎴炴媴閺団槅鍚€闁告帗甯槐姗漡ent3 閺夊牊鎸搁崵顓㈡晬婢跺鐟㈤悷浣告嚇閸樸倗鎮伴妷銈囶伈闁挎稑婀廹ent4 閺夊牊鎸搁崵顓㈡晬婢跺娈婚柛姘墔鐠愮喓鈧懓鏈弳锝夋儍閸曨剙鈷旈悶娑樼焷椤撴悂宕?
- 缁绢収鍠栭悾?Fusion API function 闁汇劌瀚惃鐔兼偨閵娾斂鈧孩鎯旇箛銉х閺夆晜鐟﹀Σ鎼佸嫉閳ь剟鏌屽鍫矗闁汇劌瀚欢顓㈠礄閻氬绀?- 闁汇垻鍠愰崹?fusion_api_server 闁圭瑳鍡╂斀闁革絻鍔庡▓鎴炴綇閹惧啿寮冲┑鍌涘灩鐎规娊鏁嶉崸濯cution contract闁?

闁哄懘缂氶崗妯绘媴閹惧啿鐎荤€规悶鍎荤槐?
- Agent1闁挎稑鐗撳〒璺盒ч崒婊勫€為悷娆欑秶缁辨岸鏁嶅渚?闁?闁活厹鍎撮惁鎴﹀炊閹规劖鐨戦柨娑樻箯I 闁规亽鍔庨幃濠囨晬?
- Agent2闁挎稑鐗嗛崵鎴炴媴閺団槅鍤斿☉鏂款槼椤宕氶幒鐐电闁挎稒顑欸 闁?闁告垹濮崇紞宥囨嫚椤撴繄鐤呴柨娑樻箯I 闁规亽鍔庨幃濠囨晬?
- Agent3闁挎稑鐗嗛懜浼存偐鐠鸿櫣鏉介柣婊勫椤宕氶幒鐐电闁挎稒鑹鹃崵鎴炴媴閺団槅鍤斿☉?闁?鐎点倗鍎よ啯缂佹稒鐗滈弳鎰版晬閸懇鈧鈧纰嶉埀顑棭娼愰柛鎺撶懕缁?
- Agent4闁挎稑鐗愰ˉ濠囨煀瀹ュ牜鍤斿☉鏂款槼椤宕氶幒鐐电闁挎稒顑欸 + 濠靛倹鍨圭€?闁?閻熶礁鎳橀崢銈夊礂瀹曞洭鍏囬柨娑樻耿LM 閺夊牆鎳庢慨顏堝箳閵娧勫€為柨?
- Agent5闁挎稑鐗婂﹢浼村疾妤﹀灝鍘村ù锝嗘惈缁辨岸鏁嶅顓熸闁告艾鐗愰鎼佸礆?+ 缁绢収鍠栭悾鍓ф嫬閸愵亝鏆忓銈呮惈缁參鏁嶉崼鈶┾偓妯尖偓瑙勭閳ь儸鍥ｅ亾閺勫繒甯嗛柨?
- 闁圭瑳鍡╂斀闁革綆鐓夌槐妾塽sion_api_server闁挎稑顧€缁辨壆鎷犵拠鎻掔悼閻犱讲鈧啿鐏婇柨娑樼焷閻ㄧ喖鎮?Fusion API闁挎稑鐗撳?AI闁挎稑鐬奸垾妯尖偓瑙勭閳ь儸鍕挃閻炴稑鐭夌槐?

閺夊牊鎸搁崵顓熺附閹寸姴顔婇柨?
- function_plan.json: 閻熸瑥瀚崹婵嬫⒓閼告鍞介悗娑櫳戦妴鍌炴晬閸繂鐦堕柛姘煎亜閻ｎ剟寮?metadata闁?
- fusion_manual_plan.json: 闁圭瑳鍡╂斀闁革絻鍔忕欢顓㈠礂閵夘垳绀勯柣鈺佺摠鐢瓨绗?fusion_api_server 閻犲洩顕цぐ鍥晬?
- 濞戞挶鍊涢埀顒€鎳庨崬瀵糕偓鐟版贡濞村宕ュ畝瀣閻犱警鍨扮欢鐐寸▔瀹ュ懏鍊遍柨娑樼墛婢х晫鎮扮仦鑺ョ彜濞?run_dir 闁哄秴婀卞ú鎷屻亹閺団槅鍤㈤柛娆愮壄缁?

閺夊牆婀遍弲顐ょ棯閿旇姤灏嗛柨?
- 濞戞挸绉风换妯兼偘?AI 闁规亽鍔庨幃濠囧箣閺嵮冩瀫缂?
- 濞寸姴鎳忔晶鐣屾偘瀹€鈧垾妯尖偓瑙勭閳ь儸鍐╁€ゆ鐐舵硾閹风増顨ュ畝鍐闂侇偅妲掔欢?
- 缁绢収鍠曠换姘綇閹惧啿姣夌紒妤嬬畱閹?function_plan_schema.json 閻熸瑥瀚€?
- 缁绢収鍠曠换姘潰閵夆晩鈧?ID 闁哥儐鍨粩鎾箑瑜濈槐婵嬫焼閸喖甯冲〒姘箚缁傚棝宕橀懠顒傚磹
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from jsonschema import Draft202012Validator
from agents.Agent5_compose_plan.linker import run_linker_pass
from agents.Agent3b_compile_geometry_plan.standard_part_compiler import (
    _load_function_registry as _shared_load_function_registry,
)
from agents.common_utils import read_json as _read_json, write_json as _write_json, collect_defined_vars as _collect_defined_vars


def _shape_realization_path(run_dir: Path, *, round_index: int) -> Path:
    return run_dir / "planning" / f"shape_realization_round_{round_index}.json"


def _load_shape_realization_payload(run_dir: Path, *, round_index: int) -> Mapping[str, Any] | None:
    path = _shape_realization_path(run_dir, round_index=round_index)
    if not path.exists():
        return None
    payload = _read_json(path)
    return payload if isinstance(payload, Mapping) else None


def _normalize_transform_mm_payload(transform_raw: Any) -> Dict[str, Any]:
    tr_raw = transform_raw if isinstance(transform_raw, Mapping) else {}
    t_raw = tr_raw.get("translation") if isinstance(tr_raw.get("translation"), Mapping) else {}
    r_raw = tr_raw.get("rotation_rpy_deg") if isinstance(tr_raw.get("rotation_rpy_deg"), Mapping) else {}
    return {
        "translation": {
            "x": float(t_raw.get("x", 0.0)),
            "y": float(t_raw.get("y", 0.0)),
            "z": float(t_raw.get("z", 0.0)),
        },
        "rotation_rpy_deg": {
            "roll": float(r_raw.get("roll", 0.0)),
            "pitch": float(r_raw.get("pitch", 0.0)),
            "yaw": float(r_raw.get("yaw", 0.0)),
        },
    }


def _rotation_matrix_from_rpy_deg(rotation_raw: Any) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
    roll = math.radians(float(rotation.get("roll", 0.0)))
    pitch = math.radians(float(rotation.get("pitch", 0.0)))
    yaw = math.radians(float(rotation.get("yaw", 0.0)))

    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)

    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


def _apply_transform_mm_to_point(point_raw: Any, transform_raw: Any) -> Dict[str, float]:
    point = point_raw if isinstance(point_raw, Mapping) else {}
    transform = _normalize_transform_mm_payload(transform_raw)
    rotation = _rotation_matrix_from_rpy_deg(transform.get("rotation_rpy_deg"))
    x = float(point.get("x", 0.0))
    y = float(point.get("y", 0.0))
    z = float(point.get("z", 0.0))
    rx = rotation[0][0] * x + rotation[0][1] * y + rotation[0][2] * z
    ry = rotation[1][0] * x + rotation[1][1] * y + rotation[1][2] * z
    rz = rotation[2][0] * x + rotation[2][1] * y + rotation[2][2] * z
    translation = transform.get("translation") if isinstance(transform.get("translation"), Mapping) else {}
    return {
        "x": round(float(translation.get("x", 0.0)) + rx, 6),
        "y": round(float(translation.get("y", 0.0)) + ry, 6),
        "z": round(float(translation.get("z", 0.0)) + rz, 6),
    }


def _feature_matches_connection(feature: Mapping[str, Any], connection_id: str) -> bool:
    if not isinstance(connection_id, str) or not connection_id:
        return False
    for key in ("feature_id", "feature_group_id", "connection_id"):
        value = feature.get(key)
        if isinstance(value, str) and (value == connection_id or value.startswith(f"{connection_id}@")):
            return True
    return False


def _rewrite_fastener_initial_placements(
    placements: List[Dict[str, Any]],
    *,
    run_dir: Path,
    round_index: int,
    shape_payload: Mapping[str, Any] | None,
) -> List[Dict[str, Any]]:
    if not placements or not isinstance(shape_payload, Mapping):
        return list(placements)

    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return list(placements)

    try:
        knowledge_graph = _read_json(kg_path)
    except Exception:
        return list(placements)
    if not isinstance(knowledge_graph, Mapping):
        return list(placements)

    parts = shape_payload.get("parts")
    crs = knowledge_graph.get("connection_requirements")
    if not isinstance(parts, list) or not isinstance(crs, list):
        return list(placements)

    world_transform_by_component: Dict[str, Dict[str, Any]] = {}
    for placement in placements:
        cid = placement.get("component_id")
        if isinstance(cid, str) and cid:
            world_transform_by_component[cid] = _normalize_transform_mm_payload(placement.get("transform"))

    hole_features_by_component: Dict[str, List[Dict[str, Any]]] = {}
    part_by_component: Dict[str, Dict[str, Any]] = {}

    def _part_thickness_mm(part_payload: Mapping[str, Any] | None) -> float:
        if not isinstance(part_payload, Mapping):
            return 0.0
        candidates = []
        modeling_strategy = part_payload.get("modeling_strategy") if isinstance(part_payload.get("modeling_strategy"), Mapping) else {}
        parameter_values = modeling_strategy.get("parameter_values") if isinstance(modeling_strategy.get("parameter_values"), Mapping) else {}
        parameter_resolution = part_payload.get("parameter_resolution") if isinstance(part_payload.get("parameter_resolution"), Mapping) else {}
        thickness_resolution = parameter_resolution.get("thickness") if isinstance(parameter_resolution.get("thickness"), Mapping) else {}
        for value in (
            parameter_values.get("thickness"),
            thickness_resolution.get("value"),
            part_payload.get("thickness"),
        ):
            if isinstance(value, (int, float)) and float(value) > 0.0:
                candidates.append(float(value))
        return candidates[0] if candidates else 0.0

    def _resolved_hole_seed_world_point(
        seed_point_raw: Mapping[str, Any],
        *,
        anchor_component_id: str | None,
        anchor_feature: Mapping[str, Any],
    ) -> Dict[str, float]:
        local_point = {
            "x": float(seed_point_raw.get("x", 0.0)),
            "y": float(seed_point_raw.get("y", 0.0)),
            "z": float(seed_point_raw.get("z", 0.0)),
        }
        feature_anchor = anchor_feature.get("anchor") if isinstance(anchor_feature.get("anchor"), Mapping) else {}
        side_hint = str(feature_anchor.get("side_hint") or "").strip().upper()
        face_interface_id = str(feature_anchor.get("face_interface_id") or "").strip().lower()
        thickness_mm = _part_thickness_mm(part_by_component.get(anchor_component_id or ""))
        if thickness_mm > 0.0:
            half_thickness = 0.5 * thickness_mm
            if side_hint == "MAX" or face_interface_id.endswith("_max"):
                local_point["z"] = half_thickness
            elif side_hint == "MIN" or face_interface_id.endswith("_min"):
                local_point["z"] = -half_thickness
            elif face_interface_id.endswith("_center") or face_interface_id.endswith("_mid"):
                local_point["z"] = 0.0
        anchor_transform = world_transform_by_component.get(anchor_component_id or "", _normalize_transform_mm_payload({}))
        return _apply_transform_mm_to_point(local_point, anchor_transform)

    for part in parts:
        if not isinstance(part, Mapping):
            continue
        component_id = part.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue
        part_by_component[component_id] = dict(part)
        features = part.get("features")
        if not isinstance(features, list):
            continue
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            if str(feature.get("feature_type") or "").strip().lower() != "hole":
                continue
            hole_features_by_component.setdefault(component_id, []).append(dict(feature))

    fastener_bindings: Dict[str, Dict[str, Any]] = {}
    for cr in crs:
        if not isinstance(cr, Mapping):
            continue
        connection_id = cr.get("id")
        if not isinstance(connection_id, str) or not connection_id:
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str) and cid]
        decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else {}
        semantics = cr.get("connection_semantics") if isinstance(cr.get("connection_semantics"), Mapping) else {}

        preferred_components: List[str] = []
        for key in ("reference_component_id", "moving_component_id"):
            cid = semantics.get(key)
            if isinstance(cid, str) and cid and cid not in preferred_components:
                preferred_components.append(cid)

        fastener_ids: List[str] = []
        ref_fastener_id = decision.get("fastener_ref_component_id")
        if isinstance(ref_fastener_id, str) and ref_fastener_id:
            fastener_ids.append(ref_fastener_id)
        for cid in between:
            lowered = cid.lower()
            if cid in preferred_components or cid in fastener_ids:
                continue
            if any(token in lowered for token in ("fastener", "bolt", "nut", "washer", "screw")):
                fastener_ids.append(cid)
                continue
            if cid not in preferred_components:
                preferred_components.append(cid)

        for fastener_id in fastener_ids:
            if not isinstance(fastener_id, str) or not fastener_id:
                continue
            fastener_bindings.setdefault(
                fastener_id,
                {
                    "connection_id": connection_id,
                    "preferred_components": list(preferred_components),
                },
            )

    rewritten: List[Dict[str, Any]] = []
    for placement in placements:
        placement_out = dict(placement)
        component_id = placement.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            rewritten.append(placement_out)
            continue

        binding = fastener_bindings.get(component_id)
        if not isinstance(binding, Mapping):
            rewritten.append(placement_out)
            continue

        connection_id = binding.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id:
            rewritten.append(placement_out)
            continue

        anchor_component_id: str | None = None
        anchor_feature: Dict[str, Any] | None = None
        preferred_components = binding.get("preferred_components") if isinstance(binding.get("preferred_components"), list) else []
        for candidate_component_id in preferred_components:
            if not isinstance(candidate_component_id, str) or not candidate_component_id:
                continue
            for feature in hole_features_by_component.get(candidate_component_id, []):
                if _feature_matches_connection(feature, connection_id):
                    anchor_component_id = candidate_component_id
                    anchor_feature = dict(feature)
                    break
            if anchor_feature is not None:
                break

        if anchor_feature is None:
            for candidate_component_id, features in sorted(hole_features_by_component.items()):
                for feature in features:
                    if _feature_matches_connection(feature, connection_id):
                        anchor_component_id = candidate_component_id
                        anchor_feature = dict(feature)
                        break
                if anchor_feature is not None:
                    break

        if anchor_feature is None:
            rewritten.append(placement_out)
            continue

        seed_point = anchor_feature.get("seed_point_mm")
        if not isinstance(seed_point, Mapping):
            rewritten.append(placement_out)
            continue

        world_point = _resolved_hole_seed_world_point(
            seed_point,
            anchor_component_id=anchor_component_id,
            anchor_feature=anchor_feature,
        )
        anchor_transform = world_transform_by_component.get(anchor_component_id or "", _normalize_transform_mm_payload({}))
        transform = _normalize_transform_mm_payload(placement_out.get("transform"))
        current_translation = transform.get("translation") if isinstance(transform.get("translation"), Mapping) else {}
        current_x = float(current_translation.get("x", 0.0))
        current_y = float(current_translation.get("y", 0.0))
        current_z = float(current_translation.get("z", 0.0))
        preserve_authoritative_translation = (
            math.isclose(current_x, float(world_point.get("x", 0.0)), abs_tol=1e-3)
            and math.isclose(current_y, float(world_point.get("y", 0.0)), abs_tol=1e-3)
            and not (
                math.isclose(current_x, 0.0, abs_tol=1e-6)
                and math.isclose(current_y, 0.0, abs_tol=1e-6)
                and math.isclose(current_z, 0.0, abs_tol=1e-6)
            )
        )
        placement_source = "fastener_authoritative_initial_placement" if preserve_authoritative_translation else "fastener_hole_seed_fallback"
        if preserve_authoritative_translation:
            transform["translation"] = {
                "x": current_x,
                "y": current_y,
                "z": current_z,
            }
        else:
            transform["translation"] = world_point
            transform["rotation_rpy_deg"] = dict(
                anchor_transform.get("rotation_rpy_deg")
                if isinstance(anchor_transform.get("rotation_rpy_deg"), Mapping)
                else transform.get("rotation_rpy_deg", {})
            )
        placement_out["transform"] = transform

        metadata = dict(placement_out.get("metadata")) if isinstance(placement_out.get("metadata"), Mapping) else {}
        metadata.update({
            "placement_source": placement_source,
            "connection_id": connection_id,
            "anchor_component_id": anchor_component_id,
            "anchor_feature_id": anchor_feature.get("feature_id"),
            "authoritative_translation_preserved": preserve_authoritative_translation,
        })
        placement_out["metadata"] = metadata
        rewritten.append(placement_out)

    return rewritten


def _iter_interface_declarations(modeling_payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    declarations: List[Dict[str, Any]] = []

    top_level = modeling_payload.get("interface_declarations")
    if isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, Mapping):
                declarations.append(dict(item))

    parts = modeling_payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            per_part = part.get("interface_declarations")
            if isinstance(per_part, list):
                for item in per_part:
                    if isinstance(item, Mapping):
                        declarations.append(dict(item))

    return declarations


def _index_manifest_interfaces(interface_manifest: Mapping[str, Any]) -> Dict[tuple[str, str], Dict[str, Any]]:
    out: Dict[tuple[str, str], Dict[str, Any]] = {}
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue
        interfaces = comp.get("interfaces")
        if not isinstance(interfaces, list):
            continue
        for iface in interfaces:
            if not isinstance(iface, Mapping):
                continue
            interface_name = iface.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                out[(component_id, interface_name)] = dict(iface)
    return out


_INTERFACE_DECLARATION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "shaft_axis": ("bore_axis",),
    "fixation_req": ("planar_face",),
    "mounting_req": ("planar_face",),
    "mounting_req_drill_anchor": ("through_hole",),
}


def _iter_decl_interface_names(interface_name: str) -> Iterable[str]:
    if not isinstance(interface_name, str) or not interface_name:
        return
    yield interface_name
    for alias_name in _INTERFACE_DECLARATION_ALIASES.get(interface_name, ()):
        if isinstance(alias_name, str) and alias_name and alias_name != interface_name:
            yield alias_name


def _build_decl_index(
    modeling_semantics: Mapping[str, Any] | None,
    *,
    component_alias_map: Mapping[str, str] | None = None,
) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Build declaration index from modeling semantics interface_declarations."""
    decl_by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    alias_map = dict(component_alias_map or {})
    if isinstance(modeling_semantics, Mapping):
        for item in _iter_interface_declarations(modeling_semantics):
            comp_id = item.get("component_id")
            iface_name = item.get("interface_name")
            if not (isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name):
                continue
            interface_names = tuple(_iter_decl_interface_names(iface_name))
            for declared_name in interface_names:
                decl = dict(item)
                decl["interface_name"] = declared_name
                if declared_name == iface_name:
                    decl_by_key[(comp_id, declared_name)] = decl
                else:
                    decl_by_key.setdefault((comp_id, declared_name), decl)
            aliased_component_id = alias_map.get(comp_id)
            if isinstance(aliased_component_id, str) and aliased_component_id and aliased_component_id != comp_id:
                for declared_name in interface_names:
                    aliased_decl = dict(item)
                    aliased_decl["component_id"] = aliased_component_id
                    aliased_decl["interface_name"] = declared_name
                    decl_by_key.setdefault((aliased_component_id, declared_name), aliased_decl)
    return decl_by_key


def _index_manifest_interfaces_with_duplicates(
    interface_manifest: Mapping[str, Any],
) -> Tuple[Dict[tuple[str, str], Dict[str, Any]], List[Dict[str, Any]]]:
    """Build manifest index and detect duplicate interface entries."""
    out: Dict[tuple[str, str], Dict[str, Any]] = {}
    duplicates: List[Dict[str, Any]] = []
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return out, duplicates
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue
        interfaces = comp.get("interfaces")
        if not isinstance(interfaces, list):
            continue
        for iface in interfaces:
            if not isinstance(iface, Mapping):
                continue
            interface_name = iface.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                key = (component_id, interface_name)
                if key in out:
                    duplicates.append(
                        {
                            "code": "manifest_duplicate_interface",
                            "component_id": component_id,
                            "interface_name": interface_name,
                        }
                    )
                else:
                    out[key] = dict(iface)
    return out, duplicates


def _detect_manifest_declaration_drift(
    decl_map: Dict[tuple[str, str], Dict[str, Any]],
    manifest_map: Dict[tuple[str, str], Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compare manifest entries against declarations for drift.

    Returns:
        missing_decls: manifest interfaces with no corresponding declaration
        drift: role or recipe mismatches for shared keys
    """
    missing_decls: List[Dict[str, Any]] = []
    drift: List[Dict[str, Any]] = []

    for key in sorted(manifest_map.keys()):
        manifest_iface = manifest_map[key]
        decl = decl_map.get(key)
        if decl is None:
            missing_decls.append({"component_id": key[0], "interface_name": key[1]})
            continue

        decl_role = decl.get("semantic_role")
        man_role = manifest_iface.get("semantic_role")
        if isinstance(decl_role, str) and isinstance(man_role, str) and decl_role != man_role:
            drift.append(
                {
                    "component_id": key[0],
                    "interface_name": key[1],
                    "field": "semantic_role",
                    "declared": decl_role,
                    "manifest": man_role,
                }
            )

        decl_recipe = decl.get("recipe")
        man_recipe = manifest_iface.get("recipe")
        if isinstance(decl_recipe, Mapping) and isinstance(man_recipe, Mapping):
            if json.dumps(decl_recipe, sort_keys=True, ensure_ascii=False) != json.dumps(man_recipe, sort_keys=True, ensure_ascii=False):
                drift.append(
                    {
                        "component_id": key[0],
                        "interface_name": key[1],
                        "field": "recipe",
                        "message": "manifest recipe differs from declared recipe",
                    }
                )

    return missing_decls, drift


def _normalize_geometry_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v in {"planar", "plane", "flat"}:
        return "planar"
    if v in {"cylindrical", "cylinder", "cyl_shaft", "cyl_hole"}:
        return "cylindrical"
    if v in {"axis", "datum_axis"}:
        return "axis"
    if v in {"complex"}:
        return "complex"
    return v


def _manifest_iface_geometry_type(manifest_iface: Mapping[str, Any]) -> str | None:
    recipe = manifest_iface.get("recipe") if isinstance(manifest_iface.get("recipe"), Mapping) else None
    if isinstance(recipe, Mapping):
        gt = _normalize_geometry_type(recipe.get("geometry_type"))
        if gt:
            return gt
    # Fallback: map manifest type field
    t = manifest_iface.get("type")
    t_norm = _normalize_geometry_type(t)
    if t_norm in {"planar_mate"}:
        return "planar"
    if t_norm in {"cyl_shaft"}:
        return "cylindrical"
    if t_norm in {"datum_axis"}:
        return "axis"
    return None


def _declared_iface_geometry_type(decl: Mapping[str, Any]) -> str | None:
    gt = decl.get("geometry_type")
    out = _normalize_geometry_type(gt)
    if out:
        return out
    gt2 = decl.get("geom_type")
    return _normalize_geometry_type(gt2)


def _collect_interface_reference_evidence(
    *,
    merged_steps: List[Dict[str, Any]],
    assembly_patch: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []

    # 1) RESOLVE_INTERFACE steps (strongest evidence; carries recipe)
    for idx, step in enumerate(merged_steps):
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "RESOLVE_INTERFACE":
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"
        meta = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
        comp_id = meta.get("component_id")
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        iface_name = inputs.get("interface_name")
        recipe = inputs.get("recipe") if isinstance(inputs.get("recipe"), Mapping) else None
        if isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name:
            evidence.append(
                {
                    "component_id": comp_id,
                    "interface_name": iface_name,
                    "source": "resolve_step",
                    "step_id": sid,
                    "recipe_geometry_type": _normalize_geometry_type(recipe.get("geometry_type")) if isinstance(recipe, Mapping) else None,
                }
            )

    # 2) interface_ref objects in step inputs
    def _scan_inputs(obj: Any, step_id: str, path: str) -> None:
        if isinstance(obj, Mapping):
            if path.endswith("interface_ref"):
                component_id = obj.get("component_id")
                interface_name = obj.get("name") if isinstance(obj.get("name"), str) else obj.get("interface_name")
                if isinstance(component_id, str) and component_id and isinstance(interface_name, str) and interface_name:
                    evidence.append(
                        {
                            "component_id": component_id,
                            "interface_name": interface_name,
                            "source": "input_interface_ref",
                            "step_id": step_id,
                            "path": path,
                            "declared_geometry_type": _normalize_geometry_type(obj.get("geometry_type") or obj.get("geom_type")),
                        }
                    )
            for k, v in obj.items():
                if isinstance(k, str):
                    _scan_inputs(v, step_id, f"{path}.{k}")
            return
        if isinstance(obj, list):
            for idx, item in enumerate(obj):
                _scan_inputs(item, step_id, f"{path}[{idx}]")

    for idx, step in enumerate(merged_steps):
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"
        inputs = step.get("inputs")
        if isinstance(inputs, Mapping):
            _scan_inputs(inputs, sid, "inputs")

    # 3) Assembly constraints/unresolved endpoints (Agent4 output)
    for key in ("constraints", "unresolved"):
        rows = assembly_patch.get(key)
        if not isinstance(rows, list):
            continue
        for ridx, rel in enumerate(rows):
            if not isinstance(rel, Mapping):
                continue
            rel_id = rel.get("relation_id") if isinstance(rel.get("relation_id"), str) else f"<{key}:{ridx}>"
            for endpoint_name in ("from", "to"):
                endpoint = rel.get(endpoint_name)
                if not isinstance(endpoint, Mapping):
                    continue
                component_id = endpoint.get("component_id")
                interface_name = endpoint.get("interface_id")
                if isinstance(component_id, str) and component_id and isinstance(interface_name, str) and interface_name:
                    evidence.append(
                        {
                            "component_id": component_id,
                            "interface_name": interface_name,
                            "source": "assembly_endpoint",
                            "relation_id": rel_id,
                            "endpoint": endpoint_name,
                        }
                    )

    return evidence


def _validate_interface_contract_closure(
    *,
    run_dir: Path,
    round_index: int,
    interface_manifest: Mapping[str, Any] | None,
    modeling_semantics: Mapping[str, Any] | None,
    merged_steps: List[Dict[str, Any]],
    assembly_patch: Mapping[str, Any],
    component_alias_map: Mapping[str, str] | None = None,
) -> None:
    errors: List[Dict[str, Any]] = []

    if not isinstance(interface_manifest, Mapping):
        errors.append(
            {
                "code": "interface_manifest_missing",
                "message": "interface_manifest_round_N.json is required for interface contract closure checks",
            }
        )

    decl_by_key = _build_decl_index(modeling_semantics, component_alias_map=component_alias_map)
    if not isinstance(modeling_semantics, Mapping):
        errors.append(
            {
                "code": "interface_declarations_missing",
                "message": "geometry_semantics_modeling_round_N.json is required to validate interface_declarations vs interface_manifest",
            }
        )

    manifest_by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    if isinstance(interface_manifest, Mapping):
        manifest_by_key = _index_manifest_interfaces(interface_manifest)

    # 1) Manifest must not drift away from declarations (recipe/role authority)
    missing_decls, drift_items = _detect_manifest_declaration_drift(decl_by_key, manifest_by_key)
    for md in missing_decls:
        errors.append(
            {
                "code": "manifest_interface_missing_declaration",
                "message": "interface_manifest contains an interface not present in interface_declarations",
                "component_id": md["component_id"],
                "interface_name": md["interface_name"],
            }
        )
    for di in drift_items:
        if di["field"] == "semantic_role":
            errors.append(
                {
                    "code": "manifest_declaration_role_mismatch",
                    "message": "semantic_role mismatch between interface_declarations and interface_manifest",
                    "component_id": di["component_id"],
                    "interface_name": di["interface_name"],
                    "declared": di["declared"],
                    "manifest": di["manifest"],
                }
            )
        elif di["field"] == "recipe":
            errors.append(
                {
                    "code": "manifest_declaration_recipe_mismatch",
                    "message": "recipe mismatch between interface_declarations and interface_manifest",
                    "component_id": di["component_id"],
                    "interface_name": di["interface_name"],
                }
            )

    # 2) Assembly references must be resolvable via BOTH declarations and manifest.
    #    HARD CHECK: referenced interface geometry_type must match across:
    #    - Agent2 interface_declarations (authority)
    #    - Agent3b interface_manifest recipe.geometry_type
    #    - Any RESOLVE_INTERFACE step recipe.geometry_type in merged plan
    evidence = _collect_interface_reference_evidence(merged_steps=merged_steps, assembly_patch=assembly_patch)
    referenced = {(e.get("component_id"), e.get("interface_name")) for e in evidence if isinstance(e.get("component_id"), str) and isinstance(e.get("interface_name"), str)}

    missing_manifest_reported: set[tuple[str, str]] = set()
    missing_decl_reported: set[tuple[str, str]] = set()
    type_mismatch_reported: set[tuple[str, str, str, str]] = set()
    recipe_mismatch_reported: set[tuple[str, str, str, str]] = set()
    alias_map = dict(component_alias_map or {})

    def _resolve_lookup_key(component_id: str, interface_name: str) -> tuple[tuple[str, str], str | None]:
        primary = (component_id, interface_name)
        if primary in manifest_by_key or primary in decl_by_key:
            return primary, None
        aliased = alias_map.get(component_id)
        if isinstance(aliased, str) and aliased:
            fallback = (aliased, interface_name)
            if fallback in manifest_by_key or fallback in decl_by_key:
                return fallback, aliased
        return primary, None

    for entry in evidence:
        if not isinstance(entry, Mapping):
            continue
        comp_id = entry.get("component_id")
        iface_name = entry.get("interface_name")
        if not isinstance(comp_id, str) or not comp_id or not isinstance(iface_name, str) or not iface_name:
            continue

        key, resolved_component_id = _resolve_lookup_key(comp_id, iface_name)
        man = manifest_by_key.get(key)
        decl = decl_by_key.get(key)

        if man is None and key not in missing_manifest_reported:
            missing_manifest_reported.add(key)
            errors.append(
                {
                    "code": "assembly_interface_ref_not_in_manifest",
                    "message": "Assembly/plan references an interface not present in interface_manifest",
                    "component_id": comp_id,
                    "resolved_component_id": key[0],
                    "interface_name": iface_name,
                    "source": entry.get("source"),
                    "step_id": entry.get("step_id"),
                    "path": entry.get("path"),
                    "relation_id": entry.get("relation_id"),
                    "endpoint": entry.get("endpoint"),
                }
            )
        if decl is None and key not in missing_decl_reported:
            missing_decl_reported.add(key)
            errors.append(
                {
                    "code": "assembly_interface_ref_not_in_declarations",
                    "message": "Assembly/plan references an interface not present in interface_declarations",
                    "component_id": comp_id,
                    "resolved_component_id": key[0],
                    "interface_name": iface_name,
                    "source": entry.get("source"),
                }
            )

        # Only type-check when both sides exist.
        if man is None or decl is None:
            continue

        expected_gt = _declared_iface_geometry_type(decl)
        manifest_gt = _manifest_iface_geometry_type(man)

        if expected_gt and manifest_gt and expected_gt != manifest_gt:
            sig = (key[0], iface_name, expected_gt, manifest_gt)
            if sig not in type_mismatch_reported:
                type_mismatch_reported.add(sig)
                errors.append(
                    {
                        "code": "interface_geometry_type_mismatch",
                        "message": "Referenced interface geometry_type mismatch between declarations and manifest",
                        "component_id": comp_id,
                        "resolved_component_id": key[0],
                        "interface_name": iface_name,
                        "declared_geometry_type": expected_gt,
                        "manifest_geometry_type": manifest_gt,
                    }
                )

        # For RESOLVE_INTERFACE steps, enforce step recipe.geometry_type matches manifest.
        if entry.get("source") == "resolve_step":
            step_gt = _normalize_geometry_type(entry.get("recipe_geometry_type"))
            if step_gt and manifest_gt and step_gt != manifest_gt:
                sig = (key[0], iface_name, step_gt, manifest_gt)
                if sig not in recipe_mismatch_reported:
                    recipe_mismatch_reported.add(sig)
                    errors.append(
                        {
                            "code": "resolve_interface_recipe_geometry_type_mismatch",
                            "message": "RESOLVE_INTERFACE step recipe.geometry_type does not match interface_manifest recipe.geometry_type",
                            "component_id": comp_id,
                            "resolved_component_id": key[0],
                            "interface_name": iface_name,
                            "step_id": entry.get("step_id"),
                            "step_geometry_type": step_gt,
                            "manifest_geometry_type": manifest_gt,
                        }
                    )

        # For interface_ref objects that carry an explicit geometry_type, enforce it matches manifest.
        if entry.get("source") == "input_interface_ref":
            ref_gt = _normalize_geometry_type(entry.get("declared_geometry_type"))
            if ref_gt and manifest_gt and ref_gt != manifest_gt:
                sig = (key[0], iface_name, ref_gt, manifest_gt)
                if sig not in recipe_mismatch_reported:
                    recipe_mismatch_reported.add(sig)
                    errors.append(
                        {
                            "code": "interface_ref_geometry_type_mismatch",
                            "message": "interface_ref.geometry_type does not match interface_manifest recipe.geometry_type",
                            "component_id": comp_id,
                            "resolved_component_id": key[0],
                            "interface_name": iface_name,
                            "step_id": entry.get("step_id"),
                            "path": entry.get("path"),
                            "interface_ref_geometry_type": ref_gt,
                            "manifest_geometry_type": manifest_gt,
                        }
                    )

    # Keep a minimal summary-level check to ensure we have at least one reference.
    # (If there are truly no references, downstream execution becomes non-deterministic.)
    if not referenced:
        errors.append(
            {
                "code": "interface_reference_missing",
                "message": "No interface references detected in merged plan/assembly patch; deterministic interface resolution evidence is required",
            }
        )

    if not errors:
        return

    report = {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "agent5_interface_contract_gate",
            "round_index": round_index,
        },
        "summary": {
            "error_count": len(errors),
            "valid": False,
        },
        "errors": errors,
    }
    out_path = run_dir / "planning" / "errors" / "interface_contract_consistency.json"
    _write_json(out_path, report)
    raise ValueError(
        "Agent5 interface contract gate blocked plan composition. "
        f"See: {out_path}"
    )


def _validate_interface_contract_consistency(
    *,
    run_dir: Path,
    round_index: int,
    modeling_semantics: Mapping[str, Any] | None,
    interface_manifest: Mapping[str, Any] | None,
    component_alias_map: Mapping[str, str] | None = None,
) -> None:
    if modeling_semantics is None or interface_manifest is None:
        return

    decl_map = _build_decl_index(modeling_semantics, component_alias_map=component_alias_map)
    manifest_map, duplicates = _index_manifest_interfaces_with_duplicates(interface_manifest)

    errors: List[Dict[str, Any]] = []
    errors.extend(duplicates)

    missing_decls, drift = _detect_manifest_declaration_drift(decl_map, manifest_map)
    if missing_decls:
        errors.append(
            {
                "code": "manifest_interface_missing_declaration",
                "message": "Interface manifest contains interfaces not declared by Agent2 modeling semantics",
                "missing": missing_decls[:200],
                "missing_count": len(missing_decls),
            }
        )

    if drift:
        errors.append(
            {
                "code": "interface_contract_drift",
                "message": "Detected drift between Agent2 interface_declarations and Agent3b interface_manifest",
                "drift": drift[:200],
                "drift_count": len(drift),
            }
        )

    if errors:
        report = {
            "metadata": {
                "schema_version": "1.0",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": "agent5_interface_contract_gate",
                "round_index": round_index,
            },
            "summary": {
                "declared_count": len(decl_map),
                "manifest_count": len(manifest_map),
                "error_count": len(errors),
            },
            "errors": errors,
        }
        out_path = run_dir / "planning" / "errors" / "interface_contract_consistency.json"
        _write_json(out_path, report)
        raise ValueError(
            "Agent5 quality gate blocked plan composition due to interface contract drift. "
            f"See: {out_path}"
        )


def _gate_hole_orientation_plane_requirement(
    *,
    run_dir: Path,
    round_index: int,
    merged_steps: List[Dict[str, Any]],
) -> None:
    """Hard gate: HOLE_SIMPLE on a planar interface must use face_id, not plane_id-only."""

    step_by_id: Dict[str, Dict[str, Any]] = {}
    for s in merged_steps:
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            step_by_id[sid] = s

    def _find_upstream_resolve_step(start_step: Mapping[str, Any], max_hops: int = 4) -> Mapping[str, Any] | None:
        frontier: List[Mapping[str, Any]] = [start_step]
        visited: set[str] = set()
        hops = 0
        while frontier and hops < max_hops:
            nxt: List[Mapping[str, Any]] = []
            for cur in frontier:
                deps = cur.get("depends_on")
                if not isinstance(deps, list):
                    continue
                for dep_id in deps:
                    if not isinstance(dep_id, str) or not dep_id:
                        continue
                    if dep_id in visited:
                        continue
                    visited.add(dep_id)
                    dep = step_by_id.get(dep_id)
                    if not isinstance(dep, Mapping):
                        continue
                    if dep.get("function") == "RESOLVE_INTERFACE":
                        return dep
                    nxt.append(dep)
            frontier = nxt
            hops += 1
        return None

    errors: List[Dict[str, Any]] = []
    for idx, step in enumerate(merged_steps):
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "HOLE_SIMPLE":
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"

        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        uses_face = ("face_id" in inputs) and (inputs.get("face_id") is not None)
        uses_plane = ("plane_id" in inputs) and (inputs.get("plane_id") is not None)

        if not uses_face and not uses_plane:
            continue

        resolve_step = _find_upstream_resolve_step(step)
        if resolve_step is None:
            continue

        r_inputs = resolve_step.get("inputs") if isinstance(resolve_step.get("inputs"), Mapping) else {}
        recipe = r_inputs.get("recipe") if isinstance(r_inputs.get("recipe"), Mapping) else {}
        gt = _normalize_geometry_type(recipe.get("geometry_type"))

        if gt == "planar" and uses_plane and (not uses_face):
            errors.append(
                {
                    "code": "hole_planar_must_use_face",
                    "message": "HOLE_SIMPLE anchored to planar interface must use face_id, not plane_id-only",
                    "hole_step_id": sid,
                    "resolve_step_id": resolve_step.get("id"),
                    "interface_name": r_inputs.get("interface_name"),
                    "recipe_geometry_type": gt,
                    "hole_inputs": {k: inputs.get(k) for k in ("face_id", "plane_id", "center_mm", "diameter_mm", "extent", "depth_mm") if k in inputs},
                }
            )

    if not errors:
        return

    report = {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "agent5_hole_orientation_gate",
            "round_index": round_index,
        },
        "summary": {
            "error_count": len(errors),
            "valid": False,
        },
        "errors": errors,
    }
    out_path = run_dir / "planning" / "errors" / "hole_orientation_gate.json"
    _write_json(out_path, report)
    raise ValueError(
        "Agent5 hole orientation gate blocked plan composition. "
        f"See: {out_path}"
    )


def _validate_json(payload: Dict[str, Any], schema_path: Path) -> None:
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return

    lines = ["Function plan validation failed:"]
    for err in errors[:30]:
        path = ".".join([str(p) for p in err.path]) if err.path else "<root>"
        lines.append(f"- {path}: {err.message}")
    if len(errors) > 30:
        lines.append(f"... (+{len(errors) - 30} more)")
    raise ValueError("\n".join(lines))


def _ensure_unique_step_ids_between(
    base_steps: List[Dict[str, Any]],
    other_steps: List[Dict[str, Any]],
    *,
    prefix: str,
) -> List[Dict[str, Any]]:
    used: set[str] = set()
    for s in base_steps:
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            used.add(sid)

    rename_map: Dict[str, str] = {}

    def alloc(new_id: str) -> str:
        if new_id not in used:
            used.add(new_id)
            return new_id
        i = 2
        while f"{new_id}_{i}" in used:
            i += 1
        nid = f"{new_id}_{i}"
        used.add(nid)
        return nid

    out_steps: List[Dict[str, Any]] = []
    for step in other_steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            out_steps.append(step)
            continue

        if sid in used:
            new_id = alloc(f"{prefix}_{sid}")
            rename_map[sid] = new_id
            step = dict(step)
            step["id"] = new_id
        out_steps.append(step)

    if rename_map:
        # Update depends_on within steps, in case they reference each other.
        updated: List[Dict[str, Any]] = []
        for step in out_steps:
            deps = step.get("depends_on")
            if isinstance(deps, list):
                new_deps: List[Any] = []
                changed = False
                for d in deps:
                    if isinstance(d, str) and d in rename_map:
                        new_deps.append(rename_map[d])
                        changed = True
                    else:
                        new_deps.append(d)
                if changed:
                    step = dict(step)
                    step["depends_on"] = new_deps
            updated.append(step)
        out_steps = updated

    return out_steps


def _last_step_id(steps: List[Dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _dedupe_depends_on(step: Dict[str, Any]) -> Dict[str, Any]:
    deps = step.get("depends_on")
    if not isinstance(deps, list):
        return step
    seen: set[str] = set()
    new_deps: List[Any] = []
    for dep in deps:
        if isinstance(dep, str):
            if dep in seen:
                continue
            seen.add(dep)
        new_deps.append(dep)
    out = dict(step)
    out["depends_on"] = new_deps
    return out


def _add_var_based_dependencies(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    placeholder_re = re.compile(r"\$\{([^}]+)\}")

    def _scan_placeholders(obj: Any) -> List[str]:
        found: List[str] = []
        if isinstance(obj, Mapping):
            for value in obj.values():
                found.extend(_scan_placeholders(value))
        elif isinstance(obj, list):
            for value in obj:
                found.extend(_scan_placeholders(value))
        elif isinstance(obj, str):
            found.extend([m for m in placeholder_re.findall(obj) if isinstance(m, str) and m])
        return found

    producers: Dict[str, List[str]] = {}
    for step in steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        capture = step.get("capture")
        if isinstance(capture, Mapping):
            vars_map = capture.get("vars")
            if isinstance(vars_map, Mapping):
                for var_name in vars_map.keys():
                    if isinstance(var_name, str) and var_name:
                        producers.setdefault(var_name, []).append(sid)
        outputs = step.get("outputs")
        if isinstance(outputs, Mapping):
            for var_name in outputs.keys():
                if isinstance(var_name, str) and var_name:
                    producers.setdefault(var_name, []).append(sid)

    out_steps: List[Dict[str, Any]] = []
    for step in steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            out_steps.append(step)
            continue

        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        vars_used = _scan_placeholders(inputs)

        deps = step.get("depends_on")
        existing_deps: List[str] = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
        seen = set(existing_deps)
        new_deps = list(existing_deps)

        for var_name in vars_used:
            source_steps = producers.get(var_name, [])
            if not source_steps:
                continue
            # Only auto-add dependency for single-producer variables.
            # Multi-producer variables (e.g. body_id refreshed after each
            # hole) are ordered by explicit depends_on from 3b; blindly
            # picking the first producer creates cross-chain cycles after
            # symmetric folding.
            if len(source_steps) != 1:
                continue
            producer_id = source_steps[0]
            if producer_id == sid:
                continue
            if producer_id in seen:
                continue
            new_deps.append(producer_id)
            seen.add(producer_id)

        updated = dict(step)
        updated["depends_on"] = new_deps
        out_steps.append(updated)

    return out_steps


def _deterministic_topological_sort(
    steps: List[Dict[str, Any]],
    *,
    phase_rank_by_id: Mapping[str, int],
) -> List[Dict[str, Any]]:
    id_to_step: Dict[str, Dict[str, Any]] = {}
    original_index: Dict[str, int] = {}

    for idx, step in enumerate(steps):
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"Agent5 compose: step at index {idx} missing valid id")
        if sid in id_to_step:
            raise ValueError(f"Agent5 compose: duplicate step id detected before topo sort: {sid}")
        id_to_step[sid] = _dedupe_depends_on(step)
        original_index[sid] = idx

    outgoing: Dict[str, List[str]] = {sid: [] for sid in id_to_step.keys()}
    indegree: Dict[str, int] = {sid: 0 for sid in id_to_step.keys()}

    for sid, step in id_to_step.items():
        deps = step.get("depends_on")
        if not isinstance(deps, list):
            continue
        seen: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str):
                continue
            if dep in seen:
                continue
            seen.add(dep)
            if dep not in id_to_step:
                raise ValueError(
                    "Agent5 compose: depends_on references unknown step id. "
                    f"step='{sid}', missing_dep='{dep}'"
                )
            outgoing[dep].append(sid)
            indegree[sid] += 1

    heap: List[Tuple[int, int, str]] = []
    for sid, deg in indegree.items():
        if deg == 0:
            heapq.heappush(heap, (int(phase_rank_by_id.get(sid, 99)), int(original_index[sid]), sid))

    sorted_ids: List[str] = []
    while heap:
        _, _, sid = heapq.heappop(heap)
        sorted_ids.append(sid)
        for nxt in outgoing.get(sid, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, (int(phase_rank_by_id.get(nxt, 99)), int(original_index[nxt]), nxt))

    if len(sorted_ids) != len(id_to_step):
        unresolved = [sid for sid, deg in indegree.items() if deg > 0]
        raise ValueError(
            "Agent5 compose: dependency cycle detected during topo sort. "
            f"involved_steps={unresolved}"
        )

    return [id_to_step[sid] for sid in sorted_ids]


def _assert_no_unresolved_placeholders(steps: List[Dict[str, Any]]) -> None:
    _lint_unresolved_placeholders(steps)
    _lint_unresolved_execution_id_placeholders(steps)


def _lint_unresolved_placeholders(steps: List[Dict[str, Any]]) -> None:
    import re

    defined = _collect_defined_vars(steps)
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    suffix_re = re.compile(r"_(distance|width|height|thickness|length)$")

    def _hint(var_name: str) -> str:
        if var_name.endswith("_distance"):
            return "Hint: for wheels use width; for shafts use length; for plates use thickness."
        if var_name.endswith("_width"):
            return "Hint: wheels typically use width for extrude distance."
        if var_name.endswith("_length"):
            return "Hint: shafts typically use length for extrude distance."
        if var_name.endswith("_thickness"):
            return "Hint: plates typically use thickness for extrude distance."
        if var_name.endswith("_height"):
            return "Hint: check if height should map to extrude distance."
        return "Hint: map this placeholder to a concrete dimension."

    def _scan(obj: Any, path: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_path = f"{path}.{key}" if path else str(key)
                found.extend(_scan(value, key_path))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                found.extend(_scan(value, f"{path}[{idx}]"))
        elif isinstance(obj, str):
            for match in placeholder_re.findall(obj):
                found.append((path, match))
        return found

    for step in steps:
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            continue
        matches = _scan(inputs, "inputs")
        for field_path, var_name in matches:
            if var_name in defined:
                continue
            if not suffix_re.search(var_name):
                continue
            step_id = step.get("id")
            func_name = step.get("function")
            unresolved = f"${{{var_name}}}"
            raise ValueError(
                "Unresolved placeholder detected in plan: "
                f"step='{step_id}', function='{func_name}', field='{field_path}', value='{unresolved}'. "
                f"{_hint(var_name)}"
            )


def _lint_no_index_pointer_captures(steps: List[Dict[str, Any]]) -> None:
    """Block non-deterministic JSON pointer captures like "/body_ids/0".

    P0 stability rule: array-index selection is forbidden because it stops being
    stable as soon as a component gains multiple bodies/occurrences.
    """

    index_segment_re = re.compile(r"/(\d+)(/|$)")

    for step in steps:
        if not isinstance(step, dict):
            continue
        capture = step.get("capture")
        if not isinstance(capture, Mapping):
            continue
        vars_map = capture.get("vars")
        if not isinstance(vars_map, Mapping):
            continue
        for var_name, path in vars_map.items():
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            if index_segment_re.search(path):
                raise ValueError(
                    "Index-based JSON pointer capture is forbidden (P0): "
                    f"step='{step.get('id')}', function='{step.get('function')}', var='{var_name}', capture='{path}'. "
                    "Hint: capture stable ids directly (e.g. body_id/occurrence_id) and reference those vars."
                )


def _lint_unresolved_execution_id_placeholders(steps: List[Dict[str, Any]]) -> None:
    """Fail fast if *_component_id/*_occurrence_id/*_body_id placeholders are not defined.

    Rationale: These ids are required for deterministic downstream execution (assembly/interface
    resolution). Leaving them unresolved would only fail later in Fusion execution.
    """

    import re

    defined = _collect_defined_vars(steps)
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    must_exist_suffixes = ("_component_id", "_occurrence_id", "_body_id")

    def _scan(obj: Any, path: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_path = f"{path}.{key}" if path else str(key)
                found.extend(_scan(value, key_path))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                found.extend(_scan(value, f"{path}[{idx}]"))
        elif isinstance(obj, str):
            for match in placeholder_re.findall(obj):
                found.append((path, match))
        return found

    for step in steps:
        if not isinstance(step, dict):
            continue
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            continue

        matches = _scan(inputs, "inputs")
        for field_path, var_name in matches:
            if not isinstance(var_name, str):
                continue
            if not var_name.endswith(must_exist_suffixes):
                continue
            if var_name in defined:
                continue
            raise ValueError(
                "Unresolved execution id placeholder detected in plan: "
                f"step='{step.get('id')}', function='{step.get('function')}', field='{field_path}', value='${{{var_name}}}'. "
                "Hint: ensure this id is captured (CREATE_COMPONENT / stdpart insert / GET_SINGLE_BODY_ID) before it is referenced."
            )


def _compress_redundant_activate_steps(steps: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Remove redundant consecutive ACTIVATE_COMPONENT steps safely.

    Only removes a step when ALL are true:
    - function is ACTIVATE_COMPONENT
    - current active component is already the same component_id
    - step has no capture/outputs side effects
    Then rewires depends_on references from removed step id to kept step id.
    """

    if not isinstance(steps, list) or not steps:
        return list(steps), {"removed_count": 0, "rewired_dependency_edges": 0}

    kept: List[Dict[str, Any]] = []
    removed_to_kept: Dict[str, str] = {}
    active_component: str | None = None
    active_source_step_id: str | None = None

    def _activate_target(step: Mapping[str, Any]) -> str | None:
        if step.get("function") != "ACTIVATE_COMPONENT":
            return None
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else None
        if not isinstance(inputs, Mapping):
            return None
        cid = inputs.get("component_id")
        return cid if isinstance(cid, str) and cid else None

    for step in steps:
        if not isinstance(step, Mapping):
            continue

        current = dict(step)
        current_id = current.get("id") if isinstance(current.get("id"), str) else None
        current_target = _activate_target(current)

        if current_target:
            has_capture = isinstance(current.get("capture"), Mapping) and bool(current.get("capture"))
            has_outputs = isinstance(current.get("outputs"), Mapping) and bool(current.get("outputs"))
            current_id = current.get("id") if isinstance(current.get("id"), str) else None

            if (
                active_component == current_target
                and active_source_step_id
                and current_id
                and not has_capture
                and not has_outputs
            ):
                removed_to_kept[current_id] = active_source_step_id
                continue

            if current_id:
                active_component = current_target
                active_source_step_id = current_id

        kept.append(current)

    if not removed_to_kept:
        return kept, {"removed_count": 0, "rewired_dependency_edges": 0}

    rewired_edges = 0
    for step in kept:
        deps = step.get("depends_on")
        if not isinstance(deps, list) or not deps:
            continue

        new_deps: List[str] = []
        for dep in deps:
            if not isinstance(dep, str):
                continue
            target = dep
            seen: set[str] = set()
            while target in removed_to_kept and target not in seen:
                seen.add(target)
                target = removed_to_kept[target]
            if target != dep:
                rewired_edges += 1
            if target not in new_deps:
                new_deps.append(target)
        step["depends_on"] = new_deps

    return kept, {
        "removed_count": len(removed_to_kept),
        "rewired_dependency_edges": rewired_edges,
        "removed_step_ids": sorted(removed_to_kept.keys()),
    }


def _load_function_registry() -> Dict[str, Any]:
    return _shared_load_function_registry()


def _load_initial_placements(run_dir: Path, *, round_index: int) -> List[Dict[str, Any]]:
    payload = _load_shape_realization_payload(run_dir, round_index=round_index)
    if not isinstance(payload, Mapping):
        return []
    placements = payload.get("initial_placements")
    if not isinstance(placements, list):
        return []
    normalized = [dict(p) for p in placements if isinstance(p, Mapping)]
    return _rewrite_fastener_initial_placements(
        normalized,
        run_dir=run_dir,
        round_index=round_index,
        shape_payload=payload,
    )


_DEFINITION_SHARING_BLOCKED_TYPES = {
    "arm",
    "axle",
    "bearing",
    "fastener",
    "hub",
    "rim",
    "spacer",
    "tire",
    "wheel",
}

_DEFINITION_SHARING_BLOCKED_PART_KINDS = {
    "bearing",
    "fastener_bundle",
}

_DEFINITION_SHARING_BLOCKED_ID_PATTERNS = (
    re.compile(r"^wheel_\d+$"),
    re.compile(r"^wheel_arm_\d+$"),
    re.compile(r"^wheel_\d+_(axle|bearing_\d+|fastener_set|hub|rim|spacer|tire)$"),
)


def _is_definition_sharing_blocked_component(component: Mapping[str, Any] | str | None) -> bool:
    cid: str | None = None
    if isinstance(component, Mapping):
        raw_id = component.get("id")
        cid = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
        ctype = component.get("type")
        if isinstance(ctype, str) and ctype.strip().lower() in _DEFINITION_SHARING_BLOCKED_TYPES:
            return True
        part_kind = component.get("part_kind")
        if isinstance(part_kind, str) and part_kind.strip().lower() in _DEFINITION_SHARING_BLOCKED_PART_KINDS:
            return True
        modeling_policy = component.get("modeling_policy")
        if isinstance(modeling_policy, str) and modeling_policy.strip().lower() == "container_only":
            return True
        if bool(component.get("is_container_only")):
            return True
    elif isinstance(component, str):
        cid = component.strip() or None

    if not cid:
        return False
    return any(pattern.fullmatch(cid) for pattern in _DEFINITION_SHARING_BLOCKED_ID_PATTERNS)


def _load_instancing_map(run_dir: Path) -> Dict[str, str]:
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return {}
    try:
        payload = _read_json(kg_path)
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    out: Dict[str, str] = {}
    blocked_component_ids: set[str] = set()

    components = payload.get("components")
    if isinstance(components, list):
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str) or not cid:
                continue
            if _is_definition_sharing_blocked_component(comp):
                blocked_component_ids.add(cid)
                continue

            proto: str | None = None
            instanced_from = comp.get("instanced_from")
            definition_id = comp.get("definition_id")
            if isinstance(instanced_from, str) and instanced_from and instanced_from != cid:
                proto = instanced_from
            elif isinstance(definition_id, str) and definition_id and definition_id != cid:
                proto = definition_id

            if (
                isinstance(proto, str)
                and proto
                and cid not in blocked_component_ids
                and not _is_definition_sharing_blocked_component(proto)
            ):
                out[cid] = proto

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                continue
            ptype = pattern.get("type")
            if not (isinstance(ptype, str) and ptype.strip().lower() == "rotational_symmetry"):
                continue
            instances = pattern.get("instances") if isinstance(pattern.get("instances"), list) else pattern.get("component_ids")
            if not isinstance(instances, list):
                continue
            prototype = pattern.get("prototype") if isinstance(pattern.get("prototype"), str) else None
            if not (isinstance(prototype, str) and prototype):
                prototype = next(
                    (
                        instance_id
                        for instance_id in instances
                        if isinstance(instance_id, str) and instance_id
                    ),
                    None,
                )
            if not isinstance(prototype, str) or not prototype:
                continue
            if _is_definition_sharing_blocked_component(prototype):
                continue
            for instance_id in instances:
                if not isinstance(instance_id, str) or not instance_id or instance_id == prototype:
                    continue
                if instance_id in blocked_component_ids or _is_definition_sharing_blocked_component(instance_id):
                    continue
                out.setdefault(instance_id, prototype)

    return out


def _load_connection_canonical_map(run_dir: Path, *, instancing_map: Mapping[str, str]) -> Dict[str, str]:
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return {}
    try:
        payload = _read_json(kg_path)
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}

    reqs = payload.get("connection_requirements")
    if not isinstance(reqs, list):
        return {}

    grouped: Dict[Tuple[str, ...], List[str]] = {}
    for req in reqs:
        if not isinstance(req, Mapping):
            continue
        rid = req.get("id")
        between = req.get("between")
        if not (isinstance(rid, str) and rid and isinstance(between, list) and between):
            continue

        canonical_between: List[str] = []
        for cid in between:
            if not isinstance(cid, str) or not cid:
                continue
            canonical_between.append(instancing_map.get(cid, cid))
        if not canonical_between:
            continue

        signature = tuple(sorted(canonical_between))
        grouped.setdefault(signature, []).append(rid)

    alias_map: Dict[str, str] = {}
    for ids in grouped.values():
        if len(ids) <= 1:
            continue
        canonical_id = sorted(ids)[0]
        for rid in ids:
            if rid != canonical_id:
                alias_map[rid] = canonical_id
    return alias_map


_REWRITE_BLOCKED_FIELDS = {
    "parent_component_id",
    "occurrence_name",
    "occurrence_id",
}


def _is_rewrite_allowed_field(*, field_name: str | None, step_function: str | None) -> bool:
    if not isinstance(field_name, str) or not field_name:
        return False
    if field_name in _REWRITE_BLOCKED_FIELDS:
        return False
    if step_function in {"ENSURE_OCCURRENCE_R1", "CREATE_COMPONENT"} and field_name == "parent_component_id":
        return False

    if field_name in {"component_id", "body_id", "component_ids", "body_ids"}:
        return True
    if field_name.endswith("_component_id") or field_name.endswith("_body_id"):
        return True
    return False


def _rewrite_placeholders_obj(
    obj: Any,
    var_map: Mapping[str, str],
    *,
    step_function: str | None = None,
    field_name: str | None = None,
) -> Any:
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            inner = obj[2:-1]
            if inner in var_map and _is_rewrite_allowed_field(field_name=field_name, step_function=step_function):
                return f"${{{var_map[inner]}}}"
        return obj
    if isinstance(obj, list):
        return [
            _rewrite_placeholders_obj(
                v,
                var_map,
                step_function=step_function,
                field_name=field_name,
            )
            for v in obj
        ]
    if isinstance(obj, Mapping):
        out: Dict[Any, Any] = {}
        for k, v in obj.items():
            key_name = k if isinstance(k, str) else None
            out[k] = _rewrite_placeholders_obj(
                v,
                var_map,
                step_function=step_function,
                field_name=key_name,
            )
        return out
    return obj


def _rewrite_step_placeholders(
    steps: List[Dict[str, Any]],
    var_map: Mapping[str, str],
    *,
    restricted: bool = True,
) -> List[Dict[str, Any]]:
    if not var_map:
        return steps

    if restricted:
        out: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, Mapping):
                out.append(step)
                continue
            step_function = step.get("function") if isinstance(step.get("function"), str) else None
            rewritten = _rewrite_placeholders_obj(step, var_map, step_function=step_function)
            out.append(rewritten)
        return out

    # Unrestricted mode: regex-replace all ${闁炽儺娲?placeholders regardless of field.
    placeholder_re = re.compile(r"\$\{([A-Za-z0-9_.]+)\}")

    def _rewrite_obj(obj: Any) -> Any:
        if isinstance(obj, str):
            def _sub(match: re.Match[str]) -> str:
                inner = match.group(1)
                mapped = var_map.get(inner)
                if isinstance(mapped, str) and mapped:
                    return f"${{{mapped}}}"
                return match.group(0)

            return placeholder_re.sub(_sub, obj)
        if isinstance(obj, list):
            return [_rewrite_obj(v) for v in obj]
        if isinstance(obj, Mapping):
            out_m: Dict[Any, Any] = {}
            for k, v in obj.items():
                out_m[k] = _rewrite_obj(v)
            return out_m
        return obj

    out_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            out_steps.append(step)
            continue
        out_steps.append(_rewrite_obj(step))
    return out_steps


def _build_stdpart_instance_var_alias_map(steps: List[Dict[str, Any]]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    pattern = re.compile(r"^\$\{([A-Za-z0-9_.]+)\}$")

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        function_name = step.get("function")
        if function_name != "ENSURE_OCCURRENCE_R1":
            continue
        step_id = step.get("id")
        if not (isinstance(step_id, str) and step_id.startswith("stdpart_")):
            continue

        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        component_ref = inputs.get("component_id")
        if not isinstance(component_ref, str):
            continue
        match = pattern.match(component_ref)
        if match is None:
            continue
        prototype_component_var = match.group(1)
        if not prototype_component_var.endswith("_component_id"):
            continue
        prototype_prefix = prototype_component_var[: -len("_component_id")]

        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        for var_name, output_key in vars_map.items():
            if not (isinstance(var_name, str) and isinstance(output_key, str)):
                continue
            if output_key != "occurrence_id" or not var_name.endswith("_occurrence_id"):
                continue
            instance_prefix = var_name[: -len("_occurrence_id")]
            if not instance_prefix or instance_prefix == prototype_prefix:
                continue
            alias_map[f"{instance_prefix}_component_id"] = f"{prototype_prefix}_component_id"
            alias_map[f"{instance_prefix}_body_id"] = f"{prototype_prefix}_body_id"

    return alias_map


_DIRECT_JOINT_TO_AS_BUILT = {
    "RIGID_JOINT_R1": "RIGID_AS_BUILT_JOINT",
    "REVOLUTE_JOINT_R1": "REVOLUTE_AS_BUILT_JOINT",
}


def _placeholder_prefix(value: Any, suffix: str) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\$\{([A-Za-z0-9_.]+)\}", value)
    if match is None:
        return None
    inner = match.group(1)
    if not inner.endswith(suffix):
        return None
    return inner[: -len(suffix)]


def _upgrade_instanced_regular_joints_to_as_built(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not steps:
        return steps

    aliased_joint_bases: set[str] = set()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str):
            continue
        if not (step_id.endswith("_resolve_a") or step_id.endswith("_resolve_b")):
            continue
        metadata = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
        logical_component_id = metadata.get("component_id") if isinstance(metadata.get("component_id"), str) else None
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        prototype_prefix = _placeholder_prefix(inputs.get("component_id"), "_component_id")
        if logical_component_id and prototype_prefix and logical_component_id != prototype_prefix:
            aliased_joint_bases.add(step_id.rsplit("_resolve_", 1)[0])

    upgraded: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            upgraded.append(step)
            continue
        function_name = step.get("function")
        if function_name not in _DIRECT_JOINT_TO_AS_BUILT:
            upgraded.append(dict(step))
            continue

        step_id = step.get("id")
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        joint_component_prefix = _placeholder_prefix(inputs.get("component_id"), "_component_id")
        occurrence_prefixes = {
            prefix
            for prefix in (
                _placeholder_prefix(inputs.get("occurrence_one_id"), "_occurrence_id"),
                _placeholder_prefix(inputs.get("occurrence_two_id"), "_occurrence_id"),
            )
            if isinstance(prefix, str) and prefix
        }
        base_id = step_id.rsplit("_joint", 1)[0] if isinstance(step_id, str) and step_id.endswith("_joint") else None
        if not (isinstance(base_id, str) and base_id in aliased_joint_bases):
            upgraded.append(dict(step))
            continue

        upgraded_step = dict(step)
        upgraded_step["function"] = _DIRECT_JOINT_TO_AS_BUILT[str(function_name)]
        upgraded.append(upgraded_step)

    return upgraded


def _step_touches_component(step: Mapping[str, Any], component_id: str) -> bool:
    marker_vars = {
        f"{component_id}_component_id",
        f"{component_id}_body_id",
        f"{component_id}_occurrence_id",
    }

    def _scan(v: Any) -> bool:
        if isinstance(v, str):
            if v.startswith("${") and v.endswith("}"):
                inner = v[2:-1]
                if inner in marker_vars:
                    return True
            return False
        if isinstance(v, Mapping):
            for vv in v.values():
                if _scan(vv):
                    return True
            return False
        if isinstance(v, list):
            for vv in v:
                if _scan(vv):
                    return True
            return False
        return False

    if _scan(step):
        return True

    capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
    vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
    for var_name in vars_map.keys():
        if isinstance(var_name, str) and var_name in marker_vars:
            return True

    outputs = step.get("outputs") if isinstance(step.get("outputs"), Mapping) else {}
    for var_name in outputs.keys():
        if isinstance(var_name, str) and var_name in marker_vars:
            return True

    metadata = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
    md_cid = metadata.get("component_id")
    return isinstance(md_cid, str) and md_cid == component_id


def _drop_steps_with_removed_dependencies(
    steps: List[Dict[str, Any]],
    *,
    removed_step_ids: set[str],
) -> tuple[List[Dict[str, Any]], set[str]]:
    if not steps:
        return [], set(removed_step_ids)

    removed_all = {sid for sid in removed_step_ids if isinstance(sid, str) and sid}
    kept_steps = [dict(step) for step in steps if isinstance(step, Mapping)]

    changed = True
    while changed:
        changed = False
        next_kept: List[Dict[str, Any]] = []
        for step in kept_steps:
            sid = step.get("id")
            if isinstance(sid, str) and sid in removed_all:
                changed = True
                continue

            deps = step.get("depends_on")
            dep_ids = [dep for dep in deps if isinstance(dep, str)] if isinstance(deps, list) else []
            if any(dep in removed_all for dep in dep_ids):
                if isinstance(sid, str) and sid:
                    removed_all.add(sid)
                changed = True
                continue

            next_kept.append(step)
        kept_steps = next_kept

    return kept_steps, removed_all


def _extract_component_placeholder_from_step(step: Mapping[str, Any]) -> str | None:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
    cid_ref = inputs.get("component_id") if isinstance(inputs.get("component_id"), str) else None
    if not isinstance(cid_ref, str):
        return None
    m = re.fullmatch(r"\$\{([A-Za-z0-9_.]+)_component_id\}", cid_ref)
    if not m:
        return None
    return m.group(1)


def _merge_instanced_geometry_steps(
    geometry_steps: List[Dict[str, Any]],
    *,
    run_dir: Path,
    round_index: int,
    instancing_map: Mapping[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Dict[str, Any]]:
    if not instancing_map:
        return geometry_steps, {}, {"instanced_components": 0, "removed_steps": 0}

    component_instancing_meta: Dict[str, Dict[str, Any]] = {}

    def _upsert_component_meta(source: str, comp_payload: Mapping[str, Any]) -> None:
        cid = comp_payload.get("id")
        if not isinstance(cid, str) or not cid:
            cid = comp_payload.get("component_id")
        if not isinstance(cid, str) or not cid:
            return

        current = component_instancing_meta.setdefault(
            cid,
            {
                "component_id": cid,
                "definition_id": None,
                "instance_id": None,
                "instanced_from": None,
                "sources": [],
            },
        )

        for key in ("definition_id", "instance_id", "instanced_from"):
            value = comp_payload.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()

        if source not in current["sources"]:
            current["sources"].append(source)

    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if kg_path.exists():
        try:
            kg_payload = _read_json(kg_path)
        except Exception:
            kg_payload = {}
        if isinstance(kg_payload, Mapping):
            components = kg_payload.get("components")
            if isinstance(components, list):
                for comp in components:
                    if isinstance(comp, Mapping):
                        _upsert_component_meta("knowledge_graph", comp)

    shape_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    if shape_path.exists():
        try:
            shape_payload = _read_json(shape_path)
        except Exception:
            shape_payload = {}
        if isinstance(shape_payload, Mapping):
            for key in ("parts", "component_realizations"):
                items = shape_payload.get(key)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, Mapping):
                            _upsert_component_meta("shape_realization", item)

    instance_ids = sorted({cid for cid in instancing_map.keys() if isinstance(cid, str) and cid})
    prototype_ids = sorted({proto for proto in instancing_map.values() if isinstance(proto, str) and proto})

    removed_step_ids: set[str] = set()
    duplicate_ops: List[Dict[str, Any]] = []
    suggested_fix_points: set[str] = set()

    def _build_fix_suggestion(*, component_id: str, prototype_id: str | None, meta: Mapping[str, Any]) -> Dict[str, Any]:
        definition_id = meta.get("definition_id") if isinstance(meta.get("definition_id"), str) else None
        instanced_from = meta.get("instanced_from") if isinstance(meta.get("instanced_from"), str) else None
        instance_id = meta.get("instance_id") if isinstance(meta.get("instance_id"), str) else None

        if not definition_id and not instanced_from:
            suggested_fix_points.add("Agent1_requirement_to_kg")
            return {
                "owner": "Agent1_requirement_to_kg",
                "message": "Missing instancing metadata: instance components need definition_id/instanced_from or a rotational_symmetry prototype.",
                "fields": ["components[*].definition_id", "components[*].instanced_from", "patterns[*].prototype"],
            }

        if isinstance(prototype_id, str) and prototype_id and definition_id and definition_id != prototype_id:
            suggested_fix_points.add("Agent1_requirement_to_kg")
            return {
                "owner": "Agent1_requirement_to_kg",
                "message": "definition_id does not match the instancing prototype; normalize definition_id/instanced_from to the prototype.",
                "fields": ["components[*].definition_id", "components[*].instanced_from"],
            }
        suggested_fix_points.add("Agent3b_compile_geometry_plan")
        return {
            "owner": "Agent3b_compile_geometry_plan",
            "message": "Instancing drift: geometry planning emitted instance-specific geometry without consistent definition_id/prototype metadata.",
            "fields": ["component_definition_by_id", "patterns.rotational_symmetry.prototype"],
            "instance_id": instance_id,
        }

    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {"ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}:
            continue
        touched_instances = [cid for cid in instance_ids if _step_touches_component(step, cid)]
        if not touched_instances:
            continue
        if isinstance(sid, str) and sid:
            removed_step_ids.add(sid)
        for cid in touched_instances:
            component_meta = component_instancing_meta.get(
                cid,
                {
                    "component_id": cid,
                    "definition_id": None,
                    "instance_id": None,
                    "instanced_from": None,
                    "sources": [],
                },
            )
            suggestion = _build_fix_suggestion(
                component_id=cid,
                prototype_id=instancing_map.get(cid),
                meta=component_meta,
            )
            duplicate_ops.append(
                {
                    "step_id": sid,
                    "function": function_name,
                    "component_id": cid,
                    "instance_component_id": cid,
                    "prototype_component_id": instancing_map.get(cid),
                    "instancing_fields": {
                        "definition_id": component_meta.get("definition_id"),
                        "instance_id": component_meta.get("instance_id"),
                        "instanced_from": component_meta.get("instanced_from"),
                        "sources": component_meta.get("sources"),
                    },
                    "suggested_fix_point": suggestion,
                }
            )

    kept_steps: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if isinstance(sid, str) and sid in removed_step_ids:
            continue
        step_copy = dict(step)
        deps = step_copy.get("depends_on")
        if isinstance(deps, list):
            step_copy["depends_on"] = [d for d in deps if not (isinstance(d, str) and d in removed_step_ids)]
        kept_steps.append(step_copy)

    var_map: Dict[str, str] = {}
    for cid, proto in instancing_map.items():
        if not isinstance(cid, str) or not isinstance(proto, str) or not cid or not proto:
            continue
        var_map[f"{cid}_component_id"] = f"{proto}_component_id"
        var_map[f"{cid}_body_id"] = f"{proto}_body_id"

    rewritten = _rewrite_step_placeholders(kept_steps, var_map)

    report = {
        "round_index": int(round_index),
        "instanced_components": len(instance_ids),
        "prototypes": prototype_ids,
        "removed_steps": len(removed_step_ids),
        "removed_step_ids": sorted(removed_step_ids),
        "duplicate_geometry_ops": duplicate_ops,
    }

    if duplicate_ops:
        error_payload = {
            "metadata": {
                "source": "Agent5_compose_plan.instancing_audit",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "instanced_components": len(instance_ids),
                "duplicate_geometry_step_count": len(duplicate_ops),
                "suggested_fix_points": sorted(suggested_fix_points),
            },
            "duplicates": duplicate_ops,
            "component_instancing_metadata": [
                component_instancing_meta[cid]
                for cid in sorted(component_instancing_meta.keys())
                if cid in set(instance_ids)
            ],
        }
        _write_json(run_dir / "planning" / "errors" / "instancing_duplicate_geometry.json", error_payload)
        raise RuntimeError(
            "instancing_duplicate_geometry_detected: same prototype geometry generated for multiple instances. "
            "See planning/errors/instancing_duplicate_geometry.json"
        )

    return rewritten, var_map, report


def _fold_symmetric_connection_geometry_steps(
    geometry_steps: List[Dict[str, Any]],
    *,
    instancing_map: Mapping[str, str],
    connection_alias_map: Mapping[str, str] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not geometry_steps or not instancing_map:
        return geometry_steps, {"removed_steps": 0, "removed_step_ids": []}

    token_pairs: List[Tuple[str, str]] = []

    def _tail2(value: str) -> str | None:
        parts = [p for p in value.split("_") if p]
        if len(parts) >= 2:
            return "_".join(parts[-2:])
        return None

    def _family_root(value: str) -> str | None:
        parts = [p for p in value.split("_") if p]
        if len(parts) < 2:
            return None
        if not parts[1].isdigit():
            return None
        return f"{parts[0]}_{parts[1]}"

    for inst, proto in instancing_map.items():
        if not (isinstance(inst, str) and isinstance(proto, str) and inst and proto and inst != proto):
            continue
        token_pairs.append((inst, proto))
        inst_tail = _tail2(inst)
        proto_tail = _tail2(proto)
        if isinstance(inst_tail, str) and isinstance(proto_tail, str) and inst_tail and proto_tail and inst_tail != proto_tail:
            token_pairs.append((inst_tail, proto_tail))
        inst_root = _family_root(inst)
        proto_root = _family_root(proto)
        if isinstance(inst_root, str) and isinstance(proto_root, str) and inst_root and proto_root and inst_root != proto_root:
            token_pairs.append((inst_root, proto_root))

    # Keep deterministic order and dedupe pair definitions.
    seen_pair: set[Tuple[str, str]] = set()
    ordered_pairs: List[Tuple[str, str]] = []
    for pair in sorted(token_pairs, key=lambda p: (-len(p[0]), p[0], p[1])):
        if pair in seen_pair:
            continue
        seen_pair.add(pair)
        ordered_pairs.append(pair)

    def _canonicalize_step_id(step_id: str) -> str:
        out = step_id
        for src, dst in ordered_pairs:
            if src == dst:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(src)}(?![A-Za-z0-9])")
            out = pattern.sub(dst, out)
        return out

    alias_map = dict(connection_alias_map or {})

    def _canonicalize_connection_req_tokens(step_id: str) -> str:
        out = step_id
        for source_id, canonical_id in sorted(alias_map.items(), key=lambda item: (-len(item[0]), item[0])):
            if source_id == canonical_id:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(source_id)}(?![A-Za-z0-9])")
            out = pattern.sub(canonical_id, out)
        return out

    def _canonicalize_full_step_id(step_id: str) -> str:
        return _canonicalize_connection_req_tokens(_canonicalize_step_id(step_id))

    def _eligible(step: Mapping[str, Any], step_id: str) -> bool:
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {
            "CREATE_COMPONENT",
            "ENSURE_OCCURRENCE_R1",
            "SET_OCCURRENCE_TRANSFORM_R1",
            "CREATE_SKETCH_ON_PLANE",
            "SKETCH_CIRCLE",
            "SKETCH_RECTANGLE",
            "EXTRUDE_NEW_BODY",
        }:
            return False
        lowered = step_id.lower()
        component_token = _extract_component_placeholder_from_step(step)
        if not (isinstance(component_token, str) and component_token):
            return False
        if _canonicalize_full_step_id(step_id) != step_id:
            return True
        for source_id, canonical_id in alias_map.items():
            for token in (source_id, canonical_id):
                if not (isinstance(token, str) and token):
                    continue
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])")
                if pattern.search(step_id):
                    return True
        if "req_" in lowered:
            return True
        if "central_hub" in component_token.lower() and "arm_" in lowered:
            return any(tok in lowered for tok in ("hole", "pattern", "resolve_face", "activate", "counterbore", "countersink"))
        return False

    canonical_groups: Dict[str, List[str]] = {}
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        if not _eligible(step, sid):
            continue
        canonical = _canonicalize_full_step_id(sid)
        canonical = re.sub(r"_[0-9]+$", "", canonical)
        canonical_groups.setdefault(canonical, []).append(sid)

    removed_to_kept: Dict[str, str] = {}
    folded_pairs: List[Dict[str, str]] = []
    for canonical_key, members in canonical_groups.items():
        if len(members) <= 1:
            continue

        # Distinguish prototype steps (canonicalization left ID unchanged) from
        # instance-derived steps (ID was rewritten).  Prototype steps within the
        # same canonical group are SEQUENTIAL operations (e.g. re_resolve_face_2
        # and re_resolve_face_4 in the same feature chain for *one* arm) and must
        # NOT be folded together.  Only instance-derived duplicates are genuinely
        # symmetric and should be collapsed.
        prototype_sids = frozenset(
            sid for sid in members if _canonicalize_full_step_id(sid) == sid
        )
        instance_sids = [sid for sid in members if sid not in prototype_sids]

        if not instance_sids:
            # All members are prototype steps 闁?sequential, not symmetric copies.
            continue

        if prototype_sids:
            winner = sorted(prototype_sids)[0]
        elif canonical_key in members:
            winner = canonical_key
        else:
            winner = sorted(members)[0]

        for sid in sorted(members):
            if sid == winner or sid in prototype_sids:
                continue
            removed_to_kept[sid] = winner
            folded_pairs.append(
                {
                    "removed_step_id": sid,
                    "canonical_step_id": winner,
                    "canonical_key": canonical_key,
                }
            )

    # Remove dependent symmetric duplicates that directly depend on already removed seeds.
    changed = True
    while changed:
        changed = False
        for step in geometry_steps:
            if not isinstance(step, Mapping):
                continue
            sid = step.get("id")
            if not isinstance(sid, str) or not sid or sid in removed_to_kept:
                continue
            if not _eligible(step, sid):
                continue
            deps = step.get("depends_on")
            if not isinstance(deps, list):
                continue
            removed_dep = next((d for d in deps if isinstance(d, str) and d in removed_to_kept), None)
            if not isinstance(removed_dep, str):
                continue
            removed_to_kept[sid] = removed_to_kept[removed_dep]
            folded_pairs.append(
                {
                    "removed_step_id": sid,
                    "canonical_step_id": removed_to_kept[removed_dep],
                    "canonical_key": "dependent_removed_with_seed",
                }
            )
            changed = True

    if not removed_to_kept:
        return geometry_steps, {
            "removed_steps": 0,
            "removed_step_ids": [],
            "folded_pairs": [],
            "connection_alias_count": len(alias_map),
        }

    kept: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if isinstance(sid, str) and sid in removed_to_kept:
            continue
        step_copy = dict(step)
        deps = step_copy.get("depends_on")
        if isinstance(deps, list) and deps:
            new_deps: List[str] = []
            for dep in deps:
                if not isinstance(dep, str):
                    continue
                target = dep
                seen: set[str] = set()
                while target in removed_to_kept and target not in seen:
                    seen.add(target)
                    target = removed_to_kept[target]
                if target not in new_deps:
                    new_deps.append(target)
            step_copy["depends_on"] = new_deps
        kept.append(step_copy)

    step_by_id: Dict[str, Mapping[str, Any]] = {}
    for step in geometry_steps:
        sid = step.get("id") if isinstance(step, Mapping) else None
        if isinstance(sid, str) and sid:
            step_by_id[sid] = step

    var_alias_map: Dict[str, str] = {}
    for removed_id, kept_id in removed_to_kept.items():
        removed_step = step_by_id.get(removed_id)
        kept_step = step_by_id.get(kept_id)
        if not (isinstance(removed_step, Mapping) and isinstance(kept_step, Mapping)):
            continue

        removed_capture = removed_step.get("capture") if isinstance(removed_step.get("capture"), Mapping) else {}
        kept_capture = kept_step.get("capture") if isinstance(kept_step.get("capture"), Mapping) else {}
        removed_vars = removed_capture.get("vars") if isinstance(removed_capture.get("vars"), Mapping) else {}
        kept_vars = kept_capture.get("vars") if isinstance(kept_capture.get("vars"), Mapping) else {}
        if not (isinstance(removed_vars, Mapping) and isinstance(kept_vars, Mapping)):
            continue

        kept_by_output_key: Dict[str, str] = {}
        for kept_var_name, output_key in kept_vars.items():
            if isinstance(kept_var_name, str) and kept_var_name and isinstance(output_key, str) and output_key:
                kept_by_output_key[output_key] = kept_var_name

        for removed_var_name, output_key in removed_vars.items():
            if not (isinstance(removed_var_name, str) and removed_var_name and isinstance(output_key, str) and output_key):
                continue
            mapped_var = kept_by_output_key.get(output_key)
            if isinstance(mapped_var, str) and mapped_var and mapped_var != removed_var_name:
                var_alias_map[removed_var_name] = mapped_var

    if var_alias_map:
        kept = _rewrite_step_placeholders(kept, var_alias_map, restricted=False)

    return kept, {
        "removed_steps": len(removed_to_kept),
        "removed_step_ids": sorted(removed_to_kept.keys()),
        "folded_pairs": folded_pairs,
        "connection_alias_count": len(alias_map),
        "rewritten_var_aliases": len(var_alias_map),
    }


def _audit_instance_specific_geometry_steps(
    *,
    geometry_steps: List[Dict[str, Any]],
    instancing_map: Mapping[str, str],
    run_dir: Path,
    round_index: int,
) -> Dict[str, Any]:
    instances_by_proto: Dict[str, List[str]] = {}
    for instance_id, prototype_id in instancing_map.items():
        if not (isinstance(instance_id, str) and instance_id and isinstance(prototype_id, str) and prototype_id):
            continue
        instances_by_proto.setdefault(prototype_id, []).append(instance_id)

    risky_groups = {
        proto: sorted({proto, *instances})
        for proto, instances in instances_by_proto.items()
        if len(set(instances + [proto])) >= 2
    }
    if not risky_groups:
        return {
            "round_index": int(round_index),
            "prototypes_with_multi_instances": 0,
            "violations": 0,
            "violating_step_ids": [],
        }

    def _instance_alias_tokens(token: str) -> List[str]:
        aliases = {token}
        m = re.match(r"^([A-Za-z]+_[0-9]+)_", token)
        if m:
            aliases.add(m.group(1))
        parts = [p for p in token.split("_") if p]
        if len(parts) >= 2:
            aliases.add("_".join(parts[-2:]))
        return sorted(a for a in aliases if a)

    violations: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {"ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}:
            continue

        component_token = _extract_component_placeholder_from_step(step)
        if not (isinstance(component_token, str) and component_token in risky_groups):
            continue

        instance_tokens: List[str] = []
        for token in risky_groups[component_token]:
            if token == component_token:
                continue
            aliases = _instance_alias_tokens(token)
            if any((f"req_{alias}_" in sid or f"_{alias}_" in sid) for alias in aliases):
                instance_tokens.append(token)
        if not instance_tokens:
            continue

        violations.append(
            {
                "step_id": sid,
                "function": function_name,
                "prototype_component_id": component_token,
                "instance_tokens": sorted(instance_tokens),
                "rule": "no_instance_specific_requirement_id_on_shared_prototype_geometry",
            }
        )

    if violations:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.instancing_geometry_audit",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "prototypes_with_multi_instances": len(risky_groups),
                "violations": len(violations),
            },
            "prototypes": [
                {"prototype_component_id": proto, "instances": instances}
                for proto, instances in sorted(risky_groups.items())
            ],
            "violations": violations,
        }
        _write_json(run_dir / "planning" / "errors" / "instancing_geometry_step_audit.json", payload)
        raise RuntimeError(
            "instancing_geometry_step_audit_failed: instance-specific requirement IDs detected on shared prototype geometry. "
            "See planning/errors/instancing_geometry_step_audit.json"
        )

    return {
        "round_index": int(round_index),
        "prototypes_with_multi_instances": len(risky_groups),
        "violations": 0,
        "violating_step_ids": [],
    }


def _inject_initial_placements(
    steps: List[Dict[str, Any]],
    *,
    run_dir: Path,
    round_index: int,
    instancing_map: Mapping[str, str] | None = None,
    var_alias_map: Mapping[str, str] | None = None,
) -> List[Dict[str, Any]]:
    placements = _load_initial_placements(run_dir, round_index=round_index)
    report: Dict[str, Any] = {
        "round_index": int(round_index),
        "placements_total": len(placements),
        "transform_steps_expected": len(placements),
        "transform_steps_injected": 0,
        "placed_count": 0,
        "skipped_count": 0,
        "placed_component_ids": [],
        "placed": [],
        "skipped": [],
    }

    instancing = dict(instancing_map or {})
    var_aliases = {
        str(src): str(dst)
        for src, dst in dict(var_alias_map or {}).items()
        if isinstance(src, str) and src and isinstance(dst, str) and dst
    }

    def _resolve_var_alias(var_name: str) -> str:
        current = var_name
        seen: set[str] = set()
        while current in var_aliases and current not in seen:
            seen.add(current)
            nxt = var_aliases[current]
            if not isinstance(nxt, str) or not nxt or nxt == current:
                break
            current = nxt
        return current

    used_ids: set[str] = set()
    for step in steps:
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            used_ids.add(sid)

    def _unique_id(base: str) -> str:
        if base not in used_ids:
            used_ids.add(base)
            return base
        i = 2
        while f"{base}_{i}" in used_ids:
            i += 1
        out = f"{base}_{i}"
        used_ids.add(out)
        return out

    placement_by_component: Dict[str, Mapping[str, Any]] = {}
    world_transform_by_component: Dict[str, Dict[str, Any]] = {}

    def _normalize_transform_mm(transform_raw: Any) -> Dict[str, Any]:
        tr_raw = transform_raw if isinstance(transform_raw, Mapping) else {}
        t_raw = tr_raw.get("translation") if isinstance(tr_raw.get("translation"), Mapping) else {}
        r_raw = tr_raw.get("rotation_rpy_deg") if isinstance(tr_raw.get("rotation_rpy_deg"), Mapping) else {}
        return {
            "translation": {
                "x": float(t_raw.get("x", 0.0)),
                "y": float(t_raw.get("y", 0.0)),
                "z": float(t_raw.get("z", 0.0)),
            },
            "rotation_rpy_deg": {
                "roll": float(r_raw.get("roll", 0.0)),
                "pitch": float(r_raw.get("pitch", 0.0)),
                "yaw": float(r_raw.get("yaw", 0.0)),
            },
        }

    for placement in placements:
        cid = placement.get("component_id")
        if not isinstance(cid, str) or not cid:
            continue
        placement_by_component[cid] = placement
        world_transform_by_component[cid] = _normalize_transform_mm(placement.get("transform"))

    def _to_local_transform(component_id: str, parent_component_id: str | None) -> Dict[str, Any]:
        world = world_transform_by_component.get(component_id)
        if not isinstance(world, Mapping):
            return _normalize_transform_mm({})
        if not isinstance(parent_component_id, str) or not parent_component_id:
            return dict(world)

        parent_world = world_transform_by_component.get(parent_component_id)
        if not isinstance(parent_world, Mapping):
            return dict(world)

        wt = world.get("translation") if isinstance(world.get("translation"), Mapping) else {}
        wr = world.get("rotation_rpy_deg") if isinstance(world.get("rotation_rpy_deg"), Mapping) else {}
        pt = parent_world.get("translation") if isinstance(parent_world.get("translation"), Mapping) else {}
        pr = parent_world.get("rotation_rpy_deg") if isinstance(parent_world.get("rotation_rpy_deg"), Mapping) else {}

        return {
            "translation": {
                "x": float(wt.get("x", 0.0)) - float(pt.get("x", 0.0)),
                "y": float(wt.get("y", 0.0)) - float(pt.get("y", 0.0)),
                "z": float(wt.get("z", 0.0)) - float(pt.get("z", 0.0)),
            },
            "rotation_rpy_deg": {
                "roll": float(wr.get("roll", 0.0)) - float(pr.get("roll", 0.0)),
                "pitch": float(wr.get("pitch", 0.0)) - float(pr.get("pitch", 0.0)),
                "yaw": float(wr.get("yaw", 0.0)) - float(pr.get("yaw", 0.0)),
            },
        }

    for placement in placements:
        cid = placement.get("component_id")
        if not isinstance(cid, str) or not cid:
            report["skipped"].append({"component_id": cid, "reason": "invalid_component_id"})
            continue
        placement_by_component[cid] = placement

    required_components: set[str] = set()
    placement_satisfied_components: set[str] = set(placement_by_component.keys())

    def _select_required_component_ids(candidates: List[str]) -> List[str]:
        normalized = [cid for cid in candidates if isinstance(cid, str) and cid]
        if not normalized:
            return []
        unique = sorted(set(normalized))

        def _is_standard_alias(component_id: str) -> bool:
            return component_id.startswith("stdpart_") or component_id.startswith("std_")

        if len(unique) <= 1:
            if unique and _is_standard_alias(unique[0]):
                return []
            return unique

        # Standard-part injection may capture both an internal alias prefix
        # (e.g. stdpart_xxx_component_id) and the bound real component id
        # from the same output key. For completeness gating, prefer canonical
        # component ids that already have placement records.
        present_in_placements = [cid for cid in unique if cid in placement_by_component]
        if present_in_placements:
            return present_in_placements

        non_stdpart = [cid for cid in unique if not _is_standard_alias(cid)]
        if non_stdpart:
            return non_stdpart

        return []

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if not isinstance(vars_map, Mapping):
            continue
        step_component_ids: List[str] = []
        step_occurrence_ids: List[str] = []
        for var_name, output_key in vars_map.items():
            if not isinstance(var_name, str) or not var_name:
                continue
            if output_key == "component_id" and var_name.endswith("_component_id"):
                cid = var_name[: -len("_component_id")]
                if isinstance(cid, str) and cid:
                    step_component_ids.append(cid)
                continue
            if output_key == "occurrence_id":
                if var_name.endswith("_existing_occurrence_id"):
                    cid = var_name[: -len("_existing_occurrence_id")]
                elif var_name.endswith("_occurrence_id"):
                    cid = var_name[: -len("_occurrence_id")]
                else:
                    cid = None
                if isinstance(cid, str) and cid:
                    step_occurrence_ids.append(cid)

        resolved_component_ids = _select_required_component_ids(step_component_ids)
        resolved_occurrence_ids = _select_required_component_ids(step_occurrence_ids)
        for cid in resolved_component_ids:
            required_components.add(cid)
        for cid in resolved_occurrence_ids:
            required_components.add(cid)
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        has_explicit_transform = (
            (step.get("function") == "CREATE_COMPONENT" and isinstance(inputs.get("transform"), Mapping))
            or (step.get("function") == "ENSURE_OCCURRENCE_R1" and isinstance(inputs.get("transform_mm"), Mapping))
        )
        if has_explicit_transform:
            for cid in resolved_component_ids:
                placement_satisfied_components.add(cid)

    for cid, proto in instancing.items():
        if isinstance(cid, str) and cid:
            required_components.add(cid)
        if isinstance(proto, str) and proto:
            required_components.add(proto)

    missing_placement_components = sorted(
        cid for cid in required_components if cid not in placement_satisfied_components
    )
    if missing_placement_components:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "required_components": len(required_components),
                "missing_initial_placements": len(missing_placement_components),
            },
            "missing_component_ids": missing_placement_components,
        }
        _write_json(run_dir / "planning" / "errors" / "initial_placement_completeness.json", payload)
        raise RuntimeError(
            "initial_placement_completeness_failed: missing initial_placements for one or more required components. "
            "See planning/errors/initial_placement_completeness.json"
        )

    step_ids_by_index: Dict[int, str] = {}
    var_last_def: Dict[str, Tuple[int, str]] = {}
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else None
        if not isinstance(sid, str) or not sid:
            continue
        step_ids_by_index[idx] = sid

        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if isinstance(vars_map, Mapping):
            for var_name in vars_map.keys():
                if isinstance(var_name, str) and var_name:
                    var_last_def[var_name] = (idx, sid)

    inject_after_index: Dict[int, List[Dict[str, Any]]] = {}
    existing_ensure_occurrence_names: set[str] = set()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occurrence_name = inputs.get("occurrence_name") if isinstance(inputs, Mapping) else None
        if isinstance(occurrence_name, str) and occurrence_name:
            existing_ensure_occurrence_names.add(occurrence_name)

    def _queue_after(index: int, step_obj: Dict[str, Any]) -> None:
        inject_after_index.setdefault(index, []).append(step_obj)

    # ---- D-16: Detect shared component definitions ----
    # A prototype's Fusion 360 definition is shared once any other component
    # creates an ENSURE_OCCURRENCE_R1 referencing it.  Children added to a
    # shared definition appear in ALL occurrences, so we must *lift* those
    # children to the nearest independent (non-shared) ancestor.
    _shared_def_ids: set[str] = set()
    for _inst_cid in required_components:
        _inst_proto = instancing.get(_inst_cid)
        if not isinstance(_inst_proto, str) or not _inst_proto:
            continue
        _inst_occ_var = f"{_inst_cid}_occurrence_id"
        if not isinstance(var_last_def.get(_inst_occ_var), tuple):
            _shared_def_ids.add(_inst_proto)
    for _s in steps:
        if not isinstance(_s, Mapping) or _s.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        _s_inputs = _s.get("inputs") if isinstance(_s.get("inputs"), Mapping) else {}
        _comp_ref = _s_inputs.get("component_id", "") if isinstance(_s_inputs, Mapping) else ""
        if isinstance(_comp_ref, str) and _comp_ref.startswith("${") and _comp_ref.endswith("}"):
            _vname = _comp_ref[2:-1]
            if _vname.endswith("_component_id"):
                _shared_def_ids.add(_vname[: -len("_component_id")])
    _create_parent_fixes: Dict[int, str | None] = {}

    for cid, placement in placement_by_component.items():
        if cid not in required_components:
            continue

        parent_assembly_raw = placement.get("parent_assembly")
        parent_component_id = (
            str(parent_assembly_raw)
            if isinstance(parent_assembly_raw, str) and parent_assembly_raw and parent_assembly_raw != "root"
            else None
        )

        # ---- D-16: Lift parent out of shared definitions ----
        _original_parent = parent_component_id
        if isinstance(parent_component_id, str) and parent_component_id:
            _walk = parent_component_id
            for _ in range(10):
                _is_shared = (
                    _walk in _shared_def_ids
                    or (
                        _walk in instancing
                        and isinstance(instancing.get(_walk), str)
                        and instancing[_walk] in _shared_def_ids
                    )
                )
                if not _is_shared:
                    break
                _walk_pl = placement_by_component.get(_walk)
                if not isinstance(_walk_pl, Mapping):
                    break
                _anc = _walk_pl.get("parent_assembly")
                if not isinstance(_anc, str) or _anc == "root" or not _anc:
                    _walk = None
                    break
                _walk = _anc
            if _walk != parent_component_id:
                parent_component_id = _walk

        # ---- Flat hierarchy: all components at root ----
        # Fusion 360 occ.transform2 only works for direct children of root,
        # so parent_component_id is always None regardless of KG hierarchy.
        parent_component_id = None

        occurrence_var = f"{cid}_occurrence_id"
        transform = _to_local_transform(cid, parent_component_id)
        grounded = placement.get("ground")
        if not isinstance(grounded, bool):
            grounded = False

        existing_occ_anchor = var_last_def.get(occurrence_var)
        if isinstance(existing_occ_anchor, tuple):
            anchor_idx, anchor_sid = existing_occ_anchor

            # ---- D-16: Fix CREATE_COMPONENT parent for lifted prototypes ----
            if parent_component_id != _original_parent:
                _new_pvar = f"${{{parent_component_id}_component_id}}" if parent_component_id else None
                for _fix_idx, _fix_step in enumerate(steps):
                    if not isinstance(_fix_step, Mapping):
                        continue
                    if _fix_step.get("function") != "CREATE_COMPONENT":
                        continue
                    _fix_capture = _fix_step.get("capture") if isinstance(_fix_step.get("capture"), Mapping) else {}
                    _fix_vars = _fix_capture.get("vars") if isinstance(_fix_capture.get("vars"), Mapping) else {}
                    if f"{cid}_component_id" in _fix_vars:
                        _create_parent_fixes[_fix_idx] = _new_pvar
                        break

            xform_id = _unique_id(f"place_{cid}_xform")
            xform_step: Dict[str, Any] = {
                "id": xform_id,
                "function": "SET_OCCURRENCE_TRANSFORM_R1",
                "inputs": {
                    "occurrence_id": f"${{{occurrence_var}}}",
                    "transform_mm": dict(transform),
                    "mode": "absolute",
                    "grounded": grounded,
                },
                "depends_on": [anchor_sid],
            }
            _queue_after(anchor_idx, xform_step)

            report["placed_count"] = int(report.get("placed_count", 0)) + 1
            report["transform_steps_injected"] = int(report.get("transform_steps_injected", 0)) + 1
            report["placed_component_ids"].append(cid)
            report["placed"].append(
                {
                    "component_id": cid,
                    "prototype_component_id": instancing.get(cid, cid),
                    "occurrence_name": placement.get("occurrence_name") or cid,
                    "grounded": grounded,
                    "mode": "absolute",
                    "parent_component_id": parent_component_id,
                    "transform_mm": dict(transform),
                    "injected_steps": {
                        "ensure_step_id": None,
                        "transform_step_id": xform_id,
                        "anchor_step_id": anchor_sid,
                    },
                }
            )
            continue

        prototype_cid = instancing.get(cid, cid)
        component_var_raw = f"{prototype_cid}_component_id"
        component_var = _resolve_var_alias(component_var_raw)
        component_anchor = var_last_def.get(component_var)
        if not isinstance(component_anchor, tuple):
            report["skipped"].append(
                {
                    "component_id": cid,
                    "reason": "missing_plan_vars",
                    "details": {
                        "required": [component_var_raw],
                        "missing": [component_var_raw],
                        **({"resolved_alias": component_var} if component_var != component_var_raw else {}),
                    },
                }
            )
            continue

        parent_var: str | None = None
        effective_parent_component_id = parent_component_id
        parent_anchor: Tuple[int, str] | None = None
        if isinstance(parent_component_id, str) and parent_component_id:
            parent_candidate_ids: List[str] = [parent_component_id]
            parent_proto = instancing.get(parent_component_id)
            if isinstance(parent_proto, str) and parent_proto and parent_proto not in parent_candidate_ids:
                parent_candidate_ids.append(parent_proto)

            for parent_cid in parent_candidate_ids:
                candidate_var_raw = f"{parent_cid}_component_id"
                candidate_var = _resolve_var_alias(candidate_var_raw)
                candidate_anchor = var_last_def.get(candidate_var)
                if isinstance(candidate_anchor, tuple):
                    parent_var = candidate_var
                    parent_anchor = candidate_anchor
                    break

            if not isinstance(parent_anchor, tuple):
                required_parent_vars = [f"{pcid}_component_id" for pcid in parent_candidate_ids]
                report["skipped"].append(
                    {
                        "component_id": cid,
                        "reason": "missing_parent_component_var",
                        "details": {
                            "parent_component_id": parent_component_id,
                            "required": required_parent_vars,
                        },
                    }
                )
                continue

        anchor_candidates = [component_anchor]
        if isinstance(parent_anchor, tuple):
            anchor_candidates.append(parent_anchor)
        anchor_idx, anchor_sid = max(anchor_candidates, key=lambda item: item[0])

        ensure_id = _unique_id(f"place_{cid}_ensure")
        ensure_inputs: Dict[str, Any] = {
            "component_id": f"${{{component_var}}}",
            "occurrence_name": placement.get("occurrence_name") or cid,
            "parent_component_id": f"${{{parent_var}}}" if isinstance(parent_var, str) and parent_var else None,
            "transform_mm": dict(transform),
        }
        ensure_step: Dict[str, Any] = {
            "id": ensure_id,
            "function": "ENSURE_OCCURRENCE_R1",
            "inputs": ensure_inputs,
            "depends_on": [anchor_sid],
            "capture": {"vars": {occurrence_var: "occurrence_id"}},
        }

        xform_id = _unique_id(f"place_{cid}_xform")
        xform_step = {
            "id": xform_id,
            "function": "SET_OCCURRENCE_TRANSFORM_R1",
            "inputs": {
                "occurrence_id": f"${{{occurrence_var}}}",
                "transform_mm": dict(transform),
                "mode": "absolute",
                "grounded": grounded,
            },
            "depends_on": [ensure_id],
        }
        _queue_after(anchor_idx, ensure_step)
        _queue_after(anchor_idx, xform_step)

        report["placed_count"] = int(report.get("placed_count", 0)) + 1
        report["transform_steps_injected"] = int(report.get("transform_steps_injected", 0)) + 1
        report["placed_component_ids"].append(cid)
        report["placed"].append(
            {
                "component_id": cid,
                "prototype_component_id": prototype_cid,
                "occurrence_name": placement.get("occurrence_name") or cid,
                "grounded": grounded,
                "mode": "absolute",
                "parent_component_id": effective_parent_component_id,
                "transform_mm": dict(transform),
                "injected_steps": {
                    "ensure_step_id": ensure_id,
                    "transform_step_id": xform_id,
                    "anchor_step_id": anchor_sid,
                },
            }
        )

    out_steps: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        _sdict = dict(step)
        # ---- D-16: Apply CREATE_COMPONENT parent fixes ----
        if idx in _create_parent_fixes:
            _fix_inputs = dict(_sdict.get("inputs")) if isinstance(_sdict.get("inputs"), Mapping) else {}
            _fix_inputs["parent_component_id"] = _create_parent_fixes[idx]
            _sdict["inputs"] = _fix_inputs
        out_steps.append(_sdict)
        for injected in inject_after_index.get(idx, []):
            out_steps.append(dict(injected))

    ensure_occurrence_map: Dict[str, List[str]] = {}
    for step in out_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occurrence_name = inputs.get("occurrence_name") if isinstance(inputs, Mapping) else None
        if not isinstance(occurrence_name, str) or not occurrence_name:
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else "<unknown>"
        ensure_occurrence_map.setdefault(occurrence_name, []).append(sid)

    duplicates = {
        name: sorted(step_ids)
        for name, step_ids in ensure_occurrence_map.items()
        if len(step_ids) > 1
    }
    if duplicates:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "duplicate_occurrence_names": len(duplicates),
                "violations": sum(len(v) for v in duplicates.values()),
            },
            "duplicates": [
                {"occurrence_name": name, "ensure_step_ids": step_ids}
                for name, step_ids in sorted(duplicates.items())
            ],
        }
        _write_json(run_dir / "planning" / "errors" / "duplicate_ensure_occurrence.json", payload)
        raise RuntimeError(
            "duplicate_ensure_occurrence_detected: same occurrence_name appears in ENSURE_OCCURRENCE_R1 more than once. "
            "See planning/errors/duplicate_ensure_occurrence.json"
        )

    if report.get("skipped"):
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "violations": len(report.get("skipped") or []),
            },
            "violations": report.get("skipped") or [],
        }
        _write_json(run_dir / "planning" / "errors" / "initial_placement_injection_failures.json", payload)
        raise RuntimeError(
            "initial_placement_injection_failed: cannot inject deterministic placement for all components. "
            "See planning/errors/initial_placement_injection_failures.json"
        )

    out_index_by_step_id: Dict[str, int] = {}
    for idx, step in enumerate(out_steps):
        sid = step.get("id") if isinstance(step, Mapping) and isinstance(step.get("id"), str) else None
        if isinstance(sid, str) and sid:
            out_index_by_step_id[sid] = idx

    def _step_defines_component(step_obj: Mapping[str, Any], component_id: str) -> bool:
        target_var = f"{component_id}_component_id"

        capture = step_obj.get("capture") if isinstance(step_obj.get("capture"), Mapping) else {}
        capture_vars = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if isinstance(capture_vars, Mapping):
            output_key = capture_vars.get(target_var)
            if output_key == "component_id":
                return True

        outputs = step_obj.get("outputs") if isinstance(step_obj.get("outputs"), Mapping) else {}
        if isinstance(outputs, Mapping):
            output_key = outputs.get(target_var)
            if output_key == "component_id":
                return True

        return False

    placement_index_by_component: Dict[str, int] = {}
    for item in report.get("placed") or []:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        injected = item.get("injected_steps") if isinstance(item.get("injected_steps"), Mapping) else {}
        xform_step_id = injected.get("transform_step_id") if isinstance(injected.get("transform_step_id"), str) else None
        if not isinstance(cid, str) or not cid or not isinstance(xform_step_id, str) or not xform_step_id:
            continue
        xform_idx = out_index_by_step_id.get(xform_step_id)
        if isinstance(xform_idx, int):
            placement_index_by_component[cid] = xform_idx

    ordering_violations: List[Dict[str, Any]] = []
    placement_functions = {"CREATE_COMPONENT", "ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}
    tracked_components = sorted(placement_by_component.keys())
    for idx, step in enumerate(out_steps):
        if not isinstance(step, Mapping):
            continue
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in placement_functions:
            continue
        step_id = step.get("id") if isinstance(step.get("id"), str) else "<unknown>"
        for cid in tracked_components:
            if not _step_touches_component(step, cid):
                continue
            if _step_defines_component(step, cid):
                continue
            placement_idx = placement_index_by_component.get(cid)
            if not isinstance(placement_idx, int):
                ordering_violations.append(
                    {
                        "component_id": cid,
                        "step_id": step_id,
                        "reason": "missing_placement_transform_step",
                    }
                )
                continue
            if idx < placement_idx:
                ordering_violations.append(
                    {
                        "component_id": cid,
                        "step_id": step_id,
                        "reason": "step_executes_before_initial_placement",
                        "step_index": idx,
                        "placement_step_index": placement_idx,
                    }
                )

    if ordering_violations:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "violations": len(ordering_violations),
            },
            "violations": ordering_violations,
        }
        _write_json(run_dir / "planning" / "errors" / "placement_before_modeling_violations.json", payload)
        raise RuntimeError(
            "placement_before_modeling_violation: component modeling step executes before initial placement. "
            "See planning/errors/placement_before_modeling_violations.json"
        )

    report["skipped_count"] = len(report.get("skipped") or [])
    return out_steps


def _is_identity_transform_mm(transform_mm: Any, *, eps: float = 1e-12) -> bool:
    if not isinstance(transform_mm, Mapping):
        return True
    translation_raw = transform_mm.get("translation")
    rotation_raw = transform_mm.get("rotation_rpy_deg")
    translation = translation_raw if isinstance(translation_raw, Mapping) else {}
    rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
    try:
        tx = float(translation.get("x", 0.0))
        ty = float(translation.get("y", 0.0))
        tz = float(translation.get("z", 0.0))
        roll = float(rotation.get("roll", 0.0))
        pitch = float(rotation.get("pitch", 0.0))
        yaw = float(rotation.get("yaw", 0.0))
    except Exception:
        return False
    return (
        abs(tx) <= eps
        and abs(ty) <= eps
        and abs(tz) <= eps
        and abs(roll) <= eps
        and abs(pitch) <= eps
        and abs(yaw) <= eps
    )


def audit_occurrence_transforms(
    plan_steps: List[Dict[str, Any]], *, run_dir: Path, round_index: int
) -> Dict[str, Any]:
    """Static audit for SET_OCCURRENCE_TRANSFORM_R1 writes.

    Hard constraints:
    - Same occurrence_name must not have >=2 non-identity transforms.
    - Total transform steps must equal initial_placements count for this round.
    """
    # Map CREATE_COMPONENT capture vars -> occurrence_name
    var_to_occ_name: Dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "CREATE_COMPONENT":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occ_name = inputs.get("name")
        if not isinstance(occ_name, str) or not occ_name:
            continue
        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        for var_name, out_key in vars_map.items():
            if out_key == "occurrence_id" and isinstance(var_name, str) and var_name:
                var_to_occ_name[var_name] = occ_name

    def _occ_name_from_transform_step(step: Mapping[str, Any]) -> str:
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occ_id = inputs.get("occurrence_id")
        if isinstance(occ_id, str) and occ_id.startswith("${") and occ_id.endswith("}"):
            var = occ_id[2:-1]
            if var in var_to_occ_name:
                return var_to_occ_name[var]
        # Fallbacks
        if isinstance(occ_id, str) and occ_id:
            return occ_id
        return "<unknown>"

    by_occ: Dict[str, List[Dict[str, Any]]] = {}
    total = 0
    non_identity = 0
    for step in plan_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "SET_OCCURRENCE_TRANSFORM_R1":
            continue
        total += 1
        occ_name = _occ_name_from_transform_step(step)
        sid = step.get("id")
        step_id = sid if isinstance(sid, str) else "<missing_id>"
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        identity = _is_identity_transform_mm(inputs.get("transform_mm"))
        if not identity:
            non_identity += 1
        by_occ.setdefault(occ_name, []).append(
            {
                "step_id": step_id,
                "identity": identity,
                "mode": inputs.get("mode"),
                "occurrence_id": inputs.get("occurrence_id"),
            }
        )

    expected: int | None = None
    try:
        placements = _load_initial_placements(run_dir, round_index=round_index)
        defined = _collect_defined_vars(plan_steps)
        expected = 0
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            cid = placement.get("component_id")
            if not isinstance(cid, str) or not cid:
                continue
            component_var = f"{cid}_component_id"
            occurrence_var = f"{cid}_occurrence_id"
            if component_var not in defined or occurrence_var not in defined:
                continue
            parent = placement.get("parent_assembly")
            if isinstance(parent, str) and parent and parent != "root":
                parent_var = f"{parent}_component_id"
                if parent_var not in defined:
                    continue
            expected += 1
    except Exception:
        expected = None

    report: Dict[str, Any] = {
        "metadata": {
            "source": "Agent5_compose_plan.audit_occurrence_transforms",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "round_index": int(round_index),
        },
        "summary": {
            "expected_placements": expected,
            "transform_steps_total": total,
            "transform_steps_non_identity": non_identity,
            "occurrence_count": len(by_occ),
        },
        "by_occurrence": by_occ,
        "violations": [],
    }

    if expected is not None and total != expected:
        report.setdefault("warnings", []).append(
            {
                "type": "transform_count_mismatch",
                "expected": expected,
                "found": total,
            }
        )

    for occ_name, recs in by_occ.items():
        non_id = [r for r in recs if not r.get("identity")]
        if len(non_id) >= 2:
            report["violations"].append(
                {
                    "type": "multi_non_identity_transform",
                    "occurrence_name": occ_name,
                    "non_identity_steps": non_id,
                }
            )

    if report["violations"]:
        out_path = run_dir / "planning" / "errors" / "multi_transform_violation.json"
        _write_json(out_path, report)
        raise RuntimeError(
            "multi_transform_violation: occurrence transform written multiple times. "
            f"details={json.dumps(report, ensure_ascii=False)}"
        )

    return report


def run(
    *,
    run_dir: Path,
    round_index: int,
    plan_schema_path: Path | None = None,
    geometry_plan_path: Path | None = None,
    assembly_patch_path: Path | None = None,
) -> None:
    plan_schema_path = plan_schema_path or (Path("planning") / "function_plan_schema.json")
    # Agent3b outputs geometry_plan_round_N.json (geometry plan with function calls)
    geometry_plan_path = geometry_plan_path or (run_dir / "planning" / f"geometry_plan_round_{round_index}.json")
    # Agent4 outputs assembly_patch_round_N.json (assembly steps)
    assembly_patch_path = assembly_patch_path or (run_dir / "planning" / f"assembly_patch_round_{round_index}.json")

    if not plan_schema_path.exists():
        raise SystemExit(f"Plan schema not found: {plan_schema_path}")
    if not geometry_plan_path.exists():
        raise SystemExit(f"Geometry plan not found: {geometry_plan_path}")
    # Assembly is optional while Agent4 is being upgraded (LLM-guided).
    # If missing, compose geometry-only plan.
    assembly_patch: Mapping[str, Any]
    if not assembly_patch_path.exists():
        assembly_patch = {"metadata": {"missing": True}, "steps": []}
    else:
        assembly_patch = _read_json(assembly_patch_path)
        if not isinstance(assembly_patch, Mapping):
            raise ValueError("assembly_patch must be an object")

    geometry_plan = _read_json(geometry_plan_path)
    if not isinstance(geometry_plan, Mapping):
        raise ValueError("geometry_plan must be an object")

    # assembly_patch loaded above

    geometry_steps = geometry_plan.get("steps")
    if not isinstance(geometry_steps, list):
        raise ValueError("geometry_plan.steps must be a list")

    assembly_steps_raw = assembly_patch.get("steps")
    assembly_steps = assembly_steps_raw if isinstance(assembly_steps_raw, list) else []

    # Ensure we only combine dict steps.
    geometry_steps2: List[Dict[str, Any]] = [s for s in geometry_steps if isinstance(s, Mapping)]  # type: ignore[list-item]
    assembly_steps2: List[Dict[str, Any]] = [s for s in assembly_steps if isinstance(s, Mapping)]  # type: ignore[list-item]

    assembly_steps2 = _ensure_unique_step_ids_between(geometry_steps2, assembly_steps2, prefix="asm")

    geometry_end_step_id = _last_step_id(geometry_steps2)
    if geometry_end_step_id is None:
        raise ValueError("geometry_plan has no valid step id; cannot compose Agent5 phases")

    instancing_map = _load_instancing_map(run_dir)
    connection_alias_map = _load_connection_canonical_map(run_dir, instancing_map=instancing_map)

    # Phase 1: geometry (Agent3b)
    geometry_phase_steps: List[Dict[str, Any]] = list(geometry_steps2)
    geometry_phase_steps, symmetry_fold_report = _fold_symmetric_connection_geometry_steps(
        geometry_phase_steps,
        instancing_map=instancing_map,
        connection_alias_map=connection_alias_map,
    )
    geometry_phase_steps, instance_var_map, instancing_report = _merge_instanced_geometry_steps(
        geometry_phase_steps,
        run_dir=run_dir,
        round_index=round_index,
        instancing_map=instancing_map,
    )
    instancing_geometry_audit = _audit_instance_specific_geometry_steps(
        geometry_steps=geometry_phase_steps,
        instancing_map=instancing_map,
        run_dir=run_dir,
        round_index=round_index,
    )

    # Phase 2: Standard-part insertion is completed upstream in Agent3b.
    # Agent5 must not re-insert standard parts to avoid duplicate INSERT/capture chains.
    stdpart_phase_steps: List[Dict[str, Any]] = []

    if instance_var_map:
        assembly_steps2 = _rewrite_step_placeholders(assembly_steps2, instance_var_map)

    stdpart_alias_map = _build_stdpart_instance_var_alias_map(geometry_phase_steps)
    if stdpart_alias_map:
        assembly_steps2 = _rewrite_step_placeholders(assembly_steps2, stdpart_alias_map)

    assembly_steps2 = _upgrade_instanced_regular_joints_to_as_built(assembly_steps2)

    # Knife 3: hard-filter any assembly step that touches a hosted-standard-part component.
    # Agent4 already skips these at the relation compile level; this is the Agent5 enforcement
    # gate that prevents such steps from entering merged_steps even if they somehow survived.
    _hosted_standard_component_ids: set[str] = set()
    _non_exec_rels = assembly_patch.get("non_executable_relations")
    if isinstance(_non_exec_rels, list):
        for _rel in _non_exec_rels:
            if not isinstance(_rel, Mapping):
                continue
            if _rel.get("relation_execution_policy") != "hosted_anchor_only":
                continue
            for _ep_key in ("from", "to"):
                _ep = _rel.get(_ep_key)
                if isinstance(_ep, Mapping):
                    _cid = _ep.get("component_id")
                    if isinstance(_cid, str) and _cid:
                        _hosted_standard_component_ids.add(_cid)
            for _hosted_cid in (_rel.get("hosted_endpoints") or []):
                if isinstance(_hosted_cid, str) and _hosted_cid:
                    _hosted_standard_component_ids.add(_hosted_cid)
    if _hosted_standard_component_ids:
        _filtered_assembly_steps: List[Dict[str, Any]] = []
        _removed_hosted_step_ids: set[str] = set()
        for _step in assembly_steps2:
            if any(_step_touches_component(_step, _hcid) for _hcid in _hosted_standard_component_ids):
                _sid = _step.get("id")
                if isinstance(_sid, str) and _sid:
                    _removed_hosted_step_ids.add(_sid)
                continue
            _filtered_assembly_steps.append(_step)
        _filtered_assembly_steps, _removed_all_step_ids = _drop_steps_with_removed_dependencies(
            _filtered_assembly_steps,
            removed_step_ids=_removed_hosted_step_ids,
        )
        if len(_filtered_assembly_steps) < len(assembly_steps2):
            _dropped_count = len(assembly_steps2) - len(_filtered_assembly_steps)
            _dependency_pruned_count = max(0, len(_removed_all_step_ids) - len(_removed_hosted_step_ids))
            _suffix = ""
            if _dependency_pruned_count:
                _suffix = f" (including {_dependency_pruned_count} dependent downstream step(s))"
            print(
                f"[INFO] Agent5 Knife-3 guard: removed {_dropped_count} assembly step(s) "
                f"{_suffix}"
                f"that touch hosted standard part component(s): "
                f"{', '.join(sorted(_hosted_standard_component_ids))}"
            )
        assembly_steps2 = _filtered_assembly_steps

    geometry_phase_steps = _inject_initial_placements(        list(geometry_phase_steps),
        run_dir=run_dir,
        round_index=round_index,
        instancing_map=instancing_map,
        var_alias_map=stdpart_alias_map,
    )

    geometry_end_step_id = _last_step_id(geometry_phase_steps) or geometry_end_step_id
    stdparts_end_step_id = _last_step_id(stdpart_phase_steps) or geometry_end_step_id
    geometry_step_ids = {
        sid for sid in (step.get("id") for step in geometry_phase_steps) if isinstance(sid, str) and sid
    }

    # Phase 3: assembly (Agent4) 闁?default to stdparts end dependency.
    assembly_phase_steps: List[Dict[str, Any]] = []
    for raw in assembly_steps2:
        step = _dedupe_depends_on(dict(raw))
        deps = step.get("depends_on")
        if not isinstance(deps, list) or not deps:
            step["depends_on"] = [stdparts_end_step_id]
        else:
            explicit_deps = [d for d in deps if isinstance(d, str)]
            only_geometry = bool(explicit_deps) and all(d in geometry_step_ids for d in explicit_deps)
            if not only_geometry and stdparts_end_step_id not in explicit_deps:
                step["depends_on"] = explicit_deps + [stdparts_end_step_id]
            else:
                step["depends_on"] = explicit_deps
        assembly_phase_steps.append(step)

    merged_steps = list(geometry_phase_steps) + list(stdpart_phase_steps) + list(assembly_phase_steps)
    merged_steps = _add_var_based_dependencies(merged_steps)

    phase_rank_by_id: Dict[str, int] = {}
    for step in geometry_phase_steps:
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            phase_rank_by_id[sid] = 0
    for step in stdpart_phase_steps:
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            phase_rank_by_id[sid] = 1
    for step in assembly_phase_steps:
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            phase_rank_by_id[sid] = 2

    merged_steps = _deterministic_topological_sort(merged_steps, phase_rank_by_id=phase_rank_by_id)

    if isinstance(symmetry_fold_report, Mapping) and int(symmetry_fold_report.get("removed_steps", 0) or 0) > 0:
        _write_json(
            run_dir / "planning" / "symmetry_fold_report.json",
            {
                "round_index": int(round_index),
                "source": "Agent5_compose_plan.symmetric_connection_fold",
                "report": dict(symmetry_fold_report),
            },
        )

    if isinstance(instancing_geometry_audit, Mapping):
        _write_json(
            run_dir / "planning" / "instancing_geometry_audit.json",
            {
                "round_index": int(round_index),
                "source": "Agent5_compose_plan.instancing_geometry_audit",
                "report": dict(instancing_geometry_audit),
            },
        )

    merged_steps, compression_report = _compress_redundant_activate_steps(merged_steps)

    # Enforce single placement source of truth.
    audit_occurrence_transforms(merged_steps, run_dir=run_dir, round_index=round_index)

    fallback_threshold_raw = os.getenv("FUSION_FALLBACK_REVIEW_THRESHOLD", "0.30")
    try:
        fallback_threshold = float(fallback_threshold_raw)
    except Exception:
        fallback_threshold = 0.30
    fallback_threshold = max(0.0, min(1.0, fallback_threshold))

    intent_changed_threshold_raw = os.getenv("FUSION_INTENT_CHANGED_REVIEW_THRESHOLD", "0.35")
    try:
        intent_changed_threshold = float(intent_changed_threshold_raw)
    except Exception:
        intent_changed_threshold = 0.25
    intent_changed_threshold = max(0.0, min(1.0, intent_changed_threshold))

    clean_fallback_threshold_raw = os.getenv("FUSION_CLEAN_FALLBACK_REVIEW_THRESHOLD", "0.65")
    try:
        clean_fallback_threshold = float(clean_fallback_threshold_raw)
    except Exception:
        clean_fallback_threshold = 0.65
    clean_fallback_threshold = max(0.0, min(1.0, clean_fallback_threshold))

    clean_intent_changed_threshold_raw = os.getenv("FUSION_CLEAN_INTENT_CHANGED_REVIEW_THRESHOLD", "0.45")
    try:
        clean_intent_changed_threshold = float(clean_intent_changed_threshold_raw)
    except Exception:
        clean_intent_changed_threshold = 0.45
    clean_intent_changed_threshold = max(0.0, min(1.0, clean_intent_changed_threshold))

    feasibility_report_path = run_dir / "planning" / "errors" / "geometry_semantics_feasibility.json"
    feasibility_summary: Mapping[str, Any] | None = None
    if feasibility_report_path.exists():
        try:
            feasibility_report = _read_json(feasibility_report_path)
        except Exception:
            feasibility_report = None

        if isinstance(feasibility_report, Mapping):
            summary = feasibility_report.get("summary") if isinstance(feasibility_report.get("summary"), Mapping) else {}
            feasibility_summary = summary if isinstance(summary, Mapping) else None
            checked = int(summary.get("placements_checked")) if isinstance(summary.get("placements_checked"), int) else 0
            fallback_count = int(summary.get("fallback_count")) if isinstance(summary.get("fallback_count"), int) else 0
            fallback_ratio = summary.get("fallback_ratio") if isinstance(summary.get("fallback_ratio"), (int, float)) else None
            if fallback_ratio is None:
                fallback_ratio = (float(fallback_count) / float(checked)) if checked > 0 else 0.0

            intent_changed_count = int(summary.get("intent_changed_count")) if isinstance(summary.get("intent_changed_count"), int) else 0
            blocked_count = int(summary.get("blocked_count")) if isinstance(summary.get("blocked_count"), int) else 0
            needs_clarification_count = int(summary.get("needs_clarification_count")) if isinstance(summary.get("needs_clarification_count"), int) else 0
            intent_changed_ratio = (float(intent_changed_count) / float(checked)) if checked > 0 else 0.0
            valid_flag = bool(summary.get("valid") is True)
            clean_feasibility = valid_flag and blocked_count == 0 and needs_clarification_count == 0
            effective_fallback_threshold = clean_fallback_threshold if clean_feasibility else fallback_threshold
            effective_intent_changed_threshold = (
                clean_intent_changed_threshold if clean_feasibility else intent_changed_threshold
            )

            if blocked_count > 0:
                review_payload = {
                    "status": "needs_review",
                    "reason": "feasibility_not_clean",
                    "thresholds": {
                        "fallback_ratio": effective_fallback_threshold,
                        "intent_changed_ratio": effective_intent_changed_threshold,
                    },
                    "observed": {
                        "placements_checked": checked,
                        "fallback_count": fallback_count,
                        "fallback_ratio": round(float(fallback_ratio), 4),
                        "intent_changed_count": intent_changed_count,
                        "intent_changed_ratio": round(float(intent_changed_ratio), 4),
                        "blocked_count": blocked_count,
                        "needs_clarification_count": needs_clarification_count,
                    },
                    "source": str(feasibility_report_path).replace("\\", "/"),
                }
                review_path = run_dir / "planning" / "fallback_review_gate.json"
                _write_json(review_path, review_payload)
                raise ValueError(
                    "Agent5 quality gate blocked plan composition: "
                    f"blocked_count={blocked_count}, needs_clarification_count={needs_clarification_count}. "
                    f"Marked as needs_review at: {review_path}"
                )

            if (
                checked > 0
                and float(fallback_ratio) > effective_fallback_threshold
                and float(intent_changed_ratio) > effective_intent_changed_threshold
            ):
                review_payload = {
                    "status": "needs_review",
                    "reason": "fallback_and_intent_changed_ratio_exceed_threshold",
                    "thresholds": {
                        "fallback_ratio": effective_fallback_threshold,
                        "intent_changed_ratio": effective_intent_changed_threshold,
                    },
                    "observed": {
                        "placements_checked": checked,
                        "fallback_count": fallback_count,
                        "fallback_ratio": round(float(fallback_ratio), 4),
                        "intent_changed_count": intent_changed_count,
                        "intent_changed_ratio": round(float(intent_changed_ratio), 4),
                        "blocked_count": blocked_count,
                        "needs_clarification_count": needs_clarification_count,
                    },
                    "source": str(feasibility_report_path).replace("\\", "/"),
                }
                review_path = run_dir / "planning" / "fallback_review_gate.json"
                _write_json(review_path, review_payload)
                raise ValueError(
                    "Agent5 quality gate blocked plan composition: "
                    f"fallback_ratio={float(fallback_ratio):.3f} exceeds threshold={effective_fallback_threshold:.3f} and "
                    f"intent_changed_ratio={float(intent_changed_ratio):.3f} exceeds threshold={effective_intent_changed_threshold:.3f}. "
                    f"Marked as needs_review at: {review_path}"
                )

    interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
    interface_manifest: Mapping[str, Any] | None = None
    if interface_manifest_path.exists():
        payload = _read_json(interface_manifest_path)
        if isinstance(payload, Mapping):
            interface_manifest = payload

    modeling_semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    modeling_semantics: Mapping[str, Any] | None = None
    if modeling_semantics_path.exists():
        payload = _read_json(modeling_semantics_path)
        if isinstance(payload, Mapping):
            modeling_semantics = payload

    _validate_interface_contract_closure(
        run_dir=run_dir,
        round_index=round_index,
        interface_manifest=interface_manifest,
        modeling_semantics=modeling_semantics,
        merged_steps=merged_steps,
        assembly_patch=assembly_patch,
        component_alias_map=instancing_map,
    )

    modeling_semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    modeling_semantics: Mapping[str, Any] | None = None
    if modeling_semantics_path.exists():
        try:
            payload = _read_json(modeling_semantics_path)
        except Exception:
            payload = None
        if isinstance(payload, Mapping):
            modeling_semantics = payload

    _validate_interface_contract_consistency(
        run_dir=run_dir,
        round_index=round_index,
        modeling_semantics=modeling_semantics,
        interface_manifest=interface_manifest,
        component_alias_map=instancing_map,
    )

    _gate_hole_orientation_plane_requirement(
        run_dir=run_dir,
        round_index=round_index,
        merged_steps=merged_steps,
    )

    function_registry = _load_function_registry()
    link_report = run_linker_pass(
        steps=merged_steps,
        function_registry=function_registry,
        interface_manifest=interface_manifest,
        assembly_patch=assembly_patch,
        feasibility_summary=feasibility_summary,
        fallback_threshold=fallback_threshold,
        intent_changed_threshold=intent_changed_threshold,
    )
    link_summary = link_report.get("summary") if isinstance(link_report.get("summary"), Mapping) else {}
    link_error_count = link_summary.get("error_count") if isinstance(link_summary.get("error_count"), int) else 0
    if link_error_count > 0:
        link_errors_path = run_dir / "planning" / "errors" / "link_errors.json"
        _write_json(link_errors_path, link_report)

        out_round = run_dir / "planning" / f"function_plan_round_{round_index}.json"
        out_current = run_dir / "planning" / "function_plan.json"
        for stale in (out_round, out_current):
            try:
                if stale.exists():
                    stale.unlink()
            except Exception:
                pass

        raise ValueError(
            f"Agent5 linker failed with {link_error_count} errors. "
            f"See: {link_errors_path}"
        )

    # Compose metadata.
    md = geometry_plan.get("metadata")
    plan_id = f"{run_dir.name}_function_plan_round_{round_index}"
    if isinstance(md, Mapping):
        base = md.get("plan_id")
        if isinstance(base, str) and base.strip():
            plan_id = base.strip().replace("_geometry_", "_")

    artifacts: Dict[str, Any] = {"round_index": round_index}
    g_art = geometry_plan.get("artifacts")
    if isinstance(g_art, Mapping):
        artifacts.update(dict(g_art))
    a_art = assembly_patch.get("artifacts")
    if isinstance(a_art, Mapping):
        artifacts["assembly_plan"] = dict(a_art)

    plan: Dict[str, Any] = {
        "metadata": {
            "plan_id": plan_id,
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "author": "compose_plan",
            "capability_registry": {"path": "functions/functions.json"},
            "notes": "Composed plan: geometry + assembly.",
            "compression": {
                "activate_redundancy": compression_report,
                "instancing": instancing_report,
            },
        },
        "steps": merged_steps,
        "artifacts": artifacts,
    }

    _validate_json(plan, plan_schema_path)
    _assert_no_unresolved_placeholders(merged_steps)
    _lint_no_index_pointer_captures(merged_steps)

    # Output 1: Planning archive (versioned + current)
    out_round = run_dir / "planning" / f"function_plan_round_{round_index}.json"
    out_current = run_dir / "planning" / "function_plan.json"
    _write_json(out_round, plan)
    _write_json(out_current, plan)
    
    print("[OK] Generated function plan:")
    try:
        rel = out_round.relative_to(Path.cwd())
        print(f"  - Planning archive: {rel}")
    except Exception:
        print(f"  - Planning archive: {out_round}")
    try:
        rel_current = out_current.relative_to(Path.cwd())
        print(f"  - Current plan: {rel_current}")
    except Exception:
        print(f"  - Current plan: {out_current}")
    print(f"\n[INFO] Next step: Open Fusion 360 and run fusion_api_server/fusion_api_server.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose plan agent (run-dir IO).")
    parser.add_argument("--run-dir", dest="run_dir", required=True)
    parser.add_argument("--round-index", dest="round_index", type=int, required=True)
    parser.add_argument("--schema", dest="schema_path", default=None)
    parser.add_argument("--geometry", dest="geometry_path", default=None)
    parser.add_argument("--assembly", dest="assembly_path", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    schema_path = Path(args.schema_path) if args.schema_path else None
    geometry_path = Path(args.geometry_path) if args.geometry_path else None
    assembly_path = Path(args.assembly_path) if args.assembly_path else None

    run(
        run_dir=run_dir,
        round_index=args.round_index,
        plan_schema_path=schema_path,
        geometry_plan_path=geometry_path,
        assembly_patch_path=assembly_path,
    )


if __name__ == "__main__":
    main()





