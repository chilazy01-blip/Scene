"""Final native-round failed-admission evidence and unchanged-source audit."""

import argparse
from pathlib import Path
import numpy as np
from .engine import authorize
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    protocol = authorize(root)
    scene = read_bound_json(root / "model/SCENE.json")
    diagnostic = read_bound_json(root / "static_diagnostic/REPORT.json")
    visual = read_bound_json(root / "static_diagnostic/MANIFEST.json")
    bindings = [scene["model"], *scene["assets"], *scene["sources"].values()]
    changed = [
        b["path"] for b in bindings if sha256_file(Path(b["path"])) != b["sha256"]
    ]
    for item in scene["official_robot_meshes"]:
        assert sha256_file(Path(item["source"]["path"])) == item["official_oid"]
    probes = []
    for geom_type, size in (
        ("sphere", ".02"),
        ("box", ".1 .05 .02"),
        ("capsule", ".02 .05"),
        ("cylinder", ".02 .05"),
    ):
        xml = f'<mujoco><worldbody><body pos="0 0 .019"><freejoint/><geom type="{geom_type}" size="{size}" mass="1"/></body></worldbody><deformable><flex dim="2" body="world" radius=".001" vertex="-2 -2 0 2 -2 0 0 2 0" element="0 1 2"><contact selfcollide="none" internal="false"/></flex></deformable></mujoco>'
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        probes.append(
            {
                "geom_type": geom_type,
                "xml": xml,
                "expected_contact": True,
                "contacts": int(data.ncon),
                "passed": data.ncon > 0,
                "physics_steps": 0,
            }
        )
    sources = sum(
        len(protocol[k])
        for k in ("dependencies", "parent_dependencies", "hybrid_parent_dependencies")
    )
    summary = {
        "schema": "native-full-g1-round-review/v1",
        "static_admission_passed": False,
        "task_passed": False,
        "physics_steps": 0,
        "reason": "initial mj_forward failed: findEdges no tree found for constraint 43; collision-only diagnostic finds ten fixed-fixture/native-floor contacts, no dynamic tree; separate box/capsule triangle overlap probes also fail",
        "full_official_g1_meshes": len(scene["official_robot_meshes"]),
        "all_robot_mesh_sha256_match_official": True,
        "native_scene_surfaces": len(scene["native_collision_surfaces"]),
        "native_scene_triangles": sum(
            s["triangles"] for s in scene["native_collision_surfaces"]
        ),
        "frozen_source_bindings_checked": sources,
        "scene_bindings_checked": len(bindings),
        "changed_assets": changed,
        "bridge_probes": probes,
        "bridge_passed": all(p["passed"] for p in probes),
        "diagnostic": _file_binding(root / "static_diagnostic/REPORT.json"),
        "visualization": _file_binding(root / "static_diagnostic/MANIFEST.json"),
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "build": _file_binding(root / "BUILD_REVIEW.json"),
        "model": scene["model"],
        "visual_review": {
            "inspected": [visual["preview"]["path"], visual["room"]["path"]],
            "full_g1_and_task_visible_in_preview": True,
            "wide_room_image_occluded": True,
            "preferred_image": visual["preview"],
            "static_only": True,
            "not_a_motion_or_task_success": True,
        },
        "next_steps": [
            "new protocol/model identity: filter only immovable-immovable contacts while preserving every dynamic robot/object vs native surface contact",
            "resolve box/capsule triangle contact regression before authorizing native standing or walking",
            "fresh standing qualification, then walking and transport; no previous simplified-model success inherited",
        ],
        "positive_training_samples_exported": 0,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "no_controller_changes": True,
        "no_active_attempt_started": True,
        "no_physics_or_collision_gate_relaxed": True,
        "mujoco_version": mujoco.mj_versionString(),
        "limitations": scene["limitations"],
        "implementation": _file_binding(Path(__file__)),
    }
    if changed:
        raise ValueError("scene asset changed")
    save(root / "ROUND_REVIEW.json", summary)
    print(
        {
            k: summary[k]
            for k in (
                "static_admission_passed",
                "task_passed",
                "physics_steps",
                "frozen_source_bindings_checked",
                "changed_assets",
                "bridge_passed",
            )
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
