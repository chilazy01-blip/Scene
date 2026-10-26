"""Bind the inspected partial result without ever declaring the main goal done."""

import argparse
from pathlib import Path
from .protocol import require_motion_protocol
from .delivery import binding_ok
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, reviewed):
    require_motion_protocol(root)
    assert reviewed == ["A", "B"]
    source = root / "partial_delivery/REVIEW.json"
    review = read_bound_json(source)
    assert review["overall_goal_achieved"] is False
    assert review["qualified_conditions"] == ["A"]
    assert review["rejected_condition"] == "B" and review["unrun_conditions"] == ["C"]
    for binding in review["files"].values():
        binding_ok(binding)
    for key in ("result", "rejection_review", "continuous_dynamics", "implementation"):
        binding_ok(review[key])
    rejection = read_bound_json(Path(review["rejection_review"]["path"]))
    assert all(rejection["checks"].values()) and rejection["command_never_applied"]
    assert rejection["physics_steps"] == 0
    output = root / "PARTIAL_REVIEW_FINAL.json"
    assert not output.exists()
    save(
        output,
        {
            "schema": "native-walk-inspected-partial-result/v1",
            "overall_goal_achieved": False,
            "qualified_conditions": ["A"],
            "rejected_condition": "B",
            "unrun_conditions": ["C"],
            "review": _file_binding(source),
            "manual_visual_review": {
                "reviewer": "Codex via view_image of actual decoded MP4 frames",
                "reviewed_cases": reviewed,
                "A": "full official G1 and original study visible; actual standing, gait, braking and final hold, no proxy or added prop",
                "B": "diagnostic-only incomplete motion; no artificial final hold appended, no claim of successful stop",
                "not_a_human_subjective_animation_rating": True,
                "files": {
                    cid: _file_binding(
                        root / "partial_delivery" / f"{cid}_decoded_review.jpg"
                    )
                    for cid in reviewed
                },
            },
            "physics_cost": review["physics_cost"],
            "causal_versions_used": 2,
            "causal_version_cap": 2,
            "new_controller_work_requires_new_bounded_authorization": True,
            "scope_limitations": [
                "only one generated development study and one fully passed condition",
                "not three-condition success, heldout generalization, carrying, training or production qualification",
                "official robot native collision representation; native floor exact original cuboid, other scene parts original triangle flex",
                "privileged simulator feedback, original scene furniture fixed in place",
            ],
            "postprocessing_sources": {
                f.name: _file_binding(f)
                for f in sorted(Path(__file__).parent.glob("*.py"))
            },
            "postprocessing_regression": _file_binding(
                root / "POSTPROCESSING_FULL_REGRESSION_R2.xml"
            ),
            "video_A": _file_binding(root / "video_A_complete/motion.mp4"),
            "video_B_diagnostic": _file_binding(root / "video_B_diagnostic/motion.mp4"),
            "qualified_A_export": _file_binding(
                root / "partial_delivery/A_trajectory.npz"
            ),
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {"goal_achieved": False, "qualified_conditions": ["A"], "final": str(output)},
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--manual-reviewed", nargs="+", required=True)
    args = ap.parse_args()
    run(args.root, args.manual_reviewed)
