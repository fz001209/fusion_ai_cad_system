"""Agent3b feature patch compilation for holes, threads, seats, and connection-derived cuts."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from agents.Agent3b_compile_geometry_plan.standard_part_compiler import inject_standard_parts_steps
from agents.common_utils import read_json as _read_json, write_json as _write_json
from validation.validate_shape_realization import validate_shape_realization_contract

from .common import *
from .shape_inputs import *

def _circle_feature_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float | None,
    face_interface_id: str,
    face_recipe: Mapping[str, Any],
    side_hint: str | None,
    allowed: Mapping[str, Any],
    index: int,
    center_mm: Mapping[str, Any] | None = None,
    thread_spec: Mapping[str, Any] | None = None,
    face_geometry_type: str | None = None,
) -> List[Dict[str, Any]]:
    """Create a HOLE_SIMPLE feature anchored to a resolved interface."""
    _require_function(allowed, "ACTIVATE_COMPONENT")
    _require_function(allowed, "RESOLVE_INTERFACE")
    _require_function(allowed, "HOLE_SIMPLE")

    inferred_geometry_type = face_geometry_type
    if not isinstance(inferred_geometry_type, str) or not inferred_geometry_type:
        recipe_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None
        inferred_geometry_type = recipe_geometry_type
    planar_anchor = (
        isinstance(inferred_geometry_type, str)
        and inferred_geometry_type.lower() == "planar"
    )

    normalized_thread: Dict[str, Any] | None = None
    if isinstance(thread_spec, Mapping) and thread_spec:
        normalized_thread = _normalize_thread_spec(thread_spec)

    prefix = _safe_id(component_id)
    face_var = f"{prefix}_{feature_key}_face_{index}"
    face_kind_var = f"{prefix}_{feature_key}_face_kind_{index}"
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    hole_feature_var = f"{prefix}_{feature_key}_feature_{index}"
    hole_cyl_faces_var = f"{prefix}_{feature_key}_hole_cyl_faces_{index}"

    steps: List[Dict[str, Any]] = []
    
    # 濠电姷鏁告慨鐑姐€傛禒瀣；闁规儳顕粻楣冩煠閼圭増纭鹃柛姘愁潐缁绘盯鐓鐐茬ギ閻庢鍠曠划娆忕暦閸洖鐓涢柛鎰典簽閸樻垵鈹?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_activate", index),
            "function": "ACTIVATE_COMPONENT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
        }
    )
    
    # Resolve anchored face via interface recipe (deterministic, contract-driven)
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_resolve_face", index),
            "function": "RESOLVE_INTERFACE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "body_id": f"${{{stable_body_var}}}",
                "interface_name": face_interface_id,
                "recipe": dict(face_recipe),
            },
            "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_activate", index)],
            "metadata": {
                "component_id": component_id,
                "interface_name": face_interface_id,
                "expected_entity_kind": "face",
            },
        }
    )

    # Hole API does not require an explicit sketch center when resolving from a face.
    hole_inputs: Dict[str, Any] = {
        "component_id": _component_var_ref(component_id),
        "diameter_mm": float(diameter),
        "name": f"{component_id}_{feature_key}_{index}",
    }
    hole_inputs["face_id"] = f"${{{face_var}}}"
    if isinstance(center_mm, Mapping) and ("x" in center_mm or "y" in center_mm or "z" in center_mm):
        hole_inputs["center_mm"] = {
            "x": float(center_mm.get("x", 0.0)),
            "y": float(center_mm.get("y", 0.0)),
            "z": float(center_mm.get("z", 0.0)),
        }
    else:
        hole_inputs["center_mm"] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    if depth is None:
        # 闂備浇宕垫慨鐢稿礉閿曞倸鍨傞柟鎯版閻撴ɑ绻涢幋鐐茬劰闁?
        if side_hint == "MAX":
            hole_inputs["extent"] = "through_negative"
        elif side_hint == "MIN":
            hole_inputs["extent"] = "through_positive"
        else:
            hole_inputs["extent"] = "through_positive"
    else:
        # 闂傚倷绀佸﹢閬嶁€﹂崼婢濇椽濡舵径瀣患闂佽鍨奸悘鏃€鎯旈妸銉ь攨闂佺粯鍔曞Ο濠囧船濞差亝鈷戞慨鐟版搐婵″ジ鎮楀鐓庡⒋闁?        hole_inputs["extent"] = "distance"
        hole_inputs["depth_mm"] = float(depth)

    if normalized_thread is not None:
        hole_inputs["thread_spec"] = {
            "is_internal": bool(normalized_thread.get("is_internal", True)),
            "thread_type": normalized_thread["thread_type"],
            "thread_designation": normalized_thread["thread_designation"],
            "thread_class": normalized_thread["thread_class"],
        }
    
    hole_step_id = _make_step_id(prefix, f"{feature_key}_hole", index)
    hole_step: Dict[str, Any] = {
        "id": hole_step_id,
        "function": "HOLE_SIMPLE",
        "inputs": hole_inputs,
        "depends_on": [
            _make_step_id(
                prefix,
                f"{feature_key}_resolve_face",
                index,
            )
        ],
        "capture": {"vars": {hole_feature_var: "feature_id"}},
        "metadata": {
            "anchor": {
                "face_interface_id": face_interface_id,
                "side_hint": side_hint,
                "face_geometry_type": inferred_geometry_type,
            },
            "resolved_face_kind_var": face_kind_var,
        },
    }
    hole_step["capture"] = {
        "vars": {
            hole_feature_var: "feature_id",
            hole_cyl_faces_var: "cyl_face_ids",
        }
    }
    steps.append(hole_step)

    # Every hole modifies BRep topology.  Always emit refresh_body so
    # downstream re_resolve steps reference a current body_id.
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)
    steps.append(
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [hole_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_hole",
            },
        }
    )

    return steps


def _normalize_thread_spec(thread_spec: Mapping[str, Any]) -> Dict[str, Any]:
    thread_type = thread_spec.get("thread_type")
    thread_designation = thread_spec.get("thread_designation")
    thread_class = thread_spec.get("thread_class")

    if not (isinstance(thread_type, str) and thread_type.strip()):
        raise ValueError("thread_spec.thread_type must be a non-empty string")
    if not (isinstance(thread_designation, str) and thread_designation.strip()):
        raise ValueError("thread_spec.thread_designation must be a non-empty string")
    if not (isinstance(thread_class, str) and thread_class.strip()):
        raise ValueError("thread_spec.thread_class must be a non-empty string")

    normalized: Dict[str, Any] = {
        "thread_type": thread_type,
        "thread_designation": thread_designation,
        "thread_class": thread_class,
        "is_internal": bool(thread_spec.get("is_internal", True)),
        "is_modeled": bool(thread_spec.get("is_modeled", False)),
        "is_full_length": bool(thread_spec.get("is_full_length", True)),
    }

    if "thread_length_mm" in thread_spec:
        raw_len = thread_spec.get("thread_length_mm")
        if raw_len is not None and not isinstance(raw_len, (int, float)):
            raise ValueError("thread_spec.thread_length_mm must be a number (mm)")
        normalized["thread_length_mm"] = raw_len
    if "radius_tol_mm" in thread_spec:
        raw_tol = thread_spec.get("radius_tol_mm")
        if raw_tol is not None and not isinstance(raw_tol, (int, float)):
            raise ValueError("thread_spec.radius_tol_mm must be a number (mm)")
        normalized["radius_tol_mm"] = raw_tol

    return normalized


def _compile_hole_simple_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float | None,
    side_hint: str | None,
    face_interface_id: str,
    face_geometry_type: str | None,
    resolved_face_var: str,
    resolved_face_kind_var: str,
    allowed: Mapping[str, Any],
    index: int,
    center_mm: Mapping[str, Any] | None,
    depends_on: List[str],
    hole_mode: str,
    cbore_diameter_mm: float | None = None,
    cbore_depth_mm: float | None = None,
    csink_diameter_mm: float | None = None,
    csink_angle_rad: float | None = None,
    capture_feature_var: str | None = None,
    pattern: Mapping[str, Any] | None = None,
    pattern_axis: str | None = None,
    thread_spec: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    prefix = _safe_id(component_id)
    steps: List[Dict[str, Any]] = []

    if depth is None:
        if side_hint == "MAX":
            extent = "through_negative"
        elif side_hint == "MIN":
            extent = "through_positive"
        else:
            extent = "through_positive"
        depth_mm = None
    else:
        extent = "distance"
        depth_mm = float(depth)

    center_payload = {
        "x": float((center_mm or {}).get("x", 0.0)),
        "y": float((center_mm or {}).get("y", 0.0)),
        "z": float((center_mm or {}).get("z", 0.0)),
    }

    hole_step_id = _make_step_id(prefix, f"{feature_key}_hole", index)
    hole_inputs: Dict[str, Any] = {
        "component_id": _component_var_ref(component_id),
        "face_id": f"${{{resolved_face_var}}}",
        "center_mm": center_payload,
        "name": f"{component_id}_{feature_key}_{index}",
    }

    hole_function = "HOLE_SIMPLE"
    if hole_mode == "counterbore" and isinstance(cbore_diameter_mm, (int, float)) and isinstance(cbore_depth_mm, (int, float)):
        _require_function(allowed, "HOLE_COUNTERBORE")
        hole_function = "HOLE_COUNTERBORE"
        hole_inputs["hole_diameter_mm"] = float(diameter)
        hole_inputs["cbore_diameter_mm"] = float(cbore_diameter_mm)
        hole_inputs["cbore_depth_mm"] = float(cbore_depth_mm)
    elif hole_mode == "countersink" and isinstance(csink_diameter_mm, (int, float)) and isinstance(csink_angle_rad, (int, float)):
        _require_function(allowed, "HOLE_COUNTERSINK")
        hole_function = "HOLE_COUNTERSINK"
        hole_inputs["hole_diameter_mm"] = float(diameter)
        hole_inputs["csink_diameter_mm"] = float(csink_diameter_mm)
        hole_inputs["csink_angle_rad"] = float(csink_angle_rad)
    else:
        _require_function(allowed, "HOLE_SIMPLE")
        hole_inputs["diameter_mm"] = float(diameter)

    normalized_thread: Dict[str, Any] | None = None
    if isinstance(thread_spec, Mapping) and thread_spec:
        normalized_thread = _normalize_thread_spec(thread_spec)

    hole_inputs["extent"] = extent
    if depth_mm is not None:
        hole_inputs["depth_mm"] = depth_mm
    if normalized_thread is not None:
        hole_inputs["thread_spec"] = {
            "is_internal": bool(normalized_thread.get("is_internal", True)),
            "thread_type": normalized_thread["thread_type"],
            "thread_designation": normalized_thread["thread_designation"],
            "thread_class": normalized_thread["thread_class"],
        }

    hole_step: Dict[str, Any] = {
        "id": hole_step_id,
        "function": hole_function,
        "inputs": hole_inputs,
        "depends_on": list(depends_on),
        "metadata": {
            "anchor": {
                "face_interface_id": face_interface_id,
                "side_hint": side_hint,
                "face_geometry_type": face_geometry_type,
            },
            "resolved_face_kind_var": resolved_face_kind_var,
        },
    }
    effective_capture_feature_var = (
        capture_feature_var
        if isinstance(capture_feature_var, str) and capture_feature_var
        else f"{prefix}_{feature_key}_feature_{index}"
    )
    hole_step["capture"] = {"vars": {effective_capture_feature_var: "feature_id"}}

    steps.append(hole_step)
    latest_hole_step_id = hole_step_id

    if isinstance(pattern, Mapping):
        pattern_type = str(pattern.get("type") or "").lower()
        if pattern_type == "circular":
            quantity = pattern.get("count")
            if isinstance(quantity, int) and quantity > 1:
                expand_instances = hole_function == "HOLE_SIMPLE" and normalized_thread is not None
                cx = float(center_payload.get("x", 0.0))
                cy = float(center_payload.get("y", 0.0))
                cz = float(center_payload.get("z", 0.0))
                start_angle = pattern.get("start_angle_rad")
                radius_mm = pattern.get("radius_mm")
                total_angle = pattern.get("total_angle_rad")

                if not isinstance(start_angle, (int, float)):
                    start_angle = math.atan2(cy, cx)
                if not isinstance(radius_mm, (int, float)):
                    radius_mm = math.hypot(cx, cy)
                if not isinstance(total_angle, (int, float)):
                    total_angle = 2.0 * math.pi

                total_angle_f = float(total_angle)
                if abs(total_angle_f - 2.0 * math.pi) < 1e-6:
                    step_angle = total_angle_f / float(quantity)
                else:
                    step_angle = total_angle_f / float(max(quantity - 1, 1))

                if expand_instances and float(radius_mm) > 1e-9:
                    for inst_idx in range(1, int(quantity)):
                        angle_i = float(start_angle) + step_angle * float(inst_idx)
                        center_i = {
                            "x": float(radius_mm) * math.cos(angle_i),
                            "y": float(radius_mm) * math.sin(angle_i),
                            "z": cz,
                        }
                        hole_inputs_i = dict(hole_inputs)
                        hole_inputs_i["center_mm"] = center_i
                        hole_inputs_i["name"] = f"{component_id}_{feature_key}_{index}_{inst_idx}"
                        step_id_i = _make_step_id(prefix, f"{feature_key}_hole_i{inst_idx}", index)
                        steps.append(
                            {
                                "id": step_id_i,
                                "function": hole_function,
                                "inputs": hole_inputs_i,
                                "depends_on": [latest_hole_step_id],
                                "metadata": {
                                    "anchor": {
                                        "face_interface_id": face_interface_id,
                                        "side_hint": side_hint,
                                        "face_geometry_type": face_geometry_type,
                                    },
                                    "resolved_face_kind_var": resolved_face_kind_var,
                                    "pattern_expanded": "circular",
                                    "pattern_index": inst_idx,
                                },
                            }
                        )
                        latest_hole_step_id = step_id_i
                else:
                    _require_function(allowed, "CIRCULAR_PATTERN_FEATURES")
                    pattern_step_inputs: Dict[str, Any] = {
                        "component_id": _component_var_ref(component_id),
                        "feature_ids": [f"${{{effective_capture_feature_var}}}"],
                        "axis": {"face_id": f"${{{resolved_face_var}}}", "axis_hint": pattern_axis or "Z"},
                        "quantity": int(quantity),
                    }
                    pattern_step_inputs["total_angle_rad"] = total_angle_f
                    pattern_step_inputs["is_symmetric"] = False
                    pattern_step_id = _make_step_id(prefix, f"{feature_key}_pattern", index)
                    steps.append(
                        {
                            "id": pattern_step_id,
                            "function": "CIRCULAR_PATTERN_FEATURES",
                            "inputs": pattern_step_inputs,
                            "depends_on": [hole_step_id],
                        }
                    )
                    latest_hole_step_id = pattern_step_id
        elif pattern_type == "rectangular":
            quantity_one = pattern.get("count_x")
            distance_one_mm = pattern.get("spacing_x_mm")
            direction_one = pattern.get("direction_one")
            if (
                isinstance(quantity_one, int)
                and quantity_one > 1
                and isinstance(distance_one_mm, (int, float))
                and isinstance(direction_one, Mapping)
            ):
                _require_function(allowed, "RECTANGULAR_PATTERN_FEATURES")
                pattern_inputs: Dict[str, Any] = {
                    "component_id": _component_var_ref(component_id),
                    "feature_ids": [f"${{{effective_capture_feature_var}}}"],
                    "direction_one": dict(direction_one),
                    "quantity_one": int(quantity_one),
                    "distance_one_mm": float(distance_one_mm),
                    "pattern_distance_type": "spacing",
                }
                if isinstance(pattern.get("count_y"), int) and pattern.get("count_y") > 1:
                    direction_two = pattern.get("direction_two")
                    distance_two_mm = pattern.get("spacing_y_mm")
                    if isinstance(direction_two, Mapping) and isinstance(distance_two_mm, (int, float)):
                        pattern_inputs["direction_two"] = dict(direction_two)
                        pattern_inputs["quantity_two"] = int(pattern.get("count_y"))
                        pattern_inputs["distance_two_mm"] = float(distance_two_mm)
                steps.append(
                    {
                        "id": _make_step_id(prefix, f"{feature_key}_pattern", index),
                        "function": "RECTANGULAR_PATTERN_FEATURES",
                        "inputs": pattern_inputs,
                        "depends_on": [hole_step_id],
                    }
                )
                latest_hole_step_id = _make_step_id(prefix, f"{feature_key}_pattern", index)

    # Every hole modifies BRep topology.  Always emit refresh_body so
    # downstream re_resolve steps reference a current body_id, preventing
    # stale proxy issues in the Fusion API.
    _require_function(allowed, "GET_SINGLE_BODY_ID")
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)
    steps.append(
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [latest_hole_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_hole",
            },
        }
    )

    return steps


def _rectangle_feature_steps(
    *,
    component_id: str,
    feature_key: str,
    width: float,
    height: float,
    depth: float | None,
    allowed: Mapping[str, Any],
    index: int,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "ACTIVATE_COMPONENT")
    _require_function(allowed, "SELECT_LARGEST_PLANAR_FACE")
    _require_function(allowed, "CREATE_SKETCH_ON_FACE")
    _require_function(allowed, "SKETCH_RECTANGLE")

    if depth is None:
        _require_function(allowed, "EXTRUDE_THROUGH_ALL")
    else:
        _require_function(allowed, "EXTRUDE_CUT")

    prefix = _safe_id(component_id)
    sketch_id_var = f"{prefix}_{feature_key}_sketch_{index}"
    face_var = f"{prefix}_{feature_key}_face_{index}"
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")

    steps: List[Dict[str, Any]] = []
    
    # 濠电姷鏁告慨鐑姐€傛禒瀣；闁规儳顕粻楣冩煠閼圭増纭鹃柛姘愁潐缁绘盯鐓鐐茬ギ閻庢鍠曠划娆忕暦閸洖鐓涢柛鎰典簽閸樻垵鈹戦悙宸殶濠殿噣娼ч敃銏㈡喆閸曨収娲搁梺鍦劋濮婂綊宕楀鍕╀簻闁哄啫娲ら崥鍦磼閻樿京鐭欓柡灞剧☉椤繈顢楁担鐟伴棷闂備焦鐪归崹褰掆€﹂悜鐣屽祦婵炲棗娴氶崥瀣煕閺囥劌骞橀柍缁樻礋濮婃椽妫冮埡鍕槹闂佸憡鏌ㄧ粔褰掋€佸Δ鈧…銊╁川椤旂厧骞戞俊鐐€栧濠氬磻閹剧粯鍋╅柣顏冩姉ntext婵犵數鍋為崹鍫曞箹閳哄懎鍌ㄩ柤鎭掑劜濞呯娀鏌ｉ敐鍛拱闁?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_activate", index),
            "function": "ACTIVATE_COMPONENT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
        }
    )
    
    # 闂傚倸鍊风欢锟犲磻閸曨垁鍥箥椤旂懓浜炬慨妯稿劚婵倻鈧鍠氶弫濠氬春閳ь剚銇勯幒宥囶槮缂佸墎鍋熼幉姝岀疀閹绢垱鐏侀梺纭呮彧婵″洤鐣垫笟鈧弻鐔煎箚閺夊晝鎾翠繆濡炵厧濮傛慨濠傤煼瀹曞ジ顢曢敐鍥╃崸缂傚倷娴囨ご鎼佹偡閳哄懎钃熼柛娑卞弾濞尖晜銇勯幒鎴濃偓鎼佹偂閹达附鈷戦柛婵嗗椤忔挳鏌涢妸銉у煟濠碘€崇摠缁绘繈宕堕…鎴烆棃闂備線娼х换鍡涘焵椤掆偓绾绢厽绂掗幇鐗堢厵闁绘挸娴烽幗鐘崇箾閼碱剙鏋庢い顓炴处鐎佃偐鈧稒蓱濞?
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_select_face", index),
            "function": "SELECT_LARGEST_PLANAR_FACE",
            "inputs": {
                "body_id": f"${{{stable_body_var}}}",
            },
            "capture": {"vars": {face_var: "face_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_activate", index)],
        }
    )
    
    # 闂傚倷绶氬鑽ゆ嫻閻旂厧绀夐柟杈剧畱閻掑灚銇勯幒鍡椾壕濡炪倧瀵岄崹鍫曞箖閻愵兙鍋呴柛鎰ㄦ櫅閸擃參姊洪崨濠冨闁搞劌宕々濂稿Ω閵夈垺顫嶉梺鐟板⒔椤掓彃顔忛妷鈺傜厱闁靛鍎遍懜瑙勩亜閺囩喓鎳呴柤楦块哺娣囧﹪宕￠幁顡﹉
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_sketch", index),
            "function": "CREATE_SKETCH_ON_FACE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "face_id": f"${{{face_var}}}",
                "name": f"{component_id}_{feature_key}_{index}_sketch",
            },
            "capture": {"vars": {sketch_id_var: "sketch_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_select_face", index)],
        }
    )
    steps.append(
        {
            "id": _make_step_id(prefix, f"{feature_key}_profile", index),
            "function": "SKETCH_RECTANGLE",
            "inputs": {
                "sketch_id": f"${{{sketch_id_var}}}",
                "center": _feature_center(),
                "width": float(width),
                "height": float(height),
            },
            "capture": {"vars": {f"{prefix}_{feature_key}_profile_{index}": "profile_id"}},
            "depends_on": [_make_step_id(prefix, f"{feature_key}_sketch", index)],
        }
    )
    if depth is None:
        steps.append(
            {
                "id": _make_step_id(prefix, f"{feature_key}_cut", index),
                "function": "EXTRUDE_THROUGH_ALL",
                "inputs": {
                    "component_id": _component_var_ref(component_id),
                    "profile_id": f"${{{prefix}_{feature_key}_profile_{index}}}",
                    "operation": "cut",
                    "body_id": f"${{{stable_body_var}}}",
                },
                "depends_on": [_make_step_id(prefix, f"{feature_key}_profile", index)],
            }
        )
    else:
        steps.append(
            {
                "id": _make_step_id(prefix, f"{feature_key}_cut", index),
                "function": "EXTRUDE_CUT",
                "inputs": {
                    "component_id": _component_var_ref(component_id),
                    "profile_id": f"${{{prefix}_{feature_key}_profile_{index}}}",
                    "distance": float(depth),
                    "body_id": f"${{{stable_body_var}}}",
                },
                "depends_on": [_make_step_id(prefix, f"{feature_key}_profile", index)],
            }
        )

    return steps


def _collect_fastener_intents(feature_plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    placements = feature_plan.get("connection_placements")
    if not isinstance(placements, list):
        return []

    suppressed_mechanisms = {
        "bonded_tread",
        "bonded_mount",
        "press_fit",
        "companion_rotation_relation",
        "semantic_conflict_direct_rotor_mount",
    }

    intents: List[Dict[str, Any]] = []
    for pidx, placement in enumerate(placements):
        if not isinstance(placement, Mapping):
            continue
        placement_flags = placement.get("flags") if isinstance(placement.get("flags"), Mapping) else {}
        mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
        if bool(placement_flags.get("suppress_hole_generation")) or mechanism_name in suppressed_mechanisms:
            continue
        fastener_spec = placement.get("fastener_spec")
        if not isinstance(fastener_spec, Mapping) or not fastener_spec:
            continue

        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}

        hole_anchors: List[Dict[str, Any]] = []
        target_ids: set[str] = set()
        derived = placement.get("derived_changes") if isinstance(placement.get("derived_changes"), list) else []
        for cidx, change in enumerate(derived):
            if not isinstance(change, Mapping):
                continue
            feature = str(change.get("feature") or "").lower()
            if feature not in {"hole", "bolt_circle_pattern", "counterbore", "countersink", "clearance_hole", "threaded_hole"}:
                continue
            target_component_id = change.get("target_component_id")
            if isinstance(target_component_id, str) and target_component_id:
                target_ids.add(target_component_id)

            hole_anchors.append(
                {
                    "hole_ref": f"fastener_hole_{pidx}_{cidx}",
                    "target_component_id": target_component_id,
                    "interface_name": interface_ref.get("name"),
                    "interface_component_id": interface_ref.get("component_id"),
                    "anchor": dict(change.get("anchor")) if isinstance(change.get("anchor"), Mapping) else None,
                    "diameter_mm": (
                        float(change.get("diameter"))
                        if isinstance(change.get("diameter"), (int, float))
                        else (
                            float(change.get("hole_diameter"))
                            if isinstance(change.get("hole_diameter"), (int, float))
                            else (
                                float(change.get("bore_diameter"))
                                if isinstance(change.get("bore_diameter"), (int, float))
                                else None
                            )
                        )
                    ),
                    "feature": feature,
                }
            )

        if not hole_anchors:
            continue

        intents.append(
            {
                "intent_id": f"fastener_intent_{pidx}",
                "connection_id": placement.get("connection_id"),
                "fastener_spec": dict(fastener_spec),
                "target_component_ids": sorted(target_ids),
                "hole_anchors": hole_anchors,
                "rationale": "Standard part insertion and assembly sequencing are deferred to Agent5",
            }
        )

    return intents


def _re_resolve_group_face(
    *,
    group_ctx: Dict[str, Any],
    target_id: str,
    feature_group_id: str,
    step_index: int,
    steps: List[Dict[str, Any]],
    face_interface_id: str,
    usage: str | None,
) -> Tuple[str, str, List[str], int]:
    """Return *(face_var, face_kind_var, depends, step_index)* for the next
    hole in a grouped-hole sequence.

    When the group already contains at least one hole (`hole_count > 0`) a
    fresh ``RESOLVE_INTERFACE`` step is appended to *steps* so that the face
    reference is re-resolved after the geometry was modified by the previous
    hole.  Otherwise the original face variables from *group_ctx* are reused
    unchanged.
    """
    face_var = str(group_ctx["face_var"])
    face_kind_var = str(group_ctx["face_kind_var"])
    depends: List[str] = [str(group_ctx["resolve_step_id"])]

    if group_ctx["hole_count"] > 0:
        _grp_prefix = _safe_id(target_id)
        _grp_token = _safe_id(feature_group_id)
        _re_idx = step_index
        step_index += 1
        _re_resolve_id = _make_step_id(_grp_prefix, f"{_grp_token}_re_resolve_face", _re_idx)
        face_var = f"{_grp_prefix}_{_grp_token}_face_{_re_idx}"
        face_kind_var = f"{_grp_prefix}_{_grp_token}_face_kind_{_re_idx}"
        _stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")

        steps.append(
            {
                "id": _re_resolve_id,
                "function": "RESOLVE_INTERFACE",
                "inputs": {
                    "component_id": _component_var_ref(target_id),
                    "body_id": f"${{{_stable_body_var}}}",
                    "interface_name": face_interface_id,
                    "recipe": dict(group_ctx["_resolved_recipe"]),
                },
                "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
                "depends_on": [str(group_ctx["last_step_id"])],
                "metadata": {
                    "component_id": target_id,
                    "interface_name": face_interface_id,
                    "expected_entity_kind": "face",
                    "usage": usage,
                    "reason": "re_resolve_face_after_prior_hole",
                },
            }
        )
        depends = [_re_resolve_id]

    return face_var, face_kind_var, depends, step_index


def _infer_side_entry_slot_capture_mount(
    *,
    placement: Mapping[str, Any],
    change: Mapping[str, Any],
    target_strategy: Mapping[str, Any],
) -> bool:
    mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
    placement_geo = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
    support_topology = str(placement_geo.get("support_topology") or "").strip().lower()
    if mechanism_name == "axial_face_bolted_mount" and support_topology == "hub_radial_slot_mount":
        return True

    location_map = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
    location_interface_ref = location_map.get("interface_ref") if isinstance(location_map.get("interface_ref"), Mapping) else {}
    change_interface_ref = change.get("interface_ref") if isinstance(change.get("interface_ref"), Mapping) else {}
    anchor_map = change.get("anchor") if isinstance(change.get("anchor"), Mapping) else {}

    interface_names: set[str] = set()
    for raw_name in (
        location_interface_ref.get("name"),
        change_interface_ref.get("name"),
        anchor_map.get("face_interface_id"),
    ):
        if isinstance(raw_name, str) and raw_name.strip():
            interface_names.add(raw_name.strip().lower())

    if any(name.startswith("slot_mount_face") for name in interface_names):
        return True

    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    target_profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
    hub_slot_insert_depth = strategy_params.get("hub_slot_insert_depth")
    has_slot_insert_depth = isinstance(hub_slot_insert_depth, (int, float)) and float(hub_slot_insert_depth) > 0.0

    feature_context_tokens: set[str] = set()
    for raw_token in (
        placement.get("feature_group_id"),
        placement.get("connection_id"),
        change.get("feature_group_id"),
    ):
        if isinstance(raw_token, str) and raw_token.strip():
            feature_context_tokens.add(raw_token.strip().lower())

    if (
        "proximal_insert_face" in interface_names
        and target_profile_type == "yoke_profile"
        and (
            has_slot_insert_depth
            or any(token.startswith("central_hub_to_arm_") for token in feature_context_tokens)
        )
    ):
        return True

    return False



def _integrated_axisymmetric_bearing_seat_params(target_strategy: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    seat_diameter = strategy_params.get("opposed_bearing_seat_diameter")
    seat_depth = strategy_params.get("opposed_bearing_seat_depth")
    opposed_width = strategy_params.get("opposed_bearing_width")
    thickness = strategy_params.get("thickness")
    if not isinstance(seat_diameter, (int, float)) or float(seat_diameter) <= 0.0:
        return None
    if not isinstance(seat_depth, (int, float)) or float(seat_depth) <= 0.0:
        return None
    if not isinstance(opposed_width, (int, float)) or float(opposed_width) <= 0.0:
        return None
    if not isinstance(thickness, (int, float)) or float(thickness) <= 0.0:
        return None
    return {
        "seat_diameter": float(seat_diameter),
        "seat_depth": float(seat_depth),
        "opposed_width": float(opposed_width),
        "thickness": float(thickness),
    }


def _should_compile_axisymmetric_bearing_seat_cut(
    *,
    feature_key: str,
    target_strategy: Mapping[str, Any],
    face_interface_id: str | None,
    diameter: Any,
    depth: Any,
    centered: bool = False,
) -> bool:
    if feature_key != "bearing_seat":
        return False
    if _integrated_axisymmetric_bearing_seat_params(target_strategy) is not None:
        return False
    if not centered and (not isinstance(face_interface_id, str) or face_interface_id.lower() not in {"axial_end_face_min", "axial_end_face_max"}):
        return False
    if not isinstance(diameter, (int, float)) or float(diameter) <= 0.0:
        return False
    if not isinstance(depth, (int, float)) or float(depth) <= 0.0:
        return False

    primitive_class = str(target_strategy.get("primitive_class") or "").strip().lower()
    profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
    construction_method = str(target_strategy.get("construction_method") or target_strategy.get("primary_method") or "").strip().lower()
    if construction_method == "revolve":
        return True
    if profile_type == "half_profile" and _is_axisymmetric(primitive_class, profile_type):
        return True
    return False


def _compile_axisymmetric_bearing_seat_cut_steps(
    *,
    component_id: str,
    feature_key: str,
    diameter: float,
    depth: float,
    side_hint: str,
    face_interface_id: str,
    allowed: Mapping[str, Any],
    index: int,
    depends_on: List[str],
    target_strategy: Mapping[str, Any],
    centered: bool = False,
) -> List[Dict[str, Any]]:
    _require_function(allowed, "CREATE_OFFSET_CONSTRUCTION_PLANE")
    _require_function(allowed, "CREATE_SKETCH_ON_PLANE")
    _require_function(allowed, "SKETCH_CIRCLE")
    _require_function(allowed, "EXTRUDE_CUT")
    _require_function(allowed, "GET_SINGLE_BODY_ID")

    strategy_params = target_strategy.get("parameter_values") if isinstance(target_strategy.get("parameter_values"), Mapping) else {}
    thickness = _pick_param(strategy_params, "thickness", "width", "height", "length")
    thickness = _ensure_value(thickness, component_id=component_id, name="thickness")

    normalized_side = side_hint.strip().upper()
    plane_offset = 0.5 * float(thickness)
    cut_direction = "negative"
    seat_compile_mode = "axisymmetric_blind_cut"
    if centered:
        normalized_side = "CENTER"
        plane_offset = -0.5 * float(depth)
        cut_direction = "positive"
        seat_compile_mode = "axisymmetric_centered_cut"
    elif normalized_side == "MIN":
        plane_offset = -plane_offset
        cut_direction = "positive"

    prefix = _safe_id(component_id)
    stable_body_var = _make_capture_var(_component_prefix(component_id), "body_id")
    plane_var = f"{prefix}_{feature_key}_plane_{index}"
    sketch_var = f"{prefix}_{feature_key}_sketch_{index}"
    profile_var = f"{prefix}_{feature_key}_profile_{index}"
    feature_var = f"{prefix}_{feature_key}_feature_{index}"

    create_plane_step_id = _make_step_id(prefix, f"{feature_key}_plane", index)
    create_sketch_step_id = _make_step_id(prefix, f"{feature_key}_sketch", index)
    create_profile_step_id = _make_step_id(prefix, f"{feature_key}_profile", index)
    cut_step_id = _make_step_id(prefix, f"{feature_key}_cut", index)
    refresh_body_step_id = _make_step_id(prefix, f"{feature_key}_refresh_body", index)

    return [
        {
            "id": create_plane_step_id,
            "function": "CREATE_OFFSET_CONSTRUCTION_PLANE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "base_plane": {"type": "XY"},
                "offset_mm": float(plane_offset),
                "name": f"{component_id}_{feature_key}_{index}_plane",
            },
            "capture": {"vars": {plane_var: "plane_id"}},
            "depends_on": list(depends_on),
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "seat_compile_mode": seat_compile_mode,
                "anchor_face_interface_id": face_interface_id,
                "side_hint": normalized_side,
            },
        },
        {
            "id": create_sketch_step_id,
            "function": "CREATE_SKETCH_ON_PLANE",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "plane": {"type": "OFFSET", "plane_id": f"${{{plane_var}}}"},
                "name": f"{component_id}_{feature_key}_{index}_sketch",
            },
            "capture": {"vars": {sketch_var: "sketch_id"}},
            "depends_on": [create_plane_step_id],
        },
        {
            "id": create_profile_step_id,
            "function": "SKETCH_CIRCLE",
            "inputs": {
                "sketch_id": f"${{{sketch_var}}}",
                "center": {"x": 0.0, "y": 0.0},
                "radius": float(diameter) * 0.5,
            },
            "capture": {"vars": {profile_var: "profile_id"}},
            "depends_on": [create_sketch_step_id],
        },
        {
            "id": cut_step_id,
            "function": "EXTRUDE_CUT",
            "inputs": {
                "component_id": _component_var_ref(component_id),
                "profile_id": f"${{{profile_var}}}",
                "distance": float(depth),
                "direction": cut_direction,
                "body_id": f"${{{stable_body_var}}}",
            },
            "capture": {"vars": {feature_var: "feature_id"}},
            "depends_on": [create_profile_step_id],
            "metadata": {
                "anchor": {
                    "face_interface_id": face_interface_id,
                    "side_hint": normalized_side,
                    "face_geometry_type": "planar",
                },
                "seat_compile_mode": seat_compile_mode,
            },
        },
        {
            "id": refresh_body_step_id,
            "function": "GET_SINGLE_BODY_ID",
            "inputs": {
                "component_id": _component_var_ref(component_id),
            },
            "capture": {"vars": {stable_body_var: "body_id"}},
            "depends_on": [cut_step_id],
            "metadata": {
                "component_id": component_id,
                "source_feature": feature_key,
                "reason": "refresh_body_after_axisymmetric_bearing_seat_cut",
            },
        },
    ]


def _compile_feature_patch(
    *,
    feature_plan: Mapping[str, Any],
    allowed: Mapping[str, Any],
    skip_components: set[str],
    interface_recipe_index: Mapping[tuple[str, str], Mapping[str, Any]],
    component_definition_by_id: Mapping[str, str],
    component_strategy_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    steps: List[Dict[str, Any]] = []
    warnings: List[str] = []
    component_strategy_by_id = component_strategy_by_id if isinstance(component_strategy_by_id, Mapping) else {}

    # Deduplicate identical hole operations. Fusion will error if we try to cut
    # the same hole at the same location multiple times.
    seen_hole_signatures: set[tuple] = set()
    seen_group_seed_hole_signatures: set[tuple] = set()
    seen_thread_signatures: set[tuple] = set()
    seen_hole_intents: Dict[tuple[str, str], Dict[str, Any]] = {}
    grouped_hole_context: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    prototype_family_tokens = _build_prototype_family_tokens(component_definition_by_id)

    placements = feature_plan.get("connection_placements")
    if not isinstance(placements, list):
        return steps, warnings

    step_index = 0
    hole_like_features = {
        "hole",
        "shaft_bore",
        "bearing_seat",
        "alignment_pin_hole",
        "standoff_bore",
        "press_fit_zone",
        "retainer_groove",
        "seal_groove",
        "split_clamp_bore",
        "nut_seat",
        "bolt_circle_pattern",
        "counterbore",
        "countersink",
        "clearance_hole",
        "threaded_hole",
    }
    suppressed_mechanisms = {
        "bonded_tread",
        "bonded_mount",
        "press_fit",
        "companion_rotation_relation",
        "semantic_conflict_direct_rotor_mount",
    }
    for placement in placements:
        if not isinstance(placement, Mapping):
            continue
        instances = placement.get("instances") if isinstance(placement.get("instances"), list) else None
        derived = placement.get("derived_changes")
        placement_flags = placement.get("flags") if isinstance(placement.get("flags"), Mapping) else {}
        suppress_hole_generation = bool(placement_flags.get("suppress_hole_generation"))
        mechanism_name = str(placement.get("connection_mechanism") or "").strip().lower()
        placement_geo = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
        support_topology = str(placement_geo.get("support_topology") or "").strip().lower()
        if isinstance(derived, list):
            for change in derived:
                if not isinstance(change, Mapping):
                    continue
                target_id = change.get("target_component_id")
                if not isinstance(target_id, str) or not target_id:
                    warnings.append("derived_change missing target_component_id")
                    continue
                source_target_id = target_id
                target_id = component_definition_by_id.get(source_target_id, source_target_id)
                if target_id in skip_components:
                    warnings.append(f"derived_change skipped for standard part {target_id}")
                    continue
                feature = change.get("feature")
                if not isinstance(feature, str):
                    warnings.append(f"derived_change missing feature for {target_id}")
                    continue

                feature_key = feature.lower()
                target_strategy = component_strategy_by_id.get(target_id) if isinstance(component_strategy_by_id.get(target_id), Mapping) else {}
                if _is_standard_part_insert_only_strategy(target_strategy):
                    warnings.append(f"derived_change skipped for insert-only standard part {target_id}")
                    continue
                target_profile_type = str(target_strategy.get("profile_type") or "").strip().lower()
                slot_capture_mount = _infer_side_entry_slot_capture_mount(
                    placement=placement,
                    change=change,
                    target_strategy=target_strategy,
                )

                if (suppress_hole_generation or mechanism_name in suppressed_mechanisms) and feature_key in hole_like_features:
                    warnings.append(f"{feature_key} suppressed by semantic contract for {target_id}")
                    continue
                location_ref = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                interface_ref = location_ref.get("interface_ref") if isinstance(location_ref.get("interface_ref"), Mapping) else {}
                interface_name = str(interface_ref.get("name") or "").strip().lower()
                feature_group_name = str(change.get("feature_group_id") or placement.get("feature_group_id") or "").strip().lower()
                hub_arm_slot_mount_feature = (
                    interface_name.startswith("slot_mount_face_phase_")
                    or interface_name == "proximal_insert_face"
                    or feature_group_name.startswith("central_hub_to_arm_")
                    or feature_group_name.startswith("hub_to_arm_")
                )
                if (
                    slot_capture_mount
                    and feature_key in {"hole", "clearance_hole", "threaded_hole", "counterbore", "countersink", "nut_seat"}
                    and not (
                        (mechanism_name == "axial_face_bolted_mount" and support_topology == "hub_radial_slot_mount")
                        or hub_arm_slot_mount_feature
                    )
                ):
                    warnings.append(f"{feature_key} suppressed for side-entry slot capture mount on {target_id}")
                    continue
                if feature_key == "shaft_bore" and target_profile_type == "yoke_profile":
                    warnings.append(f"shaft_bore compiled in yoke body stage for {target_id}")
                    continue

                if feature_key in {"bolt_circle_pattern", "mounting_face"}:
                    warnings.append(f"{feature_key} treated as semantic marker only for {target_id}")
                    continue

                geometry_parameters_raw = change.get("geometry_parameters")
                geometry_parameters = geometry_parameters_raw if isinstance(geometry_parameters_raw, Mapping) else {}
                diameter = change.get("diameter") or change.get("bore_diameter") or change.get("hole_diameter")
                if not isinstance(diameter, (int, float)):
                    diameter = geometry_parameters.get("diameter") or geometry_parameters.get("bore_diameter") or geometry_parameters.get("hole_diameter")
                depth = change.get("depth")
                if isinstance(depth, str):
                    depth_val = None
                elif isinstance(depth, (int, float)):
                    depth_val = float(depth)
                else:
                    depth_val = None

                if feature_key == "thread":
                    _require_function(allowed, "ACTIVATE_COMPONENT")
                    _require_function(allowed, "SELECT_CYLINDRICAL_FACE")
                    _require_function(allowed, "THREAD_ON_CYLINDRICAL_FACES")

                    anchor = change.get("anchor")
                    anchor_map = anchor if isinstance(anchor, Mapping) else {}

                    radius_mm = anchor_map.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        radius_mm = change.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        radius_mm = geometry_parameters.get("radius_mm")
                    if not isinstance(radius_mm, (int, float)):
                        major_diameter = change.get("major_diameter")
                        if not isinstance(major_diameter, (int, float)):
                            major_diameter = geometry_parameters.get("major_diameter")
                        if isinstance(major_diameter, (int, float)):
                            radius_mm = float(major_diameter) / 2.0

                    if not isinstance(radius_mm, (int, float)):
                        warnings.append(f"thread missing radius_mm for {target_id}")
                        continue

                    tol_mm = anchor_map.get("tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = change.get("radius_tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = geometry_parameters.get("radius_tol_mm")
                    if not isinstance(tol_mm, (int, float)):
                        tol_mm = 0.05

                    raw_is_internal = change.get("is_internal")
                    if not isinstance(raw_is_internal, bool):
                        raw_is_internal = geometry_parameters.get("is_internal")
                    is_internal = bool(raw_is_internal) if isinstance(raw_is_internal, bool) else False

                    thread_type = change.get("thread_type")
                    if not isinstance(thread_type, str) or not thread_type.strip():
                        thread_type = geometry_parameters.get("thread_type")
                    if not isinstance(thread_type, str) or not thread_type.strip():
                        thread_type = "ISO Metric profile"

                    thread_designation = change.get("thread_designation")
                    if not isinstance(thread_designation, str) or not thread_designation.strip():
                        thread_designation = geometry_parameters.get("thread_designation")
                    if not isinstance(thread_designation, str) or not thread_designation.strip():
                        warnings.append(f"thread missing thread_designation for {target_id}")
                        continue

                    thread_class = change.get("thread_class")
                    if not isinstance(thread_class, str) or not thread_class.strip():
                        thread_class = geometry_parameters.get("thread_class")
                    if not isinstance(thread_class, str) or not thread_class.strip():
                        thread_class = "6H" if is_internal else "6g"

                    raw_is_modeled = change.get("is_modeled")
                    if not isinstance(raw_is_modeled, bool):
                        raw_is_modeled = geometry_parameters.get("is_modeled")
                    is_modeled = bool(raw_is_modeled) if isinstance(raw_is_modeled, bool) else False

                    raw_is_full_length = change.get("is_full_length")
                    if not isinstance(raw_is_full_length, bool):
                        raw_is_full_length = geometry_parameters.get("is_full_length")
                    is_full_length = bool(raw_is_full_length) if isinstance(raw_is_full_length, bool) else True

                    thread_length_mm = change.get("thread_length_mm")
                    if not isinstance(thread_length_mm, (int, float)):
                        thread_length_mm = geometry_parameters.get("thread_length_mm")

                    effective_is_full_length = bool(is_full_length)
                    effective_thread_length = round(float(thread_length_mm), 6) if isinstance(thread_length_mm, (int, float)) else None
                    if effective_is_full_length is False and effective_thread_length is None:
                        effective_is_full_length = True
                    thread_sig = (
                        target_id,
                        round(float(radius_mm), 6),
                        round(float(tol_mm), 6),
                        bool(is_internal),
                        thread_type.strip(),
                        thread_designation.strip(),
                        thread_class.strip(),
                        bool(is_modeled),
                        effective_is_full_length,
                        effective_thread_length,
                    )
                    if thread_sig in seen_thread_signatures:
                        warnings.append(
                            f"Duplicate thread feature skipped for {target_id} ({thread_designation.strip()})"
                        )
                        continue
                    seen_thread_signatures.add(thread_sig)

                    prefix = _safe_id(target_id)
                    stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")
                    face_var = f"{prefix}_{feature_key}_face_{step_index}"

                    activate_step_id = _make_step_id(prefix, f"{feature_key}_activate", step_index)
                    select_step_id = _make_step_id(prefix, f"{feature_key}_select_face", step_index)
                    thread_step_id = _make_step_id(prefix, f"{feature_key}_apply", step_index)

                    steps.append(
                        {
                            "id": activate_step_id,
                            "function": "ACTIVATE_COMPONENT",
                            "inputs": {
                                "component_id": _component_var_ref(target_id),
                            },
                        }
                    )

                    steps.append(
                        {
                            "id": select_step_id,
                            "function": "SELECT_CYLINDRICAL_FACE",
                            "inputs": {
                                "body_id": f"${{{stable_body_var}}}",
                                "radius_mm": float(radius_mm),
                                "tol_mm": float(tol_mm),
                            },
                            "capture": {"vars": {face_var: "face_id"}},
                            "depends_on": [activate_step_id],
                            "metadata": {
                                "component_id": target_id,
                                "source_feature": feature_key,
                            },
                        }
                    )

                    thread_inputs: Dict[str, Any] = {
                        "component_id": _component_var_ref(target_id),
                        "face_ids": [f"${{{face_var}}}"],
                        "is_internal": is_internal,
                        "thread_type": thread_type,
                        "thread_designation": thread_designation,
                        "thread_class": thread_class,
                        "is_modeled": is_modeled,
                        "is_full_length": is_full_length,
                        "name": f"{target_id}_{feature_key}_{step_index}",
                    }
                    if is_full_length is False:
                        if not isinstance(thread_length_mm, (int, float)):
                            warnings.append(
                                f"thread missing thread_length_mm while is_full_length=false for {target_id}; fallback to full_length"
                            )
                            thread_inputs["is_full_length"] = True
                        else:
                            thread_inputs["thread_length_mm"] = float(thread_length_mm)

                    steps.append(
                        {
                            "id": thread_step_id,
                            "function": "THREAD_ON_CYLINDRICAL_FACES",
                            "inputs": thread_inputs,
                            "depends_on": [select_step_id],
                            "metadata": {
                                "component_id": target_id,
                                "source_feature": feature_key,
                            },
                        }
                    )

                    step_index += 1
                    continue

                if feature_key in {
                    "hole",
                    "shaft_bore",
                    "bearing_seat",
                    "alignment_pin_hole",
                    "standoff_bore",
                    "press_fit_zone",
                    "retainer_groove",
                    "seal_groove",
                    "split_clamp_bore",
                    "nut_seat",
                    "bolt_circle_pattern",
                    "counterbore",
                    "countersink",
                }:
                    anchor = change.get("anchor")
                    anchor_map = anchor if isinstance(anchor, Mapping) else {}
                    face_interface_id = anchor_map.get("face_interface_id")
                    if not isinstance(face_interface_id, str) or not face_interface_id:
                        raise ValueError(
                            f"Hole feature '{feature_key}' for component '{target_id}' is missing anchor.face_interface_id"
                        )

                    face_recipe = interface_recipe_index.get((target_id, face_interface_id))
                    if not isinstance(face_recipe, Mapping) and source_target_id != target_id:
                        face_recipe = interface_recipe_index.get((source_target_id, face_interface_id))
                    if not isinstance(face_recipe, Mapping):
                        raise ValueError(
                            f"Missing interface recipe for hole anchor: component='{target_id}', interface='{face_interface_id}'"
                        )
                    face_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None

                    location_map = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
                    interface_ref = location_map.get("interface_ref") if isinstance(location_map.get("interface_ref"), Mapping) else {}
                    change_interface_ref = change.get("interface_ref") if isinstance(change.get("interface_ref"), Mapping) else {}
                    centered_bearing_seat = False
                    if feature_key == "bearing_seat":
                        named_interface = change_interface_ref.get("name") if isinstance(change_interface_ref.get("name"), str) else None
                        if not (isinstance(named_interface, str) and named_interface.strip()):
                            named_interface = interface_ref.get("name") if isinstance(interface_ref.get("name"), str) else None
                        named_interface = named_interface.strip().lower() if isinstance(named_interface, str) and named_interface.strip() else ""

                        seat_side = change.get("seat_side") if isinstance(change.get("seat_side"), str) else (placement.get("seat_side") if isinstance(placement.get("seat_side"), str) else None)
                        seat_side = seat_side.strip().lower() if isinstance(seat_side, str) and seat_side.strip() else ""
                        if not seat_side:
                            if named_interface.endswith("_min"):
                                seat_side = "min"
                            elif named_interface.endswith("_max"):
                                seat_side = "max"
                        centered_bearing_seat = not seat_side and named_interface == "bearing_seat"

                        preferred_face_interface_id = None
                        explicit_face_interface_id = geometry_parameters.get("face_interface_id") if isinstance(geometry_parameters.get("face_interface_id"), str) else None
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = change.get("face_interface_id") if isinstance(change.get("face_interface_id"), str) else None
                        geometry_anchor_map = geometry_parameters.get("anchor") if isinstance(geometry_parameters.get("anchor"), Mapping) else {}
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = geometry_anchor_map.get("face_interface_id") if isinstance(geometry_anchor_map.get("face_interface_id"), str) else None
                        if not (isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip()):
                            explicit_face_interface_id = anchor_map.get("face_interface_id") if isinstance(anchor_map.get("face_interface_id"), str) else None
                        if not centered_bearing_seat and isinstance(explicit_face_interface_id, str) and explicit_face_interface_id.strip():
                            preferred_face_interface_id = explicit_face_interface_id.strip()
                        if not (isinstance(preferred_face_interface_id, str) and preferred_face_interface_id):
                            if seat_side in {"min", "max"}:
                                preferred_face_interface_id = f"axial_end_face_{seat_side}"
                        if isinstance(preferred_face_interface_id, str) and preferred_face_interface_id.strip():
                            face_interface_id = preferred_face_interface_id.strip()
                            face_recipe = interface_recipe_index.get((target_id, face_interface_id))
                            if not isinstance(face_recipe, Mapping) and source_target_id != target_id:
                                face_recipe = interface_recipe_index.get((source_target_id, face_interface_id))
                            if not isinstance(face_recipe, Mapping):
                                raise ValueError(
                                    f"Missing interface recipe for hole anchor: component='{target_id}', interface='{face_interface_id}'"
                                )
                            face_geometry_type = face_recipe.get("geometry_type") if isinstance(face_recipe.get("geometry_type"), str) else None
                    usage = _recipe_usage(
                        face_recipe,
                        explicit_usage=(
                            interface_ref.get("usage")
                            if isinstance(interface_ref.get("usage"), str)
                            else (change.get("usage") if isinstance(change.get("usage"), str) else geometry_parameters.get("usage"))
                        ),
                    )
                    resolved_recipe = _sanitize_recipe_for_resolve(face_recipe, usage)

                    side_hint = anchor_map.get("side_hint") if isinstance(anchor_map.get("side_hint"), str) else None
                    if feature_key == "bearing_seat":
                        seat_side = placement.get("seat_side") if isinstance(placement.get("seat_side"), str) else None
                        seat_side = seat_side.strip().upper() if isinstance(seat_side, str) and seat_side.strip() else None
                        interface_seat_side = None
                        if isinstance(face_interface_id, str):
                            if face_interface_id.lower().endswith("_min"):
                                interface_seat_side = "MIN"
                            elif face_interface_id.lower().endswith("_max"):
                                interface_seat_side = "MAX"
                        side_hint = interface_seat_side or seat_side or side_hint
                        if isinstance(face_interface_id, str) and face_interface_id:
                            anchor_map = dict(anchor_map)
                            anchor_map["face_interface_id"] = face_interface_id
                        if isinstance(side_hint, str) and side_hint:
                            anchor_map = dict(anchor_map)
                            anchor_map["side_hint"] = side_hint

                    # Optional: thread spec on hole-like features.
                    # Accept both 'thread_spec' and 'thread' for convenience.
                    thread_spec = None
                    raw_thread = change.get("thread_spec")
                    if isinstance(raw_thread, Mapping):
                        thread_spec = raw_thread
                    else:
                        raw_thread = geometry_parameters.get("thread_spec")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread
                    if thread_spec is None:
                        raw_thread = change.get("thread")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread
                    if thread_spec is None:
                        raw_thread = geometry_parameters.get("thread")
                        if isinstance(raw_thread, Mapping):
                            thread_spec = raw_thread

                    if not isinstance(diameter, (int, float)):
                        warnings.append(f"{feature_key} missing diameter for {target_id}")
                        continue

                    hole_intent_id = geometry_parameters.get("hole_intent_id")
                    if not isinstance(hole_intent_id, str) or not hole_intent_id.strip():
                        hole_intent_id = change.get("hole_intent_id") if isinstance(change.get("hole_intent_id"), str) else None
                    hole_intent_id = hole_intent_id.strip() if isinstance(hole_intent_id, str) and hole_intent_id.strip() else None
                    if hole_intent_id is not None:
                        hole_intent_id = _canonicalize_prototype_scoped_name(
                            hole_intent_id,
                            prototype_component_id=target_id,
                            prototype_family_tokens=prototype_family_tokens,
                        )

                    hole_type_raw = geometry_parameters.get("hole_type")
                    if not isinstance(hole_type_raw, str) or not hole_type_raw.strip():
                        hole_type_raw = change.get("hole_type") if isinstance(change.get("hole_type"), str) else None
                    hole_type = hole_type_raw.strip().lower() if isinstance(hole_type_raw, str) and hole_type_raw.strip() else feature_key

                    if hole_intent_id is not None:
                        intent_key = (target_id, hole_intent_id)
                        existing = seen_hole_intents.get(intent_key)
                        if isinstance(existing, Mapping):
                            existing_hole_type = str(existing.get("hole_type") or "").lower()
                            existing_diameter = existing.get("diameter")
                            current_diameter = float(diameter)
                            conflict_reasons: List[str] = []

                            if existing_hole_type != hole_type:
                                conflict_reasons.append("hole_type_conflict")
                            if isinstance(existing_diameter, (int, float)) and abs(float(existing_diameter) - current_diameter) > 1e-6:
                                conflict_reasons.append("diameter_conflict")
                            if not conflict_reasons:
                                conflict_reasons.append("duplicate_hole_action")

                            raise ValueError(
                                "Conflicting hole realization in compile stage: "
                                f"component='{target_id}', hole_intent_id='{hole_intent_id}', "
                                f"existing_type='{existing_hole_type}', new_type='{hole_type}', "
                                f"existing_diameter={existing_diameter}, new_diameter={current_diameter}, "
                                f"reasons={conflict_reasons}"
                            )

                        seen_hole_intents[intent_key] = {
                            "hole_type": hole_type,
                            "diameter": float(diameter),
                            "feature_key": feature_key,
                        }

                    feature_group_raw = placement.get("feature_group_id")
                    if not isinstance(feature_group_raw, str) or not feature_group_raw.strip():
                        feature_group_raw = geometry_parameters.get("feature_group_id") if isinstance(geometry_parameters.get("feature_group_id"), str) else None
                    feature_group_id = feature_group_raw.strip() if isinstance(feature_group_raw, str) and feature_group_raw.strip() else feature_key
                    feature_group_id = _canonicalize_prototype_scoped_name(
                        feature_group_id,
                        prototype_component_id=target_id,
                        prototype_family_tokens=prototype_family_tokens,
                    )

                    group_key = (target_id, face_interface_id, feature_group_id)
                    group_ctx = grouped_hole_context.get(group_key)
                    if group_ctx is None:
                        prefix = _safe_id(target_id)
                        group_token = _safe_id(feature_group_id)
                        group_idx = step_index
                        step_index += 1
                        activate_step_id = _make_step_id(prefix, f"{group_token}_activate", group_idx)
                        resolve_step_id = _make_step_id(prefix, f"{group_token}_resolve_face", group_idx)
                        face_var = f"{prefix}_{group_token}_face_{group_idx}"
                        face_kind_var = f"{prefix}_{group_token}_face_kind_{group_idx}"
                        stable_body_var = _make_capture_var(_component_prefix(target_id), "body_id")

                        _require_function(allowed, "ACTIVATE_COMPONENT")
                        _require_function(allowed, "RESOLVE_INTERFACE")

                        steps.append(
                            {
                                "id": activate_step_id,
                                "function": "ACTIVATE_COMPONENT",
                                "inputs": {
                                    "component_id": _component_var_ref(target_id),
                                },
                            }
                        )
                        steps.append(
                            {
                                "id": resolve_step_id,
                                "function": "RESOLVE_INTERFACE",
                                "inputs": {
                                    "component_id": _component_var_ref(target_id),
                                    "body_id": f"${{{stable_body_var}}}",
                                    "interface_name": face_interface_id,
                                    "recipe": dict(resolved_recipe),
                                },
                                "capture": {"vars": {face_var: "entity_id", face_kind_var: "entity_kind"}},
                                "depends_on": [activate_step_id],
                                "metadata": {
                                    "component_id": target_id,
                                    "interface_name": face_interface_id,
                                    "expected_entity_kind": "face",
                                    "usage": usage,
                                },
                            }
                        )
                        group_ctx = {
                            "resolve_step_id": resolve_step_id,
                            "face_var": face_var,
                            "face_kind_var": face_kind_var,
                            "usage": usage,
                            "hole_count": 0,
                            "last_step_id": resolve_step_id,
                            "_resolved_recipe": dict(resolved_recipe),
                            "_face_interface_id": face_interface_id,
                            "_target_id": target_id,
                            "_feature_group_id": feature_group_id,
                        }
                        grouped_hole_context[group_key] = group_ctx

                    pattern_raw = placement.get("pattern")
                    pattern = pattern_raw if isinstance(pattern_raw, Mapping) else None
                    pattern_axis = placement.get("pattern_axis") if isinstance(placement.get("pattern_axis"), str) else None
                    seed_point_raw = placement.get("seed_point_mm") if isinstance(placement.get("seed_point_mm"), Mapping) else None

                    hole_mode = "simple"
                    if feature_key == "counterbore":
                        hole_mode = "counterbore"
                    elif feature_key == "countersink":
                        hole_mode = "countersink"
                    elif (
                        isinstance(geometry_parameters.get("cbore_diameter_mm"), (int, float))
                        or isinstance(geometry_parameters.get("counterbore_diameter"), (int, float))
                        or isinstance(change.get("cbore_diameter_mm"), (int, float))
                        or isinstance(change.get("counterbore_diameter"), (int, float))
                    ):
                        hole_mode = "counterbore"

                    cbore_diameter_mm = None
                    cbore_depth_mm = None
                    if hole_mode == "counterbore":
                        cbore_diameter_mm = (
                            geometry_parameters.get("cbore_diameter_mm")
                            if isinstance(geometry_parameters.get("cbore_diameter_mm"), (int, float))
                            else geometry_parameters.get("counterbore_diameter")
                        )
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = change.get("cbore_diameter_mm") if isinstance(change.get("cbore_diameter_mm"), (int, float)) else change.get("counterbore_diameter")
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = geometry_parameters.get("counterbore_diameter_mm")
                        if not isinstance(cbore_diameter_mm, (int, float)):
                            cbore_diameter_mm = change.get("counterbore_diameter_mm")
                        cbore_depth_mm = (
                            geometry_parameters.get("cbore_depth_mm")
                            if isinstance(geometry_parameters.get("cbore_depth_mm"), (int, float))
                            else geometry_parameters.get("counterbore_depth")
                        )
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = change.get("cbore_depth_mm") if isinstance(change.get("cbore_depth_mm"), (int, float)) else change.get("counterbore_depth")
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = geometry_parameters.get("counterbore_depth_mm")
                        if not isinstance(cbore_depth_mm, (int, float)):
                            cbore_depth_mm = change.get("counterbore_depth_mm")

                    csink_diameter_mm = None
                    csink_angle_rad = None
                    if hole_mode == "countersink":
                        csink_diameter_mm = (
                            geometry_parameters.get("csink_diameter_mm")
                            if isinstance(geometry_parameters.get("csink_diameter_mm"), (int, float))
                            else geometry_parameters.get("countersink_diameter")
                        )
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = change.get("csink_diameter_mm") if isinstance(change.get("csink_diameter_mm"), (int, float)) else change.get("countersink_diameter")
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = geometry_parameters.get("countersink_diameter_mm")
                        if not isinstance(csink_diameter_mm, (int, float)):
                            csink_diameter_mm = change.get("countersink_diameter_mm")
                        csink_angle_rad = geometry_parameters.get("csink_angle_rad")
                        if not isinstance(csink_angle_rad, (int, float)):
                            csink_angle_rad = change.get("csink_angle_rad")
                        if not isinstance(csink_angle_rad, (int, float)):
                            csink_angle_deg = geometry_parameters.get("csink_angle_deg")
                            if not isinstance(csink_angle_deg, (int, float)):
                                csink_angle_deg = change.get("csink_angle_deg")
                            if isinstance(csink_angle_deg, (int, float)):
                                csink_angle_rad = float(csink_angle_deg) * math.pi / 180.0

                    if hole_mode == "counterbore" and (not isinstance(cbore_diameter_mm, (int, float)) or not isinstance(cbore_depth_mm, (int, float))):
                        warnings.append(f"counterbore missing cbore geometry for {target_id}; fallback to HOLE_SIMPLE")
                        hole_mode = "simple"
                    if hole_mode == "countersink" and (not isinstance(csink_diameter_mm, (int, float)) or not isinstance(csink_angle_rad, (int, float))):
                        warnings.append(f"countersink missing csink geometry for {target_id}; fallback to HOLE_SIMPLE")
                        hole_mode = "simple"

                    if (not instances) and isinstance(pattern, Mapping) and str(pattern.get("type") or "").lower() in {"circular", "rectangular"}:
                        seed_center = {
                            "x": float((seed_point_raw or {}).get("x", 0.0)),
                            "y": float((seed_point_raw or {}).get("y", 0.0)),
                            "z": float((seed_point_raw or {}).get("z", 0.0)),
                        }
                        if depth_val is None:
                            if side_hint == "MAX":
                                extent_key = "through_negative"
                            elif side_hint == "MIN":
                                extent_key = "through_positive"
                            else:
                                extent_key = "through_positive"
                        else:
                            extent_key = "distance"

                        group_seed_sig = (
                            target_id,
                            feature_group_id,
                            face_interface_id,
                            side_hint,
                            round(seed_center["x"], 6),
                            round(seed_center["y"], 6),
                            round(seed_center["z"], 6),
                            round(float(diameter), 6),
                            extent_key,
                        )
                        if group_seed_sig in seen_group_seed_hole_signatures:
                            warnings.append(
                                f"Duplicate grouped seed hole skipped for {target_id} (feature_group_id={feature_group_id})"
                            )
                            continue

                        hole_sig = (
                            target_id,
                            feature_key,
                            face_interface_id,
                            side_hint,
                            float(diameter),
                            depth_val,
                            extent_key,
                            (round(seed_center["x"], 6), round(seed_center["y"], 6), round(seed_center["z"], 6)),
                            f"pattern:{str(pattern.get('type') or '').lower()}",
                        )
                        if hole_sig in seen_hole_signatures:
                            warnings.append(f"Duplicate patterned {feature_key} skipped for {target_id}")
                            continue
                        seen_group_seed_hole_signatures.add(group_seed_sig)
                        seen_hole_signatures.add(hole_sig)

                        seed_feature_var = f"{_safe_id(target_id)}_{_safe_id(feature_group_id)}_seed_feature_{step_index}"

                        _p_face_var, _p_face_kind_var, _p_depends, step_index = _re_resolve_group_face(
                            group_ctx=group_ctx,
                            target_id=target_id,
                            feature_group_id=feature_group_id,
                            step_index=step_index,
                            steps=steps,
                            face_interface_id=face_interface_id,
                            usage=usage,
                        )

                        _p_hole_steps = _compile_hole_simple_steps(
                            component_id=target_id,
                            feature_key=feature_key,
                            diameter=float(diameter),
                            depth=depth_val,
                            side_hint=side_hint,
                            face_interface_id=face_interface_id,
                            face_geometry_type=face_geometry_type,
                            resolved_face_var=_p_face_var,
                            resolved_face_kind_var=_p_face_kind_var,
                            allowed=allowed,
                            index=step_index,
                            center_mm=seed_center,
                            depends_on=_p_depends,
                            hole_mode=hole_mode,
                            cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                            cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                            csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                            csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                            capture_feature_var=seed_feature_var,
                            pattern=pattern,
                            pattern_axis=pattern_axis,
                            thread_spec=thread_spec,
                        )
                        steps.extend(_p_hole_steps)

                        # Update group context for next hole in group
                        group_ctx["hole_count"] += 1
                        if _p_hole_steps:
                            group_ctx["last_step_id"] = _p_hole_steps[-1]["id"]
                            group_ctx["face_var"] = _p_face_var
                            group_ctx["face_kind_var"] = _p_face_kind_var
                            group_ctx["resolve_step_id"] = _p_depends[0]

                        step_index += 1
                        continue

                    if instances:
                        for inst in instances:
                            if not isinstance(inst, Mapping):
                                continue
                            pos = inst.get("position")
                            if not isinstance(pos, Mapping):
                                continue

                            # Signature: same target + params + center => same hole.
                            extent_key = "through_positive" if depth_val is None else "distance"
                            try:
                                center_key = (
                                    round(float(pos.get("x", 0.0)), 6),
                                    round(float(pos.get("y", 0.0)), 6),
                                    round(float(pos.get("z", 0.0)), 6),
                                )
                            except Exception:
                                center_key = (0.0, 0.0, 0.0)

                            hole_sig = (
                                target_id,
                                feature_key,
                                face_interface_id,
                                side_hint,
                                float(diameter),
                                depth_val,
                                extent_key,
                                center_key,
                            )
                            if hole_sig in seen_hole_signatures:
                                warnings.append(
                                    f"Duplicate {feature_key} skipped for {target_id} at {center_key}"
                                )
                                continue
                            seen_hole_signatures.add(hole_sig)

                            current_face_var, current_face_kind_var, current_depends, step_index = _re_resolve_group_face(
                                group_ctx=group_ctx,
                                target_id=target_id,
                                feature_group_id=feature_group_id,
                                step_index=step_index,
                                steps=steps,
                                face_interface_id=face_interface_id,
                                usage=usage,
                            )

                            hole_steps = _compile_hole_simple_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=depth_val,
                                side_hint=side_hint,
                                face_interface_id=face_interface_id,
                                face_geometry_type=face_geometry_type,
                                resolved_face_var=current_face_var,
                                resolved_face_kind_var=current_face_kind_var,
                                allowed=allowed,
                                index=step_index,
                                center_mm=pos,
                                depends_on=current_depends,
                                hole_mode=hole_mode,
                                cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                                cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                                csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                                csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                                thread_spec=thread_spec,
                            )
                            steps.extend(hole_steps)

                            # Update group context for next hole in group
                            group_ctx["hole_count"] += 1
                            if hole_steps:
                                group_ctx["last_step_id"] = hole_steps[-1]["id"]
                                group_ctx["face_var"] = current_face_var
                                group_ctx["face_kind_var"] = current_face_kind_var
                                group_ctx["resolve_step_id"] = current_depends[0]

                            step_index += 1
                    else:
                        extent_key = "through_positive" if depth_val is None else "distance"
                        hole_sig = (
                            target_id,
                            feature_key,
                            face_interface_id,
                            side_hint,
                            float(diameter),
                            depth_val,
                            extent_key,
                            (0.0, 0.0, 0.0),
                        )
                        if hole_sig in seen_hole_signatures:
                            warnings.append(
                                f"Duplicate {feature_key} skipped for {target_id} at (0,0,0)"
                            )
                            continue
                        seen_hole_signatures.add(hole_sig)

                        _e_face_var, _e_face_kind_var, _e_depends, step_index = _re_resolve_group_face(
                            group_ctx=group_ctx,
                            target_id=target_id,
                            feature_group_id=feature_group_id,
                            step_index=step_index,
                            steps=steps,
                            face_interface_id=face_interface_id,
                            usage=usage,
                        )

                        integrated_axisymmetric_seat = (
                            feature_key == "bearing_seat"
                            and _integrated_axisymmetric_bearing_seat_params(target_strategy) is not None
                        )
                        if integrated_axisymmetric_seat:
                            warnings.append(
                                f"Integrated axisymmetric bearing_seat geometry already baked into profile for {target_id}; compile-time cut skipped"
                            )
                            continue
                        if _should_compile_axisymmetric_bearing_seat_cut(
                            feature_key=feature_key,
                            target_strategy=target_strategy,
                            face_interface_id=face_interface_id,
                            diameter=diameter,
                            depth=depth_val,
                            centered=centered_bearing_seat,
                        ):
                            _e_hole_steps = _compile_axisymmetric_bearing_seat_cut_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=float(depth_val),
                                side_hint=side_hint or "MAX",
                                face_interface_id=face_interface_id,
                                allowed=allowed,
                                index=step_index,
                                depends_on=_e_depends,
                                target_strategy=target_strategy,
                                centered=centered_bearing_seat,
                            )
                        else:
                            _e_hole_steps = _compile_hole_simple_steps(
                                component_id=target_id,
                                feature_key=feature_key,
                                diameter=float(diameter),
                                depth=depth_val,
                                side_hint=side_hint,
                                face_interface_id=face_interface_id,
                                face_geometry_type=face_geometry_type,
                                resolved_face_var=_e_face_var,
                                resolved_face_kind_var=_e_face_kind_var,
                                allowed=allowed,
                                index=step_index,
                                center_mm=(seed_point_raw if isinstance(seed_point_raw, Mapping) else None),
                                depends_on=_e_depends,
                                hole_mode=hole_mode,
                                cbore_diameter_mm=float(cbore_diameter_mm) if isinstance(cbore_diameter_mm, (int, float)) else None,
                                cbore_depth_mm=float(cbore_depth_mm) if isinstance(cbore_depth_mm, (int, float)) else None,
                                csink_diameter_mm=float(csink_diameter_mm) if isinstance(csink_diameter_mm, (int, float)) else None,
                                csink_angle_rad=float(csink_angle_rad) if isinstance(csink_angle_rad, (int, float)) else None,
                                thread_spec=thread_spec,
                            )
                        steps.extend(_e_hole_steps)

                        # Update group context for next hole in group
                        group_ctx["hole_count"] += 1
                        if _e_hole_steps:
                            group_ctx["last_step_id"] = _e_hole_steps[-1]["id"]
                            group_ctx["face_var"] = _e_face_var
                            group_ctx["face_kind_var"] = _e_face_kind_var
                            group_ctx["resolve_step_id"] = _e_depends[0]

                        step_index += 1
                    continue

                if feature_key in {"keyway_slot", "clamp_slot"}:
                    width = change.get("width")
                    height = change.get("height")
                    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                        warnings.append(f"{feature_key} missing width/height for {target_id}")
                        continue
                    steps.extend(
                        _rectangle_feature_steps(
                            component_id=target_id,
                            feature_key=feature_key,
                            width=float(width),
                            height=float(height),
                            depth=depth_val,
                            allowed=allowed,
                            index=step_index,
                        )
                    )
                    step_index += 1
                    continue

                if feature_key in {"local_thickening", "bonding_zone"}:
                    warnings.append(f"{feature_key} ignored (no geometric rule) for {target_id}")
                    continue

                warnings.append(f"Unsupported derived feature '{feature_key}' for {target_id}")

    return steps, warnings
