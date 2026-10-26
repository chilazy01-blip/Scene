"""Bind an accepted physical motion cycle to its exact browser/video delivery."""

import argparse
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_planner_preflight import _file_binding


def delivery(run, video, browser, output):
    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(run / "REPORT.json")
    audit = read_bound_json(run / "INDEPENDENT_AUDIT.json")
    integrity = read_bound_json(run / "REFERENCE_INTEGRITY_AUDIT.json")
    rendered = read_bound_json(video / "MANIFEST.json")
    packaged = read_bound_json(browser / "MANIFEST.json")
    digest = sha256_file(run / "REPORT.json")
    gates = {
        "physical_task_passed": audit["task_passed"]
        and report["controlled_stop_acceptance"]["passed"],
        "input_and_render_pose_integrity": integrity["classification"] == "passed",
        "video_passed_label_bound_to_audit": rendered["task_passed"] is True,
        "all_reports_identical_source": all(
            d["report"]["sha256"] == digest for d in (audit, integrity, rendered)
        ),
        "video_matches_active_ticks": rendered["frames"]
        == report["active_control_ticks"],
        "browser_duration_matches_physics": packaged["duration_s"]
        == report["active_control_ticks"] * 0.02,
        "no_replay_physics_or_generated_motion": rendered["physics_steps"] == 0
        and packaged["physics_steps"] == 0
        and not packaged["generated_or_interpolated_motion"],
    }
    bindings = [
        *report["inputs"].values(),
        *report["source_bindings"].values(),
        report["trace"],
        rendered["independent_audit"],
        rendered["renderer"],
        packaged["implementation"],
        packaged["source_manifest"],
        *rendered["artifacts"].values(),
        *packaged["artifacts"].values(),
    ]
    if any(sha256_file(Path(b["path"])) != b["sha256"] for b in bindings):
        raise ValueError("delivery dependency/artifact binding changed")
    if not all(gates.values()):
        raise ValueError(f"delivery refused: {gates}")
    document = {
        "schema": "sonic-motion-cycle-delivery/v1",
        "classification": "accepted_development_clip",
        "sample_identity_sha256": canonical_sha256(
            {"report": digest, "trace": report["trace"]["sha256"]}
        ),
        "provenance": {
            "source_role": "development_validation",
            "dataset_split": "unassigned",
            "held_out_evaluation": False,
            "random_seed": 1234,
            "scene": "official flat floor, collision-lite",
            "robot": "G1 body29, fixed hand joints; simplified render-only visual geometry",
        },
        "gates": gates,
        "metrics": audit["metrics"],
        "validation_duration_s": report["active_control_ticks"] * 0.02,
        "report": _file_binding(run / "REPORT.json"),
        "audit": _file_binding(run / "INDEPENDENT_AUDIT.json"),
        "integrity": _file_binding(run / "REFERENCE_INTEGRITY_AUDIT.json"),
        "trace": report["trace"],
        "video_manifest": _file_binding(video / "MANIFEST.json"),
        "browser_manifest": _file_binding(browser / "MANIFEST.json"),
        "animation": _file_binding(browser / "motion.gif"),
        "browser_page": _file_binding(browser / "replay.html"),
        "video": _file_binding(video / "motion.mp4"),
        "implementation": _file_binding(Path(__file__)),
        "capability_boundary": {
            "controlled_stop_validated": True,
            "single_development_case_only": True,
            "long_duration_or_generalization_validated": False,
            "full_mesh_collision_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output, document)
    print(
        json.dumps(
            {
                "classification": document["classification"],
                "gates": gates,
                "page": str(browser / "replay.html"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--video-root", type=Path, required=True)
    p.add_argument("--browser-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    delivery(args.run_root, args.video_root, args.browser_root, args.output)
