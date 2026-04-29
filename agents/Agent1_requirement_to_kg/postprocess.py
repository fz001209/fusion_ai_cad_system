"""Ordered Agent1 post-processing pipelines for LLM and structured inputs."""

from __future__ import annotations

import os
from typing import Any, Dict

from agents.Agent1_requirement_to_kg.module_wiring import wire_agent1_modules

globals().update(wire_agent1_modules())

__all__ = [
    "run_llm_postprocess_pipeline",
    "run_structured_postprocess_pipeline"
]


def _wheel_rules_enabled() -> bool:
    value = os.getenv("AGENT1_ENABLE_WHEEL_RULES", "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _run_wheel_rule_pipeline(payload: Dict[str, Any], *, validate: bool = True) -> None:
    if not _wheel_rules_enabled():
        metadata = payload.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["agent1_wheel_rules_enabled"] = False
        return

    _canonicalize_wheel_rotor_naming(payload)
    _prune_rotating_wheel_support_fastening_conflicts(payload)
    _prune_asymmetric_wheel_support_artifacts(payload)
    _prune_non_explicit_wheel_internal_fastening(payload)
    _prune_asymmetric_wheel_axle_auxiliary_artifacts(payload)
    _repair_illegal_wheel_axle_hub_links(payload)
    _repair_rotating_wheel_hub_axle_fixation_links(payload)
    _canonicalize_rotating_wheel_axle_support_mounts(payload)
    _rewire_rotating_wheel_container_rotation_hosts(payload)
    _ensure_arm_interface_requirements(payload)
    _enforce_central_hub_arm_slot_mounts(payload)
    _canonicalize_hub_arm_fastener_components(payload)
    _normalize_symmetric_hub_arm_fasteners(payload)
    _prune_non_explicit_wheel_internal_fastening(payload)
    if validate:
        _validate_wheel_arm_connection_topology(payload)
    _ensure_wheel_subcomponent_instance_patterns(payload)
    _ensure_wheel_rim_tire_position_parent(payload)
    _normalize_patterns(payload)


def run_llm_postprocess_pipeline(
    kg: Dict[str, Any],
    *,
    requirement_text: str,
    enrich_connection_semantics,
    ensure_no_isolated_structural_components,
) -> Dict[str, Any]:
    """Normalize, repair, enrich, and validate raw LLM Agent1 output."""
    _normalize_component_contract_fields(kg)
    _normalize_component_kind_and_must_model(kg)
    _ensure_wheel_mounting_requirements(kg)
    _normalize_connection_requirements(kg)

    _decompose_complex_components(kg)
    _collapse_semantic_clones(kg)
    _run_wheel_rule_pipeline(kg)
    _align_rotational_symmetry_instancing_annotations(kg)
    _sanitize_instancing_annotations(kg)
    _normalize_and_canonicalize_bearings(kg)

    _ensure_shape_semantics_defaults(kg)
    _fill_missing_dimensions(kg)
    _normalize_and_canonicalize_bearings(kg)
    _prune_stale_standard_parts(kg)
    _infer_standard_parts(kg)
    _prune_stale_standard_parts(kg)
    _validate_no_relations(kg)

    ensure_no_isolated_structural_components(kg)
    _ensure_component_hierarchy_contract(kg)
    _sync_dimensions_and_parameters(kg)
    _ensure_module_subassembly_interfaces(kg)

    _validate_fastener_usage(kg)
    _validate_clamping_subassembly_has_fasteners(kg)
    _validate_fastener_purpose_specificity(kg)
    _repair_subassembly_connections(kg)
    _prune_redundant_wheel_subassemblies(kg)
    _autofill_missing_connection_decisions(kg)
    _validate_subassembly_connectivity(kg)
    _autofill_bearing_and_shaft_closure(kg)
    _infer_module_drive_chain(requirement_text, kg)
    _sanitize_fastener_bundles(kg)
    _prune_stale_standard_parts(kg)
    _infer_standard_parts(kg)
    _prune_stale_standard_parts(kg)
    _autofill_bearing_and_shaft_closure(kg)
    _normalize_connection_requirements(kg)
    enrich_connection_semantics(kg)
    _normalize_connection_requirements(kg)
    _drop_agent1_autofilled_connection_decisions_when_semantics_present(kg)
    _autofill_agent1_deterministic_connection_semantics(kg)
    _elevate_authoritative_connection_semantics_detail(kg)
    _normalize_symmetric_wheel_rim_hub_connection_semantics(kg)
    _normalize_symmetric_wheel_tire_rim_connection_semantics(kg)
    if _wheel_rules_enabled():
        _enforce_central_hub_arm_slot_mounts(kg)
    _validate_bearing_and_shaft_completeness(kg)
    _validate_connection_semantics_contracts(kg)
    _validate_connection_decisions(kg)
    _populate_frozen_spec(kg)
    _validate_wheel_rotor_naming(kg)
    _validate_bearing_canonical_schema(kg)
    return kg


def run_structured_postprocess_pipeline(payload: Dict[str, Any], *, requirement_text_context: str) -> Dict[str, Any]:
    """Normalize and validate already-structured Agent1 KG input."""
    _normalize_component_contract_fields(payload)
    _normalize_component_kind_and_must_model(payload)
    _ensure_wheel_mounting_requirements(payload)
    _autofill_bearing_and_shaft_closure(payload)
    _infer_module_drive_chain(requirement_text_context, payload)
    _autofill_bearing_and_shaft_closure(payload)
    _normalize_connection_requirements(payload)
    _drop_agent1_autofilled_connection_decisions_when_semantics_present(payload)
    _run_wheel_rule_pipeline(payload)
    _ensure_component_hierarchy_contract(payload)
    _sync_dimensions_and_parameters(payload)
    _sanitize_fastener_bundles(payload)
    _prune_stale_standard_parts(payload)
    _infer_standard_parts(payload)
    _prune_stale_standard_parts(payload)
    _autofill_agent1_deterministic_connection_semantics(payload)
    _elevate_authoritative_connection_semantics_detail(payload)
    _normalize_symmetric_wheel_rim_hub_connection_semantics(payload)
    _normalize_symmetric_wheel_tire_rim_connection_semantics(payload)
    if _wheel_rules_enabled():
        _enforce_central_hub_arm_slot_mounts(payload)
        _canonicalize_hub_arm_fastener_components(payload)
    _prune_stale_standard_parts(payload)
    _validate_no_relations(payload)
    _validate_wheel_rotor_naming(payload)
    payload.pop("agent1_connection_semantics_audit", None)
    return payload
