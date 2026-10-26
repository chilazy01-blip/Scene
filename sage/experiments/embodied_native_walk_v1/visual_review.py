"""Record completed manual image inspection, source checks and static-stage cost."""

import argparse
from pathlib import Path
from .preflight import authorize
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    authorize(root)
    static = read_bound_json(root / "STATIC_REVIEW.json")
    scene = read_bound_json(root / "model/SCENE.json")
    preview = read_bound_json(root / "environment_preview_r2/MANIFEST.json")
    bindings = list(preview["files"].values())
    assert all(sha256_file(Path(b["path"])) == b["sha256"] for b in bindings)
    cache = read_bound_json(root / "model/CACHE.json")
    review = {
        "schema": "native-room-manual-visual-review/v1",
        "static_checks_passed": static["static_checks_passed"],
        "manual_inspected_files": [
            preview["files"][k] for k in ("environment_check.jpg", "robot_pose.jpg")
        ],
        "observations": [
            "five original generated furniture objects and full official G1 visible in cutaway and top-down views",
            "original walls and door/window geometry retained; cutaway hides walls for viewing only",
            "native generated room interior visible in corrected215deg camera; original35deg view was outside west wall and occluded",
            "blue/green transport fixtures and red payload absent",
            "top-down collision view same camera/state as native appearance view; robot blue, scene orange, floor grey",
            "robot_pose shows official complete body and hands inside original room, no proxy limbs",
        ],
        "preferred_environment_image": preview["files"]["environment_check.jpg"],
        "preferred_robot_image": preview["files"]["robot_pose.jpg"],
        "preview": _file_binding(root / "environment_preview_r2/MANIFEST.json"),
        "static_review": _file_binding(root / "STATIC_REVIEW.json"),
        "physics_steps": 0,
        "motion_frames": 0,
        "task_passed": False,
        "user_environment_confirmation_pending": True,
        "cost": {
            "new_full_model_compilations": 1,
            "build_wall_s": scene["build_wall_s"],
            "compiled_model_bytes": cache["binary"]["size_bytes"],
            "canonical_xml_bytes": scene["model"]["size_bytes"],
            "full_scene_assets_copied": False,
            "motion_physics_steps": 0,
            "static_full_model_swept_poses": static["static_sweep_pose_samples"],
            "isolated_contact_cases": static["contact_regressions"],
            "new_qualified_episodes": 0,
            "new_training_samples": 0,
            "cost_limit": "~775MiB full compiled cache per model is expensive for bulk production; assets shared by reference, no batch-scale cost claim",
        },
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "production_ready": False,
        "implementation": _file_binding(Path(__file__)),
        "scope": "static environment confirmation only; goal remains active, dynamics require user environment confirmation and new bounded protocol",
    }
    save(root / "VISUAL_REVIEW.json", review)
    print(
        {
            "manual_visual_review_recorded": True,
            "static_checks_passed": review["static_checks_passed"],
            "user_environment_confirmation_pending": True,
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
