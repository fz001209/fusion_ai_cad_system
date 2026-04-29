"""Agent4 shared loading, registry, validation, LLM, and assembly gate helpers."""

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

ASSEMBLY_PATTERNS = {
    "RIGID_MATE",
    "REVOLUTE_MATE",
    "SLIDER_MATE",
    "CYLINDRICAL_MATE",
}

EXECUTION_MODES = {
    "deterministic": {
        "description": "KG/contract-driven assembly planning without accepted LLM-only relations",
        "decision_authority": "Deterministic rules",
    },
    "llm_guided": {
        "description": "LLM proposed additional relations that passed deterministic validation",
        "decision_authority": "LLM proposals validated by deterministic rules",
    },
    "hybrid": {
        "description": "Mix of deterministic relations and accepted/corroborated LLM evidence with rejected LLM proposals recorded",
        "decision_authority": "Deterministic rules plus validated LLM evidence",
    },
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
