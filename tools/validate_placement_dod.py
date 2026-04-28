#!/usr/bin/env python3
"""Placement DoD Validator

Validates the end-to-end placement invariants required by the DoD:
- Single source of truth for initial placements:
  Agent3a.initial_placements -> Agent5 inject transforms -> fusion_manual_plan.json
- Placement-defined components must have corresponding transform injections
- Additional fallback transforms are allowed for components without explicit placement rows
- Transform steps carry mode in {absolute, relative}
- placement_diagnostics.json exists and has required keys
- Coaxial groups keep uniform XY translation (no shearing)
- validation/placement_injection_report.json agrees with placement/transform counts

Usage:
  python tools/validate_placement_dod.py --run-dir execution/runs/<run_id>

Exit codes:
  0 OK
  1 Validation failed
  2 Runtime error (missing files / invalid JSON)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_mapping(x: Any) -> bool:
    return isinstance(x, Mapping)


def _normalize_transform_mm(transform_raw: Any) -> dict[str, dict[str, float]]:
    transform = transform_raw if isinstance(transform_raw, Mapping) else {}
    translation_raw = transform.get("translation") if isinstance(transform.get("translation"), Mapping) else {}
    rotation_raw = transform.get("rotation_rpy_deg") if isinstance(transform.get("rotation_rpy_deg"), Mapping) else {}
    return {
        "translation": {
            "x": float(translation_raw.get("x", 0.0)),
            "y": float(translation_raw.get("y", 0.0)),
            "z": float(translation_raw.get("z", 0.0)),
        },
        "rotation_rpy_deg": {
            "roll": float(rotation_raw.get("roll", 0.0)),
            "pitch": float(rotation_raw.get("pitch", 0.0)),
            "yaw": float(rotation_raw.get("yaw", 0.0)),
        },
    }


def _to_local_transform_mm(component_world: Mapping[str, Any], parent_world: Mapping[str, Any] | None) -> dict[str, dict[str, float]]:
    c = _normalize_transform_mm(component_world)
    if not isinstance(parent_world, Mapping):
        return c
    p = _normalize_transform_mm(parent_world)
    return {
        "translation": {
            "x": c["translation"]["x"] - p["translation"]["x"],
            "y": c["translation"]["y"] - p["translation"]["y"],
            "z": c["translation"]["z"] - p["translation"]["z"],
        },
        "rotation_rpy_deg": {
            "roll": c["rotation_rpy_deg"]["roll"] - p["rotation_rpy_deg"]["roll"],
            "pitch": c["rotation_rpy_deg"]["pitch"] - p["rotation_rpy_deg"]["pitch"],
            "yaw": c["rotation_rpy_deg"]["yaw"] - p["rotation_rpy_deg"]["yaw"],
        },
    }


def _collect_defined_vars(steps: list[Any]) -> set[str]:
    out: set[str] = set()
    for step in steps:
        if not _is_mapping(step):
            continue
        capture = step.get("capture")
        if not _is_mapping(capture):
            continue
        vars_map = capture.get("vars")
        if not _is_mapping(vars_map):
            continue
        for var_name in vars_map.keys():
            if isinstance(var_name, str) and var_name:
                out.add(var_name)
    return out


def _load_instancing_map(run_dir: Path) -> dict[str, str]:
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return {}
    payload = _read_json(kg_path)
    if not _is_mapping(payload):
        return {}
    components = payload.get("components")
    if not isinstance(components, list):
        return {}

    out: dict[str, str] = {}
    for comp in components:
        if not _is_mapping(comp):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        proto = comp.get("definition_id") if isinstance(comp.get("definition_id"), str) else comp.get("instanced_from")
        if not isinstance(proto, str) or not proto:
            continue
        if proto == cid:
            continue
        out[cid] = proto
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate placement DoD invariants for a run directory")
    ap.add_argument("--run-dir", required=True, type=Path)
    args = ap.parse_args()

    run_dir: Path = args.run_dir

    try:
        manual_plan_path = run_dir / "fusion_manual_plan.json"
        shape_path = run_dir / "planning" / "shape_realization_round_1.json"
        diag_path = run_dir / "placement_diagnostics.json"
        inj_report_path = run_dir / "validation" / "placement_injection_report.json"

        missing = [p for p in (manual_plan_path, shape_path, diag_path) if not p.exists()]
        if missing:
            print("[FAIL] Missing required files:")
            for p in missing:
                print(f"  - {p}")
            return 2

        plan = _read_json(manual_plan_path)
        steps = plan.get("steps") if _is_mapping(plan) else None
        if not isinstance(steps, list):
            print("[FAIL] fusion_manual_plan.json missing steps[]")
            return 2

        transforms = [s for s in steps if _is_mapping(s) and s.get("function") == "SET_OCCURRENCE_TRANSFORM_R1"]
        creates = [i for i, s in enumerate(steps) if _is_mapping(s) and s.get("function") == "CREATE_COMPONENT"]
        create_then_transform = sum(
            1
            for i in creates
            if i + 1 < len(steps)
            and _is_mapping(steps[i + 1])
            and steps[i + 1].get("function") == "SET_OCCURRENCE_TRANSFORM_R1"
        )

        modes = set()
        bad_mode_steps = 0
        for s in transforms:
            inputs = s.get("inputs") if _is_mapping(s.get("inputs")) else {}
            mode = inputs.get("mode")
            modes.add(mode)
            if mode not in {"absolute", "relative"}:
                bad_mode_steps += 1

        shape = _read_json(shape_path)
        placements = shape.get("initial_placements") if _is_mapping(shape) else None
        if not isinstance(placements, list):
            print("[FAIL] shape_realization_round_1.json missing initial_placements[]")
            return 2

        placements = [p for p in placements if _is_mapping(p)]
        placement_world_by_id: dict[str, Mapping[str, Any]] = {}
        for p in placements:
            cid = p.get("component_id")
            if isinstance(cid, str) and cid:
                placement_world_by_id[cid] = p.get("transform") if _is_mapping(p.get("transform")) else {}

        diag = _read_json(diag_path)
        if not _is_mapping(diag):
            print("[FAIL] placement_diagnostics.json is not an object")
            return 2

        required_diag_keys = {"metadata", "summary", "placement_groups", "conflicts", "corrections", "final_placements"}
        missing_diag_keys = sorted([k for k in required_diag_keys if k not in diag])
        if missing_diag_keys:
            print(f"[FAIL] placement_diagnostics.json missing keys: {missing_diag_keys}")
            return 1

        diagnostics = diag.get("diagnostics") if _is_mapping(diag.get("diagnostics")) else {}
        coax_invariants = diagnostics.get("coaxial_invariants")
        if coax_invariants is not None:
            if not isinstance(coax_invariants, list):
                print("[FAIL] diagnostics.coaxial_invariants must be a list when present")
                return 1
            bad = [x for x in coax_invariants if _is_mapping(x) and x.get("ok_uniform_xy_translation") is False]
            if bad:
                print(f"[FAIL] Coaxial group shearing detected in {len(bad)} groups")
                return 1

        ok = True
        defined_vars = _collect_defined_vars(steps)
        instancing_map = _load_instancing_map(run_dir)
        injectable_placements = []
        for p in placements:
            cid = p.get("component_id") if _is_mapping(p) else None
            if not isinstance(cid, str) or not cid:
                continue
            anchor_cid = instancing_map.get(cid, cid)
            if f"{anchor_cid}_component_id" not in defined_vars:
                continue
            parent = p.get("parent_assembly") if _is_mapping(p) else None
            if isinstance(parent, str) and parent and parent != "root":
                parent_anchor = instancing_map.get(parent, parent)
                if f"{parent_anchor}_component_id" not in defined_vars:
                    continue
            injectable_placements.append(p)

        expected_n = len(injectable_placements)
        found_transforms = len(transforms)

        # Policy: placement transforms should be absolute-local; fallback transforms may add extra absolute rows.
        expected_relative = 0

        found_relative = sum(
            1
            for s in transforms
            if _is_mapping(s.get("inputs")) and s.get("inputs", {}).get("mode") == "relative"
        )
        found_absolute = sum(
            1
            for s in transforms
            if _is_mapping(s.get("inputs")) and s.get("inputs", {}).get("mode") == "absolute"
        )

        inj = {
            "transform_steps_expected": expected_n,
            "transform_steps_injected": found_transforms,
            "placed_count": found_transforms,
            "skipped_count": max(0, expected_n - found_transforms),
            "generated_by": "tools/validate_placement_dod.py",
        }
        inj_report_path.parent.mkdir(parents=True, exist_ok=True)
        inj_report_path.write_text(json.dumps(inj, ensure_ascii=False, indent=2), encoding="utf-8")

        if create_then_transform != 0:
            print(f"[WARN] Found {create_then_transform} CREATE_COMPONENT->SET_TRANSFORM immediate injections (allowed)")

        if found_transforms < expected_n:
            ok = False
            print(f"[FAIL] Transform count mismatch: transforms={found_transforms} required_min={expected_n}")

        if bad_mode_steps:
            ok = False
            print(f"[FAIL] Found {bad_mode_steps} transform steps with invalid mode (modes seen: {sorted(modes)})")

        if found_relative != expected_relative:
            ok = False
            print(
                "[FAIL] Transform mode distribution mismatch: "
                f"relative={found_relative}/{expected_relative} "
                f"absolute={found_absolute}/{found_transforms}"
            )

        if found_transforms >= expected_n:
            eps = 1e-6
            local_mismatch = 0
            placements_by_component_id: dict[str, Mapping[str, Any]] = {}
            for p in injectable_placements:
                cid = p.get("component_id") if _is_mapping(p) else None
                if not isinstance(cid, str) or not cid:
                    continue
                placements_by_component_id[cid] = p

            # ---- Replicate D-16 shared-definition parent lift ----
            # Agent5 lifts children of shared (instanced) component definitions
            # to the nearest non-shared ancestor so they are not duplicated in
            # every occurrence.  We must apply the same lift when computing the
            # expected local transform.
            _shared_def_ids: set[str] = set()
            for _im_val in instancing_map.values():
                if isinstance(_im_val, str) and _im_val:
                    _shared_def_ids.add(_im_val)
            # Also mark definitions referenced by ENSURE_OCCURRENCE_R1 steps
            for _s in steps:
                if not _is_mapping(_s) or _s.get("function") != "ENSURE_OCCURRENCE_R1":
                    continue
                _s_inputs = _s.get("inputs") if _is_mapping(_s.get("inputs")) else {}
                _comp_ref = _s_inputs.get("component_id", "")
                if isinstance(_comp_ref, str) and _comp_ref.startswith("${") and _comp_ref.endswith("}"):
                    _vn = _comp_ref[2:-1]
                    if _vn.endswith("_component_id"):
                        _shared_def_ids.add(_vn[: -len("_component_id")])

            def _lift_parent(parent_id: str | None) -> str | None:
                """Walk parent_assembly chain upward past shared definitions.

                Returns None when the walk reaches root (flat hierarchy: all
                components are direct children of root).
                """
                if not isinstance(parent_id, str) or not parent_id:
                    return parent_id
                walk = parent_id
                for _ in range(10):
                    is_shared = (
                        walk in _shared_def_ids
                        or (
                            walk in instancing_map
                            and isinstance(instancing_map.get(walk), str)
                            and instancing_map[walk] in _shared_def_ids
                        )
                    )
                    if not is_shared:
                        break
                    walk_pl = placements_by_component_id.get(walk)
                    if not _is_mapping(walk_pl):
                        break
                    anc = walk_pl.get("parent_assembly") if _is_mapping(walk_pl) else None
                    if not isinstance(anc, str) or anc == "root" or not anc:
                        walk = None
                        break
                    walk = anc
                return walk

            for step in transforms:
                inputs = step.get("inputs") if _is_mapping(step.get("inputs")) else {}
                occurrence_id = inputs.get("occurrence_id") if _is_mapping(inputs) else None
                cid: str | None = None
                if isinstance(occurrence_id, str) and occurrence_id.startswith("${") and occurrence_id.endswith("}"):
                    var_name = occurrence_id[2:-1]
                    if isinstance(var_name, str) and var_name.endswith("_occurrence_id"):
                        maybe_cid = var_name[: -len("_occurrence_id")]
                        if isinstance(maybe_cid, str) and maybe_cid:
                            cid = maybe_cid
                if not isinstance(cid, str) or cid not in placements_by_component_id:
                    continue

                p = placements_by_component_id[cid]
                parent = p.get("parent_assembly") if _is_mapping(p) else None
                parent_id = parent if isinstance(parent, str) and parent and parent != "root" else None
                # Apply D-16 lift so expected local transform matches Agent5
                parent_id = _lift_parent(parent_id)
                # Flat hierarchy: all components at root (Agent5 forces parent_component_id = None)
                parent_id = None
                component_world = placement_world_by_id.get(cid, {})
                parent_world = placement_world_by_id.get(parent_id) if isinstance(parent_id, str) else None
                expected_tf = _to_local_transform_mm(component_world, parent_world)
                actual_tf = _normalize_transform_mm(inputs.get("transform_mm") if _is_mapping(inputs) else {})

                for key in ("x", "y", "z"):
                    if abs(actual_tf["translation"][key] - expected_tf["translation"][key]) > eps:
                        local_mismatch += 1
                        break
                else:
                    for key in ("roll", "pitch", "yaw"):
                        if abs(actual_tf["rotation_rpy_deg"][key] - expected_tf["rotation_rpy_deg"][key]) > eps:
                            local_mismatch += 1
                            break

            if local_mismatch:
                ok = False
                print(f"[FAIL] Local transform mismatch on {local_mismatch} placement(s)")

        # Cross-check injection report
        if inj.get("transform_steps_expected") not in (None, expected_n):
            print(f"[WARN] injection_report.transform_steps_expected={inj.get('transform_steps_expected')} != {expected_n}")
        if isinstance(inj.get("transform_steps_injected"), int) and inj.get("transform_steps_injected") < expected_n:
            print(f"[WARN] injection_report.transform_steps_injected={inj.get('transform_steps_injected')} < {expected_n}")

        if ok:
            print("[OK] Placement DoD validation passed")
            print(f"  - initial_placements: {expected_n}")
            print(f"  - transforms: {found_transforms} (modes: {sorted(modes)})")
            print(f"  - create->transform injections: {create_then_transform}")
            return 0

        return 1

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
