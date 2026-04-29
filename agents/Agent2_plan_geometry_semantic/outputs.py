"""Agent2 ???????fallback ????????."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from jsonschema import Draft202012Validator
from planning.pattern_solver import estimate_inner_radius, estimate_outer_radius, solve_circular_pattern, solve_linear_pattern
from tools.event_log import append_event
from validation.validate_geometry_semantics import validate_geometry_semantics_feasibility
from agents.common_utils import read_json as _read_json, write_json as _write_json
from agents.Agent1_requirement_to_kg.transform import (
    _ensure_arm_interface_requirements,
    _normalize_fastener_bundle_semantics,
    _rewire_container_connections,
    _sanitize_fastener_bundles,
    _sanitize_instancing_annotations,
    _validate_wheel_arm_connection_topology,
)

from .common import *

def _validate_no_world_coordinates(placements: list[dict]):
    """缂佸倷鐒﹂?location 閻庢稒顨嗛宀勫礄閾忕懓绠?world 闁秆勫姈閻栵綁鏁嶉崸?y/z 闁轰焦澹嗙划宥夊箣?x/y/z 閻庢稒顨嗛宀勬晬婢舵稓绀夐梺顐ｅ笒缂嶅﹤螞閳ь剟寮婚妷锕€顣查柡鍫濐槸閻壆鐥閳?
    
    濞撴艾顑呴ˇ濠氭晬濮濈浛ttern_parameters.spacing.x/y 闁哄嫷鍨伴崢鎴犳媼閸濄儲鐣遍柨娑樼墢濞村鈧潧缍婂Λ璺ㄦ崉濠垫挾绀夊☉鎾崇У濡插憡绋夐弽顐ｆ珪闁秆勫姈閻栵綁鏁?
    """
    def _check_recursive(obj, path: str, p_id: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                # 濞撴艾顑呴ˇ? spacing闁告劕鎳愬▓鎲?y闁哄嫷鍨冲ù澶屸偓闈涚秺濡法鎹勫┑鍡楁闁?
                if "spacing" in path and k in ("x", "y"):
                    continue
                # 婵☆偀鍋撻柡?x/y/z key 濞戞挻鏌ㄩ埀顒勬？鐠愮喖寮弶搴撳亾?
                if k in ("x", "y", "z") and isinstance(v, (int, float)):
                    raise ValueError(
                        f"Placement {p_id} location 缂佸倷鐒﹂娑㈠礄閾忕懓绠?world 闁秆勫姈閻栵絿鈧稒顨嗛?{k} (閻犱警鍨扮欢? {path}.{k}): {v}"
                    )
                _check_recursive(v, f"{path}.{k}", p_id)
        elif isinstance(obj, (list, tuple)):
            # 婵☆偀鍋撻柡灞诲劙缁椾線宕楅崘鈺傛闁稿﹤鍚嬮弳鐔虹磼?
            if len(obj) == 3 and all(isinstance(x, (int, float)) for x in obj):
                raise ValueError(
                    f"Placement {p_id} location 缂佸倷鐒﹂娑㈠礄閾忕懓绠?world 闁秆勫姈閻栵綁寮幍顔剧煁 (閻犱警鍨扮欢? {path}): {obj}"
                )
            for i, item in enumerate(obj):
                _check_recursive(item, f"{path}[{i}]", p_id)
    
    for p in placements:
        loc = p.get("location", {})
        if loc:
            _check_recursive(loc, "location", p.get("connection_id", "unknown"))


def _annotate_pcd_groups(placements: list[dict]) -> None:
    """Annotate circular hole patterns with deterministic pcd_group.

    Group rule: same base connection id + same host component id.
    """
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        location = placement.get("location") if isinstance(placement.get("location"), dict) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), dict) else {}
        if not isinstance(pattern, dict):
            continue
        pattern_type = pattern.get("type") if isinstance(pattern.get("type"), str) else None
        if not isinstance(pattern_type, str) or pattern_type.lower() != "circular":
            continue

        conn_id = placement.get("connection_id") if isinstance(placement.get("connection_id"), str) else None
        base_conn = conn_id.split("@", 1)[0] if isinstance(conn_id, str) and conn_id else "unknown_connection"

        iface = location.get("interface_ref") if isinstance(location.get("interface_ref"), dict) else {}
        host_id = iface.get("component_id") if isinstance(iface.get("component_id"), str) and iface.get("component_id") else "unknown_host"
        pcd_group = f"{base_conn}@{host_id}"

        pattern["pcd_group"] = pcd_group
        location["pattern_parameters"] = pattern
        placement["location"] = location


def _canon_type(t: str) -> str:
    """Normalize component type names to canonical forms"""
    if t in {"plate", "rigid_plate"}:
        return "carrier_plate"
    return t


def _is_subassembly_component(comp: Dict[str, Any]) -> bool:
    """Return True if component should be skipped for geometry modeling.
    
    Skips:
    - type="subassembly" (logical grouping only)
    - is_modeling_unit=false (semantic presence but no independent geometry)
    
    Design: These remain in KG for connection semantics, but don't require geometry planning.
    """
    # New hard contract (preferred): kind + modeling_policy
    kind = comp.get("kind")
    if isinstance(kind, str) and kind.strip() == "assembly_node":
        return True

    mp = comp.get("modeling_policy")
    if isinstance(mp, str) and mp.strip():
        policy = mp.strip().lower()
        if policy in {"container_only", "reference_only"}:
            return True
        if policy == "must_model":
            return False

    # Backward-compat fallback when modeling_policy is missing.
    must_model = comp.get("must_model")
    if must_model is False:
        return True

    # Legacy/backward-compat fallbacks
    return comp.get("type") == "subassembly" or comp.get("is_modeling_unit") is False


def _normalize_angles_to_360(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_normalize_angles_to_360(x) for x in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, (int, float)) and isinstance(k, str) and "angle" in k.lower():
                out[k] = float(v) % 360.0
            else:
                out[k] = _normalize_angles_to_360(v)
        return out
    return obj


def generate_geometry_semantics(
    kg: Dict[str, Any],
    *,
    placement_only_ids: set[str] | None = None,
    placement_enabled: bool = True
) -> Dict[str, Any]:
    """
    Generate Geometry Semantics Plan from Knowledge Graph.
    
    DECISION AUTHORITY MODEL:
    - Agent 1 freezes shape_semantics and dimensions
    - Agent 2 only expands frozen connection requirements into interfaces
    - Engineering constraints are enforced and fail-fast on conflicts
    
    AGENT 2 RESPONSIBILITY (This agent):
    - Validate frozen shape_semantics and dimensions
    - Expand required semantic roles into interface declarations
    - Interface semantic roles (mounting, rotation, support, etc.)
    - Interface geometry types (planar, axis, cylindrical, etc.)
    
    DEFERRED TO AGENT 3 (compile_semantics_to_cad):
    - TODO_AGENT3: Spatial positioning (world origin, relative placement, coordinates)
    - TODO_AGENT3: Construction methods (sketch闁愁偅濮€xtrude, revolve, pattern, etc.)
    - TODO_AGENT3: Growth directions (axial, radial, normal)
    - TODO_AGENT3: Dependency ordering (which part builds first)
    - TODO_AGENT3: CAD API selection (Fusion 360 vs other backends)
    
    DEFERRED TO AGENT 4 (plan_assembly):
    - TODO_AGENT4: Assembly sequence (which components assemble first)
    - TODO_AGENT4: Mate constraints (rigid, revolute, slider)
    - TODO_AGENT4: Spatial relationships (distance, angle, offset)
    - TODO_AGENT4: Collision detection and avoidance
    - TODO_AGENT4: Kinematic closure validation
    
    This agent outputs PURE SEMANTICS - no implementation details.
    """
    components_all = kg.get("components", [])
    components = [c for c in components_all if not _is_subassembly_component(c)]
    component_ids = {c.get("id") for c in components if isinstance(c, dict)}

    connection_semantic_repairs: Dict[str, Any] = {
        "agent": "Agent2_plan_geometry_semantic",
        "rewire_report": {"rewired_count": 0, "rewired": []},
    }

    _normalize_fastener_bundle_semantics(kg)
    _sanitize_fastener_bundles(kg)
    _sanitize_instancing_annotations(kg)
    kg, rewired_report = _rewire_container_connections(kg)
    connection_semantic_repairs["rewire_report"] = rewired_report
    _ensure_arm_interface_requirements(kg)
    _validate_wheel_arm_connection_topology(kg)

    # Ensure parent-level role closure before extracting roles and freezing echo
    _ensure_parent_role_closure(kg)

    frozen_echo = _build_frozen_echo(kg)

    # Parse connection_requirements to extract required semantic roles per component
    # Also get interface_intents for enriched interface generation
    required_roles, interface_intents = _extract_required_roles_from_connections(kg)
    
    # Append required roles to prompt for LLM context
    required_roles_text = ""
    if required_roles:
        required_roles_text = "\nREQUIRED SEMANTIC ROLES (from connection_requirements):\n"
        for comp_id, roles in sorted(required_roles.items()):
            if comp_id in component_ids:
                required_roles_text += f"  - {comp_id}: {', '.join(sorted(roles))}\n"
    
    llm_decisions: Dict[str, Dict[str, Any]] = {}
    llm_audit: Dict[str, Any] | None = None

    # Deterministic execution layer: always build semantics from engineering rules
    semantics, all_overrides = _generate_fallback_semantics(
        kg,
        required_roles,
        interface_intents,
        llm_decisions
    )

    # LLM placement inference for connection requirements (non-binding to frozen fields)
    if placement_enabled:
        placements = _infer_connection_placements_llm(kg, only_connection_ids=placement_only_ids)
        if placements:
            _validate_no_world_coordinates(placements)
            semantics["connection_placements"] = placements

    semantics.setdefault("metadata", {})["frozen_echo"] = frozen_echo
    semantics.setdefault("metadata", {})["connection_semantic_repairs"] = connection_semantic_repairs

    # Bind shape overrides to corresponding LLM decisions (for full audit trail)
    if llm_decisions:
        semantics.setdefault("metadata", {})["llm_decisions"] = {
            "components": list(llm_decisions.values()),
            "audit": llm_audit
        }

    # Record NON-BINDING interface intents (intent only, no constraints)
    interface_intent_index = {}
    for part in semantics.get("parts", []):
        comp_id = part.get("component_id")
        if not comp_id:
            continue
        for iface in part.get("interfaces", []) or []:
            interface_id = iface.get("interface_id")
            semantic_role = iface.get("semantic_role")
            if not interface_id or not semantic_role:
                continue
            intent = _collect_interface_intent_summary(
                comp_id, interface_id, semantic_role, interface_intents
            )
            if intent:
                interface_intent_index.setdefault(comp_id, {})[interface_id] = intent
    if interface_intent_index:
        semantics.setdefault("metadata", {})["interface_intents"] = interface_intent_index
        semantics["metadata"]["intent_binding"] = "non-binding"

    # Record subassemblies (for structural awareness, not for geometric modeling)
    # Subassemblies are declared at KG top-level, not as component nodes
    # We record their existence and member relationships for downstream agents
    # This is the ONLY place where assembly structure should be declared
    kg_subassemblies = kg.get("subassemblies", [])
    if kg_subassemblies:
        subassembly_records = []
        for sa in kg_subassemblies:
            subassembly_records.append({
                "subassembly_id": sa.get("id"),
                "type": "subassembly",
                "description": sa.get("description", f"Assembly group: {sa.get('id')}"),
                "component_ids": sa.get("component_ids", []),
                "role": sa.get("role"),
                "note": "Assembly-only node (not a geometric part). Members should be modeled individually."
            })
        semantics["subassemblies"] = subassembly_records

    _assert_frozen_unchanged(kg, semantics)

    return semantics


def _extract_required_roles_from_connections(kg: Dict[str, Any]) -> tuple[Dict[str, set], Dict[str, Dict[str, list]]]:
    """
    Extract required semantic roles and interface intents from connection_requirements in KG.
    
    Generates two outputs:
    1. required_roles: Maps component_id -> set of required semantic roles
    2. interface_intents: Maps component_id -> interface_id -> list of intent objects
    
    Interface intent object structure:
    {
        "purpose": "rotation",              # connection purpose from KG
        "semantic_role": "rotation",        # inferred semantic role
        "counterpart_ids": ["shaft_1"],     # other components in this connection
        "counterpart_types": ["shaft"]      # types of counterpart components
    }
    
    Role inference rules:
    - "rotation" purpose 闁?"rotation" role
    - "structural_fixation" purpose 闁?"mounting" role
    - "load_support" / "support_to_structure" purpose 闁?"support" role
    - "structural_clamping" purpose 闁?"mounting" role
    
    Args:
        kg: Knowledge graph containing connection_requirements
    
    Returns:
        Tuple of (required_roles dict, interface_intents dict)
    """
    required_roles = {}  # component_id -> set of roles
    interface_intents = {}  # component_id -> interface_id -> list of intent objects
    
    # Build component type lookup
    comp_types = {c["id"]: c.get("type", "component") for c in kg.get("components", [])}
    
    # Purpose to semantic roles mapping (now supports multiple roles)
    purpose_to_roles = {
        "rotation": {"rotation"},
        "torque_transfer": {"rotation", "torque_transfer"},
        "structural_fixation": {"mounting", "fixation"},
        "load_support": {"support"},
        "support_to_structure": {"support"},
        "rotation_support": {"support", "rotation"},  # Bearings: combines support + rotation
        "structural_clamping": {"mounting"},
        "fastening_mechanism": {"mounting", "fixation"},
        "role_closure_rotation": {"rotation"},
        "role_closure_mounting": {"mounting"},
        "role_closure_support": {"support"},
    }
    
    # Parse connection requirements
    for conn_req in kg.get("connection_requirements", []):
        if not isinstance(conn_req, dict):
            continue
        
        purpose = conn_req.get("purpose", "")
        roles_raw = conn_req.get("roles")
        if isinstance(roles_raw, list):
            semantic_roles = {r.strip().lower() for r in roles_raw if isinstance(r, str) and r.strip()}
            if not semantic_roles:
                semantic_roles = purpose_to_roles.get(purpose, {"mounting"})
        else:
            semantic_roles = purpose_to_roles.get(purpose, {"mounting"})
        
        # Extract components and interfaces involved in this connection
        between = conn_req.get("between", {})
        
        # Handle two formats:
        # 1. Dict: {component_id_1: interface_id_1, component_id_2: interface_id_2, ...}
        # 2. List: [component_id_1, component_id_2, ...] - use __auto__ for interface_id
        if isinstance(between, dict):
            # between has structure: {component_id_1: interface_id_1, component_id_2: interface_id_2, ...}
            # Filter out subassembly IDs
            items = [(cid, iface_id) for cid, iface_id in between.items() if cid and "_sa" not in cid]
            comp_ids = [cid for cid, _ in items]
            # For each component in the connection, record its interface intent
            for i, (comp_id, interface_id) in enumerate(items):
                # Find counterpart components (other components in this connection)
                counterpart_ids = [cid for j, cid in enumerate(comp_ids) if j != i]
                counterpart_types = sorted(set(
                    comp_types.get(cid, "component") 
                    for cid in counterpart_ids
                ))
                counterpart_types = [t for t in counterpart_types if t != "component"]
                for semantic_role in semantic_roles:
                    # Create interface intent object
                    intent = {
                        "purpose": purpose,
                        "semantic_role": semantic_role,
                        "counterpart_ids": counterpart_ids,
                        "counterpart_types": counterpart_types
                    }
                    # Record the intent per interface
                    interface_intents.setdefault(comp_id, {}).setdefault(interface_id, []).append(intent)
                    # Also record the required role for this component
                    required_roles.setdefault(comp_id, set()).add(semantic_role)
        elif isinstance(between, list):
            # between is a list of component_ids: use __auto__ as interface_id
            comp_ids = between
            for comp_id in comp_ids:
                # Find counterpart components (other components in this connection)
                counterpart_ids = [cid for cid in comp_ids if cid != comp_id]
                counterpart_types = sorted(set(
                    comp_types.get(cid, "component") 
                    for cid in counterpart_ids
                ))
                counterpart_types = [t for t in counterpart_types if t != "component"]
                for semantic_role in semantic_roles:
                    # Create interface intent object
                    intent = {
                        "purpose": purpose,
                        "semantic_role": semantic_role,
                        "counterpart_ids": counterpart_ids,
                        "counterpart_types": counterpart_types
                    }
                    # Record the intent per __auto__ interface
                    interface_intents.setdefault(comp_id, {}).setdefault("__auto__", []).append(intent)
                    # Also record the required role for this component
                    required_roles.setdefault(comp_id, set()).add(semantic_role)
    
    return required_roles, interface_intents


def _extract_patterns_from_components(
    components: List[Dict[str, Any]],
    pattern_intents_by_comp: Dict[str, str] | None = None
) -> List[Dict[str, Any]]:
    """
    Extract geometric patterns from component definitions.
    
    Detects rotational symmetry by analyzing component IDs and types.
    
    PATTERN DETECTION RULES:
    1. Identify components with the same type
    2. Check if their IDs follow a numbered pattern (e.g., "wheel_arm_1", "wheel_arm_2", "wheel_arm_3")
    3. If pattern found, declare rotational_symmetry with count and component_ids
    
    AGENT 2 RESPONSIBILITY (this function):
    - Declare patterns that exist based on ID analysis
    
    AGENT 3 RESPONSIBILITY:
    - Decide whether to use circular_pattern, linear_pattern, or other construction methods
    - This function only makes semantic declarations, not implementation decisions
    
    Args:
        components: List of component definitions from KG
    
    Returns:
        List of pattern objects with structure:
        {
            "type": "rotational_symmetry",
            "count": 3,
            "component_ids": ["wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
            "base_name": "wheel_arm"  (common prefix)
        }
    """
    import re
    
    patterns = []
    
    # Group components by type
    by_type = {}
    for comp in components:
        comp_type = comp.get("type", "component")
        comp_id = comp.get("id")
        if comp_id:
            by_type.setdefault(comp_type, []).append(comp_id)
    
    # For each type, check if components follow a numbered pattern
    for comp_type, comp_ids in by_type.items():
        if len(comp_ids) < 2:
            continue  # Need at least 2 components for a pattern
        
        # Try to extract base name and numbers
        # Pattern: "base_name_N" where N is a digit
        pattern_dict = {}  # base_name -> list of (number, full_id)
        
        for comp_id in comp_ids:
            # Try to match pattern: anything ending with _digit(s)
            m = re.match(r'^(.+?)_(\d+)$', comp_id)
            if m:
                base_name = m.group(1)
                number = int(m.group(2))
                pattern_dict.setdefault(base_name, []).append((number, comp_id))
        
        # For each potential pattern, check if it's valid
        for base_name, numbered_list in pattern_dict.items():
            # Check if this is a valid pattern (sequential or at least multiple)
            if len(numbered_list) >= 2:
                # Sort by number
                numbered_list.sort(key=lambda x: x[0])
                numbers = [n for n, _ in numbered_list]
                comp_ids_sorted = [cid for _, cid in numbered_list]
                
                # Check if numbers form a sequence (consecutive or regular spacing)
                # For now, just require at least 2 components with same base name
                
                # Determine pattern type based on LLM intents
                pattern_type = "rotational_symmetry"  # Default
                if pattern_intents_by_comp:
                    llm_intents_for_pattern = {}
                    for comp_id in comp_ids_sorted:
                        if comp_id in pattern_intents_by_comp:
                            intent = pattern_intents_by_comp[comp_id]
                            llm_intents_for_pattern[comp_id] = intent
                    
                    if llm_intents_for_pattern:
                        # Use majority vote for pattern type
                        intent_counts = {}
                        for intent in llm_intents_for_pattern.values():
                            intent_counts[intent] = intent_counts.get(intent, 0) + 1
                        
                        # Find most common intent
                        if intent_counts:
                            majority_intent = max(intent_counts.items(), key=lambda x: x[1])[0]
                            if majority_intent in ["linear_symmetry", "mirror_symmetry", "rotational_symmetry"]:
                                pattern_type = majority_intent
                
                pattern = {
                    "type": pattern_type,
                    "count": len(comp_ids_sorted),
                    "component_ids": comp_ids_sorted,
                    "base_name": base_name,
                    "component_type": comp_type,
                    "detection_method": "id_analysis"  # Deterministic detection
                }
                
                # Record LLM's pattern_intent for comparison
                if pattern_intents_by_comp:
                    llm_intents = {}
                    for comp_id in comp_ids_sorted:
                        if comp_id in pattern_intents_by_comp:
                            intent = pattern_intents_by_comp[comp_id]
                            llm_intents[comp_id] = intent
                    
                    if llm_intents:
                        pattern["llm_pattern_intents"] = llm_intents
                        # Check if LLM agrees with deterministic detection
                        intents_set = set(llm_intents.values())
                        if pattern_type in intents_set:
                            pattern["llm_agreement"] = "agrees"
                        elif intents_set == {"none"}:
                            pattern["llm_agreement"] = "disagrees"
                        else:
                            pattern["llm_agreement"] = "partial"
                
                patterns.append(pattern)
    
    return patterns


def _infer_interfaces_from_component(
    comp: Dict[str, Any],
    required_roles: set | None = None,
    interface_intents: Dict[str, Dict[str, list]] | None = None,
    llm_decision: Dict[str, Any] | None = None
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Infer semantic interfaces from component definition.
    
    Returns:
        Tuple of (interfaces, overrides)
        - interfaces: List of interface definitions
        - overrides: List of override records (supplements, auto-fixes)
    
    Override record structure:
    {
        "component_id": str,
        "override_type": "interface_supplement" | "interface_auto_fix",
        "added_interfaces": [interface_id, ...],
        "reason": str
    }
    
    AUTHORITY MODEL FOR INTERFACES:
    - Connection scheme is frozen by Agent 1
    - Agent 2 only expands required roles into interfaces
    - Engineering constraints are MANDATORY and fail-fast when violated
    
    TWO-STEP PROCESS:
    
    Step 1: Expand required roles
    - Use explicit interfaces from KG if present
    - Add any missing roles from connection_requirements
    
    Step 2: Enforce engineering constraints (fail-fast)
    - Arm must have >= 2 interfaces
    - Wheel must have mounting + rotation
    - Bearing must have support + rotation
    - If missing, raise error instead of auto-adding
    
    Returns pure semantic declarations - no spatial data, no implementation details.
    
    OUTPUT (Agent 2 responsibility):
    - interface_id: unique identifier
    - description: human-readable purpose
    - semantic_role: mounting, rotation, support, etc.
    - geometry_type: planar, axis, cylindrical, etc.
    - NOTE: Intent signals are stored in metadata.interface_intents (non-binding)
    
    EXCLUDED (deferred to Agent 3):
    - reference_frame: coordinate system (origin, x/y/z axes)
    - constraint_type: rigid, pivot, slider
    - geometry_source: face IDs, edge IDs, vertex IDs
    
    Agent 3 will convert these semantic declarations into concrete geometric entities.
    
    Args:
        comp: Component definition from KG
        required_roles: Set of required semantic roles from connection_requirements
        interface_intents: Dict mapping component_id -> interface_id -> list of intent objects
        llm_decision: Unused placeholder (LLM decisions are disabled for interfaces)
    """
    if required_roles is None:
        required_roles = set()
    if interface_intents is None:
        interface_intents = {}
    
    interfaces = []
    overrides = []  # Collect all override records
    comp_type = _canon_type(comp.get("type", "component"))
    comp_id = comp.get("id")
    
    # Helper function to create interface (pure semantics only)
    def _make_interface(interface_id: str, description: str, semantic_role: str, geometry_type: str) -> Dict[str, Any]:
        geo = _infer_geometry_type_from_interface_id(interface_id, semantic_role)
        # Preserve explicit geometry_type only when it's non-empty and compatible.
        if isinstance(geometry_type, str) and geometry_type:
            geo = geometry_type
        return {
            "interface_id": interface_id,
            "description": description,
            "semantic_role": semantic_role,
            "geometry_type": geo,
            "geom_type": geo,
        }
    
    # First, check if explicit interfaces exist in KG
    explicit_interfaces = comp.get("interfaces", [])
    if explicit_interfaces:
        for iface in explicit_interfaces:
            interface_id = iface.get("interface_id")
            inferred_role = _infer_interface_role(comp_type, interface_id)
            interfaces.append(_make_interface(
                interface_id,
                iface.get("description", f"Interface: {interface_id}"),
                inferred_role,
                _infer_geometry_type_from_interface_id(interface_id, inferred_role)
            ))
        # Don't return early - still need to validate with required_roles and constraints
        # Fall through to Step 2 and Step 3
    
    # Step 1: Augment with required roles from connection_requirements
    existing_roles = {iface["semantic_role"] for iface in interfaces}
    missing_roles = required_roles - existing_roles

    if missing_roles:
        added_interface_ids = []
        reasons_per_role = {}  # Track reason for each role

        for role in sorted(missing_roles):
            geo_type = _infer_geometry_type_from_role(role)
            interface_id = f"{role}_req"
            interfaces.append(_make_interface(
                interface_id,
                f"Required {role} interface (from connection_requirements)",
                role,
                geo_type
            ))
            added_interface_ids.append(interface_id)

            # Collect which connections require this role
            role_sources = []
            if comp_id and interface_intents:
                intents_map = interface_intents.get(comp_id, {})
                for iface_id, intent_list in intents_map.items():
                    for intent in intent_list:
                        if intent.get("semantic_role") == role:
                            role_sources.append(f"{intent.get('purpose')}")
            reasons_per_role[role] = ", ".join(set(role_sources)) if role_sources else "unknown connection"

        # Record supplement from frozen connection requirements
        overrides.append({
            "component_id": comp_id,
            "override_type": "interface_supplement",
            "added_interfaces": added_interface_ids,
            "reason": f"Added required roles from connection_requirements: {', '.join(sorted(missing_roles))}",
            "role_sources": reasons_per_role
        })

    # Step 2: Enforce engineering constraints (fail-fast)
    # Step 1.5: Add standard geometric interfaces for stable anchoring/assembly.
    # These are pure semantic declarations (no CAD ids) and help downstream
    # RESOLVE_INTERFACE for holes and joints.
    shape_semantics = comp.get("shape_semantics")
    shape_type: Optional[str] = None
    if isinstance(shape_semantics, dict):
        shape_type_val = shape_semantics.get("type")
        if isinstance(shape_type_val, str):
            shape_type = shape_type_val

    existing_iface_ids = {iface.get("interface_id") for iface in interfaces if isinstance(iface, dict)}
    added_std: List[str] = []

    def _add_std(interface_id: str, description: str, semantic_role: str, geometry_type: str) -> None:
        if interface_id in existing_iface_ids:
            return
        interfaces.append(_make_interface(interface_id, description, semantic_role, geometry_type))
        existing_iface_ids.add(interface_id)
        added_std.append(interface_id)

    # Global standard interfaces: always provide a stable pair of end faces.
    # These are the most commonly referenced anchors by downstream planners.
    _add_std("axial_end_face", "Axial end face (default)", "mounting", "planar")
    _add_std("axial_end_face_max", "Axial end face (max)", "mounting", "planar")
    _add_std("axial_end_face_min", "Axial end face (min)", "mounting", "planar")

    if shape_type in {"cylindrical", "annular"}:
        _add_std("radial_outer_face", "Outer cylindrical face", "mounting", "cylindrical")
        _add_std("radial_inner_face", "Inner cylindrical face", "mounting", "cylindrical")
        _add_std("shaft_axis", "Primary axis of rotation", "rotation", "axis")

    if shape_type in {"prismatic", "box", "plate", "radial_plate"}:
        _add_std("side_face_x_max", "Side face (max X)", "mounting", "planar")
        _add_std("side_face_x_min", "Side face (min X)", "mounting", "planar")
        _add_std("side_face_y_max", "Side face (max Y)", "mounting", "planar")
        _add_std("side_face_y_min", "Side face (min Y)", "mounting", "planar")

    if comp_type == "arm":
        _add_std("proximal_insert_face", "Proximal insert face for hub-slot mounting", "mounting", "planar")
        _add_std("distal_mount_face", "Distal support pad face", "mounting", "planar")
        _add_std("distal_bore_axis", "Distal bore axis for wheel axle support", "rotation", "axis")

    if added_std:
        overrides.append(
            {
                "component_id": comp_id,
                "override_type": "interface_auto_fix",
                "added_interfaces": added_std,
                "reason": "Added standard geometric interfaces (global set)",
            }
        )

    final_roles = {iface["semantic_role"] for iface in interfaces}

    # Validate component-specific constraints only when relevant
    if comp_type == "arm" and len(interfaces) < 2:
        raise ValueError(
            f"Component '{comp_id}' type=arm requires >= 2 interfaces."
        )

    # wheel: only validate if connection_requirements specify mounting+rotation
    if comp_type == "wheel" and required_roles and not {"mounting", "rotation"}.issubset(final_roles):
        # Only raise error if these roles were actually required but not fulfilled
        missing = {"mounting", "rotation"} - final_roles
        if missing & required_roles:  # At least one missing role was required
            raise ValueError(
                f"Component '{comp_id}' type=wheel requires mounting + rotation roles. "
                f"Missing: {missing & required_roles}, found: {final_roles}"
            )

    # bearing: DO NOT enforce hardcoded role requirements
    # Different bearings serve different functions (rotating, fixed, load-bearing only, etc.)
    # Trust connection_requirements to specify the actual needed roles
    
    # General validation: if required_roles specified but not met, that's an error
    if required_roles and not required_roles.issubset(final_roles):
        raise ValueError(
            f"Component '{comp_id}' missing required roles from connections: "
            f"required={required_roles}, found={final_roles}, missing={required_roles - final_roles}"
        )

    if not interfaces and comp_type not in {"module", "subassembly"}:
        raise ValueError(
            f"Component '{comp_id}' has no interfaces after applying connection_requirements."
        )
    
    return (interfaces, overrides)


def _collect_interface_intent_summary(
    comp_id: str,
    interface_id: str,
    semantic_role: str,
    interface_intents: Dict[str, Dict[str, list]] | None
) -> Dict[str, Any] | None:
    """Collect NON-BINDING intent signals for an interface."""
    if not comp_id or not interface_id or not semantic_role or not interface_intents:
        return None

    intents_map = interface_intents.get(comp_id, {})
    direct = intents_map.get(interface_id, [])
    auto = intents_map.get("__auto__", [])
    auto_filtered = [it for it in auto if it.get("semantic_role") == semantic_role]
    intents = direct + auto_filtered

    if not intents:
        return None

    purposes = []
    seen = set()
    for it in intents:
        p = it.get("purpose")
        if p and p not in seen:
            seen.add(p)
            purposes.append(p)

    counterpart_types = sorted(set(
        t for it in intents for t in it.get("counterpart_types", [])
    ))

    return {
        "purposes": purposes,
        "counterpart_types": counterpart_types,
        "binding": False
    }


def _infer_interface_role(comp_type: str | None, interface_id: str) -> str:
    """Infer semantic role from component type and interface name"""
    if "rotate" in interface_id.lower() or "axis" in interface_id.lower():
        return "rotation"
    elif "mount" in interface_id.lower():
        return "mounting"
    elif "support" in interface_id.lower():
        return "support"
    elif "fix" in interface_id.lower() or "clamp" in interface_id.lower() or "fastener" in interface_id.lower():
        return "fixation"
    else:
        return "mounting"


def _infer_geometry_type_from_role(semantic_role: str) -> str:
    """
    Infer geometry type from semantic role.
    
    Maps canonical semantic roles to geometry types:
    - rotation: axis (rotational interface)
    - mounting: planar (surface-based connection)
    - support: planar (load-bearing surface)
    - fixation: planar (permanent attachment surface)
    """
    role_to_geometry = {
        "rotation": "axis",
        "torque_transfer": "axis",
        "mounting": "planar",
        "support": "planar",
        "fixation": "planar",
        "spacing": "planar",
        "datum": "planar",
    }
    return role_to_geometry.get(semantic_role, "complex")


def _generate_fallback_semantics(
    kg: Dict[str, Any],
    required_roles: Dict[str, set] | None = None,
    interface_intents: Dict[str, Dict[str, list]] | None = None,
    llm_decisions: Dict[str, Dict[str, Any]] | None = None
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Generate deterministic geometry semantics (LLM decisions optional).
    
    CRITICAL: This generator ONLY produces semantic declarations.
    NO construction rules, NO spatial relationships - those are Agent 3's job.
    
    Returns:
        Tuple of (semantics dict, all_overrides list)
    
    Args:
        kg: Knowledge graph
        required_roles: Dict mapping component_id to set of required semantic roles
        interface_intents: Dict mapping component_id -> interface_id -> list of intent objects
        llm_decisions: Optional abstract decisions per component from LLM layer
    """
    if required_roles is None:
        required_roles = {}
    if interface_intents is None:
        interface_intents = {}
    if llm_decisions is None:
        llm_decisions = {}
    
    components_all = kg.get("components", [])
    components = [c for c in components_all if not _is_subassembly_component(c)]
    parts = []
    all_overrides = []  # Collect all override records
    
    # Generate parts (pure semantic declarations)
    # TODO_AGENT3: Spatial positioning will be added by compile_semantics_to_cad
    # TODO_AGENT4: Assembly constraints will be added by plan_assembly
    
    # Build pattern_intent lookup from LLM decisions
    pattern_intents_by_comp = {}
    for comp_id, decision in llm_decisions.items():
        if decision.get("pattern_intent"):
            pattern_intents_by_comp[comp_id] = decision.get("pattern_intent")
    
    for comp in components:
        comp_id = comp["id"]

        dims = _get_component_dimensions(comp)
        shape_semantics = _get_component_shape_semantics(comp, dims)

        # Infer geometric features (if any)
        features = _infer_features_from_component(comp)

        # MANDATORY: Infer interfaces from component WITH required roles and interface intents
        comp_required_roles = required_roles.get(comp_id, set())
        interfaces, interface_overrides = _infer_interfaces_from_component(
            comp,
            comp_required_roles,
            interface_intents,
            None
        )
        if interface_overrides:
            all_overrides.extend(interface_overrides)
        
        part = {
            "component_id": comp_id,
            "shape_semantics": shape_semantics,
            "dimensions": dims,
            "interfaces": interfaces
            # INTENTIONALLY EXCLUDED (deferred to Agent 3):
            # - "anchor": spatial positioning strategy
            # - "construction_rule": how to build the geometry
            # - "depends_on": build order dependencies
            # - "reference_frame": coordinate system definitions
        }
        
        # Add features if present
        if features:
            part["features"] = features
        
        # Add pattern_intent if LLM provided one
        if comp_id in pattern_intents_by_comp:
            part["pattern_intent"] = pattern_intents_by_comp[comp_id]
        
        parts.append(part)
    
    # Determine execution mode based on LLM usage and overrides
    if not llm_decisions:
        execution_mode = "type_based"  # Purely deterministic, no LLM
    elif all_overrides:
        execution_mode = "hybrid"  # LLM + engineering constitution enforcement
    else:
        execution_mode = "llm_guided"  # LLM decisions fully accepted
    
    metadata: Dict[str, Any] = {
        "plan_id": f"geometry_semantics_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "schema_version": "2.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "execution_mode": execution_mode  # type_based | llm_guided | hybrid
    }
    
    # Add overrides to metadata if any occurred
    if all_overrides:
        metadata["overrides"] = {
            "count": len(all_overrides),
            "records": all_overrides
        }
    
    return {
        "metadata": metadata,
        "parts": parts,
        "patterns": _extract_patterns_from_components(
            kg.get("components", []),
            pattern_intents_by_comp
        )
    }, all_overrides


def _infer_features_from_component(comp: Dict[str, Any]) -> List[Dict[str, str]] | None:
    """
    Infer geometric features (bore, fillet, chamfer, etc.) from component type and parameters.
    
    Features are optional. Only return if component type typically has features.
    
    AGENT 2 DECLARES: feature_type and parameter names ONLY
    AGENT 3 HANDLES: construction method (sketch, extrude, chamfer operation, etc.)
    """
    comp_type = comp.get("type", "component")
    dims = _get_component_dimensions(comp)
    features = []
    
    # Hubs and wheels often have bore/hole
    if comp_type in ["hub", "wheel"]:
        hole_key = next((k for k in dims if any(h in k.lower() for h in ["hole", "bore", "shaft_hole"])), None)
        if hole_key:
            features.append({
                "feature_type": "bore",
                "diameter_param": hole_key
            })
    
    # Arms might have fillets at corners
    if comp_type == "arm":
        fillet_key = next((k for k in dims if "fillet" in k.lower()), None)
        if fillet_key:
            features.append({
                "feature_type": "fillet",
                "radius_param": fillet_key
            })
    
    # Carrier plates might have corner fillets
    if comp_type == "carrier_plate":
        fillet_key = next((k for k in dims if "fillet" in k.lower() or "corner" in k.lower()), None)
        if fillet_key:
            features.append({
                "feature_type": "fillet",
                "radius_param": fillet_key
            })
    
    # Return None if no features found (optional field)
    return features if features else None


def _generate_geometry_assembly_contract(
    semantics: Dict[str, Any],
    kg: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate formal contract between geometry planning and assembly planning.
    
    This contract is MANDATORY for assembly planning. Assembly planning agent
    MUST NOT reference any components, interfaces, or attachment types not
    explicitly listed in this contract.
    
    CONTRACT CONTENTS (Agent 2 provides):
    - components: list of component IDs and types
    - interfaces: semantic roles and geometry types
    - allowable_attachment_types: rigid, revolute, slider, etc.
    
    CONTRACT OMISSIONS (Agent 3 will add):
    - TODO_AGENT3: Actual geometric entities (faces, edges, axes)
    - TODO_AGENT3: Coordinate frames for each interface
    - TODO_AGENT3: CAD body references
    
    CONTRACT USAGE (Agent 4 consumes):
    - TODO_AGENT4: Use semantic_role + geometry_type to select mate types
    - TODO_AGENT4: Use allowed_mate_roles to validate connections
    - TODO_AGENT4: Use allowable_attachment_types for assembly strategy
    
    Args:
        semantics: Geometry semantics plan with interface declarations
        kg: Knowledge graph with design intent
    
    Returns:
        Geometry-Assembly contract conforming to geometry_assembly_contract_schema.json
    """
    parts = semantics.get("parts", [])
    kg_components = {c["id"]: c for c in kg.get("components", [])}
    
    # Extract component contracts from semantics
    components = []
    for part in parts:
        part_id = part["component_id"]
        kg_comp = kg_components.get(part_id, {})
        comp_type = kg_comp.get("type", "component")
        
        # Get declared interfaces from part
        interfaces = part.get("interfaces", [])
        if not interfaces:
            raise ValueError(
                f"Component '{part_id}' has no interfaces declared. "
                "Geometry planning MUST declare at least one interface per component."
            )
        
        # Convert interfaces to contract format
        # NOTE: This contract contains SEMANTIC information only
        # Agent 3 will enrich this with actual geometric references
        contract_interfaces = []
        for iface in interfaces:
            semantic_role = iface.get("semantic_role", "connection")
            allowed_mate_roles = _infer_allowed_mate_roles(semantic_role)
            
            contract_iface = {
                "interface_id": iface["interface_id"],
                "description": iface.get("description", f"Interface: {iface['interface_id']}"),
                "semantic_role": semantic_role,
                "allowed_mate_roles": allowed_mate_roles,
                "geometry_type": iface.get("geometry_type", "complex")
                # INTENTIONALLY EXCLUDED (Agent 3 will add):
                # - "cad_entity_reference": actual face/edge/vertex from CAD model
                # - "reference_frame": concrete coordinate system with origin and axes
                #
                # INTENTIONALLY EXCLUDED (Intent signals, not binding constraints):
                # - "intended_connections": stored in metadata.interface_intents
                # - "counterpart_types": stored in metadata.interface_intents
                # These are semantic hints for Agent 4, not rigid constraints for Agent 3
            }
            
            contract_interfaces.append(contract_iface)
        
        components.append({
            "component_id": part_id,
            "component_type": comp_type,
            "description": kg_comp.get("description", f"Component: {part_id}"),
            "interfaces": contract_interfaces
        })
    
    # Determine allowable attachment types based on interfaces
    allowable_attachment_types = _infer_allowable_attachment_types(components)
    
    # Extract design intent from KG
    design_intent = kg.get("design_intent", {}).get("description", "")
    
    contract = {
        "contract_version": "1.0.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_plan_id": semantics.get("metadata", {}).get("plan_id", "unknown"),
        "components": components,
        "allowable_attachment_types": allowable_attachment_types,
        "prohibited_degrees_of_freedom": {
            "no_translation_x": False,
            "no_translation_y": False,
            "no_translation_z": False,
            "no_rotation_x": False,
            "no_rotation_y": False,
            "no_rotation_z": False,
            "custom_constraints": []
        },
        "assembly_rules": {
            "require_ground_component": True,
            "allow_self_collision": False,
            "require_kinematic_closure": True
        },
        "metadata": {
            "geometry_agent_version": "2.0.0",
            "knowledge_graph_id": kg.get("metadata", {}).get("kg_id", "unknown"),
            "design_intent": design_intent
        }
    }
    
    # Validate contract against schema
    schema_path = Path("planning") / "geometry_assembly_contract_schema.json"
    if schema_path.exists():
        try:
            schema = _read_json(schema_path)
            validator = Draft202012Validator(schema)
            errors = list(validator.iter_errors(contract))
            if errors:
                print(f"WARNING: Contract validation failed with {len(errors)} errors:")
                for err in errors[:5]:
                    print(f"  - {err.message} at {'/'.join(str(p) for p in err.path)}")
        except Exception as e:
            print(f"WARNING: Could not validate contract: {e}")
    
    return contract


def _infer_allowed_mate_roles(semantic_role: str) -> List[str]:
    """
    Infer which semantic roles are allowed to mate with this interface.
    
    CANONICAL SEMANTIC ROLES (Agent 2 only uses these):
    - mounting: surface-based connections (mounting plates, flanges)
    - rotation: rotational connections (axes, shafts)
    - support: load-bearing connections (supports, bases)
    - fixation: permanent connections (fastening, welding, clamping)
    
    Empty list means no restrictions.
    """
    # Define compatibility matrix for the four canonical roles
    compatibility = {
        "mounting": ["mounting", "support", "fixation"],
        "rotation": ["rotation"],
        "support": ["mounting", "support"],
        "fixation": ["fixation", "mounting"]
    }
    
    return compatibility.get(semantic_role, [])


def _infer_allowable_attachment_types(components: List[Dict[str, Any]]) -> List[str]:
    """
    Infer allowable joint/attachment types from component interfaces.
    
    Returns sorted list of allowed attachment types based on semantic roles.
    """
    attachment_types = set()
    
    # Scan all interfaces to determine what types of joints are possible
    for comp in components:
        for iface in comp.get("interfaces", []):
            role = iface.get("semantic_role", "")
            
            if role in ["mounting", "support", "connection", "fastening"]:
                attachment_types.add("rigid")
            
            if role in ["rotation", "bearing", "motion_transfer"]:
                attachment_types.add("revolute")
            
            if role in ["sliding", "guide"]:
                attachment_types.add("slider")
            
            if role == "rotation" and "cylindrical" in iface.get("geometry_type", ""):
                attachment_types.add("cylindrical")
    
    # Always include rigid as fallback
    attachment_types.add("rigid")
    
    # Sort for deterministic output
    return sorted(list(attachment_types))
