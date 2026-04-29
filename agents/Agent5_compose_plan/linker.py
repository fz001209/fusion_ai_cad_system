from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Sequence, Tuple


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}")
_FULL_VAR_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_.]*)\}$")
_FORBIDDEN_ASM_SELECTORS = {"SELECT_LARGEST_PLANAR_FACE", "SELECT_CYLINDRICAL_FACE"}
_AUTO_REFRESH_SINGLE_BODY_CONSUMERS = {"RESOLVE_INTERFACE"}


def _collect_step_ids(steps: Sequence[Mapping[str, Any]]) -> tuple[Dict[str, int], List[Dict[str, Any]]]:
    step_index: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps):
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            errors.append(
                {
                    "code": "step_id_missing",
                    "message": "Step id is missing or invalid",
                    "step_index": idx,
                }
            )
            continue
        if sid in step_index:
            errors.append(
                {
                    "code": "step_id_duplicate",
                    "message": f"Duplicate step id: {sid}",
                    "step_id": sid,
                    "step_index": idx,
                }
            )
            continue
        step_index[sid] = idx
    return step_index, errors


def _collect_capture_sources(steps: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    producer_idx: Dict[str, int] = {}
    for idx, step in enumerate(steps):
        capture = step.get("capture")
        if isinstance(capture, Mapping):
            vars_map = capture.get("vars")
            if isinstance(vars_map, Mapping):
                for var_name in vars_map.keys():
                    if isinstance(var_name, str) and var_name and var_name not in producer_idx:
                        producer_idx[var_name] = idx
        outputs = step.get("outputs")
        if isinstance(outputs, Mapping):
            for var_name in outputs.keys():
                if isinstance(var_name, str) and var_name and var_name not in producer_idx:
                    producer_idx[var_name] = idx
    return producer_idx


def _collect_annotated_varref_paths(schema: Mapping[str, Any], path: str = "inputs") -> set[str]:
    out: set[str] = set()
    if not isinstance(schema, Mapping):
        return out

    if schema.get("x_varref") is True:
        out.add(path)

    props = schema.get("properties")
    if isinstance(props, Mapping):
        for key, sub in props.items():
            if isinstance(key, str) and isinstance(sub, Mapping):
                out |= _collect_annotated_varref_paths(sub, f"{path}.{key}")

    items = schema.get("items")
    if isinstance(items, Mapping):
        out |= _collect_annotated_varref_paths(items, f"{path}[*]")

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        for sub in one_of:
            if isinstance(sub, Mapping):
                out |= _collect_annotated_varref_paths(sub, path)

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        for sub in any_of:
            if isinstance(sub, Mapping):
                out |= _collect_annotated_varref_paths(sub, path)

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for sub in all_of:
            if isinstance(sub, Mapping):
                out |= _collect_annotated_varref_paths(sub, path)

    return out


def _norm_path_for_schema(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", path)


def _collect_step_referenced_vars(
    step: Mapping[str, Any],
    function_registry: Mapping[str, Any],
) -> set[str]:
    ref_like_leaves = {
        "component",
        "profile",
        "sketch",
        "plane",
        "entity",
        "token",
        "marker",
        "occurrence",
        "body",
    }

    def _should_infer_from_leaf(leaf: str) -> bool:
        if _is_id_like_leaf(leaf):
            return True
        return leaf in ref_like_leaves

    sid = step.get("id")
    if not isinstance(sid, str) or not sid:
        return set()
    function_name = step.get("function") if isinstance(step.get("function"), str) else None
    inputs = step.get("inputs")
    if not isinstance(inputs, Mapping):
        return set()

    x_varref_paths: set[str] = set()
    if isinstance(function_name, str) and function_name:
        entry = function_registry.get(function_name)
        schema = entry.get("inputs") if isinstance(entry, Mapping) and isinstance(entry.get("inputs"), Mapping) else None
        if isinstance(schema, Mapping):
            x_varref_paths = _collect_annotated_varref_paths(schema)

    referenced_vars: set[str] = set()
    for path, value in _iter_input_values(inputs):
        if not isinstance(value, str):
            continue
        leaf = _path_leaf(path)
        if x_varref_paths:
            npath = _norm_path_for_schema(path)
            if npath not in x_varref_paths:
                continue
        else:
            if not _should_infer_from_leaf(leaf):
                continue
        referenced_vars.update(_VAR_RE.findall(value))

    return referenced_vars


def _update_current_var_producer(step: Mapping[str, Any], current_var_producer: Dict[str, str]) -> None:
    sid = step.get("id")
    if not isinstance(sid, str) or not sid:
        return

    capture = step.get("capture")
    if isinstance(capture, Mapping):
        vars_map = capture.get("vars")
        if isinstance(vars_map, Mapping):
            for var_name in vars_map.keys():
                if isinstance(var_name, str) and var_name:
                    current_var_producer[var_name] = sid

    outputs = step.get("outputs")
    if isinstance(outputs, Mapping):
        for var_name in outputs.keys():
            if isinstance(var_name, str) and var_name:
                current_var_producer[var_name] = sid


def _extract_full_var_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _FULL_VAR_RE.match(value)
    if match is None:
        return None
    return match.group(1)


def _step_refreshes_body_var(step: Mapping[str, Any] | None, *, body_var: str, component_var: str) -> bool:
    if not isinstance(step, Mapping):
        return False
    if step.get("function") != "GET_SINGLE_BODY_ID":
        return False

    inputs = step.get("inputs")
    capture = step.get("capture")
    if not isinstance(inputs, Mapping) or not isinstance(capture, Mapping):
        return False

    vars_map = capture.get("vars")
    if not isinstance(vars_map, Mapping):
        return False

    refreshed_body_var = None
    for var_name, output_key in vars_map.items():
        if output_key == "body_id" and isinstance(var_name, str):
            refreshed_body_var = var_name
            break

    return (
        refreshed_body_var == body_var
        and _extract_full_var_name(inputs.get("component_id")) == component_var
    )


def _make_unique_step_id(used_ids: set[str], base_id: str) -> str:
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _autofill_single_body_refresh_steps(
    steps: Sequence[Mapping[str, Any]],
    function_registry: Mapping[str, Any],
) -> None:
    if not isinstance(steps, list):
        return
    if "GET_SINGLE_BODY_ID" not in function_registry:
        return

    used_ids = {
        sid
        for step in steps
        for sid in [step.get("id") if isinstance(step, Mapping) else None]
        if isinstance(sid, str) and sid
    }

    idx = 0
    while idx < len(steps):
        step = steps[idx]
        if not isinstance(step, dict):
            idx += 1
            continue

        function_name = step.get("function")
        if function_name not in _AUTO_REFRESH_SINGLE_BODY_CONSUMERS:
            idx += 1
            continue

        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            idx += 1
            continue

        body_var = _extract_full_var_name(inputs.get("body_id"))
        component_var = _extract_full_var_name(inputs.get("component_id"))
        if not body_var or not component_var:
            idx += 1
            continue

        prev_step = steps[idx - 1] if idx > 0 else None
        if _step_refreshes_body_var(prev_step, body_var=body_var, component_var=component_var):
            existing_deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            prev_id = prev_step.get("id") if isinstance(prev_step, Mapping) else None
            if isinstance(prev_id, str) and prev_id and prev_id not in existing_deps:
                existing_deps = list(existing_deps)
                existing_deps.append(prev_id)
                step["depends_on"] = existing_deps
            idx += 1
            continue

        step_id = step.get("id") if isinstance(step.get("id"), str) and step.get("id") else f"step_{idx}"
        refresh_step_id = _make_unique_step_id(used_ids, f"{step_id}__refresh_body")
        inherited_deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
        refresh_step: Dict[str, Any] = {
            "id": refresh_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": f"${{{component_var}}}",
                "allow_multi_body_fallback": True,
            },
            "capture": {"vars": {body_var: "body_id"}},
            "depends_on": list(inherited_deps),
            "metadata": {
                "autofill": True,
                "reason": "refresh_body_before_body_consumer",
                "target_step_id": step_id,
            },
        }
        steps.insert(idx, refresh_step)

        consumer_deps = list(inherited_deps)
        if refresh_step_id not in consumer_deps:
            consumer_deps.append(refresh_step_id)
        step["depends_on"] = consumer_deps
        idx += 2


def _supplement_depends_on_from_var_refs(
    steps: Sequence[Mapping[str, Any]],
    function_registry: Mapping[str, Any],
) -> None:
    current_var_producer: Dict[str, str] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            _update_current_var_producer(step, current_var_producer)
            continue

        referenced_vars = _collect_step_referenced_vars(step, function_registry)
        if not referenced_vars:
            _update_current_var_producer(step, current_var_producer)
            continue

        inferred_deps: List[str] = []
        for var_name in referenced_vars:
            producer_step_id = current_var_producer.get(var_name)
            if isinstance(producer_step_id, str) and producer_step_id and producer_step_id != sid:
                inferred_deps.append(producer_step_id)

        if inferred_deps:
            existing_deps_raw = step.get("depends_on")
            existing_deps = existing_deps_raw if isinstance(existing_deps_raw, list) else []
            seen: set[str] = set(d for d in existing_deps if isinstance(d, str) and d)
            for dep in inferred_deps:
                if dep not in seen:
                    existing_deps.append(dep)
                    seen.add(dep)
            if existing_deps:
                step["depends_on"] = existing_deps

        _update_current_var_producer(step, current_var_producer)


def _collect_latest_producer_expectations(
    steps: Sequence[Mapping[str, Any]],
    function_registry: Mapping[str, Any],
) -> Dict[str, Dict[str, str]]:
    latest: Dict[str, str] = {}
    expectations: Dict[str, Dict[str, str]] = {}

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            _update_current_var_producer(step, latest)
            continue

        refs = _collect_step_referenced_vars(step, function_registry)
        if refs:
            expected_for_step: Dict[str, str] = {}
            for var_name in refs:
                producer = latest.get(var_name)
                if isinstance(producer, str) and producer:
                    expected_for_step[var_name] = producer
            if expected_for_step:
                expectations[sid] = expected_for_step

        _update_current_var_producer(step, latest)

    return expectations


def _collect_step_ancestors(steps: Sequence[Mapping[str, Any]]) -> Dict[str, set[str]]:
    deps_by_step: Dict[str, List[str]] = {}
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        deps = step.get("depends_on")
        dep_list = [d for d in deps if isinstance(d, str) and d] if isinstance(deps, list) else []
        deps_by_step[sid] = dep_list

    memo: Dict[str, set[str]] = {}

    def _dfs(sid: str, stack: set[str]) -> set[str]:
        if sid in memo:
            return memo[sid]
        if sid in stack:
            return set()
        stack.add(sid)
        out: set[str] = set()
        for dep in deps_by_step.get(sid, []):
            out.add(dep)
            out |= _dfs(dep, stack)
        stack.remove(sid)
        memo[sid] = out
        return out

    for sid in deps_by_step.keys():
        _dfs(sid, set())

    return memo


def _validate_latest_var_dependency_closure(
    *,
    steps: Sequence[Mapping[str, Any]],
    function_registry: Mapping[str, Any],
    errors: List[Dict[str, Any]],
) -> None:
    expectations = _collect_latest_producer_expectations(steps, function_registry)
    if not expectations:
        return

    ancestors = _collect_step_ancestors(steps)
    for sid, expected in expectations.items():
        reachable = ancestors.get(sid, set())
        for var_name, producer_sid in expected.items():
            if producer_sid == sid:
                continue
            if producer_sid not in reachable:
                errors.append(
                    {
                        "code": "var_reference_missing_latest_producer_dependency",
                        "message": "Step references variable but depends_on graph does not reach latest producer",
                        "step_id": sid,
                        "variable": var_name,
                        "latest_producer_step_id": producer_sid,
                    }
                )


def _build_graph(
    steps: Sequence[Mapping[str, Any]],
    step_index: Mapping[str, int],
) -> tuple[Dict[str, List[str]], Dict[str, int], List[Dict[str, Any]]]:
    edges: Dict[str, List[str]] = {sid: [] for sid in step_index.keys()}
    indegree: Dict[str, int] = {sid: 0 for sid in step_index.keys()}
    errors: List[Dict[str, Any]] = []

    for step in steps:
        sid = step.get("id")
        if not isinstance(sid, str) or sid not in step_index:
            continue
        deps = step.get("depends_on")
        if deps is None:
            continue
        if not isinstance(deps, list):
            errors.append(
                {
                    "code": "depends_on_invalid_type",
                    "message": "depends_on must be a list when provided",
                    "step_id": sid,
                }
            )
            continue
        seen: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str) or not dep:
                errors.append(
                    {
                        "code": "depends_on_invalid_item",
                        "message": "depends_on item must be non-empty string",
                        "step_id": sid,
                    }
                )
                continue
            if dep not in step_index:
                errors.append(
                    {
                        "code": "depends_on_unknown_step",
                        "message": f"depends_on references unknown step '{dep}'",
                        "step_id": sid,
                    }
                )
                continue
            if dep in seen:
                continue
            seen.add(dep)
            edges[dep].append(sid)
            indegree[sid] += 1
    return edges, indegree, errors


def _topological_sort(
    step_index: Mapping[str, int],
    edges: Mapping[str, List[str]],
    indegree: Mapping[str, int],
) -> tuple[List[str], bool]:
    queue = sorted([sid for sid, deg in indegree.items() if deg == 0], key=lambda sid: step_index[sid])
    local_indegree = dict(indegree)
    ordered: List[str] = []

    while queue:
        sid = queue.pop(0)
        ordered.append(sid)
        for nxt in edges.get(sid, []):
            local_indegree[nxt] -= 1
            if local_indegree[nxt] == 0:
                queue.append(nxt)

    has_cycle = len(ordered) != len(step_index)
    return ordered, has_cycle


def _expected_type_names(type_decl: Any) -> List[str]:
    if isinstance(type_decl, str):
        return [type_decl]
    if isinstance(type_decl, list):
        out: List[str] = []
        for item in type_decl:
            if isinstance(item, str):
                out.append(item)
        return out
    return []


def _value_matches_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, Mapping)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True


def _validate_against_schema(
    *,
    value: Any,
    schema: Mapping[str, Any],
    path: str,
    step_id: str,
    errors: List[Dict[str, Any]],
) -> None:
    if isinstance(value, str) and _FULL_VAR_RE.match(value):
        return

    expected_types = _expected_type_names(schema.get("type"))
    if expected_types:
        if not any(_value_matches_type(value, t) for t in expected_types):
            errors.append(
                {
                    "code": "schema_type_mismatch",
                    "message": f"{path} type mismatch; expected {expected_types}",
                    "step_id": step_id,
                    "path": path,
                    "value": value,
                }
            )
            return

    if isinstance(value, Mapping):
        props = schema.get("properties")
        props_map = props if isinstance(props, Mapping) else {}
        required = schema.get("required")
        req_list = required if isinstance(required, list) else []
        for key in req_list:
            if isinstance(key, str) and key not in value:
                errors.append(
                    {
                        "code": "schema_required_missing",
                        "message": f"Missing required input '{key}'",
                        "step_id": step_id,
                        "path": path,
                    }
                )

        additional = schema.get("additionalProperties")
        if additional is False:
            for key in value.keys():
                if isinstance(key, str) and key not in props_map:
                    errors.append(
                        {
                            "code": "schema_additional_property",
                            "message": f"Unexpected property '{key}'",
                            "step_id": step_id,
                            "path": f"{path}.{key}",
                        }
                    )

        for key, sub in value.items():
            if not isinstance(key, str):
                continue
            sub_schema = props_map.get(key)
            if isinstance(sub_schema, Mapping):
                _validate_against_schema(
                    value=sub,
                    schema=sub_schema,
                    path=f"{path}.{key}",
                    step_id=step_id,
                    errors=errors,
                )
        return

    if isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, Mapping):
            for idx, item in enumerate(value):
                _validate_against_schema(
                    value=item,
                    schema=items_schema,
                    path=f"{path}[{idx}]",
                    step_id=step_id,
                    errors=errors,
                )


def _iter_input_values(obj: Any, path: str = "inputs") -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if not isinstance(key, str):
                continue
            key_path = f"{path}.{key}"
            out.extend(_iter_input_values(value, key_path))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            out.extend(_iter_input_values(value, f"{path}[{idx}]"))
    else:
        out.append((path, obj))
    return out


def _path_leaf(path: str) -> str:
    if not path:
        return ""
    tail = path.split(".")[-1]
    return re.sub(r"\[\d+\]", "", tail)


def _is_id_like_leaf(leaf: str) -> bool:
    if leaf in {"component_a", "component_b"}:
        return True
    if leaf.endswith("_id"):
        return True
    return False


def _is_assembly_step(step: Mapping[str, Any]) -> bool:
    sid = step.get("id")
    fn = step.get("function")
    sid_s = sid if isinstance(sid, str) else ""
    fn_s = fn if isinstance(fn, str) else ""
    if sid_s.startswith("asm_"):
        return True
    markers = ("JOINT", "RESOLVE_INTERFACE", "CREATE_JOINT_GEOMETRY")
    return any(m in fn_s for m in markers)


def _manifest_index(interface_manifest: Mapping[str, Any]) -> Dict[str, set[str]]:
    out: Dict[str, set[str]] = {}
    components = interface_manifest.get("components")
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        component_id = comp.get("component_id")
        interfaces = comp.get("interfaces")
        if not isinstance(component_id, str) or not component_id:
            continue
        if not isinstance(interfaces, list):
            continue
        names: set[str] = set()
        for iface in interfaces:
            if not isinstance(iface, Mapping):
                continue
            interface_name = iface.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                names.add(interface_name)
        out[component_id] = names
    return out


def _validate_dropped_relations_audit(
    *,
    assembly_patch: Mapping[str, Any],
    errors: List[Dict[str, Any]],
) -> None:
    metadata = assembly_patch.get("metadata") if isinstance(assembly_patch.get("metadata"), Mapping) else {}
    constraint_validation = (
        metadata.get("constraint_validation")
        if isinstance(metadata, Mapping) and isinstance(metadata.get("constraint_validation"), Mapping)
        else {}
    )
    dropped_expected = (
        constraint_validation.get("dropped_relations")
        if isinstance(constraint_validation, Mapping) and isinstance(constraint_validation.get("dropped_relations"), int)
        else 0
    )
    dropped_rows = assembly_patch.get("dropped_relations")

    if dropped_expected > 0 and not isinstance(dropped_rows, list):
        errors.append(
            {
                "code": "dropped_relations_unexplained",
                "message": "Assembly patch reports dropped_relations but dropped_relations audit list is missing",
                "expected_dropped_relations": dropped_expected,
            }
        )
        return

    if not isinstance(dropped_rows, list):
        return

    if dropped_expected > 0 and len(dropped_rows) < dropped_expected:
        errors.append(
            {
                "code": "dropped_relations_audit_incomplete",
                "message": "Dropped relation audit rows are fewer than dropped_relations count",
                "expected_dropped_relations": dropped_expected,
                "audited_rows": len(dropped_rows),
            }
        )

    for idx, row in enumerate(dropped_rows):
        if not isinstance(row, Mapping):
            errors.append(
                {
                    "code": "dropped_relation_row_invalid",
                    "message": "Dropped relation audit row must be an object",
                    "row_index": idx,
                }
            )
            continue
        drop_reason = row.get("drop_reason")
        if not isinstance(drop_reason, str) or not drop_reason:
            errors.append(
                {
                    "code": "dropped_relation_reason_missing",
                    "message": "Dropped relation must include drop_reason",
                    "row_index": idx,
                }
            )
        if "replacement_relation_id" not in row:
            errors.append(
                {
                    "code": "dropped_relation_replacement_missing",
                    "message": "Dropped relation must explicitly include replacement_relation_id (nullable allowed)",
                    "row_index": idx,
                }
            )


def _validate_interface_manifest_refs(
    *,
    steps: Sequence[Mapping[str, Any]],
    interface_manifest: Mapping[str, Any] | None,
    errors: List[Dict[str, Any]],
) -> None:
    if not isinstance(interface_manifest, Mapping):
        errors.append(
            {
                "code": "interface_manifest_missing",
                "message": "interface_manifest is required for link-time interface resolution checks",
            }
        )
        return

    index = _manifest_index(interface_manifest)
    if not index:
        errors.append(
            {
                "code": "interface_manifest_empty",
                "message": "interface_manifest has no resolvable component/interface entries",
            }
        )

    resolve_step_count = 0

    for idx, step in enumerate(steps):
        fn = step.get("function")
        if fn != "RESOLVE_INTERFACE":
            continue
        resolve_step_count += 1

        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        interface_name = inputs.get("interface_name")
        if not isinstance(interface_name, str) or not interface_name:
            errors.append(
                {
                    "code": "resolve_interface_name_missing",
                    "message": "RESOLVE_INTERFACE.inputs.interface_name must be non-empty string",
                    "step_id": sid,
                }
            )
            continue

        meta = step.get("metadata") if isinstance(step.get("metadata"), Mapping) else {}
        component_id = meta.get("component_id") if isinstance(meta.get("component_id"), str) else None
        if not component_id:
            errors.append(
                {
                    "code": "resolve_interface_component_unresolved",
                    "message": "RESOLVE_INTERFACE step must provide metadata.component_id for link-time verification",
                    "step_id": sid,
                }
            )
            continue

        valid_ifaces = index.get(component_id)
        if not isinstance(valid_ifaces, set) or interface_name not in valid_ifaces:
            errors.append(
                {
                    "code": "resolve_interface_not_in_manifest",
                    "message": "RESOLVE_INTERFACE interface_name not found in interface_manifest for component",
                    "step_id": sid,
                    "component_id": component_id,
                    "interface_name": interface_name,
                }
            )

    if resolve_step_count == 0:
        errors.append(
            {
                "code": "resolve_interface_step_missing",
                "message": "No RESOLVE_INTERFACE step found; link-time interface resolution evidence is required",
            }
        )


def _validate_interface_refs_in_inputs(
    *,
    steps: Sequence[Mapping[str, Any]],
    interface_manifest: Mapping[str, Any] | None,
    errors: List[Dict[str, Any]],
) -> None:
    if not isinstance(interface_manifest, Mapping):
        return

    index = _manifest_index(interface_manifest)

    def _scan(obj: Any, step_id: str, path: str) -> None:
        if isinstance(obj, Mapping):
            # Only validate *actual* interface_ref objects. Do not treat arbitrary
            # inputs like {component_id, name} (e.g., sketch names) as interface refs.
            if path.endswith("interface_ref"):
                component_id = obj.get("component_id")
                interface_name = obj.get("name") if isinstance(obj.get("name"), str) else obj.get("interface_name")
                if isinstance(component_id, str) and component_id and isinstance(interface_name, str) and interface_name:
                    known = index.get(component_id)
                    if not isinstance(known, set) or interface_name not in known:
                        errors.append(
                            {
                                "code": "interface_ref_unresolvable",
                                "message": "interface_ref in step inputs is not resolvable via interface_manifest",
                                "step_id": step_id,
                                "path": path,
                                "component_id": component_id,
                                "interface_name": interface_name,
                            }
                        )
            for key, value in obj.items():
                if isinstance(key, str):
                    _scan(value, step_id, f"{path}.{key}")
            return

        if isinstance(obj, list):
            for idx, item in enumerate(obj):
                _scan(item, step_id, f"{path}[{idx}]")

    for idx, step in enumerate(steps):
        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        _scan(inputs, sid, "inputs")


def _validate_feasibility_summary(
    *,
    feasibility_summary: Mapping[str, Any] | None,
    fallback_threshold: float,
    intent_changed_threshold: float,
    errors: List[Dict[str, Any]],
) -> None:
    if not isinstance(feasibility_summary, Mapping):
        errors.append(
            {
                "code": "feasibility_summary_missing",
                "message": "geometry semantics feasibility summary is required for linker quality gate",
            }
        )
        return

    checked = int(feasibility_summary.get("placements_checked")) if isinstance(feasibility_summary.get("placements_checked"), int) else 0
    fallback_ratio_raw = feasibility_summary.get("fallback_ratio")
    fallback_ratio = float(fallback_ratio_raw) if isinstance(fallback_ratio_raw, (int, float)) else 0.0
    intent_changed_count = int(feasibility_summary.get("intent_changed_count")) if isinstance(feasibility_summary.get("intent_changed_count"), int) else 0
    intent_changed_ratio = (float(intent_changed_count) / float(checked)) if checked > 0 else 0.0
    blocked_count = int(feasibility_summary.get("blocked_count")) if isinstance(feasibility_summary.get("blocked_count"), int) else 0
    needs_clarification_count = int(feasibility_summary.get("needs_clarification_count")) if isinstance(feasibility_summary.get("needs_clarification_count"), int) else 0
    valid_flag = bool(feasibility_summary.get("valid") is True)
    clean_feasibility = valid_flag and blocked_count == 0 and needs_clarification_count == 0
    effective_fallback_threshold = 0.65 if clean_feasibility else fallback_threshold
    effective_intent_changed_threshold = 0.45 if clean_feasibility else intent_changed_threshold

    if blocked_count > 0 or needs_clarification_count > 0:
        errors.append(
            {
                "code": "feasibility_not_clean",
                "message": "Feasibility report contains blocked or needs_clarification placements",
                "blocked_count": blocked_count,
                "needs_clarification_count": needs_clarification_count,
                "placements_checked": checked,
            }
        )
        return

    if checked > 0 and fallback_ratio > effective_fallback_threshold and intent_changed_ratio > effective_intent_changed_threshold:
        errors.append(
            {
                "code": "fallback_and_intent_changed_ratio_exceed_threshold",
                "message": "Fallback ratio and intent-changed ratio exceed linker thresholds",
                "observed": round(fallback_ratio, 4),
                "threshold": round(effective_fallback_threshold, 4),
                "intent_changed_observed": round(intent_changed_ratio, 4),
                "intent_changed_threshold": round(effective_intent_changed_threshold, 4),
                "placements_checked": checked,
            }
        )


def run_linker_pass(
    *,
    steps: Sequence[Mapping[str, Any]],
    function_registry: Mapping[str, Any],
    interface_manifest: Mapping[str, Any] | None = None,
    assembly_patch: Mapping[str, Any] | None = None,
    feasibility_summary: Mapping[str, Any] | None = None,
    fallback_threshold: float = 0.30,
    intent_changed_threshold: float = 0.35,
) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []

    _autofill_single_body_refresh_steps(steps, function_registry)

    step_index, step_errors = _collect_step_ids(steps)
    errors.extend(step_errors)

    _supplement_depends_on_from_var_refs(steps, function_registry)

    producer_idx = _collect_capture_sources(steps)

    edges, indegree, dep_errors = _build_graph(steps, step_index)
    errors.extend(dep_errors)
    _, has_cycle = _topological_sort(step_index, edges, indegree)
    if has_cycle:
        errors.append(
            {
                "code": "depends_on_cycle",
                "message": "depends_on graph contains a cycle",
            }
        )

    _validate_latest_var_dependency_closure(
        steps=steps,
        function_registry=function_registry,
        errors=errors,
    )

    for idx, step in enumerate(steps):
        sid = step.get("id") if isinstance(step.get("id"), str) else f"<index:{idx}>"
        fn = step.get("function")
        if not isinstance(fn, str) or not fn:
            errors.append(
                {
                    "code": "function_missing",
                    "message": "Step function is missing",
                    "step_id": sid,
                }
            )
            continue

        if fn not in function_registry:
            errors.append(
                {
                    "code": "function_unregistered",
                    "message": f"Function not in registry: {fn}",
                    "step_id": sid,
                }
            )
            continue

        entry = function_registry.get(fn)
        schema = entry.get("inputs") if isinstance(entry, Mapping) else None
        inputs = step.get("inputs")
        if not isinstance(inputs, Mapping):
            errors.append(
                {
                    "code": "inputs_invalid",
                    "message": "Step inputs must be an object",
                    "step_id": sid,
                }
            )
            continue

        if isinstance(schema, Mapping):
            _validate_against_schema(
                value=inputs,
                schema=schema,
                path="inputs",
                step_id=sid,
                errors=errors,
            )

        asm_step = _is_assembly_step(step)
        if asm_step and fn in _FORBIDDEN_ASM_SELECTORS:
            errors.append(
                {
                    "code": "assembly_direct_face_selector_forbidden",
                    "message": f"Assembly step must resolve via interface, forbidden selector used: {fn}",
                    "step_id": sid,
                }
            )

        for path, value in _iter_input_values(inputs):
            leaf = _path_leaf(path)

            if "face_index" in leaf:
                errors.append(
                    {
                        "code": "direct_face_index_forbidden",
                        "message": "Direct face index reference is forbidden",
                        "step_id": sid,
                        "path": path,
                    }
                )

            if isinstance(value, str):
                vars_in_value = _VAR_RE.findall(value)
                for var_name in vars_in_value:
                    prod = producer_idx.get(var_name)
                    if prod is None:
                        errors.append(
                            {
                                "code": "placeholder_not_captured",
                                "message": f"Variable '{var_name}' is not produced by any upstream capture",
                                "step_id": sid,
                                "path": path,
                            }
                        )
                    elif prod >= idx:
                        errors.append(
                            {
                                "code": "placeholder_not_upstream",
                                "message": f"Variable '{var_name}' is not produced upstream of this step",
                                "step_id": sid,
                                "path": path,
                            }
                        )

            if _is_id_like_leaf(leaf):
                if isinstance(value, str):
                    m = _FULL_VAR_RE.match(value)
                    if m is None:
                        errors.append(
                            {
                                "code": "id_field_not_template",
                                "message": f"ID/token field '{leaf}' must reference captured variable",
                                "step_id": sid,
                                "path": path,
                                "value": value,
                            }
                        )
                    else:
                        var_name = m.group(1)
                        if var_name not in producer_idx:
                            errors.append(
                                {
                                    "code": "id_field_variable_not_captured",
                                    "message": f"ID/token variable '{var_name}' is not captured upstream",
                                    "step_id": sid,
                                    "path": path,
                                }
                            )
                elif value is not None:
                    errors.append(
                        {
                            "code": "id_field_invalid_type",
                            "message": f"ID/token field '{leaf}' must be ${'{var}'} template or null",
                            "step_id": sid,
                            "path": path,
                            "value": value,
                        }
                    )

                if asm_step and leaf == "face_id" and isinstance(value, str):
                    if _FULL_VAR_RE.match(value) is None:
                        errors.append(
                            {
                                "code": "assembly_face_ref_not_interface_token",
                                "message": "Assembly face references must come from interface resolution capture",
                                "step_id": sid,
                                "path": path,
                            }
                        )

    _validate_interface_manifest_refs(
        steps=steps,
        interface_manifest=interface_manifest,
        errors=errors,
    )
    _validate_interface_refs_in_inputs(
        steps=steps,
        interface_manifest=interface_manifest,
        errors=errors,
    )
    _validate_feasibility_summary(
        feasibility_summary=feasibility_summary,
        fallback_threshold=fallback_threshold,
        intent_changed_threshold=intent_changed_threshold,
        errors=errors,
    )

    if isinstance(assembly_patch, Mapping):
        _validate_dropped_relations_audit(
            assembly_patch=assembly_patch,
            errors=errors,
        )

    report = {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "agent5_linker",
        },
        "summary": {
            "step_count": len(steps),
            "error_count": len(errors),
            "valid": len(errors) == 0,
        },
        "errors": errors,
    }
    return report
