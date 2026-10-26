"""One continuous, motor-only reintegration of each qualified recorded episode.

No state injection between steps and no controller optimization. The three
single-use slots fit beneath the original global budget even if the live driver
uses every declared prefix ceiling. Failed/started slots are never retried.
"""

import argparse
from pathlib import Path
import time
import numpy as np
from .protocol import require_motion_protocol
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def rows(trace):
    yield from trace["warmup_substeps"]
    for record in trace["records"]:
        yield from record["substeps"]


def prepare(root):
    p = require_motion_protocol(root)
    path = root / "DYNAMICS_REPLAY_PLAN.json"
    if path.exists():
        raise FileExistsError(path)
    driver_ceiling = p["prior_physics_steps"] + 3 * (440 + 1440 + 3240 + 6240)
    slots = {cid: 6040 for cid in ("A", "B", "C")}
    assert driver_ceiling + sum(slots.values()) <= p["max_total_physics_steps"]
    save(
        path,
        {
            "schema": "native-walk-continuous-reintegration-plan/v1",
            "protocol": _file_binding(root / "REVISION_02_PROTOCOL.json"),
            "implementation": _file_binding(Path(__file__)),
            "driver_worst_case_including_v1_steps": driver_ceiling,
            "one_shot_slots_max_steps": slots,
            "combined_worst_case_steps": driver_ceiling + sum(slots.values()),
            "global_limit": p["max_total_physics_steps"],
            "method": "initialize once from frozen case; apply recorded native43ctrl; mj_step then mj_forward; never inject intermediate state",
            "tolerance": 0.0,
            "failed_slots_preserved_no_retry": True,
        },
    )
    return read_bound_json(path)


def run(root, episode):
    import mujoco

    p = require_motion_protocol(root)
    plan = read_bound_json(root / "DYNAMICS_REPLAY_PLAN.json")
    assert plan["implementation"]["sha256"] == sha256_file(Path(__file__))
    assert plan["protocol"]["sha256"] == sha256_file(root / "REVISION_02_PROTOCOL.json")
    report = read_bound_json(episode / "REPORT.json")
    audit = read_bound_json(episode / "AUDIT.json")
    cid = episode.parent.name
    assert cid in plan["one_shot_slots_max_steps"]
    assert report["case"] == p["case_bindings"][cid]
    assert report["task_passed"] and audit["control_passed"] and audit["task_passed"]
    assert audit["report"]["sha256"] == sha256_file(episode / "REPORT.json")
    assert report["trace"]["sha256"] == sha256_file(Path(report["trace"]["path"]))
    trace = read_bound_json(Path(report["trace"]["path"]))
    expected = sum(1 for _ in rows(trace))
    assert expected == report["physics_steps"] <= plan["one_shot_slots_max_steps"][cid]
    output = root / "continuous_dynamics" / cid
    output.mkdir(parents=True, exist_ok=False)
    save(
        output / "STARTED.json",
        {
            "plan": _file_binding(root / "DYNAMICS_REPLAY_PLAN.json"),
            "report": _file_binding(episode / "REPORT.json"),
            "audit": _file_binding(episode / "AUDIT.json"),
            "trace": report["trace"],
            "reserved_steps_charged_if_interrupted": expected,
            "implementation": _file_binding(Path(__file__)),
        },
    )
    model = load_model(report["model"]["path"])
    model.opt.timestep = p["acceptance_limits"]["simulation_dt_s"]
    data = mujoco.MjData(model)
    case = read_bound_json(Path(p["case_bindings"][cid]["path"]))
    data.qpos[:] = case["initial_qpos"]
    mujoco.mj_forward(model, data)
    maxima = {k: 0.0 for k in ("qpos", "qvel", "warmstart", "time")}
    count = 0
    failure = None
    started = time.monotonic()

    def compare(row, suffix):
        for key, actual, recorded in (
            ("qpos", data.qpos, row["full_qpos_" + suffix]),
            ("qvel", data.qvel, row["full_qvel_" + suffix]),
            ("warmstart", data.qacc_warmstart, row["qacc_warmstart_" + suffix]),
            ("time", data.time, row["time_" + suffix + "_s"]),
        ):
            err = float(np.max(np.abs(np.asarray(actual) - np.asarray(recorded))))
            if not np.isfinite(err):
                raise ValueError("nonfinite replay state")
            maxima[key] = max(maxima[key], err)
            if err != 0:
                raise ValueError(
                    f"continuous mismatch {key} {suffix} step={count}: {err}"
                )

    try:
        for row in rows(trace):
            compare(row, "before")
            if np.any(row["xfrc_applied"]) or np.any(row["qfrc_applied"]):
                raise ValueError("recorded external force")
            data.ctrl[:] = row["all_ctrl"]
            # Zero-initialized applied forces remain zero; no root/body state writes.
            mujoco.mj_step(model, data)
            count += 1
            mujoco.mj_forward(model, data)
            compare(row, "after")
            if count % 200 == 0:
                save(
                    output / "PROGRESS.json",
                    {"physics_steps": count, "expected_steps": expected},
                )
                print(
                    {"case": cid, "dynamics_step": count, "maximum_error": maxima},
                    flush=True,
                )
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    result = {
        "schema": "native-walk-continuous-reintegration/v1",
        "passed": failure is None and count == expected,
        "failure": failure,
        "physics_steps": count,
        "expected_steps": expected,
        "maximum_absolute_error": maxima,
        "intermediate_state_injections": 0,
        "initializations": 1,
        "no_external_support": True,
        "not_an_additional_autonomous_success": True,
        "wall_s": time.monotonic() - started,
        "started": _file_binding(output / "STARTED.json"),
    }
    save(output / "RESULT.json", result)
    print(result, flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--episode", type=Path)
    ap.add_argument("--prepare", action="store_true")
    args = ap.parse_args()
    if args.prepare:
        print(prepare(args.root), flush=True)
    else:
        run(args.root, args.episode)
