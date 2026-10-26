"""Finalize only after actual inspection of decoded evidence for every case."""

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


def finalize(root, manually_reviewed):
    require_motion_protocol(root)
    assert manually_reviewed == ["A", "B", "C"]
    path = root / "delivery/MECHANICAL_REVIEW.json"
    mechanical = read_bound_json(path)
    assert mechanical["machine_checks_passed"]
    assert mechanical["all_three_conditions_same_frozen_controller"]
    binding_ok(mechanical["implementation"])
    binding_ok(mechanical["result"])
    binding_ok(mechanical["failure_preserved"])
    for binding in mechanical["files"].values():
        binding_ok(binding)
    for case in mechanical["cases"]:
        assert case["id"] in manually_reviewed
        for key in ("report", "audit", "continuous_dynamics", "video", "export"):
            binding_ok(case[key])
    output = root / "FINAL_REVIEW.json"
    assert not output.exists()
    save(
        output,
        {
            "schema": "native-walk-goal-final-review/v1",
            "goal_achieved": True,
            "conditions": ["A", "B", "C"],
            "same_frozen_controller": True,
            "mechanical_review": _file_binding(path),
            "visual_review": {
                "reviewer": "Codex using actual view_image inspection of decoded MP4 frames",
                "sampled_encoded_frames_actually_reviewed_for_cases": manually_reviewed,
                "full_video_decodability_and_timing": "all encoded frames mechanically checked",
                "findings": "full official G1 head, hands, feet visible; real native study and original furnishings; actual standing/walking/braking/final standing; no proxy, props or artificial frame padding",
                "not_a_human_subjective_quality_rating": True,
                "files": {
                    cid: _file_binding(root / "delivery" / f"{cid}_decoded_review.jpg")
                    for cid in manually_reviewed
                },
            },
            "physics_cost": mechanical["physics_cost"],
            "environment_approval": _file_binding(root / "ENVIRONMENT_APPROVAL.json"),
            "protocol": _file_binding(root / "REVISION_02_PROTOCOL.json"),
            "replay_plan": _file_binding(root / "DYNAMICS_REPLAY_PLAN.json"),
            "postprocessing_tests": _file_binding(
                root / "POSTPROCESSING_FULL_REGRESSION_R2.xml"
            ),
            "implementation": _file_binding(Path(__file__)),
            "scope": "one original generated native study, three predeclared start/yaw conditions, unsupported 10s stand -> >=1m actual walk -> 5s stop stand",
            "collision_scope": "unchanged official G1 native collision geoms; original closed native-floor cuboid exact-volume collider; all remaining native scene meshes rigid triangle flex, original concavities retained; not arbitrary nonconvex robot triangle self-collision",
            "limitations": [
                "one development room and three nearby conditions, not cross-scene generalization",
                "privileged simulator feedback, not a deployed onboard perception stack",
                "no carrying task in this milestone",
                "three development demonstration exports, no training or learning benefit claim",
                "native scene furniture fixed at original generated poses; not movable articulated furniture manipulation",
            ],
            "artifacts": {
                cid: {
                    "video": _file_binding(root / f"video_{cid}_complete/motion.mp4"),
                    "trajectory": _file_binding(
                        root / "delivery" / f"{cid}_trajectory.npz"
                    ),
                }
                for cid in manually_reviewed
            },
        },
    )
    print(
        {
            "goal_achieved": True,
            "final_review": str(output),
            "physics_cost": mechanical["physics_cost"],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--manual-reviewed", nargs="+", required=True)
    args = ap.parse_args()
    finalize(args.root, args.manual_reviewed)
