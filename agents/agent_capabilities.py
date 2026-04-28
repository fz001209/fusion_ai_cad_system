from __future__ import annotations

# Declarative agent capability self-declaration (no logic).
#
# This is intentionally a plain data module so that:
# - planners can bound their search space without hardcoding assumptions
# - audits/papers can cite a stable capability surface

AGENT_CAPABILITIES = {
    "plan_geometry_semantic": {
        "produces_functions": [],
        "strategy": ["semantic_contract", "interface_decl"],
    },
    "shape_realization_planner_3a": {
        "produces_functions": [],
        "strategy": ["component_based", "layout", "instance_realization"],
    },
    "compile_geometry_plan_3b": {
        "produces_functions": [
            "CREATE_COMPONENT",
            "CREATE_SKETCH_ON_PLANE",
            "SKETCH_RECTANGLE",
            "EXTRUDE_NEW_BODY",
            "INSERT_BEARING_R1",
            "INSERT_FASTENER_R1",
        ],
        "strategy": ["component_based", "single_body"],
    },
    "plan_assembly": {
        "produces_functions": [
            "LIST_COMPONENT_BODIES",
            "LIST_BODY_FACES",
            "CREATE_JOINT_GEOMETRY",
            "RIGID_JOINT_R1",
            "REVOLUTE_JOINT_R1",
            "LIST_COMPONENT_OCCURRENCES",
            "RIGID_AS_BUILT_JOINT",
            "REVOLUTE_AS_BUILT_JOINT",
            "REVOLUTE_JOINT",
            "PLANAR_AS_BUILT_JOINT",
        ],
        "strategy": ["component_based"],
    },
}
