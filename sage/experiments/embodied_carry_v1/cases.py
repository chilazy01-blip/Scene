"""Create one immutable preloaded-grasp case, only after conditional admission."""

import argparse
from pathlib import Path
from .model import authorize
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def create(main_root, model_root, preflight, index, mode, output, standing_report=None):
    admitted = authorize(main_root)
    if output.exists():
        raise FileExistsError(output)
    candidate = read_bound_json(preflight)["candidates"][index]
    case = read_bound_json(main_root / "matrix_protocol_01/C001.json")
    scene = model_root / "SCENE.json"
    model = read_bound_json(scene)
    case.update(
        schema="conditional-preloaded-carry-case/v1",
        main_root=str(main_root),
        main_admission=admitted,
        model_path=model["model"]["path"],
        scene_manifest_path=str(scene),
        scene_manifest=_file_binding(scene),
        carry_mode=mode,
        joint_noise_std_rad=0.0,
        payload_local_xyz_m=candidate["payload_local_xyz_m"],
        initial_right_hand_targets=candidate["initial_right_hand_targets"],
        right_hand_targets=candidate["right_hand_targets"],
        grasp_preflight=_file_binding(preflight),
        grasp_candidate_index=index,
        preloaded_grasp_not_pickup=True,
    )
    if mode == "walking":
        if standing_report is None:
            raise ValueError("standing report required before walking")
        case["standing_report"] = str(standing_report)
        case["standing_audit"] = str(standing_report.with_name("CARRY_AUDIT.json"))
    case.pop("content_sha256_excluding_this_field", None)
    case["content_sha256_excluding_this_field"] = canonical_sha256(case)
    write_json_atomic(output, case)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--main-root", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--preflight", type=Path, required=True)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--mode", choices=("standing", "walking"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--standing-report", type=Path)
    a = p.parse_args()
    create(
        a.main_root,
        a.model_root,
        a.preflight,
        a.index,
        a.mode,
        a.output,
        a.standing_report,
    )
