# Agent4 Module Layout

Agent4 turns the knowledge graph and geometry assembly contract into assembly semantics and assembly patch steps.
It decides how modeled parts should mate, but it does not run Fusion.

The code is grouped into three main modules:

- `common.py`: shared loading, registry checks, component aliases, contract validation, skip gates, and optional LLM call handling.
- `assembly_geometry.py`: chooses usable interfaces and compiles assembly relations into joint/resolve steps.
- `semantics.py`: builds assembly relations from KG/contract/LLM evidence, cleans relation types, adds constraints, and applies modeling-semantic refinements.
- `transform.py`: public entrypoint; reads inputs, builds semantics, compiles steps, validates coverage, and writes `assembly_semantics_round_N.json` plus `assembly_patch_round_N.json`.

Plain answer for defense:
Agent4 decides how parts are assembled. It reads which interfaces exist, decides whether a relation should be rigid, revolute, bonded, or skipped, and emits assembly-level steps. It is not responsible for modeling geometry; it only plans how already-modeled parts connect.
