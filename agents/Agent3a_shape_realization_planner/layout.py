"""Agent3a layout inference, symmetry detection, and initial placement planning."""

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

def _build_coordinate_frame(
    *,
    component_id: str,
    layout_positions: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    _ = component_id
    _ = layout_positions
    return {
        "reference_frame": "component_local",
        "origin_mm": {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        },
        "axes": {
            "x_axis": {"x": 1.0, "y": 0.0, "z": 0.0},
            "y_axis": {"x": 0.0, "y": 1.0, "z": 0.0},
            "z_axis": {"x": 0.0, "y": 0.0, "z": 1.0},
        },
    }


def _registry_supports_construction_method(
    registry: Dict[str, Any],
    method: str,
) -> bool:
    if not isinstance(registry, dict):
        return False
    names = set(registry.keys())
    if method == "extrude":
        return any(n.startswith("EXTRUDE_") for n in names)
    if method == "revolve":
        return "REVOLVE_NEW_BODY" in names
    return False


def _extract_position_hints(kg: Dict[str, Any]) -> Dict[str, str]:
    """
    婵犵數鍋涢顓熸叏閹绢喖绀冮柣婵囧缁绘盯骞嬮悙瀛樺剮闂佸憡锚閳ь剛鍠嗘禍鐟般€掑锝呬壕閻庤娲╃紞浣割嚕鐠轰警鐎堕柡鍛焽tion_offset闂傚倷鑳堕、濠囶敋瑜忛幑銏犖旈崨顓㈠敹濡炪倕绻愰悧濠囧疾椤掑嫭鍊堕柣鎰硾娴滃湱绱掔€ｎ亷宸ラ柍钘夘樀楠炴﹢宕滄担鍓愨啓M闂傚倷娴囬～澶嬬娴犲绀夐煫鍥ㄤ緱閺佸﹪鏌熸潏楣冩闁稿骸绉归弻娑㈠即閵娿儲鐝梺鎼炲€栭弻銊╁煡婢舵劕妫樻繛鍡欏亾鏁堥柣鐔哥矒椤ｏ箓鎳楅崜浣稿灊闁割偁鍎辩粻鎺楁煙閸濆嫭顥滃ù?
    
    Returns: {component_id: "semantic position hint" or ""}
    """
    hints = {}
    for comp in kg.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        
        # Extract position_offset description if available
        offset = comp.get("position_offset")
        if isinstance(offset, dict):
            desc = offset.get("description", "")
            along_axis = offset.get("along_axis", "")
            if desc:
                hints[comp_id] = f"{desc} (along {along_axis})" if along_axis else desc
        
    return hints


def _build_position_parent_constraints(kg: Dict[str, Any]) -> str:
    """
    闂傚倷绀侀幖顐︻敄閸涱垪鍋撳鐓庡缂佽鲸鎹囬獮鏍х暋閻ョそtion_parent闂傚倷绀侀幖顐ょ矓閻㈢鍨傞柣鐔稿閺嬫棃鏌熺€电啸婵☆偒鍨堕弻銊╁籍閸ヮ灝鎾绘倶韫囨挻顥滈懣鎰版煕閵夘垳鍒板褎褰冮湁闁绘挸瀛╅崵鍥煛娴ｅ摜孝闁伙絾绻堥崺鈧い鎺戝閺嬩線鏌曢崼婵囶棤妞も晞灏欓埀顒€绠嶉崕鎶藉箯閻?prompt闂?
    
    Returns: 闂傚倷绀侀幖顐ょ矓閸洖鍌ㄧ憸蹇撐ｉ幇鐗堟櫢闁绘灏欓ˇ閬嶆⒑閸濆嫮鈻夐柛瀣嚇閹偓娼忛埡鍐紲闂佽鍎抽幊妯侯瀶椤旂晫绠剧痪鏉垮船娴滄壆鈧鍣崜鐔风暦閸洖惟闁挎棁妫勯浼存⒒娴ｄ警鏀版い鏇嗗懏宕叉俊銈呮噹闁?    """
    components = kg.get("components", []) or []
    ground_root_id = _select_ground_root_id(kg)

    roots = [c for c in components if isinstance(c, dict) and not c.get("position_parent")]
    
    tree_lines = ["ASSEMBLY HIERARCHY (position_parent tree):"]
    
    for root in roots:
        root_id = root.get("id")
        if not isinstance(root_id, str):
            continue
        
        if root_id == ground_root_id:
            tree_lines.append(f"  {root_id} (ROOT - must be at origin 0,0,0)")
        else:
            tree_lines.append(f"  {root_id} (UNPARENTED - NOT grounded; free placement allowed)")
        
        def traverse(parent_id, indent=4):
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                if comp.get("position_parent") != parent_id:
                    continue
                child_id = comp.get("id")
                if not isinstance(child_id, str):
                    continue
                comp_type = comp.get("type", "")
                tree_lines.append(f"{'  ' * (indent // 2)}{child_id} (type: {comp_type})")
                traverse(child_id, indent + 4)
        
        traverse(root_id)
    
    return "\n".join(tree_lines)


def _detect_radial_symmetry_pattern(kg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    濠电姷顣藉Σ鍛村磻閳ь剟鏌涚€ｎ偅灏扮紒缁樼洴瀵爼骞嬮鐐插婵犵鈧啿绾ч柟顔煎€搁悾鐑藉Ψ閳哄倹娅囬梺閫炲苯澧撮柟顔芥そ婵℃悂鍩℃担鐟扮ザ闂備線娼ч…鍫ュ磿瀹曞洨鐜婚柣鎰劋閻撴洘鎱ㄥ鍡楀箹闁诲繈鍎查妵鍕即閵娿儲鐏撶紓渚囧枟濡啴骞冭瀹曟椽顢栫捄顭戞М濡炪倖娲╃紞鈧紒鐘崇洴婵＄柉顦存い锔规櫊濮婃椽宕崟顓夈儲銇勯銏╂Ц闁伙絽鐏氱粙濠勬婵紴闂傚倷绀侀幉锛勫垝瀹€鍕垫晩濠靛婀糴nt闂傚倷鐒︾€笛呯矙閹次诲洭顢橀姀鐘靛姦?
    
    Returns: {parent_id: [component_ids]} 闂?None
    """
    components = kg.get("components", []) or []
    
    # Group by parent
    by_parent = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        parent = comp.get("position_parent")
        if parent not in by_parent:
            by_parent[parent] = []
        by_parent[parent].append(comp)
    
    # Check for radial symmetry: components with same type under same parent
    patterns = {}
    for parent_id, sibs in by_parent.items():
        if parent_id is None:
            continue
        types = {}
        for comp in sibs:
            ctype = comp.get("type")
            if ctype not in types:
                types[ctype] = []
            cid = comp.get("id")
            if isinstance(cid, str):
                types[ctype].append(cid)
        
        # If 3+ siblings of same type, likely radial symmetric
        for ctype, ids in types.items():
            if len(ids) >= 3:
                patterns[parent_id] = {
                    "type": ctype,
                    "count": len(ids),
                    "components": ids
                }
    
    return patterns if patterns else None


def _select_ground_root_id(kg: Dict[str, Any]) -> str:
    components = [c for c in (kg.get("components") or []) if isinstance(c, dict)]
    if not components:
        return "root"

    def _is_fixed_support_component(comp: Dict[str, Any]) -> bool:
        cid = str(comp.get("id") or "").strip()
        if not cid:
            return False
        cid_lower = cid.lower()
        role_lower = str(comp.get("role") or "").strip().lower()
        type_lower = str(comp.get("type") or "").strip().lower()
        if "support_housing" in cid_lower:
            return True
        if role_lower in {"fixed_support_housing", "support_housing", "carrier", "fixed_bracket"}:
            return True
        return type_lower in {"housing", "bracket", "carrier"} and any(token in role_lower for token in ("support", "fixed"))

    support_candidates = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c.get("id"), str) and c.get("id") and _is_fixed_support_component(c)
        ]
    )
    if support_candidates:
        return support_candidates[0]

    ids = sorted(
        [str(c.get("id")) for c in components if isinstance(c.get("id"), str) and c.get("id")]
    )
    if "central_hub" in ids:
        return "central_hub"

    hub_candidates = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c.get("id"), str)
            and c.get("id")
            and str(c.get("type", "")).strip().lower() in {"hub", "center", "central"}
        ]
    )
    if hub_candidates:
        return hub_candidates[0]

    parent_ref_count: Dict[str, int] = {}
    for comp in components:
        parent = comp.get("position_parent")
        if isinstance(parent, str) and parent:
            parent_ref_count[parent] = parent_ref_count.get(parent, 0) + 1
    if parent_ref_count:
        best = sorted(parent_ref_count.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if isinstance(best, str) and best:
            return best

    first = components[0].get("id")
    if isinstance(first, str) and first:
        return first
    return "root"


def _extract_rotational_pattern_component_ids(kg: Dict[str, Any]) -> List[str]:
    out: set[str] = set()
    patterns = kg.get("patterns")
    if not isinstance(patterns, list):
        return []
    for pat in patterns:
        if not isinstance(pat, dict):
            continue
        ptype = pat.get("type")
        if not isinstance(ptype, str):
            continue
        if ptype.strip().lower() not in {"rotational_symmetry", "radial_symmetry", "rotational"}:
            continue
        comp_ids = pat.get("component_ids")
        if isinstance(comp_ids, list):
            for cid in comp_ids:
                if isinstance(cid, str) and cid:
                    out.add(cid)
    return sorted(out)


def _validate_llm_positions(
    positions: Dict[str, Dict[str, Any]],
    kg: Dict[str, Any],
    parent_chains: Dict[str, List[str]],
    warnings: List[str],
    *,
    ground_root_id: str,
    llm_target_ids: List[str],
) -> bool:
    """
    婵犲痉鏉库偓妤佹叏閹绢喗鍎楀〒姘ｅ亾闁诡垯鐒︾换鍛節閻ф洟姊洪崫鍕垫Ц闁绘锕獮鎰板箹娴ｇ鎯炲銈嗘尪閸ㄦ椽宕曞澶嬬厱闁哄洢鍔屾禍婵嬫煕婵炲灝鈧繈寮婚敐澶嬪€烽柛娆忣樈濡繝姊洪柅鐐茶嫰閸旑垰霉閿濆棗绲诲ù婊堢畺閺屾稓浠﹂崣銉х箒濠殿喖锕粻鏍蓟閿涘嫪娌悹鍥ㄥ絻婵绱?    1. 闂傚倷绀佸﹢閬嶃€傛禒瀣；闁瑰墽绮悡娑㈡煕椤愶絿绠ユ俊鑼舵缁辨帡顢欓懖鈹絿绱掗崒娑樻诞鐎规洖銈稿鎾倷閹绘帞顓洪梻浣藉吹閸嬬偤宕欒ぐ鎺戠；闁告稒娼欏Λ妯好归敐鍫燁仩缁惧墽鍋撻妵鍕籍閸パ冩優闂佸摜鍠庨敃顏堝蓟濞戞﹩娼╂い鎾楀嫷鍚呯紓?    2. Root缂傚倸鍊搁崐椋庣矆娴ｈ　鍋撳闂寸盎闁宠閰ｆ慨鈧柕鍫濇噺瀹撳秹姊洪棃娑辩劸闁稿酣浜跺顒冾樄闁哄矉缍侀獮鍥敊閽樺鐣梻浣筋嚃閸燁偊宕堕妸锔界彨?
    3. 闂佽楠搁悘姘熆濡皷鍋撳鐓庡⒋妤犵偛鍟…銊╁川椤忓嫪澹曢梻鍌氱墛缁嬫帞鎷归敍鍕仏闁靛ň鏅滈悡娆愩亜閹搭厼澧俊顐幖椤洨鎹勯崨闈涢叄瀹曞爼濡歌閻ｅジ姊洪崫鍕棏闁稿鎸荤换娑氣偓娑欘焽閻﹥淇婇锝庢疁妤犵偛鍟抽ˇ褰掓煛?
    
    Returns: True if valid, False otherwise (濠德板€楁慨鐑藉磻閻樿鏄ラ柡宥庡幖闁裤倕鈹戦悩鍙夋悙缂佲偓婢舵劖鐓熸俊顖滎攰椤掔喖鏌涢弬鎸庡殗闁哄本绋戦埥澶婎潨閸噥鏆┑鐑囩到濞层倝鏁冮鍫㈠祦?
    """
    components = kg.get("components", []) or []
    
    # Check 1: Grounded root must be present in output.
    root_pos = positions.get(ground_root_id)
    if not root_pos or not isinstance(root_pos, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} missing in LLM output")
        return False

    # Check 2: All target components placed?
    all_ids = {cid for cid in llm_target_ids if isinstance(cid, str) and cid}
    placed_ids = set(positions.keys())
    missing = all_ids - placed_ids
    
    if missing:
        warnings.append(f"LLM validation FAILED: Missing target components not placed: {missing}")
        return False

    # Check 3: Grounded root anchored at origin (with normalization pass)
    pos = positions.get(ground_root_id)
    if not isinstance(pos, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} has invalid position payload")
        return False

    gx = float(pos.get("x", 0.0) or 0.0)
    gy = float(pos.get("y", 0.0) or 0.0)
    gz = float(pos.get("z", 0.0) or 0.0)

    if abs(gx) > 0.1 or abs(gy) > 0.1 or abs(gz) > 0.1:
        dx, dy, dz = -gx, -gy, -gz
        for cid, p in positions.items():
            if not isinstance(p, dict):
                continue
            px = float(p.get("x", 0.0) or 0.0)
            py = float(p.get("y", 0.0) or 0.0)
            pz = float(p.get("z", 0.0) or 0.0)
            p["x"] = px + dx
            p["y"] = py + dy
            p["z"] = pz + dz
        warnings.append(
            f"LLM validation normalized global offset by delta=({dx:.3f}, {dy:.3f}, {dz:.3f}) to anchor {ground_root_id} at origin"
        )

    pos2 = positions.get(ground_root_id)
    if not pos2 or not isinstance(pos2, dict):
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} missing after normalization")
        return False
    gx2 = float(pos2.get("x", 0.0) or 0.0)
    gy2 = float(pos2.get("y", 0.0) or 0.0)
    gz2 = float(pos2.get("z", 0.0) or 0.0)
    if abs(gx2) > 0.1 or abs(gy2) > 0.1 or abs(gz2) > 0.1:
        warnings.append(f"LLM validation FAILED: Grounded root {ground_root_id} not at origin after normalization: {pos2}")
        return False
    
    # Check 4: Radial symmetry preserved?
    sym_patterns = _detect_radial_symmetry_pattern(kg)
    if sym_patterns:
        for parent_id, pattern in sym_patterns.items():
            comp_positions = [positions.get(cid) for cid in pattern["components"] if isinstance(cid, str)]
            comp_positions = [p for p in comp_positions if p and isinstance(p, dict)]
            
            if len(comp_positions) != pattern["count"]:
                warnings.append(f"LLM validation WARNING: Radial pattern under {parent_id} incomplete")
                continue
            
            # Check if distances from parent are roughly equal
            parent_pos = positions.get(parent_id)
            if parent_pos:
                distances = []
                for pos in comp_positions:
                    dx = float(pos.get("x", 0)) - float(parent_pos.get("x", 0))
                    dy = float(pos.get("y", 0)) - float(parent_pos.get("y", 0))
                    dz = float(pos.get("z", 0)) - float(parent_pos.get("z", 0))
                    dist = (dx**2 + dy**2 + dz**2)**0.5
                    distances.append(dist)
                
                # All distances should be roughly equal (within 5% tolerance)
                if distances and max(distances) > 0:
                    variance = max(distances) / min(d for d in distances if d > 0)
                    if variance > 1.05:
                        warnings.append(
                            f"LLM validation WARNING: Radial pattern under {parent_id} "
                            f"has uneven spacing (variance {variance:.2f}x)"
                        )
    
    return True


def _infer_layout_positions(kg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic + LLM-assisted layout position inference (improved version).
    
    Four-phase approach:
    1. **Deterministic**: Recognize equal-spacing patterns
    2. **Constraint Generation**: Extract position hints and hierarchy info
    3. **Improved LLM**: Call with stronger constraints and validation
    4. **Fallback**: If LLM fails validation, use deterministic-only result
    
    Returns:
        {
            "layout_positions": {
                "component_id": {"x": float, "y": float, "z": float},
                ...
            },
            "inference_mode": "deterministic_equal_spacing" | "llm_hierarchical" | "hybrid" | "fallback_origin_only",
            "warnings": [str...],
            "parent_chains": {...}  # Debug info
        }
    """
    import math
    import os
    import json
    
    positions: Dict[str, Dict[str, float]] = {}
    warnings: List[str] = []
    inference_mode = "unknown"
    parent_chains: Dict[str, List[str]] = {}
    
    components = kg.get("components", [])
    if not components:
        return {
            "layout_positions": positions,
            "inference_mode": "empty_kg",
            "warnings": ["No components in KG"],
            "parent_chains": {}
        }
    
    # Build lookup tables
    by_id: Dict[str, Dict[str, Any]] = {}
    by_prefix: Dict[str, List[tuple[str, int, Dict[str, Any]]]] = {}
    
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        by_id[comp_id] = comp
        
        # Try to match pattern: "prefix_N"
        match = re.match(r"^([a-z_]+?)_(\d+)$", comp_id)
        if match:
            prefix = match.group(1)
            index = int(match.group(2))
            if prefix not in by_prefix:
                by_prefix[prefix] = []
            by_prefix[prefix].append((comp_id, index, comp))
    
    # ===== PHASE 1: Deterministic Equal Spacing =====
    for prefix, items in by_prefix.items():
        if len(items) < 3:
            continue
        
        types = {comp.get("type") for _, _, comp in items}
        roles = {comp.get("role") for _, _, comp in items}
        
        if len(types) != 1 or len(roles) != 1:
            continue
        
        radial_dist = None
        first_comp = items[0][2]
        comp_type = first_comp.get("type", "")
        dims = first_comp.get("dimensions", {})
        
        if comp_type == "arm" and "length" in dims:
            radial_dist = float(dims.get("length", 60))
        
        if radial_dist is None:
            radial_dist = 60.0
        
        n = len(items)
        angle_step = 2 * math.pi / n
        
        for idx, (comp_id, _, _) in enumerate(sorted(items, key=lambda x: x[1])):
            angle = idx * angle_step
            x = radial_dist * math.cos(angle)
            y = radial_dist * math.sin(angle)
            z = 0.0
            
            positions[comp_id] = {
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(z, 4)
            }
        
        inference_mode = f"deterministic_equal_spacing_{n}way"
    
    # ===== PHASE 2: Build position parent hierarchy =====
    ground_root_id = _select_ground_root_id(kg)
    position_hints = _extract_position_hints(kg)
    hierarchy_constraints = _build_position_parent_constraints(kg)
    
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id in positions:
            continue  # Already handled by deterministic phase
        
        # Trace position_parent chain
        chain: List[str] = [comp_id]
        current_id = comp_id
        visited: set[str] = {comp_id}
        
        while True:
            current_comp = by_id.get(current_id)
            if not current_comp:
                break
            
            parent_id = current_comp.get("position_parent")
            if not isinstance(parent_id, str):
                break
            
            if parent_id in visited:
                warnings.append(f"Circular position_parent chain detected: {comp_id}")
                break
            
            chain.append(parent_id)
            visited.add(parent_id)
            current_id = parent_id
        
        parent_chains[comp_id] = chain
    
    # Ensure single grounded root at origin
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue
        if comp_id == ground_root_id and comp_id not in positions:
            positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}

    total_count = len([c for c in components if isinstance(c, dict) and isinstance(c.get("id"), str)])
    root_count = len([c for c in components if isinstance(c, dict) and not c.get("position_parent")])
    root_ratio = (float(root_count) / float(total_count)) if total_count > 0 else 1.0
    rotational_ids = _extract_rotational_pattern_component_ids(kg)
    has_rotational_pattern = bool(rotational_ids)

    parented_ids = sorted(
        [
            str(c.get("id"))
            for c in components
            if isinstance(c, dict)
            and isinstance(c.get("id"), str)
            and isinstance(c.get("position_parent"), str)
            and c.get("position_parent")
        ]
    )
    llm_target_ids = sorted(
        {
            cid
            for cid in (parented_ids + rotational_ids + [ground_root_id])
            if isinstance(cid, str) and cid
        }
    )
    
    # ===== PHASE 3: Improved LLM inference with constraints + validation =====
    has_position_parents = len(parented_ids) > 0
    llm_eligible = len(llm_target_ids) > 0 and (has_position_parents or has_rotational_pattern)
    if llm_eligible and ((root_ratio > 0.6) or (root_count > 5)) and (not has_rotational_pattern):
        llm_eligible = False
        warnings.append(
            f"LLM layout gate disabled: root_ratio={root_ratio:.2f}, root_count={root_count}; using deterministic_only"
        )
        if not inference_mode.startswith("deterministic"):
            inference_mode = "deterministic_only"
    
    llm_call_succeeded = False
    llm_attempted = False
    
    if llm_eligible:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                llm_attempted = True
                
                # Build improved LLM prompt with STRONG constraints
                prompt = f"""You are a mechanical assembly positioning expert. Your task is to infer ABSOLUTE global coordinates for the requested target components.

GROUNDED ROOT ID (the only true ROOT):
{ground_root_id}

STRUCTURAL CONSTRAINT - IMMUTABLE:
The following position_parent relationships form the assembly hierarchy. You MUST respect this tree structure exactly:

{hierarchy_constraints}

CRITICAL RULES:
1. Only component {ground_root_id} is ROOT and MUST be positioned exactly at (0, 0, 0).
2. Other components with position_parent null/None are NOT ROOT and are NOT constrained to origin.
3. For each component with a position_parent, calculate its absolute position by:
   a. Getting the parent's absolute position
   b. Adding the child's relative offset (from position_offset description)
   c. Store the result as absolute global coordinates
4. Return coordinates ONLY for target component ids listed below.
5. Grounded root {ground_root_id} MUST be included in the output and MUST be exactly (0, 0, 0).

LLM TARGET COMPONENT IDS (output only these):
{json.dumps(llm_target_ids, ensure_ascii=False)}

SEMANTIC HINTS (use these to infer relative offsets):
{json.dumps(position_hints, ensure_ascii=False, indent=2) if position_hints else "No position_offset hints available; use engineering defaults."}

SYMMETRY DETECTION:
If multiple components have the same type and same position_parent (where position_parent is a concrete component id), they likely form radial symmetry. Distribute them evenly around the parent.
Do NOT apply symmetry grouping for components whose position_parent is null/None.

Knowledge Graph Components Details:
{json.dumps([dict(comp, id=c.get('id'), type=c.get('type'), position_parent=c.get('position_parent'), position_offset=c.get('position_offset'), dimensions=c.get('dimensions')) for c in components if isinstance(c, dict)], indent=2, ensure_ascii=False)}

OUTPUT REQUIREMENT:
Return ONLY valid JSON (no explanation, no markdown formatting):
{{
    "target_component_id": {{"x": number, "y": number, "z": number}}
}}

Coordinate conventions:
- x, y, z are absolute global coordinates
- Unit: mm (consistent with dimensions in KG)
- Grounded root {ground_root_id}: (0, 0, 0)
- Other coordinates: calculated from position_parent chain
"""
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }],
                    temperature=0.0,
                    timeout=180.0  # 3闂傚倷绀侀幉锛勬暜閹烘嚦娑樷攽鐎ｎ亞顔囬梺鐟板⒔缁垶寮查浣瑰弿婵妫楁晶缁樹繆閺屻儰鎲鹃柡?00+缂傚倸鍊搁崐椋庣矆娴ｈ　鍋撳闂寸盎闁宠閰ｆ慨鈧柕鍫濇閸?D婵犵數鍋犻幓顏嗗緤閻ｅ瞼鐭撻柛顐ｆ礃閸嬵亪鏌涢埄鍐槈缂佺姵濞婇弻鏇熺節韫囨稒顎嶉梺缁樺笂缁瑥顫忔繝姘倞闁挎繂鎳嶆竟鏇㈡⒑閼姐倕鏋戞繛鍙夊灴閹偤鏁冮埀顒傚弲闂佺鍕垫畷闁抽攱鍔欓弻鐔虹矙閸噮鍔夊銇礁娲﹂埛?
                )
                
                try:
                    llm_output = response.choices[0].message.content.strip()
                    
                    # Try to extract JSON if it's wrapped in markdown
                    if "```json" in llm_output:
                        llm_output = llm_output.split("```json")[1].split("```")[0].strip()
                    elif "```" in llm_output:
                        llm_output = llm_output.split("```")[1].split("```")[0].strip()
                    
                    llm_positions = json.loads(llm_output)
                    
                    if not isinstance(llm_positions, dict):
                        warnings.append(f"LLM returned non-dict output: {type(llm_positions)}")
                        llm_call_succeeded = False
                    else:
                        # Validate LLM output before accepting
                        if _validate_llm_positions(
                            llm_positions,
                            kg,
                            parent_chains,
                            warnings,
                            ground_root_id=ground_root_id,
                            llm_target_ids=llm_target_ids,
                        ):
                            # Validation passed - accept LLM positions
                            for comp_id in llm_target_ids:
                                pos = llm_positions.get(comp_id)
                                if isinstance(pos, dict) and "x" in pos and "y" in pos and "z" in pos:
                                    positions[comp_id] = {
                                        "x": float(pos["x"]),
                                        "y": float(pos["y"]),
                                        "z": float(pos["z"])
                                    }
                            llm_call_succeeded = True
                            inference_mode = "hybrid" if "deterministic" in inference_mode else "llm_hierarchical"
                            warnings.append("LLM inference completed and validated successfully")
                        else:
                            # Validation failed - will fallback to deterministic only
                            llm_call_succeeded = False
                            warnings.append("LLM output failed validation; will use fallback")
                
                except json.JSONDecodeError as e:
                    warnings.append(f"LLM position inference failed to parse JSON: {str(e)}")
                    llm_call_succeeded = False
                
            except Exception as e:
                warnings.append(f"LLM position inference error: {str(e)}")
                llm_call_succeeded = False
        else:
            warnings.append("LLM not configured; will use deterministic inference only")
            llm_call_succeeded = False
            llm_attempted = False
            if not inference_mode.startswith("deterministic"):
                inference_mode = "deterministic_only"
    else:
        if not inference_mode.startswith("deterministic"):
            inference_mode = "deterministic_only"
        if not llm_target_ids:
            warnings.append("LLM layout skipped: no target components require LLM positioning")
    
    # ===== PHASE 4: Fallback if LLM failed or not available =====
    if llm_attempted and not llm_call_succeeded:
        # LLM was attempted but failed validation or threw error
        # Fall back to deterministic: root at origin, others at origin too (conservative)
        warnings.append("Using fallback mode: only explicitly positioned components placed, others at origin")
        inference_mode = "fallback_origin_only"
        
        # Ensure all unplaced components are at least at origin with their parent
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id")
            if comp_id and comp_id not in positions:
                positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    
    # Final fallback: ensure all components have at least a position
    if not positions:
        warnings.append("No layout positions inferred; all components at origin (fallback)")
        inference_mode = "fallback_origin_only"
    
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str):
            comp_id = comp.get("id")
            if comp_id not in positions:
                positions[comp_id] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    return {
        "layout_positions": positions,
        "inference_mode": inference_mode,
        "warnings": warnings,
        "parent_chains": parent_chains,
        "ground_root_id": ground_root_id,
        "llm_target_ids": llm_target_ids,
        "root_ratio": round(root_ratio, 4),
        "root_count": root_count,
    }


def _build_connectivity_graph(kg: Dict[str, Any]) -> Dict[str, set[str]]:
    graph: Dict[str, set[str]] = {}
    reqs = kg.get("connection_requirements")
    if not isinstance(reqs, list):
        return graph
    for req in reqs:
        if not isinstance(req, dict):
            continue
        between = req.get("between")
        if not isinstance(between, list) or len(between) < 2:
            continue
        a = between[0] if isinstance(between[0], str) else None
        b = between[1] if isinstance(between[1], str) else None
        if not a or not b:
            continue
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    return graph


def _infer_aabb_size_mm(*, component_id: str, kg: Dict[str, Any]) -> tuple[float, float, float]:
    comps = kg.get("components")
    dims: dict[str, Any] = {}
    comp_type = ""
    shape_type = ""

    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            if c.get("id") != component_id:
                continue
            comp_type = c.get("type") if isinstance(c.get("type"), str) else ""
            shape = c.get("shape_semantics") if isinstance(c.get("shape_semantics"), dict) else {}
            shape_type = shape.get("type") if isinstance(shape.get("type"), str) else ""
            params = c.get("parameters")
            if isinstance(params, dict):
                dims = dict(params)
            else:
                raw_dims = c.get("dimensions")
                if isinstance(raw_dims, dict):
                    dims = dict(raw_dims)
            break

    def _num(key: str) -> float | None:
        v = dims.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        return None

    radius = _num("outer_radius")
    if radius is None:
        diameter = _num("diameter")
        if diameter is None:
            diameter = _num("outer_diameter")
        if diameter is not None:
            radius = diameter / 2.0
    if radius is None:
        nominal = _num("nominal_diameter")
        if nominal is not None:
            radius = max(1.0, nominal / 2.0)

    thickness = _num("thickness")
    if thickness is None:
        thickness = _num("width")
    if radius is not None and thickness is not None:
        d = max(1.0, float(radius) * 2.0)
        t = max(1.0, float(thickness))
        return (d, d, t)

    length = _num("length")
    width = _num("width")
    height = _num("height")
    if height is None:
        height = _num("thickness")
    if length is not None and width is not None and height is not None:
        return (max(1.0, float(length)), max(1.0, float(width)), max(1.0, float(height)))

    if comp_type == "plate" or shape_type == "radial_plate":
        hub_radius = _num("hub_radius")
        arm_length = _num("arm_length")
        t = height if height is not None else 6.0
        if hub_radius is not None or arm_length is not None:
            hr = float(hub_radius or 20.0)
            al = float(arm_length or 60.0)
            span = max(1.0, 2.0 * (hr + al))
            return (span, span, max(1.0, float(t)))

    return (30.0, 30.0, 30.0)


def _compute_initial_placements(
    *,
    kg: Dict[str, Any],
    component_ids: List[str],
    semantics: Mapping[str, Any] | None = None,
    margin_mm: float = 5.0,
    ground_component_id_override: str | None = None,
) -> Dict[str, Any]:
    import math
    import re

    graph = _build_connectivity_graph(kg)
    comp_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id")): c
        for c in (kg.get("components") or [])
        if isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id")
    }
    component_type_by_id: Dict[str, str] = {
        component_id: str(component.get("type") or "")
        for component_id, component in comp_by_id.items()
        if isinstance(component, Mapping)
    }

    def _is_executable_placement_component(component_id: str) -> bool:
        comp = comp_by_id.get(component_id)
        if not isinstance(comp, Mapping):
            return True
        kind = str(comp.get("kind") or "").strip().lower()
        if kind == "assembly_node":
            return False
        policy = str(comp.get("modeling_policy") or "").strip().lower()
        if policy in {"container_only", "reference_only"}:
            return False
        if comp.get("must_model") is False:
            return False
        if comp.get("has_geometry") is False:
            return False
        shape = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        shape_type = str(shape.get("type") or "").strip().lower()
        if shape_type == "assembly_node":
            return False
        return True

    candidates = [
        cid
        for cid in component_ids
        if isinstance(cid, str) and cid and _is_executable_placement_component(cid)
    ]
    if not candidates:
        return {"initial_placements": [], "summary": {"component_count": 0}}
    candidate_set = set(candidates)

    requested_ground: str | None = None
    if isinstance(ground_component_id_override, str) and ground_component_id_override.strip():
        requested_ground = ground_component_id_override.strip()

    reqs = kg.get("connection_requirements")
    req_list = reqs if isinstance(reqs, list) else []
    synthetic_rigid_pairs: set[tuple[str, str]] = set()

    def _edge_kind(a: str, b: str) -> str:
        # Deterministic, best-effort classification for placement pre-assembly.
        key = tuple(sorted((a, b)))
        if key in synthetic_rigid_pairs:
            return "rigid"
        for req in req_list:
            if not isinstance(req, dict):
                continue
            between = req.get("between")
            if not isinstance(between, list) or len(between) < 2:
                continue
            aa = between[0] if isinstance(between[0], str) else None
            bb = between[1] if isinstance(between[1], str) else None
            if not aa or not bb:
                continue
            if tuple(sorted((aa, bb))) != key:
                continue
            intent = req.get("constraint_intent")
            purpose = req.get("purpose")
            roles = req.get("roles")
            intent_s = str(intent).lower() if isinstance(intent, str) else ""
            purpose_s = str(purpose).lower() if isinstance(purpose, str) else ""
            roles_s = " ".join([str(r).lower() for r in roles]) if isinstance(roles, list) else ""

            if intent_s in {"revolute", "coaxial", "hinge"} or purpose_s in {"rotation", "revolute", "hinge"} or "rotation" in roles_s:
                return "coaxial"
            # Planar mates should be treated as rigid for initial placement grouping,
            # so overlap resolution cannot shear them apart.
            if (
                intent_s in {"planar_mate", "planar", "planar_joint"}
                or purpose_s in {"planar_mate", "planar", "coplanar", "face_alignment"}
                or "planar" in roles_s
                or "coplanar" in roles_s
            ):
                return "rigid"
            if (
                intent_s in {"rigid", "fixed", "bolted", "fastening_mechanism", "bearing_fit"}
                or purpose_s in {"structural_fixation", "load_support", "fastening_mechanism", "bolted", "bearing_fit"}
            ):
                return "rigid"
            return "generic"
        return "generic"

    def _build_allow_overlap_group_lookup() -> Dict[str, str]:
        coax_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        for a in candidates:
            for b in graph.get(a, set()):
                if b not in candidates or a == b:
                    continue
                if _edge_kind(a, b) == "coaxial":
                    coax_adj[a].add(b)

        lookup: Dict[str, str] = {}
        seen: set[str] = set()
        for start in sorted(candidates):
            if start in seen or not coax_adj.get(start):
                continue
            stack = [start]
            seen.add(start)
            members: List[str] = []
            while stack:
                cur = stack.pop()
                members.append(cur)
                for nb in coax_adj.get(cur, set()):
                    if nb in seen:
                        continue
                    seen.add(nb)
                    stack.append(nb)
            if len(members) < 2:
                continue
            chain_set = set(members)
            extended = True
            while extended:
                extended = False
                for cid in candidates:
                    if cid in chain_set:
                        continue
                    comp = comp_by_id.get(cid, {})
                    parent_id = comp.get("position_parent")
                    if isinstance(parent_id, str) and parent_id in chain_set:
                        chain_set.add(cid)
                        extended = True
            group_key = f"coaxial::{sorted(chain_set)[0]}"
            for cid in chain_set:
                lookup[cid] = group_key
        return lookup

    def _is_hierarchy_overlap_candidate(component_id: str) -> bool:
        comp = comp_by_id.get(component_id, {})
        comp_type = str(comp.get("type") or "").strip().lower()
        if comp_type in {
            "wheel", "hub", "rim", "tire", "axle", "shaft", "bearing",
            "spacer", "sleeve", "bushing", "roller", "pulley",
        }:
            return True
        shape = comp.get("shape_semantics") if isinstance(comp.get("shape_semantics"), Mapping) else {}
        shape_type = str(shape.get("type") or "").strip().lower()
        return shape_type in {"cylindrical", "annular"}

    def _augment_allow_overlap_lookup_from_hierarchy(lookup: Dict[str, str]) -> Dict[str, str]:
        root_to_members: Dict[str, List[str]] = {}
        for cid in candidates:
            current = cid
            visited_local: set[str] = {cid}
            while True:
                parent = comp_by_id.get(current, {}).get("position_parent")
                if not isinstance(parent, str) or parent not in candidates or parent in visited_local:
                    break
                visited_local.add(parent)
                current = parent
            root_to_members.setdefault(current, []).append(cid)

        for root_id, members in sorted(root_to_members.items(), key=lambda item: item[0]):
            eligible = [
                cid for cid in sorted(set(members))
                if cid == root_id or _is_hierarchy_overlap_candidate(cid)
            ]
            descendant_eligible = [cid for cid in eligible if cid != root_id]
            anchored = [cid for cid in eligible if cid in lookup]
            if len(descendant_eligible) < 2 and not anchored:
                continue
            group_key = lookup.get(anchored[0]) if anchored else f"hierarchy_overlap::{root_id}"
            for cid in eligible:
                lookup.setdefault(cid, group_key)
        return lookup

    allow_overlap_group_by_component = _augment_allow_overlap_lookup_from_hierarchy(
        _build_allow_overlap_group_lookup()
    )

    def _shared_allow_overlap_group(a: str, b: str) -> bool:
        ga = allow_overlap_group_by_component.get(a)
        return bool(ga) and ga == allow_overlap_group_by_component.get(b)

    def degree(cid: str) -> int:
        return len(graph.get(cid, set()))

    def _select_grounded_root() -> str:
        if isinstance(ground_component_id_override, str) and ground_component_id_override.strip():
            ov = ground_component_id_override.strip()
            if ov in candidates:
                return ov
        # Prefer obvious structural roots to keep assembly near-origin.
        for preferred in (
            "module_support_housing",
            "support_housing",
            "fixed_support_housing",
            "central_hub",
            "hub",
            "base",
            "frame",
            "carrier",
            "root",
        ):
            if preferred in candidates:
                return preferred
        # Fallback: highest degree.
        return max(candidates, key=lambda cid: (degree(cid), cid))

    grounded = _select_grounded_root()
    applied_override = bool(requested_ground and grounded == requested_ground)

    sizes = {cid: _infer_aabb_size_mm(component_id=cid, kg=kg) for cid in candidates}
    placed: Dict[str, Dict[str, float]] = {grounded: {"x": 0.0, "y": 0.0, "z": 0.0}}
    yaw_by_cid: Dict[str, float] = {grounded: 0.0}
    orientation_unknown: Dict[str, bool] = {}
    preplaced_wheel_arms: set[str] = set()

    from collections import deque

    q: deque[str] = deque([grounded])
    visited: set[str] = {grounded}

    # Special-case array layout for wheel_arm_<n> to avoid deterministic overlap.
    wheel_arm_pattern = re.compile(r"wheel_arm_(\d+)$", re.IGNORECASE)
    wheel_arm_candidates: List[tuple[int, str]] = []
    for cid in candidates:
        match = wheel_arm_pattern.fullmatch(cid)
        if not match:
            continue
        try:
            idx = int(match.group(1))
        except Exception:
            continue
        wheel_arm_candidates.append((idx, cid))

    if len(wheel_arm_candidates) >= 3:
        wheel_arm_candidates = sorted(wheel_arm_candidates, key=lambda item: (item[0], item[1]))
        arm_size_x = max(float(sizes.get(cid, (30.0, 30.0, 30.0))[0]) for _, cid in wheel_arm_candidates)
        radius_mm = max(float(arm_size_x), 80.0) + float(margin_mm)
        center = placed.get(grounded, {"x": 0.0, "y": 0.0, "z": 0.0})
        cx, cy, cz = float(center.get("x", 0.0)), float(center.get("y", 0.0)), float(center.get("z", 0.0))
        arm_count = len(wheel_arm_candidates)
        for order, (_, cid) in enumerate(wheel_arm_candidates):
            angle_deg = 360.0 * (float(order) / float(arm_count))
            angle_rad = math.radians(angle_deg)
            z_val = float(placed.get(cid, {}).get("z", cz if isinstance(cz, (int, float)) else 0.0))
            placed[cid] = {
                "x": cx + radius_mm * math.cos(angle_rad),
                "y": cy + radius_mm * math.sin(angle_rad),
                "z": z_val,
            }
            yaw_by_cid[cid] = float(angle_deg)
            preplaced_wheel_arms.add(cid)
            if cid not in visited:
                visited.add(cid)
                q.append(cid)

    def _radial_distance_mm(a: str, b: str) -> float:
        asx, asy, _ = sizes.get(a, (30.0, 30.0, 30.0))
        bsx, bsy, _ = sizes.get(b, (30.0, 30.0, 30.0))
        ar = 0.5 * max(float(asx), float(asy))
        br = 0.5 * max(float(bsx), float(bsy))
        return max(10.0, ar + br + float(margin_mm))

    def _axial_distance_mm(a: str, b: str) -> float:
        _, _, az = sizes.get(a, (30.0, 30.0, 30.0))
        _, _, bz = sizes.get(b, (30.0, 30.0, 30.0))
        return max(10.0, 0.5 * float(az) + 0.5 * float(bz) + float(margin_mm))

    def _place_near(parent: str, child: str, *, slot_index: int, sibling_count: int) -> None:
        if child in placed or parent not in placed:
            return
        base = placed[parent]
        kind = _edge_kind(parent, child)

        px, py, pz = float(base.get("x", 0.0)), float(base.get("y", 0.0)), float(base.get("z", 0.0))

        if kind == "coaxial":
            if _shared_allow_overlap_group(parent, child):
                placed[child] = {"x": px, "y": py, "z": pz}
            else:
                dz = _axial_distance_mm(parent, child)
                placed[child] = {"x": px, "y": py, "z": pz + dz}
            yaw_by_cid[child] = 0.0
            orientation_unknown[child] = True
            return


        if kind == "rigid":
            dx = _radial_distance_mm(parent, child)
            sign = -1.0 if (slot_index % 2 == 1) else 1.0
            placed[child] = {"x": px + sign * dx, "y": py, "z": pz}
            yaw_by_cid[child] = 0.0
            return

        # Generic fallback: small offset in X.
        dx = max(10.0, float(sizes.get(child, (30.0, 30.0, 30.0))[0]) + float(margin_mm))
        placed[child] = {"x": px + dx, "y": py, "z": pz}

        yaw_by_cid[child] = 0.0

    while q:
        cur = q.popleft()
        nbs_raw = [nb for nb in graph.get(cur, set()) if nb in candidates]

        def _prio(nb: str) -> tuple[int, str]:
            k = _edge_kind(cur, nb)
            if k == "coaxial":
                return (0, nb)
            if k == "rigid":
                return (1, nb)
            return (2, nb)

        nbs = sorted(nbs_raw, key=_prio)
        for idx, nb in enumerate(nbs):
            if nb not in visited:
                visited.add(nb)
                q.append(nb)
            if nb not in placed:
                _place_near(cur, nb, slot_index=idx, sibling_count=len(nbs))

    # Place disconnected components on an outer ring.
    unplaced = [cid for cid in candidates if cid not in placed]
    if unplaced:
        base_r = 0.0
        for cid in placed:
            if cid == grounded:
                continue
            base_r = max(base_r, math.hypot(float(placed[cid]["x"]), float(placed[cid]["y"])))
        base_r = max(50.0, base_r + 50.0)
        for i, cid in enumerate(sorted(unplaced)):
            ang = 2.0 * math.pi * (float(i) / float(max(1, len(unplaced))))
            r = base_r + _radial_distance_mm(grounded, cid)
            placed[cid] = {"x": r * math.cos(ang), "y": r * math.sin(ang), "z": 0.0}
            yaw_by_cid[cid] = float(math.degrees(ang))

    # Parent-follow pass: enforce position_parent hierarchy deterministically.
    # Children inherit parent frame with small role-based offset.
    role_offsets_mm: Dict[str, Dict[str, float]] = {
        "rim": {"x": 0.0, "y": 0.0, "z": 0.0},
        "tire": {"x": 0.0, "y": 0.0, "z": 1.0},
        "hub": {"x": 0.0, "y": 0.0, "z": 0.0},
        "axle": {"x": 0.0, "y": 0.0, "z": 1.0},
    }

    def _role_of(comp: Mapping[str, Any]) -> str:
        role = comp.get("role_in_parent")
        if isinstance(role, str) and role.strip():
            return role.strip().lower()
        ctype = str(comp.get("type") or "").strip().lower()
        if ctype:
            return ctype
        cid = str(comp.get("id") or "").strip().lower()
        for tok in ("rim", "tire", "hub", "axle"):
            if tok in cid:
                return tok
        return ""

    children_by_parent: Dict[str, List[str]] = {}
    roots: List[str] = []
    for cid in candidates:
        comp = comp_by_id.get(cid, {})
        parent = comp.get("position_parent")
        if isinstance(parent, str) and parent in candidates:
            children_by_parent.setdefault(parent, []).append(cid)
        else:
            roots.append(cid)

    from collections import deque as _dq
    q2: _dq[str] = _dq(sorted(set(roots)))
    seen2: set[str] = set()
    while q2:
        parent = q2.popleft()
        if parent in seen2:
            continue
        seen2.add(parent)
        parent_pos = placed.get(parent, {"x": 0.0, "y": 0.0, "z": 0.0})
        for child in sorted(children_by_parent.get(parent, [])):
            if child in preplaced_wheel_arms:
                q2.append(child)
                continue
            comp = comp_by_id.get(child, {})
            role = _role_of(comp)
            if _shared_allow_overlap_group(parent, child):
                off = {"x": 0.0, "y": 0.0, "z": 0.0}
            else:
                off = role_offsets_mm.get(role, {"x": 0.0, "y": 0.0, "z": 0.0})
            placed[child] = {
                "x": float(parent_pos.get("x", 0.0)) + float(off.get("x", 0.0)),
                "y": float(parent_pos.get("y", 0.0)) + float(off.get("y", 0.0)),
                "z": float(parent_pos.get("z", 0.0)) + float(off.get("z", 0.0)),
            }
            yaw_by_cid[child] = float(yaw_by_cid.get(parent, 0.0))
            q2.append(child)

    def _base_connection_id(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        base = value.split("@", 1)[0].strip()
        return base or None

    def _collect_anchor_semantics() -> List[Dict[str, Any]]:
        placements_src = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
        if not isinstance(placements_src, list):
            return []
        deduped: Dict[str, Dict[str, Any]] = {}
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            status = str(placement.get("status") or "").strip().lower()
            if placement.get("requires_clarification") is True or status in {"requires_clarification", "unresolved", "blocked", "rejected"}:
                continue
            anchor = placement.get("anchor_semantics")
            if not isinstance(anchor, Mapping):
                continue
            base_id = _base_connection_id(placement.get("connection_id"))
            if not base_id or base_id in deduped:
                continue
            reference_component_id = anchor.get("reference_component_id")
            moving_component_id = anchor.get("moving_component_id")
            if reference_component_id not in candidates or moving_component_id not in candidates:
                continue
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            anchor_copy = dict(anchor)
            reference_anchor = dict(anchor_copy.get("reference_anchor") or {}) if isinstance(anchor_copy.get("reference_anchor"), Mapping) else {}
            moving_anchor = dict(anchor_copy.get("moving_anchor") or {}) if isinstance(anchor_copy.get("moving_anchor"), Mapping) else {}
            if reference_anchor:
                if not isinstance(reference_anchor.get("radius_mm"), (int, float)):
                    for value in (pattern.get("pattern_radius_mm"), pattern.get("pattern_radius")):
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            reference_anchor["radius_mm"] = float(value)
                            break
                if not isinstance(reference_anchor.get("phase_rad"), (int, float)):
                    start_angle_rad = pattern.get("start_angle_rad")
                    if isinstance(start_angle_rad, (int, float)):
                        reference_anchor["phase_rad"] = float(start_angle_rad)
                if not isinstance(reference_anchor.get("phase_deg"), (int, float)):
                    for value in (pattern.get("start_angle"), pattern.get("phase_deg")):
                        if isinstance(value, (int, float)):
                            reference_anchor["phase_deg"] = float(value)
                            break
                anchor_copy["reference_anchor"] = reference_anchor
            if moving_anchor:
                if not isinstance(moving_anchor.get("inset_mm"), (int, float)):
                    for value in (pattern.get("offset_from_edge"), pattern.get("edge_margin_mm")):
                        if isinstance(value, (int, float)) and float(value) > 0.0:
                            moving_anchor["inset_mm"] = float(value)
                            break
                anchor_copy["moving_anchor"] = moving_anchor
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            if isinstance(geometric_semantics, Mapping) and geometric_semantics:
                anchor_copy["geometric_semantics"] = dict(geometric_semantics)
            mechanism_name = placement.get("connection_mechanism") if isinstance(placement.get("connection_mechanism"), str) else None
            if isinstance(mechanism_name, str) and mechanism_name.strip():
                anchor_copy["connection_mechanism"] = mechanism_name.strip().lower()
            deduped[base_id] = anchor_copy
        return [deduped[key] for key in sorted(deduped.keys())]

    subtree_cache: Dict[str, List[str]] = {}

    def _root_component_id(component_id: str) -> str:
        current = component_id
        seen: set[str] = set()
        while current not in seen:
            seen.add(current)
            parent = comp_by_id.get(current, {}).get("position_parent")
            if not isinstance(parent, str) or parent not in candidates:
                break
            current = parent
        return current

    def _subtree_members(root_id: str) -> List[str]:
        cached = subtree_cache.get(root_id)
        if cached is not None:
            return list(cached)
        members: List[str] = []
        stack = [root_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in candidates:
                members.append(current)
            for child in children_by_parent.get(current, []):
                if child not in seen:
                    stack.append(child)
        members = sorted(members)
        subtree_cache[root_id] = members
        return list(members)

    def _component_dims(component_id: str) -> Mapping[str, Any]:
        comp = comp_by_id.get(component_id, {})
        dims = comp.get("dimensions") if isinstance(comp.get("dimensions"), Mapping) else {}
        params = comp.get("parameters") if isinstance(comp.get("parameters"), Mapping) else {}
        merged: Dict[str, Any] = {}
        if dims:
            merged.update(dims)
        if params:
            for key, value in params.items():
                if key not in merged:
                    merged[key] = value
        return merged

    def _component_length_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("length", "arm_length", "depth"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        return max(1.0, float(sizes.get(component_id, (30.0, 30.0, 30.0))[0]))

    def _component_radius_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("outer_radius", "radius"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        for key in ("diameter", "outer_diameter", "nominal_diameter"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value) / 2.0
        size = sizes.get(component_id, (30.0, 30.0, 30.0))
        return max(1.0, 0.5 * max(float(size[0]), float(size[1])))

    def _component_thickness_mm(component_id: str) -> float:
        dims = _component_dims(component_id)
        for key in ("thickness", "width", "height"):
            value = dims.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return float(value)
        return max(1.0, float(sizes.get(component_id, (30.0, 30.0, 30.0))[2]))

    def _rotate_xy(dx: float, dy: float, yaw_deg: float) -> Dict[str, float]:
        angle = math.radians(float(yaw_deg))
        c = math.cos(angle)
        s = math.sin(angle)
        return {
            "x": float(dx) * c - float(dy) * s,
            "y": float(dx) * s + float(dy) * c,
        }

    def _anchor_world_point(
        component_id: str,
        anchor_def: Mapping[str, Any],
        *,
        counterpart_id: str | None = None,
    ) -> Dict[str, float] | None:
        if component_id not in placed:
            return None
        center = placed.get(component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        cx = float(center.get("x", 0.0))
        cy = float(center.get("y", 0.0))
        cz = float(center.get("z", 0.0))
        kind = str(anchor_def.get("kind") or "component_center").strip().lower()
        axis = str(anchor_def.get("axis") or "x").strip().lower()
        yaw_deg = float(yaw_by_cid.get(component_id, 0.0))

        if kind == "component_center":
            return {"x": cx, "y": cy, "z": cz}

        if kind in {"distal_end", "proximal_end"}:
            half_length = 0.5 * _component_length_mm(component_id)
            sign = 1.0 if kind == "distal_end" else -1.0
            if axis == "z":
                return {"x": cx, "y": cy, "z": cz + sign * half_length}
            local_dx = sign * half_length if axis != "y" else 0.0
            local_dy = sign * half_length if axis == "y" else 0.0
            rotated = _rotate_xy(local_dx, local_dy, yaw_deg)
            return {"x": cx + rotated["x"], "y": cy + rotated["y"], "z": cz}

        if kind == "radial_mount_perimeter":
            radius = _component_radius_mm(component_id)
            vx = 0.0
            vy = 0.0
            if isinstance(counterpart_id, str) and counterpart_id in placed:
                counterpart_pos = placed.get(counterpart_id, {"x": 0.0, "y": 0.0, "z": 0.0})
                vx = float(counterpart_pos.get("x", 0.0)) - cx
                vy = float(counterpart_pos.get("y", 0.0)) - cy
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                base = _rotate_xy(1.0, 0.0, yaw_deg)
                vx = float(base["x"])
                vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                return {"x": cx, "y": cy, "z": cz}
            return {
                "x": cx + radius * (vx / mag),
                "y": cy + radius * (vy / mag),
                "z": cz,
            }

        if kind in {"axial_face_perimeter_max", "axial_face_perimeter_min"}:
            radius_value = anchor_def.get("radius_mm")
            radius = float(radius_value) if isinstance(radius_value, (int, float)) and float(radius_value) > 0.0 else _component_radius_mm(component_id)
            thickness_half = 0.5 * _component_thickness_mm(component_id)
            z_sign = 1.0 if kind.endswith("_max") else -1.0
            phase_rad_value = anchor_def.get("phase_rad")
            if isinstance(phase_rad_value, (int, float)):
                phase_rad = float(phase_rad_value)
            else:
                phase_deg_value = anchor_def.get("phase_deg")
                phase_rad = math.radians(float(phase_deg_value)) if isinstance(phase_deg_value, (int, float)) else None
            if isinstance(phase_rad, (int, float)):
                return {
                    "x": cx + radius * math.cos(float(phase_rad)),
                    "y": cy + radius * math.sin(float(phase_rad)),
                    "z": cz + z_sign * thickness_half,
                }
            vx = 0.0
            vy = 0.0
            if isinstance(counterpart_id, str) and counterpart_id in placed:
                counterpart_pos = placed.get(counterpart_id, {"x": 0.0, "y": 0.0, "z": 0.0})
                vx = float(counterpart_pos.get("x", 0.0)) - cx
                vy = float(counterpart_pos.get("y", 0.0)) - cy
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                base = _rotate_xy(1.0, 0.0, yaw_deg)
                vx = float(base["x"])
                vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                return {"x": cx, "y": cy, "z": cz + z_sign * thickness_half}
            return {
                "x": cx + radius * (vx / mag),
                "y": cy + radius * (vy / mag),
                "z": cz + z_sign * thickness_half,
            }

        if kind in {"proximal_mount_face_min", "proximal_mount_face_max"}:
            half_length = 0.5 * _component_length_mm(component_id)
            half_thickness = 0.5 * _component_thickness_mm(component_id)
            inset_value = anchor_def.get("inset_mm")
            inset = float(inset_value) if isinstance(inset_value, (int, float)) and float(inset_value) > 0.0 else 0.0
            local_dx = (-half_length + inset) if axis != "y" else 0.0
            local_dy = (-half_length + inset) if axis == "y" else 0.0
            rotated = _rotate_xy(local_dx, local_dy, yaw_deg)
            z_sign = -1.0 if kind.endswith("_min") else 1.0
            return {
                "x": cx + rotated["x"],
                "y": cy + rotated["y"],
                "z": cz + z_sign * half_thickness,
            }

        return {"x": cx, "y": cy, "z": cz}

    def _apply_translation_to_members(members: List[str], dx: float, dy: float, dz: float) -> None:
        for member in members:
            if member not in placed:
                continue
            placed[member] = {
                "x": float(placed[member].get("x", 0.0)) + float(dx),
                "y": float(placed[member].get("y", 0.0)) + float(dy),
                "z": float(placed[member].get("z", 0.0)) + float(dz),
            }

    def _anchor_requires_axis_only_alignment(anchor: Mapping[str, Any]) -> bool:
        mechanism_name = str(anchor.get("connection_mechanism") or "").strip().lower()
        if mechanism_name != "shaft_bore_fit":
            return False
        geometric_semantics = anchor.get("geometric_semantics") if isinstance(anchor.get("geometric_semantics"), Mapping) else {}
        contact_model = str(geometric_semantics.get("contact_model") or "").strip().lower()
        axial_stack_policy = str(geometric_semantics.get("axial_stack_policy") or "").strip().lower()
        return (
            contact_model in {"coaxial_revolute_fit", "bearing_inner_race_revolute_fit"}
            or axial_stack_policy == "preserve_independent_axial_stack"
        )

    def _wheel_group_members_for_axle(axle_id: str) -> List[str]:
        match = re.match(r"^wheel_(\d+)_axle$", axle_id, flags=re.IGNORECASE)
        if not match:
            return []
        suffix = match.group(1)
        root_id = f"wheel_{suffix}"
        prefix = root_id + "_"
        members: List[str] = []

        def _is_wheel_fastener_like(component_id: str) -> bool:
            comp = comp_by_id.get(component_id, {}) if isinstance(comp_by_id.get(component_id), Mapping) else {}
            comp_type = str(comp.get("type") or "").strip().lower()
            part_kind = str(comp.get("part_kind") or "").strip().lower()
            if comp_type in {"fastener", "bolt", "nut", "washer", "screw"}:
                return True
            if part_kind in {"fastener", "fastener_bundle", "hardware", "hardware_bundle"}:
                return True
            component_id_l = component_id.strip().lower()
            return any(token in component_id_l for token in ("fastener", "bolt", "nut", "washer", "screw"))

        for cid in candidates:
            if cid == axle_id:
                continue
            if _is_wheel_fastener_like(cid):
                continue
            if cid == root_id or (cid.startswith(prefix) and not cid.startswith(f"wheel_arm_{suffix}")):
                members.append(cid)
        return sorted(set(members))

    def _wheel_rotating_stack_members_for_axle(axle_id: str) -> List[str]:
        rotating_types = {
            "wheel",
            "hub",
            "rim",
            "tire",
            "bearing",
            "spacer",
            "sleeve",
            "bushing",
            "roller",
            "pulley",
        }
        members: List[str] = []
        for cid in _wheel_group_members_for_axle(axle_id):
            comp = comp_by_id.get(cid, {}) if isinstance(comp_by_id.get(cid), Mapping) else {}
            comp_type = str(comp.get("type") or "").strip().lower()
            if comp_type in rotating_types:
                members.append(cid)
                continue
            cid_l = cid.strip().lower()
            if any(token in cid_l for token in ("hub", "rim", "tire", "bearing", "spacer", "sleeve", "bushing", "roller", "pulley")):
                members.append(cid)
        return sorted(set(members))

    def _wheel_group_width_mm(member_ids: List[str]) -> float:
        widths: List[float] = []
        for member_id in member_ids:
            dims = _component_dims(member_id)
            for key in ("width", "thickness", "height"):
                value = dims.get(key)
                if isinstance(value, (int, float)) and float(value) > 0.0:
                    widths.append(float(value))
                    break
        return max(widths) if widths else 12.0

    anchor_adjustments: List[Dict[str, Any]] = []
    anchor_semantics_list = _collect_anchor_semantics()
    anchor_coupled_pairs: set[tuple[str, str]] = set()
    for anchor in anchor_semantics_list:
        if not isinstance(anchor, Mapping):
            continue
        reference_component_id = anchor.get("reference_component_id")
        moving_component_id = anchor.get("moving_component_id")
        if (
            isinstance(reference_component_id, str)
            and isinstance(moving_component_id, str)
            and reference_component_id in candidates
            and moving_component_id in candidates
            and reference_component_id != moving_component_id
        ):
            anchor_coupled_pairs.add(tuple(sorted((reference_component_id, moving_component_id))))
    if anchor_semantics_list:
        for _pass_index in range(max(1, len(anchor_semantics_list))):
            moved_any = False
            for anchor in anchor_semantics_list:
                reference_component_id = anchor.get("reference_component_id")
                moving_component_id = anchor.get("moving_component_id")
                reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
                moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
                if reference_component_id not in candidates or moving_component_id not in candidates:
                    continue

                moving_root = _root_component_id(str(moving_component_id))
                reference_root = _root_component_id(str(reference_component_id))
                if moving_root == reference_root:
                    continue

                moving_members = _subtree_members(moving_root)
                if reference_component_id in moving_members:
                    continue

                reference_point = _anchor_world_point(
                    str(reference_component_id),
                    reference_anchor,
                    counterpart_id=str(moving_component_id),
                )
                moving_point = _anchor_world_point(
                    str(moving_component_id),
                    moving_anchor,
                    counterpart_id=str(reference_component_id),
                )
                if not isinstance(reference_point, Mapping) or not isinstance(moving_point, Mapping):
                    continue

                dx = float(reference_point.get("x", 0.0)) - float(moving_point.get("x", 0.0))
                dy = float(reference_point.get("y", 0.0)) - float(moving_point.get("y", 0.0))
                dz = float(reference_point.get("z", 0.0)) - float(moving_point.get("z", 0.0))
                if _anchor_requires_axis_only_alignment(anchor):
                    dz = 0.0

                orientation_policy = str(anchor.get("orientation_policy") or "preserve").strip().lower()
                desired_yaw: float | None = None
                if orientation_policy == "inherit_reference_yaw":
                    desired_yaw = float(yaw_by_cid.get(str(reference_component_id), yaw_by_cid.get(reference_root, 0.0)))
                elif orientation_policy == "radial_from_reference_center":
                    ref_center = placed.get(str(reference_component_id), {"x": 0.0, "y": 0.0, "z": 0.0})
                    vx = float(reference_point.get("x", 0.0)) - float(ref_center.get("x", 0.0))
                    vy = float(reference_point.get("y", 0.0)) - float(ref_center.get("y", 0.0))
                    if abs(vx) >= 1e-9 or abs(vy) >= 1e-9:
                        desired_yaw = float(math.degrees(math.atan2(vy, vx)))

                current_root_yaw = float(yaw_by_cid.get(moving_root, 0.0))
                translation_needed = abs(dx) > 1e-6 or abs(dy) > 1e-6 or abs(dz) > 1e-6
                yaw_needed = desired_yaw is not None and abs(float(desired_yaw) - current_root_yaw) > 1e-6
                if not translation_needed and not yaw_needed:
                    continue

                _apply_translation_to_members(moving_members, dx, dy, dz)
                if desired_yaw is not None:
                    for member in moving_members:
                        yaw_by_cid[member] = float(desired_yaw)

                anchor_adjustments.append(
                    {
                        "reference_component_id": str(reference_component_id),
                        "moving_component_id": str(moving_component_id),
                        "moving_root_component_id": moving_root,
                        "relation_type": str(anchor.get("relation_type") or "unknown"),
                        "delta_mm": {"x": dx, "y": dy, "z": dz},
                        "pass_index": int(_pass_index),
                    }
                )
                moved_any = True
            if not moved_any:
                break

    hub_slot_mount_offsets: List[Dict[str, Any]] = []
    outboard_support_offsets: List[Dict[str, Any]] = []
    placements_src = semantics.get("connection_placements") if isinstance(semantics, Mapping) else []
    arm_to_axle: Dict[str, str] = {}
    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            if str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower() != "support_member_distal_attachment":
                continue
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if isinstance(arm_id, str) and isinstance(axle_id, str):
                arm_to_axle[arm_id] = axle_id

    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
            if support_topology != "hub_radial_slot_mount":
                continue
            hub_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            arm_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(hub_id, str) or not isinstance(arm_id, str):
                continue
            if hub_id not in placed or arm_id not in placed:
                continue
            hub_pos = placed.get(hub_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            arm_pos = placed.get(arm_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            vx = float(arm_pos.get("x", 0.0)) - float(hub_pos.get("x", 0.0))
            vy = float(arm_pos.get("y", 0.0)) - float(hub_pos.get("y", 0.0))
            if abs(vx) < 1e-9 and abs(vy) < 1e-9:
                ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
                phase_deg = ref_anchor.get("phase_deg")
                if isinstance(phase_deg, (int, float)):
                    ang = math.radians(float(phase_deg))
                    vx = math.cos(ang)
                    vy = math.sin(ang)
                else:
                    base = _rotate_xy(1.0, 0.0, float(yaw_by_cid.get(arm_id, 0.0)))
                    vx = float(base["x"])
                    vy = float(base["y"])
            mag = math.hypot(vx, vy)
            if mag < 1e-9:
                continue
            ux = vx / mag
            uy = vy / mag
            moving_anchor = anchor.get("moving_anchor") if isinstance(anchor.get("moving_anchor"), Mapping) else {}
            insert_depth = moving_anchor.get("inset_mm")
            if not isinstance(insert_depth, (int, float)) or float(insert_depth) <= 0.0:
                insert_depth = 12.0
            hub_radius = _component_radius_mm(hub_id)
            arm_length = _component_length_mm(arm_id)
            hub_thickness = _component_thickness_mm(hub_id)
            arm_thickness = _component_thickness_mm(arm_id)
            arm_dims = _component_dims(arm_id)
            desired_arm_x = float(hub_pos.get("x", 0.0)) + ux * (hub_radius + 0.5 * arm_length - float(insert_depth))
            desired_arm_y = float(hub_pos.get("y", 0.0)) + uy * (hub_radius + 0.5 * arm_length - float(insert_depth))
            if isinstance(arm_dims.get("root_web_thickness"), (int, float)) and float(arm_dims.get("root_web_thickness")) > 0.0:
                desired_arm_z = float(hub_pos.get("z", 0.0)) + (0.5 * hub_thickness)
            else:
                desired_arm_z = float(hub_pos.get("z", 0.0)) + max(0.0, 0.5 * (hub_thickness - arm_thickness))
            dx = desired_arm_x - float(arm_pos.get("x", 0.0))
            dy = desired_arm_y - float(arm_pos.get("y", 0.0))
            dz = desired_arm_z - float(arm_pos.get("z", 0.0))
            members = [arm_id]
            axle_id = arm_to_axle.get(arm_id)
            if isinstance(axle_id, str) and axle_id:
                members.append(axle_id)
                members.extend(_wheel_group_members_for_axle(axle_id))
            members = sorted(set(member for member in members if member in placed))
            if abs(dx) > 1e-6 or abs(dy) > 1e-6 or abs(dz) > 1e-6:
                _apply_translation_to_members(members, dx, dy, dz)
            yaw_by_cid[arm_id] = float(math.degrees(math.atan2(uy, ux)))
            hub_slot_mount_offsets.append(
                {
                    "hub_component_id": hub_id,
                    "arm_component_id": arm_id,
                    "insert_depth_mm": float(insert_depth),
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                    "yaw_deg": float(yaw_by_cid.get(arm_id, 0.0)),
                    "support_topology": support_topology,
                }
            )

    if isinstance(placements_src, list):
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            if str(placement.get("connection_mechanism") or "").strip().lower() != "shaft_bore_fit":
                continue
            geometric_semantics = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}
            support_topology = str(geometric_semantics.get("support_topology") or "").strip().lower()
            axial_stack_policy = str(geometric_semantics.get("axial_stack_policy") or "").strip().lower()
            is_yoke = support_topology == "double_shear_yoke_support" or axial_stack_policy == "wheel_body_between_support_plates"
            is_outboard = support_topology in {"outboard_single_shear", "distal_fork_dropout_support"} or axial_stack_policy == "wheel_body_outboard_of_support_plane"
            if not is_yoke and not is_outboard:
                continue
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            arm_id = anchor.get("reference_component_id") if isinstance(anchor.get("reference_component_id"), str) else None
            axle_id = anchor.get("moving_component_id") if isinstance(anchor.get("moving_component_id"), str) else None
            if not isinstance(arm_id, str) or not isinstance(axle_id, str):
                continue
            if arm_id not in placed:
                continue
            current_members = [member_id for member_id in _wheel_group_members_for_axle(axle_id) if member_id in placed]
            if is_yoke:
                current_members = [axle_id] + [member_id for member_id in current_members if member_id != axle_id]
            if not current_members:
                continue
            arm_pos = placed.get(arm_id, {}) if isinstance(placed.get(arm_id), Mapping) else {}
            arm_x = float(arm_pos.get("x", 0.0))
            arm_y = float(arm_pos.get("y", 0.0))
            arm_z = float(arm_pos.get("z", 0.0))
            arm_dims = _component_dims(arm_id)
            arm_thickness = _component_thickness_mm(arm_id)
            wheel_width = _wheel_group_width_mm([member_id for member_id in current_members if member_id != axle_id])
            clearance_mm = 1.0
            mount_side = str(geometric_semantics.get("mount_side") or ("centered_z" if is_yoke else "positive_z")).strip().lower()
            arm_length = _component_length_mm(arm_id)
            ref_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
            inset_value = arm_dims.get("axle_inset_mm")
            if not isinstance(inset_value, (int, float)) or float(inset_value) <= 0.0:
                inset_value = ref_anchor.get("inset_mm")
            if not isinstance(inset_value, (int, float)) or float(inset_value) <= 0.0:
                inset_value = 12.0
            bore_local_x = max(0.0, 0.5 * float(arm_length) - float(inset_value))
            yaw_deg = yaw_by_cid.get(arm_id)
            if not isinstance(yaw_deg, (int, float)):
                axle_pos = placed.get(axle_id, {}) if isinstance(placed.get(axle_id), Mapping) else {}
                dx_guess = float(axle_pos.get("x", arm_x)) - arm_x
                dy_guess = float(axle_pos.get("y", arm_y)) - arm_y
                yaw_deg = math.degrees(math.atan2(dy_guess, dx_guess)) if abs(dx_guess) > 1e-9 or abs(dy_guess) > 1e-9 else 0.0
            yaw_rad = math.radians(float(yaw_deg))
            ux = math.cos(yaw_rad)
            uy = math.sin(yaw_rad)
            desired_x = arm_x + (ux * bore_local_x)
            desired_y = arm_y + (uy * bore_local_x)
            if is_yoke:
                plate_thickness_value = arm_dims.get("yoke_plate_thickness")
                gap_width_value = arm_dims.get("yoke_gap_width")
                plate_thickness = float(plate_thickness_value) if isinstance(plate_thickness_value, (int, float)) and float(plate_thickness_value) > 0.0 else max(3.0, 0.25 * arm_thickness)
                gap_width = float(gap_width_value) if isinstance(gap_width_value, (int, float)) and float(gap_width_value) > 0.0 else max(wheel_width + 2.0 * clearance_mm, 2.0 * plate_thickness)
                if str(arm_dims.get("yoke_profile_origin") or "").strip().lower() == "midplane":
                    desired_z = arm_z
                else:
                    desired_z = arm_z + plate_thickness + (0.5 * gap_width)
            else:
                sign = -1.0 if mount_side == "negative_z" else 1.0
                desired_z = arm_z + sign * (0.5 * arm_thickness + 0.5 * wheel_width + clearance_mm)
            axle_pos = placed.get(axle_id, {}) if isinstance(placed.get(axle_id), Mapping) else {}
            if axle_pos:
                current_x = float(axle_pos.get("x", desired_x))
                current_y = float(axle_pos.get("y", desired_y))
            else:
                current_x = sum(float(placed.get(member_id, {}).get("x", 0.0)) for member_id in current_members) / float(len(current_members))
                current_y = sum(float(placed.get(member_id, {}).get("y", 0.0)) for member_id in current_members) / float(len(current_members))
            current_z = sum(float(placed.get(member_id, {}).get("z", 0.0)) for member_id in current_members) / float(len(current_members))
            dx = desired_x - current_x
            dy = desired_y - current_y
            dz = desired_z - current_z
            if abs(dx) <= 1e-6 and abs(dy) <= 1e-6 and abs(dz) <= 1e-6:
                continue
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                _apply_translation_to_members(current_members, dx, dy, 0.0)
            if is_yoke:
                for member_id in current_members:
                    if member_id in placed:
                        placed[member_id]["z"] = float(desired_z)
            else:
                if abs(dz) > 1e-6:
                    _apply_translation_to_members(current_members, 0.0, 0.0, dz)
            outboard_support_offsets.append(
                {
                    "arm_component_id": arm_id,
                    "axle_component_id": axle_id,
                    "wheel_members": list(current_members),
                    "mount_side": mount_side,
                    "support_topology": support_topology or ("double_shear_yoke_support" if is_yoke else "distal_fork_dropout_support"),
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                }
            )

    rotating_stack_snaps: List[Dict[str, Any]] = []
    for axle_id in sorted(cid for cid in candidates if re.match(r"^wheel_\d+_axle$", cid, flags=re.IGNORECASE)):
        if axle_id not in placed:
            continue
        rotating_members = [member_id for member_id in _wheel_rotating_stack_members_for_axle(axle_id) if member_id in placed]
        if not rotating_members:
            continue
        shared_rotating_gid = f"rotating_stack::{axle_id}"
        allow_overlap_group_by_component[axle_id] = shared_rotating_gid
        for member_id in rotating_members:
            allow_overlap_group_by_component[member_id] = shared_rotating_gid
        axle_center = placed.get(axle_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        target_x = float(axle_center.get("x", 0.0))
        target_y = float(axle_center.get("y", 0.0))
        target_z = float(axle_center.get("z", 0.0))
        axle_yaw = float(yaw_by_cid.get(axle_id, 0.0))
        moved_members: List[Dict[str, Any]] = []
        for member_id in rotating_members:
            current = placed.get(member_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            dx = target_x - float(current.get("x", 0.0))
            dy = target_y - float(current.get("y", 0.0))
            dz = target_z - float(current.get("z", 0.0))
            if abs(dx) <= 1e-6 and abs(dy) <= 1e-6 and abs(dz) <= 1e-6:
                yaw_by_cid[member_id] = axle_yaw
                continue
            placed[member_id] = {"x": target_x, "y": target_y, "z": target_z}
            yaw_by_cid[member_id] = axle_yaw
            moved_members.append(
                {
                    "component_id": member_id,
                    "delta_mm": {"x": dx, "y": dy, "z": dz},
                }
            )
        if moved_members:
            rotating_stack_snaps.append(
                {
                    "axle_component_id": axle_id,
                    "target_mm": {"x": target_x, "y": target_y, "z": target_z},
                    "moved_members": moved_members,
                }
            )


    def _collect_fastener_bindings() -> Dict[str, Dict[str, Any]]:
        reqs_src = kg.get("connection_requirements")
        if not isinstance(reqs_src, list):
            return {}

        bindings: Dict[str, Dict[str, Any]] = {}
        for req in reqs_src:
            if not isinstance(req, Mapping):
                continue
            req_id = req.get("id")
            if not isinstance(req_id, str) or not req_id:
                continue
            base_req_id = _base_connection_id(req_id) or req_id
            between = [cid for cid in req.get("between", []) if isinstance(cid, str) and cid]
            decision = req.get("connection_decision") if isinstance(req.get("connection_decision"), Mapping) else {}
            semantics_req = req.get("connection_semantics") if isinstance(req.get("connection_semantics"), Mapping) else {}

            preferred_components: List[str] = []
            for key in ("reference_component_id", "moving_component_id"):
                cid = semantics_req.get(key)
                if isinstance(cid, str) and cid and cid not in preferred_components:
                    preferred_components.append(cid)

            fastener_ids: List[str] = []
            ref_fastener_id = decision.get("fastener_ref_component_id")
            if isinstance(ref_fastener_id, str) and ref_fastener_id:
                fastener_ids.append(ref_fastener_id)

            for cid in between:
                lowered = cid.lower()
                if cid in preferred_components or cid in fastener_ids:
                    continue
                if any(token in lowered for token in ("fastener", "bolt", "nut", "washer", "screw")):
                    fastener_ids.append(cid)
                    continue
                if cid not in preferred_components:
                    preferred_components.append(cid)

            for fastener_id in fastener_ids:
                if not isinstance(fastener_id, str) or not fastener_id:
                    continue
                bindings.setdefault(
                    fastener_id,
                    {
                        "connection_id": base_req_id,
                        "preferred_components": list(preferred_components),
                    },
                )

        return bindings

    def _placement_pattern_phase_rad(
        placement: Mapping[str, Any],
        reference_anchor: Mapping[str, Any],
        reference_component_id: str,
        moving_component_id: str | None,
    ) -> float | None:
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
        for key in ("start_angle_rad", "phase_rad"):
            value = pattern.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for key in ("start_angle", "phase_deg"):
            value = pattern.get(key)
            if isinstance(value, (int, float)):
                return math.radians(float(value))

        phase_rad_value = reference_anchor.get("phase_rad")
        if isinstance(phase_rad_value, (int, float)):
            return float(phase_rad_value)
        phase_deg_value = reference_anchor.get("phase_deg")
        if isinstance(phase_deg_value, (int, float)):
            return math.radians(float(phase_deg_value))

        if isinstance(moving_component_id, str) and moving_component_id in placed:
            ref_center = placed.get(reference_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            moving_center = placed.get(moving_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            vx = float(moving_center.get("x", 0.0)) - float(ref_center.get("x", 0.0))
            vy = float(moving_center.get("y", 0.0)) - float(ref_center.get("y", 0.0))
            if abs(vx) >= 1e-9 or abs(vy) >= 1e-9:
                return math.atan2(vy, vx)

        return math.radians(float(yaw_by_cid.get(reference_component_id, 0.0)))

    def _resolve_fastener_mount_z(
        *,
        placement: Mapping[str, Any],
        anchor: Mapping[str, Any],
        reference_component_id: str,
        reference_center: Mapping[str, Any],
        reference_anchor: Mapping[str, Any],
        default_z: float,
    ) -> float:
        relation_type = str(anchor.get("relation_type") or placement.get("relation_type") or "").strip().lower()
        mechanism_name = str(placement.get("connection_mechanism") or anchor.get("connection_mechanism") or "").strip().lower()
        if relation_type != "axial_face_perimeter_mount" and mechanism_name != "axial_face_bolted_mount":
            return float(default_z)

        center_z = float(reference_center.get("z", 0.0))
        thickness = _component_thickness_mm(reference_component_id)
        half_thickness = 0.5 * thickness
        reference_kind = str(reference_anchor.get("kind") or "").strip().lower()
        if reference_kind.endswith("_min"):
            return center_z - half_thickness
        if reference_kind.endswith("_center") or reference_kind.endswith("_mid"):
            return center_z
        return center_z + half_thickness

    def _resolve_fastener_world_point(placement: Mapping[str, Any]) -> Dict[str, float] | None:
        anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
        reference_component_id = anchor.get("reference_component_id")
        moving_component_id = anchor.get("moving_component_id")
        if not isinstance(reference_component_id, str) or reference_component_id not in placed:
            return None

        reference_center = placed.get(reference_component_id, {"x": 0.0, "y": 0.0, "z": 0.0})
        reference_anchor = anchor.get("reference_anchor") if isinstance(anchor.get("reference_anchor"), Mapping) else {}
        location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
        pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}

        radius_mm: float | None = None
        for value in (
            pattern.get("pattern_radius_mm"),
            pattern.get("pattern_radius"),
            reference_anchor.get("radius_mm"),
        ):
            if isinstance(value, (int, float)) and float(value) > 0.0:
                radius_mm = float(value)
                break

        resolved: Dict[str, float] | None = None
        if isinstance(radius_mm, float) and radius_mm > 0.0:
            phase_rad = _placement_pattern_phase_rad(
                placement,
                reference_anchor,
                reference_component_id,
                moving_component_id if isinstance(moving_component_id, str) else None,
            )
            if not isinstance(phase_rad, (int, float)):
                return None
            resolved = {
                "x": float(reference_center.get("x", 0.0)) + radius_mm * math.cos(float(phase_rad)),
                "y": float(reference_center.get("y", 0.0)) + radius_mm * math.sin(float(phase_rad)),
                "z": float(reference_center.get("z", 0.0)),
            }
        else:
            point = _anchor_world_point(
                reference_component_id,
                reference_anchor,
                counterpart_id=moving_component_id if isinstance(moving_component_id, str) else None,
            )
            if not isinstance(point, Mapping):
                return None
            resolved = {
                "x": float(point.get("x", 0.0)),
                "y": float(point.get("y", 0.0)),
                "z": float(point.get("z", 0.0)),
            }

        resolved["z"] = _resolve_fastener_mount_z(
            placement=placement,
            anchor=anchor,
            reference_component_id=reference_component_id,
            reference_center=reference_center,
            reference_anchor=reference_anchor,
            default_z=float(resolved.get("z", 0.0)),
        )
        return resolved

    fastener_anchor_offsets: List[Dict[str, Any]] = []
    fastener_bindings = _collect_fastener_bindings()
    if fastener_bindings and isinstance(placements_src, list):
        placements_by_connection: Dict[str, List[Mapping[str, Any]]] = {}
        for placement in placements_src:
            if not isinstance(placement, Mapping):
                continue
            base_connection_id = _base_connection_id(placement.get("connection_id"))
            if isinstance(base_connection_id, str) and base_connection_id:
                placements_by_connection.setdefault(base_connection_id, []).append(placement)

        def _placement_score(placement: Mapping[str, Any], binding: Mapping[str, Any]) -> int:
            score = 0
            anchor = placement.get("anchor_semantics") if isinstance(placement.get("anchor_semantics"), Mapping) else {}
            location = placement.get("location") if isinstance(placement.get("location"), Mapping) else {}
            interface_ref = location.get("interface_ref") if isinstance(location.get("interface_ref"), Mapping) else {}
            pattern = location.get("pattern_parameters") if isinstance(location.get("pattern_parameters"), Mapping) else {}
            geometric = placement.get("geometric_semantics") if isinstance(placement.get("geometric_semantics"), Mapping) else {}

            if isinstance(pattern.get("pattern_radius_mm"), (int, float)) or isinstance(pattern.get("pattern_radius"), (int, float)):
                score += 100
            if isinstance(interface_ref.get("component_id"), str) and interface_ref.get("component_id") == anchor.get("reference_component_id"):
                score += 40
            preferred_components = binding.get("preferred_components") if isinstance(binding.get("preferred_components"), list) else []
            if anchor.get("reference_component_id") in preferred_components:
                score += 20
            if str(placement.get("purpose") or "").strip().lower() == "fastening_mechanism":
                score += 10
            if "through_bolt" in str(geometric.get("hardware_layout") or "").strip().lower():
                score += 10
            return score

        for fastener_id, binding in sorted(fastener_bindings.items()):
            if fastener_id not in placed:
                continue
            connection_id = binding.get("connection_id")
            if not isinstance(connection_id, str) or not connection_id:
                continue
            placement_candidates = placements_by_connection.get(connection_id, [])
            if not placement_candidates:
                continue

            best_placement: Mapping[str, Any] | None = None
            best_score = -1
            for placement in placement_candidates:
                score = _placement_score(placement, binding)
                if score > best_score:
                    best_score = score
                    best_placement = placement
            if not isinstance(best_placement, Mapping):
                continue

            target_point = _resolve_fastener_world_point(best_placement)
            if not isinstance(target_point, Mapping):
                continue

            current_point = placed.get(fastener_id, {"x": 0.0, "y": 0.0, "z": 0.0})
            anchor = best_placement.get("anchor_semantics") if isinstance(best_placement.get("anchor_semantics"), Mapping) else {}
            reference_component_id = anchor.get("reference_component_id")
            if isinstance(reference_component_id, str) and reference_component_id in yaw_by_cid:
                yaw_by_cid[fastener_id] = float(yaw_by_cid.get(reference_component_id, 0.0))
                synthetic_rigid_pairs.add(tuple(sorted((fastener_id, reference_component_id))))
                graph.setdefault(fastener_id, set()).add(reference_component_id)
                graph.setdefault(reference_component_id, set()).add(fastener_id)

            placed[fastener_id] = {
                "x": float(target_point.get("x", 0.0)),
                "y": float(target_point.get("y", 0.0)),
                "z": float(target_point.get("z", 0.0)),
            }
            fastener_anchor_offsets.append(
                {
                    "fastener_component_id": fastener_id,
                    "connection_id": connection_id,
                    "reference_component_id": reference_component_id,
                    "delta_mm": {
                        "x": float(target_point.get("x", 0.0)) - float(current_point.get("x", 0.0)),
                        "y": float(target_point.get("y", 0.0)) - float(current_point.get("y", 0.0)),
                        "z": float(target_point.get("z", 0.0)) - float(current_point.get("z", 0.0)),
                    },
                    "target_mm": dict(placed[fastener_id]),
                }
            )

    opposed_bearing_offsets: List[Dict[str, Any]] = []
    if isinstance(placements_src, list):
        host_to_bearings: Dict[str, Dict[str, str]] = {}
        for placement in placements_src:
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
            if len(bearing_sides) < 2 or host_id not in placed:
                continue
            host_z = float(placed.get(host_id, {}).get("z", 0.0))
            host_dims = _component_dims(host_id)
            host_thickness = float(host_dims.get("thickness") or _component_thickness_mm(host_id))
            shoulder_mm = float(host_dims.get("opposed_bearing_shoulder") or 1.0)
            for bearing_id, side in bearing_sides.items():
                if bearing_id not in placed:
                    continue
                bearing_dims = _component_dims(bearing_id)
                bearing_width = float(bearing_dims.get("width") or bearing_dims.get("thickness") or 7.0)
                center_offset = max(0.0, 0.5 * host_thickness - 0.5 * bearing_width - shoulder_mm)
                desired_z = host_z + (-center_offset if side == "min" else center_offset)
                current = placed.get(bearing_id, {}) if isinstance(placed.get(bearing_id), Mapping) else {}
                current_z = float(current.get("z", host_z))
                dz = desired_z - current_z
                if abs(dz) <= 1e-6:
                    continue
                placed[bearing_id]["z"] = float(desired_z)
                opposed_bearing_offsets.append(
                    {
                        "host_component_id": host_id,
                        "bearing_component_id": bearing_id,
                        "seat_side": side,
                        "delta_z_mm": dz,
                    }
                )

    # -----------------
    # Placement groups
    # -----------------
    def _build_groups() -> List[Dict[str, Any]]:
        class_priority = {
            "rigid_cluster": 300,
            "coaxial_chain": 200,
            "free": 100,
        }
        # Build coaxial connected components first.
        coax_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        rigid_adj: Dict[str, set[str]] = {cid: set() for cid in candidates}
        for a in candidates:
            for b in graph.get(a, set()):
                if b not in candidates or a == b:
                    continue
                k = _edge_kind(a, b)
                if k == "coaxial":
                    coax_adj[a].add(b)
                elif k == "rigid":
                    rigid_adj[a].add(b)

        groups: List[Dict[str, Any]] = []
        assigned: set[str] = set()

        def _cc(adj: Dict[str, set[str]]) -> List[List[str]]:
            comps: List[List[str]] = []
            seen: set[str] = set()
            for start in candidates:
                if start in seen:
                    continue
                stack = [start]
                cur: List[str] = []
                seen.add(start)
                while stack:
                    x = stack.pop()
                    cur.append(x)
                    for y in adj.get(x, set()):
                        if y in seen:
                            continue
                        seen.add(y)
                        stack.append(y)
                comps.append(sorted(cur))
            return comps

        for members in _cc(coax_adj):
            if len(members) < 2:
                continue
            # ---- Extend coaxial chain: include components whose
            # position_parent chain leads to a chain member.  This ensures
            # rim, tire, spacer etc. that are parented to a hub/axle in the
            # chain stay coaxial and don't get pushed away by overlap
            # resolution.
            chain_set = set(members)
            extended = True
            while extended:
                extended = False
                for cid in list(candidates):
                    if cid in chain_set:
                        continue
                    comp = comp_by_id.get(cid, {})
                    pp = comp.get("position_parent")
                    if isinstance(pp, str) and pp in chain_set:
                        chain_set.add(cid)
                        extended = True
            members = sorted(chain_set)
            for m in members:
                assigned.add(m)
            gid = f"coaxial_{members[0]}"
            groups.append(
                {
                    "group_id": gid,
                    "class": "coaxial_chain",
                    "members": members,
                    "primary_axis_world": [0.0, 0.0, 1.0],
                    "allow_overlap": True,
                    "priority": class_priority["coaxial_chain"],
                }
            )

        overlap_group_members: Dict[str, List[str]] = {}
        for cid in candidates:
            if cid in assigned:
                continue
            overlap_gid = allow_overlap_group_by_component.get(cid)
            if overlap_gid:
                overlap_group_members.setdefault(overlap_gid, []).append(cid)

        for _, members in sorted(overlap_group_members.items(), key=lambda item: item[0]):
            members = sorted(set(members))
            if len(members) < 2:
                continue
            for m in members:
                assigned.add(m)
            groups.append(
                {
                    "group_id": f"overlap::{members[0]}",
                    "class": "coaxial_chain",
                    "members": members,
                    "primary_axis_world": [0.0, 0.0, 1.0],
                    "allow_overlap": True,
                    "priority": class_priority["coaxial_chain"],
                }
            )

        remaining = [cid for cid in candidates if cid not in assigned]
        # Rigid clusters among remaining.
        if remaining:
            rigid_sub_adj = {cid: set([n for n in rigid_adj.get(cid, set()) if n in remaining]) for cid in remaining}
            seen2: set[str] = set()
            for start in sorted(remaining):
                if start in seen2:
                    continue
                stack = [start]
                seen2.add(start)
                members: List[str] = []
                while stack:
                    x = stack.pop()
                    members.append(x)
                    for y in rigid_sub_adj.get(x, set()):
                        if y in seen2:
                            continue
                        seen2.add(y)
                        stack.append(y)
                members = sorted(members)
                if len(members) >= 2:
                    for m in members:
                        assigned.add(m)
                    gid = f"rigid_{members[0]}"
                    groups.append(
                        {
                            "group_id": gid,
                            "class": "rigid_cluster",
                            "members": members,
                            "allow_overlap": False,
                            "priority": class_priority["rigid_cluster"],
                        }
                    )

        # Free singletons.
        for cid in sorted(candidates):
            if cid in assigned:
                continue
            groups.append(
                {
                    "group_id": f"free_{cid}",
                    "class": "free",
                    "members": [cid],
                    "allow_overlap": False,
                    "priority": class_priority["free"],
                }
            )
        return groups

    placement_groups = _build_groups()

    # -----------------
    # Group-based overlap resolution
    # -----------------
    before_pos = {cid: dict(placed.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})) for cid in candidates}
    after_pos = {cid: dict(before_pos[cid]) for cid in candidates}

    def _aabb_minmax(center: Dict[str, float], size: tuple[float, float, float]) -> Dict[str, float]:
        cx, cy, cz = float(center.get("x", 0.0)), float(center.get("y", 0.0)), float(center.get("z", 0.0))
        sx, sy, sz = size
        return {
            "min_x": cx - sx / 2.0,
            "max_x": cx + sx / 2.0,
            "min_y": cy - sy / 2.0,
            "max_y": cy + sy / 2.0,
            "min_z": cz - sz / 2.0,
            "max_z": cz + sz / 2.0,
        }

    def _merge_minmax(mm_list: List[Dict[str, float]]) -> Dict[str, float]:
        out = dict(mm_list[0])
        for mm in mm_list[1:]:
            out["min_x"] = min(out["min_x"], mm["min_x"])
            out["max_x"] = max(out["max_x"], mm["max_x"])
            out["min_y"] = min(out["min_y"], mm["min_y"])
            out["max_y"] = max(out["max_y"], mm["max_y"])
            out["min_z"] = min(out["min_z"], mm["min_z"])
            out["max_z"] = max(out["max_z"], mm["max_z"])
        return out

    def _group_aabb(g: Mapping[str, Any]) -> Dict[str, float]:
        mms: List[Dict[str, float]] = []
        for cid in g.get("members", []) or []:
            if cid not in after_pos:
                continue
            mms.append(_aabb_minmax(after_pos[cid], sizes.get(cid, (30.0, 30.0, 30.0))))
        if not mms:
            return {"min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0, "min_z": 0.0, "max_z": 0.0}
        return _merge_minmax(mms)

    def _minmax_overlaps(a: Mapping[str, float], b: Mapping[str, float], *, margin: float) -> bool:
        if float(a["max_x"]) + margin <= float(b["min_x"]) or float(b["max_x"]) + margin <= float(a["min_x"]):
            return False
        if float(a["max_y"]) + margin <= float(b["min_y"]) or float(b["max_y"]) + margin <= float(a["min_y"]):
            return False
        if float(a["max_z"]) + margin <= float(b["min_z"]) or float(b["max_z"]) + margin <= float(a["min_z"]):
            return False
        return True

    def _center_from_minmax(mm: Mapping[str, float]) -> Dict[str, float]:
        return {
            "x": 0.5 * (float(mm["min_x"]) + float(mm["max_x"])),
            "y": 0.5 * (float(mm["min_y"]) + float(mm["max_y"])),
            "z": 0.5 * (float(mm["min_z"]) + float(mm["max_z"])),
        }

    def _apply_group_translation(g: Mapping[str, Any], vec: Dict[str, float]) -> None:
        for cid in g.get("members", []) or []:
            if cid not in after_pos:
                continue
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)) + float(vec.get("x", 0.0)),
                "y": float(after_pos[cid].get("y", 0.0)) + float(vec.get("y", 0.0)),
                "z": float(after_pos[cid].get("z", 0.0)) + float(vec.get("z", 0.0)),
            }

    # Stage A: group-internal handling (do NOT push coaxial members in X/Y)
    axial_jitters: List[Dict[str, Any]] = []
    for g in placement_groups:
        if g.get("class") != "coaxial_chain":
            continue
        if bool(g.get("allow_overlap")):
            continue
        axis = g.get("primary_axis_world")
        if not (isinstance(axis, list) and len(axis) == 3):
            axis = [0.0, 0.0, 1.0]
        ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
        # Only support axis-aligned jitter for now.
        if abs(az) < 0.9:
            continue
        members = [m for m in (g.get("members") or []) if isinstance(m, str) and m in after_pos]
        z_seen: Dict[float, int] = {}
        for m in members:
            z = float(after_pos[m].get("z", 0.0))
            key = round(z, 6)
            z_seen[key] = z_seen.get(key, 0) + 1
        if all(v <= 1 for v in z_seen.values()):
            continue
        # Apply small +/- jitter in Z to break exact co-planarity.
        for i, m in enumerate(sorted(members)):
            if m == grounded:
                continue
            dz = (1.0 if (i % 2 == 0) else -1.0) * float((i // 2) + 1)
            _apply_group_translation({"members": [m]}, {"x": 0.0, "y": 0.0, "z": dz})
            axial_jitters.append({"component_id": m, "delta_mm": {"x": 0.0, "y": 0.0, "z": dz}})

    # Stage B: group-level separation only (translate whole groups)
    group_by_id = {str(g.get("group_id")): g for g in placement_groups if isinstance(g, Mapping) and g.get("group_id")}
    grounded_groups: set[str] = set()
    for gid, g in group_by_id.items():
        members = g.get("members") or []
        if isinstance(members, list) and grounded in members:
            grounded_groups.add(gid)
    applied_translations: List[Dict[str, Any]] = []
    conflict_resolutions: List[Dict[str, Any]] = []
    invalidated_assumptions: Dict[str, Dict[str, Any]] = {}

    def _priority_of(g: Mapping[str, Any]) -> int:
        p = g.get("priority")
        if isinstance(p, int):
            return p
        cls = g.get("class") if isinstance(g.get("class"), str) else "free"
        if cls == "rigid_cluster":
            return 300
        if cls == "coaxial_chain":
            return 200
        return 100

    def _groups_directly_structurally_coupled(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
        m1 = [cid for cid in (g1.get("members") or []) if isinstance(cid, str)]
        m2 = [cid for cid in (g2.get("members") or []) if isinstance(cid, str)]
        if not m1 or not m2:
            return False

        # If there is any rigid or anchor-coupled edge between groups, they belong to the same semantic support cluster.
        for a in m1:
            for b in m2:
                if a == b:
                    continue
                if _edge_kind(a, b) == "rigid":
                    return True
                if tuple(sorted((a, b))) in anchor_coupled_pairs:
                    return True
        return False

    def _build_structural_group_clusters() -> Dict[str, str]:
        adjacency: Dict[str, set[str]] = {gid: set() for gid in group_by_id}
        gids_local = sorted(adjacency.keys())
        for i in range(len(gids_local)):
            gid_a = gids_local[i]
            ga = group_by_id[gid_a]
            for j in range(i + 1, len(gids_local)):
                gid_b = gids_local[j]
                gb = group_by_id[gid_b]
                if not _groups_directly_structurally_coupled(ga, gb):
                    continue
                adjacency[gid_a].add(gid_b)
                adjacency[gid_b].add(gid_a)

        cluster_by_gid: Dict[str, str] = {}
        seen: set[str] = set()
        cluster_index = 0
        for start_gid in gids_local:
            if start_gid in seen:
                continue
            stack = [start_gid]
            seen.add(start_gid)
            members: List[str] = []
            while stack:
                current_gid = stack.pop()
                members.append(current_gid)
                for neighbor_gid in sorted(adjacency.get(current_gid, set())):
                    if neighbor_gid in seen:
                        continue
                    seen.add(neighbor_gid)
                    stack.append(neighbor_gid)
            cluster_id = f"structural_cluster_{cluster_index}"
            for member_gid in members:
                cluster_by_gid[member_gid] = cluster_id
            cluster_index += 1
        return cluster_by_gid

    structural_cluster_by_group = _build_structural_group_clusters()

    def _groups_structurally_coupled(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
        gid1 = str(g1.get("group_id")) if g1.get("group_id") else ""
        gid2 = str(g2.get("group_id")) if g2.get("group_id") else ""
        if not gid1 or not gid2:
            return False
        if gid1 == gid2:
            return True
        cluster1 = structural_cluster_by_group.get(gid1)
        cluster2 = structural_cluster_by_group.get(gid2)
        return isinstance(cluster1, str) and cluster1 == cluster2

    def _choose_movable(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
        gid1 = str(g1.get("group_id"))
        gid2 = str(g2.get("group_id"))
        if gid1 in grounded_groups and gid2 not in grounded_groups:
            return g2, "grounded_group_pinned"
        if gid2 in grounded_groups and gid1 not in grounded_groups:
            return g1, "grounded_group_pinned"

        p1 = _priority_of(g1)
        p2 = _priority_of(g2)
        if p1 > p2:
            return g2, "lower_priority_group_moves"
        if p2 > p1:
            return g1, "lower_priority_group_moves"

        # Prefer moving non-coaxial groups away from coaxial chains.
        a_overlap = bool(g1.get("allow_overlap"))
        b_overlap = bool(g2.get("allow_overlap"))
        if a_overlap and not b_overlap:
            return g2, "coaxial_anchor_preserved"
        if b_overlap and not a_overlap:
            return g1, "coaxial_anchor_preserved"
        # Otherwise deterministic: move lexicographically later group_id
        return (g2, "lexicographic_tie_break") if gid2 >= gid1 else (g1, "lexicographic_tie_break")

    def _compute_push(static_mm: Mapping[str, float], move_mm: Mapping[str, float], *, prefer_xy: bool) -> Dict[str, float]:
        axes = ["x", "y", "z"] if not prefer_xy else ["x", "y", "z"]
        # prefer_xy currently means: try X/Y first (already ordered).
        s_center = _center_from_minmax(static_mm)
        m_center = _center_from_minmax(move_mm)

        best_vec: Dict[str, float] | None = None
        best_mag = float("inf")
        for axname in axes:
            if axname == "x":
                if float(m_center["x"]) >= float(s_center["x"]):
                    delta = (float(static_mm["max_x"]) + float(margin_mm)) - float(move_mm["min_x"])
                else:
                    delta = (float(static_mm["min_x"]) - float(margin_mm)) - float(move_mm["max_x"])
                vec = {"x": float(delta), "y": 0.0, "z": 0.0}
                mag = abs(float(delta))
            elif axname == "y":
                if float(m_center["y"]) >= float(s_center["y"]):
                    delta = (float(static_mm["max_y"]) + float(margin_mm)) - float(move_mm["min_y"])
                else:
                    delta = (float(static_mm["min_y"]) - float(margin_mm)) - float(move_mm["max_y"])
                vec = {"x": 0.0, "y": float(delta), "z": 0.0}
                mag = abs(float(delta))
            else:
                if float(m_center["z"]) >= float(s_center["z"]):
                    delta = (float(static_mm["max_z"]) + float(margin_mm)) - float(move_mm["min_z"])
                else:
                    delta = (float(static_mm["min_z"]) - float(margin_mm)) - float(move_mm["max_z"])
                vec = {"x": 0.0, "y": 0.0, "z": float(delta)}
                mag = abs(float(delta))

            if mag < best_mag:
                best_mag = mag
                best_vec = vec

        return best_vec or {"x": float(margin_mm), "y": 0.0, "z": 0.0}

    # Iteratively resolve group overlaps.
    for _ in range(200):
        any_moved = False
        group_aabbs = {gid: _group_aabb(g) for gid, g in group_by_id.items()}
        gids = sorted(group_aabbs.keys())
        for i in range(len(gids)):
            for j in range(i + 1, len(gids)):
                ga = group_by_id[gids[i]]
                gb = group_by_id[gids[j]]
                a_mm = group_aabbs[gids[i]]
                b_mm = group_aabbs[gids[j]]
                if not _minmax_overlaps(a_mm, b_mm, margin=float(margin_mm)):
                    continue

                if _groups_structurally_coupled(ga, gb):
                    conflict_resolutions.append(
                        {
                            "group_a": str(ga.get("group_id")),
                            "group_b": str(gb.get("group_id")),
                            "moved_group_id": None,
                            "preserved_group_id": None,
                            "moved_group_class": None,
                            "preserved_group_class": None,
                            "moved_group_priority": None,
                            "preserved_group_priority": None,
                            "decision_reason": "structurally_coupled_groups_overlap_allowed",
                            "delta_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
                        }
                    )
                    continue

                movable, decision_reason = _choose_movable(ga, gb)
                static = gb if movable is ga else ga
                movable_id = str(movable.get("group_id"))
                static_id = str(static.get("group_id"))

                prefer_xy = (movable.get("class") == "coaxial_chain") or (static.get("class") == "coaxial_chain")
                static_mm = group_aabbs[static_id]
                move_mm = group_aabbs[movable_id]
                vec = _compute_push(static_mm, move_mm, prefer_xy=prefer_xy)
                _apply_group_translation(movable, vec)
                applied_translations.append(
                    {
                        "moved_group_id": movable_id,
                        "static_group_id": static_id,
                        "delta_mm": vec,
                        "decision_reason": decision_reason,
                    }
                )
                movable_priority = _priority_of(movable)
                static_priority = _priority_of(static)
                conflict_resolutions.append(
                    {
                        "group_a": str(ga.get("group_id")),
                        "group_b": str(gb.get("group_id")),
                        "moved_group_id": movable_id,
                        "preserved_group_id": static_id,
                        "moved_group_class": movable.get("class"),
                        "preserved_group_class": static.get("class"),
                        "moved_group_priority": movable_priority,
                        "preserved_group_priority": static_priority,
                        "decision_reason": decision_reason,
                        "delta_mm": vec,
                    }
                )
                if static_priority > movable_priority:
                    invalidated_assumptions[movable_id] = {
                        "group_id": movable_id,
                        "constraint_status": "relaxed_due_conflict",
                        "sacrificed_to": static_id,
                        "decision_reason": decision_reason,
                        "group_priority": movable_priority,
                        "counterparty_priority": static_priority,
                    }
                any_moved = True
                # Recompute in next outer iteration.
                break
            if any_moved:
                break
        if not any_moved:
            break

    # Deterministic de-dup pass: if multiple components share the same rounded translation,
    # jitter later IDs along +Y to guarantee non-overlapping initial placements.
    dedup_jitters: List[Dict[str, Any]] = []
    bucket_to_ids: Dict[tuple[float, float, float], List[str]] = {}
    for cid in sorted(candidates):
        pos = after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})
        key = (
            round(float(pos.get("x", 0.0)), 3),
            round(float(pos.get("y", 0.0)), 3),
            round(float(pos.get("z", 0.0)), 3),
        )
        bucket_to_ids.setdefault(key, []).append(cid)

    dedup_step = max(10.0, float(margin_mm) + 5.0)

    def _bucket_is_intentionally_coupled(ids: List[str]) -> bool:
        if len(ids) <= 1:
            return False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = ids[i]
                b = ids[j]
                if tuple(sorted((a, b))) in anchor_coupled_pairs:
                    continue
                if _edge_kind(a, b) == "rigid" and _is_hierarchy_overlap_candidate(a) and _is_hierarchy_overlap_candidate(b):
                    continue
                return False
        return True

    for key in sorted(bucket_to_ids.keys()):
        ids = sorted(bucket_to_ids[key])
        if len(ids) <= 1:
            continue
        if _bucket_is_intentionally_coupled(ids):
            continue
        protected_ids = [cid for cid in ids if allow_overlap_group_by_component.get(cid)]
        if protected_ids:
            shared_gid = allow_overlap_group_by_component.get(protected_ids[0])
            if shared_gid and all(allow_overlap_group_by_component.get(cid) == shared_gid for cid in ids):
                continue
        if grounded in ids or protected_ids:
            movable_ids = [cid for cid in ids if cid != grounded and cid not in protected_ids]
            for k, cid in enumerate(movable_ids, start=1):
                delta_y = float(k) * dedup_step
                after_pos[cid] = {
                    "x": float(after_pos[cid].get("x", 0.0)),
                    "y": float(after_pos[cid].get("y", 0.0)) + delta_y,
                    "z": float(after_pos[cid].get("z", 0.0)),
                }
                dedup_jitters.append(
                    {
                        "component_id": cid,
                        "bucket_key": key,
                        "delta_mm": {"x": 0.0, "y": delta_y, "z": 0.0},
                    }
                )
            continue
        for k, cid in enumerate(ids):
            if k == 0:
                continue
            delta_y = float(k) * dedup_step
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)),
                "y": float(after_pos[cid].get("y", 0.0)) + delta_y,
                "z": float(after_pos[cid].get("z", 0.0)),
            }
            dedup_jitters.append(
                {
                    "component_id": cid,
                    "bucket_key": key,
                    "delta_mm": {"x": 0.0, "y": delta_y, "z": 0.0},
                }
            )

    # Final normalization: keep grounded component at origin for deterministic global frame.
    grounded_pos = after_pos.get(grounded, {"x": 0.0, "y": 0.0, "z": 0.0})
    norm_offset = {
        "x": float(grounded_pos.get("x", 0.0)),
        "y": float(grounded_pos.get("y", 0.0)),
        "z": float(grounded_pos.get("z", 0.0)),
    }
    if abs(norm_offset["x"]) > 1e-9 or abs(norm_offset["y"]) > 1e-9 or abs(norm_offset["z"]) > 1e-9:
        for cid in candidates:
            if cid not in after_pos:
                continue
            after_pos[cid] = {
                "x": float(after_pos[cid].get("x", 0.0)) - norm_offset["x"],
                "y": float(after_pos[cid].get("y", 0.0)) - norm_offset["y"],
                "z": float(after_pos[cid].get("z", 0.0)) - norm_offset["z"],
            }

    # Collect final conflicts for diagnostics.
    final_conflicts: List[Dict[str, Any]] = []
    group_aabbs = {gid: _group_aabb(g) for gid, g in group_by_id.items()}
    gids = sorted(group_aabbs.keys())
    for i in range(len(gids)):
        for j in range(i + 1, len(gids)):
            ga = group_by_id[gids[i]]
            gb = group_by_id[gids[j]]
            if _groups_structurally_coupled(ga, gb):
                continue
            a_mm = group_aabbs[gids[i]]
            b_mm = group_aabbs[gids[j]]
            if _minmax_overlaps(a_mm, b_mm, margin=float(margin_mm)):
                final_conflicts.append({"group_a": gids[i], "group_b": gids[j]})

    # Invariants: coaxial members must not be sheared (xy delta must be uniform within group).
    coaxial_invariants: List[Dict[str, Any]] = []
    for g in placement_groups:
        if g.get("class") != "coaxial_chain":
            continue
        members = [m for m in (g.get("members") or []) if isinstance(m, str) and m in before_pos and m in after_pos]
        deltas = set()
        for m in members:
            dx = float(after_pos[m]["x"]) - float(before_pos[m]["x"])
            dy = float(after_pos[m]["y"]) - float(before_pos[m]["y"])
            deltas.add((round(dx, 9), round(dy, 9)))
        coaxial_invariants.append(
            {
                "group_id": g.get("group_id"),
                "xy_translation_unique_count": len(deltas),
                "ok_uniform_xy_translation": len(deltas) <= 1,
            }
        )

    initial_placements: List[Dict[str, Any]] = []
    for cid in candidates:
        pos = after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})
        yaw = float(yaw_by_cid.get(cid, 0.0))
        parent_comp = comp_by_id.get(cid, {}).get("position_parent")
        parent_assembly = parent_comp if isinstance(parent_comp, str) and parent_comp in candidate_set else "root"
        initial_placements.append(
            {
                "component_id": cid,
                "occurrence_name": cid,
                "parent_assembly": parent_assembly,
                "transform": {
                    "translation": {
                        "x": float(pos.get("x", 0.0)),
                        "y": float(pos.get("y", 0.0)),
                        "z": float(pos.get("z", 0.0)),
                    },
                    "rotation_rpy_deg": {"roll": 0.0, "pitch": 0.0, "yaw": yaw},
                },
                "ground": bool(cid == grounded),
                "orientation_unknown": bool(orientation_unknown.get(cid, False)),
            }
        )

    placement_groups_out: List[Dict[str, Any]] = []
    for g in placement_groups:
        g_out = dict(g) if isinstance(g, Mapping) else {}
        gid = g_out.get("group_id") if isinstance(g_out.get("group_id"), str) else None
        if isinstance(gid, str) and gid in invalidated_assumptions:
            g_out["constraint_status"] = "relaxed_due_conflict"
            g_out["constraint_relaxation"] = dict(invalidated_assumptions[gid])
        else:
            g_out["constraint_status"] = "active"
        placement_groups_out.append(g_out)

    return {
        "initial_placements": initial_placements,
        "placement_groups": placement_groups_out,
        "diagnostics": {
            "before": [
                {
                    "component_id": cid,
                    "translation_mm": dict(before_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})),
                }
                for cid in candidates
            ],
            "after": [
                {
                    "component_id": cid,
                    "translation_mm": dict(after_pos.get(cid, {"x": 0.0, "y": 0.0, "z": 0.0})),
                    "yaw_deg": float(yaw_by_cid.get(cid, 0.0)),
                }
                for cid in candidates
            ],
            "group_conflicts": final_conflicts,
            "conflict_resolutions": conflict_resolutions,
            "invalidated_assumptions": [
                dict(v) for _, v in sorted(invalidated_assumptions.items(), key=lambda item: item[0])
            ],
            "applied_group_translations": applied_translations,
            "axial_jitters": axial_jitters,
            "anchor_adjustments": anchor_adjustments,
            "hub_slot_mount_offsets": hub_slot_mount_offsets,
            "outboard_support_offsets": outboard_support_offsets,
            "rotating_stack_snaps": rotating_stack_snaps,
            "fastener_anchor_offsets": fastener_anchor_offsets,
            "opposed_bearing_offsets": opposed_bearing_offsets,
            "dedup_jitters": dedup_jitters,
            "coaxial_invariants": coaxial_invariants,
            "normalization_offset_mm": norm_offset,
            "grounded_groups": sorted(grounded_groups),
            "structural_group_clusters": [
                {"group_id": gid, "cluster_id": structural_cluster_by_group.get(gid)}
                for gid in sorted(structural_cluster_by_group.keys())
            ],
        },
        "summary": {
            "strategy": "preassembly_graph_bfs_v2",
            "component_count": len(candidates),
            "ground_component_id": grounded,
            "requested_ground_component_id": requested_ground,
            "ground_override_applied": applied_override,
            "anchor_semantics_count": len(anchor_semantics_list),
            "margin_mm": float(margin_mm),
        },
    }
