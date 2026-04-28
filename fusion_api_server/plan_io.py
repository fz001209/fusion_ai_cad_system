"""Locate and load ``fusion_manual_plan.json`` for Fusion-side execution."""

from __future__ import annotations

import json
import os
from pathlib import Path


def get_run_id_and_dir():
    run_id = os.environ.get("FUSION_RUN_ID") or "demo_001"
    run_dir = os.path.join("execution", "runs", run_id)
    return run_id, run_dir


def find_repo_root():
    """Find the repo root by locating ``tools/run_pipeline.py``."""
    env_root = os.environ.get("FUSION_REPO_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if (env_path / "tools" / "run_pipeline.py").is_file():
            return env_path

    def _walk_up(start: Path):
        cur = start
        while cur != cur.parent:
            if (cur / "tools" / "run_pipeline.py").is_file():
                return cur
            cur = cur.parent
        return None

    found = _walk_up(Path(__file__).resolve().parent)
    if found:
        return found

    cwd = Path.cwd().resolve()
    found = _walk_up(cwd)
    if found:
        return found

    return None


def _latest_child_dir(parent: Path):
    if not parent.is_dir():
        return None
    run_dirs = [d for d in parent.iterdir() if d.is_dir()]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return run_dirs[0]


def find_latest_run_dir(repo_root):
    return _latest_child_dir(repo_root / "execution" / "runs")


def find_latest_sample_run_dir(repo_root):
    return _latest_child_dir(repo_root / "archive" / "sample_runs")


def _resolve_named_run_dir(repo_root: Path, run_id: str):
    candidates = (
        repo_root / "execution" / "runs" / run_id,
        repo_root / "archive" / "sample_runs" / run_id,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def resolve_plan_path(repo_root):
    env_path = os.environ.get("FUSION_PLAN_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.is_file():
            return p

    if repo_root is None:
        return None

    run_id = (os.environ.get("FUSION_RUN_ID") or "").strip()
    if run_id:
        named_run = _resolve_named_run_dir(repo_root, run_id)
        if named_run is not None:
            plan_path = named_run / "fusion_manual_plan.json"
            if plan_path.is_file():
                return plan_path

    for run_dir in (
        find_latest_run_dir(repo_root),
        find_latest_sample_run_dir(repo_root),
    ):
        if run_dir is None:
            continue
        plan_path = run_dir / "fusion_manual_plan.json"
        if plan_path.is_file():
            return plan_path

    return None


def describe_plan_lookup(repo_root):
    paths = []

    env_path = (os.environ.get("FUSION_PLAN_PATH") or "").strip()
    if env_path:
        paths.append(f"FUSION_PLAN_PATH={Path(env_path).expanduser()}")

    run_id = (os.environ.get("FUSION_RUN_ID") or "").strip()
    if repo_root is not None and run_id:
        paths.append(repo_root / "execution" / "runs" / run_id / "fusion_manual_plan.json")
        paths.append(repo_root / "archive" / "sample_runs" / run_id / "fusion_manual_plan.json")

    if repo_root is not None:
        paths.append(repo_root / "execution" / "runs" / "<latest>" / "fusion_manual_plan.json")
        paths.append(repo_root / "archive" / "sample_runs" / "<latest>" / "fusion_manual_plan.json")

    return [str(p) for p in paths]


def load_plan(plan_path):
    with open(plan_path, "r", encoding="utf-8") as f:
        return json.load(f)


def derive_run_dir(plan_path):
    p = Path(plan_path).resolve()
    if p.name != "fusion_manual_plan.json":
        raise ValueError("plan_path is not fusion_manual_plan.json")
    return p.parent
