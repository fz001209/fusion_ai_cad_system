from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .capability_map import get_dryrun_handler
from .executor_base import ExecutorBase


def _declared_output_keys(registry: Mapping[str, Any], function_name: str) -> Iterable[str]:
    spec = registry.get(function_name, {})
    if not isinstance(spec, dict):
        return []

    outputs = spec.get("outputs")
    if not isinstance(outputs, dict):
        return []

    # New contract format: outputs is an object schema with a 'properties' map.
    properties = outputs.get("properties")
    if isinstance(properties, dict):
        return properties.keys()

    # Backward compatibility: outputs is a flat mapping of name -> description.
    return outputs.keys()


@dataclass(frozen=True, slots=True)
class DryRunExecutor(ExecutorBase):

        # 只做 dryrun 规划，不做任何 CAD/Fusion/自动执行相关操作。

    def execute(
        self,
        *,
        function_name: str,
        inputs: Mapping[str, Any],
        step: Mapping[str, Any],
        registry: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        output_keys = list(_declared_output_keys(registry, function_name))

        handler = get_dryrun_handler(function_name)
        fabricated = handler(inputs, step, registry, context) if handler is not None else {}

        if output_keys:
            return {k: fabricated.get(k) for k in output_keys}
        return fabricated
