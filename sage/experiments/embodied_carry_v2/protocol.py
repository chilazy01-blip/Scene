"""User-authorized ordered carrying stages, frozen before dynamics."""

import argparse
from pathlib import Path
import time
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def authorize(root):
    protocol = read_bound_json(root / "PROTOCOL.json")
    if protocol["schema"] != "ordered-contact-carry-protocol/v2":
        raise ValueError("wrong protocol")
    for b in [
        *protocol["dependencies"].values(),
        protocol["prior_main_delivery"],
        protocol["prior_grasp_preflight"],
        protocol["model_manifest"],
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("frozen source changed: " + b["path"])
    return _file_binding(root / "PROTOCOL.json")


def freeze(prior, root):
    root.mkdir(parents=True, exist_ok=False)
    main = read_bound_json(prior / "delivery/DELIVERY.json")
    if main["classification"] != "accepted_development_pipeline":
        raise ValueError("missing locomotion foundation")
    plan = {
        "schema": "ordered-contact-carry-protocol/v2",
        "frozen_utc_timestamp": time.time(),
        "user_authorization": "implement stable grasp, unsupported standing hold, then object carrying walk in that order",
        "prior_root": str(prior),
        "prior_main_delivery": _file_binding(prior / "delivery/DELIVERY.json"),
        "prior_grasp_preflight": _file_binding(prior / "carry/GRASP_PREFLIGHT.json"),
        "model_manifest": _file_binding(prior / "carry/model_01/SCENE.json"),
        "grasp_candidate_index": 0,
        "initial_cases": 1,
        "max_causal_development_revisions": 3,
        "revision_rule": "new source/protocol/output identities after documented diagnosis; never overwrite old evidence or blindly repeat a rejected case",
        "grip_protocol": {
            "anchor_physics_step": 140,
            "anchor_rule": "exactly 0.7s after initialization (40 warmup + 100 observer physics steps); record once, never change physical object pose",
            "max_acquisition_displacement_m": 0.08,
            "qualification_max_relative_speed_m_s": 0.02,
            "min_consecutive_stable_physics_steps": 100,
            "post_anchor_max_slip_m": 0.03,
            "post_anchor_max_rotation_rad": 0.5235987755982988,
            "minimum_object_height_m": 0.25,
            "opposing_contact": "thumb and index-or-middle with measured normal force >0.01N",
            "non_hand_support_allowed": False,
            "calibration": "development choice informed by preserved v1 closure displacement; no held-out claim and no reclassification of old failures",
        },
        "stages": [
            "standing observer admission",
            "unsupported standing 2 seconds",
            "unsupported standing 6 seconds",
            "walking observer admission",
            "walking 2-second safety/retention check",
            "walking and stop 6 seconds",
        ],
        "standing_full_ticks": 300,
        "walking_full_ticks": 300,
        "short_ticks": 100,
        "qualification_ticks": 50,
        "observer_ticks": 100,
        "per_process_wall_s": 120,
        "body_safety": "unchanged SONIC raw actions, official joints/PD/effort, 0.5433987842330933rad slew, 10mm penetration,600N, pelvis>=.65m/up>=.5; active no bias or external wrench",
        "quality": "active up>=.97 and pelvis>=.7m; standing/stop last1s drift<=.02m speed<=.08m/s joint_RMS<=.6rad/s double_support>=.9; walking requires true dual-foot steps and goal region",
        "scope": "50g free preloaded cylinder, one prior generated layout; not pickup, whole-body mesh collision, production or held-out generalization",
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
    }
    plan["content_sha256_excluding_this_field"] = canonical_sha256(plan)
    write_json_atomic(root / "PROTOCOL.json", plan)
    return plan


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    freeze(a.prior, a.root)
