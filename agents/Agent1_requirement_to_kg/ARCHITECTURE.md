# Agent1 Module Layout

Agent1 turns the requirement YAML into `knowledge/knowledge_graph.json`.
It is not just a prompt: the LLM drafts the KG, then deterministic code cleans,
repairs, validates, and completes the mechanical facts.

The code is grouped into a small number of explainable modules:

- `input_prompt.py`: reads input/config and builds the LLM prompt.
- `components.py`: decides what the parts are, fixes hierarchy, decomposes large vague parts into real mechanical subparts, fills dimensions, and adds standard-part hints.
- `connections.py`: decides how parts connect, cleans connection requirements, checks fasteners/bearings/shafts, fills missing mechanical closure, and freezes explicit connection semantics for downstream agents.
- `wheel_domain.py`: contains the tri-star/wheel-specific rules for wheel, rim, tire, hub, axle, bearing, and arm topology.
- `postprocess.py`: lists the ordered cleanup pipeline, so the run sequence is visible in one place.
- `transform.py`: public entrypoint; reads YAML/schema, calls the model, runs postprocess, writes the KG, and keeps old helper imports working.
- `standard_parts_resolver.py`: separate standard-parts library matching stage.

Plain answer for defense:
Agent1 first asks the model to draft the mechanical knowledge graph. Then the code checks whether the draft is physically usable: are the parts real, are the connections explicit, are shafts/bearings/fasteners complete, and does the tri-star wheel topology make sense. The prompt explains the desired format; the deterministic modules prevent vague or mechanically impossible output from passing downstream.
