from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

SUPPORTED_EXTS = {".f3d", ".f3z", ".step", ".stp"}


def _safe_float(token: str) -> float | None:
    try:
        return float(token)
    except Exception:
        return None


def _parse_length_mm(token: str) -> float | None:
    raw = token.strip()
    if not raw:
        return None
    m = re.fullmatch(r"[Ll](\d+(?:\.\d+)?)", raw)
    if m:
        return _safe_float(m.group(1))
    return _safe_float(raw)


def _parse_bearing_dims_token(token: str) -> Tuple[float | None, float | None, float | None]:
    text = token.strip().lower().replace("mm", "")
    if not text:
        return None, None, None
    for sep in ("x", "_", "-"):
        parts = [p for p in text.split(sep) if p]
        if len(parts) == 3:
            vals = [_safe_float(p) for p in parts]
            if all(v is not None for v in vals):
                return vals[0], vals[1], vals[2]
    return None, None, None


def _iter_cad_files(cad_root: Path) -> Iterable[Path]:
    if not cad_root.exists():
        return
    for path in cad_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            yield path


def _entry_from_fastener(rel_parts: List[str], rel_posix: str, stem: str) -> Dict[str, Any] | None:
    # expected:
    # cad/fasteners/<kind>/<standard>/<size>/<length>/<lod>/<file>
    if len(rel_parts) < 7:
        return None
    _, _, kind, standard, size, length_token, lod = rel_parts[:7]
    length_mm = _parse_length_mm(length_token)
    entry: Dict[str, Any] = {
        "part_id": stem,
        "family": "fastener",
        "kind": kind.lower(),
        "standard": standard,
        "size": size,
        "lod": lod.lower(),
        "cad_relpath": rel_posix,
    }
    if length_mm is not None:
        entry["length_mm"] = length_mm
    m = re.fullmatch(r"[Mm](\d+(?:\.\d+)?)", size.strip())
    if m:
        dia = _safe_float(m.group(1))
        if dia is not None:
            entry["nominal_diameter_mm"] = dia
    return entry


def _entry_from_bearing(rel_parts: List[str], rel_posix: str, stem: str) -> Dict[str, Any] | None:
    # expected:
    # cad/bearings/<series>/<designation_or_dims>/<lod>/<file>
    if len(rel_parts) < 6:
        return None
    _, _, series, designation_or_dims, lod = rel_parts[:5]
    id_mm, od_mm, w_mm = _parse_bearing_dims_token(designation_or_dims)
    entry: Dict[str, Any] = {
        "part_id": stem,
        "family": "bearing",
        "type": series,
        "lod": lod.lower(),
        "cad_relpath": rel_posix,
    }
    if id_mm is not None and od_mm is not None and w_mm is not None:
        entry["inner_diameter_mm"] = id_mm
        entry["outer_diameter_mm"] = od_mm
        entry["width_mm"] = w_mm
        entry["designation"] = designation_or_dims
    else:
        entry["designation"] = designation_or_dims
    return entry


def _entry_from_path(cad_root: Path, file_path: Path) -> Tuple[Dict[str, Any] | None, str | None]:
    rel = file_path.relative_to(cad_root.parent)  # keep prefix as cad/...
    rel_parts = list(rel.parts)
    rel_posix = rel.as_posix()
    stem = file_path.stem

    if len(rel_parts) < 2:
        return None, f"skip unsupported path: {rel_posix}"

    top = rel_parts[1].lower() if rel_parts[0].lower() == "cad" and len(rel_parts) > 1 else ""
    if top == "fasteners":
        entry = _entry_from_fastener(rel_parts, rel_posix, stem)
        if entry is None:
            return None, f"skip malformed fastener path: {rel_posix}"
        return entry, None
    if top == "bearings":
        entry = _entry_from_bearing(rel_parts, rel_posix, stem)
        if entry is None:
            return None, f"skip malformed bearing path: {rel_posix}"
        return entry, None

    return None, f"skip unknown family path: {rel_posix}"


def build_index(library_root: Path) -> Dict[str, Any]:
    cad_root = library_root / "cad"
    index_path = library_root / "index" / "parts_index.json"

    existing_entries: Dict[str, Dict[str, Any]] = {}
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            parts = payload.get("parts") if isinstance(payload, dict) else None
            if isinstance(parts, list):
                for item in parts:
                    if isinstance(item, dict) and isinstance(item.get("part_id"), str):
                        existing_entries[item["part_id"]] = item
        except Exception:
            pass

    warnings: List[str] = []
    generated: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for file_path in sorted(_iter_cad_files(cad_root), key=lambda p: p.as_posix().lower()):
        entry, warn = _entry_from_path(cad_root, file_path)
        if warn:
            warnings.append(warn)
            continue
        if not isinstance(entry, dict):
            continue

        part_id = str(entry.get("part_id") or "").strip()
        if not part_id:
            warnings.append(f"skip part without part_id: {file_path}")
            continue
        if part_id in seen:
            warnings.append(f"duplicate part_id '{part_id}', keep first")
            continue
        seen.add(part_id)

        prev = existing_entries.get(part_id)
        if isinstance(prev, dict):
            merged = dict(prev)
            merged.update(entry)
            entry = merged
        generated.append(entry)

    result = {
        "version": "0.1",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "parts": generated,
        "warnings": warnings,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build part_library/index/parts_index.json from part_library/cad")
    parser.add_argument(
        "--library-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "part_library",
        help="Root of part_library (default: <repo>/part_library)",
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=None,
        help="Optional output index path (default: <library-root>/index/parts_index.json)",
    )
    args = parser.parse_args()

    library_root = args.library_root.resolve()
    output = args.index_path.resolve() if args.index_path else (library_root / "index" / "parts_index.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = build_index(library_root)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] parts_index generated: {output}")
    print(f"  - parts: {len(payload.get('parts', []))}")
    print(f"  - warnings: {len(payload.get('warnings', []))}")


if __name__ == "__main__":
    main()
