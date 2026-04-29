"""Agent4 interface selection and assembly-step compilation."""

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

def _is_assembly_pattern_allowed(pattern: str, from_iface: Dict[str, Any], to_iface: Dict[str, Any]) -> bool:
    """
    Validate assembly pattern against interface allowed_mate_roles.
    
    Args:
        pattern: Assembly pattern from ASSEMBLY_PATTERNS
        from_iface: Interface definition from contract
        to_iface: Interface definition from contract
    
    Returns:
        True if pattern is allowed for these interfaces
    """
    if pattern not in ASSEMBLY_PATTERNS:
        return False
    
    from_roles = set(from_iface.get("allowed_mate_roles", []))
    to_roles = set(to_iface.get("allowed_mate_roles", []))
    
    # Pattern-specific validation rules (bidirectional)
    if pattern == "RIGID_MATE":
        # At least one interface must support mounting/fixation
        mounting_roles = {"mounting", "support", "fixation"}
        return bool(from_roles & mounting_roles) or bool(to_roles & mounting_roles)
    
    elif pattern == "REVOLUTE_MATE":
        # Both interfaces must support rotation OR one rotation + one support
        rotation_roles = {"rotation"}
        support_roles = {"support", "mounting"}
        has_rotation = bool(from_roles & rotation_roles) and bool(to_roles & rotation_roles)
        has_mixed = (bool(from_roles & rotation_roles) and bool(to_roles & support_roles)) or \
                    (bool(to_roles & rotation_roles) and bool(from_roles & support_roles))
        return has_rotation or has_mixed
    
    elif pattern == "SLIDER_MATE":
        # Linear motion requires support roles on both sides
        support_roles = {"support", "rotation"}  # rotation interfaces can also slide
        return bool(from_roles & support_roles) and bool(to_roles & support_roles)
    
    elif pattern == "CYLINDRICAL_MATE":
        # Cylindrical requires rotation capability
        rotation_roles = {"rotation"}
        return bool(from_roles & rotation_roles) and bool(to_roles & rotation_roles)
    
    return False


def _map_pattern_to_attachment_type(pattern: str) -> str:
    """
    Map assembly pattern to attachment type for output.
    
    Args:
        pattern: Assembly pattern from ASSEMBLY_PATTERNS enum
    
    Returns:
        Attachment type string (rigid, revolute, slider, cylindrical)
    """
    pattern_map = {
        "RIGID_MATE": "rigid",
        "REVOLUTE_MATE": "revolute",
        "SLIDER_MATE": "slider",
        "CYLINDRICAL_MATE": "cylindrical"
    }
    return pattern_map.get(pattern, "rigid")


def _generate_interface_resolution_step(
    *,
    base_id: str,
    component_id: str,
    component_id_var: str,
    body_id_var: str,
    interface_name: str,
    recipe: Dict[str, Any],
    allowed: Dict[str, Any],
    token_var: str,
    marker_var: str,
    entity_id_var: str,
    entity_kind_var: str,
) -> Dict[str, Any]:
    """Generate one RESOLVE_INTERFACE call step and capture resolved token/entity ids."""
    _require_function(allowed, "RESOLVE_INTERFACE")
    return {
        "id": base_id,
        "function": "RESOLVE_INTERFACE",
        "inputs": {
            "component_id": f"${{{component_id_var}}}",
            "body_id": f"${{{body_id_var}}}",
            "interface_name": interface_name,
            "recipe": recipe,
        },
        "capture": {
            "vars": {
                token_var: "token_id",
                marker_var: "marker_id",
                entity_id_var: "entity_id",
                entity_kind_var: "entity_kind",
            }
        },
        "metadata": {
            "selection_strategy": "interface_recipe_resolution",
            "component_id": component_id,
            "interface_name": interface_name,
        },
    }


def _attachment_type_from_requirement(req: Dict[str, Any]) -> str:
    purpose = req.get("purpose")
    roles = req.get("roles")
    raw_decision = req.get("connection_decision")
    decision: Dict[str, Any] = raw_decision if isinstance(raw_decision, dict) else {}
    method = str(decision.get("method") or "").strip().lower()
    connection_semantics = req.get("connection_semantics")
    semantics: Dict[str, Any] = connection_semantics if isinstance(connection_semantics, dict) else {}
    geometric_semantics = semantics.get("geometric_semantics")
    geom: Dict[str, Any] = geometric_semantics if isinstance(geometric_semantics, dict) else {}
    purpose_norm = str(purpose or "").strip().lower()
    relation_type = str(semantics.get("relation_type") or "").strip().lower()
    orientation_policy = str(semantics.get("orientation_policy") or "").strip().lower()
    mechanism = str(semantics.get("connection_mechanism") or "").strip().lower()
    contact_model = str(geom.get("contact_model") or "").strip().lower()
    support_topology = str(geom.get("support_topology") or "").strip().lower()

    roles_set = set(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else set()

    if (
        contact_model in {"slot_insert_with_bolted_retention", "through_bolt_clamp_in_radial_slot", "double_shear_yoke_shaft_support"}
        or support_topology in {"hub_radial_slot_mount", "double_shear_yoke_support"}
        or (mechanism == "axial_face_bolted_mount" and relation_type == "axial_face_perimeter_mount")
    ):
        return "rigid"

    if purpose_norm == "torque_transfer":
        if (
            orientation_policy == "free"
            or any(token in method for token in ("bearing", "revolute", "rotat"))
            or any(token in mechanism for token in ("bearing", "revolute"))
            or any(token in contact_model for token in ("bearing", "revolute"))
            or relation_type in {"bearing_inner_race_to_shaft", "bearing_outer_race_to_housing"}
        ):
            return "revolute"
        return "rigid"

    if "rotation" in roles_set:
        return "revolute"
    if purpose_norm in {"rotation", "rotation_support", "rotational_motion"}:
        return "revolute"
    if any(token in method for token in ("bearing", "revolute", "rotat")):
        return "revolute"
    if any(token in mechanism for token in ("bearing", "revolute")):
        return "revolute"
    if any(token in contact_model for token in ("bearing", "revolute")):
        return "revolute"

    return "rigid"


def _pick_interface_by_role(
    *,
    component_id: str,
    desired_roles: List[str],
    interfaces_by_component: Dict[str, Set[str]],
    interface_map: Dict[str, Dict[str, Any]],
) -> str | None:
    candidates = interfaces_by_component.get(component_id, set())
    if not candidates:
        return None

    role_set = set(r for r in desired_roles if isinstance(r, str))
    role_interface_hints = {
        "fixation": {"fixation_req"},
        "mounting": {"mounting_req", "mounting_req_drill_anchor"},
        "support": {"support_req"},
        "rotation": {"rotation_req"},
        "torque_transfer": {"torque_transfer_req"},
    }
    geometric_interface_prefixes = (
        "axial_end_face",
        "side_face_",
        "top_face",
        "bottom_face",
        "radial_outer_face",
        "shaft_axis",
    )

    def _score_interface(iface_id: str) -> tuple[int, int, str]:
        iface_def = interface_map.get(f"{component_id}:{iface_id}") or {}
        semantic_role = str(iface_def.get("semantic_role") or "").strip().lower()
        usage = str(iface_def.get("usage") or "").strip().lower()
        interface_name = str(iface_def.get("interface_name") or iface_id).strip().lower()
        source_interface_id = str(iface_def.get("source_interface_id") or interface_name).strip().lower()

        score = 0
        if role_set:
            if semantic_role in role_set:
                score += 30
            if usage in role_set:
                score += 20

            hinted_names: Set[str] = set()
            for role in role_set:
                hinted_names.update(role_interface_hints.get(role, set()))
            if interface_name in hinted_names or source_interface_id in hinted_names:
                score += 100
            elif interface_name.endswith("_req") or source_interface_id.endswith("_req"):
                score += 40

        if usage == "mate_surface":
            score += 5

        if any(interface_name.startswith(prefix) or source_interface_id.startswith(prefix) for prefix in geometric_interface_prefixes):
            score -= 25

        abstraction_rank = 1 if (interface_name.endswith("_req") or source_interface_id.endswith("_req")) else 0
        return score, abstraction_rank, iface_id

    if role_set:
        ranked = sorted((_score_interface(iface_id) for iface_id in candidates), key=lambda item: (-item[0], -item[1], item[2]))
        if ranked and ranked[0][0] > 0:
            return ranked[0][2]

    preferred: List[str] = []
    for iface_id in sorted(candidates):
        iface_def = interface_map.get(f"{component_id}:{iface_id}") or {}
        if iface_def.get("usage") == "mate_surface" or iface_def.get("semantic_role") == "mate_surface":
            preferred.append(iface_id)
    if preferred:
        return preferred[0]

    return sorted(candidates)[0]

def _augment_subcomponent_internal_relations(
    *,
    assembly_relations: List[Dict[str, Any]],
    knowledge_graph: Dict[str, Any],
    interfaces_by_component: Dict[str, Set[str]],
    interface_map: Dict[str, Dict[str, Any]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    components = knowledge_graph.get("components")
    if not isinstance(components, list):
        return assembly_relations

    excluded_types = {
        "fastener",
        "bolt",
        "nut",
        "washer",
        "pin",
        "bearing",
        "shaft",
        "axle",
        "spacer",
        "key",
        "fastener_set",
    }
    explicit_kinematic_types = {
        "wheel",
        "rim",
        "tire",
        "hub",
        "bearing",
        "bushing",
        "seal",
        "shaft",
        "axle",
        "spacer",
        "roller",
        "pulley",
    }

    def _is_candidate(comp: Dict[str, Any]) -> bool:
        ctype = comp.get("type")
        if isinstance(ctype, str) and ctype.strip().lower() in excluded_types:
            return False
        policy = comp.get("modeling_policy")
        if isinstance(policy, str) and policy.strip().lower() == "container_only":
            return False
        return True

    children_by_parent: Dict[str, List[str]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        by_id[cid] = comp
        parent_id = comp.get("parent_id")
        if not isinstance(parent_id, str) or not parent_id:
            parent_id = comp.get("position_parent") if isinstance(comp.get("position_parent"), str) else None
        if isinstance(parent_id, str) and parent_id:
            children_by_parent.setdefault(parent_id, []).append(cid)

    existing_pairs: Set[Tuple[str, str]] = set()
    for rel in assembly_relations:
        if not isinstance(rel, dict):
            continue
        from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
        to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}
        a = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
        b = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
        if isinstance(a, str) and a and isinstance(b, str) and b:
            pair = (a, b) if a <= b else (b, a)
            existing_pairs.add(pair)

    def _requires_explicit_internal_kinematics(component_ids: List[str]) -> bool:
        child_set = {cid for cid in component_ids if isinstance(cid, str) and cid in by_id}
        if not child_set:
            return False
        child_types = {
            str(by_id[cid].get("type") or "").strip().lower()
            for cid in child_set
            if isinstance(by_id.get(cid), dict)
        }
        if child_types & explicit_kinematic_types:
            return True

        for rel in assembly_relations:
            if not isinstance(rel, dict):
                continue
            from_ep = rel.get("from") if isinstance(rel.get("from"), dict) else {}
            to_ep = rel.get("to") if isinstance(rel.get("to"), dict) else {}
            a = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            b = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            if not (isinstance(a, str) and isinstance(b, str) and a in child_set and b in child_set):
                continue
            attachment = str(rel.get("attachment_type") or "").strip().lower()
            if attachment and attachment != "rigid":
                return True
        return False

    out = list(assembly_relations)
    for parent_id, child_ids in children_by_parent.items():
        if not isinstance(parent_id, str) or not parent_id:
            continue

        filtered = [
            cid
            for cid in sorted(set(child_ids))
            if isinstance(cid, str) and cid and isinstance(by_id.get(cid), dict) and _is_candidate(by_id[cid])
        ]
        if len(filtered) < 2:
            continue

        if _requires_explicit_internal_kinematics(filtered):
            warnings.append(
                f"auto internal relation skipped for parent '{parent_id}': explicit kinematic subcomponents require authoritative relations"
            )
            continue

        iface_by_child: Dict[str, str] = {}
        for cid in filtered:
            iface = _pick_interface_by_role(
                component_id=cid,
                desired_roles=["mate_surface"],
                interfaces_by_component=interfaces_by_component,
                interface_map=interface_map,
            )
            if isinstance(iface, str) and iface:
                iface_by_child[cid] = iface

        eligible = [cid for cid in filtered if cid in iface_by_child]
        if len(eligible) < 2:
            warnings.append(
                f"auto internal relation skipped for parent '{parent_id}': insufficient mate_surface interfaces"
            )
            continue

        anchor = eligible[0]
        for cid in eligible[1:]:
            pair = (anchor, cid) if anchor <= cid else (cid, anchor)
            if pair in existing_pairs:
                continue
            out.append(
                {
                    "relation_id": f"auto_{parent_id}_{anchor}_{cid}_rigid",
                    "attachment_type": "rigid",
                    "from": {"component_id": anchor, "interface_id": iface_by_child[anchor]},
                    "to": {"component_id": cid, "interface_id": iface_by_child[cid]},
                    "source": "auto_subcomponent_internal",
                    "semantic_reason": f"Auto-added rigid relation for siblings under parent '{parent_id}'",
                }
            )
            existing_pairs.add(pair)

    return out
def resolve_assembly_geometry(assembly_geo: Dict[str, Any], kg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase A: Resolve assembly geometry semantics into deterministic attachment types.
    This phase does NOT generate CAD steps.
    """
    connection_keys = ("connections", "attachments", "joints", "mates")
    connections = None
    for key in connection_keys:
        candidate = assembly_geo.get(key)
        if isinstance(candidate, list):
            connections = candidate
            break

    if connections is None:
        raise ValueError("Missing assembly connection definitions (connections/attachments/joints/mates)")

    def _requires_rotation(conn: Dict[str, Any]) -> bool:
        if conn.get("requires_rotation") is True:
            return True
        if conn.get("intent") == "rotational":
            return True
        from_comp = conn.get("from", {}).get("component_id")
        to_comp = conn.get("to", {}).get("component_id")
        for rel in kg.get("relations", []):
            if rel.get("requires_rotation") is True:
                return True
            rel_a = rel.get("a", {}).get("component_id")
            rel_b = rel.get("b", {}).get("component_id")
            if {from_comp, to_comp} == {rel_a, rel_b}:
                rel_type = rel.get("type")
                if rel_type in {"rotation", "torque_transfer"}:
                    return True
        for req in kg.get("connection_requirements", []):
            if req.get("requires_rotation") is True:
                return True
            between = req.get("between", [])
            if isinstance(between, list) and from_comp in between and to_comp in between:
                if req.get("purpose") in {"rotation", "torque_transfer"}:
                    return True
        return False

    resolved_connections: List[Dict[str, Any]] = []
    for idx, conn in enumerate(connections):
        if not isinstance(conn, dict):
            raise ValueError(f"Connection at index {idx} must be an object")

        conn_id = conn.get("id") or conn.get("relation_id") or f"conn_{idx}"
        from_ep = conn.get("from") or conn.get("a") or {}
        to_ep = conn.get("to") or conn.get("b") or {}

        resolved = {
            "id": conn_id,
            "from": {
                "component_id": from_ep.get("component_id"),
                "interface_id": from_ep.get("interface_id"),
            },
            "to": {
                "component_id": to_ep.get("component_id"),
                "interface_id": to_ep.get("interface_id"),
            },
        }
        if isinstance(conn.get("connection_semantics"), dict):
            resolved["connection_semantics"] = conn.get("connection_semantics")

        if conn.get("attachment_type"):
            resolved["attachment_type"] = conn.get("attachment_type")
            resolved["resolution_source"] = "explicit"
            resolved_connections.append(resolved)
            continue

        allowed = conn.get("allowed_attachment_types")
        if not isinstance(allowed, list) or not allowed:
            allowed = assembly_geo.get("allowable_attachment_types")

        if not isinstance(allowed, list) or not allowed:
            resolved["attachment_type"] = "rigid"
            resolved["resolution_source"] = "deterministic_rule"
            resolved_connections.append(resolved)
            continue

        if len(allowed) == 1:
            resolved["attachment_type"] = allowed[0]
            resolved["resolution_source"] = "single_option"
            resolved_connections.append(resolved)
            continue

        if "revolute" in allowed and _requires_rotation(conn):
            resolved["attachment_type"] = "revolute"
            resolved["resolution_source"] = "intent_rule"
            resolved_connections.append(resolved)
            continue

        if "rigid" in allowed:
            resolved["attachment_type"] = "rigid"
            resolved["resolution_source"] = "lowest_constraint_rule"
            resolved_connections.append(resolved)
            continue

        resolved["attachment_type"] = allowed[0]
        resolved["resolution_source"] = "list_fallback"
        resolved_connections.append(resolved)

    return {"resolved_connections": resolved_connections}


def compile_assembly_steps(
    assembly_semantics: Dict[str, Any],
    function_registry: Dict[str, Any],
    externally_defined_vars: Set[str] | None = None,
    available_component_names: Set[str] | None = None,
    deferred_component_names: Set[str] | None = None,
    hosted_standard_component_names: Set[str] | None = None,
    interface_manifest: Dict[str, Any] | None = None,
    interface_declarations: Dict[Tuple[str, str], Dict[str, Any]] | None = None,
    clarification_relation_ids: Set[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    def _infer_depends_on_from_var_flow(step_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        var_producer: Dict[str, str] = {}
        for step in step_list:
            if not isinstance(step, dict):
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str):
                continue
            capture = step.get("capture")
            if isinstance(capture, dict):
                vars_map = capture.get("vars")
                if isinstance(vars_map, dict):
                    for var_name in vars_map.keys():
                        if isinstance(var_name, str) and var_name not in var_producer:
                            var_producer[var_name] = step_id

        var_pattern = re.compile(r"\$\{([^}]+)\}")

        def _collect_vars(value: Any, found: List[str]) -> None:
            if isinstance(value, str):
                for var in var_pattern.findall(value):
                    found.append(var)
                return
            if isinstance(value, list):
                for item in value:
                    _collect_vars(item, found)
                return
            if isinstance(value, dict):
                for item in value.values():
                    _collect_vars(item, found)

        for step in step_list:
            if not isinstance(step, dict):
                continue
            inputs = step.get("inputs")
            if not isinstance(inputs, dict):
                continue
            found_vars: List[str] = []
            _collect_vars(inputs, found_vars)

            depends_on = step.get("depends_on")
            if not isinstance(depends_on, list):
                depends_on = []
                step["depends_on"] = depends_on

            seen = {d for d in depends_on if isinstance(d, str)}
            for var_name in found_vars:
                producer = var_producer.get(var_name)
                if not producer or producer == step.get("id"):
                    continue
                if producer in seen:
                    continue
                depends_on.append(producer)
                seen.add(producer)

        return step_list

    resolved_connections = assembly_semantics.get("assembly_relations")
    if not isinstance(resolved_connections, list):
        raise ValueError("assembly_semantics missing assembly_relations list")

    allowed = function_registry

    required_shared = [
        "RESOLVE_INTERFACE",
        "CREATE_JOINT_GEOMETRY",
    ]
    for fn in required_shared:
        _require_function(allowed, fn)

    steps: List[Dict[str, Any]] = []
    compile_warnings: List[str] = []
    compiled_constraints: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    non_executable_relations: List[Dict[str, Any]] = []

    expected_by_type: Dict[str, int] = {}
    compiled_by_type: Dict[str, int] = {}
    unresolved_by_type: Dict[str, int] = {}

    def _inc(counter: Dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1

    iface_decl_map: Dict[Tuple[str, str], Dict[str, Any]] = dict(interface_declarations or {})
    blocked_relation_ids: Set[str] = set(clarification_relation_ids or set())

    def _interface_usage(iface_decl: Mapping[str, Any]) -> str | None:
        usage = iface_decl.get("usage")
        if isinstance(usage, str) and usage.strip():
            return usage.strip()
        return None

    def _interface_geometry_type(iface_decl: Mapping[str, Any]) -> str | None:
        for key in ("geometry_type", "geom_type"):
            value = iface_decl.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        recipe = iface_decl.get("recipe")
        if isinstance(recipe, Mapping):
            value = recipe.get("geometry_type")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return None

    def _is_cylindrical_or_axis(iface_decl: Mapping[str, Any], iface_id: str) -> bool:
        gtype = _interface_geometry_type(iface_decl)
        if gtype in {"axis", "cylindrical"}:
            return True
        iface_name = iface_id.lower()
        return any(tok in iface_name for tok in ("axis", "axle", "shaft", "bore", "cyl", "hole"))

    def _lookup_interface_declaration(component_id: str, interface_id: str) -> Dict[str, Any] | None:
        direct = iface_decl_map.get((component_id, interface_id))
        if direct is not None:
            return direct
        base_component = re.sub(r"_\d+$", "", component_id)
        if base_component != component_id:
            return iface_decl_map.get((base_component, interface_id))
        return None

    def _pick_revolute_interface(component_id: str, current_iface_id: str) -> Tuple[str, Dict[str, Any]] | None:
        candidates: List[Tuple[str, Dict[str, Any]]] = []
        base_component = re.sub(r"_\d+$", "", component_id)
        for (cid, iface_id), decl in iface_decl_map.items():
            if cid != component_id and cid != base_component:
                continue
            if not isinstance(decl, dict):
                continue
            usage = _interface_usage(decl)
            if usage != "mate_surface":
                continue
            if not _is_cylindrical_or_axis(decl, iface_id):
                continue
            candidates.append((iface_id, decl))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (0 if item[0] == current_iface_id else 1, item[0]))
        return candidates[0]

    def _norm_text(value: Any) -> str:
        return value.strip().lower() if isinstance(value, str) and value.strip() else ""

    def _connection_semantics(conn: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        semantics = conn.get("connection_semantics")
        if not isinstance(semantics, Mapping):
            return {}, {}
        geometric = semantics.get("geometric_semantics")
        if not isinstance(geometric, Mapping):
            geometric = {}
        return dict(semantics), dict(geometric)

    def _apply_semantic_interface_hints(
        *,
        from_comp: str,
        to_comp: str,
        from_iface: str | None,
        to_iface: str | None,
        iface_decl_a: Dict[str, Any],
        iface_decl_b: Dict[str, Any],
        conn: Mapping[str, Any],
    ) -> Tuple[str | None, Dict[str, Any], str | None, Dict[str, Any]]:
        semantics, _ = _connection_semantics(conn)
        if not semantics:
            return from_iface, iface_decl_a, to_iface, iface_decl_b

        ref_comp = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
        mov_comp = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
        ref_hint = semantics.get("assembly_reference_interface_hint") if isinstance(semantics.get("assembly_reference_interface_hint"), str) else None
        if not isinstance(ref_hint, str):
            ref_hint = semantics.get("reference_interface_hint") if isinstance(semantics.get("reference_interface_hint"), str) else None
        mov_hint = semantics.get("assembly_moving_interface_hint") if isinstance(semantics.get("assembly_moving_interface_hint"), str) else None
        if not isinstance(mov_hint, str):
            mov_hint = semantics.get("moving_interface_hint") if isinstance(semantics.get("moving_interface_hint"), str) else None

        _, geometric = _connection_semantics(conn)
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
        generic_hints = {"fixation_req", "mounting_req", "mounting_req_drill_anchor", "support_req", "generic_interface", "unspecified"}

        if support_topology == "hub_radial_slot_mount":
            if not (isinstance(mov_hint, str) and mov_hint.strip() and mov_hint.strip().lower() not in generic_hints):
                mov_hint = "proximal_insert_face"
        if support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates":
            if not (isinstance(ref_hint, str) and ref_hint.strip() and ref_hint.strip().lower() not in generic_hints):
                ref_hint = "distal_bore_axis"

        def _choose(component_id: str, current_iface: str | None, current_decl: Dict[str, Any], preferred_iface: str | None) -> Tuple[str | None, Dict[str, Any]]:
            if not (isinstance(preferred_iface, str) and preferred_iface):
                return current_iface, current_decl
            preferred_decl = _lookup_interface_declaration(component_id, preferred_iface)
            if isinstance(preferred_decl, dict):
                current_usage = _interface_usage(current_decl)
                preferred_usage = _interface_usage(preferred_decl)
                if current_usage == "mate_surface" and preferred_usage not in {None, "", "mate_surface"}:
                    return current_iface, current_decl
                return preferred_iface, preferred_decl
            return current_iface, current_decl

        if from_comp == ref_comp:
            from_iface, iface_decl_a = _choose(from_comp, from_iface, iface_decl_a, ref_hint)
        elif from_comp == mov_comp:
            from_iface, iface_decl_a = _choose(from_comp, from_iface, iface_decl_a, mov_hint)

        if to_comp == ref_comp:
            to_iface, iface_decl_b = _choose(to_comp, to_iface, iface_decl_b, ref_hint)
        elif to_comp == mov_comp:
            to_iface, iface_decl_b = _choose(to_comp, to_iface, iface_decl_b, mov_hint)

        return from_iface, iface_decl_a, to_iface, iface_decl_b

    def _pick_joint_function_for_relation(*, attachment_type: str, conn: Mapping[str, Any]) -> str:
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        support_topology = str(geometric.get("support_topology") or "").strip().lower()
        axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()

        if attachment_type == "rigid":
            if (
                mechanism == "press_fit"
                or relation_type in {"bearing_outer_race_seat", "axial_face_single_bolt_mount", "bonded_tread_wrap"}
                or contact_model in {
                    "slot_insert_with_bolted_retention",
                    "through_bolt_clamp_in_radial_slot",
                    "double_shear_yoke_shaft_support",
                    "interference_cylindrical_seat",
                    "press_fit_bore",
                    "opposed_planar_clamp",
                    "radial_wrap_bond",
                    "shaft_in_bore_support",
                    "coaxial_locked_coupling",
                }
                or support_topology in {"hub_radial_slot_mount", "double_shear_yoke_support"}
                or axial_stack_policy == "wheel_body_between_support_plates"
            ):
                return _pick_function(
                    allowed,
                    ["RIGID_AS_BUILT_JOINT", "RIGID_JOINT_R1", "PLANAR_AS_BUILT_JOINT"],
                    label="rigid attachment",
                )
            return _pick_function(
                allowed,
                ["RIGID_JOINT_R1", "RIGID_AS_BUILT_JOINT", "PLANAR_AS_BUILT_JOINT"],
                label="rigid attachment",
            )

        if attachment_type == "revolute":
            if (
                contact_model in {"coaxial_revolute_fit", "bearing_inner_race_revolute_fit"}
                or mechanism == "shaft_bore_fit"
                or relation_type == "shaft_axis_to_bore"
            ):
                return _pick_function(
                    allowed,
                    ["REVOLUTE_AS_BUILT_JOINT", "REVOLUTE_JOINT_R1", "REVOLUTE_JOINT"],
                    label="revolute attachment",
                )
            return _pick_function(
                allowed,
                ["REVOLUTE_JOINT_R1", "REVOLUTE_AS_BUILT_JOINT", "REVOLUTE_JOINT"],
                label="revolute attachment",
            )

        return _pick_function(
            allowed,
            ["RIGID_JOINT_R1", "RIGID_AS_BUILT_JOINT", "PLANAR_AS_BUILT_JOINT"],
            label="rigid attachment",
        )

    def _is_geometry_only_axial_retention_relation(conn: Mapping[str, Any]) -> bool:
        if not isinstance(conn, Mapping):
            return False
        purpose = _norm_text(conn.get("purpose"))
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        return purpose == "fastening_mechanism" and (
            relation_type in {"axial_preload_retention", "axial_shaft_retention", "axial_spacer_stack"}
            or contact_model in {"axial_retention_stack", "threaded_axial_retention", "axial_face_stackup"}
        )

    def _is_non_executable_bearing_proxy_relation(conn: Mapping[str, Any]) -> bool:
        if not isinstance(conn, Mapping):
            return False
        relation_id = _norm_text(conn.get("relation_id"))
        purpose = _norm_text(conn.get("purpose"))
        semantics, geometric = _connection_semantics(conn)
        mechanism = _norm_text(semantics.get("connection_mechanism"))
        relation_type = _norm_text(semantics.get("relation_type"))
        contact_model = _norm_text(geometric.get("contact_model"))
        return (
            "bearing" in relation_id
            or purpose in {"load_support", "rotation_support", "support_to_structure"}
        ) and (
            relation_type in {"rotation_support", "bearing_inner_race_rotation_support"}
            or (purpose == "rotation_support" and mechanism == "shaft_bore_fit")
            or contact_model == "bearing_inner_race_revolute_fit"
        )

    def _connection_dup_score(conn: Mapping[str, Any]) -> int:
        relation_id = _norm_text(conn.get("relation_id"))
        score = 0
        if relation_id and "_auto_" not in relation_id:
            score += 20
        if "body_support" in relation_id:
            score += 8
        if "support_structure_auto" in relation_id:
            score -= 4
        source = _norm_text(conn.get("source"))
        if source in {"knowledge_graph", "explicit_contract", "knowledge_graph_connection_requirements", "knowledge_graph_connection_requirements_fastener"}:
            score += 4
        return score

    def _dedupe_semantic_duplicate_relations(relations: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        best_by_signature = {}
        passthrough = []
        dropped = []
        for idx, conn in enumerate(relations):
            if not isinstance(conn, dict):
                continue
            from_ep = conn.get("from") if isinstance(conn.get("from"), Mapping) else {}
            to_ep = conn.get("to") if isinstance(conn.get("to"), Mapping) else {}
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            attachment_type = _norm_text(conn.get("attachment_type"))
            semantics, _geometric = _connection_semantics(conn)
            mechanism = _norm_text(semantics.get("connection_mechanism"))
            relation_type = _norm_text(semantics.get("relation_type"))
            if not (from_comp and to_comp and attachment_type and mechanism and relation_type):
                passthrough.append((idx, conn))
                continue
            signature = (tuple(sorted((from_comp, to_comp))), attachment_type, mechanism, relation_type)
            score = _connection_dup_score(conn)
            current = best_by_signature.get(signature)
            if current is None or score > current[1] or (score == current[1] and idx < current[0]):
                if current is not None:
                    dropped_id = current[2].get("relation_id")
                    if isinstance(dropped_id, str) and dropped_id:
                        dropped.append(dropped_id)
                best_by_signature[signature] = (idx, score, conn)
            else:
                relation_id = conn.get("relation_id")
                if isinstance(relation_id, str) and relation_id:
                    dropped.append(relation_id)
        kept = passthrough + [(idx, conn) for idx, _score, conn in best_by_signature.values()]
        kept.sort(key=lambda item: item[0])
        warnings = [f"dedupe assembly relation: dropped semantic duplicate '{relation_id}'" for relation_id in dropped]
        return [conn for _idx, conn in kept], warnings

    resolved_connections, dedupe_warnings = _dedupe_semantic_duplicate_relations(resolved_connections)
    compile_warnings.extend(dedupe_warnings)

    def _find_redundant_bearing_backed_wheel_rotation_relations(relations: List[Dict[str, Any]]) -> Set[str]:
        hub_to_bearings: Dict[str, Set[str]] = {}
        axle_to_bearings: Dict[str, Set[str]] = {}

        def _endpoint_ids(conn: Mapping[str, Any]) -> Tuple[str | None, str | None]:
            from_ep = conn.get("from") if isinstance(conn.get("from"), Mapping) else {}
            to_ep = conn.get("to") if isinstance(conn.get("to"), Mapping) else {}
            from_comp = from_ep.get("component_id") if isinstance(from_ep.get("component_id"), str) else None
            to_comp = to_ep.get("component_id") if isinstance(to_ep.get("component_id"), str) else None
            return from_comp, to_comp

        for conn in relations:
            if not isinstance(conn, Mapping):
                continue
            semantics, geometric = _connection_semantics(conn)
            relation_type = _norm_text(semantics.get("relation_type"))
            contact_model = _norm_text(geometric.get("contact_model"))
            mechanism = _norm_text(semantics.get("connection_mechanism"))
            ref_id = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
            mov_id = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
            from_comp, to_comp = _endpoint_ids(conn)

            if mechanism == "press_fit" and relation_type == "bearing_outer_race_seat":
                hub_id = ref_id or from_comp or to_comp
                bearing_id = mov_id or from_comp or to_comp
                if isinstance(hub_id, str) and isinstance(bearing_id, str):
                    hub_to_bearings.setdefault(hub_id, set()).add(bearing_id)
                continue

            if mechanism == "shaft_bore_fit" and contact_model == "bearing_inner_race_revolute_fit":
                axle_id = ref_id or from_comp or to_comp
                bearing_id = mov_id or from_comp or to_comp
                if isinstance(axle_id, str) and isinstance(bearing_id, str):
                    axle_to_bearings.setdefault(axle_id, set()).add(bearing_id)

        redundant: Set[str] = set()
        for conn in relations:
            if not isinstance(conn, Mapping):
                continue
            relation_id = conn.get("relation_id") if isinstance(conn.get("relation_id"), str) else None
            if not relation_id:
                continue
            attachment_type = _norm_text(conn.get("attachment_type"))
            semantics, geometric = _connection_semantics(conn)
            relation_type = _norm_text(semantics.get("relation_type"))
            contact_model = _norm_text(geometric.get("contact_model"))
            if attachment_type != "revolute" or relation_type != "shaft_axis_to_bore" or contact_model != "coaxial_revolute_fit":
                continue

            ref_id = semantics.get("reference_component_id") if isinstance(semantics.get("reference_component_id"), str) else None
            mov_id = semantics.get("moving_component_id") if isinstance(semantics.get("moving_component_id"), str) else None
            from_comp, to_comp = _endpoint_ids(conn)
            axle_id = ref_id if isinstance(ref_id, str) and "axle" in ref_id.lower() else None
            hub_id = mov_id if isinstance(mov_id, str) and "hub" in mov_id.lower() else None
            if axle_id is None:
                for candidate in (from_comp, to_comp):
                    if isinstance(candidate, str) and "axle" in candidate.lower():
                        axle_id = candidate
                        break
            if hub_id is None:
                for candidate in (mov_id, from_comp, to_comp):
                    if isinstance(candidate, str) and "hub" in candidate.lower():
                        hub_id = candidate
                        break
            if not isinstance(axle_id, str) or not isinstance(hub_id, str):
                continue

            wheel_match = re.match(r"^wheel_(\d+)_", hub_id, flags=re.IGNORECASE) or re.match(r"^wheel_(\d+)_", axle_id, flags=re.IGNORECASE)
            if wheel_match is not None:
                candidate_hub_id = f"wheel_{wheel_match.group(1)}_hub"
                if candidate_hub_id in hub_to_bearings:
                    hub_id = candidate_hub_id

            if hub_to_bearings.get(hub_id) and axle_to_bearings.get(axle_id) and (hub_to_bearings[hub_id] & axle_to_bearings[axle_id]):
                redundant.add(relation_id)

        return redundant

    redundant_bearing_backed_rotation_ids = _find_redundant_bearing_backed_wheel_rotation_relations(resolved_connections)

    logical_component_ids: Set[str] = set()
    ext_vars = set(externally_defined_vars or set())
    non_assembly_relation_ids: Set[str] = set()
    hosted_standard_names = set(hosted_standard_component_names or set())

    deferred_names = set(deferred_component_names or set())
    resolvable_names: Set[str] = set(available_component_names or set()) | deferred_names

    for idx, conn in enumerate(resolved_connections, start=1):
        relation_id = conn.get("relation_id") if isinstance(conn, dict) and isinstance(conn.get("relation_id"), str) else f"connection_{idx}"
        if not isinstance(conn, dict):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "reason_code": "invalid_relation_payload",
                    "reason": "relation item is not an object",
                }
            )
            _inc(unresolved_by_type, "unknown")
            continue

        attachment_raw = conn.get("attachment_type")
        attachment_type = attachment_raw if isinstance(attachment_raw, str) and attachment_raw else "unknown"
        if _is_geometry_only_axial_retention_relation(conn):
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' is geometry-only axial retention and will not be compiled into an assembly joint"
            )
            continue
        if _is_non_executable_bearing_proxy_relation(conn):
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' targets a single-occurrence bearing proxy and will not be compiled into an assembly joint"
            )
            continue
        if relation_id in redundant_bearing_backed_rotation_ids:
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' is redundant because wheel rotation is already mediated by a bearing inner-race revolute plus outer-race seat"
            )
            continue
        _inc(expected_by_type, attachment_type)

        from_ep_raw = conn.get("from")
        to_ep_raw = conn.get("to")
        from_ep: Dict[str, Any] = from_ep_raw if isinstance(from_ep_raw, dict) else {}
        to_ep: Dict[str, Any] = to_ep_raw if isinstance(to_ep_raw, dict) else {}
        from_comp_raw = from_ep.get("component_id")
        to_comp_raw = to_ep.get("component_id")
        from_iface_raw = from_ep.get("interface_id")
        to_iface_raw = to_ep.get("interface_id")
        from_iface = from_iface_raw if isinstance(from_iface_raw, str) and from_iface_raw else None
        to_iface = to_iface_raw if isinstance(to_iface_raw, str) and to_iface_raw else None

        from_comp = from_comp_raw if isinstance(from_comp_raw, str) and from_comp_raw else None
        to_comp = to_comp_raw if isinstance(to_comp_raw, str) and to_comp_raw else None

        hosted_endpoints: List[str] = []
        if isinstance(from_comp, str) and from_comp in hosted_standard_names:
            hosted_endpoints.append(from_comp)
        if isinstance(to_comp, str) and to_comp in hosted_standard_names:
            hosted_endpoints.append(to_comp)
        if hosted_endpoints:
            non_assembly_relation_ids.add(relation_id)
            compile_warnings.append(
                f"skip connection[{idx}]: relation '{relation_id}' touches hosted standard part endpoint(s) "
                f"{', '.join(sorted(set(hosted_endpoints)))} and will not be compiled into an assembly joint"
            )
            non_executable_relations.append(
                {
                    "relation_id": relation_id,
                    "status": "non_executable",
                    "reason_code": "hosted_standard_part_endpoint",
                    "reason": "relation endpoint is a hosted standard part; placement is anchor-driven, no joint emitted",
                    "relation_execution_policy": "hosted_anchor_only",
                    "relation_output_role": "validation_anchor_metadata_only",
                    "hosted_endpoints": sorted(set(hosted_endpoints)),
                    "attachment_type": attachment_type,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                    "connection_semantics": conn.get("connection_semantics"),
                }
            )
            continue

        if relation_id in blocked_relation_ids:
            compile_warnings.append(
                f"skip connection[{idx}]: geometry semantics marked relation '{relation_id}' as requires_clarification"
            )
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "geometry_requires_clarification",
                    "reason": "geometry semantics marked relation requires_clarification; assembly joint generation skipped until anchor semantics are explicit",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if from_comp is not None:
            logical_component_ids.add(from_comp)
        if to_comp is not None:
            logical_component_ids.add(to_comp)

        if attachment_type not in {"rigid", "revolute"}:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "unsupported_attachment_type",
                    "reason": f"Unsupported attachment_type: {attachment_type}",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue
        function_name = _pick_joint_function_for_relation(
            attachment_type=attachment_type,
            conn=conn,
        )

        if resolvable_names:
            if from_comp is not None:
                from_comp = _resolve_collection_component_name(from_comp, resolvable_names)
            if to_comp is not None:
                to_comp = _resolve_collection_component_name(to_comp, resolvable_names)

        if not from_comp or not to_comp:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_component",
                    "reason": "from/to endpoint missing component_id",
                    "from": from_ep,
                    "to": to_ep,
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        missing_components: List[str] = []
        if available_component_names and from_comp not in available_component_names and from_comp not in deferred_names:
            missing_components.append(from_comp)
        if available_component_names and to_comp not in available_component_names and to_comp not in deferred_names:
            missing_components.append(to_comp)
        if missing_components:
            reason = f"components not in geometry plan: {', '.join(sorted(set(missing_components)))}"
            compile_warnings.append(f"skip connection[{idx}]: {reason}")
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "component_not_in_geometry_plan",
                    "reason": reason,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        # Audit trail: endpoints that will be injected later by compose_plan.
        if (from_comp in deferred_names) or (to_comp in deferred_names):
            deferred_eps = []
            if from_comp in deferred_names:
                deferred_eps.append(from_comp)
            if to_comp in deferred_names:
                deferred_eps.append(to_comp)
            compile_warnings.append(
                f"deferred endpoint(s) for connection[{idx}] (standard parts injected later): {', '.join(sorted(set(deferred_eps)))}"
            )

        if attachment_type == "rigid" and (not from_iface or not to_iface):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_interface",
                    "reason": "rigid relation missing interface_id on endpoint",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if not from_iface or not to_iface:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_endpoint_interface",
                    "reason": "relation endpoint missing interface_id",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        iface_decl_a = _lookup_interface_declaration(from_comp, from_iface)
        iface_decl_b = _lookup_interface_declaration(to_comp, to_iface)
        if not isinstance(iface_decl_a, dict) or not isinstance(iface_decl_b, dict):
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_interface_declaration",
                    "reason": "missing interface_declarations entry for relation endpoint",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        from_iface, iface_decl_a, to_iface, iface_decl_b = _apply_semantic_interface_hints(
            from_comp=from_comp,
            to_comp=to_comp,
            from_iface=from_iface,
            to_iface=to_iface,
            iface_decl_a=iface_decl_a,
            iface_decl_b=iface_decl_b,
            conn=conn,
        )

        usage_a = _interface_usage(iface_decl_a)
        usage_b = _interface_usage(iface_decl_b)
        if usage_a != "mate_surface" or usage_b != "mate_surface":
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "invalid_interface_usage",
                    "reason": "assembly constraints allow only usage=mate_surface interfaces",
                    "from": {"component_id": from_comp, "interface_id": from_iface, "usage": usage_a},
                    "to": {"component_id": to_comp, "interface_id": to_iface, "usage": usage_b},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        if attachment_type == "revolute":
            if not _is_cylindrical_or_axis(iface_decl_a, from_iface):
                picked_a = _pick_revolute_interface(from_comp, from_iface)
                if picked_a is not None:
                    from_iface, iface_decl_a = picked_a
                    compile_warnings.append(
                        f"connection[{idx}] switched revolute from-interface to cylindrical/axis candidate: {from_comp}:{from_iface}"
                    )
            if not _is_cylindrical_or_axis(iface_decl_b, to_iface):
                picked_b = _pick_revolute_interface(to_comp, to_iface)
                if picked_b is not None:
                    to_iface, iface_decl_b = picked_b
                    compile_warnings.append(
                        f"connection[{idx}] switched revolute to-interface to cylindrical/axis candidate: {to_comp}:{to_iface}"
                    )

            if not _is_cylindrical_or_axis(iface_decl_a, from_iface) or not _is_cylindrical_or_axis(iface_decl_b, to_iface):
                unresolved.append(
                    {
                        "relation_id": relation_id,
                        "status": "unresolved",
                        "attachment_type": attachment_type,
                        "reason_code": "revolute_requires_cylindrical_interface",
                        "reason": "revolute assembly requires axis/cylindrical interfaces on both endpoints",
                        "from": {"component_id": from_comp, "interface_id": from_iface},
                        "to": {"component_id": to_comp, "interface_id": to_iface},
                    }
                )
                _inc(unresolved_by_type, attachment_type)
                continue

        recipe_a = iface_decl_a.get("recipe") if isinstance(iface_decl_a.get("recipe"), dict) else None
        recipe_b = iface_decl_b.get("recipe") if isinstance(iface_decl_b.get("recipe"), dict) else None
        if recipe_a is None or recipe_b is None:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_interface_recipe",
                    "reason": "interface declaration missing recipe",
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        base_id = f"asm_{idx:02d}_{attachment_type}"
        body_a_var = f"{from_comp}_body_id"
        body_b_var = f"{to_comp}_body_id"
        token_a_var = f"{base_id}_token_a"
        token_b_var = f"{base_id}_token_b"
        marker_a_var = f"{base_id}_marker_a"
        marker_b_var = f"{base_id}_marker_b"
        entity_a_var = f"{base_id}_entity_a"
        entity_b_var = f"{base_id}_entity_b"
        kind_a_var = f"{base_id}_kind_a"
        kind_b_var = f"{base_id}_kind_b"
        geom_a_var = f"{base_id}_geom_a"
        geom_b_var = f"{base_id}_geom_b"
        occ_a_var = f"{from_comp}_occurrence_id"
        occ_b_var = f"{to_comp}_occurrence_id"
        comp_a_var = f"{from_comp}_component_id"
        comp_b_var = f"{to_comp}_component_id"

        required_vars = [body_a_var, body_b_var, occ_a_var, occ_b_var, comp_a_var, comp_b_var]
        missing_vars = [var_name for var_name in required_vars if var_name not in ext_vars]
        if missing_vars:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "missing_execution_vars",
                    "reason": "required execution vars not available for assembly compilation",
                    "missing_vars": missing_vars,
                    "from": {"component_id": from_comp, "interface_id": from_iface},
                    "to": {"component_id": to_comp, "interface_id": to_iface},
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        steps.append(
            _generate_interface_resolution_step(
                base_id=f"{base_id}_resolve_a",
                component_id=from_comp,
                component_id_var=comp_a_var,
                body_id_var=body_a_var,
                interface_name=from_iface,
                recipe=recipe_a,
                allowed=allowed,
                token_var=token_a_var,
                marker_var=marker_a_var,
                entity_id_var=entity_a_var,
                entity_kind_var=kind_a_var,
            )
        )
        steps.append(
            _generate_interface_resolution_step(
                base_id=f"{base_id}_resolve_b",
                component_id=to_comp,
                component_id_var=comp_b_var,
                body_id_var=body_b_var,
                interface_name=to_iface,
                recipe=recipe_b,
                allowed=allowed,
                token_var=token_b_var,
                marker_var=marker_b_var,
                entity_id_var=entity_b_var,
                entity_kind_var=kind_b_var,
            )
        )

        steps.append(
            {
                "id": f"{base_id}_create_geom_a",
                "function": "CREATE_JOINT_GEOMETRY",
                "inputs": {
                    "entity": {"type": "marker", "marker_id": f"${{{marker_a_var}}}"},
                },
                "capture": {"vars": {geom_a_var: "joint_geometry_id"}},
            }
        )
        steps.append(
            {
                "id": f"{base_id}_create_geom_b",
                "function": "CREATE_JOINT_GEOMETRY",
                "inputs": {
                    "entity": {"type": "marker", "marker_id": f"${{{marker_b_var}}}"},
                },
                "capture": {"vars": {geom_b_var: "joint_geometry_id"}},
            }
        )

        joint_step_id = f"{base_id}_joint"
        if function_name in {
            "RIGID_JOINT_R1",
            "REVOLUTE_JOINT_R1",
            "RIGID_AS_BUILT_JOINT",
            "SLIDER_AS_BUILT_JOINT",
            "CYLINDRICAL_AS_BUILT_JOINT",
            "PLANAR_AS_BUILT_JOINT",
            "REVOLUTE_AS_BUILT_JOINT",
        }:
            joint_inputs: Dict[str, Any] = {
                "component_id": _component_var_ref(from_comp),
                "occurrence_one_id": f"${{{occ_a_var}}}",
                "occurrence_two_id": f"${{{occ_b_var}}}",
                "joint_geometry_one_id": f"${{{geom_a_var}}}",
                "joint_geometry_two_id": f"${{{geom_b_var}}}",
            }
        elif function_name == "REVOLUTE_JOINT":
            joint_inputs = {
                "component_a": _component_var_ref(from_comp),
                "component_b": _component_var_ref(to_comp),
                "axis": {"marker_id": f"${{{marker_a_var}}}"},
            }
        else:
            unresolved.append(
                {
                    "relation_id": relation_id,
                    "status": "unresolved",
                    "attachment_type": attachment_type,
                    "reason_code": "unsupported_joint_function",
                    "reason": f"Unsupported joint function: {function_name}",
                }
            )
            _inc(unresolved_by_type, attachment_type)
            continue

        steps.append(
            {
                "id": joint_step_id,
                "function": function_name,
                "inputs": joint_inputs,
            }
        )

        compiled_constraints.append(
            {
                "relation_id": relation_id,
                "status": "compiled",
                "attachment_type": attachment_type,
                "joint_function": function_name,
                "joint_step_id": joint_step_id,
                "expected_remaining_dof": conn.get("expected_remaining_dof"),
                "connection_semantics": conn.get("connection_semantics"),
                "from": {"component_id": from_comp, "interface_id": from_iface},
                "to": {"component_id": to_comp, "interface_id": to_iface},
                "selector": {
                    "from": "interface_recipe",
                    "to": "interface_recipe",
                    "mode": "resolved_interface_token",
                },
            }
        )
        _inc(compiled_by_type, attachment_type)

    _lint_component_refs(
        steps=steps,
        logical_component_ids=logical_component_ids,
        externally_defined_vars=externally_defined_vars,
    )

    expected_total = max(0, len(resolved_connections) - len(non_assembly_relation_ids))
    compiled_total = len(compiled_constraints)
    unresolved_total = len(unresolved)

    type_keys = sorted(set(expected_by_type.keys()) | set(compiled_by_type.keys()) | set(unresolved_by_type.keys()))
    by_attachment: Dict[str, Dict[str, Any]] = {}
    for key in type_keys:
        expected_count = expected_by_type.get(key, 0)
        compiled_count = compiled_by_type.get(key, 0)
        unresolved_count = unresolved_by_type.get(key, 0)
        by_attachment[key] = {
            "expected": expected_count,
            "compiled": compiled_count,
            "unresolved": unresolved_count,
            "coverage_ratio": (compiled_count / expected_count) if expected_count > 0 else 1.0,
        }

    coverage_summary = {
        "expected_relations": expected_total,
        "compiled_relations": compiled_total,
        "unresolved_relations": unresolved_total,
        "coverage_ratio": (compiled_total / expected_total) if expected_total > 0 else 1.0,
        "by_attachment_type": by_attachment,
    }

    return _infer_depends_on_from_var_flow(steps), compile_warnings, compiled_constraints, unresolved, coverage_summary, non_executable_relations
