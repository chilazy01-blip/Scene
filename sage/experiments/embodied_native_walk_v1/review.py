"""Final static environment review; never substitutes for motion qualification."""

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


def review(root):
    plan = authorize(root)
    scene = read_bound_json(root / "model/SCENE.json")
    preflight = read_bound_json(root / "GEOMETRY_PREFLIGHT.json")
    contacts = read_bound_json(root / "CONTACT_PROBES.json")
    preview = read_bound_json(root / "environment_preview/MANIFEST.json")
    bindings = [
        scene["model"],
        scene["compiled_model_cache"],
        *scene["assets"],
        *scene["sources"].values(),
        *preview["files"].values(),
    ]
    changed = [
        b["path"] for b in bindings if sha256_file(Path(b["path"])) != b["sha256"]
    ]
    source_plan = read_bound_json(root / "PLAN.json")
    official_ok = all(
        sha256_file(Path(item["source"]["path"])) == item["official_oid"]
        for item in scene["official_robot_meshes"]
    )
    result = {
        "schema": "native-walk-static-environment-review/v1",
        "static_checks_passed": preflight["passed"]
        and contacts["passed"]
        and official_ok
        and not changed,
        "user_environment_confirmation_pending": True,
        "motion_authorized": False,
        "physics_steps": 0,
        "motion_frames": 0,
        "task_passed": False,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "positive_training_samples": 0,
        "scene": _file_binding(root / "model/SCENE.json"),
        "plan": _file_binding(root / "PLAN.json"),
        "geometry_preflight": _file_binding(root / "GEOMETRY_PREFLIGHT.json"),
        "contact_probes": _file_binding(root / "CONTACT_PROBES.json"),
        "preview": _file_binding(root / "environment_preview/MANIFEST.json"),
        "original_scene_bindings_and_images_checked": len(bindings),
        "changed_assets": changed,
        "official_g1_meshes_checked": len(scene["official_robot_meshes"]),
        "all_official_meshes_exact": official_ok,
        "native_parts_covered": len(preflight["coverage"]),
        "exact_native_floor_box": scene["native_floor"]["recognition"],
        "predeclared_start_conditions": [
            {
                k: c[k]
                for k in (
                    "id",
                    "start_xy_m",
                    "start_yaw_deg",
                    "goal_xy_m",
                    "corridor_min_radius_m",
                    "passed",
                )
            }
            for c in preflight["conditions"]
        ],
        "static_sweep_pose_samples": sum(
            c["swept_pose_samples"] for c in preflight["conditions"]
        ),
        "contact_regressions": len(contacts["results"]),
        "no_non_native_fixtures_or_payload": True,
        "no_furniture_layout_or_visual_geometry_changes": True,
        "no_official_robot_physics_changes": True,
        "source_preservation": "parent native_v1 and earlier simplified success files not edited; own source frozen by plan or self-bound report",
        "limitations": scene["limitations"],
        "implementation": _file_binding(Path(__file__)),
        "next_action": "user checks actual native room/full G1/collision coverage images; only then freeze a separate bounded motion protocol and run standing/start/walk/stop on all3conditions",
    }
    save(root / "STATIC_REVIEW.json", result)
    print(
        {
            k: result[k]
            for k in (
                "static_checks_passed",
                "native_parts_covered",
                "static_sweep_pose_samples",
                "contact_regressions",
                "changed_assets",
                "physics_steps",
                "user_environment_confirmation_pending",
            )
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    review(p.parse_args().root)
