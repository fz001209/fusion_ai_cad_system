"""Agent1 input/environment helpers and LLM prompt construction."""

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

FASTENER_DIAMETERS = [2, 3, 4, 5, 6, 8, 10, 12]

FASTENER_LENGTHS = [4, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 50]

STANDARD_SHAFT_DIAMETERS = [6, 8, 10, 12]

DECOMPOSITION_CONFIDENCE_THRESHOLD = 0.72

DECOMPOSITION_MAX_ADDED_RATIO = 1.25

FEATURE_LIKE_TYPES = {
    "feature",
    "hole",
    "slot",
    "fillet",
    "chamfer",
    "thread",
    "groove",
    "pocket",
    "boss",
}

def _nearest_option(value: float, options: list[int]) -> int:
    return min(options, key=lambda x: abs(x - value))

def _nearest_fastener_designation(nominal: float, length: float) -> str:
    dia = _nearest_option(float(nominal), FASTENER_DIAMETERS)
    leng = _nearest_option(float(length), FASTENER_LENGTHS)
    return f"M{int(dia)}x{int(leng)}"

def _is_fastener_family_type(component_type: str | None) -> bool:
    if not isinstance(component_type, str):
        return False
    value = component_type.strip().lower()
    return value in {
        "fastener",
        "fastener_set",
        "bolt_set",
        "nut_set",
        "bolt",
        "screw",
        "nut",
        "washer",
        "pin",
        "key",
        "rivet",
        "spacer",
        "standoff_set",
    }

def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _load_repo_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        if not key:
            continue
        parsed[key] = value.strip().strip('"').strip("'")

    override = parsed.get("AGENT1_ENV_OVERRIDE", os.getenv("AGENT1_ENV_OVERRIDE", "0")).strip().lower()
    should_override = override in {"1", "true", "on", "yes"}
    runtime_preferred_keys = {"AGENT1_ENABLE_WHEEL_RULES"}
    for key, value in parsed.items():
        if key in runtime_preferred_keys and key in os.environ:
            continue
        if should_override or key not in os.environ:
            os.environ[key] = value

def _normalize_purpose(purpose: str | None) -> str:
  if not isinstance(purpose, str):
    return ""
  value = purpose.strip().lower()
  mapping = {
    "support": "support_to_structure",
    "bearing_support": "support_to_structure",
    "bearing_seat": "support_to_structure",
    "support_to_structure": "support_to_structure",
    "load_support": "load_support",
    "load_bearing": "load_support",
    "fixation": "structural_fixation",
    "structural_fixation": "structural_fixation",
    "clamping": "structural_clamping",
    "structural_clamping": "structural_clamping",
    "fastening": "fastening_mechanism",
    "fastening_mechanism": "fastening_mechanism",
    "bolted_joint": "fastening_mechanism",
    "bolted": "fastening_mechanism",
    "rotation": "rotation",
    "torque_transfer": "torque_transfer",
    "alignment": "alignment",
    "spacing": "spacing",
  }
  return mapping.get(value, value)

def _derive_roles_from_purpose(purpose: str) -> list[str]:
    """Derive semantic roles from normalized connection purpose."""
    purpose_to_roles = {
        "rotation": {"rotation"},
        "torque_transfer": {"rotation", "torque_transfer"},
        "structural_fixation": {"mounting", "fixation"},
        "structural_clamping": {"mounting"},
        "fastening_mechanism": {"mounting", "fixation"},
        "support_to_structure": {"support"},
        "load_support": {"support"},
        "alignment": {"mounting"},
        "spacing": {"mounting"},
    }
    roles = purpose_to_roles.get(purpose, {"mounting"})
    return sorted(roles)

def _build_type_map(components: list) -> dict[str, str]:
    """Build {component_id: component_type} mapping from a components list."""
    result: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, Mapping):
            continue
        cid = comp.get("id")
        ctype = comp.get("type")
        if isinstance(cid, str) and isinstance(ctype, str):
            result[cid] = ctype
    return result

def build_requirement_to_kg_prompt(requirement_text: str) -> str:
    prompt = """You are an engineering requirement interpretation agent for a mechanical CAD synthesis system.

Your task is NOT to generate geometry, coordinates, CAD steps, or layouts.

Your only responsibility is to fully understand the design intent expressed in the requirement file and convert it into a complete, non-simplified, structural knowledge graph suitable for downstream reasoning and planning.

User Requirements (in Chinese):
```yaml
""" + requirement_text + """
```

TASK DEFINITION (Agent 1's Single Responsibility):

Given a YAML requirement file describing a mechanical product or mechanism:

Produce a knowledge_graph.json that represents:
1. All required components (including components not explicitly mentioned but logically necessary)
2. Component properties, shape semantics, and immutable dimensions (sizes, roles, categories)
3. Inter-component relationships and constraints

闁?CRITICAL CONSTRAINTS:
   - Do NOT define any absolute or relative spatial coordinates
   - Do NOT simplify the design by omitting structurally necessary parts
   - Do NOT generate CAD operations, sketches, or manufacturing steps
   - Do NOT make geometry decisions that belong to downstream planning agents

Your job is INTERPRETATION and STRUCTURE, not CAD geometry or manufacturing.

NEW REQUIREMENT:
You MUST output abstract shape semantics and complete, immutable dimensions for every component.
- shape_semantics: type + cross_section + optional axis/notes (semantic only, no coordinates)
- dimensions: all required sizes (must be numeric, inferred using typical proportions when not explicit)
- dimension_sources: source + confidence for each dimension (input/standard_catalog/inferred_default/derived)
- parameters MUST mirror dimensions exactly (legacy compatibility)

RELATIONS RULE:
- Do NOT output relations[] in Agent1.
- Only output connection_requirements (facts + intent).

CONNECTION DECISION REQUIREMENT:
- If a connection involves clamping/fastening OR a fastener component exists, you MUST output connection_decision
- For bolted connections, connection_decision.method + count + fastener_size are REQUIRED
- Output standard_parts[] with catalog designations (e.g., ISO 4762 M4x12, 608ZZ)
- standard_parts MUST be real catalog items (choose closest standard size if needed)
- DO NOT output location_intent; that will be inferred by Agent2 based on Agent1's connection topology

FROZEN CONNECTION SEMANTICS CONTRACT (NEW, REQUIRED FOR MECHANICALLY RESOLVED CONNECTIONS):
- For every connection_requirement whose purpose is rotation / rotation_support / torque_transfer / structural_fixation / structural_clamping / fastening_mechanism / load_support / support_to_structure / spacing, you MUST output connection_semantics
- connection_semantics MUST include: connection_mechanism, relation_type, reference_component_id, moving_component_id, reference_anchor, moving_anchor, reference_interface_hint, moving_interface_hint, orientation_policy, geometric_semantics
- geometric_semantics MUST include: contact_model, reference_feature_strategy, moving_feature_strategy, pattern_policy, and pattern_count when pattern_policy implies an array
- relation_type MUST be geometrically specific; generic values like fastening / fixation / support / rotation are forbidden
- pattern_policy and pattern_count, not fastener bundle quantity, decide whether the mount is single or an array
- reference_anchor and moving_anchor MUST be JSON objects, never bare strings
- Allowed anchor kinds are: component_center, distal_end, proximal_end, radial_mount_perimeter, axial_face_perimeter_max, axial_face_perimeter_min, proximal_mount_face_min, proximal_mount_face_max
- Use concrete interface hints such as bore_axis, axial_end_face_max, distal_mount_face, radial_outer_face; placeholders like fixation_req / mounting_req / unspecified are forbidden
- If an arm connects to a hub, the arm-side anchor is its proximal mount; if an arm supports an axle, the arm-side anchor is its distal end
- If a tire attaches to a rim, use bonded_tread or press_fit semantics; do NOT model that as a bolted hole pattern through the tire
- These are abstract semantic anchors and interface hints, NOT coordinates
- Downstream agents are allowed to execute or reject this contract, but NOT reinterpret it into a different mechanism
- generic_mount is NOT acceptable when a concrete mechanical realization is inferable from the requirement

STANDARD PARTS FORMAT:
- standard_parts[] entries MUST include: category, designation, quantity, applied_to, selection_rationale
- applied_to should reference connection_requirement ids or subassembly ids

CONNECTION PURPOSE & ROLES REQUIREMENT:
- Every connection_requirement MUST include a normalized purpose (e.g., rotation, torque_transfer, structural_fixation, fastening_mechanism)
- Every connection_requirement MUST include roles (array of semantic roles), derived from purpose if not explicitly stated
- connection_requirements MAY include constraints (must_rotate / must_be_rigid / must_support_load / must_limit_axial)
- Roles examples: mounting, rotation, support, fixation, torque_transfer

---

STRICT PROHIBITIONS (DO NOT VIOLATE THESE):

闁?Assign absolute positions, translations, rotations, or coordinates
   - No (x, y, z) coordinates for component placement
   - No angles used for positioning components
   - No layout or spatial decisions of any kind

闁?Generate CAD-oriented abstractions
   - No "sketches" as design elements
   - No "extrusions" or "revolutions"
   - Avoid CAD jargon; use engineering language instead

闁?Reduce the design to "minimal rigid bodies"
   - Do NOT assume wheels, arms, hubs are monolithic solids
   - Do NOT collapse assemblies into single parts
   - Include all structurally and functionally necessary parts

闁?Decide how parts are manufactured or modeled in CAD
   - That decision belongs to downstream agents (plan_geometry_semantic, compile_semantics_to_cad)
   - Your job is STRUCTURE, not MANUFACTURING

---

闁?REQUIRED BEHAVIOR (YOU MUST DO THESE):

1闁挎柨绻嗛崕?Complete Semantic Understanding (no task simplification)

You MUST assume that:
   - The design intent is engineering-realistic, not conceptual
   - If a function or connection cannot exist physically without a component, that component MUST be included
   
Examples:
   - A rotating wheel 闁?implies axle/bearing/spacer
   - A rigid plate-to-plate connection 闁?implies fasteners (bolts, washers, nuts)
   - Load-bearing rotating hub 闁?implies bearing seats or bearing cartridges
   - Repeated symmetric structures 闁?imply patterned subassemblies, NOT copied coordinates

2闁挎柨绻嗛崕?Component Set = Explicit + Inferred (Semantic Closure)

Your output MUST include:

a) Explicitly mentioned components (hub, wheel arm, wheel, carrier plates)

b) Inferred but necessary components:
   - Axles / shafts (if components rotate about an axis)
   - Module input/drive shafts (if the ENTIRE MODULE rotates or receives rotational input)
   - Bearings (if there is rotational motion or load transfer)
   - Spacers / bushings / washers (for spacing and alignment)
   - Fasteners (bolts, nuts, washers, pins, rivets)
   - Structural interfaces (flanges, bearing seats, mounting pads)
   - Alignment components (dowel pins, keys, splines)

妫ｅ啯鏆?**MODULE-LEVEL MOTION INFERENCE (CRITICAL):**

If the requirement describes MODULE-LEVEL rotational motion (e.g., "the entire module rotates"),
you MUST infer a module input shaft or drive axis component.

Examples:
- **"The tri-star wheel module can rotate as a whole"** 
  闁?MUST add: a module input shaft component (e.g., "module_drive_shaft", "central_rotation_input")
  闁?This shaft connects to the central_hub and provides rotational input to the entire assembly
  闁?Connection_requirement: {"between": ["module_drive_shaft", "central_hub"], "purpose": "torque_transfer"}

- **"The assembly spins around its center axis"** 
  闁?MUST add: a central_input_axis component
  闁?This axis passes through the hub and enables module-level rotation

- **Wheels rotate individually BUT the module rotates as a whole**
  闁?Do NOT confuse individual wheel rotation with module rotation
  闁?Both require separate components: wheel_axles (for wheel rotation) AND module_drive_shaft (for module rotation)
  闁?These are two different input mechanisms

妫ｅ啯鏆?**CRITICAL: Without a MODULE INPUT component, module-level rotation is MECHANICALLY IMPOSSIBLE.**

If a requirement says "the module rotates", you MUST create a corresponding component in the KG.
This is NOT optional. It is a structural requirement.

Do NOT confuse module-level rotation with individual wheel rotation.

Each inferred component must have:
   - id: unique identifier
   - type: category (shaft, bearing, fastener, spacer, plate, arm, etc.)
   - role: functional role (load-bearing, rotating_interface, fixation, spacing, alignment)
  - shape_semantics: abstract shape description (type + cross_section, no coordinates)
  - dimensions: complete numeric dimensions (immutable)
  - dimension_sources: per-dimension provenance (explicit or derived)
  - parent_id: which parent component it belongs to (optional)

妫ｅ啯鏆?**COMPLEX COMPONENT DECOMPOSITION (REQUIRED):**

If a component is mechanically composite, you MUST decompose it into subcomponents.
Examples:
- Wheel 闁?tire + hub + fasteners (and possibly bearing seat)
- Track module 闁?rollers + frame + fasteners
- Motorized module 闁?motor + coupling + shaft + fasteners

Use subassemblies to group such composite parts and ensure their internal connections exist.

闁宠法濯寸粭?CONNECTION SEMANTIC CLOSURE (CRITICAL):

When interpreting the requirement file, you MUST assume that any fixed or clamped relationship 
between structural components requires explicit connecting components.

Specifically:
- Any "fixed_to" relationship between load-bearing or structural parts implies the existence 
  of fasteners and/or spacers.
- Fasteners (e.g. bolts, screws, nuts, washers, pins) MUST be explicitly represented as 
  components when they are structurally necessary to realize a constraint.
- Do NOT omit fasteners simply to simplify the model.
- If the requirement describes a mechanically realistic product, assume realistic fastening 
  unless explicitly stated otherwise.

Each inferred fastener component must include:
- type: fastener
- role: fixation / clamping / load_transfer
- parameters: approximate numeric parameter placeholders (e.g. nominal_diameter, count, length) if inferable
  NOTE: All parameter values must be numbers, not strings. Do NOT use string values like "bolt_with_nut".

Example:
```json
{
  "id": "hub_to_arm_fastener_set",
  "type": "fastener",
  "role": "fixation",
  "shape_semantics": {"type": "cylindrical", "cross_section": "circular"},
  "dimensions": {
    "nominal_diameter": 3,
    "count": 3,
    "length": 8
  },
  "dimension_sources": {
    "nominal_diameter": {"source": "explicit"},
    "count": {"source": "explicit"},
    "length": {"source": "explicit"}
  },
  "parameters": {
    "nominal_diameter": 3,
    "count": 3,
    "length": 8
  }
}
```

3闁挎柨绻嗛崕?Connection Requirements Instead of Relations (CRITICAL NEW BEHAVIOR)

妫ｅ啯鏆?CRITICAL PROHIBITION:

You are NOT allowed to emit a legacy `relations[]` section with unconstrained CAD-style
labels like `fixed_to`, `rotates_about`, or `supported_by`.

Agent1 MUST still define the mechanical contract in `connection_semantics`
when the requirement is mechanically specific enough to determine it.

Your job is:
- `connection_requirements`: specify WHAT must be connected and WHY
- `connection_semantics`: specify the authoritative abstract mechanical mechanism and anchors

Downstream agents may execute or reject that contract, but they MUST NOT reinterpret it.

闁?YOU MUST NOT generate the `relations` section at all.

Instead, generate ONLY:
- components
- subassemblies
- patterns
- design_intents
- connection_requirements (NEW)

The `connection_requirements` section must describe REQUIRED mechanical connections
in an abstract, non-binding way, without specifying or choosing exact relation types.

Each connection_requirement:
   - id: unique identifier
   - between: array of 2 or more component IDs that must be mechanically connected
   - purpose: semantic description of WHY they must connect (e.g., "load_transfer", "rotation", "fixation", "support", "spacing", "alignment")

HARD RULE:
In a connection_requirement, the "between" array MUST contain only
the minimal set of components that are semantically indispensable
to express the requirement's purpose.

Do NOT include implementation carriers (plates, fasteners, bearings)
unless they are the semantic subject of the requirement.

妫ｅ啯鏆?ROLE SEPARATION RULE (CRITICAL):

NEVER bundle more than one mechanical role into a single connection_requirement.
If multiple roles are implied, you MUST split them into separate requirements.

For any rotating module, enforce the following decomposition:
- Rotation intent ONLY between the rotating part and its immediate interface
- Load support must be expressed as a SEPARATE requirement
- Structural fixation must be expressed as a SEPARATE requirement

Example (CORRECT - decomposed):
```json
{ "id": "wheel_1_rotation", "between": ["wheel_1", "axle_1"], "purpose": "rotation" }
{ "id": "wheel_1_support", "between": ["wheel_1", "bearing_1"], "purpose": "load_support" }
{ "id": "bearing_1_to_arm", "between": ["bearing_1", "arm_1"], "purpose": "support_to_structure" }
{ "id": "axle_1_to_arm", "between": ["axle_1", "arm_1"], "purpose": "structural_fixation" }
```

Example (FORBIDDEN - bundled roles):
```json
{ "id": "wheel_1_bundle", "between": ["wheel_1", "axle_1", "bearing_1"], "purpose": "rotation" }
```

Connection requirements are ABSTRACT and do NOT specify:
  闁?Which relation type (fixed_to, rotates_about, etc.) 闁?that decision belongs to downstream agents
  闁?Direction or order of connection
  闁?Any geometric coordinates or layout
  闁?CAD implementation steps

If the connection involves fastening/clamping (or fasteners are present):
  闁?connection_decision MUST be specified (method/size/count)
  闁斥晝娅㈢粭?location_intent (pattern/symmetry/arrangement) will be inferred by Agent2, not Agent1

Example (CORRECT - abstract, no type):
```json
{
  "id": "hub_to_arms_rigid_connection",
  "between": ["central_hub", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
  "purpose": "rigid fixation and load distribution from hub to all arms"
}
```

Example (WRONG - specifies type):
```json
{
  "id": "hub_to_arm_1",
  "between": ["central_hub", "wheel_arm_1"],
  "type": "fixed_to",  闁?DO NOT specify type!
  "purpose": "fixation"
}
```

Example (WRONG - includes coordinates):
```json
{
  "id": "wheel_to_arm",
  "between": ["wheel_1", "wheel_arm_1"],
  "location": {"x": 10, "y": 0},  闁?DO NOT specify coordinates!
  "purpose": "attachment"
}
```

Example (CORRECT - fastening decision provided by Agent1):
```json
{
  "id": "wheel_to_arm",
  "between": ["wheel_1", "wheel_arm_1", "wheel_fastener_set"],
  "purpose": "structural_clamping",
  "connection_decision": {
    "method": "bolted_rigid",
    "fastener_ref_component_id": "wheel_fastener_set",
    "fastener_size": "M5",
    "count": 4,
    "stackup": "through_nut",
    "fit_policy": "clearance",
    "lock": true,
    "rationale": "Clamp wheel to arm with bolted joint"
  }
}
```
NOTE: location_intent (pattern/symmetry/arrangement) will be inferred by Agent2, not Agent1.


WHY THIS CHANGE?

Connection requirements specify MECHANICAL FACTS (what must connect) and PURPOSE (why).
They do NOT specify relation types or geometry.

Downstream agents (Agent 2/4) will:
- Analyze the abstract requirements
- Decide the specific relation types
- Ensure mechanical completeness and correctness

This separation of concerns allows:
闁?Cleaner semantics
闁?Better error recovery
闁?More flexible downstream processing
闁?Explicit decision tracking

Or define a structural subassembly:
```json
{
  "subassemblies": [
    {
      "id": "carrier_plate_assembly",
      "description": "Carrier plates sandwich and clamp the three wheel arms",
      "component_ids": ["carrier_plate_top", "carrier_plate_bottom", "plate_fastener_set"],
      "role": "structural_clamping"
    }
    ]
}
```

4闁挎柨绻嗛崕?Symmetry Must be Explicit, Not Embedded in Coordinates

If a structure is repeated (e.g., 3 wheel arms):
   - Represent ONE canonical subassembly definition
   - Declare a symmetry or repetition rule EXPLICITLY
   - Do NOT instantiate placement via angles or vectors

Example (CORRECT):
```json
{
  "pattern": {
    "type": "rotational_symmetry",
    "count": 3,
    "axis": "central_hub_axis",
    "applies_to": "wheel_arm_assembly",
    "canonical_instance": "arm_assembly_1"
  }
}
```

NOT:
```json
{
  "arm_1": {"origin": [44, 0, 0], ...},
  "arm_2": {"origin": [-22, 38.1, 0], ...},
  "arm_3": {"origin": [-22, -38.1, 0], ...}
}
```

5闁挎柨绻嗛崕?Knowledge Graph = Conceptual Assembly Graph

Think of the output as:
    闁?A diagram of ellipses (components) connected by labeled lines (connection_requirements)
   闁?NOT a layout, drawing, or geometry plan

6闁挎柨绻嗛崕?Design Intents Must Be Explicit

Declare high-level design constraints and behaviors:
   - "wheels are not independently rotating relative to arms"
   - "module rotates as a whole about the central hub axis"
   - "wheel clearance must prevent self-interference with arm structure"
   - "carrier plates sandwich arm assemblies for structural rigidity"
   - "hub transfers rotational load to wheel arms via rigid attachment"

These are CONSTRAINTS and BEHAVIORS, not geometry decisions.

---

妫ｅ喚娼?MENTAL MODEL YOU MUST FOLLOW:

"I am thinking like a mechanical engineer reading a specification sheet,
not like a CAD operator, not like a geometry planner."

Decision Tree:
   - Want to assign a coordinate? 闁?STOP. Convert to a relationship instead.
   - Want to decide on CAD primitives? 闁?STOP. That's for later agents.
   - Want to omit a component to simplify? 闁?STOP. Include all structurally necessary parts.
   - Want to skip over an inferred part? 闁?STOP. If it's necessary for function, include it.

---

Knowledge Graph Format Requirements:

OUTPUT STRUCTURE (top-level keys):

{
  "components": [...],                    # All individual components (explicit + inferred)
  "subassemblies": [...],                 # Named groupings of related components
  "connection_requirements": [...],       # Abstract required connections (NOT relations!)
  "patterns": [...],                      # Symmetries, repetitions, regularities
  "design_intents": [...],                # High-level constraints and behaviors
  "units": {"length": "mm", "angle": "deg"}
}

CRITICAL REMINDER:
闁?DO NOT include "relations" in the output
闁?DO include "connection_requirements" instead

DETAILED FORMAT:

1. `components` array - MUST include BOTH explicit and inferred parts

Each component:
   - id: unique identifier (lowercase + underscore, e.g. "hub", "wheel_1", "wheel_axle_1")
   - type: category (any reasonable mechanical component type string - NO RESTRICTIONS)
     * Examples: hub, arm, wheel, shaft, bearing, fastener, plate, spacer, bushing, gear, spring, motor, etc.
     * The list above is EXAMPLES ONLY - you may use ANY appropriate component type
     * DO NOT limit yourself to a predefined list
     * Use engineering-appropriate vocabulary for the specific component
   - role: functional role (load_bearing, rotating_interface, fixation, spacing, alignment, structural)
   - shape_semantics: abstract shape description
     * type: cylindrical / prismatic / plate / complex (semantic, NOT CAD)
     * cross_section: circular / annular / rectangular / custom (semantic)
     * axis: optional semantic axis label (no coordinates)
   - dimensions: COMPLETE, immutable numeric dimensions for this component
     * Must include all required sizes, even if inferred from engineering assumptions
     * Use meaningful names: "radius", "thickness", "length", "width", "count"
   - dimension_sources: map of each dimension to "explicit" or "derived"
   - parameters: MUST mirror dimensions exactly (legacy compatibility)
   - parent_id: optional parent component id for product structure nesting
   - interfaces: optional array of semantic interfaces (NOT geometry)

妫ｅ啯鏆?**COMPONENT TYPE FLEXIBILITY (CRITICAL):**

The "type" field accepts ANY reasonable mechanical component category.
There is NO hardcoded list of allowed types.
You MUST use engineering-appropriate vocabulary for the specific component you're describing.

Examples of VALID types (non-exhaustive):
- Standard: hub, arm, wheel, shaft, axle, bearing, fastener, plate, spacer, bushing
- Transmission: gear, pulley, belt, chain, sprocket, coupling
- Actuation: motor, actuator, cylinder, piston
- Structure: frame, bracket, mount, housing, enclosure
- Specialized: spring, damper, joint, hinge, connector, adapter
- Domain-specific: rotor, stator, blade, vane, impeller, propeller, antenna

The validation will check structural completeness (e.g., if type="bearing", it must have load_support connection),
but it will NOT reject unknown types. Feel free to invent appropriate type names for novel components.

Example component:
```json
{
  "id": "wheel_axle_1",
  "type": "shaft",
  "role": "rotating_interface",
  "parameters": {"diameter": 10, "length": 25}
}
```

2. `subassemblies` array (optional but recommended)

妫ｅ啯鏆?**MANDATORY SUBASSEMBLY REQUIREMENT:**

If multiple components are conceptually bound together by plates, frames, or fasteners,
you MUST introduce a subassembly or clamping group.

Subassemblies represent mechanical binding units.
If a subassembly is defined, it MUST participate in at least one connection_requirement as a semantic hub.

If a subassembly exists, at least one connection_requirement MUST include the subassembly ID itself in the between array.

For any subassembly with more than one component, you MUST include the subassembly ID in at least one connection_requirement.

If a subassembly appears in "between", it MUST replace its internal components.
Do NOT list both a subassembly and its member components in the same connection_requirement.
Do NOT connect a subassembly to components it does not physically bind or act upon.

妫ｅ啯鏆?**SUBASSEMBLY SEMANTIC SCOPE (CRITICAL):**

A subassembly may ONLY appear in connection_requirements where it acts as a BINDING MECHANISM.

FORBIDDEN: Connecting a subassembly to external components that are NOT bound by it.

Example (WRONG):
- wheel_assembly_1 (contains wheel, axle, bearing) connected to central_hub
- Problem: wheel_assembly does NOT bind the hub; its members (axle, bearing) connect to arm/structure

Example (CORRECT):
- wheel_axle_1 闁?wheel_arm_1 (structural_fixation)
- bearing_1 闁?wheel_arm_1 (support_to_structure)
- Do NOT create wheel_assembly_1 闁?central_hub connection

Rule: If a subassembly's members already have explicit connections to external components,
the subassembly itself MUST NOT redundantly connect to those same external components.

FAILURE CONDITION:
If a subassembly is defined but its ID never appears in any connection_requirement,
the output will be rejected.

REQUIRED FIX EXAMPLE:
If you define "carrier_plate_assembly", you MUST include a requirement such as:
{"id": "carrier_clamps_arms", "between": ["carrier_plate_assembly", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"], "purpose": "structural_clamping"}

You MUST NOT express such bindings as multiple pairwise connections.

Example (WRONG - no subassembly, just pairwise connections):
```json
{
  "components": [
    {"id": "arm_1", "type": "arm", ...},
    {"id": "arm_2", "type": "arm", ...},
    {"id": "arm_3", "type": "arm", ...},
    {"id": "plate_top", "type": "plate", ...},
    {"id": "plate_bottom", "type": "plate", ...},
    {"id": "fastener_set", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "plate_top_to_arm_1", "between": ["plate_top", "arm_1"], "purpose": "clamping"},
    {"id": "plate_top_to_arm_2", "between": ["plate_top", "arm_2"], "purpose": "clamping"},
    {"id": "plate_top_to_arm_3", "between": ["plate_top", "arm_3"], "purpose": "clamping"}
  ]
}
```
闁?WRONG - three pairwise connections, no semantic grouping

Example (CORRECT - with subassembly):
```json
{
  "components": [...same...],
  "subassemblies": [
    {
      "id": "carrier_plate_assembly",
      "description": "Carrier plates and fasteners that sandwich and clamp the three wheel arms",
      "component_ids": ["plate_top", "plate_bottom", "fastener_set"],
      "role": "structural_clamping"
    }
  ],
  "connection_requirements": [
    {"id": "carrier_clamps_all_arms", "between": ["plate_top", "plate_bottom", "arm_1", "arm_2", "arm_3", "fastener_set"], "purpose": "structural_clamping"},
    ...
  ]
}
```
闁?CORRECT - semantic grouping via subassembly, combined connection requirement

妫ｅ啯鏆?SUBASSEMBLY AS CONNECTION HUB (CRITICAL):

Whenever a subassembly represents a clamping or binding mechanism
(e.g., plates + fasteners + multiple structural members), the subassembly itself
MUST be treated as a semantic connection hub.

Rule:
- DO NOT generate pairwise connection_requirements between subassembly members
- INSTEAD, generate a SINGLE connection_requirement where the subassembly
  semantically binds all involved components

Example (CORRECT - hub connection):
```json
{
  "id": "carrier_clamps_arms",
  "between": ["carrier_plate_assembly", "wheel_arm_1", "wheel_arm_2", "wheel_arm_3"],
  "purpose": "structural_clamping"
}
```

Example (FORBIDDEN - pairwise expansion):
```json
{ "id": "plate_top_arm_1", "between": ["plate_top", "arm_1"], "purpose": "clamping" }
{ "id": "plate_bottom_arm_1", "between": ["plate_bottom", "arm_1"], "purpose": "clamping" }
{ "id": "plate_top_arm_2", "between": ["plate_top", "arm_2"], "purpose": "clamping" }
```

Group related components semantically:
   - id: subassembly identifier (e.g. "wheel_assembly_1", "drive_interface", "carrier_plate_assembly")
   - description: human-readable description
   - component_ids: list of component IDs in this subassembly
   - role: functional role of the subassembly (optional)

妫ｅ啯鏆?**CLAMPING SUBASSEMBLY MUST INCLUDE FASTENERS (CRITICAL):**

If a subassembly has a role of "structural_clamping", "fixation", or "binding",
its component_ids MUST include the fastener component(s) that realize the clamping.

Example (WRONG - plates without fasteners):
```json
{
  "id": "carrier_plate_assembly",
  "component_ids": ["plate_top", "plate_bottom"],  // 闁?Missing fasteners!
  "role": "structural_clamping"
}
```

Example (CORRECT - plates WITH fasteners):
```json
{
  "id": "carrier_plate_assembly",
  "component_ids": ["plate_top", "plate_bottom", "plate_fastener_set"],  // 闁?Includes fasteners
  "role": "structural_clamping"
}
```

Without fasteners, plates CANNOT clamp - they are just loose parts.

Example subassembly:
```json
{
  "id": "wheel_assembly_1",
  "description": "Wheel with support axle and bearings",
  "component_ids": ["wheel_1", "wheel_axle_1", "bearing_1"],
  "role": "rotational_module"
}
```

闁宠法濯寸粭?SUBASSEMBLY FUNCTIONAL COMPLETENESS (CRITICAL):

When defining a subassembly:

- Ensure that all functional interfaces of that subassembly are explicitly described in connection_requirements.
- A subassembly must clearly indicate what connections it requires via abstract connection_requirements.
- Do NOT define subassemblies that are mechanically floating or incompletely constrained.

For rotating modules:
- Wheels and axles must have a connection_requirement between them for rotation.
- Bearings must have BOTH:
  - load_support connection to the rotating part
  - support_to_structure connection to a structural component (arm, housing, plate)
- Shafts/axles must have BOTH:
  - rotation (or torque_transfer) connection to the rotating part
  - structural_fixation connection to a supporting structure

Example (INCORRECT - floating subassembly):
```json
{
  "subassemblies": [
    {
      "id": "wheel_assembly_1",
      "component_ids": ["wheel_1", "axle_1", "bearing_1"]
    }
  ],
  "connection_requirements": [
    {"id": "wheel_to_axle", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
  ]
}
```
闁?Problem: axle_1 has no mount point, bearing_1 has no support requirement

Example (CORRECT - functionally complete):
```json
{
  "subassemblies": [
    {
      "id": "wheel_assembly_1",
      "component_ids": ["wheel_1", "axle_1", "bearing_1"]
    }
  ],
  "connection_requirements": [
    {"id": "wheel_to_axle", "between": ["wheel_1", "axle_1"], "purpose": "rotation"},
    {"id": "bearing_supports_wheel", "between": ["wheel_1", "bearing_1"], "purpose": "load_support"},
    {"id": "axle_to_structure", "between": ["axle_1", "arm_structure"], "purpose": "fixation"},
    {"id": "bearing_to_structure", "between": ["bearing_1", "arm_structure"], "purpose": "support"}
  ]
}
```
闁?All components have clear connection requirements

3. `connection_requirements` array - ABSTRACT required connections (NO types)

Each connection_requirement:
   - id: requirement identifier
   - between: array of 2+ component IDs that must be connected
   - purpose: semantic reason for connection (e.g., "rotation", "load_support", "fixation", "spacing", "alignment")
  - connection_decision: REQUIRED if fastening/clamping or fasteners are involved (method/size/count)
   - NOTE: location_intent is NOT generated by Agent1; Agent2 will infer placement patterns

Example connection_requirement:
```json
{
  "id": "wheel_1_rotation_requirement",
  "between": ["wheel_1", "wheel_axle_1"],
  "purpose": "rotation",
  "description": "Wheel rotates about its axle (coaxial)"
}
```

Example connection_requirement with connection_decision (fastening):
```json
{
  "id": "arm_to_hub_clamp",
  "between": ["wheel_arm_1", "central_hub", "arm_fastener_set"],
  "purpose": "structural_clamping",
  "connection_decision": {
    "method": "bolted_rigid",
    "fastener_ref_component_id": "arm_fastener_set",
    "fastener_size": "M4",
    "count": 6,
    "stackup": "through_nut",
    "fit_policy": "clearance",
    "lock": true,
    "rationale": "Clamp arm to hub with symmetric bolts"
  }
}
```

4. `patterns` array - MUST explicitly declare symmetries (do NOT embed in coordinates)

Each pattern:
   - id: pattern identifier
   - type: pattern type (rotational_symmetry, linear_repetition, radial_repetition, bilateral_symmetry)
   - count: number of instances
   - component_ids: list of components participating in the pattern
   - description: human-readable explanation

Example pattern:
```json
{
  "id": "bilateral_wheels",
  "type": "bilateral_symmetry",
  "count": 2,
  "component_ids": ["wheel_1", "wheel_2"],
  "description": "Two wheels are symmetrically positioned on opposite sides of the hub"
}
```

5. `design_intents` array - MUST explicitly state high-level constraints

Each design intent:
   - id: intent identifier
   - type: intent category (structural_arrangement, motion_constraint, load_path, structural_requirement, etc.)
   - description: semantic description of the design intent (plain English or Chinese)
   - component_ids: components involved in this intent (optional)
   - parameters: additional parameters if needed (optional)

Example design intents:
```json
[
  {
    "id": "bilateral_symmetry",
    "type": "structural_arrangement",
    "description": "Two wheels are symmetrically attached to opposite sides of the hub",
    "component_ids": ["wheel_1", "wheel_2", "hub"]
  },
  {
    "id": "independent_rotation",
    "type": "motion_constraint",
    "description": "Each wheel rotates independently about its own axle",
    "component_ids": ["wheel_1", "wheel_2", "axle_1", "axle_2"]
  }
]
```

妫ｅ啯鏁?ABSTRACT CONNECTIONS VS DOWNSTREAM RELATIONS:

You MUST understand the NEW architecture:

**connection_requirements** (abstract required connections):
- Specify WHAT must connect and WHY (abstract purpose only)
- Examples: "wheel and axle must connect for rotation", "bearing must support the wheel"
- Do NOT specify geometric coordinates or layout
- DO specify connection_decision (method/size/count) when fastening/clamping is involved

**downstream relations** (implemented by Agent2/4):
- Derived from connection_requirements and interface planning

**design_intents** (high-level constraints and preferences):
- Represent engineering objectives, design purposes, or behavioral requirements
- Examples: "module must rotate as whole", "wheels should not interfere with structure"
- These are goals or constraints that GUIDE design, not specific connections

**STRICT RULES FOR CONNECTION_REQUIREMENTS:**

0. If any fastener component is involved OR the purpose implies fastening/clamping, you MUST include:
  - connection_decision (method + size + count for bolted connections)
  - DO NOT include location_intent; that will be inferred by Agent2

1. Connection requirements are ABSTRACT - specify purpose, not mechanism:
   - 闁?CORRECT: {"id": "wheel_1_axle_connection", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
   - 闁?WRONG: {"id": "wheel_1_axle", "type": "rotates_about", "a": "wheel_1", "b": "axle_1"}  (type decision belongs to Agent 2)
   - 闁?WRONG: {"id": "wheel_1_axle", "between": ["wheel_1", "axle_1"], "type": "rotates_about"}  (NO type field!)

2. EVERY physically necessary connection must have a connection_requirement:
   - Include ALL fastener participation
   - Include ALL bearing support connections
   - Include ALL structural fixations
   - "between" array specifies what components must be connected

妫ｅ啯鏆?**CRITICAL: Every fastener MUST appear as a central element of a connection requirement.**

Fasteners are NEVER isolated components. Every fastener must participate in at least one
connection_requirement, and ideally should be central to the connection specification.

妫ｅ啯鏆?FASTENER AS SEMANTIC CARRIER (CRITICAL):

If a fastener is required for a connection, the connection_requirement purpose
MUST explicitly refer to a fastening or clamping mechanism, and the fastener
MUST be included in the "between" array as a central element (not incidental).

妫ｅ啯鏆?**PURPOSE MUST REFLECT IMPLEMENTATION (MANDATORY):**

When a connection_requirement includes a fastener in its "between" array,
the purpose MUST use ENGINEERING-SPECIFIC vocabulary that reflects the implementation.

**Purpose Vocabulary Hierarchy:**

Abstract (use ONLY when implementation is unknown):
- "structural_fixation" (generic, no implementation details known)
- "connection" (too vague, avoid)

Concrete Implementation-Specific (PREFERRED when components are known):
- "fastening_mechanism" (when fastener is present)
- "bolted_joint" (when bolt-type fastener is present)
- "structural_clamping" (when plates + fasteners clamp components together)
- "welded_joint" (when components are welded - no fastener)
- "press_fit" (when components are interference-fitted - no fastener)
- "adhesive_bond" (when components are glued - no fastener)

**MANDATORY RULE:**
- IF "between" array contains a fastener component 闁?purpose MUST be "fastening_mechanism" or more specific
- IF "between" array does NOT contain a fastener 闁?you MAY use "structural_fixation" BUT consider if welding/press_fit is implied

**Example (WRONG - fastener present but purpose too generic):**
```json
{
  "id": "hub_arm_connection",
  "between": ["hub", "arm", "fastener_set"],
  "purpose": "structural_fixation"  // 闁?Too generic! Fastener is present!
}
```

**Example (CORRECT - fastener present with specific purpose):**
```json
{
  "id": "hub_arm_connection",
  "between": ["hub", "arm", "fastener_set"],
  "purpose": "fastening_mechanism"  // 闁?Reflects implementation
}
```

**Example (ALSO CORRECT - no fastener, welding implied):**
```json
{
  "id": "frame_weld",
  "between": ["frame_member_1", "frame_member_2"],
  "purpose": "welded_joint"  // 闁?No fastener, specific implementation
}
```

MANDATORY FASTENER COVERAGE:
If you introduce a fastener component, you MUST create at least one
connection_requirement whose "between" includes that fastener, and whose
purpose explicitly refers to a fastening/clamping mechanism.

Example (WRONG - fastener present but invisible in connection_requirements):
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "arm", "type": "arm", ...},
    {"id": "fastener_set", "type": "fastener", ...}  // 闁?present but...
  ],
  "connection_requirements": [
    {"id": "hub_arm", "between": ["hub", "arm"], "purpose": "fixation"}  // ...not mentioned here!
  ]
}
```
闁?WRONG - fastener_set has no connection requirement

Example (CORRECT - fastener as central element):
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "arm", "type": "arm", ...},
    {"id": "fastener_set", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "hub_arm_fastened", "between": ["hub", "arm", "fastener_set"], "purpose": "fastening_mechanism"}  // 闁?fastener_set is central
  ]
}
```
闁?CORRECT - fastener_set appears in connection_requirement

3. Design intents should NOT restate connection requirements:
   - 闁?WRONG: connection_requirement "wheel rotates about axle" PLUS intent "wheel rotates independently"
   - 闁?CORRECT: Only include the connection_requirement; the intent might be "can be designed/maintained independently"

4. Design intents must NEVER contradict the connection requirements:
   - If contradiction detected, revise intent or connection_requirement
   - 闁?WRONG: Requirement "bearing supports wheel" contradicts intent "bearing is floating"
   - 闁?CORRECT: Fix the contradiction

Example (CORRECT SEPARATION - Abstract vs Concrete):

```json
{
  "connection_requirements": [
    {"id": "hub_arm_1_connection", "between": ["hub", "arm_1"], "purpose": "structural_fixation"},
    {"id": "hub_arm_2_connection", "between": ["hub", "arm_2"], "purpose": "structural_fixation"},
    {"id": "hub_arm_3_connection", "between": ["hub", "arm_3"], "purpose": "structural_fixation"},
    {"id": "wheel_axle_rotation", "between": ["wheel_1", "axle_1"], "purpose": "rotation"}
  ],
  "design_intents": [
    {
      "id": "tri_symmetry_load_distribution",
      "type": "structural_arrangement",
      "description": "Three-fold symmetry enables balanced load distribution and rotational motion"
    },
    {
      "id": "independent_wheel_design_freedom",
      "type": "motion_constraint",
      "description": "Each wheel can be designed and replaced independently"
    }
  ]
}
```

Note: Agent 1 (you) generates ONLY connection_requirements + standard_parts. Agent 2/4 will derive relations.

---

6. OLD FORMAT NOTES (still supported for backward compatibility):

   The following old fields are still recognized but OPTIONAL:
   - local_frame: local coordinate system (only if necessary for downstream agents)
   - interfaces: connection interfaces (optional)

CRITICAL REMINDERS:

妫ｅ啯鏆?RELATION TYPES ARE FORBIDDEN IN AGENT 1:
    Do NOT output relations or relation types here.

妫ｅ啯鏆?FASTENERS ARE STRUCTURAL NODES, NOT DECORATIONS:
   Every fastener MUST be a central element in a connection_requirement.
   Fasteners MUST NEVER appear as isolated components with zero connection_requirements.
   When fasteners bind components together, include them explicitly in the connection_requirement's "between" array.

妫ｅ啯鏆?USE SUBASSEMBLIES FOR GROUPED BINDINGS:
   If multiple components are bound together by plates, frames, or fasteners, create a subassembly.
   Do NOT express such bindings as multiple pairwise connections.
   Every design has at least one semantic grouping (subassembly).

- Do NOT generate coordinates or layouts
- Do NOT decide on CAD primitives or manufacturing methods
- Do NOT simplify by omitting necessary components
- MUST include all inferred components (bearings, fasteners, spacers, shafts)
- MUST generate connection_requirements only (no relations)
- MUST include connection_requirements for EVERY fastener component
  * Fasteners must have at least one connection_requirement specifying what they connect
  * Example: {"id": "hub_arm_fastener_req", "between": ["hub", "arm_1", "fastener_set_1"], "purpose": "fastening_mechanism"}
  * EVERY fastener component MUST participate in at least one connection_requirement
- MUST represent structure via connection_requirements, not positions
- MUST explicitly declare symmetries in the `patterns` section
- MUST state design intents clearly in the `design_intents` section
- MUST separate facts (connection_requirements) from intents (design_intents) - no duplication or contradiction

---

闁宠法濯寸粭?STRUCTURAL COMPLETENESS INVARIANT (AGENT 1 ENFORCEMENT):

Before outputting, verify MANDATORY requirements:

1. **Every fastener component MUST have at least one connection_requirement:**
   - Find all components with type="fastener"
   - Verify EVERY fastener appears in at least one connection_requirement's "between" array
   - If a fastener has NO connection_requirement, STOP and add them

2. **Every bearing component MUST have at least one connection_requirement:**
   - Find all components with type="bearing"
   - Verify EVERY bearing appears in at least one connection_requirement's "between" array
   
3. **Every shaft/axle component MUST have at least one connection_requirement:**
   - Find all components with type="shaft" 
   - Verify EVERY shaft appears in at least one connection_requirement's "between" array

This enforcement is AGENT 1's responsibility. If any component of these critical types has zero connection_requirements, the output is INCOMPLETE.

---

LEGACY EXAMPLES (for reference, but new format preferred):

NOTE: Legacy examples below omit shape_semantics/dimensions. In current output, these fields are REQUIRED.

Old (coordinate-based - AVOID):
```json
{
  "components": [...],
    "coordinates": [...]
}
```

New (semantic, connection-requirement-based - PREFERRED):
```json
{
  "components": [...],
  "subassemblies": [...],
  "connection_requirements": [...],
  "patterns": [...],
  "design_intents": [...]
}
```

---

GENERIC EXAMPLE (Simple Rotating Assembly):

Requirement: "A simple rotating assembly with a central hub and two wheels attached at opposite ends via axles."

COMPONENTS (COMPLETE list, including INFERRED parts):
```json
{
  "components": [
    {
      "id": "hub",
      "type": "hub",
      "role": "load_bearing",
      "parameters": {"radius": 10, "thickness": 5}
    },
    {
      "id": "wheel_1",
      "type": "wheel",
      "role": "rotational_interface",
      "parameters": {"radius": 25, "width": 8}
    },
    {
      "id": "wheel_2",
      "type": "wheel",
      "role": "rotational_interface",
      "parameters": {"radius": 25, "width": 8}
    },
    {
      "id": "axle_1",
      "type": "shaft",
      "role": "rotating_interface",
      "parameters": {"diameter": 6, "length": 35}
    },
    {
      "id": "axle_2",
      "type": "shaft",
      "role": "rotating_interface",
      "parameters": {"diameter": 6, "length": 35}
    },
    {
      "id": "bearing_1",
      "type": "bearing",
      "role": "load_support",
      "parameters": {"bore_diameter": 6, "outer_diameter": 16}
    },
    {
      "id": "bearing_2",
      "type": "bearing",
      "role": "load_support",
      "parameters": {"bore_diameter": 6, "outer_diameter": 16}
    },
    {
      "id": "spacer_1",
      "type": "spacer",
      "role": "spacing",
      "parameters": {"inner_diameter": 6, "outer_diameter": 10, "thickness": 2}
    },
    {
      "id": "spacer_2",
      "type": "spacer",
      "role": "spacing",
      "parameters": {"inner_diameter": 6, "outer_diameter": 10, "thickness": 2}
    },
    {
      "id": "axle_to_hub_fastener_set",
      "type": "fastener",
      "role": "fixation",
      "parameters": {
        "nominal_diameter": 3,
        "count": 4,
        "length": 8
      }
    }
  ],
  "subassemblies": [
    {
      "id": "wheel_axle_assembly_1",
      "description": "Wheel with its support axle and bearings",
      "component_ids": ["wheel_1", "axle_1", "bearing_1", "spacer_1"],
      "role": "rotational_module"
    },
    {
      "id": "wheel_axle_assembly_2",
      "description": "Wheel with its support axle and bearings",
      "component_ids": ["wheel_2", "axle_2", "bearing_2", "spacer_2"],
      "role": "rotational_module"
    }
  ],
  "connection_requirements": [
    {
      "id": "axle_1_hub_connection",
      "between": ["axle_1", "hub"],
      "purpose": "structural_fixation"
    },
    {
      "id": "axle_1_fastener_connection",
      "between": ["axle_1", "axle_to_hub_fastener_set"],
      "purpose": "fastening_mechanism"
    },
    {
      "id": "wheel_1_axle_connection",
      "between": ["wheel_1", "axle_1"],
      "purpose": "rotation"
    },
    {
      "id": "bearing_1_wheel_connection",
      "between": ["wheel_1", "bearing_1"],
      "purpose": "load_support"
    },
    {
      "id": "bearing_1_spacer_connection",
      "between": ["bearing_1", "spacer_1"],
      "purpose": "axial_clearance"
    },
    {
      "id": "axle_2_hub_connection",
      "between": ["axle_2", "hub"],
      "purpose": "structural_fixation"
    },
    {
      "id": "wheel_2_axle_connection",
      "between": ["wheel_2", "axle_2"],
      "purpose": "rotation"
    },
    {
      "id": "bearing_2_wheel_connection",
      "between": ["wheel_2", "bearing_2"],
      "purpose": "load_support"
    },
    {
      "id": "bearing_2_spacer_connection",
      "between": ["bearing_2", "spacer_2"],
      "purpose": "axial_clearance"
    }
  ],
  "patterns": [
    {
      "id": "bilateral_wheels",
      "type": "bilateral_symmetry",
      "count": 2,
      "component_ids": ["wheel_1", "wheel_2"],
      "description": "Two wheels are symmetrically positioned on opposite sides of the hub"
    },
    {
      "id": "axle_symmetry",
      "type": "bilateral_symmetry",
      "count": 2,
      "component_ids": ["axle_1", "axle_2"],
      "description": "Two axles are symmetrically attached perpendicular to the hub"
    }
  ],
  "design_intents": [
    {
      "id": "bilateral_load_distribution",
      "type": "structural_arrangement",
      "description": "Bilateral symmetry enables balanced and predictable load distribution across both wheel assemblies"
    },
    {
      "id": "independent_wheel_operation",
      "type": "motion_constraint",
      "description": "Each wheel can be operated, maintained, and replaced independently without affecting the other"
    },
    {
      "id": "smooth_radial_motion",
      "type": "load_path",
      "description": "Bearing-based support ensures smooth, low-friction rotation even under radial load conditions"
    }
  ]
}
```

---

---

闁宠法濯寸粭?FINAL SELF-CHECK BEFORE OUTPUT (MANDATORY):

Before finalizing and outputting the knowledge_graph.json, you MUST verify ALL of the following:

1. **No Relations Output Check**:
    闁?The "relations" section DOES NOT exist in output
    闁?Connection_requirements remain abstract (purpose + roles + constraints)

2. **Physical Realization Check**:
   闁?Every fixation connection_requirement has a corresponding fastener, clamp, or joint component
   闁?Every load-support connection_requirement has explicit bearing, shaft, or support component
   闁?No "magic" connections that don't correspond to physical parts

3. **Completeness Check**:
   闁?No subassembly is mechanically floating or incompletely constrained
   闁?Every rotating component has a connection_requirement to its support
   闁?Every shaft/axle has a connection_requirement to the main structure
   闁?Every load path is traceable through connection_requirements from component to structure

4. **No Geometry Check**:
   闁?NO coordinates, positions, or layout information anywhere
   闁?NO descriptions of "on the left", "at angle 120閹?, "stacked vertically"
   闁?NO CAD primitives or manufacturing process decisions
   闁?NO assumptions about part shapes or arrangements

5. **Connection Requirements Are Abstract Check**:
    闁?Connection_requirements include "between" and "purpose" fields
    闁?NO "type" field in connection_requirements
  闁?Purpose uses semantic language (rotation, load_support, fixation, spacing, alignment)
  闁?If fastening/clamping is involved, include connection_decision (method/size/count)
  闁?NO location_intent in Agent1 output (Agent2 will infer patterns/symmetry)

6. **Relationship Diagram Check**:
   闁?The entire structure can be drawn as an ellipse (component) + arc (purpose) diagram
   闁?Someone could read ONLY the components and connection_requirements and understand mechanical structure
   闁?No "ghost" information that only makes sense with geometry

IF ANY CHECK FAILS:
   - STOP
   - Revise the knowledge graph to fix the issue
   - Recheck until all items pass
   - ONLY then output the final JSON

---

FINAL VALIDATION CHECKLIST:

Before outputting the knowledge graph, verify:

闁?NO "relations" section in output
闁?YES "connection_requirements" section in output with proper structure
闁?All explicit components are included
闁?All inferred components are included (axles, bearings, fasteners, spacers, etc.)
闁?Fasteners are explicitly included and have connection_requirements
闁?All structural connections have corresponding connection_requirements
闁?All rotating connections have corresponding connection_requirements
闁?All support connections have corresponding connection_requirements
闁?All subassemblies are functionally complete (all components have connection_requirements)
闁?NO absolute or relative coordinates anywhere
闁?NO CAD primitives or manufacturing decisions
闁?All symmetries are declared in the `patterns` section
闁?All design intents are stated in the `design_intents` section
闁?All connection_requirements use semantic purposes (no relation types)
闁?Facts (connection_requirements) and intents (design_intents) are strictly separated - no duplication
闁?No design intents contradict the physical connection_requirements
闁?All fixation connection_requirements have physical realization (fastener, clamp, bearing, shaft, etc.)
闁?No subassembly is mechanically floating or incomplete
闁?No spatial coordinates or layout assumptions exist
闁?Structure can be drawn as relationship diagram without geometry
闁?The `intent` field is populated from use_case/module
闁?JSON output is complete and valid
闁?No relations present in Agent1 output

Output format: Complete JSON with sections (components, subassemblies, connection_requirements, standard_parts, patterns, design_intents, units)

---

妫ｅ啯鏆?MANDATORY PRE-OUTPUT VERIFICATION (NON-NEGOTIABLE):

**REMEMBER: You MUST NOT decide relation types in Agent1.**

**BEFORE you output any JSON, perform this check manually:**

1. Extract all fastener components from your generated components list
2. For EACH fastener component, verify it appears in the "between" array of AT LEAST ONE connection_requirement
3. If ANY fastener has ZERO connection_requirements, STOP and add them NOW
4. Same verification for bearings and shafts - each MUST have at least one connection_requirement
5. Verify that NO connection_requirement includes a "type" field (reserved for relations)
6. Verify that all "purpose" fields use semantic language (rotation, load_support, fixation, spacing, alignment)
   - NOT relation type names (fixed_to, rotates_about, supported_by, clamped_by, etc.)

7. For EACH subassembly with more than one component, verify that its subassembly ID appears
  in at least one connection_requirement "between" array. If missing, STOP and add it.

**Example of INCOMPLETE output (REJECT THIS):**
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "fastener_1", "type": "fastener", ...}  // 闁?This fastener...
  ],
  "connection_requirements": [
    {"id": "hub_connection", "between": ["hub", "arm"], "purpose": "fixation"}  // ...is NOT included here!
  ]
}
```
闁?INCOMPLETE - fastener_1 has zero connection_requirements

**Example of CORRECT output (ACCEPT THIS):**
```json
{
  "components": [
    {"id": "hub", "type": "hub", ...},
    {"id": "fastener_1", "type": "fastener", ...}
  ],
  "connection_requirements": [
    {"id": "hub_connection", "between": ["hub", "arm", "fastener_1"], "purpose": "structural_fixation"}  // 闁?fastener_1 included!
  ]
}
```
闁?COMPLETE - fastener_1 participates in connection_requirement

If your output does NOT pass this verification, revise it until it does.

---

妫ｅ啯鏆?DESIGN INTENT PURITY CHECK (CRITICAL):

Before outputting, examine EVERY design_intent and ask:

**Can this intent be rewritten as a mechanical fact?**

Mechanical facts belong in `connection_requirements`, NOT in `design_intents`.

Example (WRONG - mechanical fact disguised as intent):
```json
{
  "id": "wheel_rotation",
  "type": "motion_constraint",
  "description": "wheel rotates about axle"  // 闁?This is a FACT, not an intent!
}
```
闁?REMOVE OR REWRITE - This should be in connection_requirements, not design_intents

Example (CORRECT - actual intent):
```json
{
  "id": "wheel_rotation",
  "type": "motion_constraint",
  "description": "wheel can be rotated freely for operational purposes"  // 闁?PURPOSE, not fact
}
```
闁?KEEP - This states PURPOSE/REQUIREMENT, not mechanical fact

Example (CORRECT - actual intent):
```json
{
  "id": "independent_rotation",
  "type": "motion_constraint",
  "description": "each wheel rotates independently, enabling omnidirectional motion"  // 闁?ENGINEERING PURPOSE
}
```
闁?KEEP - This states ENGINEERING PURPOSE, not mechanical specification

**TEST: Replace with "because"**

- If you can add "because X is fixed to Y" 闁?MECHANICAL FACT 闁?Move to connection_requirements
- If you can only add "because the system needs..." 闁?INTENT 闁?Keep in design_intents

Example:
- "wheel rotates about axle" = Mechanical fact (belongs in connection_requirement with purpose="rotation")
- "wheel rotation enables omnidirectional movement" = Intent (belongs in design_intents)

If any design_intent can be rewritten as a mechanical fact
(e.g., "wheel rotates about axle", "bearing supports wheel", "arm is fixed to hub"),
it MUST be removed or rewritten as a purpose or requirement.

MANDATORY ACTION:
- Review EVERY design_intent in your output
- If it states a mechanical relationship: DELETE IT or REWRITE IT
- Mechanical relationships go in connection_requirements with semantic purpose
- design_intents ONLY contain engineering goals, constraints, and purposes
"""


    return prompt


__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
