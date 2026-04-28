from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def assert_llm_decision_has_no_api_instructions(
    decision: Any,
    *,
    forbidden_function_names: Sequence[str] | None = None,
) -> None:
    """Assert an LLM-produced decision contains no API-level instructions.

    This is a safety guardrail for *LLM-produced* decision objects used to guide
    planning. It must ensure the LLM output does NOT:
    - include any CAD API / executor function names (e.g., CREATE_COMPONENT)
    - include low-level API instructions (e.g., "call EXTRUDE_NEW_BODY")

    The goal is to keep LLM decisions at the *intent/strategy* level.

    Notes:
    - This function is deterministic and performs a conservative scan.
    - Call sites should only invoke it on decisions that actually come from an LLM.
    """

    forbidden: set[str] = set()
    if forbidden_function_names is not None:
        for x in forbidden_function_names:
            if isinstance(x, str) and x.strip():
                forbidden.add(x.strip())

    offenders: List[Dict[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                kk = str(k)
                walk(v, f"{path}.{kk}" if path else kk)
            return
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
            return
        if isinstance(obj, str):
            s = obj
            tokens = _TOKEN_RE.findall(s)

            # 1) Exact forbidden function names.
            hit = sorted({t for t in tokens if t in forbidden})
            if hit:
                offenders.append(
                    {
                        "path": path,
                        "kind": "function_name",
                        "tokens": hit,
                        "text_excerpt": s[:200],
                    }
                )

            # 2) Conservative heuristic: ALLCAPS_WITH_UNDERSCORES usually indicate API functions.
            # Allow a few common acronyms.
            allow_acronyms = {"JSON", "LLM", "MLLM", "CAD", "API"}
            suspicious = []
            for t in tokens:
                if t in allow_acronyms:
                    continue
                if "_" in t and t.upper() == t and len(t) >= 5:
                    suspicious.append(t)
            if suspicious:
                offenders.append(
                    {
                        "path": path,
                        "kind": "api_like_token",
                        "tokens": sorted(set(suspicious))[:20],
                        "text_excerpt": s[:200],
                    }
                )

            # 3) Known API instruction fragments.
            lowered = s.lower()
            api_fragments = [
                "adsk.",
                "fusionapi",
                "executor",
                "function_name",
                "inputs",
                "outputs",
                "call ",
                "invoke ",
            ]
            if any(frag in lowered for frag in api_fragments):
                offenders.append(
                    {
                        "path": path,
                        "kind": "api_instruction_fragment",
                        "text_excerpt": s[:200],
                    }
                )
            return

    walk(decision, path="")

    if offenders:
        raise AssertionError(
            "LLM decision contains API-level instructions/function names; "
            f"offenders={offenders[:10]}"
        )


def assert_llm_decision_is_high_level_only(
    decision: Any,
    *,
    forbidden_function_names: Sequence[str] | None = None,
    forbidden_api_terms: Sequence[str] | None = None,
) -> None:
    """Stricter guardrail for LLM-produced decisions.

    Asserts:
    - No field contains CAD API function names
    - No field contains step ids (e.g., create_seat, extrude_leg_1, attach_x)
    - No field contains API terms (extrude/sketch/mate/etc.)

    This is intentionally conservative.
    """

    # 1) Reuse existing conservative checks.
    assert_llm_decision_has_no_api_instructions(
        decision,
        forbidden_function_names=forbidden_function_names,
    )

    forbidden_terms: List[str] = []
    if forbidden_api_terms is not None:
        for t in forbidden_api_terms:
            if isinstance(t, str) and t.strip():
                forbidden_terms.append(t.strip().lower())

    # Common API-ish terms (lowercased). Keep this list small and obvious.
    default_terms = [
        "extrude",
        "sketch",
        "mate",
        "loft",
        "fillet",
        "chamfer",
        "revolve",
        "sweep",
        "boolean",
        "join",
        "cut",
    ]
    for t in default_terms:
        if t not in forbidden_terms:
            forbidden_terms.append(t)

    # Step-id patterns from our planner conventions.
    step_id_re = re.compile(r"\b(create|sketch|rect|circle|extrude|attach)_[A-Za-z0-9_]+\b", re.IGNORECASE)

    offenders: List[Dict[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                # Check keys too (they are "fields").
                kk = str(k)
                walk(kk, f"{path}.{kk}" if path else kk)
                walk(v, f"{path}.{kk}" if path else kk)
            return
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
            return
        if isinstance(obj, str):
            s = obj
            sl = s.lower()

            m = step_id_re.search(s)
            if m:
                offenders.append(
                    {
                        "path": path,
                        "kind": "step_id",
                        "match": m.group(0),
                        "text_excerpt": s[:200],
                    }
                )

            for term in forbidden_terms:
                if term and term in sl:
                    offenders.append(
                        {
                            "path": path,
                            "kind": "api_term",
                            "term": term,
                            "text_excerpt": s[:200],
                        }
                    )
            return

    walk(decision, path="")

    if offenders:
        raise AssertionError(
            "LLM decision must be high-level only (no step ids / API terms); "
            f"offenders={offenders[:10]}"
        )
