"""Freeze only the one causal early-feedback revision; no new model or case."""

import argparse
from pathlib import Path
from copy import deepcopy
from . import engine, audit, attempt, protocol, reference, metrics
from sage.experiments.embodied_native_walk_v1.motion_gate import (
    require_motion_protocol as master,
)
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root):
    old = master(root)
    if (root / "REVISION_02_PROTOCOL.json").exists():
        raise FileExistsError("revision already frozen")
    cause = read_bound_json(root / "STARTUP_CAUSAL_REVIEW.json")
    prior = read_bound_json(root / "motion_v1/RESULT.json")
    assert (
        cause["first_policy_command_finite_in_range_and_native_slew"]
        and not prior["task_passed"]
        and prior["physics_steps"] == 175
    )
    first = read_bound_json(root / "motion_v1/A/admission/TRACE.json")["records"][0]
    p = deepcopy(old)
    p.update(
        schema="native-early-feedback-revision/v2",
        version=2,
        parent=_file_binding(root / "MOTION_PROTOCOL.json"),
        causal_review=_file_binding(root / "STARTUP_CAUSAL_REVIEW.json"),
        prior_outcome=_file_binding(root / "motion_v1/RESULT.json"),
        prior_physics_steps=prior["physics_steps"],
        startup="unchanged10tick warmup, then original NN29 feedback from first tick; actual100tick NN-controlled admission; no open-loop50/100tick observer",
        first_A_command={
            "encoder_input_sha256": first["encoder_input_sha256"],
            "decoder_input_sha256": first["decoder_input_sha256"],
            "candidate_rad": first["candidate_rad"],
            "full_qpos_before": first["substeps"][0]["full_qpos_before"],
            "full_qvel_before": first["substeps"][0]["full_qvel_before"],
        },
        finite_exit="second and last causal controller; preserve all limits/model/cases/goal; no repeated failed case; total master budget includes175prior steps",
        implementation=_file_binding(Path(__file__)),
    )
    for f in sorted(Path(__file__).parent.glob("*.py")):
        if not f.name.startswith("test"):
            p["dependencies"][str(f)] = _file_binding(f)
    p["dependencies"]["data:startup_cause"] = _file_binding(
        root / "STARTUP_CAUSAL_REVIEW.json"
    )
    p["dependencies"]["data:prior_result"] = _file_binding(
        root / "motion_v1/RESULT.json"
    )
    p["dependencies"]["data:revision_contract_tests"] = _file_binding(
        root / "REVISION_02_CONTRACT_TESTS.xml"
    )
    save(root / "REVISION_02_PROTOCOL.json", p)
    protocol.require_motion_protocol(root)
    print(
        {
            "revision": 2,
            "same_model_limits_cases_reference": True,
            "prior_physics_steps": 175,
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    prepare(p.parse_args().root)
