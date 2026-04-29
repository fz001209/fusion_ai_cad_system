"""Step ID, dependency, ordering, and placeholder helpers for Agent5."""

from __future__ import annotations

import heapq
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from jsonschema import Draft202012Validator

from agents.Agent3b_compile_geometry_plan.standard_part_compiler import (
    _load_function_registry as _shared_load_function_registry,
)
from agents.common_utils import read_json as _read_json, collect_defined_vars as _collect_defined_vars


def _validate_json(payload: Dict[str, Any], schema_path: Path) -> None:
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return

    lines = ["Function plan validation failed:"]
    for err in errors[:30]:
        path = ".".join([str(p) for p in err.path]) if err.path else "<root>"
        lines.append(f"- {path}: {err.message}")
    if len(errors) > 30:
        lines.append(f"... (+{len(errors) - 30} more)")
    raise ValueError("\n".join(lines))


def _ensure_unique_step_ids_between(
    base_steps: List[Dict[str, Any]],
    other_steps: List[Dict[str, Any]],
    *,
    prefix: str,
) -> List[Dict[str, Any]]:
    used: set[str] = set()
    for s in base_steps:
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            used.add(sid)

    rename_map: Dict[str, str] = {}

    def alloc(new_id: str) -> str:
        if new_id not in used:
            used.add(new_id)
            return new_id
        i = 2
        while f"{new_id}_{i}" in used:
            i += 1
        nid = f"{new_id}_{i}"
        used.add(nid)
        return nid

    out_steps: List[Dict[str, Any]] = []
    for step in other_steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            out_steps.append(step)
            continue

        if sid in used:
            new_id = alloc(f"{prefix}_{sid}")
            rename_map[sid] = new_id
            step = dict(step)
            step["id"] = new_id
        out_steps.append(step)

    if rename_map:
        # Update depends_on within steps, in case they reference each other.
        updated: List[Dict[str, Any]] = []
        for step in out_steps:
            deps = step.get("depends_on")
            if isinstance(deps, list):
                new_deps: List[Any] = []
                changed = False
                for d in deps:
                    if isinstance(d, str) and d in rename_map:
                        new_deps.append(rename_map[d])
                        changed = True
                    else:
                        new_deps.append(d)
                if changed:
                    step = dict(step)
                    step["depends_on"] = new_deps
            updated.append(step)
        out_steps = updated

    return out_steps


def _last_step_id(steps: List[Dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _dedupe_depends_on(step: Dict[str, Any]) -> Dict[str, Any]:
    deps = step.get("depends_on")
    if not isinstance(deps, list):
        return step
    seen: set[str] = set()
    new_deps: List[Any] = []
    for dep in deps:
        if isinstance(dep, str):
            if dep in seen:
                continue
            seen.add(dep)
        new_deps.append(dep)
    out = dict(step)
    out["depends_on"] = new_deps
    return out


def _add_var_based_dependencies(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    placeholder_re = re.compile(r"\$\{([^}]+)\}")

    def _scan_placeholders(obj: Any) -> List[str]:
        found: List[str] = []
        if isinstance(obj, Mapping):
            for value in obj.values():
                found.extend(_scan_placeholders(value))
        elif isinstance(obj, list):
            for value in obj:
                found.extend(_scan_placeholders(value))
        elif isinstance(obj, str):
            found.extend([m for m in placeholder_re.findall(obj) if isinstance(m, str) and m])
        return found

    producers: Dict[str, List[str]] = {}
    for step in steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        capture = step.get("capture")
        if isinstance(capture, Mapping):
            vars_map = capture.get("vars")
            if isinstance(vars_map, Mapping):
                for var_name in vars_map.keys():
                    if isinstance(var_name, str) and var_name:
                        producers.setdefault(var_name, []).append(sid)
        outputs = step.get("outputs")
        if isinstance(outputs, Mapping):
            for var_name in outputs.keys():
                if isinstance(var_name, str) and var_name:
                    producers.setdefault(var_name, []).append(sid)

    out_steps: List[Dict[str, Any]] = []
    for step in steps:
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            out_steps.append(step)
            continue

        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        vars_used = _scan_placeholders(inputs)

        deps = step.get("depends_on")
        existing_deps: List[str] = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
        seen = set(existing_deps)
        new_deps = list(existing_deps)

        for var_name in vars_used:
            source_steps = producers.get(var_name, [])
            if not source_steps:
                continue
            # Only auto-add dependency for single-producer variables.
            # Multi-producer variables (e.g. body_id refreshed after each
            # hole) are ordered by explicit depends_on from 3b; blindly
            # picking the first producer creates cross-chain cycles after
            # symmetric folding.
            if len(source_steps) != 1:
                continue
            producer_id = source_steps[0]
            if producer_id == sid:
                continue
            if producer_id in seen:
                continue
            new_deps.append(producer_id)
            seen.add(producer_id)

        updated = dict(step)
        updated["depends_on"] = new_deps
        out_steps.append(updated)

    return out_steps


def _deterministic_topological_sort(
    steps: List[Dict[str, Any]],
    *,
    phase_rank_by_id: Mapping[str, int],
) -> List[Dict[str, Any]]:
    id_to_step: Dict[str, Dict[str, Any]] = {}
    original_index: Dict[str, int] = {}

    for idx, step in enumerate(steps):
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"Agent5 compose: step at index {idx} missing valid id")
        if sid in id_to_step:
            raise ValueError(f"Agent5 compose: duplicate step id detected before topo sort: {sid}")
        id_to_step[sid] = _dedupe_depends_on(step)
        original_index[sid] = idx

    outgoing: Dict[str, List[str]] = {sid: [] for sid in id_to_step.keys()}
    indegree: Dict[str, int] = {sid: 0 for sid in id_to_step.keys()}

    for sid, step in id_to_step.items():
        deps = step.get("depends_on")
        if not isinstance(deps, list):
            continue
        seen: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str):
                continue
            if dep in seen:
                continue
            seen.add(dep)
            if dep not in id_to_step:
                raise ValueError(
                    "Agent5 compose: depends_on references unknown step id. "
                    f"step='{sid}', missing_dep='{dep}'"
                )
            outgoing[dep].append(sid)
            indegree[sid] += 1

    heap: List[Tuple[int, int, str]] = []
    for sid, deg in indegree.items():
        if deg == 0:
            heapq.heappush(heap, (int(phase_rank_by_id.get(sid, 99)), int(original_index[sid]), sid))

    sorted_ids: List[str] = []
    while heap:
        _, _, sid = heapq.heappop(heap)
        sorted_ids.append(sid)
        for nxt in outgoing.get(sid, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, (int(phase_rank_by_id.get(nxt, 99)), int(original_index[nxt]), nxt))

    if len(sorted_ids) != len(id_to_step):
        unresolved = [sid for sid, deg in indegree.items() if deg > 0]
        raise ValueError(
            "Agent5 compose: dependency cycle detected during topo sort. "
            f"involved_steps={unresolved}"
        )

    return [id_to_step[sid] for sid in sorted_ids]


def _assert_no_unresolved_placeholders(steps: List[Dict[str, Any]]) -> None:
    _lint_unresolved_placeholders(steps)
    _lint_unresolved_execution_id_placeholders(steps)


def _lint_unresolved_placeholders(steps: List[Dict[str, Any]]) -> None:
    import re

    defined = _collect_defined_vars(steps)
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    suffix_re = re.compile(r"_(distance|width|height|thickness|length)$")

    def _hint(var_name: str) -> str:
        if var_name.endswith("_distance"):
            return "Hint: for wheels use width; for shafts use length; for plates use thickness."
        if var_name.endswith("_width"):
            return "Hint: wheels typically use width for extrude distance."
        if var_name.endswith("_length"):
            return "Hint: shafts typically use length for extrude distance."
        if var_name.endswith("_thickness"):
            return "Hint: plates typically use thickness for extrude distance."
        if var_name.endswith("_height"):
            return "Hint: check if height should map to extrude distance."
        return "Hint: map this placeholder to a concrete dimension."

    def _scan(obj: Any, path: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_path = f"{path}.{key}" if path else str(key)
                found.extend(_scan(value, key_path))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                found.extend(_scan(value, f"{path}[{idx}]"))
        elif isinstance(obj, str):
            for match in placeholder_re.findall(obj):
                found.append((path, match))
        return found

    for step in steps:
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            continue
        matches = _scan(inputs, "inputs")
        for field_path, var_name in matches:
            if var_name in defined:
                continue
            if not suffix_re.search(var_name):
                continue
            step_id = step.get("id")
            func_name = step.get("function")
            unresolved = f"${{{var_name}}}"
            raise ValueError(
                "Unresolved placeholder detected in plan: "
                f"step='{step_id}', function='{func_name}', field='{field_path}', value='{unresolved}'. "
                f"{_hint(var_name)}"
            )


def _lint_no_index_pointer_captures(steps: List[Dict[str, Any]]) -> None:
    """Block non-deterministic JSON pointer captures like "/body_ids/0".

    P0 stability rule: array-index selection is forbidden because it stops being
    stable as soon as a component gains multiple bodies/occurrences.
    """

    index_segment_re = re.compile(r"/(\d+)(/|$)")

    for step in steps:
        if not isinstance(step, dict):
            continue
        capture = step.get("capture")
        if not isinstance(capture, Mapping):
            continue
        vars_map = capture.get("vars")
        if not isinstance(vars_map, Mapping):
            continue
        for var_name, path in vars_map.items():
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            if index_segment_re.search(path):
                raise ValueError(
                    "Index-based JSON pointer capture is forbidden (P0): "
                    f"step='{step.get('id')}', function='{step.get('function')}', var='{var_name}', capture='{path}'. "
                    "Hint: capture stable ids directly (e.g. body_id/occurrence_id) and reference those vars."
                )


def _lint_unresolved_execution_id_placeholders(steps: List[Dict[str, Any]]) -> None:
    """Fail fast if *_component_id/*_occurrence_id/*_body_id placeholders are not defined.

    Rationale: These ids are required for deterministic downstream execution (assembly/interface
    resolution). Leaving them unresolved would only fail later in Fusion execution.
    """

    import re

    defined = _collect_defined_vars(steps)
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    must_exist_suffixes = ("_component_id", "_occurrence_id", "_body_id")

    def _scan(obj: Any, path: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_path = f"{path}.{key}" if path else str(key)
                found.extend(_scan(value, key_path))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                found.extend(_scan(value, f"{path}[{idx}]"))
        elif isinstance(obj, str):
            for match in placeholder_re.findall(obj):
                found.append((path, match))
        return found

    for step in steps:
        if not isinstance(step, dict):
            continue
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            continue

        matches = _scan(inputs, "inputs")
        for field_path, var_name in matches:
            if not isinstance(var_name, str):
                continue
            if not var_name.endswith(must_exist_suffixes):
                continue
            if var_name in defined:
                continue
            raise ValueError(
                "Unresolved execution id placeholder detected in plan: "
                f"step='{step.get('id')}', function='{step.get('function')}', field='{field_path}', value='${{{var_name}}}'. "
                "Hint: ensure this id is captured (CREATE_COMPONENT / stdpart insert / GET_SINGLE_BODY_ID) before it is referenced."
            )


def _compress_redundant_activate_steps(steps: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Remove redundant consecutive ACTIVATE_COMPONENT steps safely.

    Only removes a step when ALL are true:
    - function is ACTIVATE_COMPONENT
    - current active component is already the same component_id
    - step has no capture/outputs side effects
    Then rewires depends_on references from removed step id to kept step id.
    """

    if not isinstance(steps, list) or not steps:
        return list(steps), {"removed_count": 0, "rewired_dependency_edges": 0}

    kept: List[Dict[str, Any]] = []
    removed_to_kept: Dict[str, str] = {}
    active_component: str | None = None
    active_source_step_id: str | None = None

    def _activate_target(step: Mapping[str, Any]) -> str | None:
        if step.get("function") != "ACTIVATE_COMPONENT":
            return None
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else None
        if not isinstance(inputs, Mapping):
            return None
        cid = inputs.get("component_id")
        return cid if isinstance(cid, str) and cid else None

    for step in steps:
        if not isinstance(step, Mapping):
            continue

        current = dict(step)
        current_id = current.get("id") if isinstance(current.get("id"), str) else None
        current_target = _activate_target(current)

        if current_target:
            has_capture = isinstance(current.get("capture"), Mapping) and bool(current.get("capture"))
            has_outputs = isinstance(current.get("outputs"), Mapping) and bool(current.get("outputs"))
            current_id = current.get("id") if isinstance(current.get("id"), str) else None

            if (
                active_component == current_target
                and active_source_step_id
                and current_id
                and not has_capture
                and not has_outputs
            ):
                removed_to_kept[current_id] = active_source_step_id
                continue

            if current_id:
                active_component = current_target
                active_source_step_id = current_id

        kept.append(current)

    if not removed_to_kept:
        return kept, {"removed_count": 0, "rewired_dependency_edges": 0}

    rewired_edges = 0
    for step in kept:
        deps = step.get("depends_on")
        if not isinstance(deps, list) or not deps:
            continue

        new_deps: List[str] = []
        for dep in deps:
            if not isinstance(dep, str):
                continue
            target = dep
            seen: set[str] = set()
            while target in removed_to_kept and target not in seen:
                seen.add(target)
                target = removed_to_kept[target]
            if target != dep:
                rewired_edges += 1
            if target not in new_deps:
                new_deps.append(target)
        step["depends_on"] = new_deps

    return kept, {
        "removed_count": len(removed_to_kept),
        "rewired_dependency_edges": rewired_edges,
        "removed_step_ids": sorted(removed_to_kept.keys()),
    }


def _load_function_registry() -> Dict[str, Any]:
    return _shared_load_function_registry()
