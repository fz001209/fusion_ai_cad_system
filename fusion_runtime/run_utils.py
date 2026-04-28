from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


def _try_parse_timestamp(text: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _run_timestamp(run_dir: Path) -> Optional[datetime]:
    """Best-effort run timestamp.

    Preference order:
    1) run_dir/metadata.json -> timestamp
    2) run_dir/events.jsonl first line -> timestamp
    3) None

    This remains read-only and never mutates the run.
    """

    metadata_path = run_dir / "metadata.json"
    if metadata_path.exists():
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                ts = raw.get("timestamp")
                if isinstance(ts, str):
                    parsed = _try_parse_timestamp(ts)
                    if parsed is not None:
                        return parsed
        except Exception:
            pass

    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        try:
            first_line = events_path.open("r", encoding="utf-8").readline().strip()
            if first_line:
                rec = json.loads(first_line)
                if isinstance(rec, dict):
                    ts = rec.get("timestamp")
                    if isinstance(ts, str):
                        parsed = _try_parse_timestamp(ts)
                        if parsed is not None:
                            return parsed
        except Exception:
            pass

    return None


def list_runs_sorted(runs_dir: Path) -> List[Path]:
    """List run directories sorted from newest to oldest.

    Uses run metadata timestamps when available; otherwise falls back to directory mtime.
    """

    if not runs_dir.exists() or not runs_dir.is_dir():
        return []

    run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]

    def sort_key(p: Path) -> Tuple[int, float, str]:
        ts = _run_timestamp(p)
        if ts is not None:
            return (1, ts.timestamp(), p.name)
        try:
            return (0, p.stat().st_mtime, p.name)
        except Exception:
            return (0, 0.0, p.name)

    run_dirs.sort(key=sort_key, reverse=True)
    return run_dirs
