from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping


def append_event(
    *,
    run_dir: Path,
    event_type: str,
    data: Mapping[str, Any] | None = None,
    file_name: str = "events.jsonl",
) -> Path:
    """Append a single event record under a run directory.

    Facts-only output: JSONL (one JSON object per line).
    Writes nowhere outside run_dir.
    """

    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / file_name

    record: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "type": event_type,
        "data": dict(data) if data is not None else {},
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")

    return path
