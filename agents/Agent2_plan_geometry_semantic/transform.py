"""
Agent2 facade.

The implementation is split by functional area. This module keeps the legacy
public import surface stable for the pipeline and tests.
"""

from __future__ import annotations

import argparse
import os
from types import FunctionType
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
from tools.event_log import append_event
from validation.validate_geometry_semantics import validate_geometry_semantics_feasibility
from agents.common_utils import read_json as _read_json, write_json as _write_json

from .module_wiring import wire_agent2_modules

_AGENT2_SPLIT_NAMESPACE = wire_agent2_modules()
globals().update(_AGENT2_SPLIT_NAMESPACE)


def _bind_agent2_helpers_to_facade() -> None:
    """Keep legacy transform.py monkeypatch behavior after splitting modules."""
    for name, value in list(_AGENT2_SPLIT_NAMESPACE.items()):
        if not isinstance(value, FunctionType):
            continue
        if not str(getattr(value, "__module__", "")).startswith("agents.Agent2_plan_geometry_semantic."):
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


_bind_agent2_helpers_to_facade()


def run(*, run_dir: Path, round_index: int) -> Dict[str, Any]:
    """
    Generate Geometry Semantics Plan from Knowledge Graph.
    
    AGENT 2 OUTPUT (this agent):
    - geometry_semantics_modeling_round_{N}.json: Modeling-only semantics for Agent3a
    - geometry_semantics_assembly_round_{N}.json: Assembly semantics contract for Agent4
    
    DOWNSTREAM CONSUMPTION:
    - Agent 3a (shape_realization_planner) reads modeling semantics
    - Agent 4 (plan_assembly) reads assembly semantics contract
    
    DESIGN PHILOSOPHY:
    This agent is CAD-backend agnostic. It describes WHAT to build, not HOW.
    Construction strategies are deferred to Agent 3, which knows CAD specifics.
    """
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    
    if not kg_path.exists():
        raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
    
    kg = _read_json(kg_path)
    
    # 闁衡偓椤栨稑鐦悹?rerun 濠㈣泛绉堕弫?connection_placements
    modeling_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    force_reinfer = os.environ.get("FORCE_REINFER_PLACEMENT", "0") == "1"
    existing_semantics = None
    if modeling_path.exists() and not force_reinfer:
        existing_semantics = _load_existing_geometry_semantics(str(modeling_path))

    # 閻犱緤绱曢悾鑽ょ磽閸濆嫨浜奸柣?connection_id
    missing_ids = _missing_placement_connection_ids(kg, existing_semantics)
    placement_enabled = True
    placement_only_ids: set[str] | None = None
    if force_reinfer:
        # 闊洨鏅弳鎰啅閸欏绠?placements闁挎稑鑻崣蹇涙焾閵娿儮鍋撳▎鎾亾婢舵劕娅㈤柟?
        placement_only_ids = set(_missing_placement_connection_ids(kg, None))
    else:
        if not missing_ids:
            placement_enabled = False
        else:
            placement_only_ids = set(missing_ids)

    # 闁汇垻鍠愰崹姘跺棘閹殿喗鐣遍悹鍥跺幒缁?
    semantics = generate_geometry_semantics(
        kg,
        placement_only_ids=placement_only_ids,
        placement_enabled=placement_enabled
    )
    semantics = _normalize_angles_to_360(semantics)

    # 濠㈣泛绉堕弫銈夊籍瑜忓▓?connection_placements闁挎稑鐗婂Λ顐︽儍閸曨亞鍠橀柛蹇撶墳缁?
    if existing_semantics and "connection_placements" in existing_semantics and not force_reinfer:
        old_placements = existing_semantics["connection_placements"]
        new_placements = semantics.get("connection_placements", [])
        existing_ids = {_normalize_placement_connection_id(p) for p in old_placements}
        merged = list(old_placements)
        merged.extend([p for p in new_placements if _normalize_placement_connection_id(p) not in existing_ids])
        semantics["connection_placements"] = merged

    # 濞存粌鏈鑲╂偘閵夛箑鑵归柣鐐叉４缁辩増绂掗崨顓у殸缂傚倸鎼妵?id闁挎稑鑻崯鈧悹瀣暟閺併倖绋夐埀顒€鈻?LLM闁挎稑鐗呯粭澶屾啺閸℃瑦纾扮€圭寮跺﹢渚€鏁?
    second_pass = os.environ.get("PLACEMENT_SECOND_PASS_LLM", "0") == "1"
    if second_pass and not force_reinfer:
        current = semantics.get("connection_placements", [])
        missing_ids = _missing_placement_connection_ids(kg, {"connection_placements": current})
        if missing_ids:
            second_new = _infer_connection_placements_llm(kg, only_connection_ids=set(missing_ids))
            if second_new:
                existing_ids = {_normalize_placement_connection_id(p) for p in current}
                current.extend([p for p in second_new if _normalize_placement_connection_id(p) not in existing_ids])
                semantics["connection_placements"] = current

    # 閻炴稏鍎电紞鍫㈢磽閸濆嫨浜奸柣?placement闁挎稑鐗嗗畷鐗堟媴瀹ュ浂鍎婇柨?
    placements = semantics.get("connection_placements", [])
    placements = _ensure_placement_completeness(
        kg,
        placements,
        candidate_purposes=PLACEMENT_PURPOSES
    )
    placements = _normalize_placement_schema(placements)
    if placements:
        _apply_deterministic_placement_intents(kg, placements)
        _apply_deterministic_derived_changes(kg, placements)
        _enforce_authoritative_contract_execution_mapping(kg, placements)
        _specialize_opposed_bearing_seat_placements(kg, placements)
        _ensure_holes_for_fasteners(kg, placements)  # 閻炴稏鍎遍崣蹇曠磽閸濆嫨浜奸柣銊ュ閻＄喓鈧鐭粻?
        placements = _split_connection_placements_per_target(semantics=semantics, placements=placements)
        placements = _dedupe_duplicate_authoritative_placements(placements)
        _validate_per_target_placement_consistency(placements)
        mechanism_rewrite_audit = _rewrite_connection_feature_mechanisms(kg, placements)
        if mechanism_rewrite_audit:
            semantics.setdefault("metadata", {})["agent2_connection_mechanism_audit"] = mechanism_rewrite_audit
        _rewrite_axial_retention_on_shaft(kg, placements)
        thread_geometry_audit = _sanitize_thread_features_against_host_geometry(kg, placements)
        if thread_geometry_audit:
            semantics.setdefault("metadata", {})["agent2_thread_geometry_audit"] = thread_geometry_audit
        _ensure_circular_hole_host_is_valid(kg, placements)
        _seed_missing_pattern_parameters(kg, placements)
        _ensure_pattern_parameters_complete(kg, placements)
        _enforce_solved_pattern_parameters(kg, placements)
        _annotate_pcd_groups(placements)
        _prealign_group_circular_patterns(placements)
        _distribute_single_circular_mount_phases(placements)
        _synchronize_pattern_sources_with_location(placements)
        _validate_no_world_coordinates(placements)
        alignment_policy_audit = _normalize_alignment_pin_hole_policy(kg, placements)
        if alignment_policy_audit:
            semantics.setdefault("metadata", {})["agent2_alignment_pin_policy_audit"] = alignment_policy_audit
        semantics["connection_placements"] = placements

    feasibility_report = validate_geometry_semantics_feasibility(
        semantics=semantics,
        kg=kg,
        apply_fallback=True,
    )
    policy_audit = semantics.get("metadata", {}).get("agent2_alignment_pin_policy_audit")
    if isinstance(policy_audit, list) and policy_audit:
        existing_policy_audit = feasibility_report.get("agent2_policy_audit")
        if isinstance(existing_policy_audit, list):
            feasibility_report["agent2_policy_audit"] = existing_policy_audit + [a for a in policy_audit if isinstance(a, dict)]
        else:
            feasibility_report["agent2_policy_audit"] = [a for a in policy_audit if isinstance(a, dict)]
    semantics.setdefault("metadata", {})["placement_feasibility"] = feasibility_report.get("summary", {})
    feasibility_report_path = run_dir / "planning" / "errors" / "geometry_semantics_feasibility.json"
    _write_json(feasibility_report_path, feasibility_report)

    summary = feasibility_report.get("summary")
    blocked_count = 0
    needs_clarification_count = 0
    if isinstance(summary, dict):
        blocked_raw = summary.get("blocked_count")
        if isinstance(blocked_raw, int):
            blocked_count = blocked_raw
        needs_raw = summary.get("needs_clarification_count")
        if isinstance(needs_raw, int):
            needs_clarification_count = needs_raw

    if blocked_count > 0 or needs_clarification_count > 0:
        append_event(
            run_dir=run_dir,
            event_type="warning.geometry_semantics_feasibility",
            data={
                "blocked_count": blocked_count,
                "needs_clarification_count": needs_clarification_count,
                "report": str(feasibility_report_path.relative_to(run_dir)).replace("\\", "/"),
            },
        )

    # Validate against schema if available
    schema_path = Path("planning") / "geometry_semantics_schema.json"
    if schema_path.exists():
        try:
            schema = _read_json(schema_path)
            validator = Draft202012Validator(schema)
            errors = list(validator.iter_errors(semantics))
            if errors:
                print(f"WARNING: Geometry semantics validation failed with {len(errors)} errors")
                for err in errors[:5]:
                    print(f"  - {err.message}")
        except Exception as e:
            print(f"WARNING: Could not validate semantics: {e}")

    # Write modeling-only semantics (for Agent3a)
    modeling_semantics = _build_modeling_semantics(semantics)
    _write_json(modeling_path, modeling_semantics)

    # Generate Geometry-Assembly Contract (MANDATORY for assembly planning)
    contract = _generate_geometry_assembly_contract(semantics, kg)
    assembly_path = run_dir / "planning" / f"geometry_semantics_assembly_round_{round_index}.json"
    _write_json(assembly_path, contract)

    print(f"[OK] Generated geometry-assembly contract: {assembly_path.name}")
    print(f"  - {len(contract['components'])} components with {sum(len(c['interfaces']) for c in contract['components'])} interfaces")
    print(f"  - Allowable attachment types: {', '.join(contract['allowable_attachment_types'])}")

    return {
        "modeling_path": f"planning/geometry_semantics_modeling_round_{round_index}.json",
        "assembly_path": f"planning/geometry_semantics_assembly_round_{round_index}.json"
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate geometry semantics plan")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)
    
    args = parser.parse_args()
    
    result = run(run_dir=args.run_dir, round_index=args.round_index)
    print(f"Generated modeling semantics: {result['modeling_path']}")


if __name__ == "__main__":
    main()
