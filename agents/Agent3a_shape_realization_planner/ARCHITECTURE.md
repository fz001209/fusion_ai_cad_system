# Agent3a Module Layout

Agent3a turns Agent2's geometry semantics into shape-realization plans for Agent3b.
It does not execute CAD commands. It chooses modeling strategies, numeric parameters,
features, and initial placement hints.

The code is grouped into four main modules:

- `common.py`: shared basics, such as realization class labels, registry loading, side hints, and small feature helpers.
- `feature_plans.py`: turns connection placements into concrete part features, such as bores, threaded holes, bearing seats, and radial slots.
- `layout.py`: decides where parts should initially sit, including symmetry detection, ground-root selection, group placement, and overlap corrections.
- `planner_core.py`: contains `ShapeRealizationPlanner`, which chooses the main modeling strategy and parameters for each component.
- `transform.py`: public entrypoint; reads inputs, calls the planner, merges features and placements, and writes `shape_realization_round_N.json`.

Plain answer for defense:
Agent3a takes the cleaned mechanical meaning from Agent2 and decides how each part should be modeled at a high level. It does not call Fusion directly. It says things like: this hub should be revolved, this arm should be extruded, this bearing needs a seat, this fastener needs a threaded hole, and these parts should start in these relative positions.
