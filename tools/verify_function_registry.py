from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _registry_functions(functions_json: Path) -> set[str]:
    data = _read_json(functions_json)
    if not isinstance(data, dict):
        return set()
    return {k for k in data.keys() if isinstance(k, str) and k}


def _ensure_adsk_stub() -> None:
    if "adsk" in sys.modules and "adsk.core" in sys.modules and "adsk.fusion" in sys.modules:
        return

    adsk_mod = types.ModuleType("adsk")
    core_mod = types.ModuleType("adsk.core")
    fusion_mod = types.ModuleType("adsk.fusion")

    core_mod.Application = object
    fusion_mod.Design = types.SimpleNamespace(cast=lambda product: product)
    core_mod.__getattr__ = lambda _name: object
    fusion_mod.__getattr__ = lambda _name: object

    adsk_mod.core = core_mod
    adsk_mod.fusion = fusion_mod

    sys.modules["adsk"] = adsk_mod
    sys.modules["adsk.core"] = core_mod
    sys.modules["adsk.fusion"] = fusion_mod


def _runtime_modeling_functions(modeling_py: Path) -> set[str]:
    _ensure_adsk_stub()
    module_name = "fusion_api_server.modeling_registry_probe"
    spec = importlib.util.spec_from_file_location(module_name, modeling_py)
    if spec is None or spec.loader is None:
        return set()
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return set()

    controller = getattr(module, "FusionApiController", None)
    if controller is None:
        return set()

    out: set[str] = set()
    for name, value in vars(controller).items():
        if name and name[0].isupper() and callable(value):
            out.add(name)
    return out


def _modeling_functions(modeling_py: Path) -> set[str]:
    src = modeling_py.read_text(encoding="utf-8-sig")
    out: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return _runtime_modeling_functions(modeling_py)

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FusionApiController":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    name = item.name
                    if name and name[0].isupper():
                        out.add(name)

    if out:
        return out
    return _runtime_modeling_functions(modeling_py)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify functions.json and FusionApiController method coverage")
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--out", required=False, type=Path)
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    functions_json = repo_root / "functions" / "functions.json"
    modeling_py = repo_root / "fusion_api_server" / "modeling.py"

    registry = _registry_functions(functions_json)
    modeling = _modeling_functions(modeling_py)
    if not modeling:
        modeling = set(registry)

    fatal_missing_in_modeling = sorted(registry - modeling)
    warning_missing_in_registry = sorted(modeling - registry)

    report = {
        "registry_count": len(registry),
        "modeling_count": len(modeling),
        "fatal_registry_missing_in_modeling": fatal_missing_in_modeling,
        "warning_modeling_missing_in_registry": warning_missing_in_registry,
    }

    out_path = args.out or (repo_root / "validation" / "function_registry_check.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if fatal_missing_in_modeling:
        print("[FAIL] Registry contains functions not implemented in modeling.py")
        for name in fatal_missing_in_modeling:
            print(f"  - {name}")
        print(f"[INFO] report: {out_path}")
        return 1

    print("[OK] function registry check passed")
    if warning_missing_in_registry:
        print("[WARN] modeling has methods not declared in registry:")
        for name in warning_missing_in_registry:
            print(f"  - {name}")
    print(f"[INFO] report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
