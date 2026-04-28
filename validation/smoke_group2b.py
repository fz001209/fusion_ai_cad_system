"""Minimal Group 2B smoke checks.

Run this inside Fusion's Python environment (adsk available), after wiring a FusionApiController.
"""


def _assert_r1(result: dict, label: str) -> None:
    missing = [k for k in ("feature_id", "feature_ids", "body_ids") if k not in result]
    if missing:
        raise AssertionError(f"{label} missing keys: {missing}")
    if not isinstance(result.get("feature_ids"), list):
        raise AssertionError(f"{label} feature_ids must be list")
    if not isinstance(result.get("body_ids"), list):
        raise AssertionError(f"{label} body_ids must be list")


def run(controller):
    """Run minimal smoke operations.

    controller: FusionApiController instance.
    """
    comp = controller.root_comp
    comp_id = controller._resolve_component_id(getattr(comp, "name", "root"))

    # TODO: Construct actual bodies and geometry in Fusion before running these.
    # This is a placeholder scaffold to wire your own test setup.
    raise RuntimeError(
        "Provide concrete setup for bodies/planes/curves, then call controller methods and _assert_r1."
    )
