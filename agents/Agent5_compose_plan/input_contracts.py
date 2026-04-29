"""Input loading and contract validation helpers for Agent5."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from agents.common_utils import read_json as _read_json, write_json as _write_json


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
