"""
Agent3a shape-realization planner facade.

The implementation is grouped into a few large modules. This file keeps the
public entrypoint and old helper imports stable.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

from agents.common_utils import read_json as _read_json, write_json as _write_json

from .module_wiring import wire_agent3a_modules

globals().update(wire_agent3a_modules())


def run(
    *,
    run_dir: Path,
    round_index: int
) -> Dict[str, Any]:
    """
    Plan shape realization strategies.
    
    Args:
        run_dir: Run directory
        round_index: Planning round number
    
    Returns:
        Dict with output path
    """
    semantics_path = run_dir / "planning" / f"geometry_semantics_modeling_round_{round_index}.json"
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    
    if not semantics_path.exists():
        raise FileNotFoundError(f"Geometry semantics not found: {semantics_path}")
    if not kg_path.exists():
        raise FileNotFoundError(f"Knowledge graph not found: {kg_path}")
    
    # Load inputs
    semantics = _read_json(semantics_path)
    kg = _read_json(kg_path)
    
    # Plan
    function_registry = _load_function_registry()
    planner = ShapeRealizationPlanner(kg, function_registry=function_registry)
    realization = planner.plan(semantics)

    # Infer layout positions (deterministic + LLM)
    layout_plan = _infer_layout_positions(kg)
    layout_positions = layout_plan.get("layout_positions", {})
    if not isinstance(layout_positions, dict):
        layout_positions = {}

    feature_map = _build_part_feature_map(
        semantics=semantics,
        kg=kg,
        layout_positions=layout_positions,
    )

    anchor_errors = feature_map.pop("__anchor_errors__", []) if isinstance(feature_map, dict) else []
    if isinstance(anchor_errors, list) and anchor_errors:
        error_path = run_dir / "planning" / "errors" / "shape_realization_missing_anchor.json"
        _write_json(
            error_path,
            {
                "metadata": {
                    "source": "Agent3a_shape_realization_planner",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                "errors": anchor_errors,
            },
        )
        raise ValueError(
            f"Hole anchoring contract violated. See: planning/errors/{error_path.name}"
        )

    hole_arbitration = feature_map.pop("__hole_arbitration__", {}) if isinstance(feature_map, dict) else {}
    thread_warnings = feature_map.pop("__thread_warnings__", []) if isinstance(feature_map, dict) else []

    component_realizations = realization.get("component_realizations")
    if not isinstance(component_realizations, list):
        component_realizations = []

    component_type_by_id: Dict[str, str] = {}
    for comp in kg.get("components", []) if isinstance(kg.get("components"), list) else []:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and cid and isinstance(ctype, str):
            component_type_by_id[cid] = ctype

    parts: List[Dict[str, Any]] = []
    for item in component_realizations:
        if not isinstance(item, dict):
            continue
        component_id = item.get("component_id")
        strategy = item.get("modeling_strategy")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(strategy, dict):
            continue
        primary_method = strategy.get("primary_method")
        if not isinstance(primary_method, str) or not primary_method:
            construction_method = strategy.get("construction_method")
            if isinstance(construction_method, str) and construction_method:
                primary_method = construction_method.upper()
            else:
                primary_method = "EXTRUDE"

        coordinate_frame = _build_coordinate_frame(
            component_id=component_id,
            layout_positions=layout_positions,
        )
        origin_raw = coordinate_frame.get("origin_mm")
        origin_mm = origin_raw if isinstance(origin_raw, dict) else {}

        realization_features = item.get("features") if isinstance(item.get("features"), list) else None
        if realization_features is None:
            selected_features = feature_map.get(component_id, [])
        else:
            selected_features = realization_features

        part_record: Dict[str, Any] = {
            "component_id": component_id,
            "realization_class": (
                item.get("realization_class")
                if isinstance(item.get("realization_class"), str)
                else _infer_realization_class(
                    component_type=component_type_by_id.get(component_id, ""),
                    modeling_strategy=strategy,
                    part_payload=item,
                )
            ),
            "primary_method": primary_method,
            "modeling_strategy": strategy,
            "parameter_resolution": item.get("parameter_resolution", {}),
            "contract_pattern_used": item.get("contract_pattern_used"),
            "contract_pattern_source": item.get("contract_pattern_source"),
            "coordinate_frame": coordinate_frame,
            "root_transform_mm": {
                "translation": {
                    "x": float(origin_mm.get("x", 0.0)),
                    "y": float(origin_mm.get("y", 0.0)),
                    "z": float(origin_mm.get("z", 0.0)),
                },
                "rotation_rpy_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            },
            "features": selected_features,
        }
        parts.append(part_record)

    planner._suppress_bearing_backed_wheel_hub_bores(parts, semantics)
    planner._rewrite_hub_slot_mount_fastener_features(parts)
    _rewrite_yoke_support_shaft_bore_features(parts)
    _sync_axisymmetric_bearing_profile_params(parts)

    inherited_interface_manifest = semantics.get("interface_manifest")
    if not isinstance(inherited_interface_manifest, dict):
        inherited_interface_manifest = {
            "metadata": {
                "schema_version": "1.0",
                "source": "agent3a_shape_realization_inherited",
                "warning": "missing interface_manifest in geometry semantics",
            },
            "components": [],
        }

    def _load_ground_component_override() -> str | None:
        env_id = os.getenv("FUSION_GROUND_COMPONENT_ID", "").strip()
        if env_id:
            return env_id

        kg_root = kg.get("root_component_id")
        if isinstance(kg_root, str) and kg_root.strip():
            return kg_root.strip()

        input_dir = run_dir / "input"
        if not input_dir.exists():
            return None
        try:
            import yaml  # type: ignore
        except Exception:
            return None

        def _extract(obj: Any) -> str | None:
            if isinstance(obj, dict):
                v = obj.get("ground_component_id")
                if isinstance(v, str) and v.strip():
                    return v.strip()
                for key in ("placement", "assembly", "constraints", "planner"):
                    out = _extract(obj.get(key))
                    if out:
                        return out
            return None

        for p in sorted(input_dir.glob("*.yml")) + sorted(input_dir.glob("*.yaml")):
            try:
                payload = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out = _extract(payload)
            if out:
                return out
        return None

    all_component_ids: List[str] = []
    seen_component_ids: set[str] = set()
    for comp in (kg.get("components") or []):
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid in seen_component_ids:
            continue
        seen_component_ids.add(cid)
        all_component_ids.append(cid)

    for p in parts:
        if not isinstance(p, Mapping):
            continue
        cid = p.get("component_id")
        if not isinstance(cid, str) or not cid or cid in seen_component_ids:
            continue
        seen_component_ids.add(cid)
        all_component_ids.append(cid)

    placement_plan = _compute_initial_placements(
        kg=kg,
        component_ids=all_component_ids,
        semantics=semantics,
        margin_mm=5.0,
        ground_component_id_override=_load_ground_component_override(),
    )
    initial_placements = placement_plan.get("initial_placements")
    if not isinstance(initial_placements, list):
        initial_placements = []

    _project_hub_radial_slot_geometry(realization, initial_placements)

    placement_groups = placement_plan.get("placement_groups")
    if not isinstance(placement_groups, list):
        placement_groups = []

    # Always write diagnostics (one per run; last round wins).
    try:
        diag = placement_plan.get("diagnostics")
        if not isinstance(diag, dict):
            diag = {}
        _write_json(
            run_dir / "placement_diagnostics.json",
            {
                "metadata": {
                    "source": "Agent3a_shape_realization_planner",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "round_index": int(round_index),
                },
                "summary": placement_plan.get("summary", {}),
                "placement_groups": placement_groups,
                # Explicit, easy-to-assert aliases for DoD:
                # - conflicts: overlap detections (group-level)
                # - corrections: the applied translations/jitters to resolve overlaps
                # - final_placements: resulting poses
                "conflicts": diag.get("group_conflicts", []),
                "corrections": {
                    "applied_group_translations": diag.get("applied_group_translations", []),
                    "axial_jitters": diag.get("axial_jitters", []),
                },
                "final_placements": diag.get("after", []),
                "diagnostics": diag,
            },
        )
    except Exception:
        pass

    realization_output = {
        "metadata": realization.get("metadata", {}),
        "parts": parts,
        "interface_manifest": inherited_interface_manifest,
        "initial_placements": initial_placements,
        "placement_groups": placement_groups,
    }

    meta = realization_output.get("metadata")
    if isinstance(meta, dict):
        meta["layout_inference"] = {
            "mode": layout_plan.get("inference_mode"),
            "warnings": layout_plan.get("warnings", []),
        }
        manifest_components = inherited_interface_manifest.get("components") if isinstance(inherited_interface_manifest, dict) else []
        meta["interface_manifest"] = {
            "component_count": len(manifest_components) if isinstance(manifest_components, list) else 0,
        }
        meta["initial_placements"] = placement_plan.get("summary", {})
        realization_counts: Dict[str, int] = {
            REALIZATION_CLASS_NATIVE: 0,
            REALIZATION_CLASS_HOSTED_STANDARD: 0,
            REALIZATION_CLASS_KINEMATIC_IMPORTED: 0,
        }
        realization_by_component: Dict[str, str] = {}
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            cid = part.get("component_id") if isinstance(part.get("component_id"), str) else None
            rc = part.get("realization_class") if isinstance(part.get("realization_class"), str) else None
            if not isinstance(cid, str) or not cid or not isinstance(rc, str) or not rc:
                continue
            realization_by_component[cid] = rc
            if rc in realization_counts:
                realization_counts[rc] = int(realization_counts.get(rc, 0)) + 1
            else:
                realization_counts[rc] = 1
        meta["realization_classes"] = {
            "counts": realization_counts,
            "by_component": realization_by_component,
        }
        if isinstance(hole_arbitration, Mapping):
            meta["hole_arbitration"] = {
                "kept": hole_arbitration.get("kept", []),
                "dropped": hole_arbitration.get("dropped", []),
            }
        if isinstance(thread_warnings, list) and thread_warnings:
            meta["threading_warnings"] = thread_warnings

    # Write output
    output_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    _write_json(output_path, realization_output)
    
    print(f"[OK] Generated shape realization plan: {output_path.name}")
    print(f"  - {len(parts)} parts")
    if layout_plan.get("layout_positions"):
        print(f"  - {len(layout_plan['layout_positions'])} component positions ({layout_plan['inference_mode']})")
    if layout_plan.get("warnings"):
        for warning in layout_plan["warnings"]:
            print(f"  - [layout] {warning}")
    
    return {"path": f"planning/shape_realization_round_{round_index}.json"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan shape realization strategies"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--round-index", required=True, type=int)
    
    args = parser.parse_args()
    
    result = run(
        run_dir=args.run_dir,
        round_index=args.round_index
    )
    
    print(f"Shape realization plan: {result['path']}")


if __name__ == "__main__":
    main()
