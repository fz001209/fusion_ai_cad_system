# Agent5 Module Layout

Agent5 composes the geometry plan from Agent3b and the assembly patch from Agent4 into the final executable function plan.
It does not create new design intent; it merges, rewrites, orders, and validates the steps that previous agents already decided.

The code is grouped into three main modules:

- `input_contracts.py`: reads shape-realization data, validates interface contracts, checks hole-orientation requirements, and handles low-level transform math used by validation.
- `step_graph.py`: fixes step IDs, rewrites dependencies, sorts steps, checks unresolved placeholders, compresses redundant activate steps, and loads the function registry.
- `instancing.py`: handles repeated parts, instance-specific geometry, placeholder rewrites, initial placements, symmetric connection folding, and occurrence-transform audits.
- `linker.py`: existing final-link pass that cleans the composed function plan before writing it.
- `memory_snapshot.py`: existing helper for recording compact planning memory.
- `transform.py`: public entrypoint; reads Agent3b/Agent4 outputs, calls the helper modules, validates the final plan, and writes `function_plan_round_N.json`.

Plain answer for defense:
Agent5 is the final assembler of the CAD instruction list. Agent3b gives geometry steps, Agent4 gives assembly steps, and Agent5 stitches them together into one ordered executable plan. Its main job is to make sure references, dependencies, repeated instances, placements, and transforms are all consistent before Fusion runs the plan.
