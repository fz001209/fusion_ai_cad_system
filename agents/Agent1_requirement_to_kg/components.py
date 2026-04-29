"""Agent1 component cleanup, hierarchy, decomposition, dimensions, patterns, and standard-part hints."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

import yaml

from tools.catalog.bearing_catalog import (
    candidate_series_for_bore,
    find_bearing_by_designation,
    nearest_bearing_by_dims,
    select_bearing_by_series_and_bore,
)

def _infer_part_kind_and_policy(component: Mapping[str, Any]) -> tuple[str, str]:
    component_type = str(component.get("type", "")).strip().lower()
    component_id = str(component.get("id", "")).strip().lower()

    if component_type == "subassembly":
        return ("subassembly", "reference_only")
    if component_type in {"bearing"}:
        return ("bearing", "simplified_model")
    if component_type in {"shaft", "axle"}:
        return ("shaft", "must_model")
    if component_type in {"fastener", "fastener_set", "bolt_set"}:
        return ("fastener_bundle", "simplified_model")
    if component_type in {"bolt", "screw"}:
        return ("bolt", "simplified_model")
    if component_type in {"nut", "nut_set"}:
        return ("nut", "simplified_model")
    if component_type in {"washer"}:
        return ("washer", "simplified_model")
    if component_type in {"pin"}:
        return ("pin", "simplified_model")
    if component_type in {"key"}:
        return ("key", "must_model")
    if component_type in {"spacer", "standoff_set"}:
        return ("spacer", "simplified_model")
    if any(tag in component_id for tag in ("fastener", "bolt", "screw", "nut", "washer", "pin", "key", "spacer")):
        return ("connector", "simplified_model")
    if component_type:
        return ("structural", "must_model")
    return ("other", "must_model")

_ASSEMBLY_ONLY_COMPONENT_TYPES = {"subassembly", "assembly", "module"}

_PHYSICAL_PART_TYPES = {
    "arm",
    "axle",
    "bar",
    "base",
    "beam",
    "bearing",
    "block",
    "bolt",
    "body",
    "bracket",
    "bushing",
    "cap",
    "carrier",
    "clamp",
    "cover",
    "disc",
    "flange",
    "frame",
    "gear",
    "handle",
    "housing",
    "hub",
    "key",
    "nut",
    "pin",
    "plate",
    "pulley",
    "rim",
    "ring",
    "rod",
    "roller",
    "screw",
    "seal",
    "shaft",
    "shell",
    "spacer",
    "standoff",
    "tire",
    "washer",
    "wheel_arm",
}

def _has_positive_dimensions(component: Mapping[str, Any]) -> bool:
    dims = component.get("dimensions")
    if not isinstance(dims, Mapping):
        return False
    for value in dims.values():
        if isinstance(value, (int, float)) and float(value) > 0.0:
            return True
    return False

def _shape_semantics_indicates_physical_geometry(component: Mapping[str, Any]) -> bool:
    shape = component.get("shape_semantics")
    if not isinstance(shape, Mapping):
        return False
    shape_type = str(shape.get("type") or "").strip().lower()
    if shape_type and shape_type not in {"assembly_node", "unknown", "logical", "container"}:
        return True
    return any(
        key in shape
        for key in ("cross_section", "geometry_type", "profile_type", "outer_profile", "features")
    )

def _is_physical_part_candidate(component: Mapping[str, Any]) -> bool:
    component_type = str(component.get("type") or "").strip().lower()
    if component_type in _ASSEMBLY_ONLY_COMPONENT_TYPES:
        return False
    if component_type in _PHYSICAL_PART_TYPES:
        return True

    part_kind = str(component.get("part_kind") or "").strip().lower()
    if part_kind in {
        "bearing",
        "bolt",
        "connector",
        "key",
        "nut",
        "pin",
        "shaft",
        "spacer",
        "structural",
        "washer",
    }:
        return True

    return _shape_semantics_indicates_physical_geometry(component) or _has_positive_dimensions(component)

def _sanitize_dimension_sources(component: Dict[str, Any]) -> None:
    raw_sources = component.get("dimension_sources")
    if not isinstance(raw_sources, Mapping):
        return

    allowed_keys = {
        "source",
        "derived_from",
        "derived_from_component",
        "rule_id",
        "confidence",
        "usable_for_standard_part_selection",
    }
    source_aliases = {
        "explicit": "input",
        "input_requirement": "input",
        "catalog": "standard_catalog",
        "standard": "standard_catalog",
        "default": "inferred_default",
        "inferred": "inferred_default",
        "inferred_default": "inferred_default",
        "derived": "derived",
    }
    allowed_sources = {"input", "standard_catalog", "inferred_default", "derived"}

    cleaned_sources: Dict[str, Dict[str, Any]] = {}
    for dim_name, raw_meta in raw_sources.items():
        if not isinstance(dim_name, str) or not dim_name:
            continue
        if isinstance(raw_meta, Mapping):
            meta = {k: v for k, v in raw_meta.items() if k in allowed_keys}
        else:
            meta = {}

        source = meta.get("source")
        if isinstance(source, str):
            source = source_aliases.get(source.strip().lower(), source.strip().lower())
        if source not in allowed_sources:
            source = "inferred_default"
        meta["source"] = source

        confidence = meta.get("confidence")
        if isinstance(confidence, (int, float)):
            meta["confidence"] = max(0.0, min(1.0, float(confidence)))
        elif "confidence" in meta:
            meta.pop("confidence", None)

        derived_from = meta.get("derived_from")
        if "derived_from" in meta and not (
            isinstance(derived_from, list)
            and all(isinstance(item, str) for item in derived_from)
        ):
            meta.pop("derived_from", None)

        cleaned_sources[dim_name] = meta

    component["dimension_sources"] = cleaned_sources

def _normalize_component_contract_fields(kg: Dict[str, Any]) -> None:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        inferred_kind, inferred_policy = _infer_part_kind_and_policy(comp)
        part_kind = comp.get("part_kind")
        modeling_policy = comp.get("modeling_policy")
        comp["part_kind"] = part_kind if isinstance(part_kind, str) and part_kind.strip() else inferred_kind
        comp["modeling_policy"] = (
            modeling_policy if isinstance(modeling_policy, str) and modeling_policy.strip() else inferred_policy
        )
        _sanitize_dimension_sources(comp)

def _collect_component_hierarchy_candidates(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    components = payload.get("components")
    if not isinstance(components, list):
        return {}, {}

    by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id"):
            by_id[str(comp["id"])] = comp
    if not by_id:
        return {}, {}

    children_by_parent: Dict[str, List[str]] = {}
    for comp_id, comp in by_id.items():
        for parent_field in ("position_parent", "parent_id"):
            parent = comp.get(parent_field)
            if isinstance(parent, str) and parent in by_id and parent != comp_id:
                children_by_parent.setdefault(parent, []).append(comp_id)
                break

    wheel_child_types = {"rim", "tire", "hub", "axle", "bearing", "spacer", "fastener"}
    for parent_id, parent_comp in by_id.items():
        parent_type = str(parent_comp.get("type") or "").strip().lower()
        parent_shape = parent_comp.get("shape_semantics")
        parent_shape_type = (
            str(parent_shape.get("type") or "").strip().lower()
            if isinstance(parent_shape, Mapping)
            else ""
        )
        parent_id_l = parent_id.lower()
        looks_like_wheel_parent = (
            parent_type == "wheel"
            or parent_shape_type == "wheel"
            or bool(re.match(r"^wheel_\d+$", parent_id_l))
        )
        if not looks_like_wheel_parent:
            continue

        inferred_children = set(children_by_parent.get(parent_id, []))
        for cid, comp in by_id.items():
            if cid == parent_id:
                continue
            ctype = str(comp.get("type") or "").strip().lower()
            if ctype not in wheel_child_types:
                continue
            cid_l = cid.lower()
            if parent_id_l in cid_l or cid_l.startswith(f"{parent_id_l}_"):
                inferred_children.add(cid)
        if inferred_children:
            children_by_parent[parent_id] = sorted(inferred_children)

    normalized_children: Dict[str, List[str]] = {}
    for parent_id, children in children_by_parent.items():
        uniq_children = sorted(
            {
                child_id
                for child_id in children
                if isinstance(child_id, str) and child_id in by_id and child_id != parent_id
            }
        )
        if uniq_children:
            normalized_children[parent_id] = uniq_children

    return by_id, normalized_children

def _mark_component_as_container_only(comp: Dict[str, Any], *, note: str | None = None) -> None:
    comp["kind"] = "assembly_node"
    comp["is_container_only"] = True
    comp["is_container"] = True
    comp["has_geometry"] = False
    comp["must_model"] = False
    comp["modeling_policy"] = "container_only"
    comp["dimensions"] = {}
    comp["parameters"] = {}
    comp["dimension_sources"] = {}
    comp["is_modeling_unit"] = False

    shape = comp.get("shape_semantics")
    existing_note = shape.get("notes") if isinstance(shape, Mapping) else None
    final_note = note or (existing_note if isinstance(existing_note, str) and existing_note.strip() else None)
    comp["shape_semantics"] = {"type": "assembly_node"}
    if isinstance(final_note, str) and final_note.strip():
        comp["shape_semantics"]["notes"] = final_note.strip()

def _preserve_hierarchy_parent_as_physical(component: Mapping[str, Any]) -> bool:
    """True when a hierarchy parent still needs its own geometry."""
    component_type = str(component.get("type") or "").strip().lower()
    if component_type in _ASSEMBLY_ONLY_COMPONENT_TYPES or component_type in {"wheel"}:
        return False

    if component_type in _PHYSICAL_PART_TYPES:
        return True

    part_kind = str(component.get("part_kind") or "").strip().lower()
    if part_kind in {
        "bearing",
        "bolt",
        "connector",
        "key",
        "nut",
        "pin",
        "shaft",
        "spacer",
        "structural",
        "washer",
    }:
        return True

    if _has_positive_dimensions(component):
        return True

    shape = component.get("shape_semantics")
    if isinstance(shape, Mapping):
        return any(
            key in shape
            for key in ("cross_section", "geometry_type", "profile_type", "outer_profile", "features")
        )

    return False

def _mark_component_as_physical_part(comp: Dict[str, Any]) -> None:
    inferred_part_kind, inferred_policy = _infer_part_kind_and_policy(comp)
    if inferred_policy == "reference_only":
        inferred_policy = "must_model"
    comp["kind"] = "part"
    comp["part_kind"] = inferred_part_kind
    comp["must_model"] = True
    comp["modeling_policy"] = inferred_policy
    comp["is_container"] = False
    comp["is_container_only"] = False
    comp["has_geometry"] = True
    comp["is_modeling_unit"] = True

def _normalize_component_kind_and_must_model(kg: Dict[str, Any]) -> None:
    """Hard contract for hierarchy vs geometry modeling.

    - kind='assembly_node' => hierarchy-only organizer node, must_model=false
    - kind='part'          => real geometric part (may be simplified), must_model=true

    This intentionally makes downstream filtering deterministic.
    """

    components = kg.get("components", [])
    if not isinstance(components, list):
        return

    meta = kg.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        kg["metadata"] = meta
    warnings_list = meta.get("normalization_warnings")
    if not isinstance(warnings_list, list):
        warnings_list = []
        meta["normalization_warnings"] = warnings_list

    seen_ids: set[str] = set()
    dup_ids: set[str] = set()
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if isinstance(cid, str) and cid:
            if cid in seen_ids:
                dup_ids.add(cid)
            seen_ids.add(cid)
    if dup_ids:
        raise ValueError(f"Duplicate component ids in KG are forbidden: {sorted(dup_ids)}")

    def _looks_like_assembly_node(comp: Mapping[str, Any]) -> bool:
        comp_type = comp.get("type")
        part_kind = comp.get("part_kind")
        modeling_policy = comp.get("modeling_policy")
        is_container = comp.get("is_container")
        is_modeling_unit = comp.get("is_modeling_unit")
        cid = comp.get("id")
        cid_s = cid if isinstance(cid, str) else ""
        type_s = comp_type.strip().lower() if isinstance(comp_type, str) else ""
        pk_s = part_kind.strip().lower() if isinstance(part_kind, str) else ""
        mp_s = modeling_policy.strip().lower() if isinstance(modeling_policy, str) else ""

        if mp_s == "reference_only":
            return True
        if pk_s == "subassembly" or type_s in _ASSEMBLY_ONLY_COMPONENT_TYPES:
            return True
        if _is_physical_part_candidate(comp):
            return False
        if bool(is_container) is True:
            return True
        if bool(is_modeling_unit) is False and is_modeling_unit is not None:
            return True
        if "assembly" in cid_s.lower() or cid_s.lower().endswith("_module"):
            return True
        return False
    for comp in components:
        if not isinstance(comp, dict):
            continue

        cid = comp.get("id")
        comp_id = cid if isinstance(cid, str) else "<unknown>"

        kind_raw = comp.get("kind")
        kind = kind_raw.strip() if isinstance(kind_raw, str) else None
        must_model_raw = comp.get("must_model")
        must_model = must_model_raw if isinstance(must_model_raw, bool) else None

        modeling_policy = comp.get("modeling_policy")
        mp_s = modeling_policy.strip().lower() if isinstance(modeling_policy, str) else ""

        inferred_kind = "assembly_node" if _looks_like_assembly_node(comp) else "part"
        inferred_must_model = inferred_kind == "part" and mp_s != "reference_only"

        if kind not in {"assembly_node", "part"}:
            kind = inferred_kind
        if must_model is None:
            must_model = bool(inferred_must_model)

        # Auto-fix common LLM drift: never block pipeline for mixed intent.
        # If a node looks like a container (e.g. *_module) but explicitly asks to be modeled,
        # treat it as a real part. This preserves references and enables downstream geometry.
        if kind == "assembly_node" and mp_s in {"must_model", "simplified_model"}:
            warnings_list.append(
                {
                    "code": "autofix_mixed_modeling_intent",
                    "component_id": comp_id,
                    "from": {"kind": "assembly_node", "modeling_policy": mp_s},
                    "to": {"kind": "part", "must_model": True},
                    "message": "Auto-fixed mixed modeling intent: coerced assembly_node to part because modeling_policy requires geometry",
                }
            )
            kind = "part"
            must_model = True

        if kind == "assembly_node" and mp_s != "reference_only" and _is_physical_part_candidate(comp):
            inferred_part_kind, inferred_policy = _infer_part_kind_and_policy(comp)
            if inferred_policy == "reference_only":
                inferred_policy = "must_model"
            warnings_list.append(
                {
                    "code": "autofix_physical_part_mislabeled_as_assembly",
                    "component_id": comp_id,
                    "from": {
                        "kind": "assembly_node",
                        "modeling_policy": mp_s or comp.get("modeling_policy"),
                        "is_container": comp.get("is_container"),
                        "is_modeling_unit": comp.get("is_modeling_unit"),
                    },
                    "to": {
                        "kind": "part",
                        "must_model": True,
                        "modeling_policy": inferred_policy,
                        "part_kind": inferred_part_kind,
                    },
                    "message": "Auto-fixed physical component mislabeled as assembly_node because it carries geometric part evidence",
                }
            )
            comp["part_kind"] = inferred_part_kind
            comp["modeling_policy"] = inferred_policy
            mp_s = inferred_policy.lower()
            kind = "part"
            must_model = True

        # Symmetric fix: a part cannot be reference_only; coerce to assembly_node.
        if kind == "part" and mp_s == "reference_only":
            warnings_list.append(
                {
                    "code": "autofix_part_reference_only",
                    "component_id": comp_id,
                    "from": {"kind": "part", "modeling_policy": mp_s},
                    "to": {"kind": "assembly_node", "must_model": False, "modeling_policy": "reference_only"},
                    "message": "Auto-fixed invalid part contract: coerced part to assembly_node because modeling_policy=reference_only",
                }
            )
            kind = "assembly_node"
            must_model = False

        # Hard normalization: assembly_node can never be modeled.
        if kind == "assembly_node":
            comp["kind"] = "assembly_node"
            comp["must_model"] = False
            comp["modeling_policy"] = "reference_only"
            comp["is_container"] = True
            comp["is_container_only"] = True
            comp["has_geometry"] = False
            comp["is_modeling_unit"] = False
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            shape = comp.get("shape_semantics")
            notes = None
            if isinstance(shape, Mapping):
                notes = shape.get("notes")
            comp["shape_semantics"] = {"type": "assembly_node"}
            if isinstance(notes, str) and notes.strip():
                comp["shape_semantics"]["notes"] = notes
            continue

        # kind == 'part'
        if mp_s == "reference_only":
            # Parts that should not be modeled must be expressed as assembly_node.
            # This should have been auto-fixed above, but keep a safe fallback.
            comp["kind"] = "assembly_node"
            comp["must_model"] = False
            comp["modeling_policy"] = "reference_only"
            comp["is_container"] = True
            comp["is_container_only"] = True
            comp["has_geometry"] = False
            comp["is_modeling_unit"] = False
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            comp["shape_semantics"] = {"type": "assembly_node"}
            continue

        comp["kind"] = "part"
        comp["must_model"] = True if must_model is None else bool(must_model)
        comp["is_container"] = False
        comp["is_container_only"] = False
        comp["has_geometry"] = True
        comp["is_modeling_unit"] = True
        if comp["must_model"] is not True:
            warnings_list.append(
                {
                    "code": "autofix_part_must_model_false",
                    "component_id": comp_id,
                    "from": {"kind": "part", "must_model": comp.get("must_model")},
                    "to": {"kind": "part", "must_model": True},
                    "message": "Auto-fixed invalid part contract: coerced must_model to true",
                }
            )
            comp["must_model"] = True

def _promote_subassemblies_to_components(kg: Dict[str, Any]) -> None:
    """Promote subassemblies to component nodes.
    
    Each subassembly becomes BOTH:
    - An entry in subassemblies[] (semantic grouping)
    - An entry in components[] with type="subassembly" (connectable node for Agent2)
    
    This ensures Agent2's type map can recognize subassembly nodes and doesn't default to "unknown".
    """
    subassemblies = kg.get("subassemblies", [])
    if not isinstance(subassemblies, list) or not subassemblies:
        return
    
    components = kg.get("components", [])
    if not isinstance(components, list):
        components = []
        kg["components"] = components
    
    existing_component_ids = {c.get("id") for c in components if isinstance(c, Mapping)}
    
    for sa in subassemblies:
        if not isinstance(sa, Mapping):
            continue
        sa_id = sa.get("id")
        if not isinstance(sa_id, str):
            continue
        
        # Skip if already exists as component
        if sa_id in existing_component_ids:
            continue
        
        # Promote subassembly to component node
        component_entry = {
            "id": sa_id,
            "type": "subassembly",
            "role": sa.get("role", "binding"),
          "parameters": {},
          "dimensions": {},
          "dimension_sources": {},
          "shape_semantics": {"type": "complex", "notes": "subassembly"},
        }
        
        # Copy description if available
        if "description" in sa and isinstance(sa["description"], str):
            # Store description in a way that's compatible with schema
            # Schema doesn't have description field, so we skip it
            pass
        
        components.append(component_entry)
        print(f"[PROMOTE] Subassembly '{sa_id}' added to components[] with type='subassembly'")

def _annotate_component_execution_roles(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    role_map: Dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str) or not comp_id:
            continue

        ctype = str(comp.get("type") or "").strip().lower()
        is_container = bool(comp.get("is_container"))
        must_model = bool(comp.get("must_model"))
        modeling_policy = str(comp.get("modeling_policy") or "").strip().lower()

        if ctype in {"subassembly", "assembly", "module"} or is_container or (not must_model and modeling_policy == "reference_only"):
            role_map[comp_id] = "container_only"
            continue

        if ctype in {"fastener", "bearing", "spacer"} or "fastener_set" in comp_id:
            role_map[comp_id] = "standard_part_insert_only"
            continue

        role_map[comp_id] = "model_entity"

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["component_execution_roles"] = role_map

def _infer_role_in_parent(component: Mapping[str, Any]) -> str | None:
    ctype = str(component.get("type") or "").strip().lower()
    cid = str(component.get("id") or "").strip().lower()
    if ctype in {"rim", "tire", "hub", "axle"}:
        return ctype
    for tok in ("rim", "tire", "hub", "axle"):
        if tok in cid:
            return tok
    return None

def _ensure_component_hierarchy_contract(payload: Dict[str, Any]) -> None:
    by_id, children_by_parent = _collect_component_hierarchy_candidates(payload)
    if not by_id:
        return

    hierarchy: List[Dict[str, Any]] = []
    for parent_id, children in sorted(children_by_parent.items()):
        if parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        if _preserve_hierarchy_parent_as_physical(parent):
            _mark_component_as_physical_part(parent)
        else:
            _mark_component_as_container_only(
                parent,
                note="inferred_hierarchy_container_from_child_components",
            )

        uniq_children = sorted({c for c in children if c in by_id})
        if not uniq_children:
            continue
        for child_id in uniq_children:
            child = by_id[child_id]
            child["position_parent"] = parent_id
            role = _infer_role_in_parent(child)
            if role:
                child["role_in_parent"] = role
        hierarchy.append({"id": parent_id, "children": uniq_children})

    if hierarchy:
        payload["component_hierarchy"] = hierarchy

def _rewire_container_connections(kg: dict) -> Tuple[dict, dict]:
    components = kg.get("components", [])
    if not isinstance(components, list):
        return kg, {"rewired_count": 0, "rewired": []}

    connection_requirements = kg.get("connection_requirements", [])
    if not isinstance(connection_requirements, list):
        return kg, {"rewired_count": 0, "rewired": []}

    component_by_id: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id:
            component_by_id[comp_id] = comp

    def _is_container_component(component_id: str) -> bool:
        comp = component_by_id.get(component_id)
        if not isinstance(comp, dict):
            return False
        if bool(comp.get("is_container_only")):
            return True
        if bool(comp.get("is_container")):
            return True
        policy = comp.get("modeling_policy")
        if isinstance(policy, str) and policy.strip().lower() in {"container_only"}:
            return True
        return False

    children_by_parent: Dict[str, List[str]] = {}
    hierarchy = kg.get("component_hierarchy")
    if isinstance(hierarchy, list):
        for node in hierarchy:
            if not isinstance(node, Mapping):
                continue
            parent_id = node.get("id")
            children = node.get("children")
            if not isinstance(parent_id, str) or not parent_id:
                continue
            if not isinstance(children, list):
                continue
            child_ids = sorted({cid for cid in children if isinstance(cid, str) and cid in component_by_id})
            if child_ids:
                children_by_parent[parent_id] = child_ids

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        child_id = comp.get("id")
        parent_id = comp.get("position_parent")
        if isinstance(child_id, str) and child_id and isinstance(parent_id, str) and parent_id in component_by_id:
            children_by_parent.setdefault(parent_id, [])
            if child_id not in children_by_parent[parent_id]:
                children_by_parent[parent_id].append(child_id)

    for parent_id in list(children_by_parent.keys()):
        children_by_parent[parent_id] = sorted(children_by_parent[parent_id])

    rewired: List[Dict[str, Any]] = []

    def _contains_any(values: List[str], needles: set[str]) -> bool:
        for value in values:
            lower_value = value.lower()
            for needle in needles:
                if needle in lower_value:
                    return True
        return False

    def _choose_child(parent_id: str, conn: Mapping[str, Any]) -> str:
        candidates = children_by_parent.get(parent_id, [])
        if not candidates:
            raise ValueError(
                f"Container connection rewiring failed: container '{parent_id}' has no child components"
            )

        purpose = str(conn.get("purpose") or "").strip().lower()
        constraint_intent = str(conn.get("constraint_intent") or "").strip().lower()
        roles = [str(r).strip().lower() for r in conn.get("roles", []) if isinstance(r, str)] if isinstance(conn.get("roles"), list) else []
        mating_features = [str(m).strip().lower() for m in conn.get("mating_features", []) if isinstance(m, str)] if isinstance(conn.get("mating_features"), list) else []

        rotation_like = (
            purpose == "rotation"
            or constraint_intent == "revolute"
            or _contains_any(mating_features, {"axis", "seat"})
        )
        fasten_like = (
            "fasten" in purpose
            or any(role in {"fixation", "mounting"} for role in roles)
            or _contains_any(mating_features, {"through_hole", "thread_feature"})
        )

        preference_tokens: List[str] = []
        if rotation_like:
            preference_tokens = ["hub", "axle"]
        elif fasten_like:
            preference_tokens = ["hub", "spoke", "arm"]

        normalized_candidates = [(cid, cid.lower()) for cid in sorted(candidates)]
        for token in preference_tokens:
            for cid, lower_cid in normalized_candidates:
                if token in lower_cid:
                    return cid

        return sorted(candidates)[0]

    for conn in connection_requirements:
        if not isinstance(conn, dict):
            continue
        between = conn.get("between")
        if not isinstance(between, list) or len(between) < 2:
            continue

        purpose = str(conn.get("purpose") or "").strip().lower()
        if "subassembly" in purpose and "group" in purpose:
            continue

        original_between = [cid for cid in between if isinstance(cid, str)]
        if len(original_between) < 2:
            continue

        connection_semantics = conn.get("connection_semantics") if isinstance(conn.get("connection_semantics"), Mapping) else None
        if isinstance(connection_semantics, Mapping):
            if isinstance(connection_semantics.get("connection_mechanism"), str) and str(connection_semantics.get("connection_mechanism") or "").strip():
                conn.setdefault("metadata", {})["rewire_skipped"] = {
                    "reason": "authoritative_connection_semantics_preserved",
                    "original_between": original_between,
                }
                continue

        new_between = list(original_between)
        changed = False
        for idx, comp_id in enumerate(original_between):
            if not _is_container_component(comp_id):
                continue
            replacement = _choose_child(comp_id, conn)
            if replacement != comp_id:
                new_between[idx] = replacement
                changed = True

        if changed:
            # Prevent self-connections (both sides rewired to same child)
            unique_between = list(dict.fromkeys(new_between))  # preserve order, dedup
            if len(unique_between) < 2:
                # Both endpoints collapsed to the same component -- skip rewiring
                conn["between"] = original_between
                conn.setdefault("metadata", {})["rewire_skipped"] = {
                    "reason": "self_connection_after_rewire",
                    "collapsed_to": unique_between[0] if unique_between else None,
                }
                continue
            conn["between"] = new_between
            conn["rewired_from"] = {
                "original_between": original_between,
                "reason": "container_component_rewired_to_child_for_interface_resolution",
            }
            rewired.append(
                {
                    "connection_id": conn.get("id"),
                    "original_between": original_between,
                    "rewired_between": new_between,
                }
            )

    return kg, {
        "rewired_count": len(rewired),
        "rewired": rewired,
    }

def _strip_for_agent1(defn: Dict[str, Any]) -> Dict[str, Any]:
    d = copy.deepcopy(defn)
    if isinstance(d, dict) and "properties" in d and isinstance(d["properties"], dict):
        d["properties"].pop("interfaces", None)
        d["properties"].pop("parent_id", None)
    return d

def _ensure_shape_semantics_defaults(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    shape_by_type = {
        "wheel": {"type": "cylindrical", "cross_section": "circular"},
        "hub": {"type": "cylindrical", "cross_section": "circular"},
        "tire": {"type": "cylindrical", "cross_section": "annular"},
        "bearing": {"type": "cylindrical", "cross_section": "annular"},
        "shaft": {"type": "cylindrical", "cross_section": "circular"},
        "axle": {"type": "cylindrical", "cross_section": "circular"},
        "fastener": {"type": "cylindrical", "cross_section": "circular"},
        "spacer": {"type": "cylindrical", "cross_section": "annular"},
        "arm": {"type": "prismatic", "cross_section": "rectangular"},
        "plate": {"type": "prismatic", "cross_section": "rectangular"},
        "carrier_plate": {"type": "radial_plate", "cross_section": "rectangular"},
        "rigid_plate": {"type": "prismatic", "cross_section": "rectangular"},
    }

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        if comp.get("type") == "subassembly":
            continue
        shape = comp.get("shape_semantics")
        comp_type = comp.get("type") if isinstance(comp.get("type"), str) else ""
        defaults = shape_by_type.get(comp_type, {"type": "complex"})

        if not isinstance(shape, Mapping):
            comp["shape_semantics"] = dict(defaults)
            continue

        if not shape.get("type"):
            shape["type"] = defaults.get("type", "complex")
        if "cross_section" not in shape and defaults.get("cross_section"):
            shape["cross_section"] = defaults["cross_section"]

def _component_decomposition_confidence(comp: dict, template: str) -> float:
    comp_type = str(comp.get("type", "")).lower()
    comp_id = str(comp.get("id", "")).lower()
    role = str(comp.get("role", "")).lower()
    shape = comp.get("shape_semantics")
    shape_type = ""
    if isinstance(shape, Mapping):
        shape_type = str(shape.get("type", "")).lower()

    score = 0.0

    if template == "wheel":
        if comp_type == "wheel":
            score += 0.85
        if shape_type == "wheel":
            score += 0.2
        if "wheel" in comp_id or "轮" in comp_id:
            score += 0.12
    elif template == "shaft":
        if comp_type in {"shaft", "axle", "pin"}:
            score += 0.85
        if any(token in comp_id for token in {"shaft", "axle", "pin", "轴", "销"}):
            score += 0.12
    elif template == "bearing_unit":
        if comp_type == "bearing":
            score += 0.88
        if "bearing" in comp_id or "轴承" in comp_id:
            score += 0.1
    elif template == "motor_gearbox":
        if comp_type in {"motor", "electric_motor", "gearbox", "gear_reducer", "减速器"}:
            score += 0.82
        if any(token in comp_id for token in {"motor", "电机", "gearbox", "gear_reducer", "减速器"}):
            score += 0.14
    elif template == "coupling":
        if comp_type == "coupling":
            score += 0.82
        if any(token in comp_id for token in {"coupling", "联轴器", "耦合器"}):
            score += 0.14
    elif template == "plate_assembly":
        if comp_type in {"plate_assembly", "carrier_plate"}:
            score += 0.82
        elif comp_type == "plate":
            score += 0.52
        if any(token in comp_id for token in {"plate_top", "plate_bottom", "carrier_top", "carrier_bottom"}):
            score += 0.25

    if role in {"rotation", "load_support", "mounting", "fastening"}:
        score += 0.05

    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        score -= 0.35
    if comp_type in FEATURE_LIKE_TYPES:
        score -= 0.5

    return max(0.0, min(1.0, score))

def _has_existing_decomposition_signature(parent_id: str, template: str, components: list[dict]) -> bool:
    if not parent_id:
        return False

    child_types = {
        str(c.get("type", "")).lower()
        for c in components
        if isinstance(c, Mapping) and c.get("parent_id") == parent_id
    }

    signatures: dict[str, set[str]] = {
        "wheel": {"hub", "tire", "rim", "axle", "bearing"},
        "shaft": {"retainer", "spacer"},
        "bearing_unit": {"bearing_seat", "retainer"},
        "motor_gearbox": {"shaft", "mounting_flange"},
        "coupling": {"coupling_body", "fastener", "key"},
        "plate_assembly": {"standoff_set", "fastener", "nut_set"},
    }
    required = signatures.get(template, set())
    if not required:
        return False
    return len(required & child_types) >= max(2, len(required) // 2)

def _collect_referenced_component_ids(payload: Dict[str, Any]) -> set[str]:
    referenced: set[str] = set()

    for cr in payload.get("connection_requirements", []) or []:
        if not isinstance(cr, Mapping):
            continue
        between = cr.get("between", [])
        if isinstance(between, list):
            referenced.update({cid for cid in between if isinstance(cid, str)})

    for sa in payload.get("subassemblies", []) or []:
        if not isinstance(sa, Mapping):
            continue
        members = sa.get("component_ids", [])
        if isinstance(members, list):
            referenced.update({cid for cid in members if isinstance(cid, str)})

    for sp in payload.get("standard_parts", []) or []:
        if not isinstance(sp, Mapping):
            continue
        applied_to = sp.get("applied_to", [])
        if isinstance(applied_to, list):
            referenced.update({cid for cid in applied_to if isinstance(cid, str)})

    return referenced

def _collapse_semantic_clones(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    referenced = _collect_referenced_component_ids(payload)
    removable_types = {
        "retainer",
        "spacer",
        "bearing_seat",
        "mounting_flange",
        "key",
        "fastener_set",
        "standoff_set",
        "nut_set",
    }

    id_seen: set[str] = set()
    deduped: list[dict] = []
    removed_id_collisions = 0
    clone_bucket_seen: set[tuple[str, str, str]] = set()
    removed_unreferenced_clones = 0

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id in id_seen:
            removed_id_collisions += 1
            continue
        id_seen.add(comp_id)

        comp_type = str(comp.get("type", "")).lower()
        parent_id = str(comp.get("parent_id", ""))
        role = str(comp.get("role", "")).lower()
        bucket = (parent_id, comp_type, role)
        if comp_type in removable_types and comp_id not in referenced and bucket in clone_bucket_seen:
            removed_unreferenced_clones += 1
            continue

        clone_bucket_seen.add(bucket)
        deduped.append(comp)

    payload["components"] = deduped
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["entity_convergence"] = {
            "removed_id_collisions": removed_id_collisions,
            "removed_unreferenced_clones": removed_unreferenced_clones,
            "components_after_convergence": len(deduped),
        }

def _normalize_and_canonicalize_bearings(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    bearing_components = [
        c for c in components
        if isinstance(c, dict) and c.get("type") == "bearing" and isinstance(c.get("id"), str)
    ]
    if not bearing_components:
        return

    canonical_pattern = re.compile(r"^wheel_\d+_bearing_\d+$")
    generic_pattern = re.compile(r"^bearing_\d+$")
    canonical_ids = {
        str(c.get("id"))
        for c in bearing_components
        if canonical_pattern.match(str(c.get("id")))
    }

    removed_generic_ids: set[str] = set()

    for comp in bearing_components:
        raw_dims = comp.get("dimensions")
        dims: dict[str, Any] = dict(raw_dims) if isinstance(raw_dims, dict) else {}
        raw_sources = comp.get("dimension_sources")
        sources: dict[str, Any] = dict(raw_sources) if isinstance(raw_sources, dict) else {}

        if not isinstance(dims.get("bore_diameter"), (int, float)) and isinstance(dims.get("inner_diameter"), (int, float)):
            dims["bore_diameter"] = float(dims["inner_diameter"])
        if not isinstance(dims.get("width"), (int, float)) and isinstance(dims.get("thickness"), (int, float)):
            dims["width"] = float(dims["thickness"])

        if "bore_diameter" not in sources and isinstance(sources.get("inner_diameter"), dict):
            sources["bore_diameter"] = dict(sources["inner_diameter"])
        if "width" not in sources and isinstance(sources.get("thickness"), dict):
            sources["width"] = dict(sources["thickness"])

        dims.pop("inner_diameter", None)
        dims.pop("thickness", None)
        sources.pop("inner_diameter", None)
        sources.pop("thickness", None)

        comp["dimensions"] = dims
        comp["dimension_sources"] = sources

        comp_id = str(comp.get("id"))
        if canonical_ids and generic_pattern.match(comp_id):
            removed_generic_ids.add(comp_id)

    if not removed_generic_ids:
        return

    removed_component_ids: set[str] = set(removed_generic_ids)
    changed = True
    while changed:
        changed = False
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id")
            parent_id = comp.get("parent_id")
            if not isinstance(comp_id, str) or comp_id in removed_component_ids:
                continue
            if isinstance(parent_id, str) and parent_id in removed_component_ids:
                removed_component_ids.add(comp_id)
                changed = True

    payload["components"] = [
        c for c in components
        if not (isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id") in removed_component_ids)
    ]

    crs = payload.get("connection_requirements")
    if isinstance(crs, list):
        filtered_crs: list[dict] = []
        removed_cr_ids: set[str] = set()
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                filtered_crs.append(cr)
                continue
            new_between = [cid for cid in between if isinstance(cid, str) and cid not in removed_component_ids]
            if len(new_between) < 2:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_cr_ids.add(cr_id)
                continue
            cr["between"] = new_between
            filtered_crs.append(cr)
        payload["connection_requirements"] = filtered_crs

        standard_parts = payload.get("standard_parts")
        if isinstance(standard_parts, list):
            filtered_parts: list[dict[str, Any]] = []
            for part in standard_parts:
                if not isinstance(part, dict):
                    continue
                part_id = part.get("id")
                comp_id = part.get("component_id")
                if isinstance(comp_id, str) and comp_id in removed_component_ids:
                    continue
                bound_ids = part.get("bound_component_ids")
                if isinstance(bound_ids, list) and any(
                    isinstance(cid, str) and cid in removed_component_ids for cid in bound_ids
                ):
                    continue
                if isinstance(part_id, str) and any(part_id == f"std_{cid}" for cid in removed_component_ids):
                    continue
                applied_to = part.get("applied_to")
                if isinstance(applied_to, list) and removed_cr_ids:
                    part["applied_to"] = [cid for cid in applied_to if isinstance(cid, str) and cid not in removed_cr_ids]
                filtered_parts.append(part)
            payload["standard_parts"] = filtered_parts

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, dict):
                continue
            comp_ids = sa.get("component_ids")
            if isinstance(comp_ids, list):
                sa["component_ids"] = [cid for cid in comp_ids if isinstance(cid, str) and cid not in removed_component_ids]

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        filtered_patterns: list[dict[str, Any]] = []
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            component_ids = pattern.get("component_ids")
            if isinstance(component_ids, list):
                component_ids = [
                    cid for cid in component_ids if isinstance(cid, str) and cid not in removed_component_ids
                ]
                if len(component_ids) < 2:
                    continue
                pattern["component_ids"] = component_ids
                instances = pattern.get("instances")
                if isinstance(instances, list):
                    pattern["instances"] = [
                        cid for cid in instances if isinstance(cid, str) and cid not in removed_component_ids
                    ]
                prototype = pattern.get("prototype")
                if isinstance(prototype, str) and prototype in removed_component_ids:
                    pattern["prototype"] = component_ids[0]
            filtered_patterns.append(pattern)
        payload["patterns"] = filtered_patterns

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["bearing_canonicalization"] = {
            "canonical_pattern": "wheel_<n>_bearing_<m>",
            "removed_legacy_bearings": sorted(removed_generic_ids),
            "removed_legacy_descendants": sorted(removed_component_ids - removed_generic_ids),
        }

def _canonicalize_wheel_rotor_naming(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    legacy_axle_pattern = re.compile(r"^wheel_axle_(\d+)$")
    legacy_fastener_pattern = re.compile(r"^wheel_fastener_set_(\d+)$")
    canonical_wheel_axle_pattern = re.compile(r"^wheel_(\d+)_axle$")

    id_to_component: dict[str, dict[str, Any]] = {
        str(c.get("id")): c
        for c in components
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }

    rename_map: dict[str, str] = {}
    removed_legacy_components: set[str] = set()

    def _canonical_id(comp_id: str) -> str | None:
        m_axle = legacy_axle_pattern.match(comp_id)
        if m_axle:
            return f"wheel_{m_axle.group(1)}_axle"
        m_fastener = legacy_fastener_pattern.match(comp_id)
        if m_fastener:
            return f"wheel_{m_fastener.group(1)}_fastener_set"
        return None

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        canonical_id = _canonical_id(comp_id)
        if not canonical_id:
            continue

        rename_map[comp_id] = canonical_id
        if canonical_id in id_to_component and canonical_id != comp_id:
            removed_legacy_components.add(comp_id)
            continue

        comp["id"] = canonical_id
        id_to_component[canonical_id] = comp
        if comp_id in id_to_component:
            id_to_component.pop(comp_id, None)

    if removed_legacy_components:
        payload["components"] = [
            c
            for c in payload.get("components", [])
            if not (isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id") in removed_legacy_components)
        ]

    type_by_id = _build_type_map(payload.get("components", []))

    if not rename_map and not removed_legacy_components:
        return

    def _remap_component_id(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return rename_map.get(value, value)

    for comp in payload.get("components", []) if isinstance(payload.get("components", []), list) else []:
        if not isinstance(comp, dict):
            continue
        if isinstance(comp.get("parent_id"), str):
            comp["parent_id"] = _remap_component_id(comp.get("parent_id"))
        if isinstance(comp.get("position_parent"), str):
            comp["position_parent"] = _remap_component_id(comp.get("position_parent"))

    subassemblies = payload.get("subassemblies", [])
    if isinstance(subassemblies, list):
        for sa in subassemblies:
            if not isinstance(sa, dict):
                continue
            members = sa.get("component_ids")
            if not isinstance(members, list):
                continue
            remapped = [_remap_component_id(cid) for cid in members if isinstance(cid, str)]
            deduped: list[str] = []
            for cid in remapped:
                if isinstance(cid, str) and cid not in deduped:
                    deduped.append(cid)
            sa["component_ids"] = deduped

    crs = payload.get("connection_requirements", [])
    removed_invalid_cr_ids: set[str] = set()
    if isinstance(crs, list):
        filtered_crs: list[dict[str, Any]] = []
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if isinstance(between, list):
                remapped_between = [_remap_component_id(cid) for cid in between if isinstance(cid, str)]
                deduped_between: list[str] = []
                for cid in remapped_between:
                    if isinstance(cid, str) and cid not in deduped_between:
                        deduped_between.append(cid)
                cr["between"] = deduped_between

            decision = cr.get("connection_decision")
            if isinstance(decision, dict):
                ref_id = decision.get("fastener_ref_component_id")
                if isinstance(ref_id, str):
                    decision["fastener_ref_component_id"] = _remap_component_id(ref_id)

            current_between = cr.get("between")
            if not isinstance(current_between, list):
                filtered_crs.append(cr)
                continue

            has_central_hub = any(
                isinstance(cid, str) and _is_central_hub_component_id(cid, type_by_id)
                for cid in current_between
            )
            has_wheel_axle = any(
                isinstance(cid, str) and canonical_wheel_axle_pattern.match(cid)
                for cid in current_between
            )
            if has_central_hub and has_wheel_axle:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_invalid_cr_ids.add(cr_id)
                continue

            if len([cid for cid in current_between if isinstance(cid, str)]) < 2:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    removed_invalid_cr_ids.add(cr_id)
                continue

            filtered_crs.append(cr)

        payload["connection_requirements"] = filtered_crs

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, dict):
                continue
            comp_id = part.get("component_id")
            if isinstance(comp_id, str):
                part["component_id"] = _remap_component_id(comp_id)
            bound_ids = part.get("bound_component_ids")
            if isinstance(bound_ids, list):
                part["bound_component_ids"] = [
                    _remap_component_id(cid)
                    for cid in bound_ids
                    if isinstance(cid, str)
                ]
            applied_to = part.get("applied_to")
            if isinstance(applied_to, list) and removed_invalid_cr_ids:
                part["applied_to"] = [
                    cr_id for cr_id in applied_to if isinstance(cr_id, str) and cr_id not in removed_invalid_cr_ids
                ]

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["wheel_rotor_canonicalization"] = {
            "renamed_components": {k: v for k, v in sorted(rename_map.items())},
            "removed_legacy_components": sorted(removed_legacy_components),
            "removed_invalid_connections": sorted(removed_invalid_cr_ids),
        }

def _validate_wheel_rotor_naming(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    legacy_axle_pattern = re.compile(r"^wheel_axle_(\d+)$")
    legacy_fastener_pattern = re.compile(r"^wheel_fastener_set_(\d+)$")
    canonical_axle_pattern = re.compile(r"^wheel_(\d+)_axle$")
    canonical_fastener_pattern = re.compile(r"^wheel_(\d+)_fastener_set$")

    legacy_axle_ids: list[str] = []
    legacy_fastener_ids: list[str] = []
    canonical_axle_by_suffix: dict[str, set[str]] = {}
    canonical_fastener_by_suffix: dict[str, set[str]] = {}
    legacy_axle_by_suffix: dict[str, set[str]] = {}
    legacy_fastener_by_suffix: dict[str, set[str]] = {}

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        m = canonical_axle_pattern.match(comp_id)
        if m:
            canonical_axle_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = canonical_fastener_pattern.match(comp_id)
        if m:
            canonical_fastener_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = legacy_axle_pattern.match(comp_id)
        if m:
            legacy_axle_ids.append(comp_id)
            legacy_axle_by_suffix.setdefault(m.group(1), set()).add(comp_id)
        m = legacy_fastener_pattern.match(comp_id)
        if m:
            legacy_fastener_ids.append(comp_id)
            legacy_fastener_by_suffix.setdefault(m.group(1), set()).add(comp_id)

    mixed_suffixes_axle = sorted(
        s for s in legacy_axle_by_suffix.keys() if s in canonical_axle_by_suffix
    )
    mixed_suffixes_fastener = sorted(
        s for s in legacy_fastener_by_suffix.keys() if s in canonical_fastener_by_suffix
    )

    if mixed_suffixes_axle or mixed_suffixes_fastener:
        raise ValueError(
            "Validation failed: mixed wheel naming schemes detected for axle/fastener_set. "
            f"mixed_axle_suffixes={mixed_suffixes_axle}, mixed_fastener_suffixes={mixed_suffixes_fastener}"
        )

    if legacy_axle_ids or legacy_fastener_ids:
        raise ValueError(
            "Validation failed: legacy wheel naming is not allowed. "
            f"legacy_axle_ids={sorted(legacy_axle_ids)}, legacy_fastener_ids={sorted(legacy_fastener_ids)}"
        )

    type_by_id = _build_type_map(components)

    crs = payload.get("connection_requirements", [])
    if isinstance(crs, list):
        illegal_links: list[str] = []
        for cr in crs:
            if not isinstance(cr, dict):
                continue
            between = cr.get("between")
            if not isinstance(between, list):
                continue
            has_central_hub = any(
                isinstance(cid, str) and _is_central_hub_component_id(cid, type_by_id)
                for cid in between
            )
            if not has_central_hub:
                continue
            axle_hits = [cid for cid in between if isinstance(cid, str) and canonical_axle_pattern.match(cid)]
            if axle_hits:
                cr_id = cr.get("id") if isinstance(cr.get("id"), str) else "<unknown>"
                illegal_links.append(f"{cr_id}:{sorted(axle_hits)}")
        if illegal_links:
            raise ValueError(
                "Validation failed: illegal wheel axle to central hub connection(s) detected. "
                f"violations={illegal_links}"
            )

def _ensure_wheel_subcomponent_instance_patterns(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    allowed_subs = {
        "wheel",
        "rim",
        "tire",
        "hub",
        "axle",
        "bearing_1",
        "bearing_2",
        "spacer",
        "fastener_set",
    }
    id_pattern = re.compile(r"^wheel_(\d+)(?:_(rim|tire|hub|axle|bearing_1|bearing_2|spacer|fastener_set))?$")

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    grouped_ids: Dict[str, Dict[int, str]] = {sub: {} for sub in allowed_subs}
    for comp_id in comp_by_id.keys():
        match = id_pattern.match(comp_id)
        if not match:
            continue
        idx = int(match.group(1))
        sub = match.group(2) or "wheel"
        grouped_ids[sub][idx] = comp_id

    patterns_raw = payload.get("patterns")
    patterns: List[Dict[str, Any]] = [p for p in patterns_raw if isinstance(p, dict)] if isinstance(patterns_raw, list) else []

    def _extract_requirement_text() -> str:
        candidates: list[Any] = [
            payload.get("requirement_text"),
            payload.get("user_requirement"),
            payload.get("prompt"),
        ]
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.extend(
                [
                    metadata.get("requirement_text"),
                    metadata.get("user_requirement"),
                    metadata.get("source_requirement"),
                    metadata.get("prompt"),
                ]
            )
        merged = "\n".join(str(v) for v in candidates if isinstance(v, str) and v.strip())
        return merged.lower()

    requirement_text_lower = _extract_requirement_text()

    def _force_instancing_by_requirement_text() -> bool:
        explicit_hints = [
            "120°",
            "120 degree",
            "三等分",
            "three-fold symmetry",
            "threefold symmetry",
            "三个轮子均布",
            "三个轮子对称分布",
            "three identical wheels",
            "three wheels are identical",
        ]
        return any(token in requirement_text_lower for token in explicit_hints)

    force_instancing = _force_instancing_by_requirement_text()

    def _numeric_dims(comp: Dict[str, Any]) -> Dict[str, float]:
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), dict) else {}
        out: Dict[str, float] = {}
        for key, value in dims.items():
            if not isinstance(key, str):
                continue
            value = dims.get(key)
            if isinstance(value, (int, float)):
                out[key] = float(value)
        return out

    def _dims_compatible(a: Dict[str, float], b: Dict[str, float], tol: float = 1e-3) -> bool:
        common_keys = set(a.keys()) & set(b.keys())
        for key in common_keys:
            if abs(a[key] - b[key]) >= tol:
                return False
        return True

    def _apply_instance_pattern(
        *,
        instances: list[str],
        pattern_id: str,
        description: str,
    ) -> None:
        if len(instances) != 3:
            return

        prototype = instances[0]
        prototype_comp = comp_by_id.get(prototype)
        if not isinstance(prototype_comp, dict):
            return

        expected_type = prototype_comp.get("type") if isinstance(prototype_comp.get("type"), str) else None
        expected_dims = _numeric_dims(prototype_comp)

        is_consistent = True
        mismatch_reason = ""
        for comp_id in instances[1:]:
            comp = comp_by_id.get(comp_id)
            if not isinstance(comp, dict):
                is_consistent = False
                mismatch_reason = "missing_component_payload"
                break
            ctype = comp.get("type") if isinstance(comp.get("type"), str) else None
            if ctype != expected_type:
                is_consistent = False
                mismatch_reason = "type_mismatch"
                break
            if not _dims_compatible(expected_dims, _numeric_dims(comp)):
                is_consistent = False
                mismatch_reason = "dimension_mismatch"
                break

        forced = False
        if not is_consistent and force_instancing and mismatch_reason != "type_mismatch":
            is_consistent = True
            forced = True

        if not is_consistent:
            return

        for comp_id in instances:
            comp = comp_by_id.get(comp_id)
            if isinstance(comp, dict):
                comp["definition_id"] = prototype
                comp["instance_id"] = comp_id
                if comp_id != prototype:
                    comp["instanced_from"] = prototype
                elif "instanced_from" in comp:
                    comp.pop("instanced_from", None)

        created_pattern_ids.add(pattern_id)
        if forced:
            forced_pattern_ids.add(pattern_id)
        pattern_payload = {
            "id": pattern_id,
            "type": "rotational_symmetry",
            "count": len(instances),
            "component_ids": instances,
            "prototype": prototype,
            "instances": instances,
            "axis": "Z",
            "description": description,
        }
        if forced:
            pattern_payload["force_instancing"] = True
            pattern_payload["force_reason"] = "requirement_text_threefold_symmetry_hint"

        replaced = False
        for idx, item in enumerate(patterns):
            if isinstance(item.get("id"), str) and item.get("id") == pattern_id:
                patterns[idx] = pattern_payload
                replaced = True
                break
        if not replaced:
            patterns.append(pattern_payload)

    created_pattern_ids: set[str] = set()
    forced_pattern_ids: set[str] = set()
    for sub in sorted(allowed_subs):
        per_index = grouped_ids.get(sub, {})
        if len(per_index) < 3:
            continue

        indices = sorted(per_index.keys())
        if indices != [1, 2, 3]:
            continue

        instances = [per_index[i] for i in indices]
        _apply_instance_pattern(
            instances=instances,
            pattern_id=f"wheel_{sub}_rotational_symmetry",
            description="Wheel subcomponents are identical instances",
        )

    arm_pattern = re.compile(r"^wheel_arm_(\d+)$")
    arm_group: Dict[int, str] = {}
    for comp_id in comp_by_id.keys():
        match = arm_pattern.match(comp_id)
        if not match:
            continue
        arm_group[int(match.group(1))] = comp_id

    arm_indices = sorted(arm_group.keys())
    if arm_indices == [1, 2, 3]:
        _apply_instance_pattern(
            instances=[arm_group[i] for i in arm_indices],
            pattern_id="wheel_arm_rotational_symmetry",
            description="Wheel arms are identical instances",
        )

    if created_pattern_ids:
        payload["patterns"] = patterns

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["wheel_instance_patterns"] = {
        "created_pattern_ids": sorted(created_pattern_ids),
        "count": len(created_pattern_ids),
        "forced_pattern_ids": sorted(forced_pattern_ids),
        "forced_by_requirement_text": bool(forced_pattern_ids),
        "force_trigger_detected": force_instancing,
    }

def _canonicalize_hub_arm_fastener_components(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    def _is_hub_arm_fastener_connection(conn: Mapping[str, Any], idx: int, fastener_id: str) -> bool:
        between = [cid for cid in conn.get("between", []) if isinstance(cid, str)]
        required = {"central_hub", f"wheel_arm_{idx}", fastener_id}
        if required.issubset(set(between)):
            return True
        decision = conn.get("connection_decision") if isinstance(conn.get("connection_decision"), Mapping) else {}
        ref_id = decision.get("fastener_ref_component_id")
        if isinstance(ref_id, str) and ref_id == fastener_id:
            return True
        return False

    remap: Dict[str, str] = {}
    rename_in_place: Dict[str, str] = {}
    for idx in (1, 2, 3):
        legacy_id = f"wheel_{idx}_fastener_set"
        canonical_id = f"central_hub_to_wheel_arm_{idx}_fastener_set"
        if legacy_id not in comp_by_id:
            continue
        conn = next(
            (
                cr for cr in crs
                if isinstance(cr, Mapping)
                and str(cr.get("id") or "").strip() == f"hub_to_arm_{idx}_connection"
                and _is_hub_arm_fastener_connection(cr, idx, legacy_id)
            ),
            None,
        )
        if conn is None:
            continue
        remap[legacy_id] = canonical_id
        if canonical_id not in comp_by_id:
            rename_in_place[legacy_id] = canonical_id
    if not remap:
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else None
        if isinstance(comp_id, str) and comp_id in rename_in_place:
            comp["id"] = rename_in_place[comp_id]
        for field in ("definition_id", "instance_id", "instanced_from"):
            field_value = comp.get(field)
            if isinstance(field_value, str) and field_value in remap:
                comp[field] = remap[field_value]

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        between = cr.get("between")
        if isinstance(between, list):
            remapped_between: list[str] = []
            for cid in between:
                if not isinstance(cid, str):
                    continue
                mapped = remap.get(cid, cid)
                if mapped not in remapped_between:
                    remapped_between.append(mapped)
            cr["between"] = remapped_between
        decision = cr.get("connection_decision")
        if isinstance(decision, dict):
            ref_id = decision.get("fastener_ref_component_id")
            if isinstance(ref_id, str) and ref_id in remap:
                decision["fastener_ref_component_id"] = remap[ref_id]

    referenced_ids = {
        cid
        for cr in crs
        if isinstance(cr, Mapping)
        for cid in cr.get("between", [])
        if isinstance(cid, str)
    }
    removed_component_ids = {
        legacy_id
        for legacy_id, canonical_id in remap.items()
        if legacy_id not in rename_in_place and canonical_id in comp_by_id and legacy_id not in referenced_ids
    }
    if removed_component_ids:
        payload["components"] = [
            comp
            for comp in components
            if not (isinstance(comp, dict) and isinstance(comp.get("id"), str) and comp.get("id") in removed_component_ids)
        ]

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, dict):
                continue
            comp_id = part.get("component_id")
            if isinstance(comp_id, str) and comp_id in remap:
                part["component_id"] = remap[comp_id]
            bound_ids = part.get("bound_component_ids")
            if isinstance(bound_ids, list):
                part["bound_component_ids"] = [remap.get(cid, cid) for cid in bound_ids if isinstance(cid, str)]
            bound_component_id = part.get("bound_component_id")
            if isinstance(bound_component_id, str) and bound_component_id in remap:
                part["bound_component_id"] = remap[bound_component_id]

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            prototype = pattern.get("prototype")
            if isinstance(prototype, str) and prototype in remap:
                pattern["prototype"] = remap[prototype]
            component_ids = pattern.get("component_ids")
            if isinstance(component_ids, list):
                pattern["component_ids"] = [remap.get(cid, cid) for cid in component_ids if isinstance(cid, str)]

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        for subassembly in subassemblies:
            if not isinstance(subassembly, dict):
                continue
            component_ids = subassembly.get("component_ids")
            if not isinstance(component_ids, list):
                continue
            remapped_ids: list[str] = []
            for cid in component_ids:
                if not isinstance(cid, str):
                    continue
                mapped = remap.get(cid, cid)
                if mapped not in remapped_ids:
                    remapped_ids.append(mapped)
            subassembly["component_ids"] = remapped_ids

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata["hub_arm_fastener_component_canonicalization"] = {
        "remapped_components": {k: v for k, v in sorted(remap.items())},
        "renamed_legacy_components": sorted(rename_in_place.keys()),
        "removed_legacy_components": sorted(removed_component_ids),
    }
    payload["metadata"] = metadata

def _prune_stale_standard_parts(payload: Dict[str, Any]) -> None:
    standard_parts = payload.get("standard_parts")
    if not isinstance(standard_parts, list):
        _prune_orphan_wheel_fastener_components(payload)
        return

    component_ids = {
        comp.get("id")
        for comp in payload.get("components", [])
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
    }
    connection_by_id = {
        cr.get("id"): cr
        for cr in payload.get("connection_requirements", [])
        if isinstance(cr, Mapping) and isinstance(cr.get("id"), str)
    }
    connection_ids = set(connection_by_id.keys())

    filtered: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    for part in standard_parts:
        if not isinstance(part, dict):
            continue
        comp_id = part.get("component_id") if isinstance(part.get("component_id"), str) else None
        has_bound_field = isinstance(part.get("bound_component_ids"), list)
        bound_ids = part.get("bound_component_ids") if has_bound_field else []
        applied_to = part.get("applied_to") if isinstance(part.get("applied_to"), list) else []

        comp_id = comp_id if comp_id in component_ids else None
        bound_ids = [cid for cid in bound_ids if isinstance(cid, str) and cid in component_ids]
        applied_to = [cid for cid in applied_to if isinstance(cid, str) and cid in connection_ids]

        if comp_id is not None:
            part["component_id"] = comp_id
        else:
            part.pop("component_id", None)
        if has_bound_field:
            part["bound_component_ids"] = bound_ids
        part["applied_to"] = applied_to

        has_component_ref = comp_id is not None or (has_bound_field and bool(bound_ids))
        has_connection_ref = bool(applied_to)
        category = str(part.get("category") or "").strip().lower()
        if category == "fastener" and not has_component_ref:
            inferred_refs = {
                str(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id"))
                for conn_id in applied_to
                if isinstance(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id"), str)
                and str(((connection_by_id.get(conn_id) or {}).get("connection_decision") or {}).get("fastener_ref_component_id")) in component_ids
            }
            has_component_ref = bool(inferred_refs)
        if (not has_component_ref and not has_connection_ref) or (category == "fastener" and not has_component_ref):
            if isinstance(part.get("id"), str):
                removed_ids.append(part["id"])
            continue
        filtered.append(part)

    payload["standard_parts"] = filtered
    if removed_ids:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata["stale_standard_parts_pruned"] = sorted(removed_ids)
        payload["metadata"] = metadata
    _prune_orphan_wheel_fastener_components(payload)

def _prune_orphan_wheel_fastener_components(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list) or not components:
        return

    orphan_pattern = re.compile(r"^(?:wheel_fastener_set(?:_\d+)?|wheel_\d+_fastener_set)$")
    referenced_ids: set[str] = set()

    crs = payload.get("connection_requirements", [])
    if isinstance(crs, list):
        for cr in crs:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between")
            if isinstance(between, list):
                for cid in between:
                    if isinstance(cid, str) and cid:
                        referenced_ids.add(cid)
            decision = cr.get("connection_decision") if isinstance(cr.get("connection_decision"), Mapping) else {}
            fastener_ref = decision.get("fastener_ref_component_id")
            if isinstance(fastener_ref, str) and fastener_ref:
                referenced_ids.add(fastener_ref)

    standard_parts = payload.get("standard_parts")
    if isinstance(standard_parts, list):
        for part in standard_parts:
            if not isinstance(part, Mapping):
                continue
            bound_component_id = part.get("bound_component_id")
            if isinstance(bound_component_id, str) and bound_component_id:
                referenced_ids.add(bound_component_id)
            bound_component_ids = part.get("bound_component_ids")
            if isinstance(bound_component_ids, list):
                for cid in bound_component_ids:
                    if isinstance(cid, str) and cid:
                        referenced_ids.add(cid)

    removed_ids: list[str] = []
    kept_components: list[Any] = []
    for comp in components:
        if not isinstance(comp, Mapping):
            kept_components.append(comp)
            continue
        comp_id = comp.get("id")
        comp_type = str(comp.get("type") or "").strip().lower()
        if (
            isinstance(comp_id, str)
            and orphan_pattern.fullmatch(comp_id) is not None
            and comp_type in {"fastener", "fastener_set", "bolt_set"}
            and comp_id not in referenced_ids
        ):
            removed_ids.append(comp_id)
            continue
        kept_components.append(comp)

    if not removed_ids:
        return

    payload["components"] = kept_components

    patterns = payload.get("patterns")
    if isinstance(patterns, list):
        payload["patterns"] = [
            pattern
            for pattern in patterns
            if not (
                isinstance(pattern, Mapping)
                and (
                    (
                        isinstance(pattern.get("prototype"), str)
                        and pattern.get("prototype") in removed_ids
                    )
                    or any(
                        isinstance(cid, str) and cid in removed_ids
                        for cid in (
                            pattern.get("component_ids")
                            if isinstance(pattern.get("component_ids"), list)
                            else []
                        )
                    )
                )
            )
        ]

    subassemblies = payload.get("subassemblies")
    if isinstance(subassemblies, list):
        filtered_subassemblies: list[Any] = []
        for sa in subassemblies:
            if not isinstance(sa, Mapping):
                filtered_subassemblies.append(sa)
                continue
            component_ids = sa.get("component_ids")
            if isinstance(component_ids, list):
                kept_ids = [cid for cid in component_ids if not (isinstance(cid, str) and cid in removed_ids)]
                if not kept_ids:
                    continue
                sa_out = dict(sa)
                sa_out["component_ids"] = kept_ids
                filtered_subassemblies.append(sa_out)
                continue
            filtered_subassemblies.append(sa)
        payload["subassemblies"] = filtered_subassemblies

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    existing = metadata.get("orphan_wheel_fastener_components_pruned")
    pruned = set(existing) if isinstance(existing, list) else set()
    pruned.update(removed_ids)
    metadata["orphan_wheel_fastener_components_pruned"] = sorted(pruned)
    payload["metadata"] = metadata

def _normalize_symmetric_hub_arm_fasteners(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    crs = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(crs, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }

    def _fastener_id_for_index(idx: int) -> str | None:
        for candidate in (
            f"central_hub_to_wheel_arm_{idx}_fastener_set",
            f"wheel_{idx}_fastener_set",
        ):
            if candidate in comp_by_id:
                return candidate
        return None

    fastener_ids = [_fastener_id_for_index(idx) for idx in (1, 2, 3)]
    if any(not isinstance(fid, str) or not fid for fid in fastener_ids):
        return

    for idx, fastener_id in zip((1, 2, 3), fastener_ids):
        conn = next(
            (
                cr for cr in crs
                if isinstance(cr, dict)
                and cr.get("id") == f"hub_to_arm_{idx}_connection"
            ),
            None,
        )
        if not isinstance(conn, dict):
            return
        between = [cid for cid in conn.get("between", []) if isinstance(cid, str)]
        required = {"central_hub", f"wheel_arm_{idx}", fastener_id}
        if not required.issubset(set(between)):
            return

    def _signature(comp: Mapping[str, Any]) -> str:
        payload = {
            "type": comp.get("type"),
            "role": comp.get("role"),
            "dimensions": comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {},
            "parameters": comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {},
            "shape_semantics": comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {},
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    buckets: Dict[str, list[str]] = {}
    for fid in fastener_ids:
        buckets.setdefault(_signature(comp_by_id[fid]), []).append(fid)

    sorted_buckets = sorted(
        buckets.items(),
        key=lambda item: (-len(item[1]), 0 if "wheel_1_fastener_set" in item[1] else 1, sorted(item[1])[0]),
    )
    prototype_id = sorted_buckets[0][1][0]
    prototype = comp_by_id.get(prototype_id)
    if not isinstance(prototype, dict):
        return

    updated_ids: list[str] = []
    copied_fields = (
        "type",
        "role",
        "shape_semantics",
        "dimensions",
        "parameters",
        "dimension_sources",
        "part_kind",
        "modeling_policy",
        "kind",
        "must_model",
        "is_container",
        "is_container_only",
        "has_geometry",
        "is_modeling_unit",
    )
    for fid in fastener_ids:
        if fid == prototype_id:
            continue
        target = comp_by_id.get(fid)
        if not isinstance(target, dict):
            continue
        if _signature(target) == _signature(prototype):
            continue
        for field in copied_fields:
            value = prototype.get(field)
            if isinstance(value, Mapping):
                target[field] = dict(value)
            else:
                target[field] = copy.deepcopy(value)
        target["definition_id"] = prototype_id
        target["instance_id"] = fid
        target["instanced_from"] = prototype_id
        updated_ids.append(fid)

    if updated_ids:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata["hub_arm_fastener_symmetry_normalization"] = {
            "prototype_id": prototype_id,
            "updated_ids": sorted(updated_ids),
        }
        payload["metadata"] = metadata

def _ensure_wheel_rim_tire_position_parent(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }
    if not comp_by_id:
        return

    pattern = re.compile(r"^wheel_(\d+)_(rim|tire)$")
    for cid, comp in comp_by_id.items():
        match = pattern.match(cid)
        if not match:
            continue
        idx = match.group(1)
        hub_id = f"wheel_{idx}_hub"
        wheel_id = f"wheel_{idx}"

        parent = hub_id if hub_id in comp_by_id else (wheel_id if wheel_id in comp_by_id else None)
        if isinstance(parent, str) and parent:
            comp["position_parent"] = parent

def _normalize_patterns(payload: Dict[str, Any]) -> None:
    patterns = payload.get("patterns", [])
    if not isinstance(patterns, list):
        return

    component_ids = {
        comp.get("id")
        for comp in payload.get("components", [])
        if isinstance(comp, Mapping) and isinstance(comp.get("id"), str)
    }
    type_aliases = {
        "tri_fold_symmetry": "rotational_symmetry",
        "threefold_symmetry": "rotational_symmetry",
        "three_fold_symmetry": "rotational_symmetry",
        "radial_symmetry": "rotational_symmetry",
        "rotational_repetition": "rotational_symmetry",
        "mirror": "mirror_symmetry",
        "bilateral": "bilateral_symmetry",
    }
    allowed_types = {
        "rotational_symmetry",
        "mirror_symmetry",
        "bilateral_symmetry",
        "linear_repetition",
        "radial_repetition",
    }

    normalized: list[dict[str, Any]] = []
    for idx, pattern in enumerate(patterns, start=1):
        if not isinstance(pattern, dict):
            continue

        ptype = str(pattern.get("type") or "").strip().lower()
        pattern["type"] = type_aliases.get(ptype, ptype if ptype in allowed_types else "rotational_symmetry")
        if not isinstance(pattern.get("id"), str) or not pattern.get("id"):
            pattern["id"] = f"pattern_{idx}"

        ids: list[str] = []
        for key in ("component_ids", "components", "instances", "instance_ids"):
            raw = pattern.get(key)
            if isinstance(raw, list):
                ids.extend(item for item in raw if isinstance(item, str))
        applies_to = pattern.get("applies_to")
        if isinstance(applies_to, str) and applies_to in component_ids:
            ids.append(applies_to)
        prototype = pattern.get("prototype")
        if isinstance(prototype, str) and prototype in component_ids:
            ids.append(prototype)

        ids = [cid for cid in dict.fromkeys(ids) if cid in component_ids]
        if len(ids) < 2:
            continue
        pattern["component_ids"] = ids

        count = pattern.get("count")
        if not isinstance(count, int) or count < 2:
            pattern["count"] = len(ids)

        for stale_key in ("components", "instance_ids"):
            pattern.pop(stale_key, None)
        normalized.append(pattern)

    payload["patterns"] = normalized

def _align_rotational_symmetry_instancing_annotations(payload: Dict[str, Any]) -> None:
    components = payload.get("components")
    patterns = payload.get("patterns")
    if not isinstance(components, list) or not isinstance(patterns, list):
        return

    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(comp.get("id")): comp
        for comp in components
        if isinstance(comp, dict) and isinstance(comp.get("id"), str)
    }
    if not comp_by_id:
        return

    def _numeric_dims(comp: Dict[str, Any]) -> Dict[str, float]:
        dims = comp.get("dimensions")
        if not isinstance(dims, dict):
            return {}
        result: Dict[str, float] = {}
        for key, value in dims.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(key)] = float(value)
        return result

    def _dims_match(a: Dict[str, float], b: Dict[str, float], tol: float = 1e-3) -> bool:
        if set(a.keys()) != set(b.keys()):
            return False
        for key in a.keys():
            if abs(a[key] - b[key]) > tol:
                return False
        return True

    aligned_count = 0
    skipped_pattern_ids: list[str] = []
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        if pattern.get("type") != "rotational_symmetry":
            continue

        raw_ids = pattern.get("component_ids")
        component_ids = [cid for cid in raw_ids if isinstance(cid, str)] if isinstance(raw_ids, list) else []
        pattern_id = pattern.get("id") if isinstance(pattern.get("id"), str) else "rotational_symmetry"
        if len(component_ids) < 2:
            skipped_pattern_ids.append(pattern_id)
            continue

        prototype_id = component_ids[0]
        prototype_comp = comp_by_id.get(prototype_id)
        if not isinstance(prototype_comp, dict):
            skipped_pattern_ids.append(pattern_id)
            continue

        prototype_type = prototype_comp.get("type") if isinstance(prototype_comp.get("type"), str) else None
        prototype_dims = _numeric_dims(prototype_comp)
        consistent = True
        for component_id in component_ids[1:]:
            comp = comp_by_id.get(component_id)
            if not isinstance(comp, dict):
                consistent = False
                break
            comp_type = comp.get("type") if isinstance(comp.get("type"), str) else None
            if comp_type != prototype_type or not _dims_match(prototype_dims, _numeric_dims(comp)):
                consistent = False
                break

        if not consistent:
            skipped_pattern_ids.append(pattern_id)
            continue

        pattern["prototype"] = prototype_id
        pattern["instances"] = component_ids
        for component_id in component_ids:
            comp = comp_by_id.get(component_id)
            if not isinstance(comp, dict):
                continue
            comp["definition_id"] = prototype_id
            comp["instance_id"] = component_id
            if component_id == prototype_id:
                comp.pop("instanced_from", None)
            else:
                comp["instanced_from"] = prototype_id
        aligned_count += 1

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["rotational_pattern_instancing_alignment"] = {
        "aligned_count": aligned_count,
        "skipped_pattern_ids": skipped_pattern_ids,
    }

def _sanitize_instancing_annotations(payload: Dict[str, Any]) -> None:
    components = payload.get("components")
    if not isinstance(components, list):
        return

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str) or not comp_id:
            continue

        instanced_from = comp.get("instanced_from")
        if isinstance(instanced_from, str) and instanced_from == comp_id:
            comp.pop("instanced_from", None)

        definition_id = comp.get("definition_id")
        if not isinstance(definition_id, str) or not definition_id.strip():
            comp["definition_id"] = comp_id

        instance_id = comp.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.strip():
            comp["instance_id"] = comp_id

def _validate_bearing_canonical_schema(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    canonical_pattern = re.compile(r"^wheel_\d+_bearing_\d+$")
    generic_pattern = re.compile(r"^bearing_\d+$")
    canonical_ids: list[str] = []
    generic_ids: list[str] = []
    bad_fields: list[str] = []

    for comp in components:
        if not isinstance(comp, dict) or comp.get("type") != "bearing":
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if canonical_pattern.match(comp_id):
            canonical_ids.append(comp_id)
        if generic_pattern.match(comp_id):
            generic_ids.append(comp_id)

        raw_dims = comp.get("dimensions")
        dims: dict[str, Any] = raw_dims if isinstance(raw_dims, dict) else {}
        if "inner_diameter" in dims or "thickness" in dims:
            bad_fields.append(comp_id)

    if canonical_ids and generic_ids:
        raise ValueError(
            "Validation failed: mixed bearing naming schemes detected. "
            f"canonical={sorted(canonical_ids)}, generic={sorted(generic_ids)}"
        )

    if bad_fields:
        raise ValueError(
            "Validation failed: bearing dimensions must use canonical keys "
            "bore_diameter/outer_diameter/width only. "
            f"Invalid components: {sorted(bad_fields)}"
        )

def _decompose_complex_components(payload: Dict[str, Any]) -> None:
    """Apply deterministic decomposition templates to complex components.
    
    - Does NOT depend on LLM output correctness
    - Uses component.type, shape_semantics.class, and keywords to trigger decomposition
    - Auto-generates sub-components and connection_requirements
    - Must be called AFTER _normalize_connection_requirements, BEFORE _fill_missing_dimensions
    """
    
    components = payload.get("components", [])
    connection_requirements = payload.get("connection_requirements", [])
    if not isinstance(components, list) or not isinstance(connection_requirements, list):
        return
    
    comp_by_id: dict[str, dict] = {
        c.get("id"): c
        for c in components if isinstance(c, dict) and c.get("id")
    }

    ordered_templates = [
        "wheel",
        "shaft",
        "bearing_unit",
        "motor_gearbox",
        "coupling",
        "plate_assembly",
    ]
    template_predicates: dict[str, Any] = {
        "wheel": _should_decompose_wheel,
        "shaft": _should_decompose_shaft,
        "bearing_unit": _should_decompose_bearing_unit,
        "motor_gearbox": _should_decompose_motor_gearbox,
        "coupling": _should_decompose_coupling,
        "plate_assembly": _should_decompose_plate_assembly,
    }

    decomposition_queue: list[tuple[str, str, dict, float]] = []
    guardrail_report: dict[str, Any] = {
        "threshold": DECOMPOSITION_CONFIDENCE_THRESHOLD,
        "candidates": 0,
        "selected": 0,
        "skipped_low_confidence": 0,
        "skipped_child_component": 0,
        "skipped_existing_signature": 0,
        "skipped_budget": 0,
    }

    for comp in list(components):
        if not isinstance(comp, dict) or not comp.get("id"):
            continue
        if comp.get("type") == "module":
            continue

        comp_id = comp.get("id")
        if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
            guardrail_report["skipped_child_component"] += 1
            continue

        selected_template: str | None = None
        selected_confidence = 0.0
        for template_name in ordered_templates:
            predicate = template_predicates[template_name]
            if not predicate(comp):
                continue
            guardrail_report["candidates"] += 1
            confidence = _component_decomposition_confidence(comp, template_name)
            if confidence < DECOMPOSITION_CONFIDENCE_THRESHOLD:
                guardrail_report["skipped_low_confidence"] += 1
                continue
            if _has_existing_decomposition_signature(str(comp_id), template_name, components):
                guardrail_report["skipped_existing_signature"] += 1
                continue
            selected_template = template_name
            selected_confidence = confidence
            break

        if selected_template:
            decomposition_queue.append((str(comp_id), selected_template, comp, selected_confidence))

    original_count = len([c for c in components if isinstance(c, Mapping)])
    max_added = max(6, int(original_count * DECOMPOSITION_MAX_ADDED_RATIO))
    applied = 0

    for parent_id, template_name, parent_comp, confidence in decomposition_queue:
        before_count = len(components)
        if template_name == "wheel":
            _decompose_wheel_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "shaft":
            _decompose_shaft_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "bearing_unit":
            _decompose_bearing_unit_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "motor_gearbox":
            _decompose_motor_gearbox_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "coupling":
            _decompose_coupling_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )
        elif template_name == "plate_assembly":
            _decompose_plate_assembly_template(
                payload, parent_id, parent_comp, components, connection_requirements, comp_by_id
            )

        added = len(components) - before_count
        if added > 0:
            applied += 1
            if len(components) - original_count >= max_added:
                guardrail_report["skipped_budget"] += max(0, len(decomposition_queue) - applied)
                break

    guardrail_report["selected"] = applied
    guardrail_report["components_before"] = original_count
    guardrail_report["components_after"] = len(components)
    guardrail_report["max_added_components"] = max_added

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["decomposition_guardrail"] = guardrail_report

def _should_decompose_wheel(comp: dict) -> bool:
    """Check if component should trigger wheel decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "wheel":
        return True
    
    shape = comp.get("shape_semantics")
    if isinstance(shape, dict) and shape.get("type") == "wheel":
        return True
    
    return False

def _should_decompose_shaft(comp: dict) -> bool:
    """Check if component should trigger shaft decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type in {"shaft", "axle", "pin"}:
        return True

    return False

def _should_decompose_bearing_unit(comp: dict) -> bool:
    """Check if component should trigger bearing unit decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "bearing":
        return True

    return False

def _should_decompose_motor_gearbox(comp: dict) -> bool:
    """Check if component should trigger motor+gearbox decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    is_motor = comp_type in {"motor", "electric_motor"}
    is_gearbox = comp_type in {"gearbox", "gear_reducer", "减速器"}

    return is_motor or is_gearbox

def _should_decompose_coupling(comp: dict) -> bool:
    """Check if component should trigger coupling decomposition."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type == "coupling":
        return True

    return False

def _should_decompose_plate_assembly(comp: dict) -> bool:
    """Check if component is part of plate pair (top+bottom) that should be decomposed."""
    if isinstance(comp.get("parent_id"), str) and comp.get("parent_id"):
        return False
    comp_type = str(comp.get("type", "")).lower()
    if comp_type not in {"plate_assembly", "carrier_plate"}:
        return False

    return True

def _wheel_requires_opposed_bearing_stack(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when the wheel explicitly requests a stacked support package."""

    evidence_tokens = {
        "dual_bearing",
        "double_bearing",
        "opposed_bearing",
        "opposed bearing",
        "bearing_pair",
        "pair_of_bearings",
        "two_bearings",
        "second_bearing",
        "spacer_stack",
        "spacer stack",
        "axial_capture_with_spacer_stack",
        "retaining_nut",
        "retaining nut",
        "locknut",
    }
    bearing_count_keys = {
        "bearing_count",
        "support_bearing_count",
        "bearing_quantity",
        "number_of_bearings",
    }
    explicit_child_ids = {
        f"{parent_id}_bearing_2",
        f"{parent_id}_spacer",
    }
    fastener_component_id = f"{parent_id}_fastener_set"
    related_component_ids = {
        parent_id,
        f"{parent_id}_axle",
        f"{parent_id}_hub",
        f"{parent_id}_bearing_1",
        fastener_component_id,
        *explicit_child_ids,
    }

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _parse_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value) > 0:
            return int(round(float(value)))
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = float(candidate)
            except ValueError:
                return None
            if parsed > 0:
                return int(round(parsed))
        return None

    def _contains_stack_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _fastener_requests_axial_stack(comp: Mapping[str, Any]) -> bool:
        role = str(comp.get("role") or "").strip().lower()
        if any(token in role for token in ("axial", "retention", "locknut")):
            return True

        for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
            raw = comp.get(section)
            if not isinstance(raw, Mapping):
                continue
            for item in _walk_scalars(raw):
                if not isinstance(item, str):
                    continue
                normalized = item.strip().lower()
                if any(
                    token in normalized
                    for token in (
                        "axial_retention",
                        "axial retention",
                        "axial_clamping",
                        "axial clamping",
                        "locknut",
                        "retaining_nut",
                        "retaining nut",
                        "threaded_shaft",
                        "nut_on_threaded_shaft",
                        "nut_only",
                        "inner_race_capture",
                    )
                ):
                    return True
        return False

    def _mapping_requests_stack(mapping: Mapping[str, Any]) -> bool:
        for key in bearing_count_keys:
            count = _parse_positive_int(mapping.get(key))
            if count is not None and count >= 2:
                return True
        return any(_contains_stack_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_stack(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_stack(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type == "spacer":
            return True
        if comp_type in {"fastener", "fastener_set", "bolt_set"} and _fastener_requests_axial_stack(comp):
            return True
        if comp_type == "bearing" and isinstance(comp_id, str) and "_bearing_2" in comp_id:
            return True
        if any(_contains_stack_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if str(cr.get("purpose") or "").strip().lower() == "spacing":
            return True
        lower_id = cr_id.lower()
        if any(token in lower_id for token in ("bearing_2", "spacer_axial", "fastener_axial_clamping")):
            return True
        if any(_contains_stack_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_stack_token(item) for item in _walk_scalars(intent)):
                return True

    return False

def _decompose_wheel_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a wheel into rim, tire, hub, axle, and a single default bearing.

    Add a second bearing, spacer, and axial retention hardware only when the
    source payload explicitly requests an opposed bearing stack.
    """

    parent_dims = parent_comp.get("dimensions", {})
    parent_diameter = parent_dims.get("outer_diameter")
    parent_width = parent_dims.get("thickness")
    requires_opposed_bearing_stack = _wheel_requires_opposed_bearing_stack(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    )
    support_architecture = "opposed_bearing_stack" if requires_opposed_bearing_stack else "single_bearing_through_bore"

    parent_comp["kind"] = "assembly_node"
    parent_comp["modeling_policy"] = "container_only"
    parent_comp["must_model"] = False
    parent_comp["is_container"] = True
    parent_comp["is_container_only"] = True
    parent_comp["is_modeling_unit"] = False
    parent_comp["has_geometry"] = False
    parent_comp["dimensions"] = {}
    parent_comp["parameters"] = {}
    parent_comp["dimension_sources"] = {}
    parent_comp["shape_semantics"] = {
        "type": "assembly_node",
        "notes": "decomposed_wheel_container",
        "support_architecture": support_architecture,
    }

    body_id = f"{parent_id}_body"
    rim_id = f"{parent_id}_rim"
    tire_id = f"{parent_id}_tire"
    hub_id = f"{parent_id}_hub"
    axle_id = f"{parent_id}_axle"
    bearing_1_id = f"{parent_id}_bearing_1"
    bearing_2_id = f"{parent_id}_bearing_2"
    spacer_id = f"{parent_id}_spacer"
    fastener_set_id = f"{parent_id}_fastener_set"

    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}

    child_ids = [rim_id, tire_id, hub_id, axle_id, bearing_1_id]
    if requires_opposed_bearing_stack:
        child_ids.extend([bearing_2_id, spacer_id, fastener_set_id])
    child_ids = [cid for cid in child_ids if cid not in existing_ids]

    if not child_ids:
        return

    new_components = []

    if body_id in existing_ids and rim_id not in existing_ids:
        rim_id = body_id
    if rim_id not in existing_ids:
        rim_comp = {
            "id": rim_id,
            "type": "rim",
            "role": "structural",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            rim_outer = round(parent_diameter * 0.72, 2)
            rim_comp["dimensions"]["outer_diameter"] = rim_outer
            rim_comp["dimension_sources"]["outer_diameter"] = {"source": "derived", "derived_from": ["parent.outer_diameter * 0.72"]}
        if parent_width is not None:
            rim_comp["dimensions"]["thickness"] = parent_width
            rim_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(rim_comp)
    if tire_id not in existing_ids:
        tire_comp = {
            "id": tire_id,
            "type": "tire",
            "role": "contact",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            tire_comp["dimensions"]["outer_diameter"] = parent_diameter
            tire_comp["dimension_sources"]["outer_diameter"] = {"source": "derived", "derived_from": ["parent.outer_diameter"]}
            rim_outer = round(parent_diameter * 0.72, 2)
            tire_comp["dimensions"]["inner_diameter"] = rim_outer
            tire_comp["dimension_sources"]["inner_diameter"] = {"source": "derived", "derived_from": ["rim.outer_diameter"]}
        if parent_width is not None:
            tire_comp["dimensions"]["thickness"] = parent_width
            tire_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(tire_comp)
    if hub_id not in existing_ids:
        hub_comp = {
            "id": hub_id,
            "type": "hub",
            "role": "rotation",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if parent_diameter is not None:
            hub_comp["dimensions"]["outer_diameter"] = round(parent_diameter * 0.4, 2)
            hub_comp["dimension_sources"]["outer_diameter"] = {"source": "derived"}
        if parent_width is not None:
            hub_comp["dimensions"]["thickness"] = parent_width
            hub_comp["dimension_sources"]["thickness"] = {"source": "derived"}
        new_components.append(hub_comp)

    if axle_id not in existing_ids:
        axle_comp = {
            "id": axle_id,
            "type": "axle",
            "role": "rotation",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        axle_comp["dimensions"]["diameter"] = 8
        axle_comp["dimension_sources"]["diameter"] = {
            "source": "inferred_default",
            "confidence": 0.4,
        }
        new_components.append(axle_comp)

    if bearing_1_id not in existing_ids:
        bearing_1_comp = {
            "id": bearing_1_id,
            "type": "bearing",
            "role": "load_support",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {"bore_diameter": 8, "outer_diameter": 22, "width": 7},
            "dimension_sources": {
                "bore_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "outer_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "width": {"source": "standard_catalog", "confidence": 0.9},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(bearing_1_comp)

    if requires_opposed_bearing_stack and bearing_2_id not in existing_ids:
        bearing_2_comp = {
            "id": bearing_2_id,
            "type": "bearing",
            "role": "load_support",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {"bore_diameter": 8, "outer_diameter": 22, "width": 7},
            "dimension_sources": {
                "bore_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "outer_diameter": {"source": "standard_catalog", "confidence": 0.9},
                "width": {"source": "standard_catalog", "confidence": 0.9},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(bearing_2_comp)

    if requires_opposed_bearing_stack and spacer_id not in existing_ids:
        spacer_comp = {
            "id": spacer_id,
            "type": "spacer",
            "role": "spacing",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {},
            "dimensions": {
                "inner_diameter": 8,
                "outer_diameter": 12,
                "length": 5,
            },
            "dimension_sources": {
                "inner_diameter": {"source": "derived", "confidence": 0.7},
                "outer_diameter": {"source": "derived", "confidence": 0.6},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(spacer_comp)

    if requires_opposed_bearing_stack and fastener_set_id not in existing_ids:
        axle_diameter = 8.0
        axle_comp_existing = comp_by_id.get(axle_id) if isinstance(comp_by_id, dict) else None
        if isinstance(axle_comp_existing, dict):
            axle_dims_existing = axle_comp_existing.get("dimensions")
            if isinstance(axle_dims_existing, dict):
                axle_d = axle_dims_existing.get("diameter")
                if isinstance(axle_d, (int, float)) and float(axle_d) > 0:
                    axle_diameter = float(axle_d)

        for comp in new_components:
            if isinstance(comp, dict) and comp.get("id") == axle_id:
                axle_dims_new = comp.get("dimensions")
                if isinstance(axle_dims_new, dict):
                    axle_d_new = axle_dims_new.get("diameter")
                    if isinstance(axle_d_new, (int, float)) and float(axle_d_new) > 0:
                        axle_diameter = float(axle_d_new)
                break

        count = 1
        nominal_diameter = float(axle_diameter)
        length = max(12.0, round(nominal_diameter * 2.0, 1))
        fastener_comp = {
            "id": fastener_set_id,
            "type": "fastener",
            "role": "axial_retention",
            "parent_id": parent_id,
            "position_parent": parent_id,
            "parameters": {
                "count": count,
                "nominal_diameter": nominal_diameter,
                "length": length,
                "bundle_style": "nut_only",
                "application": "axial_retention",
            },
            "dimensions": {
                "count": count,
                "nominal_diameter": nominal_diameter,
                "length": length,
                "bundle_style": "nut_only",
                "application": "axial_retention",
            },
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "derived", "confidence": 0.8},
                "length": {"source": "inferred_default", "confidence": 0.4},
                "bundle_style": {"source": "derived", "confidence": 0.8},
                "application": {"source": "derived", "confidence": 0.8},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(fastener_comp)

    components.extend(new_components)

    new_connections = []

    contract_component_lookup = dict(comp_by_id) if isinstance(comp_by_id, Mapping) else {}
    contract_component_lookup[parent_id] = parent_comp

    body_ref_id = hub_id
    rotation_req = {
        "id": f"req_{parent_id}_body_axle_rotation",
        "between": [body_ref_id, axle_id],
        "purpose": "rotation",
        "roles": ["rotation"],
        "constraints": {
            "coaxial_required": True,
            "allow_rotation": True,
            "lock_translation": True,
        },
        "connection_semantics": {
            "connection_mechanism": "shaft_bore_fit",
            "relation_type": "rotation",
            "reference_component_id": axle_id,
            "moving_component_id": body_ref_id,
            "reference_anchor": {"kind": "component_center"},
            "moving_anchor": {"kind": "component_center"},
            "reference_interface_hint": "bore_axis",
            "moving_interface_hint": "bore_axis",
            "orientation_policy": "free",
            "rationale": "Wheel body rotates around the axle on a shared bore axis.",
        },
    }
    new_connections.append(rotation_req)

    bearing_support_1 = {
        "id": f"req_{parent_id}_bearing_1_body_support",
        "between": [bearing_1_id, body_ref_id],
        "purpose": "load_support",
        "roles": ["mounting"],
        "constraints": {"concentric_required": True},
        "connection_semantics": _build_bearing_outer_race_seat_contract(
            host_component_id=body_ref_id,
            bearing_component_id=bearing_1_id,
            rationale="Bearing outer ring seats in the wheel body to provide structural radial support.",
            component_lookup=contract_component_lookup,
        ),
    }
    new_connections.append(bearing_support_1)

    bearing_rotation_1 = {
        "id": f"req_{parent_id}_bearing_1_axle_rotation",
        "between": [bearing_1_id, axle_id],
        "purpose": "rotation_support",
        "roles": ["rotation"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(bearing_rotation_1)

    if requires_opposed_bearing_stack:
        bearing_support_2 = {
            "id": f"req_{parent_id}_bearing_2_body_support",
            "between": [bearing_2_id, body_ref_id],
            "purpose": "load_support",
            "roles": ["mounting"],
            "constraints": {"concentric_required": True},
            "connection_semantics": _build_bearing_outer_race_seat_contract(
                host_component_id=body_ref_id,
                bearing_component_id=bearing_2_id,
                rationale="Bearing outer ring seats in the wheel body to provide structural radial support.",
                component_lookup=contract_component_lookup,
            ),
        }
        new_connections.append(bearing_support_2)

        bearing_rotation_2 = {
            "id": f"req_{parent_id}_bearing_2_axle_rotation",
            "between": [bearing_2_id, axle_id],
            "purpose": "rotation_support",
            "roles": ["rotation"],
            "constraints": {"coaxial_required": True},
        }
        new_connections.append(bearing_rotation_2)

        spacer_constraint = {
            "id": f"req_{parent_id}_spacer_axial",
            "between": [spacer_id, bearing_1_id, bearing_2_id],
            "purpose": "spacing",
            "roles": ["spacing"],
            "constraints": {"gap": parent_width if parent_width else 5},
        }
        new_connections.append(spacer_constraint)

        axial_fastener_nominal = 8.0
        axial_fastener_length = 16.0

        existing_fastener_comp = comp_by_id.get(fastener_set_id) if isinstance(comp_by_id, dict) else None
        if isinstance(existing_fastener_comp, dict):
            existing_dims = existing_fastener_comp.get("dimensions")
            if isinstance(existing_dims, dict):
                existing_nominal = existing_dims.get("nominal_diameter")
                if isinstance(existing_nominal, (int, float)) and float(existing_nominal) > 0:
                    axial_fastener_nominal = float(existing_nominal)
                existing_length = existing_dims.get("length")
                if isinstance(existing_length, (int, float)) and float(existing_length) > 0:
                    axial_fastener_length = float(existing_length)

        for comp in new_components:
            if isinstance(comp, dict) and comp.get("id") == fastener_set_id:
                new_dims = comp.get("dimensions")
                if isinstance(new_dims, dict):
                    new_nominal = new_dims.get("nominal_diameter")
                    if isinstance(new_nominal, (int, float)) and float(new_nominal) > 0:
                        axial_fastener_nominal = float(new_nominal)
                    new_length = new_dims.get("length")
                    if isinstance(new_length, (int, float)) and float(new_length) > 0:
                        axial_fastener_length = float(new_length)
                break

        axial_fastener_size = _nearest_fastener_designation(axial_fastener_nominal, axial_fastener_length)
        fastening_req = {
            "id": f"req_{parent_id}_fastener_axial_clamping",
            "between": [fastener_set_id, axle_id],
            "purpose": "fastening_mechanism",
            "roles": ["fixation"],
            "constraints": {
                "axial_preload": True,
                "retention": "nut_on_threaded_shaft",
            },
            "connection_decision": {
                "method": "bolted_rigid",
                "count": 1,
                "fit_policy": "close_fit",
                "lock": True,
                "fastener_ref_component_id": fastener_set_id,
                "fastener_size": axial_fastener_size,
                "rationale": "Axial retention uses a single nut/washer on shaft; bolt circle forbidden.",
            },
        }
        new_connections.append(fastening_req)

    connection_requirements.extend(new_connections)

    if rim_id and hub_id:
        connection_requirements.append({
            "id": f"req_{parent_id}_rim_hub_fix",
            "between": [rim_id, hub_id],
            "purpose": "structural_fixation",
            "roles": ["mounting", "fixation"],
        })
    if tire_id and rim_id:
        connection_requirements.append({
            "id": f"req_{parent_id}_tire_rim_fix",
            "between": [tire_id, rim_id],
            "purpose": "structural_fixation",
            "roles": ["mounting", "fixation"],
            "connection_semantics": {
                "connection_mechanism": "bonded_tread",
                "relation_type": "fixation",
                "reference_component_id": rim_id,
                "moving_component_id": tire_id,
                "reference_anchor": {"kind": "component_center"},
                "moving_anchor": {"kind": "component_center"},
                "reference_interface_hint": "radial_outer_face",
                "moving_interface_hint": "radial_inner_face",
                "orientation_policy": "locked",
                "rationale": "Tire is retained on the rim as a bonded or seated tread, not by through-fasteners.",
            },
        })

def _shaft_requires_auxiliary_retention_stack(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when a shaft explicitly asks for retainers or spacer hardware."""

    evidence_tokens = {
        "retainer",
        "retention",
        "retaining_ring",
        "snap_ring",
        "circlip",
        "locknut",
        "shaft_collar",
        "collar",
        "threaded_end",
        "threaded shaft",
        "axial_preload",
    }
    truthy_keys = {
        "requires_retention_hardware",
        "retention_hardware",
        "requires_retainers",
        "has_threaded_end",
        "threaded_end",
    }
    count_keys = {"retainer_count", "retainer_quantity"}
    explicit_child_ids = {
        f"{parent_id}_retainer_left",
        f"{parent_id}_retainer_right",
        f"{parent_id}_spacer",
    }
    related_component_ids = {parent_id, *explicit_child_ids}

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _parse_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value) > 0:
            return int(round(float(value)))
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = float(candidate)
            except ValueError:
                return None
            if parsed > 0:
                return int(round(parsed))
        return None

    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "required"}
        return False

    def _contains_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _mapping_requests_retention(mapping: Mapping[str, Any]) -> bool:
        for key in truthy_keys:
            if _is_truthy(mapping.get(key)):
                return True
        for key in count_keys:
            count = _parse_positive_int(mapping.get(key))
            if count is not None and count > 0:
                return True
        return any(_contains_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_retention(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_retention(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {"retainer", "spacer", "fastener", "fastener_set", "bolt_set"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if str(cr.get("purpose") or "").strip().lower() in {"spacing", "fastening_mechanism"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_token(item) for item in _walk_scalars(intent)):
                return True

    return False

def _decompose_shaft_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a shaft only when retention hardware is explicitly requested.
    """

    if not _shaft_requires_auxiliary_retention_stack(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    ):
        return

    # Generate child component IDs
    retainer_left_id = f"{parent_id}_retainer_left"
    retainer_right_id = f"{parent_id}_retainer_right"
    spacer_id = f"{parent_id}_spacer"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [retainer_left_id, retainer_right_id, spacer_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    # Get shaft diameter if available
    shaft_dims = parent_comp.get("dimensions", {})
    shaft_diameter = shaft_dims.get("diameter")
    
    new_components = []
    
    # shaft_retainer_left
    if retainer_left_id not in existing_ids:
        retainer_l = {
            "id": retainer_left_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        if shaft_diameter:
            retainer_l["dimensions"]["bore_diameter"] = shaft_diameter
            retainer_l["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(retainer_l)
    
    # shaft_retainer_right
    if retainer_right_id not in existing_ids:
        retainer_r = {
            "id": retainer_right_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        if shaft_diameter:
            retainer_r["dimensions"]["bore_diameter"] = shaft_diameter
            retainer_r["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(retainer_r)
    
    # shaft_spacer (optional but recommended)
    if spacer_id not in existing_ids:
        spacer = {
            "id": spacer_id,
            "type": "spacer",
            "role": "spacing",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {
                "inner_diameter": shaft_diameter if shaft_diameter else 8,
                "outer_diameter": (shaft_diameter + 4) if shaft_diameter else 12,
                "length": 3,
            },
            "dimension_sources": {
                "inner_diameter": {"source": "derived", "confidence": 0.8},
                "outer_diameter": {"source": "derived", "confidence": 0.7},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(spacer)
    
    components.extend(new_components)
    
    # Auto-generate connection_requirements
    new_connections = []
    
    # Retaining
    for retainer_id in [retainer_left_id, retainer_right_id]:
        if retainer_id not in existing_ids:
            req = {
                "id": f"req_{retainer_id}_retention",
                "between": [retainer_id, parent_id],
                "purpose": "fastening_mechanism",
                "roles": ["fixation"],
                "constraints": {"axial_retention": True},
            }
            new_connections.append(req)
    
    connection_requirements.extend(new_connections)

def _bearing_unit_requires_auxiliary_components(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: Mapping[str, Any],
    components: list,
    connection_requirements: list,
) -> bool:
    """Return True only when a bearing explicitly asks for seat or retainer hardware."""

    evidence_tokens = {
        "bearing_seat",
        "outer_race_seat",
        "retainer",
        "retention",
        "snap_ring",
        "circlip",
        "end_cap",
        "cartridge",
    }
    truthy_keys = {
        "requires_bearing_seat",
        "requires_retainer",
        "requires_housing",
        "cartridge_unit",
    }
    explicit_child_ids = {f"{parent_id}_seat", f"{parent_id}_retainer"}
    related_component_ids = {parent_id, *explicit_child_ids}

    def _walk_scalars(value: Any):
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                yield from _walk_scalars(nested_key)
                yield from _walk_scalars(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                yield from _walk_scalars(nested_value)
            return
        yield value

    def _contains_token(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return any(token in normalized for token in evidence_tokens)

    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "required"}
        return False

    def _mapping_requests_auxiliary_components(mapping: Mapping[str, Any]) -> bool:
        for key in truthy_keys:
            if _is_truthy(mapping.get(key)):
                return True
        return any(_contains_token(item) for item in _walk_scalars(mapping))

    if _mapping_requests_auxiliary_components(parent_comp):
        return True

    for section in ("parameters", "dimensions", "shape_semantics", "metadata"):
        raw = parent_comp.get(section)
        if isinstance(raw, Mapping) and _mapping_requests_auxiliary_components(raw):
            return True

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_id = comp.get("id")
        if isinstance(comp_id, str) and comp_id in explicit_child_ids:
            return True
        if comp.get("parent_id") != parent_id:
            continue
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {"bearing_seat", "retainer", "housing"}:
            return True
        if any(_contains_token(item) for item in _walk_scalars(comp)):
            return True

    for cr in connection_requirements:
        if not isinstance(cr, Mapping):
            continue
        between = [cid for cid in cr.get("between", []) if isinstance(cid, str)]
        cr_id = str(cr.get("id") or "")
        if not (set(between) & related_component_ids or parent_id in cr_id):
            continue
        if any(cid in explicit_child_ids for cid in between):
            return True
        if any(_contains_token(item) for item in _walk_scalars(cr)):
            return True

    design_intents = payload.get("design_intents")
    if isinstance(design_intents, list):
        for intent in design_intents:
            if not isinstance(intent, Mapping):
                continue
            component_ids = [cid for cid in intent.get("component_ids", []) if isinstance(cid, str)]
            if parent_id not in component_ids and not any(cid.startswith(f"{parent_id}_") for cid in component_ids):
                continue
            if any(_contains_token(item) for item in _walk_scalars(intent)):
                return True

    return False

def _decompose_bearing_unit_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose a bearing only when seat or retainer hardware is explicitly requested.
    """

    if not _bearing_unit_requires_auxiliary_components(
        payload=payload,
        parent_id=parent_id,
        parent_comp=parent_comp,
        components=components,
        connection_requirements=connection_requirements,
    ):
        return

    seat_id = f"{parent_id}_seat"
    retainer_id = f"{parent_id}_retainer"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    
    # Bearing is typically already decomposed; just add seat and retainer if missing
    new_components = []
    
    # Bearing seat (structural feature, can be virtual)
    if seat_id not in existing_ids:
        seat = {
            "id": seat_id,
            "type": "bearing_seat",
            "role": "mounting",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        # Bearing outer diameter should match seat bore
        bearing_dims = parent_comp.get("dimensions", {})
        if "outer_diameter" in bearing_dims:
            seat["dimensions"]["bore_diameter"] = bearing_dims.get("outer_diameter")
            seat["dimension_sources"]["bore_diameter"] = {"source": "standard_catalog"}
        new_components.append(seat)
    
    # Retainer (cap, e-clip, or snap ring)
    if retainer_id not in existing_ids:
        retainer = {
            "id": retainer_id,
            "type": "retainer",
            "role": "fixation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        new_components.append(retainer)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    if seat_id not in existing_ids:
        req = {
            "id": f"req_{parent_id}_seat_fixation",
            "between": [parent_id, seat_id],
            "purpose": "structural_fixation",
            "roles": ["mounting"],
            "constraints": {"concentric_required": True},
        }
        new_connections.append(req)
    
    if retainer_id not in existing_ids:
        req = {
            "id": f"req_{parent_id}_retainer_fixation",
            "between": [retainer_id, parent_id],
            "purpose": "fastening_mechanism",
            "roles": ["fixation"],
            "constraints": {"axial_retention": True},
        }
        new_connections.append(req)
    
    connection_requirements.extend(new_connections)

def _decompose_motor_gearbox_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    If component is motor/gearbox, ensure output_shaft is explicit.
    Generate: motor (black-box), gearbox (black-box), output_shaft, mounting_flange
    """
    comp_type = str(parent_comp.get("type", "")).lower()

    # Detect if this is a combined motor+gearbox or separate
    is_motor = "motor" in comp_type or "电机" in parent_id
    is_gearbox = "gearbox" in comp_type or "减速器" in parent_id

    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    
    # If it's already a motor or gearbox separately, check if output_shaft exists
    if is_motor or is_gearbox:
        shaft_id = f"{parent_id}_output_shaft"
        flange_id = f"{parent_id}_mounting_flange"
        
        if shaft_id in existing_ids:
            return  # Already decomposed
        
        new_components = []
        
        # Output shaft
        shaft = {
            "id": shaft_id,
            "type": "shaft",
            "role": "rotation",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {"diameter": 6, "length": 20},
            "dimension_sources": {
                "diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(shaft)
        
        # Mounting flange
        flange = {
            "id": flange_id,
            "type": "mounting_flange",
            "role": "mounting",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {"diameter": 40, "thickness": 5},
            "dimension_sources": {
                "diameter": {"source": "inferred_default", "confidence": 0.4},
                "thickness": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "plate", "cross_section": "rectangular"},
        }
        new_components.append(flange)
        
        components.extend(new_components)
        
        # Auto-generate connections
        new_connections = []
        
        # Output shaft 闁?gearbox (torque transfer)
        req = {
            "id": f"req_{parent_id}_output_shaft_connection",
            "between": [shaft_id, parent_id],
            "purpose": "torque_transfer",
            "roles": ["rotation", "torque_transfer"],
            "constraints": {"coaxial_required": True},
        }
        new_connections.append(req)
        
        # Mounting flange 闁?motor/gearbox (structural fixation)
        req = {
            "id": f"req_{parent_id}_mounting_flange",
            "between": [flange_id, parent_id],
            "purpose": "structural_fixation",
            "roles": ["mounting"],
        }
        new_connections.append(req)
        
        connection_requirements.extend(new_connections)

def _decompose_coupling_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose coupling into: coupling_body, clamp_screw_set, optional key
    """
    
    body_id = f"{parent_id}_body"
    screw_set_id = f"{parent_id}_clamp_screw_set"
    key_id = f"{parent_id}_key"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [body_id, screw_set_id, key_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    coupling_dims = parent_comp.get("dimensions", {})
    bore_diameter = coupling_dims.get("bore_diameter")
    
    new_components = []
    
    # Coupling body
    if body_id not in existing_ids:
        body = {
            "id": body_id,
            "type": "coupling_body",
            "role": "torque_transfer",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        if bore_diameter:
            body["dimensions"]["bore_diameter"] = bore_diameter
            body["dimension_sources"]["bore_diameter"] = {"source": "derived"}
        new_components.append(body)
    
    # Clamp screw bundle
    if screw_set_id not in existing_ids:
        count = 2
        screw_set = {
            "id": screw_set_id,
            "type": "fastener",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": count, "nominal_diameter": 4.0, "length": 12.0},
            "dimensions": {"count": count, "nominal_diameter": 4.0, "length": 12.0},
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {"source": "inferred_default", "confidence": 0.4},
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(screw_set)
    
    # Key (optional but useful)
    if key_id not in existing_ids:
        key = {
            "id": key_id,
            "type": "key",
            "role": "torque_transfer",
            "parent_id": parent_id,
            "parameters": {},
            "dimensions": {
                "width": bore_diameter / 4 if bore_diameter else 2,
                "height": bore_diameter / 4 if bore_diameter else 2,
                "length": bore_diameter / 2 if bore_diameter else 4,
            },
            "dimension_sources": {
                "width": {"source": "derived", "confidence": 0.6},
                "height": {"source": "derived", "confidence": 0.6},
                "length": {"source": "derived", "confidence": 0.6},
            },
            "shape_semantics": {"type": "prismatic", "cross_section": "rectangular"},
        }
        new_components.append(key)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    # Coupling body 闁?shaft
    req = {
        "id": f"req_{parent_id}_body_shaft",
        "between": [body_id, parent_id],
        "purpose": "torque_transfer",
        "roles": ["torque_transfer"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(req)
    
    # Clamp screw 闁?coupling body
    req = {
        "id": f"req_{parent_id}_screw_fastening",
        "between": [screw_set_id, body_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    # Key (optional, for additional torque transfer)
    req = {
        "id": f"req_{parent_id}_key_shaft",
        "between": [key_id, parent_id],
        "purpose": "torque_transfer",
        "roles": ["torque_transfer"],
        "constraints": {"coaxial_required": True},
    }
    new_connections.append(req)
    
    connection_requirements.extend(new_connections)

def _decompose_plate_assembly_template(
    payload: Dict[str, Any],
    parent_id: str,
    parent_comp: dict,
    components: list,
    connection_requirements: list,
    comp_by_id: dict,
) -> None:
    """
    Decompose plate assembly into: standoff_set, bolt_set, nut_set
    """
    
    standoff_id = f"{parent_id}_standoff_set"
    bolt_id = f"{parent_id}_bolt_set"
    nut_id = f"{parent_id}_nut_set"
    
    existing_ids = {c.get("id") for c in components if isinstance(c, dict)}
    child_ids = [standoff_id, bolt_id, nut_id]
    child_ids = [cid for cid in child_ids if cid not in existing_ids]
    
    if not child_ids:
        return
    
    plate_dims = parent_comp.get("dimensions", {})
    plate_thickness = plate_dims.get("thickness", 3)
    
    new_components = []
    
    # Standoff set
    if standoff_id not in existing_ids:
        standoff = {
            "id": standoff_id,
            "type": "standoff_set",
            "role": "spacing",
            "parent_id": parent_id,
            "parameters": {"count": 4},
            "dimensions": {
                "inner_diameter": 4,
                "outer_diameter": 6,
                "length": plate_thickness + 5,
            },
            "dimension_sources": {
                "length": {
                    "source": "derived",
                    "derived_from": [f"{parent_id}.thickness"],
                    "confidence": 0.7,
                }
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "annular"},
        }
        new_components.append(standoff)
    
    # Bolt set
    if bolt_id not in existing_ids:
        bolt = {
            "id": bolt_id,
            "type": "fastener",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": 4, "nominal_diameter": 4.0, "length": float(plate_thickness) + 8.0},
            "dimensions": {"count": 4, "nominal_diameter": 4.0, "length": float(plate_thickness) + 8.0},
            "dimension_sources": {
                "count": {"source": "inferred_default", "confidence": 0.5},
                "nominal_diameter": {"source": "inferred_default", "confidence": 0.4},
                "length": {
                    "source": "derived",
                    "derived_from": [f"{parent_id}.thickness"],
                    "confidence": 0.6,
                },
            },
            "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
        }
        new_components.append(bolt)
    
    # Nut set
    if nut_id not in existing_ids:
        nut = {
            "id": nut_id,
            "type": "nut_set",
            "role": "fastening",
            "parent_id": parent_id,
            "parameters": {"count": 4},
            "dimensions": {},
            "dimension_sources": {},
            "shape_semantics": {"type": "complex"},
        }
        new_components.append(nut)
    
    components.extend(new_components)
    
    # Auto-generate connections
    new_connections = []
    
    # Standoff 闁?plate (spacing constraint)
    req = {
        "id": f"req_{parent_id}_standoff_spacing",
        "between": [standoff_id, parent_id],
        "purpose": "spacing",
        "roles": ["spacing"],
        "constraints": {"gap": plate_thickness + 5},
    }
    new_connections.append(req)
    
    # Bolt 闁?plate (fastening)
    req = {
        "id": f"req_{parent_id}_bolt_fastening",
        "between": [bolt_id, parent_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    # Nut 闁?bolt (fastening pair)
    req = {
        "id": f"req_{parent_id}_nut_bolt",
        "between": [nut_id, bolt_id],
        "purpose": "fastening_mechanism",
        "roles": ["fixation"],
    }
    new_connections.append(req)
    
    connection_requirements.extend(new_connections)

def _fill_missing_dimensions(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    type_by_id: dict[str, str] = {}
    comp_by_id: dict[str, Mapping] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and isinstance(ctype, str):
            type_by_id[cid] = ctype
            comp_by_id[cid] = comp

    def _get_dim(dims: Mapping, *keys: str) -> float | None:
        for key in keys:
            value = dims.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _set_dim(
        dims: Dict[str, Any],
        sources: Dict[str, Any],
        key: str,
        value: float,
        derived_from: list[str] | None = None,
        source: str = "derived",
        confidence: float | None = None,
    ) -> None:
        if key in dims:
            return
        dims[key] = float(value)
        sources[key] = {
            "source": source,
            "derived_from": derived_from or [],
        }
        if confidence is not None:
            sources[key]["confidence"] = float(confidence)

    def _related_component_ids(comp_id: str) -> set[str]:
        related: set[str] = set()
        for cr in payload.get("connection_requirements", []) or []:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if isinstance(between, list) and comp_id in between:
                for cid in between:
                    if isinstance(cid, str) and cid != comp_id:
                        related.add(cid)
        return related

    def _find_related_dim(comp_id: str, target_types: set[str], dim_keys: list[str]) -> float | None:
        for other_id in _related_component_ids(comp_id):
            if type_by_id.get(other_id) not in target_types:
                continue
            other = comp_by_id.get(other_id, {})
            dims_other = other.get("dimensions") if isinstance(other, Mapping) else None
            if isinstance(dims_other, Mapping):
                value = _get_dim(dims_other, *dim_keys)
                if isinstance(value, (int, float)):
                    return float(value)
        return None

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        if comp.get("type") == "subassembly":
            continue

        dims = comp.get("dimensions")
        if not isinstance(dims, Mapping):
            dims = {}
            comp["dimensions"] = dims
        dims = dict(dims)
        comp["dimensions"] = dims

        sources = comp.get("dimension_sources")
        if not isinstance(sources, Mapping):
            sources = {}
        sources = dict(sources)
        comp["dimension_sources"] = sources

        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else ""
        comp_type = comp.get("type") if isinstance(comp.get("type"), str) else ""

        if comp_type in {"wheel", "tire", "rim"}:
            radius = _get_dim(dims, "outer_radius", "radius")
            if radius is None:
                diameter = _get_dim(dims, "outer_diameter", "diameter")
                if diameter is not None:
                    radius = diameter / 2.0
                    _set_dim(dims, sources, "outer_radius", radius, ["outer_diameter"])

            # ----------------------------------------------------------
            # Rim / tire differentiation: rim sits inside the tire.
            # When no explicit outer_radius is present, derive from the
            # parent wheel component (already processed earlier in this
            # loop because the parent appears before children in the
            # component list).
            #   tire  -> keeps full parent wheel outer_radius
            #   rim   -> 72 % of parent wheel outer_radius
            # ----------------------------------------------------------
            if radius is None and comp_type in {"tire", "rim"}:
                parent_id = comp.get("parent_id") if isinstance(comp.get("parent_id"), str) else ""
                parent = comp_by_id.get(parent_id)
                if isinstance(parent, Mapping):
                    p_dims = parent.get("dimensions")
                    if isinstance(p_dims, Mapping):
                        parent_radius = _get_dim(p_dims, "outer_radius", "radius")
                        if parent_radius is not None:
                            if comp_type == "rim":
                                radius = round(parent_radius * 0.72, 2)
                                _set_dim(dims, sources, "outer_radius", radius,
                                         ["parent.outer_radius * 0.72"],
                                         source="derived", confidence=0.7)
                            else:  # tire
                                radius = parent_radius
                                _set_dim(dims, sources, "outer_radius", radius,
                                         ["parent.outer_radius"],
                                         source="derived", confidence=0.7)

            if radius is None:
                radius = 30.0
                _set_dim(dims, sources, "outer_radius", radius, ["default"], source="inferred_default", confidence=0.4)
            width = _get_dim(dims, "width", "thickness")
            if width is None:
                width = max(6.0, round(radius * 0.4, 2))
                _set_dim(dims, sources, "width", width, ["outer_radius"], source="derived", confidence=0.6)
            if _get_dim(dims, "thickness") is None and isinstance(width, (int, float)):
                _set_dim(dims, sources, "thickness", float(width), ["width"], source="derived", confidence=0.7)
            if comp_type in {"tire", "rim"}:
                inner_radius = _get_dim(dims, "inner_radius")
                if inner_radius is None and comp_type == "tire":
                    # Tire inner = rim outer; find sibling rim
                    _parent_id = comp.get("parent_id") if isinstance(comp.get("parent_id"), str) else ""
                    for sib in components:
                        if (isinstance(sib, Mapping) and sib.get("parent_id") == _parent_id
                                and sib.get("type") == "rim" and sib.get("id") != comp_id):
                            sib_dims = sib.get("dimensions") if isinstance(sib.get("dimensions"), Mapping) else {}
                            rim_outer = _get_dim(sib_dims, "outer_radius")
                            if rim_outer is not None:
                                inner_radius = rim_outer
                                _set_dim(dims, sources, "inner_radius", inner_radius,
                                         ["sibling_rim.outer_radius"],
                                         source="derived", confidence=0.7)
                            break
                if inner_radius is None and isinstance(radius, (int, float)):
                    inner_radius = max(0.1, round(float(radius) * 0.72, 2))
                    _set_dim(dims, sources, "inner_radius", inner_radius, ["outer_radius"], source="derived", confidence=0.6)
                if _get_dim(dims, "inner_diameter") is None and isinstance(inner_radius, (int, float)):
                    _set_dim(dims, sources, "inner_diameter", round(float(inner_radius) * 2.0, 2), ["inner_radius"], source="derived", confidence=0.7)

        if comp_type in {"hub"}:
            radius = _get_dim(dims, "outer_radius", "radius")
            if radius is None:
                diameter = _get_dim(dims, "outer_diameter", "diameter")
                if diameter is not None:
                    radius = diameter / 2.0
                    _set_dim(dims, sources, "outer_radius", radius, ["outer_diameter"])
            if radius is None:
                radius = 14.0
                _set_dim(dims, sources, "outer_radius", radius, ["default"], source="inferred_default", confidence=0.4)
            thickness = _get_dim(dims, "thickness", "width")
            if thickness is None:
                thickness = max(4.0, round(radius * 0.4, 2))
                _set_dim(dims, sources, "thickness", thickness, ["outer_radius"], source="derived", confidence=0.6)

            bore = _get_dim(dims, "bore_diameter", "inner_diameter")
            if bore is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    bore = shaft_d + 0.2
                    _set_dim(dims, sources, "bore_diameter", bore, ["shaft.diameter"], source="derived", confidence=0.7)
            if isinstance(bore, (int, float)):
                if _get_dim(dims, "inner_diameter") is None:
                    _set_dim(dims, sources, "inner_diameter", float(bore), ["bore_diameter"], source="derived", confidence=0.8)
                if _get_dim(dims, "inner_radius") is None:
                    _set_dim(dims, sources, "inner_radius", round(float(bore) / 2.0, 2), ["bore_diameter"], source="derived", confidence=0.8)

        if comp_type in {"shaft", "axle"}:
            diameter = _get_dim(dims, "diameter")
            if diameter is None:
                diameter = 6.0
                _set_dim(dims, sources, "diameter", diameter, ["default"], source="inferred_default", confidence=0.4)
            length = _get_dim(dims, "length")
            if length is None:
                length = max(20.0, round(diameter * 10.0, 2))
                _set_dim(dims, sources, "length", length, ["diameter"], source="derived", confidence=0.6)

        if comp_type == "bearing":
            bore = _get_dim(dims, "bore_diameter", "inner_diameter")
            if bore is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    bore = shaft_d + 0.2
                    _set_dim(dims, sources, "bore_diameter", bore, ["shaft.diameter"], source="derived", confidence=0.7)
            outer = _get_dim(dims, "outer_diameter")
            if outer is None and bore is not None:
                outer = round(bore * 2.75, 2)
                _set_dim(dims, sources, "outer_diameter", outer, ["bore_diameter"], source="derived", confidence=0.6)
            width = _get_dim(dims, "width", "thickness")
            if width is None and bore is not None:
                width = round(bore * 0.9, 2)
                _set_dim(dims, sources, "width", width, ["bore_diameter"], source="derived", confidence=0.6)

        if comp_type == "fastener":
            nominal = _get_dim(dims, "nominal_diameter", "diameter")
            if nominal is None:
                nominal = 4.0
                _set_dim(dims, sources, "nominal_diameter", nominal, ["default"], source="inferred_default", confidence=0.4)
            length = _get_dim(dims, "length")
            if length is None:
                length = max(8.0, round(nominal * 3.0, 2))
                _set_dim(dims, sources, "length", length, ["nominal_diameter"], source="derived", confidence=0.6)
            count = dims.get("count")
            if not isinstance(count, (int, float)):
                _set_dim(dims, sources, "count", 4, ["default"], source="inferred_default", confidence=0.5)

        if comp_type in {"arm", "wheel_arm"}:
            length = _get_dim(dims, "length")
            if length is None:
                wheel_r = _find_related_dim(comp_id, {"wheel"}, ["outer_radius", "radius"])
                if wheel_r is not None:
                    length = round(wheel_r * 2.5, 2)
                    _set_dim(dims, sources, "length", length, ["wheel.outer_radius"], source="derived", confidence=0.6)
                else:
                    length = 100.0
                    _set_dim(dims, sources, "length", length, ["default"], source="inferred_default", confidence=0.4)
            width = _get_dim(dims, "width")
            if width is None:
                width = round(length * 0.2, 2)
                _set_dim(dims, sources, "width", width, ["length"], source="derived", confidence=0.6)
            thickness = _get_dim(dims, "thickness")
            if thickness is None:
                thickness = round(width * 0.3, 2)
                _set_dim(dims, sources, "thickness", thickness, ["width"], source="derived", confidence=0.6)

        if comp_type == "spacer":
            inner = _get_dim(dims, "inner_diameter")
            if inner is None:
                shaft_d = _find_related_dim(comp_id, {"shaft", "axle"}, ["diameter"])
                if shaft_d is not None:
                    inner = shaft_d + 0.3
                    _set_dim(dims, sources, "inner_diameter", inner, ["shaft.diameter"], source="derived", confidence=0.7)
            outer = _get_dim(dims, "outer_diameter")
            if outer is None and inner is not None:
                _set_dim(dims, sources, "outer_diameter", round(inner * 1.6, 2), ["inner_diameter"], source="derived", confidence=0.6)
            thickness = _get_dim(dims, "thickness")
            if thickness is None:
                _set_dim(dims, sources, "thickness", 2.0, ["default"], source="inferred_default", confidence=0.4)

        if not dims:
            if comp_type in {"fastener_set", "bolt_set"}:
                _set_dim(dims, sources, "nominal_diameter", 4.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "length", 12.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "count", 4.0, ["default"], source="inferred_default", confidence=0.5)
            elif comp_type == "nut_set":
                _set_dim(dims, sources, "nominal_diameter", 4.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 3.2, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "count", 4.0, ["default"], source="inferred_default", confidence=0.5)
            elif comp_type == "retainer":
                _set_dim(dims, sources, "bore_diameter", 8.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 1.5, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "bearing_seat":
                _set_dim(dims, sources, "bore_diameter", 22.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 7.0, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "mounting_flange":
                _set_dim(dims, sources, "diameter", 40.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "thickness", 5.0, ["default"], source="inferred_default", confidence=0.4)
            elif comp_type == "key":
                _set_dim(dims, sources, "width", 2.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "height", 2.0, ["default"], source="inferred_default", confidence=0.4)
                _set_dim(dims, sources, "length", 6.0, ["default"], source="inferred_default", confidence=0.4)

def _infer_standard_parts(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    def _dimension_source(comp: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
        srcs = comp.get("dimension_sources")
        if not isinstance(srcs, Mapping):
            return None
        source = srcs.get(key)
        if isinstance(source, Mapping):
            return source
        return None

    def _is_bore_only_inference(comp: Mapping[str, Any], *, has_outer: bool, has_width: bool) -> bool:
        if not has_outer or not has_width:
            return True
        outer_src = _dimension_source(comp, "outer_diameter")
        width_src = _dimension_source(comp, "thickness") or _dimension_source(comp, "width")

        def _derived_from_bore(src: Mapping[str, Any] | None) -> bool:
            if not isinstance(src, Mapping):
                return False
            if src.get("source") != "derived":
                return False
            from_list = src.get("derived_from")
            if isinstance(from_list, list):
                return any(isinstance(v, str) and "bore_diameter" in v for v in from_list)
            return False

        return _derived_from_bore(outer_src) and _derived_from_bore(width_src)

    def _part_class_for_category(category: str) -> str:
        cat = category.strip().lower()
        if cat in {"fastener", "bolt", "screw", "washer", "nut", "rivet"}:
            return "fasteners"
        if cat == "bearing":
            return "bearings"
        return "others"

    standard_parts = payload.get("standard_parts")
    if not isinstance(standard_parts, list):
        standard_parts = []
        payload["standard_parts"] = standard_parts

    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    unresolved_parts: list[Dict[str, Any]] = []
    unresolved_bearing_component_ids: set[str] = set()

    def _connection_ids_for_component(comp_id: str) -> list[str]:
        ids: list[str] = []
        for cr in payload.get("connection_requirements", []) or []:
            if not isinstance(cr, Mapping):
                continue
            between = cr.get("between", [])
            if isinstance(between, list) and comp_id in between:
                cr_id = cr.get("id")
                if isinstance(cr_id, str):
                    ids.append(cr_id)
        return ids

    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        comp_type = comp.get("type")
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else None
        std_id = f"std_{comp_id}" if comp_id else None
        if std_id and any(isinstance(p, Mapping) and p.get("id") == std_id for p in standard_parts):
            continue

        if comp_type == "fastener":
            nominal = dims.get("nominal_diameter")
            length = dims.get("length")
            if not isinstance(nominal, (int, float)) or not isinstance(length, (int, float)):
                unresolved_parts.append({
                    "id": f"std_{comp_id}" if comp_id else f"std_fastener_unresolved_{len(unresolved_parts) + 1}",
                    "category": "fastener",
                    "part_class": "fasteners",
                    "component_id": comp_id,
                    "reason": "missing_nominal_diameter_or_length",
                    "available": {
                        "nominal_diameter": nominal,
                        "length": length,
                    },
                    "selection_rationale": "Fastener standard selection requires nominal_diameter and length.",
                })
                continue

            designation = _nearest_fastener_designation(float(nominal), float(length))
            quantity = dims.get("count") if isinstance(dims.get("count"), (int, float)) else 1
            applied_to = _connection_ids_for_component(comp_id) if comp_id else []
            standard_parts.append({
                "id": f"std_{comp_id}" if comp_id else f"std_fastener_{len(standard_parts) + 1}",
                "category": "fastener",
                "part_class": "fasteners",
                "designation": designation,
                "quantity": int(quantity),
                "applied_to": applied_to,
                "selection_rationale": "Nearest standard size based on nominal_diameter and length"
            })

        if comp_type == "bearing":
            params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
            bore = dims.get("bore_diameter") if isinstance(dims.get("bore_diameter"), (int, float)) else None
            outer = dims.get("outer_diameter") if isinstance(dims.get("outer_diameter"), (int, float)) else None
            width = dims.get("width") if isinstance(dims.get("width"), (int, float)) else None

            designation_raw = None
            for candidate in (
                comp.get("designation"),
                params.get("designation") if isinstance(params, Mapping) else None,
                params.get("bearing_designation") if isinstance(params, Mapping) else None,
            ):
                if isinstance(candidate, str) and candidate.strip():
                    designation_raw = candidate.strip()
                    break

            series_hint = None
            for candidate in (
                comp.get("iso_series"),
                params.get("iso_series") if isinstance(params, Mapping) else None,
            ):
                if isinstance(candidate, str) and candidate.strip():
                    series_hint = candidate.strip()
                    break

            resolved_item: Dict[str, Any] | None = None
            rationale = ""

            if designation_raw:
                resolved_item = find_bearing_by_designation(designation_raw)
                if resolved_item:
                    rationale = "Catalog lookup by designation"

            has_complete_dims = all(isinstance(v, (int, float)) for v in [bore, outer, width])
            bore_only = isinstance(bore, (int, float)) and not isinstance(outer, (int, float)) and not isinstance(width, (int, float))

            if resolved_item is None and has_complete_dims and not designation_raw and not series_hint:
                if not _is_bore_only_inference(comp, has_outer=True, has_width=True):
                    resolved_item = nearest_bearing_by_dims(float(bore), float(outer), float(width))
                    rationale = "Nearest catalog bearing by d/D/B"

            if resolved_item is None and series_hint and isinstance(bore, (int, float)):
                resolved_item = select_bearing_by_series_and_bore(series_hint, float(bore))
                if resolved_item:
                    rationale = f"Catalog lookup by iso_series={series_hint} and bore"

            if resolved_item:
                designation = str(resolved_item["code"])
                dims["bore_diameter"] = float(resolved_item["bore"])
                dims["outer_diameter"] = float(resolved_item["outer"])
                dims["width"] = float(resolved_item["width"])
                dim_sources = comp.get("dimension_sources") if isinstance(comp.get("dimension_sources"), Mapping) else {}
                dim_sources = dict(dim_sources)
                dim_sources["bore_diameter"] = {"source": "standard_catalog", "confidence": 0.95}
                dim_sources["outer_diameter"] = {"source": "standard_catalog", "confidence": 0.95}
                dim_sources["width"] = {"source": "standard_catalog", "confidence": 0.95}
                comp["dimension_sources"] = dim_sources
            else:
                candidate_series = candidate_series_for_bore(float(bore)) if isinstance(bore, (int, float)) else []
                unresolved_parts.append({
                    "id": f"std_{comp_id}" if comp_id else f"std_bearing_unresolved_{len(unresolved_parts) + 1}",
                    "category": "bearing",
                    "part_class": "bearings",
                    "component_id": comp_id,
                    "reason": "missing_closed_loop_bearing_parameters",
                    "available": {
                        "designation": designation_raw,
                        "iso_series": series_hint,
                        "bore_diameter": bore,
                        "outer_diameter": outer,
                        "width": width,
                    },
                    "candidate_series": candidate_series,
                    "selection_rationale": (
                        "Only bore is not enough to uniquely determine OD/width; "
                        "requires designation or iso_series+bore or complete d/D/B"
                    ),
                })
                if isinstance(comp_id, str):
                    unresolved_bearing_component_ids.add(comp_id)
                continue

            applied_to = _connection_ids_for_component(comp_id) if comp_id else []
            standard_parts.append({
                "id": f"std_{comp_id}" if comp_id else f"std_bearing_{len(standard_parts) + 1}",
                "category": "bearing",
                "part_class": "bearings",
                "designation": designation,
                "quantity": 1,
                "dimensions": {
                    "d_mm": dims.get("bore_diameter"),
                    "D_mm": dims.get("outer_diameter"),
                    "B_mm": dims.get("width"),
                },
                "applied_to": applied_to,
                "selection_rationale": rationale or "Catalog-resolved bearing"
            })

    for part in standard_parts:
        if not isinstance(part, Mapping):
            continue
        category = part.get("category") if isinstance(part.get("category"), str) else "other"
        if "part_class" not in part:
            part["part_class"] = _part_class_for_category(category)

    metadata["standard_parts_unresolved"] = unresolved_parts
    metadata["unresolved_bearing_component_ids"] = sorted(unresolved_bearing_component_ids)
    metadata["bearing_resolution_summary"] = {
        "resolved": len(
            [
                p for p in standard_parts
                if isinstance(p, Mapping)
                and p.get("category") == "bearing"
            ]
        ),
        "unresolved": len(unresolved_parts),
    }

def _validate_no_relations(payload: Dict[str, Any]) -> None:
    if "relations" in payload:
        raise ValueError("Agent1 must not output relations; remove relations[] from KG")

def _sync_dimensions_and_parameters(payload: Dict[str, Any]) -> None:
    components = payload.get("components", [])
    if not isinstance(components, list):
        return

    _, children_by_parent = _collect_component_hierarchy_candidates(payload)
    hierarchy_parent_ids = set(children_by_parent.keys())
    for comp in components:
        if not isinstance(comp, Mapping):
            continue

        comp_type = comp.get("type")
        dims = comp.get("dimensions")
        params = comp.get("parameters")

        if dims is None and isinstance(params, Mapping):
            comp["dimensions"] = dict(params)
            dims = comp["dimensions"]
        if params is None and isinstance(dims, Mapping):
            comp["parameters"] = dict(dims)
            params = comp["parameters"]

        if not isinstance(dims, Mapping):
            raise ValueError(
                f"Component '{comp.get('id')}' must include 'dimensions' as an object."
            )
        if not isinstance(params, Mapping):
            raise ValueError(
                f"Component '{comp.get('id')}' must include 'parameters' as an object."
            )

        comp_id = comp.get("id") if isinstance(comp.get("id"), str) else ""
        kind = comp.get("kind")
        policy = comp.get("modeling_policy")
        is_container_only = bool(comp.get("is_container_only"))
        if comp_id and comp_id in hierarchy_parent_ids and isinstance(comp, dict):
            if _preserve_hierarchy_parent_as_physical(comp):
                _mark_component_as_physical_part(comp)
                kind = "part"
                policy = str(comp.get("modeling_policy") or "must_model")
                is_container_only = False
            else:
                _mark_component_as_container_only(
                    comp,
                    note="inferred_hierarchy_container_from_child_components",
                )
                kind = "assembly_node"
                policy = "container_only"
                is_container_only = True
        if isinstance(kind, str) and kind.strip() == "assembly_node":
            is_container_only = True
        if isinstance(policy, str) and policy.strip().lower() in {"container_only", "reference_only"}:
            is_container_only = True

        if is_container_only:
            comp["dimensions"] = {}
            comp["parameters"] = {}
            comp["dimension_sources"] = {}
            continue

        if comp_type != "subassembly" and len(dims) == 0:
            if comp_type in {"fastener", "fastener_set", "bolt_set"}:
                dims = {"nominal_diameter": 4.0, "length": 12.0, "count": 4.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "nut_set":
                dims = {"nominal_diameter": 4.0, "thickness": 3.2, "count": 4.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type in {"retainer", "bearing_seat"}:
                dims = {"bore_diameter": 8.0, "thickness": 2.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "key":
                dims = {"width": 2.0, "height": 2.0, "length": 6.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)
            elif comp_type == "mounting_flange":
                dims = {"diameter": 40.0, "thickness": 5.0}
                comp["dimensions"] = dims
                comp["parameters"] = dict(dims)

        if comp_type != "subassembly" and len(dims) == 0:
            raise ValueError(
                f"Component '{comp.get('id')}' is missing dimensions. Agent1 must provide full sizes."
            )

        if dims != params:
            comp["parameters"] = dict(dims)
            params = comp["parameters"]

        dim_sources = comp.get("dimension_sources")
        if not isinstance(dim_sources, Mapping):
            comp["dimension_sources"] = {k: {"source": "input", "confidence": 0.9} for k in dims.keys()}
        else:
            source_alias = {
                "explicit": "input",
                "manual": "input",
                "catalog": "standard_catalog",
                "default": "inferred_default",
            }
            normalized_sources: Dict[str, Any] = {}
            for key, value in dim_sources.items():
                if isinstance(value, str):
                    normalized = source_alias.get(value, value)
                    normalized_sources[key] = {"source": normalized, "confidence": 0.9 if normalized == "input" else 0.7}
                elif isinstance(value, Mapping):
                    if "source" in value:
                        normalized_value = dict(value)
                        raw_source = normalized_value.get("source")
                        if isinstance(raw_source, str):
                            normalized_value["source"] = source_alias.get(raw_source, raw_source)
                        normalized_sources[key] = normalized_value
                    else:
                        normalized_sources[key] = {"source": "input", "confidence": 0.9}
                else:
                    normalized_sources[key] = {"source": "input", "confidence": 0.9}
            for dim_key in dims.keys():
                if dim_key not in normalized_sources:
                    normalized_sources[dim_key] = {"source": "input", "confidence": 0.9}
            comp["dimension_sources"] = normalized_sources

        shape_semantics = comp.get("shape_semantics")
        if not isinstance(shape_semantics, Mapping) or not shape_semantics.get("type"):
            raise ValueError(
                f"Component '{comp.get('id')}' must include shape_semantics.type."
            )


__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
