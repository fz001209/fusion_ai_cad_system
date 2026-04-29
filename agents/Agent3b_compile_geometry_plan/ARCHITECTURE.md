# Agent3b Module Layout

Agent3b compiles Agent3a's shape-realization plan into executable geometry steps.
It should not invent new design intent. It translates already-decided parts,
features, and interfaces into calls from `functions/functions.json`.

The code is grouped into four main modules:

- `common.py`: shared basics, such as function registry checks, step emission, parameter lookup, IDs, and placeholder handling.
- `shape_inputs.py`: reads and normalizes Agent3a's shape plan, extracts features/realizations, validates interface references, and builds the interface manifest.
- `feature_compiler.py`: compiles add-on features, such as holes, threaded holes, counterbores, bearing seats, group face resolution, and connection-derived cuts.
- `component_compiler.py`: compiles main component bodies, such as revolves, extrudes, profiles, yokes, hub radial slots, and container components.
- `standard_part_compiler.py`: injects library standard parts after normal geometry steps.
- `transform.py`: public entrypoint; reads inputs, calls the compilers, injects standard parts, writes `geometry_plan_round_N.json`, and writes the interface manifest.

Plain answer for defense:
Agent3b is the translator from plan to executable CAD instructions. Agent3a says what each part should look like; Agent3b turns that into ordered function calls like create component, make profile, extrude, cut holes, add threaded holes, and insert standard parts. It should not redesign the object; it should compile the plan.
