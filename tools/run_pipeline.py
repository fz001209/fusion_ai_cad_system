from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv_if_present(path: Path) -> None:
    """Load KEY=VALUE pairs from a local .env file into os.environ.

    This is a convenience for local development. The .env file should NOT be
    committed to source control.

    Rules:
    - Lines starting with '#' are ignored
    - Supports optional leading 'export '
    - Values may be wrapped in single or double quotes
    - Existing environment variables are not overwritten
    """

    if not path.exists():
        return

    # Windows users sometimes save .env as UTF-16 via Notepad; be permissive.
    text: str | None = None
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            # Any other IO error: treat as optional and continue.
            return

    if text is None:
        return

    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("export "):
                line = line[7:].lstrip()

            if "=" in line:
                key, value = line.split("=", 1)
            elif ":" in line:
                # Tolerate a common mistake where users write YAML-like `KEY: VALUE`.
                key, value = line.split(":", 1)
            else:
                continue
            key = key.strip()
            value = value.strip()

            if not key:
                continue

            if (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]

            os.environ.setdefault(key, value)
    except Exception:
        # .env is strictly optional; never fail the pipeline due to parsing.
        return


_load_dotenv_if_present(REPO_ROOT / ".env")

# Helpful (non-secret) diagnostics for common local setup issues.
if (REPO_ROOT / ".env").exists() and not os.environ.get("OPENAI_API_KEY"):
    print(
        "WARNING: Found .env but OPENAI_API_KEY is missing/empty. "
        "Edit .env and set OPENAI_API_KEY=sk-... (no quotes required)."
    )

from agents.Agent1_requirement_to_kg.standard_parts_resolver import (
    run as agent1_standard_parts_resolver_run,
)
from agents.Agent1_requirement_to_kg.transform import inject_resolved_standard_parts, run as requirement_to_kg_run
from agents.Agent2_plan_geometry_semantic.transform import run as plan_geometry_semantic_run
from agents.Agent3a_shape_realization_planner.transform import (
    run as shape_realization_planner_run,
)
from agents.Agent3b_compile_geometry_plan.transform import (
    run as compile_geometry_plan_run,
)
from agents.Agent4_plan_assembly.transform import run as plan_assembly_run
from agents.Agent5_compose_plan.memory_snapshot import run as compose_plan_memory_snapshot_run
from agents.Agent5_compose_plan.transform import run as compose_plan_run
from agents.agent_guardrails import evaluate_agent_outputs
from tools.event_log import append_event


def _default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _copy_text(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


 


def _use_selected_geometry_plan_if_exists(*, run_dir: Path, round_index: int) -> None:
    """
    If planning/selected_geometry_plan_round_n.json exists,
    extract its "plan" field and write to planning/geometry_plan_round_n.json
    so that compose_plan uses the selected candidate instead of the original.
    
    Fallback to existing geometry_plan_round_n.json if:
    - selected plan file is missing
    - selected plan file is invalid JSON
    - "plan" field is missing or invalid
    - any other error occurs
    
    Never raises exceptions.
    """
    planning_dir = run_dir / "planning"
    selected_path = planning_dir / f"selected_geometry_plan_round_{round_index}.json"
    geometry_path = planning_dir / f"geometry_plan_round_{round_index}.json"
    
    if not selected_path.exists():
        return
    
    try:
        selected_data = json.loads(selected_path.read_text(encoding="utf-8"))
        if not isinstance(selected_data, dict):
            return
        
        plan_content = selected_data.get("plan")
        if not isinstance(plan_content, dict):
            return
        
        # Validate plan has required structure
        if "metadata" not in plan_content or "steps" not in plan_content:
            return
        
        # Write the plan content to geometry_plan_round_n.json
        geometry_path.write_text(
            json.dumps(plan_content, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        
    except Exception:
        # Non-blocking: if extraction fails, compose_plan will use existing geometry plan
        pass


def log_agent_event(
    *,
    run_dir: Path,
    agent_name: str,
    phase: str,
    payload: Dict[str, List[str]],
    round_index: int | None = None,
) -> None:
    """Append a minimal agent-level audit event.

    Writes to run_dir/events.jsonl (append-only). Payload is restricted to:
    - inputs_written: list[str] (relative paths)
    - outputs_written: list[str] (relative paths)

    No parsing, validation, or dependency on planner/dispatcher/executor internals.
    """

    data: Dict[str, Any] = {
        "inputs_written": list(payload.get("inputs_written", [])),
        "outputs_written": list(payload.get("outputs_written", [])),
    }
    if round_index is not None:
        data["round_index"] = int(round_index)
    append_event(run_dir=run_dir, event_type=f"agent.{agent_name}.{phase}", data=data)


def audit_guardrails(
    *,
    run_dir: Path,
    agent_name: str,
    outputs_written: List[str],
    p1_sink: List[Dict[str, Any]] | None = None,
) -> None:
    violations = evaluate_agent_outputs(agent_name, outputs_written)
    if not violations:
        return

    repaired: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    for item in violations:
        if not isinstance(item, dict):
            continue
        auto = item.get("auto_repair") if isinstance(item.get("auto_repair"), dict) else None
        rel = item.get("path") if isinstance(item.get("path"), str) else None
        if rel and isinstance(auto, dict) and auto.get("action") == "move":
            target = auto.get("target_path") if isinstance(auto.get("target_path"), str) else None
            src = run_dir / rel
            dst = run_dir / target if isinstance(target, str) else None
            if src.exists() and isinstance(dst, Path):
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(src), str(dst))
                    repaired.append(
                        {
                            "path": rel,
                            "target_path": target,
                            "severity": item.get("severity"),
                        }
                    )
                    continue
                except Exception:
                    pass
        unresolved.append(item)

    if repaired:
        append_event(
            run_dir=run_dir,
            event_type="agent.guardrail_autofix",
            data={
                "agent_name": agent_name,
                "repaired": repaired,
            },
        )

    if not unresolved:
        return

    p0 = [v for v in unresolved if isinstance(v, dict) and v.get("severity") == "P0"]
    p1 = [v for v in unresolved if isinstance(v, dict) and v.get("severity") == "P1"]
    p2 = [v for v in unresolved if isinstance(v, dict) and v.get("severity") == "P2"]

    append_event(
        run_dir=run_dir,
        event_type="agent.guardrail_violation",
        data={
            "agent_name": agent_name,
            "violations": unresolved,
            "summary": {
                "p0_count": len(p0),
                "p1_count": len(p1),
                "p2_count": len(p2),
            },
        },
    )

    if p1 and isinstance(p1_sink, list):
        p1_sink.append(
            {
                "agent_name": agent_name,
                "count": len(p1),
                "violations": p1,
            }
        )

    if p0:
        raise RuntimeError(
            f"Guardrail blocked pipeline for agent '{agent_name}': {len(p0)} P0 violation(s)."
        )


def _snapshot_run_files(run_dir: Path) -> set[str]:
    """Return a set of run_dir-relative file paths (POSIX-style)."""

    out: set[str] = set()
    for p in run_dir.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(run_dir)
        except Exception:
            continue
        rel_s = str(rel).replace("\\", "/")
        # Always ignore the audit log itself.
        if rel_s == "events.jsonl":
            continue
        out.add(rel_s)
    return out


def _diff_outputs(before: set[str], after: set[str], *, ignore: set[str] | None = None) -> List[str]:
    ignore = ignore or set()
    created = sorted((after - before) - ignore)
    return created


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_REVIEW_STRIP_ROOTS = {"input", "knowledge", "planning", "execution", "validation", "memory"}


def _normalize_rel_path(rel_path: str) -> str:
    return str(Path(rel_path)).replace("\\", "/").lstrip("./")


def _review_rel_path_for(*, agent_name: str, rel_path: str) -> str:
    normalized = _normalize_rel_path(rel_path)
    parts = [part for part in Path(normalized).parts if part not in ("", ".")]
    if not parts:
        raise ValueError("rel_path must not be empty")

    stripped = parts[1:] if len(parts) > 1 and parts[0] in _REVIEW_STRIP_ROOTS else parts
    review_rel = Path("final") / agent_name / Path(*stripped)
    return str(review_rel).replace("\\", "/")


def _sync_review_outputs(
    *,
    run_dir: Path,
    agent_name: str,
    rel_paths: List[str],
    round_index: int | None = None,
) -> List[str]:
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = final_dir / "review_manifest.json"
    manifest: Dict[str, Any]
    if manifest_path.exists():
        try:
            loaded = _read_json(manifest_path)
            manifest = loaded if isinstance(loaded, dict) else {}
        except Exception:
            manifest = {}
    else:
        manifest = {}

    manifest.setdefault(
        "metadata",
        {
            "run_id": run_dir.name,
            "root": "final",
            "description": "Human-review copies of canonical agent outputs.",
        },
    )
    manifest["metadata"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
    entries = manifest.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        manifest["entries"] = entries

    existing_keys = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        existing_keys.add(
            (
                entry.get("agent"),
                entry.get("source"),
                entry.get("review_path"),
                entry.get("round_index"),
            )
        )

    copied_review_paths: List[str] = []
    seen_sources: set[str] = set()
    for rel_path in rel_paths:
        if not isinstance(rel_path, str) or not rel_path.strip():
            continue
        source_rel = _normalize_rel_path(rel_path)
        if source_rel in seen_sources:
            continue
        seen_sources.add(source_rel)

        src = run_dir / source_rel
        if not src.exists() or not src.is_file():
            continue

        review_rel = _review_rel_path_for(agent_name=agent_name, rel_path=source_rel)
        _copy_file(src, run_dir / review_rel)
        copied_review_paths.append(review_rel)

        key = (agent_name, source_rel, review_rel, round_index)
        if key in existing_keys:
            continue
        record: Dict[str, Any] = {
            "agent": agent_name,
            "source": source_rel,
            "review_path": review_rel,
        }
        if round_index is not None:
            record["round_index"] = int(round_index)
        entries.append(record)
        existing_keys.add(key)

    manifest["summary"] = {
        "entry_count": len([entry for entry in entries if isinstance(entry, dict)]),
        "agents": sorted(
            {
                str(entry.get("agent"))
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("agent"), str)
            }
        ),
    }
    _write_json(manifest_path, manifest)
    return copied_review_paths


def _sync_agent_review_outputs(
    *,
    run_dir: Path,
    agent_name: str,
    rel_paths: List[str],
    round_index: int | None = None,
) -> None:
    review_outputs = _sync_review_outputs(
        run_dir=run_dir,
        agent_name=agent_name,
        rel_paths=rel_paths,
        round_index=round_index,
    )
    if review_outputs:
        log_agent_event(
            run_dir=run_dir,
            agent_name=agent_name,
            phase="review_sync",
            payload={"inputs_written": [], "outputs_written": review_outputs},
            round_index=round_index,
        )




def _preserve_execution_artifacts(*, execution_dir: Path, round_index: int) -> None:
    """Best-effort snapshot of execution artifacts before re-dispatch overwrites them."""

    dst = execution_dir / f"round_{round_index}"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("context.json", "resolved_steps.json", "execution_trace.json"):
        src = execution_dir / name
        if src.exists():
            _copy_file(src, dst / name)


def main() -> None:
    def _extract_fusion_manual_plan(function_plan: dict) -> tuple[list, list]:
        """
        閸欘亜鍘戠拋闀愮矤 function_plan 鐠囪褰?allowlist 閸愬懐娈?step閵?
        
        allowlist 閸斻劍鈧胶鏁撻幋鎰剁窗娴?modeling.py 閻?FusionApiController 娑擃厽褰侀崣鏍ㄥ閺?
        婢堆冨晸鐎涙鐦濆鈧径瀵告畱閺傝纭堕崥宥忕礄鏉╂瑤绨洪弰?CAD 閹垮秳缍旈崙鑺ユ殶閿涘绱濋崝鐘辩瑐 EXPORT_STEP閵?
        
        閸忕厧顔?function/func/function_name 鐎涙顔岄妴?
        """
        # 閸斻劍鈧胶鏁撻幋?allowlist閿涙矮绮?modeling.py 閼惧嘲褰囬幍鈧張?CAD 閹垮秳缍旈崙鑺ユ殶
        allowlist = _build_allowlist()
        
        steps = function_plan.get("steps") or function_plan.get("plan") or []
        if not isinstance(steps, list):
            return []
        def get_func_name(step):
            for k in ("function", "func", "function_name"):
                v = step.get(k)
                if isinstance(v, str):
                    return v
            return None
        kept: list = []
        dropped: list = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                dropped.append(
                    {
                        "index": idx,
                        "reason": "non_object_step",
                        "step": step,
                    }
                )
                continue
            func_name = get_func_name(step)
            if func_name in allowlist:
                kept.append(step)
                continue
            dropped.append(
                {
                    "index": idx,
                    "reason": "function_not_in_allowlist",
                    "function": func_name,
                    "step_id": step.get("id"),
                    "step": step,
                }
            )
        return kept, dropped
    
    def _build_allowlist():
        """
        娴?modeling.py 閸斻劍鈧焦鐎鍝勫帒鐠佺鍤遍弫鏉垮灙鐞涖劊鈧?
        
        缁涙牜鏆愰敍?
        1. 鐏忔繆鐦€电厧鍙?fusion_api_server 娑擃厾娈?modeling 濡€虫健
        2. 閸欏秴鐨?FusionApiController 缁紮绱濋懢宄板絿閹碘偓閺堝銇囬崘娆忕摟濮ｅ秴绱戞径瀵告畱閺傝纭?
        3. 閸旂姳绗傞悧瑙勭暕閸戣姤鏆?EXPORT_STEP閿涘牅绗夐崷?modeling.py 娑擃叏绱?
        
        婵″倹鐏夌€电厧鍙嗘径杈Е閿涘苯娲栭柅鈧崚鎵€栫紓鏍垳閻ㄥ嫭娓剁亸?allowlist閵?
        """
        import sys
        from pathlib import Path
        
        allowlist = {"EXPORT_STEP"}  # 閸╄櫣顢呴崚妤勩€冮敍灞锯偓缁樻Ц閸栧懎鎯堟潻娆庨嚋
        
        try:
            # 绾喖鐣?fusion_api_server 閻╊喖缍?
            script_dir = Path(__file__).resolve().parent
            fusion_api_server_dir = script_dir.parent / "fusion_api_server"
            
            # 娑撳瓨妞傚ǎ璇插閸?sys.path
            if str(fusion_api_server_dir) not in sys.path:
                sys.path.insert(0, str(fusion_api_server_dir))
            
            # 鐎电厧鍙?modeling 濡€虫健閿涘牅绗夌€电厧鍙?Fusion 閻?adsk閿涘苯娲滄稉楦跨箹閸?PC 缁旑垯绗夐崣顖滄暏閿?
            # 閹存垳婊戦崣顏呮Ц娑撹桨绨″Λ鈧弻銉︽煙濞夋洖鎮曢敍灞肩瑝鐎圭偤妾崚娑樼紦鐎电钖?
            try:
                import inspect
                import importlib.util
                
                # 鐠囪褰囧┃鎰瀮娴犺绱濇稉宥嗗⒔鐞涘矉绱欓柆鍨帳 adsk 鐎电厧鍙嗘径杈Е閿?
                modeling_path = fusion_api_server_dir / "modeling.py"
                if modeling_path.exists():
                    with open(modeling_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 缁犫偓閸楁洜娈戝锝呭灟閸栧綊鍘ら敍姘閹碘偓閺?"def UPPERCASE_NAME("
                    # 閸忎浇顔忛弫鏉跨摟閿涘牅绶ユ俊?INSERT_FASTENER_R1閿?
                    import re
                    pattern = r'def\s+([A-Z][A-Z0-9_]*)\s*\('
                    matches = re.findall(pattern, content)
                    
                    # 鏉╁洦鎶ら幒澶婁紣閸忓嘲鍤遍弫甯礄mm, cm_vec, cm_point閿涘绱濋崣顏冪箽閻?CAD 閹垮秳缍?
                    cad_functions = {
                        m for m in matches 
                        if m not in {'MM', 'CM_VEC', 'CM_POINT'}  # 閹烘帡娅庨崘鍛村劥瀹搞儱鍙块崙鑺ユ殶
                    }
                    
                    if cad_functions:
                        allowlist.update(cad_functions)
                        print(f"[AutoAllowlist] detected {len(cad_functions)} CAD functions from modeling.py")
                    else:
                        functions_path = script_dir.parent / "functions" / "functions.json"
                        if functions_path.exists():
                            import json
                            functions_data = json.loads(functions_path.read_text(encoding="utf-8-sig"))
                            registry_functions = {
                                name for name in functions_data.keys() if isinstance(name, str) and name
                            }
                            allowlist.update(registry_functions)
                            print(f"[AutoAllowlist] modeling.py scan returned no CAD functions; fell back to functions.json ({len(registry_functions)})")
                    
            except Exception as e:
                print(f"[AutoAllowlist] source scan failed ({e}); falling back to functions.json")
                functions_path = script_dir.parent / "functions" / "functions.json"
                if functions_path.exists():
                    import json
                    functions_data = json.loads(functions_path.read_text(encoding="utf-8-sig"))
                    allowlist.update({name for name in functions_data.keys() if isinstance(name, str) and name})
        
        except Exception as e:
            print(f"[AutoAllowlist] 閸掓繂顫愰崠鏍с亼鐠?({e})閿涘奔濞囬悽銊︽付鐏?allowlist")
        
        return allowlist

    parser = argparse.ArgumentParser(
        description="Run pipeline orchestrator (creates run dir, copies inputs, invokes agents)."
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run id (default: timestamp).",
    )
    parser.add_argument(
        "--source-anforderungsliste",
        default="input/anforderungsliste.yaml",
        help="Source requirements YAML (staging area).",
    )
    parser.add_argument(
        "--runs-root",
        default="execution/runs",
        help="Runs root directory.",
    )
    parser.add_argument(
        "--schema",
        default="planning/knowledge_graph_schema.json",
        help="Knowledge graph JSON schema.",
    )
    # 瑜拌绨崇粔濠氭珟 executor 闁瀚ㄩ崣鍌涙殶閿涘ipeline 閸欘亝鏁幐?dryrun 鐟欏嫬鍨?
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum planning rounds (default: 3).",
    )
    parser.add_argument(
        "--use-llm-strategy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable LLM-backed high-level strategy decision in plan_geometry. "
            "This only records the flag to metadata.json; plan_geometry reads it from the run dir. "
            "Use --no-use-llm-strategy to disable."
        ),
    )
    parser.add_argument(
        "--use-llm-assembly-intent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable LLM-backed declarative assembly intent reasoning in plan_assembly. "
            "This only records the flag to metadata.json; plan_assembly reads it from the run dir. "
            "Use --no-use-llm-assembly-intent to disable."
        ),
    )
    args = parser.parse_args()

    # LLM is enabled by default, but actual calls require OPENAI_API_KEY.
    # Make the fallback explicit to avoid confusion.
    if bool(args.use_llm_strategy) or bool(args.use_llm_assembly_intent):
        api_key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
        if not api_key_present:
            print("[WARN] LLM enabled but OPENAI_API_KEY is missing; planning will fall back to deterministic rules.")

    run_id = args.run_id or _default_run_id()

    runs_root = Path(args.runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)

    # Default UX: never fail just because a run id folder already exists.
    # If the target run dir exists, append a numeric suffix.
    base_run_id = run_id
    run_dir = runs_root / run_id
    if run_dir.exists():
        i = 2
        while (runs_root / f"{base_run_id}_{i}").exists():
            i += 1
        run_id = f"{base_run_id}_{i}"
        run_dir = runs_root / run_id
        print(f"[WARN] run_id '{base_run_id}' already exists; using '{run_id}' instead")

    src_req = Path(args.source_anforderungsliste)
    if not src_req.exists():
        raise SystemExit(f"Source input not found: {src_req}")

    # Run layout
    input_dir = run_dir / "input"
    knowledge_dir = run_dir / "knowledge"
    planning_dir = run_dir / "planning"
    execution_dir = run_dir / "execution"
    validation_dir = run_dir / "validation"
    final_dir = run_dir / "final"
    input_dir.mkdir(parents=True, exist_ok=False)
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    planning_dir.mkdir(parents=True, exist_ok=True)
    execution_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    append_event(run_dir=run_dir, event_type="pipeline.start", data={"run_id": run_id})
    append_event(run_dir=run_dir, event_type="pipeline.executor_selected", data={"executor": "dryrun"})

    # Copy inputs into run
    dst_req = input_dir / "anforderungsliste.yaml"
    _copy_text(src_req, dst_req)
    append_event(
        run_dir=run_dir,
        event_type="pipeline.input_copied",
        data={
            "source": str(src_req).replace("\\", "/"),
            "dest": str(dst_req).replace("\\", "/"),
        },
    )

    # Metadata (facts-only)
    metadata = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "use_llm_strategy": bool(args.use_llm_strategy),
        "use_llm_assembly_intent": bool(args.use_llm_assembly_intent),
        "pipeline": [
            {
                "agent": "requirement_to_kg",
                "inputs": ["input/anforderungsliste.yaml"],
                "outputs": [
                    "knowledge/knowledge_graph.json",
                    "planning/standard_parts_resolved.json",
                    "planning/standard_parts_unresolved.json",
                    "validation/standard_parts_consistency.json",
                ],
            },
            {
                "agent": "plan_geometry_semantic",
                "inputs": [
                    "knowledge/knowledge_graph.json",
                    "planning/standard_parts_resolved.json",
                    "planning/standard_parts_unresolved.json",
                ],
                "outputs": [
                    "planning/geometry_semantics_modeling_round_<n>.json",
                    "planning/geometry_semantics_assembly_round_<n>.json",
                    "planning/interface_manifest_round_<n>.json",
                ],
            },
            {
                "agent": "shape_realization_planner_3a",
                "inputs": ["planning/geometry_semantics_modeling_round_<n>.json"],
                "outputs": [
                    "planning/shape_realization_round_<n>.json",
                    "placement_diagnostics.json",
                ],
            },
            {
                "agent": "compile_geometry_plan_3b",
                "inputs": [
                    "planning/shape_realization_round_<n>.json",
                    "planning/standard_parts_resolved.json",
                ],
                "outputs": [
                    "planning/geometry_plan_round_<n>.json",
                    "planning/interface_manifest_round_<n>.json",
                ],
            },
            {
                "agent": "plan_assembly",
                "inputs": [
                    "knowledge/knowledge_graph.json",
                    "planning/geometry_semantics_assembly_round_<n>.json",
                    "planning/interface_manifest_round_<n>.json",
                ],
                "outputs": [
                    "planning/assembly_semantics_round_<n>.json",
                    "planning/assembly_patch_round_<n>.json",
                ],
            },
            {
                "agent": "compose_plan",
                "inputs": ["planning/geometry_plan_round_<n>.json", "planning/assembly_patch_round_<n>.json"],
                "outputs": ["planning/function_plan_round_<n>.json", "planning/function_plan.json"],
            },
        ],
    }
    metadata["pipeline"].append(
        {
            "agent": "compose_plan",
            "phase": "memory_snapshot",
            "inputs": ["events.jsonl"],
            "outputs": ["memory/run_memory.json"],
            "optional": True,
        }
    )
    # 瑜拌绨崇粔濠氭珟閹碘偓閺堝绗?Fusion 閹笛嗩攽閵嗕礁顕遍崙鎭掆偓浣硅閺屾挶鈧線鐛欑拠浣烘祲閸忓磭娈?pipeline 閸忓啯鏆熼幑?
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    append_event(run_dir=run_dir, event_type="pipeline.metadata_written", data={"path": "metadata.json"})
    _sync_agent_review_outputs(
        run_dir=run_dir,
        agent_name="pipeline",
        rel_paths=["input/anforderungsliste.yaml", "metadata.json"],
    )

    guardrail_p1_records: List[Dict[str, Any]] = []

    # Agent executions (no dispatcher/executor/CAD)
    try:
        max_rounds = int(args.max_rounds)
        if max_rounds < 1:
            raise ValueError("--max-rounds must be >= 1")

        # Round 1: requirement_to_kg (facts-layer transform)
        log_agent_event(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            phase="start",
            payload={"inputs_written": ["input/anforderungsliste.yaml"], "outputs_written": []},
            round_index=1,
        )
        snap_before = _snapshot_run_files(run_dir)
        requirement_to_kg_run(run_dir=run_dir, schema_path=Path(args.schema))
        snap_after = _snapshot_run_files(run_dir)
        req_outputs = _diff_outputs(snap_before, snap_after)
        log_agent_event(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            phase="end",
            payload={"inputs_written": [], "outputs_written": req_outputs},
            round_index=1,
        )
        audit_guardrails(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            outputs_written=req_outputs,
            p1_sink=guardrail_p1_records,
        )
        _sync_agent_review_outputs(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            rel_paths=["knowledge/knowledge_graph.json", *req_outputs],
            round_index=1,
        )

        # Agent1 subphase: deterministic standard-parts grounding and validation.
        log_agent_event(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            phase="standard_parts_start",
            payload={"inputs_written": ["knowledge/knowledge_graph.json"], "outputs_written": []},
            round_index=1,
        )
        snap_before = _snapshot_run_files(run_dir)
        agent1_standard_parts_resolver_run(run_dir=run_dir)
        inject_resolved_standard_parts(run_dir=run_dir)

        std_validator = REPO_ROOT / "validation" / "validate_standard_parts_consistency.py"
        proc_std = subprocess.run(
            [sys.executable, str(std_validator), "--run-dir", str(run_dir)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if proc_std.stdout:
            print(proc_std.stdout, end="")
        if proc_std.stderr:
            print(proc_std.stderr, end="", file=sys.stderr)
        append_event(
            run_dir=run_dir,
            event_type="pipeline.standard_parts_validated",
            data={
                "ok": proc_std.returncode == 0,
                "exit_code": proc_std.returncode,
                "validator": str(std_validator),
                "report": "validation/standard_parts_consistency.json",
            },
        )
        if proc_std.returncode != 0:
            raise SystemExit(
                "Standard parts consistency validation failed. "
                f"See: {run_dir / 'validation' / 'standard_parts_consistency.json'}"
            )

        snap_after = _snapshot_run_files(run_dir)
        std_outputs = _diff_outputs(snap_before, snap_after)
        log_agent_event(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            phase="standard_parts_end",
            payload={"inputs_written": [], "outputs_written": std_outputs},
            round_index=1,
        )
        audit_guardrails(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            outputs_written=std_outputs,
            p1_sink=guardrail_p1_records,
        )
        _sync_agent_review_outputs(
            run_dir=run_dir,
            agent_name="requirement_to_kg",
            rel_paths=[
                "knowledge/knowledge_graph.json",
                "planning/standard_parts_resolved.json",
                "planning/standard_parts_unresolved.json",
                "validation/standard_parts_consistency.json",
                *std_outputs,
            ],
            round_index=1,
        )

        for round_index in range(1, max_rounds + 1):
            append_event(
                run_dir=run_dir,
                event_type="pipeline.planning_round.start",
                data={"round_index": round_index},
            )

            # plan_geometry_semantic (NEW: outputs construction semantics)
            log_agent_event(
                run_dir=run_dir,
                agent_name="plan_geometry_semantic",
                phase="start",
                payload={"inputs_written": ["knowledge/knowledge_graph.json"], "outputs_written": []},
                round_index=round_index,
            )
            snap_before = _snapshot_run_files(run_dir)
            plan_geometry_semantic_run(run_dir=run_dir, round_index=round_index)
            snap_after = _snapshot_run_files(run_dir)
            sem_outputs = _diff_outputs(snap_before, snap_after)
            log_agent_event(
                run_dir=run_dir,
                agent_name="plan_geometry_semantic",
                phase="end",
                payload={
                    "inputs_written": [],
                    "outputs_written": sem_outputs,
                },
                round_index=round_index,
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="plan_geometry_semantic",
                outputs_written=sem_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="plan_geometry_semantic",
                rel_paths=[
                    f"planning/geometry_semantics_modeling_round_{round_index}.json",
                    f"planning/geometry_semantics_assembly_round_{round_index}.json",
                    f"planning/interface_manifest_round_{round_index}.json",
                    *sem_outputs,
                ],
                round_index=round_index,
            )

            # Agent3a: shape_realization_planner_3a (strategy-level planning)
            log_agent_event(
                run_dir=run_dir,
                agent_name="shape_realization_planner_3a",
                phase="start",
                payload={
                    "inputs_written": [
                        "knowledge/knowledge_graph.json",
                        f"planning/geometry_semantics_modeling_round_{round_index}.json",
                    ],
                    "outputs_written": [],
                },
                round_index=round_index,
            )
            snap_before = _snapshot_run_files(run_dir)
            shape_realization_planner_run(run_dir=run_dir, round_index=round_index)
            snap_after = _snapshot_run_files(run_dir)
            geom_outputs = _diff_outputs(snap_before, snap_after)
            log_agent_event(
                run_dir=run_dir,
                agent_name="shape_realization_planner_3a",
                phase="end",
                payload={
                    "inputs_written": [],
                    "outputs_written": geom_outputs,
                },
                round_index=round_index,
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="shape_realization_planner_3a",
                outputs_written=geom_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="shape_realization_planner_3a",
                rel_paths=[
                    f"planning/shape_realization_round_{round_index}.json",
                    *geom_outputs,
                ],
                round_index=round_index,
            )

            # Agent3b: compile_geometry_plan_3b (strategy -> geometry plan)
            log_agent_event(
                run_dir=run_dir,
                agent_name="compile_geometry_plan_3b",
                phase="start",
                payload={
                    "inputs_written": [
                        f"planning/shape_realization_round_{round_index}.json",
                    ],
                    "outputs_written": [],
                },
                round_index=round_index,
            )
            snap_before = _snapshot_run_files(run_dir)
            compile_geometry_plan_run(run_dir=run_dir, round_index=round_index)
            snap_after = _snapshot_run_files(run_dir)
            geom_plan_outputs = _diff_outputs(snap_before, snap_after)
            log_agent_event(
                run_dir=run_dir,
                agent_name="compile_geometry_plan_3b",
                phase="end",
                payload={
                    "inputs_written": [],
                    "outputs_written": geom_plan_outputs,
                },
                round_index=round_index,
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="compile_geometry_plan_3b",
                outputs_written=geom_plan_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="compile_geometry_plan_3b",
                rel_paths=[
                    f"planning/geometry_plan_round_{round_index}.json",
                    f"planning/selected_geometry_plan_round_{round_index}.json",
                    f"planning/interface_manifest_round_{round_index}.json",
                    *geom_plan_outputs,
                ],
                round_index=round_index,
            )

            # plan_assembly
            log_agent_event(
                run_dir=run_dir,
                agent_name="plan_assembly",
                phase="start",
                payload={
                    "inputs_written": [
                        "knowledge/knowledge_graph.json",
                        f"planning/geometry_semantics_assembly_round_{round_index}.json",
                        f"planning/geometry_semantics_modeling_round_{round_index}.json",
                        f"planning/interface_manifest_round_{round_index}.json",
                    ],
                    "outputs_written": [],
                },
                round_index=round_index,
            )
            snap_before = _snapshot_run_files(run_dir)
            plan_assembly_run(run_dir=run_dir, round_index=round_index)
            snap_after = _snapshot_run_files(run_dir)
            asm_outputs = _diff_outputs(snap_before, snap_after)
            log_agent_event(
                run_dir=run_dir,
                agent_name="plan_assembly",
                phase="end",
                payload={
                    "inputs_written": [],
                    "outputs_written": asm_outputs,
                },
                round_index=round_index,
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="plan_assembly",
                outputs_written=asm_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="plan_assembly",
                rel_paths=[
                    f"planning/assembly_semantics_round_{round_index}.json",
                    f"planning/assembly_patch_round_{round_index}.json",
                    *asm_outputs,
                ],
                round_index=round_index,
            )

            # Use selected geometry plan if available
            _use_selected_geometry_plan_if_exists(run_dir=run_dir, round_index=round_index)

            # compose_plan
            log_agent_event(
                run_dir=run_dir,
                agent_name="compose_plan",
                phase="start",
                payload={
                    "inputs_written": [
                        f"planning/geometry_plan_round_{round_index}.json",
                        f"planning/assembly_patch_round_{round_index}.json",
                        f"planning/assembly_semantics_round_{round_index}.json",
                    ],
                    "outputs_written": [],
                },
                round_index=round_index,
            )
            snap_before = _snapshot_run_files(run_dir)
            compose_plan_run(run_dir=run_dir, round_index=round_index)
            snap_after = _snapshot_run_files(run_dir)
            compose_outputs = _diff_outputs(snap_before, snap_after)
            log_agent_event(
                run_dir=run_dir,
                agent_name="compose_plan",
                phase="end",
                payload={
                    "inputs_written": [],
                    "outputs_written": compose_outputs,
                },
                round_index=round_index,
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="compose_plan",
                outputs_written=compose_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="compose_plan",
                rel_paths=[
                    f"planning/function_plan_round_{round_index}.json",
                    "planning/function_plan.json",
                    "planning/function_plan_final.json",
                    *compose_outputs,
                ],
                round_index=round_index,
            )
            # Registry gate: functions/functions.json <-> fusion_api_server/modeling.py must align.
            verifier = REPO_ROOT / "tools" / "verify_function_registry.py"
            verifier_report = run_dir / "validation" / "function_registry_check.json"
            proc_registry = subprocess.run(
                [
                    sys.executable,
                    str(verifier),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--out",
                    str(verifier_report),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            if proc_registry.stdout:
                print(proc_registry.stdout, end="")
            if proc_registry.stderr:
                print(proc_registry.stderr, end="", file=sys.stderr)
            append_event(
                run_dir=run_dir,
                event_type="pipeline.registry_verified",
                data={
                    "ok": proc_registry.returncode == 0,
                    "exit_code": proc_registry.returncode,
                    "report": str(verifier_report.relative_to(run_dir)).replace("\\", "/"),
                },
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="pipeline",
                rel_paths=["validation/function_registry_check.json"],
            )
            if proc_registry.returncode != 0:
                raise SystemExit(
                    "Function registry verification failed. "
                    f"See: {verifier_report}"
                )
            # compose_plan 閸氬孩妫ら弶鈥叉鐎电厧鍤?fusion_manual_plan.json
            planning_dir = run_dir / "planning"
            plan_path = planning_dir / "function_plan_final.json"
            if not plan_path.exists():
                plan_path = planning_dir / "function_plan.json"
            manual_plan_path = None
            try:
                plan_data = _read_json(plan_path)
                fusion_steps, dropped_steps = _extract_fusion_manual_plan(plan_data)
                dropped_path = planning_dir / "dropped_steps.json"
                dropped_payload = {
                    "metadata": {
                        "source_plan": str(plan_path.relative_to(run_dir)).replace("\\", "/"),
                        "allow_dropped_steps": os.getenv("ALLOW_DROPPED_STEPS", "0") == "1",
                    },
                    "summary": {
                        "dropped_count": len(dropped_steps),
                        "kept_count": len(fusion_steps),
                    },
                    "dropped_steps": dropped_steps,
                }
                _write_json(dropped_path, dropped_payload)

                allow_dropped = os.getenv("ALLOW_DROPPED_STEPS", "0") == "1"
                if dropped_steps and not allow_dropped:
                    raise RuntimeError(
                        "fusion_manual_plan export blocked: dropped steps detected after allowlist filtering. "
                        f"Set ALLOW_DROPPED_STEPS=1 to bypass. See: {dropped_path}"
                    )

                manual_plan = {"steps": fusion_steps}
                manual_plan_path = run_dir / "fusion_manual_plan.json"
                _write_json(manual_plan_path, manual_plan)
                append_event(
                    run_dir=run_dir,
                    event_type="pipeline.fusion_manual_plan_exported",
                    data={
                        "path": str(manual_plan_path.relative_to(run_dir)),
                        "num_steps": len(fusion_steps),
                        "dropped_steps": len(dropped_steps),
                        "dropped_report": str(dropped_path.relative_to(run_dir)).replace("\\", "/"),
                    },
                )
                _sync_agent_review_outputs(
                    run_dir=run_dir,
                    agent_name="pipeline",
                    rel_paths=["fusion_manual_plan.json", "planning/dropped_steps.json"],
                )
            except Exception as e:
                append_event(
                    run_dir=run_dir,
                    event_type="pipeline.fusion_manual_plan_export_failed",
                    data={"error": repr(e)},
                )

            # Agent5 post-run observability snapshot (facts-only)
            log_agent_event(
                run_dir=run_dir,
                agent_name="compose_plan",
                phase="memory_snapshot_start",
                payload={"inputs_written": ["events.jsonl"], "outputs_written": []},
            )
            snap_before = _snapshot_run_files(run_dir)
            mem_res = compose_plan_memory_snapshot_run(run_dir=run_dir)
            snap_after = _snapshot_run_files(run_dir)

            mem_outputs: List[str] = []
            if isinstance(mem_res, dict):
                p = mem_res.get("path")
                if isinstance(p, str) and p.strip():
                    mem_outputs = [p.strip()]
            if not mem_outputs:
                mem_outputs = _diff_outputs(snap_before, snap_after)

            log_agent_event(
                run_dir=run_dir,
                agent_name="compose_plan",
                phase="memory_snapshot_end",
                payload={"inputs_written": [], "outputs_written": mem_outputs},
            )
            audit_guardrails(
                run_dir=run_dir,
                agent_name="compose_plan",
                outputs_written=mem_outputs,
                p1_sink=guardrail_p1_records,
            )
            _sync_agent_review_outputs(
                run_dir=run_dir,
                agent_name="compose_plan",
                rel_paths=["memory/run_memory.json", *mem_outputs],
            )

            # DoD gate: validate placement invariants for this run.
            if manual_plan_path is not None:
                validator = REPO_ROOT / "tools" / "validate_placement_dod.py"
                try:
                    proc = subprocess.run(
                        [sys.executable, str(validator), "--run-dir", str(run_dir)],
                        cwd=str(REPO_ROOT),
                        capture_output=True,
                        text=True,
                    )
                    if proc.stdout:
                        print(proc.stdout, end="")
                    if proc.stderr:
                        print(proc.stderr, end="", file=sys.stderr)
                    append_event(
                        run_dir=run_dir,
                        event_type="pipeline.placement_dod_validated",
                        data={"ok": proc.returncode == 0, "exit_code": proc.returncode, "validator": str(validator)},
                    )
                    _sync_agent_review_outputs(
                        run_dir=run_dir,
                        agent_name="pipeline",
                        rel_paths=[
                            "placement_diagnostics.json",
                            "validation/placement_injection_report.json",
                        ],
                    )
                    if proc.returncode != 0:
                        raise SystemExit(
                            "Placement DoD validation failed. "
                            f"See: {run_dir / 'placement_diagnostics.json'}"
                        )
                except SystemExit:
                    raise
                except Exception as e:
                    append_event(
                        run_dir=run_dir,
                        event_type="pipeline.placement_dod_validation_error",
                        data={"error": repr(e), "validator": str(validator)},
                    )
                    raise

            if manual_plan_path is not None:
                if guardrail_p1_records:
                    guardrail_report = {
                        "metadata": {
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "source": "run_pipeline.audit_guardrails",
                        },
                        "summary": {
                            "p1_groups": len(guardrail_p1_records),
                            "p1_violations": sum(int(item.get("count", 0)) for item in guardrail_p1_records),
                        },
                        "groups": guardrail_p1_records,
                    }
                    (run_dir / "validation" / "guardrail_summary.json").write_text(
                        json.dumps(guardrail_report, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("[GUARDRAIL][P1] Contract drift detected (pipeline continued).")
                    print(
                        "[GUARDRAIL][P1] "
                        f"groups={guardrail_report['summary']['p1_groups']} "
                        f"violations={guardrail_report['summary']['p1_violations']} "
                        "report=validation/guardrail_summary.json"
                    )
                    _sync_agent_review_outputs(
                        run_dir=run_dir,
                        agent_name="pipeline",
                        rel_paths=["validation/guardrail_summary.json"],
                    )

                print(f"\nPipeline finished. Final output: {manual_plan_path}\n")
                print(f"Review outputs: {final_dir}\n")
            else:
                print("\nPipeline finished, but fusion_manual_plan.json was not generated.\n")
                print(f"Review outputs: {final_dir}\n")
            return

    except Exception as e:
        append_event(
            run_dir=run_dir,
            event_type="pipeline.error",
            data={"error": repr(e)},
        )
        raise

    print(f"Run created: {run_dir}")
    print("\nPipeline finished successfully.\n鐠囧嘲婀?Fusion 360 娑擃厽澧滈崝銊ㄧ箥鐞?fusion_api_server.py閿涘矁鍤滈崝銊嚢閸?fusion_manual_plan.json 楠炶泛缂撳Ο掳鈧繐n")


if __name__ == "__main__":
    main()
