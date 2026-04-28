from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_metric_nominal(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    m = re.search(r"\bM\s*(\d+(?:\.\d+)?)", value, flags=re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _extract_metric_length_from_designation(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    m = re.search(r"\bM\s*\d+(?:\.\d+)?\s*[x×]\s*(\d+(?:\.\d+)?)", value, flags=re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _extract_part_id_nominal(part_id: Any) -> float | None:
    if not isinstance(part_id, str):
        return None
    m = re.search(r"_M(\d+(?:\.\d+)?)_", part_id, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"_M(\d+(?:\.\d+)?)$", part_id, flags=re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _extract_part_id_length(part_id: Any) -> float | None:
    if not isinstance(part_id, str):
        return None
    m = re.search(r"_L(\d+(?:\.\d+)?)_", part_id, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"_L(\d+(?:\.\d+)?)$", part_id, flags=re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _normalize_standard_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = re.sub(r"\s+", "", value).upper().strip()
    if not token:
        return None
    token = token.replace("GB/T", "GBT")
    return token


def _extract_designation_standard(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.search(r"\b(ISO\s*\d+|DIN\s*\d+|GB\s*/?\s*T\s*\d+|GBT\s*\d+)\b", value, flags=re.IGNORECASE)
    if not m:
        return None
    return _normalize_standard_token(m.group(1))


def _extract_part_id_standard(part_id: Any) -> str | None:
    if not isinstance(part_id, str):
        return None
    m = re.search(r"^[^_]+_([^_]+)_M\d", part_id, flags=re.IGNORECASE)
    if not m:
        return None
    return _normalize_standard_token(m.group(1))


def validate_run(run_dir: Path) -> Dict[str, Any]:
    resolved_path = run_dir / "planning" / "standard_parts_resolved.json"
    report_path = run_dir / "validation" / "standard_parts_consistency.json"

    issues: List[Dict[str, Any]] = []
    checked = 0

    if not resolved_path.exists():
        payload = {
            "metadata": {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": str(resolved_path).replace("\\", "/"),
            },
            "summary": {"checked": 0, "issues": 0, "ok": True},
            "issues": [],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    payload = _read_json(resolved_path)
    resolved = payload.get("resolved", []) if isinstance(payload, Mapping) else []
    if not isinstance(resolved, list):
        resolved = []

    for row in resolved:
        if not isinstance(row, Mapping):
            continue
        category = str(row.get("category") or "").strip().lower()
        if category not in {"fastener", "bolt", "screw", "nut", "washer", "rivet"}:
            continue
        checked += 1

        designation = row.get("designation")
        if not isinstance(designation, str) or not designation.strip():
            designation = row.get("resolved_designation")
        if not isinstance(designation, str) or not designation.strip():
            designation = row.get("size")

        part_id = row.get("part_id")
        des_nominal = _extract_metric_nominal(designation)
        part_nominal = _extract_part_id_nominal(part_id)
        des_length = _extract_metric_length_from_designation(designation)
        part_length = _extract_part_id_length(part_id)

        des_standard = _extract_designation_standard(designation)
        if not des_standard:
            des_standard = _normalize_standard_token(row.get("standard"))
        part_standard = _extract_part_id_standard(part_id)

        if isinstance(des_nominal, (int, float)) and isinstance(part_nominal, (int, float)):
            if abs(float(des_nominal) - float(part_nominal)) > 1e-6:
                issues.append(
                    {
                        "id": row.get("id"),
                        "category": category,
                        "designation": designation,
                        "part_id": part_id,
                        "designation_nominal_mm": des_nominal,
                        "part_id_nominal_mm": part_nominal,
                        "reason": "designation_part_id_metric_nominal_mismatch",
                    }
                )

        if isinstance(des_length, (int, float)) and isinstance(part_length, (int, float)):
            if abs(float(des_length) - float(part_length)) > 1e-6:
                issues.append(
                    {
                        "id": row.get("id"),
                        "category": category,
                        "designation": designation,
                        "part_id": part_id,
                        "designation_length_mm": des_length,
                        "part_id_length_mm": part_length,
                        "reason": "designation_part_id_length_mismatch",
                    }
                )

        if isinstance(des_standard, str) and isinstance(part_standard, str):
            if des_standard != part_standard:
                issues.append(
                    {
                        "id": row.get("id"),
                        "category": category,
                        "designation": designation,
                        "part_id": part_id,
                        "designation_standard": des_standard,
                        "part_id_standard": part_standard,
                        "reason": "designation_part_id_standard_mismatch",
                    }
                )

    report = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(resolved_path).replace("\\", "/"),
        },
        "summary": {
            "checked": checked,
            "issues": len(issues),
            "ok": len(issues) == 0,
        },
        "issues": issues,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate standard-parts designation/part_id consistency")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    report = validate_run(run_dir)
    ok = bool(report.get("summary", {}).get("ok", False))
    print(f"[STD_PARTS_CHECK] checked={report.get('summary', {}).get('checked', 0)} issues={report.get('summary', {}).get('issues', 0)}")
    if not ok:
        raise SystemExit(
            "Standard parts consistency validation failed. "
            f"See: {run_dir / 'validation' / 'standard_parts_consistency.json'}"
        )


if __name__ == "__main__":
    main()
