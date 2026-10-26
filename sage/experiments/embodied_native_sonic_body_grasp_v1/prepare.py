"""Freeze a reviewable trial and the six-hour override without changing old evidence."""
import argparse
from pathlib import Path
from .protocol import read_bound_json,safe_save,_file_binding


def run(root,parent,plan,number):
    result=read_bound_json(plan)
    assert result['eligible'] and result['new_physics_steps']==0
    old=read_bound_json(parent/'INTEGRATION_PROTOCOL.json')
    case=read_bound_json(Path(old['case']['path']))
    names=result['physical_touch_joint_names'];motor=result['quasistatic_motor_allocation']['motor_reference_angles_rad']
    case.update(body_motor_reference_rad=dict(zip(names,motor)),
        equilibrium_physical_touch_rad=dict(zip(names,result['physical_touch_angles_rad'])),
        body_grasp_rotation=result['wrist_rotation'],body_grasp_wrist_goal_m=result['wrist_goal_m'],
        body_min_rim_margin_m=.008,body_max_hover_drift_m_s=.002,
        loaded_native_reference_ratio=float(result.get('reference_ratio',.65)),loaded_reference_extension_after_carry_ticks=40,
        control_regime='Original native physics. Preclose realignment to a planned cup-body opposing grasp; original motor PD/effort and full-task gates. New carry admission requires8mm contact-centroid rim margin and at most2mm/s1s relative drift.')
    trial=root/f'trial_{number:02d}';trial.mkdir(exist_ok=False)
    safe_save(trial/'CASE.json',case)
    auth=read_bound_json(root/'SIX_HOUR_AUTHORIZATION.json')
    dependencies={str(path):_file_binding(path) for path in Path(__file__).parent.glob('*.py')}
    dependencies.update({'reused/'+k:v for k,v in old['dependencies'].items()})
    p=dict(old,case=_file_binding(trial/'CASE.json'),authorization=_file_binding(root/'SIX_HOUR_AUTHORIZATION.json'),
        deadline_epoch_utc=auth['deadline_epoch_utc'],ledger_root=str(root),prior_native_steps=66204,
        cumulative_native_cap=None,max_new_physics_steps=None,full_ticks=3000,
        prefix_active_ticks=980,prefix_physics_steps=3960,
        task_module='sage.experiments.embodied_native_sonic_body_grasp_v1.task_body',
        prefix_report=_file_binding(parent/'equilibrium_prefix/REPORT.json'),
        prefix_trace=_file_binding(parent/'equilibrium_prefix/TRACE.json'),
        prefix_io=_file_binding(parent/'equilibrium_prefix/POLICY_IO.npz'),
        body_plan=_file_binding(plan),dependencies=dependencies,
        old_step_cap_and_failure_count_limits_superseded=True,
        active_source='native_mug_task_expert/body_grasp_v1',
        six_hour_user_instruction=auth['user_instruction_verbatim'])
    safe_save(trial/'PROTOCOL.json',p)
    print(dict(prepared=str(trial),prefix_steps=3960,max_trial_new_steps=8080,deadline_utc=auth['deadline_utc']))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--number',type=int,required=True)
    a=ap.parse_args();run(a.root,a.parent,a.plan,a.number)
