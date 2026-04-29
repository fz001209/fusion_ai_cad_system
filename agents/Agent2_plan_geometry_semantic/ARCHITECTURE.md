# Agent2 Module Layout

Agent2 still exposes `transform.py` as the public entrypoint. The real implementation is grouped into five practical modules:

- `common.py`: shared basics, such as constants, cleanup helpers, frozen-field checks, dimensions, and spacing math.
- `interfaces.py`: finds usable component interfaces, such as faces, axes, bores, seats, and mounting surfaces.
- `placements.py`: decides where each connection should land, including Agent1 connection contracts, LLM placements, missing placement fill-in, per-target split, and host selection.
- `features.py`: turns placements into buildable features, such as fastener holes, threads, bearing seats, derived changes, circular patterns, and mechanism rewrites.
- `outputs.py`: builds final outputs, including geometry semantics, fallback semantics, and the assembly contract.

`transform.py` only orchestrates the run: read the KG, merge existing placements, run placement and feature passes, validate, and write modeling/assembly outputs.

`module_wiring.py` is compatibility glue. It keeps old imports like `from ...transform import _some_helper` working while the implementation lives in the grouped modules.
