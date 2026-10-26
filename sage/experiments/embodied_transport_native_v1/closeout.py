"""Summarize this fresh native round without inheriting old task success."""

import argparse
from pathlib import Path
from .engine import authorize
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def run(root, failed_build=None):
    protocol = authorize(root)
    scene = read_bound_json(root / "model/SCENE.json")
    pre = read_bound_json(root / "NATIVE_PREFLIGHT.json")
    result = (
        read_bound_json(root / "attempt_01/RESULT.json")
        if (root / "attempt_01/RESULT.json").exists()
        else None
    )
    bindings = [scene["model"], *scene["assets"], *scene["sources"].values()]
    changed = [
        b["path"] for b in bindings if sha256_file(Path(b["path"])) != b["sha256"]
    ]
    failed = None
    if failed_build:
        failed = {
            "directory": str(failed_build),
            "physics_steps": 0,
            "kind": "engineering assertion over fixed furniture inferred inertia, before any simulation; corrected to verify all robot/payload inertias and all motor parameters, fixed furniture changes declared",
            "model": _file_binding(failed_build / "model/model.xml"),
            "builder_snapshot": _file_binding(failed_build / "BUILD_FAILED_SOURCE.py"),
        }
    reports = (
        sorted((root / "attempt_01").glob("*/REPORT.json"))
        if (root / "attempt_01").exists()
        else []
    )
    steps = sum(read_bound_json(p)["physics_steps"] for p in reports)
    summary = {
        "schema": "native-full-g1-round-review/v1",
        "static_passed": pre["passed"],
        "task_passed": bool(result and result["task_passed"]),
        "physics_steps": steps,
        "failed_build": failed,
        "preflight": _file_binding(root / "NATIVE_PREFLIGHT.json"),
        "attempt": _file_binding(root / "attempt_01/RESULT.json") if result else None,
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "scene": _file_binding(root / "model/SCENE.json"),
        "assets_checked": len(bindings),
        "changed_assets": changed,
        "full_official_g1_meshes": len(scene["official_robot_meshes"]),
        "native_triangles": sum(
            s["triangles"] for s in scene["native_collision_surfaces"]
        ),
        "visual_manifests": [
            _file_binding(p) for p in sorted(root.glob("*/MANIFEST.json"))
        ],
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "positive_training_samples_exported": 0,
        "limitations": scene["limitations"],
        "implementation": _file_binding(Path(__file__)),
        "no_old_success_inherited": True,
        "no_controller_or_collision_mask_tuning": True,
    }
    if changed:
        raise ValueError("changed scene assets")
    save(root / "ROUND_REVIEW.json", summary)
    print(
        {
            k: summary[k]
            for k in (
                "static_passed",
                "task_passed",
                "physics_steps",
                "changed_assets",
                "native_triangles",
            )
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--failed-build", type=Path)
    a = p.parse_args()
    run(a.root, a.failed_build)
