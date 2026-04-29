"""Agent4 assembly semantic reasoning, relation cleanup, constraints, and refinements."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set, Tuple

from agents.common_utils import read_json as _read_json, write_json as _write_json, collect_defined_vars as _collect_defined_vars

from .common import *
from .assembly_geometry import *

class AssemblySemanticReasoner:
    """
    LLM-assisted assembly semantic reasoner.
    
    DECISION SEMANTICS: Global but Independent
    - LLM receives ALL interfaces in ONE call (global context)
    - Each potential relation is decided INDEPENDENTLY
    - Relation A does NOT affect relation B decision
    - This enables batch reasoning while maintaining autonomy
    """
    
    def __init__(self, contract: Dict[str, Any]):
        self.contract = contract
        self.component_ids, self.interfaces_by_component, self.interface_map = self._build_contract_index(contract)
        self.allowed_attachments = set(contract.get("allowable_attachment_types", []))
        self.llm_last_audit: Dict[str, Any] | None = None
    
    def _build_contract_index(self, contract: Dict[str, Any]) -> Tuple[Set[str], Dict[str, Set[str]], Dict[str, Dict[str, Any]]]:
        """Build lookup structures for contract validation."""
        component_ids: Set[str] = set()
        interfaces_by_component: Dict[str, Set[str]] = {}
        interface_map: Dict[str, Dict[str, Any]] = {}  # comp_id:iface_id -> interface def
        
        for comp in contract.get("components", []):
            comp_id = comp.get("component_id")
            if not comp_id:
                continue
            component_ids.add(comp_id)
            iface_ids: Set[str] = set()
            for iface in comp.get("interfaces", []):
                iface_id = iface.get("interface_id")
                if iface_id:
                    iface_ids.add(iface_id)
                    key = f"{comp_id}:{iface_id}"
                    interface_map[key] = iface
            interfaces_by_component[comp_id] = iface_ids
        
        return component_ids, interfaces_by_component, interface_map
    
    def get_llm_decisions(
        self,
        kg_component_ids: Set[str],
        *,
        knowledge_graph: Dict[str, Any] | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get LLM assembly relation inferences.
        
        LLM input: contract components and their interfaces (NOT raw geometry).
        LLM output: proposed assembly relations with patterns from ASSEMBLY_PATTERNS.
        
        Returns:
            Dict mapping relation_id to decision dict with:
            - from/to: component_id and interface_id
            - assembly_pattern: str from ASSEMBLY_PATTERNS
            - rationale: str
            - valid: bool
        """
        if not kg_component_ids or not self.contract.get("components"):
            return {}
        
        # Filter contract to relevant components
        relevant_components = [c for c in self.contract.get("components", []) 
                              if c.get("component_id") in kg_component_ids]
        
        if not relevant_components:
            return {}
        
        kg_hints: Dict[str, Any] = {}
        if isinstance(knowledge_graph, dict):
            reqs = knowledge_graph.get("connection_requirements")
            if isinstance(reqs, list):
                kg_hints["connection_requirements"] = [
                    {
                        "id": r.get("id"),
                        "between": r.get("between"),
                        "purpose": r.get("purpose"),
                        "roles": r.get("roles"),
                        "connection_decision": r.get("connection_decision"),
                    }
                    for r in reqs
                    if isinstance(r, dict)
                ]

        prompt = f"""You are the LLM assembly reasoning layer for Agent 4 (Assembly Semantic Planner).

TASK:
Infer assembly relations between components based on their interfaces.
You MUST select attachment patterns from the ASSEMBLY_PATTERNS enum below.

DECISION SEMANTICS: Global but Independent
- You receive ALL components in this ONE call (global context for efficiency)
- Infer relations for EACH component pair INDEPENDENTLY
- Relation between A-B does NOT affect C-D relation inference
- Focus on EACH pair's individual interface compatibility

ALLOWED PATTERNS:
- RIGID_MATE: Permanent rigid connections (mounting, fixation, support)
- REVOLUTE_MATE: Rotational joints (wheels, shafts, bearings)
- SLIDER_MATE: Linear sliding joints (guides, sliders)
- CYLINDRICAL_MATE: Combined rotation+sliding (cylindrical joints)

IMPORTANT - UNDIRECTED RELATIONS:
- Assembly relations are BIDIRECTIONAL (A→B same as B→A)
- Only output ONE direction per component pair
- Choose the direction that makes semantic sense (e.g., wheel→shaft, not shaft→wheel)

NEGATIVE EXAMPLES (DO NOT DO):
? Connecting components with incompatible interface roles
? Using REVOLUTE_MATE for purely rigid connections
? Proposing multiple relations between same component pair
? Creating circular dependencies in a single inference

STRICT RULES:
1) Do NOT output Fusion API names or operations
2) Do NOT output assembly sequence or ordering
3) Do NOT output spatial coordinates or DOF values
4) ONLY propose relations between components that have interfaces
5) ONLY use patterns from ASSEMBLY_PATTERNS above
6) Provide brief rationale for each relation
7) Output at most one relation per component pair (bidirectional)

Component Interfaces:
```json
{json.dumps(relevant_components, indent=2, ensure_ascii=False)}
```

Knowledge Graph Hints:
```json
{json.dumps(kg_hints, indent=2, ensure_ascii=False)}
```

Return JSON in this format:
{{
    "relations": [
        {{
            "from": {{
                "component_id": "...",
                "interface_id": "..."
            }},
            "to": {{
                "component_id": "...",
                "interface_id": "..."
            }},
            "assembly_pattern": "RIGID_MATE|REVOLUTE_MATE|SLIDER_MATE|CYLINDRICAL_MATE",
            "rationale": "short explanation"
        }}
    ]
}}
"""
        
        response, audit = _call_llm(prompt)
        self.llm_last_audit = audit
        if not response:
            return {}
        
        obj = _extract_json(response)
        if not obj or not isinstance(obj, dict):
            return {}
        
        decisions = {}
        raw_relations = obj.get("relations", [])
        
        if not isinstance(raw_relations, list):
            return {}
        
        for idx, item in enumerate(raw_relations):
            if not isinstance(item, dict):
                continue
            
            from_data = item.get("from", {})
            to_data = item.get("to", {})
            pattern = item.get("assembly_pattern")
            rationale = item.get("rationale", "")
            
            from_comp = from_data.get("component_id")
            from_iface = from_data.get("interface_id")
            to_comp = to_data.get("component_id")
            to_iface = to_data.get("interface_id")
            
            if not all([from_comp, from_iface, to_comp, to_iface, pattern]):
                continue
            
            # Validate pattern is in allowed set
            valid = pattern in ASSEMBLY_PATTERNS if pattern else False
            
            rel_id = f"llm_rel_{idx}"
            decisions[rel_id] = {
                "relation_id": rel_id,
                "from": {"component_id": from_comp, "interface_id": from_iface},
                "to": {"component_id": to_comp, "interface_id": to_iface},
                "assembly_pattern": pattern,
                "attachment_type": _map_pattern_to_attachment_type(pattern) if pattern else "rigid",
                "rationale": rationale,
                "valid": valid
            }
        
        return decisions
    
    def validate_llm_relation(self, relation: Dict[str, Any]) -> Tuple[bool, str | None]:
        """
        Validate LLM-proposed relation against contract constraints.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        from_comp = relation.get("from", {}).get("component_id")
        from_iface = relation.get("from", {}).get("interface_id")
        to_comp = relation.get("to", {}).get("component_id")
        to_iface = relation.get("to", {}).get("interface_id")
        pattern = relation.get("assembly_pattern")
        attachment_type = relation.get("attachment_type")
        
        # Check components exist
        if not from_comp or from_comp not in self.component_ids:
            return False, f"from component '{from_comp}' not in contract"
        if not to_comp or to_comp not in self.component_ids:
            return False, f"to component '{to_comp}' not in contract"
        
        # Check interfaces exist
        if not from_iface or from_iface not in self.interfaces_by_component.get(from_comp, set()):
            return False, f"from interface '{from_iface}' not in component '{from_comp}'"
        if not to_iface or to_iface not in self.interfaces_by_component.get(to_comp, set()):
            return False, f"to interface '{to_iface}' not in component '{to_comp}'"
        
        # Check attachment type allowed
        if not attachment_type or attachment_type not in self.allowed_attachments:
            return False, f"attachment_type '{attachment_type}' not allowed by contract"
        
        # Check interface compatibility
        from_key = f"{from_comp}:{from_iface}"
        to_key = f"{to_comp}:{to_iface}"
        from_iface_def = self.interface_map.get(from_key, {})
        to_iface_def = self.interface_map.get(to_key, {})
        
        if pattern and not _is_assembly_pattern_allowed(pattern, from_iface_def, to_iface_def):
            return False, f"pattern '{pattern}' incompatible with interface roles"
        
        return True, None


def _map_relation_type(rel_type: str) -> str | None:
    """Map KG relation type to attachment type."""
    if rel_type == "rigid_attachment":
        return "rigid"
    if rel_type == "rotation":
        return "revolute"
    return None


def _validate_relation_fields(rel: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, str | None]:
    """Validate relation endpoints structure."""
    a = rel.get("a")
    b = rel.get("b")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None, "relation missing a/b endpoints"

    a_comp = a.get("component_id")
    a_iface = a.get("interface_id")
    b_comp = b.get("component_id")
    b_iface = b.get("interface_id")

    if not all([a_comp, a_iface, b_comp, b_iface]):
        return None, "relation endpoints missing component_id or interface_id"

    return {
        "a_component_id": a_comp,
        "a_interface_id": a_iface,
        "b_component_id": b_comp,
        "b_interface_id": b_iface,
    }, None


_EXPECTED_REMAINING_DOF = {
    "rigid": 0,
    "revolute": 1,
    "slider": 1,
    "cylindrical": 2,
}


def _enforce_relation_consistency(
    relations: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Deterministic CSP-lite checks for assembly relation set.

    Rules:
    - one component pair can only keep one relation (first seen wins)
    - interface occupancy conflict only when SAME endpoint is reused for the SAME component pair
    - each kept relation is annotated with expected_remaining_dof
    """
    kept: List[Dict[str, Any]] = []
    warnings: List[str] = []
    overrides: List[Dict[str, Any]] = []
    dropped_audit: List[Dict[str, Any]] = []
    occupied_interfaces_for_pair: Set[Tuple[Tuple[str, str], str, str]] = set()
    pair_seen: Set[Tuple[str, str]] = set()
    relation_by_interface: Dict[Tuple[str, str], str] = {}
    relation_by_pair: Dict[Tuple[str, str], str] = {}

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        rid = rel.get("relation_id") if isinstance(rel.get("relation_id"), str) else "unknown_relation"
        rid_s = str(rid)
        from_ep_raw = rel.get("from")
        to_ep_raw = rel.get("to")
        from_ep: Dict[str, Any] = from_ep_raw if isinstance(from_ep_raw, dict) else {}
        to_ep: Dict[str, Any] = to_ep_raw if isinstance(to_ep_raw, dict) else {}
        a_comp = from_ep.get("component_id")
        a_iface = from_ep.get("interface_id")
        b_comp = to_ep.get("component_id")
        b_iface = to_ep.get("interface_id")

        if not all(isinstance(x, str) and x for x in (a_comp, a_iface, b_comp, b_iface)):
            warnings.append(f"{rid}: missing endpoint identifiers, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "relation_endpoint_incomplete",
                    "reason": "missing component_id/interface_id on relation endpoint",
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "unresolvable_interface",
                    "reason": "missing component_id/interface_id on relation endpoint",
                    "replacement_relation_id": None,
                    "replaced_by": None,
                    "replacement_type": None,
                }
            )
            continue

        a_comp_s = str(a_comp)
        a_iface_s = str(a_iface)
        b_comp_s = str(b_comp)
        b_iface_s = str(b_iface)

        iface_a_key: Tuple[str, str] = (a_comp_s, a_iface_s)
        iface_b_key: Tuple[str, str] = (b_comp_s, b_iface_s)

        pair_key: Tuple[str, str] = (
            (a_comp_s, b_comp_s) if a_comp_s <= b_comp_s else (b_comp_s, a_comp_s)
        )
        pair_iface_a_key = (pair_key, a_comp_s, a_iface_s)
        pair_iface_b_key = (pair_key, b_comp_s, b_iface_s)
        if pair_iface_a_key in occupied_interfaces_for_pair or pair_iface_b_key in occupied_interfaces_for_pair:
            replaced_by: str | None = relation_by_interface.get(iface_a_key) or relation_by_interface.get(iface_b_key)
            warnings.append(f"{rid}: interface occupancy conflict, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "interface_occupancy_conflict",
                    "reason": "interface endpoint already occupied by another relation",
                    "endpoints": [
                        {"component_id": a_comp_s, "interface_id": a_iface_s},
                        {"component_id": b_comp_s, "interface_id": b_iface_s},
                    ],
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "conflict",
                    "reason": "interface endpoint already occupied by another relation",
                    "replacement_relation_id": replaced_by,
                    "replaced_by": replaced_by,
                    "replacement_type": "kept_relation" if isinstance(replaced_by, str) else None,
                    "occupied_endpoints": [
                        {"component_id": a_comp_s, "interface_id": a_iface_s},
                        {"component_id": b_comp_s, "interface_id": b_iface_s},
                    ],
                }
            )
            continue

        if pair_key in pair_seen:
            replaced_by = relation_by_pair.get(pair_key)
            warnings.append(f"{rid}: duplicate component pair relation, dropped")
            overrides.append(
                {
                    "relation_id": rid,
                    "override_type": "component_pair_duplicate",
                    "reason": "component pair already constrained by another relation",
                    "pair": [pair_key[0], pair_key[1]],
                }
            )
            dropped_audit.append(
                {
                    "relation_id": rid,
                    "drop_reason": "duplicate",
                    "reason": "component pair already constrained by another relation",
                    "replacement_relation_id": replaced_by,
                    "replaced_by": replaced_by,
                    "replacement_type": "kept_relation" if isinstance(replaced_by, str) else None,
                    "pair": [pair_key[0], pair_key[1]],
                }
            )
            continue

        attachment_type = rel.get("attachment_type")
        if isinstance(attachment_type, str):
            rel["expected_remaining_dof"] = _EXPECTED_REMAINING_DOF.get(attachment_type)

        kept.append(rel)
        occupied_interfaces_for_pair.add(pair_iface_a_key)
        occupied_interfaces_for_pair.add(pair_iface_b_key)
        pair_seen.add(pair_key)
        relation_by_interface[iface_a_key] = rid_s
        relation_by_interface[iface_b_key] = rid_s
        relation_by_pair[pair_key] = rid_s

    dof_histogram: Dict[str, int] = {}
    unknown_attachment_count = 0
    for rel in kept:
        attachment_type = rel.get("attachment_type")
        key = attachment_type if isinstance(attachment_type, str) and attachment_type else "unknown"
        dof_histogram[key] = dof_histogram.get(key, 0) + 1
        if rel.get("expected_remaining_dof") is None:
            unknown_attachment_count += 1

    summary: Dict[str, Any] = {
        "input_relations": len(relations),
        "kept_relations": len(kept),
        "dropped_relations": max(0, len(relations) - len(kept)),
        "occupied_interfaces": len(occupied_interfaces_for_pair),
        "dof_histogram": dof_histogram,
        "unknown_or_unmapped_attachment_count": unknown_attachment_count,
        "dropped_relation_audit_count": len(dropped_audit),
    }
    return kept, warnings, overrides, summary, dropped_audit


def _extract_fastener_steps(geometry_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract fastener_steps from geometry_plan.
    
    Fastener steps are feature_steps with function='place_fastener_group'.
    
    Returns:
        List of fastener_step dictionaries with fastener_spec information.
    """
    fastener_steps: List[Dict[str, Any]] = []
    steps = geometry_plan.get("steps")
    if not isinstance(steps, list):
        return fastener_steps
    
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") != "place_fastener_group":
            continue
        fastener_steps.append(step)
    
    return fastener_steps


def _infer_torque_spec(fastener_size: str) -> str:
    """
    Infer torque specification from fastener size.
    
    Uses common ISO 4017 bolt torque recommendations:
    - M3: 0.5-0.8 Nm
    - M5: 1.5-2.5 Nm
    - M6: 2.5-3.5 Nm
    - M8: 6-8 Nm
    - M10: 12-16 Nm
    - M12: 20-28 Nm
    """
    if not fastener_size:
        return "0-1 Nm"
    
    size_match = re.match(r"M(\d+)", fastener_size, re.IGNORECASE)
    if not size_match:
        return "0-1 Nm"
    
    size_num = int(size_match.group(1))
    torque_map: Dict[int, str] = {
        3: "0.5-0.8 Nm",
        5: "1.5-2.5 Nm",
        6: "2.5-3.5 Nm",
        8: "6-8 Nm",
        10: "12-16 Nm",
        12: "20-28 Nm",
    }
    
    return torque_map.get(size_num, "0-1 Nm")


def _determine_locking_mechanism(fastener_spec: Dict[str, Any]) -> str:
    """
    Determine locking mechanism from fastener_spec.
    
    Args:
        fastener_spec: Dictionary with fastener specification.
    
    Returns:
        Locking mechanism type (thread_lock, washer, self_locking).
    """
    if not isinstance(fastener_spec, dict):
        return "thread_lock"
    
    # Check explicit lock flag
    if fastener_spec.get("lock"):
        return "thread_lock"
    
    # Check fastener type
    fastener_type = fastener_spec.get("type", "").lower()
    if "self" in fastener_type or "nylon" in fastener_type:
        return "self_locking"
    
    return "thread_lock"


def _generate_assembly_constraints(
    fastener_steps: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate assembly_constraints from fastener_steps.
    
    Converts fastener placement steps into constraint definitions that specify
    how bolts connect components through holes.
    
    Each fastener_step produces one assembly_constraint with:
    - constraint_id: Unique identifier
    - type: Constraint type (bolted_rigid_connection)
    - fastener_spec: Size and type (e.g., M5x12)
    - fastener_standard: ISO standard
    - connections: List of component pairs connected by fastener
    - hole_ids: Holes through which fastener passes
    - torque_requirement: Torque spec for this fastener
    - locking_mechanism: How locking is achieved
    
    Args:
        fastener_steps: List of fastener steps from geometry_plan
    
    Returns:
        List of assembly_constraint dictionaries
    """
    constraints: List[Dict[str, Any]] = []
    
    for step_idx, step in enumerate(fastener_steps):
        if not isinstance(step, dict):
            continue
        
        inputs = step.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        
        # Extract fastener information
        fastener_spec_str = inputs.get("fastener_spec", "")
        fastener_type = inputs.get("fastener_type", "bolt")
        fastener_count = inputs.get("fastener_count", 1)
        fastener_standard = inputs.get("fastener_standard", "ISO4017")
        hole_refs = inputs.get("hole_references", [])
        target_components = inputs.get("target_components", [])
        fit_policy = inputs.get("fit_policy", "clearance")
        fastener_spec_dict = inputs.get("fastener_spec_obj", {})
        
        # Build constraint
        constraint: Dict[str, Any] = {
            "constraint_id": f"AC_{step_idx:03d}",
            "type": "bolted_rigid_connection",
            "fastener_spec": fastener_spec_str,
            "fastener_type": fastener_type,
            "fastener_count": fastener_count,
            "fastener_standard": fastener_standard,
            "connections": target_components,
            "hole_ids": hole_refs if isinstance(hole_refs, list) else [],
            "torque_requirement": _infer_torque_spec(fastener_spec_str),
            "locking_mechanism": _determine_locking_mechanism(fastener_spec_dict),
            "fit_policy": fit_policy,
        }
        
        constraints.append(constraint)
    
    return constraints


def _generate_assembly_sequence(
    geometry_steps: List[Dict[str, Any]],
    fastener_constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Generate assembly_sequence defining operation order.
    
    Defines the logical sequence: component creation → hole creation → fastener insertion.
    
    Args:
        geometry_steps: All steps from geometry_plan
        fastener_constraints: Assembly constraints for fasteners
    
    Returns:
        List of sequence dictionaries defining operation order
    """
    sequence: List[Dict[str, Any]] = []
    
    # Phase 1: Component creation
    component_steps: List[str] = []
    for step in geometry_steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") == "CREATE_COMPONENT":
            component_id = step.get("outputs", {}).get("component_id")
            if component_id:
                component_steps.append(component_id)
                sequence.append({
                    "phase": 1,
                    "operation": "create_component",
                    "component_id": component_id,
                    "order": len(sequence),
                })
    
    # Phase 2: Hole/feature creation
    for step in geometry_steps:
        if not isinstance(step, dict):
            continue
        if step.get("function") == "create_hole":
            hole_id = step.get("outputs", {}).get("hole_id")
            target_comp = step.get("inputs", {}).get("target_component")
            if hole_id:
                sequence.append({
                    "phase": 2,
                    "operation": "create_hole",
                    "hole_id": hole_id,
                    "target_component": target_comp,
                    "order": len(sequence),
                })
    
    # Phase 3: Fastener insertion
    for constraint in fastener_constraints:
        constraint_id = constraint.get("constraint_id")
        hole_ids = constraint.get("hole_ids", [])
        connections = constraint.get("connections", [])
        
        sequence.append({
            "phase": 3,
            "operation": "insert_fastener",
            "constraint_id": constraint_id,
            "fastener_spec": constraint.get("fastener_spec"),
            "hole_ids": hole_ids,
            "connections": connections,
            "order": len(sequence),
        })
    
    return sequence


def build_assembly_semantics(
    *,
    knowledge_graph: Dict[str, Any],
    contract: Dict[str, Any],
    use_llm_assembly_intent: bool = True,
    component_realization_classes: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """
    Build assembly semantics from KG relations and LLM inferences.

    DECISION AUTHORITY MODEL:
    - KG relations are ALWAYS included (source of truth)
    - LLM proposes ADDITIONAL relations for arbitrary assemblies
    - Deterministic rules validate all relations (KG + LLM)
    - Invalid relations are rejected with override records
    
    Interface auto-matching:
    - If specified interface_id is not in contract, use first available
    - Handles name mismatches between KG and contract-generated names
    """
    warnings: List[str] = []
    assembly_relations: List[Dict[str, Any]] = []
    all_overrides: List[Dict[str, Any]] = []
    llm_corroborations: List[Dict[str, Any]] = []

    # Phase A: resolve explicit contract connections (highest priority)
    explicit_resolved = False
    for key in ("connections", "attachments", "joints", "mates"):
        if explicit_resolved:
            continue
        if isinstance(contract.get(key), list):
            resolved = resolve_assembly_geometry(contract, knowledge_graph)
            assembly_relations = resolved.get("resolved_connections", [])
            for rel in assembly_relations:
                if isinstance(rel, dict):
                    rel["source"] = "explicit_contract"
            explicit_resolved = True
    
    reasoner = AssemblySemanticReasoner(contract)
    component_ids = reasoner.component_ids
    interfaces_by_component = reasoner.interfaces_by_component
    allowed_attachments = reasoner.allowed_attachments

    def _hole_axis_interface_name(connection_id: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]+", "_", str(connection_id or "").strip()).strip("_")
        if not token:
            token = "connection"
        return f"{token}_hole_axis"

    # Get KG component IDs for LLM context
    kg_component_ids = {c.get("id") for c in knowledge_graph.get("components", []) if c.get("id")}
    
    # Process KG connection_requirements (deterministic, always included when present)
    kg_relation_count = 0
    for idx, req in enumerate(knowledge_graph.get("connection_requirements", [])):
        if not isinstance(req, dict):
            continue
        between = req.get("between")
        if not isinstance(between, list) or len(between) < 2:
            warnings.append(f"kg_requirement[{idx}] invalid between")
            continue
        a_comp = between[0]
        b_comp = between[1]
        if not isinstance(a_comp, str) or not isinstance(b_comp, str):
            warnings.append(f"kg_requirement[{idx}] invalid component ids")
            continue
        if a_comp not in component_ids or b_comp not in component_ids:
            warnings.append(f"kg_requirement[{idx}] component not in contract")
            continue

        roles_list = [r for r in req.get("roles", []) if isinstance(r, str)] if isinstance(req.get("roles"), list) else []
        attachment_type = _attachment_type_from_requirement(req)
        if attachment_type not in allowed_attachments:
            attachment_type = "rigid" if "rigid" in allowed_attachments else next(iter(allowed_attachments), "rigid")

        a_iface = _pick_interface_by_role(
            component_id=a_comp,
            desired_roles=roles_list,
            interfaces_by_component=interfaces_by_component,
            interface_map=reasoner.interface_map,
        )
        b_iface = _pick_interface_by_role(
            component_id=b_comp,
            desired_roles=roles_list,
            interfaces_by_component=interfaces_by_component,
            interface_map=reasoner.interface_map,
        )
        if not a_iface or not b_iface:
            warnings.append(f"kg_requirement[{idx}] no interfaces for endpoint component")
            continue

        req_id = req.get("id") if isinstance(req.get("id"), str) else f"kg_req_{idx}"
        req_semantics = req.get("connection_semantics") if isinstance(req.get("connection_semantics"), dict) else None
        assembly_relations.append(
            {
                "relation_id": req_id,
                "attachment_type": attachment_type,
                "from": {"component_id": a_comp, "interface_id": a_iface},
                "to": {"component_id": b_comp, "interface_id": b_iface},
                "connection_semantics": req_semantics,
                "source": "knowledge_graph_connection_requirements",
                "semantic_reason": (
                    f"From KG connection_requirement '{req_id}' purpose='{req.get('purpose')}' roles={roles_list}"
                ),
            }
        )

        connection_decision = req.get("connection_decision") if isinstance(req.get("connection_decision"), Mapping) else {}
        fastener_component_id = connection_decision.get("fastener_ref_component_id")
        reference_component_id = None
        if isinstance(req_semantics, Mapping):
            reference_component_id = req_semantics.get("reference_component_id")
        if not isinstance(reference_component_id, str) or not reference_component_id:
            reference_component_id = a_comp
        fastener_relation_semantics = copy.deepcopy(req_semantics) if isinstance(req_semantics, Mapping) else {}
        if isinstance(fastener_component_id, str) and fastener_component_id in component_ids and reference_component_id in component_ids:
            hole_axis_interface_id = _hole_axis_interface_name(req_id)
            fastener_relation_semantics["reference_component_id"] = fastener_component_id
            fastener_relation_semantics["moving_component_id"] = reference_component_id
            fastener_relation_semantics["reference_interface_hint"] = "shaft_axis"
            fastener_relation_semantics["assembly_reference_interface_hint"] = "shaft_axis"
            fastener_relation_semantics["moving_interface_hint"] = hole_axis_interface_id
            fastener_relation_semantics["assembly_moving_interface_hint"] = hole_axis_interface_id
            fastener_relation_semantics["relation_type"] = "fastener_shaft_to_hole_axis"
            assembly_relations.append(
                {
                    "relation_id": f"{req_id}__fastener_mount",
                    "attachment_type": "rigid",
                    "from": {"component_id": fastener_component_id, "interface_id": "shaft_axis"},
                    "to": {"component_id": reference_component_id, "interface_id": hole_axis_interface_id},
                    "connection_semantics": fastener_relation_semantics,
                    "source": "knowledge_graph_connection_requirements_fastener",
                    "semantic_reason": (
                        f"From KG connection_requirement '{req_id}' fastener '{fastener_component_id}' mounted to hole axis '{hole_axis_interface_id}'"
                    ),
                }
            )

        kg_relation_count += 1

    # Get LLM inferences (optional)
    llm_decisions: Dict[str, Dict[str, Any]] = {}
    if use_llm_assembly_intent:
        llm_decisions = reasoner.get_llm_decisions(kg_component_ids, knowledge_graph=knowledge_graph)
    
    # Process KG relations (legacy field; deterministic, always included)
    for idx, rel in enumerate(knowledge_graph.get("relations", [])):
        rel_type = rel.get("type")
        attachment_type = _map_relation_type(rel_type)
        if attachment_type is None:
            warnings.append(f"kg_relation[{idx}] unsupported type: {rel_type}")
            continue

        result = _validate_relation_fields(rel)
        endpoints = result[0]
        warn = result[1]
        if warn or endpoints is None:
            warnings.append(f"kg_relation[{idx}] {warn}")
            continue

        a_comp = endpoints.get("a_component_id")
        a_iface = endpoints.get("a_interface_id")
        b_comp = endpoints.get("b_component_id")
        b_iface = endpoints.get("b_interface_id")

        if not a_comp or not b_comp or a_comp not in component_ids or b_comp not in component_ids:
            warnings.append(f"kg_relation[{idx}] component not in contract")
            continue
        
        # Auto-match interfaces
        available_a_ifaces = interfaces_by_component.get(a_comp, set())
        if a_iface not in available_a_ifaces:
            if available_a_ifaces:
                a_iface = next(iter(available_a_ifaces))
            else:
                warnings.append(f"kg_relation[{idx}] no interfaces for '{a_comp}'")
                continue
        
        available_b_ifaces = interfaces_by_component.get(b_comp, set())
        if b_iface not in available_b_ifaces:
            if available_b_ifaces:
                b_iface = next(iter(available_b_ifaces))
            else:
                warnings.append(f"kg_relation[{idx}] no interfaces for '{b_comp}'")
                continue
        
        if attachment_type not in allowed_attachments:
            warnings.append(f"kg_relation[{idx}] type not allowed")
            continue

        relation_id = rel.get("id") if isinstance(rel.get("id"), str) else None

        assembly_relations.append({
            "relation_id": relation_id or f"kg_rel_{idx}",
            "attachment_type": attachment_type,
            "from": {
                "component_id": a_comp,
                "interface_id": a_iface,
            },
            "to": {
                "component_id": b_comp,
                "interface_id": b_iface,
            },
            "source": "knowledge_graph",
            "semantic_reason": (
                f"From KG relation '{rel.get('id', idx)}' type '{rel_type}' "
                f"mapped to attachment_type '{attachment_type}'"
            ),
        })
        kg_relation_count += 1
    
    # Build deduplication index keyed by unordered component pairs.
    existing_relations_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rel in assembly_relations:
        from_comp = rel.get("from", {}).get("component_id")
        to_comp = rel.get("to", {}).get("component_id")
        if not (isinstance(from_comp, str) and isinstance(to_comp, str) and from_comp and to_comp):
            continue
        pair_key = (from_comp, to_comp) if from_comp <= to_comp else (to_comp, from_comp)
        existing_relations_by_pair.setdefault(pair_key, rel)

    # Process LLM inferences with corroboration-aware duplicate handling.
    llm_relation_count = 0
    for rel_id, decision in llm_decisions.items():
        if not decision.get("valid"):
            warnings.append(f"{rel_id} invalid pattern: {decision.get('assembly_pattern')}")
            continue

        from_comp = decision.get("from", {}).get("component_id")
        to_comp = decision.get("to", {}).get("component_id")
        if not (isinstance(from_comp, str) and isinstance(to_comp, str) and from_comp and to_comp):
            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_rejected",
                "llm_proposed": decision,
                "reason": "LLM relation missing component endpoints",
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} rejected: missing component endpoints")
            continue

        pair_key = (from_comp, to_comp) if from_comp <= to_comp else (to_comp, from_comp)
        existing_rel = existing_relations_by_pair.get(pair_key)
        attachment_type = decision.get("attachment_type")
        is_valid, error = reasoner.validate_llm_relation(decision)

        if existing_rel is not None:
            existing_attachment = existing_rel.get("attachment_type")
            if isinstance(existing_attachment, str) and existing_attachment == attachment_type:
                llm_corroborations.append(
                    {
                        "relation_id": rel_id,
                        "status": "corroborated_existing_relation",
                        "llm_proposed": decision,
                        "corroborates_relation_id": existing_rel.get("relation_id"),
                        "existing_source": existing_rel.get("source"),
                        "reason": f"LLM confirmed existing relation between '{from_comp}' and '{to_comp}'",
                    }
                )
                warnings.append(f"{rel_id} corroborated: {from_comp} ? {to_comp}")
                continue

            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_conflict",
                "llm_proposed": decision,
                "reason": (
                    f"Conflicting relation for '{from_comp}' and '{to_comp}': "
                    f"existing attachment_type='{existing_attachment}', llm attachment_type='{attachment_type}'"
                ),
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} conflict: {from_comp} ? {to_comp}")
            continue

        if not is_valid:
            override = {
                "relation_id": rel_id,
                "override_type": "assembly_relation_rejected",
                "llm_proposed": decision,
                "reason": error or "Engineering constraint violation"
            }
            all_overrides.append(override)
            warnings.append(f"{rel_id} rejected: {error}")
            continue

        accepted_relation = {
            "relation_id": rel_id,
            "attachment_type": attachment_type,
            "from": decision.get("from"),
            "to": decision.get("to"),
            "source": "llm_inference",
            "semantic_reason": (
                f"LLM inferred pattern '{decision.get('assembly_pattern')}': "
                f"{decision.get('rationale', 'semantic reasoning')}"
            ),
        }
        assembly_relations.append(accepted_relation)
        existing_relations_by_pair[pair_key] = accepted_relation
        llm_relation_count += 1
    assembly_relations = _augment_subcomponent_internal_relations(
        assembly_relations=assembly_relations,
        knowledge_graph=knowledge_graph,
        interfaces_by_component=interfaces_by_component,
        interface_map=reasoner.interface_map,
        warnings=warnings,
    )
    
    # Deterministic consistency enforcement (interface occupancy + pair uniqueness + DOF annotation)
    assembly_relations, consistency_warnings, consistency_overrides, consistency_summary, dropped_relation_audit = _enforce_relation_consistency(
        assembly_relations
    )
    if consistency_warnings:
        warnings.extend(consistency_warnings)
    if consistency_overrides:
        all_overrides.extend(consistency_overrides)

    # Recompute source counts after consistency enforcement
    final_kg_count = 0
    final_llm_count = 0
    for rel in assembly_relations:
        source = rel.get("source")
        if source in {"knowledge_graph", "knowledge_graph_connection_requirements", "knowledge_graph_connection_requirements_fastener", "explicit_contract"}:
            final_kg_count += 1
        elif source == "llm_inference":
            final_llm_count += 1

    realization_class_map = {
        str(cid): str(rc)
        for cid, rc in dict(component_realization_classes or {}).items()
        if isinstance(cid, str) and cid and isinstance(rc, str) and rc
    }
    for rel in assembly_relations:
        if not isinstance(rel, dict):
            continue
        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}

        from_cid = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
        to_cid = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None

        from_rc = realization_class_map.get(from_cid or "", REALIZATION_CLASS_NATIVE)
        to_rc = realization_class_map.get(to_cid or "", REALIZATION_CLASS_NATIVE)

        if isinstance(from_ep, dict):
            from_ep["realization_class"] = from_rc
            rel["from"] = from_ep
        if isinstance(to_ep, dict):
            to_ep["realization_class"] = to_rc
            rel["to"] = to_ep

        hosted_relation = (
            from_rc == REALIZATION_CLASS_HOSTED_STANDARD
            or to_rc == REALIZATION_CLASS_HOSTED_STANDARD
        )
        if hosted_relation:
            rel["relation_execution_policy"] = "hosted_anchor_only"
            rel["relation_output_role"] = "validation_anchor_metadata_only"
        else:
            rel.setdefault("relation_execution_policy", "assembly_executable")
            rel.setdefault("relation_output_role", "assembly_joint_candidate")

    # Determine execution mode (more precise logic)
    has_llm_decisions = bool(llm_decisions)
    llm_corroboration_count = len(llm_corroborations)
    has_llm_accepted = final_llm_count > 0
    has_overrides = len(all_overrides) > 0
    has_kg_relations = final_kg_count > 0
    has_llm_supported = has_llm_accepted or llm_corroboration_count > 0
    
    if not has_llm_decisions:
        # No LLM attempted
        execution_mode = "deterministic"
    elif has_llm_accepted and not has_overrides:
        # LLM used, all accepted
        execution_mode = "llm_guided"
    elif has_llm_supported and has_overrides:
        # LLM used with a mix of accepted/corroborated relations and rejected/conflicting ones
        execution_mode = "hybrid"
    elif llm_corroboration_count > 0:
        # LLM agreed with deterministic relations without adding new ones
        execution_mode = "deterministic"
    elif not has_llm_supported and has_overrides:
        # LLM used, all rejected (falls back to deterministic with warnings)
        execution_mode = "deterministic"  # Special case: LLM tried but all failed
    else:
        # Fallback
        execution_mode = "deterministic"
    
    metadata = {
        "plan_id": f"assembly_semantics_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "schema_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "plan_assembly",
        "execution_mode": execution_mode,
        "execution_mode_definition": EXECUTION_MODES.get(execution_mode, {}),
        "llm": {
            "enabled": bool(use_llm_assembly_intent),
            "attempted": bool((reasoner.llm_last_audit or {}).get("attempted")),
            "api_key_present": bool((reasoner.llm_last_audit or {}).get("api_key_present")),
            "ok": bool((reasoner.llm_last_audit or {}).get("ok")),
            "error": (reasoner.llm_last_audit or {}).get("error"),
            "timeout_seconds": (reasoner.llm_last_audit or {}).get("timeout_seconds"),
            "max_attempts": (reasoner.llm_last_audit or {}).get("max_attempts"),
            "attempts": (reasoner.llm_last_audit or {}).get("attempts"),
            "errors": (reasoner.llm_last_audit or {}).get("errors"),
            "model": (reasoner.llm_last_audit or {}).get("model"),
            "base_url": (reasoner.llm_last_audit or {}).get("base_url"),
        },
        "notes": {
            "rigid_resolution": "Rigid attachment_type may be derived by deterministic rules (not failure fallback).",
            "relation_priority": "Explicit contract relations are highest priority; LLM may add new relations and corroborate compatible existing ones without being marked as rejected."
        },
        "constraint_validation": consistency_summary,
        "dropped_relation_audit": dropped_relation_audit,
    }
    
    # Record LLM decisions
    if llm_decisions:
        metadata["llm_decisions"] = {
            "count": len(llm_decisions),
            "decisions": list(llm_decisions.values())
        }
    
    if llm_corroborations:
        metadata["llm_corroborations"] = {
            "count": len(llm_corroborations),
            "records": llm_corroborations
        }

    # Record overrides
    if all_overrides:
        metadata["overrides"] = {
            "count": len(all_overrides),
            "records": all_overrides
        }
    
    # Record sources
    metadata["relation_sources"] = {
        "knowledge_graph_count": final_kg_count,
        "llm_proposed_count": len(llm_decisions),
        "llm_inference_count": final_llm_count,
        "llm_corroboration_count": llm_corroboration_count,
        "total": len(assembly_relations),
    }
    metadata["component_realization_classes"] = realization_class_map
    metadata["realization_class_summary"] = {
        "native_functional_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_NATIVE),
        "hosted_standard_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_HOSTED_STANDARD),
        "kinematic_imported_part": sum(1 for v in realization_class_map.values() if v == REALIZATION_CLASS_KINEMATIC_IMPORTED),
    }

    return {
        "metadata": metadata,
        "assembly_relations": assembly_relations,
        "warnings": warnings,
    }


def _build_modeling_connection_semantics_refinements(modeling_payload: Mapping[str, Any]) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
    placements = modeling_payload.get("connection_placements") if isinstance(modeling_payload, Mapping) else None
    if not isinstance(placements, list):
        return {}

    refinements: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        ref_comp = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
        mov_comp = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
        relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
        if not (isinstance(ref_comp, str) and ref_comp and isinstance(mov_comp, str) and mov_comp and relation_type and mechanism):
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
        target_component = interface_ref.get("component_id") if isinstance(interface_ref.get("component_id"), str) else None
        interface_name = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
        authoritative_interface_hints = placement.get("authoritative_interface_hints") if isinstance(placement.get("authoritative_interface_hints"), Mapping) else {}
        mapped_ref_hint = authoritative_interface_hints.get(ref_comp) if isinstance(authoritative_interface_hints.get(ref_comp), str) else None
        mapped_mov_hint = authoritative_interface_hints.get(mov_comp) if isinstance(authoritative_interface_hints.get(mov_comp), str) else None
        explicit_ref_hint = anchor.get("assembly_reference_interface_hint")
        if not isinstance(explicit_ref_hint, str) or not explicit_ref_hint.strip():
            explicit_ref_hint = anchor.get("reference_interface_hint")
        explicit_ref_hint = explicit_ref_hint.strip() if isinstance(explicit_ref_hint, str) and explicit_ref_hint.strip() else None
        explicit_mov_hint = anchor.get("assembly_moving_interface_hint")
        if not isinstance(explicit_mov_hint, str) or not explicit_mov_hint.strip():
            explicit_mov_hint = anchor.get("moving_interface_hint")
        explicit_mov_hint = explicit_mov_hint.strip() if isinstance(explicit_mov_hint, str) and explicit_mov_hint.strip() else None

        geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
        generic_hints = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}
        if not (isinstance(explicit_ref_hint, str) and explicit_ref_hint and explicit_ref_hint.lower() not in generic_hints):
            explicit_ref_hint = mapped_ref_hint.strip() if isinstance(mapped_ref_hint, str) and mapped_ref_hint.strip() else explicit_ref_hint
        if not (isinstance(explicit_mov_hint, str) and explicit_mov_hint and explicit_mov_hint.lower() not in generic_hints):
            explicit_mov_hint = mapped_mov_hint.strip() if isinstance(mapped_mov_hint, str) and mapped_mov_hint.strip() else explicit_mov_hint
        if support_topology == "hub_radial_slot_mount":
            if not (isinstance(explicit_mov_hint, str) and explicit_mov_hint and explicit_mov_hint.lower() not in generic_hints):
                explicit_mov_hint = "proximal_insert_face"
        if support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates":
            if not (isinstance(explicit_ref_hint, str) and explicit_ref_hint and explicit_ref_hint.lower() not in generic_hints):
                explicit_ref_hint = "distal_bore_axis"

        key = (ref_comp, mov_comp, relation_type, mechanism)
        refinement = refinements.setdefault(key, {})

        if isinstance(explicit_ref_hint, str) and explicit_ref_hint:
            refinement["reference_interface_hint"] = explicit_ref_hint
            refinement["assembly_reference_interface_hint"] = explicit_ref_hint
        if isinstance(explicit_mov_hint, str) and explicit_mov_hint:
            refinement["moving_interface_hint"] = explicit_mov_hint
            refinement["assembly_moving_interface_hint"] = explicit_mov_hint

        if target_component == ref_comp:
            preferred_ref_hint = explicit_ref_hint or interface_name
            if isinstance(preferred_ref_hint, str) and preferred_ref_hint:
                refinement["reference_interface_hint"] = preferred_ref_hint
                refinement["assembly_reference_interface_hint"] = preferred_ref_hint
            reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else None
            if isinstance(reference_anchor, Mapping):
                refinement["reference_anchor"] = copy.deepcopy(dict(reference_anchor))
        if target_component == mov_comp:
            preferred_mov_hint = explicit_mov_hint or interface_name
            if isinstance(preferred_mov_hint, str) and preferred_mov_hint:
                refinement["moving_interface_hint"] = preferred_mov_hint
                refinement["assembly_moving_interface_hint"] = preferred_mov_hint
            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else None
            if isinstance(moving_anchor, Mapping):
                refinement["moving_anchor"] = copy.deepcopy(dict(moving_anchor))

    return refinements


def _apply_modeling_connection_semantics_refinements(assembly_semantics: Dict[str, Any], modeling_payload: Mapping[str, Any]) -> None:
    relations = assembly_semantics.get("assembly_relations") if isinstance(assembly_semantics, Mapping) else None
    if not isinstance(relations, list):
        return

    refinements = _build_modeling_connection_semantics_refinements(modeling_payload)
    if not refinements:
        return

    interface_declarations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in _iter_interface_declarations(dict(modeling_payload)):
        comp_id = item.get("component_id")
        iface_name = item.get("interface_name")
        if isinstance(comp_id, str) and comp_id and isinstance(iface_name, str) and iface_name:
            interface_declarations[(comp_id, iface_name)] = item

    generic_interface_ids = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}

    def _is_generic_interface_name(interface_id: Any) -> bool:
        if not isinstance(interface_id, str):
            return True
        name = interface_id.strip().lower()
        if not name:
            return True
        return name in generic_interface_ids or name.endswith("_req")

    def _resolve_preferred_interface(component_id: str, preferred_iface: str) -> str | None:
        preferred_name = preferred_iface.strip()
        if not preferred_name or _is_generic_interface_name(preferred_name):
            return None
        direct = interface_declarations.get((component_id, preferred_name))
        if isinstance(direct, Mapping):
            usage = str(direct.get("usage") or "").strip().lower()
            if not usage or usage == "mate_surface":
                return preferred_name
        component_candidates = {
            iface_name.lower(): iface_name
            for (cid, iface_name), decl in interface_declarations.items()
            if cid == component_id and isinstance(decl, Mapping)
        }
        alias_preferences = {
            "proximal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "proximal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "distal_mount_face_min": ("axial_end_face_min", "side_face_x_min", "side_face_y_min", "bottom_face", "planar_face"),
            "distal_mount_face_max": ("axial_end_face_max", "side_face_x_max", "side_face_y_max", "top_face", "planar_face"),
            "axial_face_perimeter_min": ("axial_end_face_min", "axial_end_face", "planar_face"),
            "axial_face_perimeter_max": ("axial_end_face_max", "axial_end_face", "planar_face"),
            "radial_mount_perimeter": ("radial_outer_face", "radial_inner_face"),
        }
        for alias in alias_preferences.get(preferred_name.lower(), ()): 
            resolved = component_candidates.get(alias)
            if not isinstance(resolved, str):
                continue
            decl = interface_declarations.get((component_id, resolved))
            if not isinstance(decl, Mapping):
                continue
            usage = str(decl.get("usage") or "").strip().lower()
            if not usage or usage == "mate_surface":
                return resolved
        return None

    def _promote_endpoint_interface(endpoint: Dict[str, Any], preferred_iface: str | None) -> None:
        component_id = endpoint.get("component_id") if isinstance(endpoint.get("component_id"), str) else None
        current_iface = endpoint.get("interface_id") if isinstance(endpoint.get("interface_id"), str) else None
        if not (isinstance(component_id, str) and component_id):
            return
        if not _is_generic_interface_name(current_iface):
            return
        if not (isinstance(preferred_iface, str) and preferred_iface.strip()):
            return
        resolved_iface = _resolve_preferred_interface(component_id, preferred_iface)
        if not isinstance(resolved_iface, str) or not resolved_iface:
            return
        endpoint["interface_id"] = resolved_iface

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        semantics = rel.get("connection_semantics") if isinstance(rel.get("connection_semantics"), Mapping) else None
        if not isinstance(semantics, Mapping):
            continue
        ref_comp = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
        mov_comp = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
        relation_type = str(semantics.get("relation_type") or "").strip().lower()
        mechanism = str(semantics.get("connection_mechanism") or "").strip().lower()
        if not (isinstance(ref_comp, str) and ref_comp and isinstance(mov_comp, str) and mov_comp and relation_type and mechanism):
            continue

        refinement = refinements.get((ref_comp, mov_comp, relation_type, mechanism))
        if not isinstance(refinement, Mapping):
            continue

        merged = copy.deepcopy(dict(semantics))
        for key, value in refinement.items():
            merged[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
        rel["connection_semantics"] = merged

        ref_hint = merged.get("assembly_reference_interface_hint")
        if not isinstance(ref_hint, str) or not ref_hint.strip():
            ref_hint = merged.get("reference_interface_hint")
        mov_hint = merged.get("assembly_moving_interface_hint")
        if not isinstance(mov_hint, str) or not mov_hint.strip():
            mov_hint = merged.get("moving_interface_hint")

        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else None
        if isinstance(from_ep, dict):
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            if from_comp == ref_comp:
                _promote_endpoint_interface(from_ep, ref_hint)
            elif from_comp == mov_comp:
                _promote_endpoint_interface(from_ep, mov_hint)

        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else None
        if isinstance(to_ep, dict):
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            if to_comp == ref_comp:
                _promote_endpoint_interface(to_ep, ref_hint)
            elif to_comp == mov_comp:
                _promote_endpoint_interface(to_ep, mov_hint)
