from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set

from fusion_runtime.capability_map import get_dryrun_handler




class FunctionPlanDispatcher:
    """
    Dispatcher is facts-only and never performs CAD execution.

    只负责 resolve steps、拓扑排序、生成 execution facts（JSON）。
    不接收 executor/executor_type 参数，不分支执行，不做任何 CAD/Fusion/自动执行。
    """
    def __init__(
        self,
        plan_path: Path,
        registry_path: Path | None = None,
        out_dir: Path | None = None,
        run_id: str | None = None,
        run_dir: Path | None = None,
        run_root: Path | None = None,
    ):
        self.plan_path = plan_path
        self.registry_path = registry_path or self._default_registry_path()
        self.out_dir = out_dir
        self.run_id = run_id
        self.run_dir = run_dir
        self.run_root = run_root
        self.plan: Dict[str, Any] = {}
        self.registry: Mapping[str, Any] = {}
        self.context: Dict[str, Any] = {}
        if self.run_id is not None:
            self.context.setdefault("meta.run_id", self.run_id)

    def _execution_dir(self) -> Path | None:
        """Return the execution output directory.

        - If run_root is set, outputs go to run_root/execution/.
        - Else if run_dir is set (legacy), outputs go to run_dir/.
        """

        if self.run_root is not None:
            return self.run_root / "execution"
        if self.run_dir is not None:
            return self.run_dir
        return None

    def _append_event(self, event_type: str, data: Mapping[str, Any] | None = None) -> None:
        """Append a minimal JSONL event under run_root/events.jsonl.

        Implemented locally to avoid importing entry-layer tooling.
        """

        if self.run_root is None:
            return

        self.run_root.mkdir(parents=True, exist_ok=True)
        path = self.run_root / "events.jsonl"
        record: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "data": dict(data) if data is not None else {},
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

    @staticmethod
    def _default_registry_path() -> Path:
        # Repo layout: <root>/fusion_runtime/dispatcher.py -> <root>/functions/functions.json
        return Path(__file__).resolve().parents[1] / "functions" / "functions.json"

    def load_plan(self) -> None:
        if not self.plan_path.exists():
            raise FileNotFoundError(f"Plan file not found: {self.plan_path}")

        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))

    def load_registry(self) -> None:
        if not self.registry_path.exists():
            raise FileNotFoundError(
                "Function registry not found. "
                f"Expected: {self.registry_path}. "
                "Generate it via: python -m functions.export_registry"
            )

        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(
                f"Invalid registry format in {self.registry_path}: expected a JSON object at top-level"
            )
        self.registry = raw

    def _allowed_function_names(self) -> Set[str]:
        return set(self.registry.keys())

    def validate_plan(self) -> None:
        if not self.registry:
            raise RuntimeError("Registry not loaded. Call load_registry() before validate_plan().")

        steps: List[Dict[str, Any]] = self.plan.get("steps", [])
        allowed = self._allowed_function_names()

        unknown: List[str] = []
        missing: List[str] = []
        for step in steps:
            function_name = step.get("function")
            step_id = step.get("id")

            if not function_name:
                missing.append(str(step_id))
                continue

            if isinstance(function_name, str) and function_name.startswith("DISABLED::"):
                continue

            if function_name not in allowed:
                unknown.append(f"{step_id}:{function_name}")

        if missing or unknown:
            allowed_sorted = ", ".join(sorted(allowed))
            parts: List[str] = []
            if missing:
                parts.append("Steps missing 'function': " + ", ".join(missing))
            if unknown:
                parts.append("Unknown functions: " + ", ".join(unknown))
            parts.append("Allowed functions: " + allowed_sorted)
            raise ValueError("; ".join(parts))

    def _resolve_template(self, text: str, *, step_id: str) -> Any:
        """Resolve ${var} templates within a string.

        - If the entire string is exactly "${var}", return the underlying value (preserving type).
        - If templates appear inside a larger string, substitute with str(value).
        """

        pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}")
        matches = list(pattern.finditer(text))
        if not matches:
            return text

        # Exact-variable form: preserve original type.
        if len(matches) == 1 and matches[0].span() == (0, len(text)):
            var_name = matches[0].group(1)
            if var_name not in self.context:
                raise KeyError(
                    f"Unresolved variable '{var_name}' referenced by step '{step_id}'. "
                    "Ensure a prior step captures it via 'capture.vars'."
                )
            return self.context[var_name]

        def repl(m: re.Match[str]) -> str:
            var_name = m.group(1)
            if var_name not in self.context:
                raise KeyError(
                    f"Unresolved variable '{var_name}' referenced by step '{step_id}'. "
                    "Ensure a prior step captures it via 'capture.vars'."
                )
            return str(self.context[var_name])

        return pattern.sub(repl, text)

    def _resolve_value(self, value: Any, *, step_id: str) -> Any:
        """Recursively resolve ${var} templates in JSON-like data."""

        if isinstance(value, str):
            return self._resolve_template(value, step_id=step_id)
        if isinstance(value, list):
            return [self._resolve_value(v, step_id=step_id) for v in value]
        if isinstance(value, dict):
            return {k: self._resolve_value(v, step_id=step_id) for k, v in value.items()}
        return value

    @staticmethod
    def _json_pointer_get(data: Any, pointer: str) -> Any:
        """Extract a value from a JSON-like structure using JSON Pointer (RFC 6901)."""

        if pointer == "":
            return data
        if not pointer.startswith("/"):
            raise ValueError(f"Invalid JSON Pointer: {pointer}")

        current = data
        for part in pointer.lstrip("/").split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                current = current[int(part)]
            else:
                current = current[part]
        return current

    def _capture_outputs(self, step: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        capture = step.get("capture") or {}
        vars_map = capture.get("vars") or {}
        if not isinstance(vars_map, dict):
            raise ValueError(f"Invalid capture.vars for step {step.get('id')}: expected object")

        for var_name, selector in vars_map.items():
            if not isinstance(var_name, str) or not isinstance(selector, str):
                raise ValueError(
                    f"Invalid capture mapping in step {step.get('id')}: keys/values must be strings"
                )

            if selector.startswith("/"):
                value = self._json_pointer_get(result, selector)
            else:
                value = result.get(selector)

            self.context[var_name] = value

        # Optionally provide the entire step result under a predictable name.
        if capture.get("passthrough") is True:
            step_id = str(step.get("id"))
            self.context[f"step.{step_id}.result"] = dict(result)

    @staticmethod
    def _deterministic_interface_resolution(
        *,
        component_id: str,
        interface_name: str,
        recipe: Mapping[str, Any] | None,
    ) -> Dict[str, Any]:
        recipe_payload = dict(recipe) if isinstance(recipe, Mapping) else {}
        raw = json.dumps(
            {
                "component_id": component_id,
                "interface_name": interface_name,
                "recipe": recipe_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        geometry_type = recipe_payload.get("geometry_type") if isinstance(recipe_payload.get("geometry_type"), str) else "planar"
        entity_kind = "face" if geometry_type != "axis" else "axis"
        return {
            "token_id": f"ifc:{component_id}:{interface_name}",
            "entity_kind": entity_kind,
            "entity_id": f"{entity_kind}::{component_id}::{interface_name}::{digest}",
            "geometry_summary": {
                "geometry_type": geometry_type,
                "fingerprint": digest,
            },
        }

    @staticmethod
    def _build_component_bindings(context: Mapping[str, Any]) -> List[Dict[str, Any]]:
        by_component: Dict[str, Dict[str, Any]] = {}
        for key, value in context.items():
            if not isinstance(key, str):
                continue
            if key.endswith("_component_id"):
                cid = key[: -len("_component_id")]
                row = by_component.setdefault(cid, {"component_id": cid, "occurrence_id": None, "body_id": None})
                row["component_id"] = value if isinstance(value, str) and value else cid
            elif key.endswith("_occurrence_id"):
                cid = key[: -len("_occurrence_id")]
                row = by_component.setdefault(cid, {"component_id": cid, "occurrence_id": None, "body_id": None})
                row["occurrence_id"] = value if isinstance(value, str) and value else None
            elif key.endswith("_body_id"):
                cid = key[: -len("_body_id")]
                row = by_component.setdefault(cid, {"component_id": cid, "occurrence_id": None, "body_id": None})
                row["body_id"] = value if isinstance(value, str) and value else None
        return [by_component[k] for k in sorted(by_component.keys())]

    def dispatch(self) -> None:
        metadata = self.plan.get("metadata", {})
        steps: List[Dict[str, Any]] = self.plan.get("steps", [])

        # Pre-compute how many steps will actually be executed (DISABLED steps are skipped).
        exec_step_count = 0
        for s in steps:
            fn = s.get("function")
            if isinstance(fn, str) and fn.startswith("DISABLED::"):
                continue
            exec_step_count += 1
        exec_step_index = 0

        # Validate that the plan only references known capabilities.
        self.validate_plan()

        print(f"[Dispatcher] Plan ID: {metadata.get('plan_id')}")
        print(f"[Dispatcher] Total steps: {len(steps)}")
        print("-" * 50)

        self._append_event(
            "dispatcher.start",
            {
                "plan": str(self.plan_path).replace("\\", "/"),
            },
        )

        trace: List[Dict[str, Any]] = []
        resolved_steps: List[Dict[str, Any]] = []
        resolved_interfaces: List[Dict[str, Any]] = []
        trace_path: Path | None = None
        context_path: Path | None = None
        resolved_steps_path: Path | None = None
        resolved_interfaces_path: Path | None = None
        execution_dir = self._execution_dir()
        if execution_dir is not None:
            execution_dir.mkdir(parents=True, exist_ok=True)
            trace_path = execution_dir / "execution_trace.json"
            if not trace_path.exists():
                trace_path.write_text("[]", encoding="utf-8")
            context_path = execution_dir / "context.json"
            resolved_steps_path = execution_dir / "resolved_steps.json"
            resolved_interfaces_path = execution_dir / "resolved_interfaces.json"

        for idx, step in enumerate(steps, start=1):
            step_id = step.get("id")
            function_name = step.get("function")
            depends_on = step.get("depends_on", [])


            # Per-step metadata
            if self.run_id is not None:
                self.context["meta.run_id"] = self.run_id
            self.context["meta.step_index"] = idx
            self.context["meta.step_count"] = len(steps)
            if step_id is not None:
                self.context["meta.step_id"] = str(step_id)

            raw_inputs = step.get("inputs", {})

            is_disabled = isinstance(function_name, str) and function_name.startswith("DISABLED::")
            if is_disabled:
                resolved_inputs = raw_inputs
            else:
                exec_step_index += 1
                self.context["meta.exec_step_index"] = exec_step_index
                self.context["meta.exec_step_count"] = exec_step_count
                resolved_inputs = self._resolve_value(raw_inputs, step_id=str(step_id))

            print(f"[Step {idx}] id={step_id}")
            print(f"  function    : {function_name}")
            if depends_on:
                print(f"  depends_on  : {depends_on}")


            if is_disabled:
                print("  status      : DISABLED (skipped)")
                result: Dict[str, Any] = {
                    "run_id": self.run_id,
                    "step_id": str(step_id),
                    "function_name": str(function_name),
                    "inputs": resolved_inputs,
                    "outputs": None,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "status": "DISABLED",
                }
                trace.append(result)
                resolved_steps.append(
                    {
                        "step_id": str(step_id),
                        "function_name": str(function_name),
                        "resolved_inputs": resolved_inputs,
                        "outputs": None,
                        "status": "DISABLED",
                    }
                )
                if trace_path is not None:
                    try:
                        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                continue

            fabricated: Dict[str, Any] = {}
            if isinstance(function_name, str):
                handler = get_dryrun_handler(function_name)
                if handler is not None:
                    try:
                        payload = handler(
                            resolved_inputs if isinstance(resolved_inputs, Mapping) else {},
                            step,
                            self.registry,
                            self.context,
                        )
                        if isinstance(payload, Mapping):
                            fabricated = dict(payload)
                    except Exception:
                        fabricated = {}

            # facts-only: 不做任何 CAD 执行，仅记录可复现 dryrun outputs
            result = dict(fabricated)
            result["inputs"] = resolved_inputs
            result["status"] = "RESOLVED"
            self._capture_outputs(step, result)

            if function_name == "RESOLVE_INTERFACE" and isinstance(resolved_inputs, dict):
                component_id = resolved_inputs.get("component_id")
                interface_name = resolved_inputs.get("interface_name")
                if isinstance(component_id, str) and isinstance(interface_name, str):
                    resolved = {
                        "token_id": result.get("token_id"),
                        "entity_kind": result.get("entity_kind"),
                        "entity_id": result.get("entity_id"),
                        "geometry_summary": result.get("geometry_summary"),
                    }
                    if not (isinstance(resolved.get("token_id"), str) and isinstance(resolved.get("entity_id"), str)):
                        resolved = self._deterministic_interface_resolution(
                            component_id=component_id,
                            interface_name=interface_name,
                            recipe=(resolved_inputs.get("recipe") if isinstance(resolved_inputs.get("recipe"), dict) else None),
                        )
                    resolved_interfaces.append(
                        {
                            "component_id": component_id,
                            "interface_name": interface_name,
                            "token_id": resolved.get("token_id"),
                            "entity_kind": resolved.get("entity_kind"),
                            "entity_id": resolved.get("entity_id"),
                            "geometry_summary": resolved.get("geometry_summary"),
                            "status": "resolved",
                        }
                    )

            resolved_steps.append(
                {
                    "step_id": step_id,
                    "function_name": str(function_name),
                    "resolved_inputs": resolved_inputs,
                    "outputs": result,
                }
            )

            # 只记录 execution facts，不做任何 CAD 执行
            if trace_path is not None and self.run_id is not None:
                trace.append(
                    {
                        "run_id": self.run_id,
                        "step_id": step_id,
                        "function_name": str(function_name),
                        "inputs": resolved_inputs,
                        "outputs": result,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                trace_path.write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )

            print(f"  status      : RESOLVED (facts-only)")
            if resolved_inputs:
                print(f"  inputs      : {resolved_inputs}")
            if result:
                print(f"  outputs     : {result}")
            print("-" * 50)

        if context_path is not None:
            context_payload: Dict[str, Any] = dict(self.context)
            context_payload["component_bindings"] = self._build_component_bindings(self.context)
            context_path.write_text(
                json.dumps(context_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

        if resolved_steps_path is not None:
            resolved_steps_path.write_text(
                json.dumps(resolved_steps, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

        if resolved_interfaces_path is not None:
            resolved_interfaces_path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "schema_version": "1.0",
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "source": "dispatcher",
                        },
                        "interfaces": resolved_interfaces,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )

        if self.run_root is not None:
            try:
                missing_items: List[Dict[str, Any]] = []
                for item in resolved_steps:
                    if not isinstance(item, dict):
                        continue
                    fn = item.get("function_name")
                    if fn not in {"INSERT_FASTENER_R1", "INSERT_BEARING_R1"}:
                        continue
                    outputs = item.get("outputs")
                    if not isinstance(outputs, dict):
                        continue
                    if str(outputs.get("status") or "").strip().lower() != "library_missing":
                        continue
                    resolved_inputs = item.get("resolved_inputs")
                    payload = {
                        "step_id": item.get("step_id"),
                        "function_name": fn,
                        "component_name": (
                            resolved_inputs.get("component_name")
                            if isinstance(resolved_inputs, dict)
                            else None
                        ),
                        "required_spec": {
                            "kind": resolved_inputs.get("kind") if isinstance(resolved_inputs, dict) else None,
                            "designation": resolved_inputs.get("designation") if isinstance(resolved_inputs, dict) else None,
                            "standard": resolved_inputs.get("standard") if isinstance(resolved_inputs, dict) else None,
                            "size": resolved_inputs.get("size") if isinstance(resolved_inputs, dict) else None,
                            "length_mm": resolved_inputs.get("length_mm") if isinstance(resolved_inputs, dict) else None,
                            "inner_diameter_mm": resolved_inputs.get("inner_diameter_mm") if isinstance(resolved_inputs, dict) else None,
                            "outer_diameter_mm": resolved_inputs.get("outer_diameter_mm") if isinstance(resolved_inputs, dict) else None,
                            "width_mm": resolved_inputs.get("width_mm") if isinstance(resolved_inputs, dict) else None,
                        },
                        "message": outputs.get("message"),
                    }
                    missing_items.append(payload)

                if missing_items:
                    planning_dir = self.run_root / "planning"
                    planning_dir.mkdir(parents=True, exist_ok=True)
                    report_path = planning_dir / "library_missing_report.json"
                    report_path.write_text(
                        json.dumps(
                            {
                                "metadata": {
                                    "schema_version": "1.0",
                                    "created_at": datetime.now().isoformat(timespec="seconds"),
                                    "source": "dispatcher",
                                },
                                "missing": missing_items,
                            },
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        ),
                        encoding="utf-8",
                    )
            except Exception:
                pass


        # 不再有任何 finalize 或自动执行逻辑

        self._append_event(
            "dispatcher.end",
            {
                "outputs": [
                    "execution/context.json",
                    "execution/resolved_steps.json",
                    "execution/execution_trace.json",
                    "execution/resolved_interfaces.json",
                ]
            },
        )



# 已彻底移除所有 executor 选择与自动执行分支，仅支持 dryrun
