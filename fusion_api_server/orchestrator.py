"""
Fusion缁?orchestrator 閸忋儱褰?
"""

import traceback
import json
import datetime
import re
import os

# Script-safe imports (NO relative imports)
import plan_io
import marker_io
import postprocess


VAR_NAME_PATTERN = r"([A-Za-z_][A-Za-z0-9_.]*)"
FULL_PLACEHOLDER_PATTERN = re.compile(rf"\$\{{{VAR_NAME_PATTERN}\}}")
ANY_PLACEHOLDER_PATTERN = re.compile(r"\$\{[^{}]+\}")
AUTO_REFRESH_SINGLE_BODY_CONSUMERS = {"RESOLVE_INTERFACE"}
PROGRESS_DIALOG_TITLE = "Fusion Execution"
PROGRESS_DIALOG_INITIAL = "Running..."
PROGRESS_STAGE_MODELING = "Modeling..."
PROGRESS_STAGE_POSTPROCESS = "Post-processing..."
PROGRESS_STAGE_COMPLETE = "Completed"
MSG_PLAN_NOT_FOUND = (
    "fusion_manual_plan.json was not found under the resolved repo root. "
    "Generate a plan on the PC side or set FUSION_PLAN_PATH / FUSION_RUN_ID and try again."
)
MSG_EXECUTION_SUCCESS = "Fusion modeling completed: all steps executed successfully."


def _start_fresh_design_document(app):
    import adsk.core

    docs = getattr(app, "documents", None)
    if docs is None:
        raise RuntimeError("Fusion Application.documents unavailable; cannot start fresh design")

    doc_types = getattr(adsk.core, "DocumentTypes", None)
    design_doc_type = getattr(doc_types, "FusionDesignDocumentType", None) if doc_types is not None else None
    if design_doc_type is None:
        raise RuntimeError("Fusion Design document type unavailable; cannot start fresh design")

    new_doc = docs.add(design_doc_type)
    if new_doc is None:
        raise RuntimeError("Failed to create fresh Fusion design document")

    activate = getattr(new_doc, "activate", None)
    if callable(activate):
        try:
            activate()
        except Exception:
            pass

    return new_doc



def _resolve_variables(obj, context):
    """闁帒缍婇弴鎸庡床 ${var_name} 娑?context[var_name]"""
    if isinstance(obj, str):
        def resolve_var(var_name):
            if var_name in context:
                return True, context[var_name]
            return False, None

        full_match = FULL_PLACEHOLDER_PATTERN.fullmatch(obj)
        if full_match:
            var_name = full_match.group(1)
            found, value = resolve_var(var_name)
            return value if found else obj

        # 閺囨寧宕?${var_name} (partial interpolation)
        def replacer(match):
            var_name = match.group(1)
            found, value = resolve_var(var_name)
            return str(value) if found else match.group(0)

        return FULL_PLACEHOLDER_PATTERN.sub(replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_variables(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_variables(item, context) for item in obj]
    else:
        return obj


def _find_placeholders(obj, path=""):
    """鏉╂柨娲栭幍鈧張澶嬬暙閻?${var} 閻ㄥ嫯鐭惧鍕灙鐞?"""
    found = []
    if isinstance(obj, str):
        if ANY_PLACEHOLDER_PATTERN.search(obj):
            found.append(path or "$")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            found.extend(_find_placeholders(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            found.extend(_find_placeholders(v, p))
    return found


def _extract_full_placeholder_name(value):
    if not isinstance(value, str):
        return None
    match = FULL_PLACEHOLDER_PATTERN.fullmatch(value)
    if match is None:
        return None
    return match.group(1)


def _step_refreshes_runtime_body_var(step, *, body_var, component_var):
    if not isinstance(step, dict):
        return False
    if step.get("function") != "GET_SINGLE_BODY_ID":
        return False

    inputs = step.get("inputs")
    capture = step.get("capture")
    if not isinstance(inputs, dict) or not isinstance(capture, dict):
        return False

    vars_map = capture.get("vars")
    if not isinstance(vars_map, dict):
        return False

    refreshed_body_var = None
    for var_name, output_key in vars_map.items():
        if output_key == "body_id" and isinstance(var_name, str):
            refreshed_body_var = var_name
            break

    return (
        refreshed_body_var == body_var
        and _extract_full_placeholder_name(inputs.get("component_id")) == component_var
    )


def _make_runtime_step_id(used_ids, base_id):
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _inject_runtime_single_body_refresh_steps(steps):
    if not isinstance(steps, list):
        return 0

    used_ids = {
        sid
        for step in steps
        for sid in [step.get("id") if isinstance(step, dict) else None]
        if isinstance(sid, str) and sid
    }

    inserted = 0
    idx = 0
    while idx < len(steps):
        step = steps[idx]
        if not isinstance(step, dict):
            idx += 1
            continue

        function_name = step.get("function") or step.get("function_name")
        if function_name not in AUTO_REFRESH_SINGLE_BODY_CONSUMERS:
            idx += 1
            continue

        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            idx += 1
            continue

        body_var = _extract_full_placeholder_name(inputs.get("body_id"))
        component_var = _extract_full_placeholder_name(inputs.get("component_id"))
        if not body_var or not component_var:
            idx += 1
            continue

        prev_step = steps[idx - 1] if idx > 0 else None
        if _step_refreshes_runtime_body_var(prev_step, body_var=body_var, component_var=component_var):
            existing_deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            prev_id = prev_step.get("id") if isinstance(prev_step, dict) else None
            if isinstance(prev_id, str) and prev_id and prev_id not in existing_deps:
                updated = list(existing_deps)
                updated.append(prev_id)
                step["depends_on"] = updated
            idx += 1
            continue

        step_id = step.get("id") if isinstance(step.get("id"), str) and step.get("id") else f"step_{idx}"
        refresh_step_id = _make_runtime_step_id(used_ids, f"{step_id}__runtime_refresh_body")
        inherited_deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
        refresh_step = {
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
                "reason": "runtime_refresh_body_before_body_consumer",
                "target_step_id": step_id,
            },
        }
        steps.insert(idx, refresh_step)

        updated_deps = list(inherited_deps)
        if refresh_step_id not in updated_deps:
            updated_deps.append(refresh_step_id)
        step["depends_on"] = updated_deps
        inserted += 1
        idx += 2

    return inserted


def _extract_capture_value(result, path, *, step_id, var_name):
    path = path.strip()
    if path.startswith("/"):
        path = path[1:]
    if not path:
        raise RuntimeError(
            f"Capture failed in step '{step_id}': var '{var_name}' path is empty."
        )

    parts = path.split("/")
    cur = result
    for part in parts:
        if part.isdigit():
            if not isinstance(cur, list):
                raise RuntimeError(
                    f"Capture failed in step '{step_id}': var '{var_name}' path '{path}' "
                    f"expects list at '{part}', got {type(cur).__name__}."
                )
            idx = int(part)
            if idx >= len(cur):
                raise RuntimeError(
                    f"Capture failed in step '{step_id}': var '{var_name}' path '{path}' "
                    f"index {idx} out of range (len={len(cur)})."
                )
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                raise RuntimeError(
                    f"Capture failed in step '{step_id}': var '{var_name}' path '{path}' "
                    f"expects dict at '{part}', got {type(cur).__name__}."
                )
            if part not in cur:
                available = ", ".join(sorted(cur.keys()))
                raise RuntimeError(
                    f"Capture failed in step '{step_id}': var '{var_name}' path '{path}' "
                    f"missing key '{part}'. Available keys: [{available}]"
                )
            cur = cur[part]
    return cur


def _build_topological_execution_order(steps):
    """Return step execution order using depends_on with deterministic tie-breaks.

    Rules:
    - Missing/empty depends_on => immediately runnable
    - Missing dependency id => hard fail
    - Dependency cycle => hard fail
    - Tie-break between ready nodes follows original step order
    """
    records = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        sid = step.get("id") if isinstance(step.get("id"), str) and step.get("id") else f"step_{idx}"
        records.append((idx, sid, step))

    if not records:
        return []

    id_to_record = {}
    for idx, sid, step in records:
        if sid in id_to_record:
            raise RuntimeError(f"dispatch_plan duplicate step id detected: '{sid}'")
        id_to_record[sid] = (idx, step)

    indegree = {sid: 0 for _, sid, _ in records}
    outgoing = {sid: [] for _, sid, _ in records}

    for _, sid, step in records:
        deps_raw = step.get("depends_on")
        deps = [d for d in deps_raw if isinstance(d, str) and d] if isinstance(deps_raw, list) else []
        for dep in deps:
            if dep not in id_to_record:
                raise RuntimeError(
                    f"dispatch_plan missing dependency: step '{sid}' depends_on '{dep}' (not found)"
                )
            indegree[sid] += 1
            outgoing[dep].append(sid)

    ready = [sid for sid, deg in indegree.items() if deg == 0]
    ready.sort(key=lambda s: id_to_record[s][0])

    ordered_ids = []
    while ready:
        sid = ready.pop(0)
        ordered_ids.append(sid)
        for nxt in outgoing[sid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda s: id_to_record[s][0])

    if len(ordered_ids) != len(records):
        cycle_nodes = [sid for sid, deg in indegree.items() if deg > 0]
        cycle_nodes.sort(key=lambda s: id_to_record[s][0])
        raise RuntimeError(
            "dispatch_plan dependency cycle detected among steps: "
            + ", ".join(cycle_nodes)
        )

    out = []
    for sid in ordered_ids:
        idx, step = id_to_record[sid]
        out.append((idx, sid, step))
    return out


def dispatch_plan(controller, steps, ui, progress=None):
    """
    Function dispatcher for Fusion manual plans.

    Args:
        controller: FusionApiController instance.
        steps: The ordered step records from fusion_manual_plan.json.
        ui: Fusion UI object for reporting.
        progress: Optional progress dialog.

    Returns:
        execution_context: Captured outputs accumulated during execution.
    """
    execution_context = {}
    total_steps = len(steps)

    # Best-effort step trace: resolved inputs, capture outputs, context delta.
    trace_fp = None
    trace_path = None
    try:
        if hasattr(controller, "_repo_root") and controller._repo_root:
            repo_root = controller._repo_root
        else:
            repo_root = None
    except Exception:
        repo_root = None

    def _summarize_result(res):
        if not isinstance(res, dict):
            return {"type": type(res).__name__}
        summary = {"keys": sorted(list(res.keys()))[:50]}
        for k in (
            "component_id",
            "occurrence_id",
            "sketch_id",
            "profile_id",
            "feature_id",
            "body_id",
            "face_id",
            "edge_id",
            "vertex_id",
        ):
            if k in res:
                summary[k] = res.get(k)
        for k in ("body_ids", "face_ids", "edge_ids", "occurrence_ids", "feature_ids"):
            if k in res:
                v = res.get(k)
                if isinstance(v, list):
                    summary[k] = {"len": len(v), "head": v[:5]}
                else:
                    summary[k] = v
        if "warning" in res:
            summary["warning"] = res.get("warning")
        if "warnings" in res:
            summary["warnings"] = res.get("warnings")
        if "ok" in res:
            summary["ok"] = res.get("ok")
        return summary

    def _ensure_trace(run_dir):
        nonlocal trace_fp, trace_path
        if trace_fp is not None:
            return
        if not run_dir:
            return
        try:
            exec_dir = os.path.join(str(run_dir), "execution")
            os.makedirs(exec_dir, exist_ok=True)
            trace_path = os.path.join(exec_dir, "fusion_step_trace.jsonl")
            trace_fp = open(trace_path, "a", encoding="utf-8")
        except Exception:
            trace_fp = None
            trace_path = None

    def _append_trace(run_dir, payload):
        if trace_fp is None:
            _ensure_trace(run_dir)
        if trace_fp is None:
            return
        try:
            trace_fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            trace_fp.flush()
        except Exception:
            pass
    
    def log(msg):
        if hasattr(ui, 'messageBox'):
            # 閸欘垯浜掗弨閫涜礋閸欘亜鍟撻弮銉ョ箶閼板奔绗夊鍦崶
            pass
        print(f"[Dispatcher] {msg}")
    
    # Try to resolve run_dir from env if available (fallback only).
    # Note: run_dir is typically passed by caller (run_once) for markers, but
    # dispatch_plan is also used standalone in some setups.
    env_run_dir = None
    try:
        if repo_root is not None:
            rid = os.environ.get("FUSION_RUN_ID")
            if rid:
                env_run_dir = os.path.join(str(repo_root), "execution", "runs", rid)
    except Exception:
        env_run_dir = None

    try:
        ordered_steps = _build_topological_execution_order(steps)
    except Exception as dep_err:
        if env_run_dir:
            marker_io.write_failed(env_run_dir, f"dispatch dependency error: {dep_err}")
        raise

    total_steps = len(ordered_steps)

    for exec_idx, (idx, ordered_step_id, step) in enumerate(ordered_steps):
        step_id = ordered_step_id
        # 閸忕厧顔?function 閸?function_name 娑撱倗顫掔€涙顔?
        function_name = step.get("function") or step.get("function_name")
        inputs_dict = step.get("inputs", {})
        strict_mode = bool(getattr(controller, "strict_mode", False))
        
        # 閸欐﹢鍣洪弴鎸庡床閿涙艾鐨?${var_name} 閺囨寧宕叉稉?execution_context[var_name]
        inputs_dict = _resolve_variables(inputs_dict, execution_context)

        # Provide step_id to transform setter for run-dir logging (not part of plan contract).
        if function_name == "SET_OCCURRENCE_TRANSFORM_R1" and isinstance(inputs_dict, dict):
            inputs_dict = dict(inputs_dict)
            inputs_dict.setdefault("step_id", step_id)

        placeholders = _find_placeholders(inputs_dict)
        if placeholders:
            error_detail = {
                "step_id": step_id,
                "function": function_name,
                "strict_mode": strict_mode,
                "placeholder_paths": placeholders,
                "resolved_inputs": inputs_dict,
            }
            if strict_mode:
                raise RuntimeError(
                    "Unresolved placeholders detected under strict_mode: "
                    + json.dumps(error_detail, ensure_ascii=False)
                )
            marker_io.append_warning(
                env_run_dir,
                "Unresolved placeholders kept (strict_mode=false): "
                + json.dumps(error_detail, ensure_ascii=False),
            )
        
        log(f"=== Step {exec_idx+1}/{total_steps}: {step_id} ===")
        log(f"Function: {function_name}")
        log(f"Inputs (resolved): {json.dumps(inputs_dict, indent=2, ensure_ascii=False)}")
        
        # 濡偓閺屻儲鏌熷▔鏇熸Ц閸氾箑鐡ㄩ崷?
        if not hasattr(controller, function_name):
            error_msg = f"Function '{function_name}' not found in FusionApiController"
            log(f"ERROR: {error_msg}")
            raise AttributeError(error_msg)
        
        # 閸斻劍鈧浇鐨熼悽?
        try:
            ctx_size_before = len(execution_context)
            method = getattr(controller, function_name)
            result = method(**inputs_dict)
            
            log(f"Result: {result}")
            
            # 婢跺嫮鎮?capture 閸欐﹢鍣洪敍鍫濐洤閺嬫粓娓剁憰渚婄礆
            capture = step.get("capture", {})
            if capture and isinstance(capture, dict):
                vars_mapping = capture.get("vars", {})
                if isinstance(result, dict) and vars_mapping:
                    captured = []
                    for var_name, output_key in vars_mapping.items():
                        value = _extract_capture_value(
                            result,
                            str(output_key),
                            step_id=step_id,
                            var_name=str(var_name),
                        )
                        execution_context[var_name] = value
                        log(f"Captured: {var_name} = {value}")
                        captured.append({"var": str(var_name), "path": str(output_key), "value": value})

                    _append_trace(
                        env_run_dir,
                        {
                            "ts": datetime.datetime.now().isoformat(),
                            "step_id": step_id,
                            "function": function_name,
                            "inputs_resolved": inputs_dict,
                            "captured": captured,
                            "context_delta": {
                                "size_before": ctx_size_before,
                                "size_after": len(execution_context),
                                "new_keys": [c["var"] for c in captured],
                            },
                            "result_summary": _summarize_result(result),
                        },
                    )
                else:
                    _append_trace(
                        env_run_dir,
                        {
                            "ts": datetime.datetime.now().isoformat(),
                            "step_id": step_id,
                            "function": function_name,
                            "inputs_resolved": inputs_dict,
                            "captured": [],
                            "context_delta": {
                                "size_before": ctx_size_before,
                                "size_after": len(execution_context),
                                "new_keys": [],
                            },
                            "result_summary": _summarize_result(result),
                        },
                    )
            else:
                _append_trace(
                    env_run_dir,
                    {
                        "ts": datetime.datetime.now().isoformat(),
                        "step_id": step_id,
                        "function": function_name,
                        "inputs_resolved": inputs_dict,
                        "captured": [],
                        "context_delta": {
                            "size_before": ctx_size_before,
                            "size_after": len(execution_context),
                            "new_keys": [],
                        },
                        "result_summary": _summarize_result(result),
                    },
                )
        
        except Exception as e:
            error_msg = f"Step {step_id} ({function_name}) failed: {str(e)}"
            log(f"ERROR: {error_msg}")
            _append_trace(
                env_run_dir,
                {
                    "ts": datetime.datetime.now().isoformat(),
                    "step_id": step_id,
                    "function": function_name,
                    "inputs_resolved": inputs_dict,
                    "error": str(e),
                },
            )
            raise RuntimeError(error_msg) from e
        
        # 閺囧瓨鏌婃潻娑樺閺?
        if progress:
            progress.progressValue = int(10 + 60 * (exec_idx + 1) / total_steps)
        
        log(f"=== Step {step_id} completed ===\n")
    
    return execution_context


def run_once(app, ui):
    import adsk.core

    progress = None
    run_dir = None  # 閹绘劕澧犳竟鐗堟
    
    # 閺堚偓婢舵牕鐪?try-except閿涘本宕熼懢宄板瘶閹?plan 閸旂姾娴囬崷銊ュ敶閻ㄥ嫭澧嶉張澶婄磽鐢?
    try:
        try:
            # 1. Resolve plan
            repo_root = plan_io.find_repo_root()

            plan_path = plan_io.resolve_plan_path(repo_root)
            

            if plan_path is None:
                if repo_root is None:
                    ui.messageBox(
                        "Fusion repo root or fusion_manual_plan.json not found. Set FUSION_REPO_ROOT or FUSION_PLAN_PATH and try again."
                        ""
                    )
                else:
                    ui.messageBox(MSG_PLAN_NOT_FOUND)
                return

            plan = plan_io.load_plan(plan_path)
            run_dir = plan_io.derive_run_dir(plan_path)
            steps = plan.get("steps", [])
            runtime_refresh_count = _inject_runtime_single_body_refresh_steps(steps)
        except Exception as e:
            # Plan 閸旂姾娴囨径杈Е閿涘苯鐨剧拠鏇炲晸闁挎瑨顕ら弮銉ョ箶閸掓澘顦挎稉顏冪秴缂?
            tb = traceback.format_exc()
            failed_path = marker_io.write_failed(None, tb)
            if failed_path:
                ui.messageBox(f"Failed to load plan: {str(e)}\nSee {failed_path}")
            else:
                ui.messageBox(f"Failed to load plan: {str(e)}\nCould not write fusion_failed.json")
            return
        
        # 2. IMMEDIATELY write started marker (before any modeling)
        plan_summary = {
            "step_count": len(steps),
            "functions": list({(s.get("function") or s.get("function_name")) for s in steps})
        }
        marker_io.write_started(run_dir, str(plan_path), plan_summary)
        if runtime_refresh_count > 0:
            marker_io.append_warning(
                run_dir,
                f"Injected {runtime_refresh_count} runtime GET_SINGLE_BODY_ID refresh step(s) for body consumers.",
            )
        

        # 3. Progress dialog
        progress = ui.createProgressDialog()
        progress.show(PROGRESS_DIALOG_TITLE, PROGRESS_DIALOG_INITIAL, 0, 100)
        progress.isCancelButtonShown = True
        progress.progressValue = 0

        # ------------------------------------------------------------------
        # Modeling phase: dispatch plan
        # ------------------------------------------------------------------
        progress.message = PROGRESS_STAGE_MODELING
        import importlib
        import modeling as _modeling
        importlib.reload(_modeling)
        # Rewrite the started marker after reloading modeling so runtime metadata
        # captures the exact code Fusion is about to execute.
        marker_io.write_started(run_dir, str(plan_path), plan_summary)
        _ = _start_fresh_design_document(app)
        controller = _modeling.FusionApiController(app, strict_mode=True, run_dir=run_dir)
        
        execution_context = dispatch_plan(controller, steps, ui, progress)
        
        if progress.wasCancelled:
            marker_io.append_warning(run_dir, "Execution cancelled by user during modeling")
            return

        # ------------------------------------------------------------------
        # Post-process (non-blocking, export disabled)
        # ------------------------------------------------------------------
        progress.progressValue = 70
        progress.message = PROGRESS_STAGE_POSTPROCESS

        artifacts = {}

        try:
            artifacts = postprocess.run_all(
                run_dir,
                ui,
                enable_export=False,
                execution_context=execution_context,
            )
        except Exception as e:
            marker_io.append_warning(run_dir, f"Post-process warning (ignored): {e}")

        # ------------------------------------------------------------------
        # Hide construction planes (yellow planes clutter the view)
        # ------------------------------------------------------------------
        try:
            result = controller.hide_all_construction_planes()
            hidden_count = result.get("hidden_count", 0)
            if hidden_count > 0:
                marker_io.append_warning(run_dir, f"Construction planes hidden: {hidden_count}")
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Done marker
        # ------------------------------------------------------------------
        timestamps = {"finished": datetime.datetime.now().isoformat()}
        marker_io.write_done(run_dir, artifacts=artifacts, timestamps=timestamps)

        progress.progressValue = 100
        progress.message = PROGRESS_STAGE_COMPLETE
        ui.messageBox(MSG_EXECUTION_SUCCESS)

    except Exception as e:
        tb = traceback.format_exc()
        # --- Best-effort: hide construction planes even on failure ---
        try:
            if 'controller' in dir():
                controller.hide_all_construction_planes()
        except Exception:
            pass
        try:
            failed_path = marker_io.write_failed(run_dir if 'run_dir' in locals() else None, tb)
        except Exception:
            failed_path = None
        if failed_path:
            ui.messageBox(f"Fusion modeling failed: {str(e)}\nSee {failed_path}")
        else:
            ui.messageBox(f"Fusion modeling failed: {str(e)}\nCould not write fusion_failed.json")

    finally:
        # Always hide construction planes as a safety net
        try:
            if 'controller' in dir():
                controller.hide_all_construction_planes()
        except Exception:
            pass
        if progress:
            try:
                progress.hide()
            except Exception:
                pass
