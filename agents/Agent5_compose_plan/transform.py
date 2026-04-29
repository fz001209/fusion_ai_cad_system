"""
Agent5 compose-plan facade.

The implementation is grouped into a few large modules. This file keeps the
public entrypoint and old helper imports stable.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from types import FunctionType
from typing import Any, Dict, List, Mapping, Tuple

from agents.Agent5_compose_plan.linker import run_linker_pass
from agents.common_utils import read_json as _read_json, write_json as _write_json, collect_defined_vars as _collect_defined_vars

from .module_wiring import wire_agent5_modules

_AGENT5_SPLIT_NAMESPACE = wire_agent5_modules()
globals().update(_AGENT5_SPLIT_NAMESPACE)


def _bind_agent5_helpers_to_facade() -> None:
    """Keep legacy transform.py monkeypatch behavior after splitting modules."""
    for name, value in list(_AGENT5_SPLIT_NAMESPACE.items()):
        if not isinstance(value, FunctionType):
            continue
        module_name = str(getattr(value, "__module__", ""))
        if module_name in {
            "agents.Agent5_compose_plan.linker",
            "agents.Agent5_compose_plan.memory_snapshot",
        }:
            continue
        if not module_name.startswith("agents.Agent5_compose_plan."):
            continue
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
        globals()[name] = rebound


_bind_agent5_helpers_to_facade()


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





