"""Mechanical evidence review and compact reusable development trajectory export."""

import argparse
from pathlib import Path
import numpy as np
from .protocol import require_motion_protocol
from .dynamics_replay import rows
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def binding_ok(binding):
    assert sha256_file(Path(binding["path"])) == binding["sha256"], binding["path"]


def verify(root):
    import av
    import cv2

    protocol = require_motion_protocol(root)
    result = read_bound_json(root / "motion_v2/RESULT.json")
    prior = read_bound_json(root / "motion_v1/RESULT.json")
    assert result["task_passed"] and result["qualified_conditions"] == ["A", "B", "C"]
    assert (
        result["error"] is None
        and result["unresolved_child_conservative_step_charge"] == 0
    )
    assert prior["physics_steps"] == protocol["prior_physics_steps"]
    for outcome in prior["outcomes"] + result["outcomes"]:
        binding_ok(outcome["report"])
        binding_ok(outcome["audit"])
    dynamics = {}
    for cid in ("A", "B", "C"):
        dpath = root / "continuous_dynamics" / cid / "RESULT.json"
        dyn = read_bound_json(dpath)
        assert dyn["passed"] and dyn["failure"] is None
        assert dyn["initializations"] == 1 and dyn["intermediate_state_injections"] == 0
        assert max(dyn["maximum_absolute_error"].values()) == 0
        binding_ok(dyn["started"])
        start = read_bound_json(Path(dyn["started"]["path"]))
        for key in ("plan", "report", "audit", "trace", "implementation"):
            binding_ok(start[key])
        dynamics[cid] = dyn
    cost = (
        prior["physics_steps"]
        + result["physics_steps"]
        + sum(d["physics_steps"] for d in dynamics.values())
    )
    assert cost <= protocol["max_total_physics_steps"]
    output = root / "delivery"
    output.mkdir(exist_ok=False)
    from sage.experiments.embodied_transport_native_v1.model import load_model
    from sage.experiments.embodied_data_stability_v1 import (
        sonic_native_dynamic_shadow as native,
    )
    import mujoco

    scene = read_bound_json(root / "model/SCENE.json")
    model = load_model(scene["model"]["path"])
    ids = native._model_ids(mujoco, model)
    save(
        output / "EXPORT_SCHEMA.json",
        {
            "schema": "native-walk-reusable-trajectory/v1",
            "nq": model.nq,
            "nv": model.nv,
            "nu": model.nu,
            "joint_order": [
                {
                    "name": model.joint(i).name,
                    "qpos_address": int(model.jnt_qposadr[i]),
                    "dof_address": int(model.jnt_dofadr[i]),
                }
                for i in range(model.njnt)
            ],
            "actuator_order": [model.actuator(i).name for i in range(model.nu)],
            "body_target_joint_names": [
                model.joint(int(i)).name for i in ids["joint_ids"]
            ],
            "model": scene["model"],
            "scene": _file_binding(root / "model/SCENE.json"),
            "simulation_dt_s": 0.005,
            "policy_dt_s": 0.02,
            "units": {
                "time": "second",
                "root_position": "meter",
                "joint_angle": "radian",
                "ctrl": "native actuator torque newton_meter",
            },
            "row_alignment": "each complete physical step, before and after state with actual native43ctrl, time_s is interval end",
            "contacts_and_policy_io": "full contacts and exact encoder/decoder IO retained in per-case bound original TRACE/POLICY_IO, not silently omitted from evidence",
            "source_role": "development_validation",
            "dataset_split": "unassigned",
            "training_claim": "three quality-controlled development demonstrations only; no policy trained and no heldout/learning benefit asserted",
        },
    )
    cases = []
    engine_hashes = set()
    for cid in ("A", "B", "C"):
        qualified = [
            o for o in result["outcomes"] if o["case"] == cid and o["task_passed"]
        ]
        assert len(qualified) == 1
        start = read_bound_json(root / "continuous_dynamics" / cid / "STARTED.json")
        assert start["report"] == qualified[0]["report"]
        assert start["audit"] == qualified[0]["audit"]
        episode = Path(qualified[0]["report"]["path"]).parent
        report = read_bound_json(episode / "REPORT.json")
        audit = read_bound_json(episode / "AUDIT.json")
        assert (
            report["task_passed"]
            and audit["task_passed"]
            and all(audit["gates"].values())
        )
        assert report["case"] == protocol["case_bindings"][cid]
        assert report["protocol"]["sha256"] == sha256_file(
            root / "REVISION_02_PROTOCOL.json"
        )
        assert (
            report["source_role"] == "development_validation"
            and report["dataset_split"] == "unassigned"
        )
        assert report["no_external_support"]
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
        engine_hashes.add(report["engine"]["sha256"])
        trace = read_bound_json(Path(report["trace"]["path"]))
        physical = list(rows(trace))
        assert (
            len(physical) == report["physics_steps"] == dynamics[cid]["physics_steps"]
        )
        assert all(
            s["safe"]
            and not s["forbidden_contacts"]
            and not np.any(s["xfrc_applied"])
            and not np.any(s["qfrc_applied"])
            for s in physical
        )
        video = root / f"video_{cid}_complete"
        vm = read_bound_json(video / "MANIFEST.json")
        for binding in vm["files"].values():
            binding_ok(binding)
        for key in ("report", "audit", "trace", "model", "scene", "implementation"):
            binding_ok(vm[key])
        assert vm["report"] == qualified[0]["report"]
        assert not vm["diagnostic_only"] and not vm["camera_check_only"]
        assert vm["proxy_body"] is False and vm["new_physics_steps"] == 0
        assert vm["frames"] * 4 == len(physical)
        assert abs(vm["duration_s"] - vm["source_duration_s"]) < 1e-9
        # Decode actual encoded MP4 rather than trusting renderer success or stills.
        selection = sorted(
            set(
                [0, vm["frames"] - 1]
                + [
                    i // 4
                    for i, s in enumerate(physical)
                    if i % 4 == 3
                    and s["phase"] in ("walking", "braking", "final_stand")
                    and (i == 3 or s["phase"] != physical[i - 4]["phase"])
                ]
            )
        )
        for phase in ("walking", "braking", "final_stand"):
            phase_frames = [
                i // 4
                for i, s in enumerate(physical)
                if i % 4 == 3 and s["phase"] == phase
            ]
            assert phase_frames
            selection.append(phase_frames[len(phase_frames) // 2])
        selection = sorted(set(selection))
        decoded = []
        count = 0
        timestamps = []
        container = av.open(str(video / "motion.mp4"))
        for index, vf in enumerate(container.decode(video=0)):
            timestamps.append(float(vf.time))
            if index in selection:
                rgb = vf.to_ndarray(format="rgb24")
                path = output / f"{cid}_decoded_{index:04d}.jpg"
                cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                decoded.append(rgb)
            count += 1
        container.close()
        assert count == vm["frames"]
        assert np.max(np.abs(np.asarray(timestamps) - np.arange(count) / 50)) < 1e-9
        assert decoded
        thumbs = [
            cv2.resize(rgb, (640, 480), interpolation=cv2.INTER_AREA) for rgb in decoded
        ]
        while len(thumbs) % 4:
            thumbs.append(np.zeros_like(thumbs[0]))
        grid = np.concatenate(
            [
                np.concatenate(thumbs[i : i + 4], axis=1)
                for i in range(0, len(thumbs), 4)
            ],
            axis=0,
        )
        cv2.imwrite(
            str(output / f"{cid}_decoded_review.jpg"),
            cv2.cvtColor(grid, cv2.COLOR_RGB2BGR),
        )
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
            "xfrc_applied": "xfrc_applied",
            "qfrc_applied": "qfrc_applied",
        }
        arrays = {
            name: np.asarray([s[key] for s in physical]) for name, key in fields.items()
        }
        np.savez_compressed(output / f"{cid}_trajectory.npz", **arrays)
        with np.load(output / f"{cid}_trajectory.npz", allow_pickle=False) as exported:
            assert all(
                np.array_equal(exported[name], value) for name, value in arrays.items()
            )
        cases.append(
            {
                "id": cid,
                "report": qualified[0]["report"],
                "audit": qualified[0]["audit"],
                "continuous_dynamics": _file_binding(
                    root / "continuous_dynamics" / cid / "RESULT.json"
                ),
                "video": _file_binding(video / "MANIFEST.json"),
                "decoded_frames": count,
                "export": _file_binding(output / f"{cid}_trajectory.npz"),
                "task_metrics": audit["task_metrics"],
                "maximum_penetration_m": max(s["penetration_m"] for s in physical),
                "maximum_contact_force_n": max(s["contact_force_n"] for s in physical),
                "minimum_up_component": min(s["up_component"] for s in physical),
                "minimum_root_height_m": min(s["full_qpos_after"][2] for s in physical),
                "physical_steps": len(physical),
            }
        )
        print(
            {"case": cid, "decoded_frames": count, "machine_checks_passed": True},
            flush=True,
        )
    assert len(engine_hashes) == 1
    save(
        output / "MECHANICAL_REVIEW.json",
        {
            "schema": "native-walk-final-mechanical-review/v1",
            "machine_checks_passed": True,
            "manual_video_review_pending": True,
            "all_three_conditions_same_frozen_controller": True,
            "cases": cases,
            "physics_cost": {
                "failed_v1_steps": prior["physics_steps"],
                "v2_all_prefix_steps": result["physics_steps"],
                "continuous_reintegration_steps": sum(
                    d["physics_steps"] for d in dynamics.values()
                ),
                "global_total": cost,
                "limit": protocol["max_total_physics_steps"],
            },
            "failure_preserved": _file_binding(root / "motion_v1/RESULT.json"),
            "result": _file_binding(root / "motion_v2/RESULT.json"),
            "implementation": _file_binding(Path(__file__)),
            "source_role": "development_validation",
            "dataset_split": "unassigned",
            "not_heldout_generalization_or_production": True,
            "files": {
                f.name: _file_binding(f)
                for f in sorted(output.iterdir())
                if f.is_file()
            },
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    verify(ap.parse_args().root)
