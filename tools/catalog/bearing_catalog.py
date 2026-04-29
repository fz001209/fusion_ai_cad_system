from __future__ import annotations

import re
from typing import Any, Dict

BEARING_CATALOG: list[Dict[str, Any]] = [
    {"code": "625", "bore": 5.0, "outer": 16.0, "width": 5.0, "series": "62xx"},
    {"code": "606", "bore": 6.0, "outer": 17.0, "width": 6.0, "series": "60xx"},
    {"code": "626", "bore": 6.0, "outer": 19.0, "width": 6.0, "series": "62xx"},
    {"code": "607", "bore": 7.0, "outer": 19.0, "width": 6.0, "series": "60xx"},
    {"code": "608", "bore": 8.0, "outer": 22.0, "width": 7.0, "series": "60xx"},
    {"code": "628", "bore": 8.0, "outer": 24.0, "width": 8.0, "series": "62xx"},
    {"code": "6000", "bore": 10.0, "outer": 26.0, "width": 8.0, "series": "60xx"},
    {"code": "6200", "bore": 10.0, "outer": 30.0, "width": 9.0, "series": "62xx"},
    {"code": "6001", "bore": 12.0, "outer": 28.0, "width": 8.0, "series": "60xx"},
    {"code": "6201", "bore": 12.0, "outer": 32.0, "width": 10.0, "series": "62xx"},
    {"code": "6002", "bore": 15.0, "outer": 32.0, "width": 9.0, "series": "60xx"},
    {"code": "6202", "bore": 15.0, "outer": 35.0, "width": 11.0, "series": "62xx"},
    {"code": "6203", "bore": 17.0, "outer": 40.0, "width": 12.0, "series": "62xx"},
]


def _normalize_designation_text(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", text.upper())


def _extract_bearing_code(text: str) -> str | None:
    normalized = _normalize_designation_text(text)
    m = re.search(r"(6\d{2,3})", normalized)
    if not m:
        return None
    return m.group(1)


def find_bearing_by_designation(text: str) -> Dict[str, Any] | None:
    code = _extract_bearing_code(text)
    if not code:
        return None
    for item in BEARING_CATALOG:
        if str(item.get("code")) == code:
            return item
    return None


def nearest_bearing_by_dims(bore: float, outer: float, width: float) -> Dict[str, Any] | None:
    best = None
    best_score = None
    for item in BEARING_CATALOG:
        score = abs(float(item["bore"]) - bore) + abs(float(item["outer"]) - outer) + abs(float(item["width"]) - width)
        if best_score is None or score < best_score:
            best_score = score
            best = item
    return best


def candidate_series_for_bore(bore: float) -> list[str]:
    families = {
        str(item.get("series"))
        for item in BEARING_CATALOG
        if abs(float(item.get("bore", -1.0)) - bore) < 1e-6 and isinstance(item.get("series"), str)
    }
    return sorted(families)


def select_bearing_by_series_and_bore(series_hint: str, bore: float) -> Dict[str, Any] | None:
    prefix = ""
    hint = series_hint.lower().strip()
    if hint.startswith("60"):
        prefix = "60"
    elif hint.startswith("62"):
        prefix = "62"

    candidates = [
        item
        for item in BEARING_CATALOG
        if abs(float(item.get("bore", -1.0)) - bore) < 1e-6
        and (not prefix or str(item.get("code", "")).startswith(prefix))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (float(x.get("outer", 0.0)), float(x.get("width", 0.0))))
    return candidates[0]
