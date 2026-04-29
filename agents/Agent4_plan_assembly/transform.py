"""
Agent4 assembly planner facade.

The implementation is grouped into a few large modules. This file keeps the
public entrypoint and old helper imports stable.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from types import FunctionType
from typing import Any, Dict, List, Mapping, Set, Tuple

from agents.common_utils import read_json as _read_json, write_json as _write_json, collect_defined_vars as _collect_defined_vars

from .module_wiring import wire_agent4_modules

_AGENT4_SPLIT_NAMESPACE = wire_agent4_modules()
globals().update(_AGENT4_SPLIT_NAMESPACE)


def _bind_agent4_helpers_to_facade() -> None:
    """Keep legacy transform.py monkeypatch behavior after splitting modules."""
    def _rebind_function(name: str, value: FunctionType) -> FunctionType:
        rebound = FunctionType(
            value.__code__,
            globals(),
            name=value.__name__,
            argdefs=value.__defaults__,
            closure=value.__closure__,
        )
        rebound.__kwdefaults__ = value.__kwdefaults__
        rebound.__annotations__ = dict(getattr(value, "__annotations__", {}))
        rebound.__dict__.update(getattr(value, "__dict__", {}))
        rebound.__doc__ = value.__doc__
        rebound.__module__ = __name__
        return rebound

    for name, value in list(_AGENT4_SPLIT_NAMESPACE.items()):
        if not isinstance(value, FunctionType):
            continue
        if not str(getattr(value, "__module__", "")).startswith("agents.Agent4_plan_assembly."):
            continue
        globals()[name] = _rebind_function(name, value)

    for value in list(_AGENT4_SPLIT_NAMESPACE.values()):
        if not isinstance(value, type):
            continue
        if not str(getattr(value, "__module__", "")).startswith("agents.Agent4_plan_assembly."):
            continue
        for attr_name, attr_value in list(vars(value).items()):
            descriptor_type = None
            func = attr_value
            if isinstance(attr_value, staticmethod):
                descriptor_type = staticmethod
                func = attr_value.__func__
            elif isinstance(attr_value, classmethod):
                descriptor_type = classmethod
                func = attr_value.__func__
            if not isinstance(func, FunctionType):
                continue
            if not str(getattr(func, "__module__", "")).startswith("agents.Agent4_plan_assembly."):
                continue
            rebound = _rebind_function(attr_name, func)
            if descriptor_type is staticmethod:
                setattr(value, attr_name, staticmethod(rebound))
            elif descriptor_type is classmethod:
                setattr(value, attr_name, classmethod(rebound))
            else:
                setattr(value, attr_name, rebound)


_bind_agent4_helpers_to_facade()


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











