"""Zero-integration audit of body/finger controls, continuous state and task roles."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_v1.metrics_r5 import observe
from .control import ARM, SONIC
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ISAACLAB_TO_MUJOCO,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def audit(root):
    import mujoco

    output = root / "AUDIT.json"
    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(root / "REPORT.json")
    case = read_bound_json(Path(report["case"]["path"]))
    for b in [
        report["case"],
        report["protocol"],
        report["trace"],
        report["model"],
        *report["source_bindings"].values(),
        *report["inputs"].values(),
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("evidence binding changed: " + b["path"])
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = trace["records"]
    active = [r for r in rows if r["sonic_candidate_consumed_by_physics"]]
    samples = trace["warmup_substeps"] + [s for r in rows for s in r["substeps"]]
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    model.opt.timestep = native.SIMULATION_DT_S
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    controls = {k: np.array(v) for k, v in native.official_control_arrays().items()}
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    max_pd = max_raw = max_hand = max_geometry = max_contact = max_ff = 0.0
    snapshots = np.load(root / "reference_snapshots.npz")
    standing = case["task_mode"] == "standing_pick_place"
    targets = commands = physical = geometry = external = True
    previous = np.array(DEFAULT_ANGLES)
    previous_applied = None
    history_targets = True
    for row_index, r in enumerate(rows):
        applied = np.array(r["hybrid_target_rad"])
        decoded_applied = (
            np.array(DEFAULT_ANGLES)
            + np.array(r["applied_raw_action_isaaclab"])[list(ISAACLAB_TO_MUJOCO)]
            * ACTION_SCALES
        )
        history_targets &= np.max(np.abs(decoded_applied - applied)) < 1e-6
        if previous_applied is not None and r["sonic_candidate_consumed_by_physics"]:
            history_targets &= (
                np.all(applied >= lower)
                and np.all(applied <= upper)
                and np.max(np.abs(applied - previous_applied))
                <= native.MAX_CANDIDATE_STEP_RAD
            )
        previous_applied = applied
        target = (
            np.array(DEFAULT_ANGLES)
            + np.array(r["raw_action_isaaclab"])[list(ISAACLAB_TO_MUJOCO)]
            * ACTION_SCALES
        )
        max_raw = max(max_raw, float(np.max(np.abs(target - r["candidate_rad"]))))
        if r["sonic_candidate_consumed_by_physics"] or r["tick"] < 50:
            commands &= bool(
                np.isfinite(target).all()
                and np.all((target >= lower) & (target <= upper))
                and np.max(np.abs(target - previous)) <= native.MAX_CANDIDATE_STEP_RAD
            )
        previous = target
        if not r["sonic_candidate_consumed_by_physics"]:
            continue
        mixed = target.copy()
        mixed[ARM] = snapshots["per_tick_qpos"][row_index, ARM + 7]
        targets &= np.array_equal(mixed, np.array(r["hybrid_target_rad"]))
        target = mixed
        for s in r["substeps"]:
            data.qpos[:] = s["full_qpos_before"]
            data.qvel[:] = s["full_qvel_before"]
            mujoco.mj_forward(model, data)
            ff = np.zeros(29)
            ff[ARM] = data.qfrc_bias[np.array(ids["dof_ids"])[ARM]]
            max_ff = max(max_ff, float(np.max(np.abs(ff - s["body_feedforward_nm"]))))
            torque = np.clip(
                controls["kp"] * (target - s["body_position_before_rad"])
                - controls["kd"] * s["body_velocity_before_rad_s"]
                + ff,
                -controls["effort_limit"],
                controls["effort_limit"],
            )
            max_pd = max(
                max_pd,
                float(np.max(np.abs(torque - s["body_torque_nm"]))),
                float(
                    np.max(
                        np.abs(torque - np.array(s["all_ctrl"])[ids["actuator_ids"]])
                    )
                ),
            )
            targets &= (
                s["position_target_rad"] == r["hybrid_target_rad"]
                and not s["support_enabled"]
                and not np.any(s["xfrc_applied"])
            )
    for s in samples:
        data.qpos[:] = s["full_qpos_after"]
        data.qvel[:] = s["full_qvel_after"]
        data.ctrl[:] = s["all_ctrl"]
        data.qacc_warmstart[:] = s["qacc_warmstart_after"]
        data.xfrc_applied[:] = s["xfrc_applied"]
        data.qfrc_applied[:] = s["qfrc_applied"]
        mujoco.mj_forward(model, data)
        p = observe(mujoco, model, data)
        max_geometry = max(
            max_geometry,
            float(
                np.max(
                    np.abs(
                        np.array(p["world_position_m"])
                        - s["payload"]["world_position_m"]
                    )
                )
            ),
            abs(p["bottom_z_m"] - s["payload"]["bottom_z_m"]),
        )
        geometry &= len(p["contacts"]) == len(s["payload"]["contacts"])
        for a, b in zip(p["contacts"], s["payload"]["contacts"]):
            geometry &= a["role"] == b["role"] and a["other_geom"] == b["other_geom"]
            max_contact = max(
                max_contact,
                abs(a["normal_force_n"] - b["normal_force_n"]),
                abs(a["distance_m"] - b["distance_m"]),
            )
        body = model.body("pelvis").id
        f = np.array(s["xfrc_applied"])
        f[body] = 0
        external &= not np.any(f) and not np.any(s["qfrc_applied"])
        peak = depth = 0.0
        for i, c in enumerate(data.contact):
            force = np.zeros(6)
            mujoco.mj_contactForce(model, data, i, force)
            peak = max(peak, float(np.linalg.norm(force[:3])))
            depth = max(depth, -float(c.dist))
        physical &= bool(
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and data.xpos[body, 2] >= 0.65
            and data.xmat[body].reshape(3, 3)[2, 2] >= 0.5
            and depth <= 0.01
            and peak <= 600
            and not p["scene_violation"]
            and not p["body_fixture_violation"]
            and not p["non_task_contact"]
            and p["world_position_m"][2] >= 0.25
        )
        h = s["hand_pd"]
        names = h["joint_names"]
        effort = np.array([model.actuator(n).ctrlrange[1] for n in names])
        kp = np.array([2.0 if "thumb_0" in n else 1.5 for n in names])
        torque = np.clip(
            kp * (np.array(h["target_rad"]) - h["positions_before_rad"])
            - 0.1 * np.array(h["velocities_before_rad_s"]),
            -effort,
            effort,
        )
        max_hand = max(max_hand, float(np.max(np.abs(torque - h["torque_nm"]))))
    prefix = True
    if report["admission"]:
        a = read_bound_json(Path(report["admission"]["path"]))
        t = read_bound_json(Path(a["trace"]["path"]))
        prefix &= len(rows) >= 50 and all(
            x[k] == y[k]
            for x, y in zip(rows[:50], t["records"][:50])
            for k in ("candidate_rad", "encoder_input_sha256", "decoder_input_sha256")
        )
        prefix &= all(
            x["full_qpos_after"] == y["full_qpos_after"]
            for ra, rb in zip(rows[:50], t["records"][:50])
            for x, y in zip(ra["substeps"], rb["substeps"])
        )
    if report["previous"]:
        pr = read_bound_json(Path(report["previous"]["path"]))
        pt = read_bound_json(Path(pr["trace"]["path"]))
        previous_active = [
            r for r in pt["records"] if r["sonic_candidate_consumed_by_physics"]
        ]
        prefix &= len(active) >= len(previous_active) and all(
            x["full_qpos_after"] == y["full_qpos_after"]
            for ra, rb in zip(active, previous_active)
            for x, y in zip(ra["substeps"], rb["substeps"])
        )
    free = (
        model.body_parentid[model.body("payload").id] == 0
        and model.jnt_type[model.joint("payload_free").id] == mujoco.mjtJoint.mjJNT_FREE
        and model.neq == 0
        and model.nmocap == 0
    )
    complete = (
        (
            report["active_safety_passed"]
            and len(active) == report["active_control_ticks"]
        )
        if report["admission"]
        else report["admission_ready"] and len(rows) == 100
    )
    gates = {
        "applied_hybrid_action_history_and_guard": bool(history_targets),
        "bounded_complete_prefix": bool(complete and report["stop_reason"] is None),
        "unchanged_SONIC22_and_declared_right_arm7": bool(
            targets and commands and max_raw == 0 and max_pd <= 1e-9 and max_ff <= 1e-9
        ),
        "native_finger_pd": max_hand == 0,
        "reconstructed_physics": bool(physical),
        "reconstructed_object_contacts": bool(
            geometry and max_geometry <= 1e-12 and max_contact <= 1e-6
        ),
        "external_forces_only_observer_pelvis": bool(external),
        "state_chain": all(
            a["full_qpos_after"] == b["full_qpos_before"]
            for a, b in zip(samples, samples[1:])
        ),
        "all_prefixes_exact": bool(prefix),
        "free_unattached_object": bool(free),
        "initial_empty_hand_object_on_source": not trace["initial_object"][
            "hand_contact"
        ]
        and np.linalg.norm(
            np.array(samples[0]["payload"]["world_position_m"])
            - case["source_object_xyz_m"]
        )
        < 0.01,
    }
    control = all(gates.values())
    expected = [
        "source_stop",
        "reach",
        "close",
        "lift",
        "carry",
        "target_stop",
        "place",
        "release",
        "retract",
        "settle",
        "done",
    ]
    if standing:
        expected = [
            "reach",
            "close",
            "lift",
            "place",
            "release",
            "retract",
            "settle",
            "done",
        ]
    events = report["task_events"]
    order = [e["to"] for e in events]
    task_gates = {
        "ordered_full_task": order == expected,
        "source_clearance": False,
        "physical_transport": False,
        "destination_release": False,
        "final_object_hand_free": False,
    }
    if order == expected:
        lift = next(e for e in events if e["to"] == ("place" if standing else "carry"))
        release = next(e for e in events if e["to"] == "release")
        final = events[-1]["object"]
        task_gates.update(
            source_clearance=lift["object"]["bottom_z_m"]
            >= case["support_top_m"] + 0.02
            and not lift["object"]["source_supported"]
            and lift["object"]["opposing"],
            physical_transport=np.linalg.norm(
                np.array(final["world_position_m"])[:2]
                - case["source_object_xyz_m"][:2]
            )
            >= (0.10 if standing else 0.2),
            destination_release=release["object"]["target_supported"],
            final_object_hand_free=final["target_supported"]
            and not final["hand_contact"]
            and np.linalg.norm(final["linear_velocity_m_s"]) < 0.02,
        )
        lift_frame = next(
            e["frame"] for e in events if e["to"] == ("place" if standing else "carry")
        )
        lift_window = [
            s
            for r in active
            if lift_frame - 25 <= r["reference_tick"] < lift_frame
            for s in r["substeps"]
        ]
        task_gates["continuous_half_second_true_lift"] = len(
            lift_window
        ) == 100 and all(
            s["payload"]["bottom_z_m"] >= case["support_top_m"] + 0.02
            and s["payload"]["opposing"]
            and not s["payload"]["source_supported"]
            and not s["payload"]["target_supported"]
            for s in lift_window
        )
        carry_rows = [
            r for r in active if r["task"]["stage"] in ("carry", "target_stop")
        ]
        for side in () if standing else ("left", "right"):
            airborne = landed = False
            for r in carry_rows:
                foot = r["substeps"][-1]["feet"][side]
                if (
                    foot["sole_clearance_m"] > 0.015
                    and foot["ground_contact_force_max_n"] < 1
                ):
                    airborne = True
                if airborne and foot["ground_contact_force_max_n"] > 5:
                    landed = True
            task_gates[side + "_real_carry_step"] = landed
        tail = [s for r in active[-25:] for s in r["substeps"]]
        task_gates["continuous_final_hand_free_hold"] = len(tail) == 100 and all(
            s["payload"]["target_supported"]
            and not s["payload"]["hand_contact"]
            and np.linalg.norm(s["payload"]["linear_velocity_m_s"]) < 0.02
            and np.linalg.norm(s["root_velocity_after_m_s"][:2]) < 0.04
            and s["pelvis_height_m"] >= 0.7
            and s["up_component"] >= 0.97
            for s in tail
        )
    result = {
        "schema": "continuous-transport-audit/v1",
        "control_passed": bool(control),
        "task_passed": bool(
            control and report["task_passed"] and all(task_gates.values())
        ),
        "gates": {key: bool(value) for key, value in gates.items()},
        "task_gates": {key: bool(value) for key, value in task_gates.items()},
        "max_body_pd_error": max_pd,
        "max_declared_arm_feedforward_error": max_ff,
        "task_mode": case["task_mode"],
        "full_transport_passed": bool(
            not standing
            and control
            and report["task_passed"]
            and all(task_gates.values())
        ),
        "max_raw_transform_error": max_raw,
        "max_finger_pd_error": max_hand,
        "max_object_geometry_error": max_geometry,
        "max_contact_error": max_contact,
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {"control": control, "task": result["task_passed"], "gates": gates}, flush=True
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    audit(p.parse_args().root)
