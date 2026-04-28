from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _iter_plan_files(planning_dir: Path) -> Iterable[Path]:
    # Read all function_plan*.json variants for maximal coverage evidence.
    # Examples: function_plan.json, function_plan_round_1.json
    yield from sorted(planning_dir.glob("function_plan*.json"))


def _normalize_function_name(fn: str) -> str:
    fn = (fn or "").strip()
    if fn.startswith("DISABLED::"):
        return fn[len("DISABLED::") :]
    return fn


def collect_used_functions(*, run_dir: Path) -> Set[str]:
    planning_dir = run_dir / "planning"
    used: Set[str] = set()

    for path in _iter_plan_files(planning_dir):
        try:
            raw = _read_json(path)
        except Exception:
            continue
        if not isinstance(raw, Mapping):
            continue
        steps = raw.get("steps")
        if not isinstance(steps, list):
            continue
        for s in steps:
            if not isinstance(s, Mapping):
                continue
            fn = s.get("function")
            if not isinstance(fn, str) or not fn.strip():
                continue
            used.add(_normalize_function_name(fn))

    return {u for u in used if u}


def generate_coverage_report(
    *,
    used_functions: Set[str],
    implemented_functions: Set[str],
) -> Dict[str, Any]:
    missing = sorted(used_functions - implemented_functions)
    extra = sorted(implemented_functions - used_functions)

    return {
        "used_functions": sorted(used_functions),
        "implemented_functions": sorted(implemented_functions),
        "missing_functions": missing,
        "extra_functions": extra,
        "ok": len(missing) == 0,
    }


def run(*, run_dir: Path, fusion_executor: Any) -> str:
    """Write a run-local capability coverage report (facts-only).

    Constraints:
    - Must not call Fusion API.
    - Reads only plan JSONs under run_dir/planning.
    - Writes only run_dir/execution/capability_coverage.json.

    Returns the run_dir-relative path to the report.
    """

    used = collect_used_functions(run_dir=run_dir)

    implemented_raw = fusion_executor.implemented_functions()
    implemented: Set[str] = set()
    if isinstance(implemented_raw, (list, set, tuple)):
        for x in implemented_raw:
            if isinstance(x, str) and x.strip():
                implemented.add(x.strip())

    report = generate_coverage_report(used_functions=used, implemented_functions=implemented)

    out_path = run_dir / "execution" / "capability_coverage.json"
    _write_json(out_path, report)

    return "execution/capability_coverage.json"
