from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping

_ALLOWED_PRIMARY_METHODS = {"EXTRUDE", "REVOLVE", "LOFT", "SWEEP"}

_PATTERN_TO_PRIMARY_METHOD = {
    "ROTATIONAL_REVOLVE": "REVOLVE",
    "AXIAL_EXTRUSION": "EXTRUDE",
    "PLANAR_PLATE_EXTRUSION": "EXTRUDE",
    "PROFILE_EXTRUSION": "EXTRUDE",
    "RADIAL_PLATE_EXTRUSION": "EXTRUDE",
}

_REVOLVE_ONLY_KEYS = {
    "axis",
    "revolve_axis",
    "revolve_angle",
    "revolve_angle_rad",
    "angle_rad",
}

_EXTRUDE_ONLY_KEYS = {
    "direction",
    "distance",
    "extrude_distance",
}

_HOLE_NORMAL_MODES = {"FACE_NORMAL", "AXIS_INTERFACE", "WORLD_AXIS", "COMPONENT_AXIS"}
_HOLE_SIDE_HINTS = {"MIN", "MAX", "AUTO"}


def _is_hole_like_feature_type(feature_type: str) -> bool:
    ft = feature_type.lower()
    if "hole" in ft:
        return True
    return ft in {
        "bolt_circle_pattern",
        "counterbore",
        "countersink",
        "shaft_bore",
        "bearing_seat",
        "standoff_bore",
        "press_fit_zone",
        "retainer_groove",
        "seal_groove",
        "split_clamp_bore",
        "nut_seat",
    }


def _add_violation(
    violations: List[Dict[str, Any]],
    *,
    component_id: str,
    path: str,
    rule: str,
    message: str,
    details: Dict[str, Any] | None = None,
) -> None:
    payload: Dict[str, Any] = {
        "component_id": component_id,
        "path": path,
        "rule": rule,
        "message": message,
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    violations.append(payload)


def validate_shape_realization_contract(shape: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate shape realization contract for single primary modeling method per component."""
    violations: List[Dict[str, Any]] = []

    # Optional index: (component_id, interface_name) -> geometry_type
    interface_geom_type_index: Dict[tuple[str, str], str] = {}
    interface_manifest = shape.get("interface_manifest")
    if isinstance(interface_manifest, Mapping):
        comps = interface_manifest.get("components")
        if isinstance(comps, list):
            for comp in comps:
                if not isinstance(comp, Mapping):
                    continue
                cid = comp.get("component_id")
                if not isinstance(cid, str) or not cid:
                    continue
                ifaces = comp.get("interfaces")
                if not isinstance(ifaces, list):
                    continue
                for iface in ifaces:
                    if not isinstance(iface, Mapping):
                        continue
                    name = iface.get("interface_name")
                    if not isinstance(name, str) or not name:
                        continue
                    recipe = iface.get("recipe")
                    geom_type = None
                    if isinstance(recipe, Mapping) and isinstance(recipe.get("geometry_type"), str):
                        geom_type = recipe.get("geometry_type")
                    elif isinstance(iface.get("geometry_type"), str):
                        geom_type = iface.get("geometry_type")
                    if isinstance(geom_type, str) and geom_type:
                        interface_geom_type_index[(cid, name)] = geom_type

    realizations = shape.get("component_realizations")
    uses_parts_contract = False
    if not isinstance(realizations, list):
        parts = shape.get("parts")
        if isinstance(parts, list):
            uses_parts_contract = True
            converted: List[Dict[str, Any]] = []
            for idx, part in enumerate(parts):
                if not isinstance(part, Mapping):
                    continue
                component_id = part.get("component_id") if isinstance(part.get("component_id"), str) else f"<index:{idx}>"
                primary_method = part.get("primary_method")
                strategy = part.get("modeling_strategy")
                strategy_obj = dict(strategy) if isinstance(strategy, Mapping) else {}
                strategy_primary = strategy_obj.get("primary_method") if isinstance(strategy_obj.get("primary_method"), str) else None
                if isinstance(primary_method, str) and primary_method and not isinstance(strategy_primary, str):
                    strategy_obj["primary_method"] = primary_method
                converted.append(
                    {
                        "component_id": component_id,
                        "modeling_strategy": strategy_obj,
                        "part_primary_method": primary_method,
                        "strategy_primary_method": strategy_primary,
                        "features": part.get("features"),
                        "coordinate_frame": part.get("coordinate_frame"),
                    }
                )
            realizations = converted

    if not isinstance(realizations, list):
        return {
            "metadata": {
                "schema_version": "1.0",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "validator": "validate_shape_realization_contract",
            },
            "summary": {
                "components_checked": 0,
                "violations_count": 1,
                "conflicted_components": [],
            },
            "violations": [
                {
                    "component_id": "<shape_realization>",
                    "path": "parts|component_realizations",
                    "rule": "parts_or_component_realizations_list_required",
                    "message": "shape_realization.parts or shape_realization.component_realizations must be a list",
                }
            ],
        }

    components_checked = 0
    conflicted_components: set[str] = set()

    for idx, item in enumerate(realizations):
        if not isinstance(item, Mapping):
            continue
        component_id = item.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            component_id = f"<index:{idx}>"
        components_checked += 1

        if uses_parts_contract:
            part_primary = item.get("part_primary_method")
            strategy_primary = item.get("strategy_primary_method")
            if isinstance(part_primary, str) and part_primary.strip() and isinstance(strategy_primary, str) and strategy_primary.strip():
                if part_primary.strip().upper() != strategy_primary.strip().upper():
                    _add_violation(
                        violations,
                        component_id=component_id,
                        path=f"parts[{idx}].primary_method",
                        rule="primary_method_conflict",
                        message="parts[].primary_method conflicts with modeling_strategy.primary_method",
                        details={
                            "part_primary_method": part_primary,
                            "strategy_primary_method": strategy_primary,
                        },
                    )
                    conflicted_components.add(component_id)

            features = item.get("features")
            if not isinstance(features, list):
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=f"parts[{idx}].features",
                    rule="features_required",
                    message="parts[].features must be a list",
                )
                conflicted_components.add(component_id)
            else:
                # Enforce anchored hole contract: every hole-like feature must include
                # anchor.{face_interface_id, normal_hint.mode, side_hint}
                hole_intent_index: Dict[str, List[Dict[str, Any]]] = {}
                for f_idx, feat in enumerate(features):
                    if not isinstance(feat, Mapping):
                        continue
                    ftype = feat.get("feature_type")
                    if not (isinstance(ftype, str) and _is_hole_like_feature_type(ftype)):
                        continue
                    anchor = feat.get("anchor")
                    if not isinstance(anchor, Mapping):
                        _add_violation(
                            violations,
                            component_id=component_id,
                            path=f"parts[{idx}].features[{f_idx}].anchor",
                            rule="hole_anchor_required",
                            message="hole-like feature must include anchor with face_interface_id + normal_hint.mode + side_hint",
                            details={"feature_id": feat.get("feature_id")},
                        )
                        conflicted_components.add(component_id)
                        continue

                    face_iface = anchor.get("face_interface_id")
                    if not isinstance(face_iface, str) or not face_iface.strip():
                        _add_violation(
                            violations,
                            component_id=component_id,
                            path=f"parts[{idx}].features[{f_idx}].anchor.face_interface_id",
                            rule="hole_anchor_face_interface_required",
                            message="hole.anchor.face_interface_id must be a non-empty string",
                            details={"feature_id": feat.get("feature_id")},
                        )
                        conflicted_components.add(component_id)
                    else:
                        # HOLE_SIMPLE contract: anchored face must be planar.
                        # If a hole is anchored to a cylindrical interface (e.g., radial_outer_face),
                        # Fusion will often throw InternalValidationError: logicalSelection.
                        iface_geom = interface_geom_type_index.get((component_id, face_iface.strip()))
                        if isinstance(iface_geom, str) and iface_geom and iface_geom != "planar":
                            _add_violation(
                                violations,
                                component_id=component_id,
                                path=f"parts[{idx}].features[{f_idx}].anchor.face_interface_id",
                                rule="hole_anchor_requires_planar_face",
                                message="hole-like feature anchor.face_interface_id must resolve to a planar face interface",
                                details={
                                    "feature_id": feat.get("feature_id"),
                                    "interface_name": face_iface.strip(),
                                    "resolved_geometry_type": iface_geom,
                                },
                            )
                            conflicted_components.add(component_id)

                    normal_hint = anchor.get("normal_hint")
                    if not isinstance(normal_hint, Mapping):
                        _add_violation(
                            violations,
                            component_id=component_id,
                            path=f"parts[{idx}].features[{f_idx}].anchor.normal_hint",
                            rule="hole_anchor_normal_hint_required",
                            message="hole.anchor.normal_hint must be an object with mode",
                            details={"feature_id": feat.get("feature_id")},
                        )
                        conflicted_components.add(component_id)
                    else:
                        mode = normal_hint.get("mode")
                        if not isinstance(mode, str) or mode not in _HOLE_NORMAL_MODES:
                            _add_violation(
                                violations,
                                component_id=component_id,
                                path=f"parts[{idx}].features[{f_idx}].anchor.normal_hint.mode",
                                rule="hole_anchor_normal_mode_enum",
                                message=f"hole.anchor.normal_hint.mode must be one of: {sorted(_HOLE_NORMAL_MODES)}",
                                details={"feature_id": feat.get("feature_id"), "value": mode},
                            )
                            conflicted_components.add(component_id)

                    side_hint = anchor.get("side_hint")
                    if not isinstance(side_hint, str) or side_hint not in _HOLE_SIDE_HINTS:
                        _add_violation(
                            violations,
                            component_id=component_id,
                            path=f"parts[{idx}].features[{f_idx}].anchor.side_hint",
                            rule="hole_anchor_side_hint_enum",
                            message=f"hole.anchor.side_hint must be one of: {sorted(_HOLE_SIDE_HINTS)}",
                            details={"feature_id": feat.get("feature_id"), "value": side_hint},
                        )
                        conflicted_components.add(component_id)

                    geometry_parameters = feat.get("geometry_parameters")
                    geometry_parameters_map = geometry_parameters if isinstance(geometry_parameters, Mapping) else {}
                    hole_intent_id = geometry_parameters_map.get("hole_intent_id")
                    if isinstance(hole_intent_id, str) and hole_intent_id.strip():
                        hole_type_raw = geometry_parameters_map.get("hole_type")
                        if not isinstance(hole_type_raw, str) or not hole_type_raw.strip():
                            hole_type_raw = ftype
                        hole_type = hole_type_raw.strip().lower() if isinstance(hole_type_raw, str) else str(ftype).lower()
                        diameter = (
                            geometry_parameters_map.get("diameter")
                            or geometry_parameters_map.get("hole_diameter")
                            or geometry_parameters_map.get("bore_diameter")
                        )
                        hole_intent_index.setdefault(hole_intent_id.strip(), []).append(
                            {
                                "feature_index": f_idx,
                                "feature_id": feat.get("feature_id"),
                                "feature_type": ftype,
                                "hole_type": hole_type,
                                "diameter": diameter,
                            }
                        )

                for hole_intent_id, hole_features in hole_intent_index.items():
                    if len(hole_features) <= 1:
                        continue

                    _add_violation(
                        violations,
                        component_id=component_id,
                        path=f"parts[{idx}].features",
                        rule="hole_intent_multiple_features_fatal",
                        message="FATAL: one component cannot realize the same hole_intent_id with multiple hole-like features",
                        details={
                            "hole_intent_id": hole_intent_id,
                            "count": len(hole_features),
                            "features": hole_features,
                        },
                    )
                    conflicted_components.add(component_id)

                    hole_types = {str(item.get("hole_type") or "").lower() for item in hole_features}
                    if "threaded_hole" in hole_types and "clearance_hole" in hole_types:
                        _add_violation(
                            violations,
                            component_id=component_id,
                            path=f"parts[{idx}].features",
                            rule="hole_intent_threaded_clearance_conflict_fatal",
                            message="FATAL: threaded_hole and clearance_hole cannot coexist for same hole_intent_id in one component",
                            details={
                                "hole_intent_id": hole_intent_id,
                                "features": hole_features,
                            },
                        )
                        conflicted_components.add(component_id)
            coordinate_frame = item.get("coordinate_frame")
            if not isinstance(coordinate_frame, Mapping):
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=f"parts[{idx}].coordinate_frame",
                    rule="coordinate_frame_required",
                    message="parts[].coordinate_frame must be an object",
                )
                conflicted_components.add(component_id)

        strategy = item.get("modeling_strategy")
        path_prefix = f"component_realizations[{idx}].modeling_strategy"
        if not isinstance(strategy, Mapping):
            _add_violation(
                violations,
                component_id=component_id,
                path=path_prefix,
                rule="modeling_strategy_required",
                message="modeling_strategy must be an object",
            )
            conflicted_components.add(component_id)
            continue

        primary_raw = strategy.get("primary_method")
        construction_raw = strategy.get("construction_method")

        if not isinstance(primary_raw, str) or not primary_raw.strip():
            _add_violation(
                violations,
                component_id=component_id,
                path=f"{path_prefix}.primary_method",
                rule="primary_method_required",
                message="modeling_strategy.primary_method is required",
            )
            conflicted_components.add(component_id)
            primary_method = None
        else:
            primary_method = primary_raw.strip().upper()
            if primary_method not in _ALLOWED_PRIMARY_METHODS:
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=f"{path_prefix}.primary_method",
                    rule="primary_method_enum",
                    message="primary_method must be one of EXTRUDE|REVOLVE|LOFT|SWEEP",
                    details={"value": primary_raw},
                )
                conflicted_components.add(component_id)

        if isinstance(construction_raw, str) and construction_raw.strip() and primary_method:
            construction_method = construction_raw.strip().upper()
            if construction_method != primary_method:
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=f"{path_prefix}.construction_method",
                    rule="construction_primary_mismatch",
                    message="construction_method conflicts with primary_method",
                    details={
                        "construction_method": construction_raw,
                        "primary_method": primary_method,
                    },
                )
                conflicted_components.add(component_id)

        if primary_method == "REVOLVE":
            illegal = sorted(k for k in _EXTRUDE_ONLY_KEYS if k in strategy)
            if illegal:
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=path_prefix,
                    rule="revolve_with_extrude_fields",
                    message="Extrude-only fields are not allowed when primary_method=REVOLVE",
                    details={"fields": illegal},
                )
                conflicted_components.add(component_id)

        if primary_method == "EXTRUDE":
            illegal = sorted(k for k in _REVOLVE_ONLY_KEYS if k in strategy)
            if illegal:
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=path_prefix,
                    rule="extrude_with_revolve_fields",
                    message="Revolve-only fields are not allowed when primary_method=EXTRUDE",
                    details={"fields": illegal},
                )
                conflicted_components.add(component_id)

        contract_pattern = item.get("contract_pattern_used")
        if isinstance(contract_pattern, str) and primary_method:
            expected = _PATTERN_TO_PRIMARY_METHOD.get(contract_pattern)
            if expected and expected != primary_method:
                _add_violation(
                    violations,
                    component_id=component_id,
                    path=f"component_realizations[{idx}].contract_pattern_used",
                    rule="contract_pattern_primary_mismatch",
                    message="contract_pattern_used conflicts with modeling_strategy.primary_method",
                    details={
                        "contract_pattern_used": contract_pattern,
                        "expected_primary_method": expected,
                        "actual_primary_method": primary_method,
                    },
                )
                conflicted_components.add(component_id)

    return {
        "metadata": {
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "validator": "validate_shape_realization_contract",
        },
        "summary": {
            "components_checked": components_checked,
            "violations_count": len(violations),
            "conflicted_components": sorted(conflicted_components),
        },
        "violations": violations,
    }
