"""
Agent3b geometry-plan compiler facade.

The implementation is grouped into a few large modules. This file keeps the
public entrypoint and old helper imports stable.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

from agents.Agent3b_compile_geometry_plan.standard_part_compiler import inject_standard_parts_steps
from agents.common_utils import read_json as _read_json, write_json as _write_json
from validation.validate_shape_realization import validate_shape_realization_contract

from .module_wiring import wire_agent3b_modules

globals().update(wire_agent3b_modules())


def run(*, run_dir: Path, round_index: int) -> Dict[str, Any]:
    shape_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    if not shape_path.exists():
        raise FileNotFoundError(f"Shape realization not found: {shape_path}")

    shape = _read_json(shape_path)
    if not isinstance(shape, Mapping):
        raise ValueError("shape_realization must be an object")

    realizations = _extract_realizations(shape)
    if not realizations:
        raise ValueError("shape_realization must provide non-empty parts or component_realizations")

    registry_path = Path("functions") / "functions.json"
    allowed = _load_function_registry(registry_path)

    skip_components = _load_standard_part_bindings(run_dir)

    # Load KG to extract component dimensions and hierarchy
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    kg_dims_by_id: Dict[str, Mapping[str, Any]] = {}
    component_parent_by_id: Dict[str, str | None] = {}
    component_modeling_policy_by_id: Dict[str, str] = {}
    component_definition_by_id: Dict[str, str] = {}
    pattern_definition_fallback_by_id: Dict[str, str] = {}

    def _collect_pattern_fallback(pattern_items: Any) -> None:
        if not isinstance(pattern_items, list):
            return
        for pattern in pattern_items:
            if not isinstance(pattern, Mapping):
                continue
            if pattern.get("type") != "rotational_symmetry":
                continue
            prototype = pattern.get("prototype")
            if not isinstance(prototype, str) or not prototype:
                continue
            component_ids = pattern.get("component_ids")
            if not isinstance(component_ids, list):
                component_ids = pattern.get("instances") if isinstance(pattern.get("instances"), list) else []
            for cid in component_ids:
                if isinstance(cid, str) and cid and not _is_definition_sharing_blocked_component(cid):
                    pattern_definition_fallback_by_id[cid] = prototype

    _collect_pattern_fallback(shape.get("patterns"))

    if kg_path.exists():
        kg = _read_json(kg_path)
        if isinstance(kg, Mapping):
            metadata = kg.get("metadata") if isinstance(kg.get("metadata"), Mapping) else {}
            execution_roles = metadata.get("component_execution_roles") if isinstance(metadata.get("component_execution_roles"), Mapping) else {}
            for comp_id, role in execution_roles.items():
                if isinstance(comp_id, str) and str(role).strip().lower() == "standard_part_insert_only":
                    skip_components.add(comp_id)
            _collect_pattern_fallback(kg.get("patterns"))
            components = kg.get("components")
            if isinstance(components, list):
                for comp in components:
                    if isinstance(comp, Mapping):
                        comp_id = comp.get("id")
                        dims = comp.get("dimensions")
                        if isinstance(comp_id, str) and isinstance(dims, Mapping):
                            kg_dims_by_id[comp_id] = dims
                        if isinstance(comp_id, str):
                            parent_id = comp.get("position_parent")
                            component_parent_by_id[comp_id] = parent_id if isinstance(parent_id, str) and parent_id else None
                            policy = comp.get("modeling_policy")
                            if isinstance(policy, str) and policy.strip():
                                component_modeling_policy_by_id[comp_id] = policy.strip().lower()
                            if _is_definition_sharing_blocked_component(comp_id):
                                definition_id = comp_id
                            else:
                                definition_id = _normalize_definition_id(
                                    component_id=comp_id,
                                    value=(
                                        comp.get("definition_id")
                                        if isinstance(comp.get("definition_id"), str)
                                        else comp.get("instanced_from")
                                    ),
                                )
                            component_definition_by_id[comp_id] = definition_id

    for cid, proto in pattern_definition_fallback_by_id.items():
        if not isinstance(cid, str) or not isinstance(proto, str) or not cid or not proto:
            continue
        if cid not in component_definition_by_id:
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=proto)
            continue
        current = component_definition_by_id.get(cid)
        if not isinstance(current, str) or not current.strip() or current == cid:
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=proto)

    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        if not isinstance(cid, str) or not cid:
            continue
        if _is_definition_sharing_blocked_component(cid):
            item_definition_id = cid
        else:
            item_definition_id = _normalize_definition_id(
                component_id=cid,
                value=(
                    item.get("definition_id")
                    if isinstance(item.get("definition_id"), str)
                    else item.get("instanced_from")
                ),
            )
        fallback_proto = pattern_definition_fallback_by_id.get(cid)
        if cid not in component_definition_by_id:
            if isinstance(fallback_proto, str) and fallback_proto and item_definition_id == cid:
                component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=fallback_proto)
            else:
                component_definition_by_id[cid] = item_definition_id
            continue

        current = component_definition_by_id.get(cid)
        if isinstance(fallback_proto, str) and fallback_proto and (not isinstance(current, str) or current == cid):
            component_definition_by_id[cid] = _normalize_definition_id(component_id=cid, value=fallback_proto)

    realization_by_id: Dict[str, Mapping[str, Any]] = {}
    for item in realizations:
        if isinstance(item, Mapping):
            cid = item.get("component_id")
            if isinstance(cid, str) and cid:
                realization_by_id[cid] = item
    component_strategy_by_id: Dict[str, Mapping[str, Any]] = {
        cid: item.get("modeling_strategy")
        for cid, item in realization_by_id.items()
        if isinstance(item.get("modeling_strategy"), Mapping)
    }
    ordered_realization_ids: List[str] = []
    perm_mark: set[str] = set()
    temp_mark: set[str] = set()

    def _dfs_order(cid: str) -> None:
        if cid in perm_mark:
            return
        if cid in temp_mark:
            return
        temp_mark.add(cid)
        parent_id = component_parent_by_id.get(cid)
        if isinstance(parent_id, str) and parent_id in realization_by_id:
            _dfs_order(parent_id)
        temp_mark.remove(cid)
        perm_mark.add(cid)
        ordered_realization_ids.append(cid)

    for cid in sorted(realization_by_id.keys()):
        _dfs_order(cid)

    ordered_realizations: List[Mapping[str, Any]] = [realization_by_id[cid] for cid in ordered_realization_ids if cid in realization_by_id]
    ordered_set = set(ordered_realization_ids)
    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        if isinstance(cid, str) and cid in ordered_set:
            continue
        ordered_realizations.append(item)
    realizations = ordered_realizations

    steps: List[Dict[str, Any]] = []
    emitter = StepEmitter(allowed_registry=allowed, sink=steps)

    _require_function(allowed, "CREATE_COMPONENT")
    root_transforms = _extract_root_transforms(shape)

    container_ids_set: set[str] = set()
    for maybe_parent in component_parent_by_id.values():
        if isinstance(maybe_parent, str) and maybe_parent and maybe_parent not in realization_by_id:
            if component_modeling_policy_by_id.get(maybe_parent) in {"container_only", "reference_only"}:
                continue
            parent_definition_id = component_definition_by_id.get(maybe_parent, maybe_parent)
            if isinstance(parent_definition_id, str) and parent_definition_id and parent_definition_id != maybe_parent:
                continue
            container_ids_set.add(maybe_parent)

    container_ids = sorted(container_ids_set)
    perm_cont: set[str] = set()
    temp_cont: set[str] = set()
    ordered_containers: List[str] = []

    def _dfs_container(cid: str) -> None:
        if cid in perm_cont:
            return
        if cid in temp_cont:
            return
        temp_cont.add(cid)
        parent_id = component_parent_by_id.get(cid)
        if isinstance(parent_id, str) and parent_id in container_ids_set:
            _dfs_container(parent_id)
        temp_cont.remove(cid)
        perm_cont.add(cid)
        ordered_containers.append(cid)

    for cid in container_ids:
        _dfs_container(cid)

    for cid in ordered_containers:
        emitter.emit_step(
            _compile_container_component_step(
                component_id=cid,
                root_transform_mm=root_transforms.get(cid),
            )
        )

    _validate_shape_realization_inputs(shape)

    drift_report = validate_shape_realization_contract(shape)
    preflight_interface_manifest = shape.get("interface_manifest") if isinstance(shape.get("interface_manifest"), Mapping) else None

    if isinstance(preflight_interface_manifest, Mapping):
        name_index = _build_interface_name_index(preflight_interface_manifest)
        interface_violations = _validate_feature_interface_refs(
            shape=shape,
            interface_name_index=name_index,
        )
        filtered_interface_violations: List[Dict[str, Any]] = []
        for violation in interface_violations:
            if not isinstance(violation, Mapping):
                continue
            details = violation.get("details") if isinstance(violation.get("details"), Mapping) else {}
            iface_comp = details.get("interface_component_id")
            if (
                isinstance(iface_comp, str)
                and component_modeling_policy_by_id.get(iface_comp) == "container_only"
                and violation.get("rule") == "feature_interface_not_in_manifest"
            ):
                continue
            filtered_interface_violations.append(dict(violation))
        interface_violations = filtered_interface_violations
        if interface_violations:
            existing = drift_report.get("violations")
            if isinstance(existing, list):
                existing.extend(interface_violations)
            else:
                drift_report["violations"] = interface_violations

            summary = drift_report.get("summary")
            if isinstance(summary, dict):
                current_count = summary.get("violations_count")
                base_count = int(current_count) if isinstance(current_count, int) else 0
                summary["violations_count"] = base_count + len(interface_violations)
    elif isinstance(shape.get("parts"), list):
        missing_manifest_violation = {
            "component_id": "<shape_realization>",
            "path": "shape_realization.interface_manifest",
            "rule": "interface_manifest_unavailable",
            "message": "Cannot validate feature interface references because shape_realization.interface_manifest is missing",
        }
        existing = drift_report.get("violations")
        if isinstance(existing, list):
            existing.append(missing_manifest_violation)
        else:
            drift_report["violations"] = [missing_manifest_violation]

        summary = drift_report.get("summary")
        if isinstance(summary, dict):
            current_count = summary.get("violations_count")
            base_count = int(current_count) if isinstance(current_count, int) else 0
            summary["violations_count"] = base_count + 1

    summary = drift_report.get("summary") if isinstance(drift_report, Mapping) else None
    violation_count = 0
    if isinstance(summary, Mapping):
        count = summary.get("violations_count")
        if isinstance(count, int):
            violation_count = count
    if violation_count == 0:
        violations = drift_report.get("violations") if isinstance(drift_report, Mapping) else None
        if isinstance(violations, list):
            violation_count = len(violations)
    if violation_count > 0:
        drift_path = run_dir / "planning" / "errors" / "contract_drift.json"
        _write_json(drift_path, drift_report)
        raise ValueError(
            f"Shape realization contract drift detected ({violation_count} violations). "
            f"Details written to: {drift_path}"
        )

    for item in realizations:
        if not isinstance(item, Mapping):
            continue
        component_id = item.get("component_id")
        strategy = item.get("modeling_strategy")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(strategy, Mapping):
            raise ValueError(f"Missing modeling_strategy for component '{component_id}'.")

        definition_id = component_definition_by_id.get(component_id, component_id)
        if definition_id != component_id:
            continue

        if component_id in skip_components or _is_standard_part_insert_only_strategy(strategy):
            # Standard parts are inserted exclusively via standard-parts injection.
            # Never compile definition geometry for library-driven insert-only parts.
            continue

        collection_info = strategy.get("collection_info")
        resolution = item.get("parameter_resolution") if isinstance(item, Mapping) else None
        execution_params = _derive_execution_params(
            strategy,
            resolution if isinstance(resolution, Mapping) else None,
        )
        execution_params = _prefer_feature_authored_shaft_bore_base_solid(
            realization=item,
            strategy=strategy,
            execution_params=execution_params,
        )
        
        # Add KG dimensions to execution_params for this component
        # Use standard parameter names (with _param suffix for dimension resolution to work)
        kg_dims = kg_dims_by_id.get(component_id)
        if isinstance(kg_dims, Mapping):
            for dim_key, dim_value in kg_dims.items():
                if isinstance(dim_key, str) and isinstance(dim_value, (int, float)):
                    # KG dimensions are fallback-only. Do not clobber Agent3a's
                    # upgraded realization params (for example hub thickness widened
                    # to accommodate opposed bearing seats).
                    param_name = f"{dim_key}_param"
                    execution_params.setdefault(param_name, float(dim_value))
        
        prefer_placeholders = False
        if isinstance(collection_info, Mapping) and collection_info.get("is_collection"):
            count = collection_info.get("individual_count")
            if isinstance(count, int) and count > 1:
                for i in range(1, count + 1):
                    coll_id = f"{component_id}_{i}"
                    if coll_id in skip_components:
                        continue
                    coll_definition_id = component_definition_by_id.get(coll_id, coll_id)
                    if coll_definition_id != coll_id:
                        continue
                    coll_parent_id = component_parent_by_id.get(coll_id) or component_parent_by_id.get(component_id)
                    coll_parent_ref = None
                    if isinstance(coll_parent_id, str) and coll_parent_id:
                        coll_parent_ref = f"${{{_make_capture_var(_component_prefix(coll_parent_id), 'component_id')}}}"
                    # Also add dimensions for collection members
                    coll_execution_params = dict(execution_params)
                    coll_kg_dims = kg_dims_by_id.get(coll_id)
                    if isinstance(coll_kg_dims, Mapping):
                        for dim_key, dim_value in coll_kg_dims.items():
                            if isinstance(dim_key, str) and isinstance(dim_value, (int, float)):
                                param_name = f"{dim_key}_param"
                                coll_execution_params.setdefault(param_name, float(dim_value))
                    emitter.emit_many(
                        _compile_component_steps(
                            component_id=coll_id,
                            strategy=strategy,
                            allowed=allowed,
                            execution_params=coll_execution_params,
                            prefer_placeholders=True,
                            root_transform_mm=root_transforms.get(coll_id) or root_transforms.get(component_id),
                            parent_component_ref=coll_parent_ref,
                        )
                    )
                continue

        parent_id = component_parent_by_id.get(component_id)
        parent_ref = None
        if isinstance(parent_id, str) and parent_id:
            parent_ref = f"${{{_make_capture_var(_component_prefix(parent_id), 'component_id')}}}"
        emitter.emit_many(
            _compile_component_steps(
                component_id=component_id,
                strategy=strategy,
                allowed=allowed,
                execution_params=execution_params,
                prefer_placeholders=prefer_placeholders,
                root_transform_mm=root_transforms.get(component_id),
                parent_component_ref=parent_ref,
            )
        )

    feature_plan = _extract_feature_plan(shape)
    recipe_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    placements_for_patch = feature_plan.get("connection_placements")
    if isinstance(placements_for_patch, list) and placements_for_patch:
        interface_manifest_for_features = shape.get("interface_manifest") if isinstance(shape.get("interface_manifest"), Mapping) else None
        if not isinstance(interface_manifest_for_features, Mapping):
            raise ValueError("shape_realization.interface_manifest is required for anchored feature compilation")
        recipe_index = _build_interface_recipe_index(interface_manifest_for_features)
    patch_steps, patch_warnings = _compile_feature_patch(
        feature_plan=feature_plan,
        allowed=allowed,
        skip_components=skip_components,
        interface_recipe_index=recipe_index,
        component_definition_by_id=component_definition_by_id,
        component_strategy_by_id=component_strategy_by_id,
    )
    if patch_steps:
        geom_last_id: str | None = None
        for step in reversed(steps):
            sid = step.get("id")
            if isinstance(sid, str) and sid:
                geom_last_id = sid
                break
        if geom_last_id is None:
            raise ValueError("geometry_plan has no valid step id; cannot attach feature patches")
        for step in patch_steps:
            deps = step.get("depends_on")
            if not isinstance(deps, list):
                step["depends_on"] = [geom_last_id]
        emitter.emit_many(patch_steps)

    fastener_intents = _collect_fastener_intents(feature_plan)

    _validate_compiled_step_functions(allowed=allowed, steps=steps)

    steps = inject_standard_parts_steps(
        steps,
        run_dir=run_dir,
        base_dep_step_id=_last_step_id(steps),
    )

    plan_id = "geometry_plan"
    md = shape.get("metadata")
    if isinstance(md, Mapping):
        base = md.get("plan_id")
        if isinstance(base, str) and base:
            plan_id = base.replace("_realization_", "_geometry_plan_")

    plan: Dict[str, Any] = {
        "metadata": {
            "plan_id": plan_id,
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "author": "compile_geometry_plan_3b",
            "capability_registry": {"path": "functions/functions.json"},
            "notes": "Deterministic compilation from shape realization strategies.",
            "fastener_intents": fastener_intents,
        },
        "steps": steps,
        "artifacts": {
            "source_shape_realization": f"planning/shape_realization_round_{round_index}.json",
        },
    }
    if patch_warnings:
        plan["artifacts"]["feature_patch_warnings"] = patch_warnings

    output_path = run_dir / "planning" / f"geometry_plan_round_{round_index}.json"
    _lint_unresolved_placeholders(steps)
    _write_json(output_path, plan)

    assembly_contract_path = run_dir / "planning" / f"geometry_semantics_assembly_round_{round_index}.json"
    modeling_semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    if assembly_contract_path.exists():
        assembly_contract = _read_json(assembly_contract_path)
        if isinstance(assembly_contract, Mapping):
            modeling_semantics: Mapping[str, Any] | None = None
            if modeling_semantics_path.exists():
                payload = _read_json(modeling_semantics_path)
                if isinstance(payload, Mapping):
                    modeling_semantics = payload
            interface_manifest = _make_interface_manifest(
                geometry_plan=plan,
                assembly_contract=assembly_contract,
                modeling_semantics=modeling_semantics,
                component_definition_by_id=component_definition_by_id,
            )
            allow_enrich = os.getenv("FUSION_ALLOW_EXECUTION_CONTEXT_ENRICH", "0").strip() == "1"
            if allow_enrich:
                interface_manifest, resolution_summary = _enrich_manifest_with_execution_context(
                    run_dir=run_dir,
                    manifest=interface_manifest,
                )
            else:
                resolution_summary = {
                    "status": "deferred",
                    "reason": "Execution-context enrichment disabled (set FUSION_ALLOW_EXECUTION_CONTEXT_ENRICH=1 to enable)",
                    "resolved_components": 0,
                }
            metadata = interface_manifest.get("metadata")
            if isinstance(metadata, dict):
                metadata["resolution"] = resolution_summary
            interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
            _write_json(interface_manifest_path, interface_manifest)

    print(f"[OK] Generated geometry plan: {output_path.name}")
    print(f"  - {len(steps)} steps")

    result = {"path": f"planning/geometry_plan_round_{round_index}.json"}
    interface_manifest_path = run_dir / "planning" / f"interface_manifest_round_{round_index}.json"
    if interface_manifest_path.exists():
        result["interface_manifest_path"] = f"planning/interface_manifest_round_{round_index}.json"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile geometry plan from shape realization strategies"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)

    args = parser.parse_args()
    result = run(run_dir=args.run_dir, round_index=args.round_index)
    print(f"Geometry plan: {result['path']}")


if __name__ == "__main__":
    main()








