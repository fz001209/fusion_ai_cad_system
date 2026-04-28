"""
plan_assembly 智能体（装配语义规划器）

系统角色：
- Agent4 从知识图谱和几何-装配契约中推导装配语义。它声明"什么"连接到"什么"，以及使用什么连接类型。
- 新功能：LLM 辅助推理，适用于任意装配体（不局限于预定义模型）

边界约束（严格）：
- Agent3（shape_realization_planner）：仅决定如何建模单个零件
- Agent4（本智能体）：仅决定装配关系，不执行，不排序
- Agent5（CAD 编译器）：执行装配并生成 CAD 操作
- 禁止：CAD 执行、Fusion API 调用、装配顺序、空间坐标、自由度数值

决策权限模型：
- KG 关系始终被包含（真值来源）
- LLM 为任意装配体提出额外关系
- 确定性规则验证所有关系（KG + LLM）
- 无效关系被拒绝并记录覆盖
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set, Tuple

from agents.common_utils import read_json as _read_json, write_json as _write_json, collect_defined_vars as _collect_defined_vars


REALIZATION_CLASS_NATIVE = "native_functional_part"
REALIZATION_CLASS_HOSTED_STANDARD = "hosted_standard_part"
REALIZATION_CLASS_KINEMATIC_IMPORTED = "kinematic_imported_part"

_HOSTED_STANDARD_COMPONENT_TYPES = {
    "bearing",
    "fastener",
    "fastener_set",
    "bolt",
    "screw",
    "nut",
    "washer",
}


def _load_shape_realization_classes(run_dir: Path, round_index: int) -> Dict[str, str]:
    out: Dict[str, str] = {}
    path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    if not path.exists():
        return out
    try:
        payload = _read_json(path)
    except Exception:
        return out
    if not isinstance(payload, Mapping):
        return out

    for key in ("parts", "component_realizations"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cid = row.get("component_id") if isinstance(row.get("component_id"), str) else None
            rc = row.get("realization_class") if isinstance(row.get("realization_class"), str) else None
            if isinstance(cid, str) and cid and isinstance(rc, str) and rc:
                out[cid] = rc

    return out


def _load_standard_part_bound_component_ids(run_dir: Path) -> Set[str]:
    out: Set[str] = set()
    path = run_dir / "planning" / "standard_parts_resolved.json"
    if not path.exists():
        return out
    try:
        payload = _read_json(path)
    except Exception:
        return out
    if not isinstance(payload, Mapping):
        return out
    resolved = payload.get("resolved")
    if not isinstance(resolved, list):
        return out
    for part in resolved:
        if not isinstance(part, Mapping):
            continue
        bound_ids = part.get("bound_component_ids")
        if isinstance(bound_ids, list):
            for cid in bound_ids:
                if isinstance(cid, str) and cid:
                    out.add(cid)
        pid = part.get("id")
        if isinstance(pid, str) and pid:
            out.add(pid)
    return out


def _build_component_realization_class_map(
    *,
    knowledge_graph: Mapping[str, Any],
    run_dir: Path,
    round_index: int,
) -> Dict[str, str]:
    class_map: Dict[str, str] = {}

    components = knowledge_graph.get("components") if isinstance(knowledge_graph.get("components"), list) else []
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id") if isinstance(comp.get("id"), str) else None
        if not isinstance(cid, str) or not cid:
            continue

        declared = comp.get("realization_class") if isinstance(comp.get("realization_class"), str) else None
        if isinstance(declared, str) and declared in {
            REALIZATION_CLASS_NATIVE,
            REALIZATION_CLASS_HOSTED_STANDARD,
            REALIZATION_CLASS_KINEMATIC_IMPORTED,
        }:
            class_map[cid] = declared
            continue

        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in _HOSTED_STANDARD_COMPONENT_TYPES:
            class_map[cid] = REALIZATION_CLASS_HOSTED_STANDARD
            continue

        import_strategy = str(comp.get("import_strategy") or "").strip().lower()
        execution_role = str(comp.get("execution_role") or "").strip().lower()
        if import_strategy in {"kinematic_imported", "kinematic_imported_part"} or execution_role in {
            "kinematic_imported",
            "kinematic_imported_part",
        }:
            class_map[cid] = REALIZATION_CLASS_KINEMATIC_IMPORTED
            continue

        class_map[cid] = REALIZATION_CLASS_NATIVE

    class_map.update(_load_shape_realization_classes(run_dir, round_index))

    for cid in _load_standard_part_bound_component_ids(run_dir):
        class_map[cid] = REALIZATION_CLASS_HOSTED_STANDARD

    return class_map


def _write_preflight_resolved_interfaces(
    *,
    run_dir: Path,
    round_index: int,
    compiled_constraints: List[Dict[str, Any]],
    unresolved_relations: List[Dict[str, Any]],
    interface_manifest: Dict[str, Any] | None,
) -> None:
    manifest_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if isinstance(interface_manifest, dict):
        components = interface_manifest.get("components")
        if isinstance(components, list):
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                component_id = comp.get("component_id")
                if not isinstance(component_id, str) or not component_id:
                    continue
                interfaces = comp.get("interfaces")
                if not isinstance(interfaces, list):
                    continue
                for iface in interfaces:
                    if not isinstance(iface, dict):
                        continue
                    interface_name = iface.get("interface_name")
                    if not isinstance(interface_name, str) or not interface_name:
                        continue
                    resolution = iface.get("resolution")
                    if isinstance(resolution, dict):
                        manifest_map[(component_id, interface_name)] = resolution

    def _iter_endpoints(rel: Dict[str, Any]) -> List[Tuple[str, str, str]]:
        relation_id_raw = rel.get("relation_id")
        relation_id = relation_id_raw if isinstance(relation_id_raw, str) and relation_id_raw else "unknown_relation"
        out: List[Tuple[str, str, str]] = []
        for endpoint_name in ("from", "to"):
            endpoint_raw = rel.get(endpoint_name)
            endpoint = endpoint_raw if isinstance(endpoint_raw, dict) else {}
            component_id = endpoint.get("component_id")
            interface_name = endpoint.get("interface_id")
            if isinstance(component_id, str) and component_id and isinstance(interface_name, str) and interface_name:
                out.append((relation_id, component_id, interface_name))
        return out

    rows: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str]] = set()

    for rel in compiled_constraints:
        for relation_id, component_id, interface_name in _iter_endpoints(rel):
            key = (component_id, interface_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            resolution = manifest_map.get(key, {})
            resolved_token = resolution.get("resolved_token") if isinstance(resolution, dict) else None
            token_info = resolved_token if isinstance(resolved_token, dict) else {}
            token_id_raw = token_info.get("token_id")
            entity_kind_raw = token_info.get("entity_kind")
            entity_id_raw = token_info.get("entity_id")
            geometry_summary_raw = token_info.get("geometry_summary")

            rows.append(
                {
                    "relation_id": relation_id,
                    "component_id": component_id,
                    "interface_name": interface_name,
                    "token_id": token_id_raw if isinstance(token_id_raw, str) and token_id_raw else f"ifc:{component_id}:{interface_name}",
                    "entity_kind": entity_kind_raw if isinstance(entity_kind_raw, str) and entity_kind_raw else None,
                    "entity_id": entity_id_raw if isinstance(entity_id_raw, str) and entity_id_raw else None,
                    "geometry_summary": geometry_summary_raw if isinstance(geometry_summary_raw, dict) else None,
                    "status": "preflight_compiled",
                }
            )

    for rel in unresolved_relations:
        reason_code = rel.get("reason_code") if isinstance(rel.get("reason_code"), str) else "unknown"
        for relation_id, component_id, interface_name in _iter_endpoints(rel):
            key = (component_id, interface_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(
                {
                    "relation_id": relation_id,
                    "component_id": component_id,
                    "interface_name": interface_name,
                    "token_id": f"ifc:{component_id}:{interface_name}",
                    "entity_kind": None,
                    "entity_id": None,
                    "geometry_summary": None,
                    "status": "preflight_unresolved",
                    "reason_code": reason_code,
                }
            )

    payload = {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "agent4_plan_assembly_preflight",
            "round_index": round_index,
            "note": "Preflight interface evidence generated before compose/dispatcher",
        },
        "interfaces": rows,
    }
    _write_json(run_dir / "planning" / f"preflight_resolved_interfaces_round_{round_index}.json", payload)


def _write_preflight_execution_context(
    *,
    run_dir: Path,
    round_index: int,
    external_vars: Set[str],
) -> None:
    component_map: Dict[str, Dict[str, str]] = {}
    context_vars: Dict[str, str] = {}

    for var_name in sorted(external_vars):
        if not isinstance(var_name, str):
            continue
        if var_name.endswith("_component_id"):
            prefix = var_name[: -len("_component_id")]
            component_id = prefix
            context_vars[var_name] = component_id
            row = component_map.setdefault(component_id, {})
            row["component_id"] = component_id
            row.setdefault("occurrence_id", f"occ::{component_id}")
            row.setdefault("body_id", f"bd::{component_id}")
        elif var_name.endswith("_occurrence_id"):
            prefix = var_name[: -len("_occurrence_id")]
            component_id = prefix
            occurrence_id = f"occ::{component_id}"
            context_vars[var_name] = occurrence_id
            row = component_map.setdefault(component_id, {})
            row.setdefault("component_id", component_id)
            row["occurrence_id"] = occurrence_id
            row.setdefault("body_id", f"bd::{component_id}")
        elif var_name.endswith("_body_id"):
            prefix = var_name[: -len("_body_id")]
            component_id = prefix
            body_id = f"bd::{component_id}"
            context_vars[var_name] = body_id
            row = component_map.setdefault(component_id, {})
            row.setdefault("component_id", component_id)
            row.setdefault("occurrence_id", f"occ::{component_id}")
            row["body_id"] = body_id

    payload = {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "agent4_plan_assembly_preflight",
            "round_index": round_index,
            "status": "preflight_compiled",
            "note": "Preflight execution context synthesized before dispatcher dryrun",
        },
        "component_bindings": [
            {
                "component_id": comp_id,
                "occurrence_id": data.get("occurrence_id"),
                "body_id": data.get("body_id"),
            }
            for comp_id, data in sorted(component_map.items())
        ],
        "vars": context_vars,
    }
    _write_json(run_dir / "planning" / f"preflight_context_round_{round_index}.json", payload)


def _iter_interface_declarations(modeling_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    declarations: List[Dict[str, Any]] = []

    top_level = modeling_payload.get("interface_declarations")
    if isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, dict):
                declarations.append(item)

    parts = modeling_payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            per_part = part.get("interface_declarations")
            if isinstance(per_part, list):
                for item in per_part:
                    if isinstance(item, dict):
                        declarations.append(item)

    return declarations


def _load_function_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Function registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _require_function(allowed: Dict[str, Any], name: str) -> None:
    if name not in allowed:
        raise ValueError(f"Required function '{name}' missing from registry")


def _pick_function(allowed: Dict[str, Any], candidates: List[str], *, label: str) -> str:
    for name in candidates:
        if name in allowed:
            return name
    choices = ", ".join(candidates)
    raise ValueError(f"No available function for {label}. Tried: {choices}")


def _component_var_ref(component_id: str) -> str:
    """Map a logical component id to its execution-time component_id variable."""
    safe_id = component_id.replace("-", "_")
    return f"${{{safe_id}_component_id}}"


def _build_component_alias_map(knowledge_graph: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    components = knowledge_graph.get("components") if isinstance(knowledge_graph.get("components"), list) else []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        definition_id = comp.get("definition_id")
        instanced_from = comp.get("instanced_from")
        proto = None
        if isinstance(instanced_from, str) and instanced_from and instanced_from != cid:
            proto = instanced_from
        elif isinstance(definition_id, str) and definition_id and definition_id != cid:
            proto = definition_id
        if isinstance(proto, str) and proto:
            out[cid] = proto
    return out


def _resolve_collection_component_name(name: str, available_names: Set[str]) -> str:
    """Resolve a collection/archetype name to a concrete instance if available."""
    if name in available_names:
        return name
    pattern = re.compile(rf"^{re.escape(name)}_(\d+)$")
    candidates: List[Tuple[int, str]] = []
    for candidate in available_names:
        match = pattern.match(candidate)
        if match:
            candidates.append((int(match.group(1)), candidate))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    return name


def _collect_geometry_component_names(geometry_plan: Dict[str, Any]) -> Set[str]:
    names: Set[str] = set()
    steps = geometry_plan.get("steps")
    if not isinstance(steps, list):
        return names
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") != "CREATE_COMPONENT":
            continue
        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            continue
        name = inputs.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _build_manifest_interface_index(interface_manifest: Dict[str, Any] | None) -> Set[Tuple[str, str]]:
    index: Set[Tuple[str, str]] = set()
    if not isinstance(interface_manifest, dict):
        return index
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return index
    for comp in components:
        if not isinstance(comp, dict):
            continue
        component_id = comp.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            continue
        interfaces = comp.get("interfaces")
        if not isinstance(interfaces, list):
            continue
        for iface in interfaces:
            if not isinstance(iface, dict):
                continue
            name = iface.get("interface_name") if isinstance(iface.get("interface_name"), str) else None
            iid = iface.get("interface_id") if isinstance(iface.get("interface_id"), str) else None
            if isinstance(name, str) and name:
                index.add((component_id, name))
            if isinstance(iid, str) and iid:
                index.add((component_id, iid))
    return index


def validate_assembly_contract(
    *,
    assembly_semantics: Dict[str, Any],
    interface_manifest: Dict[str, Any] | None,
    geometry_plan: Dict[str, Any] | None,
    assembly_plan: Dict[str, Any],
    component_alias_map: Mapping[str, str] | None = None,
    external_defined_vars: Set[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    steps = assembly_plan.get("steps") if isinstance(assembly_plan.get("steps"), list) else []
    constraints = assembly_plan.get("constraints") if isinstance(assembly_plan.get("constraints"), list) else []

    manifest_index = _build_manifest_interface_index(interface_manifest)
    geometry_steps = geometry_plan.get("steps") if isinstance(geometry_plan, dict) and isinstance(geometry_plan.get("steps"), list) else []
    geometry_vars = _collect_defined_vars([s for s in geometry_steps if isinstance(s, dict)])
    if isinstance(external_defined_vars, set):
        geometry_vars |= set(external_defined_vars)
    elif external_defined_vars:
        geometry_vars |= {v for v in external_defined_vars if isinstance(v, str)}
    geometry_components_from_vars: Set[str] = {
        var_name[: -len("_component_id")]
        for var_name in geometry_vars
        if isinstance(var_name, str) and var_name.endswith("_component_id") and len(var_name) > len("_component_id")
    }
    geometry_components = geometry_components_from_vars | _collect_geometry_component_names(geometry_plan or {})

    alias_map = dict(component_alias_map or {})

    def _resolve_manifest_key(component_id: str | None, interface_id: str | None) -> Tuple[str | None, str | None]:
        if not isinstance(component_id, str) or not component_id:
            return None, None
        if not isinstance(interface_id, str) or not interface_id:
            return component_id, None
        direct = (component_id, interface_id)
        if direct in manifest_index:
            return component_id, interface_id
        proto = alias_map.get(component_id)
        if isinstance(proto, str) and proto:
            fallback = (proto, interface_id)
            if fallback in manifest_index:
                return proto, interface_id
        return component_id, interface_id
    for instance_id, prototype_id in alias_map.items():
        if not isinstance(instance_id, str) or not instance_id:
            continue
        if not isinstance(prototype_id, str) or not prototype_id:
            continue
        if prototype_id in geometry_components:
            geometry_components.add(instance_id)
        if f"{prototype_id}_component_id" in geometry_vars:
            geometry_vars.add(f"{instance_id}_component_id")
        if f"{prototype_id}_body_id" in geometry_vars:
            geometry_vars.add(f"{instance_id}_body_id")

    invalid_relations: Dict[str, Dict[str, Any]] = {}
    relation_prefix: Dict[str, str] = {}
    valid_constraints: List[Dict[str, Any]] = []
    skipped_relations: List[Dict[str, Any]] = []

    for item in constraints:
        if not isinstance(item, dict):
            continue
        relation_id = item.get("relation_id") if isinstance(item.get("relation_id"), str) else "unknown_relation"
        joint_step_id = item.get("joint_step_id") if isinstance(item.get("joint_step_id"), str) else ""
        prefix = joint_step_id[:-len("_joint")] if joint_step_id.endswith("_joint") else joint_step_id
        if prefix:
            relation_prefix[relation_id] = prefix

        from_ep = item.get("from") if isinstance(item.get("from"), dict) else {}
        to_ep = item.get("to") if isinstance(item.get("to"), dict) else {}
        from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
        to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
        from_iface = from_ep.get("interface_id") if isinstance(from_ep.get("interface_id"), str) else None
        to_iface = to_ep.get("interface_id") if isinstance(to_ep.get("interface_id"), str) else None
        from_manifest_comp, from_manifest_iface = _resolve_manifest_key(from_comp, from_iface)
        to_manifest_comp, to_manifest_iface = _resolve_manifest_key(to_comp, to_iface)

        reason_code = None
        reason = None
        if not from_comp or not to_comp:
            reason_code = "missing_component_ref"
            reason = "compiled constraint endpoint missing component_id"
        elif from_comp not in geometry_components or to_comp not in geometry_components:
            reason_code = "component_not_in_geometry_plan"
            reason = "compiled constraint component not found in geometry plan"
        elif not from_iface or not to_iface:
            reason_code = "missing_interface_ref"
            reason = "compiled constraint endpoint missing interface_id"
        elif (
            (from_manifest_comp, from_manifest_iface) not in manifest_index
            or (to_manifest_comp, to_manifest_iface) not in manifest_index
        ):
            reason_code = "missing_interface_recipe"
            reason = "compiled constraint references interface not present in interface_manifest"
        else:
            required_vars = [
                f"{from_comp}_component_id",
                f"{to_comp}_component_id",
                f"{from_comp}_occurrence_id",
                f"{to_comp}_occurrence_id",
                f"{from_comp}_body_id",
                f"{to_comp}_body_id",
            ]
            missing_vars = [v for v in required_vars if v not in geometry_vars]
            if missing_vars:
                reason_code = "missing_geometry_trace"
                reason = "required geometry output vars are not traceable in geometry_plan"

        if reason_code is not None:
            invalid_relations[relation_id] = {
                "relation_id": relation_id,
                "relation_type": item.get("relation_type") if isinstance(item.get("relation_type"), str) else None,
                "status": "skipped_missing_interface",
                "reason_code": reason_code,
                "reason": reason,
                "from": {"component_id": from_comp, "interface_id": from_iface},
                "to": {"component_id": to_comp, "interface_id": to_iface},
            }
            skipped_relations.append(dict(invalid_relations[relation_id]))
        else:
            valid_constraints.append(item)

    filtered_steps: List[Dict[str, Any]] = []
    skipped_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("id") if isinstance(step.get("id"), str) else ""
        skip_detail = None
        for relation_id, info in invalid_relations.items():
            prefix = relation_prefix.get(relation_id)
            if isinstance(prefix, str) and prefix and step_id.startswith(prefix):
                skip_detail = info
                break
        if skip_detail is None:
            filtered_steps.append(step)
            continue

        skipped_steps.append(
            {
                "step_id": step_id,
                "function": step.get("function"),
                "status": "skipped_missing_interface",
                "relation_id": skip_detail.get("relation_id"),
                "reason_code": skip_detail.get("reason_code"),
                "reason": skip_detail.get("reason"),
            }
        )

    diagnostics = assembly_semantics.setdefault("diagnostics", {}) if isinstance(assembly_semantics, dict) else {}
    if isinstance(diagnostics, dict):
        diagnostics["assembly_contract_validation"] = {
            "checked_constraints": len(constraints),
            "checked_steps": len(steps),
            "skipped_constraints": len(skipped_relations),
            "skipped_steps": len(skipped_steps),
            "status": "ok" if not skipped_steps else "needs_clarification",
            "skipped_constraint_details": skipped_relations,
            "skipped_step_details": skipped_steps,
        }

    return filtered_steps, valid_constraints, skipped_relations, skipped_steps


def _strict_assembly_enabled() -> bool:
    return os.getenv("PIPELINE_STRICT_ASSEMBLY", "0").strip() == "1"


def _compute_critical_skips(skipped_or_unresolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    critical_reason_codes = {
        "missing_component_ref",
        "component_not_in_geometry_plan",
        "missing_interface_ref",
        "missing_interface_recipe",
        "missing_geometry_trace",
        "missing_endpoint_component",
        "missing_endpoint_interface",
        "missing_interface_declaration",
        "missing_execution_vars",
        "relation_conflict_dropped",
        "unconstrained_component",
    }
    critical_relation_types = {
        "rigid",
        "fixed",
        "insert",
        "fastener",
        "bolted",
    }

    critical: List[Dict[str, Any]] = []
    for item in skipped_or_unresolved:
        if not isinstance(item, dict):
            continue
        reason_code = item.get("reason_code") if isinstance(item.get("reason_code"), str) else ""
        relation_type = item.get("relation_type") if isinstance(item.get("relation_type"), str) else ""
        relation_id = item.get("relation_id") if isinstance(item.get("relation_id"), str) else ""
        rel_type_norm = relation_type.strip().lower()
        rel_id_norm = relation_id.strip().lower()

        is_critical_type = rel_type_norm in critical_relation_types
        if not is_critical_type and rel_id_norm:
            is_critical_type = any(tok in rel_id_norm for tok in ("fastener", "insert", "rigid", "fixed"))

        if reason_code in critical_reason_codes or is_critical_type:
            critical.append(item)

    return critical


def _collect_geometry_components_for_gate(geometry_plan: Dict[str, Any] | None) -> Set[str]:
    if not isinstance(geometry_plan, dict):
        return set()
    geometry_steps = geometry_plan.get("steps") if isinstance(geometry_plan.get("steps"), list) else []
    steps_list = [s for s in geometry_steps if isinstance(s, dict)]
    geometry_vars = _collect_defined_vars(steps_list)
    from_vars: Set[str] = {
        var_name[: -len("_component_id")]
        for var_name in geometry_vars
        if isinstance(var_name, str) and var_name.endswith("_component_id") and len(var_name) > len("_component_id")
    }
    return from_vars | _collect_geometry_component_names(geometry_plan)


def _collect_constrained_components(constraints: List[Dict[str, Any]]) -> Set[str]:
    constrained: Set[str] = set()
    for item in constraints:
        if not isinstance(item, dict):
            continue
        for endpoint_key in ("from", "to"):
            endpoint = item.get(endpoint_key) if isinstance(item.get(endpoint_key), dict) else {}
            component_id = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
            if isinstance(component_id, str) and component_id:
                constrained.add(component_id)
    return constrained


def _collect_conflict_drop_components(dropped_relations: List[Dict[str, Any]]) -> Set[str]:
    components: Set[str] = set()
    for item in dropped_relations:
        if not isinstance(item, dict):
            continue
        if item.get("drop_reason") != "conflict":
            continue
        occupied = item.get("occupied_endpoints") if isinstance(item.get("occupied_endpoints"), list) else []
        for endpoint in occupied:
            if not isinstance(endpoint, dict):
                continue
            cid = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
            if isinstance(cid, str) and cid:
                components.add(cid)
    return components


def _is_required_symmetric_conflict_drop(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("drop_reason") != "conflict":
        return False
    rid = item.get("relation_id") if isinstance(item.get("relation_id"), str) else ""
    rid_l = rid.lower()
    if "hub_to_arm_2" in rid_l or "hub_to_arm_3" in rid_l:
        return True
    occupied = item.get("occupied_endpoints") if isinstance(item.get("occupied_endpoints"), list) else []
    comps: Set[str] = set()
    for endpoint in occupied:
        if not isinstance(endpoint, dict):
            continue
        cid = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
        if isinstance(cid, str) and cid:
            comps.add(cid)
    if "central_hub" in comps and ("wheel_arm_2" in comps or "wheel_arm_3" in comps):
        return True
    return False


def _select_ground_root_component(knowledge_graph: Dict[str, Any], geometry_components_gate: Set[str]) -> str | None:
    explicit_root = knowledge_graph.get("root_component_id")
    if isinstance(explicit_root, str) and explicit_root:
        return explicit_root

    components = [c for c in (knowledge_graph.get("components") or []) if isinstance(c, dict)]
    support_candidates: List[str] = []
    for comp in components:
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid or cid not in geometry_components_gate:
            continue
        cid_lower = cid.lower()
        role_lower = str(comp.get("role") or "").strip().lower()
        type_lower = str(comp.get("type") or "").strip().lower()
        if (
            "support_housing" in cid_lower
            or role_lower in {"fixed_support_housing", "support_housing", "carrier", "fixed_bracket"}
            or (type_lower in {"housing", "bracket", "carrier", "hub"} and any(token in role_lower for token in ("support", "fixed")))
        ):
            support_candidates.append(cid)
    if support_candidates:
        return sorted(support_candidates)[0]
    if "central_hub" in geometry_components_gate:
        return "central_hub"
    return None


def _compute_unconstrained_components(
    *,
    geometry_components: Set[str],
    constrained_components: Set[str],
    semantic_components: Set[str],
    dropped_conflict_components: Set[str],
    ground_root: str | None,
    allowed_free_set: Set[str],
    contained_components: Set[str],
) -> List[str]:
    must_constrain = (semantic_components | dropped_conflict_components) & geometry_components
    exclusions = set(allowed_free_set)
    exclusions |= set(contained_components)
    if isinstance(ground_root, str) and ground_root:
        exclusions.add(ground_root)
    unconstrained = sorted(must_constrain - constrained_components - exclusions)
    return unconstrained


def _lint_component_refs(
    *,
    steps: List[Dict[str, Any]],
    logical_component_ids: Set[str],
    externally_defined_vars: Set[str] | None = None,
) -> None:
    """Ensure component_id/component_a/component_b use defined execution vars."""
    defined = _collect_defined_vars(steps)
    if externally_defined_vars:
        defined |= set(externally_defined_vars)

    def _extract_var(value: str) -> str | None:
        if value.startswith("${") and value.endswith("}"):
            return value[2:-1]
        return None

    for step in steps:
        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key in ("component_id", "component_a", "component_b"):
            raw = inputs.get(key)
            if not isinstance(raw, str):
                continue
            var = _extract_var(raw)
            if var is not None:
                if var not in defined:
                    raise ValueError(
                        "Assembly plan lint: unresolved component reference variable: "
                        f"step='{step.get('id')}', function='{step.get('function')}', field='{key}', value='{raw}'. "
                        "Hint: ensure CREATE_COMPONENT capture defines this variable."
                    )
                continue
            if raw in logical_component_ids:
                raise ValueError(
                    "Assembly plan lint: logical component id used where execution variable is required: "
                    f"step='{step.get('id')}', function='{step.get('function')}', field='{key}', value='{raw}'. "
                    "Hint: use _component_var_ref(component_id)."
                )


def _call_llm(prompt: str) -> tuple[str | None, Dict[str, Any]]:
    """Call OpenAI for assembly relation inference.

    Returns:
        (content, audit)
        - content: model response text or None
        - audit: non-secret diagnostics (key presence, base_url, model, error)
    """
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

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    audit["api_key_present"] = bool(api_key)
    if not api_key:
        audit["error"] = "OPENAI_API_KEY missing"
        return None, audit

    try:
        import socket
        import time
        import urllib.error
        import urllib.request

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip().rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        url = f"{base_url}/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

        timeout_s = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "180").strip() or "180")
        retries = int(os.getenv("OPENAI_MAX_RETRIES", "2").strip() or "2")
        max_attempts = max(1, 1 + max(0, retries))

        audit["base_url"] = base_url
        audit["model"] = model
        audit["attempted"] = True
        audit["timeout_seconds"] = timeout_s
        audit["max_attempts"] = max_attempts

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

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
                    return content_s, audit
                last_error = "Empty response content"
                audit["errors"].append(last_error)

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
        return None, audit

    except Exception as e:
        audit["error"] = f"{type(e).__name__}: {e}"
        return None, audit


def _extract_json(text: str) -> Dict[str, Any] | None:
    """Extract JSON from LLM response."""
    if not text:
        return None
    
    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    
    # Try extracting from code fences
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    
    # Try finding first JSON object
    m2 = re.search(r'(\{.*\})', text, re.DOTALL)
    if m2:
        try:
            obj = json.loads(m2.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    
    return None


# Canonical assembly patterns (LLM decision vocabulary)
ASSEMBLY_PATTERNS = {
    "RIGID_MATE",        # Permanent rigid connection
    "REVOLUTE_MATE",     # Rotational joint around fixed axis
    "SLIDER_MATE",       # Linear sliding joint
    "CYLINDRICAL_MATE"   # Cylindrical joint (rotation + sliding)
}

# EXECUTION MODE DEFINITIONS
EXECUTION_MODES = {
    "deterministic": {
        "description": "KG relations only (LLM disabled/unavailable, or LLM contributed 0 accepted relations)",
        "decision_authority": "Knowledge graph relations only",
        "use_case": "Deterministic baseline; LLM may be off or filtered out",
        "guarantees": "Fully reproducible, no AI variability"
    },
    "llm_guided": {
        "description": "LLM inferences fully accepted",
        "decision_authority": "LLM proposes, all pass validation",
        "use_case": "LLM available and all inferences are legal",
        "guarantees": "AI-assisted reasoning within engineering constraints"
    },
    "hybrid": {
        "description": "KG + LLM, with engineering rule enforcement",
        "decision_authority": "KG + LLM, validation overrides when necessary",
        "use_case": "Both KG and LLM used, some overrides applied",
        "guarantees": "Complete coverage with validation enforcement"
    }
}


def _is_assembly_pattern_allowed(pattern: str, from_iface: Dict[str, Any], to_iface: Dict[str, Any]) -> bool:
    """
    Validate assembly pattern against interface allowed_mate_roles.
    
    Args:
        pattern: Assembly pattern from ASSEMBLY_PATTERNS
        from_iface: Interface definition from contract
        to_iface: Interface definition from contract
    
    Returns:
        True if pattern is allowed for these interfaces
    """
    if pattern not in ASSEMBLY_PATTERNS:
        return False
    
    from_roles = set(from_iface.get("allowed_mate_roles", []))
    to_roles = set(to_iface.get("allowed_mate_roles", []))
    
    # Pattern-specific validation rules (bidirectional)
    if pattern == "RIGID_MATE":
        # At least one interface must support mounting/fixation
        mounting_roles = {"mounting", "support", "fixation"}
        return bool(from_roles & mounting_roles) or bool(to_roles & mounting_roles)
    
    elif pattern == "REVOLUTE_MATE":
        # Both interfaces must support rotation OR one rotation + one support
        rotation_roles = {"rotation"}
        support_roles = {"support", "mounting"}
        has_rotation = bool(from_roles & rotation_roles) and bool(to_roles & rotation_roles)
        has_mixed = (bool(from_roles & rotation_roles) and bool(to_roles & support_roles)) or \
                    (bool(to_roles & rotation_roles) and bool(from_roles & support_roles))
        return has_rotation or has_mixed
    
    elif pattern == "SLIDER_MATE":
        # Linear motion requires support roles on both sides
        support_roles = {"support", "rotation"}  # rotation interfaces can also slide
        return bool(from_roles & support_roles) and bool(to_roles & support_roles)
    
    elif pattern == "CYLINDRICAL_MATE":
        # Cylindrical requires rotation capability
        rotation_roles = {"rotation"}
        return bool(from_roles & rotation_roles) and bool(to_roles & rotation_roles)
    
    return False


def _map_pattern_to_attachment_type(pattern: str) -> str:
    """
    Map assembly pattern to attachment type for output.
    
    Args:
        pattern: Assembly pattern from ASSEMBLY_PATTERNS enum
    
    Returns:
        Attachment type string (rigid, revolute, slider, cylindrical)
    """
    pattern_map = {
        "RIGID_MATE": "rigid",
        "REVOLUTE_MATE": "revolute",
        "SLIDER_MATE": "slider",
        "CYLINDRICAL_MATE": "cylindrical"
    }
    return pattern_map.get(pattern, "rigid")


def _generate_interface_resolution_step(
    *,
    base_id: str,
    component_id: str,
    component_id_var: str,
    body_id_var: str,
    interface_name: str,
    recipe: Dict[str, Any],
    allowed: Dict[str, Any],
    token_var: str,
    marker_var: str,
    entity_id_var: str,
    entity_kind_var: str,
) -> Dict[str, Any]:
    """Generate one RESOLVE_INTERFACE call step and capture resolved token/entity ids."""
    _require_function(allowed, "RESOLVE_INTERFACE")
    return {
        "id": base_id,
        "function": "RESOLVE_INTERFACE",
        "inputs": {
            "component_id": f"${{{component_id_var}}}",
            "body_id": f"${{{body_id_var}}}",
            "interface_name": interface_name,
            "recipe": recipe,
        },
        "capture": {
            "vars": {
                token_var: "token_id",
                marker_var: "marker_id",
                entity_id_var: "entity_id",
                entity_kind_var: "entity_kind",
            }
        },
        "metadata": {
            "selection_strategy": "interface_recipe_resolution",
            "component_id": component_id,
            "interface_name": interface_name,
        },
    }


def _attachment_type_from_requirement(req: Dict[str, Any]) -> str:
    purpose = req.get("purpose")
    roles = req.get("roles")
    raw_decision = req.get("connection_decision")
    decision: Dict[str, Any] = raw_decision if isinstance(raw_decision, dict) else {}
    method = str(decision.get("method") or "").strip().lower()
    connection_semantics = req.get("connection_semantics")
    semantics: Dict[str, Any] = connection_semantics if isinstance(connection_semantics, dict) else {}
    geometric_semantics = semantics.get("geometric_semantics")
    geom: Dict[str, Any] = geometric_semantics if isinstance(geometric_semantics, dict) else {}
    purpose_norm = str(purpose or "").strip().lower()
    relation_type = str(semantics.get("relation_type") or "").strip().lower()
    orientation_policy = str(semantics.get("orientation_policy") or "").strip().lower()
    mechanism = str(semantics.get("connection_mechanism") or "").strip().lower()
    contact_model = str(geom.get("contact_model") or "").strip().lower()
    support_topology = str(geom.get("support_topology") or "").strip().lower()

    roles_set = set(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else set()

    if (
        contact_model in {"slot_insert_with_bolted_retention", "through_bolt_clamp_in_radial_slot", "double_shear_yoke_shaft_support"}
        or support_topology in {"hub_radial_slot_mount", "double_shear_yoke_support"}
        or (mechanism == "axial_face_bolted_mount" and relation_type == "axial_face_perimeter_mount")
    ):
        return "rigid"

    if purpose_norm == "torque_transfer":
        if (
            orientation_policy == "free"
            or any(token in method for token in ("bearing", "revolute", "rotat"))
            or any(token in mechanism for token in ("bearing", "revolute"))
            or any(token in contact_model for token in ("bearing", "revolute"))
            or relation_type in {"bearing_inner_race_to_shaft", "bearing_outer_race_to_housing"}
        ):
            return "revolute"
        return "rigid"

    if "rotation" in roles_set:
        return "revolute"
    if purpose_norm in {"rotation", "rotation_support", "rotational_motion"}:
        return "revolute"
    if any(token in method for token in ("bearing", "revolute", "rotat")):
        return "revolute"
    if any(token in mechanism for token in ("bearing", "revolute")):
        return "revolute"
    if any(token in contact_model for token in ("bearing", "revolute")):
        return "revolute"

    return "rigid"


def _pick_interface_by_role(
    *,
    component_id: str,
    desired_roles: List[str],
    interfaces_by_component: Dict[str, Set[str]],
    interface_map: Dict[str, Dict[str, Any]],
) -> str | None:
    candidates = interfaces_by_component.get(component_id, set())
    if not candidates:
        return None

    role_set = set(r for r in desired_roles if isinstance(r, str))
    role_interface_hints = {
        "fixation": {"fixation_req"},
        "mounting": {"mounting_req", "mounting_req_drill_anchor"},
        "support": {"support_req"},
        "rotation": {"rotation_req"},
        "torque_transfer": {"torque_transfer_req"},
    }
    geometric_interface_prefixes = (
        "axial_end_face",
        "side_face_",
        "top_face",
        "bottom_face",
        "radial_outer_face",
        "shaft_axis",
    )

    def _score_interface(iface_id: str) -> tuple[int, int, str]:
        iface_def = interface_map.get(f"{component_id}:{iface_id}") or {}
        semantic_role = str(iface_def.get("semantic_role") or "").strip().lower()
        usage = str(iface_def.get("usage") or "").strip().lower()
        interface_name = str(iface_def.get("interface_name") or iface_id).strip().lower()
        source_interface_id = str(iface_def.get("source_interface_id") or interface_name).strip().lower()

        score = 0
        if role_set:
            if semantic_role in role_set:
                score += 30
            if usage in role_set:
                score += 20

            hinted_names: Set[str] = set()
            for role in role_set:
                hinted_names.update(role_interface_hints.get(role, set()))
            if interface_name in hinted_names or source_interface_id in hinted_names:
                score += 100
            elif interface_name.endswith("_req") or source_interface_id.endswith("_req"):
                score += 40

        if usage == "mate_surface":
            score += 5

        if any(interface_name.startswith(prefix) or source_interface_id.startswith(prefix) for prefix in geometric_interface_prefixes):
            score -= 25

        abstraction_rank = 1 if (interface_name.endswith("_req") or source_interface_id.endswith("_req")) else 0
        return score, abstraction_rank, iface_id

    if role_set:
        ranked = sorted((_score_interface(iface_id) for iface_id in candidates), key=lambda item: (-item[0], -item[1], item[2]))
        if ranked and ranked[0][0] > 0:
            return ranked[0][2]

    preferred: List[str] = []
    for iface_id in sorted(candidates):
        iface_def = interface_map.get(f"{component_id}:{iface_id}") or {}
        if iface_def.get("usage") == "mate_surface" or iface_def.get("semantic_role") == "mate_surface":
            preferred.append(iface_id)
    if preferred:
        return preferred[0]

    return sorted(candidates)[0]

def _augment_subcomponent_internal_relations(
    *,
    assembly_relations: List[Dict[str, Any]],
    knowledge_graph: Dict[str, Any],
    interfaces_by_component: Dict[str, Set[str]],
    interface_map: Dict[str, Dict[str, Any]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    components = knowledge_graph.get("components")
    if not isinstance(components, list):
        return assembly_relations

    excluded_types = {
        "fastener",
        "bolt",
        "nut",
        "washer",
        "pin",
        "bearing",
        "shaft",
        "axle",
        "spacer",
        "key",
        "fastener_set",
    }
    explicit_kinematic_types = {
        "wheel",
        "rim",
        "tire",
        "hub",
        "bearing",
        "bushing",
        "seal",
        "shaft",
        "axle",
        "spacer",
        "roller",
        "pulley",
    }

    def _is_candidate(comp: Dict[str, Any]) -> bool:
        ctype = comp.get("type")
        if isinstance(ctype, str) and ctype.strip().lower() in excluded_types:
            return False
        policy = comp.get("modeling_policy")
        if isinstance(policy, str) and policy.strip().lower() == "container_only":
            return False
        return True

    children_by_parent: Dict[str, List[str]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        by_id[cid] = comp
        parent_id = comp.get("parent_id")
        if not isinstance(parent_id, str) or not parent_id:
            parent_id = comp.get("position_parent") if isinstance(comp.get("position_parent"), str) else None
        if isinstance(parent_id, str) and parent_id:
            children_by_parent.setdefault(parent_id, []).append(cid)

    existing_pairs: Set[Tuple[str, str]] = set()
    for rel in assembly_relations:
        if not isinstance(rel, dict):
            continue
        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}
        a = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
        b = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
        if isinstance(a, str) and a and isinstance(b, str) and b:
            pair = (a, b) if a <= b else (b, a)
            existing_pairs.add(pair)

    def _requires_explicit_internal_kinematics(component_ids: List[str]) -> bool:
        child_set = {cid for cid in component_ids if isinstance(cid, str) and cid in by_id}
        if not child_set:
            return False
        child_types = {
            str(by_id[cid].get("type") or "").strip().lower()
            for cid in child_set
            if isinstance(by_id.get(cid), dict)
        }
        if child_types & explicit_kinematic_types:
            return True

        for rel in assembly_relations:
            if not isinstance(rel, dict):
                continue
            from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
            to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}
            a = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            b = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            if not (isinstance(a, str) and isinstance(b, str) and a in child_set and b in child_set):
                continue
            attachment = str(rel.get("attachment_type") or "").strip().lower()
            if attachment and attachment != "rigid":
                return True
        return False

    out = list(assembly_relations)
    for parent_id, child_ids in children_by_parent.items():
        if not isinstance(parent_id, str) or not parent_id:
            continue

        filtered = [
            cid
            for cid in sorted(set(child_ids))
            if isinstance(cid, str) and cid and isinstance(by_id.get(cid), dict) and _is_candidate(by_id[cid])
        ]
        if len(filtered) < 2:
            continue

        if _requires_explicit_internal_kinematics(filtered):
            warnings.append(
                f"auto internal relation skipped for parent '{parent_id}': explicit kinematic subcomponents require authoritative relations"
            )
            continue

        iface_by_child: Dict[str, str] = {}
        for cid in filtered:
            iface = _pick_interface_by_role(
                component_id=cid,
                desired_roles=["mate_surface"],
                interfaces_by_component=interfaces_by_component,
                interface_map=interface_map,
            )
            if isinstance(iface, str) and iface:
                iface_by_child[cid] = iface

        eligible = [cid for cid in filtered if cid in iface_by_child]
        if len(eligible) < 2:
            warnings.append(
                f"auto internal relation skipped for parent '{parent_id}': insufficient mate_surface interfaces"
            )
            continue

        anchor = eligible[0]
        for cid in eligible[1:]:
            pair = (anchor, cid) if anchor <= cid else (cid, anchor)
            if pair in existing_pairs:
                continue
            out.append(
                {
                    "relation_id": f"auto_{parent_id}_{anchor}_{cid}_rigid",
                    "attachment_type": "rigid",
                    "from": {"component_id": anchor, "interface_id": iface_by_child[anchor]},
                    "to": {"component_id": cid, "interface_id": iface_by_child[cid]},
                    "source": "auto_subcomponent_internal",
                    "semantic_reason": f"Auto-added rigid relation for siblings under parent '{parent_id}'",
                }
            )
            existing_pairs.add(pair)

    return out
def resolve_assembly_geometry(assembly_geo: Dict[str, Any], kg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase A: Resolve assembly geometry semantics into deterministic attachment types.
    This phase does NOT generate CAD steps.
    """
    connection_keys = ("connections", "attachments", "joints", "mates")
    connections = None
    for key in connection_keys:
        candidate = assembly_geo.get(key)
        if isinstance(candidate, list):
            connections = candidate
            break

    if connections is None:
        raise ValueError("Missing assembly connection definitions (connections/attachments/joints/mates)")

    def _requires_rotation(conn: Dict[str, Any]) -> bool:
        if conn.get("requires_rotation") is True:
            return True
        if conn.get("intent") == "rotational":
            return True
        from_comp = conn.get("from", {}).get("component_id")
        to_comp = conn.get("to", {}).get("component_id")
        for rel in kg.get("relations", []):
            if rel.get("requires_rotation") is True:
                return True
            rel_a = rel.get("a", {}).get("component_id")
            rel_b = rel.get("b", {}).get("component_id")
            if {from_comp, to_comp} == {rel_a, rel_b}:
                rel_type = rel.get("type")
                if rel_type in {"rotation", "torque_transfer"}:
                    return True
        for req in kg.get("connection_requirements", []):
            if req.get("requires_rotation") is True:
                return True
            between = req.get("between", [])
            if isinstance(between, list) and from_comp in between and to_comp in between:
                if req.get("purpose") in {"rotation", "torque_transfer"}:
                    return True
        return False

    resolved_connections: List[Dict[str, Any]] = []
    for idx, conn in enumerate(connections):
        if not isinstance(conn, dict):
            raise ValueError(f"Connection at index {idx} must be an object")

        conn_id = conn.get("id") or conn.get("relation_id") or f"conn_{idx}"
        from_ep = conn.get("from") or conn.get("a") or {}
        to_ep = conn.get("to") or conn.get("b") or {}

        resolved = {
            "id": conn_id,
            "from": {
                "component_id": from_ep.get("component_id"),
                "interface_id": from_ep.get("interface_id"),
            },
            "to": {
                "component_id": to_ep.get("component_id"),
                "interface_id": to_ep.get("interface_id"),
            },
        }
        if isinstance(conn.get("connection_semantics"), dict):
            resolved["connection_semantics"] = conn.get("connection_semantics")

        if conn.get("attachment_type"):
            resolved["attachment_type"] = conn.get("attachment_type")
            resolved["resolution_source"] = "explicit"
            resolved_connections.append(resolved)
            continue

        allowed = conn.get("allowed_attachment_types")
        if not isinstance(allowed, list) or not allowed:
            allowed = assembly_geo.get("allowable_attachment_types")

        if not isinstance(allowed, list) or not allowed:
            resolved["attachment_type"] = "rigid"
            resolved["resolution_source"] = "deterministic_rule"
            resolved_connections.append(resolved)
            continue

        if len(allowed) == 1:
            resolved["attachment_type"] = allowed[0]
            resolved["resolution_source"] = "single_option"
            resolved_connections.append(resolved)
            continue

        if "revolute" in allowed and _requires_rotation(conn):
            resolved["attachment_type"] = "revolute"
            resolved["resolution_source"] = "intent_rule"
            resolved_connections.append(resolved)
            continue

        if "rigid" in allowed:
            resolved["attachment_type"] = "rigid"
            resolved["resolution_source"] = "lowest_constraint_rule"
            resolved_connections.append(resolved)
            continue

        resolved["attachment_type"] = allowed[0]
        resolved["resolution_source"] = "list_fallback"
        resolved_connections.append(resolved)

    return {"resolved_connections": resolved_connections}


def compile_assembly_steps(
    assembly_semantics: Dict[str, Any],
    function_registry: Dict[str, Any],
    externally_defined_vars: Set[str] | None = None,
    available_component_names: Set[str] | None = None,
    deferred_component_names: Set[str] | None = None,
    hosted_standard_component_names: Set[str] | None = None,
    interface_manifest: Dict[str, Any] | None = None,
    interface_declarations: Dict[Tuple[str, str], Dict[str, Any]] | None = None,
    clarification_relation_ids: Set[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    def _infer_depends_on_from_var_flow(step_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        var_producer: Dict[str, str] = {}
        for step in step_list:
            if not isinstance(step, dict):
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str):
                continue
            capture = step.get("capture")
            if isinstance(capture, dict):
                vars_map = capture.get("vars")
                if isinstance(vars_map, dict):
                    for var_name in vars_map.keys():
                        if isinstance(var_name, str) and var_name not in var_producer:
                            var_producer[var_name] = step_id

        var_pattern = re.compile(r"\$\{([^}]+)\}")

        def _collect_vars(value: Any, found: List[str]) -> None:
            if isinstance(value, str):
                for var in var_pattern.findall(value):
                    found.append(var)
                return
            if isinstance(value, list):
                for item in value:
                    _collect_vars(item, found)
                return
            if isinstance(value, dict):
                for item in value.values():
                    _collect_vars(item, found)

        for step in step_list:
            if not isinstance(step, dict):
                continue
            inputs = step.get("inputs")
            if not isinstance(inputs, dict):
                continue
            found_vars: List[str] = []
            _collect_vars(inputs, found_vars)

            depends_on = step.get("depends_on")
            if not isinstance(depends_on, list):
                depends_on = []
                step["depends_on"] = depends_on

            seen = {d for d in depends_on if isinstance(d, str)}
            for var_name in found_vars:
                producer = var_producer.get(var_name)
                if not producer or producer == step.get("id"):
                    continue
                if producer in seen:
                    continue
                depends_on.append(producer)
                seen.add(producer)

        return step_list

    resolved_connections = assembly_semantics.get("assembly_relations")
    if not isinstance(resolved_connections, list):
        raise ValueError("assembly_semantics missing assembly_relations list")

    allowed = function_registry

    required_shared = [
        "RESOLVE_INTERFACE",
        "CREATE_JOINT_GEOMETRY",
    ]
    for fn in required_shared:
        _require_function(allowed, fn)

    steps: List[Dict[str, Any]] = []
    compile_warnings: List[str] = []
    compiled_constraints: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    non_executable_relations: List[Dict[str, Any]] = []

    expected_by_type: Dict[str, int] = {}
    compiled_by_type: Dict[str, int] = {}
    unresolved_by_type: Dict[str, int] = {}

    def _inc(counter: Dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1

    iface_decl_map: Dict[Tuple[str, str], Dict[str, Any]] = dict(interface_declarations or {})
    blocked_relation_ids: Set[str] = set(clarification_relation_ids or set())

    def _interface_usage(iface_decl: Mapping[str, Any]) -> str | None:
        usage = iface_decl.get("usage")
        if isinstance(usage, str) and usage.strip():
            return usage.strip()
        return None

    def _interface_geometry_type(iface_decl: Mapping[str, Any]) -> str | None:
        for key in ("geometry_type", "geom_type"):
            value = iface_decl.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        recipe = iface_decl.get("recipe")
        if isinstance(recipe, Mapping):
            value = recipe.get("geometry_type")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return None

    def _is_cylindrical_or_axis(iface_decl: Mapping[str, Any], iface_id: str) -> bool:
        gtype = _interface_geometry_type(iface_decl)
        if gtype in {"axis", "cylindrical"}:
            return True
        iface_name = iface_id.lower()
        return any(tok in iface_name for tok in ("axis", "axle", "shaft", "bore", "cyl", "hole"))

    def _lookup_interface_declaration(component_id: str, interface_id: str) -> Dict[str, Any] | None:
        direct = iface_decl_map.get((component_id, interface_id))
        if direct is not None:
            return direct
        base_component = re.sub(r"_\d+$", "", component_id)
        if base_component != component_id:
            return iface_decl_map.get((base_component, interface_id))
        return None

    def _pick_revolute_interface(component_id: str, current_iface_id: str) -> Tuple[str, Dict[str, Any]] | None:
        candidates: List[Tuple[str, Dict[str, Any]]] = []
        base_component = re.sub(r"_\d+$", "", component_id)
        for (cid, iface_id), decl in iface_decl_map.items():
            if cid != component_id and cid != base_component:
                continue
            if not isinstance(decl, dict):
                continue
            usage = _interface_usage(decl)
            if usage != "mate_surface":
                continue
            if not _is_cylindrical_or_axis(decl, iface_id):
                continue
            candidates.append((iface_id, decl))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (0 if item[0] == current_iface_id else 1, item[0]))
        return candidates[0]

    def _norm_text(value: Any) -> str:
        return value.strip().lower() if isinstance(value, str) and value.strip() else ""

    def _connection_semantics(conn: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        semantics = conn.get("connection_semantics")
        if not isinstance(semantics, Mapping):
            return {}, {}
        geometric = semantics.get("geometric_semantics")
        if not isinstance(geometric, Mapping):
            geometric = {}
        return dict(semantics), dict(geometric)

    def _apply_semantic_interface_hints(
        *,
        from_comp: str,
        to_comp: str,
        from_iface: str | None,
        to_iface: str | None,
        iface_decl_a: Dict[str, Any],
        iface_decl_b: Dict[str, Any],
        conn: Mapping[str, Any],
    ) -> Tuple[str | None, Dict[str, Any], str | None, Dict[str, Any]]:
        semantics, _ = _connection_semantics(conn)
        if not semantics:
            return from_iface, iface_decl_a, to_iface, iface_decl_b

        ref_comp = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
        mov_comp = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
        ref_hint = semantics.get("assembly_reference_interface_hint") if isinstance(semantics.get("assembly_reference_interface_hint"), str) else None
        if not isinstance(ref_hint, str):
            ref_hint = semantics.get("reference_interface_hint") if isinstance(semantics.get("reference_interface_hint"), str) else None
        mov_hint = semantics.get("assembly_moving_interface_hint") if isinstance(semantics.get("assembly_moving_interface_hint"), str) else None
        if not isinstance(mov_hint, str):
            mov_hint = semantics.get("moving_interface_hint") if isinstance(semantics.get("moving_interface_hint"), str) else None

        _, geometric = _connection_semantics(conn)
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
        generic_hints = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}

        if support_topology == "hub_radial_slot_mount":
            if not (isinstance(mov_hint, str) and mov_hint.strip() and mov_hint.strip().lower() not in generic_hints):
                mov_hint = "proximal_insert_face"
        if support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates":
            if not (isinstance(ref_hint, str) and ref_hint.strip() and ref_hint.strip().lower() not in generic_hints):
                ref_hint = "distal_bore_axis"

        def _choose(component_id: str, current_iface: str | None, current_decl: Dict[str, Any], preferred_iface: str | None) -> Tuple[str | None, Dict[str, Any]]:
            if not (isinstance(preferred_iface, str) and preferred_iface):
                return current_iface, current_decl
            preferred_decl = _lookup_interface_declaration(component_id, preferred_iface)
            if isinstance(preferred_decl, dict):
                current_usage = _interface_usage(current_decl)
                preferred_usage = _interface_usage(preferred_decl)
                if current_usage == "mate_surface" and preferred_usage not in {None, "", "mate_surface"}:
                    return current_iface, current_decl
                return preferred_iface, preferred_decl
            return current_iface, current_decl

        if from_comp == ref_comp:
            from_iface, iface_decl_a = _choose(from_comp, from_iface, iface_decl_a, ref_hint)
        elif from_comp == mov_comp:
            from_iface, iface_decl_a = _choose(from_comp, from_iface, iface_decl_a, mov_hint)

        if to_comp == ref_comp:
            to_iface, iface_decl_b = _choose(to_comp, to_iface, iface_decl_b, ref_hint)
        elif to_comp == mov_comp:
            to_iface, iface_decl_b = _choose(to_comp, to_iface, iface_decl_b, mov_hint)

        return from_iface, iface_decl_a, to_iface, iface_decl_b

    def _pick_joint_function_for_relation(*, attachment_type: str, conn: Mapping[str, Any]) -> str:
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()

        if attachment_type == "rigid":
            if (
                mechanism == "press_fit"
                or relation_type in {"bearing_outer_race_seat", "axial_face_single_bolt_mount", "bonded_tread_wrap"}
                or contact_model in {
                    "slot_insert_with_bolted_retention",
                    "through_bolt_clamp_in_radial_slot",
                    "double_shear_yoke_shaft_support",
                    "interference_cylindrical_seat",
                    "press_fit_bore",
                    "opposed_planar_clamp",
                    "radial_wrap_bond",
                    "shaft_in_bore_support",
                    "coaxial_locked_coupling",
                }
                or support_topology in {"hub_radial_slot_mount", "double_shear_yoke_support"}
                or axial_stack_policy == "wheel_body_between_support_plates"
            ):
                return _pick_function(
                    allowed,
                    ["RIGID_AS_BUILT_JOINT", "RIGID_JOINT_R1", "PLANAR_AS_BUILT_JOINT"],
                    label="rigid attachment",
                )
            return _pick_function(
                allowed,
                ["RIGID_JOINT_R1", "RIGID_AS_BUILT_JOINT", "PLANAR_AS_BUILT_JOINT"],
                label="rigid attachment",
            )

        if attachment_type == "revolute":
            if (
                contact_model in {"coaxial_revolute_fit", "bearing_inner_race_revolute_fit"}
                or mechanism == "shaft_bore_fit"
                or relation_type == "shaft_axis_to_bore"
            ):
                return _pick_function(
                    allowed,
                    ["REVOLUTE_AS_BUILT_JOINT", "REVOLUTE_JOINT_R1", "REVOLUTE_JOINT"],
                    label="revolute attachment",
                )
            return _pick_function(
                allowed,
                ["REVOLUTE_JOINT_R1", "REVOLUTE_AS_BUILT_JOINT", "REVOLUTE_JOINT"],
                label="revolute attachment",
            )

        return _pick_function(
            allowed,
            ["RIGID_JOINT_R1", "RIGID_AS_BUILT_JOINT", "PLANAR_AS_BUILT_JOINT"],
            label="rigid attachment",
        )

    def _is_geometry_only_axial_retention_relation(conn: Mapping[str, Any]) -> bool:
        if not isinstance(conn, Mapping):
            return False
        purpose = _norm_text(conn.get("purpose"))
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        return purpose == "fastening_mechanism" and (
            relation_type in {"axial_preload_retention", "axial_shaft_retention", "axial_spacer_stack"}
            or contact_model in {"axial_retention_stack", "threaded_axial_retention", "axial_face_stackup"}
        )

    def _is_non_executable_bearing_proxy_relation(conn: Mapping[str, Any]) -> bool:
        if not isinstance(conn, Mapping):
            return False
        relation_id = _norm_text(conn.get("relation_id"))
        purpose = _norm_text(conn.get("purpose"))
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        return (
            "bearing" in relation_id
            or purpose in {"load_support", "rotation_support", "support_to_structure"}
        ) and (
            relation_type in {"rotation_support", "bearing_inner_race_rotation_support"}
            or (purpose == "rotation_support" and mechanism == "shaft_bore_fit")
            or contact_model == "bearing_inner_race_revolute_fit"
        )

    def _connection_dup_score(conn: Mapping[str, Any]) -> int:
        relation_id = _norm_text(conn.get("relation_id"))
        score = 0
        if relation_id and "_auto_" not in relation_id:
            score += 20
        if "body_support" in relation_id:
            score += 8
        if "support_structure_auto" in relation_id:
            score -= 4
        source = _norm_text(conn.get("source"))
        if source in {"knowledge_graph", "explicit_contract", "knowledge_graph_connection_requirements", "knowledge_graph_connection_requirements_fastener"}:
            score += 4
        return score

    def _dedupe_semantic_duplicate_relations(relations: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        best_by_signature = {}
        passthrough = []
        dropped = []
        for idx, conn in enumerate(relations):
            if not isinstance(conn, dict):
                continue
            from_ep = conn.get("from") if isinstance(conn.get("from"), Mapping) else {}
            to_ep = conn.get("to") if isinstance(conn.get("to"), Mapping) else {}
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            attachment_type = _norm_text(conn.get("attachment_type"))
            semantics, _geometric = _connection_semantics(conn)
            mechanism = _norm_text(semantics.get("connection_mechanism"))
            relation_type = _norm_text(semantics.get("relation_type"))
            if not (from_comp and to_comp and attachment_type and mechanism and relation_type):
                passthrough.append((idx, conn))
                continue
            signature = (tuple(sorted((from_comp, to_comp))), attachment_type, mechanism, relation_type)
            score = _connection_dup_score(conn)
            current = best_by_signature.get(signature)
            if current is None or score > current[1] or (score == current[1] and idx < current[0]):
                if current is not None:
                    dropped_id = current[2].get("relation_id")
                    if isinstance(dropped_id, str) and dropped_id:
                        dropped.append(dropped_id)
                best_by_signature[signature] = (idx, score, conn)
            else:
                relation_id = conn.get("relation_id")
                if isinstance(relation_id, str) and relation_id:
                    dropped.append(relation_id)
        kept = passthrough + [(idx, conn) for idx, _score, conn in best_by_signature.values()]
        kept.sort(key=lambda item: item[0])
        warnings = [f"dedupe assembly relation: dropped semantic duplicate '{relation_id}'" for relation_id in dropped]
        return [conn for _idx, conn in kept], warnings

    resolved_connections, dedupe_warnings = _dedupe_semantic_duplicate_relations(resolved_connections)
    compile_warnings.extend(dedupe_warnings)

    def _find_redundant_bearing_backed_wheel_rotation_relations(relations: List[Dict[str, Any]]) -> Set[str]:
        hub_to_bearings: Dict[str, Set[str]] = {}
        axle_to_bearings: Dict[str, Set[str]] = {}

        def _endpoint_ids(conn: Mapping[str, Any]) -> Tuple[str | None, str | None]:
            from_ep = conn.get("from") if isinstance(conn.get("from"), Mapping) else {}
            to_ep = conn.get("to") if isinstance(conn.get("to"), Mapping) else {}
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            return from_comp, to_comp

        for conn in relations:
            if not isinstance(conn, Mapping):
                continue
            semantics, geometric = _connection_semantics(conn)
            relation_type = _norm_text(semantics.get("relation_type"))
            contact_model = _norm_text(geometric.get("contact_model"))
            mechanism = _norm_text(semantics.get("connection_mechanism"))
            ref_id = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
            mov_id = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
            from_comp, to_comp = _endpoint_ids(conn)

            if mechanism == "press_fit" and relation_type == "bearing_outer_race_seat":
                hub_id = ref_id or from_comp or to_comp
                bearing_id = mov_id or from_comp or to_comp
                if isinstance(hub_id, str) and isinstance(bearing_id, str):
                    hub_to_bearings.setdefault(hub_id, set()).add(bearing_id)
                continue

            if mechanism == "shaft_bore_fit" and contact_model == "bearing_inner_race_revolute_fit":
                axle_id = ref_id or from_comp or to_comp
                bearing_id = mov_id or from_comp or to_comp
                if isinstance(axle_id, str) and isinstance(bearing_id, str):
                    axle_to_bearings.setdefault(axle_id, set()).add(bearing_id)

        redundant: Set[str] = set()
        for conn in relations:
            if not isinstance(conn, Mapping):
                continue
            relation_id = conn.get("relation_id") if isinstance(conn.get("relation_id"), str) else None
            if not relation_id:
                continue
            attachment_type = _norm_text(conn.get("attachment_type"))
            semantics, geometric = _connection_semantics(conn)
            relation_type = _norm_text(semantics.get("relation_type"))
            contact_model = _norm_text(geometric.get("contact_model"))
            if attachment_type != "revolute" or relation_type != "shaft_axis_to_bore" or contact_model != "coaxial_revolute_fit":
                continue

            ref_id = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
            mov_id = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
            from_comp, to_comp = _endpoint_ids(conn)
            axle_id = ref_id if isinstance(ref_id, str) and "axle" in ref_id.lower() else None
            hub_id = mov_id if isinstance(mov_id, str) and "hub" in mov_id.lower() else None
            if axle_id is None:
                for candidate in (from_comp, to_comp):
                    if isinstance(candidate, str) and "axle" in candidate.lower():
                        axle_id = candidate
                        break
            if hub_id is None:
                for candidate in (mov_id, from_comp, to_comp):
                    if isinstance(candidate, str) and "hub" in candidate.lower():
                        hub_id = candidate
                        break
            if not isinstance(axle_id, str) or not isinstance(hub_id, str):
                continue

            wheel_match = re.match(r"^wheel_(\d+)_", hub_id, flags=re.IGNORECASE) or re.match(r"^wheel_(\d+)_", axle_id, flags=re.IGNORECASE)
            if wheel_match is not None:
                candidate_hub_id = f"wheel_{wheel_match.group(1)}_hub"
                if candidate_hub_id in hub_to_bearings:
                    hub_id = candidate_hub_id

            if hub_to_bearings.get(hub_id) and axle_to_bearings.get(axle_id) and (hub_to_bearings[hub_id] & axle_to_bearings[axle_id]):
                redundant.add(relation_id)

        return redundant

    redundant_bearing_backed_rotation_ids = _find_redundant_bearing_backed_wheel_rotation_relations(resolved_connections)

    logical_component_ids: Set[str] = set()
    ext_vars = set(externally_defined_vars or set())
    non_assembly_relation_ids: Set[str] = set()
    hosted_standard_names = set(hosted_standard_component_names or set())

    deferred_names = set(deferred_component_names or set())
    resolvable_names: Set[str] = set(available_component_names or set()) | deferred_names

    for idx, conn in enumerate(resolved_connections, start=1):
        relation_id = conn.get("relation_id") if isinstance(conn, dict) and isinstance(conn.get("relation_id"), str) else f"connection_{idx}"
        if not isinstance(conn, dict):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "reason_code": "invalid_relation_payload",
                    "reason": "relation item is not an object",
                }
            )
            _inc(unresolved_by_type, "unknown")
            continue

        attachment_raw = conn.get("attachment_type")
        attachment_type = attachment_raw if isinstance(attachment_raw, str) and attachment_raw else "unknown"
        if _is_geometry_only_axial_retention_relation(conn):
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' is geometry-only axial retention and will not be compiled into an assembly joint"
            )
            continue
        if _is_non_executable_bearing_proxy_relation(conn):
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' targets a single-occurrence bearing proxy and will not be compiled into an assembly joint"
            )
            continue
        if relation_id in redundant_bearing_backed_rotation_ids:
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' is redundant because wheel rotation is already mediated by a bearing inner-race revolute plus outer-race seat"
            )
            continue
        _inc(expected_by_type, attachment_type)

        from_ep_raw = conn.get("from")
        to_ep_raw = conn.get("to")
        from_ep: Dict[str, Any] = from_ep_raw if isinstance(from_ep_raw, dict) else {}
        to_ep: Dict[str, Any] = to_ep_raw if isinstance(to_ep_raw, dict) else {}
        from_comp_raw = from_ep.get("component_id")
        to_comp_raw = to_ep.get("component_id")
        from_iface_raw = from_ep.get("interface_id")
        to_iface_raw = to_ep.get("interface_id")
        from_iface = from_iface_raw if isinstance(from_iface_raw, str) and from_iface_raw else None
        to_iface = to_iface_raw if isinstance(to_iface_raw, str) and to_iface_raw else None

        from_comp = from_comp_raw if isinstance(from_comp_raw, str) and from_comp_raw else None
        to_comp = to_comp_raw if isinstance(to_comp_raw, str) and to_comp_raw else None

        hosted_endpoints: List[str] = []
        if isinstance(from_comp, str) and from_comp in hosted_standard_names:
            hosted_endpoints.append(from_comp)
        if isinstance(to_comp, str) and to_comp in hosted_standard_names:
            hosted_endpoints.append(to_comp)
        if hosted_endpoints:
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' touches hosted standard part endpoint(s) "
                f"{', '.join(sorted(set(hosted_endpoints)))} and will not be compiled into an assembly joint"
            )
            non_executable_relations.append(
                {
                    "relation_id": relation_id,
                    "status": "non_executable",
                    "reason_code": "hosted_standard_part_endpoint",
                    "reason": "relation endpoint is a hosted standard part; placement is anchor-driven, no joint emitted",
                    "relation_execution_policy": "hosted_anchor_only",
                    "relation_output_role": "validation_anchor_metadata_only",
                    "hosted_endpoints": sorted(set(hosted_endpoints)),
                    "attachment_type": attachment_type,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                    "connection_semantics": conn.get("connection_semantics"),
                }
            )
            continue

        if relation_id in blocked_relation_ids:
            compile_warnings.append(
                f"skip connection[{idx}]: geometry semantics marked relation '{relation_id}' as requires_clarification"
            )
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "geometry_requires_clarification",
                    "reason": "geometry semantics marked relation requires_clarification; assembly joint generation skipped until anchor semantics are explicit",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if from_comp is not None:
            logical_component_ids.add(from_comp)
        if to_comp is not None:
            logical_component_ids.add(to_comp)

        if attachment_type not in {"rigid", "revolute"}:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "unsupported_attachment_type",
                    "reason": f"Unsupported attachment_type: {attachment_type}",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue
        function_name = _pick_joint_function_for_relation(
            attachment_type=attachment_type,
            conn=conn,
        )

        if resolvable_names:
            if from_comp is not None:
                from_comp = _resolve_collection_component_name(from_comp, resolvable_names)
            if to_comp is not None:
                to_comp = _resolve_collection_component_name(to_comp, resolvable_names)

        if not from_comp or not to_comp:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_component",
                    "reason": "from/to endpoint missing component_id",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        missing_components: List[str] = []
        if available_component_names and from_comp not in available_component_names and from_comp not in deferred_names:
            missing_components.append(from_comp)
        if available_component_names and to_comp not in available_component_names and to_comp not in deferred_names:
            missing_components.append(to_comp)
        if missing_components:
            reason = f"components not in geometry plan: {', '.join(sorted(set(missing_components)))}"
            compile_warnings.append(f"skip connection[{idx}]: {reason}")
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "component_not_in_geometry_plan",
                    "reason": reason,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        # Audit trail: endpoints that will be injected later by compose_plan.
        if (from_comp in deferred_names) or (to_comp in deferred_names):
            deferred_eps = []
            if from_comp in deferred_names:
                deferred_eps.append(from_comp)
            if to_comp in deferred_names:
                deferred_eps.append(to_comp)
            compile_warnings.append(
                f"deferred endpoint(s) for connection[{idx}] (standard parts injected later): {', '.join(sorted(set(deferred_eps)))}"
            )

        if attachment_type == "rigid" and (not from_iface or not to_iface):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_interface",
                    "reason": "rigid relation missing interface_id on endpoint",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if not from_iface or not to_iface:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_interface",
                    "reason": "relation endpoint missing interface_id",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        iface_decl_a = _lookup_interface_declaration(from_comp, from_iface)
        iface_decl_b = _lookup_interface_declaration(to_comp, to_iface)
        if not isinstance(iface_decl_a, dict) or not isinstance(iface_decl_b, dict):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_interface_declaration",
                    "reason": "missing interface_declarations entry for relation endpoint",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        from_iface, iface_decl_a, to_iface, iface_decl_b = _apply_semantic_interface_hints(
            from_comp=from_comp,
            to_comp=to_comp,
            from_iface=from_iface,
            to_iface=to_iface,
            iface_decl_a=iface_decl_a,
            iface_decl_b=iface_decl_b,
            conn=conn,
        )

        usage_a = _interface_usage(iface_decl_a)
        usage_b = _interface_usage(iface_decl_b)
        if usage_a != "mate_surface" or usage_b != "mate_surface":
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "invalid_interface_usage",
                    "reason": "assembly constraints allow only usage=mate_surface interfaces",
                    "from": {"component_id": from_comp, "interface_id": from_iface, "usage": usage_a},
                    "to": {"component_id": to_comp, "interface_id": to_iface, "usage": usage_b},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if attachment_type == "revolute":
            if not _is_cylindrical_or_axis(iface_decl_a, from_iface):
                picked_a = _pick_revolute_interface(from_comp, from_iface)
                if picked_a is not None:
                    from_iface, iface_decl_a = picked_a
                    compile_warnings.append(
                        f"connection[{idx}] switched revolute from-interface to cylindrical/axis candidate: {from_comp}:{from_iface}"
                    )
            if not _is_cylindrical_or_axis(iface_decl_b, to_iface):
                picked_b = _pick_revolute_interface(to_comp, to_iface)
                if picked_b is not None:
                    to_iface, iface_decl_b = picked_b
                    compile_warnings.append(
                        f"connection[{idx}] switched revolute to-interface to cylindrical/axis candidate: {to_comp}:{to_iface}"
                    )

            if not _is_cylindrical_or_axis(iface_decl_a, from_iface) or not _is_cylindrical_or_axis(iface_decl_b, to_iface):
                unresolved.append(
                    {
                        "relation_id": relation_id,
                        "status": "unresolved",
                        "attachment_type": attachment_type,
                        "reason_code": "revolute_requires_cylindrical_interface",
                        "reason": "revolute assembly requires axis/cylindrical interfaces on both endpoints",
                        "from": {"component_id": from_comp, "interface_id": from_iface},
                        "to": {"component_id": to_comp, "interface_id": to_iface},
                    }
                )
                _inc(unresolved_by_type, attachment_type)
                continue

        recipe_a = iface_decl_a.get("recipe") if isinstance(iface_decl_a.get("recipe"), dict) else None
        recipe_b = iface_decl_b.get("recipe") if isinstance(iface_decl_b.get("recipe"), dict) else None
        if recipe_a is None or recipe_b is None:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_interface_recipe",
                    "reason": "interface declaration missing recipe",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        base_id = f"asm_{idx:02d}_{attachment_type}"
        body_a_var = f"{from_comp}_body_id"
        body_b_var = f"{to_comp}_body_id"
        token_a_var = f"{base_id}_token_a"
        token_b_var = f"{base_id}_token_b"
        marker_a_var = f"{base_id}_marker_a"
        marker_b_var = f"{base_id}_marker_b"
        entity_a_var = f"{base_id}_entity_a"
        entity_b_var = f"{base_id}_entity_b"
        kind_a_var = f"{base_id}_kind_a"
        kind_b_var = f"{base_id}_kind_b"
        geom_a_var = f"{base_id}_geom_a"
        geom_b_var = f"{base_id}_geom_b"
        occ_a_var = f"{from_comp}_occurrence_id"
        occ_b_var = f"{to_comp}_occurrence_id"
        comp_a_var = f"{from_comp}_component_id"
        comp_b_var = f"{to_comp}_component_id"

        required_vars = [body_a_var, body_b_var, occ_a_var, occ_b_var, comp_a_var, comp_b_var]
        missing_vars = [var_name for var_name in required_vars if var_name not in ext_vars]
        if missing_vars:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_execution_vars",
                    "reason": "required execution vars not available for assembly compilation",
                    "missing_vars": missing_vars,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        steps.append(
            _generate_interface_resolution_step(
                base_id=f"{base_id}_resolve_a",
                component_id=from_comp,
                component_id_var=comp_a_var,
                body_id_var=body_a_var,
                interface_name=from_iface,
                recipe=recipe_a,
                allowed=allowed,
                token_var=token_a_var,
                marker_var=marker_a_var,
                entity_id_var=entity_a_var,
                entity_kind_var=kind_a_var,
            )
        )
        steps.append(
            _generate_interface_resolution_step(
                base_id=f"{base_id}_resolve_b",
                component_id=to_comp,
                component_id_var=comp_b_var,
                body_id_var=body_b_var,
                interface_name=to_iface,
                recipe=recipe_b,
                allowed=allowed,
                token_var=token_b_var,
                marker_var=marker_b_var,
                entity_id_var=entity_b_var,
                entity_kind_var=kind_b_var,
            )
        )

        steps.append(
            {
                "id": f"{base_id}_create_geom_a",
                "function": "CREATE_JOINT_GEOMETRY",
                "inputs": {
                    "entity": {"type": "marker", "marker_id": f"${{{marker_a_var}}}"},
                },
                "capture": {"vars": {geom_a_var: "joint_geometry_id"}},
            }
        )
        steps.append(
            {
                "id": f"{base_id}_create_geom_b",
                "function": "CREATE_JOINT_GEOMETRY",
                "inputs": {
                    "entity": {"type": "marker", "marker_id": f"${{{marker_b_var}}}"},
                },
                "capture": {"vars": {geom_b_var: "joint_geometry_id"}},
            }
        )

        joint_step_id = f"{base_id}_joint"
        if function_name in {
            "RIGID_JOINT_R1",
            "REVOLUTE_JOINT_R1",
            "RIGID_AS_BUILT_JOINT",
            "SLIDER_AS_BUILT_JOINT",
            "CYLINDRICAL_AS_BUILT_JOINT",
            "PLANAR_AS_BUILT_JOINT",
            "REVOLUTE_AS_BUILT_JOINT",
        }:
            joint_inputs: Dict[str, Any] = {
                "component_id": _component_var_ref(from_comp),
                "occurrence_one_id": f"${{{occ_a_var}}}",
                "occurrence_two_id": f"${{{occ_b_var}}}",
                "joint_geometry_one_id": f"${{{geom_a_var}}}",
                "joint_geometry_two_id": f"${{{geom_b_var}}}",
            }
        elif function_name == "REVOLUTE_JOINT":
            joint_inputs = {
                "component_a": _component_var_ref(from_comp),
                "component_b": _component_var_ref(to_comp),
                "axis": {"marker_id": f"${{{marker_a_var}}}"},
            }
        else:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "unsupported_joint_function",
                    "reason": f"Unsupported joint function: {function_name}",
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        steps.append(
            {
                "id": joint_step_id,
                "function": function_name,
                "inputs": joint_inputs,
            }
        )

        compiled_constraints.append(
            {
                "relation_id": relation_id,
                "status": "compiled",
                "attachment_type": attachment_type,
                "joint_function": function_name,
                "joint_step_id": joint_step_id,
                "expected_remaining_dof": conn.get("expected_remaining_dof"),
                "connection_semantics": conn.get("connection_semantics"),
                "from": {"component_id": from_comp, "interface_id": from_iface},
                "to": {"component_id": to_comp, "interface_id": to_iface},
                "selector": {
                    "from": "interface_recipe",
                    "to": "interface_recipe",
                    "mode": "resolved_interface_token",
                },
            }
        )
        _inc(compiled_by_type, attachment_type)

    _lint_component_refs(
        steps=steps,
        logical_component_ids=logical_component_ids,
        externally_defined_vars=externally_defined_vars,
    )

    expected_total = max(0, len(resolved_connections) - len(non_assembly_relation_ids))
    compiled_total = len(compiled_constraints)
    unresolved_total = len(unresolved)

    type_keys = sorted(set(expected_by_type.keys()) | set(compiled_by_type.keys()) | set(unresolved_by_type.keys()))
    by_attachment: Dict[str, Dict[str, Any]] = {}
    for key in type_keys:
        expected_count = expected_by_type.get(key, 0)
        compiled_count = compiled_by_type.get(key, 0)
        unresolved_count = unresolved_by_type.get(key, 0)
        by_attachment[key] = {
            "expected": expected_count,
            "compiled": compiled_count,
            "unresolved": unresolved_count,
            "coverage_ratio": (compiled_count / expected_count) if expected_count > 0 else 1.0,
        }

    coverage_summary = {
        "expected_relations": expected_total,
        "compiled_relations": compiled_total,
        "unresolved_relations": unresolved_total,
        "coverage_ratio": (compiled_total / expected_total) if expected_total > 0 else 1.0,
        "by_attachment_type": by_attachment,
    }

    return _infer_depends_on_from_var_flow(steps), compile_warnings, compiled_constraints, unresolved, coverage_summary, non_executable_relations


class AssemblySemanticReasoner:
    """
    LLM-assisted assembly semantic reasoner.
    
    DECISION SEMANTICS: Global but Independent
    - LLM receives ALL interfaces in ONE call (global context)
    - Each potential relation is decided INDEPENDENTLY
    - Relation A does NOT affect relation B decision
    - This enables batch reasoning while maintaining autonomy
    """
    
    def __init__(self, contract: Dict[str, Any]):
        self.contract = contract
        self.component_ids, self.interfaces_by_component, self.interface_map = self._build_contract_index(contract)
        self.allowed_attachments = set(contract.get("allowable_attachment_types", []))
        self.llm_last_audit: Dict[str, Any] | None = None
    
    def _build_contract_index(self, contract: Dict[str, Any]) -> Tuple[Set[str], Dict[str, Set[str]], Dict[str, Dict[str, Any]]]:
        """Build lookup structures for contract validation."""
        component_ids: Set[str] = set()
        interfaces_by_component: Dict[str, Set[str]] = {}
        interface_map: Dict[str, Dict[str, Any]] = {}  # comp_id:iface_id -> interface def
        
        for comp in contract.get("components", []):
            comp_id = comp.get("component_id")
            if not comp_id:
                continue
            component_ids.add(comp_id)
            iface_ids: Set[str] = set()
            for iface in comp.get("interfaces", []):
                iface_id = iface.get("interface_id")
                if iface_id:
                    iface_ids.add(iface_id)
                    key = f"{comp_id}:{iface_id}"
                    interface_map[key] = iface
            interfaces_by_component[comp_id] = iface_ids
        
        return component_ids, interfaces_by_component, interface_map
    
    def get_llm_decisions(
        self,
        kg_component_ids: Set[str],
        *,
        knowledge_graph: Dict[str, Any] | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get LLM assembly relation inferences.
        
        LLM input: contract components and their interfaces (NOT raw geometry).
        LLM output: proposed assembly relations with patterns from ASSEMBLY_PATTERNS.
        
        Returns:
            Dict mapping relation_id to decision dict with:
            - from/to: component_id and interface_id
            - assembly_pattern: str from ASSEMBLY_PATTERNS
            - rationale: str
            - valid: bool
        """
        if not kg_component_ids or not self.contract.get("components"):
            return {}
        
        # Filter contract to relevant components
        relevant_components = [c for c in self.contract.get("components", []) 
                              if c.get("component_id") in kg_component_ids]
        
        if not relevant_components:
            return {}
        
        kg_hints: Dict[str, Any] = {}
        if isinstance(knowledge_graph, dict):
            reqs = knowledge_graph.get("connection_requirements")
            if isinstance(reqs, list):
                kg_hints["connection_requirements"] = [
                    {
                        "id": r.get("id"),
                        "between": r.get("between"),
                        "purpose": r.get("purpose"),
                        "roles": r.get("roles"),
                        "connection_decision": r.get("connection_decision"),
                    }
                    for r in reqs
                    if isinstance(r, dict)
                ]

        prompt = f"""You are the LLM assembly reasoning layer for Agent 4 (Assembly Semantic Planner).

TASK:
Infer assembly relations between components based on their interfaces.
You MUST select attachment patterns from the ASSEMBLY_PATTERNS enum below.

DECISION SEMANTICS: Global but Independent
- You receive ALL components in this ONE call (global context for efficiency)
- Infer relations for EACH component pair INDEPENDENTLY
- Relation between A-B does NOT affect C-D relation inference
- Focus on EACH pair's individual interface compatibility

ALLOWED PATTERNS:
- RIGID_MATE: Permanent rigid connections (mounting, fixation, support)
- REVOLUTE_MATE: Rotational joints (wheels, shafts, bearings)
- SLIDER_MATE: Linear sliding joints (guides, sliders)
- CYLINDRICAL_MATE: Combined rotation+sliding (cylindrical joints)

IMPORTANT - UNDIRECTED RELATIONS:
- Assembly relations are BIDIRECTIONAL (A→B same as B→A)
- Only output ONE direction per component pair
- Choose the direction that makes semantic sense (e.g., wheel→shaft, not shaft→wheel)

NEGATIVE EXAMPLES (DO NOT DO):
? Connecting components with incompatible interface roles
? Using REVOLUTE_MATE for purely rigid connections
? Proposing multiple relations between same component pair
? Creating circular dependencies in a single inference

STRICT RULES:
1) Do NOT output Fusion API names or operations
2) Do NOT output assembly sequence or ordering
3) Do NOT output spatial coordinates or DOF values
4) ONLY propose relations between components that have interfaces
5) ONLY use patterns from ASSEMBLY_PATTERNS above
6) Provide brief rationale for each relation
7) Output at most one relation per component pair (bidirectional)

Component Interfaces:
```json
{json.dumps(relevant_components, indent=2, ensure_ascii=False)}
```

Knowledge Graph Hints:
```json
{json.dumps(kg_hints, indent=2, ensure_ascii=False)}
```

Return JSON in this format:
{{
    "relations": [
        {{
            "from": {{
                "component_id": "...",
                "interface_id": "..."
            }},
            "to": {{
                "component_id": "...",
                "interface_id": "..."
            }},
            "assembly_pattern": "RIGID_MATE|REVOLUTE_MATE|SLIDER_MATE|CYLINDRICAL_MATE",
            "rationale": "short explanation"
        }}
    ]
}}
"""
        
        response, audit = _call_llm(prompt)
        self.llm_last_audit = audit
        if not response:
            return {}
        
        obj = _extract_json(response)
        if not obj or not isinstance(obj, dict):
            return {}
        
        decisions = {}
        raw_relations = obj.get("relations", [])
        
        if not isinstance(raw_relations, list):
            return {}
        
        for idx, item in enumerate(raw_relations):
            if not isinstance(item, dict):
                continue
            
            from_data = item.get("from", {})
            to_data = item.get("to", {})
            pattern = item.get("assembly_pattern")
            rationale = item.get("rationale", "")
            
            from_comp = from_data.get("component_id")
            from_iface = from_data.get("interface_id")
            to_comp = to_data.get("component_id")
            to_iface = to_data.get("interface_id")
            
            if not all([from_comp, from_iface, to_comp, to_iface, pattern]):
                continue
            
            # Validate pattern is in allowed set
            valid = pattern in ASSEMBLY_PATTERNS if pattern else False
            
            rel_id = f"llm_rel_{idx}"
            decisions[rel_id] = {
                "relation_id": rel_id,
                "from": {"component_id": from_comp, "interface_id": from_iface},
                "to": {"component_id": to_comp, "interface_id": to_iface},
                "assembly_pattern": pattern,
                "attachment_type": _map_pattern_to_attachment_type(pattern) if pattern else "rigid",
                "rationale": rationale,
                "valid": valid
            }
        
        return decisions
    
    def validate_llm_relation(self, relation: Dict[str, Any]) -> Tuple[bool, str | None]:
        """
        Validate LLM-proposed relation against contract constraints.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        from_comp = relation.get("from", {}).get("component_id")
        from_iface = relation.get("from", {}).get("interface_id")
        to_comp = relation.get("to", {}).get("component_id")
        to_iface = relation.get("to", {}).get("interface_id")
        pattern = relation.get("assembly_pattern")
        attachment_type = relation.get("attachment_type")
        
        # Check components exist
        if not from_comp or from_comp not in self.component_ids:
            return False, f"from component '{from_comp}' not in contract"
        if not to_comp or to_comp not in self.component_ids:
            return False, f"to component '{to_comp}' not in contract"
        
        # Check interfaces exist
        if not from_iface or from_iface not in self.interfaces_by_component.get(from_comp, set()):
            return False, f"from interface '{from_iface}' not in component '{from_comp}'"
        if not to_iface or to_iface not in self.interfaces_by_component.get(to_comp, set()):
            return False, f"to interface '{to_iface}' not in component '{to_comp}'"
        
        # Check attachment type allowed
        if not attachment_type or attachment_type not in self.allowed_attachments:
            return False, f"attachment_type '{attachment_type}' not allowed by contract"
        
        # Check interface compatibility
        from_key = f"{from_comp}:{from_iface}"
        to_key = f"{to_comp}:{to_iface}"
        from_iface_def = self.interface_map.get(from_key, {})
        to_iface_def = self.interface_map.get(to_key, {})
        
        if pattern and not _is_assembly_pattern_allowed(pattern, from_iface_def, to_iface_def):
            return False, f"pattern '{pattern}' incompatible with interface roles"
        
        return True, None


def _map_relation_type(rel_type: str) -> str | None:
    """Map KG relation type to attachment type."""
    if rel_type == "rigid_attachment":
        return "rigid"
    if rel_type == "rotation":
        return "revolute"
    return None


def _validate_relation_fields(rel: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, str | None]:
    """Validate relation endpoints structure."""
    a = rel.get("a")
    b = rel.get("b")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None, "relation missing a/b endpoints"

    a_comp = a.get("component_id")
    a_iface = a.get("interface_id")
    b_comp = b.get("component_id")
    b_iface = b.get("interface_id")

    if not all([a_comp, a_iface, b_comp, b_iface]):
        return None, "relation endpoints missing component_id or interface_id"

    return {
        "a_component_id": a_comp,
        "a_interface_id": a_iface,
        "b_component_id": b_comp,
        "b_interface_id": b_iface,
    }, None


_EXPECTED_REMAINING_DOF = {
    "rigid": 0,
    "revolute": 1,
    "slider": 1,
    "cylindrical": 2,
}


def _enforce_relation_consistency(
    relations: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Deterministic CSP-lite checks for assembly relation set.

    Rules:
    - one component pair can only keep one relation (first seen wins)
    - interface occupancy conflict only when SAME endpoint is reused for the SAME component pair
    - each kept relation is annotated with expected_remaining_dof
    """
    kept: List[Dict[str, Any]] = []
    warnings: List[str] = []
    overrides: List[Dict[str, Any]] = []
    dropped_audit: List[Dict[str, Any]] = []
    occupied_interfaces_for_pair: Set[Tuple[Tuple[str, str], str, str]] = set()
    pair_seen: Set[Tuple[str, str]] = set()
    relation_by_interface: Dict[Tuple[str, str], str] = {}
    relation_by_pair: Dict[Tuple[str, str], str] = {}

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        rid = rel.get("relation_id") if isinstance(rel.get("relation_id"), str) else "unknown_relation"
        rid_s = str(rid)
        from_ep_raw = rel.get("from")
        to_ep_raw = rel.get("to")
        from_ep: Dict[str, Any] = from_ep_raw if isinstance(from_ep_raw, dict) else {}
        to_ep: Dict[str, Any] = to_ep_raw if isinstance(to_ep_raw, dict) else {}
        a_comp = from_ep.get("component_id")
        a_iface = from_ep.get("interface_id")
        b_comp = to_ep.get("component_id")
        b_iface = to_ep.get("interface_id")

        if not all(isinstance(x, str) and x for x in (a_comp, a_iface, b_comp, b_iface)):
            warnings.append(f"{rid}: missing endpoint identifiers, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "relation_endpoint_incomplete",
                    "reason": "missing component_id/interface_id on relation endpoint",
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "unresolvable_interface",
                    "reason": "missing component_id/interface_id on relation endpoint",
                    "replacement_relation_id": None,
                    "replaced_by": None,
                    "replacement_type": None,
                }
            )
            continue

        a_comp_s = str(a_comp)
        a_iface_s = str(a_iface)
        b_comp_s = str(b_comp)
        b_iface_s = str(b_iface)

        iface_a_key: Tuple[str, str] = (a_comp_s, a_iface_s)
        iface_b_key: Tuple[str, str] = (b_comp_s, b_iface_s)

        pair_key: Tuple[str, str] = (
            (a_comp_s, b_comp_s) if a_comp_s <= b_comp_s else (b_comp_s, a_comp_s)
        )
        pair_iface_a_key = (pair_key, a_comp_s, a_iface_s)
        pair_iface_b_key = (pair_key, b_comp_s, b_iface_s)
        if pair_iface_a_key in occupied_interfaces_for_pair or pair_iface_b_key in occupied_interfaces_for_pair:
            replaced_by: str | None = relation_by_interface.get(iface_a_key) or relation_by_interface.get(iface_b_key)
            warnings.append(f"{rid}: interface occupancy conflict, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "interface_occupancy_conflict",
                    "reason": "interface endpoint already occupied by another relation",
                    "endpoints": [
                        {"component_id": a_comp_s, "interface_id": a_iface_s},
                        {"component_id": b_comp_s, "interface_id": b_iface_s},
                    ],
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "conflict",
                    "reason": "interface endpoint already occupied by another relation",
                    "replacement_relation_id": replaced_by,
                    "replaced_by": replaced_by,
                    "replacement_type": "kept_relation" if isinstance(replaced_by, str) else None,
                    "occupied_endpoints": [
                        {"component_id": a_comp_s, "interface_id": a_iface_s},
                        {"component_id": b_comp_s, "interface_id": b_iface_s},
                    ],
                }
            )
            continue

        if pair_key in pair_seen:
            replaced_by = relation_by_pair.get(pair_key)
            warnings.append(f"{rid}: duplicate component pair relation, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "component_pair_duplicate",
                    "reason": "component pair already constrained by another relation",
                    "pair": [pair_key[0], pair_key[1]],
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "duplicate",
                    "reason": "component pair already constrained by another relation",
                    "replacement_relation_id": replaced_by,
                    "replaced_by": replaced_by,
                    "replacement_type": "kept_relation" if isinstance(replaced_by, str) else None,
                    "pair": [pair_key[0], pair_key[1]],
                }
            )
            continue

        attachment_type = rel.get("attachment_type")
        if isinstance(attachment_type, str):
            rel["expected_remaining_dof"] = _EXPECTED_REMAINING_DOF.get(attachment_type)

        kept.append(rel)
        occupied_interfaces_for_pair.add(pair_iface_a_key)
        occupied_interfaces_for_pair.add(pair_iface_b_key)
        pair_seen.add(pair_key)
        relation_by_interface[iface_a_key] = rid_s
        relation_by_interface[iface_b_key] = rid_s
        relation_by_pair[pair_key] = rid_s

    dof_histogram: Dict[str, int] = {}
    unknown_attachment_count = 0
    for rel in kept:
        attachment_type = rel.get("attachment_type")
        key = attachment_type if isinstance(attachment_type, str) and attachment_type else "unknown"
        dof_histogram[key] = dof_histogram.get(key, 0) + 1
        if rel.get("expected_remaining_dof") is None:
            unknown_attachment_count += 1

    summary: Dict[str, Any] = {
        "input_relations": len(relations),
        "kept_relations": len(kept),
        "dropped_relations": max(0, len(relations) - len(kept)),
        "occupied_interfaces": len(occupied_interfaces_for_pair),
        "dof_histogram": dof_histogram,
        "unknown_or_unmapped_attachment_count": unknown_attachment_count,
        "dropped_relation_audit_count": len(dropped_audit),
    }
    return kept, warnings, overrides, summary, dropped_audit


def _extract_fastener_steps(geometry_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract fastener_steps from geometry_plan.
    
    Fastener steps are feature_steps with function='place_fastener_group'.
    
    Returns:
        List of fastener_step dictionaries with fastener_spec information.
    """
    fastener_steps: List[Dict[str, Any]] = []
    steps = geometry_plan.get("steps")
    if not isinstance(steps, list):
        return fastener_steps
    
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") != "place_fastener_group":
            continue
        fastener_steps.append(step)
    
    return fastener_steps


def _infer_torque_spec(fastener_size: str) -> str:
    """
    Infer torque specification from fastener size.
    
    Uses common ISO 4017 bolt torque recommendations:
    - M3: 0.5-0.8 Nm
    - M5: 1.5-2.5 Nm
    - M6: 2.5-3.5 Nm
    - M8: 6-8 Nm
    - M10: 12-16 Nm
    - M12: 20-28 Nm
    """
    if not fastener_size:
        return "0-1 Nm"
    
    size_match = re.match(r"M(\d+)", fastener_size, re.IGNORECASE)
    if not size_match:
        return "0-1 Nm"
    
    size_num = int(size_match.group(1))
    torque_map: Dict[int, str] = {
        3: "0.5-0.8 Nm",
        5: "1.5-2.5 Nm",
        6: "2.5-3.5 Nm",
        8: "6-8 Nm",
        10: "12-16 Nm",
        12: "20-28 Nm",
    }
    
    return torque_map.get(size_num, "0-1 Nm")


def _determine_locking_mechanism(fastener_spec: Dict[str, Any]) -> str:
    """
    Determine locking mechanism from fastener_spec.
    
    Args:
        fastener_spec: Dictionary with fastener specification.
    
    Returns:
        Locking mechanism type (thread_lock, washer, self_locking).
    """
    if not isinstance(fastener_spec, dict):
        return "thread_lock"
    
    # Check explicit lock flag
    if fastener_spec.get("lock"):
        return "thread_lock"
    
    # Check fastener type
    fastener_type = fastener_spec.get("type", "").lower()
    if "self" in fastener_type or "nylon" in fastener_type:
        return "self_locking"
    
    return "thread_lock"


def _generate_assembly_constraints(
    fastener_steps: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate assembly_constraints from fastener_steps.
    
    Converts fastener placement steps into constraint definitions that specify
    how bolts connect components through holes.
    
    Each fastener_step produces one assembly_constraint with:
    - constraint_id: Unique identifier
    - type: Constraint type (bolted_rigid_connection)
    - fastener_spec: Size and type (e.g., M5x12)
    - fastener_standard: ISO standard
    - connections: List of component pairs connected by fastener
    - hole_ids: Holes through which fastener passes
    - torque_requirement: Torque spec for this fastener
    - locking_mechanism: How locking is achieved
    
    Args:
        fastener_steps: List of fastener steps from geometry_plan
    
    Returns:
        List of assembly_constraint dictionaries
    """
    constraints: List[Dict[str, Any]] = []
    
    for step_idx, step in enumerate(fastener_steps):
        if not isinstance(step, dict):
            continue
        
        inputs = step.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        
        # Extract fastener information
        fastener_spec_str = inputs.get("fastener_spec", "")
        fastener_type = inputs.get("fastener_type", "bolt")
        fastener_count = inputs.get("fastener_count", 1)
        fastener_standard = inputs.get("fastener_standard", "ISO4017")
        hole_refs = inputs.get("hole_references", [])
        target_components = inputs.get("target_components", [])
        fit_policy = inputs.get("fit_policy", "clearance")
        fastener_spec_dict = inputs.get("fastener_spec_obj", {})
        
        # Build constraint
        constraint: Dict[str, Any] = {
            "constraint_id": f"AC_{step_idx:03d}",
            "type": "bolted_rigid_connection",
            "fastener_spec": fastener_spec_str,
            "fastener_type": fastener_type,
            "fastener_count": fastener_count,
            "fastener_standard": fastener_standard,
            "connections": target_components,
            "hole_ids": hole_refs if isinstance(hole_refs, list) else [],
            "torque_requirement": _infer_torque_spec(fastener_spec_str),
            "locking_mechanism": _determine_locking_mechanism(fastener_spec_dict),
            "fit_policy": fit_policy,
        }
        
        constraints.append(constraint)
    
    return constraints


def _generate_assembly_sequence(
    geometry_steps: List[Dict[str, Any]],
    fastener_constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Generate assembly_sequence defining operation order.
    
    Defines the logical sequence: component creation → hole creation → fastener insertion.
    
    Args:
        geometry_steps: All steps from geometry_plan
        fastener_constraints: Assembly constraints for fasteners
    
    Returns:
        List of sequence dictionaries defining operation order
    """
    sequence: List[Dict[str, Any]] = []
    
    # Phase 1: Component creation
    component_steps: List[str] = []
    for step in geometry_steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") == "CREATE_COMPONENT":
            component_id = step.get("outputs", {}).get("component_id")
            if component_id:
                component_steps.append(component_id)
                sequence.append({
                    "phase": 1,
                    "operation": "create_component",
                    "component_id": component_id,
                    "order": len(sequence),
                })
    
    # Phase 2: Hole/feature creation
    for step in geometry_steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") == "create_hole":
            hole_id = step.get("outputs", {}).get("hole_id")
            target_comp = step.get("inputs", {}).get("target_component")
            if hole_id:
                sequence.append({
                    "phase": 2,
                    "operation": "create_hole",
                    "hole_id": hole_id,
                    "target_component": target_comp,
                    "order": len(sequence),
                })
    
    # Phase 3: Fastener insertion
    for constraint in fastener_constraints:
        constraint_id = constraint.get("constraint_id")
        hole_ids = constraint.get("hole_ids", [])
        connections = constraint.get("connections", [])
        
        sequence.append({
            "phase": 3,
            "operation": "insert_fastener",
            "constraint_id": constraint_id,
            "fastener_spec": constraint.get("fastener_spec"),
            "hole_ids": hole_ids,
            "connections": connections,
            "order": len(sequence),
        })
    
    return sequence


def build_assembly_semantics(
    *,
    knowledge_graph: Dict[str, Any],
    contract: Dict[str, Any],
    use_llm_assembly_intent: bool = True,
    component_realization_classes: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """
    Build assembly semantics from KG relations and LLM inferences.

    DECISION AUTHORITY MODEL:
    - KG relations are ALWAYS included (source of truth)
    - LLM proposes ADDITIONAL relations for arbitrary assemblies
    - Deterministic rules validate all relations (KG + LLM)
    - Invalid relations are rejected with override records
    
    Interface auto-matching:
    - If specified interface_id is not in contract, use first available
    - Handles name mismatches between KG and contract-generated names
    """
    warnings: List[str] = []
    assembly_relations: List[Dict[str, Any]] = []
    all_overrides: List[Dict[str, Any]] = []
    llm_corroborations: List[Dict[str, Any]] = []

    # Phase A: resolve explicit contract connections (highest priority)
    explicit_resolved = False
    for key in ("connections", "attachments", "joints", "mates"):
        if explicit_resolved:
            continue
        if isinstance(contract.get(key), list):
            resolved = resolve_assembly_geometry(contract, knowledge_graph)
            assembly_relations = resolved.get("resolved_connections", [])
            for rel in assembly_relations:
                if isinstance(rel, dict):
                    rel["source"] = "explicit_contract"
            explicit_resolved = True
    
    reasoner = AssemblySemanticReasoner(contract)
    component_ids = reasoner.component_ids
    interfaces_by_component = reasoner.interfaces_by_component
    allowed_attachments = reasoner.allowed_attachments

    def _hole_axis_interface_name(connection_id: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]+", "_", str(connection_id or "").strip()).strip("_")
        if not token:
            token = "connection"
        return f"{token}_hole_axis"

    # Get KG component IDs for LLM context
    kg_component_ids = {c.get("id") for c in knowledge_graph.get("components", []) if c.get("id")}
    
    # Process KG connection_requirements (deterministic, always included when present)
    kg_relation_count = 0
    for idx, req in enumerate(knowledge_graph.get("connection_requirements", [])):
        if not isinstance(req, dict):
            continue
        between = req.get("between")
        if not isinstance(between, list) or len(between) < 2:
            warnings.append(f"kg_requirement[{idx}] invalid between")
            continue
        a_comp = between[0]
        b_comp = between[1]
        if not isinstance(a_comp, str) or not isinstance(b_comp, str):
            warnings.append(f"kg_requirement[{idx}] invalid component ids")
            continue
        if a_comp not in component_ids or b_comp not in component_ids:
            warnings.append(f"kg_requirement[{idx}] component not in contract")
            continue

        roles_list = [r for r in req.get("roles", []) if isinstance(r, str)] if isinstance(req.get("roles"), list) else []
        attachment_type = _attachment_type_from_requirement(req)
        if attachment_type not in allowed_attachments:
            attachment_type = "rigid" if "rigid" in allowed_attachments else next(iter(allowed_attachments), "rigid")

        a_iface = _pick_interface_by_role(
            component_id=a_comp,
            desired_roles=roles_list,
            interfaces_by_component=interfaces_by_component,
            interface_map=reasoner.interface_map,
        )
        b_iface = _pick_interface_by_role(
            component_id=b_comp,
            desired_roles=roles_list,
            interfaces_by_component=interfaces_by_component,
            interface_map=reasoner.interface_map,
        )
        if not a_iface or not b_iface:
            warnings.append(f"kg_requirement[{idx}] no interfaces for endpoint component")
            continue

        req_id = req.get("id") if isinstance(req.get("id"), str) else f"kg_req_{idx}"
        req_semantics = req.get("connection_semantics") if isinstance(req.get("connection_semantics"), dict) else None
        assembly_relations.append(
            {
                "relation_id": req_id,
                "attachment_type": attachment_type,
                "from": {"component_id": a_comp, "interface_id": a_iface},
                "to": {"component_id": b_comp, "interface_id": b_iface},
                "connection_semantics": req_semantics,
                "source": "knowledge_graph_connection_requirements",
                "semantic_reason": (
                    f"From KG connection_requirement '{req_id}' purpose='{req.get('purpose')}' roles={roles_list}"
                ),
            }
        )

        connection_decision = req.get("connection_decision") if isinstance(req.get("connection_decision"), Mapping) else {}
        fastener_component_id = connection_decision.get("fastener_ref_component_id")
        reference_component_id = None
        if isinstance(req_semantics, Mapping):
            reference_component_id = req_semantics.get("reference_component_id")
        if not isinstance(reference_component_id, str) or not reference_component_id:
            reference_component_id = a_comp
        fastener_relation_semantics = copy.deepcopy(req_semantics) if isinstance(req_semantics, Mapping) else {}
        if isinstance(fastener_component_id, str) and fastener_component_id in component_ids and reference_component_id in component_ids:
            hole_axis_interface_id = _hole_axis_interface_name(req_id)
            fastener_relation_semantics["reference_component_id"] = fastener_component_id
            fastener_relation_semantics["moving_component_id"] = reference_component_id
            fastener_relation_semantics["reference_interface_hint"] = "shaft_axis"
            fastener_relation_semantics["assembly_reference_interface_hint"] = "shaft_axis"
            fastener_relation_semantics["moving_interface_hint"] = hole_axis_interface_id
            fastener_relation_semantics["assembly_moving_interface_hint"] = hole_axis_interface_id
            fastener_relation_semantics["relation_type"] = "fastener_shaft_to_hole_axis"
            assembly_relations.append(
                {
                    "relation_id": f"{req_id}__fastener_mount",
                    "attachment_type": "rigid",
                    "from": {"component_id": fastener_component_id, "interface_id": "shaft_axis"},
                    "to": {"component_id": reference_component_id, "interface_id": hole_axis_interface_id},
                    "connection_semantics": fastener_relation_semantics,
                    "source": "knowledge_graph_connection_requirements_fastener",
                    "semantic_reason": (
                        f"From KG connection_requirement '{req_id}' fastener '{fastener_component_id}' mounted to hole axis '{hole_axis_interface_id}'"
                    ),
                }
            )

        kg_relation_count += 1

    # Get LLM inferences (optional)
    llm_decisions: Dict[str, Dict[str, Any]] = {}
    if use_llm_assembly_intent:
        llm_decisions = reasoner.get_llm_decisions(kg_component_ids, knowledge_graph=knowledge_graph)
    
    # Process KG relations (legacy field; deterministic, always included)
    for idx, rel in enumerate(knowledge_graph.get("relations", [])):
        rel_type = rel.get("type")
        attachment_type = _map_relation_type(rel_type)
        if attachment_type is None:
            warnings.append(f"kg_relation[{idx}] unsupported type: {rel_type}")
            continue

        result = _validate_relation_fields(rel)
        endpoints = result[0]
        warn = result[1]
        if warn or endpoints is None:
            warnings.append(f"kg_relation[{idx}] {warn}")
            continue

        a_comp = endpoints.get("a_component_id")
        a_iface = endpoints.get("a_interface_id")
        b_comp = endpoints.get("b_component_id")
        b_iface = endpoints.get("b_interface_id")

        if not a_comp or not b_comp or a_comp not in component_ids or b_comp not in component_ids:
            warnings.append(f"kg_relation[{idx}] component not in contract")
            continue
        
        # Auto-match interfaces
        available_a_ifaces = interfaces_by_component.get(a_comp, set())
        if a_iface not in available_a_ifaces:
            if available_a_ifaces:
                a_iface = next(iter(available_a_ifaces))
            else:
                warnings.append(f"kg_relation[{idx}] no interfaces for '{a_comp}'")
                continue
        
        available_b_ifaces = interfaces_by_component.get(b_comp, set())
        if b_iface not in available_b_ifaces:
            if available_b_ifaces:
                b_iface = next(iter(available_b_ifaces))
            else:
                warnings.append(f"kg_relation[{idx}] no interfaces for '{b_comp}'")
                continue
        
        if attachment_type not in allowed_attachments:
            warnings.append(f"kg_relation[{idx}] type not allowed")
            continue

        relation_id = rel.get("id") if isinstance(rel.get("id"), str) else None

        assembly_relations.append({
            "relation_id": relation_id or f"kg_rel_{idx}",
            "attachment_type": attachment_type,
            "from": {
                "component_id": a_comp,
                "interface_id": a_iface,
            },
            "to": {
                "component_id": b_comp,
                "interface_id": b_iface,
            },
            "source": "knowledge_graph",
            "semantic_reason": (
                f"From KG relation '{rel.get('id', idx)}' type '{rel_type}' "
                f"mapped to attachment_type '{attachment_type}'"
            ),
        })
        kg_relation_count += 1
    
    # Build deduplication index keyed by unordered component pairs.
    existing_relations_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rel in assembly_relations:
        from_comp = rel.get("from", {}).get("component_id")
        to_comp = rel.get("to", {}).get("component_id")
        if not (isinstance(from_comp, str) and isinstance(to_comp, str) and from_comp and to_comp):
            continue
        pair_key = (from_comp, to_comp) if from_comp <= to_comp else (to_comp, from_comp)
        existing_relations_by_pair.setdefault(pair_key, rel)

    # Process LLM inferences with corroboration-aware duplicate handling.
    llm_relation_count = 0
    for rel_id, decision in llm_decisions.items():
        if not decision.get("valid"):
            warnings.append(f"{rel_id} invalid pattern: {decision.get('assembly_pattern')}")
            continue

        from_comp = decision.get("from", {}).get("component_id")
        to_comp = decision.get("to", {}).get("component_id")
        if not (isinstance(from_comp, str) and isinstance(to_comp, str) and from_comp and to_comp):
            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_rejected",
                "llm_proposed": decision,
                "reason": "LLM relation missing component endpoints",
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} rejected: missing component endpoints")
            continue

        pair_key = (from_comp, to_comp) if from_comp <= to_comp else (to_comp, from_comp)
        existing_rel = existing_relations_by_pair.get(pair_key)
        attachment_type = decision.get("attachment_type")
        is_valid, error = reasoner.validate_llm_relation(decision)

        if existing_rel is not None:
            existing_attachment = existing_rel.get("attachment_type")
            if isinstance(existing_attachment, str) and existing_attachment == attachment_type:
                llm_corroborations.append(
                    {
                        "relation_id": rel_id,
                        "status": "corroborated_existing_relation",
                        "llm_proposed": decision,
                        "corroborates_relation_id": existing_rel.get("relation_id"),
                        "existing_source": existing_rel.get("source"),
                        "reason": f"LLM confirmed existing relation between '{from_comp}' and '{to_comp}'",
                    }
                )
                warnings.append(f"{rel_id} corroborated: {from_comp} ? {to_comp}")
                continue

            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_conflict",
                "llm_proposed": decision,
                "reason": (
                    f"Conflicting relation for '{from_comp}' and '{to_comp}': "
                    f"existing attachment_type='{existing_attachment}', llm attachment_type='{attachment_type}'"
                ),
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} conflict: {from_comp} ? {to_comp}")
            continue

        if not is_valid:
            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_rejected",
                "llm_proposed": decision,
                "reason": error or "Engineering constraint violation"
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} rejected: {error}")
            continue

        accepted_relation = {
            "relation_id": rel_id,
            "attachment_type": attachment_type,
            "from": decision.get("from"),
            "to": decision.get("to"),
            "source": "llm_inference",
            "semantic_reason": (
                f"LLM inferred pattern '{decision.get('assembly_pattern')}': "
                f"{decision.get('rationale', 'semantic reasoning')}"
            ),
        }
        assembly_relations.append(accepted_relation)
        existing_relations_by_pair[pair_key] = accepted_relation
        llm_relation_count += 1
    assembly_relations = _augment_subcomponent_internal_relations(
        assembly_relations=assembly_relations,
        knowledge_graph=knowledge_graph,
        interfaces_by_component=interfaces_by_component,
        interface_map=reasoner.interface_map,
        warnings=warnings,
    )
    
    # Deterministic consistency enforcement (interface occupancy + pair uniqueness + DOF annotation)
    assembly_relations, consistency_warnings, consistency_overrides, consistency_summary, dropped_relation_audit = _enforce_relation_consistency(
        assembly_relations
    )
    if consistency_warnings:
        warnings.extend(consistency_warnings)
    if consistency_overrides:
        all_overrides.extend(consistency_overrides)

    # Recompute source counts after consistency enforcement
    final_kg_count = 0
    final_llm_count = 0
    for rel in assembly_relations:
        source = rel.get("source")
        if source in {"knowledge_graph", "knowledge_graph_connection_requirements", "knowledge_graph_connection_requirements_fastener", "explicit_contract"}:
            final_kg_count += 1
        elif source == "llm_inference":
            final_llm_count += 1

    realization_class_map = {
        str(cid): str(rc)
        for cid, rc in dict(component_realization_classes or {}).items()
        if isinstance(cid, str) and cid and isinstance(rc, str) and rc
    }
    for rel in assembly_relations:
        if not isinstance(rel, dict):
            continue
        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}

        from_cid = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
        to_cid = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None

        from_rc = realization_class_map.get(from_cid or "", REALIZATION_CLASS_NATIVE)
        to_rc = realization_class_map.get(to_cid or "", REALIZATION_CLASS_NATIVE)

        if isinstance(from_ep, dict):
            from_ep["realization_class"] = from_rc
            rel["from"] = from_ep
        if isinstance(to_ep, dict):
            to_ep["realization_class"] = to_rc
            rel["to"] = to_ep

        hosted_relation = (
            from_rc == REALIZATION_CLASS_HOSTED_STANDARD
            or to_rc == REALIZATION_CLASS_HOSTED_STANDARD
        )
        if hosted_relation:
            rel["relation_execution_policy"] = "hosted_anchor_only"
            rel["relation_output_role"] = "validation_anchor_metadata_only"
        else:
            rel.setdefault("relation_execution_policy", "assembly_executable")
            rel.setdefault("relation_output_role", "assembly_joint_candidate")

    # Determine execution mode (more precise logic)
    has_llm_decisions = bool(llm_decisions)
    llm_corroboration_count = len(llm_corroborations)
    has_llm_accepted = final_llm_count > 0
    has_overrides = len(all_overrides) > 0
    has_kg_relations = final_kg_count > 0
    has_llm_supported = has_llm_accepted or llm_corroboration_count > 0
    
    if not has_llm_decisions:
        # No LLM attempted
        execution_mode = "deterministic"
    elif has_llm_accepted and not has_overrides:
        # LLM used, all accepted
        execution_mode = "llm_guided"
    elif has_llm_supported and has_overrides:
        # LLM used with a mix of accepted/corroborated relations and rejected/conflicting ones
        execution_mode = "hybrid"
    elif llm_corroboration_count > 0:
        # LLM agreed with deterministic relations without adding new ones
        execution_mode = "deterministic"
    elif not has_llm_supported and has_overrides:
        # LLM used, all rejected (falls back to deterministic with warnings)
        execution_mode = "deterministic"  # Special case: LLM tried but all failed
    else:
        # Fallback
        execution_mode = "deterministic"
    
    metadata = {
        "plan_id": f"assembly_semantics_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "schema_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "plan_assembly",
        "execution_mode": execution_mode,
        "execution_mode_definition": EXECUTION_MODES.get(execution_mode, {}),
        "llm": {
            "enabled": bool(use_llm_assembly_intent),
            "attempted": bool((reasoner.llm_last_audit or {}).get("attempted")),
            "api_key_present": bool((reasoner.llm_last_audit or {}).get("api_key_present")),
            "ok": bool((reasoner.llm_last_audit or {}).get("ok")),
            "error": (reasoner.llm_last_audit or {}).get("error"),
            "timeout_seconds": (reasoner.llm_last_audit or {}).get("timeout_seconds"),
            "max_attempts": (reasoner.llm_last_audit or {}).get("max_attempts"),
            "attempts": (reasoner.llm_last_audit or {}).get("attempts"),
            "errors": (reasoner.llm_last_audit or {}).get("errors"),
            "model": (reasoner.llm_last_audit or {}).get("model"),
            "base_url": (reasoner.llm_last_audit or {}).get("base_url"),
        },
        "notes": {
            "rigid_resolution": "Rigid attachment_type may be derived by deterministic rules (not failure fallback).",
            "relation_priority": "Explicit contract relations are highest priority; LLM may add new relations and corroborate compatible existing ones without being marked as rejected."
        },
        "constraint_validation": consistency_summary,
        "dropped_relation_audit": dropped_relation_audit,
    }
    
    # Record LLM decisions
    if llm_decisions:
        metadata["llm_decisions"] = {
            "count": len(llm_decisions),
            "decisions": list(llm_decisions.values())
        }
    
    if llm_corroborations:
        metadata["llm_corroborations"] = {
            "count": len(llm_corroborations),
            "records": llm_corroborations
        }

    # Record overrides
    if all_overrides:
        metadata["overrides"] = {
            "count": len(all_overrides),
            "records": all_overrides
        }
    
    # Record sources
    metadata["relation_sources"] = {
        "knowledge_graph_count": final_kg_count,
        "llm_proposed_count": len(llm_decisions),
        "llm_inference_count": final_llm_count,
        "llm_corroboration_count": llm_corroboration_count,
        "total": len(assembly_relations),
    }
    metadata["component_realization_classes"] = realization_class_map
    metadata["realization_class_summary"] = {
        "native_functional_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_NATIVE),
        "hosted_standard_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_HOSTED_STANDARD),
        "kinematic_imported_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_KINEMATIC_IMPORTED),
    }

    return {
        "metadata": metadata,
        "assembly_relations": assembly_relations,
        "warnings": warnings,
    }


def _build_modeling_connection_semantics_refinements(modeling_payload: Mapping[str, Any]) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
    placements = modeling_payload.get("connection_placements") if isinstance(modeling_payload, Mapping) else None
    if not isinstance(placements, list):
        return {}

    refinements: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        ref_comp = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
        mov_comp = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
        relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
        if not (isinstance(ref_comp, str) and ref_comp and isinstance(mov_comp, str) and mov_comp and relation_type and mechanism):
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        target_component = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else None
        interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
        authoritative_interface_hints = placement.get("authoritative_interface_hints") if isinstance(placement.get("authoritative_interface_hints"), Mapping) else {}
        mapped_ref_hint = authoritative_interface_hints.get(ref_comp) if isinstance(authoritative_interface_hints.get(ref_comp), str) else None
        mapped_mov_hint = authoritative_interface_hints.get(mov_comp) if isinstance(authoritative_interface_hints.get(mov_comp), str) else None
        explicit_ref_hint = anchor.get("assembly_reference_interface_hint")
        if not isinstance(explicit_ref_hint, str) or not explicit_ref_hint.strip():
            explicit_ref_hint = anchor.get("reference_interface_hint")
        explicit_ref_hint = explicit_ref_hint.strip() if isinstance(explicit_ref_hint, str) and explicit_ref_hint.strip() else None
        explicit_mov_hint = anchor.get("assembly_moving_interface_hint")
        if not isinstance(explicit_mov_hint, str) or not explicit_mov_hint.strip():
            explicit_mov_hint = anchor.get("moving_interface_hint")
        explicit_mov_hint = explicit_mov_hint.strip() if isinstance(explicit_mov_hint, str) and explicit_mov_hint.strip() else None

        geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
        generic_hints = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}
        if not (isinstance(explicit_ref_hint, str) and explicit_ref_hint and explicit_ref_hint.lower() not in generic_hints):
            explicit_ref_hint = mapped_ref_hint.strip() if isinstance(mapped_ref_hint, str) and mapped_ref_hint.strip() else explicit_ref_hint
        if not (isinstance(explicit_mov_hint, str) and explicit_mov_hint and explicit_mov_hint.lower() not in generic_hints):
            explicit_mov_hint = mapped_mov_hint.strip() if isinstance(mapped_mov_hint, str) and mapped_mov_hint.strip() else explicit_mov_hint
        if support_topology == "hub_radial_slot_mount":
            if not (isinstance(explicit_mov_hint, str) and explicit_mov_hint and explicit_mov_hint.lower() not in generic_hints):
                explicit_mov_hint = "proximal_insert_face"
        if support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates":
            if not (isinstance(explicit_ref_hint, str) and explicit_ref_hint and explicit_ref_hint.lower() not in generic_hints):
                explicit_ref_hint = "distal_bore_axis"

        key = (ref_comp, mov_comp, relation_type, mechanism)
        refinement = refinements.setdefault(key, {})

        if isinstance(explicit_ref_hint, str) and explicit_ref_hint:
            refinement["reference_interface_hint"] = explicit_ref_hint
            refinement["assembly_reference_interface_hint"] = explicit_ref_hint
        if isinstance(explicit_mov_hint, str) and explicit_mov_hint:
            refinement["moving_interface_hint"] = explicit_mov_hint
            refinement["assembly_moving_interface_hint"] = explicit_mov_hint

        if target_component == ref_comp:
            preferred_ref_hint = explicit_ref_hint or interface_name
            if isinstance(preferred_ref_hint, str) and preferred_ref_hint:
                refinement["reference_interface_hint"] = preferred_ref_hint
                refinement["assembly_reference_interface_hint"] = preferred_ref_hint
            reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else None
            if isinstance(reference_anchor, Mapping):
                refinement["reference_anchor"] = copy.deepcopy(dict(reference_anchor))
        if target_component == mov_comp:
            preferred_mov_hint = explicit_mov_hint or interface_name
            if isinstance(preferred_mov_hint, str) and preferred_mov_hint:
                refinement["moving_interface_hint"] = preferred_mov_hint
                refinement["assembly_moving_interface_hint"] = preferred_mov_hint
            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else None
            if isinstance(moving_anchor, Mapping):
                refinement["moving_anchor"] = copy.deepcopy(dict(moving_anchor))

    return refinements


def _apply_modeling_connection_semantics_refinements(assembly_semantics: Dict[str, Any], modeling_payload: Mapping[str, Any]) -> None:
    relations = assembly_semantics.get("assembly_relations") if isinstance(assembly_semantics, Mapping) else None
    if not isinstance(relations, list):
        return

    refinements = _build_modeling_connection_semantics_refinements(modeling_payload)
    if not refinements:
        return

    interface_declarations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in _iter_interface_declarations(dict(modeling_payload)):
        comp_id = item.get("component_id")
        iface_name = item.get("interface_name")
        if isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name:
            interface_declarations[(comp_id, iface_name)] = item

    generic_interface_ids = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}

    def _is_generic_interface_name(interface_id: Any) -> bool:
        if not isinstance(interface_id, str):
            return True
        name = interface_id.strip().lower()
        if not name:
            return True
        return name in generic_interface_ids or name.endswith("_req")

    def _resolve_preferred_interface(component_id: str, preferred_iface: str) -> str | None:
        preferred_name = preferred_iface.strip()
        if not preferred_name or _is_generic_interface_name(preferred_name):
            return None
        direct = interface_declarations.get((component_id, preferred_name))
        if isinstance(direct, Mapping):
            usage = str(direct.get("usage") or "").strip().lower()
            if not usage or usage == "mate_surface":
                return preferred_name
        component_candidates = {
            iface_name.lower(): iface_name
            for (cid, iface_name), decl in interface_declarations.items()
            if cid == component_id and isinstance(decl, Mapping)
        }
        alias_preferences = {
            "proximal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "proximal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "distal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "distal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "axial_face_perimeter_min": ("axial_end_face_min", "axial_end_face", "planar_face"),
            "axial_face_perimeter_max": ("axial_end_face_max", "axial_end_face", "planar_face"),
            "radial_mount_perimeter": ("radial_outer_face", "radial_inner_face"),
        }
        for alias in alias_preferences.get(preferred_name.lower(), ()): 
            resolved = component_candidates.get(alias)
            if not isinstance(resolved, str):
                continue
            decl = interface_declarations.get((component_id, resolved))
            if not isinstance(decl, Mapping):
                continue
            usage = str(decl.get("usage") or "").strip().lower()
            if not usage or usage == "mate_surface":
                return resolved
        return None

    def _promote_endpoint_interface(endpoint: Dict[str, Any], preferred_iface: str | None) -> None:
        component_id = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
        current_iface = endpoint.get("interface_id") if isinstance(endpoint.get("interface_id"), str) else None
        if not (isinstance(component_id, str) and component_id):
            return
        if not _is_generic_interface_name(current_iface):
            return
        if not (isinstance(preferred_iface, str) and preferred_iface.strip()):
            return
        resolved_iface = _resolve_preferred_interface(component_id, preferred_iface)
        if not isinstance(resolved_iface, str) or not resolved_iface:
            return
        endpoint["interface_id"] = resolved_iface

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        semantics = rel.get("connection_semantics") if isinstance(rel.get("connection_semantics"), Mapping) else None
        if not isinstance(semantics, Mapping):
            continue
        ref_comp = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
        mov_comp = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
        relation_type = str(semantics.get("relation_type") or "").strip().lower()
        mechanism = str(semantics.get("connection_mechanism") or "").strip().lower()
        if not (isinstance(ref_comp, str) and ref_comp and isinstance(mov_comp, str) and mov_comp and relation_type and mechanism):
            continue

        refinement = refinements.get((ref_comp, mov_comp, relation_type, mechanism))
        if not isinstance(refinement, Mapping):
            continue

        merged = copy.deepcopy(dict(semantics))
        for key, value in refinement.items():
            merged[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
        rel["connection_semantics"] = merged

        ref_hint = merged.get("assembly_reference_interface_hint")
        if not isinstance(ref_hint, str) or not ref_hint.strip():
            ref_hint = merged.get("reference_interface_hint")
        mov_hint = merged.get("assembly_moving_interface_hint")
        if not isinstance(mov_hint, str) or not mov_hint.strip():
            mov_hint = merged.get("moving_interface_hint")

        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else None
        if isinstance(from_ep, dict):
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            if from_comp == ref_comp:
                _promote_endpoint_interface(from_ep, ref_hint)
            elif from_comp == mov_comp:
                _promote_endpoint_interface(from_ep, mov_hint)

        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else None
        if isinstance(to_ep, dict):
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            if to_comp == ref_comp:
                _promote_endpoint_interface(to_ep, ref_hint)
            elif to_comp == mov_comp:
                _promote_endpoint_interface(to_ep, mov_hint)

def run(*, run_dir: Path, round_index: int) -> Dict[str, Any]:
    """Run assembly semantic planning."""
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    contract_path = run_dir / "planning" / f"geometry_semantics_assembly_round_{round_index}.json"
    registry_path = Path("functions") / "functions.json"

    if not kg_path.exists():
        raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
    if not contract_path.exists():
        raise FileNotFoundError(f"Geometry assembly contract not found: {contract_path}")

    knowledge_graph = _read_json(kg_path)
    contract = _read_json(contract_path)

    # Read pipeline metadata flags (authored by tools/run_pipeline.py)
    use_llm_assembly_intent = True
    metadata_path = run_dir / "metadata.json"
    if metadata_path.exists():
        try:
            pipeline_meta = _read_json(metadata_path)
            if isinstance(pipeline_meta, dict) and "use_llm_assembly_intent" in pipeline_meta:
                use_llm_assembly_intent = bool(pipeline_meta.get("use_llm_assembly_intent"))
        except Exception:
            # Non-fatal: keep default
            pass

    component_realization_classes = _build_component_realization_class_map(
        knowledge_graph=knowledge_graph,
        run_dir=run_dir,
        round_index=round_index,
    )

    assembly_semantics = build_assembly_semantics(
        knowledge_graph=knowledge_graph,
        contract=contract,
        use_llm_assembly_intent=use_llm_assembly_intent,
        component_realization_classes=component_realization_classes,
    )
    component_alias_map = _build_component_alias_map(knowledge_graph)

    # If LLM is enabled and an API key is present, do NOT silently fall back.
    # Persist the semantics artifact for debugging, then fail fast.
    semantics_metadata = assembly_semantics.get("metadata")
    llm_status = semantics_metadata.get("llm") if isinstance(semantics_metadata, dict) else None
    if (
        use_llm_assembly_intent
        and isinstance(llm_status, dict)
        and bool(llm_status.get("api_key_present"))
        and not bool(llm_status.get("ok"))
    ):
        output_path = run_dir / "planning" / f"assembly_semantics_round_{round_index}.json"
        try:
            _write_json(output_path, assembly_semantics)
        except Exception:
            # Best-effort artifact persistence; primary goal is to fail fast.
            pass
        raise RuntimeError(
            "LLM is enabled (use_llm_assembly_intent=true) and OPENAI_API_KEY is present, "
            "but the LLM call failed. This pipeline does not fall back to deterministic mode in this configuration. "
            "You can increase OPENAI_TIMEOUT_SECONDS / OPENAI_MAX_RETRIES, or disable LLM via run metadata.json. "
            f"Last error: {llm_status.get('error')}"
        )

    function_registry = _load_function_registry(registry_path)
    geometry_plan_path = run_dir / "planning" / f"geometry_plan_round_{round_index}.json"
    modeling_semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
    interface_manifest: Dict[str, Any] | None = None
    interface_declarations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    clarification_relation_ids: Set[str] = set()
    if interface_manifest_path.exists():
        payload = _read_json(interface_manifest_path)
        if isinstance(payload, dict):
            interface_manifest = payload
    if modeling_semantics_path.exists():
        modeling_payload = _read_json(modeling_semantics_path)
        if isinstance(modeling_payload, dict):
            _apply_modeling_connection_semantics_refinements(assembly_semantics, modeling_payload)
            for item in _iter_interface_declarations(modeling_payload):
                comp_id = item.get("component_id")
                iface_name = item.get("interface_name")
                if isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name:
                    interface_declarations[(comp_id, iface_name)] = item
            connection_placements = modeling_payload.get("connection_placements")
            if isinstance(connection_placements, list):
                for placement in connection_placements:
                    if not isinstance(placement, dict) or placement.get("requires_clarification") is not True:
                        continue
                    connection_id = placement.get("connection_id")
                    if isinstance(connection_id, str) and connection_id:
                        clarification_relation_ids.add(connection_id.split("@", 1)[0])
    external_vars: Set[str] = set()
    available_component_names: Set[str] = set()
    deferred_component_names: Set[str] = set()
    hosted_standard_component_names: Set[str] = {
        cid
        for cid, rc in component_realization_classes.items()
        if rc == REALIZATION_CLASS_HOSTED_STANDARD
    }
    fastener_steps: List[Dict[str, Any]] = []
    geometry_steps: List[Dict[str, Any]] = []
    
    if geometry_plan_path.exists():
        geometry_plan = _read_json(geometry_plan_path)
        if isinstance(geometry_plan, dict):
            geom_steps = geometry_plan.get("steps")
            if isinstance(geom_steps, list):
                external_vars = _collect_defined_vars([s for s in geom_steps if isinstance(s, dict)])
                geometry_steps = geom_steps
            available_component_names = _collect_geometry_component_names(geometry_plan)

    for cid, proto in component_alias_map.items():
        if not isinstance(cid, str) or not isinstance(proto, str) or not cid or not proto:
            continue
        available_component_names.add(cid)
        external_vars.add(f"{cid}_component_id")
        external_vars.add(f"{cid}_body_id")
        external_vars.add(f"{cid}_occurrence_id")
        
        # Extract fastener steps for assembly constraints
        fastener_steps = _extract_fastener_steps(geometry_plan)

    # Standard parts (fasteners/bearings) are inserted later (compose_plan), so their
    # `${<id>_component_id}` vars are not present in geometry_plan. Predeclare them
    # from resolver output to avoid failing assembly lint.
    std_resolved_path = run_dir / "planning" / "standard_parts_resolved.json"
    if std_resolved_path.exists():
        try:
            payload = _read_json(std_resolved_path)
            resolved = payload.get("resolved", []) if isinstance(payload, dict) else []
            if isinstance(resolved, list):
                for part in resolved:
                    if not isinstance(part, dict):
                        continue
                    category = part.get("category") if isinstance(part.get("category"), str) else None
                    is_hosted_standard = isinstance(category, str) and bool(category.strip())
                    bound_ids = part.get("bound_component_ids")
                    if isinstance(bound_ids, list):
                        for cid in bound_ids:
                            if isinstance(cid, str) and cid:
                                deferred_component_names.add(cid)
                                external_vars.add(f"{cid}_component_id")
                                external_vars.add(f"{cid}_occurrence_id")
                                external_vars.add(f"{cid}_body_id")
                                if is_hosted_standard:
                                    hosted_standard_component_names.add(cid)
                    pid = part.get("id")
                    if isinstance(pid, str) and pid:
                        deferred_component_names.add(pid)
                        external_vars.add(f"{pid}_component_id")
                        external_vars.add(f"{pid}_occurrence_id")
                        external_vars.add(f"{pid}_body_id")
        except Exception:
            pass

    steps, compile_warnings, compiled_constraints, unresolved_relations, coverage_summary, non_executable_relations = compile_assembly_steps(
        assembly_semantics,
        function_registry,
        externally_defined_vars=external_vars,
        available_component_names=available_component_names,
        deferred_component_names=deferred_component_names,
        hosted_standard_component_names=hosted_standard_component_names,
        interface_manifest=interface_manifest,
        interface_declarations=interface_declarations,
        clarification_relation_ids=clarification_relation_ids,
    )

    # Planning/execution separation: never write execution/* facts here.
    # Optional debug artifacts can be emitted under planning/ only when explicitly enabled.
    if os.getenv("FUSION_WRITE_PREFLIGHT_ARTIFACTS", "0").strip() == "1":
        _write_preflight_execution_context(
            run_dir=run_dir,
            round_index=round_index,
            external_vars=external_vars,
        )

    # Generate fastener assembly constraints and sequence
    assembly_constraints = _generate_assembly_constraints(fastener_steps)
    assembly_sequence = _generate_assembly_sequence(geometry_steps, assembly_constraints)

    assembly_plan = {
        "metadata": {
            "plan_id": f"assembly_plan_round_{round_index}",
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "author": "agent4_assembly_compiler",
            "capability_registry": {"path": "functions/functions.json"},
        },
        "steps": steps,
        "constraints": compiled_constraints,
        "unresolved": unresolved_relations,
        "non_executable_relations": non_executable_relations,
        "coverage_summary": coverage_summary,
        "assembly_constraints": assembly_constraints,
        "assembly_sequence": assembly_sequence,
        "dropped_relations": (
            assembly_semantics.get("metadata", {}).get("dropped_relation_audit", [])
            if isinstance(assembly_semantics.get("metadata"), dict)
            else []
        ),
        "artifacts": {
            "source_assembly_geometry_semantics": (
                f"planning/geometry_semantics_assembly_round_{round_index}.json"
            )
        },
    }

    validated_steps, validated_constraints, skipped_relations, skipped_steps = validate_assembly_contract(
        assembly_semantics=assembly_semantics,
        interface_manifest=interface_manifest,
        geometry_plan=geometry_plan if isinstance(locals().get("geometry_plan"), dict) else None,
        assembly_plan=assembly_plan,
        component_alias_map=component_alias_map,
        external_defined_vars=external_vars,
    )
    assembly_plan["steps"] = validated_steps
    assembly_plan["constraints"] = validated_constraints
    if skipped_relations:
        unresolved_relations.extend(skipped_relations)
    if skipped_steps:
        assembly_plan.setdefault("artifacts", {})["skipped_steps"] = skipped_steps

    dropped_relations = assembly_plan.get("dropped_relations") if isinstance(assembly_plan.get("dropped_relations"), list) else []
    dropped_conflict_components = _collect_conflict_drop_components(dropped_relations)
    conflict_drop_errors: List[Dict[str, Any]] = []
    for item in dropped_relations:
        if not isinstance(item, dict):
            continue
        if not _is_required_symmetric_conflict_drop(item):
            continue
        conflict_drop_errors.append(
            {
                "relation_id": item.get("relation_id") if isinstance(item.get("relation_id"), str) else "unknown_relation",
                "status": "failed_conflict_drop",
                "reason_code": "relation_conflict_dropped",
                "reason": item.get("reason") if isinstance(item.get("reason"), str) else "required relation dropped by consistency conflict",
                "occupied_endpoints": item.get("occupied_endpoints") if isinstance(item.get("occupied_endpoints"), list) else [],
            }
        )

    if conflict_drop_errors:
        unresolved_relations.extend(conflict_drop_errors)

    geometry_components_gate = _collect_geometry_components_for_gate(
        geometry_plan if isinstance(locals().get("geometry_plan"), dict) else None
    )
    constrained_components = _collect_constrained_components(validated_constraints)
    semantic_components: Set[str] = set()
    for rel in assembly_semantics.get("assembly_relations", []) if isinstance(assembly_semantics.get("assembly_relations"), list) else []:
        if not isinstance(rel, dict):
            continue
        for endpoint_key in ("from", "to"):
            endpoint = rel.get(endpoint_key) if isinstance(rel.get(endpoint_key), dict) else {}
            cid = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
            if isinstance(cid, str) and cid:
                semantic_components.add(cid)

    free_raw = None
    sem_meta = assembly_semantics.get("metadata") if isinstance(assembly_semantics.get("metadata"), dict) else {}
    if isinstance(sem_meta, dict):
        free_raw = sem_meta.get("allowed_free_components")
    allowed_free_set = {cid for cid in free_raw if isinstance(cid, str) and cid} if isinstance(free_raw, list) else set()
    allowed_free_set |= hosted_standard_component_names

    component_type_map: Dict[str, str] = {}
    position_parent_map: Dict[str, str] = {}
    for comp in knowledge_graph.get("components", []) if isinstance(knowledge_graph.get("components"), list) else []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id") if isinstance(comp.get("id"), str) else None
        ctype = comp.get("type") if isinstance(comp.get("type"), str) else None
        if isinstance(cid, str) and isinstance(ctype, str):
            component_type_map[cid] = ctype.strip().lower()
        pparent = comp.get("position_parent") if isinstance(comp.get("position_parent"), str) else None
        if isinstance(cid, str) and cid and isinstance(pparent, str) and pparent:
            position_parent_map[cid] = pparent
    fastener_like = {"fastener", "bolt", "nut", "washer", "pin", "key", "spacer", "rivet"}
    for cid, ctype in component_type_map.items():
        if ctype in fastener_like:
            allowed_free_set.add(cid)

    ground_root = _select_ground_root_component(knowledge_graph, geometry_components_gate)

    unconstrained_components = _compute_unconstrained_components(
        geometry_components=geometry_components_gate,
        constrained_components=constrained_components,
        semantic_components=semantic_components,
        dropped_conflict_components=dropped_conflict_components,
        ground_root=ground_root,
        allowed_free_set=allowed_free_set,
        contained_components=set(position_parent_map.keys()),
    )
    unconstrained_errors: List[Dict[str, Any]] = [
        {
            "relation_id": f"unconstrained::{cid}",
            "status": "failed_unconstrained",
            "reason_code": "unconstrained_component",
            "reason": "component appears in assembly semantics/conflict drops but has no compiled assembly constraint",
            "component_id": cid,
        }
        for cid in unconstrained_components
    ]
    if unconstrained_errors:
        unresolved_relations.extend(unconstrained_errors)

    fatal_skips = _compute_critical_skips(unresolved_relations)
    if conflict_drop_errors or unconstrained_components:
        metadata_obj = assembly_plan.setdefault("metadata", {})
        if isinstance(metadata_obj, dict):
            metadata_obj["assembly_constraint_gate"] = {
                "status": "failed",
                "strict_mode": _strict_assembly_enabled(),
                "conflict_drop_count": len(conflict_drop_errors),
                "unconstrained_component_count": len(unconstrained_components),
                "unconstrained_components": unconstrained_components,
            }
    if skipped_relations:
        metadata_obj = assembly_plan.setdefault("metadata", {})
        if isinstance(metadata_obj, dict):
            metadata_obj["skipped_relations_summary"] = {
                "count": len(skipped_relations),
                "fatal_skips": len(fatal_skips),
                "status": "failed" if fatal_skips else "needs_clarification",
                "strict_mode": _strict_assembly_enabled(),
            }

    if compile_warnings:
        assembly_plan["metadata"]["compile_warnings"] = compile_warnings
    assembly_plan["metadata"]["coverage_summary"] = coverage_summary
    semantics_metadata = assembly_semantics.get("metadata")
    if isinstance(semantics_metadata, dict):
        constraint_validation = semantics_metadata.get("constraint_validation")
        if isinstance(constraint_validation, dict):
            assembly_plan["metadata"]["constraint_validation"] = constraint_validation
    if interface_manifest is not None:
        assembly_plan["metadata"]["interface_manifest"] = {
            "path": f"planning/interface_manifest_round_{round_index}.json",
            "mode": "preferred_with_fallback",
        }
        manifest_meta = interface_manifest.get("metadata") if isinstance(interface_manifest, dict) else None
        if isinstance(manifest_meta, dict):
            resolution = manifest_meta.get("resolution")
            if isinstance(resolution, dict):
                assembly_plan["metadata"]["interface_manifest"]["resolution"] = resolution

    output_path = run_dir / "planning" / f"assembly_semantics_round_{round_index}.json"
    _write_json(output_path, assembly_semantics)

    plan_path = run_dir / "planning" / f"assembly_patch_round_{round_index}.json"
    _write_json(plan_path, assembly_plan)

    if os.getenv("FUSION_WRITE_PREFLIGHT_ARTIFACTS", "0").strip() == "1":
        _write_preflight_resolved_interfaces(
            run_dir=run_dir,
            round_index=round_index,
            compiled_constraints=compiled_constraints,
            unresolved_relations=unresolved_relations,
            interface_manifest=interface_manifest,
        )

    if unresolved_relations:
        errors_path = run_dir / "planning" / "errors" / "assembly_errors.json"
        errors_payload = {
            "metadata": {
                "schema_version": "1.0",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": "agent4_plan_assembly",
                "round_index": round_index,
            },
            "summary": {
                "unresolved_count": len(unresolved_relations),
                "compiled_count": len(compiled_constraints),
                "expected_count": len(assembly_semantics.get("assembly_relations", [])) if isinstance(assembly_semantics.get("assembly_relations"), list) else 0,
            },
            "errors": unresolved_relations,
        }
        _write_json(errors_path, errors_payload)
        if isinstance(assembly_semantics, dict):
            diagnostics = assembly_semantics.setdefault("diagnostics", {}) if isinstance(assembly_semantics.get("diagnostics"), dict) else {}
            if isinstance(diagnostics, dict):
                diagnostics["unresolved_relations"] = {
                    "count": len(unresolved_relations),
                    "fatal_skip_count": len(fatal_skips),
                    "unconstrained_components": unconstrained_components,
                    "errors_path": f"planning/errors/assembly_errors.json",
                    "status": "failed" if fatal_skips else "needs_clarification",
                }
                _write_json(output_path, assembly_semantics)
        print(
            f"[WARN] Assembly has {len(unresolved_relations)} unresolved relations; unexecutable steps were skipped. "
            f"Details: {errors_path}"
        )
        if _strict_assembly_enabled() and fatal_skips:
            raise RuntimeError(
                "Strict assembly mode failed: critical skipped/unresolved relations detected "
                f"({len(fatal_skips)} fatal of {len(unresolved_relations)} unresolved). "
                "See planning/errors/assembly_errors.json"
            )

    print(f"[OK] Generated assembly semantics: {output_path.name}")
    metadata = assembly_semantics.get("metadata", {})
    print(f"  - Execution mode: {metadata.get('execution_mode')}")
    sources = metadata.get("relation_sources", {}) if isinstance(metadata, dict) else {}
    print(f"  - KG relations: {sources.get('knowledge_graph_count')}")
    print(
        "  - LLM proposed/accepted: "
        f"{sources.get('llm_proposed_count')}/{sources.get('llm_inference_count')}"
    )
    print(f"  - Total relations: {len(assembly_semantics.get('assembly_relations', []))}")

    llm_status = metadata.get("llm") if isinstance(metadata, dict) else None
    if isinstance(llm_status, dict):
        # Only print a short status; do not print secrets.
        print(
            "  - LLM status: "
            f"enabled={llm_status.get('enabled')} "
            f"attempted={llm_status.get('attempted')} "
            f"ok={llm_status.get('ok')} "
            f"api_key_present={llm_status.get('api_key_present')}"
        )
        if llm_status.get("enabled") and not llm_status.get("ok"):
            err = llm_status.get("error")
            if isinstance(err, str) and err:
                print(f"  - LLM error: {err}")

    print(f"[OK] Generated assembly plan: {plan_path.name}")
    print(f"  - {len(steps)} steps")
    print(f"  - {len(assembly_constraints)} assembly constraints")
    print(f"  - {len(assembly_sequence)} sequence operations")

    return {
        "path": f"planning/assembly_semantics_round_{round_index}.json",
        "assembly_plan_path": f"planning/assembly_patch_round_{round_index}.json",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan assembly semantics")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)

    args = parser.parse_args()

    result = run(run_dir=args.run_dir, round_index=args.round_index)
    print(f"Assembly semantics: {result['path']}")


if __name__ == "__main__":
    main()











