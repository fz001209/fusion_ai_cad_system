from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, Mapping

# capability_name -> executor handler mapping (table-driven)

CapabilityHandler = Callable[
	[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
	Mapping[str, Any],
]


def _dryrun_create_component(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	base = str(inputs.get("name") or "component")
	return {
		"component_id": base,
		"occurrence_id": f"occ::{base}",
	}


def _dryrun_create_sketch_on_plane(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	comp = str(inputs.get("component_id") or "component")
	name = inputs.get("name")
	suffix = str(name) if name else "sketch"
	return {
		"sketch_id": f"sk::{comp}::{suffix}",
		"sketch_plane": inputs.get("plane"),
	}


def _dryrun_sketch_rectangle(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	sketch = str(inputs.get("sketch_id") or "sketch")
	return {
		"curve_ids": [
			f"cv::{sketch}::1",
			f"cv::{sketch}::2",
			f"cv::{sketch}::3",
			f"cv::{sketch}::4",
		],
		"profile_id": f"pf::{sketch}::rect",
	}


def _dryrun_extrude_new_body(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	comp = str(inputs.get("component_id") or "component")
	profile = str(inputs.get("profile_id") or "profile")
	return {
		"body_id": f"bd::{comp}::{profile}",
		"feature_id": f"feat::{comp}::{profile}",
	}


def _dryrun_create_joint_geometry(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	entity = inputs.get("entity") if isinstance(inputs.get("entity"), Mapping) else {}
	entity_type = str(entity.get("type") or "entity")
	entity_id = str(
		entity.get("marker_id")
		or entity.get("face_id")
		or entity.get("edge_id")
		or entity.get("axis_id")
		or "unknown"
	)
	digest = hashlib.sha256(f"{entity_type}:{entity_id}".encode("utf-8")).hexdigest()[:10]
	return {
		"joint_geometry_id": f"jg::{entity_type}::{digest}",
	}


def _dryrun_resolve_interface(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	component_id = str(inputs.get("component_id") or "component")
	interface_name = str(inputs.get("interface_name") or "interface")
	recipe = inputs.get("recipe") if isinstance(inputs.get("recipe"), Mapping) else {}
	geometry_type = str(recipe.get("geometry_type") or "planar")
	digest_src = json.dumps(
		{
			"component_id": component_id,
			"interface_name": interface_name,
			"recipe": recipe,
		},
		ensure_ascii=False,
		sort_keys=True,
	)
	digest = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:12]
	entity_kind = "axis" if geometry_type == "axis" else "face"
	entity_id = f"{entity_kind}::{component_id}::{interface_name}::{digest}"
	return {
		"token_id": f"ifc:{component_id}:{interface_name}",
		"marker_id": f"mkr:ifc:{component_id}:{interface_name}",
		"entity_kind": entity_kind,
		"entity_id": entity_id,
		"geometry_summary": {
			"geometry_type": geometry_type,
			"fingerprint": digest,
		},
	}


def _dryrun_set_occurrence_transform_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	occurrence_id = str(inputs.get("occurrence_id") or "")
	return {
		"occurrence_id": occurrence_id,
		"applied": True,
	}


def _dryrun_rigid_mate_faces(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	a = inputs.get("face_ref_a")
	b = inputs.get("face_ref_b")
	a_tag = json.dumps(a, sort_keys=True, ensure_ascii=False) if isinstance(a, dict) else str(a)
	b_tag = json.dumps(b, sort_keys=True, ensure_ascii=False) if isinstance(b, dict) else str(b)
	digest = hashlib.sha256((a_tag + "|" + b_tag).encode("utf-8")).hexdigest()[:8]
	return {
		"mate_id": f"mate::{digest}",
	}


def _dryrun_insert_fastener_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	name = str(inputs.get("component_name") or "fastener")
	insert_mode = str(inputs.get("insert_mode") or "").strip().lower()
	if insert_mode == "library":
		insert_mode = "library_local"
	allow_placeholder = True if inputs.get("allow_placeholder") is None else bool(inputs.get("allow_placeholder"))

	if insert_mode == "library_local" and not allow_placeholder:
		return {
			"component_id": None,
			"occurrence_id": None,
			"used_placeholder": False,
			"status": "library_missing",
			"message": "dryrun: local library availability is not resolved",
		}

	return {
		"component_id": f"comp::{name}",
		"occurrence_id": f"occ::{name}",
		"used_placeholder": True,
		"status": "dryrun_placeholder",
		"message": None,
	}


def _dryrun_verify_fastener_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	return {
		"status": "ok",
		"component_id": inputs.get("component_id"),
		"is_placeholder": False,
		"message": None,
	}


def _dryrun_replace_fastener_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	name = str(inputs.get("component_name") or "fastener")
	return {
		"component_id": f"comp::{name}",
		"occurrence_id": f"occ::{name}",
		"used_placeholder": True,
		"action": "dryrun_placeholder",
		"message": None,
	}


def _dryrun_insert_bearing_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	name = str(inputs.get("component_name") or "bearing")
	insert_mode = str(inputs.get("insert_mode") or "").strip().lower()
	if insert_mode == "library":
		insert_mode = "library_local"
	allow_placeholder = True if inputs.get("allow_placeholder") is None else bool(inputs.get("allow_placeholder"))

	if insert_mode == "library_local" and not allow_placeholder:
		return {
			"component_id": None,
			"occurrence_id": None,
			"used_placeholder": False,
			"status": "library_missing",
			"message": "dryrun: local library availability is not resolved",
		}

	return {
		"component_id": f"comp::{name}",
		"occurrence_id": f"occ::{name}",
		"used_placeholder": True,
		"status": "dryrun_placeholder",
		"message": None,
	}


def _dryrun_verify_bearing_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	return {
		"status": "ok",
		"component_id": inputs.get("component_id"),
		"is_placeholder": False,
		"message": None,
	}


def _dryrun_replace_bearing_r1(
	inputs: Mapping[str, Any],
	step: Mapping[str, Any],
	registry: Mapping[str, Any],
	context: Mapping[str, Any],
) -> Mapping[str, Any]:
	name = str(inputs.get("component_name") or "bearing")
	return {
		"component_id": f"comp::{name}",
		"occurrence_id": f"occ::{name}",
		"used_placeholder": True,
		"action": "dryrun_placeholder",
		"message": None,
	}


DRYRUN_CAPABILITY_HANDLERS: Dict[str, CapabilityHandler] = {
	"CREATE_COMPONENT": _dryrun_create_component,
	"CREATE_SKETCH_ON_PLANE": _dryrun_create_sketch_on_plane,
	"SKETCH_RECTANGLE": _dryrun_sketch_rectangle,
	"EXTRUDE_NEW_BODY": _dryrun_extrude_new_body,
	"CREATE_JOINT_GEOMETRY": _dryrun_create_joint_geometry,
	"RESOLVE_INTERFACE": _dryrun_resolve_interface,
	"SET_OCCURRENCE_TRANSFORM_R1": _dryrun_set_occurrence_transform_r1,
	"RIGID_MATE_FACES": _dryrun_rigid_mate_faces,
	"INSERT_FASTENER_R1": _dryrun_insert_fastener_r1,
	"VERIFY_FASTENER_R1": _dryrun_verify_fastener_r1,
	"REPLACE_FASTENER_R1": _dryrun_replace_fastener_r1,
	"INSERT_BEARING_R1": _dryrun_insert_bearing_r1,
	"VERIFY_BEARING_R1": _dryrun_verify_bearing_r1,
	"REPLACE_BEARING_R1": _dryrun_replace_bearing_r1,
}


def get_dryrun_handler(capability_name: str) -> CapabilityHandler | None:
	return DRYRUN_CAPABILITY_HANDLERS.get(capability_name)

