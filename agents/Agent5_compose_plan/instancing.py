"""Instancing, placeholder rewrite, placement injection, and transform audits for Agent5."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from agents.common_utils import read_json as _read_json, write_json as _write_json

from .input_contracts import (
    _load_shape_realization_payload,
    _rewrite_fastener_initial_placements,
)


def _load_initial_placements(run_dir: Path, *, round_index: int) -> List[Dict[str, Any]]:
    payload = _load_shape_realization_payload(run_dir, round_index=round_index)
    if not isinstance(payload, Mapping):
        return []
    placements = payload.get("initial_placements")
    if not isinstance(placements, list):
        return []
    normalized = [dict(p) for p in placements if isinstance(p, Mapping)]
    return _rewrite_fastener_initial_placements(
        normalized,
        run_dir=run_dir,
        round_index=round_index,
        shape_payload=payload,
    )


_DEFINITION_SHARING_BLOCKED_TYPES = {
    "arm",
    "axle",
    "bearing",
    "fastener",
    "hub",
    "rim",
    "spacer",
    "tire",
    "wheel",
}

_DEFINITION_SHARING_BLOCKED_PART_KINDS = {
    "bearing",
    "fastener_bundle",
}

_DEFINITION_SHARING_BLOCKED_ID_PATTERNS = (
    re.compile(r"^wheel_\d+$"),
    re.compile(r"^wheel_arm_\d+$"),
    re.compile(r"^wheel_\d+_(axle|bearing_\d+|fastener_set|hub|rim|spacer|tire)$"),
)


def _is_definition_sharing_blocked_component(component: Mapping[str, Any] | str | None) -> bool:
    cid: str | None = None
    if isinstance(component, Mapping):
        raw_id = component.get("id")
        cid = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
        ctype = component.get("type")
        if isinstance(ctype, str) and ctype.strip().lower() in _DEFINITION_SHARING_BLOCKED_TYPES:
            return True
        part_kind = component.get("part_kind")
        if isinstance(part_kind, str) and part_kind.strip().lower() in _DEFINITION_SHARING_BLOCKED_PART_KINDS:
            return True
        modeling_policy = component.get("modeling_policy")
        if isinstance(modeling_policy, str) and modeling_policy.strip().lower() == "container_only":
            return True
        if bool(component.get("is_container_only")):
            return True
    elif isinstance(component, str):
        cid = component.strip() or None

    if not cid:
        return False
    return any(pattern.fullmatch(cid) for pattern in _DEFINITION_SHARING_BLOCKED_ID_PATTERNS)


def _load_instancing_map(run_dir: Path) -> Dict[str, str]:
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return {}
    try:
        payload = _read_json(kg_path)
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    out: Dict[str, str] = {}
    blocked_component_ids: set[str] = set()

    components = payload.get("components")
    if isinstance(components, list):
        for comp in components:
            if not isinstance(comp, Mapping):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str) or not cid:
                continue
            if _is_definition_sharing_blocked_component(comp):
                blocked_component_ids.add(cid)
                continue

            proto: str | None = None
            instanced_from = comp.get("instanced_from")
            definition_id = comp.get("definition_id")
            if isinstance(instanced_from, str) and instanced_from and instanced_from != cid:
                proto = instanced_from
            elif isinstance(definition_id, str) and definition_id and definition_id != cid:
                proto = definition_id

            if (
                isinstance(proto, str)
                and proto
                and cid not in blocked_component_ids
                and not _is_definition_sharing_blocked_component(proto)
            ):
                out[cid] = proto

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                continue
            ptype = pattern.get("type")
            if not (isinstance(ptype, str) and ptype.strip().lower() == "rotational_symmetry"):
                continue
            instances = pattern.get("instances") if isinstance(pattern.get("instances"), list) else pattern.get("component_ids")
            if not isinstance(instances, list):
                continue
            prototype = pattern.get("prototype") if isinstance(pattern.get("prototype"), str) else None
            if not (isinstance(prototype, str) and prototype):
                prototype = next(
                    (
                        instance_id
                        for instance_id in instances
                        if isinstance(instance_id, str) and instance_id
                    ),
                    None,
                )
            if not isinstance(prototype, str) or not prototype:
                continue
            if _is_definition_sharing_blocked_component(prototype):
                continue
            for instance_id in instances:
                if not isinstance(instance_id, str) or not instance_id or instance_id == prototype:
                    continue
                if instance_id in blocked_component_ids or _is_definition_sharing_blocked_component(instance_id):
                    continue
                out.setdefault(instance_id, prototype)

    return out


def _load_connection_canonical_map(run_dir: Path, *, instancing_map: Mapping[str, str]) -> Dict[str, str]:
    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        return {}
    try:
        payload = _read_json(kg_path)
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}

    reqs = payload.get("connection_requirements")
    if not isinstance(reqs, list):
        return {}

    grouped: Dict[Tuple[str, ...], List[str]] = {}
    for req in reqs:
        if not isinstance(req, Mapping):
            continue
        rid = req.get("id")
        between = req.get("between")
        if not (isinstance(rid, str) and rid and isinstance(between, list) and between):
            continue

        canonical_between: List[str] = []
        for cid in between:
            if not isinstance(cid, str) or not cid:
                continue
            canonical_between.append(instancing_map.get(cid, cid))
        if not canonical_between:
            continue

        signature = tuple(sorted(canonical_between))
        grouped.setdefault(signature, []).append(rid)

    alias_map: Dict[str, str] = {}
    for ids in grouped.values():
        if len(ids) <= 1:
            continue
        canonical_id = sorted(ids)[0]
        for rid in ids:
            if rid != canonical_id:
                alias_map[rid] = canonical_id
    return alias_map


_REWRITE_BLOCKED_FIELDS = {
    "parent_component_id",
    "occurrence_name",
    "occurrence_id",
}


def _is_rewrite_allowed_field(*, field_name: str | None, step_function: str | None) -> bool:
    if not isinstance(field_name, str) or not field_name:
        return False
    if field_name in _REWRITE_BLOCKED_FIELDS:
        return False
    if step_function in {"ENSURE_OCCURRENCE_R1", "CREATE_COMPONENT"} and field_name == "parent_component_id":
        return False

    if field_name in {"component_id", "body_id", "component_ids", "body_ids"}:
        return True
    if field_name.endswith("_component_id") or field_name.endswith("_body_id"):
        return True
    return False


def _rewrite_placeholders_obj(
    obj: Any,
    var_map: Mapping[str, str],
    *,
    step_function: str | None = None,
    field_name: str | None = None,
) -> Any:
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            inner = obj[2:-1]
            if inner in var_map and _is_rewrite_allowed_field(field_name=field_name, step_function=step_function):
                return f"${{{var_map[inner]}}}"
        return obj
    if isinstance(obj, list):
        return [
            _rewrite_placeholders_obj(
                v,
                var_map,
                step_function=step_function,
                field_name=field_name,
            )
            for v in obj
        ]
    if isinstance(obj, Mapping):
        out: Dict[Any, Any] = {}
        for k, v in obj.items():
            key_name = k if isinstance(k, str) else None
            out[k] = _rewrite_placeholders_obj(
                v,
                var_map,
                step_function=step_function,
                field_name=key_name,
            )
        return out
    return obj


def _rewrite_step_placeholders(
    steps: List[Dict[str, Any]],
    var_map: Mapping[str, str],
    *,
    restricted: bool = True,
) -> List[Dict[str, Any]]:
    if not var_map:
        return steps

    if restricted:
        out: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, Mapping):
                out.append(step)
                continue
            step_function = step.get("function") if isinstance(step.get("function"), str) else None
            rewritten = _rewrite_placeholders_obj(step, var_map, step_function=step_function)
            out.append(rewritten)
        return out

    # Unrestricted mode: regex-replace all ${闁炽儺娲?placeholders regardless of field.
    placeholder_re = re.compile(r"\$\{([A-Za-z0-9_.]+)\}")

    def _rewrite_obj(obj: Any) -> Any:
        if isinstance(obj, str):
            def _sub(match: re.Match[str]) -> str:
                inner = match.group(1)
                mapped = var_map.get(inner)
                if isinstance(mapped, str) and mapped:
                    return f"${{{mapped}}}"
                return match.group(0)

            return placeholder_re.sub(_sub, obj)
        if isinstance(obj, list):
            return [_rewrite_obj(v) for v in obj]
        if isinstance(obj, Mapping):
            out_m: Dict[Any, Any] = {}
            for k, v in obj.items():
                out_m[k] = _rewrite_obj(v)
            return out_m
        return obj

    out_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            out_steps.append(step)
            continue
        out_steps.append(_rewrite_obj(step))
    return out_steps


def _build_stdpart_instance_var_alias_map(steps: List[Dict[str, Any]]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    pattern = re.compile(r"^\$\{([A-Za-z0-9_.]+)\}$")

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        function_name = step.get("function")
        if function_name != "ENSURE_OCCURRENCE_R1":
            continue
        step_id = step.get("id")
        if not (isinstance(step_id, str) and step_id.startswith("stdpart_")):
            continue

        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        component_ref = inputs.get("component_id")
        if not isinstance(component_ref, str):
            continue
        match = pattern.match(component_ref)
        if match is None:
            continue
        prototype_component_var = match.group(1)
        if not prototype_component_var.endswith("_component_id"):
            continue
        prototype_prefix = prototype_component_var[: -len("_component_id")]

        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        for var_name, output_key in vars_map.items():
            if not (isinstance(var_name, str) and isinstance(output_key, str)):
                continue
            if output_key != "occurrence_id" or not var_name.endswith("_occurrence_id"):
                continue
            instance_prefix = var_name[: -len("_occurrence_id")]
            if not instance_prefix or instance_prefix == prototype_prefix:
                continue
            alias_map[f"{instance_prefix}_component_id"] = f"{prototype_prefix}_component_id"
            alias_map[f"{instance_prefix}_body_id"] = f"{prototype_prefix}_body_id"

    return alias_map


_DIRECT_JOINT_TO_AS_BUILT = {
    "RIGID_JOINT_R1": "RIGID_AS_BUILT_JOINT",
    "REVOLUTE_JOINT_R1": "REVOLUTE_AS_BUILT_JOINT",
}


def _placeholder_prefix(value: Any, suffix: str) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\$\{([A-Za-z0-9_.]+)\}", value)
    if match is None:
        return None
    inner = match.group(1)
    if not inner.endswith(suffix):
        return None
    return inner[: -len(suffix)]


def _upgrade_instanced_regular_joints_to_as_built(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not steps:
        return steps

    aliased_joint_bases: set[str] = set()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str):
            continue
        if not (step_id.endswith("_resolve_a") or step_id.endswith("_resolve_b")):
            continue
        metadata = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
        logical_component_id = metadata.get("component_id") if isinstance(metadata.get("component_id"), str) else None
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        prototype_prefix = _placeholder_prefix(inputs.get("component_id"), "_component_id")
        if logical_component_id and prototype_prefix and logical_component_id != prototype_prefix:
            aliased_joint_bases.add(step_id.rsplit("_resolve_", 1)[0])

    upgraded: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            upgraded.append(step)
            continue
        function_name = step.get("function")
        if function_name not in _DIRECT_JOINT_TO_AS_BUILT:
            upgraded.append(dict(step))
            continue

        step_id = step.get("id")
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        joint_component_prefix = _placeholder_prefix(inputs.get("component_id"), "_component_id")
        occurrence_prefixes = {
            prefix
            for prefix in (
                _placeholder_prefix(inputs.get("occurrence_one_id"), "_occurrence_id"),
                _placeholder_prefix(inputs.get("occurrence_two_id"), "_occurrence_id"),
            )
            if isinstance(prefix, str) and prefix
        }
        base_id = step_id.rsplit("_joint", 1)[0] if isinstance(step_id, str) and step_id.endswith("_joint") else None
        if not (isinstance(base_id, str) and base_id in aliased_joint_bases):
            upgraded.append(dict(step))
            continue

        upgraded_step = dict(step)
        upgraded_step["function"] = _DIRECT_JOINT_TO_AS_BUILT[str(function_name)]
        upgraded.append(upgraded_step)

    return upgraded


def _step_touches_component(step: Mapping[str, Any], component_id: str) -> bool:
    marker_vars = {
        f"{component_id}_component_id",
        f"{component_id}_body_id",
        f"{component_id}_occurrence_id",
    }

    def _scan(v: Any) -> bool:
        if isinstance(v, str):
            if v.startswith("${") and v.endswith("}"):
                inner = v[2:-1]
                if inner in marker_vars:
                    return True
            return False
        if isinstance(v, Mapping):
            for vv in v.values():
                if _scan(vv):
                    return True
            return False
        if isinstance(v, list):
            for vv in v:
                if _scan(vv):
                    return True
            return False
        return False

    if _scan(step):
        return True

    capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
    vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
    for var_name in vars_map.keys():
        if isinstance(var_name, str) and var_name in marker_vars:
            return True

    outputs = step.get("outputs") if isinstance(step.get("outputs"), Mapping) else {}
    for var_name in outputs.keys():
        if isinstance(var_name, str) and var_name in marker_vars:
            return True

    metadata = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
    md_cid = metadata.get("component_id")
    return isinstance(md_cid, str) and md_cid == component_id


def _drop_steps_with_removed_dependencies(
    steps: List[Dict[str, Any]],
    *,
    removed_step_ids: set[str],
) -> tuple[List[Dict[str, Any]], set[str]]:
    if not steps:
        return [], set(removed_step_ids)

    removed_all = {sid for sid in removed_step_ids if isinstance(sid, str) and sid}
    kept_steps = [dict(step) for step in steps if isinstance(step, Mapping)]

    changed = True
    while changed:
        changed = False
        next_kept: List[Dict[str, Any]] = []
        for step in kept_steps:
            sid = step.get("id")
            if isinstance(sid, str) and sid in removed_all:
                changed = True
                continue

            deps = step.get("depends_on")
            dep_ids = [dep for dep in deps if isinstance(dep, str)] if isinstance(deps, list) else []
            if any(dep in removed_all for dep in dep_ids):
                if isinstance(sid, str) and sid:
                    removed_all.add(sid)
                changed = True
                continue

            next_kept.append(step)
        kept_steps = next_kept

    return kept_steps, removed_all


def _extract_component_placeholder_from_step(step: Mapping[str, Any]) -> str | None:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
    cid_ref = inputs.get("component_id") if isinstance(inputs.get("component_id"), str) else None
    if not isinstance(cid_ref, str):
        return None
    m = re.fullmatch(r"\$\{([A-Za-z0-9_.]+)_component_id\}", cid_ref)
    if not m:
        return None
    return m.group(1)


def _merge_instanced_geometry_steps(
    geometry_steps: List[Dict[str, Any]],
    *,
    run_dir: Path,
    round_index: int,
    instancing_map: Mapping[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Dict[str, Any]]:
    if not instancing_map:
        return geometry_steps, {}, {"instanced_components": 0, "removed_steps": 0}

    component_instancing_meta: Dict[str, Dict[str, Any]] = {}

    def _upsert_component_meta(source: str, comp_payload: Mapping[str, Any]) -> None:
        cid = comp_payload.get("id")
        if not isinstance(cid, str) or not cid:
            cid = comp_payload.get("component_id")
        if not isinstance(cid, str) or not cid:
            return

        current = component_instancing_meta.setdefault(
            cid,
            {
                "component_id": cid,
                "definition_id": None,
                "instance_id": None,
                "instanced_from": None,
                "sources": [],
            },
        )

        for key in ("definition_id", "instance_id", "instanced_from"):
            value = comp_payload.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()

        if source not in current["sources"]:
            current["sources"].append(source)

    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    if kg_path.exists():
        try:
            kg_payload = _read_json(kg_path)
        except Exception:
            kg_payload = {}
        if isinstance(kg_payload, Mapping):
            components = kg_payload.get("components")
            if isinstance(components, list):
                for comp in components:
                    if isinstance(comp, Mapping):
                        _upsert_component_meta("knowledge_graph", comp)

    shape_path = run_dir / "planning" / f"shape_realization_round_{round_index}.json"
    if shape_path.exists():
        try:
            shape_payload = _read_json(shape_path)
        except Exception:
            shape_payload = {}
        if isinstance(shape_payload, Mapping):
            for key in ("parts", "component_realizations"):
                items = shape_payload.get(key)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, Mapping):
                            _upsert_component_meta("shape_realization", item)

    instance_ids = sorted({cid for cid in instancing_map.keys() if isinstance(cid, str) and cid})
    prototype_ids = sorted({proto for proto in instancing_map.values() if isinstance(proto, str) and proto})

    removed_step_ids: set[str] = set()
    duplicate_ops: List[Dict[str, Any]] = []
    suggested_fix_points: set[str] = set()

    def _build_fix_suggestion(*, component_id: str, prototype_id: str | None, meta: Mapping[str, Any]) -> Dict[str, Any]:
        definition_id = meta.get("definition_id") if isinstance(meta.get("definition_id"), str) else None
        instanced_from = meta.get("instanced_from") if isinstance(meta.get("instanced_from"), str) else None
        instance_id = meta.get("instance_id") if isinstance(meta.get("instance_id"), str) else None

        if not definition_id and not instanced_from:
            suggested_fix_points.add("Agent1_requirement_to_kg")
            return {
                "owner": "Agent1_requirement_to_kg",
                "message": "Missing instancing metadata: instance components need definition_id/instanced_from or a rotational_symmetry prototype.",
                "fields": ["components[*].definition_id", "components[*].instanced_from", "patterns[*].prototype"],
            }

        if isinstance(prototype_id, str) and prototype_id and definition_id and definition_id != prototype_id:
            suggested_fix_points.add("Agent1_requirement_to_kg")
            return {
                "owner": "Agent1_requirement_to_kg",
                "message": "definition_id does not match the instancing prototype; normalize definition_id/instanced_from to the prototype.",
                "fields": ["components[*].definition_id", "components[*].instanced_from"],
            }
        suggested_fix_points.add("Agent3b_compile_geometry_plan")
        return {
            "owner": "Agent3b_compile_geometry_plan",
            "message": "Instancing drift: geometry planning emitted instance-specific geometry without consistent definition_id/prototype metadata.",
            "fields": ["component_definition_by_id", "patterns.rotational_symmetry.prototype"],
            "instance_id": instance_id,
        }

    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {"ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}:
            continue
        touched_instances = [cid for cid in instance_ids if _step_touches_component(step, cid)]
        if not touched_instances:
            continue
        if isinstance(sid, str) and sid:
            removed_step_ids.add(sid)
        for cid in touched_instances:
            component_meta = component_instancing_meta.get(
                cid,
                {
                    "component_id": cid,
                    "definition_id": None,
                    "instance_id": None,
                    "instanced_from": None,
                    "sources": [],
                },
            )
            suggestion = _build_fix_suggestion(
                component_id=cid,
                prototype_id=instancing_map.get(cid),
                meta=component_meta,
            )
            duplicate_ops.append(
                {
                    "step_id": sid,
                    "function": function_name,
                    "component_id": cid,
                    "instance_component_id": cid,
                    "prototype_component_id": instancing_map.get(cid),
                    "instancing_fields": {
                        "definition_id": component_meta.get("definition_id"),
                        "instance_id": component_meta.get("instance_id"),
                        "instanced_from": component_meta.get("instanced_from"),
                        "sources": component_meta.get("sources"),
                    },
                    "suggested_fix_point": suggestion,
                }
            )

    kept_steps: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if isinstance(sid, str) and sid in removed_step_ids:
            continue
        step_copy = dict(step)
        deps = step_copy.get("depends_on")
        if isinstance(deps, list):
            step_copy["depends_on"] = [d for d in deps if not (isinstance(d, str) and d in removed_step_ids)]
        kept_steps.append(step_copy)

    var_map: Dict[str, str] = {}
    for cid, proto in instancing_map.items():
        if not isinstance(cid, str) or not isinstance(proto, str) or not cid or not proto:
            continue
        var_map[f"{cid}_component_id"] = f"{proto}_component_id"
        var_map[f"{cid}_body_id"] = f"{proto}_body_id"

    rewritten = _rewrite_step_placeholders(kept_steps, var_map)

    report = {
        "round_index": int(round_index),
        "instanced_components": len(instance_ids),
        "prototypes": prototype_ids,
        "removed_steps": len(removed_step_ids),
        "removed_step_ids": sorted(removed_step_ids),
        "duplicate_geometry_ops": duplicate_ops,
    }

    if duplicate_ops:
        error_payload = {
            "metadata": {
                "source": "Agent5_compose_plan.instancing_audit",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "instanced_components": len(instance_ids),
                "duplicate_geometry_step_count": len(duplicate_ops),
                "suggested_fix_points": sorted(suggested_fix_points),
            },
            "duplicates": duplicate_ops,
            "component_instancing_metadata": [
                component_instancing_meta[cid]
                for cid in sorted(component_instancing_meta.keys())
                if cid in set(instance_ids)
            ],
        }
        _write_json(run_dir / "planning" / "errors" / "instancing_duplicate_geometry.json", error_payload)
        raise RuntimeError(
            "instancing_duplicate_geometry_detected: same prototype geometry generated for multiple instances. "
            "See planning/errors/instancing_duplicate_geometry.json"
        )

    return rewritten, var_map, report


def _fold_symmetric_connection_geometry_steps(
    geometry_steps: List[Dict[str, Any]],
    *,
    instancing_map: Mapping[str, str],
    connection_alias_map: Mapping[str, str] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not geometry_steps or not instancing_map:
        return geometry_steps, {"removed_steps": 0, "removed_step_ids": []}

    token_pairs: List[Tuple[str, str]] = []

    def _tail2(value: str) -> str | None:
        parts = [p for p in value.split("_") if p]
        if len(parts) >= 2:
            return "_".join(parts[-2:])
        return None

    def _family_root(value: str) -> str | None:
        parts = [p for p in value.split("_") if p]
        if len(parts) < 2:
            return None
        if not parts[1].isdigit():
            return None
        return f"{parts[0]}_{parts[1]}"

    for inst, proto in instancing_map.items():
        if not (isinstance(inst, str) and isinstance(proto, str) and inst and proto and inst != proto):
            continue
        token_pairs.append((inst, proto))
        inst_tail = _tail2(inst)
        proto_tail = _tail2(proto)
        if isinstance(inst_tail, str) and isinstance(proto_tail, str) and inst_tail and proto_tail and inst_tail != proto_tail:
            token_pairs.append((inst_tail, proto_tail))
        inst_root = _family_root(inst)
        proto_root = _family_root(proto)
        if isinstance(inst_root, str) and isinstance(proto_root, str) and inst_root and proto_root and inst_root != proto_root:
            token_pairs.append((inst_root, proto_root))

    # Keep deterministic order and dedupe pair definitions.
    seen_pair: set[Tuple[str, str]] = set()
    ordered_pairs: List[Tuple[str, str]] = []
    for pair in sorted(token_pairs, key=lambda p: (-len(p[0]), p[0], p[1])):
        if pair in seen_pair:
            continue
        seen_pair.add(pair)
        ordered_pairs.append(pair)

    def _canonicalize_step_id(step_id: str) -> str:
        out = step_id
        for src, dst in ordered_pairs:
            if src == dst:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(src)}(?![A-Za-z0-9])")
            out = pattern.sub(dst, out)
        return out

    alias_map = dict(connection_alias_map or {})

    def _canonicalize_connection_req_tokens(step_id: str) -> str:
        out = step_id
        for source_id, canonical_id in sorted(alias_map.items(), key=lambda item: (-len(item[0]), item[0])):
            if source_id == canonical_id:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(source_id)}(?![A-Za-z0-9])")
            out = pattern.sub(canonical_id, out)
        return out

    def _canonicalize_full_step_id(step_id: str) -> str:
        return _canonicalize_connection_req_tokens(_canonicalize_step_id(step_id))

    def _eligible(step: Mapping[str, Any], step_id: str) -> bool:
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {
            "CREATE_COMPONENT",
            "ENSURE_OCCURRENCE_R1",
            "SET_OCCURRENCE_TRANSFORM_R1",
            "CREATE_SKETCH_ON_PLANE",
            "SKETCH_CIRCLE",
            "SKETCH_RECTANGLE",
            "EXTRUDE_NEW_BODY",
        }:
            return False
        lowered = step_id.lower()
        component_token = _extract_component_placeholder_from_step(step)
        if not (isinstance(component_token, str) and component_token):
            return False
        if _canonicalize_full_step_id(step_id) != step_id:
            return True
        for source_id, canonical_id in alias_map.items():
            for token in (source_id, canonical_id):
                if not (isinstance(token, str) and token):
                    continue
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])")
                if pattern.search(step_id):
                    return True
        if "req_" in lowered:
            return True
        if "central_hub" in component_token.lower() and "arm_" in lowered:
            return any(tok in lowered for tok in ("hole", "pattern", "resolve_face", "activate", "counterbore", "countersink"))
        return False

    canonical_groups: Dict[str, List[str]] = {}
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        if not _eligible(step, sid):
            continue
        canonical = _canonicalize_full_step_id(sid)
        canonical = re.sub(r"_[0-9]+$", "", canonical)
        canonical_groups.setdefault(canonical, []).append(sid)

    removed_to_kept: Dict[str, str] = {}
    folded_pairs: List[Dict[str, str]] = []
    for canonical_key, members in canonical_groups.items():
        if len(members) <= 1:
            continue

        # Distinguish prototype steps (canonicalization left ID unchanged) from
        # instance-derived steps (ID was rewritten).  Prototype steps within the
        # same canonical group are SEQUENTIAL operations (e.g. re_resolve_face_2
        # and re_resolve_face_4 in the same feature chain for *one* arm) and must
        # NOT be folded together.  Only instance-derived duplicates are genuinely
        # symmetric and should be collapsed.
        prototype_sids = frozenset(
            sid for sid in members if _canonicalize_full_step_id(sid) == sid
        )
        instance_sids = [sid for sid in members if sid not in prototype_sids]

        if not instance_sids:
            # All members are prototype steps 闁?sequential, not symmetric copies.
            continue

        if prototype_sids:
            winner = sorted(prototype_sids)[0]
        elif canonical_key in members:
            winner = canonical_key
        else:
            winner = sorted(members)[0]

        for sid in sorted(members):
            if sid == winner or sid in prototype_sids:
                continue
            removed_to_kept[sid] = winner
            folded_pairs.append(
                {
                    "removed_step_id": sid,
                    "canonical_step_id": winner,
                    "canonical_key": canonical_key,
                }
            )

    # Remove dependent symmetric duplicates that directly depend on already removed seeds.
    changed = True
    while changed:
        changed = False
        for step in geometry_steps:
            if not isinstance(step, Mapping):
                continue
            sid = step.get("id")
            if not isinstance(sid, str) or not sid or sid in removed_to_kept:
                continue
            if not _eligible(step, sid):
                continue
            deps = step.get("depends_on")
            if not isinstance(deps, list):
                continue
            removed_dep = next((d for d in deps if isinstance(d, str) and d in removed_to_kept), None)
            if not isinstance(removed_dep, str):
                continue
            removed_to_kept[sid] = removed_to_kept[removed_dep]
            folded_pairs.append(
                {
                    "removed_step_id": sid,
                    "canonical_step_id": removed_to_kept[removed_dep],
                    "canonical_key": "dependent_removed_with_seed",
                }
            )
            changed = True

    if not removed_to_kept:
        return geometry_steps, {
            "removed_steps": 0,
            "removed_step_ids": [],
            "folded_pairs": [],
            "connection_alias_count": len(alias_map),
        }

    kept: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if isinstance(sid, str) and sid in removed_to_kept:
            continue
        step_copy = dict(step)
        deps = step_copy.get("depends_on")
        if isinstance(deps, list) and deps:
            new_deps: List[str] = []
            for dep in deps:
                if not isinstance(dep, str):
                    continue
                target = dep
                seen: set[str] = set()
                while target in removed_to_kept and target not in seen:
                    seen.add(target)
                    target = removed_to_kept[target]
                if target not in new_deps:
                    new_deps.append(target)
            step_copy["depends_on"] = new_deps
        kept.append(step_copy)

    step_by_id: Dict[str, Mapping[str, Any]] = {}
    for step in geometry_steps:
        sid = step.get("id") if isinstance(step, Mapping) else None
        if isinstance(sid, str) and sid:
            step_by_id[sid] = step

    var_alias_map: Dict[str, str] = {}
    for removed_id, kept_id in removed_to_kept.items():
        removed_step = step_by_id.get(removed_id)
        kept_step = step_by_id.get(kept_id)
        if not (isinstance(removed_step, Mapping) and isinstance(kept_step, Mapping)):
            continue

        removed_capture = removed_step.get("capture") if isinstance(removed_step.get("capture"), Mapping) else {}
        kept_capture = kept_step.get("capture") if isinstance(kept_step.get("capture"), Mapping) else {}
        removed_vars = removed_capture.get("vars") if isinstance(removed_capture.get("vars"), Mapping) else {}
        kept_vars = kept_capture.get("vars") if isinstance(kept_capture.get("vars"), Mapping) else {}
        if not (isinstance(removed_vars, Mapping) and isinstance(kept_vars, Mapping)):
            continue

        kept_by_output_key: Dict[str, str] = {}
        for kept_var_name, output_key in kept_vars.items():
            if isinstance(kept_var_name, str) and kept_var_name and isinstance(output_key, str) and output_key:
                kept_by_output_key[output_key] = kept_var_name

        for removed_var_name, output_key in removed_vars.items():
            if not (isinstance(removed_var_name, str) and removed_var_name and isinstance(output_key, str) and output_key):
                continue
            mapped_var = kept_by_output_key.get(output_key)
            if isinstance(mapped_var, str) and mapped_var and mapped_var != removed_var_name:
                var_alias_map[removed_var_name] = mapped_var

    if var_alias_map:
        kept = _rewrite_step_placeholders(kept, var_alias_map, restricted=False)

    return kept, {
        "removed_steps": len(removed_to_kept),
        "removed_step_ids": sorted(removed_to_kept.keys()),
        "folded_pairs": folded_pairs,
        "connection_alias_count": len(alias_map),
        "rewritten_var_aliases": len(var_alias_map),
    }


def _audit_instance_specific_geometry_steps(
    *,
    geometry_steps: List[Dict[str, Any]],
    instancing_map: Mapping[str, str],
    run_dir: Path,
    round_index: int,
) -> Dict[str, Any]:
    instances_by_proto: Dict[str, List[str]] = {}
    for instance_id, prototype_id in instancing_map.items():
        if not (isinstance(instance_id, str) and instance_id and isinstance(prototype_id, str) and prototype_id):
            continue
        instances_by_proto.setdefault(prototype_id, []).append(instance_id)

    risky_groups = {
        proto: sorted({proto, *instances})
        for proto, instances in instances_by_proto.items()
        if len(set(instances + [proto])) >= 2
    }
    if not risky_groups:
        return {
            "round_index": int(round_index),
            "prototypes_with_multi_instances": 0,
            "violations": 0,
            "violating_step_ids": [],
        }

    def _instance_alias_tokens(token: str) -> List[str]:
        aliases = {token}
        m = re.match(r"^([A-Za-z]+_[0-9]+)_", token)
        if m:
            aliases.add(m.group(1))
        parts = [p for p in token.split("_") if p]
        if len(parts) >= 2:
            aliases.add("_".join(parts[-2:]))
        return sorted(a for a in aliases if a)

    violations: List[Dict[str, Any]] = []
    for step in geometry_steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in {"ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}:
            continue

        component_token = _extract_component_placeholder_from_step(step)
        if not (isinstance(component_token, str) and component_token in risky_groups):
            continue

        instance_tokens: List[str] = []
        for token in risky_groups[component_token]:
            if token == component_token:
                continue
            aliases = _instance_alias_tokens(token)
            if any((f"req_{alias}_" in sid or f"_{alias}_" in sid) for alias in aliases):
                instance_tokens.append(token)
        if not instance_tokens:
            continue

        violations.append(
            {
                "step_id": sid,
                "function": function_name,
                "prototype_component_id": component_token,
                "instance_tokens": sorted(instance_tokens),
                "rule": "no_instance_specific_requirement_id_on_shared_prototype_geometry",
            }
        )

    if violations:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.instancing_geometry_audit",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "prototypes_with_multi_instances": len(risky_groups),
                "violations": len(violations),
            },
            "prototypes": [
                {"prototype_component_id": proto, "instances": instances}
                for proto, instances in sorted(risky_groups.items())
            ],
            "violations": violations,
        }
        _write_json(run_dir / "planning" / "errors" / "instancing_geometry_step_audit.json", payload)
        raise RuntimeError(
            "instancing_geometry_step_audit_failed: instance-specific requirement IDs detected on shared prototype geometry. "
            "See planning/errors/instancing_geometry_step_audit.json"
        )

    return {
        "round_index": int(round_index),
        "prototypes_with_multi_instances": len(risky_groups),
        "violations": 0,
        "violating_step_ids": [],
    }


def _inject_initial_placements(
    steps: List[Dict[str, Any]],
    *,
    run_dir: Path,
    round_index: int,
    instancing_map: Mapping[str, str] | None = None,
    var_alias_map: Mapping[str, str] | None = None,
) -> List[Dict[str, Any]]:
    placements = _load_initial_placements(run_dir, round_index=round_index)
    report: Dict[str, Any] = {
        "round_index": int(round_index),
        "placements_total": len(placements),
        "transform_steps_expected": len(placements),
        "transform_steps_injected": 0,
        "placed_count": 0,
        "skipped_count": 0,
        "placed_component_ids": [],
        "placed": [],
        "skipped": [],
    }

    instancing = dict(instancing_map or {})
    var_aliases = {
        str(src): str(dst)
        for src, dst in dict(var_alias_map or {}).items()
        if isinstance(src, str) and src and isinstance(dst, str) and dst
    }

    def _resolve_var_alias(var_name: str) -> str:
        current = var_name
        seen: set[str] = set()
        while current in var_aliases and current not in seen:
            seen.add(current)
            nxt = var_aliases[current]
            if not isinstance(nxt, str) or not nxt or nxt == current:
                break
            current = nxt
        return current

    used_ids: set[str] = set()
    for step in steps:
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            used_ids.add(sid)

    def _unique_id(base: str) -> str:
        if base not in used_ids:
            used_ids.add(base)
            return base
        i = 2
        while f"{base}_{i}" in used_ids:
            i += 1
        out = f"{base}_{i}"
        used_ids.add(out)
        return out

    placement_by_component: Dict[str, Mapping[str, Any]] = {}
    world_transform_by_component: Dict[str, Dict[str, Any]] = {}

    def _normalize_transform_mm(transform_raw: Any) -> Dict[str, Any]:
        tr_raw = transform_raw if isinstance(transform_raw, Mapping) else {}
        t_raw = tr_raw.get("translation") if isinstance(tr_raw.get("translation"), Mapping) else {}
        r_raw = tr_raw.get("rotation_rpy_deg") if isinstance(tr_raw.get("rotation_rpy_deg"), Mapping) else {}
        return {
            "translation": {
                "x": float(t_raw.get("x", 0.0)),
                "y": float(t_raw.get("y", 0.0)),
                "z": float(t_raw.get("z", 0.0)),
            },
            "rotation_rpy_deg": {
                "roll": float(r_raw.get("roll", 0.0)),
                "pitch": float(r_raw.get("pitch", 0.0)),
                "yaw": float(r_raw.get("yaw", 0.0)),
            },
        }

    for placement in placements:
        cid = placement.get("component_id")
        if not isinstance(cid, str) or not cid:
            continue
        placement_by_component[cid] = placement
        world_transform_by_component[cid] = _normalize_transform_mm(placement.get("transform"))

    def _to_local_transform(component_id: str, parent_component_id: str | None) -> Dict[str, Any]:
        world = world_transform_by_component.get(component_id)
        if not isinstance(world, Mapping):
            return _normalize_transform_mm({})
        if not isinstance(parent_component_id, str) or not parent_component_id:
            return dict(world)

        parent_world = world_transform_by_component.get(parent_component_id)
        if not isinstance(parent_world, Mapping):
            return dict(world)

        wt = world.get("translation") if isinstance(world.get("translation"), Mapping) else {}
        wr = world.get("rotation_rpy_deg") if isinstance(world.get("rotation_rpy_deg"), Mapping) else {}
        pt = parent_world.get("translation") if isinstance(parent_world.get("translation"), Mapping) else {}
        pr = parent_world.get("rotation_rpy_deg") if isinstance(parent_world.get("rotation_rpy_deg"), Mapping) else {}

        return {
            "translation": {
                "x": float(wt.get("x", 0.0)) - float(pt.get("x", 0.0)),
                "y": float(wt.get("y", 0.0)) - float(pt.get("y", 0.0)),
                "z": float(wt.get("z", 0.0)) - float(pt.get("z", 0.0)),
            },
            "rotation_rpy_deg": {
                "roll": float(wr.get("roll", 0.0)) - float(pr.get("roll", 0.0)),
                "pitch": float(wr.get("pitch", 0.0)) - float(pr.get("pitch", 0.0)),
                "yaw": float(wr.get("yaw", 0.0)) - float(pr.get("yaw", 0.0)),
            },
        }

    for placement in placements:
        cid = placement.get("component_id")
        if not isinstance(cid, str) or not cid:
            report["skipped"].append({"component_id": cid, "reason": "invalid_component_id"})
            continue
        placement_by_component[cid] = placement

    required_components: set[str] = set()
    placement_satisfied_components: set[str] = set(placement_by_component.keys())

    def _select_required_component_ids(candidates: List[str]) -> List[str]:
        normalized = [cid for cid in candidates if isinstance(cid, str) and cid]
        if not normalized:
            return []
        unique = sorted(set(normalized))

        def _is_standard_alias(component_id: str) -> bool:
            return component_id.startswith("stdpart_") or component_id.startswith("std_")

        if len(unique) <= 1:
            if unique and _is_standard_alias(unique[0]):
                return []
            return unique

        # Standard-part injection may capture both an internal alias prefix
        # (e.g. stdpart_xxx_component_id) and the bound real component id
        # from the same output key. For completeness gating, prefer canonical
        # component ids that already have placement records.
        present_in_placements = [cid for cid in unique if cid in placement_by_component]
        if present_in_placements:
            return present_in_placements

        non_stdpart = [cid for cid in unique if not _is_standard_alias(cid)]
        if non_stdpart:
            return non_stdpart

        return []

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if not isinstance(vars_map, Mapping):
            continue
        step_component_ids: List[str] = []
        step_occurrence_ids: List[str] = []
        for var_name, output_key in vars_map.items():
            if not isinstance(var_name, str) or not var_name:
                continue
            if output_key == "component_id" and var_name.endswith("_component_id"):
                cid = var_name[: -len("_component_id")]
                if isinstance(cid, str) and cid:
                    step_component_ids.append(cid)
                continue
            if output_key == "occurrence_id":
                if var_name.endswith("_existing_occurrence_id"):
                    cid = var_name[: -len("_existing_occurrence_id")]
                elif var_name.endswith("_occurrence_id"):
                    cid = var_name[: -len("_occurrence_id")]
                else:
                    cid = None
                if isinstance(cid, str) and cid:
                    step_occurrence_ids.append(cid)

        resolved_component_ids = _select_required_component_ids(step_component_ids)
        resolved_occurrence_ids = _select_required_component_ids(step_occurrence_ids)
        for cid in resolved_component_ids:
            required_components.add(cid)
        for cid in resolved_occurrence_ids:
            required_components.add(cid)
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        has_explicit_transform = (
            (step.get("function") == "CREATE_COMPONENT" and isinstance(inputs.get("transform"), Mapping))
            or (step.get("function") == "ENSURE_OCCURRENCE_R1" and isinstance(inputs.get("transform_mm"), Mapping))
        )
        if has_explicit_transform:
            for cid in resolved_component_ids:
                placement_satisfied_components.add(cid)

    for cid, proto in instancing.items():
        if isinstance(cid, str) and cid:
            required_components.add(cid)
        if isinstance(proto, str) and proto:
            required_components.add(proto)

    missing_placement_components = sorted(
        cid for cid in required_components if cid not in placement_satisfied_components
    )
    if missing_placement_components:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "required_components": len(required_components),
                "missing_initial_placements": len(missing_placement_components),
            },
            "missing_component_ids": missing_placement_components,
        }
        _write_json(run_dir / "planning" / "errors" / "initial_placement_completeness.json", payload)
        raise RuntimeError(
            "initial_placement_completeness_failed: missing initial_placements for one or more required components. "
            "See planning/errors/initial_placement_completeness.json"
        )

    step_ids_by_index: Dict[int, str] = {}
    var_last_def: Dict[str, Tuple[int, str]] = {}
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else None
        if not isinstance(sid, str) or not sid:
            continue
        step_ids_by_index[idx] = sid

        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if isinstance(vars_map, Mapping):
            for var_name in vars_map.keys():
                if isinstance(var_name, str) and var_name:
                    var_last_def[var_name] = (idx, sid)

    inject_after_index: Dict[int, List[Dict[str, Any]]] = {}
    existing_ensure_occurrence_names: set[str] = set()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occurrence_name = inputs.get("occurrence_name") if isinstance(inputs, Mapping) else None
        if isinstance(occurrence_name, str) and occurrence_name:
            existing_ensure_occurrence_names.add(occurrence_name)

    def _queue_after(index: int, step_obj: Dict[str, Any]) -> None:
        inject_after_index.setdefault(index, []).append(step_obj)

    # ---- D-16: Detect shared component definitions ----
    # A prototype's Fusion 360 definition is shared once any other component
    # creates an ENSURE_OCCURRENCE_R1 referencing it.  Children added to a
    # shared definition appear in ALL occurrences, so we must *lift* those
    # children to the nearest independent (non-shared) ancestor.
    _shared_def_ids: set[str] = set()
    for _inst_cid in required_components:
        _inst_proto = instancing.get(_inst_cid)
        if not isinstance(_inst_proto, str) or not _inst_proto:
            continue
        _inst_occ_var = f"{_inst_cid}_occurrence_id"
        if not isinstance(var_last_def.get(_inst_occ_var), tuple):
            _shared_def_ids.add(_inst_proto)
    for _s in steps:
        if not isinstance(_s, Mapping) or _s.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        _s_inputs = _s.get("inputs") if isinstance(_s.get("inputs"), Mapping) else {}
        _comp_ref = _s_inputs.get("component_id", "") if isinstance(_s_inputs, Mapping) else ""
        if isinstance(_comp_ref, str) and _comp_ref.startswith("${") and _comp_ref.endswith("}"):
            _vname = _comp_ref[2:-1]
            if _vname.endswith("_component_id"):
                _shared_def_ids.add(_vname[: -len("_component_id")])
    _create_parent_fixes: Dict[int, str | None] = {}

    for cid, placement in placement_by_component.items():
        if cid not in required_components:
            continue

        parent_assembly_raw = placement.get("parent_assembly")
        parent_component_id = (
            str(parent_assembly_raw)
            if isinstance(parent_assembly_raw, str) and parent_assembly_raw and parent_assembly_raw != "root"
            else None
        )

        # ---- D-16: Lift parent out of shared definitions ----
        _original_parent = parent_component_id
        if isinstance(parent_component_id, str) and parent_component_id:
            _walk = parent_component_id
            for _ in range(10):
                _is_shared = (
                    _walk in _shared_def_ids
                    or (
                        _walk in instancing
                        and isinstance(instancing.get(_walk), str)
                        and instancing[_walk] in _shared_def_ids
                    )
                )
                if not _is_shared:
                    break
                _walk_pl = placement_by_component.get(_walk)
                if not isinstance(_walk_pl, Mapping):
                    break
                _anc = _walk_pl.get("parent_assembly")
                if not isinstance(_anc, str) or _anc == "root" or not _anc:
                    _walk = None
                    break
                _walk = _anc
            if _walk != parent_component_id:
                parent_component_id = _walk

        # ---- Flat hierarchy: all components at root ----
        # Fusion 360 occ.transform2 only works for direct children of root,
        # so parent_component_id is always None regardless of KG hierarchy.
        parent_component_id = None

        occurrence_var = f"{cid}_occurrence_id"
        transform = _to_local_transform(cid, parent_component_id)
        grounded = placement.get("ground")
        if not isinstance(grounded, bool):
            grounded = False

        existing_occ_anchor = var_last_def.get(occurrence_var)
        if isinstance(existing_occ_anchor, tuple):
            anchor_idx, anchor_sid = existing_occ_anchor

            # ---- D-16: Fix CREATE_COMPONENT parent for lifted prototypes ----
            if parent_component_id != _original_parent:
                _new_pvar = f"${{{parent_component_id}_component_id}}" if parent_component_id else None
                for _fix_idx, _fix_step in enumerate(steps):
                    if not isinstance(_fix_step, Mapping):
                        continue
                    if _fix_step.get("function") != "CREATE_COMPONENT":
                        continue
                    _fix_capture = _fix_step.get("capture") if isinstance(_fix_step.get("capture"), Mapping) else {}
                    _fix_vars = _fix_capture.get("vars") if isinstance(_fix_capture.get("vars"), Mapping) else {}
                    if f"{cid}_component_id" in _fix_vars:
                        _create_parent_fixes[_fix_idx] = _new_pvar
                        break

            xform_id = _unique_id(f"place_{cid}_xform")
            xform_step: Dict[str, Any] = {
                "id": xform_id,
                "function": "SET_OCCURRENCE_TRANSFORM_R1",
                "inputs": {
                    "occurrence_id": f"${{{occurrence_var}}}",
                    "transform_mm": dict(transform),
                    "mode": "absolute",
                    "grounded": grounded,
                },
                "depends_on": [anchor_sid],
            }
            _queue_after(anchor_idx, xform_step)

            report["placed_count"] = int(report.get("placed_count", 0)) + 1
            report["transform_steps_injected"] = int(report.get("transform_steps_injected", 0)) + 1
            report["placed_component_ids"].append(cid)
            report["placed"].append(
                {
                    "component_id": cid,
                    "prototype_component_id": instancing.get(cid, cid),
                    "occurrence_name": placement.get("occurrence_name") or cid,
                    "grounded": grounded,
                    "mode": "absolute",
                    "parent_component_id": parent_component_id,
                    "transform_mm": dict(transform),
                    "injected_steps": {
                        "ensure_step_id": None,
                        "transform_step_id": xform_id,
                        "anchor_step_id": anchor_sid,
                    },
                }
            )
            continue

        prototype_cid = instancing.get(cid, cid)
        component_var_raw = f"{prototype_cid}_component_id"
        component_var = _resolve_var_alias(component_var_raw)
        component_anchor = var_last_def.get(component_var)
        if not isinstance(component_anchor, tuple):
            report["skipped"].append(
                {
                    "component_id": cid,
                    "reason": "missing_plan_vars",
                    "details": {
                        "required": [component_var_raw],
                        "missing": [component_var_raw],
                        **({"resolved_alias": component_var} if component_var != component_var_raw else {}),
                    },
                }
            )
            continue

        parent_var: str | None = None
        effective_parent_component_id = parent_component_id
        parent_anchor: Tuple[int, str] | None = None
        if isinstance(parent_component_id, str) and parent_component_id:
            parent_candidate_ids: List[str] = [parent_component_id]
            parent_proto = instancing.get(parent_component_id)
            if isinstance(parent_proto, str) and parent_proto and parent_proto not in parent_candidate_ids:
                parent_candidate_ids.append(parent_proto)

            for parent_cid in parent_candidate_ids:
                candidate_var_raw = f"{parent_cid}_component_id"
                candidate_var = _resolve_var_alias(candidate_var_raw)
                candidate_anchor = var_last_def.get(candidate_var)
                if isinstance(candidate_anchor, tuple):
                    parent_var = candidate_var
                    parent_anchor = candidate_anchor
                    break

            if not isinstance(parent_anchor, tuple):
                required_parent_vars = [f"{pcid}_component_id" for pcid in parent_candidate_ids]
                report["skipped"].append(
                    {
                        "component_id": cid,
                        "reason": "missing_parent_component_var",
                        "details": {
                            "parent_component_id": parent_component_id,
                            "required": required_parent_vars,
                        },
                    }
                )
                continue

        anchor_candidates = [component_anchor]
        if isinstance(parent_anchor, tuple):
            anchor_candidates.append(parent_anchor)
        anchor_idx, anchor_sid = max(anchor_candidates, key=lambda item: item[0])

        ensure_id = _unique_id(f"place_{cid}_ensure")
        ensure_inputs: Dict[str, Any] = {
            "component_id": f"${{{component_var}}}",
            "occurrence_name": placement.get("occurrence_name") or cid,
            "parent_component_id": f"${{{parent_var}}}" if isinstance(parent_var, str) and parent_var else None,
            "transform_mm": dict(transform),
        }
        ensure_step: Dict[str, Any] = {
            "id": ensure_id,
            "function": "ENSURE_OCCURRENCE_R1",
            "inputs": ensure_inputs,
            "depends_on": [anchor_sid],
            "capture": {"vars": {occurrence_var: "occurrence_id"}},
        }

        xform_id = _unique_id(f"place_{cid}_xform")
        xform_step = {
            "id": xform_id,
            "function": "SET_OCCURRENCE_TRANSFORM_R1",
            "inputs": {
                "occurrence_id": f"${{{occurrence_var}}}",
                "transform_mm": dict(transform),
                "mode": "absolute",
                "grounded": grounded,
            },
            "depends_on": [ensure_id],
        }
        _queue_after(anchor_idx, ensure_step)
        _queue_after(anchor_idx, xform_step)

        report["placed_count"] = int(report.get("placed_count", 0)) + 1
        report["transform_steps_injected"] = int(report.get("transform_steps_injected", 0)) + 1
        report["placed_component_ids"].append(cid)
        report["placed"].append(
            {
                "component_id": cid,
                "prototype_component_id": prototype_cid,
                "occurrence_name": placement.get("occurrence_name") or cid,
                "grounded": grounded,
                "mode": "absolute",
                "parent_component_id": effective_parent_component_id,
                "transform_mm": dict(transform),
                "injected_steps": {
                    "ensure_step_id": ensure_id,
                    "transform_step_id": xform_id,
                    "anchor_step_id": anchor_sid,
                },
            }
        )

    out_steps: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        _sdict = dict(step)
        # ---- D-16: Apply CREATE_COMPONENT parent fixes ----
        if idx in _create_parent_fixes:
            _fix_inputs = dict(_sdict.get("inputs")) if isinstance(_sdict.get("inputs"), Mapping) else {}
            _fix_inputs["parent_component_id"] = _create_parent_fixes[idx]
            _sdict["inputs"] = _fix_inputs
        out_steps.append(_sdict)
        for injected in inject_after_index.get(idx, []):
            out_steps.append(dict(injected))

    ensure_occurrence_map: Dict[str, List[str]] = {}
    for step in out_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "ENSURE_OCCURRENCE_R1":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occurrence_name = inputs.get("occurrence_name") if isinstance(inputs, Mapping) else None
        if not isinstance(occurrence_name, str) or not occurrence_name:
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) else "<unknown>"
        ensure_occurrence_map.setdefault(occurrence_name, []).append(sid)

    duplicates = {
        name: sorted(step_ids)
        for name, step_ids in ensure_occurrence_map.items()
        if len(step_ids) > 1
    }
    if duplicates:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "duplicate_occurrence_names": len(duplicates),
                "violations": sum(len(v) for v in duplicates.values()),
            },
            "duplicates": [
                {"occurrence_name": name, "ensure_step_ids": step_ids}
                for name, step_ids in sorted(duplicates.items())
            ],
        }
        _write_json(run_dir / "planning" / "errors" / "duplicate_ensure_occurrence.json", payload)
        raise RuntimeError(
            "duplicate_ensure_occurrence_detected: same occurrence_name appears in ENSURE_OCCURRENCE_R1 more than once. "
            "See planning/errors/duplicate_ensure_occurrence.json"
        )

    if report.get("skipped"):
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "violations": len(report.get("skipped") or []),
            },
            "violations": report.get("skipped") or [],
        }
        _write_json(run_dir / "planning" / "errors" / "initial_placement_injection_failures.json", payload)
        raise RuntimeError(
            "initial_placement_injection_failed: cannot inject deterministic placement for all components. "
            "See planning/errors/initial_placement_injection_failures.json"
        )

    out_index_by_step_id: Dict[str, int] = {}
    for idx, step in enumerate(out_steps):
        sid = step.get("id") if isinstance(step, Mapping) and isinstance(step.get("id"), str) else None
        if isinstance(sid, str) and sid:
            out_index_by_step_id[sid] = idx

    def _step_defines_component(step_obj: Mapping[str, Any], component_id: str) -> bool:
        target_var = f"{component_id}_component_id"

        capture = step_obj.get("capture") if isinstance(step_obj.get("capture"), Mapping) else {}
        capture_vars = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        if isinstance(capture_vars, Mapping):
            output_key = capture_vars.get(target_var)
            if output_key == "component_id":
                return True

        outputs = step_obj.get("outputs") if isinstance(step_obj.get("outputs"), Mapping) else {}
        if isinstance(outputs, Mapping):
            output_key = outputs.get(target_var)
            if output_key == "component_id":
                return True

        return False

    placement_index_by_component: Dict[str, int] = {}
    for item in report.get("placed") or []:
        if not isinstance(item, Mapping):
            continue
        cid = item.get("component_id")
        injected = item.get("injected_steps") if isinstance(item.get("injected_steps"), Mapping) else {}
        xform_step_id = injected.get("transform_step_id") if isinstance(injected.get("transform_step_id"), str) else None
        if not isinstance(cid, str) or not cid or not isinstance(xform_step_id, str) or not xform_step_id:
            continue
        xform_idx = out_index_by_step_id.get(xform_step_id)
        if isinstance(xform_idx, int):
            placement_index_by_component[cid] = xform_idx

    ordering_violations: List[Dict[str, Any]] = []
    placement_functions = {"CREATE_COMPONENT", "ENSURE_OCCURRENCE_R1", "SET_OCCURRENCE_TRANSFORM_R1"}
    tracked_components = sorted(placement_by_component.keys())
    for idx, step in enumerate(out_steps):
        if not isinstance(step, Mapping):
            continue
        function_name = step.get("function") if isinstance(step.get("function"), str) else ""
        if function_name in placement_functions:
            continue
        step_id = step.get("id") if isinstance(step.get("id"), str) else "<unknown>"
        for cid in tracked_components:
            if not _step_touches_component(step, cid):
                continue
            if _step_defines_component(step, cid):
                continue
            placement_idx = placement_index_by_component.get(cid)
            if not isinstance(placement_idx, int):
                ordering_violations.append(
                    {
                        "component_id": cid,
                        "step_id": step_id,
                        "reason": "missing_placement_transform_step",
                    }
                )
                continue
            if idx < placement_idx:
                ordering_violations.append(
                    {
                        "component_id": cid,
                        "step_id": step_id,
                        "reason": "step_executes_before_initial_placement",
                        "step_index": idx,
                        "placement_step_index": placement_idx,
                    }
                )

    if ordering_violations:
        payload = {
            "metadata": {
                "source": "Agent5_compose_plan.inject_initial_placements",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "round_index": int(round_index),
            },
            "summary": {
                "violations": len(ordering_violations),
            },
            "violations": ordering_violations,
        }
        _write_json(run_dir / "planning" / "errors" / "placement_before_modeling_violations.json", payload)
        raise RuntimeError(
            "placement_before_modeling_violation: component modeling step executes before initial placement. "
            "See planning/errors/placement_before_modeling_violations.json"
        )

    report["skipped_count"] = len(report.get("skipped") or [])
    return out_steps


def _is_identity_transform_mm(transform_mm: Any, *, eps: float = 1e-12) -> bool:
    if not isinstance(transform_mm, Mapping):
        return True
    translation_raw = transform_mm.get("translation")
    rotation_raw = transform_mm.get("rotation_rpy_deg")
    translation = translation_raw if isinstance(translation_raw, Mapping) else {}
    rotation = rotation_raw if isinstance(rotation_raw, Mapping) else {}
    try:
        tx = float(translation.get("x", 0.0))
        ty = float(translation.get("y", 0.0))
        tz = float(translation.get("z", 0.0))
        roll = float(rotation.get("roll", 0.0))
        pitch = float(rotation.get("pitch", 0.0))
        yaw = float(rotation.get("yaw", 0.0))
    except Exception:
        return False
    return (
        abs(tx) <= eps
        and abs(ty) <= eps
        and abs(tz) <= eps
        and abs(roll) <= eps
        and abs(pitch) <= eps
        and abs(yaw) <= eps
    )


def audit_occurrence_transforms(
    plan_steps: List[Dict[str, Any]], *, run_dir: Path, round_index: int
) -> Dict[str, Any]:
    """Static audit for SET_OCCURRENCE_TRANSFORM_R1 writes.

    Hard constraints:
    - Same occurrence_name must not have >=2 non-identity transforms.
    - Total transform steps must equal initial_placements count for this round.
    """
    # Map CREATE_COMPONENT capture vars -> occurrence_name
    var_to_occ_name: Dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "CREATE_COMPONENT":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occ_name = inputs.get("name")
        if not isinstance(occ_name, str) or not occ_name:
            continue
        capture = step.get("capture") if isinstance(step.get("capture"), Mapping) else {}
        vars_map = capture.get("vars") if isinstance(capture.get("vars"), Mapping) else {}
        for var_name, out_key in vars_map.items():
            if out_key == "occurrence_id" and isinstance(var_name, str) and var_name:
                var_to_occ_name[var_name] = occ_name

    def _occ_name_from_transform_step(step: Mapping[str, Any]) -> str:
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        occ_id = inputs.get("occurrence_id")
        if isinstance(occ_id, str) and occ_id.startswith("${") and occ_id.endswith("}"):
            var = occ_id[2:-1]
            if var in var_to_occ_name:
                return var_to_occ_name[var]
        # Fallbacks
        if isinstance(occ_id, str) and occ_id:
            return occ_id
        return "<unknown>"

    by_occ: Dict[str, List[Dict[str, Any]]] = {}
    total = 0
    non_identity = 0
    for step in plan_steps:
        if not isinstance(step, Mapping):
            continue
        if step.get("function") != "SET_OCCURRENCE_TRANSFORM_R1":
            continue
        total += 1
        occ_name = _occ_name_from_transform_step(step)
        sid = step.get("id")
        step_id = sid if isinstance(sid, str) else "<missing_id>"
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        identity = _is_identity_transform_mm(inputs.get("transform_mm"))
        if not identity:
            non_identity += 1
        by_occ.setdefault(occ_name, []).append(
            {
                "step_id": step_id,
                "identity": identity,
                "mode": inputs.get("mode"),
                "occurrence_id": inputs.get("occurrence_id"),
            }
        )

    expected: int | None = None
    try:
        placements = _load_initial_placements(run_dir, round_index=round_index)
        defined = _collect_defined_vars(plan_steps)
        expected = 0
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            cid = placement.get("component_id")
            if not isinstance(cid, str) or not cid:
                continue
            component_var = f"{cid}_component_id"
            occurrence_var = f"{cid}_occurrence_id"
            if component_var not in defined or occurrence_var not in defined:
                continue
            parent = placement.get("parent_assembly")
            if isinstance(parent, str) and parent and parent != "root":
                parent_var = f"{parent}_component_id"
                if parent_var not in defined:
                    continue
            expected += 1
    except Exception:
        expected = None

    report: Dict[str, Any] = {
        "metadata": {
            "source": "Agent5_compose_plan.audit_occurrence_transforms",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "round_index": int(round_index),
        },
        "summary": {
            "expected_placements": expected,
            "transform_steps_total": total,
            "transform_steps_non_identity": non_identity,
            "occurrence_count": len(by_occ),
        },
        "by_occurrence": by_occ,
        "violations": [],
    }

    if expected is not None and total != expected:
        report.setdefault("warnings", []).append(
            {
                "type": "transform_count_mismatch",
                "expected": expected,
                "found": total,
            }
        )

    for occ_name, recs in by_occ.items():
        non_id = [r for r in recs if not r.get("identity")]
        if len(non_id) >= 2:
            report["violations"].append(
                {
                    "type": "multi_non_identity_transform",
                    "occurrence_name": occ_name,
                    "non_identity_steps": non_id,
                }
            )

    if report["violations"]:
        out_path = run_dir / "planning" / "errors" / "multi_transform_violation.json"
        _write_json(out_path, report)
        raise RuntimeError(
            "multi_transform_violation: occurrence transform written multiple times. "
            f"details={json.dumps(report, ensure_ascii=False)}"
        )

    return report
