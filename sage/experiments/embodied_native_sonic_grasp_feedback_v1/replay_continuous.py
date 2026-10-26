"""Single-init continuous reintegration of recorded43 motor controls, counted."""

import argparse
from pathlib import Path
import time
import numpy as np
from .protocol_continuous import authorize, reserve
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, episode, output):
    import mujoco
    import resource,os
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])

    p = authorize(root)
    r = read_bound_json(episode / "REPORT.json")
    a = read_bound_json(episode / "AUDIT.json")
    from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file

    for binding in (
        r["trace"],
        r["model"],
        r["engine"],
        r["protocol"],
        a["report"],
        a["implementation"],
    ):
        assert sha256_file(Path(binding["path"])) == binding["sha256"]
    assert r["task_passed"] and a["task_passed"]
    assert not output.exists()
    trace = read_bound_json(Path(r["trace"]["path"]))
    case = read_bound_json(Path(p["case"]["path"]))
    steps = trace["warmup_substeps"] + [
        s for row in trace["records"] for s in row["substeps"]
    ]
    assert len(steps) == r["physics_steps"] <= 12040
    reserve(root, output, len(steps))
    output.mkdir(parents=True)
    safe_save(
        output / "STARTED.json",
        {
            "report": _file_binding(episode / "REPORT.json"),
            "audit": _file_binding(episode / "AUDIT.json"),
            "trace": r["trace"],
            "reserved_steps": len(steps),
            "implementation": _file_binding(Path(__file__)),
        },
    )
    model = load_model(r["model"]["path"])
    model.opt.timestep = 0.005
    data = mujoco.MjData(model)
    data.qpos[:50] = case["initial_robot_qpos"]
    adr = int(model.joint("payload_free").qposadr[0])
    data.qpos[adr : adr + 7] = [
        *case["source_object_xyz_m"],
        *case["source_object_quat"],
    ]
    mujoco.mj_forward(model, data)
    maximum = {k: 0.0 for k in ("qpos", "qvel", "warmstart", "time")}
    count = 0
    failure = None
    start = time.monotonic()

    def compare(s, when):
        for key, current, recorded in (
            ("qpos", data.qpos, s["full_qpos_" + when]),
            ("qvel", data.qvel, s["full_qvel_" + when]),
            ("warmstart", data.qacc_warmstart, s["qacc_warmstart_" + when]),
            ("time", data.time, s["time_" + when + "_s"]),
        ):
            error = float(np.max(np.abs(np.asarray(current) - np.asarray(recorded))))
            maximum[key] = max(maximum[key], error)
            if not np.isfinite(error) or error != 0:
                raise ValueError(f"{key} {when} mismatch step={count}: {error}")

    try:
        for s in steps:
            if time.time() >= p["deadline_epoch_utc"]:
                raise RuntimeError("two-hour physics deadline reached during replay")
            compare(s, "before")
            assert not np.any(s["xfrc_applied"]) and not np.any(s["qfrc_applied"])
            data.ctrl[:] = s["all_ctrl"]
            mujoco.mj_step(model, data)
            count += 1
            mujoco.mj_forward(model, data)
            compare(s, "after")
            if count % 200 == 0:
                safe_save(
                    output / "PROGRESS.json",
                    {"physics_steps": count, "expected": len(steps)},
                )
                print(
                    {"continuous_replay_steps": count, "maximum_error": maximum},
                    flush=True,
                )
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    result = {
        "schema": "native-mug-continuous-dynamics-replay/v1",
        "passed": failure is None and count == len(steps),
        "physics_steps": count,
        "expected_steps": len(steps),
        "maximum_absolute_error": maximum,
        "initializations": 1,
        "intermediate_state_injections": 0,
        "failure": failure,
        "not_an_additional_autonomous_success": True,
        "wall_s": time.monotonic() - start,
        "started": _file_binding(output / "STARTED.json"),
        "implementation": _file_binding(Path(__file__)),
    }
    safe_save(output / "REPORT.json", result)
    print(result, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--episode", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.episode, a.output)
