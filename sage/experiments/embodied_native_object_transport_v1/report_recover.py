"""Recover only the absent short-admission JSON, without rerunning physics."""

import argparse
from pathlib import Path
import numpy as np
from .protocol import authorize
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    p = authorize(root)
    out = root / "version_01/admission"
    assert not (out / "REPORT.json").exists()
    trace = read_bound_json(out / "TRACE.json")
    rows = trace["warmup_substeps"] + [
        s for r in trace["records"] for s in r["substeps"]
    ]
    assert len(rows) == 440 and len(trace["records"]) == 100
    assert not trace["events"] and trace["rejected_command"] is None
    assert all(r["safe"] for r in rows)
    case = read_bound_json(Path(p["case"]["path"]))
    last = rows[-1]
    moved = float(
        np.linalg.norm(
            np.asarray(last["object_m"])[:2]
            - np.asarray(case["source_object_xyz_m"])[:2]
        )
    )
    error = float(
        np.linalg.norm(
            np.asarray(last["object_m"])[:2]
            - np.asarray(case["target_object_xyz_m"])[:2]
        )
    )
    tail = rows[-200:]
    gates = {
        "all_physical_safe": True,
        "complete_continuous_task": False,
        "held_carry_distance": False,
        "object_transported": moved >= 0.25,
        "carry_both_foot_cycles": False,
        "goal_error": error <= 0.10,
        "released_and_settled": all(
            s["desk_supported"]
            and not s["hand_contact"]
            and np.linalg.norm(s["object_velocity_m_s"]) < 0.02
            and np.linalg.norm(s["root_velocity_m_s"]) < 0.06
            for s in tail
        ),
        "no_rejection": True,
    }
    recovery = {
        "schema": "native-admission-report-output-recovery/v1",
        "physics_steps": 0,
        "preserved_physical_trace": _file_binding(out / "TRACE.json"),
        "original_engine": _file_binding(Path(__file__).with_name("engine.py")),
        "error": "NumPy bool in admission_passed JSON field; physical loop and complete trace/IO had already finished",
        "method": "derive short admission completion and metrics from untouched full trace, no physical rerun, no state edits",
        "new_wrapper": _file_binding(Path(__file__).with_name("report_safe_engine.py")),
        "implementation": _file_binding(Path(__file__)),
    }
    safe_save(out / "REPORT_OUTPUT_RECOVERY.json", recovery)
    result = {
        "schema": "native-mug-task-report/v1",
        "task_passed": False,
        "admission_passed": moved < 0.01,
        "gates": gates,
        "physics_steps": 440,
        "active_ticks": 100,
        "stage": "initial_stand",
        "stop_reason": None,
        "error": None,
        "events": [],
        "carry_distance_m": 0.0,
        "object_displacement_xy_m": moved,
        "goal_error_m": error,
        "carry_foot_cycles": {"left": 0, "right": 0},
        "max_held_slip_m": 0.0,
        "projected_ticks": sum(
            bool(r["projection"]["projected_joints"]) for r in trace["records"]
        ),
        "maximum_target_projection_rad": max(
            r["projection"]["maximum_projection_rad"] for r in trace["records"]
        ),
        "case": p["case"],
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "scene": p["scene"],
        "model": read_bound_json(Path(p["scene"]["path"]))["model"],
        "engine": _file_binding(Path(__file__).with_name("engine.py")),
        "trace": _file_binding(out / "TRACE.json"),
        "policy_io": _file_binding(out / "POLICY_IO.npz"),
        "wall_s": None,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "independent_audit_pending": True,
        "output_recovery": _file_binding(out / "REPORT_OUTPUT_RECOVERY.json"),
    }
    safe_save(out / "REPORT.json", result)
    print(
        {
            "admission_passed": result["admission_passed"],
            "physics_steps": 440,
            "new_physics_steps": 0,
            "object_xy_drift_m": moved,
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
