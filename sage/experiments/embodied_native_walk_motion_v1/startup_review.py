"""Zero-step causal review: open-loop observer falls before policy takeover."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_walk_v1.motion_gate import require_motion_protocol
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    guard_candidate,
)
from sage.experiments.embodied_transport_native_v1.model import load_model


def run(root):
    p = require_motion_protocol(root)
    episode = root / "motion_v1/A/admission"
    r = read_bound_json(episode / "REPORT.json")
    a = read_bound_json(episode / "AUDIT.json")
    t = read_bound_json(episode / "TRACE.json")
    assert r["physics_steps"] == 175 and not any(row["active"] for row in t["records"])
    first = t["records"][0]
    candidate = np.array(first["candidate_rad"])
    m = load_model(r["model"]["path"])
    ids = native._model_ids(__import__("mujoco"), m)
    lo, hi = m.jnt_range[ids["joint_ids"]].T
    idle = np.load(p["reference_base"]["path"], allow_pickle=False)["q"][0, 7:]
    guard = guard_candidate(candidate, idle, lo, hi)
    last = t["records"][-1]["substeps"][-1]
    samples = t["warmup_substeps"] + [
        s for row in t["records"] for s in row["substeps"]
    ]
    result = {
        "schema": "native-startup-causal-review/v1",
        "physics_steps": 0,
        "source_episode_physics_steps": r["physics_steps"],
        "policy_writes_in_failed_run": 0,
        "last_time_s": last["time_after_s"],
        "last_up_component": last["up_component"],
        "last_root_m": last["root_after_m"],
        "maximum_forbidden_contacts": max(s["forbidden_contacts"] for s in samples),
        "maximum_penetration_m": max(s["penetration_m"] for s in samples),
        "first_command_at_s": first["substeps"][0]["time_before_s"],
        "first_policy_command_finite_in_range_and_native_slew": all(
            guard[k] for k in ("finite", "in_range", "step_safe")
        ),
        "first_command_handoff_guard": guard,
        "first_command": candidate.tolist(),
        "audit_pd_error_nm": a["max_pd_error_nm"],
        "audit_contact_error": a["max_contact_error"],
        "cause": "fixed-pose unsupported observer PD tilted forward before any learned balance control was applied; not scene collision, not a policy action that was already executed",
        "next_causal_revision": "same model/cases/reference/PD/limits; use first already range/slew-safe policy command after10warmup ticks, then real100tick controlled standing admission. Longer episodes exactly replay that100tick physical prefix, with no open-loop50tick observer.",
        "first_new_command_safe_is_not_proof_of_dynamic_success": True,
        "report": _file_binding(episode / "REPORT.json"),
        "audit": _file_binding(episode / "AUDIT.json"),
        "implementation": _file_binding(Path(__file__)),
    }
    save(root / "STARTUP_CAUSAL_REVIEW.json", result)
    print(
        {
            "source_steps": 175,
            "first_handoff_guard": guard,
            "next_version_uses_early_actual_NN": True,
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
