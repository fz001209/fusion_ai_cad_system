"""
Best-effort marker writers for Fusion execution state files.
"""

import datetime
import hashlib
import inspect
import json
import os
import sys


def _ensure_dir(path):
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as exc:
        print(f"[marker_io] Failed to create run dir '{path}': {exc}")
        return False


def _safe_realpath(path):
    if not path:
        return ""
    try:
        return os.path.abspath(os.path.realpath(path))
    except Exception:
        return str(path)


def _file_runtime_info(path):
    info = {"path": _safe_realpath(path)}
    if not info["path"]:
        return info

    try:
        stat = os.stat(info["path"])
    except Exception:
        info["exists"] = False
        return info

    info["exists"] = True
    info["size"] = int(stat.st_size)
    info["mtime"] = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")

    try:
        digest = hashlib.sha1()
        with open(info["path"], "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        info["sha1"] = digest.hexdigest()
    except Exception:
        pass

    return info


def _resolve_loaded_module(*module_names):
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is not None:
            return module_name, module
    return None, None


def _safe_firstlineno(obj):
    if obj is None:
        return None
    try:
        _, first_lineno = inspect.getsourcelines(obj)
        return int(first_lineno)
    except Exception:
        return None


def _resolve_member(module, dotted_name):
    current = module
    for part in str(dotted_name).split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def _module_runtime_info(module_names, *, fallback_path=None, member_names=None):
    loaded_name, module = _resolve_loaded_module(*module_names)
    module_file = getattr(module, "__file__", None) if module is not None else None
    info = {
        "loaded": bool(module is not None),
        "loaded_name": loaded_name,
        "candidates": list(module_names),
    }
    info.update(_file_runtime_info(module_file or fallback_path))

    if module is None or not member_names:
        return info

    firstlineno = {}
    for member_name in member_names:
        lineno = _safe_firstlineno(_resolve_member(module, member_name))
        if lineno is not None:
            firstlineno[str(member_name)] = lineno
    if firstlineno:
        info["firstlineno"] = firstlineno

    return info


def collect_runtime_info():
    script_root = _safe_realpath(os.path.dirname(__file__))
    return {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "cwd": _safe_realpath(os.getcwd()),
        "python_executable": _safe_realpath(sys.executable),
        "script_root": script_root,
        "modules": {
            "marker_io": _module_runtime_info(
                ("marker_io", "fusion_api_server.marker_io"),
                fallback_path=__file__,
            ),
            "orchestrator": _module_runtime_info(
                ("orchestrator", "fusion_api_server.orchestrator"),
                fallback_path=os.path.join(script_root, "orchestrator.py"),
                member_names=("run_once",),
            ),
            "modeling": _module_runtime_info(
                ("modeling", "fusion_api_server.modeling"),
                fallback_path=os.path.join(script_root, "modeling.py"),
                member_names=(
                    "FusionApiController._require_body",
                    "FusionApiController._recover_body_from_component",
                ),
            ),
        },
    }


def write_started(run_dir, plan_path, plan_summary):
    try:
        _ensure_dir(run_dir)
        marker_path = os.path.join(run_dir, "fusion_started.json")
        data = {
            "status": "started",
            "plan_path": str(plan_path),
            "plan_summary": plan_summary,
            "runtime": collect_runtime_info(),
        }
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return marker_path
    except Exception as exc:
        print(f"[marker_io] Failed to write started marker: {exc}")
        return None


def write_done(run_dir, artifacts=None, timestamps=None):
    try:
        _ensure_dir(run_dir)
        marker_path = os.path.join(run_dir, "fusion_done.json")
        data = {
            "status": "done",
            "runtime": collect_runtime_info(),
        }
        if artifacts is not None:
            data["artifacts"] = artifacts
        if timestamps is not None:
            data["timestamps"] = timestamps
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return marker_path
    except Exception as exc:
        print(f"[marker_io] Failed to write done marker: {exc}")
        return None


def write_failed(run_dir, traceback_text):
    paths = []
    if run_dir:
        paths.append(os.path.join(str(run_dir), "fusion_failed.json"))
    paths.append(os.path.join(os.getcwd(), "fusion_failed.json"))
    paths.append(os.path.join(os.path.dirname(__file__), "fusion_failed.json"))

    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp_dir:
        paths.append(os.path.join(temp_dir, "fusion_failed.json"))

    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, "fusion_failed.json"))

    data = {
        "status": "failed",
        "traceback": traceback_text,
        "runtime": collect_runtime_info(),
    }

    for marker_path in paths:
        marker_dir = os.path.dirname(marker_path)
        if marker_dir and not os.path.exists(marker_dir):
            try:
                os.makedirs(marker_dir, exist_ok=True)
            except Exception:
                pass

    for marker_path in paths:
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return marker_path
        except Exception:
            continue
    return None


def append_warning(run_dir, warning_text):
    try:
        _ensure_dir(run_dir)
        marker_path = os.path.join(run_dir, "fusion_warnings.json")
        warnings = []
        if os.path.exists(marker_path):
            with open(marker_path, "r", encoding="utf-8") as f:
                try:
                    warnings = json.load(f)
                except Exception:
                    warnings = []
        warnings.append({"warning": warning_text})
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(warnings, f, ensure_ascii=False, indent=2)
        return marker_path
    except Exception as exc:
        print(f"[marker_io] Failed to append warning: {exc}")
        return None
