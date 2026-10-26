"""Inspected negative phase closeout, without marking the transport goal done."""

import argparse
from pathlib import Path
from .protocol_v2 import authorize
from .closeout import check
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, reviewed):
    authorize(root)
    assert reviewed
    destination = root / "PHASE_01_PARTIAL_REVIEW.json"
    assert not destination.exists()
    review = read_bound_json(root / "partial_delivery/REVIEW.json")
    visual = read_bound_json(root / "preferred_video_review/REVIEW.json")
    assert (
        review["mechanically_qualified"] is False
        and review["positive_episode_count"] == 0
    )
    assert (
        review["new_physics_cost"] == 6064
        and review["native_cumulative_physics_cost"] == 24123
    )
    assert visual["all736frames_decoded"] and visual["new_physics_steps"] == 0
    for b in visual["files"].values():
        check(b)
    for key in ("report", "audit", "implementation"):
        check(review[key])
    check(visual["video"])
    check(visual["implementation"])
    snapshot = read_bound_json(root / "COST.json")
    safe_save(root / "PHASE_01_COST_SNAPSHOT.json", snapshot)
    safe_save(
        destination,
        {
            "schema": "native-mug-inspected-negative-phase/v1",
            "overall_transport_goal_achieved": False,
            "phase_complete": True,
            "positive_episode_count": 0,
            "source_role": "development_validation",
            "dataset_split": "unassigned",
            "actual_progress": "unsupported fullG1 stand, raise empty hand, actual empty-hand walking to original native desk, stop, reach cup and begin closing; no verified lift, held walk or placement",
            "actual_failure": "unexecuted right ankle pitch target exceeded native upper limit by13.879deg during close; all applied physical steps safe, no actual joint excess/fall",
            "version1_failure": "unreachable-reference soft gate at5.0255mm, preserved original failed13.4s run",
            "causal_versions_used": 2,
            "causal_version_cap_for_this_phase": 2,
            "new_physics_steps": 6064,
            "native_cumulative_physics_steps": 24123,
            "continuous_dynamics_replays": 0,
            "mechanical_partial_review": _file_binding(
                root / "partial_delivery/REVIEW.json"
            ),
            "preferred_video_decode_review": _file_binding(
                root / "preferred_video_review/REVIEW.json"
            ),
            "preferred_video": _file_binding(
                root / "version_02/diagnostic_video_framed/motion.mp4"
            ),
            "cost_snapshot": _file_binding(root / "PHASE_01_COST_SNAPSHOT.json"),
            "reference_counterfactuals": _file_binding(
                root / "COMMAND_REFERENCE_CAUSAL_PROBE.json"
            ),
            "counterfactuals_are_not_validated_repairs": True,
            "visual_review": {
                "reviewer": "Codex actual view_image of decoded MP4 frames",
                "reviewed": True,
                "findings": "full official G1, real existing white mug with rim/handle, original native desk and room; corrected render camera avoids bookcase occlusion; caption explicitly TASK NOT COMPLETED, no artificial lift/carry/stop appended",
                "not_a_human_subjective_quality_rating": True,
            },
            "additional_control_revision_authorization_pending_at_phase_close": True,
            "additional_revision_must_not_reset_original_deadline_or_40000step_budget": True,
            "old_experiment_results_unchanged": True,
            "sources": {
                f.name: _file_binding(f)
                for f in sorted(Path(__file__).parent.glob("*.py"))
            },
            "tests": _file_binding(root / "FINAL_ENGINEERING_TESTS.xml"),
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "transport_goal_achieved": False,
            "phase_closed": True,
            "new_steps": 6064,
            "positive_episodes": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--visual-reviewed", action="store_true")
    a = ap.parse_args()
    run(a.root, a.visual_reviewed)
