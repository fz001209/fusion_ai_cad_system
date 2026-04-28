from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

from agents.common_utils import read_json as _read_json, collect_defined_vars as _collect_defined_vars


def _safe_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    cleaned = cleaned.strip("_")
    return cleaned or "stdpart"


def _last_step_id(steps: List[Dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        sid = step.get("id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _load_standard_parts(run_dir: Path) -> List[Dict[str, Any]]:
    path = run_dir / "planning" / "standard_parts_resolved.json"
    if not path.exists():
        return []
    data = _read_json(path)
    if not isinstance(data, Mapping):
        return []
    parts = data.get("resolved") or data.get("standard_parts") or data.get("parts")
    if not isinstance(parts, list):
        return []
    return [dict(p) for p in parts if isinstance(p, Mapping)]


def _load_function_registry() -> Dict[str, Any]:
    path = Path("functions") / "functions.json"
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _flatten_inputs_for_schema(part: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in part.items():
        if isinstance(k, str):
            out[k] = v
        if isinstance(v, Mapping):
            for k2, v2 in v.items():
                if isinstance(k2, str) and k2 not in out:
                    out[k2] = v2
    return out


def inject_standard_parts_steps(
    steps: List[Dict[str, Any]],
    *,
    run_dir: Path,
    base_dep_step_id: str | None = None,
) -> List[Dict[str, Any]]:
    parts = _load_standard_parts(run_dir)
    if not parts:
        return list(steps)

    registry = _load_function_registry()
    defined_vars = _collect_defined_vars(steps)

    fastener_kind_categories: set[str] = {
        "bolt",
        "screw",
        "nut",
        "washer",
        "rivet",
    }

    def _normalize_fastener_category(category: str) -> str:
        cat = category.strip().lower()
        if cat in {"pin", "stud"}:
            return "screw"
        return cat

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

    depends_base = base_dep_step_id if isinstance(base_dep_step_id, str) and base_dep_step_id else _last_step_id(steps)
    if depends_base is None:
        return list(steps)

    injected: List[Dict[str, Any]] = []

    def _bound_component_ids(part: Mapping[str, Any]) -> List[str]:
        ids: List[str] = []
        single_bound = part.get("bound_component_id")
        if isinstance(single_bound, str) and single_bound:
            ids.append(single_bound)
        bound_ids = part.get("bound_component_ids")
        if isinstance(bound_ids, list):
            ids.extend([str(v) for v in bound_ids if isinstance(v, str) and v])
        if not ids and isinstance(part.get("id"), str) and part.get("id"):
            ids.append(str(part.get("id")))
        return sorted({v for v in ids if v})

    def _group_key_for_part(part: Mapping[str, Any], category: str) -> str:
        part_id = part.get("part_id")
        if isinstance(part_id, str) and part_id.strip():
            return f"part_id:{part_id.strip()}"
        cad_relpath = part.get("cad_relpath")
        if isinstance(cad_relpath, str) and cad_relpath.strip():
            return f"cad:{cad_relpath.strip()}"
        designation = part.get("designation")
        if isinstance(designation, str) and designation.strip():
            return f"fallback:{category}:{designation.strip()}"
        pid = part.get("id")
        if isinstance(pid, str) and pid.strip():
            return f"fallback_id:{pid.strip()}"
        return f"fallback_cat:{category}"

    def _prototype_rank(bound_component_id: str) -> tuple[int, str]:
        cid = bound_component_id.strip()
        if cid.startswith("wheel_1_"):
            return (0, cid)
        if "wheel_1" in cid:
            return (1, cid)
        return (2, cid)

    records: List[Dict[str, Any]] = []
    for part in parts:
        category_raw = part.get("category")
        if not isinstance(category_raw, str) or not category_raw.strip():
            continue

        category = _normalize_fastener_category(category_raw)
        kind: str | None = None
        if category in fastener_kind_categories:
            kind = category
            cat_token = "FASTENER"
        else:
            cat_token = re.sub(r"[^a-z0-9_]", "_", category).upper()

        insert_fn = f"INSERT_{cat_token}_R1"
        verify_fn = f"VERIFY_{cat_token}_R1"
        replace_fn = f"REPLACE_{cat_token}_R1"
        if insert_fn not in registry:
            continue

        group_key = _group_key_for_part(part, category)
        explicit_bound_component = part.get("bound_component_id")
        explicit_bound_components = part.get("bound_component_ids")
        has_explicit_bound_component = (
            (isinstance(explicit_bound_component, str) and explicit_bound_component.strip())
            or (
                isinstance(explicit_bound_components, list)
                and any(isinstance(item, str) and item.strip() for item in explicit_bound_components)
            )
        )
        for bound_component_id in _bound_component_ids(part):
            record_group_key = (
                f"{group_key}|bound:{bound_component_id}"
                if category == "bearing" and has_explicit_bound_component
                else group_key
            )
            component_name_raw = part.get("component_name") or bound_component_id or f"std_{_safe_key(group_key)}"
            component_name = (
                component_name_raw.strip()
                if isinstance(component_name_raw, str)
                else str(component_name_raw).strip()
            )
            if not component_name:
                component_name = f"std_{_safe_key(group_key)}"

            records.append(
                {
                    "part": dict(part),
                    "category": category,
                    "kind": kind,
                    "cat_token": cat_token,
                    "insert_fn": insert_fn,
                    "verify_fn": verify_fn,
                    "replace_fn": replace_fn,
                    "group_key": record_group_key,
                    "bound_component_id": bound_component_id,
                    "component_name": component_name,
                    "parent_component_id": part.get("parent_component_id"),
                }
            )

    records_by_group: Dict[str, List[Dict[str, Any]]] = {}
    seen_group_bound: set[tuple[str, str]] = set()
    for rec in records:
        group_key = rec.get("group_key")
        bound_component_id = rec.get("bound_component_id")
        if not isinstance(group_key, str) or not isinstance(bound_component_id, str):
            continue
        key = (group_key, bound_component_id)
        if key in seen_group_bound:
            continue
        seen_group_bound.add(key)
        records_by_group.setdefault(group_key, []).append(rec)

    for group_key in sorted(records_by_group.keys()):
        group = records_by_group.get(group_key) or []
        if not group:
            continue

        group_sorted = sorted(
            group,
            key=lambda r: _prototype_rank(str(r.get("bound_component_id") or "")),
        )
        group_bound_ids = [
            str(item.get("bound_component_id") or "").strip()
            for item in group_sorted
            if isinstance(item.get("bound_component_id"), str) and str(item.get("bound_component_id") or "").strip()
        ]
        prototype = group_sorted[0]

        proto_bound_id = str(prototype.get("bound_component_id") or "").strip()
        if not proto_bound_id:
            continue

        insert_fn = str(prototype.get("insert_fn"))
        verify_fn = str(prototype.get("verify_fn"))
        replace_fn = str(prototype.get("replace_fn"))
        kind = prototype.get("kind") if isinstance(prototype.get("kind"), str) else None
        proto_part = prototype.get("part") if isinstance(prototype.get("part"), Mapping) else {}

        safe_id = _safe_key(str(proto_part.get("part_id") or proto_part.get("cad_relpath") or group_key))
        prefix = f"stdpart_{safe_id}"

        insert_id = _unique_id(f"{prefix}_insert")
        verify_id = _unique_id(f"{prefix}_verify")
        replace_id = _unique_id(f"{prefix}_replace")

        insert_props = (
            registry.get(insert_fn, {}).get("inputs", {}).get("properties", {})
            if isinstance(registry.get(insert_fn), dict)
            else {}
        )
        verify_props = (
            registry.get(verify_fn, {}).get("inputs", {}).get("properties", {})
            if isinstance(registry.get(verify_fn), dict)
            else {}
        )
        replace_props = (
            registry.get(replace_fn, {}).get("inputs", {}).get("properties", {})
            if isinstance(registry.get(replace_fn), dict)
            else {}
        )

        flat = _flatten_inputs_for_schema(proto_part)
        component_name = str(prototype.get("component_name") or proto_bound_id).strip() or f"std_{safe_id}"
        # Standard-part insertion is flat at root level. Logical/container-only
        # parents such as wheel_1 / wheel_2 / wheel_3 may not have component-id
        # captures, so parent presence must not gate insertion.
        insert_inputs: Dict[str, Any] = {
            "component_name": component_name,
            "designation": proto_part.get("designation"),
            "quantity": proto_part.get("quantity"),
            "applied_to": proto_part.get("applied_to"),
            # All components at root 鈥?no nesting (Fusion transform2 issue).
            "parent_component_id": None,
            "insert_mode": "library_local",
            "allow_placeholder": False,
        }
        if kind is not None:
            insert_inputs["kind"] = kind
        for k in list(insert_inputs.keys()):
            if insert_props and k not in insert_props:
                insert_inputs.pop(k, None)
        for k, v in flat.items():
            if insert_props and k in insert_props:
                if k == "parent_component_id":
                    continue
                insert_inputs[k] = v

        insert_step: Dict[str, Any] = {
            "id": insert_id,
            "function": insert_fn,
            "inputs": insert_inputs,
            "depends_on": [depends_base],
            "capture": {
                "vars": {
                    f"{prefix}_component_id": "component_id",
                    f"{prefix}_occurrence_id": "occurrence_id",
                    f"{proto_bound_id}_component_id": "component_id",
                    f"{proto_bound_id}_occurrence_id": "occurrence_id",
                }
            },
        }
        injected.append(insert_step)
        depends_base = insert_id

        defined_vars.add(f"{prefix}_component_id")
        defined_vars.add(f"{prefix}_occurrence_id")
        defined_vars.add(f"{proto_bound_id}_component_id")
        defined_vars.add(f"{proto_bound_id}_occurrence_id")

        verify_status_var = f"{prefix}_verify_status"
        if verify_fn in registry:
            verify_inputs: Dict[str, Any] = {
                "component_id": f"${{{prefix}_component_id}}",
                "component_name": component_name,
                "designation": proto_part.get("designation"),
            }
            if kind is not None:
                verify_inputs["kind"] = kind
            for k in list(verify_inputs.keys()):
                if verify_props and k not in verify_props:
                    verify_inputs.pop(k, None)
            for k, v in flat.items():
                if verify_props and k in verify_props:
                    verify_inputs[k] = v

            verify_step: Dict[str, Any] = {
                "id": verify_id,
                "function": verify_fn,
                "inputs": verify_inputs,
                "depends_on": [insert_id],
                "capture": {"vars": {verify_status_var: "status"}},
            }
            injected.append(verify_step)
            depends_base = verify_id
            defined_vars.add(verify_status_var)

        if replace_fn in registry:
            replace_inputs: Dict[str, Any] = {
                "component_id": f"${{{prefix}_component_id}}",
                "component_name": component_name,
                "designation": proto_part.get("designation"),
                "quantity": proto_part.get("quantity"),
                "applied_to": proto_part.get("applied_to"),
                "verify_status": f"${{{verify_status_var}}}",
            }
            if kind is not None:
                replace_inputs["kind"] = kind
            for k in list(replace_inputs.keys()):
                if replace_props and k not in replace_props:
                    replace_inputs.pop(k, None)
            for k, v in flat.items():
                if replace_props and k in replace_props:
                    replace_inputs[k] = v

            replace_step: Dict[str, Any] = {
                "id": replace_id,
                "function": replace_fn,
                "inputs": replace_inputs,
                "depends_on": [depends_base],
                "capture": {
                    "vars": {
                        f"{prefix}_replace_action": "action",
                        f"{prefix}_used_placeholder": "used_placeholder",
                        f"{prefix}_component_id": "component_id",
                        f"{prefix}_occurrence_id": "occurrence_id",
                        f"{proto_bound_id}_component_id": "component_id",
                        f"{proto_bound_id}_occurrence_id": "occurrence_id",
                    }
                },
            }
            injected.append(replace_step)
            depends_base = replace_id

            defined_vars.add(f"{prefix}_replace_action")
            defined_vars.add(f"{prefix}_used_placeholder")
            defined_vars.add(f"{prefix}_component_id")
            defined_vars.add(f"{prefix}_occurrence_id")
            defined_vars.add(f"{proto_bound_id}_component_id")
            defined_vars.add(f"{proto_bound_id}_occurrence_id")

        body_id_step: Dict[str, Any] = {
            "id": _unique_id(f"{prefix}_body"),
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {"component_id": f"${{{prefix}_component_id}}"},
            "depends_on": [depends_base],
            "capture": {
                "vars": {
                    f"{prefix}_body_id": "body_id",
                    f"{proto_bound_id}_body_id": "body_id",
                }
            },
        }
        injected.append(body_id_step)
        depends_base = body_id_step["id"]

        defined_vars.add(f"{prefix}_body_id")
        defined_vars.add(f"{proto_bound_id}_body_id")

        ensure_props = (
            registry.get("ENSURE_OCCURRENCE_R1", {}).get("inputs", {}).get("properties", {})
            if isinstance(registry.get("ENSURE_OCCURRENCE_R1"), dict)
            else {}
        )
        for instance in group_sorted[1:]:
            instance_bound_id = str(instance.get("bound_component_id") or "").strip()
            if not instance_bound_id or instance_bound_id == proto_bound_id:
                continue
            # Non-prototype standard-part occurrences are also ensured at root
            # level, so logical parent capture is intentionally ignored here.
            instance_occ_var = f"{instance_bound_id}_occurrence_id"
            ensure_inputs: Dict[str, Any] = {
                "component_id": f"${{{proto_bound_id}_component_id}}",
                "occurrence_name": str(instance.get("component_name") or instance_bound_id).strip() or instance_bound_id,
                # All components at root 鈥?no nesting (Fusion transform2 issue).
                "parent_component_id": None,
            }
            if instance_occ_var in defined_vars:
                ensure_inputs["occurrence_id"] = f"${{{instance_occ_var}}}"
            for k in list(ensure_inputs.keys()):
                if ensure_props and k not in ensure_props:
                    ensure_inputs.pop(k, None)

            ensure_step: Dict[str, Any] = {
                "id": _unique_id(f"stdpart_{_safe_key(instance_bound_id)}_ensure"),
                "function": "ENSURE_OCCURRENCE_R1",
                "inputs": ensure_inputs,
                "depends_on": [depends_base],
                "capture": {"vars": {instance_occ_var: "occurrence_id"}},
            }
            injected.append(ensure_step)
            depends_base = ensure_step["id"]
            defined_vars.add(instance_occ_var)

    if not injected:
        return list(steps)

    return list(steps) + injected
