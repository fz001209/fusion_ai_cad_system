"""Agent3a shape realization planner and deterministic modeling strategy rules."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Mapping

from planning.pattern_solver import solve_circular_pattern
from agents.common_utils import read_json as _read_json, write_json as _write_json

from .common import *
from .feature_plans import *
from .layout import *


# LLM utilities removed: Agent3a is deterministic by design.

# LLM utilities removed: Agent3a is deterministic by design.


# Canonical Fusion 360 modeling patterns (deterministic vocabulary)
FUSION_MODELING_PATTERNS = {
    "ROTATIONAL_REVOLVE",      # Symmetric cylindrical parts (wheels, pulleys)
    "AXIAL_EXTRUSION",         # Linear cylindrical parts (shafts, pins)
    "PLANAR_PLATE_EXTRUSION",  # Flat plates with uniform thickness
    "PROFILE_EXTRUSION",       # Custom profile parts (arms, brackets)
    "RADIAL_PLATE_EXTRUSION"   # Radial plates with spoke patterns
}

# EXPLICIT CONTRACT: Modeling Pattern 闂?Fusion 360 Official Paradigm
# This is the AUTHORITATIVE mapping from abstract patterns to concrete Fusion strategies.
# Pattern selection (WHAT), this contract defines Fusion execution (HOW).
FUSION_PARADIGM_CONTRACT = {
    "ROTATIONAL_REVOLVE": {
        "primitive_class": "cylindrical",
        "construction_method": "revolve",
        "profile_variants": ["half_profile", "annular"],
        "fusion_best_practice": "Use revolve for rotationally symmetric parts to ensure balanced mass distribution",
        "applicable_to": ["wheel", "pulley", "bearing", "hub", "disk"]
    },
    "AXIAL_EXTRUSION": {
        "primitive_class": "cylindrical",
        "construction_method": "extrude",
        "profile_variants": ["circle", "annular"],
        "fusion_best_practice": "Use extrude for linear cylindrical parts to control axial direction",
        "applicable_to": ["shaft", "axle", "pin", "rod", "fastener"]
    },
    "PLANAR_PLATE_EXTRUSION": {
        "primitive_class": "prismatic",
        "construction_method": "extrude",
        "profile_variants": ["rectangle"],
        "fusion_best_practice": "Use extrude with rectangular profile for uniform thickness plates",
        "applicable_to": ["plate", "panel", "sheet"]
    },
    "PROFILE_EXTRUSION": {
        "primitive_class": "prismatic",
        "construction_method": "extrude",
        "profile_variants": ["rectangle", "fork_profile", "yoke_profile"],
        "fusion_best_practice": "Use extrude with a deterministic prismatic profile that preserves required support topology without inventing a different mechanism.",
        "applicable_to": ["arm", "bracket", "beam", "strut", "fork"]
    },
    "RADIAL_PLATE_EXTRUSION": {
        "primitive_class": "plate",
        "construction_method": "extrude",
        "profile_variants": ["macro_profile"],
        "fusion_best_practice": "Use extrude with semantic profile for radial plates with spoke patterns",
        "applicable_to": ["carrier_plate", "star_plate", "spoke_wheel"]
    }
}

ALLOWED_PROFILE_TYPES = {
    "circle",
    "annular",
    "half_profile",
    "tire_profile",
    "rectangle",
    "fork_profile",
    "yoke_profile",
    "macro_profile",
}

# Deterministic parameter rule library (component intent 闂?parameter rules)
PARAM_RULES: Dict[str, Dict[str, Any]] = {
    "hub": {
        "outer_radius": {"default": 14.0, "min": 6.0, "max": 60.0},
        "thickness": {"default": 8.0, "min": 3.0, "max": 20.0},
    },
    "arm": {
        "length": {"default": 60.0, "min": 20.0, "max": 200.0},
        "width": {"default": 14.0, "min": 6.0, "max": 60.0},
        "thickness": {"default": 6.0, "min": 3.0, "max": 20.0},
        "proportions": {
            "length_to_width": {"min": 2.0, "max": 8.0}
        },
    },
    "wheel": {
        "outer_radius": {"default": 30.0, "min": 10.0, "max": 200.0},
        "width": {"default": 12.0, "min": 4.0, "max": 50.0},
        "proportions": {
            "width_to_radius": {"min": 0.1, "max": 0.6}
        },
        "clearance": {
            "hub": {"min_radial_gap": 1.0}
        }
    },
    "carrier_plate": {
        "thickness": {"default": 6.0, "min": 3.0, "max": 15.0},
        "fillet_radius": {"default": 2.0, "min": 0.5, "max_ratio": 0.3},
        "clearance": {
            "arm": {"min_radial_gap": 1.0}
        }
    },
    "rigid_plate": {
        "thickness": {"default": 6.0, "min": 3.0, "max": 15.0},
    },
    "shaft": {
        "diameter": {"default": 4.0, "min": 2.0, "max": 20.0},
        "length": {"default": 60.0, "min": 10.0, "max": 300.0},
    },
    "bearing": {
        "bore_diameter": {"default": 4.0, "min": 2.0, "max": 200.0},
        "outer_diameter": {"default": 10.0, "min": 4.0, "max": 300.0},
        "width": {"default": 6.0, "min": 2.0, "max": 100.0},
        "thickness": {"default": 6.0, "min": 2.0, "max": 100.0},
        "proportions": {
            "outer_to_bore": {"min": 1.05, "max": 3.5}
        },
        "clearance": {
            "shaft": {"min_bore_diameter_over_shaft": 0.2}
        }
    },
    "fastener": {
        "nominal_diameter": {"default": 3.0, "min": 2.0, "max": 12.0},
        "length": {"default": 8.0, "min": 4.0, "max": 50.0},
        "count": {"default": 3, "min": 1.0, "max": 20.0}
    }
}

EXECUTION_MODES = {
    "deterministic": {
        "description": "Rule-based semantic-to-parametric realization",
        "decision_authority": "Deterministic rules only (no LLM)",
        "use_case": "Always-on deterministic planning",
        "guarantees": "Fully reproducible, no AI variability"
    }
}


def _is_modeling_pattern_allowed(
    comp_type: str,
    pattern: str,
    shape_type: str | None = None,
) -> bool:
    """
    Engineering legality check: is this modeling_pattern allowed for this component type?
    
    This enforces Fusion 360 best practices and physical constraints.
    
    Rules:
    - Rotational parts (wheel, pulley, bearing, hub) 闂?ALLOW ROTATIONAL_REVOLVE
    - Linear cylindrical parts (shaft, axle, fastener) 闂?ALLOW AXIAL_EXTRUSION, DISALLOW ROTATIONAL_REVOLVE
    - Plate parts 闂?ALLOW PLANAR_PLATE_EXTRUSION, RADIAL_PLATE_EXTRUSION
    - Prismatic parts (arm, bracket) 闂?ALLOW PROFILE_EXTRUSION
    
    Args:
        comp_type: Component type from KG
        pattern: Proposed modeling pattern from LLM
        shape_type: Optional normalized shape type hint (cylindrical/prismatic/radial_plate)
    
    Returns:
        True if pattern is allowed for comp_type, False otherwise
    """
    comp_type_lower = comp_type.lower() if comp_type else ""

    allowlist = {
        "wheel": {"ROTATIONAL_REVOLVE"},
        "pulley": {"ROTATIONAL_REVOLVE"},
        "bearing": {"ROTATIONAL_REVOLVE"},
        "hub": {"ROTATIONAL_REVOLVE"},
        "rim": {"ROTATIONAL_REVOLVE"},
        "tire": {"ROTATIONAL_REVOLVE"},
        "shaft": {"AXIAL_EXTRUSION"},
        "axle": {"AXIAL_EXTRUSION"},
        "fastener": {"AXIAL_EXTRUSION"},
        "bolt": {"AXIAL_EXTRUSION"},
        "screw": {"AXIAL_EXTRUSION"},
        "pin": {"AXIAL_EXTRUSION"},
        "arm": {"PROFILE_EXTRUSION"},
        "bracket": {"PROFILE_EXTRUSION"},
        "plate": {"PLANAR_PLATE_EXTRUSION", "RADIAL_PLATE_EXTRUSION"},
        "panel": {"PLANAR_PLATE_EXTRUSION"},
        "sheet": {"PLANAR_PLATE_EXTRUSION"},
        "carrier_plate": {"RADIAL_PLATE_EXTRUSION"},
        "rigid_plate": {"PLANAR_PLATE_EXTRUSION"}
    }
    tokens = set()
    if comp_type_lower:
        tokens.add(comp_type_lower)
        tokens |= {t for t in re.split(r"[^a-zA-Z0-9]+", comp_type_lower) if t}

    for key, allowed in allowlist.items():
        if key in tokens:
            return pattern in allowed

    # Unknown component types: allow patterns consistent with shape_type
    if shape_type == "cylindrical":
        return pattern in {"ROTATIONAL_REVOLVE", "AXIAL_EXTRUSION"}
    if shape_type == "prismatic":
        return pattern in {"PROFILE_EXTRUSION", "PLANAR_PLATE_EXTRUSION"}
    if shape_type == "radial_plate":
        return pattern in {"RADIAL_PLATE_EXTRUSION"}
    return pattern == "PROFILE_EXTRUSION"


def _map_pattern_to_strategy(
    pattern: str,
    shape_semantics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Map accepted modeling_pattern to deterministic strategy fields.
    
    This is a FIXED lookup table aligned with Fusion API best practices.
    LLM selects the pattern, this function translates it to execution parameters.
    
    Args:
        pattern: Validated modeling pattern from LLM
        shape_semantics: Shape semantics from Agent2
    
    Returns:
        Strategy dict with primitive_class, construction_method
    """
    # Fixed mapping: modeling_pattern 闂?strategy fields (no CAD-execution details)
    if pattern == "ROTATIONAL_REVOLVE":
        return {
            "primitive_class": "cylindrical",
            "construction_method": "revolve",
            "selection_rationale": "pattern_rotational_revolve"
        }

    elif pattern == "AXIAL_EXTRUSION":
        return {
            "primitive_class": "cylindrical",
            "construction_method": "extrude",
            "selection_rationale": "pattern_axial_extrusion"
        }

    elif pattern == "PLANAR_PLATE_EXTRUSION":
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "pattern_planar_plate"
        }

    elif pattern == "PROFILE_EXTRUSION":
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "pattern_profile_extrusion"
        }

    elif pattern == "RADIAL_PLATE_EXTRUSION":
        return {
            "primitive_class": "plate",
            "construction_method": "extrude",
            "selection_rationale": "pattern_radial_plate"
        }

    else:
        # Fallback (should never happen if validation works)
        return {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "selection_rationale": "unknown_pattern_fallback"
        }


class ShapeRealizationPlanner:
    """
    Agent3a 闂?Deterministic Shape Realization Planner (Semantic 闂?Parametric)
    """
    
    def __init__(self, kg: Dict[str, Any], *, function_registry: Dict[str, Any] | None = None):
        self.kg = kg
        self.function_registry = function_registry or {}
        self.components = {c["id"]: c for c in kg.get("components", [])}
        self.components_by_type: Dict[str, List[Dict[str, Any]]] = {}
        self.resolved_param_values: Dict[str, Dict[str, float]] = {}
        self.resolved_param_records: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.fallback_reasons: List[Dict[str, Any]] = []
        for comp in kg.get("components", []):
            ctype = comp.get("type")
            if isinstance(ctype, str):
                self.components_by_type.setdefault(ctype, []).append(comp)

    def _normalize_shape_type(self, shape: Dict[str, Any], comp_type: str) -> str:
        raw = shape.get("type", "prismatic") if isinstance(shape, dict) else "prismatic"
        raw_lower = raw.lower() if isinstance(raw, str) else "prismatic"
        comp_lower = comp_type.lower() if isinstance(comp_type, str) else ""
        if raw_lower in {"cylindrical", "cylinder", "annular", "annulus", "ring"}:
            return "cylindrical"
        if raw_lower in {"radial_plate", "radial", "spoke_plate"}:
            return "radial_plate"
        if raw_lower in {"plate", "planar_plate", "planar"}:
            if comp_lower in {"carrier_plate", "star_plate", "spoke_wheel"}:
                return "radial_plate"
            return "prismatic"
        if raw_lower in {"prismatic", "rectangular"}:
            return "prismatic"
        return "prismatic"

    def _profile_type_from_shape(self, shape: Dict[str, Any], shape_type: str) -> str | None:
        """
        Return a semantic hint only. Final profile_type is normalized later.
        """
        if not isinstance(shape, dict):
            return None

        candidate = shape.get("cross_section") or shape.get("profile_type")
        token = candidate.lower().strip() if isinstance(candidate, str) else None
        if shape_type == "radial_plate":
            return "radial_hint"
        if token in {"circle", "circular", "round"}:
            return "circle_hint"
        if token in {"annular", "annulus", "ring"}:
            return "annular_hint"
        if token in {"rectangle", "rectangular"}:
            return "rectangle_hint"
        if token in {"radial", "semantic_profile", "polygon", "rounded_polygon"}:
            return "radial_hint"
        return None

    def _is_modeling_component(self, component_id: str, part: Dict[str, Any]) -> bool:
        if not isinstance(component_id, str) or not component_id:
            return False

        kind = part.get("kind")
        if not isinstance(kind, str):
            component_obj = self.components.get(component_id, {})
            kind = component_obj.get("kind") if isinstance(component_obj, dict) else None
        if isinstance(kind, str) and kind.strip() == "assembly_node":
            return False

        policy = part.get("modeling_policy")
        if not isinstance(policy, str):
            component_obj = self.components.get(component_id, {})
            policy = component_obj.get("modeling_policy") if isinstance(component_obj, dict) else None
        if isinstance(policy, str) and policy.strip().lower() in {"container_only", "reference_only"}:
            return False

        must_model = part.get("must_model")
        if not isinstance(must_model, bool):
            component_obj = self.components.get(component_id, {})
            if isinstance(component_obj, dict):
                must_model = component_obj.get("must_model")
        if must_model is False:
            return False

        shape = part.get("shape_semantics")
        if isinstance(shape, dict):
            shape_type = shape.get("type")
            if isinstance(shape_type, str) and shape_type.strip().lower() == "assembly_node":
                return False

        return True

    def _select_cylindrical_construction_method(
        self,
        component_id: str,
        shape: Dict[str, Any],
    ) -> str:
        """
        Decide construction method for cylindrical components
        based on applicability domain and feasibility constraints.

        Returns:
            "extrude" or "revolve"
        """
        axial_profile = shape.get("axial_profile") if isinstance(shape, dict) else None
        rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
        axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
        profile_type_hint = shape.get("profile_type") or shape.get("cross_section") if isinstance(shape, dict) else None

        rotational_solid = rotational_profile is True or axial_shape_variation is True
        non_constant_axial = axial_profile not in (None, "constant")
        half_profile_ok = profile_type_hint in {"half_profile", "half-profile", "halfprofile"}

        inner_radius = None
        if isinstance(shape, dict):
            inner_radius = shape.get("inner_radius")
            if inner_radius is None:
                inner_radius = shape.get("bore_radius")
        inner_radius_val = self._numeric_value(inner_radius)
        touches_axis = inner_radius_val is not None and inner_radius_val <= 0

        if rotational_solid and non_constant_axial and half_profile_ok and not touches_axis:
            return "revolve"
        return "extrude"
    
    def plan(self, semantics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main planning entry point.
        
        DECISION AUTHORITY MODEL:
        - LLM proposes modeling_pattern (WHAT paradigm to use)
        - Deterministic rules validate and enforce (CAN be used)
        - Execution parameters are mapped deterministically (HOW to execute)
        
        Returns shape_realization plan with modeling_strategy for each component.
        """
        parts = semantics.get("parts", [])
        self.fallback_reasons = []
        self._resolve_parameters(parts)
        realizations = []
        for part in parts:
            component_id = part.get("component_id")
            if not component_id:
                continue
            if not self._is_modeling_component(component_id, part if isinstance(part, dict) else {}):
                continue
            realization = self._plan_component(part)
            realizations.append(realization)
        execution_mode = "deterministic"

        self._validate_feasibility(parts, realizations)
        # Bearing seat upgrades can widen the realized wheel hub envelope.
        # Size yoke supports only after those host dimensions are finalized.
        self._upgrade_opposed_bearing_seat_realizations(realizations, semantics)
        self._suppress_bearing_backed_wheel_hub_bores(realizations, semantics)
        self._upgrade_rotating_wheel_support_realizations(realizations, semantics)
        self._upgrade_hub_slot_mount_realizations(realizations, semantics)
        self._rewrite_hub_slot_mount_fastener_features(realizations)
        self._enforce_numeric_output(realizations)
        self._final_validate(realizations)
        
        metadata = {
            "plan_id": semantics["metadata"]["plan_id"].replace("_semantics_", "_realization_"),
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "shape_realization_planner",
            "source_semantics_id": semantics["metadata"]["plan_id"],
            "execution_mode": execution_mode,
            "execution_mode_definition": EXECUTION_MODES.get(execution_mode, {}),
            "fusion_paradigm_contract_version": "1.0",
            "fusion_paradigm_contract": {
                k: {
                    "primitive_class": v.get("primitive_class"),
                    "construction_method": v.get("construction_method"),
                }
                for k, v in FUSION_PARADIGM_CONTRACT.items()
            },
        }

        if self.fallback_reasons:
            metadata["fallbacks"] = {
                "count": len(self.fallback_reasons),
                "records": self.fallback_reasons
            }
        
        return {
            "metadata": metadata,
            "component_realizations": realizations
        }

    def _plan_component(
        self,
        part: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select deterministic modeling strategy for one component and resolve
        semantic parameters into numeric dimensions.

        Contract strategy is authoritative and replaces the shape-based strategy entirely.
        """
        component_id = part["component_id"]
        shape = part.get("shape_semantics", {})
        shape_type = self._normalize_shape_type(shape, self.components.get(component_id, {}).get("type", ""))
        comp_type = self.components.get(component_id, {}).get("type", "")

        contract_pattern, contract_source = self._determine_contract_pattern(part, shape_type, comp_type)
        if contract_pattern and not _is_modeling_pattern_allowed(comp_type, contract_pattern, shape_type):
            self._log_fallback(
                component_id=component_id,
                param_name="modeling_pattern",
                reason="pattern_not_allowed_fallback",
                old_value=contract_pattern,
                new_value=None,
                stage="pattern",
            )
            contract_pattern = None
            contract_source = "fallback"
        if shape_type == "cylindrical":
            strategy = self._select_cylindrical_strategy(component_id, shape)
        elif shape_type == "prismatic":
            strategy = self._select_prismatic_strategy(component_id, shape)
        elif shape_type == "radial_plate":
            strategy = self._select_radial_plate_strategy(component_id, shape)
        else:
            raise ValueError(f"Unsupported shape type '{shape_type}' for component '{component_id}'.")

        if contract_pattern:
            contract_strategy = _map_pattern_to_strategy(contract_pattern, shape)
            if not self._is_contract_compatible(contract_strategy, shape_type):
                self._log_fallback(
                    component_id=component_id,
                    param_name="modeling_pattern",
                    reason="contract_shape_mismatch",
                    old_value=contract_pattern,
                    new_value=None,
                    stage="pattern",
                )
                contract_pattern = None
                contract_source = "fallback"
            else:
                contract_rationale = contract_strategy.get("selection_rationale")
                strategy = {**strategy, **contract_strategy}
                rationale_parts = []
                if contract_rationale:
                    rationale_parts.append(contract_rationale)
                rationale_parts.append("contract_pattern_alignment")
                strategy["selection_rationale"] = ";".join(rationale_parts)

        kg_component = self.components.get(component_id, {})
        component_type = str(kg_component.get("type") or "").strip().lower()
        linear_cylindrical_types = {"shaft", "axle", "pin", "fastener", "bolt", "screw", "nut", "washer", "spacer", "standoff", "bushing"}

        # Execution policy: only truly linear cylindrical members are forced back to extrude.
        if (
            shape_type == "cylindrical"
            and isinstance(strategy, dict)
            and component_type in linear_cylindrical_types
            and (shape.get("cross_section") if isinstance(shape, dict) else None) != "annular"
        ):
            current = strategy.get("construction_method")
            cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
            if current != "extrude":
                self._log_fallback(
                    component_id=component_id,
                    param_name="construction_method",
                    reason="extrude_only_execution_policy",
                    old_value=current,
                    new_value="extrude",
                    stage="strategy_selection",
                )
                strategy["construction_method"] = "extrude"
                strategy["profile_type"] = "annular" if cross_section == "annular" else "circle"
                strategy["selection_rationale"] = "extrude_only_execution_policy"
        
        # Add collection info if present in KG
        count = None
        if "parameters" in kg_component:
            count = kg_component["parameters"].get("count")
        
        if count is not None:
            strategy["collection_info"] = {
                "is_collection": True,
                "individual_count": count
            }

        self._normalize_profile_type(strategy)

        comp_type_norm = str(comp_type).strip().lower() if isinstance(comp_type, str) else ""
        if comp_type_norm in {"bearing", "fastener", "fastener_set"}:
            strategy["import_strategy"] = "standard_part_library"
            strategy["import_source"] = "parts_index"

        # NOTE: parameter_resolution is explanatory, not authoritative.
        # Execution uses modeling_strategy.parameter_values (non-macro) or parameter_semantics (macro).
        profile_type = strategy.get("profile_type")
        if profile_type == "macro_profile":
            strategy.pop("parameter_values", None)
        else:
            strategy["parameter_values"] = dict(
                self.resolved_param_values.get(component_id, {})
            )

        construction_method = strategy.get("construction_method")
        if isinstance(construction_method, str) and construction_method:
            strategy["primary_method"] = construction_method.upper()

        realization_class = _infer_realization_class(
            component_type=component_type,
            modeling_strategy=strategy,
            part_payload=part,
        )
        strategy["realization_class"] = realization_class

        effective_contract_pattern = contract_pattern
        primary_method = strategy.get("primary_method")
        if isinstance(effective_contract_pattern, str) and isinstance(primary_method, str):
            expected_contract = FUSION_PARADIGM_CONTRACT.get(effective_contract_pattern)
            expected_method = (
                expected_contract.get("construction_method")
                if isinstance(expected_contract, dict)
                else None
            )
            if isinstance(expected_method, str) and expected_method.upper() != primary_method.upper():
                remapped_pattern = None
                if primary_method.upper() == "EXTRUDE" and shape_type == "cylindrical":
                    remapped_pattern = "AXIAL_EXTRUSION"

                self._log_fallback(
                    component_id=component_id,
                    param_name="contract_pattern_used",
                    reason="contract_pattern_method_mismatch_after_strategy_override",
                    old_value=effective_contract_pattern,
                    new_value=remapped_pattern,
                    stage="contract_alignment",
                )
                effective_contract_pattern = remapped_pattern
                contract_source = "aligned_with_primary_method"

        return {
            "component_id": component_id,
            "modeling_strategy": strategy,
            "parameter_resolution": self.resolved_param_records.get(component_id, {}),
            "contract_pattern_used": effective_contract_pattern,
            "contract_pattern_source": contract_source,
            "realization_class": realization_class,
        }

    def _determine_contract_pattern(
        self,
        part: Dict[str, Any],
        shape_type: str,
        comp_type: str,
    ) -> tuple[Optional[str], str]:
        proposed = None
        if isinstance(part, dict):
            proposed = part.get("modeling_pattern") or part.get("pattern")
        if isinstance(proposed, str) and proposed in FUSION_MODELING_PATTERNS:
            return proposed, "proposed"
        pattern_intent = part.get("pattern_intent") if isinstance(part, dict) else None
        if pattern_intent == "rotational_symmetry":
            return "ROTATIONAL_REVOLVE", "intent"
        if shape_type == "radial_plate":
            return "RADIAL_PLATE_EXTRUSION", "shape_type"
        if shape_type == "prismatic":
            return "PROFILE_EXTRUSION", "shape_type"
        if shape_type == "cylindrical":
            comp_lower = comp_type.lower() if isinstance(comp_type, str) else ""
            shape = part.get("shape_semantics") if isinstance(part, dict) else {}
            cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
            rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
            axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
            if comp_lower in {"wheel", "pulley", "bearing", "rim", "tire"}:
                return "ROTATIONAL_REVOLVE", "component_type"
            if comp_lower == "hub":
                if cross_section == "annular" or rotational_profile is True or axial_shape_variation is True:
                    return "ROTATIONAL_REVOLVE", "component_type"
                return "AXIAL_EXTRUSION", "component_type"
            return "AXIAL_EXTRUSION", "component_type"
        return None, "none"

    def _is_contract_compatible(self, contract_strategy: Dict[str, Any], shape_type: str) -> bool:
        primitive_class = contract_strategy.get("primitive_class")
        construction_method = contract_strategy.get("construction_method")
        shape_map = {
            "cylindrical": "cylindrical",
            "prismatic": "prismatic",
            "radial_plate": "plate",
        }
        expected = shape_map.get(shape_type)
        if expected is None:
            return False
        if primitive_class != expected:
            return False
        if shape_type == "cylindrical":
            return construction_method in {"revolve", "extrude"}
        if shape_type == "prismatic":
            return construction_method == "extrude"
        if shape_type == "radial_plate":
            return construction_method == "extrude"
        return False

    def _numeric_value(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict) and "value" in value:
            try:
                return float(value["value"])
            except Exception:
                return None
        if isinstance(value, str):
            try:
                return float(value)
            except Exception:
                return None
        return None

    def _component_params_raw(self, component_id: str) -> Dict[str, Any]:
        comp = self.components.get(component_id, {})
        params = comp.get("parameters")
        if isinstance(params, dict):
            return params
        return {}

    def _component_params(self, component_id: str) -> Dict[str, Any]:
        if component_id in self.resolved_param_values:
            return self.resolved_param_values[component_id]
        return self._component_params_raw(component_id)

    def _log_fallback(
        self,
        *,
        component_id: str,
        param_name: str,
        reason: str,
        old_value: Any,
        new_value: Any,
        stage: str,
    ) -> None:
        self.fallback_reasons.append(
            {
                "component_id": component_id,
                "param": param_name,
                "reason": reason,
                "old_value": old_value,
                "new_value": new_value,
                "stage": stage,
            }
        )

    def _convert_to_mm(self, value: float, unit: Optional[str]) -> float:
        if not unit:
            return value
        unit_lower = unit.lower()
        factors = {
            "mm": 1.0,
            "cm": 10.0,
            "m": 1000.0,
            "in": 25.4,
            "ft": 304.8,
        }
        factor = factors.get(unit_lower, 1.0)
        return value * factor

    def _default_value(self, component_type: str, param_name: str) -> float:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if isinstance(rule, dict) and "default" in rule:
            return float(rule["default"])
        p = param_name.lower()
        c = component_type.lower() if component_type else ""
        if "thickness" in p or p == "height":
            if "plate" in c or "arm" in c:
                return 6.0
            if "wheel" in c:
                return 8.0
            if "bearing" in c:
                return 6.0
            return 5.0
        if "width" in p:
            if "wheel" in c:
                return 12.0
            if "arm" in c:
                return 14.0
            return 8.0
        if "length" in p or "depth" in p:
            if "arm" in c or "shaft" in c:
                return 60.0
            return 30.0
        if "radius" in p or "diameter" in p:
            if "wheel" in c:
                return 30.0
            if "bearing" in c:
                return 5.0
            if "shaft" in c or "axle" in c:
                return 2.0
            if "hub" in c:
                return 10.0
            return 5.0
        if "arm_count" in p or "count" == p:
            return 3
        return 5.0

    def _is_dimensionless_param(self, param_name: str) -> bool:
        name = param_name.lower()
        return name in {"count", "arm_count"} or name.endswith("_count")

    def _unit_for_param(self, param_name: str) -> str:
        name = param_name.lower() if param_name else ""
        if name.endswith("_param"):
            name = name[: -len("_param")]
        if name in {"count", "arm_count"} or name.endswith("_count"):
            return "count"
        return "mm"

    def _bounds_for(self, value: float, bounds_source: str, param_name: str) -> tuple[float, float]:
        # bounds_source controls envelope tightness; value source is tracked separately.
        is_rule = bounds_source == "rule"
        if self._is_dimensionless_param(param_name):
            base = int(round(value))
            if is_rule:
                return max(1, base - 1), base + 1
            return max(1, base - 2), base + 2
        if is_rule:
            return value * 0.9, value * 1.1
        return value * 0.8, value * 1.2

    def _bounds_source_for(self, component_type: str, param_name: str) -> str:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if isinstance(rule, dict) and ("min" in rule or "max" in rule or "max_ratio" in rule):
            return "rule"
        return "heuristic"

    def _normalize_type_tokens(self, comp_type: str) -> set[str]:
        tokens = {comp_type.lower()} if comp_type else set()
        tokens |= {t for t in re.split(r"[^a-zA-Z0-9]+", comp_type.lower()) if t}
        return tokens

    def _apply_bounds_from_rules(
        self,
        component_type: str,
        param_name: str,
        value: float,
    ) -> float:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        rule = rules.get(param_name)
        if not isinstance(rule, dict):
            return value
        min_v = rule.get("min")
        max_v = rule.get("max")
        if isinstance(min_v, (int, float)):
            value = max(value, float(min_v))
        if isinstance(max_v, (int, float)):
            value = min(value, float(max_v))
        return value

    def _apply_proportions(
        self,
        component_id: str,
        component_type: str,
        resolved: Dict[str, float]
    ) -> None:
        rules = PARAM_RULES.get(component_type.lower() if component_type else "", {})
        proportions = rules.get("proportions") if isinstance(rules, dict) else None
        if not isinstance(proportions, dict):
            return

        if "length_to_width" in proportions and "length" in resolved and "width" in resolved:
            spec = proportions["length_to_width"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            length = resolved["length"]
            width = resolved["width"]
            ratio = length / width if width > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = width * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="length",
                        reason="proportion_min_length_to_width",
                        old_value=resolved["length"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["length"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = width * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="length",
                        reason="proportion_max_length_to_width",
                        old_value=resolved["length"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["length"] = new_val

        if "width_to_radius" in proportions and "width" in resolved and "outer_radius" in resolved:
            spec = proportions["width_to_radius"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            width = resolved["width"]
            radius = resolved["outer_radius"]
            ratio = width / radius if radius > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = radius * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="width",
                        reason="proportion_min_width_to_radius",
                        old_value=resolved["width"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["width"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = radius * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="width",
                        reason="proportion_max_width_to_radius",
                        old_value=resolved["width"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["width"] = new_val

        if "outer_to_bore" in proportions and "outer_diameter" in resolved and "bore_diameter" in resolved:
            spec = proportions["outer_to_bore"]
            min_r = spec.get("min") if isinstance(spec, dict) else None
            max_r = spec.get("max") if isinstance(spec, dict) else None
            outer = resolved["outer_diameter"]
            bore = resolved["bore_diameter"]
            ratio = outer / bore if bore > 0 else None
            if ratio is not None:
                if isinstance(min_r, (int, float)) and ratio < float(min_r):
                    new_val = bore * float(min_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="outer_diameter",
                        reason="proportion_min_outer_to_bore",
                        old_value=resolved["outer_diameter"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["outer_diameter"] = new_val
                if isinstance(max_r, (int, float)) and ratio > float(max_r):
                    new_val = bore * float(max_r)
                    self._log_fallback(
                        component_id=component_id,
                        param_name="outer_diameter",
                        reason="proportion_max_outer_to_bore",
                        old_value=resolved["outer_diameter"],
                        new_value=new_val,
                        stage="proportion",
                    )
                    resolved["outer_diameter"] = new_val

    def _apply_clearance_rules(self, component_id: str, resolved: Dict[str, float]) -> None:
        comp = self.components.get(component_id, {})
        comp_type = comp.get("type", "")
        rules = PARAM_RULES.get(comp_type.lower() if comp_type else "", {})
        clearance = rules.get("clearance") if isinstance(rules, dict) else None
        if not isinstance(clearance, dict):
            return

        if "hub" in clearance:
            gap = clearance["hub"].get("min_radial_gap")
            hub = self._infer_hub_component()
            if isinstance(gap, (int, float)) and hub:
                hub_params = hub.get("parameters", {}) if isinstance(hub.get("parameters"), dict) else {}
                hub_radius = self._numeric_value(hub_params.get("outer_radius"))
                if hub_radius is not None and "outer_radius" in resolved:
                    min_radius = hub_radius + float(gap)
                    if resolved["outer_radius"] < min_radius:
                        self._log_fallback(
                            component_id=component_id,
                            param_name="outer_radius",
                            reason="clearance_hub_min_radial_gap",
                            old_value=resolved["outer_radius"],
                            new_value=min_radius,
                            stage="clearance",
                        )
                        resolved["outer_radius"] = min_radius

        # NOTE: arm clearance for semantic profiles is enforced in feasibility

        if "shaft" in clearance:
            gap = clearance["shaft"].get("min_bore_diameter_over_shaft")
            shafts = self.components_by_type.get("shaft", [])
            kg_component = self.components.get(component_id, {}) if isinstance(self.components, dict) else {}
            dim_sources = kg_component.get("dimension_sources", {}) if isinstance(kg_component.get("dimension_sources"), dict) else {}
            bore_source = dim_sources.get("bore_diameter", {}) if isinstance(dim_sources.get("bore_diameter"), dict) else {}
            component_type = str(kg_component.get("type") or "").strip().lower()
            bore_is_catalog_authority = (
                component_type in {"bearing", "bushing", "seal"}
                or str(bore_source.get("source") or "").strip().lower() == "standard_catalog"
            )
            if isinstance(gap, (int, float)) and shafts and "bore_diameter" in resolved and not bore_is_catalog_authority:
                shaft_params = shafts[0].get("parameters", {}) if isinstance(shafts[0].get("parameters"), dict) else {}
                shaft_d = self._numeric_value(shaft_params.get("diameter"))
                if shaft_d is not None:
                    min_bore = shaft_d + float(gap)
                    if resolved["bore_diameter"] < min_bore:
                        self._log_fallback(
                            component_id=component_id,
                            param_name="bore_diameter",
                            reason="clearance_shaft_min_bore",
                            old_value=resolved["bore_diameter"],
                            new_value=min_bore,
                            stage="clearance",
                        )
                        resolved["bore_diameter"] = min_bore

    def _resolve_semantic_value(
        self,
        component_id: str,
        param_name: str,
        semantic: str | None,
        *,
        known: Dict[str, float],
    ) -> tuple[Optional[float], str]:
        comp_type = self.components.get(component_id, {}).get("type", "")
        base = self._default_value(comp_type, param_name)
        if semantic is None:
            return base, "rule"
        text = semantic.lower().strip()

        if "balanced" in text or "proportion" in text:
            if "width" in param_name and "length" in known:
                return max(4.0, known["length"] * 0.25), "rule"
            if "length" in param_name and "width" in known:
                return max(20.0, known["width"] * 3.0), "rule"
            if "radius" in param_name and "diameter" in known:
                return known["diameter"] / 2.0, "inferred"
            return base, "rule"

        if "thin" in text or "slim" in text:
            return base * 0.6, "rule"
        if "thick" in text or "robust" in text:
            return base * 1.5, "rule"
        if "light" in text:
            return base * 0.5, "rule"
        if "compact" in text:
            return base * 0.8, "rule"
        if "reasonable" in text or "default" in text:
            return base, "rule"

        return base, "rule"

    def _resolve_parameters(self, parts: List[Dict[str, Any]]) -> None:
        self.resolved_param_values = {}
        self.resolved_param_records = {}
        # NOTE: `source` reflects the last authoritative resolution stage, not original provenance.
        for part in parts:
            component_id = part.get("component_id")
            if not component_id:
                continue
            comp_type = self.components.get(component_id, {}).get("type", "")
            shape = part.get("shape_semantics", {})
            raw_params = self._component_params_raw(component_id)

            expected: set[str] = set()
            rule_params = PARAM_RULES.get(comp_type.lower() if comp_type else "", {})
            bound_names: set[str] = set()
            shape_bindings: Dict[str, str] = {}

            def is_numeric_like(val: Any) -> bool:
                if isinstance(val, dict) and "value" in val:
                    return self._numeric_value(val) is not None
                if isinstance(val, (int, float)):
                    return True
                if isinstance(val, str):
                    return self._numeric_value(val) is not None
                return False

            if isinstance(rule_params, dict):
                for key in rule_params.keys():
                    if key not in {"proportions", "clearance"}:
                        expected.add(key)
            for key, value in shape.items():
                if key.endswith("_param") and isinstance(value, str):
                    base = key[: -len("_param")]
                    shape_bindings[base] = value
                    expected.add(base)
                    bound_names.add(value)

            resolved: Dict[str, float] = {}
            records: Dict[str, Dict[str, Any]] = {}
            passthrough_param_names = {
                "diameter",
                "outer_diameter",
                "inner_diameter",
                "bore_diameter",
                "radius",
                "outer_radius",
                "inner_radius",
                "bore_radius",
                "thickness",
                "width",
                "length",
                "height",
            }
            derivable_param_sources = {
                "radius": ("diameter", "outer_diameter", "outer_radius"),
                "outer_radius": ("outer_diameter", "diameter", "radius"),
                "inner_radius": ("inner_diameter", "bore_diameter", "bore_radius"),
            }

            # Record unbound numeric parameters for audit (do not use for strategy)
            for key, val in raw_params.items():
                if key in expected or key in bound_names:
                    continue
                if not is_numeric_like(val):
                    continue
                numeric = None
                if isinstance(val, dict) and "value" in val:
                    numeric = self._numeric_value(val)
                    numeric = self._convert_to_mm(numeric, val.get("unit")) if numeric is not None else None
                elif isinstance(val, (int, float)):
                    numeric = float(val)
                elif isinstance(val, str):
                    numeric = self._numeric_value(val)
                if numeric is None:
                    continue
                if self._is_dimensionless_param(key):
                    numeric = int(round(numeric))
                bounds_source = self._bounds_source_for(comp_type, key)
                min_v, max_v = self._bounds_for(numeric, bounds_source, key)
                note = "unbound_extra_param"
                if key in passthrough_param_names and key not in resolved:
                    resolved[key] = numeric
                    note = "unbound_passthrough_param"
                records[key] = {
                    "value": numeric,
                    "unit": self._unit_for_param(key),
                    "min": min_v,
                    "max": max_v,
                    "bounds_source": bounds_source,
                    "source": "input",
                    "note": note,
                }

            # Pass 1: numeric parameters
            for name in expected:
                raw = raw_params.get(name)
                if raw is None and name in shape_bindings:
                    raw = raw_params.get(shape_bindings[name], shape_bindings[name])
                numeric = None
                source = "input"
                if isinstance(raw, dict) and "value" in raw:
                    numeric = self._numeric_value(raw)
                    numeric = self._convert_to_mm(numeric, raw.get("unit")) if numeric is not None else None
                elif isinstance(raw, (int, float)):
                    numeric = float(raw)
                elif isinstance(raw, str):
                    numeric = self._numeric_value(raw)

                if numeric is not None:
                    if self._is_dimensionless_param(name):
                        numeric = int(round(numeric))
                    if numeric <= 0:
                        fallback = self._default_value(comp_type, name)
                        self._log_fallback(
                            component_id=component_id,
                            param_name=name,
                            reason="non_positive_defaulted",
                            old_value=numeric,
                            new_value=fallback,
                            stage="resolve",
                        )
                        numeric = fallback
                    clamped = self._apply_bounds_from_rules(comp_type, name, numeric)
                    if clamped != numeric:
                        self._log_fallback(
                            component_id=component_id,
                            param_name=name,
                            reason="clamped_to_bounds",
                            old_value=numeric,
                            new_value=clamped,
                            stage="bounds",
                        )
                    numeric = clamped
                    resolved[name] = numeric
                    bounds_source = self._bounds_source_for(comp_type, name)
                    min_v, max_v = self._bounds_for(numeric, bounds_source, name)
                    records[name] = {
                        "value": numeric,
                        "unit": self._unit_for_param(name),
                        "min": min_v,
                        "max": max_v,
                        "bounds_source": bounds_source,
                        "source": source,
                    }

            # Pass 2: semantic or missing parameters
            for name in expected:
                if name in resolved:
                    continue
                derivable_from = derivable_param_sources.get(name, ())
                if any(isinstance(resolved.get(src), (int, float)) and float(resolved.get(src)) > 0 for src in derivable_from):
                    continue
                raw = raw_params.get(name)
                if raw is None and name in shape_bindings:
                    raw = raw_params.get(shape_bindings[name], shape_bindings[name])
                semantic = raw if isinstance(raw, str) else None
                value, source = self._resolve_semantic_value(
                    component_id, name, semantic, known=resolved
                )
                if value is None:
                    continue
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                if semantic is None:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="missing_param_defaulted",
                        old_value=None,
                        new_value=value,
                        stage="resolve",
                    )
                else:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="semantic_resolved_to_rule",
                        old_value=semantic,
                        new_value=value,
                        stage="resolve",
                    )
                clamped = self._apply_bounds_from_rules(comp_type, name, value)
                if clamped != value:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="clamped_to_bounds",
                        old_value=value,
                        new_value=clamped,
                        stage="bounds",
                    )
                value = clamped
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                resolved[name] = value
                bounds_source = self._bounds_source_for(comp_type, name)
                min_v, max_v = self._bounds_for(value, bounds_source, name)
                records[name] = {
                    "value": value,
                    "unit": self._unit_for_param(name),
                    "min": min_v,
                    "max": max_v,
                    "bounds_source": bounds_source,
                    "source": source,
                }

            bearing_like = str(comp_type or "").strip().lower() in {"bearing", "bushing", "seal"}
            if bearing_like:
                width_value = resolved.get("width")
                thickness_value = resolved.get("thickness")
                thickness_record = records.get("thickness") if isinstance(records.get("thickness"), dict) else {}
                width_record = records.get("width") if isinstance(records.get("width"), dict) else {}
                if isinstance(width_value, (int, float)) and (
                    not isinstance(thickness_value, (int, float))
                    or str(thickness_record.get("source") or "").strip().lower() != "input"
                ):
                    resolved["thickness"] = float(width_value)
                    records["thickness"] = {
                        "value": float(width_value),
                        "unit": self._unit_for_param("thickness"),
                        "min": None,
                        "max": None,
                        "bounds_source": self._bounds_source_for(comp_type, "thickness"),
                        "source": "derived",
                        "note": "aliased_from_width",
                    }
                elif isinstance(thickness_value, (int, float)) and (
                    not isinstance(width_value, (int, float))
                    or str(width_record.get("source") or "").strip().lower() != "input"
                ):
                    resolved["width"] = float(thickness_value)
                    records["width"] = {
                        "value": float(thickness_value),
                        "unit": self._unit_for_param("width"),
                        "min": None,
                        "max": None,
                        "bounds_source": self._bounds_source_for(comp_type, "width"),
                        "source": "derived",
                        "note": "aliased_from_thickness",
                    }

            # Pass 3: proportional constraints
            self._apply_proportions(component_id, comp_type, resolved)

            # Pass 4: clearance constraints
            self._apply_clearance_rules(component_id, resolved)

            # Re-apply bounds after adjustments
            for name, value in list(resolved.items()):
                clamped = self._apply_bounds_from_rules(comp_type, name, value)
                if clamped != value:
                    self._log_fallback(
                        component_id=component_id,
                        param_name=name,
                        reason="clamped_to_bounds",
                        old_value=value,
                        new_value=clamped,
                        stage="bounds",
                    )
                value = clamped
                if self._is_dimensionless_param(name):
                    value = int(round(value))
                resolved[name] = value
                bounds_source = self._bounds_source_for(comp_type, name)
                min_v, max_v = self._bounds_for(value, bounds_source, name)
                if name in records:
                    records[name]["value"] = value
                    records[name]["min"] = min_v
                    records[name]["max"] = max_v
                    records[name]["bounds_source"] = bounds_source
                    if records[name].get("source") == "default":
                        records[name]["source"] = "rule"
                else:
                    records[name] = {
                        "value": value,
                        "unit": self._unit_for_param(name),
                        "min": min_v,
                        "max": max_v,
                        "bounds_source": bounds_source,
                        "source": "rule",
                    }

            # Pass 5: derive cylindrical parameters (radius/inner/outer) in Agent3a
            self._derive_cylindrical_params(component_id, comp_type, resolved, records)

            # Pass 6: derive corner_radius for macro_profile (radial plate) in Agent3a
            profile_hint = self._profile_type_from_shape(shape, self._normalize_shape_type(shape, comp_type))
            is_macro_profile = self._normalize_shape_type(shape, comp_type) == "radial_plate" or profile_hint == "radial_hint"
            if is_macro_profile and "corner_radius" not in resolved:
                arm_width = resolved.get("arm_width")
                hub_radius = resolved.get("hub_radius")
                if isinstance(arm_width, (int, float)) and isinstance(hub_radius, (int, float)):
                    corner_radius = min(float(arm_width) * 0.25, float(hub_radius) * 0.25)
                    corner_radius = max(corner_radius, 0.5)
                    resolved["corner_radius"] = float(corner_radius)
                    bounds_source = self._bounds_source_for(comp_type, "corner_radius")
                    min_v, max_v = self._bounds_for(float(corner_radius), bounds_source, "corner_radius")
                    records["corner_radius"] = {
                        "value": float(corner_radius),
                        "unit": self._unit_for_param("corner_radius"),
                        "min": float(min_v),
                        "max": float(max_v),
                        "bounds_source": bounds_source,
                        "source": "derived",
                        "note": "radial_plate_corner_radius",
                    }

            self.resolved_param_values[component_id] = resolved
            self.resolved_param_records[component_id] = records

    def _derive_cylindrical_params(
        self,
        component_id: str,
        comp_type: str,
        resolved: Dict[str, float],
        records: Dict[str, Dict[str, Any]],
    ) -> None:
        """Derive radius/diameter invariants (geometry-only, not CAD binding)."""
        def _record(param_key: str, value: float, *, reason: str) -> None:
            bounds_source = self._bounds_source_for(comp_type, param_key)
            min_v, max_v = self._bounds_for(float(value), bounds_source, param_key)
            records[param_key] = {
                "value": float(value),
                "unit": self._unit_for_param(param_key),
                "min": float(min_v),
                "max": float(max_v),
                "bounds_source": bounds_source,
                "source": "derived",
                "note": reason,
            }

        radius = resolved.get("radius")
        outer_radius = resolved.get("outer_radius")
        inner_radius = resolved.get("inner_radius")
        diameter = resolved.get("diameter")
        outer_diameter = resolved.get("outer_diameter")
        inner_diameter = resolved.get("inner_diameter")
        bore_radius = resolved.get("bore_radius")
        bore_diameter = resolved.get("bore_diameter")

        if radius is None:
            if isinstance(diameter, (int, float)) and diameter > 0:
                radius = diameter / 2
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_diameter",
                    old_value=diameter,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_diameter")
            elif isinstance(outer_diameter, (int, float)) and outer_diameter > 0:
                radius = outer_diameter / 2
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_outer_diameter",
                    old_value=outer_diameter,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_outer_diameter")
            elif isinstance(outer_radius, (int, float)) and outer_radius > 0:
                radius = outer_radius
                resolved["radius"] = radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="radius",
                    reason="derived_from_outer_radius",
                    old_value=outer_radius,
                    new_value=radius,
                    stage="derive",
                )
                _record("radius", radius, reason="derived_from_outer_radius")

        if outer_radius is None and isinstance(outer_diameter, (int, float)) and outer_diameter > 0:
            outer_radius = outer_diameter / 2
            resolved["outer_radius"] = outer_radius
            self._log_fallback(
                component_id=component_id,
                param_name="outer_radius",
                reason="derived_from_outer_diameter",
                old_value=outer_diameter,
                new_value=outer_radius,
                stage="derive",
            )
            _record("outer_radius", outer_radius, reason="derived_from_outer_diameter")

        if inner_radius is None:
            if isinstance(inner_diameter, (int, float)) and inner_diameter > 0:
                inner_radius = inner_diameter / 2
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_inner_diameter",
                    old_value=inner_diameter,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_inner_diameter")
            elif isinstance(bore_radius, (int, float)) and bore_radius > 0:
                inner_radius = bore_radius
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_bore_radius",
                    old_value=bore_radius,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_bore_radius")
            elif isinstance(bore_diameter, (int, float)) and bore_diameter > 0:
                inner_radius = bore_diameter / 2
                resolved["inner_radius"] = inner_radius
                self._log_fallback(
                    component_id=component_id,
                    param_name="inner_radius",
                    reason="derived_from_bore_diameter",
                    old_value=bore_diameter,
                    new_value=inner_radius,
                    stage="derive",
                )
                _record("inner_radius", inner_radius, reason="derived_from_bore_diameter")

    def _validate_feasibility(
        self,
        parts: List[Dict[str, Any]],
        realizations: List[Dict[str, Any]],
    ) -> None:
        part_map = {p.get("component_id"): p for p in parts if isinstance(p, dict)}

        for realization in realizations:
            component_id = realization.get("component_id")
            if not component_id:
                continue
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            comp = self.components.get(component_id, {})
            comp_type = comp.get("type", "")
            resolved_values = self.resolved_param_values.setdefault(component_id, {})

            def _update_param(param_key: str, value: float) -> None:
                resolved_values[param_key] = float(value)
                bounds_source = self._bounds_source_for(comp_type, param_key)
                min_v, max_v = self._bounds_for(float(value), bounds_source, param_key)
                recs = self.resolved_param_records.setdefault(component_id, {})
                recs[param_key] = {
                    "value": float(value),
                    "unit": self._unit_for_param(param_key),
                    "source": "feasibility",
                    "min": float(min_v),
                    "max": float(max_v),
                    "bounds_source": bounds_source,
                }

            # 2) No dimension violates declared bounds
            bounds = self.resolved_param_records.get(component_id, {})
            if isinstance(bounds, dict):
                for name, record in list(bounds.items()):
                    if not isinstance(record, dict):
                        continue
                    value = record.get("value")
                    min_v = record.get("min")
                    max_v = record.get("max")
                    rule_key = record.get("rule_key") if isinstance(record.get("rule_key"), str) else None
                    if not isinstance(rule_key, str):
                        rule_key = name
                    if not isinstance(value, (int, float)):
                        continue
                    clamped = float(value)
                    if isinstance(min_v, (int, float)) and clamped < min_v:
                        clamped = float(min_v)
                    if isinstance(max_v, (int, float)) and clamped > max_v:
                        clamped = float(max_v)
                    if clamped != float(value):
                        self._log_fallback(
                            component_id=component_id,
                            param_name=rule_key,
                            reason="bounds_violation",
                            old_value=value,
                            new_value=clamped,
                            stage="feasibility",
                        )
                        _update_param(rule_key, float(clamped))
                        record["value"] = float(clamped)

            # 3) Symmetry constraints are numerically consistent
            part = part_map.get(component_id, {})
            pattern_intent = part.get("pattern_intent") if isinstance(part, dict) else None
            resolved = self.resolved_param_values.get(component_id, {})
            arm_count = None
            for key in ("arm_count", "count"):
                if key in resolved:
                    arm_count = resolved.get(key)
                    break
            if pattern_intent == "rotational_symmetry":
                if not isinstance(arm_count, (int, float)) or int(round(arm_count)) < 2:
                    fallback = 3
                    self._log_fallback(
                        component_id=component_id,
                        param_name="arm_count",
                        reason="invalid_symmetry_count_defaulted",
                        old_value=arm_count,
                        new_value=fallback,
                        stage="feasibility",
                    )
                    self.resolved_param_records.setdefault(component_id, {})["arm_count"] = {
                        "value": fallback,
                        "unit": "count",
                        "min": 2,
                        "max": 20,
                        "bounds_source": "rule",
                        "source": "feasibility",
                    }
                    _update_param("arm_count", fallback)

            # 4) Clearance between repeated components is non-negative
            kg_comp = self.components.get(component_id, {})
            count = None
            if isinstance(kg_comp, dict):
                params = kg_comp.get("parameters")
                if isinstance(params, dict):
                    count = params.get("count")
            if isinstance(count, int) and count > 1:
                clearance_value = None
                for key in ("clearance", "gap", "spacing", "pitch"):
                    if key in resolved:
                        clearance_value = resolved.get(key)
                        break
                if clearance_value is not None and (
                    not isinstance(clearance_value, (int, float)) or clearance_value < 0
                ):
                    self._log_fallback(
                        component_id=component_id,
                        param_name="clearance",
                        reason="negative_clearance_defaulted",
                        old_value=clearance_value,
                        new_value=0.0,
                        stage="feasibility",
                    )
                    self.resolved_param_records.setdefault(component_id, {})["clearance"] = {
                        "value": 0.0,
                        "unit": "mm",
                        "min": 0.0,
                        "max": 1000.0,
                        "bounds_source": "rule",
                        "source": "feasibility",
                    }

            profile_type = strategy.get("profile_type")
            if profile_type == "macro_profile":
                strategy.pop("parameter_values", None)
                resolved = self.resolved_param_values.get(component_id, {})
                hub_radius = resolved.get("hub_radius")
                arm_count = resolved.get("arm_count")
                arm_length = resolved.get("arm_length")
                arm_width = resolved.get("arm_width")
                thickness = resolved.get("thickness")
                corner_radius = resolved.get("corner_radius")

                missing = [
                    name
                    for name, value in (
                        ("hub_radius", hub_radius),
                        ("arm_count", arm_count),
                        ("arm_length", arm_length),
                        ("arm_width", arm_width),
                        ("thickness", thickness),
                        ("corner_radius", corner_radius),
                    )
                    if not isinstance(value, (int, float))
                ]
                if missing:
                    raise ValueError(
                        f"macro_profile requires numeric parameters; missing: {', '.join(missing)}"
                    )

                if arm_width <= 0 or hub_radius <= 0:
                    raise ValueError(
                        "macro_profile requires positive hub_radius and arm_width"
                    )

                strategy["parameter_semantics"] = {
                    "hub_radius": float(hub_radius),
                    "arm_count": int(round(arm_count)),
                    "arm_length": float(arm_length),
                    "arm_width": float(arm_width),
                    "thickness": float(thickness),
                    "corner_radius": float(corner_radius),
                }
                strategy["macro_kind"] = "rounded_polygon_radial_plate"
            else:
                strategy["parameter_values"] = dict(resolved_values)

    def _upgrade_rotating_wheel_support_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        def _wheel_stack_width_mm(axle_id: str, fallback_width: float, axle_diameter: float) -> float:
            prefix = axle_id.rsplit("_axle", 1)[0] if "_axle" in axle_id else axle_id
            max_width = 0.0
            for cid, comp in self.components.items():
                if not isinstance(cid, str) or not cid:
                    continue
                if cid != prefix and not cid.startswith(prefix + "_"):
                    continue
                if not isinstance(comp, Mapping):
                    continue
                ctype = str(comp.get("type") or "").strip().lower()
                if ctype not in {"wheel", "hub", "rim", "tire", "bearing", "spacer"}:
                    continue
                dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
                for key in ("thickness", "width", "height"):
                    value = dims.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0:
                        max_width = max(max_width, float(value))
                        break
            if max_width > 0:
                return max_width
            return max(axle_diameter + 4.0, min(max(fallback_width, axle_diameter + 2.0), 24.0))

        def _wheel_outer_radius_mm(axle_id: str, fallback_width: float, axle_diameter: float) -> float:
            prefix = axle_id.rsplit("_axle", 1)[0] if "_axle" in axle_id else axle_id
            max_radius = 0.0
            for cid, comp in self.components.items():
                if not isinstance(cid, str) or not cid:
                    continue
                if cid != prefix and not cid.startswith(prefix + "_"):
                    continue
                if not isinstance(comp, Mapping):
                    continue
                ctype = str(comp.get("type") or "").strip().lower()
                if ctype not in {"wheel", "hub", "rim", "tire"}:
                    continue
                dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
                radius = None
                for key in ("outer_radius", "radius"):
                    value = dims.get(key)
                    if isinstance(value, (int, float)) and float(value) > 0.0:
                        radius = float(value)
                        break
                if radius is None:
                    for key in ("outer_diameter", "diameter"):
                        value = dims.get(key)
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            radius = 0.5 * float(value)
                            break
                if isinstance(radius, (int, float)) and float(radius) > 0.0:
                    max_radius = max(max_radius, float(radius))
            if max_radius > 0.0:
                return max_radius
            return max(0.5 * max(fallback_width, axle_diameter + 6.0), 0.75 * axle_diameter)

        support_by_arm: Dict[str, Dict[str, Any]] = {}
        yoke_supported_axles: set[str] = set()
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            if str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "support_member_distal_attachment":
                continue
            support_topology = str(geometric.get("support_topology") or "").strip().lower()
            axial_stack_policy = str(geometric.get("axial_stack_policy") or "").strip().lower()
            is_yoke = support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates"
            is_fork = support_topology in {"distal_fork_dropout_support", "outboard_single_shear"} or axial_stack_policy == "wheel_body_outboard_of_support_plane"
            if not is_yoke and not is_fork:
                continue
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(arm_id, str) or not isinstance(axle_id, str):
                continue
            arm_comp = self.components.get(arm_id) if isinstance(self.components.get(arm_id), Mapping) else {}
            arm_type = str(arm_comp.get("type") or "").strip().lower()
            if arm_type not in {"arm", "fork", "bracket", "support", "link"}:
                continue
            axle_comp = self.components.get(axle_id) if isinstance(self.components.get(axle_id), Mapping) else {}
            axle_dims = axle_comp.get("dimensions") if isinstance(axle_comp.get("dimensions"), Mapping) else {}
            axle_diameter = axle_dims.get("diameter") or axle_dims.get("outer_diameter") or axle_dims.get("nominal_diameter") or 8.0
            try:
                axle_diameter = float(axle_diameter)
            except Exception:
                axle_diameter = 8.0
            resolved = self.resolved_param_values.get(arm_id, {})
            arm_width = float(resolved.get("width") or arm_comp.get("dimensions", {}).get("width") or 20.0)
            arm_length = float(resolved.get("length") or arm_comp.get("dimensions", {}).get("length") or 60.0)
            arm_thickness = float(resolved.get("thickness") or arm_comp.get("dimensions", {}).get("thickness") or 6.0)
            ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
            inset = ref_anchor.get("inset_mm")
            if not isinstance(inset, (int, float)) or float(inset) <= 0:
                inset = max(axle_diameter + 4.0, min(arm_width * 0.6, arm_length * 0.2), 10.0)
            slot_depth = min(max(float(inset), axle_diameter + 4.0), max(8.0, arm_length * 0.3))
            wheel_stack_width = _wheel_stack_width_mm(axle_id, arm_width, axle_diameter)
            wheel_outer_radius = _wheel_outer_radius_mm(axle_id, arm_width, axle_diameter)
            if is_yoke:
                clearance_mm = 2.0
                plate_thickness = max(2.5, min(max(0.5 * arm_thickness, 2.5), max(4.0, 0.75 * axle_diameter)))
                gap_width = max(wheel_stack_width + 2.0 * clearance_mm, axle_diameter + 4.0)
                total_thickness = (2.0 * plate_thickness) + gap_width
                slot_depth = max(
                    float(slot_depth),
                    float(inset) + float(wheel_outer_radius) + float(clearance_mm),
                    float(inset) + (0.5 * float(axle_diameter)) + 2.0,
                )
                root_web_thickness = max(
                    float(plate_thickness),
                    min(float(arm_thickness), max(8.0, float(plate_thickness) * 2.0)),
                )
                support_params = {
                    "axle_inset_mm": float(inset),
                    "thickness": float(total_thickness),
                    "root_web_thickness": float(root_web_thickness),
                    "distal_bore_diameter": float(axle_diameter),
                    "yoke_plate_thickness": float(plate_thickness),
                    "yoke_gap_width": float(gap_width),
                    "yoke_slot_depth": float(slot_depth),
                    "yoke_profile_origin": "midplane",
                }
                support_by_arm[arm_id] = {
                    "profile_type": "yoke_profile",
                    "rationale_suffix": "double_shear_yoke_support_profile",
                    "params": support_params,
                }
                arm_entry = self.components.get(arm_id)
                if isinstance(arm_entry, dict):
                    arm_param_map = arm_entry.get("parameters")
                    if not isinstance(arm_param_map, dict):
                        arm_param_map = {}
                        arm_entry["parameters"] = arm_param_map
                    arm_param_map.update(support_params)
                yoke_supported_axles.add(axle_id)
                continue
            slot_width = min(max(axle_diameter + 2.0, axle_diameter * 1.25), max(0.5, arm_width - 6.0))
            slot_width = max(4.0, slot_width)
            support_by_arm[arm_id] = {
                "profile_type": "fork_profile",
                "rationale_suffix": "fork_dropout_support_profile",
                "params": {
                    "axle_inset_mm": float(inset),
                    "fork_slot_width": float(slot_width),
                    "fork_slot_depth": float(slot_depth),
                },
            }

        if support_by_arm:
            for realization in realizations:
                if not isinstance(realization, Mapping):
                    continue
                component_id = realization.get("component_id")
                if not isinstance(component_id, str) or component_id not in support_by_arm:
                    continue
                strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
                if not isinstance(strategy, dict):
                    continue
                if str(strategy.get("construction_method") or "").strip().lower() != "extrude":
                    continue
                params = dict(strategy.get("parameter_values") or {})
                resolved = self.resolved_param_values.get(component_id, {})
                if "length" not in params and isinstance(resolved.get("length"), (int, float)):
                    params["length"] = float(resolved.get("length"))
                if "width" not in params and isinstance(resolved.get("width"), (int, float)):
                    params["width"] = float(resolved.get("width"))
                if "thickness" not in params and isinstance(resolved.get("thickness"), (int, float)):
                    params["thickness"] = float(resolved.get("thickness"))

                support = support_by_arm[component_id]
                params.update(support["params"])
                strategy["profile_type"] = support["profile_type"]
                rationale = str(strategy.get("selection_rationale") or "")
                strategy["selection_rationale"] = (rationale + ";" + support["rationale_suffix"]).strip(";")
                strategy["parameter_values"] = params

                comp_entry = self.components.get(component_id)
                if isinstance(comp_entry, dict):
                    dims = comp_entry.get("dimensions")
                    if not isinstance(dims, dict):
                        dims = {}
                        comp_entry["dimensions"] = dims
                    for key in ("length", "width", "thickness"):
                        value = params.get(key)
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            dims[key] = float(value)
                    comp_params = comp_entry.get("parameters")
                    if not isinstance(comp_params, dict):
                        comp_params = {}
                        comp_entry["parameters"] = comp_params
                    for key, value in support["params"].items():
                        if isinstance(value, (int, float)):
                            comp_params[key] = float(value)
                            self.resolved_param_values.setdefault(component_id, {})[key] = float(value)
                    if isinstance(params.get("thickness"), (int, float)):
                        self.resolved_param_values.setdefault(component_id, {})["thickness"] = float(params["thickness"])

                inset = float(support["params"]["axle_inset_mm"])
                half_length = 0.5 * float(params.get("length") or resolved.get("length") or 60.0)
                seed_x = round(max(0.0, half_length - inset), 4)
                for feature in realization.get("features", []) if isinstance(realization.get("features"), list) else []:
                    if not isinstance(feature, dict):
                        continue
                    if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
                        continue
                    interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                    interface_name = str(interface_ref.get("name") or "").strip().lower()
                    if support["profile_type"] != "yoke_profile" and interface_name and interface_name != "distal_mount_face":
                        continue
                    seed_z = 0.0
                    if support["profile_type"] == "yoke_profile":
                        plate_thickness = float(support["params"].get("yoke_plate_thickness") or 0.0)
                        gap_width = float(support["params"].get("yoke_gap_width") or 0.0)
                        seed_z = 0.0
                        interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                        interface_ref["name"] = "axial_end_face_max"
                        interface_ref["component_id"] = component_id
                        feature["interface_ref"] = interface_ref
                        anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
                        anchor["face_interface_id"] = "axial_end_face_max"
                        anchor["side_hint"] = "MAX"
                        anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                        feature["anchor"] = anchor
                        geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
                        geometry_parameters["face_interface_id"] = "axial_end_face_max"
                        nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                        nested_anchor["face_interface_id"] = "axial_end_face_max"
                        nested_anchor["side_hint"] = "MAX"
                        nested_anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                        geometry_parameters["anchor"] = nested_anchor
                        feature["geometry_parameters"] = geometry_parameters
                    feature["seed_point_mm"] = {"x": seed_x, "y": 0.0, "z": seed_z}
                    instances = feature.get("instances") if isinstance(feature.get("instances"), list) else []
                    for instance in instances:
                        if isinstance(instance, dict):
                            instance["position"] = {"x": seed_x, "y": 0.0, "z": seed_z}

        for realization in realizations:
            if not isinstance(realization, Mapping):
                continue
            strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
            if not isinstance(strategy, dict):
                continue
            if str(strategy.get("profile_type") or "").strip().lower() != "yoke_profile":
                continue
            params = dict(strategy.get("parameter_values") or {})
            length = float(params.get("length") or 60.0)
            axle_inset = float(params.get("axle_inset_mm") or 12.0)
            plate_thickness = float(params.get("yoke_plate_thickness") or 3.0)
            gap_width = float(params.get("yoke_gap_width") or 10.0)
            seed_x = round(max(0.0, (0.5 * length) - axle_inset), 4)
            seed_z = 0.0
            for feature in realization.get("features", []) if isinstance(realization.get("features"), list) else []:
                if not isinstance(feature, dict):
                    continue
                if str(feature.get("feature_type") or "").strip().lower() != "shaft_bore":
                    continue
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                interface_ref["name"] = "axial_end_face_max"
                interface_ref["component_id"] = component_id
                feature["interface_ref"] = interface_ref
                anchor = feature.get("anchor") if isinstance(feature.get("anchor"), Mapping) else {}
                anchor["face_interface_id"] = "axial_end_face_max"
                anchor["side_hint"] = "MAX"
                anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                feature["anchor"] = anchor
                geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), Mapping) else {}
                geometry_parameters["face_interface_id"] = "axial_end_face_max"
                nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                nested_anchor["face_interface_id"] = "axial_end_face_max"
                nested_anchor["side_hint"] = "MAX"
                nested_anchor["normal_hint"] = {"mode": "FACE_NORMAL"}
                geometry_parameters["anchor"] = nested_anchor
                feature["geometry_parameters"] = geometry_parameters
                feature["seed_point_mm"] = {"x": seed_x, "y": 0.0, "z": seed_z}
                instances = feature.get("instances") if isinstance(feature.get("instances"), list) else []
                for instance in instances:
                    if isinstance(instance, dict):
                        instance["position"] = {"x": seed_x, "y": 0.0, "z": seed_z}

        if yoke_supported_axles:
            for realization in realizations:
                if not isinstance(realization, Mapping):
                    continue
                component_id = realization.get("component_id")
                if not isinstance(component_id, str) or component_id not in yoke_supported_axles:
                    continue
                strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else None
                if not isinstance(strategy, dict):
                    continue
                if str(strategy.get("construction_method") or "").strip().lower() != "extrude":
                    continue
                params = dict(strategy.get("parameter_values") or {})
                params["symmetric_about_sketch_plane"] = True
                strategy["parameter_values"] = params

    def _upgrade_opposed_bearing_seat_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        realization_by_id: Dict[str, Dict[str, Any]] = {}
        for item in realizations:
            if isinstance(item, dict) and isinstance(item.get("component_id"), str):
                realization_by_id[str(item["component_id"])] = item

        host_to_bearings: Dict[str, Dict[str, str]] = {}
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "press_fit":
                continue
            anchor_semantics = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            if str(anchor_semantics.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "bearing_outer_race_seat":
                continue
            host_id = anchor_semantics.get("reference_component_id") if isinstance(anchor_semantics.get("reference_component_id"), str) else None
            bearing_id = anchor_semantics.get("moving_component_id") if isinstance(anchor_semantics.get("moving_component_id"), str) else None
            if not isinstance(host_id, str) or not isinstance(bearing_id, str):
                continue
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            interface_name = str(interface_ref.get("name") or placement.get("seat_side") or "").strip().lower()
            side = "min" if interface_name.endswith("_min") or interface_name == "min" else ("max" if interface_name.endswith("_max") or interface_name == "max" else "")
            if side:
                host_to_bearings.setdefault(host_id, {})[bearing_id] = side

        for host_id, bearing_sides in host_to_bearings.items():
            if len(bearing_sides) < 2:
                continue
            host_realization = realization_by_id.get(host_id)
            if not isinstance(host_realization, dict):
                continue
            strategy = host_realization.get("modeling_strategy") if isinstance(host_realization.get("modeling_strategy"), dict) else None
            if not isinstance(strategy, dict):
                continue
            params = dict(strategy.get("parameter_values") or {})
            host_comp = self.components.get(host_id) if isinstance(self.components.get(host_id), Mapping) else {}
            host_dims = host_comp.get("dimensions") if isinstance(host_comp.get("dimensions"), Mapping) else {}
            widths: List[float] = []
            for bearing_id in bearing_sides.keys():
                bearing_comp = self.components.get(bearing_id) if isinstance(self.components.get(bearing_id), Mapping) else {}
                bearing_dims = bearing_comp.get("dimensions") if isinstance(bearing_comp.get("dimensions"), Mapping) else {}
                width = bearing_dims.get("width") or bearing_dims.get("thickness")
                if isinstance(width, (int, float)) and float(width) > 0.0:
                    widths.append(float(width))
            max_width = max(widths) if widths else 7.0
            shoulder_mm = 1.0
            current_thickness = params.get("thickness")
            if not isinstance(current_thickness, (int, float)) or float(current_thickness) <= 0.0:
                current_thickness = host_dims.get("thickness") or self.resolved_param_values.get(host_id, {}).get("thickness") or (2.0 * max_width + 2.0 * shoulder_mm)
            desired_thickness = max(float(current_thickness), 2.0 * max_width + 2.0 * shoulder_mm)
            params["thickness"] = float(desired_thickness)
            params["opposed_bearing_width"] = float(max_width)
            params["opposed_bearing_shoulder"] = float(shoulder_mm)
            strategy["parameter_values"] = params
            rationale = str(strategy.get("selection_rationale") or "")
            if "opposed_bearing_outer_race_stack" not in rationale:
                strategy["selection_rationale"] = (rationale + ';opposed_bearing_outer_race_stack').strip(';')

            if isinstance(host_comp, dict):
                dims = host_comp.get("dimensions") if isinstance(host_comp.get("dimensions"), dict) else {}
                dims["thickness"] = float(desired_thickness)
                host_comp["dimensions"] = dims
                comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                comp_params["opposed_bearing_width"] = float(max_width)
                comp_params["opposed_bearing_shoulder"] = float(shoulder_mm)
                host_comp["parameters"] = comp_params
            self.resolved_param_values.setdefault(host_id, {})["thickness"] = float(desired_thickness)
            self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_width"] = float(max_width)
            self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_shoulder"] = float(shoulder_mm)

            desired_sides = sorted({side for side in bearing_sides.values() if side in {"min", "max"}}, key=lambda value: 0 if value == "min" else 1)
            seat_features = []
            for feature in host_realization.get("features", []) if isinstance(host_realization.get("features"), list) else []:
                if isinstance(feature, dict) and str(feature.get("feature_type") or "").strip().lower() == "bearing_seat":
                    seat_features.append(feature)
            seat_features.sort(key=lambda item: str(item.get("feature_id") or ""))
            seat_diameters: List[float] = []
            seat_depths: List[float] = []
            for seat_feature in seat_features:
                geometry_parameters = seat_feature.get("geometry_parameters") if isinstance(seat_feature.get("geometry_parameters"), dict) else {}
                seat_diameter = geometry_parameters.get("bore_diameter")
                seat_depth = geometry_parameters.get("depth")
                if isinstance(seat_diameter, (int, float)) and float(seat_diameter) > 0.0:
                    seat_diameters.append(float(seat_diameter))
                if isinstance(seat_depth, (int, float)) and float(seat_depth) > 0.0:
                    seat_depths.append(float(seat_depth))
            if seat_diameters:
                seat_diameter_value = float(max(seat_diameters))
                params["opposed_bearing_seat_diameter"] = seat_diameter_value
                if isinstance(host_comp, dict):
                    comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                    comp_params["opposed_bearing_seat_diameter"] = seat_diameter_value
                    host_comp["parameters"] = comp_params
                self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_seat_diameter"] = seat_diameter_value
            if seat_depths:
                seat_depth_value = float(max(seat_depths))
                params["opposed_bearing_seat_depth"] = seat_depth_value
                if isinstance(host_comp, dict):
                    comp_params = host_comp.get("parameters") if isinstance(host_comp.get("parameters"), dict) else {}
                    comp_params["opposed_bearing_seat_depth"] = seat_depth_value
                    host_comp["parameters"] = comp_params
                self.resolved_param_values.setdefault(host_id, {})["opposed_bearing_seat_depth"] = seat_depth_value
            strategy["parameter_values"] = params
            for side, feature in zip(desired_sides, seat_features):
                interface_name = f"bearing_seat_{side}"
                start_face_interface_id = f"axial_end_face_{side}"
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), dict) else {}
                interface_ref["name"] = interface_name
                feature["interface_ref"] = interface_ref
                geometry_parameters = feature.get("geometry_parameters") if isinstance(feature.get("geometry_parameters"), dict) else {}
                geometry_parameters["face_interface_id"] = start_face_interface_id
                geometry_parameters["side_hint"] = side.upper()
                nested_anchor = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), dict) else {}
                nested_anchor["face_interface_id"] = start_face_interface_id
                nested_anchor["side_hint"] = side.upper()
                geometry_parameters["anchor"] = nested_anchor
                feature["geometry_parameters"] = geometry_parameters
                anchor = feature.get("anchor") if isinstance(feature.get("anchor"), dict) else {}
                anchor["face_interface_id"] = start_face_interface_id
                anchor["side_hint"] = side.upper()
                feature["anchor"] = anchor
                feature["seat_side"] = side

    def _suppress_bearing_backed_wheel_hub_bores(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        hub_to_bearings: Dict[str, Set[str]] = {}
        axle_to_bearings: Dict[str, Set[str]] = {}
        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            mechanism = str(placement.get("connection_mechanism") or "").strip().lower()
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
            contact_model = str(geometric.get("contact_model") or "").strip().lower()
            if mechanism == "press_fit" and relation_type == "bearing_outer_race_seat":
                hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
                bearing_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
                if isinstance(hub_id, str) and isinstance(bearing_id, str):
                    hub_to_bearings.setdefault(hub_id, set()).add(bearing_id)
                continue
            if mechanism == "shaft_bore_fit" and contact_model == "bearing_inner_race_revolute_fit":
                axle_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
                bearing_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
                if isinstance(axle_id, str) and isinstance(bearing_id, str):
                    axle_to_bearings.setdefault(axle_id, set()).add(bearing_id)

        bearing_backed_hubs: Set[str] = set()
        for hub_id, bearing_ids in hub_to_bearings.items():
            match = re.match(r"^wheel_(\d+)_hub$", str(hub_id), flags=re.IGNORECASE)
            if not match:
                continue
            axle_id = f"wheel_{match.group(1)}_axle"
            if bearing_ids & axle_to_bearings.get(axle_id, set()):
                bearing_backed_hubs.add(hub_id)

        if not bearing_backed_hubs:
            return

        for realization in realizations:
            if not isinstance(realization, dict):
                continue
            component_id = realization.get("component_id")
            if not isinstance(component_id, str) or component_id not in bearing_backed_hubs:
                continue

            features = realization.get("features") if isinstance(realization.get("features"), list) else []
            rewritten_features: List[Dict[str, Any]] = []
            removed_shaft_bore = False
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                feature_type = str(feature.get("feature_type") or "").strip().lower()
                if feature_type == "shaft_bore":
                    interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                    interface_name = str(interface_ref.get("name") or "").strip().lower()
                    if interface_name == "bore_axis" or "rotation@" in str(feature.get("feature_id") or ""):
                        removed_shaft_bore = True
                        continue
                rewritten_features.append(feature)

            if features:
                realization["features"] = rewritten_features
            strategy = realization.get("modeling_strategy") if isinstance(realization.get("modeling_strategy"), dict) else {}
            params = dict(strategy.get("parameter_values") or {})
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                if key in params:
                    params[key] = 0.0
            strategy["parameter_values"] = params
            realization["modeling_strategy"] = strategy

            parameter_resolution = realization.get("parameter_resolution") if isinstance(realization.get("parameter_resolution"), dict) else {}
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                entry = parameter_resolution.get(key) if isinstance(parameter_resolution.get(key), dict) else None
                if entry is None:
                    continue
                entry["value"] = 0.0
                entry["source"] = "derived"
                entry["note"] = "suppressed_for_bearing_backed_wheel_hub"
                parameter_resolution[key] = entry
            realization["parameter_resolution"] = parameter_resolution

            comp_entry = self.components.get(component_id) if isinstance(self.components.get(component_id), dict) else None
            if isinstance(comp_entry, dict):
                dims = comp_entry.get("dimensions") if isinstance(comp_entry.get("dimensions"), dict) else {}
                for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                    if key in dims:
                        dims[key] = 0.0
                comp_entry["dimensions"] = dims
                comp_params = comp_entry.get("parameters") if isinstance(comp_entry.get("parameters"), dict) else {}
                for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                    if key in comp_params:
                        comp_params[key] = 0.0
                comp_entry["parameters"] = comp_params

            resolved = self.resolved_param_values.setdefault(component_id, {})
            for key in ("bore_diameter", "inner_diameter", "inner_radius"):
                if key in resolved:
                    resolved[key] = 0.0

    def _upgrade_hub_slot_mount_realizations(self, realizations: List[Dict[str, Any]], semantics: Mapping[str, Any]) -> None:
        placements = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements, list) or not realizations:
            return

        realization_by_id: Dict[str, Dict[str, Any]] = {}
        for item in realizations:
            if isinstance(item, dict) and isinstance(item.get("component_id"), str):
                realization_by_id[str(item["component_id"])] = item

        for placement in placements:
            if not isinstance(placement, Mapping):
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric.get("support_topology") or "").strip().lower()
            if support_topology != "hub_radial_slot_mount":
                continue
            hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            arm_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(hub_id, str) or not isinstance(arm_id, str):
                continue
            hub_realization = realization_by_id.get(hub_id)
            arm_realization = realization_by_id.get(arm_id)
            if not isinstance(hub_realization, dict) or not isinstance(arm_realization, dict):
                continue

            hub_strategy = hub_realization.get("modeling_strategy") if isinstance(hub_realization.get("modeling_strategy"), dict) else None
            arm_strategy = arm_realization.get("modeling_strategy") if isinstance(arm_realization.get("modeling_strategy"), dict) else None
            if not isinstance(hub_strategy, dict) or not isinstance(arm_strategy, dict):
                continue

            arm_params = dict(arm_strategy.get("parameter_values") or {})
            resolved_arm = self.resolved_param_values.get(arm_id, {})
            arm_comp = self.components.get(arm_id) if isinstance(self.components.get(arm_id), Mapping) else {}
            arm_width = float(arm_params.get("width") or resolved_arm.get("width") or arm_comp.get("dimensions", {}).get("width") or 20.0)
            arm_thickness = float(arm_params.get("thickness") or resolved_arm.get("thickness") or arm_comp.get("dimensions", {}).get("thickness") or 6.0)
            root_web_thickness = float(
                arm_params.get("root_web_thickness")
                or resolved_arm.get("root_web_thickness")
                or arm_thickness
            )

            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
            insert_depth = moving_anchor.get("inset_mm")
            if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
                insert_depth = 12.0
            slot_depth = max(float(insert_depth) + 2.0, min(max(8.0, arm_width * 0.6), 18.0))
            slot_width = arm_width + 1.0
            slot_height = max(2.0, root_web_thickness + 1.0)

            arm_params["hub_slot_insert_depth"] = float(insert_depth)
            arm_strategy["parameter_values"] = arm_params

            arm_entry = self.components.get(arm_id)
            if isinstance(arm_entry, dict):
                arm_params_map = arm_entry.get("parameters")
                if not isinstance(arm_params_map, dict):
                    arm_params_map = {}
                    arm_entry["parameters"] = arm_params_map
                arm_params_map["hub_slot_insert_depth"] = float(insert_depth)

            hub_params = dict(hub_strategy.get("parameter_values") or {})
            hub_entry = self.components.get(hub_id) if isinstance(self.components.get(hub_id), dict) else {}
            hub_dims = hub_entry.get("dimensions") if isinstance(hub_entry.get("dimensions"), dict) else {}
            hub_thickness = float(hub_params.get("thickness") or self.resolved_param_values.get(hub_id, {}).get("thickness") or hub_dims.get("thickness") or 20.0)
            desired_hub_thickness = max(hub_thickness, root_web_thickness + 4.0)
            hub_params["thickness"] = float(desired_hub_thickness)
            radial_slot_specs = hub_params.get("radial_slot_specs") if isinstance(hub_params.get("radial_slot_specs"), list) else []
            slot_specs_by_arm: Dict[str, Dict[str, float]] = {}
            for existing_spec in radial_slot_specs:
                if not isinstance(existing_spec, Mapping):
                    continue
                existing_arm_id = existing_spec.get("arm_id") if isinstance(existing_spec.get("arm_id"), str) else None
                if not isinstance(existing_arm_id, str) or not existing_arm_id:
                    continue
                slot_specs_by_arm[existing_arm_id] = {
                    "arm_id": existing_arm_id,
                    "slot_width": float(existing_spec.get("slot_width") or 0.0),
                    "slot_depth": float(existing_spec.get("slot_depth") or 0.0),
                    "slot_height": float(existing_spec.get("slot_height") or 0.0),
                    "insert_depth": float(existing_spec.get("insert_depth") or 0.0),
                }
            merged_slot_spec = slot_specs_by_arm.get(
                arm_id,
                {"arm_id": arm_id, "slot_width": 0.0, "slot_depth": 0.0, "slot_height": 0.0, "insert_depth": 0.0},
            )
            merged_slot_spec["slot_width"] = max(float(merged_slot_spec.get("slot_width") or 0.0), float(slot_width))
            merged_slot_spec["slot_depth"] = max(float(merged_slot_spec.get("slot_depth") or 0.0), float(slot_depth))
            merged_slot_spec["slot_height"] = max(float(merged_slot_spec.get("slot_height") or 0.0), float(slot_height))
            merged_slot_spec["insert_depth"] = max(float(merged_slot_spec.get("insert_depth") or 0.0), float(insert_depth))
            slot_specs_by_arm[arm_id] = merged_slot_spec
            hub_params["radial_slot_specs"] = list(slot_specs_by_arm.values())
            hub_strategy["parameter_values"] = hub_params

            if isinstance(hub_entry, dict):
                hub_dims = hub_entry.get("dimensions")
                if not isinstance(hub_dims, dict):
                    hub_dims = {}
                    hub_entry["dimensions"] = hub_dims
                hub_dims["thickness"] = float(desired_hub_thickness)
                hub_params_map = hub_entry.get("parameters")
                if not isinstance(hub_params_map, dict):
                    hub_params_map = {}
                    hub_entry["parameters"] = hub_params_map
                hub_params_map["radial_slot_specs"] = list(slot_specs_by_arm.values())
                hub_params_map["thickness"] = float(desired_hub_thickness)
            self.resolved_param_values.setdefault(hub_id, {})["thickness"] = float(desired_hub_thickness)

    def _rewrite_hub_slot_mount_fastener_features(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            if not isinstance(realization, dict):
                continue
            component_id = realization.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                continue
            component_entry = self.components.get(component_id) if isinstance(self.components.get(component_id), Mapping) else {}
            component_type = str(component_entry.get("type") or "").strip().lower()
            features = realization.get("features")
            if not isinstance(features, list) or not features:
                continue

            rewritten_features: List[Dict[str, Any]] = []
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                feature_type = str(feature.get("feature_type") or "").strip().lower()
                feature_group_id = str(feature.get("feature_group_id") or feature.get("feature_id") or "").strip().lower()
                interface_ref = feature.get("interface_ref") if isinstance(feature.get("interface_ref"), Mapping) else {}
                interface_name = str(interface_ref.get("name") or "").strip().lower()
                is_semantic_slot_mount_feature = (
                    interface_name.startswith("slot_mount_face_phase_")
                    or interface_name == "proximal_insert_face"
                )
                if (
                    not is_semantic_slot_mount_feature
                    and "hub_to_arm" not in feature_group_id
                    and "central_hub_to_arm" not in feature_group_id
                    and "central_hub_to_wheel_arm" not in feature_group_id
                ):
                    rewritten_features.append(feature)
                    continue

                if component_type == "arm" and feature_type == "nut_seat":
                    continue

                if feature_type != "hole":
                    rewritten_features.append(feature)
                    continue

                if component_id == "central_hub" or component_type == "arm":
                    updated_feature = dict(feature)
                    interface_ref = updated_feature.get("interface_ref") if isinstance(updated_feature.get("interface_ref"), dict) else {}
                    updated_interface_ref = dict(interface_ref)
                    target_face = "axial_end_face_max"
                    updated_interface_ref["name"] = target_face
                    updated_interface_ref["geometry_type"] = "planar"
                    updated_interface_ref["geom_type"] = "planar"
                    updated_feature["interface_ref"] = updated_interface_ref

                    anchor = updated_feature.get("anchor") if isinstance(updated_feature.get("anchor"), dict) else {}
                    updated_anchor = dict(anchor)
                    updated_anchor["face_interface_id"] = target_face
                    updated_anchor["side_hint"] = "MAX"
                    normal_hint = updated_anchor.get("normal_hint") if isinstance(updated_anchor.get("normal_hint"), dict) else {}
                    updated_anchor["normal_hint"] = {"mode": str(normal_hint.get("mode") or "FACE_NORMAL")}
                    updated_feature["anchor"] = updated_anchor
                    rewritten_features.append(updated_feature)
                    continue

                rewritten_features.append(feature)

            realization["features"] = rewritten_features

    def _enforce_numeric_output(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            component_id = realization.get("component_id")
            if not component_id:
                continue
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            profile_type = strategy.get("profile_type")
            if profile_type == "macro_profile":
                if "parameter_values" in strategy:
                    raise ValueError(
                        f"Macro profile '{profile_type}' must not include parameter_values"
                    )
                allowed_keys = {
                    "hub_radius",
                    "arm_count",
                    "arm_length",
                    "arm_width",
                    "thickness",
                    "corner_radius",
                }
                for k, v in strategy.get("parameter_semantics", {}).items():
                    if k not in allowed_keys:
                        raise ValueError(
                            f"Macro profile parameter '{k}' is not allowed"
                        )
                    if not isinstance(v, (int, float)):
                        raise ValueError(
                            f"Macro profile parameter '{k}' must be numeric, got {v}"
                        )
                    if k.endswith("_param"):
                        raise ValueError(
                            f"Macro profile parameter '{k}' must not end with _param"
                        )
                    if k == "arm_count" and not isinstance(v, int):
                        raise ValueError(
                            f"Macro profile parameter 'arm_count' must be int, got {v}"
                        )
                    if k in {"hub_radius", "arm_length", "arm_width", "thickness", "corner_radius"}:
                        if v <= 0:
                            raise ValueError(
                                f"Macro profile parameter '{k}' must be > 0, got {v}"
                            )
            else:
                if "parameter_values" not in strategy:
                    raise ValueError(
                        f"Non-semantic profile requires parameter_values but none provided"
                    )
                strategy.pop("parameter_semantics", None)

    def _normalize_profile_type(self, strategy: Dict[str, Any]) -> None:
        pt = strategy.get("profile_type")
        alias = {
            "circle_hint": "circle",
            "annular_hint": "annular",
            "rectangle_hint": "rectangle",
            "radial_hint": "macro_profile",
            "circular": "circle",
            "rectangular": "rectangle",
            "radial": "macro_profile",
            "rounded_polygon": "macro_profile",
            "polygon": "macro_profile",
            "semantic_profile": "macro_profile",
            "unspecified": None,
            "unknown": None,
        }
        pt = alias.get(pt, pt)
        if pt in {None, ""}:
            primitive_class = strategy.get("primitive_class")
            if primitive_class == "cylindrical":
                pt = "circle"
            elif primitive_class in {"prismatic", "plate"}:
                pt = "rectangle"
        if pt not in ALLOWED_PROFILE_TYPES:
            raise ValueError(f"Illegal profile_type emitted by Agent3a: {pt}")
        strategy["profile_type"] = pt

    def _assert_no_param_keys(self, obj: Any, *, path: str = "strategy") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if isinstance(key, str) and key.endswith("_param"):
                    raise ValueError(f"Illegal key ending with _param in {path}: {key}")
                next_path = f"{path}.{key}" if isinstance(key, str) else path
                self._assert_no_param_keys(val, path=next_path)
        elif isinstance(obj, list):
            for idx, val in enumerate(obj):
                self._assert_no_param_keys(val, path=f"{path}[{idx}]")

    def _final_validate(self, realizations: List[Dict[str, Any]]) -> None:
        for realization in realizations:
            strategy = realization.get("modeling_strategy", {})
            if not isinstance(strategy, dict):
                continue
            self._assert_no_param_keys(strategy)
            if strategy.get("construction_method") not in {"extrude", "revolve"}:
                raise ValueError(
                    f"Illegal construction_method emitted by Agent3a: {strategy.get('construction_method')}"
                )
            # Hard constraint: only choose methods supported by the function registry.
            # This prevents drift / fabrication when downstream execution functions are limited.
            method = strategy.get("construction_method")
            if isinstance(method, str) and self.function_registry:
                if not _registry_supports_construction_method(self.function_registry, method):
                    # Prefer sketch+extrude as a conservative fallback.
                    self._log_fallback(
                        component_id=realization.get("component_id", ""),
                        param_name="construction_method",
                        reason="method_not_supported_by_registry",
                        old_value=method,
                        new_value="extrude",
                        stage="final_validate",
                    )
                    strategy["construction_method"] = "extrude"
            if strategy.get("primitive_class") not in {"cylindrical", "prismatic", "plate"}:
                raise ValueError(
                    f"Illegal primitive_class emitted by Agent3a: {strategy.get('primitive_class')}"
                )
            profile_type = strategy.get("profile_type")
            if method == "revolve" and profile_type not in {"half_profile", "tire_profile"}:
                fallback_profile = "annular" if profile_type == "annular" else "circle"
                self._log_fallback(
                    component_id=realization.get("component_id", ""),
                    param_name="construction_method",
                    reason="revolve_requires_half_profile_execution_profile",
                    old_value=f"revolve/{profile_type}",
                    new_value=f"extrude/{fallback_profile}",
                    stage="final_validate",
                )
                strategy["construction_method"] = "extrude"
                strategy["primary_method"] = "EXTRUDE"
                strategy["profile_type"] = fallback_profile
                method = "extrude"
                profile_type = fallback_profile
            if profile_type not in ALLOWED_PROFILE_TYPES:
                raise ValueError(f"Illegal profile_type emitted by Agent3a: {profile_type}")
            if profile_type == "macro_profile":
                for v in strategy.get("parameter_semantics", {}).values():
                    if not isinstance(v, (int, float)):
                        raise ValueError(
                            "Macro profile parameters must be numeric in final validation"
                        )

    def _resolve_param_by_candidates(
        self,
        component_id: str,
        raw: Any,
        *,
        candidates: List[str],
        expect: str = "scalar",
    ) -> Optional[float]:
        params = self._component_params(component_id)
        search_names: List[str] = []
        if isinstance(raw, str):
            search_names.append(raw)
        for c in candidates:
            if c not in search_names:
                search_names.append(c)

        for name in search_names:
            if name in params:
                val = self._numeric_value(params[name])
                if val is None:
                    continue
                if expect == "radius" and "diameter" in name:
                    return val / 2
                return val

        val = self._numeric_value(raw)
        if val is not None:
            return val
        return None

    def _ensure_positive(self, component_id: str, name: str, value: Any) -> float:
        if not isinstance(value, (int, float)) or value <= 0:
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="infeasible_non_positive",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return float(fallback)
        return float(value)

    def _ensure_integer(self, component_id: str, name: str, value: Any) -> int:
        if not isinstance(value, (int, float)):
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="missing_integer_defaulted",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return int(round(fallback))
        iv = int(round(value))
        if iv <= 0:
            comp_type = self.components.get(component_id, {}).get("type", "")
            fallback = self._default_value(comp_type, name)
            self._log_fallback(
                component_id=component_id,
                param_name=name,
                reason="non_positive_integer_defaulted",
                old_value=value,
                new_value=fallback,
                stage="feasibility",
            )
            return int(round(fallback))
        return iv

    def _infer_arm_components(self) -> List[Dict[str, Any]]:
        arms = list(self.components_by_type.get("arm", []))
        if arms:
            return arms
        for comp in self.components.values():
            cid = comp.get("id", "")
            if isinstance(cid, str) and "arm" in cid:
                arms.append(comp)
        return arms

    def _infer_hub_component(self) -> Optional[Dict[str, Any]]:
        hubs = self.components_by_type.get("hub", [])
        if hubs:
            return hubs[0]
        for comp in self.components.values():
            cid = comp.get("id", "")
            if isinstance(cid, str) and "hub" in cid:
                return comp
        return None
    
    def _select_cylindrical_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for cylindrical components.
        
        CONSTRAINT: Only use binding semantic classifications (no CAD-execution assumptions).
        
        NOTE: Do NOT introduce sketch/profile primitives or *_param bindings here.
        """
        axial_profile = shape.get("axial_profile") if isinstance(shape, dict) else None
        rotational_profile = shape.get("rotational_profile") if isinstance(shape, dict) else None
        axial_shape_variation = shape.get("axial_shape_variation") if isinstance(shape, dict) else None
        profile_type_hint = shape.get("profile_type") or shape.get("cross_section") if isinstance(shape, dict) else None
        cross_section = shape.get("cross_section") if isinstance(shape, dict) else None
        kg_component = self.components.get(component_id, {}) if isinstance(self.components, Mapping) else {}
        component_type = str(kg_component.get("type") or "").strip().lower()

        rotational_solid = rotational_profile is True or axial_shape_variation is True
        non_constant_axial = axial_profile not in (None, "constant")
        half_profile_ok = profile_type_hint in {"half_profile", "half-profile", "halfprofile"}

        inner_radius = None
        if isinstance(shape, dict):
            inner_radius = shape.get("inner_radius")
            if inner_radius is None:
                inner_radius = shape.get("bore_radius")
        inner_radius_val = self._numeric_value(inner_radius)
        touches_axis = inner_radius_val is not None and inner_radius_val <= 0

        annular_rotational_types = {"bearing", "rim", "tire", "hub", "wheel", "roller", "pulley", "sheave"}
        prefer_annular_revolve = cross_section == "annular" and not touches_axis and component_type in annular_rotational_types
        explicit_revolve = rotational_solid and non_constant_axial and not touches_axis

        if prefer_annular_revolve or explicit_revolve:
            rationale = "annular_rotational_body_prefer_revolve" if prefer_annular_revolve else "non_constant_axial_profile_require_revolve"
            resolved_profile_type = "tire_profile" if component_type == "tire" else "half_profile"
            strategy: Dict[str, Any] = {
                "primitive_class": "cylindrical",
                "construction_method": "revolve",
                "profile_type": resolved_profile_type,
                "selection_rationale": rationale,
            }
            return strategy

        if rotational_solid and not non_constant_axial:
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_requires_non_constant_axial_profile",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )
        if rotational_solid and not half_profile_ok and cross_section != "annular":
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_requires_half_profile",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )
        if touches_axis:
            self._log_fallback(
                component_id=component_id,
                param_name="construction_method",
                reason="revolve_profile_touches_axis",
                old_value="revolve",
                new_value="extrude",
                stage="strategy_selection",
            )

        rationale = "constant_axial_profile_prefer_extrude"
        profile_type = "annular" if cross_section == "annular" else "circle"
        strategy = {
            "primitive_class": "cylindrical",
            "construction_method": "extrude",
            "profile_type": profile_type,
            "selection_rationale": rationale,
        }
        return strategy
    
    def _select_prismatic_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for prismatic components.
        
        Always extrude for prismatic solids.
        """
        rationale = "standard_prismatic_part"
        strategy: Dict[str, Any] = {
            "primitive_class": "prismatic",
            "construction_method": "extrude",
            "profile_type": self._profile_type_from_shape(shape, "prismatic"),
            "selection_rationale": rationale
        }
        return strategy
    
    def _select_radial_plate_strategy(
        self,
        component_id: str,
        shape: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select strategy for radial plate components.
        
        Radial plates use extrude; detailed profile binding is handled in Agent3b.
        """
        profile_type = self._profile_type_from_shape(shape, "radial_plate")

        strategy: Dict[str, Any] = {
            "primitive_class": "plate",
            "construction_method": "extrude",
            "profile_type": profile_type,
            "selection_rationale": "plate_profile_from_semantics"
        }
        return strategy
