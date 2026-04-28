from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tail_jsonl(path: Path, max_lines: int = 50) -> List[Dict[str, Any]]:
    if max_lines <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for raw in lines[-max_lines:]:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _count_jsonl(path: Path) -> int:
    try:
        return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    except Exception:
        return 0


def run(*, run_dir: Path) -> Dict[str, str]:
    """Write a facts-only memory snapshot for the run (debug-friendly)."""
    memory_dir = run_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    events_path = run_dir / "events.jsonl"
    stats = {"events": 0, "errors": 0}
    if events_path.exists():
        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            stats["events"] += 1
            try:
                event: Dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
            if event_type.endswith("error") or "error" in data:
                stats["errors"] += 1

    # Fusion markers (best-effort)
    fusion_started = _read_json(run_dir / "fusion_started.json")
    fusion_failed = _read_json(run_dir / "fusion_failed.json")
    fusion_done = _read_json(run_dir / "fusion_done.json")
    fusion_warnings = _read_json(run_dir / "fusion_warnings.json")

    # Fusion step trace (best-effort)
    step_trace_path = run_dir / "execution" / "fusion_step_trace.jsonl"
    step_trace = None
    if step_trace_path.exists():
        tail = _tail_jsonl(step_trace_path, max_lines=20)
        step_trace = {
            "path": str(step_trace_path.relative_to(run_dir)),
            "lines": _count_jsonl(step_trace_path),
            "tail": tail,
        }

    payload = {
        "stats": stats,
        "fusion": {
            "started": fusion_started,
            "failed": fusion_failed,
            "done": fusion_done,
            "warnings": fusion_warnings,
            "step_trace": step_trace,
        },
    }
    out_path = memory_dir / "run_memory.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(out_path.relative_to(run_dir))}
