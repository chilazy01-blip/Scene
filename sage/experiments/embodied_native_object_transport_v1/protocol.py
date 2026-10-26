"""Immutable new-stage identities, finite shared physics budget and safe targets."""

import argparse
from pathlib import Path
import time
import numpy as np
from .metrics import LIMITS
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def authorize(root):
    p = read_bound_json(root / "PROTOCOL.json")
    for b in [
        p["plan"],
        p["case"],
        p["scene"],
        p["geometry_preflight"],
        p["reference"],
        *p["dependencies"].values(),
        *p["reused_dependencies"].values(),
        *p["inputs"].values(),
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("frozen task dependency changed: " + b["path"])
    return p


def freeze(root, parent):
    assert not (root / "PROTOCOL.json").exists()
    native = read_bound_json(parent / "REVISION_02_PROTOCOL.json")
    pre = read_bound_json(root / "TASK_GEOMETRY_PREFLIGHT_R5.json")
    assert pre["passed"]
    dependencies = {
        f.name: _file_binding(f)
        for f in sorted(Path(__file__).parent.glob("*.py"))
        if not f.name.startswith("test")
    }
    reused = dict(native["dependencies"])
    for package in (
        "embodied_transport_hybrid_v1",
        "embodied_transport_contact_v1",
        "embodied_carry_v1",
    ):
        for f in sorted((Path(__file__).parent.parent / package).glob("*.py")):
            if not f.name.startswith("test"):
                reused[package + "/" + f.name] = _file_binding(f)
    p = {
        "schema": "native-mug-task-protocol/v1",
        "plan": _file_binding(root / "PLAN.json"),
        "case": _file_binding(root / "CASE_R5.json"),
        "scene": _file_binding(root / "model/SCENE.json"),
        "geometry_preflight": _file_binding(root / "TASK_GEOMETRY_PREFLIGHT_R5.json"),
        "reference": native["reference_base"],
        "inputs": native["inputs"],
        "dependencies": dependencies,
        "reused_dependencies": reused,
        "limits": LIMITS,
        "simulation_dt_s": 0.005,
        "control_dt_s": 0.02,
        "warmup_ticks": 10,
        "admission_ticks": 100,
        "full_ticks": 2200,
        "max_causal_versions": 2,
        "max_new_physics_steps": 40000,
        "deadline_epoch_utc": 1792566838,
        "control": "SONIC22 feedback + right arm7 world-reference servo and joint-space gravity feedforward; original native43 motor/hand gains and effort; no external root/object forces",
        "small_target_excess_rule": "clip each body target to original jnt_range only if projection<=.035rad, record raw/mixed/projected and actual normalized action history; keep original MAX_CANDIDATE_STEP_RAD; never change real model limits",
        "acceptance": "one complete native-furniture task, actual pickup and physical held steps, release and settle, quantitative safety + real video; no requirement for all3oldwalkingcases",
        "old_experiments_unchanged": True,
        "frozen_at_epoch_utc": time.time(),
    }
    # 2026-10-21 07:13:58 UTC, original two-hour user-facing stage boundary.
    from datetime import datetime, timezone

    p["deadline_epoch_utc"] = datetime(
        2026, 10, 21, 7, 13, 58, tzinfo=timezone.utc
    ).timestamp()
    save(root / "PROTOCOL.json", p)
    save(
        root / "COST.json",
        {
            "reservations": [],
            "max_physics_steps": 40000,
            "prior_native_steps": 18059,
            "cumulative_cap": 60000,
        },
    )
    print(
        {"frozen": str(root / "PROTOCOL.json"), "static_path": True, "budget": 40000},
        flush=True,
    )


def reserve(root, output, ceiling):
    p = authorize(root)
    if time.time() >= p["deadline_epoch_utc"]:
        raise RuntimeError("two-hour stage deadline reached")
    ledger = read_bound_json(root / "COST.json")
    costs = ledger["reservations"]
    assert not any(r["output"] == str(output) for r in costs)
    charged = 0
    for r in costs:
        result = Path(r["output"]) / "REPORT.json"
        charged += (
            read_bound_json(result)["physics_steps"]
            if result.exists()
            else r["maximum_steps"]
        )
    if charged + ceiling > 40000 or 18059 + charged + ceiling > 60000:
        raise RuntimeError("finite global step budget exhausted")
    costs.append(
        {
            "output": str(output),
            "maximum_steps": ceiling,
            "reserved_at_epoch_utc": time.time(),
        }
    )
    save(root / "COST.json", ledger)


def project_target(target, previous, lower, upper, max_step):
    candidate = np.asarray(target)
    if not np.isfinite(candidate).all():
        raise ValueError("nonfinite target")
    projected = np.clip(candidate, lower, upper)
    correction = float(np.max(np.abs(projected - candidate)))
    delta = float(np.max(np.abs(projected - np.asarray(previous))))
    if correction > LIMITS["max_raw_target_projection_rad"]:
        raise ValueError("large target range excess")
    if delta > max_step:
        raise ValueError("original target slew rejected")
    return projected, {
        "maximum_projection_rad": correction,
        "maximum_step_rad": delta,
        "projected_joints": np.flatnonzero(projected != candidate).tolist(),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    a = ap.parse_args()
    freeze(a.root, a.parent)
