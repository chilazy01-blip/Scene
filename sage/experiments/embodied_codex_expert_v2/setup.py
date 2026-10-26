"""Create a fresh bounded round and a writable expert workbench, never old outputs."""
import json
from pathlib import Path
import shutil
import time
from .common import ROOT,PREVIOUS,ORIGINAL,PACKAGE,safe_save,read_bound_json,_file_binding,check


def run():
    ROOT.mkdir(parents=True,exist_ok=False)
    now=time.time()
    prior=read_bound_json(PREVIOUS/'PAIRED_REVIEW.json')
    assert prior['paired_trial_complete'] and prior['cumulative_native_steps']==91644
    for binding in [prior['report'],*prior['source_files'].values()]:check(binding)
    auth=dict(schema='codex-expert-round-authorization/v1',user_instruction_verbatim='那就按照这个思路去执行下一轮',
        preceding_authorization='Expand Codex to read failure evidence, generate/modify expert policy code and call planning/simulation tools; keep physical model, motor capability, low-level control and final acceptance fixed.',
        user_authorized_expert_code_and_tools=True,user_authorized_project_context_and_expert_sources_for_codex=True,
        recorded_epoch_utc=now,deadline_epoch_utc=now+10800,max_new_physics_steps=64000,prior_native_steps=91644,
        resource_limits=dict(memory_gib_per_process=16,cpu_affinity_first_available=8,blas_threads=1),
        budget_origin='New finite three-hour round declared under the new user instruction, not a revival of the expired previous window.')
    safe_save(ROOT/'AUTHORIZATION.json',auth)
    plan=dict(schema='codex-expert-round-plan/v1',bottleneck='Timing-only references do not ensure stable cup-pose/support transfer for small target changes.',
        objective='Let an actual Codex agent inspect measured failures, write expert strategy code, use controlled tools and validate one frozen strategy on two target variants plus the original success regression.',
        cases={'target_y_minus_30mm':[-.0,-.03,0.],'target_y_plus_30mm':[0.,.03,0.],'original_regression':[0.,0.,0.]},
        development_cases=['target_y_minus_30mm','target_y_plus_30mm'],regression_case='original_regression',
        prefix_active_ticks=1597,prefix_physics_steps=6428,full_ticks=2800,
        freedoms=['Cartesian wrist positions and orientations','piecewise reference paths','native finger position reference schedules','state-feedback phase transitions','bounded recovery and planning code'],
        fixed=['native model/geometry/mass150g/friction/PD/effort/joint limits','SONIC29 body actuation and native14handPD','NoSlip0->3 at3960','original full-task eight gates','final cup upright cosine>=.98'],
        scientific_scope='Development adaptation in one scene with shared proven pickup/carry prefix; not a heldout or independent-success-rate claim.',
        prior_review=_file_binding(PREVIOUS/'PAIRED_REVIEW.json'),prior_native_steps=91644,max_new_physics_steps=64000,
        deadline_epoch_utc=auth['deadline_epoch_utc'],
        exit='Complete the fixed final three-case validation/reviews or the actual finite physics/time budget. Every failure needs evidence before a correction; version count is not an exit. No blind parameter sweep.',
        success_export_requires=['all original gates','upright quality','independent NN/PD/contact audit','original-init all43ctrl continuous replay','force reconstruction','real video decode and main-agent keyframe review'])
    safe_save(ROOT/'PLAN.json',plan)
    safe_save(ROOT/'COST.json',dict(prior_native_steps=91644,max_new_physics_steps=64000,reservations=[]))
    bench=ROOT/'workbench';(bench/'strategies').mkdir(parents=True);(bench/'inbox').mkdir();(bench/'outbox').mkdir();context=bench/'context';context.mkdir()
    for src,name in [(PREVIOUS/'TIMING_COMPARISON.json','timing_comparison.json'),
        (PREVIOUS/'ASSISTED_RELEASE_SUPPORT_DIAGNOSIS.json','release_support.json'),
        (PREVIOUS/'PROPOSAL_REVIEW.json','previous_model_proposal.json'),
        (Path('/data/wsj/main/scene/docs/CODEX_REFERENCE_RESULTS_20261025.md'),'previous_results.md'),
        (PREVIOUS/'target_y_minus_30mm/codex_v2/placement_detail/review.jpg','failed_minus.jpg'),
        (PREVIOUS/'target_y_plus_30mm/codex_v2/placement_detail/review.jpg','failed_plus.jpg'),
        (ORIGINAL/'trial_07/grasp_detail/review.jpg','original_success_grasp.jpg')]:
        shutil.copyfile(src,context/name)
    shutil.copyfile(ROOT/'PLAN.json',context/'round_plan.json')
    old=PACKAGE.parent/'embodied_codex_reference_v1'
    mapping={'engine.py':'engine.py','audit.py':'audit.py','replay.py':'replay.py','preview.py':'preview.py',
             'force.py':'force.py','delivery.py':'delivery.py','visualize.py':'visualize.py','review.py':'review.py'}
    provenance={}
    for target,source in mapping.items():
        text=(old/source).read_text()
        text=text.replace('assert p[\'prior_native_steps\'] == 84564','assert p[\'prior_native_steps\'] == 91644')
        if target=='review.py':text=text.replace('from .bootstrap import ROOT','from .common import ROOT')
        if target=='visualize.py':
            old_loop='''        for i, s in enumerate(states):
            rgb = render(
                s["full_qpos_after"],
                s["time_after_s"],
                s["stage"],
                diagnostic=diagnostic,
            )'''
            new_loop='''        prefix_frames=p["prefix_physics_steps"]//4
        source_video=Path(p["prefix_video"]["path"])
        from .common import check
        check(p["prefix_video"])
        prefix_trace=read_bound_json(Path(p["prefix_trace"]["path"]))
        assert trace["records"][:p["prefix_active_ticks"]]==prefix_trace["records"]
        old_video=av.open(str(source_video));old_frames=iter(old_video.decode(video=0))
        for i, s in enumerate(states):
            if i<prefix_frames:
                rgb=next(old_frames).to_ndarray(format="rgb24")
                if i+1==prefix_frames:old_video.close()
            else:
                rgb=render(s["full_qpos_after"],s["time_after_s"],s["stage"],diagnostic=diagnostic)'''
            assert old_loop in text;text=text.replace(old_loop,new_loop)
            text=text.replace('"static_only": episode is None,','"static_only": episode is None,\n            "reused_actual_prefix_video_frames": 0 if episode is None else prefix_frames,\n            "prefix_source_video": None if episode is None else p["prefix_video"],\n            "prefix_state_equality_checked": episode is not None,')
        (PACKAGE/target).write_text(text)
        provenance[target]=dict(source=_file_binding(old/source),copy=_file_binding(PACKAGE/target),changes='Fresh code-loading protocol/accounting; renderer reuses the byte-verified actual common prefix frames, and renders every new suffix state.')
    safe_save(ROOT/'RUNNER_PROVENANCE.json',provenance)
    print(dict(root=str(ROOT),deadline_epoch_utc=auth['deadline_epoch_utc'],prior=91644,physics_cap=64000),flush=True)


if __name__=='__main__':run()
