from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class FusionApiNotAvailable(Exception):
    pass


def _mm_to_internal_length(value_mm: float) -> float:
    """Convert millimeters (pipeline unit) to Fusion internal length units.

    Use Fusion's UnitsManager when available, so this stays correct regardless
    of document settings. Fall back to cm-based scaling if conversion fails.
    """

    v = float(value_mm)
    try:
        design = get_design()
        um = getattr(design, "unitsManager", None)
        internal = getattr(um, "internalUnits", None)
        if um is not None and isinstance(internal, str) and internal:
            # evaluateExpression returns internal-unit value.
            return float(um.evaluateExpression(f"{v} mm", internal))
    except Exception:
        pass

    # Conservative fallback: many Fusion API geometry values are in centimeters.
    return v / 10.0


def _import_fusion() -> tuple[Any, Any]:
    """Import Fusion 360 Python API modules.

    This must only succeed inside Fusion's embedded Python environment.
    """

    try:
        import adsk.core  # type: ignore
        import adsk.fusion  # type: ignore
        return adsk.core, adsk.fusion
    except Exception as e:  # pragma: no cover
        print("[INFO] Fusion API (adsk.core/adsk.fusion) is not available. Run this executor inside Autodesk Fusion 360's Python environment.")
        return None, None


def get_app() -> Any:
    adsk_core, _ = _import_fusion()
    if adsk_core is None:
        print("[INFO] Fusion core API not available.")
        return None
    app = adsk_core.Application.get()
    if app is None:  # pragma: no cover
        print("[INFO] Failed to get Fusion Application.")
        return None
    return app


def get_design() -> Any:
    adsk_core, adsk_fusion = _import_fusion()
    if adsk_core is None or adsk_fusion is None:
        print("[INFO] Fusion API not available, cannot get design.")
        return None
    app = get_app()
    if app is None:
        return None
    def _cast_product(product: Any) -> Any:
        try:
            return adsk_fusion.Design.cast(product)
        except Exception:
            return None
    # 1) Common: activeProduct is already a Design.
    design = _cast_product(app.activeProduct)
    if design is not None:
        return design
    # 2) Try: activeDocument has a Design product.
    try:
        doc = app.activeDocument
    except Exception:
        doc = None
    if doc is not None:
        try:
            prod = doc.products.itemByProductType("DesignProductType")
            design = _cast_product(prod)
            if design is not None:
                return design
        except Exception:
            pass
    # 3) Best-effort: create a new design document and fetch its Design product.
    try:
        doc = app.documents.add(adsk_core.DocumentTypes.FusionDesignDocumentType)
        try:
            prod = doc.products.itemByProductType("DesignProductType")
            design = _cast_product(prod)
        except Exception:
            design = _cast_product(app.activeProduct)
    except Exception:
        design = None
    if design is None:  # pragma: no cover
        print("[INFO] No active Fusion design.")
        return None
    return design


def get_root_component() -> Any:
    design = get_design()
    if design is None:
        print("[INFO] No design available, cannot get root component.")
        return None
    root = design.rootComponent
    if root is None:  # pragma: no cover
        print("[INFO] No root component.")
        return None
    return root


def _identity_matrix() -> Any:
    adsk_core, _ = _import_fusion()
    return adsk_core.Matrix3D.create()


def _plane_from_type(component: Any, plane_type: str) -> Any:
    t = (plane_type or "").upper()
    if t == "XY":
        return component.xYConstructionPlane
    if t == "XZ":
        return component.xZConstructionPlane
    if t == "YZ":
        return component.yZConstructionPlane
    raise ValueError(f"Unsupported plane.type: {plane_type!r} (supported: XY/XZ/YZ)")


@dataclass(frozen=True, slots=True)
class CreatedComponent:
    component: Any
    occurrence: Any


def create_component(
    *,
    name: str,
    parent_component: Any | None,
    transform: Mapping[str, Any] | None,
) -> CreatedComponent:
    """Create a new component occurrence under the given parent component."""

    parent = parent_component or get_root_component()

    # Minimal transform support: translation only (backend-agnostic).
    # Expected form:
    #   {"translation": {"x": <mm>, "y": <mm>, "z": <mm>}}
    m = _identity_matrix()
    if isinstance(transform, Mapping):
        t = transform.get("translation")
        if isinstance(t, Mapping):
            try:
                adsk_core, _ = _import_fusion()
                tx = _mm_to_internal_length(float(t.get("x", 0.0)))
                ty = _mm_to_internal_length(float(t.get("y", 0.0)))
                tz = _mm_to_internal_length(float(t.get("z", 0.0)))
                m.translation = adsk_core.Vector3D.create(tx, ty, tz)
            except Exception:
                pass

    try:
        occ = parent.occurrences.addNewComponent(m)
        comp = occ.component
        try:
            comp.name = name
        except Exception:
            pass
        return CreatedComponent(component=comp, occurrence=occ)
    except Exception as e:
        # Fusion may be in a single-component ("part") design document, where adding
        # multiple components is not allowed. In that case, degrade gracefully by
        # reusing the root component and treating occurrence as not applicable.
        msg = str(e)
        if "只能包含一个零部件" in msg or "only" in msg.lower() and "one" in msg.lower() and "component" in msg.lower():
            root = get_root_component()
            return CreatedComponent(component=root, occurrence=None)
        raise


def create_sketch_on_plane(
    *,
    component: Any,
    plane: Mapping[str, Any],
    name: str | None,
) -> tuple[Any, Mapping[str, Any]]:
    """Create a sketch on a construction plane and return (sketch, normalized_plane)."""

    plane_type = str(plane.get("type"))
    construction_plane = _plane_from_type(component, plane_type)

    sketch = component.sketches.add(construction_plane)
    if name:
        try:
            sketch.name = str(name)
        except Exception:
            pass

    normalized_plane = {"type": plane_type.upper()}
    return sketch, normalized_plane


def sketch_rectangle(
    *,
    sketch: Any,
    center: Mapping[str, Any],
    width: float,
    height: float,
) -> tuple[list[Any], Any]:
    """Draw a center rectangle and return (lines, profile)."""

    adsk_core, _ = _import_fusion()

    cx = _mm_to_internal_length(float(center.get("x", 0.0)))
    cy = _mm_to_internal_length(float(center.get("y", 0.0)))

    hw = _mm_to_internal_length(float(width)) / 2.0
    hh = _mm_to_internal_length(float(height)) / 2.0

    p1 = adsk_core.Point3D.create(cx - hw, cy - hh, 0)
    p2 = adsk_core.Point3D.create(cx + hw, cy - hh, 0)
    p3 = adsk_core.Point3D.create(cx + hw, cy + hh, 0)
    p4 = adsk_core.Point3D.create(cx - hw, cy + hh, 0)

    lines = sketch.sketchCurves.sketchLines
    l1 = lines.addByTwoPoints(p1, p2)
    l2 = lines.addByTwoPoints(p2, p3)
    l3 = lines.addByTwoPoints(p3, p4)
    l4 = lines.addByTwoPoints(p4, p1)

    profiles = sketch.profiles
    if profiles.count < 1:
        raise RuntimeError("No profile was created by SKETCH_RECTANGLE")

    profile = profiles.item(profiles.count - 1)
    return [l1, l2, l3, l4], profile


def sketch_circle(
    *,
    sketch: Any,
    center: Mapping[str, Any],
    radius: float,
) -> tuple[list[Any], Any]:
    """Draw a circle and return (curves, profile)."""

    adsk_core, _ = _import_fusion()

    cx = _mm_to_internal_length(float(center.get("x", 0.0)))
    cy = _mm_to_internal_length(float(center.get("y", 0.0)))
    r = _mm_to_internal_length(float(radius))
    if r <= 0:
        raise ValueError("SKETCH_CIRCLE requires radius > 0")

    p = adsk_core.Point3D.create(cx, cy, 0)
    circles = sketch.sketchCurves.sketchCircles
    c = circles.addByCenterRadius(p, r)

    profiles = sketch.profiles
    if profiles.count < 1:
        raise RuntimeError("No profile was created by SKETCH_CIRCLE")
    profile = profiles.item(profiles.count - 1)
    return [c], profile


def extrude_new_body(
    *,
    component: Any,
    profile: Any,
    distance: float,
    direction: str | None,
    draft_angle: float | None,
) -> tuple[Any, Any]:
    """Extrude a profile into a new body and return (feature, body)."""

    adsk_core, adsk_fusion = _import_fusion()

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk_fusion.FeatureOperations.NewBodyFeatureOperation)

    dist_value = adsk_core.ValueInput.createByReal(_mm_to_internal_length(float(distance)))
    ext_input.setDistanceExtent(False, dist_value)

    # Best-effort direction support
    if direction is not None:
        d = str(direction).lower()
        if d in {"negative", "reverse", "-", "neg"}:
            if hasattr(ext_input, "isDirectionFlipped"):
                ext_input.isDirectionFlipped = True

    # Draft support is optional; keep MVP minimal.
    _ = draft_angle

    feature = extrudes.add(ext_input)
    bodies = feature.bodies
    if bodies.count < 1:
        raise RuntimeError("EXTRUDE_NEW_BODY produced no bodies")
    body = bodies.item(0)
    return feature, body


def _face_point_z(face: Any) -> float:
    try:
        p = getattr(face, "pointOnFace", None)
        if p is not None:
            return float(getattr(p, "z", 0.0))
    except Exception:
        pass
    try:
        bb = getattr(face, "boundingBox", None)
        if bb is not None:
            max_pt = getattr(bb, "maxPoint", None)
            min_pt = getattr(bb, "minPoint", None)
            if max_pt is not None and min_pt is not None:
                return float(getattr(max_pt, "z", 0.0) + getattr(min_pt, "z", 0.0)) / 2.0
    except Exception:
        pass
    return 0.0


def _face_normal_z(face: Any) -> float | None:
    try:
        geom = getattr(face, "geometry", None)
        n = getattr(geom, "normal", None)
        if n is not None:
            return float(getattr(n, "z", 0.0))
    except Exception:
        return None
    return None


def select_interface_face(*, body: Any, interface_id: str) -> Any:
    """Map semantic interface ids to a planar face (best-effort).

    Supported (MVP):
    - top_surface: highest-Z planar face (prefer +Z normal)
    - bottom_surface: lowest-Z planar face (prefer -Z normal)
    """

    interface = (interface_id or "").strip().lower()
    faces = getattr(body, "faces", None)
    if faces is None or getattr(faces, "count", 0) < 1:
        raise RuntimeError("Body has no faces; cannot select interface")

    candidates: list[Any] = [faces.item(i) for i in range(faces.count)]

    def score(face: Any) -> float:
        z = _face_point_z(face)
        nz = _face_normal_z(face)
        if interface == "top_surface":
            bonus = 1000.0 if (nz is not None and nz > 0.5) else 0.0
            return bonus + z
        if interface == "bottom_surface":
            bonus = 1000.0 if (nz is not None and nz < -0.5) else 0.0
            return bonus - z
        return z

    return max(candidates, key=score)


def rigid_attach_occurrences(*, occ_a: Any, occ_b: Any, face_a: Any, face_b: Any, name: str | None) -> Any:
    """Create a rigid attachment between two occurrences.

    Best-effort strategy:
    1) Try As-Built Joint of rigid type.
    2) If that fails (API mismatch / not supported), ground occ_b.
    """

    adsk_core, adsk_fusion = _import_fusion()
    design = get_design()
    root = design.rootComponent

    try:
        as_built = getattr(root, "asBuiltJoints", None)
        jg_cls = getattr(adsk_fusion, "JointGeometry", None)
        jt_enum = getattr(adsk_fusion, "JointTypes", None)

        if as_built is not None and jg_cls is not None and jt_enum is not None and hasattr(jg_cls, "createByPlanarFace"):
            key_types = getattr(adsk_fusion, "JointKeyPointTypes", None)
            center_kp = getattr(key_types, "CenterKeyPoint", None) if key_types is not None else None

            try:
                jg = jg_cls.createByPlanarFace(face_a, center_kp) if center_kp is not None else jg_cls.createByPlanarFace(face_a)
            except Exception:
                jg = jg_cls.createByPlanarFace(face_a)

            if hasattr(as_built, "createInput"):
                ji = as_built.createInput(occ_a, occ_b, jg)
                try:
                    if name:
                        ji.name = str(name)
                except Exception:
                    pass
                try:
                    jm = getattr(ji, "jointMotion", None)
                    if jm is not None and hasattr(jm, "jointType"):
                        jm.jointType = jt_enum.RigidJointType
                except Exception:
                    pass
                return as_built.add(ji)

            j = as_built.add(occ_a, occ_b, jg)
            try:
                jm = getattr(j, "jointMotion", None)
                if jm is not None and hasattr(jm, "jointType"):
                    jm.jointType = jt_enum.RigidJointType
            except Exception:
                pass
            return j
    except Exception:
        pass

    # Safe fallback: try to lock/ground the second occurrence so it doesn't float.
    for prop in ("isGrounded", "isFixed", "isLocked"):
        try:
            if hasattr(occ_b, prop):
                setattr(occ_b, prop, True)
                return occ_b
        except Exception:
            continue

    # Last resort: return something non-fatal to keep the pipeline moving.
    return occ_b
