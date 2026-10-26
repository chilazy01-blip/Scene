"""Freeze target variants, shared exact prefix and one pre-outcome Codex proposal."""
import json
from pathlib import Path
import numpy as np

from .bootstrap import ROOT, OLD, PACKAGE
from .proposal import validate
from .protocol import read_bound_json, safe_save, _file_binding


def prepare_prefix(plan):
    prefix = ROOT / "prefix"
    if (prefix / "REPORT.json").exists():
        return read_bound_json(prefix / "REPORT.json")["physics_steps"]
    source = OLD / "trial_07/full"
    parent_report = read_bound_json(source / "REPORT.json")
    assert parent_report["task_passed"] and all(parent_report["gates"].values())
    trace = read_bound_json(source / "TRACE.json")
    n = plan["common_prefix_active_ticks"]
    assert trace["records"][n - 1]["stage"] == "target_stop"
    assert trace["records"][n]["stage"] == "place"
    trace["records"] = trace["records"][:n]
    trace["events"] = [e for e in trace["events"] if e.get("tick", -1) < n]
    trace["rejected_command"] = None
    prefix_steps = len(trace["warmup_substeps"]) + sum(len(row["substeps"]) for row in trace["records"])
    trace["checkpoint_continuation"] = dict(source_trace=_file_binding(source / "TRACE.json"),
        prefix_physics_steps=prefix_steps, prefix_active_ticks=n, prepared_with_zero_integrations=True)
    prefix.mkdir(exist_ok=False)
    safe_save(prefix / "TRACE.json", trace)
    with np.load(source / "POLICY_IO.npz", allow_pickle=False) as io:
        np.savez_compressed(prefix / "POLICY_IO.npz", **{k: io[k][:n] for k in io.files})
    rows = trace["records"]
    assert all(s["safe"] for row in rows for s in row["substeps"])
    safe_save(prefix / "REPORT.json", dict(schema="exact-recorded-safe-prefix/v1",
        physics_steps=prefix_steps, new_physics_steps=0,
        maximum_saturation_run_ticks=np.max([r["projection"]["saturation_run_ticks"] for r in rows], axis=0).tolist(),
        maximum_target_projection_rad=max(r["projection"]["maximum_projection_rad"] for r in rows),
        projected_ticks=sum(bool(r["projection"]["projected_joints"]) for r in rows),
        source_report=_file_binding(source / "REPORT.json"), source_trace=_file_binding(source / "TRACE.json")))
    return prefix_steps


def run(proposal_folder="proposal_01", prefix_only=False, baseline_only=False):
    plan = json.loads((ROOT / "PLAN.json").read_text())
    auth = json.loads((ROOT / "AUTHORIZATION.json").read_text())
    prefix_steps = prepare_prefix(plan)
    if prefix_only:
        print(dict(prefix_prepared=True, prefix_steps=prefix_steps, new_physics_steps=0), flush=True)
        return
    proposal = None
    if not baseline_only:
        invocation = json.loads((ROOT / proposal_folder / "INVOCATION.json").read_text())
        assert invocation["model_output_accepted"], "No synthetic fallback: actual Codex proposal required"
        proposal = validate(invocation["proposal"], json.loads((ROOT / "CONTEXT.json").read_text())["evidence"])
    prior = read_bound_json(OLD / "trial_07/PROTOCOL.json")
    n = plan["common_prefix_active_ticks"]
    prefix = ROOT / "prefix"
    dependencies = dict(prior["dependencies"])
    dependencies.update({"historical/" + k: v for k, v in prior.get("reused_dependencies", {}).items()})
    dependencies.update({"pilot/" + f.name: _file_binding(f) for f in PACKAGE.glob("*.py")})
    if not baseline_only:
        dependencies["proposal_response"] = _file_binding(ROOT / proposal_folder / "RESPONSE.json")
        dependencies["proposal_invocation"] = _file_binding(ROOT / proposal_folder / "INVOCATION.json")
    source_case = read_bound_json(Path(prior["case"]["path"]))
    prepared = []
    for spec in plan["paired_cases"]:
        for arm in plan["arms"]:
            if baseline_only and arm != "baseline":
                continue
            root = ROOT / spec["case_id"] / arm
            if (root / "PROTOCOL.json").exists():
                assert arm == "baseline", "Never replace a frozen assisted case"
                prepared.append(str(root))
                continue
            root.mkdir(parents=True, exist_ok=False)
            case = dict(source_case)
            case.update(case_id=spec["case_id"] + "/" + arm,
                        target_object_xyz_m=(np.array(source_case["target_object_xyz_m"]) + spec["target_delta_m"]).tolist(),
                        codex_reference_proposal=proposal if arm == "codex" else None,
                        source_role="development_validation", dataset_split="unassigned")
            safe_save(root / "CASE.json", case)
            protocol = dict(schema="codex-reference-pilot-protocol/v1", authorization=_file_binding(ROOT / "AUTHORIZATION.json"),
                plan=_file_binding(ROOT / "PLAN.json"), case=_file_binding(root / "CASE.json"),
                source_success_protocol=_file_binding(OLD / "trial_07/PROTOCOL.json"),
                scene=prior["scene"], reference=prior["reference"], inputs=prior["inputs"], dependencies=dependencies,
                prefix_report=_file_binding(prefix / "REPORT.json"), prefix_trace=_file_binding(prefix / "TRACE.json"),
                prefix_io=_file_binding(prefix / "POLICY_IO.npz"), prefix_active_ticks=n, prefix_physics_steps=prefix_steps,
                full_ticks=plan["full_ticks"], ledger_root=str(ROOT), prior_native_steps=84564,
                max_new_physics_steps=auth["max_new_physics_steps"], cumulative_native_cap=84564 + auth["max_new_physics_steps"],
                deadline_epoch_utc=auth["deadline_epoch_utc"], solver_schedule=prior["solver_schedule"],
                task_module="sage.experiments.embodied_codex_reference_v1.task",
                active_source="codex_reference_timing_proposal/v1" if arm == "codex" else "native_mug_task_expert/baseline_v1",
                arm=arm, paired_case_id=spec["case_id"], model_controls_trajectory_references_only=True,
                all_original_physical_and_task_gates_preserved=True, not_independent_scene_or_success_rate_sample=True)
            safe_save(root / "PROTOCOL.json", protocol)
            prepared.append(str(root))
    safe_save(ROOT / ("FROZEN_BASELINES.json" if baseline_only else "FROZEN_CASES.json"), dict(prepared=prepared, proposal=proposal,
        max_suffix_physics_per_run=40 + 4 * plan["full_ticks"] - prefix_steps,
        max_success_replay_per_run=40 + 4 * plan["full_ticks"],
        worst_case_four_runs_and_replays=4 * (2 * (40 + 4 * plan["full_ticks"]) - prefix_steps),
        prefix_steps=prefix_steps, prefix_ticks=n, new_physics_steps=0))
    print(dict(prepared=prepared, prefix_steps=prefix_steps, proposal=proposal), flush=True)


if __name__ == "__main__":
    import argparse, resource, os
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    parser = argparse.ArgumentParser(); parser.add_argument("--proposal-folder", default="proposal_01")
    parser.add_argument("--prefix-only", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args(); run(args.proposal_folder, args.prefix_only, args.baseline_only)
