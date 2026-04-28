from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping



class ExecutorBase(ABC):
	"""执行后端的抽象基类，仅用于 dryrun 规划链路。

	不包含任何 CAD/Fusion/自动执行相关接口。
	"""

	@abstractmethod
	def execute(
		self,
		*,
		function_name: str,
		inputs: Mapping[str, Any],
		step: Mapping[str, Any],
		registry: Mapping[str, Any],
		context: Mapping[str, Any],
	) -> Mapping[str, Any]:
		"""Execute one plan step and return a JSON-serializable result object.

		The returned mapping is used for `capture` (variable extraction) by the dispatcher.
		"""

		raise NotImplementedError
