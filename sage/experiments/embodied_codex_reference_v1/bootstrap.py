"""Prepare a small paired pilot and provenance-preserving copies of frozen runners."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .proposal import invoke

OLD = Path("/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_body_grasp_20261025_v1")
ROOT = Path("/data/wsj/main/scene_runs/codex_trellis_v2/embodied_codex_reference_20261025_v1")
PACKAGE = Path(__file__).parent


def begin():
    ROOT.mkdir(parents=True, exist_ok=False)
    start = time.time()
    auth = dict(schema="codex-reference-pilot-authorization/v1", user_authorized_trial=True,
                user_instruction_verbatim="那就按照这个沦陷去做尝试？",
                instruction_interpretation="Try the just-discussed Codex-assisted reference workflow.",
                prior_native_steps=84564, max_new_physics_steps=52000,
                started_epoch_utc=start, deadline_epoch_utc=start + 7200,
                budget_origin="Agent-declared finite pilot scope under the current user trial instruction; no reuse of the expired six-hour authorization.",
                resource_limits=dict(memory_gib_per_process=16, cpu_affinity_first_available=8, blas_threads=1))
    (ROOT / "AUTHORIZATION.json").write_text(json.dumps(auth, indent=2) + "\n")
    plan = dict(schema="codex-reference-pilot-plan/v1", stage="development_validation",
                bottleneck="The prepared expert has case-specific references; test a constrained Codex proposal interface and its real physical effects.",
                paired_cases=[dict(case_id="target_y_minus_30mm", target_delta_m=[0., -.03, 0.]),
                              dict(case_id="target_y_plus_30mm", target_delta_m=[0., .03, 0.])],
                arms=["baseline", "codex"], fixed_before_outcomes=True,
                common_prefix_active_ticks=1597, full_ticks=2200,
                proposal_controls=["place_duration_ticks", "retract_duration_ticks"],
                invariant="Same native geometry/mass/friction/PD/effort/limits, NoSlip0->3 at3960, SONIC29/hand14, full task gates and safe stand handoff.",
                comparison_metrics=["complete_task_pass", "final_root_speed_margin", "goal_error", "cup_upright", "held_slip", "elapsed_time", "new_physics_cost", "model_usage"],
                scope="Two target variants in one native scene with a shared proven pickup/carry prefix; not independently sampled scenes, heldout testing or a success-rate estimate.",
                positive_export_requires=["full_original_gates", "independent_audit", "original_init_full43ctrl_replay", "force_reconstruction", "video_decode", "keyframe_visual_review"],
                max_new_physics_steps=52000, wall_limit_s=7200,
                exit_conditions="Complete the fixed paired pilot and reviews, or reach the real resource/time bound. Diagnose each failure before any revision; no blind sweeps. Engineering repairs remain allowed and recorded.",
                reusable_deliverable="Structured proposal caller, bounded validator, reference compiler, paired runner and evidence report; generator interface remains a subsequent extension.")
    (ROOT / "PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    context = dict(task="full-body native G1 cup transport; improve place/retract reference timing",
                   control_hz=50, physics_hz=200,
                   cases=plan["paired_cases"],
                   baseline=dict(place_duration_ticks=65, retract_duration_ticks=40,
                                 final_root_speed_max_m_s=.05931957, final_root_speed_limit_m_s=.06,
                                 goal_error_m=.02282128, final_cup_up=.99978145),
                   evidence={
                       "E1": "Certified trial07 completed the original complete task. Final200 physics samples max root speed .05931957m/s, leaving .00068043m/s margin below .06. This is one trajectory, not proof of robustness.",
                       "E2": "Place uses previous desired wrist origin, goal = target cup position minus grasp_R times measured cup-in-wrist offset. Duration65 ticks, quintic interpolation. Stage ends only after real pose error, table support and20 ready ticks.",
                       "E3": "After a60tick release and10tick observation, retract goal is measured wrist position+[-.15,0,.08]m, previous desired reference origin, duration40ticks, quintic interpolation. The actual retract phase in trial07 lasted83ticks due to tracking.",
                       "E4": "Quintic interpolation has peak translational speed1.875*distance/duration_seconds; increasing duration reduces commanded peak speed/acceleration but consumes time and may prolong physical drift. Path changes do not directly prescribe actual robot motion.",
                       "E5": "Only after safe actual hand retraction does the established stand handoff remove world wrist/head targets. Stand lower-body references use original stand pose, upper-body uses actual joint angles, reference velocities zero. Preserve this handoff and original stable1second gates.",
                       "E6": "Codex durations must be integers: place65..110,retract40..100ticks. Existing stage timeouts place300/retract200 are unchanged. Geometry, contacts, NoSlip schedule, motor gains and release logic are fixed. Existing pre-place prefix ends before tick1597 and is identical in both arms.",
                   })
    (ROOT / "CONTEXT.json").write_text(json.dumps(context, indent=2) + "\n")
    (ROOT / "COST.json").write_text(json.dumps(dict(prior_native_steps=84564, max_new_physics_steps=52000, reservations=[]), indent=2) + "\n")
    print(dict(prepared=str(ROOT), started_utc=datetime.fromtimestamp(start, timezone.utc).isoformat()), flush=True)


def copy_runners():
    old = PACKAGE.parent / "embodied_native_sonic_body_grasp_v1"
    mapping = {"engine.py": "engine_scheduled.py", "audit.py": "audit_calibrated.py",
               "replay.py": "replay_calibrated_locked.py", "preview.py": "preview_scheduled.py",
               "visualize.py": "visualize.py", "render.py": "render.py",
               "force.py": "force_reconcile.py", "delivery.py": "delivery.py"}
    provenance = {}
    import hashlib
    for target, source in mapping.items():
        text = (old / source).read_text()
        text = text.replace("from .protocol_locked import", "from .protocol import")
        text = text.replace("from .solver_schedule import", "from sage.experiments.embodied_native_sonic_body_grasp_v1.solver_schedule import")
        text = text.replace("from .restore_scheduled import", "from sage.experiments.embodied_native_sonic_body_grasp_v1.restore_scheduled import")
        text = text.replace('source="native_mug_task_expert/body_grasp_v1"', 'source=p["active_source"]')
        text = text.replace('command.source == "native_mug_task_expert/body_grasp_v1"', 'command.source == p["active_source"]')
        text = text.replace("assert p['prior_native_steps'] == 66204  # Six-hour user authorization supersedes old numeric cap.", "assert p['prior_native_steps'] == 84564  # Fresh pilot ledger continues the certified history.")
        if (PACKAGE / target).exists():
            raise FileExistsError(PACKAGE / target)
        (PACKAGE / target).write_text(text)
        provenance[target] = dict(source=str(old / source), source_sha256=hashlib.sha256((old / source).read_bytes()).hexdigest(),
                                  destination_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                  changes="Fresh authorization/accounting imports and source identity; solver/restore reuse, task/control/acceptance logic preserved.")
    (ROOT / "RUNNER_PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("action", choices=["begin", "copy", "propose"]); p.add_argument("--attempt", default="proposal_01")
    a = p.parse_args()
    if a.action == "begin": begin()
    elif a.action == "copy": copy_runners()
    else:
        r = invoke(json.loads((ROOT / "CONTEXT.json").read_text()), ROOT / a.attempt)
        print(json.dumps(r, ensure_ascii=False), flush=True)
