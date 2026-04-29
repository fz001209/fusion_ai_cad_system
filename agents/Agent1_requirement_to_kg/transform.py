"""Agent1 requirement-to-knowledge-graph entrypoint.

This module is intentionally thin:
- input_prompt.py builds the LLM prompt and reads local environment config.
- postprocess.py defines ordered normalization/repair pipelines.
- grouped modules implement component, connection, and wheel-domain rules.

The public imports from this module are kept compatible with older tests and
pipeline code; implementation lives in the feature-specific modules.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping

from jsonschema import Draft202012Validator
from agents.common_utils import extract_json_from_llm_response

from agents.Agent1_requirement_to_kg.module_wiring import wire_agent1_modules
from agents.Agent1_requirement_to_kg.postprocess import (
    run_llm_postprocess_pipeline,
    run_structured_postprocess_pipeline,
)

globals().update(wire_agent1_modules())


def _call_llm_to_generate_kg(requirement_text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Call the configured LLM and return a validated raw Agent1 KG."""
    _load_repo_env()

    def _subassembly_of(payload: Dict[str, Any], comp_id: str) -> str | None:
        """Return the parent subassembly ID if this component is a member of one."""
        subassemblies = payload.get("subassemblies", [])
        if not isinstance(subassemblies, list):
            return None
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                continue
            sa_id = sa.get("id")
            members = sa.get("component_ids", [])
            if isinstance(sa_id, str) and isinstance(members, list) and comp_id in members:
                return sa_id
        # Also check parent_id in component itself
        components = payload.get("components", [])
        if isinstance(components, list):
            for comp in components:
                if isinstance(comp, Mapping) and comp.get("id") == comp_id:
                    parent_id = comp.get("parent_id")
                    if isinstance(parent_id, str):
                        return parent_id
        return None

    def _connected_components(payload: Dict[str, Any], comp_id: str) -> set[str]:
        """Return all component IDs that share a connection_requirement with comp_id."""
        result: set[str] = set()
        crs = payload.get("connection_requirements", [])
        if isinstance(crs, list):
            for cr in crs:
                if isinstance(cr, Mapping):
                    between = cr.get("between", [])
                    if isinstance(between, list) and comp_id in between:
                        for other_id in between:
                            if isinstance(other_id, str) and other_id != comp_id:
                                result.add(other_id)
        return result

    def _type_by_id(payload: Dict[str, Any]) -> dict[str, str]:
        """Build component type mapping."""
        result: dict[str, str] = {}
        components = payload.get("components", [])
        if isinstance(components, list):
            for comp in components:
                if isinstance(comp, Mapping):
                    comp_id = comp.get("id")
                    comp_type = comp.get("type")
                    if isinstance(comp_id, str) and isinstance(comp_type, str):
                        result[comp_id] = comp_type
        return result

    def _is_structural_type(ctype: str) -> bool:
        """Check if a component type represents structural/main body components."""
        structural_tokens = {
            "frame", "base", "housing", "mount", "bracket", "carrier",
            "hub", "structure", "plate", "chassis", "block", "body"
        }
        return any(token in ctype.lower() for token in structural_tokens)

    def _choose_structural_host(payload: Dict[str, Any], subject_id: str, candidates: list[str]) -> str | None:
        """
        Select the best structural host for a component using topology-based scoring.
        
        Scoring rules (deterministic, ties broken by component ID lexicographically):
        - Subassembly membership: +3 (same subassembly as subject)
        - Structural type: +2 (is_structural_type)
        - Already connected: +2 (shares existing CR with subject)
        - Fastener penalty: -5 (never select fastener)
        - Wheel penalty: -3 (rotary, avoid as structural host)
        
        Returns: Best scoring candidate, or None if all candidates are disqualified.
        """
        type_map = _type_by_id(payload)
        subject_sa = _subassembly_of(payload, subject_id)
        connected = _connected_components(payload, subject_id)
        
        scored: list[tuple[int, str]] = []
        for cand_id in candidates:
            if cand_id == subject_id:
                continue  # Skip self
            
            ctype = type_map.get(cand_id, "")
            
            # Disqualify fasteners and wheels
            if ctype == "fastener":
                continue
            if ctype == "wheel":
                continue
            
            score = 0
            
            # Scoring
            if subject_sa and _subassembly_of(payload, cand_id) == subject_sa:
                score += 3
            if _is_structural_type(ctype):
                score += 2
            if cand_id in connected:
                score += 2
            
            scored.append((score, cand_id))
        
        if not scored:
            return None
        
        # Sort by: (score desc, id asc) for deterministic tie-breaking
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    def _cleanup_auto_generated_connections(payload: Dict[str, Any]) -> None:
        """
        Remove all previously auto-generated connection requirements.
        This ensures deterministic completion uses latest logic without contamination from old runs.
        """
        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return
        
        # Remove all CRs with "_auto" in their ID
        cleaned_crs = [
            cr for cr in crs
            if not (isinstance(cr, dict) and isinstance(cr.get("id"), str) and "_auto" in cr.get("id"))
        ]
        
        removed_count = len(crs) - len(cleaned_crs)
        if removed_count > 0:
            payload["connection_requirements"] = cleaned_crs

    def _strip_location_intent(payload: Dict[str, Any]) -> None:
        """Remove location_intent from Agent1 output (placement intent is inferred by Agent2)."""
        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return
        for cr in crs:
            if isinstance(cr, dict) and "location_intent" in cr:
                cr.pop("location_intent", None)



    def _enrich_connection_semantics_with_llm(payload: Dict[str, Any]) -> None:
        components = payload.get("components", [])
        crs = payload.get("connection_requirements", [])
        if not isinstance(components, list) or not isinstance(crs, list):
            return

        components_by_id = {
            comp.get("id"): comp
            for comp in components
            if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
        }
        unresolved: list[dict[str, Any]] = []
        valid_ids_by_connection: dict[str, set[str]] = {}
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            purpose = cr.get("purpose") if isinstance(cr.get("purpose"), str) else None
            decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else None
            if not (_purpose_requires_explicit_connection_semantics(purpose) or isinstance(decision, Mapping)):
                continue
            between = cr.get("between")
            between_ids = [cid for cid in between if isinstance(cid, str) and cid] if isinstance(between, list) else []
            if _sanitize_connection_semantics_contract(
                cr.get("connection_semantics"),
                valid_component_ids=set(between_ids),
            ) is not None:
                continue
            cr_id = cr.get("id") if isinstance(cr.get("id"), str) else None
            if not cr_id:
                continue
            unresolved.append(
                {
                    "connection_id": cr_id,
                    "between": between_ids,
                    "purpose": purpose,
                    "roles": cr.get("roles"),
                    "constraint_intent": cr.get("constraint_intent"),
                    "dof": cr.get("dof"),
                    "mating_features": cr.get("mating_features"),
                    "connection_decision": decision,
                    "component_info": [
                        {
                            "id": cid,
                            "type": (components_by_id.get(cid) or {}).get("type"),
                            "shape_semantics": (components_by_id.get(cid) or {}).get("shape_semantics"),
                            "dimensions": (components_by_id.get(cid) or {}).get("dimensions"),
                        }
                        for cid in between_ids
                    ],
                }
            )
            valid_ids_by_connection[cr_id] = set(between_ids)
        if not unresolved:
            return

        audit: Dict[str, Any] = {
            "requested_connection_ids": [entry["connection_id"] for entry in unresolved],
            "batch_size": 6,
        }
        unresolved_by_id = {entry["connection_id"]: entry for entry in unresolved}

        def _extract_items(obj: Any) -> list[dict[str, Any]]:
            if isinstance(obj, Mapping):
                for key in ("connection_semantics", "items", "connections"):
                    value = obj.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, Mapping)]
                return []
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, Mapping)]
            return []

        def _request_json_object(prompt_text: str) -> Any:
            content_local = _request_llm(prompt_text)
            try:
                return json.loads(content_local)
            except json.JSONDecodeError:
                match = re.search(r"(\{.*\}|\[.*\])", content_local, flags=re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                raise

        canonical_anchor_guidance = (
            "Anchor objects MUST be JSON objects, never bare strings.\n"
            "Allowed reference_anchor kinds: component_center, distal_end, proximal_end, radial_mount_perimeter, axial_face_perimeter_max, axial_face_perimeter_min.\n"
            "Allowed moving_anchor kinds: component_center, distal_end, proximal_end, proximal_mount_face_min, proximal_mount_face_max.\n"
            "Examples:\n"
            "- Wheel rotating on axle: reference_anchor {\"kind\": \"component_center\"}, moving_anchor {\"kind\": \"component_center\"}, interface hints bore_axis / bore_axis, orientation_policy free.\n"
            "- Arm supporting an axle at its outer end: reference_anchor {\"kind\": \"distal_end\", \"axis\": \"x\"}, moving_anchor {\"kind\": \"component_center\"}, interface hints distal_mount_face / bore_axis.\n"
            "- Hub bolted to an arm root: reference_anchor {\"kind\": \"axial_face_perimeter_max\"}, moving_anchor {\"kind\": \"proximal_mount_face_min\", \"axis\": \"x\"}, interface hints axial_end_face_max / proximal_mount_face_min.\n"
            "- Tire fixed to rim: connection_mechanism bonded_tread or press_fit; anchors {\"kind\": \"component_center\"} on both sides; never a bolted hole through the tire.\n"
            "Mechanical grounding rules:\n"
            "- For hub-to-arm fastening, use the arm proximal mount, never the arm distal end or center.\n"
            "- For arm-to-axle support, use the arm distal end / distal mount face.\n"
            "- For wheel or hub rotation about an axle, use bore_axis interface hints with component_center anchors.\n"
            "- For tire-to-rim fixation, choose bonded_tread or press_fit, not bolted_mount.\n"
            "geometric_semantics guidance:\n"
            "- geometric_semantics MUST include contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when using an array.\n"
            "- Hub bolted to an arm root with one screw: geometric_semantics {\"contact_model\": \"opposed_planar_clamp\", \"reference_feature_strategy\": \"threaded_hole\", \"moving_feature_strategy\": \"clearance_hole\", \"pattern_policy\": \"single\", \"hardware_layout\": \"thread_in_hub_bolt_head_on_arm\", \"retention_strategy\": \"threaded_clamp\"}.\n"
            "- Arm supporting an axle: geometric_semantics {\"contact_model\": \"shaft_in_bore_support\", \"reference_feature_strategy\": \"plain_bore\", \"moving_feature_strategy\": \"plain_shaft\", \"pattern_policy\": \"none\", \"retention_strategy\": \"coaxial_support\"}.\n"
            "- Tire fixed to rim: geometric_semantics {\"contact_model\": \"bonded_wrap\", \"reference_feature_strategy\": \"retention_groove\", \"moving_feature_strategy\": \"bonding_zone\", \"pattern_policy\": \"none\", \"retention_strategy\": \"bonded_or_press_fit\"}.\n"
            "- Never infer hole count from fastener bundle quantity; pattern_policy and pattern_count must state it explicitly.\n"
        )

        canonicalized_ids: set[str] = set()

        def _canonicalize_candidate_with_llm(connection_id: str, raw_candidate: Mapping[str, Any]) -> Dict[str, Any] | None:
            entry = unresolved_by_id.get(connection_id)
            if not isinstance(entry, Mapping):
                return None
            prompt_text = (
                "You are Agent1's connection semantics canonicalization layer.\n"
                "The prior candidate captured some mechanical intent but failed the frozen schema.\n"
                "Preserve the intended mechanism and participating components whenever possible.\n"
                "Only repair invalid anchor formatting, invalid anchor kinds, generic interface placeholders, under-specified relation_type/geometric_semantics, or clearly wrong proximal/distal arm-side anchor selection.\n"
                "Do NOT invent coordinates. Do NOT modify unrelated fields.\n\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n\n"
                + "TARGET_CONNECTION_ID: " + json.dumps(connection_id, ensure_ascii=False) + "\n"
                + "ALLOWED_COMPONENT_IDS: " + json.dumps(sorted(valid_ids_by_connection[connection_id]), ensure_ascii=False) + "\n"
                + "ORIGINAL_CONNECTION: " + json.dumps(entry, ensure_ascii=False) + "\n"
                + "FAILED_CANDIDATE: " + json.dumps(raw_candidate, ensure_ascii=False)
            )
            try:
                repaired_obj = _request_json_object(prompt_text)
            except Exception:
                return None
            for repaired_item in _extract_items(repaired_obj):
                candidate_id = repaired_item.get("connection_id") if isinstance(repaired_item.get("connection_id"), str) else None
                if candidate_id != connection_id:
                    continue
                repaired_raw = repaired_item.get("connection_semantics") if isinstance(repaired_item.get("connection_semantics"), Mapping) else repaired_item
                semantics = _sanitize_connection_semantics_contract(
                    repaired_raw,
                    valid_component_ids=valid_ids_by_connection[connection_id],
                )
                if isinstance(semantics, dict):
                    canonicalized_ids.add(connection_id)
                    return semantics
            return None

        def _apply_items(items: list[dict[str, Any]], *, allow_repair: bool = True) -> dict[str, dict[str, Any]]:
            applied: dict[str, dict[str, Any]] = {}
            for item in items:
                connection_id = item.get("connection_id") if isinstance(item.get("connection_id"), str) else None
                if not connection_id or connection_id not in valid_ids_by_connection:
                    continue
                raw_semantics = item.get("connection_semantics") if isinstance(item.get("connection_semantics"), Mapping) else item
                semantics = _sanitize_connection_semantics_contract(
                    raw_semantics,
                    valid_component_ids=valid_ids_by_connection[connection_id],
                )
                if semantics is None and allow_repair and isinstance(raw_semantics, Mapping):
                    semantics = _canonicalize_candidate_with_llm(connection_id, raw_semantics)
                if isinstance(semantics, dict):
                    applied[connection_id] = semantics
            return applied

        semantics_by_id: dict[str, dict[str, Any]] = {}
        batch_size = 6
        for start in range(0, len(unresolved), batch_size):
            batch = unresolved[start:start + batch_size]
            batch_ids = [entry["connection_id"] for entry in batch]
            prompt_contract = (
                "You are Agent1's connection semantics completion layer.\n"
                "Complete frozen connection_semantics for each listed mechanically resolved connection_requirement.\n"
                "These semantics are authoritative for downstream execution. Do NOT invent coordinates. Do NOT modify any existing field outside connection_semantics.\n\n"
                "For EACH listed connection_id you MUST return: connection_mechanism, relation_type, reference_component_id, moving_component_id, reference_anchor, moving_anchor, reference_interface_hint, moving_interface_hint, orientation_policy, geometric_semantics, rationale.\n"
                "connection_mechanism MUST be one of: bolted_mount, radial_member_bolted_mount, axial_face_bolted_mount, axial_stack_locator, bonded_tread, bonded_mount, press_fit, shaft_bore_fit, companion_rotation_relation, welded_mount. generic_mount is forbidden.\n"
                "reference_interface_hint and moving_interface_hint MUST be concrete interface names such as axial_end_face_max, radial_outer_face, bore_axis, bottom_face, side_face_x_min, distal_mount_face.\n"
                "geometric_semantics MUST include contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when pattern_policy implies an array.\n"
                "For structural support or fixation that must avoid interference, geometric_semantics MUST also make support_topology, mount_side, clearance_policy, and requires_axial_offset explicit.\n"
                "relation_type MUST be a concrete geometric relation such as shaft_axis_to_bore, axial_face_single_bolt_mount, radial_member_distal_support; generic values like fastening/fixation/support/rotation are forbidden.\n"
                "Forbidden interface hints: fixation_req, mounting_req, mounting_req_drill_anchor, support_req, generic_interface, unspecified.\n"
                "For hub-to-arm structural fixation on a rotating carrier, single_station_bolted_mount is forbidden unless the contract explicitly describes anti-rotation geometry. Prefer an axial face perimeter mount with a planar root pad when the arm roots mount to a hub face.\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n"
                "Do not omit any connection_id from the batch.\n\n"
                + "BATCH_CONNECTION_IDS: " + json.dumps(batch_ids, ensure_ascii=False) + "\n"
                + "UNRESOLVED_CONNECTIONS: " + json.dumps(batch, ensure_ascii=False)
            )

            obj = _request_json_object(prompt_contract)
            semantics_by_id.update(_apply_items(_extract_items(obj)))

            missing_batch = [cid for cid in batch_ids if cid not in semantics_by_id]
            if missing_batch:
                repair_prompt = (
                    prompt_contract
                    + "\n\nCORRECTION REQUIRED:\n"
                    + "You omitted or malformed these connection_ids: "
                    + json.dumps(missing_batch, ensure_ascii=False)
                    + "\nReturn corrected JSON only."
                )
                repair_obj = _request_json_object(repair_prompt)
                semantics_by_id.update(_apply_items(_extract_items(repair_obj)))

        still_missing = [entry for entry in unresolved if entry["connection_id"] not in semantics_by_id]
        audit["missing_after_batch"] = [entry["connection_id"] for entry in still_missing]
        for entry in still_missing:
            single_prompt = (
                "You are Agent1's connection semantics completion layer.\n"
                "Return frozen connection_semantics for exactly one mechanically resolved connection_requirement.\n"
                "These semantics are authoritative for downstream execution. Do NOT invent coordinates. Do NOT modify fields outside connection_semantics.\n\n"
                + canonical_anchor_guidance
                + "Return JSON only in the form: {\"connection_semantics\": [{\"connection_id\": \"...\", \"connection_semantics\": {...}}]}.\n"
                "generic_mount is forbidden. Generic interface hints are forbidden.\n\n"
                + "TARGET_CONNECTION_ID: " + json.dumps(entry["connection_id"], ensure_ascii=False) + "\n"
                + "UNRESOLVED_CONNECTION: " + json.dumps(entry, ensure_ascii=False)
            )

            try:
                single_obj = _request_json_object(single_prompt)
            except Exception:
                continue
            semantics_by_id.update(_apply_items(_extract_items(single_obj)))

        for cr in crs:
            if not isinstance(cr, dict):
                continue
            cr_id = cr.get("id")
            if isinstance(cr_id, str) and cr_id in semantics_by_id:
                cr["connection_semantics"] = semantics_by_id[cr_id]
        audit["resolved_connection_ids"] = sorted(semantics_by_id)
        audit["canonicalized_connection_ids"] = sorted(canonicalized_ids)
        audit["missing_after_single"] = sorted(
            entry["connection_id"] for entry in unresolved if entry["connection_id"] not in semantics_by_id
        )
        payload["agent1_connection_semantics_audit"] = audit


    def _ensure_no_isolated_structural_components(payload: Dict[str, Any]) -> None:
        """Ensure no structural components appear in zero connection_requirements."""
        components = payload.get("components", [])
        if not isinstance(components, list):
            return

        crs = payload.get("connection_requirements", [])
        if not isinstance(crs, list):
            return

        type_map = _type_by_id(payload)
        
        # Find all structural components
        structural_ids = [
            cid for cid, ctype in type_map.items()
            if _is_structural_type(ctype)
        ]
        if not structural_ids:
            return
        
        # Find structural components that appear in zero CRs
        cid_in_cr: set[str] = set()
        for cr in crs:
            if isinstance(cr, Mapping):
                between = cr.get("between", [])
                if isinstance(between, list):
                    cid_in_cr.update(cid for cid in between if isinstance(cid, str))
        
        isolated = [cid for cid in structural_ids if cid not in cid_in_cr]
        if not isolated:
            return
        
        # For each isolated structural component, find a host and add connection
        existing_ids = {
            cr.get("id")
            for cr in crs
            if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
        }

        def _next_id(prefix: str) -> str:
            idx = 1
            candidate = f"{prefix}_{idx}"
            while candidate in existing_ids:
                idx += 1
                candidate = f"{prefix}_{idx}"
            existing_ids.add(candidate)
            return candidate
        
        for comp_id in isolated:
            # Find best host among OTHER structural components
            host_candidates = [cid for cid in structural_ids if cid != comp_id]
            if not host_candidates:
                continue
            
            host = _choose_structural_host(payload, comp_id, host_candidates)
            if not host:
                # Fallback: pick the first other structural component (deterministic)
                host = sorted(host_candidates)[0]
            
            crs.append({
                "id": _next_id(f"{comp_id}_isolated_fixation_auto"),
                "between": [comp_id, host],
                "purpose": "structural_fixation",
                "description": "Deterministic isolated structural component fixation",
            })


    # Read LLM client settings from the environment.
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8000"))
    response_format_mode = os.getenv("OPENAI_RESPONSE_FORMAT", "auto").strip().lower()
    
    if not api_key:
        raise ValueError(
            "LLM not configured. Set OPENAI_API_KEY environment variable to enable "
            "natural language requirement understanding. "
            "Alternatively, provide requirements in structured knowledge graph format."
        )
    
    # Import OpenAI lazily so the module remains importable without the package.
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    prompt = build_requirement_to_kg_prompt(requirement_text)

    def _json_mode_enabled() -> bool:
        if response_format_mode in {"0", "false", "off", "none", "text"}:
            return False
        if response_format_mode in {"1", "true", "on", "json", "json_object"}:
            return True
        # Mistral's OpenAI-compatible chat endpoint supports JSON mode, but it
        # does not reliably obey a prompt-only JSON instruction on long outputs.
        return "mistral.ai" in base_url.lower()

    def _request_llm(prompt_text: str) -> str:
        request_args: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if _json_mode_enabled():
            request_args["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**request_args)
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            raise ValueError(
                "LLM output was truncated before valid JSON completed. "
                "Increase OPENAI_MAX_TOKENS or use a model with a larger output limit."
            )
        return (choice.message.content or "").strip()

    last_error: Exception | None = None
    prompt_to_use = prompt
    content: str = ""
    for attempt in range(2):
        try:
            content = _request_llm(prompt_to_use)
            kg = extract_json_from_llm_response(content)
            if kg is None:
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix="_invalid.json", delete=False, encoding="utf-8"
                ) as f:
                    f.write(content)
                    error_file = f.name
                raise ValueError(
                    "LLM generated invalid JSON payload. "
                    f"Invalid JSON saved to: {error_file}\n"
                    f"Content preview: {content[:500]}..."
                )

            run_llm_postprocess_pipeline(
                kg,
                requirement_text=requirement_text,
                enrich_connection_semantics=_enrich_connection_semantics_with_llm,
                ensure_no_isolated_structural_components=_ensure_no_isolated_structural_components,
            )

            return kg
        except ValueError as exc:
            last_error = exc
            if attempt == 0:
                extra_rules = ""
                error_text = str(exc)
                
                if "does not include any fastener" in error_text.lower():
                    extra_rules += (
                        "- Clamping/fixation subassemblies MUST include fastener components in their component_ids. "
                        "Example: If 'carrier_plate_assembly' with role 'structural_clamping' has component_ids=['plate_top', 'plate_bottom', 'plate_fastener_set'], it MUST include the fastener_set.\n"
                    )
                
                if "semantically floating" in error_text.lower() and "carrier" in error_text.lower():
                    extra_rules += (
                        "- Ensure carrier_plate_assembly's component_ids includes the fastener components that physically clamp the plates together.\n"
                        "- If fastener_sets exist in the design, they MUST be members of carrier_plate_assembly.\n"
                    )
                
                if "support_to_structure" in error_text:
                    extra_rules += (
                        "- Add support_to_structure connection_requirements for EVERY bearing. "
                        "Connect each bearing to its supporting structural component (e.g., matching wheel_arm_* or carrier_plate_assembly).\n"
                    )
                
                if "subassembly is semantically floating" in error_text.lower():
                  extra_rules += (
                    "- Subassemblies with multiple components MUST either:\n"
                    "  A) Appear as a hub in at least one connection_requirement, OR\n"
                    "  B) Have at least 50% of their members directly used in connection_requirements.\n"
                    "- Check that all members of the subassembly appear in connection_requirements.\n"
                  )
                
                if "rotation/torque_transfer" in error_text or "structural_fixation" in error_text:
                    extra_rules += (
                        "- Add rotation (or torque_transfer) AND structural_fixation requirements for EVERY shaft/axle. "
                        "Do NOT bundle multiple roles in one requirement.\n"
                    )
                
                if "includes a fastener but uses generic purpose" in error_text.lower():
                    extra_rules += (
                        "- When a connection_requirement includes a fastener in 'between', the purpose MUST be engineering-specific. "
                        "Replace generic purposes like 'structural_fixation' with 'fastening_mechanism' or 'bolted_joint' when fasteners are present.\n"
                    )
                if "connection_semantics" in error_text.lower():
                    extra_rules += (
                        "- For every mechanically resolved connection_requirement, add connection_semantics with mechanism, anchors, interface hints, orientation_policy, and geometric_semantics.\n"
                        "- geometric_semantics MUST specify contact_model, feature strategies on both sides, and explicit pattern_policy/pattern_count when relevant.\n"
                        "- Do NOT use generic_mount, generic relation_type values, or placeholder hints like fixation_req / mounting_req / unspecified.\n"
                    )
                
                if "semantic overreach" in error_text.lower() or "redundant" in error_text.lower():
                    extra_rules += (
                        "- Remove connection_requirements where a subassembly connects to components that its members already connect to. "
                        "A subassembly should only appear as a hub if it adds semantic value (e.g., carrier_plate_assembly connecting to central_hub is valid, but wheel_assembly connecting to wheel_arm is redundant if wheel_axle/bearing already connect there).\n"
                    )
                if extra_rules:
                    extra_rules = "\nREPAIR RULES:\n" + extra_rules
                prompt_to_use = (
                    prompt
                    + "\n\nCORRECTION REQUIRED:\n"
                    + "You must fix the error below and return ONLY corrected JSON.\n"
                    + extra_rules
                    + f"Error: {exc}\n"
                    + "Here is your previous JSON output:\n```json\n"
                    + content
                    + "\n```\n"
                    + "Return corrected JSON only. Do not add explanations."
                )
                continue
            raise
        except Exception as e:
            raise ValueError(f"LLM failed to generate knowledge graph: {e!r}")

    if last_error is not None:
      raise last_error
    raise ValueError("LLM failed to generate knowledge graph.")




# _generate_relations_from_connection_requirements removed
# Agent1 generates connection_requirements; relations are downstream


def _validate_against_schema(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return

    lines = ["Knowledge graph validation failed:"]
    for err in errors[:20]:
        path = ".".join([str(p) for p in err.path]) if err.path else "<root>"
        lines.append(f"- {path}: {err.message}")
    if len(errors) > 20:
        lines.append(f"... (+{len(errors) - 20} more)")

    raise ValueError("\n".join(lines))


def transform_yaml_to_kg(
    requirement_yaml: Any = None,
    schema: Any = None,
    *,
    in_path: Path = None,
    schema_path: Path = None,
) -> Dict[str, Any]:
    """Transform requirements to a validated KG.

    Supports:
    - Legacy structured call: `transform_yaml_to_kg(payload_dict, schema_dict)`
    - Current file-based call: `transform_yaml_to_kg(in_path=..., schema_path=...)`
    """

    requirement_text_context = ""

    if in_path is not None or schema_path is not None:
        if in_path is None or schema_path is None:
            raise TypeError("transform_yaml_to_kg requires both in_path and schema_path in path mode")

        raw = _read_yaml(in_path)
        schema = _read_json(schema_path)

        # If the YAML is already structured as a KG, do not call the LLM.
        if isinstance(raw, dict) and "components" in raw and "connection_requirements" in raw:
            payload = copy.deepcopy(raw)
            requirement_text_context = json.dumps(raw, ensure_ascii=False)
        else:
            requirement_text = in_path.read_text(encoding="utf-8")
            payload = _call_llm_to_generate_kg(requirement_text, schema)
            requirement_text_context = requirement_text
    else:
        if not isinstance(requirement_yaml, dict) or not isinstance(schema, dict):
            raise TypeError(
                "transform_yaml_to_kg legacy mode expects (requirement_yaml: dict, schema: dict)"
            )
        payload = copy.deepcopy(requirement_yaml)
        requirement_text_context = json.dumps(requirement_yaml, ensure_ascii=False)
    
    # Promote subassemblies to component nodes BEFORE validation
    # This ensures Agent2 can recognize them in type map
    _promote_subassemblies_to_components(payload)
    
    # Filter out type="module" components - they are conceptual containers, not geometric entities
    # Agent2 processes geometric components only; modules remain as hierarchical metadata
    components = payload.get("components", [])
    if isinstance(components, list):
        geometric_components = [
            c for c in components 
            if isinstance(c, dict) and c.get("type") != "module"
        ]
        module_ids = {
            c.get("id") for c in components 
            if isinstance(c, dict) and c.get("type") == "module" and isinstance(c.get("id"), str)
        }
        payload["components"] = geometric_components
        
        # Also handle connection_requirements that reference removed module components
        # For bearing support connections, replace module with structural component
        # For other connections, remove them
        crs = payload.get("connection_requirements", [])
        if isinstance(crs, list) and module_ids:
            # Find a suitable structural replacement (hub, base, frame)
            structural_replacement = None
            for c in geometric_components:
                if isinstance(c, dict) and isinstance(c.get("id"), str):
                    ctype = c.get("type", "")
                    if ctype in {"hub", "base", "frame"} or "hub" in c.get("id", "").lower():
                        structural_replacement = c.get("id")
                        break
            
            filtered_crs = []
            for cr in crs:
                if not isinstance(cr, dict):
                    filtered_crs.append(cr)
                    continue
                
                between = cr.get("between", [])
                purpose = cr.get("purpose", "")
                
                if isinstance(between, list):
                    # Check if any component in between is a module
                    has_module = any(cid in module_ids for cid in between if isinstance(cid, str))
                    
                    if has_module:
                        # For bearing support, replace module with structural component
                        if purpose == "support_to_structure" and structural_replacement:
                            new_between = [
                                structural_replacement if cid in module_ids else cid 
                                for cid in between if isinstance(cid, str)
                            ]
                            cr = dict(cr)  # Copy to avoid modifying original
                            cr["between"] = new_between
                            filtered_crs.append(cr)
                        # For other purposes, skip the connection
                        continue
                    else:
                        filtered_crs.append(cr)
                elif isinstance(between, dict):
                    # Skip if any key in between dict is a module
                    if any(cid in module_ids for cid in between.keys()):
                        continue
                    filtered_crs.append(cr)
                else:
                    filtered_crs.append(cr)
            payload["connection_requirements"] = filtered_crs
    
    run_structured_postprocess_pipeline(
        payload,
        requirement_text_context=requirement_text_context,
    )

    _validate_against_schema(payload, schema)
    _prune_redundant_wheel_subassemblies(payload)
    _validate_subassembly_connectivity(payload)
    _annotate_component_execution_roles(payload)
    return payload




def inject_resolved_standard_parts(*, run_dir: Path) -> Dict[str, Any]:
    """Inject resolved standard parts back into knowledge_graph.json.

    Bridge step used by pipeline after tools/resolve_standard_parts.py.
    It keeps KG and planning artifacts aligned for downstream agents.
    """

    kg_path = run_dir / "knowledge" / "knowledge_graph.json"
    resolved_path = run_dir / "planning" / "standard_parts_resolved.json"
    unresolved_path = run_dir / "planning" / "standard_parts_unresolved.json"

    if not kg_path.exists():
        raise FileNotFoundError(f"knowledge_graph.json not found: {kg_path}")
    if not resolved_path.exists():
        return {
            "updated": False,
            "reason": "resolved_file_missing",
            "knowledge_graph": str(kg_path).replace("\\", "/"),
            "resolved_path": str(resolved_path).replace("\\", "/"),
        }

    kg = _read_json(kg_path)
    resolved_payload = _read_json(resolved_path)
    unresolved_payload = _read_json(unresolved_path) if unresolved_path.exists() else {}

    resolved_parts = []
    if isinstance(resolved_payload, Mapping):
        parts = resolved_payload.get("resolved", [])
        if isinstance(parts, list):
            resolved_parts = [p for p in parts if isinstance(p, Mapping)]

    unresolved_parts = []
    if isinstance(unresolved_payload, Mapping):
        parts = unresolved_payload.get("unresolved", [])
        if isinstance(parts, list):
            unresolved_parts = [p for p in parts if isinstance(p, Mapping)]

    if isinstance(kg, Mapping):
        kg = dict(kg)
    else:
        kg = {}

    def _parse_metric_size(value: Any) -> tuple[float | None, float | None]:
        if not isinstance(value, str):
            return None, None
        import re

        m = re.search(r"\bM\s*(\d+(?:\.\d+)?)\s*(?:[xX]\s*(\d+(?:\.\d+)?))?", value)
        if not m:
            return None, None
        nominal = float(m.group(1))
        length = float(m.group(2)) if m.group(2) else None
        return nominal, length

    def _size_from_resolved(row: Mapping[str, Any]) -> str | None:
        candidate = row.get("size")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        resolved_designation = row.get("resolved_designation")
        if isinstance(resolved_designation, str) and resolved_designation.strip():
            nominal, length = _parse_metric_size(resolved_designation)
            if isinstance(nominal, (int, float)):
                nominal_s = str(int(nominal)) if abs(nominal - int(nominal)) < 1e-6 else f"{nominal:g}"
                if isinstance(length, (int, float)):
                    length_s = str(int(length)) if abs(length - int(length)) < 1e-6 else f"{length:g}"
                    return f"M{nominal_s}x{length_s}"
                return f"M{nominal_s}"
        return None

    resolved_fasteners = [
        r
        for r in resolved_parts
        if isinstance(r, Mapping)
        and str(r.get("category") or "").strip().lower() in {"fastener", "bolt", "screw", "nut", "washer", "rivet"}
    ]

    by_bound_component: Dict[str, Dict[str, Any]] = {}
    by_connection_id: Dict[str, Dict[str, Any]] = {}
    for row in resolved_fasteners:
        bound_ids = row.get("bound_component_ids")
        if isinstance(bound_ids, list):
            for cid in bound_ids:
                if isinstance(cid, str) and cid and cid not in by_bound_component:
                    by_bound_component[cid] = dict(row)
        applied = row.get("applied_to")
        if isinstance(applied, list):
            for cr_id in applied:
                if isinstance(cr_id, str) and cr_id and cr_id not in by_connection_id:
                    by_connection_id[cr_id] = dict(row)

    components = kg.get("components")
    if isinstance(components, list):
        for comp in components:
            if not isinstance(comp, dict):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str) or cid not in by_bound_component:
                continue
            row = by_bound_component[cid]
            fastener = row.get("fastener") if isinstance(row.get("fastener"), Mapping) else {}
            nominal = fastener.get("nominal_diameter_mm") if isinstance(fastener.get("nominal_diameter_mm"), (int, float)) else None
            length = fastener.get("length_mm") if isinstance(fastener.get("length_mm"), (int, float)) else None
            dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
            dims = dict(dims)
            if isinstance(nominal, (int, float)):
                dims["nominal_diameter"] = float(nominal)
            if isinstance(length, (int, float)):
                dims["length"] = float(length)
            if dims:
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)

    connection_requirements = kg.get("connection_requirements")
    updated_connection_decisions = 0
    if isinstance(connection_requirements, list):
        for cr in connection_requirements:
            if not isinstance(cr, dict):
                continue
            decision = cr.get("connection_decision")
            if not isinstance(decision, Mapping):
                continue
            decision = dict(decision)

            ref_component_id = decision.get("fastener_ref_component_id")
            resolved_row = None
            if isinstance(ref_component_id, str) and ref_component_id:
                resolved_row = by_bound_component.get(ref_component_id)
            if resolved_row is None:
                cr_id = cr.get("id")
                if isinstance(cr_id, str) and cr_id:
                    resolved_row = by_connection_id.get(cr_id)
            if resolved_row is None:
                continue

            requested_size = decision.get("fastener_size") if isinstance(decision.get("fastener_size"), str) else None
            resolved_size = _size_from_resolved(resolved_row)
            if isinstance(requested_size, str) and requested_size.strip():
                decision["requested_fastener_size"] = requested_size.strip()
            if isinstance(resolved_size, str) and resolved_size:
                decision["fastener_size"] = resolved_size

            resolved_designation = resolved_row.get("resolved_designation")
            if isinstance(resolved_designation, str) and resolved_designation.strip():
                decision["resolved_fastener_designation"] = resolved_designation.strip()

            fastener = resolved_row.get("fastener") if isinstance(resolved_row.get("fastener"), Mapping) else {}
            nominal = fastener.get("nominal_diameter_mm") if isinstance(fastener.get("nominal_diameter_mm"), (int, float)) else None
            length = fastener.get("length_mm") if isinstance(fastener.get("length_mm"), (int, float)) else None
            if isinstance(nominal, (int, float)):
                decision["resolved_nominal_diameter_mm"] = float(nominal)
            if isinstance(length, (int, float)):
                decision["resolved_length_mm"] = float(length)

            cr["connection_decision"] = decision
            updated_connection_decisions += 1

    kg["standard_parts"] = resolved_parts
    kg["standard_parts_resolved"] = {
        "resolved": resolved_parts,
        "injected_at": datetime.now().isoformat(timespec="seconds"),
    }
    if unresolved_parts:
        kg["standard_parts_unresolved"] = {
            "unresolved": unresolved_parts,
            "injected_at": datetime.now().isoformat(timespec="seconds"),
        }

    kg_path.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "updated": True,
        "resolved_count": len(resolved_parts),
        "unresolved_count": len(unresolved_parts),
        "updated_connection_decisions": updated_connection_decisions,
        "knowledge_graph": str(kg_path).replace("\\", "/"),
    }


def run(*, run_dir: Path, schema_path: Path | None = None) -> None:
    """Agent entrypoint (facts-layer I/O only).

    Reads:
    - run_dir/input/anforderungsliste.yaml

    Writes:
    - run_dir/knowledge/knowledge_graph.json

    Does not write anywhere outside run_dir.
    """

    schema_path = schema_path or Path("planning") / "knowledge_graph_schema.json"

    in_path = run_dir / "input" / "anforderungsliste.yaml"
    out_path = run_dir / "knowledge" / "knowledge_graph.json"

    if not in_path.exists():
        raise SystemExit(f"Input YAML not found: {in_path}")
    if not schema_path.exists():
        raise SystemExit(f"Schema not found: {schema_path}")

    kg = transform_yaml_to_kg(in_path=in_path, schema_path=schema_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Requirement-to-KG agent (run-dir IO): input/anforderungsliste.yaml -> knowledge/knowledge_graph.json"
    )
    parser.add_argument(
        "--run-dir",
        dest="run_dir",
        required=True,
        help="Run directory, e.g. execution/runs/<run_id>",
    )
    parser.add_argument(
      "--schema",
      dest="schema_path",
            default="planning/knowledge_graph_schema.json",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    schema_path = Path(args.schema_path)
    run(run_dir=run_dir, schema_path=schema_path)
    print(f"Wrote: {run_dir / 'knowledge' / 'knowledge_graph.json'}")


if __name__ == "__main__":
    main()
