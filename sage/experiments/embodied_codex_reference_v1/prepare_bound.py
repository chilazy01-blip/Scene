"""Fix metadata serialization after the zero-step hash check rejected plain JSON.

Original failed preparations and frozen code stay intact. New arm directories use
the exact same predefined cases and physical/control conditions.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from .bootstrap import ROOT, OLD, PACKAGE
from .prepare import prepare_prefix
from .proposal import validate
from .protocol import read_bound_json, safe_save, _file_binding


def run(folder=None):
    if not (ROOT / "AUTHORIZATION_BOUND.json").exists():
        safe_save(ROOT / "AUTHORIZATION_BOUND.json", json.loads((ROOT / "AUTHORIZATION.json").read_text()))
        safe_save(ROOT / "PLAN_BOUND.json", json.loads((ROOT / "PLAN.json").read_text()))
        safe_save(ROOT / "COST.json", json.loads((ROOT / "COST.json").read_text()))
        safe_save(ROOT / "METADATA_DIAGNOSIS.json", dict(
            failure="ValueError: content hash mismatch: AUTHORIZATION.json",
            evidence_logs=[str(ROOT / "preview_minus_baseline.log"), str(ROOT / "preview_plus_baseline.log")],
            cause="The project's read_bound_json requires a canonical embedded content_sha256_excluding_this_field, while the initial new auth/plan/ledger used plain json.dumps.",
            correction="Preserve failed frozen files; serialize new bound metadata with the existing safe_save and create new versioned arm directories.",
            physical_steps_before_failure=0, changed_physical_or_success_conditions=False))
    plan = read_bound_json(ROOT / "PLAN_BOUND.json")
    auth = read_bound_json(ROOT / "AUTHORIZATION_BOUND.json")
    steps = prepare_prefix(plan); n = plan["common_prefix_active_ticks"]
    prior = read_bound_json(OLD / "trial_07/PROTOCOL.json")
    proposal = None
    if folder is not None:
        invocation = json.loads((ROOT / folder / "INVOCATION.json").read_text())
        assert invocation["model_output_accepted"]
        proposal = validate(invocation["proposal"], json.loads((ROOT / "CONTEXT.json").read_text())["evidence"])
    dependencies = dict(prior["dependencies"])
    dependencies.update({"historical/" + k: v for k, v in prior.get("reused_dependencies", {}).items()})
    dependencies.update({"pilot/" + f.name: _file_binding(f) for f in PACKAGE.glob("*.py")})
    if folder is not None:
        for name in ("RESPONSE.json", "INVOCATION.json"):
            dependencies["proposal/" + name] = _file_binding(ROOT / folder / name)
    source_case = read_bound_json(Path(prior["case"]["path"]))
    prepared = []
    for spec in plan["paired_cases"]:
        for arm in plan["arms"]:
            if folder is None and arm != "baseline": continue
            root = ROOT / spec["case_id"] / (arm + "_v2")
            if (root / "PROTOCOL.json").exists():
                assert arm == "baseline"
                prepared.append(str(root)); continue
            root.mkdir(parents=True, exist_ok=False)
            case = dict(source_case)
            case.update(case_id=spec["case_id"] + "/" + arm,
                target_object_xyz_m=(np.asarray(source_case["target_object_xyz_m"]) + spec["target_delta_m"]).tolist(),
                codex_reference_proposal=proposal if arm == "codex" else None,
                source_role="development_validation", dataset_split="unassigned")
            safe_save(root / "CASE.json", case)
            prefix = ROOT / "prefix"
            p = dict(schema="codex-reference-pilot-protocol/v2", authorization=_file_binding(ROOT / "AUTHORIZATION_BOUND.json"),
                plan=_file_binding(ROOT / "PLAN_BOUND.json"), case=_file_binding(root / "CASE.json"),
                scene=prior["scene"], reference=prior["reference"], inputs=prior["inputs"], dependencies=dependencies,
                source_success_protocol=_file_binding(OLD / "trial_07/PROTOCOL.json"),
                prefix_report=_file_binding(prefix / "REPORT.json"), prefix_trace=_file_binding(prefix / "TRACE.json"),
                prefix_io=_file_binding(prefix / "POLICY_IO.npz"), prefix_active_ticks=n, prefix_physics_steps=steps,
                full_ticks=2200, ledger_root=str(ROOT), prior_native_steps=84564, max_new_physics_steps=52000,
                cumulative_native_cap=136564, deadline_epoch_utc=auth["deadline_epoch_utc"],
                solver_schedule=prior["solver_schedule"], task_module="sage.experiments.embodied_codex_reference_v1.task",
                active_source="codex_reference_timing_proposal/v1" if arm == "codex" else "native_mug_task_expert/baseline_v1",
                arm=arm, paired_case_id=spec["case_id"], all_original_physical_and_task_gates_preserved=True,
                not_independent_scene_or_success_rate_sample=True)
            safe_save(root / "PROTOCOL.json", p); prepared.append(str(root))
    path = ROOT / ("FROZEN_CASES_BOUND.json" if folder else "FROZEN_BASELINES_BOUND.json")
    safe_save(path, dict(prepared=prepared, proposal=proposal, prefix_steps=steps, prefix_ticks=n,
                        new_physics_steps=0, worst_case_four_runs_and_replays=45008))
    print(dict(prepared=prepared, proposal=proposal, prefix_steps=steps), flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--proposal-folder")
    run(ap.parse_args().proposal_folder)
