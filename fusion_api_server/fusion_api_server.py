import importlib
import os
import sys
import traceback
from pathlib import Path

import adsk.core
import adsk.fusion


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

app = adsk.core.Application.get()
ui = app.userInterface


def run(_context: str):
    """Fusion script entrypoint."""

    marker_io_mod = None

    try:
        app.log("fusion_api_server: run() started")
        lib_root = os.getenv("FUSION_PART_LIBRARY_ROOT", "").strip()
        if lib_root:
            app.log(f"fusion_api_server: FUSION_PART_LIBRARY_ROOT={lib_root}")
        else:
            default_root = (Path(__file__).resolve().parent.parent / "part_library").resolve()
            app.log(
                "fusion_api_server: [WARN] FUSION_PART_LIBRARY_ROOT is not set; "
                f"using default relative path {default_root}"
            )

        # Fusion keeps Python modules cached within the host process. Reload the
        # whole execution chain so every rerun picks up local edits.
        run_once = None
        for module_name in ("marker_io", "plan_io", "postprocess", "orchestrator"):
            module = importlib.import_module(module_name)
            module = importlib.reload(module)
            if module_name == "marker_io":
                marker_io_mod = module
            elif module_name == "orchestrator":
                run_once = getattr(module, "run_once", None)

        if not callable(run_once):
            raise RuntimeError("orchestrator.run_once is unavailable")

        run_once(app, ui)
        app.log("fusion_api_server: run() finished")

    except Exception as e:
        tb = traceback.format_exc()
        app.log(tb)

        try:
            if marker_io_mod is None:
                marker_io_mod = importlib.reload(importlib.import_module("marker_io"))
            failed_path = marker_io_mod.write_failed(None, tb)
            if failed_path:
                ui.messageBox(f"Script execution failed: {str(e)}\nSee {failed_path}")
            else:
                ui.messageBox(f"Script execution failed: {str(e)}\nCould not write fusion_failed.json")
        except Exception:
            ui.messageBox(f"Script execution failed: {str(e)}\n(Error log could not be written)")
