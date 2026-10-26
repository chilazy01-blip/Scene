"""Early feedback is applied under guards; all plant/reference limits unchanged."""

import ast
from pathlib import Path
from .reference import Clock
from sage.experiments.embodied_native_walk_motion_v1.reference import (
    Clock as OriginalClock,
)


def test_clock_and_acceptance_not_tuned_to_the_failed_case():
    assert Clock is OriginalClock


def test_first_feedback_not_delayed_behind_fifty_observer_ticks():
    tree = ast.parse(Path(__file__).with_name("engine.py").read_text())
    active = [
        n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "active" for t in n.targets)
        and isinstance(n.value, ast.Constant)
    ]
    assert active == [True]


def test_no_band_root_force_or_new_collision_model_in_revision():
    text = Path(__file__).with_name("engine.py").read_text()
    assert "AnchoredBand" not in text and "apply_official_band" not in text
    assert (
        "model=load_model" not in text
    )  # Formatted source uses the original cached canonical XML path, no string injection.
    assert 'load_model(scene["model"]["path"])' in text
