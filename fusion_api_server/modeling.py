"""
Fusion API 寤烘ā鎺у埗鍣紙浠?fusion_api_server.py 鎷嗗垎锛?

===== 绯荤粺濂戠害 =====

- component_id := "comp:{name}:{counter}"锛圕REATE_COMPONENT 鐢熸垚锛?
- sketch_id    := "{component_id}:{sketch_name}"
- profile_id   := "{sketch_id}:profile:{index}"
- curve_id     := "{sketch_id}:{kind}:{index}"
- sketch_point_id := "{sketch_id}:sketch_point:{index}"
- body_id      := "{component_id}:body:{index}"
- occurrence_id:
    - primary: "occ:{name}:{counter}"锛圕REATE_COMPONENT 鐢熸垚锛?
    - listed: "listed:occ:{i}" and "listed:all_occ:{i}"锛圠IST_* 杩斿洖锛?

銆愬崟浣嶇害瀹氥€戯紙CRITICAL锛?
- plan 涓墍鏈夊昂瀵搞€佸潗鏍囥€侀暱搴?= 姣背锛坢m锛?
- Fusion API 浣跨敤鍘樼背锛坈m锛?
- 鏈ā鍧楄嚜鍔ㄥ仛杞崲锛歮m 鈫?cm锛? 10.0锛?
- 涓嶅瓨鍦ㄤ换浣?涓存椂鍒ゆ柇"锛堝 distance > 100 灏?/10锛夛紝杞崲瑙勫垯缁熶竴涓旀槑纭?

銆愬亸绉诲钩闈€?
- 缁熶竴浣跨敤 CREATE_OFFSET_CONSTRUCTION_PLANE
- base_plane 鏀寔 {type} 鎴?{plane_id} 鎴栫洿鎺ヤ紶 plane_id(str)

"""
import math
import json
import os
import datetime
import re
from pathlib import Path
from typing import Any
import adsk.core
import adsk.fusion


class FusionApiController:
    """Fusion 360 寤烘ā鑳藉姏搴?- 鎵€鏈夋柟娉曞悕涓?function_name 涓€鑷?
    
    銆愬崟浣嶇粺涓€銆?
    - 鎵€鏈夎緭鍏ュ弬鏁板崟浣嶏細姣背锛坢m锛?
    - 鍐呴儴杞崲涓哄帢绫筹紙cm锛変緵 Fusion 浣跨敤
    - 閫氳繃 mm() 鍜?cm_vec() 宸ュ叿鍑芥暟瀹屾垚杞崲
    """
    
    def __init__(self, app: adsk.core.Application, strict_mode: bool = False, run_dir: str | None = None):
        self.app = app
        self.ui = app.userInterface
        product = app.activeProduct
        self.design = adsk.fusion.Design.cast(product)
        if not self.design:
            raise RuntimeError("No active Fusion design")
        self.root_comp = self.design.rootComponent
        
        # 鍐呴儴鐘舵€侊細缁存姢缁勪欢銆乻ketch銆乸rofile 绛夋槧灏?
        self._components = {}  # component_id -> Component
        self._occurrences = {}  # occurrence_id -> Occurrence
        self._listed_occurrences = {}  # list_id -> Occurrence
        self._component_name_to_id = {}
        self._occ_name_to_id = {}
        self._occurrence_display_names = {}  # occurrence_id -> browser/display name
        self._occurrence_component_names = {}  # occurrence_id -> component definition name
        self._occurrence_last_translation_mm = {}  # occurrence_id -> last known world translation
        self._occurrence_last_rotation_rpy_deg = {}  # occurrence_id -> last requested world rotation
        self._component_counter = 0
        self._occ_counter = 0
        self._sketches = {}  # sketch_id -> Sketch
        self._planes = {}  # plane_id -> ConstructionPlane
        self._profiles = {}  # profile_id -> Profile
        self._profile_counter = {}  # sketch_id -> int (璁℃暟鍣?
        self._curve_counter = {}  # sketch_id -> int (璁℃暟鍣?
        self._body_counter = {}  # component_id -> int (璁℃暟鍣?
        self._bodies = {}  # body_id -> Body
        self._features = {}  # feature_id -> Feature
        self._tokens = {}  # id -> entityToken
        self._feature_counter = {}  # component_id -> int (璁℃暟鍣?
        self._curves = {}  # curve_id -> SketchCurve
        self._sketch_points = {}  # point_id -> SketchPoint
        self._sketch_point_counter = {}  # sketch_id -> int (璁℃暟鍣?
        self._dims = {}  # dim_id -> SketchDimension
        self._dim_counter = {}  # sketch_id -> int (璁℃暟鍣?
        self._constraints = {}  # constraint_id -> SketchConstraint
        self._constraint_counter = {}  # sketch_id -> int (璁℃暟鍣?
        self._selector_counter = 0  # optional deterministic selector counter
        self._paths = {}  # path_id -> Path
        self._path_counter = 0
        self._points = {}  # point_id -> ConstructionPoint
        self._axes = {}  # axis_id -> ConstructionAxis
        self._texts = {}  # text_id -> SketchText
        self._text_counter = {}  # sketch_id -> int
        self._faces = {}  # face_id -> Face
        self._face_counter = {}  # component_id -> int
        self._edges = {}  # edge_id -> Edge
        self._edge_counter = {}  # component_id -> int
        self._vertices = {}  # vertex_id -> Vertex
        self._sketch_id_by_obj = {}
        self._joints = {}  # joint_id -> joint object
        self._joint_geometries = {}  # joint_geometry_id -> JointGeometry
        self._joint_geometry_sources = {}  # joint_geometry_id -> {entity, origin_mm}
        self._joint_counter = 0
        self._interface_tokens = {}  # token_id -> {entity_kind, entity_id, interface_name}
        self._markers = {}  # marker_id -> {entity_kind, source, interface_name}
        self._standard_parts = {"by_component_id": {}, "by_component_name": {}}
        self._parts_index_cache = None
        self._parts_index_mtime = None
        self._parts_index_path = None
        self.strict_mode = bool(strict_mode)
        self.run_dir = str(run_dir) if run_dir else None

    def _append_resolved_interface_debug(self, payload: dict) -> None:
        """Best-effort append to execution/resolved_interfaces_debug.json within current run_dir."""
        if not self.run_dir:
            return
        try:
            base = Path(self.run_dir)
            out_path = base / "execution" / "resolved_interfaces_debug.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)

            existing = None
            if out_path.exists():
                try:
                    existing = json.loads(out_path.read_text(encoding="utf-8"))
                except Exception:
                    existing = None
            if not isinstance(existing, list):
                existing = []
            existing.append(payload)

            # Keep file bounded to avoid runaway growth.
            if len(existing) > 2000:
                existing = existing[-2000:]

            out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Never break execution due to debug logging.
            return

    def _append_interface_resolution_audit(self, payload: dict) -> None:
        """Best-effort append to planning/errors/interface_resolution_audit.json within current run_dir."""
        if not self.run_dir:
            return
        try:
            base = Path(self.run_dir)
            out_path = base / "planning" / "errors" / "interface_resolution_audit.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)

            existing = None
            if out_path.exists():
                try:
                    existing = json.loads(out_path.read_text(encoding="utf-8"))
                except Exception:
                    existing = None
            if not isinstance(existing, list):
                existing = []
            existing.append(payload)

            if len(existing) > 2000:
                existing = existing[-2000:]

            out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

    def _component_id_from_body_id(self, body_id: str) -> str:
        # body_id := "{component_id}:body:{index}"; component_id may itself contain ':'
        if not isinstance(body_id, str) or not body_id:
            raise RuntimeError("Invalid body_id")
        marker = ":body:"
        if marker not in body_id:
            # Fallback: treat everything before last ':body' segment as component_id
            parts = body_id.split(":")
            if len(parts) >= 3 and parts[-2] == "body":
                return ":".join(parts[:-2])
            raise RuntimeError(f"Invalid body_id format: {body_id}")
        return body_id.split(marker)[0]

    def _normalized_logical_name(self, value: str | None) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return re.sub(r":\d+$", "", text)

    def _is_standard_part_logical_name(self, value: str | None) -> bool:
        logical = self._normalized_logical_name(value)
        if not logical:
            return False

        standard_parts = getattr(self, "_standard_parts", None)
        if isinstance(standard_parts, dict):
            by_name = standard_parts.get("by_component_name")
            if isinstance(by_name, dict) and logical in by_name:
                return True

        # Fallback for runtime-only cases where registry metadata is unavailable.
        logical_l = logical.lower()
        return ("bearing" in logical_l) or ("fastener" in logical_l)

    def _is_standard_part_occurrence(self, occurrence_id: str, occ=None) -> bool:
        if not isinstance(occurrence_id, str) or not occurrence_id:
            return False

        candidates: list[str] = []

        if occurrence_id.startswith("occ:") and occurrence_id.count(":") >= 2:
            try:
                candidates.append(occurrence_id[len("occ:") :].rsplit(":", 1)[0])
            except Exception:
                pass

        display_names = getattr(self, "_occurrence_display_names", None)
        if isinstance(display_names, dict):
            display_name = display_names.get(occurrence_id)
            if isinstance(display_name, str) and display_name:
                candidates.append(display_name)

        component_names = getattr(self, "_occurrence_component_names", None)
        if isinstance(component_names, dict):
            component_name = component_names.get(occurrence_id)
            if isinstance(component_name, str) and component_name:
                candidates.append(component_name)

        if occ is not None and getattr(occ, "isValid", False):
            try:
                occ_name = getattr(occ, "name", None)
                if isinstance(occ_name, str) and occ_name:
                    candidates.append(occ_name)
            except Exception:
                pass
            try:
                comp = getattr(occ, "component", None)
                comp_name = getattr(comp, "name", None) if comp is not None else None
                if isinstance(comp_name, str) and comp_name:
                    candidates.append(comp_name)
            except Exception:
                pass

        for candidate in candidates:
            if self._is_standard_part_logical_name(candidate):
                return True
        return False

    def _standard_part_hint_from_occurrence_id(self, occurrence_id: str) -> bool:
        """Conservative fallback for hosted-standard-part joint guard.

        Runtime logs show that in some Fusion sessions occurrence metadata can be
        stale during joint creation, causing `_is_standard_part_occurrence` to
        miss obvious hosted standard parts. Use occurrence-id logical name as a
        last-resort guard to prevent creating joints on standard parts.
        """
        if not isinstance(occurrence_id, str) or not occurrence_id:
            return False

        logical = occurrence_id
        if occurrence_id.startswith("occ:") and occurrence_id.count(":") >= 2:
            try:
                logical = occurrence_id[len("occ:") :].rsplit(":", 1)[0]
            except Exception:
                logical = occurrence_id

        logical_l = str(logical).strip().lower()
        if not logical_l:
            return False
        return ("bearing" in logical_l) or ("fastener" in logical_l)

    def _joint_pose_guard_for_standard_part(
        self,
        *,
        occurrence_id: str,
        occurrence,
        pre_translation_mm: dict | None,
        post_translation_mm: dict | None,
        drift_threshold_mm: float = 0.2,
    ) -> dict:
        # DEPRECATION NOTE (Knife 4 — execution layer):
        # This function is a runtime transition guard.  Its purpose is to correct
        # any accidental joint-induced pose drift for standard parts that slip through
        # into the execution layer.
        #
        # With the three-knife architecture in place (Agent3a realization_class,
        # Agent4 relation_execution_policy, Agent5 Knife-3 step filter), no
        # assembly joint should ever reference a hosted standard part occurrence.
        # Once those planning-layer guards are fully validated in production runs,
        # this runtime correction path should be reviewed and removed.
        #
        # DO NOT add new call sites.  Track removal under the hosted-standard-part
        # architecture cleanup milestone.
        result = {
            "occurrence_id": occurrence_id,
            "is_standard_part": False,
            "corrected": False,
        }

        if not self._is_standard_part_occurrence(occurrence_id, occurrence):
            return result

        result["is_standard_part"] = True

        if not isinstance(post_translation_mm, dict):
            return result

        expected_map = getattr(self, "_occurrence_last_translation_mm", None)
        expected = None
        if isinstance(expected_map, dict):
            resolved_id = self._resolve_occurrence_id(occurrence_id)
            expected = expected_map.get(resolved_id) or expected_map.get(occurrence_id)
        expected_rotation_map = getattr(self, "_occurrence_last_rotation_rpy_deg", None)
        expected_rotation = None
        if isinstance(expected_rotation_map, dict):
            resolved_id = self._resolve_occurrence_id(occurrence_id)
            expected_rotation = expected_rotation_map.get(resolved_id) or expected_rotation_map.get(occurrence_id)
        if not isinstance(expected, dict):
            expected = pre_translation_mm if isinstance(pre_translation_mm, dict) else None
        if not isinstance(expected, dict):
            return result
        if not isinstance(expected_rotation, dict):
            expected_rotation = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}

        drift = self._mm_translation_distance(post_translation_mm, expected)
        if drift is None or float(drift) <= float(drift_threshold_mm):
            return result

        result["expected_translation_mm"] = dict(expected)
        result["expected_rotation_rpy_deg"] = {
            "roll": float(expected_rotation.get("roll", 0.0)),
            "pitch": float(expected_rotation.get("pitch", 0.0)),
            "yaw": float(expected_rotation.get("yaw", 0.0)),
        }
        result["post_translation_mm"] = dict(post_translation_mm)
        result["drift_mm"] = float(drift)

        try:
            corrected = self.SET_OCCURRENCE_TRANSFORM_R1(
                occurrence_id=occurrence_id,
                transform_mm={
                    "translation": {
                        "x": float(expected.get("x", 0.0)),
                        "y": float(expected.get("y", 0.0)),
                        "z": float(expected.get("z", 0.0)),
                    },
                    "rotation_rpy_deg": {
                        "roll": float(expected_rotation.get("roll", 0.0)),
                        "pitch": float(expected_rotation.get("pitch", 0.0)),
                        "yaw": float(expected_rotation.get("yaw", 0.0)),
                    },
                },
                grounded=False,
                mode="absolute",
                step_id="runtime_joint_pose_guard",
            )
            result["corrected"] = bool(isinstance(corrected, dict) and corrected.get("applied"))
            refreshed = self._require_occurrence(occurrence_id)
            result["corrected_translation_mm"] = self._occurrence_translation_mm(refreshed)
        except Exception as exc:
            result["error"] = str(exc)

        return result

    def _entity_recovery_marker(self, obj):
        if obj is None or not getattr(obj, "isValid", False):
            return None
        native = self._safe_native_object(obj)
        native_token = self._safe_entity_token(native)
        if native_token:
            return native_token
        token = self._safe_entity_token(obj)
        if token:
            return token
        if native is not None and getattr(native, "isValid", False):
            return id(native)
        return id(obj)

    def _iter_component_variants(self, comp):
        seen = set()
        for candidate in (comp, self._safe_native_object(comp)):
            if candidate is None or not getattr(candidate, "isValid", False):
                continue
            marker = self._safe_entity_token(candidate) or id(candidate)
            if marker is None or marker in seen:
                continue
            seen.add(marker)
            yield candidate

    def _iter_body_variants(self, body):
        seen = set()
        for candidate in (body, self._safe_native_object(body)):
            if candidate is None or not getattr(candidate, "isValid", False):
                continue
            marker = self._safe_entity_token(candidate) or id(candidate)
            if marker is None or marker in seen:
                continue
            seen.add(marker)
            yield candidate

    def _iter_body_collection_variants(self, bodies):
        seen = set()
        try:
            count = int(getattr(bodies, "count", 0) or 0) if bodies is not None else 0
        except Exception:
            count = 0
        for idx in range(count):
            try:
                body = bodies.item(idx)
            except Exception:
                continue
            for candidate_body in self._iter_body_variants(body):
                marker = self._entity_recovery_marker(candidate_body)
                if marker is None or marker in seen:
                    continue
                seen.add(marker)
                yield candidate_body

    def _iter_direct_component_bodies(self, comp):
        if comp is None or not getattr(comp, "isValid", False):
            return
        try:
            bodies = getattr(comp, "bRepBodies", None)
        except Exception:
            bodies = None
        yield from self._iter_body_collection_variants(bodies)

    def _iter_occurrence_candidate_bodies(self, occ):
        if occ is None or not getattr(occ, "isValid", False):
            return

        seen = set()

        def _yield(candidate_body):
            marker = self._entity_recovery_marker(candidate_body)
            if marker is None or marker in seen:
                return
            seen.add(marker)
            yield candidate_body

        try:
            occ_bodies = getattr(occ, "bRepBodies", None)
        except Exception:
            occ_bodies = None
        for candidate_body in self._iter_body_collection_variants(occ_bodies):
            yield from _yield(candidate_body)

        comp = self._resolve_physical_component_from_occurrence(occ)
        for body in self._iter_direct_component_bodies(comp):
            yield from _yield(body)
            native_body = self._safe_native_object(body)
            for source_body in (native_body, body):
                if source_body is None or not getattr(source_body, "isValid", False):
                    continue
                if not hasattr(source_body, "createForAssemblyContext"):
                    continue
                try:
                    prox = source_body.createForAssemblyContext(occ)
                except Exception:
                    prox = None
                yield from _yield(prox)

    def _iter_body_recovery_variants(self, body, *, occurrence=None):
        seen = set()

        def _yield(candidate):
            marker = self._entity_recovery_marker(candidate)
            if marker is None or marker in seen:
                return
            seen.add(marker)
            yield candidate

        seed_variants = []
        for candidate in self._iter_body_variants(body):
            seed_variants.append(candidate)
            yield from _yield(candidate)

        hydrated = []
        for candidate in seed_variants:
            token = self._safe_entity_token(candidate)
            resolved = self._resolve_entity_by_token_value(token, adsk.fusion.BRepBody, kind="body")
            for variant in (resolved, self._safe_native_object(resolved)):
                if variant is None or not getattr(variant, "isValid", False):
                    continue
                hydrated.append(variant)
                yield from _yield(variant)

        if occurrence is None or not getattr(occurrence, "isValid", False):
            return

        for candidate in [*seed_variants, *hydrated]:
            if candidate is None or not getattr(candidate, "isValid", False):
                continue
            if not hasattr(candidate, "createForAssemblyContext"):
                continue
            try:
                prox = candidate.createForAssemblyContext(occurrence)
            except Exception:
                prox = None
            yield from _yield(prox)

    def _iter_component_candidate_bodies(self, comp):
        seen = set()
        for candidate_comp in self._iter_component_variants(comp):
            for candidate_body in self._iter_direct_component_bodies(candidate_comp):
                marker = self._entity_recovery_marker(candidate_body)
                if marker is None or marker in seen:
                    continue
                seen.add(marker)
                yield candidate_body

    def _list_component_candidate_bodies(self, comp) -> list[Any]:
        bodies: list[Any] = []
        try:
            bodies = list(self._iter_component_candidate_bodies(comp))
        except Exception:
            bodies = []

        if bodies:
            return bodies

        try:
            direct_bodies = getattr(comp, "bRepBodies", None)
            count = int(getattr(direct_bodies, "count", 0) or 0) if direct_bodies is not None else 0
        except Exception:
            return []

        for idx in range(count):
            try:
                body = direct_bodies.item(idx)
            except Exception:
                continue
            if body is None or not getattr(body, "isValid", False):
                continue
            bodies.append(body)
        return bodies

    def _resolve_component_recovery_variant(
        self,
        comp,
        *,
        require_bodies: bool = False,
        require_faces: bool = False,
    ):
        chosen = None
        for candidate in self._iter_component_variants(comp):
            if chosen is None:
                chosen = candidate
            if not require_bodies and not require_faces:
                return candidate
            for body in self._iter_direct_component_bodies(candidate):
                if require_faces and not self._body_has_faces(body):
                    continue
                return candidate
        if not require_bodies and not require_faces:
            return chosen
        return None

    def _component_has_candidate_body(self, comp, *, require_faces: bool = False) -> bool:
        if comp is None or not getattr(comp, "isValid", False):
            return False
        if not require_faces:
            return any(True for _ in self._iter_component_candidate_bodies(comp))
        for body in self._iter_component_candidate_bodies(comp):
            if self._body_has_faces(body):
                return True
        return False

    def _recover_component_from_occurrence(
        self,
        component_id: str,
        *,
        require_bodies: bool = False,
        require_faces: bool = False,
    ):
        if not isinstance(component_id, str) or not component_id:
            return None

        exact_occurrence_id = None
        base_name = None
        if component_id.startswith("comp:") and component_id.count(":") >= 2:
            suffix = component_id[len("comp:") :]
            exact_occurrence_id = f"occ:{suffix}"
            base_name = suffix.rsplit(":", 1)[0]

        candidate_keys = []
        for key in (exact_occurrence_id, component_id, base_name):
            if isinstance(key, str) and key:
                candidate_keys.append(key)

        seen_occurrences: Set[int] = set()
        fallback_comp = None
        for key in candidate_keys:
            for mapping in (self._occurrences, self._listed_occurrences):
                occ = mapping.get(key) if isinstance(mapping, dict) else None
                if occ is None or id(occ) in seen_occurrences:
                    continue
                seen_occurrences.add(id(occ))
                if not getattr(occ, "isValid", False):
                    continue
                comp = self._resolve_physical_component_from_occurrence(occ)
                if comp is None or not getattr(comp, "isValid", False):
                    continue
                resolved_comp = self._resolve_component_recovery_variant(
                    comp,
                    require_bodies=require_bodies,
                    require_faces=require_faces,
                )
                if resolved_comp is not None:
                    self._components[component_id] = resolved_comp
                    return resolved_comp
                if fallback_comp is None:
                    fallback_comp = self._resolve_component_recovery_variant(comp)

        if isinstance(exact_occurrence_id, str) and exact_occurrence_id:
            try:
                recovered_occ = self._recover_occurrence_from_live_tree(exact_occurrence_id)
            except Exception:
                recovered_occ = None
            if recovered_occ is not None and getattr(recovered_occ, "isValid", False):
                seen_occurrences.add(id(recovered_occ))
                comp = self._resolve_physical_component_from_occurrence(recovered_occ)
                if comp is not None and getattr(comp, "isValid", False):
                    resolved_comp = self._resolve_component_recovery_variant(
                        comp,
                        require_bodies=require_bodies,
                        require_faces=require_faces,
                    )
                    if resolved_comp is not None:
                        self._components[component_id] = resolved_comp
                        return resolved_comp
                    if fallback_comp is None:
                        fallback_comp = self._resolve_component_recovery_variant(comp)

        display_names = getattr(self, "_occurrence_display_names", None)
        component_names = getattr(self, "_occurrence_component_names", None)
        target_display = display_names.get(exact_occurrence_id) if isinstance(display_names, dict) and isinstance(exact_occurrence_id, str) else None
        target_component = component_names.get(exact_occurrence_id) if isinstance(component_names, dict) and isinstance(exact_occurrence_id, str) else None
        normalized_target_component = self._normalized_logical_name(target_component)
        normalized_base_name = self._normalized_logical_name(base_name)

        live_display_matches = []
        live_component_matches = []
        live_base_matches = []
        seen_live_components: set[object] = set()
        for occ in self._iter_live_occurrences() or []:
            if occ is None or id(occ) in seen_occurrences:
                continue
            seen_occurrences.add(id(occ))
            if not getattr(occ, "isValid", False):
                continue
            comp = self._resolve_component_recovery_variant(self._resolve_physical_component_from_occurrence(occ))
            if comp is None or not getattr(comp, "isValid", False):
                continue
            comp_key = self._entity_recovery_marker(comp)
            if comp_key is None or comp_key in seen_live_components:
                continue
            seen_live_components.add(comp_key)
            occ_name = str(getattr(occ, "name", "") or "")
            comp_name = str(getattr(comp, "name", "") or "")
            normalized_occ_name = self._normalized_logical_name(occ_name)
            normalized_comp_name = self._normalized_logical_name(comp_name)
            if target_display and occ_name == target_display:
                live_display_matches.append(comp)
                continue
            if target_component and (comp_name == target_component or (normalized_target_component and normalized_comp_name == normalized_target_component)):
                live_component_matches.append(comp)
                continue
            if normalized_base_name and (normalized_occ_name == normalized_base_name or normalized_comp_name == normalized_base_name):
                live_base_matches.append(comp)

        for candidates in (live_display_matches, live_component_matches, live_base_matches):
            if len(candidates) == 1:
                candidate = candidates[0]
                resolved_comp = self._resolve_component_recovery_variant(
                    candidate,
                    require_bodies=require_bodies,
                    require_faces=require_faces,
                )
                if resolved_comp is None:
                    continue
                self._components[component_id] = resolved_comp
                return resolved_comp

        if fallback_comp is not None and not require_bodies and not require_faces:
            self._components[component_id] = fallback_comp
            return fallback_comp
        return None


    def _body_has_faces(self, body) -> bool:
        try:
            faces = getattr(body, "faces", None)
            if faces is None:
                return False
            try:
                count = int(getattr(faces, "count", 0) or 0)
            except Exception:
                count = 0
            if count > 0:
                return True
            if hasattr(faces, "item"):
                try:
                    first_face = faces.item(0)
                    return bool(first_face) and getattr(first_face, "isValid", True)
                except Exception:
                    return False
            return False
        except Exception:
            return False

    def _recover_body_from_component(self, body_id: str, *, require_faces: bool = False):
        try:
            component_id = self._component_id_from_body_id(body_id)
        except Exception:
            return None
        exact_occurrence_id = None
        base_name = None
        if component_id.startswith("comp:") and component_id.count(":") >= 2:
            suffix = component_id[len("comp:") :]
            exact_occurrence_id = f"occ:{suffix}"
            base_name = suffix.rsplit(":", 1)[0]

        saved_token = self._tokens.get(body_id)
        preferred_index = None
        try:
            preferred_index = int(str(body_id).rsplit(":body:", 1)[1]) - 1
        except Exception:
            preferred_index = None

        def _accept(candidate):
            if not candidate or not getattr(candidate, "isValid", False):
                return None
            if require_faces and not self._body_has_faces(candidate):
                return None
            self._cache_body(body_id, candidate)
            return candidate

        def _try_from_bodies(bodies, *, occurrence=None):
            if not bodies:
                return None

            def _variants_for(candidate):
                return list(self._iter_body_recovery_variants(candidate, occurrence=occurrence))

            if isinstance(saved_token, str) and saved_token:
                try:
                    for candidate in bodies:
                        for variant in _variants_for(candidate):
                            token = self._safe_entity_token(variant) or self._safe_entity_token(self._safe_native_object(variant))
                            if not (isinstance(token, str) and token == saved_token):
                                continue
                            recovered = _accept(variant)
                            if recovered is not None:
                                return recovered
                except Exception:
                    pass

            if isinstance(preferred_index, int) and preferred_index >= 0 and preferred_index < len(bodies):
                try:
                    for variant in _variants_for(bodies[preferred_index]):
                        recovered = _accept(variant)
                        if recovered is not None:
                            return recovered
                except Exception:
                    pass

            try:
                for candidate in bodies:
                    for variant in _variants_for(candidate):
                        recovered = _accept(variant)
                        if recovered is not None:
                            return recovered
            except Exception:
                return None
            return None

        def _try_from_component(comp):
            if comp is None or not getattr(comp, "isValid", False):
                return None
            return _try_from_bodies(list(self._iter_component_candidate_bodies(comp)))

        def _try_from_occurrence(occ):
            if occ is None or not getattr(occ, "isValid", False):
                return None
            return _try_from_bodies(list(self._iter_occurrence_candidate_bodies(occ)), occurrence=occ)

        candidate_components = []
        seen_components = set()

        def _push_component(comp):
            if comp is None or not getattr(comp, "isValid", False):
                return
            marker = self._entity_recovery_marker(comp)
            if marker in seen_components:
                return
            seen_components.add(marker)
            candidate_components.append(comp)

        _push_component(self._components.get(component_id))
        _push_component(
            self._recover_component_from_occurrence(
                component_id,
                require_bodies=True,
                require_faces=require_faces,
            )
        )

        candidate_occurrences = []
        seen_occurrences = set()

        def _push_occurrence(occ):
            if occ is None or not getattr(occ, "isValid", False):
                return
            marker = self._entity_recovery_marker(occ)
            if marker in seen_occurrences:
                return
            seen_occurrences.add(marker)
            candidate_occurrences.append(occ)

        if isinstance(exact_occurrence_id, str) and exact_occurrence_id:
            occurrences = getattr(self, "_occurrences", None)
            listed_occurrences = getattr(self, "_listed_occurrences", None)
            _push_occurrence(occurrences.get(exact_occurrence_id) if isinstance(occurrences, dict) else None)
            _push_occurrence(listed_occurrences.get(exact_occurrence_id) if isinstance(listed_occurrences, dict) else None)
            _push_occurrence(self._recover_occurrence_from_live_tree(exact_occurrence_id))

        display_names = getattr(self, "_occurrence_display_names", None)
        component_names = getattr(self, "_occurrence_component_names", None)
        target_display = display_names.get(exact_occurrence_id) if isinstance(display_names, dict) and isinstance(exact_occurrence_id, str) else None
        target_component = component_names.get(exact_occurrence_id) if isinstance(component_names, dict) and isinstance(exact_occurrence_id, str) else None
        normalized_target_display = self._normalized_logical_name(target_display)
        normalized_target_component = self._normalized_logical_name(target_component)
        normalized_base_name = self._normalized_logical_name(base_name)

        for occ in candidate_occurrences:
            try:
                recovered = _try_from_occurrence(occ)
            except Exception:
                recovered = None
            if recovered is not None:
                return recovered

        for occ in self._iter_live_occurrences() or []:
            if occ is None or not getattr(occ, "isValid", False):
                continue
            try:
                occ_name = str(getattr(occ, "name", "") or "")
            except Exception:
                occ_name = ""
            try:
                occ_comp = getattr(occ, "component", None)
            except Exception:
                occ_comp = None
            try:
                comp_name = str(getattr(occ_comp, "name", "") or "")
            except Exception:
                comp_name = ""
            normalized_occ_name = self._normalized_logical_name(occ_name)
            normalized_comp_name = self._normalized_logical_name(comp_name)

            matches = False
            if isinstance(target_display, str) and target_display and occ_name == target_display:
                matches = True
            elif normalized_target_display and normalized_occ_name == normalized_target_display:
                matches = True
            elif isinstance(target_component, str) and target_component and comp_name == target_component:
                matches = True
            elif normalized_target_component and normalized_comp_name == normalized_target_component:
                matches = True
            elif normalized_base_name and (normalized_occ_name == normalized_base_name or normalized_comp_name == normalized_base_name):
                matches = True

            if not matches:
                continue
            _push_occurrence(occ)

        for occ in candidate_occurrences:
            try:
                recovered = _try_from_occurrence(occ)
            except Exception:
                recovered = None
            if recovered is not None:
                if isinstance(exact_occurrence_id, str) and exact_occurrence_id:
                    try:
                        self._cache_occurrence(exact_occurrence_id, occ)
                    except Exception:
                        pass
                return recovered

        for comp in candidate_components:
            try:
                recovered = _try_from_component(comp)
            except Exception:
                recovered = None
            if recovered is not None:
                return recovered
        return None

    def _axis_vec(self, axis: str) -> tuple[float, float, float]:
        a = str(axis or "Z").upper()
        if a == "X":
            return (1.0, 0.0, 0.0)
        if a == "Y":
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)

    def _angle_deg_to_axis(self, normal: dict | None, axis: str) -> float | None:
        if not isinstance(normal, dict):
            return None
        try:
            nx = float(normal.get("x") or 0.0)
            ny = float(normal.get("y") or 0.0)
            nz = float(normal.get("z") or 0.0)
        except Exception:
            return None
        ax, ay, az = self._axis_vec(axis)
        # parallel up to sign
        dot = abs(nx * ax + ny * ay + nz * az)
        dot = max(0.0, min(1.0, dot))
        try:
            return float(math.degrees(math.acos(dot)))
        except Exception:
            return None

    def _mk_interface_marker_id(self, component_id: str, interface_name: str) -> str:
        return f"mkr:ifc:{component_id}:{interface_name}"

    def _cache_marker_from_entity(self, *, marker_id: str, entity_kind: str, entity_id: str, interface_name: str | None = None) -> None:
        if not isinstance(marker_id, str) or not marker_id:
            raise RuntimeError("Invalid marker_id")
        if not isinstance(entity_kind, str) or not entity_kind:
            raise RuntimeError("Invalid entity_kind")
        if not isinstance(entity_id, str) or not entity_id:
            raise RuntimeError("Invalid entity_id")

        token = self._tokens.get(entity_id)
        if not token:
            # Best-effort: if entity_id is cached but token missing, register it again
            try:
                if entity_kind == "face":
                    self._register_token(entity_id, self._faces.get(entity_id))
                elif entity_kind == "edge":
                    self._register_token(entity_id, self._edges.get(entity_id))
                elif entity_kind == "axis":
                    self._register_token(entity_id, self._axes.get(entity_id))
            except Exception:
                pass
            token = self._tokens.get(entity_id)
        if not token:
            raise RuntimeError(f"Cannot create marker '{marker_id}': missing entityToken for {entity_kind} {entity_id}")

        # Marker itself resolves via token
        self._tokens[marker_id] = token
        self._markers[marker_id] = {
            "entity_kind": entity_kind,
            "source_entity_id": entity_id,
            "interface_name": interface_name,
        }

    def _resolve_marker_entity_kind(self, marker_id: str) -> str:
        meta = self._markers.get(marker_id)
        if isinstance(meta, dict) and isinstance(meta.get("entity_kind"), str) and meta.get("entity_kind"):
            return str(meta.get("entity_kind"))
        # Fallback: assume face markers
        return "face"

    def _resolve_marker_to_entity_ref(self, marker_id: str) -> dict:
        if not isinstance(marker_id, str) or not marker_id:
            raise RuntimeError("Invalid marker_id")
        kind = self._resolve_marker_entity_kind(marker_id)
        meta = self._markers.get(marker_id)
        source_entity_id = meta.get("source_entity_id") if isinstance(meta, dict) and isinstance(meta.get("source_entity_id"), str) else None

        if kind == "face":
            face = None
            if source_entity_id:
                try:
                    face = self._require_face(source_entity_id)
                except Exception:
                    face = None
            if not face or not face.isValid:
                face = self._resolve_by_token(marker_id, adsk.fusion.BRepFace, "marker.face")
            if not face or not face.isValid:
                raise RuntimeError(f"Marker face not found or invalid: {marker_id}")
            face_id = source_entity_id or f"mface:{marker_id}"
            self._cache_face(face_id, face)
            return {"type": "face", "face_id": face_id}
        if kind == "edge":
            edge = None
            if source_entity_id:
                try:
                    edge = self._require_edge(source_entity_id)
                except Exception:
                    edge = None
            if not edge or not edge.isValid:
                edge = self._resolve_by_token(marker_id, adsk.fusion.BRepEdge, "marker.edge")
            if not edge or not edge.isValid:
                raise RuntimeError(f"Marker edge not found or invalid: {marker_id}")
            edge_id = source_entity_id or f"medge:{marker_id}"
            self._cache_edge(edge_id, edge)
            return {"type": "edge", "edge_id": edge_id}
        if kind == "axis":
            axis_obj = None
            if source_entity_id:
                try:
                    axis_obj = self._require_axis(source_entity_id)
                except Exception:
                    axis_obj = None
            if not axis_obj or not axis_obj.isValid:
                axis_obj = self._resolve_by_token(marker_id, adsk.fusion.ConstructionAxis, "marker.axis")
            if not axis_obj or not axis_obj.isValid:
                raise RuntimeError(f"Marker axis not found or invalid: {marker_id}")
            axis_id = source_entity_id or f"maxis:{marker_id}"
            self._axes[axis_id] = axis_obj
            self._register_token(axis_id, axis_obj)
            return {"type": "axis", "axis_id": axis_id}

        raise RuntimeError(f"Unsupported marker entity_kind: {kind}")
    def _iter_body_faces_cached(self, body_id: str):
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        if not self._body_has_faces(body):
            recovered = self._recover_body_from_component(body_id, require_faces=True)
            if recovered is not None:
                body = recovered

        component_id = self._component_id_from_body_id(body_id)
        if not self._body_has_faces(body):
            comp = self._components.get(component_id)
            if comp is not None and getattr(comp, "isValid", False):
                try:
                    for candidate in self._valid_solid_bodies(comp):
                        if not self._body_has_faces(candidate):
                            continue
                        self._cache_body(body_id, candidate)
                        body = candidate
                        break
                except Exception:
                    pass
        if not self._body_has_faces(body):
            return []

        out = []
        for i in range(body.faces.count):
            face = body.faces.item(i)
            if not face or not face.isValid:
                continue
            face_id = self._next_face_id(component_id)
            self._cache_face(face_id, face)
            out.append((face_id, face))
        return out

    def _select_face_by_recipe(self, *, body_id: str, recipe: dict) -> tuple[str, str, dict | None, dict]:
        """Return (entity_kind, entity_id, geometry_summary). Fail-fast if no match."""

        geometry_type = recipe.get("geometry_type") if isinstance(recipe.get("geometry_type"), str) else "planar"
        selection_raw = recipe.get("selection")
        selection: list = selection_raw if isinstance(selection_raw, list) else []
        fallback_policy = recipe.get("fallback_policy") if isinstance(recipe.get("fallback_policy"), str) else None
        # Agent2 emits "recipe_policy" while this reader expects "fallback_policy"; accept both.
        if fallback_policy is None:
            _rp = recipe.get("recipe_policy")
            if isinstance(_rp, str) and "any_patch" in _rp:
                fallback_policy = "planar_any_patch"
        usage = recipe.get("usage") if isinstance(recipe.get("usage"), str) else None
        effective_fallback_policy = fallback_policy
        if effective_fallback_policy is None and geometry_type not in {"axis", "cylindrical"}:
            if usage in {"mate_surface", "mount_surface", "interface_surface", "drill_anchor"}:
                effective_fallback_policy = "planar_any_patch"

        # Extract common predicates
        target_axis = None
        normal_tol_deg = None
        axis_parallel_axis = None
        axis_parallel_tol_deg = None
        centroid_z_prefer = None
        centroid_axis_prefer = None
        centroid_axis = None
        area_min_mm2 = None
        radial_min_mm = None
        radial_max_mm = None
        radial_axis = None
        bbox_contains_axis_projection_present = False
        radius_mm = None
        radius_tol_mm = 0.05
        interface_plane_axis = None
        interface_plane_preference = None
        distance_to_origin_axis = None
        distance_to_origin_preference = None
        closest_point_target = None
        closest_point_tolerance_mm = None

        for rule in selection:
            if not isinstance(rule, dict):
                continue
            pred = rule.get("predicate")
            if pred == "normal_parallel":
                axis = rule.get("axis")
                tol = rule.get("tolerance_deg")
                if isinstance(axis, str) and axis:
                    target_axis = axis
                if isinstance(tol, (int, float)) and float(tol) > 0:
                    normal_tol_deg = float(tol)
            elif pred == "axis_parallel":
                axis = rule.get("axis")
                tol = rule.get("tolerance_deg")
                if isinstance(axis, str) and axis:
                    axis_parallel_axis = str(axis).upper()
                if isinstance(tol, (int, float)) and float(tol) > 0:
                    axis_parallel_tol_deg = float(tol)
            elif pred == "centroid_z_rank":
                prefer = rule.get("prefer")
                if prefer in {"min", "max"}:
                    centroid_z_prefer = prefer
            elif pred == "centroid_axis_rank":
                axis = rule.get("axis")
                prefer = rule.get("prefer")
                if isinstance(axis, str) and axis:
                    centroid_axis = str(axis).upper()
                if prefer in {"min", "max"}:
                    centroid_axis_prefer = prefer
            elif pred == "area_min":
                v = rule.get("min_area_mm2")
                if isinstance(v, (int, float)):
                    area_min_mm2 = float(v)
            elif pred == "bbox_contains_axis_projection":
                bbox_contains_axis_projection_present = True
                axis = rule.get("axis")
                if isinstance(axis, str) and axis:
                    radial_axis = axis
                vmin = rule.get("radial_min_mm")
                vmax = rule.get("radial_max_mm")
                if isinstance(vmin, (int, float)):
                    radial_min_mm = float(vmin)
                if isinstance(vmax, (int, float)):
                    radial_max_mm = float(vmax)
            elif pred == "radius_mm":
                v = rule.get("value")
                if isinstance(v, (int, float)):
                    radius_mm = float(v)
            elif pred == "radius_proximity":
                v = rule.get("target_radius_mm")
                if isinstance(v, (int, float)):
                    radius_mm = float(v)
                tol = rule.get("tolerance_mm")
                if isinstance(tol, (int, float)) and float(tol) > 0:
                    radius_tol_mm = float(tol)
            elif pred == "radius_from_param":
                v = rule.get("value")
                if isinstance(v, (int, float)):
                    radius_mm = float(v)
                tol = rule.get("tolerance_mm")
                if isinstance(tol, (int, float)) and float(tol) > 0:
                    radius_tol_mm = float(tol)
            elif pred == "closest_to_interface_plane":
                axis = rule.get("axis")
                prefer = rule.get("plane_preference")
                if isinstance(axis, str) and axis:
                    interface_plane_axis = str(axis).upper()
                if prefer in {"min", "max"}:
                    interface_plane_preference = str(prefer)
            elif pred == "distance_to_origin":
                axis = rule.get("axis")
                prefer = rule.get("prefer")
                if isinstance(axis, str) and axis:
                    distance_to_origin_axis = str(axis).upper()
                if prefer in {"min", "max"}:
                    distance_to_origin_preference = str(prefer)
            elif pred == "closest_to_point":
                target_point = rule.get("target_point_mm")
                if isinstance(target_point, dict):
                    try:
                        closest_point_target = {
                            "x": float(target_point.get("x", 0.0)),
                            "y": float(target_point.get("y", 0.0)),
                            "z": float(target_point.get("z", 0.0)),
                        }
                    except Exception:
                        closest_point_target = None
                tol = rule.get("tolerance_mm")
                if isinstance(tol, (int, float)) and float(tol) > 0:
                    closest_point_tolerance_mm = float(tol)

        if bbox_contains_axis_projection_present:
            if not isinstance(radial_axis, str) or not radial_axis:
                if isinstance(centroid_axis, str) and centroid_axis:
                    radial_axis = centroid_axis
                elif isinstance(axis_parallel_axis, str) and axis_parallel_axis:
                    radial_axis = axis_parallel_axis
                elif isinstance(target_axis, str) and target_axis:
                    radial_axis = target_axis
                else:
                    radial_axis = "Z"
            if radial_min_mm is None and radial_max_mm is None:
                radial_max_mm = 0.0

        expected_raw = recipe.get("expected_geometry")
        expected: dict = expected_raw if isinstance(expected_raw, dict) else {}
        if target_axis is None and isinstance(expected.get("target_normal_axis"), str):
            target_axis = str(expected.get("target_normal_axis"))
        if normal_tol_deg is None and isinstance(expected.get("normal_tolerance_deg"), (int, float)):
            normal_tol_deg = float(expected.get("normal_tolerance_deg") or 0.0)
        if axis_parallel_axis is None and isinstance(expected.get("target_normal_axis"), str):
            axis_parallel_axis = str(expected.get("target_normal_axis")).upper()
        if axis_parallel_tol_deg is None and isinstance(expected.get("normal_tolerance_deg"), (int, float)):
            axis_parallel_tol_deg = float(expected.get("normal_tolerance_deg") or 0.0)
        if area_min_mm2 is None and isinstance(expected.get("min_area_mm2"), (int, float)):
            area_min_mm2 = float(expected.get("min_area_mm2") or 0.0)
        if centroid_z_prefer is None and isinstance(expected.get("centroid_z_preference"), str):
            if expected.get("centroid_z_preference") in {"min", "max"}:
                centroid_z_prefer = str(expected.get("centroid_z_preference"))
        if centroid_axis is None and isinstance(expected.get("centroid_axis"), str):
            centroid_axis = str(expected.get("centroid_axis")).upper()
        if centroid_axis_prefer is None and isinstance(expected.get("centroid_axis_preference"), str):
            if expected.get("centroid_axis_preference") in {"min", "max"}:
                centroid_axis_prefer = str(expected.get("centroid_axis_preference"))

        # Backward compatibility: if only centroid_z_* was provided, treat it as axis=Z.
        if centroid_axis is None and centroid_z_prefer in {"min", "max"}:
            centroid_axis = "Z"
        if centroid_axis_prefer is None and centroid_z_prefer in {"min", "max"}:
            centroid_axis_prefer = centroid_z_prefer
        if interface_plane_axis is None and isinstance(expected.get("centroid_axis"), str):
            interface_plane_axis = str(expected.get("centroid_axis")).upper()
        if interface_plane_preference is None and isinstance(expected.get("interface_plane_preference"), str):
            if expected.get("interface_plane_preference") in {"min", "max"}:
                interface_plane_preference = str(expected.get("interface_plane_preference"))
        if radius_mm is None and isinstance(expected.get("target_radius_mm"), (int, float)):
            radius_mm = float(expected.get("target_radius_mm") or 0.0)
        if isinstance(expected.get("radius_tolerance_mm"), (int, float)) and float(expected.get("radius_tolerance_mm") or 0.0) > 0:
            radius_tol_mm = float(expected.get("radius_tolerance_mm"))
        if closest_point_target is None:
            expected_target_point = expected.get("target_point_mm")
            if isinstance(expected_target_point, dict):
                try:
                    closest_point_target = {
                        "x": float(expected_target_point.get("x", 0.0)),
                        "y": float(expected_target_point.get("y", 0.0)),
                        "z": float(expected_target_point.get("z", 0.0)),
                    }
                except Exception:
                    closest_point_target = None
        if distance_to_origin_axis is None:
            if isinstance(centroid_axis, str) and centroid_axis:
                distance_to_origin_axis = centroid_axis
            elif isinstance(axis_parallel_axis, str) and axis_parallel_axis:
                distance_to_origin_axis = axis_parallel_axis
            elif isinstance(target_axis, str) and target_axis:
                distance_to_origin_axis = target_axis
        if distance_to_origin_preference is None and isinstance(centroid_axis_prefer, str):
            distance_to_origin_preference = centroid_axis_prefer

        candidates = []
        scanned_faces = 0
        rejected_by: dict[str, int] = {}

        def _mark_reject(reason: str) -> None:
            rejected_by[reason] = int(rejected_by.get(reason, 0)) + 1

        def _point_proximity(summary: dict) -> float | None:
            if not isinstance(closest_point_target, dict):
                return None
            point_raw = summary.get("axis_origin_mm")
            if not isinstance(point_raw, dict):
                point_raw = summary.get("centroid_mm")
            if not isinstance(point_raw, dict):
                return None
            try:
                dx = float(point_raw.get("x", 0.0)) - float(closest_point_target.get("x", 0.0))
                dy = float(point_raw.get("y", 0.0)) - float(closest_point_target.get("y", 0.0))
                dz = float(point_raw.get("z", 0.0)) - float(closest_point_target.get("z", 0.0))
            except Exception:
                return None
            return math.sqrt(dx * dx + dy * dy + dz * dz)

        for face_id, face in self._iter_body_faces_cached(body_id):
            scanned_faces += 1
            kind = self._get_face_geometry_kind(face)
            if geometry_type in {"axis", "cylindrical"}:
                if kind != "cylindrical":
                    _mark_reject("geometry_type_mismatch")
                    continue
            else:
                if kind != "planar":
                    _mark_reject("geometry_type_mismatch")
                    continue

            summary = self._face_geometry_summary(face_id, face)

            # radius filter (for cylindrical)
            if radius_mm is not None:
                r = summary.get("radius_mm")
                if not isinstance(r, (int, float)):
                    _mark_reject("missing_radius")
                    continue
                if abs(float(r) - float(radius_mm)) > float(radius_tol_mm):
                    _mark_reject("radius_out_of_tolerance")
                    continue

            if axis_parallel_axis is not None and axis_parallel_tol_deg is not None and kind == "cylindrical":
                ang = self._angle_deg_to_axis(summary.get("axis_direction"), axis_parallel_axis)
                if ang is None or ang > float(axis_parallel_tol_deg):
                    _mark_reject("axis_not_parallel")
                    continue

            # area min
            if area_min_mm2 is not None:
                a = summary.get("area_mm2")
                if not isinstance(a, (int, float)) or float(a) < float(area_min_mm2):
                    _mark_reject("area_below_min")
                    continue

            # normal parallel
            if target_axis is not None and normal_tol_deg is not None and kind == "planar":
                ang = self._angle_deg_to_axis(summary.get("normal"), target_axis)
                if ang is None or ang > float(normal_tol_deg):
                    _mark_reject("normal_not_parallel")
                    continue

            if closest_point_target is not None and closest_point_tolerance_mm is not None:
                point_delta = _point_proximity(summary)
                if point_delta is None or float(point_delta) > float(closest_point_tolerance_mm):
                    _mark_reject("point_out_of_tolerance")
                    continue

            # bbox_contains_axis_projection -> bbox annulus overlap gate
            if bbox_contains_axis_projection_present:
                bbox = summary.get("bbox_mm")
                if not isinstance(bbox, dict):
                    _mark_reject("missing_bbox")
                    continue
                try:
                    min_x = float(bbox.get("min_x"))
                    max_x = float(bbox.get("max_x"))
                    min_y = float(bbox.get("min_y"))
                    max_y = float(bbox.get("max_y"))
                    min_z = float(bbox.get("min_z"))
                    max_z = float(bbox.get("max_z"))
                except Exception:
                    _mark_reject("invalid_bbox")
                    continue

                def _axis_radial_bounds(axis_name: str) -> tuple[float, float]:
                    ax = axis_name.upper()
                    if ax == "Z":
                        u_min, u_max = min_x, max_x
                        v_min, v_max = min_y, max_y
                    elif ax == "X":
                        u_min, u_max = min_y, max_y
                        v_min, v_max = min_z, max_z
                    else:
                        u_min, u_max = min_x, max_x
                        v_min, v_max = min_z, max_z

                    du = 0.0 if (u_min <= 0.0 <= u_max) else min(abs(u_min), abs(u_max))
                    dv = 0.0 if (v_min <= 0.0 <= v_max) else min(abs(v_min), abs(v_max))
                    min_r = math.sqrt(du * du + dv * dv)

                    corners = (
                        (u_min, v_min),
                        (u_min, v_max),
                        (u_max, v_min),
                        (u_max, v_max),
                    )
                    max_r = max(math.sqrt(u * u + v * v) for u, v in corners)
                    return min_r, max_r

                min_radial, max_radial = _axis_radial_bounds(str(radial_axis))
                if radial_min_mm is not None and max_radial < float(radial_min_mm):
                    _mark_reject("radial_below_min")
                    continue
                if radial_max_mm is not None and min_radial > float(radial_max_mm):
                    _mark_reject("radial_above_max")
                    continue

            # Deterministic tie-breaker token
            token = self._tokens.get(face_id) or ""
            candidates.append({
                "face_id": face_id,
                "summary": summary,
                "token": token,
            })

        fallback_applied = False
        fallback_info: dict | None = None
        if not candidates:
            if (
                isinstance(effective_fallback_policy, str)
                and effective_fallback_policy == "planar_any_patch"
                and geometry_type not in {"axis", "cylindrical"}
            ):
                relaxed_candidates = []
                relaxed_rejected_by: dict[str, int] = {}

                def _mark_relaxed_reject(reason: str) -> None:
                    relaxed_rejected_by[reason] = int(relaxed_rejected_by.get(reason, 0)) + 1

                for face_id, face in self._iter_body_faces_cached(body_id):
                    kind = self._get_face_geometry_kind(face)
                    if kind != "planar":
                        _mark_relaxed_reject("geometry_type_mismatch")
                        continue

                    summary = self._face_geometry_summary(face_id, face)

                    if target_axis is not None and normal_tol_deg is not None:
                        ang = self._angle_deg_to_axis(summary.get("normal"), target_axis)
                        if ang is None or ang > float(normal_tol_deg):
                            _mark_relaxed_reject("normal_not_parallel")
                            continue

                    relaxed_candidates.append(
                        {
                            "face_id": face_id,
                            "summary": summary,
                            "token": self._tokens.get(face_id) or "",
                        }
                    )

                if relaxed_candidates:
                    def _fallback_sort_key(row: dict):
                        summary_raw = row.get("summary")
                        summary = summary_raw if isinstance(summary_raw, dict) else {}
                        centroid_raw = summary.get("centroid_mm")
                        centroid = centroid_raw if isinstance(centroid_raw, dict) else {}
                        z_val = float(centroid.get("z", 0.0)) if isinstance(centroid.get("z"), (int, float)) else 0.0
                        area_val = float(summary.get("area_mm2", 0.0)) if isinstance(summary.get("area_mm2"), (int, float)) else 0.0
                        return (-z_val, -area_val, str(row.get("token") or ""), str(row.get("face_id") or ""))

                    relaxed_candidates = sorted(relaxed_candidates, key=_fallback_sort_key)
                    candidates = relaxed_candidates
                    fallback_applied = True
                    fallback_info = {
                        "policy": "planar_any_patch",
                        "policy_source": "recipe" if fallback_policy == "planar_any_patch" else "implicit_for_usage",
                        "relaxed_rejected_by": relaxed_rejected_by,
                        "relaxed_candidates_count": len(relaxed_candidates),
                        "note": "area_min and non-planar strict predicates ignored; kept planar + normal_parallel",
                    }
                else:
                    rejected_by = {
                        **rejected_by,
                        "fallback_relaxed_no_match": int(len(relaxed_rejected_by)),
                    }

            if not candidates:
                diagnostics = {
                    "body_id": body_id,
                    "geometry_type": geometry_type,
                    "scanned_faces": scanned_faces,
                    "rejected_by": rejected_by,
                    "fallback_policy": fallback_policy,
                    "effective_fallback_policy": effective_fallback_policy,
                    "recipe": dict(recipe) if isinstance(recipe, dict) else recipe,
                }
                raise RuntimeError(
                    "No face matches interface recipe: "
                    + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
                )

        order_raw = recipe.get("deterministic_order")
        order: list = order_raw if isinstance(order_raw, list) else []

        # Default ordering for cylindrical/axis: prefer maximum area (most stable selection).
        # For planar faces, keep existing behavior unless explicitly ordered.
        if not order and geometry_type in {"axis", "cylindrical"}:
            order = ["area_score"]

        def sort_key(row: dict):
            summary_raw = row.get("summary")
            summary: dict = summary_raw if isinstance(summary_raw, dict) else {}
            centroid_raw = summary.get("centroid_mm")
            centroid: dict = centroid_raw if isinstance(centroid_raw, dict) else {}

            def _coord(axis_name: str | None) -> float:
                axis_name = str(axis_name or "Z").upper()
                if axis_name == "X":
                    key = "x"
                elif axis_name == "Y":
                    key = "y"
                else:
                    key = "z"
                value = centroid.get(key)
                return float(value) if isinstance(value, (int, float)) else 0.0

            keys = []
            for item in order:
                if item == "normal_alignment":
                    ang = self._angle_deg_to_axis(summary.get("normal"), target_axis or "Z")
                    keys.append(float(ang) if isinstance(ang, (int, float)) else 999.0)
                elif item == "axis_alignment":
                    ang = self._angle_deg_to_axis(summary.get("axis_direction"), axis_parallel_axis or "Z")
                    keys.append(float(ang) if isinstance(ang, (int, float)) else 999.0)
                elif item == "centroid_z_rank":
                    z = centroid.get("z")
                    zf = float(z) if isinstance(z, (int, float)) else 0.0
                    if centroid_z_prefer == "max":
                        keys.append(-zf)
                    elif centroid_z_prefer == "min":
                        keys.append(zf)
                    else:
                        keys.append(0.0)
                elif item == "centroid_axis_rank":
                    vf = _coord(centroid_axis)
                    if centroid_axis_prefer == "max":
                        keys.append(-vf)
                    elif centroid_axis_prefer == "min":
                        keys.append(vf)
                    else:
                        keys.append(0.0)
                elif item == "radius_proximity":
                    r = summary.get("radius_mm")
                    if isinstance(r, (int, float)) and radius_mm is not None:
                        keys.append(abs(float(r) - float(radius_mm)))
                    else:
                        keys.append(999.0)
                elif item == "distance_to_interface_plane":
                    vf = _coord(interface_plane_axis)
                    if interface_plane_preference == "max":
                        keys.append(-vf)
                    elif interface_plane_preference == "min":
                        keys.append(vf)
                    else:
                        keys.append(abs(vf))
                elif item == "point_proximity":
                    point_delta = _point_proximity(summary)
                    keys.append(float(point_delta) if isinstance(point_delta, (int, float)) else 999999.0)
                elif item == "distance_to_origin":
                    vf = abs(_coord(distance_to_origin_axis))
                    if distance_to_origin_preference == "max":
                        keys.append(-vf)
                    else:
                        keys.append(vf)
                elif item == "area_score":
                    a = summary.get("area_mm2")
                    af = float(a) if isinstance(a, (int, float)) else 0.0
                    keys.append(-af)
                else:
                    keys.append(0.0)
            keys.append(str(row.get("token") or ""))
            keys.append(str(row.get("face_id") or ""))
            return tuple(keys)

        # Attach computed keys for debug (does not affect sorting).
        for row in candidates:
            try:
                row["_sort_key"] = [float(x) if isinstance(x, (int, float)) else str(x) for x in sort_key(row)]
            except Exception:
                row["_sort_key"] = None

        candidates_sorted = sorted(candidates, key=sort_key)
        chosen = candidates_sorted[0]
        face_id = str(chosen.get("face_id"))
        summary = chosen.get("summary") if isinstance(chosen.get("summary"), dict) else None

        debug = {
            "body_id": body_id,
            "recipe": dict(recipe) if isinstance(recipe, dict) else recipe,
            "geometry_type": geometry_type,
            "fallback_policy": fallback_policy,
            "effective_fallback_policy": effective_fallback_policy,
            "fallback_applied": fallback_applied,
            "fallback": fallback_info,
            "deterministic_order": list(order),
            "deterministic_tie_break": ["entity_token", "face_id"],
            "scanned_faces": scanned_faces,
            "rejected_by": rejected_by,
            "candidates_count": len(candidates_sorted),
            "chosen": {
                "face_id": face_id,
                "summary": summary,
                "sort_key": chosen.get("_sort_key"),
            },
            "runner_up": (
                {
                    "face_id": str(candidates_sorted[1].get("face_id") or ""),
                    "summary": candidates_sorted[1].get("summary"),
                    "sort_key": candidates_sorted[1].get("_sort_key"),
                }
                if len(candidates_sorted) > 1
                else None
            ),
            "candidates_top": [
                {
                    "face_id": str(r.get("face_id") or ""),
                    "summary": r.get("summary"),
                    "sort_key": r.get("_sort_key"),
                }
                for r in candidates_sorted[:10]
            ],
        }
        return ("face", face_id, summary, debug)

    # ===== 鍗曚綅杞崲宸ュ叿鍑芥暟 =====
    
    def mm(self, value_mm: float) -> adsk.core.ValueInput:
        """姣背 鈫?Fusion ValueInput锛堝帢绫筹級
        
        鍙傛暟锛?
            value_mm: float - 姣背鍊?
        
        杩斿洖锛?
            adsk.core.ValueInput - 鍘樼背鍗曚綅鐨?ValueInput锛屽彲鐩存帴浼犵粰 Fusion API
        
        鐢ㄩ€旓細EXTRUDE銆丷EVOLVE銆丱FFSET 绛夋墍鏈夊昂瀵稿弬鏁?
        
        渚嬶細
            dist = self.mm(6.0)  # 6mm 鈫?0.6cm
            ext_input.setOneSideExtent(
                distance_extent,
                adsk.fusion.ExtentDirections.PositiveExtentDirection,
            )
        """
        # validate inputs & ids
        return adsk.core.ValueInput.createByReal(float(value_mm) / 10.0)
    
    def cm_vec(self, x_mm: float, y_mm: float, z_mm: float = 0.0) -> adsk.core.Vector3D:
        """姣背鍧愭爣 鈫?Fusion Vector3D锛堝帢绫筹級
        
        鍙傛暟锛?
            x_mm, y_mm, z_mm: float - 姣背鍧愭爣
        
        杩斿洖锛?
            adsk.core.Vector3D - 鍘樼背鍧愭爣鍚戦噺
        
        鐢ㄩ€旓細transform.translation銆乻ketch 鐐瑰潗鏍囩瓑
        
        渚嬶細
            pt = adsk.core.Point3D.create(*self.cm_vec(14.0, 60.0, 0.0))  # [1.4, 6.0, 0.0] cm
        """
        # validate inputs & ids
        return adsk.core.Vector3D.create(
            float(x_mm) / 10.0,
            float(y_mm) / 10.0,
            float(z_mm) / 10.0
        )
    
    def cm_point(self, x_mm: float, y_mm: float, z_mm: float = 0.0) -> adsk.core.Point3D:
        """姣背鍧愭爣 鈫?Fusion Point3D锛堝帢绫筹級
        
        鍙傛暟锛?
            x_mm, y_mm, z_mm: float - 姣背鍧愭爣
        
        杩斿洖锛?
            adsk.core.Point3D - 鍘樼背鍧愭爣鐐?
        
        渚嬶細
            center_pt = self.cm_point(0, 0, 0)
        """
        # validate inputs & ids
        v = self.cm_vec(x_mm, y_mm, z_mm)
        return adsk.core.Point3D.create(v.x, v.y, v.z)

    def _matrix_from_transform_mm(self, transform_mm: dict | None) -> adsk.core.Matrix3D:
        transform = adsk.core.Matrix3D.create()
        translation_raw = transform_mm.get("translation") if isinstance(transform_mm, dict) else None
        rotation_raw = transform_mm.get("rotation_rpy_deg") if isinstance(transform_mm, dict) else None
        translation = translation_raw if isinstance(translation_raw, dict) else {}
        rotation = rotation_raw if isinstance(rotation_raw, dict) else {}

        roll = math.radians(float(rotation.get("roll", 0.0)))
        pitch = math.radians(float(rotation.get("pitch", 0.0)))
        yaw = math.radians(float(rotation.get("yaw", 0.0)))

        origin = adsk.core.Point3D.create(0.0, 0.0, 0.0)
        rot_x = adsk.core.Matrix3D.create()
        rot_x.setToRotation(roll, adsk.core.Vector3D.create(1.0, 0.0, 0.0), origin)
        rot_y = adsk.core.Matrix3D.create()
        rot_y.setToRotation(pitch, adsk.core.Vector3D.create(0.0, 1.0, 0.0), origin)
        rot_z = adsk.core.Matrix3D.create()
        rot_z.setToRotation(yaw, adsk.core.Vector3D.create(0.0, 0.0, 1.0), origin)

        transform.transformBy(rot_x)
        transform.transformBy(rot_y)
        transform.transformBy(rot_z)
        transform.translation = self.cm_vec(
            translation.get("x", 0.0),
            translation.get("y", 0.0),
            translation.get("z", 0.0),
        )
        return transform

    @staticmethod
    def _resolve_hole_fallback_direction_label(
        extent: str | None,
        direction_hint: str | None = None,
        body_side_dot: float | None = None,
    ) -> str:
        extent_s = str(extent or "").strip().lower()
        hint_s = str(direction_hint or "").strip().lower()

        if extent_s == "through_negative":
            return "negative"
        if extent_s in {"through_positive", "through", "through_all"}:
            return "positive"

        if hint_s:
            if any(tok in hint_s for tok in ("negative", "reverse", "opposite", "minus")):
                return "negative"
            if any(tok in hint_s for tok in ("positive", "normal", "forward", "plus")):
                return "positive"

        if body_side_dot is not None:
            return "negative" if float(body_side_dot) < 0.0 else "positive"

        return "positive"

    def _next_feature_id(self, component_id: str, prefix: str) -> str:
        component_id = self._resolve_component_id(component_id)
        counter = self._feature_counter.get(component_id, 0) + 1
        self._feature_counter[component_id] = counter
        return f"{component_id}:{prefix}:{counter}"

    def _next_curve_id(self, sketch_id: str, kind: str) -> str:
        n = self._curve_counter.get(sketch_id, 0) + 1
        self._curve_counter[sketch_id] = n
        return f"{sketch_id}:{kind}:{n}"

    def _next_profile_id(self, sketch_id: str) -> str:
        n = self._profile_counter.get(sketch_id, 0) + 1
        self._profile_counter[sketch_id] = n
        return f"{sketch_id}:profile:{n}"

    def _next_body_id(self, component_id: str) -> str:
        component_id = self._resolve_component_id(component_id)
        n = self._body_counter.get(component_id, 0) + 1
        self._body_counter[component_id] = n
        return f"{component_id}:body:{n}"

    def _next_face_id(self, component_id: str) -> str:
        component_id = self._resolve_component_id(component_id)
        n = self._face_counter.get(component_id, 0) + 1
        self._face_counter[component_id] = n
        return f"{component_id}:face:{n}"

    def _next_edge_id(self, component_id: str) -> str:
        component_id = self._resolve_component_id(component_id)
        n = self._edge_counter.get(component_id, 0) + 1
        self._edge_counter[component_id] = n
        return f"{component_id}:edge:{n}"

    def _register_bodies(
        self,
        component_id: str,
        bodies,
    ) -> list[str]:
        """Register bodies into cache and return their ids."""
        body_ids = []
        if bodies is None:
            return body_ids

        if hasattr(bodies, "count") and hasattr(bodies, "item"):
            for i in range(bodies.count):
                body = bodies.item(i)
                if not body or not body.isValid:
                    continue
                body_id = self._next_body_id(component_id)
                self._cache_body(body_id, body)
                body_ids.append(body_id)
            return body_ids

        if hasattr(bodies, "isValid"):
            if bodies.isValid:
                body_id = self._next_body_id(component_id)
                self._cache_body(body_id, bodies)
                body_ids.append(body_id)
            return body_ids

        return body_ids

    def _register_token(self, entity_id: str, obj) -> None:
        if not obj or not getattr(obj, "isValid", False):
            return

        token = self._safe_entity_token(obj)
        if not token:
            token = self._safe_entity_token(self._safe_native_object(obj))
        if token:
            self._tokens[entity_id] = token

    def _resolve_by_token(self, entity_id: str, expected_type, kind: str):
        token = self._tokens.get(entity_id)
        if not token:
            return None
        return self._resolve_entity_by_token_value(token, expected_type, kind=kind, fail_on_error=bool(getattr(self, "strict_mode", False)), entity_id=entity_id)

    def _collect_token_resolution_candidates(
        self,
        token: str | None,
        expected_type,
        *,
        kind: str = "entity",
        fail_on_error: bool = False,
        entity_id: str | None = None,
    ) -> list:
        if not isinstance(token, str) or not token:
            return []
        try:
            entities = self.design.findEntityByToken(token)
        except Exception as e:
            if fail_on_error:
                label = entity_id if isinstance(entity_id, str) and entity_id else token
                self._fail(f"Failed to resolve {kind} {label}: {e}")
            return []

        raw_candidates = []
        if entities:
            if hasattr(entities, "count") and hasattr(entities, "item"):
                for i in range(entities.count):
                    candidate = entities.item(i)
                    if candidate:
                        raw_candidates.append(candidate)
            elif isinstance(entities, (list, tuple)):
                for candidate in entities:
                    if candidate:
                        raw_candidates.append(candidate)
            else:
                raw_candidates.append(entities)

        resolved_candidates = []
        seen = set()
        for candidate in raw_candidates:
            casted = None
            if hasattr(expected_type, "cast"):
                try:
                    casted = expected_type.cast(candidate)
                except Exception:
                    casted = None
            elif isinstance(candidate, expected_type):
                casted = candidate

            if not (casted and getattr(casted, "isValid", False)):
                continue

            # Token resolution can legitimately return multiple different live/stale
            # proxies that share the same entityToken. Deduping by token would throw
            # away the usable one, so only collapse exact object identity here.
            marker = id(casted)
            if marker in seen:
                continue
            seen.add(marker)
            resolved_candidates.append(casted)

        return resolved_candidates

    def _resolve_entity_by_token_value(
        self,
        token: str | None,
        expected_type,
        *,
        kind: str = "entity",
        fail_on_error: bool = False,
        entity_id: str | None = None,
    ):
        resolved_candidates = self._collect_token_resolution_candidates(
            token,
            expected_type,
            kind=kind,
            fail_on_error=fail_on_error,
            entity_id=entity_id,
        )

        if not resolved_candidates:
            return None

        if kind == "body":
            best = None
            best_score = None
            for candidate in resolved_candidates:
                native = self._safe_native_object(candidate)
                variants = [candidate]
                if native is not None and getattr(native, "isValid", False):
                    variants.append(native)

                for variant in variants:
                    score = (
                        1 if self._body_has_faces(variant) else 0,
                        1 if getattr(variant, "assemblyContext", None) is not None else 0,
                        1 if variant is not native else 0,
                    )
                    if best is None or score > best_score:
                        best = variant
                        best_score = score

            if best is not None:
                return best

        return resolved_candidates[0]

    def _debug_token_resolution_summaries(self, token: str | None, expected_type, *, kind: str = "entity", limit: int = 4) -> list[dict]:
        summaries = []
        for candidate in self._collect_token_resolution_candidates(token, expected_type, kind=kind)[: max(int(limit), 0)]:
            if kind == "body":
                summary = self._body_debug_summary(candidate)
                summary["assembly_context"] = bool(getattr(candidate, "assemblyContext", None) is not None)
            else:
                summary = {
                    "token": self._safe_entity_token(candidate),
                    "is_valid": bool(getattr(candidate, "isValid", False)),
                }
            summaries.append(summary)
        return summaries

    def _refresh_design_geometry(self) -> bool:
        refreshed = False

        design = getattr(self, "design", None)
        if design is not None:
            compute_all = getattr(design, "computeAll", None)
            if callable(compute_all):
                try:
                    compute_all()
                    refreshed = True
                except Exception:
                    pass

            try:
                root_comp = getattr(design, "rootComponent", None)
            except Exception:
                root_comp = None
            if root_comp is not None and getattr(root_comp, "isValid", True):
                self.root_comp = root_comp

        app = getattr(self, "app", None)
        if app is not None:
            try:
                viewport = getattr(app, "activeViewport", None)
            except Exception:
                viewport = None
            refresh = getattr(viewport, "refresh", None) if viewport is not None else None
            if callable(refresh):
                try:
                    refresh()
                    refreshed = True
                except Exception:
                    pass

        return refreshed

    def _cache_body(self, body_id: str, body) -> None:
        self._bodies[body_id] = body
        self._register_token(body_id, body)

    def _cache_face(self, face_id: str, face) -> None:
        self._faces[face_id] = face
        self._register_token(face_id, face)

    def _cache_edge(self, edge_id: str, edge) -> None:
        self._edges[edge_id] = edge
        self._register_token(edge_id, edge)

    def _cache_vertex(self, vertex_id: str, vertex) -> None:
        self._vertices[vertex_id] = vertex
        self._register_token(vertex_id, vertex)

    def _cache_plane(self, plane_id: str, plane) -> None:
        self._planes[plane_id] = plane
        self._register_token(plane_id, plane)

    def _cache_point(self, point_id: str, point) -> None:
        self._points[point_id] = point
        self._register_token(point_id, point)

    def _cache_axis(self, axis_id: str, axis) -> None:
        self._axes[axis_id] = axis
        self._register_token(axis_id, axis)

    def _cache_occurrence(self, occurrence_id: str, occ) -> None:
        occ_native = self._safe_native_object(occ)
        if occ_native is not None and getattr(occ_native, "isValid", False):
            occ = occ_native
        self._occurrences[occurrence_id] = occ
        display_names = getattr(self, "_occurrence_display_names", None)
        if not isinstance(display_names, dict):
            display_names = {}
            self._occurrence_display_names = display_names
        component_names = getattr(self, "_occurrence_component_names", None)
        if not isinstance(component_names, dict):
            component_names = {}
            self._occurrence_component_names = component_names
        try:
            occ_name = str(getattr(occ, "name", "") or "")
        except Exception:
            occ_name = ""
        if occ_name:
            display_names[occurrence_id] = occ_name
        try:
            comp = getattr(occ, "component", None)
        except Exception:
            comp = None
        try:
            comp_name = str(getattr(comp, "name", "") or "")
        except Exception:
            comp_name = ""
        if comp_name:
            component_names[occurrence_id] = comp_name
        self._register_token(occurrence_id, occ)

    def _safe_entity_token(self, obj) -> str | None:
        if obj is None or not getattr(obj, "isValid", False):
            return None
        try:
            token = getattr(obj, "entityToken", None)
        except Exception:
            return None
        return token if isinstance(token, str) and token else None

    def _safe_native_object(self, obj):
        if obj is None or not getattr(obj, "isValid", False):
            return None
        try:
            native = getattr(obj, "nativeObject", None)
        except Exception:
            return None
        if native is None or not getattr(native, "isValid", False):
            return None
        return native

    def _stabilize_occurrence_reference(self, occurrence_id: str, occ):
        if occ is None or not getattr(occ, "isValid", False):
            return occ
        try:
            self._cache_occurrence(occurrence_id, occ)
        except Exception:
            pass
        try:
            needs_recovery = self._occurrence_needs_recovery(occurrence_id, occ)
        except Exception:
            needs_recovery = False
        if not needs_recovery:
            return occ
        try:
            recovered = self._recover_occurrence_from_live_tree(occurrence_id)
        except Exception:
            recovered = None
        if recovered is not None and getattr(recovered, "isValid", False):
            try:
                self._cache_occurrence(occurrence_id, recovered)
            except Exception:
                pass
            return recovered
        return occ

    def _append_import_debug_log(self, payload: dict) -> None:
        run_dir = getattr(self, "run_dir", None)
        if not run_dir:
            return
        try:
            out_path = Path(run_dir) / "execution" / "import_cad_debug.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _append_body_recovery_debug_log(self, payload: dict) -> None:
        run_dir = getattr(self, "run_dir", None)
        if not run_dir:
            return
        try:
            out_path = Path(run_dir) / "execution" / "body_recovery_debug.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _body_debug_summary(self, body) -> dict:
        native = self._safe_native_object(body)
        return {
            "token": self._safe_entity_token(body),
            "has_faces": bool(body is not None and self._body_has_faces(body)),
            "is_solid": bool(getattr(body, "isSolid", False)) if body is not None else False,
            "has_native": bool(native is not None and getattr(native, "isValid", False)),
            "native_token": self._safe_entity_token(native),
            "native_has_faces": bool(native is not None and self._body_has_faces(native)),
        }

    def _iter_live_occurrences(self):
        root = getattr(self, "root_comp", None)
        if root is None:
            try:
                root = getattr(getattr(self, "design", None), "rootComponent", None)
            except Exception:
                root = None
        if root is None:
            return

        seen = set()

        def _yield_occ(occ):
            if occ is None or not getattr(occ, "isValid", False):
                return
            token = self._safe_entity_token(occ) or id(occ)
            if token in seen:
                return
            seen.add(token)
            yield occ
            try:
                child_occs = occ.childOccurrences
                child_count = int(getattr(child_occs, "count", 0) or 0)
            except Exception:
                child_occs = None
                child_count = 0
            for idx in range(child_count):
                try:
                    child = child_occs.item(idx)
                except Exception:
                    continue
                yield from _yield_occ(child)

        try:
            all_occs = getattr(root, "allOccurrences", None)
            all_count = int(getattr(all_occs, "count", 0) or 0)
        except Exception:
            all_occs = None
            all_count = 0
        if all_count > 0:
            for idx in range(all_count):
                try:
                    occ = all_occs.item(idx)
                except Exception:
                    continue
                yield from _yield_occ(occ)
            return

        try:
            occs = getattr(root, "occurrences", None)
            occ_count = int(getattr(occs, "count", 0) or 0)
        except Exception:
            occs = None
            occ_count = 0
        for idx in range(occ_count):
            try:
                occ = occs.item(idx)
            except Exception:
                continue
            yield from _yield_occ(occ)

    def _mm_translation_distance(self, lhs: dict | None, rhs: dict | None) -> float | None:
        if not isinstance(lhs, dict) or not isinstance(rhs, dict):
            return None
        try:
            dx = float(lhs.get("x", 0.0)) - float(rhs.get("x", 0.0))
            dy = float(lhs.get("y", 0.0)) - float(rhs.get("y", 0.0))
            dz = float(lhs.get("z", 0.0)) - float(rhs.get("z", 0.0))
        except Exception:
            return None
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def _occurrence_needs_recovery(self, occurrence_id: str, occ) -> bool:
        expected_map = getattr(self, "_occurrence_last_translation_mm", None)
        if not isinstance(expected_map, dict):
            return False
        expected = expected_map.get(occurrence_id)
        if not isinstance(expected, dict):
            return False
        actual = self._occurrence_translation_mm(occ)
        delta = self._mm_translation_distance(actual, expected)
        if delta is None:
            return True
        return float(delta) > 0.05

    def _recover_occurrence_from_live_tree(self, occurrence_id: str):
        if not isinstance(occurrence_id, str) or not occurrence_id:
            return None

        display_names = getattr(self, "_occurrence_display_names", None)
        component_names = getattr(self, "_occurrence_component_names", None)
        expected_map = getattr(self, "_occurrence_last_translation_mm", None)
        target_display = display_names.get(occurrence_id) if isinstance(display_names, dict) else None
        target_component = component_names.get(occurrence_id) if isinstance(component_names, dict) else None
        expected = expected_map.get(occurrence_id) if isinstance(expected_map, dict) else None

        logical_base = None
        if occurrence_id.startswith("occ:") and occurrence_id.count(":") >= 2:
            logical_base = occurrence_id[len("occ:") :].rsplit(":", 1)[0]

        exact_name_matches = []
        exact_component_matches = []
        logical_matches = []

        for occ in self._iter_live_occurrences() or []:
            try:
                occ_name = str(getattr(occ, "name", "") or "")
            except Exception:
                occ_name = ""
            try:
                comp = getattr(occ, "component", None)
            except Exception:
                comp = None
            try:
                comp_name = str(getattr(comp, "name", "") or "")
            except Exception:
                comp_name = ""

            if target_display and occ_name == target_display:
                exact_name_matches.append(occ)
                continue
            if target_component and comp_name == target_component:
                exact_component_matches.append(occ)
                continue
            if logical_base and (occ_name == logical_base or comp_name == logical_base):
                logical_matches.append(occ)

        def _pick(candidates, require_unique=False):
            if not candidates:
                return None
            if isinstance(expected, dict):
                ranked = []
                for candidate in candidates:
                    delta = self._mm_translation_distance(self._occurrence_translation_mm(candidate), expected)
                    ranked.append((float(delta) if delta is not None else 1e18, candidate))
                ranked.sort(key=lambda item: item[0])
                if ranked and (not require_unique or len(ranked) == 1 or ranked[0][0] + 1e-6 < ranked[1][0]):
                    return ranked[0][1]
            if len(candidates) == 1:
                return candidates[0]
            return None

        recovered = _pick(exact_name_matches)
        if recovered is None:
            recovered = _pick(exact_component_matches, require_unique=True)
        if recovered is None:
            recovered = _pick(logical_matches, require_unique=True)
        if recovered is None:
            return None

        self._cache_occurrence(occurrence_id, recovered)
        return recovered

    def _cache_feature(self, feature_id: str, feature) -> None:
        self._features[feature_id] = feature
        self._register_token(feature_id, feature)

    def _cache_sketch(self, sketch_id: str, sketch) -> None:
        self._sketches[sketch_id] = sketch
        self._register_token(sketch_id, sketch)

    def _cache_profile(self, profile_id: str, profile) -> None:
        self._profiles[profile_id] = profile
        self._register_token(profile_id, profile)

    def _ret_sketch(
        self,
        curve_id: str | None = None,
        curve_ids: list[str] | None = None,
        profile_id: str | None = None,
        profile_ids: list[str] | None = None,
        extra: dict | None = None,
    ) -> dict:
        if curve_ids is None:
            curve_ids = []
        else:
            curve_ids = list(curve_ids)
        if curve_id and not curve_ids:
            curve_ids = [curve_id]

        if profile_ids is None:
            profile_ids = []
        else:
            profile_ids = list(profile_ids)
        if profile_id and not profile_ids:
            profile_ids = [profile_id]

        result = {
            "curve_id": curve_id,
            "curve_ids": curve_ids,
            "profile_id": profile_id,
            "profile_ids": profile_ids,
        }
        if extra:
            result.update(extra)
        return result

    def _ret_feature(
        self,
        feature_id: str | None = None,
        feature_ids: list[str] | None = None,
        body_ids: list[str] | None = None,
        extra: dict | None = None,
    ) -> dict:
        if feature_ids is None:
            feature_ids = []
        else:
            feature_ids = list(feature_ids)

        if body_ids is None:
            body_ids = []
        else:
            body_ids = list(body_ids)

        result = {
            "feature_id": feature_id,
            "feature_ids": feature_ids,
            "body_ids": body_ids,
        }
        if extra:
            result.update(extra)
        return result

    def _warn(self, msg: str):
        try:
            print(f"[WARN] {msg}")
        except Exception:
            pass

    def _fail(self, msg: str):
        raise RuntimeError(msg)

    def _new_component_id(self, base_name: str) -> str:
        self._component_counter += 1
        return f"comp:{base_name}:{self._component_counter}"

    def _new_occurrence_id(self, base_name: str) -> str:
        self._occ_counter += 1
        return f"occ:{base_name}:{self._occ_counter}"

    def _resolve_component_id(self, component_id: str) -> str:
        strict_mode = bool(getattr(self, "strict_mode", False))
        component_name_to_id = getattr(self, "_component_name_to_id", None)
        components = getattr(self, "_components", None)
        if not strict_mode and isinstance(component_name_to_id, dict) and isinstance(components, dict):
            mapped = component_name_to_id.get(component_id)
            if mapped in components:
                return mapped
        if isinstance(components, dict) and component_id in components:
            return component_id
        return component_id

    def _resolve_occurrence_id(self, occurrence_id: str) -> str:
        strict_mode = bool(getattr(self, "strict_mode", False))
        occ_name_to_id = getattr(self, "_occ_name_to_id", None)
        occurrences = getattr(self, "_occurrences", None)
        if not strict_mode and isinstance(occ_name_to_id, dict) and isinstance(occurrences, dict):
            mapped = occ_name_to_id.get(occurrence_id)
            if mapped in occurrences:
                return mapped
        if isinstance(occurrences, dict) and occurrence_id in occurrences:
            return occurrence_id
        return occurrence_id

    def _require_component(self, component_id: str):
        if component_id is None:
            if self.strict_mode:
                self._fail("component_id is None")
            self._warn("component_id is None -> using root_comp")
            return self.root_comp
        resolved_id = self._resolve_component_id(component_id)
        comp = self._components.get(resolved_id)
        if comp is None or not getattr(comp, "isValid", False):
            comp = self._recover_component_from_occurrence(resolved_id)
        if comp is None or not getattr(comp, "isValid", False):
            if self.strict_mode:
                self._fail(f"Unknown/invalid component_id: {component_id}")
            self._warn(f"Unknown/invalid component_id {component_id} -> using root_comp")
            return self.root_comp
        return comp

    def _require_component_for_body_queries(self, component_id: str, *, require_faces: bool = False):
        if component_id is None:
            return self._require_component(component_id)
        resolved_id = self._resolve_component_id(component_id)
        comp = self._recover_component_from_occurrence(
            resolved_id,
            require_bodies=True,
            require_faces=require_faces,
        )
        if comp is not None and getattr(comp, "isValid", False):
            return comp
        return self._require_component(component_id)

    def _try_refresh_body_from_single_body_component(self, body_id: str, *, require_faces: bool = False):
        try:
            component_id = self._component_id_from_body_id(body_id)
        except Exception:
            return None
        if not isinstance(component_id, str) or not component_id:
            return None

        try:
            comp = self._require_component_for_body_queries(component_id, require_faces=require_faces)
        except Exception:
            return None

        solid_bodies = self._valid_solid_bodies(comp)
        if len(solid_bodies) != 1:
            return None

        body = solid_bodies[0]
        if body is None or not getattr(body, "isValid", False):
            return None
        if require_faces and not self._body_has_faces(body):
            return None

        self._cache_body(body_id, body)
        return body

    def _require_occurrence(self, occurrence_id: str):
        resolved_id = self._resolve_occurrence_id(occurrence_id)

        occ = self._occurrences.get(resolved_id)
        if occ is not None and getattr(occ, "isValid", False):
            occ_native = self._safe_native_object(occ)
            if occ_native is not None and getattr(occ_native, "isValid", False) and occ_native is not occ:
                occ = occ_native
                self._cache_occurrence(resolved_id, occ)
            try:
                needs_recovery = self._occurrence_needs_recovery(resolved_id, occ)
            except Exception:
                needs_recovery = False
            if not needs_recovery:
                return occ
            recovered = self._recover_occurrence_from_live_tree(resolved_id)
            if recovered is not None and getattr(recovered, "isValid", False):
                self._cache_occurrence(resolved_id, recovered)
                return recovered
            return occ

        occ = self._listed_occurrences.get(occurrence_id)
        if occ is not None and getattr(occ, "isValid", False):
            occ_native = self._safe_native_object(occ)
            if occ_native is not None and getattr(occ_native, "isValid", False):
                occ = occ_native
            self._cache_occurrence(resolved_id, occ)
            try:
                needs_recovery = self._occurrence_needs_recovery(resolved_id, occ)
            except Exception:
                needs_recovery = False
            if not needs_recovery:
                return occ
            recovered = self._recover_occurrence_from_live_tree(resolved_id)
            if recovered is not None and getattr(recovered, "isValid", False):
                self._cache_occurrence(resolved_id, recovered)
                return recovered
            return occ

        occ = self._recover_occurrence_from_live_tree(resolved_id)
        if occ is not None and getattr(occ, "isValid", False):
            return occ

        occ = self._resolve_by_token(resolved_id, adsk.fusion.Occurrence, "occurrence")
        if occ:
            occ_native = self._safe_native_object(occ)
            if occ_native is not None and getattr(occ_native, "isValid", False):
                occ = occ_native
            self._cache_occurrence(resolved_id, occ)
            try:
                needs_recovery = self._occurrence_needs_recovery(resolved_id, occ)
            except Exception:
                needs_recovery = False
            if not needs_recovery:
                return occ
            recovered = self._recover_occurrence_from_live_tree(resolved_id)
            if recovered is not None and getattr(recovered, "isValid", False):
                self._cache_occurrence(resolved_id, recovered)
                return recovered
            return occ

        self._fail(f"Unknown/invalid occurrence_id: {occurrence_id}")

    def _require_body(self, body_id: str):
        body = self._bodies.get(body_id)
        if body is not None and getattr(body, "isValid", False):
            if self._body_has_faces(body):
                return body
            recovered = self._recover_body_from_component(body_id, require_faces=True)
            if recovered is not None:
                return recovered
            refreshed = self._try_refresh_body_from_single_body_component(body_id, require_faces=True)
            if refreshed is not None:
                return refreshed

        body = self._resolve_by_token(body_id, adsk.fusion.BRepBody, "body")
        if body:
            if self._body_has_faces(body):
                self._cache_body(body_id, body)
                return body
            recovered = self._recover_body_from_component(body_id, require_faces=True)
            if recovered is not None:
                return recovered
            refreshed = self._try_refresh_body_from_single_body_component(body_id, require_faces=True)
            if refreshed is not None:
                return refreshed

        body = self._recover_body_from_component(body_id, require_faces=True)
        if body is not None:
            return body
        refreshed = self._try_refresh_body_from_single_body_component(body_id, require_faces=True)
        if refreshed is not None:
            return refreshed

        design_refresh_attempted = self._refresh_design_geometry()
        if design_refresh_attempted:
            body = self._resolve_by_token(body_id, adsk.fusion.BRepBody, "body")
            if body:
                if self._body_has_faces(body):
                    self._cache_body(body_id, body)
                    return body
                recovered = self._recover_body_from_component(body_id, require_faces=True)
                if recovered is not None:
                    return recovered
                refreshed = self._try_refresh_body_from_single_body_component(body_id, require_faces=True)
                if refreshed is not None:
                    return refreshed

            body = self._recover_body_from_component(body_id, require_faces=True)
            if body is not None:
                return body
            refreshed = self._try_refresh_body_from_single_body_component(body_id, require_faces=True)
            if refreshed is not None:
                return refreshed

        component_id = None
        try:
            component_id = self._component_id_from_body_id(body_id)
        except Exception:
            component_id = None
        cached_component = None
        if isinstance(component_id, str) and component_id:
            cached_component = self._components.get(component_id)
        occurrence_id = None
        cached_occurrence = None
        if isinstance(component_id, str) and component_id.startswith("comp:") and component_id.count(":") >= 2:
            occurrence_id = f"occ:{component_id[len('comp:'):]}"
            cached_occurrence = self._occurrences.get(occurrence_id)
        occurrence_candidates = list(self._iter_occurrence_candidate_bodies(cached_occurrence)) if cached_occurrence is not None else []
        component_candidates = list(self._iter_component_candidate_bodies(cached_component)) if cached_component is not None else []
        self._append_body_recovery_debug_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "status": "failed",
                "body_id": body_id,
                "component_id": component_id,
                "occurrence_id": occurrence_id,
                "saved_token_present": bool(self._tokens.get(body_id)),
                "saved_token": self._tokens.get(body_id),
                "saved_token_resolution_samples": self._debug_token_resolution_summaries(
                    self._tokens.get(body_id),
                    adsk.fusion.BRepBody,
                    kind="body",
                    limit=4,
                ),
                "design_refresh_attempted": design_refresh_attempted,
                "cached_body_valid": bool(body is not None and getattr(body, "isValid", False)),
                "cached_body_has_faces": bool(body is not None and self._body_has_faces(body)),
                "cached_component_valid": bool(cached_component is not None and getattr(cached_component, "isValid", False)),
                "cached_component_name": str(getattr(cached_component, "name", "") or "") if cached_component is not None else "",
                "cached_component_body_count": self._component_body_count(cached_component),
                "cached_component_native_body_count": self._component_body_count(self._safe_native_object(cached_component)),
                "cached_component_body_samples": [self._body_debug_summary(candidate) for candidate in component_candidates[:4]],
                "cached_occurrence_valid": bool(cached_occurrence is not None and getattr(cached_occurrence, "isValid", False)),
                "cached_occurrence_name": str(getattr(cached_occurrence, "name", "") or "") if cached_occurrence is not None else "",
                "cached_occurrence_body_count": len(occurrence_candidates),
                "cached_occurrence_body_samples": [self._body_debug_summary(candidate) for candidate in occurrence_candidates[:4]],
            }
        )
        self._fail(f"Unknown/invalid body_id: {body_id}")

    def _require_face(self, face_id: str):
        face = self._faces.get(face_id)
        if face is not None and getattr(face, "isValid", False):
            return face

        face = self._resolve_by_token(face_id, adsk.fusion.BRepFace, "face")
        if face:
            self._cache_face(face_id, face)
            return face

        # Last-resort: re-enumerate body faces and match by saved token.
        # This handles cases where BRep face proxies become stale between
        # RESOLVE_INTERFACE and the subsequent consumer (e.g. HOLE_SIMPLE)
        # even without topology modifications (Fusion API regeneration).
        face = self._re_enumerate_face_fallback(face_id)
        if face:
            return face

        self._fail(f"Unknown/invalid face_id: {face_id}")

    def _re_enumerate_face_fallback(self, face_id: str):
        """Try to recover a stale face by re-enumerating the parent body's faces."""
        saved_token = self._tokens.get(face_id)
        if not saved_token:
            return None
        # Derive component_id from face_id (format: {component_id}:face:{n})
        marker = ":face:"
        if marker not in face_id:
            return None
        component_id = face_id.split(marker)[0]
        try:
            comp = self._components.get(component_id)
            if comp is None or not getattr(comp, "isValid", False):
                return None
            bodies = comp.bRepBodies
            if not bodies or bodies.count == 0:
                return None
            for bi in range(bodies.count):
                body = bodies.item(bi)
                if not body or not body.isValid:
                    continue
                for fi in range(body.faces.count):
                    f = body.faces.item(fi)
                    if not f or not getattr(f, "isValid", False):
                        continue
                    try:
                        tk = getattr(f, "entityToken", None)
                    except Exception:
                        tk = None
                    if isinstance(tk, str) and tk == saved_token:
                        self._cache_face(face_id, f)
                        return f
        except Exception:
            pass
        return None

    def _recover_hole_anchor_face(self, comp, center_mm):
        """Re-enumerate a component's body faces and pick the planar face nearest to *center_mm*.

        Used as a last-resort recovery in HOLE_SIMPLE when the face_id resolved
        by a preceding RESOLVE_INTERFACE becomes stale before consumption.
        Returns a valid BRepFace or None.
        """
        try:
            bodies = comp.bRepBodies
            if not bodies or bodies.count == 0:
                return None
            # target in cm (Fusion internal units)
            if isinstance(center_mm, dict):
                tx = float(center_mm.get("x", 0)) / 10.0
                ty = float(center_mm.get("y", 0)) / 10.0
                tz = float(center_mm.get("z", 0)) / 10.0
            else:
                return None

            best_face = None
            best_score = float("inf")
            for bi in range(bodies.count):
                body = bodies.item(bi)
                if not body or not body.isValid:
                    continue
                for fi in range(body.faces.count):
                    f = body.faces.item(fi)
                    if not f or not getattr(f, "isValid", False):
                        continue
                    if not self._is_planar_face(f):
                        continue
                    try:
                        geom = f.geometry
                        normal = geom.normal
                        origin = geom.origin
                        # point-to-plane distance (cm)
                        plane_dist = abs(
                            normal.x * (tx - origin.x)
                            + normal.y * (ty - origin.y)
                            + normal.z * (tz - origin.z)
                        )
                        if plane_dist > 0.01:  # > 0.1 mm off the plane
                            continue
                        # prefer face whose bounding box centroid is closest
                        bb = f.boundingBox
                        cx = (bb.minPoint.x + bb.maxPoint.x) / 2.0
                        cy = (bb.minPoint.y + bb.maxPoint.y) / 2.0
                        cz = (bb.minPoint.z + bb.maxPoint.z) / 2.0
                        dist = math.sqrt(
                            (tx - cx) ** 2 + (ty - cy) ** 2 + (tz - cz) ** 2
                        )
                        if dist < best_score:
                            best_score = dist
                            best_face = f
                    except Exception:
                        continue
            return best_face
        except Exception:
            return None

    def _require_edge(self, edge_id: str):
        edge = self._edges.get(edge_id)
        if edge is not None and getattr(edge, "isValid", False):
            return edge

        edge = self._resolve_by_token(edge_id, adsk.fusion.BRepEdge, "edge")
        if edge:
            self._cache_edge(edge_id, edge)
            return edge

        self._fail(f"Unknown/invalid edge_id: {edge_id}")

    def _require_vertex(self, vertex_id: str):
        vertex = self._vertices.get(vertex_id)
        if vertex is not None and getattr(vertex, "isValid", False):
            return vertex

        vertex = self._resolve_by_token(vertex_id, adsk.fusion.BRepVertex, "vertex")
        if vertex:
            self._cache_vertex(vertex_id, vertex)
            return vertex

        self._fail(f"Unknown/invalid vertex_id: {vertex_id}")

    def _require_sketch(self, sketch_id: str):
        sketch = self._sketches.get(sketch_id)
        if sketch is not None and getattr(sketch, "isValid", False):
            return sketch

        sketch = self._resolve_by_token(sketch_id, adsk.fusion.Sketch, "sketch")
        if sketch:
            self._cache_sketch(sketch_id, sketch)
            return sketch

        self._fail(f"Unknown/invalid sketch_id: {sketch_id}")

    def _require_profile(self, profile_id: str):
        profile = self._profiles.get(profile_id)
        if profile is not None and getattr(profile, "isValid", False):
            return profile

        profile = self._resolve_by_token(profile_id, adsk.fusion.Profile, "profile")
        if profile:
            self._cache_profile(profile_id, profile)
            return profile

        parts = profile_id.split(":")
        if len(parts) >= 3 and parts[-2] == "profile":
            sketch_id = ":".join(parts[:-2])
            try:
                index = int(parts[-1]) - 1
            except Exception:
                index = None
            if index is not None:
                sketch = self._sketches.get(sketch_id)
                if sketch and getattr(sketch, "isValid", False):
                    profiles = sketch.profiles
                    if 0 <= index < profiles.count:
                        recovered = profiles.item(index)
                        if recovered and getattr(recovered, "isValid", False):
                            self._cache_profile(profile_id, recovered)
                            return recovered

        self._fail(f"Unknown/invalid profile_id: {profile_id}")

    def _require_curve(self, curve_id: str):
        curve = self._curves.get(curve_id)
        if curve is None or not getattr(curve, "isValid", False):
            self._fail(f"Unknown/invalid curve_id: {curve_id}")
        return curve

    def _require_point(self, point_id: str):
        point = self._points.get(point_id)
        if point is None or not getattr(point, "isValid", False):
            self._fail(f"Unknown/invalid point_id: {point_id}")
        return point

    def _require_sketch_point(self, point_id: str):
        point = self._sketch_points.get(point_id)
        if point is None or not getattr(point, "isValid", False):
            self._fail(f"Unknown/invalid sketch_point_id: {point_id}")
        return point

    def _require_plane(self, plane_id: str):
        plane = self._planes.get(plane_id)
        if plane is not None and getattr(plane, "isValid", False):
            return plane

        plane = self._resolve_by_token(plane_id, adsk.fusion.ConstructionPlane, "plane")
        if plane:
            self._cache_plane(plane_id, plane)
            return plane

        self._fail(f"Unknown/invalid plane_id: {plane_id}")

    def _require_axis(self, axis_id: str):
        axis = self._axes.get(axis_id)
        if axis is None or not getattr(axis, "isValid", False):
            self._fail(f"Unknown/invalid axis_id: {axis_id}")
        return axis

    def _require_feature(self, feature_id: str):
        feature = self._features.get(feature_id)
        if feature is not None and getattr(feature, "isValid", False):
            return feature

        feature = self._resolve_by_token(feature_id, adsk.fusion.Feature, "feature")
        if feature:
            self._cache_feature(feature_id, feature)
            return feature

        self._fail(f"Unknown/invalid feature_id: {feature_id}")

    def _next_joint_id(self, kind: str) -> str:
        self._joint_counter += 1
        return f"joint:{kind}:{self._joint_counter}"

    def _next_constraint_id(self, sketch_id: str) -> str:
        n = self._constraint_counter.get(sketch_id, 0) + 1
        self._constraint_counter[sketch_id] = n
        return f"{sketch_id}:constraint:{n}"

    def _is_planar_face(self, face) -> bool:
        try:
            return face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType
        except Exception:
            return False

    def _is_cylindrical_face(self, face) -> bool:
        try:
            return face.geometry.surfaceType == adsk.core.SurfaceTypes.CylinderSurfaceType
        except Exception:
            return False

    def _face_area(self, face) -> float:
        if hasattr(face, "area"):
            return float(face.area)

        raise RuntimeError("Unable to compute face area for planar face")

    def _pick_joint_keypoint(self):
        candidates = [
            "CenterKeyPoint",
            "MiddleKeyPoint",
            "StartKeyPoint",
            "EndKeyPoint",
        ]
        for name in candidates:
            if hasattr(adsk.fusion.JointKeyPointTypes, name):
                return getattr(adsk.fusion.JointKeyPointTypes, name)

        for name in dir(adsk.fusion.JointKeyPointTypes):
            if not name.endswith("KeyPoint"):
                continue
            value = getattr(adsk.fusion.JointKeyPointTypes, name)
            return value

        raise RuntimeError("No available JointKeyPointTypes in current Fusion API")

    def _append_joint_execution_log(self, payload: dict) -> None:
        if not self.run_dir:
            return
        try:
            out_path = Path(self.run_dir) / "execution" / "joint_execution_debug.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _append_standard_part_execution_log(self, payload: dict) -> None:
        run_dir = getattr(self, "run_dir", None)
        if not run_dir:
            return
        try:
            out_path = Path(run_dir) / "execution" / "standard_part_execution_debug.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _occurrence_translation_mm(self, occ) -> dict | None:
        if occ is None:
            return None
        try:
            transform = getattr(occ, "transform2", None)
            if transform is None:
                return None
            translation = getattr(transform, "translation", None)
            if translation is None:
                return None
            return {
                "x": float(getattr(translation, "x", 0.0)) * 10.0,
                "y": float(getattr(translation, "y", 0.0)) * 10.0,
                "z": float(getattr(translation, "z", 0.0)) * 10.0,
            }
        except Exception:
            return None

    def _entity_in_occurrence_context(self, entity_obj, occurrence):
        if entity_obj is None or occurrence is None or not getattr(occurrence, "isValid", False):
            return entity_obj

        try:
            current_ctx = getattr(entity_obj, "assemblyContext", None)
            if current_ctx is occurrence:
                return entity_obj
        except Exception:
            pass

        try:
            native = getattr(entity_obj, "nativeObject", None)
        except Exception:
            native = None

        for candidate in (native, entity_obj):
            if candidate is None or not getattr(candidate, "isValid", False):
                continue
            try:
                if hasattr(candidate, "createForAssemblyContext"):
                    prox = candidate.createForAssemblyContext(occurrence)
                    if prox is not None and getattr(prox, "isValid", False):
                        return prox
            except Exception:
                continue
        return entity_obj

    def _build_joint_geometry_from_entity(
        self,
        entity: dict,
        *,
        occurrence=None,
        origin_mm: dict | None = None,
    ):
        if not isinstance(entity, dict):
            raise RuntimeError("CREATE_JOINT_GEOMETRY requires an entity dict")

        resolved_entity = dict(entity)
        entity_type = resolved_entity.get("type")
        if entity_type == "marker":
            marker_id = resolved_entity.get("marker_id")
            if not isinstance(marker_id, str) or not marker_id:
                raise RuntimeError("CREATE_JOINT_GEOMETRY marker entity requires marker_id")
            resolved_entity = self._resolve_marker_to_entity_ref(marker_id)
            entity_type = resolved_entity.get("type")

        geom = None
        origin_pt = None
        if origin_mm is not None:
            origin_pt = self.cm_point(
                origin_mm.get("x", 0),
                origin_mm.get("y", 0),
                origin_mm.get("z", 0),
            )

        if entity_type == "face":
            face_id = resolved_entity.get("face_id")
            face = self._require_face(face_id)
            if not face or not face.isValid:
                raise RuntimeError(f"Face not found or invalid: {face_id}")
            face = self._entity_in_occurrence_context(face, occurrence)

            surf = face.geometry
            surf_type = getattr(surf, "surfaceType", None)
            surf_object = getattr(surf, "objectType", "") or ""
            keypoint = self._pick_joint_keypoint()

            is_plane = False
            if surf_type == adsk.core.SurfaceTypes.PlaneSurfaceType:
                is_plane = True
            elif "Plane" in surf_object:
                is_plane = True

            if is_plane:
                geom = adsk.fusion.JointGeometry.createByPlanarFace(
                    face, None, adsk.fusion.JointKeyPointTypes.CenterKeyPoint
                )
            else:
                is_cyl_or_cone = False
                if surf_type in (
                    adsk.core.SurfaceTypes.CylinderSurfaceType,
                    adsk.core.SurfaceTypes.ConeSurfaceType,
                ):
                    is_cyl_or_cone = True
                elif "Cylinder" in surf_object or "Cone" in surf_object:
                    is_cyl_or_cone = True

                if is_cyl_or_cone:
                    if hasattr(adsk.fusion.JointKeyPointTypes, "MiddleKeyPoint"):
                        keypoint = adsk.fusion.JointKeyPointTypes.MiddleKeyPoint
                    elif hasattr(adsk.fusion.JointKeyPointTypes, "CenterKeyPoint"):
                        keypoint = adsk.fusion.JointKeyPointTypes.CenterKeyPoint

                    quadrant = None
                    if hasattr(adsk.fusion, "JointQuadrantAngleTypes"):
                        if hasattr(
                            adsk.fusion.JointQuadrantAngleTypes,
                            "StartJointQuadrantAngleType",
                        ):
                            quadrant = (
                                adsk.fusion.JointQuadrantAngleTypes
                                .StartJointQuadrantAngleType
                            )

                    if quadrant is None:
                        raise RuntimeError(
                            "JointQuadrantAngleTypes.StartJointQuadrantAngleType not available in current API"
                        )
                    geom = adsk.fusion.JointGeometry.createByCylinderOrConeFace(
                        face,
                        quadrant,
                        keypoint,
                    )
                    if geom is None:
                        raise RuntimeError(
                            "JointGeometry.createByCylinderOrConeFace returned None; "
                            f"surfaceType={surf_type}, objectType={surf_object}"
                        )
                else:
                    non_planar = getattr(adsk.fusion.JointGeometry, "createByNonPlanarFace", None)
                    if callable(non_planar):
                        geom = non_planar(face, keypoint)
                    else:
                        raise RuntimeError(
                            "Unsupported face type for joint geometry: "
                            f"surfaceType={surf_type}, objectType={surf_object}"
                        )

        elif entity_type == "edge":
            edge_id = resolved_entity.get("edge_id")
            edge = self._require_edge(edge_id)
            if not edge or not edge.isValid:
                raise RuntimeError(f"Edge not found or invalid: {edge_id}")
            edge = self._entity_in_occurrence_context(edge, occurrence)

            keypoint = self._pick_joint_keypoint()
            if origin_pt is not None:
                geom = adsk.fusion.JointGeometry.createByCurve(edge, keypoint)
            else:
                geom = adsk.fusion.JointGeometry.createByCurve(edge, keypoint)

        elif entity_type == "axis":
            raise RuntimeError(
                "JointGeometry cannot be created directly from a ConstructionAxis. "
                "Use a cylindrical face, edge, or point instead."
            )
        else:
            raise RuntimeError(f"Unsupported joint geometry type: {entity_type}")

        return geom, resolved_entity

    def _materialize_joint_geometry(self, joint_geometry_id: str, occurrence_id: str | None = None):
        sources = getattr(self, "_joint_geometry_sources", None)
        source_meta = sources.get(joint_geometry_id) if isinstance(sources, dict) else None
        if isinstance(source_meta, dict):
            entity = source_meta.get("entity")
            if isinstance(entity, dict):
                occurrence = self._get_occurrence(occurrence_id) if occurrence_id else None
                geom, _ = self._build_joint_geometry_from_entity(
                    entity,
                    occurrence=occurrence,
                    origin_mm=source_meta.get("origin_mm") if isinstance(source_meta.get("origin_mm"), dict) else None,
                )
                return geom

        geom = self._joint_geometries.get(joint_geometry_id)
        if geom is None:
            raise RuntimeError(f"Joint geometry not found: {joint_geometry_id}")
        return geom

    def _cm_tol(self, mm: float) -> float:
        return float(mm) / 10.0

    def _resolve_measurable_entity(self, sel: dict):
        if not isinstance(sel, dict):
            self._fail("Measurement selector must be a dict")

        if "face_id" in sel:
            return self._require_face(sel.get("face_id"))
        if "edge_id" in sel:
            return self._require_edge(sel.get("edge_id"))
        if "vertex_id" in sel:
            return self._require_vertex(sel.get("vertex_id"))
        if "body_id" in sel:
            return self._require_body(sel.get("body_id"))
        if "point" in sel:
            point = sel.get("point") or {}
            return self.cm_point(
                point.get("x_mm", 0),
                point.get("y_mm", 0),
                point.get("z_mm", 0),
            )

        self._fail("Measurement selector requires face_id, edge_id, vertex_id, body_id, or point")

    def _get_occurrence(self, occurrence_id: str):
        return self._require_occurrence(occurrence_id)

    def _get_design(self) -> adsk.fusion.Design:
        product = self.app.activeProduct
        design = adsk.fusion.Design.cast(product)
        if not design:
            self._fail("No active Fusion design")
        return design

    def _find_design_appearance(self, name_or_id: str):
        if not name_or_id:
            self._fail("Appearance name_or_id is required")

        design = self._get_design()
        appearances = design.appearances

        if hasattr(appearances, "itemByName"):
            found = appearances.itemByName(name_or_id)
            if found and getattr(found, "isValid", False):
                return found

        for i in range(appearances.count):
            app = appearances.item(i)
            if app and getattr(app, "isValid", False) and app.name == name_or_id:
                return app

        try:
            index = int(name_or_id)
        except Exception:
            index = None

        if index is not None and 0 <= index < appearances.count:
            app = appearances.item(index)
            if app and getattr(app, "isValid", False):
                return app

        return None

    def _copy_appearance_to_design(
        self,
        library_name: str,
        appearance_name: str,
        new_name: str | None = None,
    ):
        if not library_name:
            self._fail("library_name is required")
        if not appearance_name:
            self._fail("appearance_name is required")

        design = self._get_design()
        libraries = self.app.materialLibraries
        library = None
        if hasattr(libraries, "itemByName"):
            library = libraries.itemByName(library_name)
        if not library:
            self._fail(f"Material library not found: {library_name}")

        lib_appearance = None
        if hasattr(library.appearances, "itemByName"):
            lib_appearance = library.appearances.itemByName(appearance_name)
        if not lib_appearance or not getattr(lib_appearance, "isValid", False):
            self._fail(f"Appearance not found in library: {appearance_name}")

        target_name = new_name or appearance_name
        if hasattr(design.appearances, "itemByName"):
            existing = design.appearances.itemByName(target_name)
            if existing and getattr(existing, "isValid", False):
                if self.strict_mode:
                    self._fail(f"Appearance already exists in design: {target_name}")
                base = target_name
                suffix = 1
                while True:
                    candidate = f"{base}_{suffix}"
                    dup = design.appearances.itemByName(candidate)
                    if not dup or not getattr(dup, "isValid", False):
                        target_name = candidate
                        break
                    suffix += 1

        copied = design.appearances.addByCopy(lib_appearance, target_name)
        if not copied or not getattr(copied, "isValid", False):
            self._fail("Failed to copy appearance into design")
        return copied
    
    def CREATE_COMPONENT(self, name: str, parent_component_id=None, transform=None):
        """鍒涘缓鏂扮粍浠讹紙澶氬眰绾ц閰嶏級
        
        ===== 鍧愭爣绯荤害瀹氾紙CRITICAL锛?====
        - transform.translation 鏄?LOCAL_TRANSFORM锛堢浉瀵逛簬 parent_component 鐨勫眬閮ㄥ潗鏍囩郴锛?
        - 褰?parent_component_id 瀛樺湪鏃讹細
          * occurrence.transform.translation = parent_local_origin锛堢浉瀵圭埗缁勪欢鐨勬湰鍦板潗鏍囷級
          * 瀹為檯 world 浣嶇疆鐢?parent occurrence 鐨?world transform 鍐冲畾
        - 褰?parent_component_id 涓嶅瓨鍦ㄦ椂锛?
          * 鎸傝浇鍦?root_comp锛宼ransform.translation 鐩稿浜?root锛堝嵆 world 鍧愭爣锛?
        
        ===== 鍙傛暟璇存槑 =====
        name: str
            鏂扮粍浠剁殑鍚嶇О锛堟樉绀哄悕锛沜omponent_id 鐢辩郴缁熺敓鎴愶級
        parent_component_id: str, optional
            鐖剁粍浠剁殑 ID銆傝嫢鎸囧畾锛屾柊 occurrence 鎸傝浇鍦ㄨ鐖剁粍浠朵笅锛?
            鑻ヤ负 None锛屾寕杞藉湪 root_comp锛堥《绾ц閰嶏級
        transform: dict, optional
            鍖呭惈 translation 鐨勫彉鎹㈢煩闃?
            {
                "translation": {
                    "x": float,  # mm锛岀浉瀵?parent锛堟垨 world锛?
                    "y": float,  # mm锛岀浉瀵?parent锛堟垨 world锛?
                    "z": float   # mm锛岀浉瀵?parent锛堟垨 world锛?
                }
            }
        """
        # validate inputs & ids
        # 鍒涘缓 Matrix3D锛岃繖灏嗕綔涓?LOCAL_TRANSFORM 璁剧疆鍒?occurrence 涓?
        local_mat = self._matrix_from_transform_mm(transform if isinstance(transform, dict) else None)

        if self.strict_mode and name in self._component_name_to_id:
            raise RuntimeError(f"Component name already exists: {name}")

        try:
            # ===== 纭畾鐩爣缁勪欢 =====
            # 濡傛灉 parent_component_id 鏈夋晥锛岃幏鍙栫埗缁勪欢锛涘惁鍒欑敤 root_comp
            target_comp = self.root_comp
            if parent_component_id:
                target_comp = self._require_component(parent_component_id)

            # ===== 鍦ㄧ洰鏍囩粍浠朵笅鍒涘缓鏂?occurrence =====
            # local_mat 鍦ㄨ繖閲屼細琚缃负 occurrence.transform锛圠OCAL 鍧愭爣绯伙級
            # Fusion 浼氭牴鎹?parent occurrence 鑷姩璁＄畻 world transform
            occ = target_comp.occurrences.addNewComponent(local_mat)
            if not occ:
                raise RuntimeError("Failed to create occurrence")

            new_comp = occ.component
            if not new_comp:
                raise RuntimeError("Failed to create component")

            # ===== 鍛藉悕 / ID 璁板綍 =====
            new_comp.name = name
            try:
                occ.name = name
            except AttributeError:
                pass

            component_id = self._new_component_id(name)
            occurrence_id = self._new_occurrence_id(name)

            self._components[component_id] = new_comp
            occ = self._stabilize_occurrence_reference(occurrence_id, occ)
            self._component_name_to_id[name] = component_id
            self._occ_name_to_id[name] = occurrence_id

            if not self.strict_mode:
                self._components.setdefault(name, new_comp)
                self._occurrences.setdefault(name, occ)

            return {
                "component_id": component_id,
                "occurrence_id": occurrence_id,
                "parent_component_id": parent_component_id,
                "occurrence_transform_mode": "local",  # 琛ㄧず occurrence.transform 鏄浉瀵圭埗鐨勫眬閮ㄥ潗鏍?
            }
        except Exception as e:
            if self.strict_mode:
                raise

            # 濡傛灉鏄崟闆朵欢璁捐鏂囨。锛屾棤娉曞垱寤烘柊缁勪欢锛屽洖閫€涓烘牴缁勪欢
            self._components[name] = self.root_comp
            return {
                "component_id": name,
                "occurrence_id": None,
                "component_mode": "root",
                "warning": str(e)
            }
    
    def ACTIVATE_COMPONENT(self, component_id: str):
        """婵€娲绘寚瀹氱粍浠?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        if comp:
            try:
                self.design.activeComponent = comp
                return {}
            except Exception:
                # 鏌愪簺鐜涓?activeComponent 涓哄彧璇伙紝蹇界暐婵€娲诲け璐?
                return {"warning": "activate_component_failed_readonly"}
        return {}

    def CREATE_USER_PARAMETER(self, name: str, value_mm: float, unit: str = "mm", comment: str = ""):
        """鍒涘缓鐢ㄦ埛鍙傛暟锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        if unit != "mm":
            raise RuntimeError(f"Unsupported unit for CREATE_USER_PARAMETER: {unit}")

        user_params = self.design.userParameters
        if self.strict_mode and user_params.itemByName(name):
            raise RuntimeError(f"User parameter already exists: {name}")

        value_input = adsk.core.ValueInput.createByString(f"{float(value_mm)} mm")
        user_params.add(name, value_input, "mm", comment)
        return {"parameter_name": name}

    def SET_USER_PARAMETER(self, name: str, value_mm: float):
        """璁剧疆鐢ㄦ埛鍙傛暟锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        user_params = self.design.userParameters
        param = user_params.itemByName(name)
        if not param:
            raise RuntimeError(f"User parameter not found: {name}")

        # 鐢?expression 鏇粹€滃弬鏁板寲鑼冨紡鈥濓紝涓旇窡 UI 涓€鑷?
        param.expression = f"{float(value_mm)} mm"
        return {"parameter_name": name}

    def LIST_DESIGN_APPEARANCES(self) -> dict:
        """List appearances available in the current design."""
        design = self._get_design()
        names = []
        for i in range(design.appearances.count):
            app = design.appearances.item(i)
            if app and getattr(app, "isValid", False):
                names.append(app.name)
        names.sort()
        return {"appearance_names": names}

    def LIST_MATERIAL_LIBRARIES(self) -> dict:
        """List material libraries available in the app."""
        names = []
        libs = self.app.materialLibraries
        for i in range(libs.count):
            lib = libs.item(i)
            if lib:
                names.append(lib.name)
        names.sort()
        return {"library_names": names}

    def COPY_APPEARANCE_FROM_LIBRARY(
        self,
        library_name: str,
        appearance_name: str,
        new_name: str | None = None,
    ) -> dict:
        """Copy a library appearance into the current design."""
        copied = self._copy_appearance_to_design(library_name, appearance_name, new_name)
        return {"appearance_name": copied.name}

    def SET_BODY_APPEARANCE(self, body_id: str, appearance_name: str) -> dict:
        """Apply a design appearance to a body."""
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        appearance = self._find_design_appearance(appearance_name)
        if not appearance:
            self._fail("Appearance not found in design; use COPY_APPEARANCE_FROM_LIBRARY first")
        if not getattr(appearance, "isValid", False):
            self._fail(f"Appearance not valid: {appearance_name}")

        body.appearance = appearance
        return {"ok": True}

    def SET_OCCURRENCE_APPEARANCE(self, occurrence_id: str, appearance_name: str) -> dict:
        """Apply a design appearance to an occurrence."""
        occ = self._require_occurrence(occurrence_id)
        if not occ or not occ.isValid:
            raise RuntimeError(f"Occurrence not found or invalid: {occurrence_id}")

        appearance = self._find_design_appearance(appearance_name)
        if not appearance:
            self._fail("Appearance not found in design; use COPY_APPEARANCE_FROM_LIBRARY first")
        if not getattr(appearance, "isValid", False):
            self._fail(f"Appearance not valid: {appearance_name}")

        occ.appearance = appearance
        return {"ok": True}

    def SET_FACE_APPEARANCE(self, face_id: str, appearance_name: str) -> dict:
        """Apply a design appearance to a face."""
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")

        appearance = self._find_design_appearance(appearance_name)
        if not appearance:
            self._fail("Appearance not found in design; use COPY_APPEARANCE_FROM_LIBRARY first")
        if not getattr(appearance, "isValid", False):
            self._fail(f"Appearance not valid: {appearance_name}")

        face.appearance = appearance
        return {"ok": True}

    def CLEAR_BODY_APPEARANCE(self, body_id: str) -> dict:
        """Clear appearance override on a body."""
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        try:
            body.appearance = None
        except Exception as e:
            self._fail(f"Failed to clear body appearance: {e}")

        return {"ok": True}

    def CLEAR_OCCURRENCE_APPEARANCE(self, occurrence_id: str) -> dict:
        """Clear appearance override on an occurrence."""
        occ = self._require_occurrence(occurrence_id)
        if not occ or not occ.isValid:
            raise RuntimeError(f"Occurrence not found or invalid: {occurrence_id}")

        try:
            occ.appearance = None
        except Exception as e:
            self._fail(f"Failed to clear occurrence appearance: {e}")

        return {"ok": True}
    
    def CREATE_SKETCH_ON_PLANE(self, component_id: str, plane, name: str = None):
        """鍦ㄦ寚瀹氬钩闈㈠垱寤?sketch
        plane 鏀寔锛?
          - {"type": "XY"|"XZ"|"YZ"}
          - {"plane_id": "..."}  # ConstructionPlane
          - {"face_id": "..."}   # BRepFace
          - "..."                # 鐩存帴浼?plane_id(str)
        """
        # validate inputs & ids
        if not name:
            raise RuntimeError("CREATE_SKETCH_ON_PLANE requires a non-empty name")

        comp = self._require_component(component_id)
        sketches = comp.sketches

        # ---------- resolve plane object ----------
        plane_obj = None

        # 1) allow passing plane_id directly as string
        if isinstance(plane, str) and plane.strip():
            plane_obj = self._require_plane(plane.strip())

        # 2) dict form
        elif isinstance(plane, dict):
            # a) explicit plane_id
            plane_ref = plane.get("plane_id")
            if plane_ref:
                plane_obj = self._require_plane(plane_ref)

            # b) face_id (common: sketch on a planar face)
            face_ref = plane.get("face_id")
            if plane_obj is None and face_ref:
                plane_obj = self._require_face(face_ref)

            # c) base planes
            if plane_obj is None:
                plane_type = plane.get("type", "XY")
                if plane_type == "XY":
                    plane_obj = comp.xYConstructionPlane
                elif plane_type == "XZ":
                    plane_obj = comp.xZConstructionPlane
                elif plane_type == "YZ":
                    plane_obj = comp.yZConstructionPlane
                else:
                    raise RuntimeError(f"Unsupported plane.type in CREATE_SKETCH_ON_PLANE: {plane_type}")

        else:
            raise RuntimeError("CREATE_SKETCH_ON_PLANE requires plane as dict or plane_id string")

        if plane_obj is None or not getattr(plane_obj, "isValid", False):
            raise RuntimeError(f"Sketch plane not found or invalid: {plane}")

        # ---------- create sketch ----------
        sketch_id = f"{component_id}:{name}"
        if self.strict_mode and sketch_id in self._sketches:
            raise RuntimeError(f"Sketch already exists: {sketch_id}")

        sketch = sketches.add(plane_obj)
        sketch.name = name

        self._cache_sketch(sketch_id, sketch)
        self._sketch_id_by_obj[id(sketch)] = sketch_id
        return {"sketch_id": sketch_id}

    def CREATE_SKETCH_ON_FACE(self, component_id: str, face_id: str, name: str) -> dict:
        """鍦ㄦ寚瀹氶潰涓婂垱寤?sketch"""
        # validate inputs & ids
        if not name:
            raise RuntimeError("CREATE_SKETCH_ON_FACE requires a non-empty name")

        comp = self._require_component(component_id)
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")
        if not self._is_planar_face(face):
            raise RuntimeError(f"CREATE_SKETCH_ON_FACE requires planar face: {face_id}")

        sketches = comp.sketches

        sketch_id = f"{component_id}:{name}"
        if self.strict_mode and sketch_id in self._sketches:
            raise RuntimeError(f"Sketch already exists: {sketch_id}")

        sketch = sketches.add(face)
        sketch.name = name

        self._cache_sketch(sketch_id, sketch)
        self._sketch_id_by_obj[id(sketch)] = sketch_id
        return {"sketch_id": sketch_id}

    def CREATE_OFFSET_PLANE(self, *args, **kwargs):
        # validate inputs & ids
        raise RuntimeError(
            "CREATE_OFFSET_PLANE is deprecated. Use CREATE_OFFSET_CONSTRUCTION_PLANE instead."
        )

    def CREATE_OFFSET_CONSTRUCTION_PLANE(
        self,
        component_id: str,
        base_plane,
        offset_mm: float,
        name: str | None = None,
    ) -> dict:
        """鍒涘缓鍋忕Щ鏋勯€犲钩闈紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)

        def _resolve_base_plane(plane_ref):
            if isinstance(plane_ref, dict):
                plane_type = plane_ref.get("type")
                if plane_type == "XY":
                    return comp.xYConstructionPlane, {"kind": "construction_plane", "source": "XY"}
                if plane_type == "XZ":
                    return comp.xZConstructionPlane, {"kind": "construction_plane", "source": "XZ"}
                if plane_type == "YZ":
                    return comp.yZConstructionPlane, {"kind": "construction_plane", "source": "YZ"}
                face_id = plane_ref.get("face_id")
                if face_id:
                    face_obj = self._require_face(face_id)
                    if not face_obj or not face_obj.isValid:
                        raise RuntimeError(f"Face not found or invalid: {face_id}")
                    if not self._is_planar_face(face_obj):
                        raise RuntimeError(f"CREATE_OFFSET_CONSTRUCTION_PLANE requires planar face: {face_id}")
                    return face_obj, {"kind": "face", "face_id": face_id}
                plane_id = plane_ref.get("plane_id")
                if plane_id:
                    plane_obj = self._require_plane(plane_id)
                    if not plane_obj or not plane_obj.isValid:
                        raise RuntimeError(f"ConstructionPlane not found or invalid: {plane_id}")
                    return plane_obj, {"kind": "construction_plane", "plane_id": plane_id}
                raise RuntimeError("CREATE_OFFSET_CONSTRUCTION_PLANE requires plane type, plane_id, or face_id")
            if isinstance(plane_ref, str):
                plane_obj = self._require_plane(plane_ref)
                if not plane_obj or not plane_obj.isValid:
                    raise RuntimeError(f"ConstructionPlane not found or invalid: {plane_ref}")
                return plane_obj, {"kind": "construction_plane", "plane_id": plane_ref}
            raise RuntimeError("CREATE_OFFSET_CONSTRUCTION_PLANE requires base_plane as dict or plane_id")

        base_plane_obj, base_plane_meta = _resolve_base_plane(base_plane)

        planes = comp.constructionPlanes
        plane_input = planes.createInput()
        try:
            plane_input.setByOffset(base_plane_obj, self.mm(offset_mm))
        except Exception as first_error:
            # Some Fusion API builds may reject BRepFace directly for setByOffset.
            # Fallback: use planar face.geometry as the offset base.
            if isinstance(base_plane_meta, dict) and base_plane_meta.get("kind") == "face":
                face_id = base_plane_meta.get("face_id")
                try:
                    face_obj = self._require_face(face_id) if isinstance(face_id, str) else None
                    face_geom = getattr(face_obj, "geometry", None)
                    if face_geom is None:
                        raise RuntimeError(f"Face geometry unavailable for offset base: {face_id}")
                    plane_input = planes.createInput()
                    plane_input.setByOffset(face_geom, self.mm(offset_mm))
                except Exception as fallback_error:
                    raise RuntimeError(
                        "CREATE_OFFSET_CONSTRUCTION_PLANE failed for face_id base: "
                        f"setByOffset(face) error={first_error}; setByOffset(face.geometry) error={fallback_error}"
                    )
            else:
                raise
        plane = planes.add(plane_input)

        if name:
            plane.name = name
            plane_id = f"{component_id}:{name}"
        else:
            plane_id = f"{component_id}:plane:{len(self._planes) + 1}"

        if not plane or not plane.isValid:
            raise RuntimeError("CREATE_OFFSET_CONSTRUCTION_PLANE failed to create plane")

        self._cache_plane(plane_id, plane)
        return {"plane_id": plane_id}

    def CREATE_MIDPLANE(self, component_id: str, plane_a: dict, plane_b: dict, name: str) -> dict:
        """鍒涘缓涓ゅ钩闈腑闂撮潰锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        if not name:
            raise RuntimeError("CREATE_MIDPLANE requires a non-empty name")

        comp = self._require_component(component_id)
        plane_id = f"{component_id}:{name}"
        if self.strict_mode and plane_id in self._planes:
            raise RuntimeError(f"Construction plane already exists: {plane_id}")

        def _resolve_plane(plane: dict):
            if not isinstance(plane, dict):
                raise RuntimeError("CREATE_MIDPLANE requires plane definitions as dicts")
            plane_type = plane.get("type")
            if plane_type == "XY":
                return comp.xYConstructionPlane
            if plane_type == "XZ":
                return comp.xZConstructionPlane
            if plane_type == "YZ":
                return comp.yZConstructionPlane
            plane_ref = plane.get("plane_id")
            if plane_ref:
                plane_obj = self._require_plane(plane_ref)
                if not plane_obj or not plane_obj.isValid:
                    raise RuntimeError(f"ConstructionPlane not found or invalid: {plane_ref}")
                return plane_obj
            raise RuntimeError("CREATE_MIDPLANE requires plane type or plane_id")

        plane_a_obj = _resolve_plane(plane_a)
        plane_b_obj = _resolve_plane(plane_b)

        planes = comp.constructionPlanes
        plane_input = planes.createInput()
        plane_input.setByTwoPlanes(plane_a_obj, plane_b_obj)
        mid_plane = planes.add(plane_input)
        mid_plane.name = name
        self._cache_plane(plane_id, mid_plane)
        return {"plane_id": plane_id}

    def CREATE_PLANE_AT_ANGLE(
        self,
        component_id: str,
        edge_id: str,
        angle_deg: float,
        name: str,
    ) -> dict:
        """鍒涘缓涓庤竟鎴愯搴︾殑鏋勯€犲钩闈?"""
        # validate inputs & ids
        if not name:
            raise RuntimeError("CREATE_PLANE_AT_ANGLE requires a non-empty name")

        comp = self._require_component(component_id)
        edge = self._require_edge(edge_id)
        if not edge or not edge.isValid:
            raise RuntimeError(f"Edge not found or invalid: {edge_id}")

        planes = comp.constructionPlanes
        plane_input = planes.createInput()
        angle = adsk.core.ValueInput.createByReal(math.radians(float(angle_deg)))
        reference_plane = comp.xYConstructionPlane
        plane_input.setByAngle(edge, angle, reference_plane)
        plane = planes.add(plane_input)

        if not plane or not plane.isValid:
            raise RuntimeError("CREATE_PLANE_AT_ANGLE failed to create plane")

        plane.name = name
        plane_id = f"{component_id}:plane:{name}"
        self._cache_plane(plane_id, plane)
        return {"plane_id": plane_id}

    def CREATE_TANGENT_PLANE_AT_POINT(
        self,
        component_id: str,
        face_id: str,
        point,
        name: str,
    ) -> dict:
        """鍒涘缓鍦ㄥ渾鏌遍潰涓婁笌鐐圭浉鍒囩殑鏋勯€犲钩闈?"""
        # validate inputs & ids
        if not name:
            raise RuntimeError("CREATE_TANGENT_PLANE_AT_POINT requires a non-empty name")

        comp = self._require_component(component_id)
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")
        if not self._is_cylindrical_face(face):
            raise RuntimeError(f"CREATE_TANGENT_PLANE_AT_POINT requires cylindrical face: {face_id}")

        if isinstance(point, dict) and "sketch_point_id" in point:
            sketch_point_id = point.get("sketch_point_id")
            sketch_point = self._require_sketch_point(sketch_point_id)
            if not sketch_point or not sketch_point.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {sketch_point_id}")
            point_obj = sketch_point.geometry
        elif isinstance(point, str):
            sketch_point = self._require_sketch_point(point)
            if not sketch_point or not sketch_point.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {point}")
            point_obj = sketch_point.geometry
        elif isinstance(point, dict):
            point_obj = self.cm_point(
                point.get("x", 0),
                point.get("y", 0),
                point.get("z", 0),
            )
        else:
            raise RuntimeError("CREATE_TANGENT_PLANE_AT_POINT requires point as dict or sketch_point_id")

        planes = comp.constructionPlanes
        plane_input = planes.createInput()
        plane_input.setByTangentAtPoint(face, point_obj)
        plane = planes.add(plane_input)

        if not plane or not plane.isValid:
            raise RuntimeError("CREATE_TANGENT_PLANE_AT_POINT failed to create plane")

        plane.name = name
        plane_id = f"{component_id}:plane:{name}"
        self._cache_plane(plane_id, plane)
        return {"plane_id": plane_id}

    def CONSTRUCTION_PLANE_TANGENT_TO_CYLINDER(
        self,
        component_id: str,
        face_id: str,
        angle_deg: float,
        axial_offset_mm: float,
        axial_span_mm: float | None = None,
        name: str = "",
    ) -> dict:
        """Create a tangent construction plane on a cylindrical face at a deterministic physical location.

        IMPORTANT:
        - angle_deg is treated as an angle around the cylinder axis in *geometric space*.
        - axial_offset_mm is treated as a physical offset along the cylinder axis measured from the
          trimmed face's minimum axial projection.
        - This avoids drift when the cylindrical face is trimmed/split (UV extents are not stable).

        Output includes point_mm (mm) that lies on the face and on the plane.
        """
        if not name:
            raise RuntimeError("CONSTRUCTION_PLANE_TANGENT_TO_CYLINDER requires a non-empty name")

        comp = self._require_component(component_id)
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")
        if not self._is_cylindrical_face(face):
            raise RuntimeError(
                f"CONSTRUCTION_PLANE_TANGENT_TO_CYLINDER requires cylindrical face: {face_id}"
            )

        cyl = None
        try:
            cyl = face.geometry
        except Exception:
            cyl = None

        def _get_cylinder_axis_line(cyl_geom: Any) -> tuple[adsk.core.Point3D, adsk.core.Vector3D]:
            """
            Return (origin: Point3D, direction: Vector3D) for a cylindrical geometry.
            Must be robust across Fusion API variants.
            """
            # Accept BRepFace / wrapper objects.
            geom = cyl_geom
            try:
                if isinstance(geom, adsk.fusion.BRepFace):
                    geom = geom.geometry
            except Exception:
                pass

            # 1) axisLine first (most stable): has origin + direction
            axis_line = getattr(geom, "axisLine", None)
            if axis_line is not None:
                o = getattr(axis_line, "origin", None)
                d = getattr(axis_line, "direction", None)
                if o is not None and d is not None:
                    return o, d

            # 2) origin/basePoint + axis(Vector3D)
            origin = getattr(geom, "origin", None) or getattr(geom, "basePoint", None)
            axis_vec = getattr(geom, "axis", None)
            if origin is not None and axis_vec is not None:
                return origin, axis_vec

            # 3) Some wrappers expose nested geometry.
            nested = getattr(geom, "geometry", None)
            if nested is not None and nested is not geom:
                axis_line = getattr(nested, "axisLine", None)
                if axis_line is not None:
                    o = getattr(axis_line, "origin", None)
                    d = getattr(axis_line, "direction", None)
                    if o is not None and d is not None:
                        return o, d
                origin = getattr(nested, "origin", None) or getattr(nested, "basePoint", None)
                axis_vec = getattr(nested, "axis", None)
                if origin is not None and axis_vec is not None:
                    return origin, axis_vec

            def _safe_attrs(obj: Any) -> list[str]:
                try:
                    return sorted([n for n in dir(obj) if not n.startswith("__")])[:80]
                except Exception:
                    return []

            raise RuntimeError(
                "Cannot extract cylinder axis line"
                f" (type={type(cyl_geom)}, attrs={_safe_attrs(cyl_geom)}, nested_attrs={_safe_attrs(geom)})"
            )

        axis_line = None
        radius_cm = None
        try:
            r_val = getattr(cyl, "radius", None)
            radius_cm = float(r_val) if r_val is not None else None
        except Exception:
            radius_cm = None

        try:
            axis_origin, axis_dir = _get_cylinder_axis_line(cyl)
        except Exception as e:
            raise RuntimeError(
                f"Failed to read cylinder axis origin/direction for component_id={component_id}, face_id={face_id}: "
                f"{type(e).__name__}: {e}"
            )

        if radius_cm is None or radius_cm <= 0:
            raise RuntimeError(
                f"Failed to read cylinder radius from face.geometry for component_id={component_id}, face_id={face_id}"
            )

        if axis_origin is None or axis_dir is None:
            raise RuntimeError("Cylinder axis origin/direction missing")

        try:
            axis_dir = adsk.core.Vector3D.create(axis_dir.x, axis_dir.y, axis_dir.z)
            axis_dir.normalize()
        except Exception as e:
            raise RuntimeError(f"Failed to normalize axis direction: {type(e).__name__}: {e}")

        def _dot(a: adsk.core.Vector3D, b: adsk.core.Vector3D) -> float:
            return float(a.x) * float(b.x) + float(a.y) * float(b.y) + float(a.z) * float(b.z)

        def _scaled(v: adsk.core.Vector3D, s: float) -> adsk.core.Vector3D:
            out = adsk.core.Vector3D.create(v.x, v.y, v.z)
            out.scaleBy(float(s))
            return out

        def _sub_points(a: adsk.core.Point3D, b: adsk.core.Point3D) -> adsk.core.Vector3D:
            return adsk.core.Vector3D.create(float(a.x) - float(b.x), float(a.y) - float(b.y), float(a.z) - float(b.z))

        def _rodrigues(v: adsk.core.Vector3D, k_unit: adsk.core.Vector3D, theta_rad: float) -> adsk.core.Vector3D:
            # v_rot = v*cos + (k脳v)*sin + k*(k路v)*(1-cos)
            cos_t = math.cos(theta_rad)
            sin_t = math.sin(theta_rad)
            k = adsk.core.Vector3D.create(k_unit.x, k_unit.y, k_unit.z)
            k.normalize()

            v1 = _scaled(v, cos_t)
            cross = k.crossProduct(v)
            v2 = _scaled(cross, sin_t)
            v3 = _scaled(k, _dot(k, v) * (1.0 - cos_t))
            v1.add(v2)
            v1.add(v3)
            return v1

        # Compute trimmed-face axial span in geometric space from vertices projection.
        s_min = None
        s_max = None
        try:
            verts = getattr(face, "vertices", None)
            if verts is not None and getattr(verts, "count", 0) > 0:
                for i in range(verts.count):
                    vtx = verts.item(i)
                    if not vtx or not vtx.isValid:
                        continue
                    p = vtx.geometry
                    if p is None:
                        continue
                    rel = _sub_points(p, axis_origin)
                    s = _dot(rel, axis_dir)  # cm
                    if s_min is None or s < s_min:
                        s_min = s
                    if s_max is None or s > s_max:
                        s_max = s
        except Exception:
            s_min = None
            s_max = None

        # Fallback: parameter extents midpoint if vertices not available.
        if s_min is None or s_max is None:
            evaluator = getattr(face, "evaluator", None)
            if evaluator is None:
                raise RuntimeError("Face has no evaluator; cannot compute tangent point")
            try:
                ok, u_min, u_max, v_min, v_max = evaluator.getParameterExtents()
            except Exception as e:
                raise RuntimeError(f"Failed to get cylinder parameter extents: {type(e).__name__}: {e}")
            if not ok:
                raise RuntimeError("Failed to get cylinder parameter extents")
            try:
                u_mid = float(u_min) + 0.5 * (float(u_max) - float(u_min))
                v_mid = float(v_min) + 0.5 * (float(v_max) - float(v_min))
                ok_pt, pt_mid = evaluator.getPointAtParameter(u_mid, v_mid)
            except Exception as e:
                raise RuntimeError(f"Failed to evaluate midpoint on cylinder: {type(e).__name__}: {e}")
            if not ok_pt or pt_mid is None:
                raise RuntimeError("Failed to evaluate midpoint on cylinder")
            rel_mid = _sub_points(pt_mid, axis_origin)
            s_mid = _dot(rel_mid, axis_dir)
            s_min = s_mid - 0.5
            s_max = s_mid + 0.5

        # Physical axial offset from the trimmed face min.
        try:
            s_target = float(s_min) + float(axial_offset_mm) / 10.0
        except Exception:
            s_target = float(s_min) + 0.5 * (float(s_max) - float(s_min))

        # If caller provided an expected span, clamp but never re-map by UV.
        try:
            if isinstance(axial_span_mm, (int, float)) and float(axial_span_mm) > 0:
                # Allow offsets within [0, axial_span_mm] from s_min.
                s_target = max(float(s_min), min(float(s_min) + float(axial_span_mm) / 10.0, s_target))
        except Exception:
            pass

        # Always clamp to actual trimmed-face span.
        s_target = max(float(s_min), min(float(s_max), float(s_target)))

        axis_point = adsk.core.Point3D.create(
            float(axis_origin.x) + float(axis_dir.x) * float(s_target),
            float(axis_origin.y) + float(axis_dir.y) * float(s_target),
            float(axis_origin.z) + float(axis_dir.z) * float(s_target),
        )

        # Reference direction for angle=0: world X projected onto plane perpendicular to axis.
        world_x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
        ref = adsk.core.Vector3D.create(world_x.x, world_x.y, world_x.z)
        ref.add(_scaled(axis_dir, -_dot(ref, axis_dir)))
        if ref.length < 1e-6:
            world_y = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
            ref = adsk.core.Vector3D.create(world_y.x, world_y.y, world_y.z)
            ref.add(_scaled(axis_dir, -_dot(ref, axis_dir)))
        if ref.length < 1e-6:
            raise RuntimeError("Failed to compute cylinder reference direction")
        ref.normalize()

        try:
            ang = math.radians(float(angle_deg) % 360.0)
        except Exception:
            ang = 0.0
        radial_dir = _rodrigues(ref, axis_dir, ang)
        if radial_dir.length < 1e-9:
            raise RuntimeError("Failed to compute radial direction")
        radial_dir.normalize()
        radial_vec = _scaled(radial_dir, float(radius_cm))

        pt = adsk.core.Point3D.create(axis_point.x + radial_vec.x, axis_point.y + radial_vec.y, axis_point.z + radial_vec.z)

        planes = comp.constructionPlanes
        plane_input = planes.createInput()
        plane_input.setByTangentAtPoint(face, pt)
        plane = planes.add(plane_input)
        if not plane or not plane.isValid:
            raise RuntimeError("CONSTRUCTION_PLANE_TANGENT_TO_CYLINDER failed to create plane")
        plane.name = name
        plane_id = f"{component_id}:plane:{name}"
        self._cache_plane(plane_id, plane)

        point_mm = {
            "x": float(pt.x) * 10.0,
            "y": float(pt.y) * 10.0,
            "z": float(pt.z) * 10.0,
        }
        return {"plane_id": plane_id, "point_mm": point_mm}

    def COMBINE_BODIES(
        self,
        component_id: str,
        target_body_id: str,
        tool_body_ids: list,
        operation: str = "join",
        keep_tools: bool = True,
        name: str | None = None,
    ) -> dict:
        """缁勫悎瀹炰綋锛堝畼鏂?Combine Feature 妯″紡锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        target_body = self._require_body(target_body_id)
        if not target_body or not target_body.isValid:
            raise RuntimeError(f"Target body not found or invalid: {target_body_id}")

        tools = adsk.core.ObjectCollection.create()
        for tool_id in tool_body_ids:
            tool_body = self._require_body(tool_id)
            if not tool_body or not tool_body.isValid:
                raise RuntimeError(f"Tool body not found or invalid: {tool_id}")
            tools.add(tool_body)

        combine_feats = comp.features.combineFeatures
        combine_input = combine_feats.createInput(target_body, tools)

        if operation == "join":
            combine_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            combine_input.operation = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported combine operation: {operation}")

        combine_input.isKeepToolBodies = keep_tools
        feature = combine_feats.add(combine_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "combine")
        self._cache_feature(feature_id, feature)
        if target_body and target_body.isValid:
            self._cache_body(target_body_id, target_body)
        elif hasattr(feature, "bodies") and feature.bodies.count > 0:
            self._cache_body(target_body_id, feature.bodies.item(0))
        return self._ret_feature(feature_id=feature_id, extra={"body_id": target_body_id})

    def FILLET_BODY_EDGES(
        self,
        component_id: str,
        body_id: str,
        radius_mm: float,
        tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """瀵瑰疄浣撹竟杩涜鍊掑渾瑙掞紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        edges = adsk.core.ObjectCollection.create()
        for i in range(body.edges.count):
            edges.add(body.edges.item(i))

        fillets = comp.features.filletFeatures
        fillet_input = fillets.createInput()
        edge_sets = fillet_input.edgeSetInputs
        radius = self.mm(radius_mm)
        edge_sets.addConstantRadiusEdgeSet(edges, radius, tangent_chain)

        feature = fillets.add(fillet_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "fillet")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def CHAMFER_BODY_EDGES(
        self,
        component_id: str,
        body_id: str,
        distance_mm: float,
        distance2_mm: float | None = None,
        angle_deg: float | None = None,
        tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """Apply chamfer to all edges of a body.

        Supports three official Fusion 360 chamfer modes:
        - Equal distance:        distance_mm only
        - Two distances:         distance_mm + distance2_mm
        - Distance and angle:    distance_mm + angle_deg
        """
        import math
        # validate inputs & ids
        comp = self._require_component(component_id)
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        edges = adsk.core.ObjectCollection.create()
        for i in range(body.edges.count):
            edges.add(body.edges.item(i))

        chamfers = comp.features.chamferFeatures
        chamfer_input = chamfers.createInput2()
        edge_sets = chamfer_input.chamferEdgeSets

        if distance2_mm is not None:
            edge_sets.addTwoDistancesChamferEdgeSet(
                edges, self.mm(distance_mm), self.mm(distance2_mm), False, tangent_chain
            )
        elif angle_deg is not None:
            angle_val = adsk.core.ValueInput.createByReal(math.radians(float(angle_deg)))
            edge_sets.addDistanceAndAngleChamferEdgeSet(
                edges, self.mm(distance_mm), angle_val, False, tangent_chain
            )
        else:
            edge_sets.addEqualDistanceChamferEdgeSet(
                edges, self.mm(distance_mm), tangent_chain
            )

        feature = chamfers.add(chamfer_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "chamfer")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def MOVE_BODIES(
        self,
        component_id: str,
        body_ids: list[str],
        translation_mm: dict | None = None,
        rotation_deg: float | None = None,
        rotation_axis: dict | None = None,
        rotation_origin_mm: dict | None = None,
        name: str | None = None,
    ) -> dict:
        """Move/rotate bodies via MoveFeatures (inputs in mm, stored as cm).

        Transform construction order (critical):
          1. Build rotation matrix first (``setToRotation`` about ``rotation_origin_mm``).
          2. **Then** add user translation 鈥?so translation is in world space and
             does NOT get rotated by the rotation matrix.

        Final matrix semantics: rotate bodies around the specified origin,
        then translate by ``translation_mm`` in world coordinates.
        """
        # validate inputs & ids
        if not body_ids:
            raise RuntimeError("MOVE_BODIES requires at least one body_id")

        comp = self._require_component(component_id)
        bodies = adsk.core.ObjectCollection.create()
        for body_id in body_ids:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            bodies.add(body)

        # 鈹€鈹€ Build transform: rotation FIRST, translation SECOND 鈹€鈹€
        transform = adsk.core.Matrix3D.create()  # identity

        if rotation_deg is not None:
            import math

            angle = math.radians(float(rotation_deg))
            if rotation_axis is None:
                ax, ay, az = 0.0, 0.0, 1.0
            else:
                ax = float(rotation_axis.get("x", 0.0))
                ay = float(rotation_axis.get("y", 0.0))
                az = float(rotation_axis.get("z", 1.0))
                if abs(ax) + abs(ay) + abs(az) == 0:
                    raise RuntimeError("MOVE_BODIES rotation_axis cannot be zero vector")

            axis_vec = adsk.core.Vector3D.create(ax, ay, az)
            axis_vec.normalize()

            if rotation_origin_mm is None:
                ox, oy, oz = 0.0, 0.0, 0.0
            else:
                ox = float(rotation_origin_mm.get("x", 0.0)) / 10.0
                oy = float(rotation_origin_mm.get("y", 0.0)) / 10.0
                oz = float(rotation_origin_mm.get("z", 0.0)) / 10.0

            origin = adsk.core.Point3D.create(ox, oy, oz)
            rot = adsk.core.Matrix3D.create()
            rot.setToRotation(angle, axis_vec, origin)
            transform.transformBy(rot)  # transform = R (rotation with its own translation from non-origin)

        # Add user translation AFTER rotation (additive, not rotated)
        if translation_mm is not None:
            dx = float(translation_mm.get("x", 0.0)) / 10.0
            dy = float(translation_mm.get("y", 0.0)) / 10.0
            dz = float(translation_mm.get("z", 0.0)) / 10.0
            cur = transform.translation
            transform.translation = adsk.core.Vector3D.create(
                cur.x + dx, cur.y + dy, cur.z + dz
            )

        move_feats = comp.features.moveFeatures
        move_input = move_feats.createInput2(bodies)
        move_input.defineAsFreeMove(transform)
        feature = move_feats.add(move_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "move")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def MOVE_OCCURRENCE(
        self,
        occurrence_id: str,
        translation_mm: dict | None = None,
        rotation_deg: float | None = None,
        rotation_axis: dict | None = None,
        rotation_origin_mm: dict | None = None,
    ) -> dict:
        """Apply a delta move/rotation to an occurrence (inputs in mm, stored as cm).

        The delta transform is constructed as: rotate first, then translate.
        Translation is in world/parent space and is NOT rotated by the rotation.
        The delta is then pre-multiplied onto the existing occurrence transform.
        """
        # validate inputs & ids
        occ = self._get_occurrence(occurrence_id)

        # 鈹€鈹€ Build delta transform: rotation FIRST, translation SECOND 鈹€鈹€
        transform = adsk.core.Matrix3D.create()  # identity

        if rotation_deg is not None:
            import math

            angle = math.radians(float(rotation_deg))
            if rotation_axis is None:
                ax, ay, az = 0.0, 0.0, 1.0
            else:
                ax = float(rotation_axis.get("x", 0.0))
                ay = float(rotation_axis.get("y", 0.0))
                az = float(rotation_axis.get("z", 1.0))
                if abs(ax) + abs(ay) + abs(az) == 0:
                    raise RuntimeError("MOVE_OCCURRENCE rotation_axis cannot be zero vector")

            axis_vec = adsk.core.Vector3D.create(ax, ay, az)
            axis_vec.normalize()

            if rotation_origin_mm is None:
                ox, oy, oz = 0.0, 0.0, 0.0
            else:
                ox = float(rotation_origin_mm.get("x", 0.0)) / 10.0
                oy = float(rotation_origin_mm.get("y", 0.0)) / 10.0
                oz = float(rotation_origin_mm.get("z", 0.0)) / 10.0

            origin = adsk.core.Point3D.create(ox, oy, oz)
            rot = adsk.core.Matrix3D.create()
            rot.setToRotation(angle, axis_vec, origin)
            transform.transformBy(rot)

        # Add user translation AFTER rotation (additive, not rotated)
        if translation_mm is not None:
            dx = float(translation_mm.get("x", 0.0)) / 10.0
            dy = float(translation_mm.get("y", 0.0)) / 10.0
            dz = float(translation_mm.get("z", 0.0)) / 10.0
            cur = transform.translation
            transform.translation = adsk.core.Vector3D.create(
                cur.x + dx, cur.y + dy, cur.z + dz
            )

        # Use transform2 (official replacement for retired 'transform' property).
        current = occ.transform2
        current.transformBy(transform)
        occ.transform2 = current
        return self._ret_feature(extra={"occurrence_id": occurrence_id})

    def ENSURE_OCCURRENCE_R1(
        self,
        component_id: str,
        occurrence_name: str | None = None,
        parent_component_id: str | None = None,
        occurrence_id: str | None = None,
        transform_mm: dict | None = None,
    ) -> dict:
        """Ensure an occurrence exists for an existing component definition.

        Use-cases:
        - For components created earlier (CREATE_COMPONENT / INSERT_*), pass occurrence_id
          to validate/cache it (no-op) and optionally rename.
        - For existing component definitions without an occurrence, create a new occurrence
          under parent (or root) deterministically.
        """
        if occurrence_id:
            occ = self._require_occurrence(occurrence_id)
            if occurrence_name:
                try:
                    occ.name = str(occurrence_name)
                except Exception:
                    pass
            occ = self._stabilize_occurrence_reference(str(occurrence_id), occ)
            if occurrence_name:
                try:
                    self._occ_name_to_id[str(occurrence_name)] = str(occurrence_id)
                except Exception:
                    pass
            return {"occurrence_id": str(occurrence_id), "created": False}

        comp = self._require_component(component_id)
        target = self.root_comp
        if parent_component_id:
            target = self._require_component(parent_component_id)

        mat = self._matrix_from_transform_mm(transform_mm)

        occ = target.occurrences.addExistingComponent(comp, mat)
        if not occ or not getattr(occ, "isValid", False):
            self._fail(f"Failed to create occurrence for component_id: {component_id}")

        try:
            if occurrence_name:
                occ.name = str(occurrence_name)
        except Exception:
            pass

        new_id = self._new_occurrence_id(str(occurrence_name or getattr(comp, "name", "occ")))
        occ = self._stabilize_occurrence_reference(new_id, occ)
        if occurrence_name:
            self._occ_name_to_id[str(occurrence_name)] = new_id

        return {"occurrence_id": new_id, "created": True}

    def _append_occurrence_transform_log(self, payload: dict) -> None:
        if not self.run_dir:
            return
        try:
            out_path = Path(self.run_dir) / "fusion_occurrence_transforms.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def SET_OCCURRENCE_TRANSFORM_R1(
        self,
        occurrence_id: str,
        transform_mm: dict,
        grounded: bool | None = None,
        mode: str = "absolute",
        step_id: str | None = None,
    ) -> dict:
        """Set occurrence local transform using mm translation + roll/pitch/yaw(deg).

        Args:
            mode: 'absolute' (default) or 'relative' (post-multiply existing transform by delta).
            step_id: optional dispatcher step id (for run-dir logging).
        """
        occ = self._require_occurrence(occurrence_id)
        if not isinstance(transform_mm, dict):
            raise RuntimeError("SET_OCCURRENCE_TRANSFORM_R1 requires transform_mm object")

        translation_raw = transform_mm.get("translation")
        rotation_raw = transform_mm.get("rotation_rpy_deg")
        translation = translation_raw if isinstance(translation_raw, dict) else {}
        rotation = rotation_raw if isinstance(rotation_raw, dict) else {}

        transform = self._matrix_from_transform_mm(transform_mm)

        mode_s = str(mode).strip().lower() if isinstance(mode, str) else "absolute"
        if mode_s not in {"absolute", "relative"}:
            mode_s = "absolute"

        requested_rotation = {
            "roll": float(rotation.get("roll", 0.0)),
            "pitch": float(rotation.get("pitch", 0.0)),
            "yaw": float(rotation.get("yaw", 0.0)),
        }

        def _apply_transform(target_occ):
            nonlocal mode_s
            if mode_s == "relative":
                try:
                    base = target_occ.transform2.copy()
                except Exception:
                    base = adsk.core.Matrix3D.create()
                    try:
                        base.setToIdentity()
                    except Exception:
                        pass
                try:
                    base.transformBy(transform)
                    target_occ.transform2 = base
                except Exception:
                    target_occ.transform2 = transform
                    mode_s = "absolute"
            else:
                target_occ.transform2 = transform
            if grounded is not None:
                try:
                    target_occ.isGrounded = bool(grounded)
                except Exception:
                    pass

        _apply_transform(occ)

        resolved_occurrence_id = self._resolve_occurrence_id(occurrence_id)
        requested_translation = {
            "x": float(translation.get("x", 0.0)),
            "y": float(translation.get("y", 0.0)),
            "z": float(translation.get("z", 0.0)),
        }
        try:
            expected_map = getattr(self, "_occurrence_last_translation_mm", None)
            if isinstance(expected_map, dict):
                expected_map[str(resolved_occurrence_id)] = dict(requested_translation)
            expected_rotation_map = getattr(self, "_occurrence_last_rotation_rpy_deg", None)
            if isinstance(expected_rotation_map, dict):
                expected_rotation_map[str(resolved_occurrence_id)] = dict(requested_rotation)
        except Exception:
            pass

        try:
            recovered = self._recover_occurrence_from_live_tree(resolved_occurrence_id)
        except Exception:
            recovered = None
        if recovered is not None and getattr(recovered, "isValid", False) and recovered is not occ:
            occ = recovered
            _apply_transform(occ)
            try:
                self._cache_occurrence(str(resolved_occurrence_id), occ)
            except Exception:
                pass

        # Best-effort transform log (run-dir rooted).
        try:
            occ_name = None
            try:
                occ_name = getattr(occ, "name", None)
            except Exception:
                occ_name = None
            actual_translation = self._occurrence_translation_mm(occ)
            try:
                if isinstance(getattr(self, "_occurrence_last_translation_mm", None), dict) and isinstance(actual_translation, dict):
                    self._occurrence_last_translation_mm[str(resolved_occurrence_id)] = dict(actual_translation)
            except Exception:
                pass
            self._append_occurrence_transform_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "step_id": step_id,
                    "occurrence_id": occurrence_id,
                    "occurrence_name": occ_name,
                    "mode": mode_s,
                    "translation_mm": dict(requested_translation),
                    "requested_translation_mm": dict(requested_translation),
                    "actual_translation_mm": actual_translation,
                    "rotation_rpy_deg": dict(requested_rotation),
                    "grounded": grounded,
                }
            )
        except Exception:
            pass
        return {"occurrence_id": occurrence_id, "applied": True}

    def GROUND_OCCURRENCE(self, occurrence_id: str) -> dict:
        """灏?occurrence 璁句负 grounded"""
        # validate inputs & ids
        occ = self._get_occurrence(occurrence_id)
        occ.isGrounded = True
        return {"occurrence_id": occurrence_id}

    def UNGROUND_OCCURRENCE(self, occurrence_id: str) -> dict:
        """鍙栨秷 occurrence 鐨?grounded"""
        # validate inputs & ids
        occ = self._get_occurrence(occurrence_id)
        occ.isGrounded = False
        return {"occurrence_id": occurrence_id}

    def MIRROR_BODIES(
        self,
        component_id: str,
        body_ids: list[str],
        mirror_plane: dict,
        operation: str = "new_body",
        name: str | None = None,
    ) -> dict:
        """浣跨敤 MirrorFeatures 闀滃儚瀹炰綋"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        entities = adsk.core.ObjectCollection.create()
        for body_id in body_ids:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            entities.add(body)

        if not isinstance(mirror_plane, dict):
            raise RuntimeError("MIRROR_BODIES requires mirror_plane to be a dict")

        plane_obj = None
        plane_type = mirror_plane.get("type")
        if plane_type == "XY":
            plane_obj = comp.xYConstructionPlane
        elif plane_type == "XZ":
            plane_obj = comp.xZConstructionPlane
        elif plane_type == "YZ":
            plane_obj = comp.yZConstructionPlane
        elif "plane_id" in mirror_plane:
            plane_id = mirror_plane.get("plane_id")
            plane_obj = self._require_plane(plane_id)
            if not plane_obj or not plane_obj.isValid:
                raise RuntimeError(f"ConstructionPlane not found or invalid: {plane_id}")
        else:
            raise RuntimeError("MIRROR_BODIES requires plane type or plane_id")

        mirrors = comp.features.mirrorFeatures
        mirror_input = mirrors.createInput(entities, plane_obj)

        # MirrorFeatureInput has no 'operation' property. Only isCombine (bool)
        # controls whether mirrored bodies are Boolean-unioned with originals.
        if operation == "new_body":
            mirror_input.isCombine = False
        elif operation == "join":
            mirror_input.isCombine = True
        elif operation in ("cut", "intersect"):
            # Mirror API does not natively support cut/intersect. Use combine
            # (isCombine=True) as the closest approximation; post-processing
            # with CombineFeature can achieve cut/intersect if needed later.
            mirror_input.isCombine = True
        else:
            raise RuntimeError(f"Unsupported mirror operation: {operation}")

        feature = mirrors.add(mirror_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "mirror")
        self._cache_feature(feature_id, feature)
        new_body_ids: list[str] = []
        if not mirror_input.isCombine:
            new_body_ids = self._register_bodies(component_id, feature.bodies)
        return self._ret_feature(feature_id=feature_id, body_ids=new_body_ids)

    def MIRROR_FEATURES(
        self,
        component_id: str,
        feature_ids: list[str],
        mirror_plane: dict,
        is_combine: bool = False,
        name: str | None = None,
    ) -> dict:
        """浣跨敤 MirrorFeatures 闀滃儚鐗瑰緛"""
        # validate inputs & ids
        if not feature_ids:
            raise RuntimeError("MIRROR_FEATURES requires non-empty feature_ids")

        comp = self._require_component(component_id)
        mirror_features = comp.features.mirrorFeatures

        entities = adsk.core.ObjectCollection.create()
        for feature_id in feature_ids:
            feature = self._require_feature(feature_id)
            if not feature or not feature.isValid:
                raise RuntimeError(f"Feature not found or invalid: {feature_id}")
            entities.add(feature)

        if not isinstance(mirror_plane, dict):
            raise RuntimeError("MIRROR_FEATURES requires mirror_plane to be a dict")

        plane_obj = None
        plane_type = mirror_plane.get("type")
        if plane_type == "plane":
            plane_id = mirror_plane.get("plane_id")
            plane_obj = self._require_plane(plane_id)
            if not plane_obj or not plane_obj.isValid:
                raise RuntimeError(f"ConstructionPlane not found or invalid: {plane_id}")
        elif plane_type == "face":
            face_id = mirror_plane.get("face_id")
            face = self._require_face(face_id)
            if not face or not face.isValid:
                raise RuntimeError(f"Face not found or invalid: {face_id}")
            if not self._is_planar_face(face):
                raise RuntimeError(f"Face is not planar: {face_id}")
            plane_obj = face
        elif plane_type == "base":
            which = mirror_plane.get("which")
            if which == "XY":
                plane_obj = comp.xYConstructionPlane
            elif which == "XZ":
                plane_obj = comp.xZConstructionPlane
            elif which == "YZ":
                plane_obj = comp.yZConstructionPlane
            else:
                raise RuntimeError("MIRROR_FEATURES requires base which=XY|XZ|YZ")
        else:
            raise RuntimeError("MIRROR_FEATURES requires mirror_plane type plane|face|base")

        mirror_input = mirror_features.createInput(entities, plane_obj)
        mirror_input.isCombine = bool(is_combine)

        feature = mirror_features.add(mirror_input)
        if name:
            feature.name = name

        mirror_id = self._next_feature_id(component_id, "mirror_features")
        self._cache_feature(mirror_id, feature)
        return self._ret_feature(feature_id=mirror_id, extra={"mirror_feature_id": mirror_id})

    def CIRCULAR_PATTERN_BODIES(
        self,
        component_id: str,
        body_ids: list[str],
        axis,
        quantity: int,
        total_angle_rad: float | None = None,
        name: str | None = None,
    ) -> dict:
        """浣跨敤 CircularPatternFeatures 鐢熸垚鍦嗗懆闃靛垪"""
        # validate inputs & ids
        import math

        comp = self._require_component(component_id)
        entities = adsk.core.ObjectCollection.create()
        for body_id in body_ids:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            entities.add(body)

        # Handle dict axis input - resolve from caches
        axis_obj = None
        if isinstance(axis, dict):
            axis_id = axis.get("axis_id")
            edge_id = axis.get("edge_id")
            face_id = axis.get("face_id")
            axis_type = axis.get("type")
            if axis_id:
                axis_obj = self._require_axis(axis_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Axis not found or invalid: {axis_id}")
            elif edge_id:
                axis_obj = self._require_edge(edge_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Edge not found or invalid: {edge_id}")
            elif face_id:
                axis_obj = self._require_face(face_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
            elif isinstance(axis_type, str) and axis_type.strip():
                axis_key = axis_type.strip().upper()
                if axis_key == "X":
                    axis_obj = getattr(comp, "xConstructionAxis", None)
                elif axis_key == "Y":
                    axis_obj = getattr(comp, "yConstructionAxis", None)
                elif axis_key == "Z":
                    axis_obj = getattr(comp, "zConstructionAxis", None)
                else:
                    raise RuntimeError(f"Unsupported revolve axis type: {axis_type}")
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Component construction axis not found or invalid: {axis_type}")
            else:
                raise RuntimeError("Dict axis requires axis_id, edge_id, face_id, or type")
        else:
            axis_obj = axis

        # Relax axis validation - accept multiple types that Fusion API supports
        if not isinstance(axis_obj, (
            adsk.fusion.ConstructionAxis,
            adsk.fusion.SketchLine,
            adsk.fusion.BRepEdge,
            adsk.fusion.BRepFace
        )):
            raise RuntimeError("Axis must be ConstructionAxis, SketchLine, BRepEdge, or BRepFace")

        if not isinstance(quantity, int) or quantity <= 1:
            raise RuntimeError("CIRCULAR_PATTERN_BODIES requires quantity > 1")

        patterns = comp.features.circularPatternFeatures
        pattern_input = patterns.createInput(entities, axis_obj)
        pattern_input.quantity = adsk.core.ValueInput.createByString(str(quantity))
        if total_angle_rad is None:
            pattern_input.isSymmetric = False
            pattern_input.totalAngle = adsk.core.ValueInput.createByReal(2 * math.pi)
        else:
            if float(total_angle_rad) <= 0:
                raise RuntimeError("CIRCULAR_PATTERN_BODIES requires total_angle_rad > 0")
            pattern_input.totalAngle = adsk.core.ValueInput.createByReal(float(total_angle_rad))

        feature = patterns.add(pattern_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "cpattern")
        self._cache_feature(feature_id, feature)
        body_ids = self._register_bodies(component_id, feature.bodies)
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def RECTANGULAR_PATTERN_BODIES(
        self,
        component_id: str,
        body_ids: list[str],
        direction_one: dict,
        quantity_one: int,
        distance_one_mm: float,
        direction_two: dict | None = None,
        quantity_two: int = 1,
        distance_two_mm: float = 0.0,
        pattern_distance_type: str = "spacing",
        name: str | None = None,
    ) -> dict:
        """浣跨敤 RectangularPatternFeatures 鐢熸垚鐭╁舰闃靛垪"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        entities = adsk.core.ObjectCollection.create()
        for body_id in body_ids:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            entities.add(body)

        if not isinstance(direction_one, dict):
            raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires direction_one to be a dict")

        if not isinstance(quantity_one, int) or quantity_one <= 1:
            raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires quantity_one > 1")

        axis_key = direction_one.get("axis")
        axis_id = direction_one.get("axis_id")
        if axis_key == "X":
            dir1 = comp.xConstructionAxis
        elif axis_key == "Y":
            dir1 = comp.yConstructionAxis
        elif axis_key == "Z":
            dir1 = comp.zConstructionAxis
        elif axis_id:
            dir1 = self._require_axis(axis_id)
            if not dir1 or not dir1.isValid:
                raise RuntimeError(f"ConstructionAxis not found or invalid: {axis_id}")
        else:
            raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires axis or axis_id for direction_one")

        dir2 = None
        if direction_two is not None:
            if not isinstance(direction_two, dict):
                raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires direction_two to be a dict")
            if not isinstance(quantity_two, int) or quantity_two <= 1:
                raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires quantity_two > 1")
            axis_key_two = direction_two.get("axis")
            axis_id_two = direction_two.get("axis_id")
            if axis_key_two == "X":
                dir2 = comp.xConstructionAxis
            elif axis_key_two == "Y":
                dir2 = comp.yConstructionAxis
            elif axis_key_two == "Z":
                dir2 = comp.zConstructionAxis
            elif axis_id_two:
                dir2 = self._require_axis(axis_id_two)
                if not dir2 or not dir2.isValid:
                    raise RuntimeError(f"ConstructionAxis not found or invalid: {axis_id_two}")
            else:
                raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires axis or axis_id for direction_two")

        patterns = comp.features.rectangularPatternFeatures
        q1 = adsk.core.ValueInput.createByString(str(int(quantity_one)))
        d1 = self.mm(distance_one_mm)
        if pattern_distance_type == "spacing":
            pdt = adsk.fusion.PatternDistanceType.SpacingPatternDistanceType
        elif pattern_distance_type == "extent":
            pdt = adsk.fusion.PatternDistanceType.ExtentPatternDistanceType
        else:
            raise RuntimeError("RECTANGULAR_PATTERN_BODIES requires pattern_distance_type spacing|extent")
        pattern_input = patterns.createInput(entities, dir1, q1, d1, pdt)

        if dir2 is not None:
            pattern_input.directionTwoEntity = dir2
            pattern_input.quantityTwo = adsk.core.ValueInput.createByString(str(int(quantity_two)))
            pattern_input.distanceTwo = self.mm(distance_two_mm)

        feature = patterns.add(pattern_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "rpattern")
        self._cache_feature(feature_id, feature)
        body_ids = self._register_bodies(component_id, feature.bodies)
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def RECTANGULAR_PATTERN_FEATURES(
        self,
        component_id: str,
        feature_ids: list[str],
        direction_one: dict,
        quantity_one: int,
        distance_one_mm: float,
        pattern_distance_type: str = "spacing",
        direction_two: dict | None = None,
        quantity_two: int | None = None,
        distance_two_mm: float | None = None,
    ) -> dict:
        """浣跨敤 RectangularPatternFeatures 鐢熸垚鐗瑰緛闃靛垪"""
        # validate inputs & ids
        if not feature_ids:
            raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires non-empty feature_ids")

        comp = self._require_component(component_id)
        patterns = comp.features.rectangularPatternFeatures

        entities = adsk.core.ObjectCollection.create()
        for feat_id in feature_ids:
            feature = self._require_feature(feat_id)
            if not feature or not feature.isValid:
                raise RuntimeError(f"Feature not found or invalid: {feat_id}")
            entities.add(feature)

        if not isinstance(direction_one, dict):
            raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires direction_one to be a dict")
        if not isinstance(quantity_one, int) or quantity_one <= 1:
            raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires quantity_one > 1")

        def _resolve_direction(direction: dict):
            d_type = direction.get("type")
            if d_type == "edge":
                edge_id = direction.get("edge_id")
                edge = self._require_edge(edge_id)
                if not edge or not edge.isValid:
                    raise RuntimeError(f"Edge not found or invalid: {edge_id}")
                return edge
            if d_type == "axis":
                axis_id = direction.get("axis_id")
                axis = self._require_axis(axis_id)
                if not axis or not axis.isValid:
                    raise RuntimeError(f"ConstructionAxis not found or invalid: {axis_id}")
                return axis
            if d_type == "sketch_line":
                curve_id = direction.get("curve_id")
                curve = self._require_curve(curve_id)
                if not curve or not curve.isValid:
                    raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
                if not isinstance(curve, adsk.fusion.SketchLine):
                    raise RuntimeError(f"Curve is not SketchLine: {curve_id}")
                return curve
            raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires direction type edge|axis|sketch_line")

        dir1 = _resolve_direction(direction_one)
        q1 = adsk.core.ValueInput.createByString(str(int(quantity_one)))
        d1 = self.mm(distance_one_mm)

        if pattern_distance_type == "spacing":
            pdt = adsk.fusion.PatternDistanceType.SpacingPatternDistanceType
        elif pattern_distance_type == "extent":
            pdt = adsk.fusion.PatternDistanceType.ExtentPatternDistanceType
        else:
            raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires pattern_distance_type spacing|extent")

        pattern_input = patterns.createInput(entities, dir1, q1, d1, pdt)

        if direction_two is not None:
            if quantity_two is None or distance_two_mm is None:
                raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires quantity_two and distance_two_mm")
            if not isinstance(quantity_two, int) or quantity_two <= 1:
                raise RuntimeError("RECTANGULAR_PATTERN_FEATURES requires quantity_two > 1")
            dir2 = _resolve_direction(direction_two)
            pattern_input.directionTwoEntity = dir2
            pattern_input.quantityTwo = adsk.core.ValueInput.createByString(str(int(quantity_two)))
            pattern_input.distanceTwo = self.mm(distance_two_mm)

        feature = patterns.add(pattern_input)
        pattern_id = self._next_feature_id(component_id, "rect_pattern_features")
        self._cache_feature(pattern_id, feature)
        return self._ret_feature(feature_id=pattern_id, extra={"pattern_feature_id": pattern_id})

    def CIRCULAR_PATTERN_FEATURES(
        self,
        component_id: str,
        feature_ids: list[str],
        axis: dict,
        quantity: int,
        total_angle_rad: float | None = None,
        is_symmetric: bool = False,
    ) -> dict:
        """浣跨敤 CircularPatternFeatures 鐢熸垚鐗瑰緛闃靛垪"""
        # validate inputs & ids
        if not feature_ids:
            raise RuntimeError("CIRCULAR_PATTERN_FEATURES requires non-empty feature_ids")

        comp = self._require_component(component_id)
        patterns = comp.features.circularPatternFeatures

        def _normalize_for_component_context(entity_obj):
            if entity_obj is None or not getattr(entity_obj, "isValid", False):
                return None

            try:
                comp_occ = getattr(comp, "assemblyContext", None)
            except Exception:
                comp_occ = None

            try:
                ent_occ = getattr(entity_obj, "assemblyContext", None)
            except Exception:
                ent_occ = None

            try:
                ent_native = getattr(entity_obj, "nativeObject", None)
            except Exception:
                ent_native = None

            if comp_occ is None:
                if ent_occ is not None and ent_native is not None and getattr(ent_native, "isValid", False):
                    return ent_native
                return entity_obj

            if ent_occ == comp_occ:
                return entity_obj

            if ent_native is not None and getattr(ent_native, "isValid", False) and hasattr(ent_native, "createForAssemblyContext"):
                try:
                    prox = ent_native.createForAssemblyContext(comp_occ)
                    if prox is not None and getattr(prox, "isValid", False):
                        return prox
                except Exception:
                    pass

            if ent_occ is None and hasattr(entity_obj, "createForAssemblyContext"):
                try:
                    prox = entity_obj.createForAssemblyContext(comp_occ)
                    if prox is not None and getattr(prox, "isValid", False):
                        return prox
                except Exception:
                    pass

            return entity_obj

        entities = adsk.core.ObjectCollection.create()
        for feat_id in feature_ids:
            feature = self._require_feature(feat_id)
            if not feature or not feature.isValid:
                raise RuntimeError(f"Feature not found or invalid: {feat_id}")
            feature_ctx = _normalize_for_component_context(feature)
            if feature_ctx is None or not getattr(feature_ctx, "isValid", False):
                raise RuntimeError(f"Feature context invalid for circular pattern: {feat_id}")
            entities.add(feature_ctx)

        if not isinstance(axis, dict):
            raise RuntimeError("CIRCULAR_PATTERN_FEATURES requires axis as dict")

        axis_entity = None
        face_entity = None
        axis_id = axis.get("axis_id")
        edge_id = axis.get("edge_id")
        face_id = axis.get("face_id")
        if axis_id:
            axis_entity = self._require_axis(axis_id)
            if not axis_entity or not axis_entity.isValid:
                raise RuntimeError(f"Axis not found or invalid: {axis_id}")
            axis_entity = _normalize_for_component_context(axis_entity)
        elif edge_id:
            axis_entity = self._require_edge(edge_id)
            if not axis_entity or not axis_entity.isValid:
                raise RuntimeError(f"Edge not found or invalid: {edge_id}")
            axis_entity = _normalize_for_component_context(axis_entity)
        elif face_id:
            face_entity = self._require_face(face_id)
            if not face_entity or not face_entity.isValid:
                raise RuntimeError(f"Face not found or invalid: {face_id}")
            face_entity = _normalize_for_component_context(face_entity)
            axis_hint = axis.get("axis_hint") if isinstance(axis.get("axis_hint"), str) else None
            axis_key = str(axis_hint or "Z").strip().upper()
            if axis_key == "X":
                axis_entity = getattr(comp, "xConstructionAxis", None)
            elif axis_key == "Y":
                axis_entity = getattr(comp, "yConstructionAxis", None)
            else:
                axis_entity = getattr(comp, "zConstructionAxis", None)
            axis_entity = _normalize_for_component_context(axis_entity)

            if not axis_entity or not axis_entity.isValid:
                raise RuntimeError(
                    f"CIRCULAR_PATTERN_FEATURES cannot resolve component construction axis for face_id={face_id}, axis_hint={axis_hint}"
                )
        else:
            raise RuntimeError("CIRCULAR_PATTERN_FEATURES requires axis_id, edge_id, or face_id")

        axis_candidates: list[tuple[Any, str]] = []
        seen_axis: set[str | int] = set()

        def _push_axis(candidate, tag: str):
            if candidate is None or not getattr(candidate, "isValid", False):
                return
            key = getattr(candidate, "entityToken", None)
            if not isinstance(key, str) or not key:
                key = id(candidate)
            if key in seen_axis:
                return
            seen_axis.add(key)
            axis_candidates.append((candidate, tag))

        _push_axis(axis_entity, "resolved_axis")

        if not axis_candidates:
            raise RuntimeError("CIRCULAR_PATTERN_FEATURES has no valid axis candidates")

        last_exc: Exception | None = None
        attempt_errors: list[str] = []
        feature = None
        used_axis_tag = "resolved_axis"

        for axis_try, axis_tag in axis_candidates:
            try:
                pattern_input = patterns.createInput(entities, axis_try)
                pattern_input.quantity = adsk.core.ValueInput.createByString(str(int(quantity)))
                if total_angle_rad is None:
                    pattern_input.totalAngle = adsk.core.ValueInput.createByReal(2 * math.pi)
                else:
                    pattern_input.totalAngle = adsk.core.ValueInput.createByReal(float(total_angle_rad))
                pattern_input.isSymmetric = bool(is_symmetric)

                feature = patterns.add(pattern_input)
                used_axis_tag = axis_tag
                break
            except Exception as e:
                last_exc = e
                attempt_errors.append(f"{axis_tag}: {type(e).__name__}: {e}")

        if feature is None:
            raise RuntimeError(
                "CIRCULAR_PATTERN_FEATURES failed for all axis candidates; "
                f"errors={attempt_errors}; last_error={type(last_exc).__name__ if last_exc else 'None'}: {last_exc}"
            )

        pattern_id = self._next_feature_id(component_id, "circ_pattern_features")
        self._cache_feature(pattern_id, feature)
        extra = {"pattern_feature_id": pattern_id}
        if used_axis_tag != "resolved_axis":
            extra["warning"] = f"CIRCULAR_PATTERN_FEATURES auto-adjusted axis via {used_axis_tag}"
        return self._ret_feature(feature_id=pattern_id, extra=extra)

    def OFFSET_FACES(self, component_id: str, face_ids: list[str], offset_mm: float, name: str | None = None) -> dict:
        """鍋忕Щ鎸囧畾闈?"""
        # validate inputs & ids
        if not face_ids:
            raise RuntimeError("OFFSET_FACES requires at least one face_id")

        comp = self._require_component(component_id)
        faces = []
        for fid in face_ids:
            face = self.GET_FACE_BY_ID(fid)
            faces.append(face)

        faces_collection = adsk.core.ObjectCollection.create()
        for f in faces:
            faces_collection.add(f)

        offset_faces = comp.features.offsetFacesFeatures
        inp = offset_faces.createInput(faces_collection, self.mm(offset_mm))
        feature = offset_faces.add(inp)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "offset_faces")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def THICKEN_SURFACES(self, component_id: str, face_ids: list[str], thickness_mm: float,
                        is_symmetric: bool = False, operation: str = "new_body", name: str | None = None) -> dict:
        """鍔犲帤鏇查潰鍒涘缓瀹炰綋"""
        # validate inputs & ids
        if not face_ids:
            raise RuntimeError("THICKEN_SURFACES requires at least one face_id")
        if thickness_mm <= 0:
            raise RuntimeError(f"THICKEN_SURFACES requires thickness_mm > 0, got {thickness_mm}")

        comp = self._require_component(component_id)
        faces = adsk.core.ObjectCollection.create()
        for fid in face_ids:
            face = self.GET_FACE_BY_ID(fid)
            faces.add(face)

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported thicken operation: {operation}")

        thicken_feats = comp.features.thickenFeatures
        inp = thicken_feats.createInput(faces, self.mm(thickness_mm), False, mapped_op, False)
        if hasattr(inp, "isSymmetric"):
            inp.isSymmetric = bool(is_symmetric)
        feature = thicken_feats.add(inp)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "thicken")
        self._cache_feature(feature_id, feature)

        body_ids = []
        if operation == "new_body" and feature.bodies.count > 0:
            for i in range(feature.bodies.count):
                body = feature.bodies.item(i)
                bid = self._next_body_id(component_id)
                self._cache_body(bid, body)
                body_ids.append(bid)

        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def OFFSET_FEATURE(self, component_id: str, face_ids: list[str], offset_mm: float,
                      operation: str = "new_body", name: str | None = None) -> dict:
        """鍋忕Щ鐗瑰緛"""
        # validate inputs & ids
        if not face_ids:
            raise RuntimeError("OFFSET_FEATURE requires at least one face_id")

        comp = self._require_component(component_id)
        entities = adsk.core.ObjectCollection.create()
        for fid in face_ids:
            face = self.GET_FACE_BY_ID(fid)
            entities.add(face)

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported offset operation: {operation}")

        offset_feats = comp.features.offsetFacesFeatures
        inp = offset_feats.createInput(entities, self.mm(offset_mm))
        feature = offset_feats.add(inp)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "offset")
        self._cache_feature(feature_id, feature)

        body_ids = []
        if operation == "new_body" and feature.bodies.count > 0:
            for i in range(feature.bodies.count):
                body = feature.bodies.item(i)
                bid = self._next_body_id(component_id)
                self._cache_body(bid, body)
                body_ids.append(bid)

        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def CREATE_CONSTRUCTION_POINT(self, component_id: str, name: str, point_mm: dict) -> dict:
        """鍒涘缓鏋勯€犵偣锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)

        if self.design.designType != adsk.fusion.DesignTypes.DirectDesignType:
            raise RuntimeError(
                "CREATE_CONSTRUCTION_POINT only supports DirectDesignType; "
                "use reference-based points in ParametricDesignType"
            )

        x = float(point_mm.get("x", 0.0)) / 10.0
        y = float(point_mm.get("y", 0.0)) / 10.0
        z = float(point_mm.get("z", 0.0)) / 10.0
        point = adsk.core.Point3D.create(x, y, z)

        point_id = f"{component_id}:{name}"
        if self.strict_mode and point_id in self._points:
            raise RuntimeError(f"ConstructionPoint already exists: {point_id}")

        points = comp.constructionPoints
        point_input = points.createInput()
        point_input.setByPoint(point)
        created_point = points.add(point_input)
        created_point.name = name
        self._cache_point(point_id, created_point)
        return {"point_id": point_id}

    def CREATE_CONSTRUCTION_AXIS_BY_TWO_POINTS(
        self,
        component_id: str,
        name: str,
        point_a_id: str,
        point_b_id: str,
    ) -> dict:
        """閫氳繃涓や釜鐐瑰垱寤烘瀯閫犺酱"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        point_a = self._require_point(point_a_id)
        point_b = self._require_point(point_b_id)
        if not point_a or not point_a.isValid:
            raise RuntimeError(f"Point not found or invalid: {point_a_id}")
        if not point_b or not point_b.isValid:
            raise RuntimeError(f"Point not found or invalid: {point_b_id}")

        axis_id = f"{component_id}:{name}"
        if self.strict_mode and axis_id in self._axes:
            raise RuntimeError(f"ConstructionAxis already exists: {axis_id}")

        axes = comp.constructionAxes
        axis_input = axes.createInput()
        axis_input.setByTwoPoints(point_a, point_b)
        axis = axes.add(axis_input)
        axis.name = name
        self._cache_axis(axis_id, axis)
        return {"axis_id": axis_id}

    def CREATE_AXIS_THROUGH_TWO_POINTS(
        self,
        component_id: str,
        point_a,
        point_b,
        name: str | None = None,
    ) -> dict:
        """閫氳繃涓ょ偣鍒涘缓鏋勯€犺酱锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)

        def _resolve_point(ref):
            if isinstance(ref, dict):
                if "point_id" in ref:
                    pt_id = ref.get("point_id")
                    pt = self._require_point(pt_id)
                    if not pt or not pt.isValid:
                        raise RuntimeError(f"ConstructionPoint not found or invalid: {pt_id}")
                    return pt
                if "sketch_point_id" in ref:
                    sp_id = ref.get("sketch_point_id")
                    sp = self._require_sketch_point(sp_id)
                    if not sp or not sp.isValid:
                        raise RuntimeError(f"SketchPoint not found or invalid: {sp_id}")
                    pt3d = sp.geometry
                else:
                    pt3d = self.cm_point(ref.get("x", 0), ref.get("y", 0), ref.get("z", 0))
            elif isinstance(ref, str):
                pt = self._require_point(ref)
                if pt and pt.isValid:
                    return pt
                sp = self._require_sketch_point(ref)
                if sp and sp.isValid:
                    pt3d = sp.geometry
                else:
                    raise RuntimeError(f"Point not found or invalid: {ref}")
            else:
                raise RuntimeError("CREATE_AXIS_THROUGH_TWO_POINTS requires dict or point_id")

            points = comp.constructionPoints
            point_input = points.createInput()
            point_input.setByPoint(pt3d)
            created_point = points.add(point_input)
            point_id = f"{component_id}:point:{len(self._points) + 1}"
            self._cache_point(point_id, created_point)
            return created_point

        point_a_obj = _resolve_point(point_a)
        point_b_obj = _resolve_point(point_b)

        axes = comp.constructionAxes
        axis_input = axes.createInput()
        axis_input.setByTwoPoints(point_a_obj, point_b_obj)
        axis = axes.add(axis_input)

        axis_name = name or f"axis_{len(self._axes) + 1}"
        axis.name = axis_name
        axis_id = f"{component_id}:{axis_name}"
        if not axis or not axis.isValid:
            raise RuntimeError("CREATE_AXIS_THROUGH_TWO_POINTS failed to create axis")

        self._cache_axis(axis_id, axis)
        return {"axis_id": axis_id}

    def CREATE_CONSTRUCTION_AXIS_BY_EDGE(
        self,
        component_id: str,
        name: str,
        edge_id: str,
    ) -> dict:
        """閫氳繃杈瑰垱寤烘瀯閫犺酱"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        edge = self.GET_EDGE_BY_ID(edge_id)

        axis_id = f"{component_id}:{name}"
        if self.strict_mode and axis_id in self._axes:
            raise RuntimeError(f"ConstructionAxis already exists: {axis_id}")

        axes = comp.constructionAxes
        axis_input = axes.createInput()
        axis_input.setByLine(edge)
        axis = axes.add(axis_input)
        axis.name = name
        self._cache_axis(axis_id, axis)
        return {"axis_id": axis_id}
    
    def SKETCH_CIRCLE(self, sketch_id: str, center: dict, radius: float, construction: bool = False):
        """鍦?sketch 涓敾鍦?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")
        
        before_count = sketch.profiles.count
        
        center_pt = self.cm_point(
            center.get("x", 0),
            center.get("y", 0),
            center.get("z", 0),
        )
        radius_cm = float(radius) / 10.0  # mm 鈫?cm
        circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center_pt, radius_cm)
        circle.isConstruction = construction

        if construction:
            # 鏋勯€犲渾锛氬瓨鍌ㄥ湪 _curves锛屼笉妫€鏌?profile 鍙樺寲
            curve_id = self._next_curve_id(sketch_id, "circle")
            self._curves[curve_id] = circle
            return self._ret_sketch(curve_id=curve_id)
        else:
            # 闈炴瀯閫犲渾锛氭鏌?profile 鍙樺寲骞跺瓨鍌?
            after_count = sketch.profiles.count
            delta = after_count - before_count
            if delta != 1:
                raise RuntimeError(
                    f"SKETCH_CIRCLE profile count mismatch for {sketch_id}: "
                    f"before={before_count}, after={after_count}"
                )
            profile = sketch.profiles.item(before_count)
            
            profile_id = self._next_profile_id(sketch_id)
            self._cache_profile(profile_id, profile)
            return self._ret_sketch(profile_id=profile_id)

    def SKETCH_LINE(self, sketch_id: str, start: dict, end: dict, construction: bool = False) -> dict:
        """鍦?sketch 涓敾绾挎"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        p1 = self.cm_point(start.get("x", 0), start.get("y", 0), start.get("z", 0))
        p2 = self.cm_point(end.get("x", 0), end.get("y", 0), end.get("z", 0))
        line = sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
        line.isConstruction = construction

        curve_id = self._next_curve_id(sketch_id, "line")
        self._curves[curve_id] = line
        return self._ret_sketch(curve_id=curve_id)

    def SKETCH_POLYLINE(
        self,
        sketch_id: str,
        points: list[dict],
        closed: bool = False,
        construction: bool = False,
    ) -> dict:
        """??sketch ??????"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")
        if not points or len(points) < 2:
            raise RuntimeError("SKETCH_POLYLINE requires at least two points")

        before_count = 0
        if closed and not construction:
            try:
                before_count = int(sketch.profiles.count)
            except Exception:
                before_count = 0

        curve_ids = []
        sketch.isComputeDeferred = True
        try:
            pts = [self.cm_point(p.get("x", 0), p.get("y", 0), p.get("z", 0)) for p in points]

            for i in range(len(pts) - 1):
                line = sketch.sketchCurves.sketchLines.addByTwoPoints(pts[i], pts[i + 1])
                line.isConstruction = construction
                curve_id = self._next_curve_id(sketch_id, "line")
                self._curves[curve_id] = line
                curve_ids.append(curve_id)

            if closed:
                line = sketch.sketchCurves.sketchLines.addByTwoPoints(pts[-1], pts[0])
                line.isConstruction = construction
                curve_id = self._next_curve_id(sketch_id, "line")
                self._curves[curve_id] = line
                curve_ids.append(curve_id)
        finally:
            sketch.isComputeDeferred = False

        if not closed or construction:
            return self._ret_sketch(curve_ids=curve_ids)

        try:
            after_count = int(sketch.profiles.count)
        except Exception:
            after_count = before_count
        delta = after_count - before_count
        if delta <= 0:
            raise RuntimeError(
                f"SKETCH_POLYLINE profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )

        profile_ids = []
        for idx in range(before_count, after_count):
            profile = sketch.profiles.item(idx)
            profile_id = self._next_profile_id(sketch_id)
            self._cache_profile(profile_id, profile)
            profile_ids.append(profile_id)

        return self._ret_sketch(
            curve_ids=curve_ids,
            profile_id=profile_ids[0],
            profile_ids=profile_ids,
        )

    def SKETCH_ARC_3PT(
        self,
        sketch_id: str,
        start: dict,
        point_on_arc: dict,
        end: dict,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓敾涓夌偣鍦嗗姬"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        p1 = self.cm_point(start.get("x", 0), start.get("y", 0), start.get("z", 0))
        p2 = self.cm_point(
            point_on_arc.get("x", 0),
            point_on_arc.get("y", 0),
            point_on_arc.get("z", 0),
        )
        p3 = self.cm_point(end.get("x", 0), end.get("y", 0), end.get("z", 0))
        arc = sketch.sketchCurves.sketchArcs.addByThreePoints(p1, p2, p3)
        arc.isConstruction = construction

        curve_id = self._next_curve_id(sketch_id, "arc")
        self._curves[curve_id] = arc
        return self._ret_sketch(curve_id=curve_id)

    def SKETCH_CIRCLE_3PT(
        self,
        sketch_id: str,
        p1: dict,
        p2: dict,
        p3: dict,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓敾涓夌偣鍦?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        before_count = sketch.profiles.count

        pt1 = self.cm_point(p1.get("x", 0), p1.get("y", 0), p1.get("z", 0))
        pt2 = self.cm_point(p2.get("x", 0), p2.get("y", 0), p2.get("z", 0))
        pt3 = self.cm_point(p3.get("x", 0), p3.get("y", 0), p3.get("z", 0))
        circle = sketch.sketchCurves.sketchCircles.addByThreePoints(pt1, pt2, pt3)
        circle.isConstruction = construction

        if construction:
            curve_id = self._next_curve_id(sketch_id, "circle")
            self._curves[curve_id] = circle
            return self._ret_sketch(curve_id=curve_id)

        after_count = sketch.profiles.count
        delta = after_count - before_count
        if delta != 1:
            raise RuntimeError(
                f"SKETCH_CIRCLE_3PT profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )
        profile = sketch.profiles.item(before_count)

        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)

    def SKETCH_REGULAR_POLYGON(
        self,
        sketch_id: str,
        center: dict,
        radius: float,
        sides: int,
        start_angle_rad: float = 0.0,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓敾姝ｅ杈瑰舰"""
        # validate inputs & ids
        import math

        if sides < 3:
            raise RuntimeError("SKETCH_REGULAR_POLYGON requires sides >= 3")

        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        before_count = sketch.profiles.count

        center_pt = self.cm_point(center.get("x", 0), center.get("y", 0), center.get("z", 0))
        radius_cm = float(radius) / 10.0
        vertices = []
        for i in range(sides):
            theta = float(start_angle_rad) + (2 * math.pi * i / sides)
            x = center_pt.x + radius_cm * math.cos(theta)
            y = center_pt.y + radius_cm * math.sin(theta)
            vertices.append(adsk.core.Point3D.create(x, y, center_pt.z))

        curve_ids = []
        for i in range(sides):
            p1 = vertices[i]
            p2 = vertices[(i + 1) % sides]
            line = sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
            line.isConstruction = construction
            if construction:
                curve_id = self._next_curve_id(sketch_id, "line")
                self._curves[curve_id] = line
                curve_ids.append(curve_id)

        if construction:
            return self._ret_sketch(curve_ids=curve_ids)

        after_count = sketch.profiles.count
        delta = after_count - before_count
        if delta != 1:
            raise RuntimeError(
                f"SKETCH_REGULAR_POLYGON profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )
        profile = sketch.profiles.item(before_count)

        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)

    def SKETCH_POINT(self, sketch_id: str, point: dict, construction: bool = True) -> dict:
        """鍦?sketch 涓垱寤虹偣"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        point3d = self.cm_point(
            point.get("x", 0),
            point.get("y", 0),
            point.get("z", 0),
        )
        sketch_point = sketch.sketchPoints.add(point3d)
        sketch_point.isFixed = False

        counter = self._sketch_point_counter.get(sketch_id, 0) + 1
        self._sketch_point_counter[sketch_id] = counter
        point_id = f"{sketch_id}:sketch_point:{counter}"
        self._sketch_points[point_id] = sketch_point
        return {"point_id": point_id}

    def ADD_SKETCH_CONSTRAINT_COINCIDENT(
        self,
        sketch_id: str,
        point_id: str,
        target: dict,
    ) -> dict:
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch or not sketch.isValid:
            raise RuntimeError(f"Sketch {sketch_id} not found or invalid")

        point = self._require_sketch_point(point_id)
        if not point or not point.isValid:
            raise RuntimeError(f"SketchPoint not found or invalid: {point_id}")

        constraints = sketch.geometricConstraints
        target_type = target.get("type")
        if target_type == "point":
            target_id = target.get("point_id")
            other = self._require_sketch_point(target_id)
            if not other or not other.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {target_id}")
            constraint = constraints.addCoincident(point, other)
        elif target_type == "curve":
            target_id = target.get("curve_id")
            curve = self._require_curve(target_id)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {target_id}")
            constraint = constraints.addCoincident(point, curve)
        else:
            raise RuntimeError("ADD_SKETCH_CONSTRAINT_COINCIDENT requires target type point or curve")

        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def ADD_SKETCH_CONSTRAINT_HORIZONTAL(self, sketch_id: str, curve_id: str) -> dict:
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch or not sketch.isValid:
            raise RuntimeError(f"Sketch {sketch_id} not found or invalid")

        curve = self._require_curve(curve_id)
        if not curve or not curve.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")

        constraint = sketch.geometricConstraints.addHorizontal(curve)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def ADD_SKETCH_CONSTRAINT_VERTICAL(self, sketch_id: str, curve_id: str) -> dict:
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch or not sketch.isValid:
            raise RuntimeError(f"Sketch {sketch_id} not found or invalid")

        curve = self._require_curve(curve_id)
        if not curve or not curve.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")

        constraint = sketch.geometricConstraints.addVertical(curve)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def ADD_SKETCH_CONSTRAINT_EQUAL(self, sketch_id: str, curve_id_a: str, curve_id_b: str) -> dict:
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch or not sketch.isValid:
            raise RuntimeError(f"Sketch {sketch_id} not found or invalid")

        curve_a = self._require_curve(curve_id_a)
        curve_b = self._require_curve(curve_id_b)
        if not curve_a or not curve_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_a}")
        if not curve_b or not curve_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_b}")

        constraint = sketch.geometricConstraints.addEqual(curve_a, curve_b)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def ADD_SKETCH_CONSTRAINT_CONCENTRIC(self, sketch_id: str, curve_id_a: str, curve_id_b: str) -> dict:
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch or not sketch.isValid:
            raise RuntimeError(f"Sketch {sketch_id} not found or invalid")

        curve_a = self._require_curve(curve_id_a)
        curve_b = self._require_curve(curve_id_b)
        if not curve_a or not curve_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_a}")
        if not curve_b or not curve_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_b}")

        try:
            constraint = sketch.geometricConstraints.addConcentric(curve_a, curve_b)
        except Exception:
            raise RuntimeError("ADD_SKETCH_CONSTRAINT_CONCENTRIC requires circle/arc/ellipse")

        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def SKETCH_CONSTRAINT_MIDPOINT(self, point_id: str, line_id: str) -> dict:
        """Add midpoint constraint between a sketch point and a sketch line."""
        # validate inputs & ids
        point = self._require_sketch_point(point_id)
        line = self._require_curve(line_id)
        if not point or not point.isValid:
            raise RuntimeError(f"SketchPoint not found or invalid: {point_id}")
        if not line or not line.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id}")
        if not isinstance(line, adsk.fusion.SketchLine):
            raise RuntimeError("SKETCH_CONSTRAINT_MIDPOINT requires a SketchLine")

        sketch_p = getattr(point, "parentSketch", None)
        sketch_l = getattr(line, "parentSketch", None)
        if not sketch_p or not getattr(sketch_p, "isValid", False):
            raise RuntimeError("Point has no valid parent sketch")
        if not sketch_l or not getattr(sketch_l, "isValid", False):
            raise RuntimeError("Line has no valid parent sketch")
        if sketch_p != sketch_l:
            self._fail("SKETCH_CONSTRAINT_MIDPOINT requires entities in the same sketch")

        sketch_p.geometricConstraints.addMidPoint(point, line)
        return {"ok": True}

    def SKETCH_CONSTRAINT_FIX(self, entity_id: str) -> dict:
        """Fix a sketch entity (point or curve)."""
        # validate inputs & ids
        entity = None
        if entity_id in self._sketch_points:
            entity = self._require_sketch_point(entity_id)
        else:
            entity = self._require_curve(entity_id)

        if not entity or not entity.isValid:
            raise RuntimeError(f"Sketch entity not found or invalid: {entity_id}")

        sketch = getattr(entity, "parentSketch", None)
        if not sketch or not getattr(sketch, "isValid", False):
            raise RuntimeError("Entity has no valid parent sketch")

        sketch.geometricConstraints.addFix(entity)
        return {"ok": True}

    def SKETCH_CONSTRAINT_COLLINEAR(self, line_id_a: str, line_id_b: str) -> dict:
        """Add collinear constraint between two sketch lines."""
        # validate inputs & ids
        line_a = self._require_curve(line_id_a)
        line_b = self._require_curve(line_id_b)
        if not line_a or not line_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_a}")
        if not line_b or not line_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_b}")
        if not isinstance(line_a, adsk.fusion.SketchLine) or not isinstance(line_b, adsk.fusion.SketchLine):
            raise RuntimeError("SKETCH_CONSTRAINT_COLLINEAR requires SketchLine inputs")

        sketch_a = getattr(line_a, "parentSketch", None)
        sketch_b = getattr(line_b, "parentSketch", None)
        if not sketch_a or not getattr(sketch_a, "isValid", False):
            raise RuntimeError("Line A has no valid parent sketch")
        if not sketch_b or not getattr(sketch_b, "isValid", False):
            raise RuntimeError("Line B has no valid parent sketch")
        if sketch_a != sketch_b:
            self._fail("SKETCH_CONSTRAINT_COLLINEAR requires entities in the same sketch")

        sketch_a.geometricConstraints.addCollinear(line_a, line_b)
        return {"ok": True}

    def SKETCH_CONSTRAINT_TANGENT(self, curve_id_a: str, curve_id_b: str) -> dict:
        """Add tangent constraint between two sketch curves."""
        # validate inputs & ids
        curve_a = self._require_curve(curve_id_a)
        curve_b = self._require_curve(curve_id_b)
        if not curve_a or not curve_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_a}")
        if not curve_b or not curve_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_b}")

        sketch_a = getattr(curve_a, "parentSketch", None)
        sketch_b = getattr(curve_b, "parentSketch", None)
        if not sketch_a or not getattr(sketch_a, "isValid", False):
            raise RuntimeError("Curve A has no valid parent sketch")
        if not sketch_b or not getattr(sketch_b, "isValid", False):
            raise RuntimeError("Curve B has no valid parent sketch")
        if sketch_a != sketch_b:
            self._fail("SKETCH_CONSTRAINT_TANGENT requires curves in the same sketch")

        sketch_id = self._sketch_id_by_obj.get(id(sketch_a))
        if not sketch_id:
            self._fail("Parent sketch not registered for tangent constraint")

        constraint = sketch_a.geometricConstraints.addTangent(curve_a, curve_b)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def SKETCH_CONSTRAINT_PARALLEL(self, line_id_a: str, line_id_b: str) -> dict:
        """Add parallel constraint between two sketch lines/curves."""
        # validate inputs & ids
        line_a = self._require_curve(line_id_a)
        line_b = self._require_curve(line_id_b)
        if not line_a or not line_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_a}")
        if not line_b or not line_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_b}")

        sketch_a = getattr(line_a, "parentSketch", None)
        sketch_b = getattr(line_b, "parentSketch", None)
        if not sketch_a or not getattr(sketch_a, "isValid", False):
            raise RuntimeError("Line A has no valid parent sketch")
        if not sketch_b or not getattr(sketch_b, "isValid", False):
            raise RuntimeError("Line B has no valid parent sketch")
        if sketch_a != sketch_b:
            self._fail("SKETCH_CONSTRAINT_PARALLEL requires entities in the same sketch")

        sketch_id = self._sketch_id_by_obj.get(id(sketch_a))
        if not sketch_id:
            self._fail("Parent sketch not registered for parallel constraint")

        constraint = sketch_a.geometricConstraints.addParallel(line_a, line_b)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def SKETCH_CONSTRAINT_PERPENDICULAR(self, line_id_a: str, line_id_b: str) -> dict:
        """Add perpendicular constraint between two sketch lines/curves."""
        # validate inputs & ids
        line_a = self._require_curve(line_id_a)
        line_b = self._require_curve(line_id_b)
        if not line_a or not line_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_a}")
        if not line_b or not line_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {line_id_b}")

        sketch_a = getattr(line_a, "parentSketch", None)
        sketch_b = getattr(line_b, "parentSketch", None)
        if not sketch_a or not getattr(sketch_a, "isValid", False):
            raise RuntimeError("Line A has no valid parent sketch")
        if not sketch_b or not getattr(sketch_b, "isValid", False):
            raise RuntimeError("Line B has no valid parent sketch")
        if sketch_a != sketch_b:
            self._fail("SKETCH_CONSTRAINT_PERPENDICULAR requires entities in the same sketch")

        sketch_id = self._sketch_id_by_obj.get(id(sketch_a))
        if not sketch_id:
            self._fail("Parent sketch not registered for perpendicular constraint")

        constraint = sketch_a.geometricConstraints.addPerpendicular(line_a, line_b)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def SKETCH_CONSTRAINT_SYMMETRY(
        self,
        entity_id_a: str,
        entity_id_b: str,
        symmetry_line_id: str,
    ) -> dict:
        """Add symmetry constraint between two entities about a symmetry line."""
        # validate inputs & ids
        ent_a = self._require_curve(entity_id_a)
        ent_b = self._require_curve(entity_id_b)
        sym_line = self._require_curve(symmetry_line_id)
        if not ent_a or not ent_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {entity_id_a}")
        if not ent_b or not ent_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {entity_id_b}")
        if not sym_line or not sym_line.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {symmetry_line_id}")

        sketch_a = getattr(ent_a, "parentSketch", None)
        sketch_b = getattr(ent_b, "parentSketch", None)
        sketch_s = getattr(sym_line, "parentSketch", None)
        if not sketch_a or not getattr(sketch_a, "isValid", False):
            raise RuntimeError("Entity A has no valid parent sketch")
        if not sketch_b or not getattr(sketch_b, "isValid", False):
            raise RuntimeError("Entity B has no valid parent sketch")
        if not sketch_s or not getattr(sketch_s, "isValid", False):
            raise RuntimeError("Symmetry line has no valid parent sketch")
        if sketch_a != sketch_b or sketch_a != sketch_s:
            self._fail("SKETCH_CONSTRAINT_SYMMETRY requires entities in the same sketch")

        sketch_id = self._sketch_id_by_obj.get(id(sketch_a))
        if not sketch_id:
            self._fail("Parent sketch not registered for symmetry constraint")

        constraint = sketch_a.geometricConstraints.addSymmetry(ent_a, ent_b, sym_line)
        constraint_id = self._next_constraint_id(sketch_id)
        self._constraints[constraint_id] = constraint
        return {"constraint_id": constraint_id}

    def SELECT_LARGEST_PLANAR_FACE(self, body_id: str) -> dict:
        # validate inputs & ids
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        max_face = None
        max_area = -1.0
        for i in range(body.faces.count):
            face = body.faces.item(i)
            if not face or not face.isValid:
                continue
            if not self._is_planar_face(face):
                continue
            area = self._face_area(face)
            if area > max_area:
                max_area = area
                max_face = face

        if not max_face:
            raise RuntimeError("No planar face found")

        face_id = f"{body_id}:face:planar:max"
        self._cache_face(face_id, max_face)
        return {"face_id": face_id}

    def MEASURE_MIN_DISTANCE(self, entity_a: dict, entity_b: dict) -> dict:
        """Measure minimum distance between two entities."""
        # validate inputs & ids
        meas_a = self._resolve_measurable_entity(entity_a)
        meas_b = self._resolve_measurable_entity(entity_b)

        measure_manager = self.app.activeProduct.measureManager
        result = measure_manager.measureMinimumDistance(meas_a, meas_b)
        if not result:
            raise RuntimeError("Failed to measure minimum distance")

        distance_cm = float(result.value)
        distance_mm = distance_cm * 10.0
        return {"distance_mm": distance_mm, "distance_cm": distance_cm}

    def GET_MASS_PROPERTIES(self, target: dict) -> dict:
        """Get mass properties for a body or component."""
        # validate inputs & ids
        if not isinstance(target, dict):
            raise RuntimeError("GET_MASS_PROPERTIES requires target as dict")

        props = None
        if "body_id" in target:
            body = self._require_body(target.get("body_id"))
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {target.get('body_id')}")
            props = body.physicalProperties
        elif "component_id" in target:
            comp = self._require_component(target.get("component_id"))
            if not comp or not comp.isValid:
                raise RuntimeError(f"Component not found or invalid: {target.get('component_id')}")
            props = comp.physicalProperties
        else:
            raise RuntimeError("GET_MASS_PROPERTIES requires body_id or component_id")

        if not props:
            raise RuntimeError("Failed to resolve physical properties")

        com = props.centerOfMass
        center_of_mass_mm = {
            "x": com.x * 10.0,
            "y": com.y * 10.0,
            "z": com.z * 10.0,
        }

        return {
            "mass": props.mass,
            "volume": props.volume,
            "area": props.area,
            "density": props.density,
            "center_of_mass_mm": center_of_mass_mm,
        }

    def SELECT_CYLINDRICAL_FACES(
        self,
        body_id: str,
        feature_id: str | None = None,
        feature_ids: list[str] | None = None,
        radius_mm: float | None = None,
        tol_mm: float = 0.05,
    ) -> dict:
        # validate inputs & ids
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        desired = None if radius_mm is None else self._cm_tol(radius_mm)
        tol = self._cm_tol(tol_mm)

        scoped_feature_ids: list[str] = []
        if isinstance(feature_ids, list):
            scoped_feature_ids.extend([fid for fid in feature_ids if isinstance(fid, str) and fid])
        if isinstance(feature_id, str) and feature_id:
            scoped_feature_ids.append(feature_id)

        def _entity_token(obj) -> str | None:
            if not obj or not getattr(obj, "isValid", False):
                return None
            try:
                token = getattr(obj, "entityToken", None)
                if isinstance(token, str) and token:
                    return token
            except Exception:
                return None
            return None

        def _iter_feature_face_collections(feature_obj):
            seen_collections: set[int] = set()
            explicit_attrs = ("faces", "sideFaces", "endFaces", "startFaces", "holeFaces")

            def _push_collection(value):
                if value is None:
                    return
                if not hasattr(value, "count") or not hasattr(value, "item"):
                    return
                key = id(value)
                if key in seen_collections:
                    return
                seen_collections.add(key)
                yield value

            for attr in explicit_attrs:
                try:
                    value = getattr(feature_obj, attr, None)
                except Exception:
                    value = None
                yield from _push_collection(value)

            for attr in dir(feature_obj):
                if not isinstance(attr, str) or not attr.endswith("Faces"):
                    continue
                try:
                    value = getattr(feature_obj, attr, None)
                except Exception:
                    continue
                yield from _push_collection(value)

        body_token = _entity_token(body)

        def _face_belongs_to_body(face_obj) -> bool:
            try:
                face_body = getattr(face_obj, "body", None)
                if face_body is None:
                    return False
                if face_body is body:
                    return True
                if body_token:
                    return _entity_token(face_body) == body_token
            except Exception:
                return False
            return False

        candidate_faces = None
        if scoped_feature_ids:
            candidate_faces = []
            seen_face_refs: set[str | int] = set()
            for fid in scoped_feature_ids:
                feature = self._require_feature(fid)
                for faces in _iter_feature_face_collections(feature):
                    count = getattr(faces, "count", 0)
                    for i in range(count):
                        face = faces.item(i)
                        if not face or not getattr(face, "isValid", False):
                            continue
                        if not _face_belongs_to_body(face):
                            continue
                        key = _entity_token(face) or id(face)
                        if key in seen_face_refs:
                            continue
                        seen_face_refs.add(key)
                        candidate_faces.append(face)

            if not candidate_faces:
                raise RuntimeError(
                    "No faces resolved from feature scope for SELECT_CYLINDRICAL_FACES: "
                    f"feature_ids={scoped_feature_ids}"
                )

        face_ids = []
        if candidate_faces is None:
            face_iter = [body.faces.item(i) for i in range(body.faces.count)]
        else:
            face_iter = candidate_faces

        for face in face_iter:
            if not face or not face.isValid:
                continue
            if not self._is_cylindrical_face(face):
                continue
            radius = face.geometry.radius
            if desired is not None and abs(radius - desired) > tol:
                continue
            face_id = f"{body_id}:face:cyl:{len(face_ids) + 1}"
            self._cache_face(face_id, face)
            face_ids.append(face_id)

        if radius_mm is not None and not face_ids:
            if scoped_feature_ids:
                raise RuntimeError(
                    f"No cylindrical face with radius {radius_mm} in feature scope {scoped_feature_ids}"
                )
            raise RuntimeError(f"No cylindrical face with radius {radius_mm}")

        return {"face_ids": face_ids}

    def SELECT_CYLINDRICAL_FACE(
        self,
        body_id: str,
        radius_mm: float | None = None,
        tol_mm: float = 0.05,
    ) -> dict:
        # validate inputs & ids
        result = self.SELECT_CYLINDRICAL_FACES(
            body_id=body_id,
            radius_mm=radius_mm,
            tol_mm=tol_mm,
        )
        face_ids = result.get("face_ids")
        if not isinstance(face_ids, list) or not face_ids:
            if radius_mm is not None:
                raise RuntimeError(f"No cylindrical face with radius {radius_mm}")
            raise RuntimeError("No cylindrical face found")

        face_id = face_ids[0]
        if not isinstance(face_id, str) or not face_id:
            raise RuntimeError("Invalid cylindrical face selection")
        return {"face_id": face_id}

    def _face_geometry_summary(self, face_id: str, face) -> dict:
        summary: dict = {
            "face_id": face_id,
            "area_mm2": None,
            "centroid_mm": None,
            "normal": None,
            "bbox_mm": None,
            "radius_mm": None,
            "axis_direction": None,
            "axis_origin_mm": None,
        }
        if not face or not getattr(face, "isValid", False):
            return summary

        try:
            summary["area_mm2"] = float(face.area) * 100.0
        except Exception:
            pass

        try:
            center = getattr(face, "centroid", None) or getattr(face, "pointOnFace", None)
            if center is not None:
                summary["centroid_mm"] = {
                    "x": float(center.x) * 10.0,
                    "y": float(center.y) * 10.0,
                    "z": float(center.z) * 10.0,
                }
        except Exception:
            pass

        try:
            bb = getattr(face, "boundingBox", None)
            if bb is not None:
                min_pt = getattr(bb, "minPoint", None)
                max_pt = getattr(bb, "maxPoint", None)
                if min_pt is not None and max_pt is not None:
                    summary["bbox_mm"] = {
                        "min_x": float(min_pt.x) * 10.0,
                        "max_x": float(max_pt.x) * 10.0,
                        "min_y": float(min_pt.y) * 10.0,
                        "max_y": float(max_pt.y) * 10.0,
                        "min_z": float(min_pt.z) * 10.0,
                        "max_z": float(max_pt.z) * 10.0,
                    }
        except Exception:
            pass

        try:
            geom = face.geometry

            def _safe_cast(caster, obj):
                try:
                    if caster is None or obj is None:
                        return None
                    cast_fn = getattr(caster, "cast", None)
                    if callable(cast_fn):
                        return cast_fn(obj)
                except Exception:
                    return None
                return None

            def _read_scalar(source, attr):
                try:
                    return getattr(source, attr, None)
                except Exception:
                    return None

            def _read_vector(source, attr):
                try:
                    vec = getattr(source, attr, None)
                except Exception:
                    return None
                if vec is None:
                    return None
                try:
                    return {
                        "x": float(vec.x),
                        "y": float(vec.y),
                        "z": float(vec.z),
                    }
                except Exception:
                    return None

            def _read_point_mm(source, attr):
                try:
                    pt = getattr(source, attr, None)
                except Exception:
                    return None
                if pt is None:
                    return None
                try:
                    return {
                        "x": float(pt.x) * 10.0,
                        "y": float(pt.y) * 10.0,
                        "z": float(pt.z) * 10.0,
                    }
                except Exception:
                    return None

            plane_geom = _safe_cast(getattr(adsk.core, "Plane", None), geom)
            cylinder_geom = _safe_cast(getattr(adsk.core, "Cylinder", None), geom)
            cone_geom = _safe_cast(getattr(adsk.core, "Cone", None), geom)

            normal = _read_vector(plane_geom if plane_geom is not None else geom, "normal")
            if normal is not None:
                summary["normal"] = normal
            elif summary.get("centroid_mm") is not None:
                try:
                    evaluator = getattr(face, "evaluator", None)
                    point = getattr(face, "pointOnFace", None)
                    if evaluator is not None and point is not None and hasattr(evaluator, "getNormalAtPoint"):
                        normal_result = evaluator.getNormalAtPoint(point)
                        normal_obj = None
                        if isinstance(normal_result, tuple):
                            if len(normal_result) >= 2 and isinstance(normal_result[0], bool) and normal_result[0]:
                                normal_obj = normal_result[1]
                            elif len(normal_result) >= 1:
                                normal_obj = normal_result[-1]
                        else:
                            normal_obj = normal_result
                        if normal_obj is not None:
                            summary["normal"] = {
                                "x": float(normal_obj.x),
                                "y": float(normal_obj.y),
                                "z": float(normal_obj.z),
                            }
                except Exception:
                    pass

            axis_source = cylinder_geom if cylinder_geom is not None else cone_geom if cone_geom is not None else geom
            radius_source = cylinder_geom if cylinder_geom is not None else cone_geom if cone_geom is not None else geom

            radius = _read_scalar(radius_source, "radius")
            if isinstance(radius, (int, float)):
                summary["radius_mm"] = float(radius) * 10.0
            elif summary["radius_mm"] is None:
                face_radius = self._get_face_radius(face)
                if isinstance(face_radius, (int, float)):
                    summary["radius_mm"] = float(face_radius) * 10.0

            axis_direction = _read_vector(axis_source, "axis")
            if axis_direction is not None:
                summary["axis_direction"] = axis_direction

            axis_origin_mm = _read_point_mm(axis_source, "origin")
            if axis_origin_mm is not None:
                summary["axis_origin_mm"] = axis_origin_mm
        except Exception:
            pass

        return summary

    def GET_FACE_PROPERTIES(self, face_id: str) -> dict:
        # validate inputs & ids
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")
        return self._face_geometry_summary(face_id, face)

    def RESOLVE_INTERFACE(
        self,
        component_id: str,
        body_id: str,
        interface_name: str,
        recipe: dict,
    ) -> dict:
        # validate inputs & ids
        _ = self._require_component(component_id)
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")
        if not isinstance(interface_name, str) or not interface_name:
            raise RuntimeError("RESOLVE_INTERFACE requires interface_name")
        if not isinstance(recipe, dict):
            raise RuntimeError("RESOLVE_INTERFACE requires recipe dict")

        # Deterministic, predicate-based selection (fail-fast)
        try:
            entity_kind, entity_id, geometry_summary, select_debug = self._select_face_by_recipe(body_id=body_id, recipe=recipe)
        except Exception as e:
            try:
                self._append_interface_resolution_audit(
                    {
                        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        "status": "failed",
                        "component_id": component_id,
                        "body_id": body_id,
                        "interface_name": interface_name,
                        "recipe": dict(recipe),
                        "error": f"{type(e).__name__}: {e}",
                    }
                )
            except Exception:
                pass
            raise

        if not isinstance(entity_id, str) or not entity_id:
            raise RuntimeError(f"Failed to resolve interface '{interface_name}' on body '{body_id}'")

        token_id = f"ifc:{component_id}:{interface_name}"
        self._interface_tokens[token_id] = {
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "interface_name": interface_name,
        }

        # Create a stable marker for downstream anchoring.
        marker_id = self._mk_interface_marker_id(component_id, interface_name)
        self._cache_marker_from_entity(
            marker_id=marker_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            interface_name=interface_name,
        )

        try:
            self._append_resolved_interface_debug(
                {
                    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "component_id": component_id,
                    "interface_name": interface_name,
                    "token_id": token_id,
                    "marker_id": marker_id,
                    "selection": select_debug,
                }
            )
        except Exception:
            pass

        try:
            self._append_interface_resolution_audit(
                {
                    "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "status": "resolved",
                    "component_id": component_id,
                    "body_id": body_id,
                    "interface_name": interface_name,
                    "token_id": token_id,
                    "marker_id": marker_id,
                    "entity_kind": entity_kind,
                    "entity_id": entity_id,
                    "selection": select_debug,
                }
            )
        except Exception:
            pass

        return {
            "token_id": token_id,
            "marker_id": marker_id,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "interface_name": interface_name,
            "geometry_summary": geometry_summary,
        }


    def ADD_SKETCH_DIMENSION(
        self,
        sketch_id: str,
        kind: str,
        entity_refs: dict,
        value_mm: float,
        is_driving: bool = True,
    ) -> dict:
        """鍦?sketch 涓坊鍔犲昂瀵告爣娉紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        dims = sketch.sketchDimensions
        dim = None

        if kind == "line_length":
            curve_id = entity_refs.get("curve_id")
            curve = self._require_curve(curve_id)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
            p1 = curve.startSketchPoint
            p2 = curve.endSketchPoint
            if not p1 or not p2:
                raise RuntimeError("line_length requires a line with start/end points")
            mid = adsk.core.Point3D.create(
                (p1.geometry.x + p2.geometry.x) / 2.0,
                (p1.geometry.y + p2.geometry.y) / 2.0,
                (p1.geometry.z + p2.geometry.z) / 2.0,
            )
            dim = dims.addDistanceDimension(
                p1,
                p2,
                adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
                mid,
            )
        elif kind == "circle_diameter":
            curve_id = entity_refs.get("curve_id")
            curve = self._require_curve(curve_id)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
            center = curve.centerSketchPoint.geometry
            text_pt = adsk.core.Point3D.create(center.x, center.y, center.z)
            dim = dims.addDiameterDimension(curve, text_pt)
        elif kind == "point_distance":
            p1_id = entity_refs.get("point_id_a")
            p2_id = entity_refs.get("point_id_b")
            sp1 = self._require_sketch_point(p1_id)
            sp2 = self._require_sketch_point(p2_id)
            if not sp1 or not sp1.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {p1_id}")
            if not sp2 or not sp2.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {p2_id}")
            mid = adsk.core.Point3D.create(
                (sp1.geometry.x + sp2.geometry.x) / 2.0,
                (sp1.geometry.y + sp2.geometry.y) / 2.0,
                (sp1.geometry.z + sp2.geometry.z) / 2.0,
            )
            dim = dims.addDistanceDimension(
                sp1,
                sp2,
                adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
                mid,
            )
        else:
            raise RuntimeError(f"Unsupported sketch dimension kind: {kind}")

        if not dim or not dim.isValid:
            raise RuntimeError("Failed to create sketch dimension")

        if hasattr(dim, "isDriving"):
            dim.isDriving = bool(is_driving)

        if bool(is_driving) and hasattr(dim, "parameter") and dim.parameter:
            dim.parameter.value = float(value_mm) / 10.0

        counter = self._dim_counter.get(sketch_id, 0) + 1
        self._dim_counter[sketch_id] = counter
        dim_id = f"{sketch_id}:dim:{counter}"
        self._dims[dim_id] = dim
        return {"dimension_id": dim_id}

    def SKETCH_SPLINE_THROUGH_POINTS(
        self,
        sketch_id: str,
        points: list[dict],
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓€氳繃鐐瑰垱寤烘牱鏉?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")
        if not points or len(points) < 2:
            raise RuntimeError("SKETCH_SPLINE_THROUGH_POINTS requires at least two points")

        sketch.isComputeDeferred = True
        try:
            point_collection = adsk.core.ObjectCollection.create()
            for pt in points:
                point_collection.add(self.cm_point(pt.get("x", 0), pt.get("y", 0), pt.get("z", 0)))

            splines = sketch.sketchCurves.sketchFittedSplines
            spline = splines.add(point_collection)
            spline.isConstruction = construction

            curve_id = self._next_curve_id(sketch_id, "spline")
            self._curves[curve_id] = spline
            return self._ret_sketch(curve_id=curve_id)
        finally:
            sketch.isComputeDeferred = False

    def CREATE_PATH_FROM_CURVES(self, curve_ids: list[str], is_chain: bool = True) -> dict:
        """浠庢洸绾垮垱寤?Path"""
        # validate inputs & ids
        if not curve_ids:
            raise RuntimeError("CREATE_PATH_FROM_CURVES requires non-empty curve_ids")

        curve_collection = adsk.core.ObjectCollection.create()
        for curve_id in curve_ids:
            curve = self._require_curve(curve_id)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
            curve_collection.add(curve)

        if is_chain:
            chain_option = adsk.fusion.ChainedCurveOptions.ConnectedChainedCurves
        else:
            chain_option = adsk.fusion.ChainedCurveOptions.NoChainedCurves
        path = adsk.fusion.Path.create(curve_collection, chain_option)
        self._path_counter += 1
        path_id = f"path:{self._path_counter}"
        self._paths[path_id] = path
        return {"path_id": path_id}

    def LOFT_NEW_BODY(
        self,
        component_id: str,
        profile_ids: list[str],
        is_solid: bool = True,
        operation: str = "new_body",
        name: str | None = None,
    ) -> dict:
        """閫氳繃澶氫釜鎴潰鍒涘缓鏀炬牱瀹炰綋"""
        # validate inputs & ids
        if not profile_ids or len(profile_ids) < 2:
            raise RuntimeError("LOFT_NEW_BODY requires at least two profiles")

        comp = self._require_component(component_id)
        profiles = []
        for profile_id in profile_ids:
            profile = self._require_profile(profile_id)
            if not profile or not profile.isValid:
                raise RuntimeError(f"Profile not found or invalid: {profile_id}")
            profiles.append(profile)

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported loft operation: {operation}")

        lofts = comp.features.loftFeatures
        loft_input = lofts.createInput(mapped_op)
        sections = loft_input.loftSections
        for profile in profiles:
            sections.add(profile)
        loft_input.isSolid = bool(is_solid)

        feature = lofts.add(loft_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "loft")
        self._cache_feature(feature_id, feature)
        body_ids: list[str] = []
        if mapped_op in {
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }:
            self._assign_extrude_participant_bodies(ext_input, comp, body_id=body_id)

        if mapped_op == adsk.fusion.FeatureOperations.NewBodyFeatureOperation:
            body_ids = self._register_bodies(component_id, feature.bodies)
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def SWEEP_NEW_BODY(
        self,
        component_id: str,
        profile_id: str,
        path_id: str,
        operation: str = "new_body",
        name: str | None = None,
    ) -> dict:
        """娌胯矾寰勬壂鎺犲垱寤哄疄浣?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile not found or invalid: {profile_id}")

        path = self._paths.get(path_id)
        if not path or (hasattr(path, "isValid") and not path.isValid):
            raise RuntimeError(f"Path not found or invalid: {path_id}")

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported sweep operation: {operation}")

        sweeps = comp.features.sweepFeatures
        sweep_input = sweeps.createInput(profile, path, mapped_op)
        feature = sweeps.add(sweep_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "sweep")
        self._cache_feature(feature_id, feature)
        body_ids: list[str] = []
        if mapped_op == adsk.fusion.FeatureOperations.NewBodyFeatureOperation:
            body_ids = self._register_bodies(component_id, feature.bodies)
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids)

    def SKETCH_ELLIPSE(
        self,
        sketch_id: str,
        center: dict,
        major_radius_mm: float,
        minor_radius_mm: float,
        major_axis_angle_rad: float = 0.0,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓敾妞渾锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        import math

        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        before_count = sketch.profiles.count
        center_pt = self.cm_point(center.get("x", 0), center.get("y", 0), center.get("z", 0))
        major_r_cm = float(major_radius_mm) / 10.0
        minor_r_cm = float(minor_radius_mm) / 10.0
        angle = float(major_axis_angle_rad)

        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        major_axis_pt = adsk.core.Point3D.create(
            center_pt.x + major_r_cm * cos_a,
            center_pt.y + major_r_cm * sin_a,
            center_pt.z,
        )
        minor_axis_pt = adsk.core.Point3D.create(
            center_pt.x - minor_r_cm * sin_a,
            center_pt.y + minor_r_cm * cos_a,
            center_pt.z,
        )

        ellipse = sketch.sketchCurves.sketchEllipses.add(center_pt, major_axis_pt, minor_axis_pt)
        ellipse.isConstruction = construction

        if construction:
            curve_id = self._next_curve_id(sketch_id, "ellipse")
            self._curves[curve_id] = ellipse
            return self._ret_sketch(curve_id=curve_id)

        after_count = sketch.profiles.count
        delta = after_count - before_count
        if delta != 1:
            raise RuntimeError(
                f"SKETCH_ELLIPSE profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )
        profile = sketch.profiles.item(before_count)

        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)

    def SKETCH_SLOT(
        self,
        sketch_id: str,
        center1: dict,
        center2: dict,
        width_mm: float,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓敾鐙紳锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        before_count = sketch.profiles.count
        p1 = self.cm_point(center1.get("x", 0), center1.get("y", 0), center1.get("z", 0))
        p2 = self.cm_point(center2.get("x", 0), center2.get("y", 0), center2.get("z", 0))
        width_cm = float(width_mm) / 10.0

        slots = sketch.sketchCurves.sketchSlots
        slot = slots.addCenterToCenterSlot(p1, p2, width_cm)
        slot.isConstruction = construction

        if construction:
            curve_id = self._next_curve_id(sketch_id, "slot")
            self._curves[curve_id] = slot
            return self._ret_sketch(curve_id=curve_id)

        after_count = sketch.profiles.count
        delta = after_count - before_count
        if delta != 1:
            raise RuntimeError(
                f"SKETCH_SLOT profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )
        profile = sketch.profiles.item(before_count)

        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)

    def SKETCH_TEXT(
        self,
        sketch_id: str,
        text: str,
        position: dict,
        height_mm: float,
        rotation_rad: float = 0.0,
    ) -> dict:
        """鍦?sketch 涓垱寤烘枃鏈紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        position_pt = self.cm_point(position.get("x", 0), position.get("y", 0), position.get("z", 0))
        height_cm = float(height_mm) / 10.0

        texts = sketch.sketchTexts
        # createInput2(text, height, point) 鈥?available in Fusion 2023+
        # Fallback to createInput(text, height, point, cornerPoint) for older builds.
        try:
            text_input = texts.createInput2(str(text), height_cm, position_pt)
        except AttributeError:
            # Legacy API: createInput requires a second corner point
            corner_pt = adsk.core.Point3D.create(
                position_pt.x + height_cm * max(1, len(str(text))) * 0.6,
                position_pt.y + height_cm,
                position_pt.z,
            )
            text_input = texts.createInput(str(text), height_cm, position_pt, corner_pt)
        text_input.angle = float(rotation_rad)
        created_text = texts.add(text_input)

        counter = self._text_counter.get(sketch_id, 0) + 1
        self._text_counter[sketch_id] = counter
        text_id = f"{sketch_id}:text:{counter}"
        self._texts[text_id] = created_text
        return {"text_id": text_id}

    def PROJECT_CURVES_TO_SKETCH(
        self,
        target_sketch_id: str,
        source_curve_ids: list[str],
    ) -> dict:
        """灏嗘洸绾挎姇褰卞埌 sketch"""
        # validate inputs & ids
        target_sketch = self._require_sketch(target_sketch_id)
        if not target_sketch:
            raise RuntimeError(f"Target sketch not found: {target_sketch_id}")

        if not source_curve_ids:
            raise RuntimeError("PROJECT_CURVES_TO_SKETCH requires non-empty source_curve_ids")

        target_sketch.isComputeDeferred = True
        try:
            source_curves = []
            for curve_id in source_curve_ids:
                curve = self._require_curve(curve_id)
                if not curve or not curve.isValid:
                    raise RuntimeError(f"Source curve not found or invalid: {curve_id}")
                source_curves.append(curve)

            created_curves = []
            for curve in source_curves:
                projected = target_sketch.project(curve)
                if hasattr(projected, "count"):
                    for i in range(projected.count):
                        created_curves.append(projected.item(i))
                elif isinstance(projected, (list, tuple)):
                    created_curves.extend(projected)
                elif projected is not None:
                    created_curves.append(projected)

            if not created_curves:
                raise RuntimeError("PROJECT_CURVES_TO_SKETCH produced no curves")

            new_curve_ids = []
            for curve in created_curves:
                curve_id = self._next_curve_id(target_sketch_id, "projected")
                self._curves[curve_id] = curve
                new_curve_ids.append(curve_id)
            return self._ret_sketch(curve_ids=new_curve_ids)
        finally:
            target_sketch.isComputeDeferred = False

    def PROJECT_EDGES_TO_SKETCH(
        self,
        sketch_id: str,
        edge_ids: list[str],
    ) -> dict:
        """Project edges onto a sketch using ``Sketch.project(entity)``.

        ``Sketch.projectCutEdges()`` does not exist in the official Fusion 360
        API; the ``is_cut`` parameter has therefore been removed.
        """
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch not found: {sketch_id}")

        if not edge_ids:
            raise RuntimeError("PROJECT_EDGES_TO_SKETCH requires non-empty edge_ids")

        sketch.isComputeDeferred = True
        try:
            created_curves = []
            for edge_id in edge_ids:
                edge = self.GET_EDGE_BY_ID(edge_id)
                projected = sketch.project(edge)

                if hasattr(projected, "count"):
                    for i in range(projected.count):
                        created_curves.append(projected.item(i))
                elif isinstance(projected, (list, tuple)):
                    created_curves.extend(projected)
                elif projected is not None:
                    created_curves.append(projected)

            if not created_curves:
                raise RuntimeError("PROJECT_EDGES_TO_SKETCH produced no curves")
        finally:
            sketch.isComputeDeferred = False

        new_curve_ids = []
        for curve in created_curves:
            curve_id = self._next_curve_id(sketch_id, "projected_edge")
            self._curves[curve_id] = curve
            new_curve_ids.append(curve_id)
        return self._ret_sketch(curve_ids=new_curve_ids)

    def LIST_COMPONENT_BODIES(self, component_id: str) -> dict:
        """鍒椾妇缁勪欢涓殑瀹炰綋骞跺垎閰嶇ǔ瀹欼D"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        body_ids = []
        for i in range(comp.bRepBodies.count):
            body = comp.bRepBodies.item(i)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid at index: {i}")
            if self.strict_mode and any(existing is body for existing in self._bodies.values()):
                continue
            body_id = self._next_body_id(component_id)
            self._cache_body(body_id, body)
            body_ids.append(body_id)
        return {"body_ids": body_ids}

    # ------------------------------------------------------------------
    # Helper: auto-merge fragment bodies back into a single body
    # ------------------------------------------------------------------
    def _auto_merge_fragment_bodies(self, comp, component_id: str) -> int:
        """灏濊瘯灏嗙粍浠跺唴澶氫釜纰庣墖 body 鍚堝苟涓轰竴涓€?

        绛栫暐锛?
        1. 鍏堝皾璇?CombineFeatures(Join) 灏嗘墍鏈?body 鍚堝苟锛堥€傜敤浜庣浉閭荤鐗囷級銆?
        2. 鑻?Join 澶辫触锛堢鐗囦笉鐩搁偦锛夛紝淇濈暀浣撶Н鏈€澶х殑 body锛屽垹闄ゅ叾浣欑鐗囥€?

        杩斿洖锛氬悎骞?娓呯悊鍚庣殑 body 鏁伴噺銆?
        """
        bodies = comp.bRepBodies
        count = int(bodies.count)
        if count <= 1:
            return count

        # -- 鏀堕泦鎵€鏈夋湁鏁?solid body --
        solid_bodies: list[tuple[Any, float]] = []  # (body_obj, volume)
        for bi in range(count):
            body = bodies.item(bi)
            if not body or not getattr(body, "isValid", False):
                continue
            if not getattr(body, "isSolid", False):
                continue
            try:
                vol = float(body.volume)
            except Exception:
                vol = 0.0
            solid_bodies.append((body, vol))

        if len(solid_bodies) <= 1:
            return len(solid_bodies) if len(solid_bodies) == 1 else int(bodies.count)

        # 鎸変綋绉檷搴忔帓鍒楋紝绗竴涓负 target锛堟渶澶э級锛屽叾浣欎负 tool
        solid_bodies.sort(key=lambda x: x[1], reverse=True)
        target_body = solid_bodies[0][0]
        tool_bodies = [b for b, _ in solid_bodies[1:]]

        # -- 绛栫暐 1: CombineFeatures Join --
        try:
            tools = adsk.core.ObjectCollection.create()
            for tb in tool_bodies:
                tools.add(tb)
            combine_feats = comp.features.combineFeatures
            combine_input = combine_feats.createInput(target_body, tools)
            combine_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
            combine_input.isKeepToolBodies = False
            combine_feats.add(combine_input)
            self._evict_stale_bodies()
            new_count = int(bodies.count)
            if new_count == 1:
                print(
                    f"[AUTO_MERGE] Combined {len(solid_bodies)} fragment bodies "
                    f"in '{component_id}' via CombineFeatures(Join)."
                )
                return new_count
        except Exception:
            pass  # Join failed (non-adjacent fragments); fall through

        # -- 绛栫暐 2: 淇濈暀鏈€澶?body锛屽垹闄ゅ叾浣欑鐗?--
        new_count = int(bodies.count)
        if new_count <= 1:
            return new_count

        # 闇€瑕侀噸鏂版壂鎻忥紝鍥犱负 combine 鍙兘宸查儴鍒嗕慨鏀?
        delete_targets: list[Any] = []
        best_volume = -1.0
        best_body = None
        for bi in range(int(bodies.count)):
            body = bodies.item(bi)
            if not body or not getattr(body, "isValid", False):
                continue
            try:
                vol = float(body.volume)
            except Exception:
                vol = 0.0
            if vol > best_volume:
                if best_body is not None:
                    delete_targets.append(best_body)
                best_body = body
                best_volume = vol
            else:
                delete_targets.append(body)

        removed = 0
        for frag in delete_targets:
            if not frag or not getattr(frag, "isValid", False):
                continue
            try:
                frag.deleteMe()
                removed += 1
            except Exception:
                pass

        # -- 娓呯悊 body 缂撳瓨涓凡澶辨晥鐨勫紩鐢?--
        self._evict_stale_bodies()

        final_count = int(bodies.count)
        if removed > 0:
            print(
                f"[AUTO_MERGE] Deleted {removed} fragment body(ies) "
                f"in '{component_id}' (kept largest, vol={best_volume:.4f} cm鲁). "
                f"Bodies remaining: {final_count}."
            )
        return final_count

    def _evict_stale_bodies(self) -> None:
        """浠?_bodies 缂撳瓨涓Щ闄ゅ凡澶辨晥鐨?body 寮曠敤銆?"""
        stale = [
            bid for bid, body in self._bodies.items()
            if body is None or not getattr(body, "isValid", False)
        ]
        for bid in stale:
            del self._bodies[bid]

    def _valid_solid_bodies(self, comp) -> list[Any]:
        solids: list[Any] = []
        try:
            bodies = self._list_component_candidate_bodies(comp)
        except Exception:
            return solids

        for body in bodies:
            if body is None or not getattr(body, "isValid", False):
                continue
            if not bool(getattr(body, "isSolid", False)):
                continue
            solids.append(body)
        return solids

    def _collect_extrude_participant_bodies(self, comp, body_id: str | None = None):
        collection_factory = getattr(adsk.core, "ObjectCollection", None)
        if collection_factory is None or not hasattr(collection_factory, "create"):
            return None
        try:
            participants = collection_factory.create()
        except Exception:
            return None

        if isinstance(body_id, str) and body_id:
            try:
                body = self._require_body(body_id)
            except Exception:
                body = None
            if body is not None and getattr(body, "isValid", False) and bool(getattr(body, "isSolid", False)):
                try:
                    participants.add(body)
                    return participants
                except Exception:
                    return None
            return None

        for body in self._valid_solid_bodies(comp):
            try:
                participants.add(body)
            except Exception:
                continue
        return participants

    def _assign_extrude_participant_bodies(self, ext_input, comp, body_id: str | None = None) -> bool:
        if ext_input is None or comp is None or not hasattr(ext_input, "participantBodies"):
            return False
        participants = self._collect_extrude_participant_bodies(comp, body_id=body_id)
        if participants is None:
            return False
        try:
            count = int(getattr(participants, "count", 0) or 0)
        except Exception:
            count = 0
        if count <= 0:
            return False
        try:
            ext_input.participantBodies = participants
            return True
        except Exception:
            return False

    def GET_SINGLE_BODY_ID(self, component_id: str, allow_multi_body_fallback: bool = False) -> dict:
        """杩斿洖缁勪欢鍞竴 body 鐨勭ǔ瀹?body_id锛堜弗鏍?fail-fast锛夈€?

        璁捐鐩殑锛?
        - 璁″垝灞傜姝娇鐢?/body_ids/0 杩欑被 index-based capture锛堜笉绋冲畾锛?
        - 浣嗚閰嶆帴鍙ｈВ鏋愰渶瑕?body_id
        - 瀵规爣鍑嗕欢/搴撲欢锛氶€氬父鍙寘鍚竴涓?body锛屾湰鍑芥暟鍙‘瀹氭€ц繑鍥炲畠

        瑙勫垯锛?
        - 缁勪欢蹇呴』鎭板ソ鍖呭惈 1 涓湁鏁?body
        - 鑻?body 宸茬紦瀛橈紝杩斿洖宸叉湁 body_id锛涘惁鍒欏垎閰嶆柊鐨勭ǔ瀹?id 骞剁紦瀛?

        鑷姩鎭㈠锛?
        - 褰?body 鏁?> 1 鏃讹紙渚嬪璐┛瀛斿皢钖勫鐜垏鏂骇鐢熺鐗囷級鍏堝皾璇?
          CombineFeatures(Join) 灏嗘墍鏈?body 鍚堝苟鎴愪竴涓紱
        - 鑻?Join 澶辫触锛堢鐗囦笉鐩搁偦锛夛紝淇濈暀浣撶Н鏈€澶х殑 body 骞跺垹闄ょ鐗囥€?
        """
        try:
            comp = self._require_component_for_body_queries(component_id, require_faces=True)
        except Exception:
            comp = self._require_component(component_id)

        candidate_bodies = self._list_component_candidate_bodies(comp)
        try:
            count = max(len(candidate_bodies), self._component_body_count(comp))
        except Exception:
            count = len(candidate_bodies)
        if count > 1:
            count = self._auto_merge_fragment_bodies(comp, component_id)
            try:
                comp = self._require_component_for_body_queries(component_id, require_faces=True)
            except Exception:
                comp = self._require_component(component_id)
            candidate_bodies = self._list_component_candidate_bodies(comp)
            if candidate_bodies:
                count = max(len(candidate_bodies), count)

        solid_bodies = self._valid_solid_bodies(comp)
        if len(solid_bodies) == 1:
            body = solid_bodies[0]
        else:
            if bool(allow_multi_body_fallback):
                fallback = []
                if solid_bodies:
                    fallback = [b for b in solid_bodies if b is not None and getattr(b, "isValid", False)]
                else:
                    fallback = [b for b in candidate_bodies if b is not None and getattr(b, "isValid", False)]

                if not fallback:
                    raise RuntimeError(
                        f"GET_SINGLE_BODY_ID fallback failed for component '{component_id}': no valid fallback bodies."
                    )

                def _vol(candidate_body):
                    try:
                        return float(getattr(candidate_body, "volume", 0.0) or 0.0)
                    except Exception:
                        return 0.0

                body = max(fallback, key=_vol)
            else:
                if count != 1:
                    raise RuntimeError(
                        f"GET_SINGLE_BODY_ID requires component '{component_id}' to have exactly 1 body, got {count}."
                    )
                if len(candidate_bodies) != 1:
                    raise RuntimeError(
                        f"GET_SINGLE_BODY_ID requires component '{component_id}' to expose exactly 1 recoverable body, got {len(candidate_bodies)}."
                    )
                body = candidate_bodies[0]
                if not body or not body.isValid:
                    raise RuntimeError(f"GET_SINGLE_BODY_ID: body invalid for component '{component_id}'.")

        for existing_id, existing_body in self._bodies.items():
            if existing_body is body:
                return {"body_id": existing_id}

        body_id = self._next_body_id(component_id)
        self._cache_body(body_id, body)
        return {"body_id": body_id}

    def LIST_COMPONENT_OCCURRENCES(self, component_id: str | None = None) -> dict:
        """鍒椾妇缁勪欢涓嬬殑 occurrences"""
        # validate inputs & ids
        if component_id is None:
            target_component = None
            prefix = "listed:occ"
        else:
            target_component = self._require_component(component_id)
            prefix = "listed:occ"

        occ_prefix = f"{prefix}:occ:"
        for key in list(self._listed_occurrences.keys()):
            if key.startswith(occ_prefix):
                del self._listed_occurrences[key]

        def _iter_occurrences(comp):
            occs = comp.occurrences
            for i in range(occs.count):
                occ = occs.item(i)
                if not occ or not occ.isValid:
                    continue
                yield occ
                child_occs = occ.childOccurrences
                for j in range(child_occs.count):
                    child = child_occs.item(j)
                    if not child or not child.isValid:
                        continue
                    yield from _iter_occurrences(child.component)

        occ_ids = []
        root = self.design.rootComponent
        matched = []
        for occ in _iter_occurrences(root):
            if target_component is not None and occ.component != target_component:
                continue
            matched.append(occ)

        for i, occ in enumerate(matched):
            occ_id = f"{prefix}:occ:{i}"
            self._listed_occurrences[occ_id] = occ
            occ_ids.append(occ_id)

        return {"occurrence_ids": occ_ids}

    def LIST_ALL_OCCURRENCES(self, component_id: str | None = None) -> dict:
        """鍒椾妇缁勪欢涓嬬殑鎵€鏈?occurrences锛堥€掑綊锛屽寘鎷瓙缁勪欢锛?"""
        # validate inputs & ids
        if component_id is None:
            comp = self.design.rootComponent
            prefix = "listed:all_occ"
        else:
            comp = self._require_component(component_id)
            prefix = "listed:all_occ"

        occ_prefix = f"{prefix}:all_occ:"
        for key in list(self._listed_occurrences.keys()):
            if key.startswith(occ_prefix):
                del self._listed_occurrences[key]

        occ_ids = []
        all_occs = comp.allOccurrences
        for i in range(all_occs.count):
            occ = all_occs.item(i)
            if not occ or not occ.isValid:
                continue
            occ_id = f"{prefix}:all_occ:{i}"
            self._listed_occurrences[occ_id] = occ
            occ_ids.append(occ_id)

        return {"occurrence_ids": occ_ids}

    def LIST_BODY_FACES(self, body_id: str) -> dict:
        """鍒椾妇韬綋鐨勯潰骞跺垎閰嶇ǔ瀹欼D"""
        # validate inputs & ids
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        face_prefix = f"{body_id}:face:"
        for key in list(self._faces.keys()):
            if key.startswith(face_prefix):
                del self._faces[key]

        face_ids = []
        for i in range(body.faces.count):
            face = body.faces.item(i)
            face_id = f"{body_id}:face:{i}"
            self._cache_face(face_id, face)
            face_ids.append(face_id)

        return {"face_ids": face_ids}

    def LIST_BODY_EDGES(self, body_id: str) -> dict:
        """鍒椾妇韬綋鐨勮竟骞跺垎閰嶇ǔ瀹欼D"""
        # validate inputs & ids
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        edge_prefix = f"{body_id}:edge:"
        for key in list(self._edges.keys()):
            if key.startswith(edge_prefix):
                del self._edges[key]

        edge_ids = []
        for i in range(body.edges.count):
            edge = body.edges.item(i)
            edge_id = f"{body_id}:edge:{i}"
            self._cache_edge(edge_id, edge)
            edge_ids.append(edge_id)

        return {"edge_ids": edge_ids}

    def GET_FACE_BY_ID(self, face_id: str):
        """鏍规嵁ID鑾峰彇闈㈠璞★紙鍐呴儴杈呭姪鍑芥暟锛岃繑鍥?adsk 瀵硅薄锛?"""
        # validate inputs & ids
        face = self._require_face(face_id)
        if not face or not face.isValid:
            raise RuntimeError(f"Face not found or invalid: {face_id}")
        return face

    def GET_EDGE_BY_ID(self, edge_id: str):
        """鏍规嵁ID鑾峰彇杈瑰璞★紙鍐呴儴杈呭姪鍑芥暟锛岃繑鍥?adsk 瀵硅薄锛?"""
        # validate inputs & ids
        edge = self._require_edge(edge_id)
        if not edge or not edge.isValid:
            raise RuntimeError(f"Edge not found or invalid: {edge_id}")
        return edge

    def GET_VERTEX_BY_ID(self, vertex_id: str):
        """鏍规嵁ID鑾峰彇椤剁偣瀵硅薄锛堝唴閮ㄨ緟鍔╁嚱鏁帮紝杩斿洖 adsk 瀵硅薄锛?"""
        # validate inputs & ids
        vertex = self._require_vertex(vertex_id)
        if not vertex or not vertex.isValid:
            raise RuntimeError(f"Vertex not found or invalid: {vertex_id}")
        return vertex

    def LIST_BODY_VERTICES(self, body_id: str) -> dict:
        """鍒椾妇韬綋鐨勯《鐐瑰苟鍒嗛厤绋冲畾ID"""
        # validate inputs & ids
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        vertex_prefix = f"{body_id}:vertex:"
        for key in list(self._vertices.keys()):
            if key.startswith(vertex_prefix):
                del self._vertices[key]

        vertex_ids = []
        for i in range(body.vertices.count):
            vertex = body.vertices.item(i)
            vertex_id = f"{body_id}:vertex:{i}"
            self._cache_vertex(vertex_id, vertex)
            vertex_ids.append(vertex_id)

        return {"vertex_ids": vertex_ids}

    def FILLET_EDGES(
        self,
        component_id: str,
        edge_ids: list[str],
        radius_mm: float,
        tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """瀵硅竟杩涜鍦嗚澶勭悊锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        if not edge_ids:
            raise RuntimeError("FILLET_EDGES requires non-empty edge_ids")

        comp = self._require_component(component_id)
        
        edges = adsk.core.ObjectCollection.create()
        for edge_id in edge_ids:
            edge = self.GET_EDGE_BY_ID(edge_id)
            edges.add(edge)

        fillets = comp.features.filletFeatures
        fillet_input = fillets.createInput()
        edge_sets = fillet_input.edgeSetInputs
        edge_sets.addConstantRadiusEdgeSet(edges, self.mm(radius_mm), tangent_chain)

        feature = fillets.add(fillet_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "fillet")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def CHAMFER_EDGES(
        self,
        component_id: str,
        edge_ids: list[str],
        distance_mm: float,
        distance2_mm: float | None = None,
        angle_deg: float | None = None,
        tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """Apply chamfer to specified edges.

        Supports three official Fusion 360 chamfer modes:
        - Equal distance:        distance_mm only
        - Two distances:         distance_mm + distance2_mm
        - Distance and angle:    distance_mm + angle_deg

        Uses ChamferFeatures.createInput2() 鈫?ChamferEdgeSets.add*().
        """
        import math
        # validate inputs & ids
        if not edge_ids:
            raise RuntimeError("CHAMFER_EDGES requires non-empty edge_ids")

        comp = self._require_component(component_id)

        edges = adsk.core.ObjectCollection.create()
        for edge_id in edge_ids:
            edge = self.GET_EDGE_BY_ID(edge_id)
            edges.add(edge)

        chamfers = comp.features.chamferFeatures
        chamfer_input = chamfers.createInput2()
        edge_sets = chamfer_input.chamferEdgeSets

        if distance2_mm is not None:
            # Two-distance chamfer
            edge_sets.addTwoDistancesChamferEdgeSet(
                edges, self.mm(distance_mm), self.mm(distance2_mm), False, tangent_chain
            )
        elif angle_deg is not None:
            # Distance + angle chamfer
            angle_val = adsk.core.ValueInput.createByReal(math.radians(float(angle_deg)))
            edge_sets.addDistanceAndAngleChamferEdgeSet(
                edges, self.mm(distance_mm), angle_val, False, tangent_chain
            )
        else:
            # Equal distance chamfer (default)
            edge_sets.addEqualDistanceChamferEdgeSet(
                edges, self.mm(distance_mm), tangent_chain
            )

        feature = chamfers.add(chamfer_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "chamfer")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def HOLE_SIMPLE(
        self,
        component_id: str,
        center_mm: dict,
        diameter_mm: float,
        thread_spec: dict | None = None,
        face_id: str | None = None,
        plane_id: str | None = None,
        extent: str | None = None,
        depth_mm: float | None = None,
        direction: str | None = None,
        name: str | None = None,
    ) -> dict:
        """鍦ㄦ寚瀹氶潰涓婇捇瀛旓紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?
        
        extent: "distance" (闇€鎻愪緵 depth_mm), "through_positive", "through_negative"
        direction: (宸插純鐢? 鍚戝悗鍏煎鍙傛暟锛屽皢琚槧灏勫埌 extent
        """
        # validate inputs & ids
        warning = None

        normalized_thread: dict | None = None
        if thread_spec is not None:
            if not isinstance(thread_spec, dict) or not thread_spec:
                raise RuntimeError("HOLE_SIMPLE thread_spec must be a non-empty object when provided")
            thread_type = thread_spec.get("thread_type")
            thread_designation = thread_spec.get("thread_designation")
            thread_class = thread_spec.get("thread_class")
            if not (isinstance(thread_type, str) and thread_type.strip()):
                raise RuntimeError("HOLE_SIMPLE thread_spec.thread_type must be a non-empty string")
            if not (isinstance(thread_designation, str) and thread_designation.strip()):
                raise RuntimeError("HOLE_SIMPLE thread_spec.thread_designation must be a non-empty string")
            if not (isinstance(thread_class, str) and thread_class.strip()):
                raise RuntimeError("HOLE_SIMPLE thread_spec.thread_class must be a non-empty string")
            normalized_thread = {
                "is_internal": bool(thread_spec.get("is_internal", True)),
                "thread_type": thread_type,
                "thread_designation": thread_designation,
                "thread_class": thread_class,
            }
        
        # 楠岃瘉 extent 鍜?direction 鐨勫啿绐?
        if extent is not None and direction is not None:
            raise RuntimeError(
                "Cannot specify both 'extent' and 'direction' parameters; "
                "use 'extent' only (direction is deprecated)"
            )
        
        direction_hint_raw = direction

        # 濡傛灉鎻愪緵浜?direction锛屾槧灏勫埌 extent
        if direction is not None:
            if direction == "through_positive":
                extent = "through_positive"
            elif direction == "through_negative":
                extent = "through_negative"
            elif direction == "through":
                extent = "through_positive"
                warning = "direction='through' is deprecated; use extent='through_positive'"
            else:
                # "normal" 鎴栧叾浠栨湭璇嗗埆鐨勫€?-> distance
                extent = "distance"
        
        # 濡傛灉閮芥病鎸囧畾锛屼娇鐢ㄩ粯璁ゅ€?
        if extent is None:
            extent = "distance"
        
        # 楠岃瘉 extent 鍙傛暟
        valid_extents = ["distance", "through_positive", "through_negative"]
        if extent not in valid_extents:
            raise RuntimeError(
                f"Invalid extent '{extent}'; must be one of: {valid_extents}"
            )

        # 楠岃瘉 extent 涓?depth_mm 鐨勫叧绯?
        if extent == "distance":
            if depth_mm is None or depth_mm <= 0:
                raise RuntimeError(
                    f"extent='distance' requires depth_mm > 0, got: {depth_mm}"
                )
        elif extent.startswith("through"):
            if depth_mm is not None:
                raise RuntimeError(
                    f"extent='{extent}' must not have depth_mm; got: {depth_mm}"
                )

        if bool(face_id) == bool(plane_id):
            raise RuntimeError("HOLE_SIMPLE requires exactly one of face_id or plane_id")

        comp = self._require_component(component_id)

        def _entity_token(obj) -> str | None:
            if not obj or not getattr(obj, "isValid", False):
                return None
            try:
                token = getattr(obj, "entityToken", None)
                if isinstance(token, str) and token:
                    return token
            except Exception:
                return None
            return None

        def _iter_feature_face_collections(feature_obj):
            seen_collections: set[int] = set()
            explicit_attrs = ("faces", "sideFaces", "endFaces", "startFaces", "holeFaces")

            def _push_collection(value):
                if value is None:
                    return
                if not hasattr(value, "count") or not hasattr(value, "item"):
                    return
                key = id(value)
                if key in seen_collections:
                    return
                seen_collections.add(key)
                yield value

            for attr in explicit_attrs:
                try:
                    value = getattr(feature_obj, attr, None)
                except Exception:
                    value = None
                yield from _push_collection(value)

            for attr in dir(feature_obj):
                if not isinstance(attr, str) or not attr.endswith("Faces"):
                    continue
                try:
                    value = getattr(feature_obj, attr, None)
                except Exception:
                    continue
                yield from _push_collection(value)

        def _body_snapshot(component_obj) -> dict[str, set[str]]:
            snapshot: dict[str, set[str]] = {}
            bodies = getattr(component_obj, "bRepBodies", None)
            if bodies is None:
                return snapshot
            body_count = int(getattr(bodies, "count", 0) or 0)
            for bi in range(body_count):
                body_obj = bodies.item(bi)
                if not body_obj or not getattr(body_obj, "isValid", False):
                    continue
                body_key = _entity_token(body_obj) or f"body_obj_{id(body_obj)}"
                token_set: set[str] = set()
                body_faces = getattr(body_obj, "faces", None)
                if body_faces is None:
                    snapshot[body_key] = token_set
                    continue
                face_count = int(getattr(body_faces, "count", 0) or 0)
                for fi in range(face_count):
                    face_obj = body_faces.item(fi)
                    token = _entity_token(face_obj)
                    if token:
                        token_set.add(token)
                snapshot[body_key] = token_set
            return snapshot

        def _collect_hole_cyl_faces(component_obj, feature_obj, before_snapshot: dict[str, set[str]]):
            collected_feature_faces: list[Any] = []
            collected_body_faces: list[Any] = []
            seen: set[str | int] = set()

            for faces in _iter_feature_face_collections(feature_obj):
                count = int(getattr(faces, "count", 0) or 0)
                for i in range(count):
                    face_obj = faces.item(i)
                    if not face_obj or not getattr(face_obj, "isValid", False):
                        continue
                    if not self._is_cylindrical_face(face_obj):
                        continue
                    key = _entity_token(face_obj) or id(face_obj)
                    if key in seen:
                        continue
                    seen.add(key)
                    collected_feature_faces.append(face_obj)

            bodies = getattr(component_obj, "bRepBodies", None)
            if bodies is None:
                return collected_feature_faces

            body_count = int(getattr(bodies, "count", 0) or 0)
            for bi in range(body_count):
                body_obj = bodies.item(bi)
                if not body_obj or not getattr(body_obj, "isValid", False):
                    continue
                body_key = _entity_token(body_obj) or f"body_obj_{id(body_obj)}"
                old_tokens = before_snapshot.get(body_key, set())
                body_faces = getattr(body_obj, "faces", None)
                if body_faces is None:
                    continue
                face_count = int(getattr(body_faces, "count", 0) or 0)
                for fi in range(face_count):
                    face_obj = body_faces.item(fi)
                    if not face_obj or not getattr(face_obj, "isValid", False):
                        continue
                    if not self._is_cylindrical_face(face_obj):
                        continue
                    token = _entity_token(face_obj)
                    if token and token in old_tokens:
                        continue
                    key = token or id(face_obj)
                    if key in seen:
                        continue
                    seen.add(key)
                    collected_body_faces.append(face_obj)

            if collected_body_faces:
                return collected_body_faces
            return collected_feature_faces

        before_snapshot = _body_snapshot(comp)
        participant_bodies = adsk.core.ObjectCollection.create()

        expected_hole_radius_cm = float(diameter_mm) / 20.0 if isinstance(diameter_mm, (int, float)) else None

        def _select_thread_faces(cyl_faces: list[Any], center_point, direction_normal) -> list[Any]:
            if not cyl_faces:
                return []

            def _score(face_obj):
                geometry = getattr(face_obj, "geometry", None)
                radius = getattr(geometry, "radius", None) if geometry is not None else None
                axis = getattr(geometry, "axis", None) if geometry is not None else None
                origin = getattr(geometry, "origin", None) if geometry is not None else None

                radius_penalty = 1e9
                if isinstance(radius, (int, float)) and isinstance(expected_hole_radius_cm, (int, float)):
                    radius_penalty = abs(float(radius) - float(expected_hole_radius_cm))

                axis_dist = 1e9
                axis_align_penalty = 1.0
                try:
                    if axis is not None and origin is not None and center_point is not None:
                        ax = float(getattr(axis, "x", 0.0))
                        ay = float(getattr(axis, "y", 0.0))
                        az = float(getattr(axis, "z", 0.0))
                        norm = math.sqrt(ax * ax + ay * ay + az * az)
                        if norm > 1e-12:
                            ax /= norm
                            ay /= norm
                            az /= norm
                            vx = float(getattr(center_point, "x", 0.0)) - float(getattr(origin, "x", 0.0))
                            vy = float(getattr(center_point, "y", 0.0)) - float(getattr(origin, "y", 0.0))
                            vz = float(getattr(center_point, "z", 0.0)) - float(getattr(origin, "z", 0.0))
                            cx = vy * az - vz * ay
                            cy = vz * ax - vx * az
                            cz = vx * ay - vy * ax
                            axis_dist = math.sqrt(cx * cx + cy * cy + cz * cz)

                            if direction_normal is not None:
                                nx = float(getattr(direction_normal, "x", 0.0))
                                ny = float(getattr(direction_normal, "y", 0.0))
                                nz = float(getattr(direction_normal, "z", 0.0))
                                n_norm = math.sqrt(nx * nx + ny * ny + nz * nz)
                                if n_norm > 1e-12:
                                    nx /= n_norm
                                    ny /= n_norm
                                    nz /= n_norm
                                    axis_align_penalty = 1.0 - abs(ax * nx + ay * ny + az * nz)
                except Exception:
                    pass

                return (radius_penalty, axis_dist, axis_align_penalty)

            ranked = sorted(
                [f for f in cyl_faces if f is not None and getattr(f, "isValid", False)],
                key=_score,
            )
            if not ranked:
                return []

            chosen = ranked[0]
            return [chosen]

        def _project_point_to_planar_entity(point_obj, geometry_obj, entity_obj=None):
            projected = None
            if geometry_obj is not None:
                try:
                    if hasattr(geometry_obj, "project"):
                        projected = geometry_obj.project(point_obj)
                except Exception:
                    projected = None

            if projected is not None:
                return projected

            try:
                normal = getattr(geometry_obj, "normal", None)
                origin = getattr(geometry_obj, "origin", None)
                if normal is None or origin is None:
                    normal = None
                    if entity_obj is not None:
                        ent_geom = getattr(entity_obj, "geometry", None)
                        if ent_geom is not None:
                            normal = getattr(ent_geom, "normal", None)
                            origin = getattr(ent_geom, "origin", None)
                    if normal is None and entity_obj is not None:
                        normal = getattr(getattr(entity_obj, "geometry", None), "normal", None)
                        origin = getattr(entity_obj, "pointOnFace", None)

                if normal is not None and origin is not None:
                    nx = float(getattr(normal, "x", 0.0))
                    ny = float(getattr(normal, "y", 0.0))
                    nz = float(getattr(normal, "z", 0.0))
                    norm2 = nx * nx + ny * ny + nz * nz
                    if norm2 > 1e-20:
                        ox = float(getattr(origin, "x", 0.0))
                        oy = float(getattr(origin, "y", 0.0))
                        oz = float(getattr(origin, "z", 0.0))
                        px = float(getattr(point_obj, "x", 0.0))
                        py = float(getattr(point_obj, "y", 0.0))
                        pz = float(getattr(point_obj, "z", 0.0))
                        t = ((px - ox) * nx + (py - oy) * ny + (pz - oz) * nz) / norm2
                        return adsk.core.Point3D.create(px - t * nx, py - t * ny, pz - t * nz)
            except Exception:
                pass

            return point_obj

        def _collect_participant_bodies(component_obj):
            participants = adsk.core.ObjectCollection.create()
            try:
                bodies = getattr(component_obj, "bRepBodies", None)
                if bodies is None:
                    return participants
                body_count = int(getattr(bodies, "count", 0) or 0)
                for bi in range(body_count):
                    body = bodies.item(bi)
                    if not body or not getattr(body, "isValid", False):
                        continue
                    if bool(getattr(body, "isSolid", False)):
                        participants.add(body)
            except Exception:
                pass
            return participants

        def _collect_face_participant_bodies(face_obj, component_obj):
            participants = adsk.core.ObjectCollection.create()
            seen_keys: set[str | int] = set()

            def _append_body(body_obj):
                if body_obj is None or not getattr(body_obj, "isValid", False):
                    return
                if not bool(getattr(body_obj, "isSolid", False)):
                    return
                key = _entity_token(body_obj) or id(body_obj)
                if key in seen_keys:
                    return
                seen_keys.add(key)
                participants.add(body_obj)

            try:
                comp_occ = getattr(component_obj, "assemblyContext", None)
            except Exception:
                comp_occ = None

            # Prefer single owning body first to avoid broad mixed-context participants.
            try:
                direct_body = getattr(face_obj, "body", None) or getattr(face_obj, "parentBody", None)
            except Exception:
                direct_body = None
            if direct_body is not None and getattr(direct_body, "isValid", False) and bool(getattr(direct_body, "isSolid", False)):
                _append_body(direct_body)
                if int(getattr(participants, "count", 0) or 0) > 0:
                    return participants

            candidate_faces: list[Any] = []
            if face_obj is not None and getattr(face_obj, "isValid", False):
                candidate_faces.append(face_obj)
                try:
                    native_face = getattr(face_obj, "nativeObject", None)
                    if native_face is not None and getattr(native_face, "isValid", False):
                        candidate_faces.append(native_face)
                except Exception:
                    pass

            for cand_face in candidate_faces:
                try:
                    body_obj = getattr(cand_face, "body", None) or getattr(cand_face, "parentBody", None)
                except Exception:
                    body_obj = None
                if body_obj is None or not getattr(body_obj, "isValid", False):
                    continue

                _append_body(body_obj)

                try:
                    native_body = getattr(body_obj, "nativeObject", None)
                except Exception:
                    native_body = None
                _append_body(native_body)

                if comp_occ is not None:
                    try:
                        if native_body is not None and hasattr(native_body, "createForAssemblyContext"):
                            _append_body(native_body.createForAssemblyContext(comp_occ))
                    except Exception:
                        pass
                    try:
                        if hasattr(body_obj, "createForAssemblyContext"):
                            _append_body(body_obj.createForAssemblyContext(comp_occ))
                    except Exception:
                        pass

            return participants

        def _apply_post_hole_thread(selected_faces: list[Any], thread_name: str | None = None):
            if normalized_thread is None:
                raise RuntimeError("_apply_post_hole_thread requires normalized_thread")

            def _resolve_face_owner_component(face_obj):
                if face_obj is None or not getattr(face_obj, "isValid", False):
                    return None
                candidates = [face_obj]
                try:
                    native_obj = getattr(face_obj, "nativeObject", None)
                    if native_obj is not None:
                        candidates.append(native_obj)
                except Exception:
                    pass
                for candidate in candidates:
                    try:
                        body_obj = getattr(candidate, "body", None) or getattr(candidate, "parentBody", None)
                    except Exception:
                        body_obj = None
                    if body_obj is None or not getattr(body_obj, "isValid", False):
                        continue
                    try:
                        owner_comp = getattr(body_obj, "parentComponent", None)
                    except Exception:
                        owner_comp = None
                    if owner_comp is not None and getattr(owner_comp, "isValid", False):
                        return owner_comp
                return None

            owner_comp = None
            for _face in selected_faces:
                owner_comp = _resolve_face_owner_component(_face)
                if owner_comp is not None:
                    break
            if owner_comp is None:
                owner_comp = comp

            tdq = adsk.fusion.ThreadDataQuery.create()
            all_types = tdq.allThreadTypes
            thread_features = owner_comp.features.threadFeatures

            is_internal_thread = bool(normalized_thread["is_internal"])
            requested_type = str(normalized_thread.get("thread_type") or "").strip()
            requested_designation = str(normalized_thread.get("thread_designation") or "").strip()
            requested_class = str(normalized_thread.get("thread_class") or "").strip()

            if all_types:
                if requested_type in all_types:
                    resolved_type = requested_type
                else:
                    resolved_type = next(
                        (t for t in all_types if str(t).strip().casefold() == requested_type.casefold()),
                        None,
                    )
                    if resolved_type is None:
                        raise RuntimeError(
                            f"Unknown thread_type for post-hole threading: {requested_type}. "
                            f"Example types: {all_types[:5]}"
                        )
            else:
                resolved_type = requested_type

            def _dedupe_keep_order(values):
                out: list[str] = []
                seen_vals: set[str] = set()
                for value in values:
                    if not isinstance(value, str):
                        continue
                    token = value.strip()
                    if not token:
                        continue
                    key = token.casefold()
                    if key in seen_vals:
                        continue
                    seen_vals.add(key)
                    out.append(token)
                return out

            def _as_string_list(raw):
                out: list[str] = []

                def _walk(value):
                    if value is None:
                        return
                    if isinstance(value, str):
                        out.append(value)
                        return
                    if isinstance(value, (list, tuple, set)):
                        for entry in value:
                            _walk(entry)
                        return
                    count = getattr(value, "count", None)
                    item = getattr(value, "item", None)
                    if isinstance(count, int) and callable(item):
                        for i in range(int(count)):
                            try:
                                entry = item(i)
                            except Exception:
                                continue
                            _walk(entry)

                _walk(raw)
                return out

            def _query_designations(thread_type_value: str) -> list[str]:
                queried: list[str] = []
                # Official API: allDesignations(threadType: str, size: str)
                # First get all sizes, then query designations for each size.
                try:
                    sizes = _as_string_list(tdq.allSizes(thread_type_value))
                except Exception:
                    sizes = []
                for size in sizes:
                    try:
                        queried.extend(_as_string_list(tdq.allDesignations(thread_type_value, size)))
                    except Exception:
                        continue
                return _dedupe_keep_order([requested_designation, *queried])

            def _query_classes(thread_type_value: str, designation_value: str) -> list[str]:
                queried: list[str] = []
                # Official API: allClasses(isInternal: bool, threadType: str, designation: str)
                try:
                    queried.extend(_as_string_list(
                        tdq.allClasses(is_internal_thread, thread_type_value, designation_value)
                    ))
                except Exception:
                    pass
                return _dedupe_keep_order([requested_class, *queried])

            designation_candidates = _query_designations(str(resolved_type))
            if not designation_candidates:
                designation_candidates = [requested_designation]

            def _metric_designation_variants(text: str) -> list[str]:
                if not isinstance(text, str):
                    return []
                src = text.strip()
                if not src or not src.upper().startswith("M"):
                    return []
                token = src[1:]
                for sep in ("脳", "X"):
                    token = token.replace(sep, "x")
                head = token
                pitch = None
                if "x" in token:
                    head, pitch = token.split("x", 1)
                head = head.strip()
                pitch = pitch.strip() if isinstance(pitch, str) else None

                out: list[str] = []

                def _append(v: str):
                    if isinstance(v, str) and v.strip():
                        out.append(v.strip())

                _append(f"M{head}" if head else "")
                if head and pitch:
                    _append(f"M{head}x{pitch}")
                    try:
                        p_val = float(pitch)
                        if abs(p_val - round(p_val)) < 1e-9:
                            _append(f"M{head}x{int(round(p_val))}")
                        else:
                            _append(f"M{head}x{format(p_val, 'g')}")
                    except Exception:
                        pass
                return out

            designation_candidates = _dedupe_keep_order([
                *designation_candidates,
                *_metric_designation_variants(requested_designation),
            ])

            metric_nominal = None
            if requested_designation.upper().startswith("M"):
                token = requested_designation[1:]
                for sep in ("x", "X", "脳"):
                    if sep in token:
                        token = token.split(sep, 1)[0]
                        break
                if token:
                    metric_nominal = f"M{token}"
            if metric_nominal:
                preferred = [d for d in designation_candidates if metric_nominal.casefold() in d.casefold()]
                others = [d for d in designation_candidates if d not in preferred]
                designation_candidates = preferred + others

            thread_info = None
            thread_info_errors: list[str] = []
            for designation_try in designation_candidates:
                class_candidates = _query_classes(str(resolved_type), designation_try)
                if not class_candidates:
                    class_candidates = [requested_class]
                for class_try in class_candidates:
                    try:
                        thread_info = thread_features.createThreadInfo(
                            is_internal_thread,
                            str(resolved_type),
                            str(designation_try),
                            str(class_try),
                        )
                        break
                    except Exception as e_info:
                        thread_info_errors.append(
                            f"type={resolved_type},designation={designation_try},class={class_try}: {type(e_info).__name__}: {e_info}"
                        )
                if thread_info is not None:
                    break

            if thread_info is None:
                preview = thread_info_errors[:8]
                raise RuntimeError(
                    "Failed to resolve post-hole thread info from provided spec and available query data; "
                    f"requested={{'type': '{requested_type}', 'designation': '{requested_designation}', 'class': '{requested_class}'}}; "
                    f"attempts={len(thread_info_errors)}; errors={preview}"
                )

            def _to_face_collection(faces_src: list[Any]):
                coll = adsk.core.ObjectCollection.create()
                comp_occ = getattr(owner_comp, "assemblyContext", None)
                for face_obj in faces_src:
                    if face_obj is None or not getattr(face_obj, "isValid", False):
                        continue
                    candidate = face_obj
                    try:
                        face_occ = getattr(face_obj, "assemblyContext", None)
                    except Exception:
                        face_occ = None

                    try:
                        native = getattr(face_obj, "nativeObject", None)
                    except Exception:
                        native = None

                    try:
                        if comp_occ is None:
                            if face_occ is not None and native is not None and getattr(native, "isValid", False):
                                candidate = native
                        else:
                            if face_occ is None:
                                if hasattr(face_obj, "createForAssemblyContext"):
                                    prox = face_obj.createForAssemblyContext(comp_occ)
                                    if prox is not None and getattr(prox, "isValid", False):
                                        candidate = prox
                            elif face_occ != comp_occ and native is not None and getattr(native, "isValid", False):
                                if hasattr(native, "createForAssemblyContext"):
                                    prox = native.createForAssemblyContext(comp_occ)
                                    if prox is not None and getattr(prox, "isValid", False):
                                        candidate = prox
                    except Exception:
                        pass

                    if candidate is not None and getattr(candidate, "isValid", False):
                        coll.add(candidate)
                return coll

            def _face_variants(face_obj):
                variants: list[Any] = []
                seen_keys: set[str | int] = set()

                def _append_variant(candidate_obj):
                    if candidate_obj is None or not getattr(candidate_obj, "isValid", False):
                        return
                    key = _entity_token(candidate_obj) or id(candidate_obj)
                    if key in seen_keys:
                        return
                    seen_keys.add(key)
                    variants.append(candidate_obj)

                comp_occ = getattr(owner_comp, "assemblyContext", None)
                _append_variant(face_obj)

                native = None
                try:
                    native = getattr(face_obj, "nativeObject", None)
                except Exception:
                    native = None
                _append_variant(native)

                try:
                    if native is not None and comp_occ is not None and hasattr(native, "createForAssemblyContext"):
                        _append_variant(native.createForAssemblyContext(comp_occ))
                except Exception:
                    pass

                try:
                    if face_obj is not None and comp_occ is not None and hasattr(face_obj, "createForAssemblyContext"):
                        _append_variant(face_obj.createForAssemblyContext(comp_occ))
                except Exception:
                    pass

                try:
                    token = _entity_token(face_obj)
                    if token:
                        resolved = self._resolve_by_token(token, adsk.fusion.BRepFace, "face")
                        _append_variant(resolved)
                        resolved_native = getattr(resolved, "nativeObject", None) if resolved is not None else None
                        _append_variant(resolved_native)
                        if resolved_native is not None and comp_occ is not None and hasattr(resolved_native, "createForAssemblyContext"):
                            _append_variant(resolved_native.createForAssemblyContext(comp_occ))
                except Exception:
                    pass

                return variants

            face_collection = _to_face_collection(selected_faces)
            if int(getattr(face_collection, "count", 0) or 0) <= 0:
                raise RuntimeError("Post-hole threading face collection is empty")

            try:
                thread_input = thread_features.createInput(face_collection, thread_info)
            except TypeError:
                thread_input = thread_features.createInput(face_collection)
                thread_input.threadInfo = thread_info

            thread_input.isModeled = True
            thread_input.isFullLength = True

            try:
                thread_feature = thread_features.add(thread_input)
                if thread_name:
                    thread_feature.name = thread_name
                return
            except Exception as e_all:
                per_face_errors: list[str] = []
                for face_obj in selected_faces:
                    for variant in _face_variants(face_obj):
                        single_collection = _to_face_collection([variant])
                        if int(getattr(single_collection, "count", 0) or 0) <= 0:
                            continue
                        try:
                            try:
                                single_input = thread_features.createInput(single_collection, thread_info)
                            except TypeError:
                                single_input = thread_features.createInput(single_collection)
                                single_input.threadInfo = thread_info
                            single_input.isModeled = True
                            single_input.isFullLength = True
                            thread_feature = thread_features.add(single_input)
                            if thread_name:
                                thread_feature.name = thread_name
                            return
                        except Exception as e_single:
                            per_face_errors.append(f"{type(e_single).__name__}: {e_single}")

                raise RuntimeError(
                    f"Thread add failed for all selected faces; collection_error={type(e_all).__name__}: {e_all}; "
                    f"per_face_errors={per_face_errors}"
                )

        participant_bodies = _collect_participant_bodies(comp)

        plane_geom = None
        planar_entity = None

        face = None
        plane = None
        if face_id:
            try:
                face = self.GET_FACE_BY_ID(face_id)
            except Exception as e_face_lookup:
                # BRep face proxy may become stale between RESOLVE_INTERFACE and
                # HOLE_SIMPLE (Fusion API BRep regeneration).  Recovery: find the
                # nearest planar face on the component's body.
                face = self._recover_hole_anchor_face(comp, center_mm)
                if face is None:
                    raise RuntimeError(
                        f"HOLE_SIMPLE face recovery failed for {face_id}: "
                        f"original error: {e_face_lookup}"
                    ) from e_face_lookup
            if not face or not face.isValid:
                # Cached face object became invalid; attempt recovery
                face = self._recover_hole_anchor_face(comp, center_mm)
                if not face or not face.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
            if not self._is_planar_face(face):
                raise RuntimeError(
                    f"HOLE_SIMPLE requires planar face_id; got non-planar face: {face_id}"
                )
            planar_entity = face
            try:
                plane_geom = face.geometry
            except Exception:
                plane_geom = None

        if plane_id:
            plane = self._require_plane(plane_id)
            if not plane or not plane.isValid:
                raise RuntimeError(f"Plane not found or invalid: {plane_id}")
            planar_entity = plane
            try:
                plane_geom = plane.geometry
            except Exception:
                plane_geom = None

        if face is not None:
            face_participants = _collect_face_participant_bodies(face, comp)
            if int(getattr(face_participants, "count", 0) or 0) > 0:
                participant_bodies = face_participants

        if isinstance(center_mm, dict) and "sketch_point_id" in center_mm:
            sketch_point_id = center_mm.get("sketch_point_id")
            sketch_point = self._require_sketch_point(sketch_point_id)
            if not sketch_point or not sketch_point.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {sketch_point_id}")
            center_pt = sketch_point.geometry
        elif isinstance(center_mm, str):
            sketch_point = self._require_sketch_point(center_mm)
            if not sketch_point or not sketch_point.isValid:
                raise RuntimeError(f"SketchPoint not found or invalid: {center_mm}")
            center_pt = sketch_point.geometry
        else:
            center_pt = self.cm_point(
                center_mm.get("x", 0),
                center_mm.get("y", 0),
                center_mm.get("z", 0),
            )

        if plane_geom is not None:
            try:
                projected = _project_point_to_planar_entity(center_pt, plane_geom, planar_entity)
                if projected is not None:
                    center_pt = projected
                elif self.strict_mode:
                    raise RuntimeError("HOLE_SIMPLE strict projection gate failed: cannot project center onto planar entity")
            except Exception as e:
                if self.strict_mode and isinstance(e, RuntimeError):
                    raise
                # Non-strict: keep legacy behavior.
                pass

        hole_feats = comp.features.holeFeatures
        feature = None
        applied_extent = extent
        applied_diameter_mm = float(diameter_mm)
        attempt_extents: list[str] = [str(extent)]
        if extent in {"through_positive", "through_negative"}:
            opposite = "through_negative" if extent == "through_positive" else "through_positive"
            attempt_extents.append(opposite)

        requested_diameter_mm = float(diameter_mm)
        diameter_candidates_mm: list[float] = [requested_diameter_mm]
        if normalized_thread is not None:
            designation = str(normalized_thread.get("thread_designation") or "").strip()
            nominal_mm: float | None = None
            if designation.upper().startswith("M"):
                token = designation[1:]
                for sep in ("x", "X", "脳"):
                    if sep in token:
                        token = token.split(sep, 1)[0]
                        break
                try:
                    candidate = float(token)
                    if candidate > 0:
                        nominal_mm = candidate
                except Exception:
                    nominal_mm = None
            # Guardrail: never auto-enlarge hole diameter during fallback retries.
            # Only allow nominal diameter when it is not greater than requested diameter.
            if (
                isinstance(nominal_mm, float)
                and nominal_mm <= requested_diameter_mm + 1e-6
                and all(abs(nominal_mm - d) > 1e-6 for d in diameter_candidates_mm)
            ):
                diameter_candidates_mm.append(nominal_mm)

        planar_candidates: list[tuple[Any, Any, str]] = []
        planar_candidates.append((planar_entity, plane_geom, "base"))

        last_exc: Exception | None = None
        attempt_records: list[dict[str, Any]] = []
        thread_applied = normalized_thread is None
        fallback_entity = planar_entity
        fallback_center = center_pt
        fallback_extent = extent
        fallback_preferred_face = face if face is not None else None

        def _center_candidates_for_entity(base_center, entity_obj, entity_geom):
            candidates: list[tuple[Any, str]] = []
            seen_keys: set[tuple[int, int, int]] = set()

            def _append_center(pt, tag: str):
                if pt is None:
                    return
                try:
                    px = float(getattr(pt, "x", 0.0))
                    py = float(getattr(pt, "y", 0.0))
                    pz = float(getattr(pt, "z", 0.0))
                except Exception:
                    return
                key = (int(round(px * 1e6)), int(round(py * 1e6)), int(round(pz * 1e6)))
                if key in seen_keys:
                    return
                seen_keys.add(key)
                candidates.append((pt, tag))

            _append_center(base_center, "input")

            if entity_geom is not None:
                try:
                    projected = _project_point_to_planar_entity(base_center, entity_geom, entity_obj)
                    _append_center(projected, "projected_input")
                except Exception:
                    pass

            if entity_obj is not None and isinstance(entity_obj, adsk.fusion.BRepFace):
                try:
                    _append_center(getattr(entity_obj, "pointOnFace", None), "face_pointOnFace")
                except Exception:
                    pass
                try:
                    _append_center(getattr(entity_obj, "centroid", None), "face_centroid")
                except Exception:
                    pass

            return candidates

        def _try_add_hole_feature(
            *,
            anchor_entity,
            center_candidate,
            attempt_extent_value: str,
            diameter_try_mm: float,
            participants,
        ) -> tuple[Any, bool]:
            def _build_input(with_participants: bool):
                local_input = hole_feats.createSimpleInput(self.mm(diameter_try_mm))
                if with_participants:
                    try:
                        if int(getattr(participants, "count", 0) or 0) > 0 and hasattr(local_input, "participantBodies"):
                            local_input.participantBodies = participants
                    except Exception:
                        pass

                local_input.setPositionByPoint(anchor_entity, center_candidate)

                if attempt_extent_value == "distance":
                    local_input.setDistanceExtent(self.mm(float(depth_mm)))
                elif attempt_extent_value == "through_positive":
                    local_input.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
                elif attempt_extent_value == "through_negative":
                    local_input.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)
                else:
                    raise RuntimeError(f"Unsupported hole extent: {attempt_extent_value}")

                return local_input

            first_exc: Exception | None = None
            try:
                return hole_feats.add(_build_input(with_participants=True)), False
            except Exception as e:
                first_exc = e

            try:
                if int(getattr(participants, "count", 0) or 0) > 0:
                    return hole_feats.add(_build_input(with_participants=False)), True
            except Exception as e_no_part:
                raise RuntimeError(
                    f"with_participants={type(first_exc).__name__}: {first_exc}; "
                    f"without_participants={type(e_no_part).__name__}: {e_no_part}"
                )

            if first_exc is not None:
                raise first_exc
            raise RuntimeError("HOLE_SIMPLE failed to add hole feature")

        for cand_entity, cand_plane_geom, cand_tag in planar_candidates:
            if cand_entity is None:
                continue
            center_candidates = _center_candidates_for_entity(center_pt, cand_entity, cand_plane_geom)
            if not center_candidates:
                center_candidates = [(center_pt, "input")]
            for idx, attempt_extent in enumerate(attempt_extents):
                for center_try, center_tag in center_candidates:
                    fallback_entity = cand_entity
                    fallback_center = center_try
                    fallback_extent = attempt_extent
                    for diameter_try_mm in diameter_candidates_mm:
                        try:
                            feature, used_without_participants = _try_add_hole_feature(
                                anchor_entity=cand_entity,
                                center_candidate=center_try,
                                attempt_extent_value=attempt_extent,
                                diameter_try_mm=float(diameter_try_mm),
                                participants=participant_bodies,
                            )
                            applied_extent = attempt_extent
                            applied_diameter_mm = float(diameter_try_mm)
                            if (
                                idx > 0
                                or cand_tag != "base"
                                or center_tag != "input"
                                or abs(float(diameter_try_mm) - float(diameter_mm)) > 1e-6
                                or used_without_participants
                            ):
                                warning_msg = (
                                    f"HOLE_SIMPLE auto-adjusted: extent '{extent}' -> '{attempt_extent}', "
                                    f"plane_candidate='{cand_tag}', center='{center_tag}', "
                                    f"diameter_mm={float(diameter_mm)}->{float(diameter_try_mm)}"
                                )
                                if used_without_participants:
                                    warning_msg = warning_msg + "; participantBodies fallback=disabled"
                                warning = warning_msg
                            break
                        except Exception as e:
                            last_exc = e
                            attempt_records.append(
                                {
                                    "plane_candidate": cand_tag,
                                    "center_candidate": center_tag,
                                    "extent": attempt_extent,
                                    "diameter_mm": float(diameter_try_mm),
                                    "error": f"{type(e).__name__}: {e}",
                                }
                            )
                    if feature is not None:
                        break
                if feature is not None:
                    break
            if feature is not None:
                break

        if feature is not None and normalized_thread is not None:
            try:
                cyl_faces = _collect_hole_cyl_faces(comp, feature, before_snapshot)
                if not cyl_faces:
                    raise RuntimeError("No cylindrical faces found for post-hole threading")

                direction_normal = getattr(plane_geom, "normal", None) if plane_geom is not None else None
                selected_faces = _select_thread_faces(cyl_faces, center_pt, direction_normal)
                if not selected_faces:
                    raise RuntimeError("No suitable cylindrical faces selected for post-hole threading")

                thread_name = f"{name}_thread" if name else None
                _apply_post_hole_thread(selected_faces, thread_name=thread_name)

                if warning:
                    warning = warning + "; post-hole threading applied"
                else:
                    warning = "HOLE_SIMPLE strategy: plain hole + post-hole threading"
                thread_applied = True
            except Exception as e:
                last_exc = e
                attempt_records.append(
                    {
                        "plane_candidate": "post_hole_thread_apply",
                        "extent": str(applied_extent),
                        "diameter_mm": float(applied_diameter_mm),
                        "error": f"{type(e).__name__}: {e}",
                    }
                )
                raise RuntimeError(f"HOLE_SIMPLE thread_spec requested but post-hole threading failed: {type(e).__name__}: {e}")

        if feature is None and (plane_id or face_id):
            err_text = str(last_exc or "")
            err_lower = err_text.lower()
            if ("no_target_body" in err_lower) or ("logicalselection" in err_lower):
                retry_face = None
                retry_face_tag = None
                best_key: tuple[float, float] | None = None
                plane_normal = None
                anchor_label = "plane_id" if plane_id else "face_id"
                try:
                    plane_normal = getattr(plane_geom, "normal", None)
                except Exception:
                    plane_normal = None

                bodies = getattr(comp, "bRepBodies", None)
                if bodies is not None:
                    for bi in range(int(getattr(bodies, "count", 0))):
                        body = bodies.item(bi)
                        if not body or not body.isValid:
                            continue
                        faces = getattr(body, "faces", None)
                        if faces is None:
                            continue
                        for fi in range(int(getattr(faces, "count", 0))):
                            cand_face = faces.item(fi)
                            if not cand_face or not cand_face.isValid:
                                continue
                            if not self._is_planar_face(cand_face):
                                continue
                            try:
                                area = float(getattr(cand_face, "area", 0.0) or 0.0)
                            except Exception:
                                area = 0.0
                            parallel_score = 0.0
                            try:
                                if plane_normal is not None:
                                    cand_geom = getattr(cand_face, "geometry", None)
                                    cand_normal = getattr(cand_geom, "normal", None) if cand_geom is not None else None
                                    if cand_normal is not None:
                                        pn = adsk.core.Vector3D.create(float(plane_normal.x), float(plane_normal.y), float(plane_normal.z))
                                        fn = adsk.core.Vector3D.create(float(cand_normal.x), float(cand_normal.y), float(cand_normal.z))
                                        pn.normalize()
                                        fn.normalize()
                                        parallel_score = abs(float(pn.dotProduct(fn)))
                            except Exception:
                                parallel_score = 0.0

                            # Use proximity to the requested center point as a
                            # stronger tie-breaker than raw area so that the retry
                            # picks the face closest to where the hole should be
                            # (e.g. the top face at Z=20 vs bottom face at Z=0).
                            proximity_score = 0.0
                            try:
                                cand_centroid = getattr(cand_face, "centroid", None)
                                if cand_centroid is not None and center_pt is not None:
                                    dx = float(getattr(cand_centroid, "x", 0.0)) - float(getattr(center_pt, "x", 0.0))
                                    dy = float(getattr(cand_centroid, "y", 0.0)) - float(getattr(center_pt, "y", 0.0))
                                    dz = float(getattr(cand_centroid, "z", 0.0)) - float(getattr(center_pt, "z", 0.0))
                                    proximity_score = -(dx * dx + dy * dy + dz * dz)
                            except Exception:
                                proximity_score = 0.0

                            key = (parallel_score, proximity_score, area)
                            if best_key is None or key > best_key:
                                best_key = key
                                retry_face = cand_face
                                retry_face_tag = f"plane_to_face_retry_body{bi}_face{fi}"

                if retry_face is not None:
                    fallback_preferred_face = retry_face
                    retry_participant_bodies = _collect_face_participant_bodies(retry_face, comp)
                    for attempt_extent in attempt_extents:
                        try:
                            center_try = center_pt
                            try:
                                face_geom = getattr(retry_face, "geometry", None)
                                center_try = _project_point_to_planar_entity(center_pt, face_geom, retry_face)
                            except Exception:
                                pass

                            participants_for_retry = retry_participant_bodies
                            if int(getattr(participants_for_retry, "count", 0) or 0) <= 0:
                                participants_for_retry = participant_bodies

                            feature, used_without_participants = _try_add_hole_feature(
                                anchor_entity=retry_face,
                                center_candidate=center_try,
                                attempt_extent_value=attempt_extent,
                                diameter_try_mm=float(diameter_mm),
                                participants=participants_for_retry,
                            )
                            applied_extent = attempt_extent
                            warning_msg = (
                                f"HOLE_SIMPLE auto-adjusted: {anchor_label} anchor retry switched to planar face selection "
                                f"(reason='{type(last_exc).__name__}: {last_exc}', face_candidate='{retry_face_tag}', extent='{attempt_extent}')"
                            )
                            if used_without_participants:
                                warning_msg = warning_msg + "; participantBodies fallback=disabled"
                            warning = warning_msg
                            break
                        except Exception as e:
                            last_exc = e
                            attempt_records.append(
                                {
                                    "plane_candidate": retry_face_tag or "plane_to_face_retry",
                                    "extent": attempt_extent,
                                    "error": f"{type(e).__name__}: {e}",
                                }
                            )

        if feature is not None and normalized_thread is not None and not thread_applied:
            try:
                cyl_faces = _collect_hole_cyl_faces(comp, feature, before_snapshot)
                if not cyl_faces:
                    raise RuntimeError("No cylindrical faces found for post-hole threading (retry path)")

                direction_normal = getattr(plane_geom, "normal", None) if plane_geom is not None else None
                selected_faces = _select_thread_faces(cyl_faces, center_pt, direction_normal)
                if not selected_faces:
                    raise RuntimeError("No suitable cylindrical faces selected for post-hole threading (retry path)")

                thread_name = f"{name}_thread" if name else None
                _apply_post_hole_thread(selected_faces, thread_name=thread_name)

                if warning:
                    warning = warning + "; post-hole threading applied"
                else:
                    warning = "HOLE_SIMPLE strategy: plain hole + post-hole threading"
                thread_applied = True
            except Exception as e:
                last_exc = e
                attempt_records.append(
                    {
                        "plane_candidate": "post_hole_thread_apply_retry",
                        "extent": str(applied_extent),
                        "diameter_mm": float(applied_diameter_mm),
                        "error": f"{type(e).__name__}: {e}",
                    }
                )
                raise RuntimeError(
                    f"HOLE_SIMPLE thread_spec requested but post-hole threading failed (retry path): {type(e).__name__}: {e}"
                )

        if feature is None:
            e = last_exc if last_exc is not None else RuntimeError("Unknown HOLE_SIMPLE failure")

            fallback_exc: Exception | None = None
            try:
                sketch_entity = fallback_entity
                if fallback_preferred_face is not None and getattr(fallback_preferred_face, "isValid", False):
                    sketch_entity = fallback_preferred_face

                sketch_center_model = fallback_center
                try:
                    sketch_geom = getattr(sketch_entity, "geometry", None)
                    if sketch_geom is not None:
                        sketch_center_model = _project_point_to_planar_entity(fallback_center, sketch_geom, sketch_entity)
                except Exception:
                    pass

                sketch_name = f"hole_fallback_{self._feature_counter.get(component_id, 0) + 1}"
                sketch = comp.sketches.add(sketch_entity)
                sketch.name = sketch_name

                sketch_center = sketch.modelToSketchSpace(sketch_center_model)
                if sketch_center is None:
                    raise RuntimeError("modelToSketchSpace returned None in HOLE_SIMPLE fallback")

                before_count = int(sketch.profiles.count)
                sketch.sketchCurves.sketchCircles.addByCenterRadius(
                    sketch_center,
                    float(diameter_mm) / 20.0,
                )
                after_count = int(sketch.profiles.count)

                if after_count <= before_count:
                    raise RuntimeError(
                        f"HOLE_SIMPLE fallback profile count mismatch: before={before_count}, after={after_count}"
                    )
                profile = sketch.profiles.item(before_count)

                extrudes = comp.features.extrudeFeatures

                fallback_extent_s = str(fallback_extent or "").lower()
                through_extents = {"through", "through_all", "through_positive", "through_negative"}
                body_side_dot = None
                try:
                    sketch_normal = None
                    sketch_geom = getattr(sketch_entity, "geometry", None)
                    if sketch_geom is not None:
                        sketch_normal = getattr(sketch_geom, "normal", None)
                    if sketch_normal is not None:
                        nearest_body_center = None
                        nearest_dist2 = None
                        bodies = getattr(comp, "bRepBodies", None)
                        if bodies is not None:
                            for bi in range(int(getattr(bodies, "count", 0) or 0)):
                                body = bodies.item(bi)
                                if not body or not getattr(body, "isValid", False):
                                    continue
                                bb = getattr(body, "boundingBox", None)
                                if bb is None:
                                    continue
                                min_pt = getattr(bb, "minPoint", None)
                                max_pt = getattr(bb, "maxPoint", None)
                                if min_pt is None or max_pt is None:
                                    continue
                                cx = (float(min_pt.x) + float(max_pt.x)) * 0.5
                                cy = (float(min_pt.y) + float(max_pt.y)) * 0.5
                                cz = (float(min_pt.z) + float(max_pt.z)) * 0.5
                                dx = cx - float(sketch_center_model.x)
                                dy = cy - float(sketch_center_model.y)
                                dz = cz - float(sketch_center_model.z)
                                dist2 = dx * dx + dy * dy + dz * dz
                                if nearest_dist2 is None or dist2 < nearest_dist2:
                                    nearest_dist2 = dist2
                                    nearest_body_center = (cx, cy, cz)

                        if nearest_body_center is not None:
                            vx = float(nearest_body_center[0]) - float(sketch_center_model.x)
                            vy = float(nearest_body_center[1]) - float(sketch_center_model.y)
                            vz = float(nearest_body_center[2]) - float(sketch_center_model.z)
                            body_side_dot = (
                                float(sketch_normal.x) * vx
                                + float(sketch_normal.y) * vy
                                + float(sketch_normal.z) * vz
                            )
                except Exception:
                    body_side_dot = None

                direction_label = self._resolve_hole_fallback_direction_label(
                    fallback_extent_s,
                    direction_hint_raw,
                    body_side_dot,
                )
                direction_labels: list[str] = [direction_label]
                opposite_direction = "negative" if direction_label == "positive" else "positive"
                if opposite_direction not in direction_labels:
                    direction_labels.append(opposite_direction)

                def _direction_enum(label: str):
                    return (
                        adsk.fusion.ExtentDirections.NegativeExtentDirection
                        if str(label).lower() == "negative"
                        else adsk.fusion.ExtentDirections.PositiveExtentDirection
                    )

                fallback_feature = None
                fallback_attempt_errors: list[str] = []

                def _try_fallback_cut(*, direction_lbl: str, mode: str, depth_try_mm: float | None = None):
                    local_input = extrudes.createInput(
                        profile,
                        adsk.fusion.FeatureOperations.CutFeatureOperation,
                    )
                    try:
                        if int(getattr(participant_bodies, "count", 0) or 0) > 0 and hasattr(local_input, "participantBodies"):
                            local_input.participantBodies = participant_bodies
                    except Exception:
                        pass
                    if mode == "through":
                        extent_def = adsk.fusion.ThroughAllExtentDefinition.create()
                        local_input.setOneSideExtent(extent_def, _direction_enum(direction_lbl))
                    elif mode == "distance":
                        if depth_try_mm is None or float(depth_try_mm) <= 0:
                            raise RuntimeError("HOLE_SIMPLE fallback requires depth_mm > 0 for distance extent")
                        distance_extent = adsk.fusion.DistanceExtentDefinition.create(self.mm(float(depth_try_mm)))
                        local_input.setOneSideExtent(distance_extent, _direction_enum(direction_lbl))
                    else:
                        raise RuntimeError(f"Unsupported fallback mode: {mode}")
                    return extrudes.add(local_input)

                if fallback_extent_s in through_extents:
                    for dlabel in direction_labels:
                        try:
                            fallback_feature = _try_fallback_cut(direction_lbl=dlabel, mode="through")
                            break
                        except Exception as ex_try:
                            fallback_attempt_errors.append(f"through/{dlabel}: {type(ex_try).__name__}: {ex_try}")
                    if fallback_feature is None:
                        probe_depth_mm = max(100.0, float(diameter_mm) * 20.0)
                        for dlabel in direction_labels:
                            try:
                                fallback_feature = _try_fallback_cut(
                                    direction_lbl=dlabel,
                                    mode="distance",
                                    depth_try_mm=probe_depth_mm,
                                )
                                break
                            except Exception as ex_try:
                                fallback_attempt_errors.append(
                                    f"distance({probe_depth_mm})/{dlabel}: {type(ex_try).__name__}: {ex_try}"
                                )
                elif fallback_extent_s == "distance":
                    if depth_mm is None or float(depth_mm) <= 0:
                        raise RuntimeError("HOLE_SIMPLE fallback requires depth_mm > 0 for distance extent")
                    for dlabel in direction_labels:
                        try:
                            fallback_feature = _try_fallback_cut(
                                direction_lbl=dlabel,
                                mode="distance",
                                depth_try_mm=float(depth_mm),
                            )
                            break
                        except Exception as ex_try:
                            fallback_attempt_errors.append(
                                f"distance({float(depth_mm)})/{dlabel}: {type(ex_try).__name__}: {ex_try}"
                            )
                else:
                    raise RuntimeError(f"Unsupported fallback extent in HOLE_SIMPLE: {fallback_extent}")

                if fallback_feature is None:
                    raise RuntimeError(
                        "HOLE_SIMPLE fallback sketch+extrude failed; attempts=" + " | ".join(fallback_attempt_errors)
                    )
                if name:
                    fallback_feature.name = f"{name}_fallback"

                feature_id = self._next_feature_id(component_id, "hole_fallback_extrude_cut")
                self._cache_feature(feature_id, fallback_feature)
                extra = {
                    "warning": "HOLE_SIMPLE failed; fallback sketch+extrude_cut applied",
                    "fallback": "hole_fallback_extrude_cut",
                }
                return self._ret_feature(feature_id=feature_id, extra=extra)
            except Exception as fe:
                fallback_exc = fe

            try:
                import json as _json

                face_summary = None
                try:
                    if face_id and face is not None:
                        face_summary = self._face_geometry_summary(face_id, face)
                except Exception:
                    face_summary = None

                debug = {
                    "component_id": component_id,
                    "face_id": face_id,
                    "plane_id": plane_id,
                    "diameter_mm": float(diameter_mm) if isinstance(diameter_mm, (int, float)) else diameter_mm,
                    "applied_diameter_mm": float(applied_diameter_mm) if isinstance(applied_diameter_mm, (int, float)) else applied_diameter_mm,
                    "center_mm": center_mm,
                    "extent": extent,
                    "attempt_extents": attempt_extents,
                    "attempt_records": attempt_records,
                    "fallback_error": f"{type(fallback_exc).__name__}: {fallback_exc}" if fallback_exc is not None else None,
                    "depth_mm": depth_mm,
                    "face_summary": face_summary,
                }
                raise RuntimeError(
                    f"HOLE_SIMPLE failed: {type(e).__name__}: {e}; debug={_json.dumps(debug, ensure_ascii=False)}"
                )
            except Exception:
                raise
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "hole")
        self._cache_feature(feature_id, feature)
        cyl_face_ids: list[str] = []
        try:
            cyl_faces = _collect_hole_cyl_faces(comp, feature, before_snapshot)
            for idx, cyl_face in enumerate(cyl_faces):
                cache_face_id = f"{feature_id}:face:cyl:{idx + 1}"
                self._cache_face(cache_face_id, cyl_face)
                cyl_face_ids.append(cache_face_id)
        except Exception:
            cyl_face_ids = []

        extra = None
        if warning:
            extra = {"warning": warning}
        if cyl_face_ids:
            if extra is None:
                extra = {}
            extra["cyl_face_ids"] = cyl_face_ids
        return self._ret_feature(feature_id=feature_id, extra=extra)

    def HOLE_COUNTERBORE(
        self,
        component_id: str,
        face_id: str,
        center_mm: dict,
        hole_diameter_mm: float,
        cbore_diameter_mm: float,
        cbore_depth_mm: float,
        extent: str = "distance",
        depth_mm: float | None = None,
        name: str | None = None,
    ) -> dict:
        """鍦ㄦ寚瀹氶潰涓婇捇娌夊瓟锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        valid_extents = ["distance", "through_positive", "through_negative"]
        if extent not in valid_extents:
            raise RuntimeError(
                f"Invalid extent '{extent}'; must be one of: {valid_extents}"
            )

        if extent == "distance":
            if depth_mm is None or depth_mm <= 0:
                raise RuntimeError(
                    f"extent='distance' requires depth_mm > 0, got: {depth_mm}"
                )
        elif extent.startswith("through"):
            if depth_mm is not None:
                raise RuntimeError(
                    f"extent='{extent}' must not have depth_mm; got: {depth_mm}"
                )

        comp = self._require_component(component_id)
        face = self.GET_FACE_BY_ID(face_id)

        center_pt = self.cm_point(
            center_mm.get("x", 0),
            center_mm.get("y", 0),
            center_mm.get("z", 0),
        )

        hole_feats = comp.features.holeFeatures
        hole_input = hole_feats.createCounterboreInput(
            self.mm(hole_diameter_mm),
            self.mm(cbore_diameter_mm),
            self.mm(cbore_depth_mm),
        )
        hole_input.setPositionByPoint(face, center_pt)

        if extent == "distance":
            hole_input.setDistanceExtent(self.mm(depth_mm))
        elif extent == "through_positive":
            hole_input.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
        elif extent == "through_negative":
            hole_input.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)

        feature = hole_feats.add(hole_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "hole_cbore")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def HOLE_COUNTERSINK(
        self,
        component_id: str,
        face_id: str,
        center_mm: dict,
        hole_diameter_mm: float,
        csink_diameter_mm: float,
        csink_angle_rad: float,
        extent: str = "distance",
        depth_mm: float | None = None,
        name: str | None = None,
    ) -> dict:
        """鍦ㄦ寚瀹氶潰涓婇捇娌夊ご瀛旓紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        valid_extents = ["distance", "through_positive", "through_negative"]
        if extent not in valid_extents:
            raise RuntimeError(
                f"Invalid extent '{extent}'; must be one of: {valid_extents}"
            )

        if extent == "distance":
            if depth_mm is None or depth_mm <= 0:
                raise RuntimeError(
                    f"extent='distance' requires depth_mm > 0, got: {depth_mm}"
                )
        elif extent.startswith("through"):
            if depth_mm is not None:
                raise RuntimeError(
                    f"extent='{extent}' must not have depth_mm; got: {depth_mm}"
                )

        comp = self._require_component(component_id)
        face = self.GET_FACE_BY_ID(face_id)

        center_pt = self.cm_point(
            center_mm.get("x", 0),
            center_mm.get("y", 0),
            center_mm.get("z", 0),
        )

        hole_feats = comp.features.holeFeatures
        hole_input = hole_feats.createCountersinkInput(
            self.mm(hole_diameter_mm),
            self.mm(csink_diameter_mm),
            adsk.core.ValueInput.createByReal(csink_angle_rad),
        )
        hole_input.setPositionByPoint(face, center_pt)

        if extent == "distance":
            hole_input.setDistanceExtent(self.mm(depth_mm))
        elif extent == "through_positive":
            hole_input.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
        elif extent == "through_negative":
            hole_input.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)

        feature = hole_feats.add(hole_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "hole_csink")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def THREAD_ON_CYLINDRICAL_FACES(
        self,
        component_id: str,
        face_ids: list,
        is_internal: bool,
        thread_type: str,
        thread_designation: str,
        thread_class: str,
        is_modeled: bool = False,
        is_full_length: bool = True,
        thread_length_mm: float = None,
        name: str = None,
    ) -> dict:
        """
        Create Thread feature on one or more cylindrical faces.

        - thread_type / designation / class should use Fusion's internal names (English).
        - Uses modern ThreadDataQuery.create() pathway (threadDataQuery property retired Sep 2025).
        """
        # validate inputs & ids
        comp = self._require_component(component_id)
        feats = comp.features
        thread_feats = feats.threadFeatures

        if not face_ids or not isinstance(face_ids, list):
            self._fail("THREAD_ON_CYLINDRICAL_FACES requires non-empty face_ids list")

        cyl_faces = adsk.core.ObjectCollection.create()
        for fid in face_ids:
            f = self._require_face(fid)
            cyl_faces.add(f)

        # --- thread info (type/designation/class) ---
        tdq = adsk.fusion.ThreadDataQuery.create()

        all_types = tdq.allThreadTypes
        if thread_type not in all_types:
            self._fail(f"Unknown thread_type: {thread_type}. Example types: {all_types[:5]}")

        thread_info = thread_feats.createThreadInfo(
            bool(is_internal),
            thread_type,
            thread_designation,
            thread_class,
        )

        # Create input (API equivalent to Thread dialog)
        # Newer Fusion API requires threadInfo in createInput; keep compatibility with older signature.
        try:
            thread_input = thread_feats.createInput(cyl_faces, thread_info)
        except TypeError:
            thread_input = thread_feats.createInput(cyl_faces)
            thread_input.threadInfo = thread_info

        thread_input.isModeled = bool(is_modeled)
        thread_input.isFullLength = bool(is_full_length)

        if not is_full_length:
            if thread_length_mm is None:
                self._fail("thread_length_mm is required when is_full_length is False")
            thread_input.threadLength = self.mm(thread_length_mm)

        feature = thread_feats.add(thread_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "thread")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def SHELL_BODIES(
        self,
        component_id: str,
        body_id: str,
        thickness_mm: float,
        remove_face_ids: list[str] | None = None,
        is_tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """瀵硅韩浣撹繘琛屽３浣撳寲澶勭悊锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body not found or invalid: {body_id}")

        input_entities = adsk.core.ObjectCollection.create()

        if remove_face_ids:
            for face_id in remove_face_ids:
                face = self._require_face(face_id)
                if not face or not face.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
                input_entities.add(face)
        else:
            # When no faces to remove, the body itself must be included so
            # the API knows which body to shell.
            input_entities.add(body)

        shell_feats = comp.features.shellFeatures
        shell_input = shell_feats.createInput(input_entities, bool(is_tangent_chain))
        shell_input.insideThickness = self.mm(thickness_mm)

        feature = shell_feats.add(shell_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "shell")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def SPLIT_FACE_WITH_FACE(
        self,
        component_id: str,
        face_ids_to_split: list,
        tool_face_id: str,
        extend_splitting_tool: bool = True,
        name: str = None,
    ) -> dict:
        """浣跨敤闈㈠垎鍓查潰"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        feats = comp.features
        split_feats = feats.splitFaceFeatures

        if not face_ids_to_split:
            self._fail("SPLIT_FACE_WITH_FACE requires non-empty face_ids_to_split")

        faces = adsk.core.ObjectCollection.create()
        for fid in face_ids_to_split:
            faces.add(self._require_face(fid))

        tool_faces = adsk.core.ObjectCollection.create()
        tool_faces.add(self._require_face(tool_face_id))

        split_input = split_feats.createInput(faces, tool_faces, bool(extend_splitting_tool))
        feature = split_feats.add(split_input)

        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "split_face")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def SPLIT_FACE_WITH_CURVES(
        self,
        component_id: str,
        face_ids_to_split: list,
        curve_ids: list,
        extend_splitting_tool: bool = True,
        split_type: str = "closest_point",
        name: str = None,
    ) -> dict:
        """浣跨敤鏇茬嚎鍒嗗壊闈?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        feats = comp.features
        split_feats = feats.splitFaceFeatures

        if not face_ids_to_split:
            self._fail("SPLIT_FACE_WITH_CURVES requires non-empty face_ids_to_split")
        if not curve_ids:
            self._fail("SPLIT_FACE_WITH_CURVES requires non-empty curve_ids")

        faces = adsk.core.ObjectCollection.create()
        for fid in face_ids_to_split:
            faces.add(self._require_face(fid))

        curves = adsk.core.ObjectCollection.create()
        for cid in curve_ids:
            curves.add(self._require_curve(cid))

        split_input = split_feats.createInput(faces, curves, bool(extend_splitting_tool))

        if split_type == "closest_point":
            split_input.setClosestPointSplitType()
        elif split_type == "surface":
            # Surface-to-surface intersection. If split tool is curve, Fusion will extrude it to a surface as documented.
            split_input.setSurfaceIntersectionSplitType(bool(extend_splitting_tool))
        else:
            self._fail(f"Unknown split_type: {split_type}")

        feature = split_feats.add(split_input)

        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "split_face")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def SPLIT_BODY_BY_PLANE(
        self,
        component_id: str,
        body_ids: list,
        plane_id: str,
        extend_splitting_tool: bool = True,
        name: str | None = None,
    ) -> dict:
        """Split bodies by a construction plane."""
        # validate inputs & ids
        if not body_ids:
            raise RuntimeError("SPLIT_BODY_BY_PLANE requires non-empty body_ids")

        comp = self._require_component(component_id)
        plane_obj = self._require_plane(plane_id)
        if not plane_obj or not plane_obj.isValid:
            raise RuntimeError(f"Construction plane not found or invalid: {plane_id}")

        splits = comp.features.splitBodyFeatures
        feature_ids = []
        for body_id in body_ids:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            split_input = splits.createInput(body, plane_obj, bool(extend_splitting_tool))
            feature = splits.add(split_input)
            if name:
                feature.name = name
            feature_id = self._next_feature_id(component_id, "split_body")
            self._cache_feature(feature_id, feature)
            feature_ids.append(feature_id)

        return self._ret_feature(feature_ids=feature_ids)

    def SPLIT_BODY_BY_TOOL_BODY(
        self,
        component_id: str,
        target_body_ids: list,
        tool_body_id: str,
        extend_splitting_tool: bool = True,
        name: str | None = None,
    ) -> dict:
        """Split bodies by another body as the splitting tool."""
        # validate inputs & ids
        if not target_body_ids:
            raise RuntimeError("SPLIT_BODY_BY_TOOL_BODY requires non-empty target_body_ids")

        comp = self._require_component(component_id)
        tool_body = self._require_body(tool_body_id)
        if not tool_body or not tool_body.isValid:
            raise RuntimeError(f"Tool body not found or invalid: {tool_body_id}")

        splits = comp.features.splitBodyFeatures
        feature_ids = []
        for body_id in target_body_ids:
            target_body = self._require_body(body_id)
            if not target_body or not target_body.isValid:
                raise RuntimeError(f"Body not found or invalid: {body_id}")
            split_input = splits.createInput(target_body, tool_body, bool(extend_splitting_tool))
            feature = splits.add(split_input)
            if name:
                feature.name = name
            feature_id = self._next_feature_id(component_id, "split_body")
            self._cache_feature(feature_id, feature)
            feature_ids.append(feature_id)

        return self._ret_feature(feature_ids=feature_ids)

    def DRAFT_FACES(
        self,
        component_id: str,
        face_ids: list[str],
        neutral_plane: dict,
        pull_direction: dict,
        angle_rad: float,
        is_tangent_chain: bool = True,
        name: str | None = None,
    ) -> dict:
        """瀵归潰杩涜鎷旀ā锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        if not face_ids:
            raise RuntimeError("DRAFT_FACES requires non-empty face_ids")

        comp = self._require_component(component_id)

        faces = adsk.core.ObjectCollection.create()
        for face_id in face_ids:
            face = self.GET_FACE_BY_ID(face_id)
            faces.add(face)

        neutral_plane_obj = None
        if isinstance(neutral_plane, dict):
            plane_type = neutral_plane.get("type")
            plane_id = neutral_plane.get("plane_id")
            if plane_type == "XY":
                neutral_plane_obj = comp.xYConstructionPlane
            elif plane_type == "XZ":
                neutral_plane_obj = comp.xZConstructionPlane
            elif plane_type == "YZ":
                neutral_plane_obj = comp.yZConstructionPlane
            elif plane_id:
                neutral_plane_obj = self._require_plane(plane_id)
                if not neutral_plane_obj or not neutral_plane_obj.isValid:
                    raise RuntimeError(
                        f"Construction plane not found or invalid: {plane_id}"
                    )

        if not neutral_plane_obj:
            raise RuntimeError("DRAFT_FACES requires a valid neutral plane")

        pull_axis = None
        if isinstance(pull_direction, dict):
            axis_id = pull_direction.get("axis_id")
            axis_name = pull_direction.get("axis")
            if axis_id:
                pull_axis = self._require_axis(axis_id)
                if not pull_axis or not pull_axis.isValid:
                    raise RuntimeError(f"Axis not found or invalid: {axis_id}")
            elif axis_name == "X":
                pull_axis = comp.xConstructionAxis
            elif axis_name == "Y":
                pull_axis = comp.yConstructionAxis
            elif axis_name == "Z":
                pull_axis = comp.zConstructionAxis

        if not pull_axis:
            raise RuntimeError("DRAFT_FACES requires a valid pull direction")

        drafts = comp.features.draftFeatures
        angle_input = adsk.core.ValueInput.createByReal(angle_rad)
        draft_input = drafts.createInput(
            faces,
            neutral_plane_obj,
            bool(is_tangent_chain),
        )
        draft_input.setSingleAngle(False, angle_input)

        feature = drafts.add(draft_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "draft")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def OFFSET_SKETCH_CURVES(
        self,
        sketch_id: str,
        curve_ids: list[str],
        offset_mm: float,
        direction_point: dict | None = None,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓亸绉绘洸绾匡紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        if not curve_ids:
            raise RuntimeError("OFFSET_SKETCH_CURVES requires non-empty curve_ids")

        if direction_point is None:
            raise RuntimeError("OFFSET_SKETCH_CURVES requires direction_point")

        sketch.isComputeDeferred = True
        try:
            curve_collection = adsk.core.ObjectCollection.create()
            for curve_id in curve_ids:
                curve = self._require_curve(curve_id)
                if not curve or not curve.isValid:
                    raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
                curve_collection.add(curve)

            direction_pt = self.cm_point(
                direction_point.get("x", 0),
                direction_point.get("y", 0),
                direction_point.get("z", 0),
            )
            offset_cm = float(offset_mm) / 10.0
            new_curves = sketch.sketchCurves.offset(curve_collection, direction_pt, offset_cm)

            created_curves = []
            if hasattr(new_curves, "count"):
                for i in range(new_curves.count):
                    created_curves.append(new_curves.item(i))
            elif isinstance(new_curves, (list, tuple)):
                created_curves.extend(new_curves)
            elif new_curves is not None:
                created_curves.append(new_curves)

            if not created_curves:
                raise RuntimeError("OFFSET_SKETCH_CURVES produced no curves")

            new_curve_ids = []
            for curve in created_curves:
                curve.isConstruction = construction
                new_curve_id = self._next_curve_id(sketch_id, "offset")
                self._curves[new_curve_id] = curve
                new_curve_ids.append(new_curve_id)
            return self._ret_sketch(curve_ids=new_curve_ids)
        finally:
            sketch.isComputeDeferred = False

    def TRIM_SKETCH_CURVE(self, curve_id: str, trim_point: dict) -> dict:
        """Trim a sketch curve at a point.

        Fusion 360 API does not provide SketchCurve.trim().
        Official approach: split the curve at the nearest parameter, then
        delete the segment closest to *trim_point*.

        Uses ``SketchCurve.split()`` (available since ~Fusion 2023) with a
        ``deleteMe()`` follow-up.  If ``split`` is not available on the
        runtime version, falls back to deleting the entire curve (best-effort
        trim semantics).
        """
        # validate inputs & ids
        curve = self._require_curve(curve_id)
        if not curve or not curve.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")

        parent_sketch = curve.parentSketch
        if not parent_sketch:
            raise RuntimeError("TRIM_SKETCH_CURVE cannot resolve parent sketch")

        sketch_id = self._sketch_id_by_obj.get(id(parent_sketch))
        if not sketch_id:
            raise RuntimeError("Parent sketch id not found for curve")

        trim_pt = self.cm_point(
            trim_point.get("x", 0),
            trim_point.get("y", 0),
            trim_point.get("z", 0),
        )

        # Collect curves before the operation so we can identify new segments
        before_curves: set[int] = set()
        for col_name in ("sketchLines", "sketchArcs", "sketchCircles",
                         "sketchFittedSplines", "sketchConicCurves",
                         "sketchEllipses"):
            col = getattr(parent_sketch.sketchCurves, col_name, None)
            if col:
                for i in range(col.count):
                    before_curves.add(id(col.item(i)))

        # ----- Primary path: SketchCurve.split() (Fusion 2023+) -----
        if hasattr(curve, "split"):
            try:
                curve.split(trim_pt)
            except Exception:
                pass  # fall through to deleteMe fallback

        # Remove the old curve id from cache
        if curve_id in self._curves:
            del self._curves[curve_id]

        # Identify surviving / new segments
        remaining_curves: list = []
        for col_name in ("sketchLines", "sketchArcs", "sketchCircles",
                         "sketchFittedSplines", "sketchConicCurves",
                         "sketchEllipses"):
            col = getattr(parent_sketch.sketchCurves, col_name, None)
            if col:
                for i in range(col.count):
                    item = col.item(i)
                    if id(item) not in before_curves and item.isValid:
                        remaining_curves.append(item)

        # If split produced new segments, find the one nearest to trim_pt
        # and delete it (= the portion being trimmed away).
        if remaining_curves:
            import math
            def _dist_to_curve(c):
                try:
                    ev = c.geometry.evaluator
                    ok, sp, ep = ev.getEndPoints()
                    if ok:
                        # Use midpoint of start/end as representative point
                        mx = (sp.x + ep.x) / 2.0
                        my = (sp.y + ep.y) / 2.0
                        mz = (sp.z + ep.z) / 2.0
                        return math.sqrt(
                            (mx - trim_pt.x) ** 2
                            + (my - trim_pt.y) ** 2
                            + (mz - trim_pt.z) ** 2
                        )
                except Exception:
                    pass
                return 1e30

            remaining_curves.sort(key=_dist_to_curve)
            # Delete the segment closest to the trim point
            try:
                remaining_curves[0].deleteMe()
            except Exception:
                pass
            remaining_curves = remaining_curves[1:]  # keep the rest
        else:
            # split() was unavailable or no-op 鈫?best-effort: delete the
            # original curve entirely
            if curve.isValid:
                try:
                    curve.deleteMe()
                except Exception:
                    pass

        # Register surviving new segments
        new_curve_ids: list[str] = []
        for new_curve in remaining_curves:
            if new_curve.isValid:
                new_curve_id = self._next_curve_id(sketch_id, "trim")
                self._curves[new_curve_id] = new_curve
                new_curve_ids.append(new_curve_id)

        result_curve_id = new_curve_ids[0] if len(new_curve_ids) == 1 else None
        return self._ret_sketch(curve_id=result_curve_id, curve_ids=new_curve_ids)

    def SKETCH_FILLET(
        self,
        sketch_id: str,
        curve_id_a: str,
        curve_id_b: str,
        point_on_a: dict,
        point_on_b: dict,
        radius_mm: float,
        construction: bool = False,
    ) -> dict:
        """鍦?sketch 涓€掑渾瑙掞紙杈撳叆鍗曚綅涓?mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        curve_a = self._require_curve(curve_id_a)
        curve_b = self._require_curve(curve_id_b)
        if not curve_a or not curve_a.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_a}")
        if not curve_b or not curve_b.isValid:
            raise RuntimeError(f"SketchCurve not found or invalid: {curve_id_b}")
        if curve_a.parentSketch != sketch or curve_b.parentSketch != sketch:
            raise RuntimeError("SKETCH_FILLET curves must belong to the specified sketch")

        point_a = self.cm_point(
            point_on_a.get("x", 0),
            point_on_a.get("y", 0),
            point_on_a.get("z", 0),
        )
        point_b = self.cm_point(
            point_on_b.get("x", 0),
            point_on_b.get("y", 0),
            point_on_b.get("z", 0),
        )
        radius_cm = float(radius_mm) / 10.0

        fillet_curve = sketch.sketchCurves.sketchArcs.addFillet(curve_a, point_a, curve_b, point_b, radius_cm)
        fillet_curve.isConstruction = construction

        curve_id = self._next_curve_id(sketch_id, "fillet")
        self._curves[curve_id] = fillet_curve
        return self._ret_sketch(curve_id=curve_id)

    def SKETCH_PROFILE_FROM_EDGES(self, sketch_id: str, edge_curve_ids: list[str]) -> dict:
        """浠庡凡鏈?sketch 鏇茬嚎鍒涘缓 profile"""
        # validate inputs & ids
        if not edge_curve_ids:
            raise RuntimeError("SKETCH_PROFILE_FROM_EDGES requires non-empty edge_curve_ids")

        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        curves = adsk.core.ObjectCollection.create()
        for curve_id in edge_curve_ids:
            curve = self._require_curve(curve_id)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {curve_id}")
            if curve.parentSketch != sketch:
                raise RuntimeError("SKETCH_PROFILE_FROM_EDGES curves must belong to the specified sketch")
            curves.add(curve)

        profiles = sketch.profiles
        profile = None
        if hasattr(profiles, "add"):
            profile = profiles.add(curves)
        else:
            before_count = profiles.count
            if hasattr(sketch, "evaluate"):
                sketch.evaluate()
            after_count = profiles.count
            if after_count <= before_count:
                raise RuntimeError("No new profile was created; curves may not form a closed loop")
            profile = profiles.item(after_count - 1)

        if not profile or not profile.isValid:
            raise RuntimeError("SKETCH_PROFILE_FROM_EDGES failed to create a valid profile")

        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)

    @staticmethod
    def _reflect_point_across_line(
        pt: adsk.core.Point3D,
        line_start: adsk.core.Point3D,
        line_end: adsk.core.Point3D,
    ) -> adsk.core.Point3D:
        """Reflect *pt* across the infinite line through *line_start* 鈫?*line_end*.

        All coordinates are in the same unit system (cm inside Fusion).
        Works in the 2-D sketch plane (uses x/y, preserves z from *pt*).
        """
        import math
        dx = line_end.x - line_start.x
        dy = line_end.y - line_start.y
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-14:
            return adsk.core.Point3D.create(pt.x, pt.y, pt.z)
        # vector from line_start to pt
        apx = pt.x - line_start.x
        apy = pt.y - line_start.y
        t = (apx * dx + apy * dy) / len_sq
        # closest point on line
        cx = line_start.x + t * dx
        cy = line_start.y + t * dy
        # reflection
        return adsk.core.Point3D.create(2.0 * cx - pt.x, 2.0 * cy - pt.y, pt.z)

    def SKETCH_MIRROR(self, sketch_id: str, curve_ids: list[str], mirror_line_curve_id: str) -> dict:
        """Mirror sketch curves across a line by recreating reflected geometry.

        Fusion 360 API does not expose Sketch.mirror() or SketchCurves.mirror().
        This implementation reflects each curve's control points across the
        mirror line and creates new SketchLine / SketchCircle / SketchArc /
        SketchFittedSpline entities accordingly.
        """
        import math
        # validate inputs & ids
        if not curve_ids:
            raise RuntimeError("SKETCH_MIRROR requires non-empty curve_ids")

        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        mirror_line = self._require_curve(mirror_line_curve_id)
        if not mirror_line or not mirror_line.isValid:
            raise RuntimeError(f"Mirror line not found or invalid: {mirror_line_curve_id}")
        if mirror_line.parentSketch != sketch:
            raise RuntimeError("SKETCH_MIRROR mirror line must belong to the specified sketch")

        # Resolve mirror line endpoints
        line_start = mirror_line.startSketchPoint.geometry
        line_end = mirror_line.endSketchPoint.geometry

        source_curves = []
        for cid in curve_ids:
            curve = self._require_curve(cid)
            if not curve or not curve.isValid:
                raise RuntimeError(f"SketchCurve not found or invalid: {cid}")
            if curve.parentSketch != sketch:
                raise RuntimeError("SKETCH_MIRROR curves must belong to the specified sketch")
            source_curves.append(curve)

        reflect = self._reflect_point_across_line
        new_curve_ids: list[str] = []

        for curve in source_curves:
            created = None
            geo = curve.geometry  # underlying Curve3D

            # --- SketchLine ---
            if isinstance(geo, adsk.core.Line3D):
                sp = reflect(curve.startSketchPoint.geometry, line_start, line_end)
                ep = reflect(curve.endSketchPoint.geometry, line_start, line_end)
                created = sketch.sketchCurves.sketchLines.addByTwoPoints(sp, ep)

            # --- SketchCircle (full circle) ---
            elif isinstance(geo, adsk.core.Circle3D):
                center = reflect(geo.center, line_start, line_end)
                created = sketch.sketchCurves.sketchCircles.addByCenterRadius(
                    center, geo.radius
                )

            # --- SketchArc ---
            elif isinstance(geo, adsk.core.Arc3D):
                sp = reflect(geo.startPoint, line_start, line_end)
                ep = reflect(geo.endPoint, line_start, line_end)
                # mid-point of the arc for 3-point reconstruction
                eval_ok, mid_pt = curve.geometry.evaluator.getPointAtParameter(
                    (curve.geometry.evaluator.getParameterExtents()[1]
                     + curve.geometry.evaluator.getParameterExtents()[2]) / 2.0
                )
                if not eval_ok:
                    mid_pt = adsk.core.Point3D.create(
                        (geo.startPoint.x + geo.endPoint.x) / 2.0,
                        (geo.startPoint.y + geo.endPoint.y) / 2.0,
                        (geo.startPoint.z + geo.endPoint.z) / 2.0,
                    )
                mp = reflect(mid_pt, line_start, line_end)
                created = sketch.sketchCurves.sketchArcs.addByThreePoints(sp, mp, ep)

            # --- SketchEllipse / SketchEllipticalArc ---
            elif isinstance(geo, (adsk.core.Ellipse3D, adsk.core.EllipticalArc3D)):
                # Approximate with a fitted spline through evaluated points
                evaluator = curve.geometry.evaluator
                _, p_start, p_end = evaluator.getParameterExtents()
                pts = adsk.core.ObjectCollection.create()
                n_samples = 32
                for i in range(n_samples + 1):
                    t = p_start + (p_end - p_start) * i / n_samples
                    ok, pt = evaluator.getPointAtParameter(t)
                    if ok:
                        pts.add(reflect(pt, line_start, line_end))
                created = sketch.sketchCurves.sketchFittedSplines.add(pts)

            # --- SketchFittedSpline / NurbsCurve3D ---
            elif isinstance(geo, adsk.core.NurbsCurve3D):
                evaluator = curve.geometry.evaluator
                _, p_start, p_end = evaluator.getParameterExtents()
                pts = adsk.core.ObjectCollection.create()
                n_samples = max(16, geo.controlPointCount * 4)
                for i in range(n_samples + 1):
                    t = p_start + (p_end - p_start) * i / n_samples
                    ok, pt = evaluator.getPointAtParameter(t)
                    if ok:
                        pts.add(reflect(pt, line_start, line_end))
                created = sketch.sketchCurves.sketchFittedSplines.add(pts)

            else:
                # Generic fallback: sample the curve evaluator and create a spline
                evaluator = curve.geometry.evaluator
                _, p_start, p_end = evaluator.getParameterExtents()
                pts = adsk.core.ObjectCollection.create()
                n_samples = 24
                for i in range(n_samples + 1):
                    t = p_start + (p_end - p_start) * i / n_samples
                    ok, pt = evaluator.getPointAtParameter(t)
                    if ok:
                        pts.add(reflect(pt, line_start, line_end))
                created = sketch.sketchCurves.sketchFittedSplines.add(pts)

            if created is None:
                raise RuntimeError(f"SKETCH_MIRROR failed to mirror curve type {type(geo).__name__}")

            if hasattr(curve, 'isConstruction'):
                created.isConstruction = curve.isConstruction

            new_curve_id = self._next_curve_id(sketch_id, "mirror")
            self._curves[new_curve_id] = created
            new_curve_ids.append(new_curve_id)

        if not new_curve_ids:
            raise RuntimeError("SKETCH_MIRROR produced no curves")

        return self._ret_sketch(curve_ids=new_curve_ids)
    
    def SKETCH_RECTANGLE(self, sketch_id: str, center: dict, width: float, height: float, construction: bool = False):
        """鍦?sketch 涓敾鐭╁舰锛堜腑蹇冪偣 + 瀹介珮锛?
        
        鍙傛暟鍗曚綅锛歮m
        """
        # validate inputs & ids
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        # 涓績鐐硅浆鎹负 cm
        center_vec = self.cm_vec(center.get("x", 0), center.get("y", 0))
        cx = center_vec.x
        cy = center_vec.y
        cz_mm = center.get("z", 0)
        cz_cm = float(cz_mm) / 10.0
        
        # 瀹介珮杞崲涓?cm
        width_cm = float(width) / 10.0  # mm 鈫?cm
        height_cm = float(height) / 10.0  # mm 鈫?cm
        
        # 璁＄畻鐭╁舰鍥涗釜瑙?
        x1 = cx - width_cm / 2.0
        y1 = cy - height_cm / 2.0
        x2 = cx + width_cm / 2.0
        y2 = cy + height_cm / 2.0
        
        before_count = sketch.profiles.count

        p1 = adsk.core.Point3D.create(x1, y1, cz_cm)
        p2 = adsk.core.Point3D.create(x2, y2, cz_cm)
        lines = sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
        
        for i in range(lines.count):
            lines.item(i).isConstruction = construction

        if construction:
            curve_ids = []
            for i in range(lines.count):
                curve_id = self._next_curve_id(sketch_id, "line")
                self._curves[curve_id] = lines.item(i)
                curve_ids.append(curve_id)
            return self._ret_sketch(curve_ids=curve_ids)

        after_count = sketch.profiles.count
        delta = after_count - before_count
        if delta != 1:
            raise RuntimeError(
                f"SKETCH_RECTANGLE profile count mismatch for {sketch_id}: "
                f"before={before_count}, after={after_count}"
            )
        profile = sketch.profiles.item(before_count)
        
        profile_id = self._next_profile_id(sketch_id)
        self._cache_profile(profile_id, profile)
        return self._ret_sketch(profile_id=profile_id)
    
    def EXTRUDE_NEW_BODY(self, component_id: str, profile_id: str, distance: float, direction: str = "positive", draft_angle=None):
        """鎷変几鍒涘缓鏂板疄浣?
        
        鍙傛暟锛?
            distance: float - 鎷変几璺濈锛坢m锛?
            direction: "positive" | "negative" - 鎷変几鏂瑰悜
            draft_angle: float | None - 鎷旀ā瑙掞紙搴︼級
        """
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")
        
        extrudes = comp.features.extrudeFeatures
        dist = self.mm(distance)  # mm 鈫?ValueInput(cm)
        distance_extent = adsk.fusion.DistanceExtentDefinition.create(dist)
        ext_input = extrudes.createInput(
            profile,
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        if direction == "positive":
            extent_direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
        elif direction == "negative":
            extent_direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
        else:
            raise RuntimeError(f"Unsupported extrude direction: {direction}")

        if draft_angle is not None:
            import math

            taper_value = adsk.core.ValueInput.createByReal(
                math.radians(float(draft_angle))
            )
            ext_input.setOneSideExtent(
                distance_extent,
                extent_direction,
                taper_value,
            )
        else:
            ext_input.setOneSideExtent(
                distance_extent,
                extent_direction,
            )
        extrude = extrudes.add(ext_input)

        feature_id = self._next_feature_id(component_id, "extrude")
        self._cache_feature(feature_id, extrude)
        body_ids = self._register_bodies(component_id, extrude.bodies)
        body_id = body_ids[0] if body_ids else None
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids, extra={"body_id": body_id})

    def EXTRUDE_TWO_SIDES(
        self,
        component_id: str,
        profile_id: str,
        distance_one_mm: float,
        distance_two_mm: float,
        operation: str = "new_body",
        taper_one_rad: float = 0.0,
        taper_two_rad: float = 0.0,
        name: str | None = None,
        body_id: str | None = None,
    ) -> dict:
        """鍙屽悜鎷変几锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported extrude operation: {operation}")

        extrudes = comp.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, mapped_op)

        side1 = adsk.fusion.DistanceExtentDefinition.create(self.mm(distance_one_mm))
        side2 = adsk.fusion.DistanceExtentDefinition.create(self.mm(distance_two_mm))

        if float(taper_one_rad) != 0.0 or float(taper_two_rad) != 0.0:
            taper_one_value = adsk.core.ValueInput.createByReal(float(taper_one_rad))
            taper_two_value = adsk.core.ValueInput.createByReal(float(taper_two_rad))
            ext_input.setTwoSidesExtent(
                side1,
                side2,
                taper_one_value,
                taper_two_value,
            )
        else:
            ext_input.setTwoSidesExtent(side1, side2)

        if mapped_op in {
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }:
            self._assign_extrude_participant_bodies(ext_input, comp, body_id=body_id)

        feature = extrudes.add(ext_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "extrude_two_sides")
        self._cache_feature(feature_id, feature)

        if mapped_op == adsk.fusion.FeatureOperations.NewBodyFeatureOperation:
            body_ids = self._register_bodies(component_id, feature.bodies)
            body_id = body_ids[0] if len(body_ids) == 1 else None
            return self._ret_feature(feature_id=feature_id, body_ids=body_ids, extra={"body_id": body_id})

        return self._ret_feature(feature_id=feature_id)

    def EXTRUDE_SYMMETRIC(
        self,
        component_id: str,
        profile_id: str,
        distance_mm: float,
        operation: str = "new_body",
        taper_rad: float = 0.0,
        name: str | None = None,
    ) -> dict:
        """瀵圭О鎷変几锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported extrude operation: {operation}")

        extrudes = comp.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, mapped_op)
        dist = self.mm(distance_mm)
        if float(taper_rad) != 0.0:
            taper_value = adsk.core.ValueInput.createByReal(float(taper_rad))
            ext_input.setSymmetricExtent(dist, True, taper_value)
        else:
            ext_input.setSymmetricExtent(dist, True)

        feature = extrudes.add(ext_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "extrude_symmetric")
        self._cache_feature(feature_id, feature)

        if mapped_op == adsk.fusion.FeatureOperations.NewBodyFeatureOperation and feature.bodies.count > 0:
            body_ids = self._register_bodies(component_id, feature.bodies)
            body_id = body_ids[0] if len(body_ids) == 1 else None
            return self._ret_feature(feature_id=feature_id, body_ids=body_ids, extra={"body_id": body_id})

        return self._ret_feature(feature_id=feature_id)

    def EXTRUDE_THROUGH_ALL(
        self,
        component_id: str,
        profile_id: str,
        operation: str = "cut",
        direction: str = "positive",
        name: str | None = None,
        body_id: str | None = None,
    ) -> dict:
        """璐┛鎷変几锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")

        if operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported extrude operation: {operation}")

        if direction == "positive":
            extent_direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
        elif direction == "negative":
            extent_direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
        else:
            raise RuntimeError(f"Unsupported extrude direction: {direction}")

        extrudes = comp.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, mapped_op)
        ext_input.setAllExtent(extent_direction)
        if mapped_op in {
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }:
            self._assign_extrude_participant_bodies(ext_input, comp, body_id=body_id)

        feature = extrudes.add(ext_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "extrude_through_all")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)
    
    def EXTRUDE_CUT(
        self,
        component_id: str,
        profile_id: str,
        distance: float,
        direction: str = "positive",
        draft_angle=None,
        body_id: str | None = None,
    ):
        """鎷変几鍒囬櫎
        
        鍙傛暟锛?
            distance: float - 鍒囬櫎娣卞害锛坢m锛?
            direction: "positive" | "negative" - 鍒囬櫎鏂瑰悜
            draft_angle: float | None - 鎷旀ā瑙掞紙搴︼級
        """
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")
        
        extrudes = comp.features.extrudeFeatures
        dist = self.mm(distance)  # mm 鈫?ValueInput(cm)
        distance_extent = adsk.fusion.DistanceExtentDefinition.create(dist)
        ext_input = extrudes.createInput(
            profile,
            adsk.fusion.FeatureOperations.CutFeatureOperation
        )
        if direction == "positive":
            extent_direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
        elif direction == "negative":
            extent_direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
        else:
            raise RuntimeError(f"Unsupported extrude direction: {direction}")

        if draft_angle is not None:
            import math

            taper_value = adsk.core.ValueInput.createByReal(
                math.radians(float(draft_angle))
            )
            ext_input.setOneSideExtent(
                distance_extent,
                extent_direction,
                taper_value,
            )
        else:
            ext_input.setOneSideExtent(
                distance_extent,
                extent_direction,
            )
        self._assign_extrude_participant_bodies(ext_input, comp, body_id=body_id)
        cut_feature = extrudes.add(ext_input)
        feature_id = self._next_feature_id(component_id, "extrude_cut")
        self._cache_feature(feature_id, cut_feature)
        return self._ret_feature(feature_id=feature_id)

    def EXTRUDE_TO_FACE(
        self,
        component_id: str,
        profile_id: str,
        target_face_id: str,
        operation: str = "join",
        is_two_sided: bool = False,
        name: str | None = None,
    ) -> dict:
        """鎷変几鍒版寚瀹氶潰锛堣緭鍏ュ崟浣嶄负 mm锛屽瓨鍌ㄤ负 cm锛?"""
        # validate inputs & ids
        if is_two_sided:
            raise RuntimeError("EXTRUDE_TO_FACE does not support two-sided yet")

        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")

        target_face = self._require_face(target_face_id)
        if not target_face or not target_face.isValid:
            raise RuntimeError(f"Face not found or invalid: {target_face_id}")

        if operation == "join":
            mapped_op = adsk.fusion.FeatureOperations.JoinFeatureOperation
        elif operation == "cut":
            mapped_op = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif operation == "new_body":
            mapped_op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        elif operation == "intersect":
            mapped_op = adsk.fusion.FeatureOperations.IntersectFeatureOperation
        else:
            raise RuntimeError(f"Unsupported extrude operation: {operation}")

        extrudes = comp.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, mapped_op)
        to_ent = adsk.fusion.ToEntityExtentDefinition.create(target_face, False)
        ext_input.setOneSideExtent(
            to_ent,
            adsk.fusion.ExtentDirections.PositiveExtentDirection,
        )

        feature = extrudes.add(ext_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "extrude_to_face")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)

    def REVOLVE_CUT(
        self,
        component_id: str,
        profile_id: str,
        axis: dict,
        angle_rad: float = 2 * math.pi,
        name: str | None = None,
    ) -> dict:
        """鏃嬭浆鍒囬櫎锛坅ngle 鍗曚綅锛歳ad锛?"""
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")

        # Handle dict axis input - resolve from caches
        axis_obj = None
        if isinstance(axis, dict):
            axis_id = axis.get("axis_id")
            edge_id = axis.get("edge_id")
            face_id = axis.get("face_id")
            if axis_id:
                axis_obj = self._require_axis(axis_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Axis not found or invalid: {axis_id}")
            elif edge_id:
                axis_obj = self._require_edge(edge_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Edge not found or invalid: {edge_id}")
            elif face_id:
                axis_obj = self._require_face(face_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
            else:
                raise RuntimeError("Dict axis requires axis_id, edge_id, or face_id")
        else:
            axis_obj = axis

        # Validate axis object type
        if not isinstance(axis_obj, (
            adsk.fusion.ConstructionAxis,
            adsk.fusion.SketchLine,
            adsk.fusion.BRepEdge,
            adsk.fusion.BRepFace
        )):
            raise RuntimeError("Axis must be ConstructionAxis, SketchLine, BRepEdge, or BRepFace")

        revolves = comp.features.revolveFeatures
        rev_input = revolves.createInput(
            profile,
            axis_obj,
            adsk.fusion.FeatureOperations.CutFeatureOperation,
        )
        angle = adsk.core.ValueInput.createByReal(angle_rad)
        rev_input.setAngleExtent(False, angle)
        feature = revolves.add(rev_input)
        if name:
            feature.name = name

        feature_id = self._next_feature_id(component_id, "revolve_cut")
        self._cache_feature(feature_id, feature)
        return self._ret_feature(feature_id=feature_id)
    
    def REVOLVE_NEW_BODY(self, component_id: str, profile_id: str, axis, angle_rad: float):
        """鏃嬭浆鍒涘缓鏂板疄浣擄紙angle 鍗曚綅锛歳ad锛?
        
        axis 鍙互鏄細
        - ConstructionAxis: 鏋勯€犺酱
        - SketchLine: sketch 涓殑鐩寸嚎
        - BRepEdge: 绾挎€ц竟锛堝鍦嗘煴杈广€佸渾閿ヨ竟锛?
        - BRepFace: 瀹氫箟杞寸嚎鐨勯潰锛堝鍦嗘煴銆佸渾閿ャ€佸渾鐜潰锛?
        - dict: {"axis_id": "..."} 鎴?{"edge_id": "..."} 鎴?{"face_id": "..."},瑙ｆ瀽鍚庝娇鐢?
        """
        # validate inputs & ids
        comp = self._require_component(component_id)
        profile = self._require_profile(profile_id)
        if not profile or not profile.isValid:
            raise RuntimeError(f"Profile {profile_id} not found or invalid")
        
        # Handle dict axis input - resolve from caches
        axis_obj = None
        if isinstance(axis, dict):
            axis_id = axis.get("axis_id")
            edge_id = axis.get("edge_id")
            face_id = axis.get("face_id")
            axis_type = axis.get("type")
            if axis_id:
                axis_obj = self._require_axis(axis_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Axis not found or invalid: {axis_id}")
            elif edge_id:
                axis_obj = self._require_edge(edge_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Edge not found or invalid: {edge_id}")
            elif face_id:
                axis_obj = self._require_face(face_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
            elif isinstance(axis_type, str) and axis_type.strip():
                axis_key = axis_type.strip().upper()
                if axis_key == "X":
                    axis_obj = getattr(comp, "xConstructionAxis", None)
                elif axis_key == "Y":
                    axis_obj = getattr(comp, "yConstructionAxis", None)
                elif axis_key == "Z":
                    axis_obj = getattr(comp, "zConstructionAxis", None)
                else:
                    raise RuntimeError(f"Unsupported revolve axis type: {axis_type}")
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Component construction axis not found or invalid: {axis_type}")
            else:
                raise RuntimeError("Dict axis requires axis_id, edge_id, face_id, or type")
        else:
            axis_obj = axis
        
        # Relax axis validation - accept multiple types that Fusion API supports
        if not isinstance(axis_obj, (
            adsk.fusion.ConstructionAxis,
            adsk.fusion.SketchLine,
            adsk.fusion.BRepEdge,
            adsk.fusion.BRepFace
        )):
            raise RuntimeError("Axis must be ConstructionAxis, SketchLine, BRepEdge, or BRepFace")
        
        revolves = comp.features.revolveFeatures
        angle = adsk.core.ValueInput.createByReal(angle_rad)
        rev_input = revolves.createInput(
            profile,
            axis_obj,
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        rev_input.setAngleExtent(False, angle)
        rev_feature = revolves.add(rev_input)
        feature_id = self._next_feature_id(component_id, "revolve")
        self._cache_feature(feature_id, rev_feature)
        body_ids = self._register_bodies(component_id, rev_feature.bodies)
        body_id = body_ids[0] if body_ids else None
        return self._ret_feature(feature_id=feature_id, body_ids=body_ids, extra={"body_id": body_id})

    def SUPPRESS_FEATURE(self, component_id: str, feature_id: str, is_suppressed: bool) -> dict:
        """Suppress or unsuppress a feature."""
        # validate inputs & ids
        _ = self._require_component(component_id)
        feature = self._require_feature(feature_id)

        if not hasattr(feature, "isSuppressed"):
            self._fail("Feature does not support suppression")

        feature.isSuppressed = bool(is_suppressed)
        return self._ret_feature(
            feature_id=feature_id,
            extra={"ok": True, "is_suppressed": bool(is_suppressed)},
        )

    def DELETE_FEATURE(self, component_id: str, feature_id: str) -> dict:
        """Delete a feature from the timeline."""
        # validate inputs & ids
        _ = self._require_component(component_id)
        
        try:
            feature = self._require_feature(feature_id)
            if not feature or not feature.isValid:
                return {"deleted": False, "warning": f"Feature {feature_id} is not valid"}
            
            if not hasattr(feature, "deleteMe"):
                return {"deleted": False, "warning": "Feature does not support deleteMe"}
            
            deleted = feature.deleteMe()
            if deleted and feature_id in self._features:
                del self._features[feature_id]
            
            return {"deleted": bool(deleted)}
        except Exception as e:
            return {"deleted": False, "warning": str(e)}

    def DELETE_BODY(self, component_id: str, body_id: str) -> dict:
        """Delete a body from the component.

        Strategy depends on the design type:
        - **Parametric design** 鈫?``Component.features.removeFeatures.add(body)``
          (creates a RemoveFeature in the timeline).
        - **Direct design** 鈫?``BRepBody.deleteMe()``.
        """
        # validate inputs & ids
        comp = self._require_component(component_id)

        try:
            body = self._require_body(body_id)
            if not body or not body.isValid:
                return {"deleted": False, "warning": f"Body {body_id} is not valid"}

            deleted = False

            # --- Parametric design: use RemoveFeatures (official timeline approach) ---
            if self.design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
                try:
                    remove_feats = comp.features.removeFeatures
                    remove_feats.add(body)
                    deleted = True
                except Exception:
                    # Fallback to deleteMe if RemoveFeatures fails
                    pass

            # --- Direct design (or parametric fallback): deleteMe ---
            if not deleted and hasattr(body, "deleteMe"):
                deleted = bool(body.deleteMe())

            if deleted and body_id in self._bodies:
                del self._bodies[body_id]

            return {"deleted": deleted}
        except Exception as e:
            return {"deleted": False, "warning": str(e)}

    def DELETE_SKETCH(self, sketch_id: str) -> dict:
        """Delete a sketch from the design."""
        try:
            sketch = self._require_sketch(sketch_id)
            if not sketch or not sketch.isValid:
                return {"deleted": False, "warning": f"Sketch {sketch_id} is not valid"}
            
            # Sketch is a SketchObject; use deleteMe() or parent collection remove
            if hasattr(sketch, "deleteMe"):
                deleted = sketch.deleteMe()
                if deleted and sketch_id in self._sketches:
                    del self._sketches[sketch_id]
                return {"deleted": bool(deleted)}
            
            # Fallback: try parent collection
            if hasattr(sketch, "parent") and hasattr(sketch.parent, "removeByObject"):
                sketch.parent.removeByObject(sketch)
                if sketch_id in self._sketches:
                    del self._sketches[sketch_id]
                return {"deleted": True}
            
            return {"deleted": False, "warning": "Sketch does not support deletion"}
        except Exception as e:
            return {"deleted": False, "warning": str(e)}
    
    def SKETCH_ROUNDED_POLYGON(self, sketch_id: str, center: dict, hub_radius: float,
                                arm_count: int, arm_length: float, arm_width: float,
                                corner_radius: float, construction: bool = False):
        """鍦?sketch 涓敾鍙傛暟鍖栧渾瑙掑杈瑰舰锛堝涓夎噦 carrier plate锛?
        
        銆愯璁°€?
        - 涓ぎ hub锛堝渾褰級锛氬崐寰?= hub_radius
        - arm_count 鏉?arm锛堢煩褰級锛屽潎鍖€鍒嗗竷锛屼粠 hub 鍚戝
        - 姣忔潯 arm锛氬搴?= arm_width锛岄暱搴?= arm_length锛堜粠 hub 涓績鍒?arm 鏈锛?
        - 鍦嗚杩炴帴锛歨ub 涓?arm 鐨勪氦鎺ュ鍦嗚鍗婂緞 = corner_radius
        - 鍙傛暟瀹屽叏鏉ヨ嚜杈撳叆锛屼笉纭紪鐮佷换浣曞潗鏍?
        
        銆愬潗鏍囩郴銆?
        - center: 涓ぎ hub 鐨勫渾蹇?
        - arm 浠?hub 涓績鍚戝杈愬皠锛岀涓€鏉?arm 娌?x+ 鏂瑰悜
        
        鍙傛暟鍗曚綅锛歮m
        """
        # validate inputs & ids
        import math
        
        sketch = self._require_sketch(sketch_id)
        if not sketch:
            raise RuntimeError(f"Sketch {sketch_id} not found")

        sketch.isComputeDeferred = True
        try:
            before_count = sketch.profiles.count

            ignored_corner = False
            if corner_radius and corner_radius > 0:
                ignored_corner = True

            # 杞崲涓績鍧愭爣鍜屽昂瀵稿埌 cm
            center_x_cm = float(center.get("x", 0)) / 10.0
            center_y_cm = float(center.get("y", 0)) / 10.0
            center_z_cm = float(center.get("z", 0.0)) / 10.0
            hub_r_cm = float(hub_radius) / 10.0
            arm_len_cm = float(arm_length) / 10.0
            arm_w_cm = float(arm_width) / 10.0

            # 鐢讳腑澶?hub锛堝渾褰級
            center_pt = adsk.core.Point3D.create(center_x_cm, center_y_cm, center_z_cm)
            hub_circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center_pt, hub_r_cm)
            hub_circle.isConstruction = construction

            curve_ids = []

            hub_curve_id = self._next_curve_id(sketch_id, "circle")
            self._curves[hub_curve_id] = hub_circle
            curve_ids.append(hub_curve_id)

            # 瀵规瘡鏉?arm 鐢荤煩褰紙arm_count 鏉★紝鍧囧寑鍒嗗竷锛?
            half_w = arm_w_cm / 2.0

            for arm_idx in range(arm_count):
                angle_rad = 2 * math.pi * arm_idx / arm_count
                dx = math.cos(angle_rad)
                dy = math.sin(angle_rad)
                perp_x = -dy
                perp_y = dx

                inner_r = hub_r_cm
                outer_r = arm_len_cm

                inner_left = adsk.core.Point3D.create(
                    center_x_cm + dx * inner_r - perp_x * half_w,
                    center_y_cm + dy * inner_r - perp_y * half_w,
                    center_z_cm,
                )
                inner_right = adsk.core.Point3D.create(
                    center_x_cm + dx * inner_r + perp_x * half_w,
                    center_y_cm + dy * inner_r + perp_y * half_w,
                    center_z_cm,
                )
                outer_right = adsk.core.Point3D.create(
                    center_x_cm + dx * outer_r + perp_x * half_w,
                    center_y_cm + dy * outer_r + perp_y * half_w,
                    center_z_cm,
                )
                outer_left = adsk.core.Point3D.create(
                    center_x_cm + dx * outer_r - perp_x * half_w,
                    center_y_cm + dy * outer_r - perp_y * half_w,
                    center_z_cm,
                )

                line1 = sketch.sketchCurves.sketchLines.addByTwoPoints(inner_left, inner_right)
                line2 = sketch.sketchCurves.sketchLines.addByTwoPoints(inner_right, outer_right)
                line3 = sketch.sketchCurves.sketchLines.addByTwoPoints(outer_right, outer_left)
                line4 = sketch.sketchCurves.sketchLines.addByTwoPoints(outer_left, inner_left)

                for line in (line1, line2, line3, line4):
                    line.isConstruction = construction
                    curve_id = self._next_curve_id(sketch_id, "line")
                    self._curves[curve_id] = line
                    curve_ids.append(curve_id)

            # 鐜板湪杞粨搴旇鐩稿闂悎浜嗭細hub 鍦?+ arm 鐭╁舰 + 杩炴帴绾?

            after_count = sketch.profiles.count
            if self.strict_mode and after_count <= before_count:
                raise RuntimeError(
                    f"SKETCH_ROUNDED_POLYGON produced no new profiles for {sketch_id}: "
                    f"before={before_count}, after={after_count}"
                )

            profiles = [sketch.profiles.item(i) for i in range(sketch.profiles.count)]
            if not profiles:
                raise RuntimeError(f"SKETCH_ROUNDED_POLYGON has no profiles for {sketch_id}")

            max_profile = max(
                profiles,
                key=lambda p: p.areaProperties(
                    adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy
                ).area,
            )
            profile_id = self._next_profile_id(sketch_id)
            self._cache_profile(profile_id, max_profile)

            extra = None
            if ignored_corner:
                extra = {"warning": "corner_radius is currently ignored (no sketch fillet implemented)"}
            return self._ret_sketch(profile_id=profile_id, curve_ids=curve_ids, extra=extra)
        finally:
            sketch.isComputeDeferred = False

    def CREATE_JOINT_GEOMETRY(self, entity: dict, origin_mm: dict | None = None) -> dict:
        """Create JointGeometry and retain its source entity for occurrence-context rematerialization."""
        geom, source_entity = self._build_joint_geometry_from_entity(
            entity,
            occurrence=None,
            origin_mm=origin_mm,
        )

        geom_id = f"jgeom:{len(self._joint_geometries) + 1}"
        self._joint_geometries[geom_id] = geom
        if not hasattr(self, "_joint_geometry_sources") or not isinstance(self._joint_geometry_sources, dict):
            self._joint_geometry_sources = {}
        self._joint_geometry_sources[geom_id] = {
            "entity": dict(source_entity) if isinstance(source_entity, dict) else source_entity,
            "origin_mm": dict(origin_mm) if isinstance(origin_mm, dict) else None,
        }
        return {"joint_geometry_id": geom_id}

    def _pick_joint_direction(self):
        """Pick a default joint direction when the plan does not provide one."""
        candidates = [
            "ZAxisJointDirection",
            "YAxisJointDirection",
            "XAxisJointDirection",
        ]
        for name in candidates:
            if hasattr(adsk.fusion.JointDirections, name):
                return getattr(adsk.fusion.JointDirections, name)

        for name in dir(adsk.fusion.JointDirections):
            if not name.endswith("JointDirection"):
                continue
            return getattr(adsk.fusion.JointDirections, name)

        raise RuntimeError("No available JointDirections in current Fusion API")

    def _set_as_built_motion(self, joint_input, kind: str) -> None:
        """Set AsBuiltJoint motion using official setAs...JointMotion API."""
        if kind == "rigid":
            setter = getattr(joint_input, "setAsRigidJointMotion", None)
            if not callable(setter):
                raise RuntimeError("AsBuiltJointInput missing setAsRigidJointMotion")
            setter()
            return

        direction = self._pick_joint_direction()
        setter_name = {
            "revolute": "setAsRevoluteJointMotion",
            "slider": "setAsSliderJointMotion",
            "planar": "setAsPlanarJointMotion",
            "cylindrical": "setAsCylindricalJointMotion",
        }.get(kind)
        if not setter_name:
            raise RuntimeError(f"Unsupported as-built joint motion type: {kind}")

        setter = getattr(joint_input, setter_name, None)
        if not callable(setter):
            raise RuntimeError(f"AsBuiltJointInput missing {setter_name}")

        try:
            setter(direction)
        except TypeError:
            try:
                setter()
            except TypeError as exc:
                raise RuntimeError(
                    f"{setter_name} signature not supported by current Fusion API"
                ) from exc

    def _set_joint_motion(self, joint_input, kind: str) -> None:
        """Set regular Joint motion using official setAs...JointMotion API."""
        if kind == "rigid":
            setter = getattr(joint_input, "setAsRigidJointMotion", None)
            if not callable(setter):
                raise RuntimeError("JointInput missing setAsRigidJointMotion")
            setter()
            return

        direction = self._pick_joint_direction()

        setter_name = {
            "revolute": "setAsRevoluteJointMotion",
            "slider": "setAsSliderJointMotion",
            "planar": "setAsPlanarJointMotion",
            "cylindrical": "setAsCylindricalJointMotion",
        }.get(kind)
        if not setter_name:
            raise RuntimeError(f"Unsupported joint motion type: {kind}")

        setter = getattr(joint_input, setter_name, None)
        if not callable(setter):
            raise RuntimeError(f"JointInput missing {setter_name}")

        try:
            setter(direction)
        except TypeError:
            try:
                setter()
            except TypeError as exc:
                raise RuntimeError(
                    f"{setter_name} signature not supported by current Fusion API"
                ) from exc

    def _create_joint_r1(
        self,
        *,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        motion_kind: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        _ = self._require_component(component_id)
        occ1 = self._get_occurrence(occurrence_one_id)
        occ2 = self._get_occurrence(occurrence_two_id)

        # Knife-4 execution-layer guard: if either occurrence belongs to a hosted
        # standard part (bearing / fastener), skip joint creation entirely.
        # This is a regression fence — under normal operation the planning layer
        # (Agent4 non_executable_relations + Agent5 Knife-3 filter) should have
        # already removed this step before it reaches here.
        _std_hit = (
            self._is_standard_part_occurrence(occurrence_one_id, occ1),
            self._is_standard_part_occurrence(occurrence_two_id, occ2),
        )
        _std_hint = (
            self._standard_part_hint_from_occurrence_id(occurrence_one_id),
            self._standard_part_hint_from_occurrence_id(occurrence_two_id),
        )
        if any(_std_hit) or any(_std_hint):
            _skip_payload = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "joint_mode": "direct",
                "motion_kind": motion_kind,
                "component_id": component_id,
                "occurrence_one_id": occurrence_one_id,
                "occurrence_two_id": occurrence_two_id,
                "status": "skipped",
                "reason": "hosted_standard_part_guard_fired",
                "standard_part_hit": {
                    "occurrence_one": _std_hit[0],
                    "occurrence_two": _std_hit[1],
                },
                "standard_part_hint": {
                    "occurrence_one": _std_hint[0],
                    "occurrence_two": _std_hint[1],
                },
            }
            self._append_joint_execution_log(_skip_payload)
            print(
                f"[WARN] _create_joint_r1 SKIPPED (hosted_standard_part_guard): "
                f"{occurrence_one_id!r} x {occurrence_two_id!r}. "
                "Planning-layer filter (Agent4/Agent5) should have blocked this step."
            )
            return {
                "joint_id": None,
                "joint_skipped": True,
                "reason": "hosted_standard_part_guard_fired",
            }

        geom1 = self._materialize_joint_geometry(joint_geometry_one_id, occurrence_one_id)
        geom2 = self._materialize_joint_geometry(joint_geometry_two_id, occurrence_two_id)
        if not geom1 or not geom2:
            raise RuntimeError(
                "Joint requires both joint_geometry_one_id and joint_geometry_two_id"
            )

        pre_one = self._occurrence_translation_mm(occ1)
        pre_two = self._occurrence_translation_mm(occ2)

        joints = self.design.rootComponent.joints
        joint_input = joints.createInput(geom1, geom2)
        self._set_joint_motion(joint_input, motion_kind)
        try:
            joint_input.isFlipped = bool(is_flipped)
        except Exception:
            pass
        joint = joints.add(joint_input)
        if name:
            joint.name = name

        post_one = self._occurrence_translation_mm(occ1)
        post_two = self._occurrence_translation_mm(occ2)
        pose_guard_one = self._joint_pose_guard_for_standard_part(
            occurrence_id=occurrence_one_id,
            occurrence=occ1,
            pre_translation_mm=pre_one,
            post_translation_mm=post_one,
        )
        pose_guard_two = self._joint_pose_guard_for_standard_part(
            occurrence_id=occurrence_two_id,
            occurrence=occ2,
            pre_translation_mm=pre_two,
            post_translation_mm=post_two,
        )
        self._append_joint_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "joint_mode": "direct",
                "motion_kind": motion_kind,
                "component_id": component_id,
                "occurrence_one_id": occurrence_one_id,
                "occurrence_two_id": occurrence_two_id,
                "joint_geometry_one_id": joint_geometry_one_id,
                "joint_geometry_two_id": joint_geometry_two_id,
                "joint_geometry_source_one": getattr(self, "_joint_geometry_sources", {}).get(joint_geometry_one_id),
                "joint_geometry_source_two": getattr(self, "_joint_geometry_sources", {}).get(joint_geometry_two_id),
                "pre_translation_mm": {
                    "occurrence_one": pre_one,
                    "occurrence_two": pre_two,
                },
                "post_translation_mm": {
                    "occurrence_one": post_one,
                    "occurrence_two": post_two,
                },
                "pose_guard": {
                    "occurrence_one": pose_guard_one,
                    "occurrence_two": pose_guard_two,
                    # Knife-4: this guard is a transitional runtime safety net.
                    # It should become unreachable once planning-layer filters
                    # (Agent4/Agent5) fully block hosted-standard joint emission.
                    "pose_guard_deprecation_note": "transitional_guard_planned_for_removal",
                },
            }
        )

        joint_id = self._next_joint_id(motion_kind)
        self._joints[joint_id] = joint
        return {"joint_id": joint_id}

    def RIGID_JOINT_R1(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        """Create rigid direct joint."""
        return self._create_joint_r1(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="rigid",
            is_flipped=is_flipped,
            name=name,
        )

    def REVOLUTE_JOINT_R1(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        """Create revolute direct joint."""
        return self._create_joint_r1(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="revolute",
            is_flipped=is_flipped,
            name=name,
        )

    def _create_as_built_joint(
        self,
        *,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        motion_kind: str,
        is_flipped: bool = False,
        name: str | None = None,
        failure_message: str | None = None,
    ) -> dict:
        _ = self._require_component(component_id)
        occ1 = self._get_occurrence(occurrence_one_id)
        occ2 = self._get_occurrence(occurrence_two_id)

        # Knife-4 execution-layer guard: same as _create_joint_r1.
        _std_hit = (
            self._is_standard_part_occurrence(occurrence_one_id, occ1),
            self._is_standard_part_occurrence(occurrence_two_id, occ2),
        )
        _std_hint = (
            self._standard_part_hint_from_occurrence_id(occurrence_one_id),
            self._standard_part_hint_from_occurrence_id(occurrence_two_id),
        )
        if any(_std_hit) or any(_std_hint):
            _skip_payload = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "joint_mode": "as_built",
                "motion_kind": motion_kind,
                "component_id": component_id,
                "occurrence_one_id": occurrence_one_id,
                "occurrence_two_id": occurrence_two_id,
                "status": "skipped",
                "reason": "hosted_standard_part_guard_fired",
                "standard_part_hit": {
                    "occurrence_one": _std_hit[0],
                    "occurrence_two": _std_hit[1],
                },
                "standard_part_hint": {
                    "occurrence_one": _std_hint[0],
                    "occurrence_two": _std_hint[1],
                },
            }
            self._append_joint_execution_log(_skip_payload)
            print(
                f"[WARN] _create_as_built_joint SKIPPED (hosted_standard_part_guard): "
                f"{occurrence_one_id!r} x {occurrence_two_id!r}. "
                "Planning-layer filter (Agent4/Agent5) should have blocked this step."
            )
            return {
                "joint_id": None,
                "joint_skipped": True,
                "reason": "hosted_standard_part_guard_fired",
            }

        geom1 = self._materialize_joint_geometry(joint_geometry_one_id, occurrence_one_id)
        geom2 = self._materialize_joint_geometry(joint_geometry_two_id, occurrence_two_id)
        geom = geom1 or geom2
        if not geom:
            raise RuntimeError(
                "As-built joint requires at least one JointGeometry from input"
            )

        pre_one = self._occurrence_translation_mm(occ1)
        pre_two = self._occurrence_translation_mm(occ2)

        joints = self.design.rootComponent.asBuiltJoints
        joint_input = joints.createInput(occ1, occ2, geom)
        self._set_as_built_motion(joint_input, motion_kind)
        if is_flipped and hasattr(joint_input, '_set_isFlipped'):
            try:
                joint_input.isFlipped = bool(is_flipped)
            except Exception:
                pass
        try:
            joint = joints.add(joint_input)
        except Exception as exc:
            if failure_message:
                raise RuntimeError(failure_message) from exc
            raise
        if name:
            joint.name = name

        post_one = self._occurrence_translation_mm(occ1)
        post_two = self._occurrence_translation_mm(occ2)
        pose_guard_one = self._joint_pose_guard_for_standard_part(
            occurrence_id=occurrence_one_id,
            occurrence=occ1,
            pre_translation_mm=pre_one,
            post_translation_mm=post_one,
        )
        pose_guard_two = self._joint_pose_guard_for_standard_part(
            occurrence_id=occurrence_two_id,
            occurrence=occ2,
            pre_translation_mm=pre_two,
            post_translation_mm=post_two,
        )
        self._append_joint_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "joint_mode": "as_built",
                "motion_kind": motion_kind,
                "component_id": component_id,
                "occurrence_one_id": occurrence_one_id,
                "occurrence_two_id": occurrence_two_id,
                "joint_geometry_one_id": joint_geometry_one_id,
                "joint_geometry_two_id": joint_geometry_two_id,
                "joint_geometry_source_one": getattr(self, "_joint_geometry_sources", {}).get(joint_geometry_one_id),
                "joint_geometry_source_two": getattr(self, "_joint_geometry_sources", {}).get(joint_geometry_two_id),
                "geometry_from": "one" if geom1 else "two",
                "pre_translation_mm": {
                    "occurrence_one": pre_one,
                    "occurrence_two": pre_two,
                },
                "post_translation_mm": {
                    "occurrence_one": post_one,
                    "occurrence_two": post_two,
                },
                "pose_guard": {
                    "occurrence_one": pose_guard_one,
                    "occurrence_two": pose_guard_two,
                    # Knife-4: this guard is a transitional runtime safety net.
                    # It should become unreachable once planning-layer filters
                    # (Agent4/Agent5) fully block hosted-standard joint emission.
                    "pose_guard_deprecation_note": "transitional_guard_planned_for_removal",
                },
            }
        )

        joint_id = self._next_joint_id(motion_kind)
        self._joints[joint_id] = joint
        return {"joint_id": joint_id}

    def RIGID_AS_BUILT_JOINT(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        return self._create_as_built_joint(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="rigid",
            is_flipped=is_flipped,
            name=name,
        )

    def SLIDER_AS_BUILT_JOINT(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        return self._create_as_built_joint(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="slider",
            is_flipped=is_flipped,
            name=name,
        )

    def CYLINDRICAL_AS_BUILT_JOINT(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        return self._create_as_built_joint(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="cylindrical",
            is_flipped=is_flipped,
            name=name,
        )

    def PLANAR_AS_BUILT_JOINT(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        return self._create_as_built_joint(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="planar",
            is_flipped=is_flipped,
            name=name,
        )

    def REVOLUTE_AS_BUILT_JOINT(
        self,
        component_id: str,
        occurrence_one_id: str,
        occurrence_two_id: str,
        joint_geometry_one_id: str,
        joint_geometry_two_id: str,
        is_flipped: bool = False,
        name: str | None = None,
    ) -> dict:
        return self._create_as_built_joint(
            component_id=component_id,
            occurrence_one_id=occurrence_one_id,
            occurrence_two_id=occurrence_two_id,
            joint_geometry_one_id=joint_geometry_one_id,
            joint_geometry_two_id=joint_geometry_two_id,
            motion_kind="revolute",
            is_flipped=is_flipped,
            name=name,
            failure_message="REVOLUTE_AS_BUILT_JOINT failed; refusing to silently downgrade to a moving joint",
        )

    def SET_JOINT_LIMITS(
        self,
        joint_id: str,
        rotation_limits_rad: dict | None = None,
        translation_limits_mm: dict | None = None,
    ) -> dict:
        """璁剧疆鍏宠妭闄愬埗"""
        # validate inputs & ids
        joint = self._joints.get(joint_id)
        if not joint or not joint.isValid:
            raise RuntimeError(f"Joint not found or invalid: {joint_id}")

        motion = joint.jointMotion

        if rotation_limits_rad is not None:
            if not hasattr(motion, "rotationLimits"):
                raise RuntimeError("Joint motion does not support rotation limits")
            if "min" not in rotation_limits_rad or "max" not in rotation_limits_rad:
                raise RuntimeError("rotation_limits_rad requires min/max")

            rot_limits = motion.rotationLimits
            rot_limits.isMinimumValueEnabled = True
            rot_limits.minimumValue = rotation_limits_rad["min"]
            rot_limits.isMaximumValueEnabled = True
            rot_limits.maximumValue = rotation_limits_rad["max"]

        if translation_limits_mm is not None:
            if not hasattr(motion, "slideLimits"):
                raise RuntimeError("Joint motion does not support translation limits")
            if "min" not in translation_limits_mm or "max" not in translation_limits_mm:
                raise RuntimeError("translation_limits_mm requires min/max")

            slide_limits = motion.slideLimits
            slide_limits.isMinimumValueEnabled = True
            slide_limits.minimumValue = float(translation_limits_mm["min"]) / 10.0
            slide_limits.isMaximumValueEnabled = True
            slide_limits.maximumValue = float(translation_limits_mm["max"]) / 10.0

        return {"joint_id": joint_id}

    def DRIVE_JOINT(
        self,
        joint_id: str,
        rotation_rad: float | None = None,
        translation_mm: float | None = None,
    ) -> dict:
        """椹卞姩鍏宠妭杩愬姩"""
        # validate inputs & ids
        joint = self._joints.get(joint_id)
        if not joint or not joint.isValid:
            raise RuntimeError(f"Joint not found or invalid: {joint_id}")

        motion = joint.jointMotion

        if rotation_rad is not None:
            if not hasattr(motion, "rotationValue"):
                raise RuntimeError("Joint motion does not support rotation")
            motion.rotationValue = rotation_rad

        if translation_mm is not None:
            if not hasattr(motion, "slideValue"):
                raise RuntimeError("Joint motion does not support translation")
            motion.slideValue = float(translation_mm) / 10.0

        return {"joint_id": joint_id}

    def CREATE_REVOLUTE_JOINT(self, occ1_name: str, occ2_name: str, axis):
        """鍒涘缓鏃嬭浆鍏宠妭锛堜娇鐢?REVOLUTE_JOINT 浣滀负涓诲疄鐜帮級"""
        # validate inputs & ids
        return self.REVOLUTE_JOINT(occ1_name, occ2_name, axis, name=None)

    def REVOLUTE_JOINT(
        self,
        component_a: str,
        component_b: str,
        axis,
        name=None,
    ):
        """Create a revolute joint between two components via JointGeometry pipeline."""
        # validate inputs & ids
        _ = self._get_occurrence(component_a)
        _ = self._get_occurrence(component_b)

        entity = None
        if isinstance(axis, dict):
            marker_id = axis.get("marker_id")
            axis_id = axis.get("axis_id")
            edge_id = axis.get("edge_id")
            face_id = axis.get("face_id")
            if marker_id:
                entity = {"type": "marker", "marker_id": marker_id}
            elif axis_id:
                axis_obj = self._require_axis(axis_id)
                if not axis_obj or not axis_obj.isValid:
                    raise RuntimeError(f"Axis not found or invalid: {axis_id}")
                entity = {"type": "axis", "axis_id": axis_id}
            elif edge_id:
                edge_obj = self._require_edge(edge_id)
                if not edge_obj or not edge_obj.isValid:
                    raise RuntimeError(f"Edge not found or invalid: {edge_id}")
                entity = {"type": "edge", "edge_id": edge_id}
            elif face_id:
                face_obj = self._require_face(face_id)
                if not face_obj or not face_obj.isValid:
                    raise RuntimeError(f"Face not found or invalid: {face_id}")
                entity = {"type": "face", "face_id": face_id}
            else:
                raise RuntimeError("Axis dict requires marker_id, axis_id, edge_id, or face_id")
        elif isinstance(axis, adsk.fusion.ConstructionAxis):
            axis_id = None
            for key, value in self._axes.items():
                if value == axis:
                    axis_id = key
                    break
            if not axis_id:
                raise RuntimeError("ConstructionAxis is not registered; use axis_id")
            entity = {"type": "axis", "axis_id": axis_id}
        elif isinstance(axis, adsk.fusion.BRepEdge):
            edge_id = None
            for key, value in self._edges.items():
                if value == axis:
                    edge_id = key
                    break
            if not edge_id:
                raise RuntimeError("BRepEdge is not registered; use edge_id")
            entity = {"type": "edge", "edge_id": edge_id}
        elif isinstance(axis, adsk.fusion.BRepFace):
            face_id = None
            for key, value in self._faces.items():
                if value == axis:
                    face_id = key
                    break
            if not face_id:
                raise RuntimeError("BRepFace is not registered; use face_id")
            entity = {"type": "face", "face_id": face_id}
        elif isinstance(axis, adsk.fusion.SketchLine):
            raise RuntimeError(
                "SketchLine is not supported for joints; project to a BRepEdge "
                "or create/register a ConstructionAxis and pass axis_id."
            )
        else:
            raise RuntimeError("Axis must be ConstructionAxis, BRepEdge, or BRepFace")

        geom1 = self.CREATE_JOINT_GEOMETRY(entity)["joint_geometry_id"]
        geom2 = self.CREATE_JOINT_GEOMETRY(entity)["joint_geometry_id"]

        return self.REVOLUTE_AS_BUILT_JOINT(
            "root",
            component_a,
            component_b,
            geom1,
            geom2,
            name=name,
        )

    def FIND_BODY_FACES(
        self,
        body_id: str,
        kind: str | None = None,
        min_area: float | None = None,
        normal_axis: str | None = None,
        radius_range: dict | None = None,
    ) -> dict:
        """Find and cache faces in a body with optional geometric filtering.
        
        鍙傛暟锛?
            body_id: Body ID
            kind: Optional filter - "planar" | "cylindrical" | "spherical" | "toroidal" | "conical" | "other"
            min_area: Optional minimum face area in mm虏
            normal_axis: Optional "X" | "Y" | "Z" to filter planar faces with normal along that axis
            radius_range: Optional {"min": ..., "max": ...} to filter cylindrical/spherical by radius
        
        杩斿洖锛?
            {"face_ids": [...], "count": int}
        """
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body {body_id} not found or invalid")
        
        comp_id = self._component_id_from_body_id(body_id)
        face_ids = []
        
        if not hasattr(body, "faces") or body.faces.count == 0:
            return {"face_ids": [], "count": 0}
        
        for i in range(body.faces.count):
            face = body.faces.item(i)
            if not face or not face.isValid:
                continue
            
            # Apply geometric filters
            if kind:
                face_kind = self._get_face_geometry_kind(face)
                if face_kind != kind:
                    continue
            
            if min_area:
                try:
                    face_area = face.area * 100.0  # cm虏 to mm虏
                    if face_area < min_area:
                        continue
                except:
                    pass  # Skip if area calculation fails
            
            if normal_axis:
                if kind != "planar" and self._get_face_geometry_kind(face) != "planar":
                    continue
                if not self._face_has_normal_axis(face, normal_axis):
                    continue
            
            if radius_range:
                try:
                    radius = self._get_face_radius(face)
                    if radius is None:
                        continue
                    radius_mm = radius * 10.0  # cm to mm
                    if "min" in radius_range and radius_mm < radius_range["min"]:
                        continue
                    if "max" in radius_range and radius_mm > radius_range["max"]:
                        continue
                except:
                    continue  # Skip if radius calculation fails
            
            # Register face
            face_id = self._next_face_id(comp_id)
            self._cache_face(face_id, face)
            face_ids.append(face_id)
        
        return {"face_ids": face_ids, "count": len(face_ids)}

    def FIND_BODY_EDGES(
        self,
        body_id: str,
        kind: str | None = None,
        length_range: dict | None = None,
        radius_range: dict | None = None,
    ) -> dict:
        """Find and cache edges in a body with optional geometric filtering.
        
        鍙傛暟锛?
            body_id: Body ID
            kind: Optional filter - "line" | "circle" | "ellipse" | "spline" | "other"
            length_range: Optional {"min": ..., "max": ...} to filter by edge length in mm
            radius_range: Optional {"min": ..., "max": ...} to filter circular/elliptical edges by radius
        
        杩斿洖锛?
            {"edge_ids": [...], "count": int}
        """
        body = self._require_body(body_id)
        if not body or not body.isValid:
            raise RuntimeError(f"Body {body_id} not found or invalid")
        
        comp_id = body_id.split(":")[0]  # Extract component_id from body_id
        edge_ids = []
        
        if not hasattr(body, "edges") or body.edges.count == 0:
            return {"edge_ids": [], "count": 0}
        
        for i in range(body.edges.count):
            edge = body.edges.item(i)
            if not edge or not edge.isValid:
                continue
            
            # Apply geometric filters
            if kind:
                edge_kind = self._get_edge_geometry_kind(edge)
                if edge_kind != kind:
                    continue
            
            if length_range:
                try:
                    edge_length = edge.length * 10.0  # cm to mm
                    if "min" in length_range and edge_length < length_range["min"]:
                        continue
                    if "max" in length_range and edge_length > length_range["max"]:
                        continue
                except:
                    continue  # Skip if length calculation fails
            
            if radius_range:
                try:
                    radius = self._get_edge_radius(edge)
                    if radius is None:
                        continue
                    radius_mm = radius * 10.0  # cm to mm
                    if "min" in radius_range and radius_mm < radius_range["min"]:
                        continue
                    if "max" in radius_range and radius_mm > radius_range["max"]:
                        continue
                except:
                    continue  # Skip if radius calculation fails
            
            # Register edge
            edge_id = self._next_edge_id(comp_id)
            self._cache_edge(edge_id, edge)
            edge_ids.append(edge_id)
        
        return {"edge_ids": edge_ids, "count": len(edge_ids)}

    def _get_face_geometry_kind(self, face: 'adsk.fusion.BRepFace') -> str:
        """Determine face geometry type via Fusion geometry casts first."""
        try:
            geom = getattr(face, "geometry", None)
            if geom is not None:
                if adsk.core.Plane.cast(geom) is not None:
                    return "planar"
                if adsk.core.Cylinder.cast(geom) is not None:
                    return "cylindrical"
                if adsk.core.Sphere.cast(geom) is not None:
                    return "spherical"
                if adsk.core.Torus.cast(geom) is not None:
                    return "toroidal"
                if adsk.core.Cone.cast(geom) is not None:
                    return "conical"

            surface_type = getattr(face, "surfaceType", None)
            if surface_type == adsk.core.SurfaceTypes.PlaneSurfaceType:
                return "planar"
            if surface_type == adsk.core.SurfaceTypes.CylinderSurfaceType:
                return "cylindrical"
            if surface_type == adsk.core.SurfaceTypes.SphereSurfaceType:
                return "spherical"
            if surface_type == adsk.core.SurfaceTypes.TorusSurfaceType:
                return "toroidal"
            if surface_type == adsk.core.SurfaceTypes.ConeSurfaceType:
                return "conical"
        except Exception:
            pass
        
        return "other"

    def _get_edge_geometry_kind(self, edge: 'adsk.fusion.BRepEdge') -> str:
        """Determine edge geometry type via evaluator."""
        try:
            if hasattr(edge, "geometry"):
                geom = edge.geometry
                geom_type = str(geom)
                if "LineSegment" in geom_type or "Line" in geom_type:
                    return "line"
                elif "Circle" in geom_type:
                    return "circle"
                elif "Ellipse" in geom_type:
                    return "ellipse"
                elif "Spline" in geom_type or "Bezier" in geom_type or "BSpline" in geom_type:
                    return "spline"
        except:
            pass
        
        return "other"

    def _face_has_normal_axis(self, face: 'adsk.fusion.BRepFace', axis: str) -> bool:
        """Check if planar face has normal along specified axis ("X"|"Y"|"Z")."""
        try:
            if not hasattr(face, "geometry"):
                return False
            
            geom = face.geometry
            if not hasattr(geom, "normal"):
                return False
            
            normal = geom.normal
            if not normal:
                return False
            
            # Compare normal direction to axis
            tol = 0.001
            if axis.upper() == "X":
                return abs(abs(normal.x) - 1.0) < tol and abs(normal.y) < tol and abs(normal.z) < tol
            elif axis.upper() == "Y":
                return abs(normal.x) < tol and abs(abs(normal.y) - 1.0) < tol and abs(normal.z) < tol
            elif axis.upper() == "Z":
                return abs(normal.x) < tol and abs(normal.y) < tol and abs(abs(normal.z) - 1.0) < tol
        except:
            pass
        
        return False

    def _get_face_radius(self, face: 'adsk.fusion.BRepFace') -> float | None:
        """Extract radius from cylindrical/spherical face if available."""
        try:
            if hasattr(face, "geometry"):
                geom = face.geometry
                try:
                    cylinder = adsk.core.Cylinder.cast(geom)
                    if cylinder is not None and hasattr(cylinder, "radius"):
                        return float(cylinder.radius)
                except Exception:
                    pass
                try:
                    sphere = adsk.core.Sphere.cast(geom)
                    if sphere is not None and hasattr(sphere, "radius"):
                        return float(sphere.radius)
                except Exception:
                    pass
                try:
                    cone = adsk.core.Cone.cast(geom)
                    if cone is not None and hasattr(cone, "radius"):
                        return float(cone.radius)
                except Exception:
                    pass
                try:
                    return float(getattr(geom, "radius"))
                except Exception:
                    pass
        except Exception:
            pass

        return None

    def _standard_part_record(
        self,
        *,
        component_id: str | None = None,
        component_name: str | None = None,
    ) -> dict | None:
        if component_id:
            record = self._standard_parts["by_component_id"].get(component_id)
            if record:
                return record
        if component_name:
            return self._standard_parts["by_component_name"].get(component_name)
        return None

    def _library_root(self) -> Path:
        env_root = os.getenv("FUSION_PART_LIBRARY_ROOT", "").strip()
        if env_root:
            return Path(env_root).expanduser().resolve()
        return (Path(__file__).resolve().parent.parent / "part_library").resolve()

    def _load_parts_index(self) -> dict:
        library_root = self._library_root()
        index_path = library_root / "index" / "parts_index.json"
        if not index_path.exists():
            raise FileNotFoundError(f"Part index not found: {index_path}")

        mtime = index_path.stat().st_mtime
        if (
            isinstance(self._parts_index_cache, dict)
            and self._parts_index_mtime == mtime
            and self._parts_index_path == str(index_path)
        ):
            return self._parts_index_cache

        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Invalid parts index format (expected object): {index_path}")
        parts = payload.get("parts")
        if not isinstance(parts, list):
            raise RuntimeError(f"Invalid parts index format: missing list field 'parts' in {index_path}")

        self._parts_index_cache = payload
        self._parts_index_mtime = mtime
        self._parts_index_path = str(index_path)
        return payload

    def _select_imported_occurrence_component(self, imported_occ):
        imported_comp = getattr(imported_occ, "component", None)
        if imported_comp is None:
            return imported_occ, None

        try:
            body_count = int(imported_comp.bRepBodies.count)
        except Exception:
            body_count = 0
        if body_count > 0:
            return imported_occ, imported_comp

        leaf_candidates = []

        def _walk_occ(occ):
            if occ is None or not getattr(occ, "isValid", False):
                return
            comp = getattr(occ, "component", None)
            if comp is not None and getattr(comp, "isValid", False):
                try:
                    comp_body_count = int(comp.bRepBodies.count)
                except Exception:
                    comp_body_count = 0
                if comp_body_count > 0:
                    leaf_candidates.append((occ, comp, comp_body_count))
            try:
                child_occs = occ.childOccurrences
                count = int(child_occs.count)
            except Exception:
                count = 0
                child_occs = None
            for idx in range(count):
                try:
                    child = child_occs.item(idx)
                except Exception:
                    continue
                _walk_occ(child)

        _walk_occ(imported_occ)

        unique = []
        seen = set()
        for occ, comp, comp_body_count in leaf_candidates:
            token = self._safe_entity_token(comp) or id(comp)
            if token in seen:
                continue
            seen.add(token)
            unique.append((occ, comp, comp_body_count))

        if len(unique) == 1:
            occ, comp, _ = unique[0]
            return occ, comp

        return imported_occ, imported_comp

    def _component_body_count(self, comp) -> int:
        best = 0
        for candidate in self._iter_component_variants(comp):
            try:
                bodies = getattr(candidate, "bRepBodies", None)
                count = int(getattr(bodies, "count", 0) or 0) if bodies is not None else 0
            except Exception:
                count = 0
            if count > best:
                best = count
        return best

    def _resolve_physical_component_from_occurrence(self, occ):
        if occ is None or not getattr(occ, "isValid", False):
            return None

        try:
            _, selected_comp = self._select_imported_occurrence_component(occ)
        except Exception:
            selected_comp = None

        if selected_comp is not None and getattr(selected_comp, "isValid", False):
            preferred = self._resolve_component_recovery_variant(selected_comp)
            if preferred is not None and getattr(preferred, "isValid", False):
                return preferred
            return selected_comp

        try:
            comp = getattr(occ, "component", None)
        except Exception:
            comp = None
        if comp is not None and getattr(comp, "isValid", False):
            preferred = self._resolve_component_recovery_variant(comp)
            if preferred is not None and getattr(preferred, "isValid", False):
                return preferred
            return comp
        return None

    def _promote_imported_occurrence_to_direct_child(self, *, imported_root_occ, selected_occ, target_comp):
        if selected_occ is None or not getattr(selected_occ, "isValid", False):
            return selected_occ

        parent_occ = None
        for attr in ("assemblyContext", "parentOccurrence"):
            try:
                candidate = getattr(selected_occ, attr, None)
            except Exception:
                candidate = None
            if candidate is not None and getattr(candidate, "isValid", False):
                parent_occ = candidate
                break

        if parent_occ is None and selected_occ is imported_root_occ:
            return selected_occ
        if parent_occ is None:
            return selected_occ
        if imported_root_occ is not None and getattr(imported_root_occ, "isValid", False):
            return imported_root_occ
        return selected_occ

    def _import_cad_as_component(
        self,
        file_path: Path,
        parent_component_id: str | None,
    ) -> dict:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"CAD file not found: {path}")

        stage = "resolve_target_component"
        self._append_import_debug_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "stage": "start",
                "path": str(path).replace("\\", "/"),
                "parent_component_id": parent_component_id,
            }
        )
        try:
            target_comp = self.root_comp if not parent_component_id else self._require_component(parent_component_id)
            if target_comp is None:
                raise RuntimeError("Import target component is invalid")

            import_manager = getattr(self.app, "importManager", None)
            if import_manager is None:
                raise RuntimeError("Fusion importManager is not available")

            stage = "create_import_options"
            suffix = path.suffix.lower()
            options = None
            if suffix in {".f3d", ".f3z"}:
                maker = getattr(import_manager, "createFusionArchiveImportOptions", None)
                if maker is None:
                    raise RuntimeError("Fusion archive import is not supported in this Fusion API build")
                options = maker(str(path))
            elif suffix in {".step", ".stp"}:
                maker = getattr(import_manager, "createSTEPImportOptions", None)
                if maker is None:
                    raise RuntimeError("STEP import is not supported in this Fusion API build")
                options = maker(str(path))
            else:
                raise RuntimeError(f"Unsupported CAD format for library import: {path.name}")

            stage = "snapshot_target_occurrences"
            before_tokens = set()
            before_count = 0
            try:
                occs = target_comp.occurrences
                before_count = int(occs.count)
                for i in range(occs.count):
                    occ = occs.item(i)
                    token = self._safe_entity_token(occ)
                    if token:
                        before_tokens.add(token)
            except Exception:
                before_tokens = set()
                before_count = 0

            stage = "import_to_target"
            try:
                import_manager.importToTarget(options, target_comp)
            except Exception as exc:
                raise RuntimeError(f"Import to target failed for '{path}': {exc}")

            stage = "identify_imported_occurrence"
            imported_occ = None
            try:
                occs = target_comp.occurrences
                after_count = int(occs.count)
                if after_count > before_count:
                    imported_occ = occs.item(before_count)
                for i in range(occs.count):
                    if imported_occ is not None:
                        break
                    occ = occs.item(i)
                    token = self._safe_entity_token(occ)
                    if token and token not in before_tokens:
                        imported_occ = occ
                        break
            except Exception:
                imported_occ = None

            if imported_occ is None:
                try:
                    occs = target_comp.occurrences
                    if occs.count > 0:
                        imported_occ = occs.item(occs.count - 1)
                except Exception:
                    imported_occ = None

            if imported_occ is None:
                raise RuntimeError(f"Imported CAD file but failed to identify new occurrence: {path}")

            imported_root_occ = imported_occ
            stage = "select_imported_occurrence_component"
            imported_occ, imported_comp = self._select_imported_occurrence_component(imported_occ)
            if imported_comp is None:
                raise RuntimeError(f"Imported occurrence has no component: {path}")
            selected_comp = imported_comp

            stage = "promote_imported_occurrence"
            imported_occ = self._promote_imported_occurrence_to_direct_child(
                imported_root_occ=imported_root_occ,
                selected_occ=imported_occ,
                target_comp=target_comp,
            )

            stage = "refresh_imported_component"
            refreshed_comp = None
            try:
                refreshed_comp = getattr(imported_occ, "component", None)
            except Exception:
                refreshed_comp = None
            if self._component_body_count(refreshed_comp) > 0:
                imported_comp = refreshed_comp
            elif self._component_body_count(selected_comp) > 0:
                imported_comp = selected_comp
            elif refreshed_comp is not None and getattr(refreshed_comp, "isValid", False):
                imported_comp = refreshed_comp
            if imported_comp is None or not getattr(imported_comp, "isValid", False):
                try:
                    selected_comp = self._resolve_physical_component_from_occurrence(imported_occ)
                except Exception:
                    selected_comp = None
                if selected_comp is not None and getattr(selected_comp, "isValid", False):
                    imported_comp = selected_comp
            if imported_comp is None or not getattr(imported_comp, "isValid", False):
                raise RuntimeError(f"Imported occurrence has no live component after promotion: {path}")

            stage = "allocate_import_ids"
            try:
                base_name = getattr(imported_comp, "name", None)
            except Exception:
                base_name = None
            base_name = base_name or path.stem
            component_id = self._new_component_id(str(base_name))
            occurrence_id = self._new_occurrence_id(str(base_name))

            stage = "cache_imported_entities"
            self._components[component_id] = imported_comp
            imported_occ = self._stabilize_occurrence_reference(occurrence_id, imported_occ)
            if not self.strict_mode:
                self._components.setdefault(str(base_name), imported_comp)
                self._occurrences.setdefault(str(base_name), imported_occ)

            self._append_import_debug_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "stage": "completed",
                    "path": str(path).replace("\\", "/"),
                    "component_id": component_id,
                    "occurrence_id": occurrence_id,
                    "component_name": str(base_name),
                    "occurrence_name": str(getattr(imported_occ, "name", "") or "") if imported_occ is not None else None,
                }
            )
            return {
                "component_id": component_id,
                "occurrence_id": occurrence_id,
                "parent_component_id": parent_component_id,
                "occurrence_transform_mode": "local",
            }
        except Exception as exc:
            self._append_import_debug_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "stage": stage,
                    "path": str(path).replace("\\", "/"),
                    "parent_component_id": parent_component_id,
                    "error": str(exc),
                }
            )
            raise

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def _rename_standard_part_identity(
        self,
        *,
        component_id: str | None,
        occurrence_id: str | None,
        component_name: str | None,
    ) -> None:
        if not isinstance(component_name, str) or not component_name:
            return
        if isinstance(component_id, str) and component_id in self._components:
            try:
                self._components[component_id].name = component_name
            except Exception:
                pass
        if isinstance(occurrence_id, str) and occurrence_id in self._occurrences:
            try:
                self._occurrences[occurrence_id].name = component_name
            except Exception:
                pass
            try:
                self._cache_occurrence(occurrence_id, self._occurrences[occurrence_id])
            except Exception:
                pass

    def _retire_occurrence_reference(self, occurrence_id: str | None) -> None:
        if not isinstance(occurrence_id, str) or not occurrence_id:
            return

        occ = self._occurrences.get(occurrence_id)
        if occ is None or not getattr(occ, "isValid", False):
            try:
                occ = self._require_occurrence(occurrence_id)
            except Exception:
                occ = None

        if occ is not None and getattr(occ, "isValid", False):
            try:
                occ.isLightBulbOn = False
            except Exception:
                pass
            try:
                occ.deleteMe()
            except Exception:
                pass

        self._occurrences.pop(occurrence_id, None)
        display_names = getattr(self, "_occurrence_display_names", None)
        if isinstance(display_names, dict):
            display_names.pop(occurrence_id, None)
        component_names = getattr(self, "_occurrence_component_names", None)
        if isinstance(component_names, dict):
            component_names.pop(occurrence_id, None)

        rotation_map = getattr(self, "_occurrence_last_rotation_rpy_deg", None)
        if isinstance(rotation_map, dict):
            rotation_map.pop(occurrence_id, None)

        occ_name_to_id = getattr(self, "_occ_name_to_id", None)
        if isinstance(occ_name_to_id, dict):
            stale_names = [name for name, mapped_id in occ_name_to_id.items() if mapped_id == occurrence_id]
            for name in stale_names:
                occ_name_to_id.pop(name, None)

    def _retire_component_occurrences(
        self,
        *,
        component=None,
        component_id: str | None = None,
    ) -> dict:
        summary = {"matched": 0, "deleted": 0, "hidden": 0, "failed": 0}

        target_component = component
        if (target_component is None or not getattr(target_component, "isValid", False)) and isinstance(component_id, str) and component_id:
            try:
                target_component = self._require_component(component_id)
            except Exception:
                target_component = None
        if target_component is None or not getattr(target_component, "isValid", False):
            return summary

        target_marker = self._entity_recovery_marker(target_component)
        target_token = self._safe_entity_token(target_component)

        for occ in self._iter_live_occurrences() or []:
            if occ is None or not getattr(occ, "isValid", False):
                continue
            try:
                occ_component = getattr(occ, "component", None)
            except Exception:
                occ_component = None
            if occ_component is None or not getattr(occ_component, "isValid", False):
                continue

            same_component = occ_component is target_component
            if not same_component and target_marker is not None:
                same_component = self._entity_recovery_marker(occ_component) == target_marker
            if not same_component and target_token:
                same_component = self._safe_entity_token(occ_component) == target_token
            if not same_component:
                continue

            summary["matched"] += 1

            hidden = False
            try:
                occ.isLightBulbOn = False
                hidden = True
            except Exception:
                hidden = False
            if hidden:
                summary["hidden"] += 1

            deleted = False
            try:
                deleted = bool(occ.deleteMe())
            except Exception:
                deleted = False
            if not deleted:
                deleted = not bool(getattr(occ, "isValid", False))
            if deleted:
                summary["deleted"] += 1
            else:
                summary["failed"] += 1

            mapped_ids = [oid for oid, mapped_occ in list(self._occurrences.items()) if mapped_occ is occ]
            for oid in mapped_ids:
                self._retire_occurrence_reference(oid)

        return summary

    def _live_occurrences_for_component(
        self,
        *,
        component=None,
        component_id: str | None = None,
    ) -> list:
        target_component = component
        if (target_component is None or not getattr(target_component, "isValid", False)) and isinstance(component_id, str) and component_id:
            try:
                target_component = self._require_component(component_id)
            except Exception:
                target_component = None
        if target_component is None or not getattr(target_component, "isValid", False):
            return []

        target_marker = self._entity_recovery_marker(target_component)
        target_token = self._safe_entity_token(target_component)
        matches = []

        for occ in self._iter_live_occurrences() or []:
            if occ is None or not getattr(occ, "isValid", False):
                continue
            try:
                occ_component = getattr(occ, "component", None)
            except Exception:
                occ_component = None
            if occ_component is None or not getattr(occ_component, "isValid", False):
                continue

            same_component = occ_component is target_component
            if not same_component and target_marker is not None:
                same_component = self._entity_recovery_marker(occ_component) == target_marker
            if not same_component and target_token:
                same_component = self._safe_entity_token(occ_component) == target_token
            if same_component:
                matches.append(occ)

        return matches

    def _materialize_standard_part_as_native_component(
        self,
        *,
        source_component_id: str,
        source_occurrence_id: str,
        component_name: str,
        parent_component_id: str | None,
    ) -> dict:
        """Copy imported standard-part geometry into a native component in the active design.

        Library imports can yield occurrence hierarchies/proxies that behave inconsistently
        across later transform and joint steps. Standard parts are therefore re-materialized
        into a fresh native component so the rest of the pipeline works against the same
        occurrence semantics as locally created parts.
        """
        if not isinstance(source_component_id, str) or not source_component_id:
            raise RuntimeError("Standard-part materialization requires source_component_id")
        if not isinstance(source_occurrence_id, str) or not source_occurrence_id:
            raise RuntimeError("Standard-part materialization requires source_occurrence_id")
        if not isinstance(component_name, str) or not component_name:
            raise RuntimeError("Standard-part materialization requires component_name")

        source_comp = self._require_component(source_component_id)

        created = self.CREATE_COMPONENT(name=component_name, parent_component_id=parent_component_id)
        target_component_id = created.get("component_id") if isinstance(created, dict) else None
        target_occurrence_id = created.get("occurrence_id") if isinstance(created, dict) else None
        if not isinstance(target_component_id, str) or not target_component_id:
            raise RuntimeError("Failed to create native standard-part component")
        if not isinstance(target_occurrence_id, str) or not target_occurrence_id:
            raise RuntimeError("Failed to create native standard-part occurrence")

        target_comp = self._require_component(target_component_id)
        candidate_bodies = []
        try:
            candidate_bodies = list(self._list_component_candidate_bodies(source_comp))
        except Exception:
            candidate_bodies = []
        if not candidate_bodies:
            try:
                source_occ = self._require_occurrence(source_occurrence_id)
            except Exception:
                source_occ = None
            try:
                candidate_bodies = list(self._iter_occurrence_candidate_bodies(source_occ))
            except Exception:
                candidate_bodies = []
        if not candidate_bodies:
            raise RuntimeError(f"Imported standard part '{component_name}' has no copyable bodies")

        copied_count = 0
        copy_paste_bodies = None
        try:
            copy_paste_bodies = target_comp.features.copyPasteBodies
        except Exception:
            copy_paste_bodies = None

        for body in candidate_bodies:
            if body is None or not getattr(body, "isValid", False):
                continue

            copied = None
            for candidate_body in self._iter_body_variants(body):
                if candidate_body is None or not getattr(candidate_body, "isValid", False):
                    continue
                if copy_paste_bodies is not None and hasattr(copy_paste_bodies, "add"):
                    try:
                        copied = copy_paste_bodies.add(candidate_body)
                    except Exception:
                        copied = None
                if copied is None and hasattr(candidate_body, "copyToComponent"):
                    try:
                        copied = candidate_body.copyToComponent(target_comp)
                    except Exception:
                        copied = None
                if copied is not None and getattr(copied, "isValid", False):
                    copied_count += 1
                    break

        if copied_count <= 0:
            raise RuntimeError(f"Failed to copy imported standard-part bodies for '{component_name}'")

        cleanup_summary = self._retire_component_occurrences(
            component=source_comp,
            component_id=source_component_id,
        )
        self._retire_occurrence_reference(source_occurrence_id)

        cleanup_rounds = 1
        residual_source_occurrences = self._live_occurrences_for_component(
            component=source_comp,
            component_id=source_component_id,
        )
        while residual_source_occurrences and cleanup_rounds < 3:
            extra_cleanup = self._retire_component_occurrences(
                component=source_comp,
                component_id=source_component_id,
            )
            for key in ("matched", "deleted", "hidden", "failed"):
                cleanup_summary[key] = int(cleanup_summary.get(key, 0)) + int(extra_cleanup.get(key, 0))
            cleanup_rounds += 1
            residual_source_occurrences = self._live_occurrences_for_component(
                component=source_comp,
                component_id=source_component_id,
            )

        residual_source_occurrence_names = []
        for residual_occ in residual_source_occurrences:
            try:
                residual_occ.isLightBulbOn = False
            except Exception:
                pass
            try:
                residual_source_occurrence_names.append(str(getattr(residual_occ, "name", "") or ""))
            except Exception:
                residual_source_occurrence_names.append("")
        residual_source_occurrence_names = [name for name in residual_source_occurrence_names if name]

        try:
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "insert",
                    "category": "standard_part_materialize",
                    "component_name": component_name,
                    "source_component_id": source_component_id,
                    "source_occurrence_id": source_occurrence_id,
                    "component_id": target_component_id,
                    "occurrence_id": target_occurrence_id,
                    "status": "materialized_native_component",
                    "copied_body_count": copied_count,
                    "source_cleanup": cleanup_summary,
                    "source_cleanup_rounds": cleanup_rounds,
                    "residual_source_occurrence_names": residual_source_occurrence_names,
                }
            )
        except Exception:
            pass

        return {
            "component_id": target_component_id,
            "occurrence_id": target_occurrence_id,
            "copied_body_count": copied_count,
        }

    def _ensure_distinct_standard_part_occurrence(
        self,
        *,
        occurrence_id: str,
        parent_component_id: str | None,
    ) -> str:
        """Ensure the returned occurrence_id points to a unique live occurrence object.

        Some Fusion import paths may resolve to an existing occurrence when the same
        local library CAD is imported repeatedly. If multiple logical ids point to
        the same occurrence object, later transform steps overwrite each other and
        parts appear stacked. This guard clones a new occurrence when aliasing is
        detected so each standard-part instance has an independent transform target.
        """
        try:
            if not isinstance(occurrence_id, str) or not occurrence_id:
                return occurrence_id

            occ = self._require_occurrence(occurrence_id)
            if occ is None or not getattr(occ, "isValid", False):
                return occurrence_id

            alias_ids = []
            for other_id, other_occ in self._occurrences.items():
                if other_id == occurrence_id:
                    continue
                if other_occ is occ:
                    alias_ids.append(other_id)

            if not alias_ids:
                return occurrence_id

            parent_comp = self.root_comp if not parent_component_id else self._require_component(parent_component_id)
            source_comp = getattr(occ, "component", None)
            if source_comp is None or not getattr(source_comp, "isValid", False):
                return occurrence_id

            identity = adsk.core.Matrix3D.create()
            cloned_occ = parent_comp.occurrences.addExistingComponent(source_comp, identity)
            if cloned_occ is None or not getattr(cloned_occ, "isValid", False):
                return occurrence_id

            new_occurrence_id = self._new_occurrence_id(str(getattr(source_comp, "name", "stdpart") or "stdpart"))
            cloned_occ = self._stabilize_occurrence_reference(new_occurrence_id, cloned_occ)
            try:
                self._append_standard_part_execution_log(
                    {
                        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                        "operation": "insert",
                        "category": "standard_part_guard",
                        "status": "occurrence_dedup_clone",
                        "original_occurrence_id": occurrence_id,
                        "cloned_occurrence_id": new_occurrence_id,
                        "aliased_with": alias_ids,
                    }
                )
            except Exception:
                pass
            return new_occurrence_id
        except Exception:
            # Never let guard failures affect primary import path.
            return occurrence_id
        if isinstance(occurrence_id, str) and occurrence_id in self._occurrences:
            try:
                self._occurrences[occurrence_id].name = component_name
            except Exception:
                pass
            try:
                self._cache_occurrence(occurrence_id, self._occurrences[occurrence_id])
            except Exception:
                pass

    def IMPORT_F3D_COMPONENT(
        self,
        component_name: str,
        file_path: str,
        parent_component_id: str | None = None,
        insert_as_occurrence: bool = True,
    ) -> dict:
        if not isinstance(component_name, str) or not component_name.strip():
            raise RuntimeError("IMPORT_F3D_COMPONENT requires a non-empty component_name")
        if not isinstance(file_path, str) or not file_path.strip():
            raise RuntimeError("IMPORT_F3D_COMPONENT requires a non-empty file_path")

        imported = self._import_cad_as_component(Path(file_path), parent_component_id)
        if not isinstance(imported, dict):
            raise RuntimeError("IMPORT_F3D_COMPONENT failed: invalid import result")

        status = "inserted_from_library" if insert_as_occurrence else "imported"
        return {
            "component_id": imported.get("component_id"),
            "occurrence_id": imported.get("occurrence_id"),
            "status": status,
            "message": None,
        }

    def _match_fastener_library_part(
        self,
        *,
        kind: str | None,
        standard: str | None,
        size: str | None,
        length_mm: float | None,
        designation: str | None,
        nominal_diameter_mm: float | None,
    ) -> dict | None:
        index = self._load_parts_index()
        parts = index.get("parts") if isinstance(index, dict) else None
        if not isinstance(parts, list):
            return None

        standard_s = standard.strip().upper() if isinstance(standard, str) and standard.strip() else None
        size_s = size.strip().upper() if isinstance(size, str) and size.strip() else None
        kind_s = kind.strip().lower() if isinstance(kind, str) and kind.strip() else None
        designation_s = designation.strip().upper() if isinstance(designation, str) and designation.strip() else None
        target_len = self._safe_float(length_mm)
        target_d = self._safe_float(nominal_diameter_mm)

        size_candidates: set[str] = set()
        if size_s:
            size_candidates.add(size_s)
            m = re.match(r"^(M\d+(?:\.\d+)?)(?:X.*)?$", size_s, re.IGNORECASE)
            if m:
                size_candidates.add(m.group(1).upper())
        if designation_s:
            m = re.search(r"(M\d+(?:\.\d+)?)(?:X\d+(?:\.\d+)?)?", designation_s, re.IGNORECASE)
            if m:
                size_candidates.add(m.group(1).upper())

        candidates = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if str(part.get("family", "")).strip().lower() != "fastener":
                continue
            part_kind = str(part.get("kind", "")).strip().lower()
            if kind_s and part_kind != kind_s:
                continue
            part_standard = str(part.get("standard", "")).strip().upper()
            if standard_s and part_standard and part_standard != standard_s:
                continue
            part_size = str(part.get("size", "")).strip().upper()
            if size_candidates and part_size and part_size not in size_candidates:
                continue

            if designation_s:
                part_designation = str(part.get("designation", "")).strip().upper()
                if part_designation and part_designation != designation_s:
                    continue

            part_len = self._safe_float(part.get("length_mm"))

            part_d = self._safe_float(part.get("nominal_diameter_mm"))
            if target_d is not None and part_d is not None and abs(part_d - target_d) > 0.02:
                continue

            candidates.append(part)

        if not candidates:
            return None

        def _score(entry: dict) -> tuple:
            entry_len = self._safe_float(entry.get("length_mm"))
            length_delta = abs((entry_len or 0.0) - (target_len or 0.0)) if target_len is not None else 0.0
            lod = str(entry.get("lod", "")).strip().lower()
            lod_rank = 0 if lod == "simplified" else 1
            return (length_delta, lod_rank, str(entry.get("part_id", "")))

        return sorted(candidates, key=_score)[0]

    def _match_bearing_library_part(
        self,
        *,
        designation: str | None,
        inner_diameter_mm: float | None,
        outer_diameter_mm: float | None,
        width_mm: float | None,
    ) -> dict | None:
        index = self._load_parts_index()
        parts = index.get("parts") if isinstance(index, dict) else None
        if not isinstance(parts, list):
            return None

        designation_s = designation.strip().upper() if isinstance(designation, str) and designation.strip() else None
        target_id = self._safe_float(inner_diameter_mm)
        target_od = self._safe_float(outer_diameter_mm)
        target_w = self._safe_float(width_mm)

        candidates = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if str(part.get("family", "")).strip().lower() != "bearing":
                continue

            if designation_s:
                part_designation = str(part.get("designation", "")).strip().upper()
                if part_designation != designation_s:
                    continue
            else:
                part_id = self._safe_float(part.get("inner_diameter_mm"))
                part_od = self._safe_float(part.get("outer_diameter_mm"))
                part_w = self._safe_float(part.get("width_mm"))
                if target_id is not None and part_id is not None and abs(part_id - target_id) > 0.02:
                    continue
                if target_od is not None and part_od is not None and abs(part_od - target_od) > 0.02:
                    continue
                if target_w is not None and part_w is not None and abs(part_w - target_w) > 0.02:
                    continue

            candidates.append(part)

        if not candidates:
            return None

        def _score(entry: dict) -> tuple:
            lod = str(entry.get("lod", "")).strip().lower()
            lod_rank = 0 if lod == "simplified" else 1
            return (lod_rank, str(entry.get("part_id", "")))

        return sorted(candidates, key=_score)[0]

    def _register_standard_part(
        self,
        *,
        component_id: str,
        component_name: str,
        is_placeholder: bool,
        metadata: dict | None = None,
    ) -> None:
        payload = {
            "component_id": component_id,
            "component_name": component_name,
            "is_placeholder": bool(is_placeholder),
            "metadata": metadata or {},
        }
        self._standard_parts["by_component_id"][component_id] = payload
        self._standard_parts["by_component_name"][component_name] = payload

    def _existing_occurrence_id(
        self,
        *,
        component_id: str | None = None,
        component_name: str | None = None,
    ) -> str | None:
        if isinstance(component_name, str) and component_name:
            occ_id = self._occ_name_to_id.get(component_name)
            if isinstance(occ_id, str) and occ_id:
                return occ_id

        if isinstance(component_id, str) and component_id:
            for name, mapped_component_id in self._component_name_to_id.items():
                if mapped_component_id != component_id:
                    continue
                occ_id = self._occ_name_to_id.get(name)
                if isinstance(occ_id, str) and occ_id:
                    return occ_id

        return None

    def _resolve_standard_part_presence(
        self,
        *,
        component_id: str | None = None,
        component_name: str | None = None,
    ) -> dict[str, Any]:
        comp_id = component_id
        if (not isinstance(comp_id, str) or not comp_id) and isinstance(component_name, str) and component_name:
            comp_id = self._component_name_to_id.get(component_name)

        occ_id = self._existing_occurrence_id(component_id=comp_id, component_name=component_name)

        comp = None
        if isinstance(comp_id, str) and comp_id:
            comp = self._components.get(comp_id)
            if comp is None or not getattr(comp, "isValid", False):
                try:
                    comp = self._recover_component_from_occurrence(comp_id)
                except Exception:
                    comp = None
        comp_exists = bool(comp is not None and getattr(comp, "isValid", False))

        occ = None
        if isinstance(occ_id, str) and occ_id:
            occ = self._occurrences.get(occ_id)
        occ_exists = bool(occ is not None and getattr(occ, "isValid", False))

        record = self._standard_part_record(component_id=comp_id, component_name=component_name)
        return {
            "component_id": comp_id,
            "occurrence_id": occ_id,
            "component_exists": comp_exists,
            "occurrence_exists": occ_exists,
            "record": record,
        }

    def _ensure_component_by_name(self, name: str, parent_component_id: str | None = None) -> dict:
        if name in self._component_name_to_id:
            comp_id = self._component_name_to_id[name]
            occ_id = self._occ_name_to_id.get(name)
            return {
                "component_id": comp_id,
                "occurrence_id": occ_id,
                "parent_component_id": parent_component_id,
                "occurrence_transform_mode": "local",
            }
        return self.CREATE_COMPONENT(name=name, parent_component_id=parent_component_id)

    def _coerce_mm(self, value: float | None, default: float) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _create_placeholder_fastener(
        self,
        *,
        component_name: str,
        nominal_diameter_mm: float | None,
        length_mm: float | None,
        parent_component_id: str | None,
        metadata: dict | None,
    ) -> dict:
        comp_info = self._ensure_component_by_name(component_name, parent_component_id)
        component_id = comp_info.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            raise RuntimeError("Failed to create fastener component")

        diameter = self._coerce_mm(nominal_diameter_mm, 5.0)
        length = self._coerce_mm(length_mm, max(10.0, diameter * 2.0))
        radius = max(0.1, diameter / 2.0)

        sketch = self.CREATE_SKETCH_ON_PLANE(
            component_id=component_id,
            name=f"{component_name}_sketch",
            plane={"type": "XY"},
        )
        profile = self.SKETCH_CIRCLE(
            sketch_id=sketch["sketch_id"],
            center={"x": 0, "y": 0, "z": 0},
            radius=radius,
        )
        extrude = self.EXTRUDE_NEW_BODY(
            component_id=component_id,
            profile_id=profile["profile_id"],
            distance=length,
        )

        self._register_standard_part(
            component_id=component_id,
            component_name=component_name,
            is_placeholder=True,
            metadata=metadata,
        )
        return {
            **comp_info,
            "body_id": extrude.get("body_id"),
        }

    def _create_placeholder_bearing(
        self,
        *,
        component_name: str,
        inner_diameter_mm: float | None,
        outer_diameter_mm: float | None,
        width_mm: float | None,
        parent_component_id: str | None,
        metadata: dict | None,
    ) -> dict:
        comp_info = self._ensure_component_by_name(component_name, parent_component_id)
        component_id = comp_info.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            raise RuntimeError("Failed to create bearing component")

        inner_d = self._coerce_mm(inner_diameter_mm, 8.0)
        outer_d = self._coerce_mm(outer_diameter_mm, 22.0)
        width = self._coerce_mm(width_mm, 7.0)
        if inner_d >= outer_d:
            outer_d = inner_d * 2.0
        inner_r = max(0.1, inner_d / 2.0)
        outer_r = max(inner_r + 0.1, outer_d / 2.0)

        sketch = self.CREATE_SKETCH_ON_PLANE(
            component_id=component_id,
            name=f"{component_name}_sketch",
            plane={"type": "XY"},
        )
        outer_profile = self.SKETCH_CIRCLE(
            sketch_id=sketch["sketch_id"],
            center={"x": 0, "y": 0, "z": 0},
            radius=outer_r,
        )
        extrude = self.EXTRUDE_NEW_BODY(
            component_id=component_id,
            profile_id=outer_profile["profile_id"],
            distance=width,
        )
        inner_profile = self.SKETCH_CIRCLE(
            sketch_id=sketch["sketch_id"],
            center={"x": 0, "y": 0, "z": 0},
            radius=inner_r,
        )
        self.EXTRUDE_CUT(
            component_id=component_id,
            profile_id=inner_profile["profile_id"],
            distance=width,
        )

        self._register_standard_part(
            component_id=component_id,
            component_name=component_name,
            is_placeholder=True,
            metadata=metadata,
        )
        return {
            **comp_info,
            "body_id": extrude.get("body_id"),
        }

    def INSERT_FASTENER_R1(
        self,
        component_name: str,
        kind: str | None = None,
        designation: str | None = None,
        standard: str | None = None,
        size: str | None = None,
        nominal_diameter_mm: float | None = None,
        length_mm: float | None = None,
        quantity: int | None = None,
        applied_to: list[str] | None = None,
        parent_component_id: str | None = None,
        insert_mode: str | None = None,
        allow_placeholder: bool | None = None,
    ) -> dict:
        insert_mode = (insert_mode or "auto").lower()
        if insert_mode == "library":
            insert_mode = "library_local"
        allow_placeholder = True if allow_placeholder is None else bool(allow_placeholder)

        message = None
        status = "not_inserted"
        matched = None
        cad_path = None
        ui_attempted = False

        if insert_mode in {"library_local", "auto"}:
            try:
                matched = self._match_fastener_library_part(
                    kind=kind,
                    standard=standard,
                    size=size,
                    length_mm=length_mm,
                    designation=designation,
                    nominal_diameter_mm=nominal_diameter_mm,
                )
                if not isinstance(matched, dict):
                    status = "library_missing"
                else:
                    cad_relpath = matched.get("cad_relpath")
                    if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                        raise RuntimeError("Matched library part has no cad_relpath")
                    cad_path = self._library_root() / cad_relpath
                    imported = self._import_cad_as_component(cad_path, parent_component_id)

                    component_id = imported.get("component_id") if isinstance(imported, dict) else None
                    occurrence_id = imported.get("occurrence_id") if isinstance(imported, dict) else None
                    if not isinstance(component_id, str) or not component_id:
                        raise RuntimeError("Library import did not return a valid component_id")
                    if not isinstance(occurrence_id, str) or not occurrence_id:
                        raise RuntimeError("Library import did not return a valid occurrence_id")
                    if getattr(self, "root_comp", None) is not None:
                        native_instance = self._materialize_standard_part_as_native_component(
                            source_component_id=component_id,
                            source_occurrence_id=occurrence_id,
                            component_name=component_name,
                            parent_component_id=parent_component_id,
                        )
                        component_id = native_instance.get("component_id") or component_id
                        occurrence_id = native_instance.get("occurrence_id") or occurrence_id
                    occurrence_id = self._ensure_distinct_standard_part_occurrence(
                        occurrence_id=occurrence_id,
                        parent_component_id=parent_component_id,
                    )
                    self._rename_standard_part_identity(
                        component_id=component_id,
                        occurrence_id=occurrence_id,
                        component_name=component_name,
                    )
                    self._component_name_to_id[component_name] = component_id
                    self._occ_name_to_id[component_name] = occurrence_id

                    self._register_standard_part(
                        component_id=component_id,
                        component_name=component_name,
                        is_placeholder=False,
                        metadata={
                            "source": "local_library",
                            "part_id": matched.get("part_id"),
                            "cad_path": str(cad_path).replace("\\", "/"),
                            "kind": kind,
                            "designation": designation,
                            "standard": standard,
                            "size": size,
                            "nominal_diameter_mm": nominal_diameter_mm,
                            "length_mm": length_mm,
                            "quantity": quantity,
                            "applied_to": applied_to,
                        },
                    )
                    self._append_standard_part_execution_log(
                        {
                            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                            "operation": "insert",
                            "category": "fastener",
                            "component_name": component_name,
                            "component_id": component_id,
                            "occurrence_id": occurrence_id,
                            "status": "inserted_from_library",
                            "branch": "library_local",
                            "ui_attempted": ui_attempted,
                            "used_placeholder": False,
                            "cad_path": str(cad_path).replace("\\", "/"),
                            "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                        }
                    )
                    return {
                        "component_id": component_id,
                        "occurrence_id": occurrence_id,
                        "used_placeholder": False,
                        "status": "inserted_from_library",
                        "message": None,
                    }
            except Exception as e:
                status = "library_missing"
                message = str(e)

        if insert_mode in {"fasteners_ui", "auto"}:
            ui_attempted = True
            try:
                cmd_def = None
                if hasattr(self.ui, "commandDefinitions"):
                    cmd_def = self.ui.commandDefinitions.itemById("InsertFastener")
                if cmd_def:
                    cmd_def.execute()
                    status = "fasteners_ui_invoked"
                else:
                    status = "fasteners_ui_not_found"
            except Exception as e:
                status = "fasteners_ui_failed"
                message = str(e)

        if allow_placeholder and insert_mode in {"placeholder", "auto"}:
            placeholder = self._create_placeholder_fastener(
                component_name=component_name,
                nominal_diameter_mm=nominal_diameter_mm,
                length_mm=length_mm,
                parent_component_id=parent_component_id,
                metadata={
                    "kind": kind,
                    "designation": designation,
                    "standard": standard,
                    "size": size,
                    "quantity": quantity,
                    "applied_to": applied_to,
                },
            )
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "insert",
                    "category": "fastener",
                    "component_name": component_name,
                    "component_id": placeholder.get("component_id"),
                    "occurrence_id": placeholder.get("occurrence_id"),
                    "status": "placeholder",
                    "branch": "placeholder",
                    "ui_attempted": ui_attempted,
                    "used_placeholder": True,
                    "cad_path": None,
                    "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                    "message": message,
                }
            )
            return {
                "component_id": placeholder.get("component_id"),
                "occurrence_id": placeholder.get("occurrence_id"),
                "used_placeholder": True,
                "status": "placeholder",
                "message": message,
            }

        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "insert",
                "category": "fastener",
                "component_name": component_name,
                "component_id": None,
                "occurrence_id": None,
                "status": status,
                "branch": "ui" if ui_attempted else insert_mode,
                "ui_attempted": ui_attempted,
                "used_placeholder": False,
                "cad_path": str(cad_path).replace("\\", "/") if cad_path else None,
                "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                "message": message,
            }
        )
        return {
            "component_id": None,
            "occurrence_id": None,
            "used_placeholder": False,
            "status": status,
            "message": message,
        }

    def VERIFY_FASTENER_R1(
        self,
        component_id: str | None = None,
        component_name: str | None = None,
        designation: str | None = None,
    ) -> dict:
        presence = self._resolve_standard_part_presence(component_id=component_id, component_name=component_name)
        comp_id = presence.get("component_id")
        record = presence.get("record") if isinstance(presence.get("record"), dict) else None

        if record and record.get("is_placeholder"):
            result = {
                "status": "placeholder",
                "component_id": comp_id,
                "is_placeholder": True,
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "verify",
                    "category": "fastener",
                    "component_name": component_name,
                    "component_id": comp_id,
                    "occurrence_id": presence.get("occurrence_id"),
                    "status": "placeholder",
                    "used_placeholder": True,
                }
            )
            return result

        if record or presence.get("component_exists") or presence.get("occurrence_exists"):
            result = {
                "status": "ok",
                "component_id": comp_id,
                "is_placeholder": False,
                "message": None if record else "live standard part preserved without registry record",
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "verify",
                    "category": "fastener",
                    "component_name": component_name,
                    "component_id": comp_id,
                    "occurrence_id": presence.get("occurrence_id"),
                    "status": "ok",
                    "used_placeholder": False,
                    "message": result["message"],
                }
            )
            return result

        result = {
            "status": "missing",
            "component_id": comp_id,
            "is_placeholder": None,
            "message": "component not found",
        }
        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "verify",
                "category": "fastener",
                "component_name": component_name,
                "component_id": comp_id,
                "occurrence_id": presence.get("occurrence_id"),
                "status": "missing",
                "used_placeholder": None,
                "message": result["message"],
            }
        )
        return result

    def REPLACE_FASTENER_R1(
        self,
        component_id: str | None = None,
        component_name: str | None = None,
        designation: str | None = None,
        standard: str | None = None,
        size: str | None = None,
        nominal_diameter_mm: float | None = None,
        length_mm: float | None = None,
        quantity: int | None = None,
        applied_to: list[str] | None = None,
        verify_status: str | None = None,
    ) -> dict:
        status = (verify_status or "").lower()
        existing_occ_id = self._existing_occurrence_id(
            component_id=component_id,
            component_name=component_name,
        )
        if status not in {"missing", "unknown"}:
            result = {
                "component_id": component_id,
                "occurrence_id": existing_occ_id,
                "used_placeholder": False,
                "action": "skipped",
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "replace",
                    "category": "fastener",
                    "component_name": component_name,
                    "component_id": component_id,
                    "occurrence_id": existing_occ_id,
                    "status": status or "ok",
                    "action": "skipped",
                    "used_placeholder": False,
                }
            )
            return result

        presence = self._resolve_standard_part_presence(component_id=component_id, component_name=component_name)
        record = presence.get("record") if isinstance(presence.get("record"), dict) else None
        if (presence.get("component_exists") or presence.get("occurrence_exists")) and not (record and record.get("is_placeholder")):
            result = {
                "component_id": presence.get("component_id") or component_id,
                "occurrence_id": presence.get("occurrence_id") or existing_occ_id,
                "used_placeholder": False,
                "action": "skipped_existing_live_standard_part",
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "replace",
                    "category": "fastener",
                    "component_name": component_name,
                    "component_id": result["component_id"],
                    "occurrence_id": result["occurrence_id"],
                    "status": status or "unknown",
                    "action": result["action"],
                    "used_placeholder": False,
                }
            )
            return result

        name = component_name or (designation or "fastener")
        placeholder = self._create_placeholder_fastener(
            component_name=name,
            nominal_diameter_mm=nominal_diameter_mm,
            length_mm=length_mm,
            parent_component_id=None,
            metadata={
                "designation": designation,
                "standard": standard,
                "size": size,
                "quantity": quantity,
                "applied_to": applied_to,
            },
        )
        result = {
            "component_id": placeholder.get("component_id"),
            "occurrence_id": placeholder.get("occurrence_id"),
            "used_placeholder": True,
            "action": "created_placeholder",
            "message": None,
        }
        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "replace",
                "category": "fastener",
                "component_name": component_name,
                "component_id": result["component_id"],
                "occurrence_id": result["occurrence_id"],
                "status": status or "missing",
                "action": result["action"],
                "used_placeholder": True,
            }
        )
        return result

    def INSERT_BEARING_R1(
        self,
        component_name: str,
        designation: str | None = None,
        inner_diameter_mm: float | None = None,
        outer_diameter_mm: float | None = None,
        width_mm: float | None = None,
        quantity: int | None = None,
        applied_to: list[str] | None = None,
        parent_component_id: str | None = None,
        insert_mode: str | None = None,
        allow_placeholder: bool | None = None,
    ) -> dict:
        insert_mode = (insert_mode or "auto").lower()
        if insert_mode == "library":
            insert_mode = "library_local"
        allow_placeholder = True if allow_placeholder is None else bool(allow_placeholder)

        message = None
        status = "not_inserted"
        matched = None
        cad_path = None
        ui_attempted = False

        if insert_mode in {"library_local", "auto"}:
            try:
                matched = self._match_bearing_library_part(
                    designation=designation,
                    inner_diameter_mm=inner_diameter_mm,
                    outer_diameter_mm=outer_diameter_mm,
                    width_mm=width_mm,
                )
                if not isinstance(matched, dict):
                    status = "library_missing"
                else:
                    cad_relpath = matched.get("cad_relpath")
                    if not isinstance(cad_relpath, str) or not cad_relpath.strip():
                        raise RuntimeError("Matched library part has no cad_relpath")
                    cad_path = self._library_root() / cad_relpath
                    imported = self._import_cad_as_component(cad_path, parent_component_id)

                    component_id = imported.get("component_id") if isinstance(imported, dict) else None
                    occurrence_id = imported.get("occurrence_id") if isinstance(imported, dict) else None
                    if not isinstance(component_id, str) or not component_id:
                        raise RuntimeError("Library import did not return a valid component_id")
                    if not isinstance(occurrence_id, str) or not occurrence_id:
                        raise RuntimeError("Library import did not return a valid occurrence_id")
                    if getattr(self, "root_comp", None) is not None:
                        native_instance = self._materialize_standard_part_as_native_component(
                            source_component_id=component_id,
                            source_occurrence_id=occurrence_id,
                            component_name=component_name,
                            parent_component_id=parent_component_id,
                        )
                        component_id = native_instance.get("component_id") or component_id
                        occurrence_id = native_instance.get("occurrence_id") or occurrence_id
                    occurrence_id = self._ensure_distinct_standard_part_occurrence(
                        occurrence_id=occurrence_id,
                        parent_component_id=parent_component_id,
                    )
                    self._rename_standard_part_identity(
                        component_id=component_id,
                        occurrence_id=occurrence_id,
                        component_name=component_name,
                    )
                    self._component_name_to_id[component_name] = component_id
                    self._occ_name_to_id[component_name] = occurrence_id

                    self._register_standard_part(
                        component_id=component_id,
                        component_name=component_name,
                        is_placeholder=False,
                        metadata={
                            "source": "local_library",
                            "part_id": matched.get("part_id"),
                            "cad_path": str(cad_path).replace("\\", "/"),
                            "designation": designation,
                            "inner_diameter_mm": inner_diameter_mm,
                            "outer_diameter_mm": outer_diameter_mm,
                            "width_mm": width_mm,
                            "quantity": quantity,
                            "applied_to": applied_to,
                        },
                    )
                    self._append_standard_part_execution_log(
                        {
                            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                            "operation": "insert",
                            "category": "bearing",
                            "component_name": component_name,
                            "component_id": component_id,
                            "occurrence_id": occurrence_id,
                            "status": "inserted_from_library",
                            "branch": "library_local",
                            "ui_attempted": ui_attempted,
                            "used_placeholder": False,
                            "cad_path": str(cad_path).replace("\\", "/"),
                            "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                        }
                    )
                    return {
                        "component_id": component_id,
                        "occurrence_id": occurrence_id,
                        "used_placeholder": False,
                        "status": "inserted_from_library",
                        "message": None,
                    }
            except Exception as e:
                status = "library_missing"
                message = str(e)

        if insert_mode in {"fasteners_ui", "auto"}:
            ui_attempted = True
            try:
                cmd_def = None
                if hasattr(self.ui, "commandDefinitions"):
                    cmd_def = self.ui.commandDefinitions.itemById("InsertBearings")
                if cmd_def:
                    cmd_def.execute()
                    status = "fasteners_ui_invoked"
                else:
                    status = "fasteners_ui_not_found"
            except Exception as e:
                status = "fasteners_ui_failed"
                message = str(e)

        if allow_placeholder and insert_mode in {"placeholder", "auto"}:
            placeholder = self._create_placeholder_bearing(
                component_name=component_name,
                inner_diameter_mm=inner_diameter_mm,
                outer_diameter_mm=outer_diameter_mm,
                width_mm=width_mm,
                parent_component_id=parent_component_id,
                metadata={
                    "designation": designation,
                    "quantity": quantity,
                    "applied_to": applied_to,
                },
            )
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "insert",
                    "category": "bearing",
                    "component_name": component_name,
                    "component_id": placeholder.get("component_id"),
                    "occurrence_id": placeholder.get("occurrence_id"),
                    "status": "placeholder",
                    "branch": "placeholder",
                    "ui_attempted": ui_attempted,
                    "used_placeholder": True,
                    "cad_path": None,
                    "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                    "message": message,
                }
            )
            return {
                "component_id": placeholder.get("component_id"),
                "occurrence_id": placeholder.get("occurrence_id"),
                "used_placeholder": True,
                "status": "placeholder",
                "message": message,
            }

        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "insert",
                "category": "bearing",
                "component_name": component_name,
                "component_id": None,
                "occurrence_id": None,
                "status": status,
                "branch": "ui" if ui_attempted else insert_mode,
                "ui_attempted": ui_attempted,
                "used_placeholder": False,
                "cad_path": str(cad_path).replace("\\", "/") if cad_path else None,
                "part_id": matched.get("part_id") if isinstance(matched, dict) else None,
                "message": message,
            }
        )
        return {
            "component_id": None,
            "occurrence_id": None,
            "used_placeholder": False,
            "status": status,
            "message": message,
        }

    def VERIFY_BEARING_R1(
        self,
        component_id: str | None = None,
        component_name: str | None = None,
        designation: str | None = None,
    ) -> dict:
        presence = self._resolve_standard_part_presence(component_id=component_id, component_name=component_name)
        comp_id = presence.get("component_id")
        record = presence.get("record") if isinstance(presence.get("record"), dict) else None

        if record and record.get("is_placeholder"):
            result = {
                "status": "placeholder",
                "component_id": comp_id,
                "is_placeholder": True,
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "verify",
                    "category": "bearing",
                    "component_name": component_name,
                    "component_id": comp_id,
                    "occurrence_id": presence.get("occurrence_id"),
                    "status": "placeholder",
                    "used_placeholder": True,
                }
            )
            return result

        if record or presence.get("component_exists") or presence.get("occurrence_exists"):
            result = {
                "status": "ok",
                "component_id": comp_id,
                "is_placeholder": False,
                "message": None if record else "live standard part preserved without registry record",
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "verify",
                    "category": "bearing",
                    "component_name": component_name,
                    "component_id": comp_id,
                    "occurrence_id": presence.get("occurrence_id"),
                    "status": "ok",
                    "used_placeholder": False,
                    "message": result["message"],
                }
            )
            return result

        result = {
            "status": "missing",
            "component_id": comp_id,
            "is_placeholder": None,
            "message": "component not found",
        }
        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "verify",
                "category": "bearing",
                "component_name": component_name,
                "component_id": comp_id,
                "occurrence_id": presence.get("occurrence_id"),
                "status": "missing",
                "used_placeholder": None,
                "message": result["message"],
            }
        )
        return result

    def REPLACE_BEARING_R1(
        self,
        component_id: str | None = None,
        component_name: str | None = None,
        designation: str | None = None,
        inner_diameter_mm: float | None = None,
        outer_diameter_mm: float | None = None,
        width_mm: float | None = None,
        quantity: int | None = None,
        applied_to: list[str] | None = None,
        verify_status: str | None = None,
    ) -> dict:
        status = (verify_status or "").lower()
        existing_occ_id = self._existing_occurrence_id(
            component_id=component_id,
            component_name=component_name,
        )
        if status not in {"missing", "unknown"}:
            result = {
                "component_id": component_id,
                "occurrence_id": existing_occ_id,
                "used_placeholder": False,
                "action": "skipped",
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "replace",
                    "category": "bearing",
                    "component_name": component_name,
                    "component_id": component_id,
                    "occurrence_id": existing_occ_id,
                    "status": status or "ok",
                    "action": "skipped",
                    "used_placeholder": False,
                }
            )
            return result

        presence = self._resolve_standard_part_presence(component_id=component_id, component_name=component_name)
        record = presence.get("record") if isinstance(presence.get("record"), dict) else None
        if (presence.get("component_exists") or presence.get("occurrence_exists")) and not (record and record.get("is_placeholder")):
            result = {
                "component_id": presence.get("component_id") or component_id,
                "occurrence_id": presence.get("occurrence_id") or existing_occ_id,
                "used_placeholder": False,
                "action": "skipped_existing_live_standard_part",
                "message": None,
            }
            self._append_standard_part_execution_log(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "operation": "replace",
                    "category": "bearing",
                    "component_name": component_name,
                    "component_id": result["component_id"],
                    "occurrence_id": result["occurrence_id"],
                    "status": status or "unknown",
                    "action": result["action"],
                    "used_placeholder": False,
                }
            )
            return result

        name = component_name or (designation or "bearing")
        placeholder = self._create_placeholder_bearing(
            component_name=name,
            inner_diameter_mm=inner_diameter_mm,
            outer_diameter_mm=outer_diameter_mm,
            width_mm=width_mm,
            parent_component_id=None,
            metadata={
                "designation": designation,
                "quantity": quantity,
                "applied_to": applied_to,
            },
        )
        result = {
            "component_id": placeholder.get("component_id"),
            "occurrence_id": placeholder.get("occurrence_id"),
            "used_placeholder": True,
            "action": "created_placeholder",
            "message": None,
        }
        self._append_standard_part_execution_log(
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "operation": "replace",
                "category": "bearing",
                "component_name": component_name,
                "component_id": result["component_id"],
                "occurrence_id": result["occurrence_id"],
                "status": status or "missing",
                "action": result["action"],
                "used_placeholder": True,
            }
        )
        return result

    def _get_edge_radius(self, edge: 'adsk.fusion.BRepEdge') -> float | None:
        """Extract radius from circular/elliptical edge if available."""
        try:
            if hasattr(edge, "geometry"):
                geom = edge.geometry
                if hasattr(geom, "radius"):
                    return float(geom.radius)
                elif hasattr(geom, "majorRadius"):
                    return float(geom.majorRadius)
        except:
            pass
        
        return None


# ============================================================
# Dev-only sanity check: Ensure no duplicate function definitions
# ============================================================
if False:  # Disabled by default; enable to debug
    import inspect
    _method_names = [name for name, method in inspect.getmembers(FusionApiController, predicate=inspect.isfunction)]
    _seen = {}
    for _name in _method_names:
        if _name.startswith('_'):
            continue
        if _name in _seen:
            raise RuntimeError(f"Duplicate public method defined: {_name}")
        _seen[_name] = True
    # List of expected public methods (maintained for sanity checks)
    _expected_methods = {
        'SKETCH_LINE', 'SKETCH_POLYLINE', 'SKETCH_ARC_3PT', 'SKETCH_CIRCLE_3PT',
        'SKETCH_CIRCLE', 'SKETCH_ELLIPSE', 'SKETCH_SLOT', 'SKETCH_TEXT',
        'SKETCH_RECTANGLE', 'SKETCH_REGULAR_POLYGON', 'SKETCH_ROUNDED_POLYGON',
        'SKETCH_FILLET', 'SKETCH_PROFILE_FROM_EDGES', 'SKETCH_MIRROR',
        'EXTRUDE_NEW_BODY', 'EXTRUDE_CUT', 'EXTRUDE_TO_FACE',
        'REVOLVE_NEW_BODY', 'REVOLVE_CUT', 'LOFT_NEW_BODY', 'SWEEP_NEW_BODY',
        'COMBINE_BODIES', 'FILLET_EDGES', 'CHAMFER_EDGES',
        'HOLE_SIMPLE', 'SHELL_BODIES',
        'CIRCULAR_PATTERN_BODIES', 'RECTANGULAR_PATTERN_BODIES',
        'OFFSET_FACES', 'THICKEN_SURFACES', 'OFFSET_FEATURE',
        'CREATE_JOINT_GEOMETRY', 'RIGID_AS_BUILT_JOINT', 'SLIDER_AS_BUILT_JOINT',
        'CYLINDRICAL_AS_BUILT_JOINT', 'PLANAR_AS_BUILT_JOINT', 'REVOLUTE_AS_BUILT_JOINT',
        'RIGID_JOINT_R1', 'REVOLUTE_JOINT_R1',
        'CREATE_REVOLUTE_JOINT', 'REVOLUTE_JOINT',
        'SET_JOINT_LIMITS', 'DRIVE_JOINT',
        'GROUND_OCCURRENCE', 'UNGROUND_OCCURRENCE', 'MOVE_OCCURRENCE',
        'LIST_COMPONENT_OCCURRENCES', 'LIST_ALL_OCCURRENCES',
        'LIST_BODY_FACES', 'LIST_BODY_EDGES', 'LIST_BODY_VERTICES',
    }
    _defined = set(_seen.keys())
    # Check for unexpected methods
    _unexpected = _defined - _expected_methods
    if _unexpected:
        print(f"Warning: Unexpected methods found: {_unexpected}")


