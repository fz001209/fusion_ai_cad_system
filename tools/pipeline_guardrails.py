from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Sequence


# Allowed Outputs Contract (path-level, run_dir-relative, POSIX-style).
#
# NOTE: This is a read-only audit contract. It does not block execution.
#
# A small pragmatic adjustment is included:
# - plan_geometry also writes planner_feedback_round_*.json in this codebase, so it is included.
ALLOWED_OUTPUTS: Dict[str, List[str]] = {
    "requirement_to_kg": [
        "knowledge/knowledge_graph.json",
        "planning/standard_parts_resolved.json",
        "planning/standard_parts_unresolved.json",
        "validation/standard_parts_consistency.json",
    ],
    "plan_geometry_semantic": [
        "planning/geometry_semantics_modeling_round_*.json",
        "planning/geometry_semantics_assembly_round_*.json",
        "planning/interface_manifest_round_*.json",
        "planning/errors/geometry_semantics_feasibility.json",
    ],
    "shape_realization_planner_3a": [
        "planning/shape_realization_round_*.json",
        "placement_diagnostics.json",
        "planning/errors/shape_realization_missing_anchor.json",
    ],
    "compile_geometry_plan_3b": [
        "planning/geometry_plan_round_*.json",
        "planning/interface_manifest_round_*.json",
        "planning/errors/contract_drift.json",
    ],
    "plan_assembly": [
        "planning/assembly_semantics_round_*.json",
        "planning/assembly_patch_round_*.json",
        "planning/errors/assembly_errors.json",
    ],
    "compose_plan": [
        "planning/function_plan_round_*.json",
        "planning/function_plan.json",
        "planning/fallback_review_gate.json",
        "planning/symmetry_fold_report.json",
        "planning/instancing_geometry_audit.json",
        "planning/errors/interface_contract_consistency.json",
        "planning/errors/multi_transform_violation.json",
        "planning/errors/link_errors.json",
        "planning/errors/instancing_duplicate_geometry.json",
        "memory/run_memory.json",
    ],
    "planner_convergence_report": ["planning/planner_convergence_report.json"],
    "planner_experiment_summary": ["experiments_summary.json"],
    "experiments_table_export": [
        "execution/experiments_table.csv",
        "execution/experiments_table.jsonl",
    ],
    "experiments_stats_report": ["execution/experiments_stats.json"],
}


def _norm_rel_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def check_agent_outputs(agent_name: str, outputs_written: Sequence[str]) -> List[str]:
    """Return outputs that violate the agent's allowed outputs contract.

    - Non-blocking: caller decides how to surface violations.
    - Unknown agents default to "no contract" (no violations) to avoid false positives.
    """

    patterns = ALLOWED_OUTPUTS.get(agent_name)
    if not patterns:
        return []

    illegal: List[str] = []
    for out in outputs_written or []:
        if not isinstance(out, str):
            continue
        rel = _norm_rel_path(out)
        if not rel:
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            continue
        illegal.append(rel)

    # stable order for audit readability
    return sorted(set(illegal))


def evaluate_agent_outputs(agent_name: str, outputs_written: Sequence[str]) -> List[Dict[str, Any]]:
    """Evaluate output contract violations with severity and optional auto-repair hints.

    Severity policy:
    - P0: hard contract breach (should block pipeline)
    - P1: warning-level contract drift (should be surfaced and can be auto-repaired)
    - P2: informational contract drift (record only)
    """

    violations = check_agent_outputs(agent_name, outputs_written)
    if not violations:
        return []

    out: List[Dict[str, Any]] = []
    for rel in violations:
        severity = "P1" if rel.startswith("planning/") else "P0"
        item: Dict[str, Any] = {
            "path": rel,
            "severity": severity,
            "code": "output_not_in_allowlist",
            "auto_repair": None,
        }

        if agent_name == "plan_assembly" and rel == "planning/assembly_errors.json":
            item["severity"] = "P1"
            item["auto_repair"] = {
                "action": "move",
                "target_path": "planning/errors/assembly_errors.json",
                "reason": "Normalize diagnostics into planning/errors namespace",
            }

        out.append(item)

    return out
