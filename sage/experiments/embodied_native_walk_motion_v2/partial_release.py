"""Honest A-only delivery with preserved B failure, never a three-case pass."""

import argparse
from pathlib import Path
import numpy as np
from .protocol import require_motion_protocol
from .dynamics_replay import rows
from .delivery import binding_ok
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, include_b=False):
    import av
    import cv2

    protocol = require_motion_protocol(root)
    result = read_bound_json(root / "motion_v2/RESULT.json")
    assert not result["task_passed"] and result["qualified_conditions"] == ["A"]
    assert (
        result["error"] is None
        and result["unresolved_child_conservative_step_charge"] == 0
    )
    output = root / ("partial_delivery" if include_b else "A_video_review")
    output.mkdir(exist_ok=False)
    reviews = []
    for cid, stage, video_name in [("A", "active_1500", "video_A_complete")] + (
        [("B", "active_0750", "video_B_diagnostic")] if include_b else []
    ):
        episode = root / "motion_v2" / cid / stage
        report = read_bound_json(episode / "REPORT.json")
        audit = read_bound_json(episode / "AUDIT.json")
        for key in (
            "case",
            "protocol",
            "scene",
            "model",
            "engine",
            "trace",
            "policy_io",
        ):
            binding_ok(report[key])
        binding_ok(audit["report"])
        if cid == "A":
            assert (
                report["task_passed"]
                and audit["task_passed"]
                and all(audit["gates"].values())
            )
            dyn = read_bound_json(root / "continuous_dynamics/A/RESULT.json")
            assert dyn["passed"] and max(dyn["maximum_absolute_error"].values()) == 0
            start = read_bound_json(root / "continuous_dynamics/A/STARTED.json")
            assert start["report"] == _file_binding(episode / "REPORT.json")
        else:
            assert not report["task_passed"] and not audit["task_passed"]
            assert [k for k, v in audit["gates"].items() if not v] == [
                "bounded_complete_prefix"
            ]
        trace = read_bound_json(Path(report["trace"]["path"]))
        physical = list(rows(trace))
        assert len(physical) == report["physics_steps"]
        assert all(
            s["safe"]
            and not np.any(s["xfrc_applied"])
            and not np.any(s["qfrc_applied"])
            and not s["forbidden_contacts"]
            for s in physical
        )
        manifest = read_bound_json(root / video_name / "MANIFEST.json")
        for binding in manifest["files"].values():
            binding_ok(binding)
        for key in ("implementation", "report", "audit", "trace", "model", "scene"):
            binding_ok(manifest[key])
        assert manifest["report"] == _file_binding(episode / "REPORT.json")
        assert manifest["diagnostic_only"] == (cid == "B")
        assert not manifest["proxy_body"] and not manifest["physical_collision_changes"]
        assert manifest["frames"] * 4 == len(physical)
        assert abs(manifest["duration_s"] - len(physical) * 0.005) < 1e-9
        indices = {0, manifest["frames"] - 1}
        for phase in ("walking", "braking", "final_stand"):
            candidates = [
                i // 4
                for i, s in enumerate(physical)
                if i % 4 == 3 and s["phase"] == phase
            ]
            if candidates:
                indices.update([candidates[0], candidates[len(candidates) // 2]])
        decoded, timestamps = [], []
        movie = av.open(str(root / video_name / "motion.mp4"))
        for i, vf in enumerate(movie.decode(video=0)):
            timestamps.append(float(vf.time))
            if i in indices:
                rgb = vf.to_ndarray(format="rgb24")
                cv2.imwrite(
                    str(output / f"{cid}_decoded_{i:04d}.jpg"),
                    cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                )
                decoded.append(
                    cv2.resize(rgb, (640, 480), interpolation=cv2.INTER_AREA)
                )
        movie.close()
        assert len(timestamps) == manifest["frames"]
        assert (
            np.max(np.abs(np.asarray(timestamps) - np.arange(len(timestamps)) / 50))
            < 1e-9
        )
        while len(decoded) % 4:
            decoded.append(np.zeros_like(decoded[0]))
        sheet = np.concatenate(
            [
                np.concatenate(decoded[i : i + 4], axis=1)
                for i in range(0, len(decoded), 4)
            ],
            axis=0,
        )
        cv2.imwrite(
            str(output / f"{cid}_decoded_review.jpg"),
            cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR),
        )
        if cid == "A" and include_b:
            fields = {
                "time_s": "time_after_s",
                "qpos_before": "full_qpos_before",
                "qpos_after": "full_qpos_after",
                "qvel_before": "full_qvel_before",
                "qvel_after": "full_qvel_after",
                "qacc_warmstart_before": "qacc_warmstart_before",
                "qacc_warmstart_after": "qacc_warmstart_after",
                "ctrl": "all_ctrl",
                "body_position_target_rad": "position_target_rad",
                "phase": "phase",
            }
            arrays = {
                name: np.asarray([s[key] for s in physical])
                for name, key in fields.items()
            }
            np.savez_compressed(output / "A_trajectory.npz", **arrays)
            with np.load(output / "A_trajectory.npz", allow_pickle=False) as exported:
                assert all(
                    np.array_equal(exported[name], value)
                    for name, value in arrays.items()
                )
        reviews.append(
            {
                "id": cid,
                "task_passed": report["task_passed"],
                "metrics": audit["task_metrics"],
                "report": _file_binding(episode / "REPORT.json"),
                "audit": _file_binding(episode / "AUDIT.json"),
                "video": _file_binding(root / video_name / "MANIFEST.json"),
                "decoded_frames": len(timestamps),
                "maximum_penetration_m": max(s["penetration_m"] for s in physical),
                "maximum_contact_force_n": max(s["contact_force_n"] for s in physical),
            }
        )
    prior = read_bound_json(root / "motion_v1/RESULT.json")
    replay = read_bound_json(root / "continuous_dynamics/A/RESULT.json")
    cost = prior["physics_steps"] + result["physics_steps"] + replay["physics_steps"]
    assert cost == 18059 <= protocol["max_total_physics_steps"]
    save(
        output / "REVIEW.json",
        {
            "schema": "native-walk-partial-release/v1",
            "overall_goal_achieved": False,
            "qualified_conditions": ["A"],
            "rejected_condition": "B",
            "unrun_conditions": ["C"],
            "cases": reviews,
            "manual_decoded_frame_review_pending": True,
            "physics_cost": {
                "v1_failed": prior["physics_steps"],
                "v2_all_prefixes": result["physics_steps"],
                "A_dynamics_reintegration": replay["physics_steps"],
                "total": cost,
                "limit": protocol["max_total_physics_steps"],
            },
            "causal_versions_used": 2,
            "causal_version_cap": 2,
            "new_physics_steps": 0,
            "source_role": "development_validation",
            "dataset_split": "unassigned",
            "export_scope": "A only quality-controlled demonstration; nq50/nv49/nu43 native model order; body29target order uses frozen native._model_ids; units seconds/meters/radians/newton-meters; contacts/NN IO retained in bound original trace; not training or heldout proof",
            "result": _file_binding(root / "motion_v2/RESULT.json"),
            "rejection_review": _file_binding(root / "B_REJECTION_REVIEW.json"),
            "continuous_dynamics": _file_binding(
                root / "continuous_dynamics/A/RESULT.json"
            ),
            "implementation": _file_binding(Path(__file__)),
            "files": {
                f.name: _file_binding(f)
                for f in sorted(output.iterdir())
                if f.is_file()
            },
        },
    )
    print(
        {
            "output": str(output),
            "qualified": ["A"],
            "goal_achieved": False,
            "total_steps": cost,
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--include-b", action="store_true")
    args = ap.parse_args()
    run(args.root, args.include_b)
