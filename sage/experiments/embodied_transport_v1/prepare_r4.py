"""Freeze a finite single-scene source-support to target-support task."""

import argparse
from pathlib import Path
import shutil
import time
import xml.etree.ElementTree as ET
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, prior):
    root.mkdir(parents=True, exist_ok=False)
    parent = root.parent / "embodied_transport_20261020_v2"
    for name in (
        "GEOMETRIC_PREFLIGHT.json",
        "IK_DIAGNOSIS.json",
        "GRASP_CLEARANCE_PROBE.json",
    ):
        (root / name).symlink_to(parent / name)
    (root / "model").symlink_to(parent / "model", target_is_directory=True)
    print("reusing unchanged model and8cm cylinder; approach-motion revision only")


def freeze(root, prior):
    path = root / "PROTOCOL.json"
    if path.exists():
        raise FileExistsError(path)
    description = read_bound_json(root / "model/SCENE.json")
    case = read_bound_json(prior / "continuation_01/walking_full/REPORT.json")[
        "case_config"
    ]
    geometric = read_bound_json(root / "GEOMETRIC_PREFLIGHT.json")
    case.update(
        schema="continuous-transport-case/v1",
        protocol_root=str(root),
        model_path=description["model"]["path"],
        scene_manifest_path=str(root / "model/SCENE.json"),
        scene_manifest=_file_binding(root / "model/SCENE.json"),
        carry_mode="transport",
        start_xy_m=[0.85, 2.8],
        joint_noise_std_rad=0.0,
        source_root_goal_xy_m=[1.25, 2.8],
        target_root_goal_xy_m=[1.65, 2.72],
        goal_xy_m=[1.65, 2.72],
        source_object_xyz_m=[1.45, 2.45, 0.69],
        target_object_xyz_m=[1.85, 2.45, 0.69],
        grasp_local_xyz_m=geometric["grasp_local_xyz_m"],
        grasp_local_rotation=geometric["grasp_local_rotation"],
        desired_wrist_rotation=geometric["desired_upright_wrist_rotation"],
        initial_right_hand_targets={},
        preloaded_grasp_not_pickup=False,
    )
    case.pop("standing_report", None)
    case.pop("standing_audit", None)
    case.pop("content_sha256_excluding_this_field", None)
    case["content_sha256_excluding_this_field"] = canonical_sha256(case)
    write_json_atomic(root / "CASE.json", case)
    p = {
        "schema": "continuous-autonomous-transport-protocol/v1",
        "causal_revision": 4,
        "parent_protocol": _file_binding(
            root.parent / "embodied_transport_20261020_v2/PROTOCOL.json"
        ),
        "revision_evidence": _file_binding(root / "GRASP_CLEARANCE_PROBE.json"),
        "revision_reason": "R3 simultaneous upward/lateral orientation change still swept palm through source before adequate height. R4 clears vertically130mm at current orientation first, then aligns overhead, then descends; Cartesian IK knots constrain path rather than just endpoint. Add2s bounded reach time for extra phase; total40s and physical gates unchanged, same8cm cylinder and model.",
        "created_utc_timestamp": time.time(),
        "case": _file_binding(root / "CASE.json"),
        "prior_delivery": _file_binding(prior / "delivery/DELIVERY.json"),
        "geometric_preflight": _file_binding(root / "GEOMETRIC_PREFLIGHT.json"),
        "scope": "single generated room and two explicit narrow support fixtures, 50g upright cylinder, privileged simulator state feedback; not vision or held-out",
        "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
        "budget_rule": "new independent admission then2s short; every extension requires accepted preceding exact prefix and all physical guards; total hard maximum40s active, no resetting across phases",
        "per_process_wall_s": 180,
        "stage_limits_ticks": {
            "approach": 300,
            "source_stop": 150,
            "reach": 350,
            "close": 150,
            "lift": 150,
            "carry": 300,
            "target_stop": 150,
            "place": 250,
            "release": 100,
            "retract": 150,
            "settle": 100,
        },
        "max_causal_revisions": 4,
        "repeat_rejected_identical_case": False,
        "control": "unchanged raw SONIC29 body, official PD/effort; upper-body task goals only through smooth reference IK, separate native finger PD; no body-command overrides or SourceA body controls",
        "physical_thresholds": "unchanged .65m pelvis/.5up/.01m penetration/600N/.5433987842330933rad slew; active external forces and bias prohibited",
        "task_contract": "empty hand at initial object-on-source; true opposing contact then >=20mm source clearance >=.5s; carry object >=.2m with no source/target support; controlled destination placement/contact; release, retract >=50mm, target object stable and hand-free >=.5s; no weld/state reset/pose assignment after initialization",
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
    }
    p["content_sha256_excluding_this_field"] = canonical_sha256(p)
    write_json_atomic(path, p)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--freeze", action="store_true")
    a = p.parse_args()
    freeze(a.root, a.prior) if a.freeze else prepare(a.root, a.prior)
