"""Bind a measured causal chain, independent checks and exported force plot."""
import argparse,csv,time
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,parent):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    j=read_bound_json(root/'FRICTION_RECONSTRUCTION.json');verify=read_bound_json(root/'INDEPENDENT_FORCE_CHECK.json');step=read_bound_json(root/'ACTUAL_STEP_FORCE_CHECK.json');rows=j['rows'];lift=[a for a in rows if a['stage']=='lift'];start=lift[0]['time_s']-.005
    before=min(rows,key=lambda a:abs(a['time_s']-start));entry=min(lift,key=lambda a:abs(a['time_s']-23.58));cc=[c for a in lift for c in a['contacts'] if c['role'] in ['thumb','index','middle','palm'] and c['normal_n']>.01];fn=sum(c['normal_n'] for c in cc)
    assert j['cone']==0 and all(c['dim']==3 and c['friction'][:2]==[1.,1.] for c in cc)
    original=read_bound_json(parent/'FINAL_REVIEW.json');assert original['cumulative_native_steps']==46402
    out=root/'FORCE_TIMELINE.csv'
    with out.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['time_s','stage','hand_vertical_force_n','hand_vertical_friction_n','hand_vertical_normal_n','desk_vertical_force_n','cup_weight_n','cup_angular_speed_rad_s','cup_wrist_slip_mm'])
        anchor=np.array(before['object_local_to_wrist_m'])
        for a in rows:w.writerow([a['time_s'],a['stage'],a['hand_force_world_n'][2],a['hand_friction_world_n'][2],a['hand_normal_world_n'][2],a['desk_force_world_n'][2],a['weight_n'],a['cup_angular_speed_rad_s'],1000*np.linalg.norm(np.array(a['object_local_to_wrist_m'])-anchor)])
    t=np.array([a['time_s']-start for a in rows]);fig,axs=plt.subplots(3,1,figsize=(10,9),sharex=True)
    for label,key,color in [('hand total','hand_force_world_n','black'),('hand friction','hand_friction_world_n','tab:blue'),('hand normal','hand_normal_world_n','tab:orange'),('desk support','desk_force_world_n','gray')]:
        axs[0].plot(t,[a[key][2] for a in rows],label=label,color=color,linewidth=1)
    axs[0].axhline(entry['weight_n'],color='tab:red',linestyle='--',label='cup weight 1.4715 N');axs[0].set_ylabel('Vertical force (N)');axs[0].legend(ncol=3,fontsize=8);axs[0].set_title('Recorded failed grasp: friction acts, but lifting equilibrium is not established')
    selected=[a for a in rows if a.get('static_capacity_contact_caps',{}).get('eligible')]
    axs[1].plot([a['time_s']-start for a in selected],[a['static_capacity_contact_caps']['maximum_weight_multiple'] for a in selected],'o-',label='observed contact preload caps')
    axs[1].plot([a['time_s']-start for a in selected],[a['static_capacity_group_caps']['maximum_weight_multiple'] for a in selected],'s--',label='optimistic group redistribution')
    axs[1].axhline(1,color='tab:red',linestyle='--');axs[1].set_ylabel('Static load / cup weight');axs[1].legend(fontsize=8)
    slip=[1000*np.linalg.norm(np.array(a['object_local_to_wrist_m'])-anchor) for a in rows];axs[2].plot(t,slip,color='tab:purple',label='cup relative wrist displacement');axs[2].axhline(40,color='tab:red',linestyle='--',label='original slip stop');axs[2].set_ylabel('Relative displacement (mm)');axs[2].set_xlabel('Time since lift transition (s)');axs[2].legend(fontsize=8)
    for ax in axs:ax.axvline(0,color='gray',linestyle=':');ax.grid(alpha=.25)
    fig.text(.01,.005,'Actual saved post-step states; no integrations or parameter changes. LP curves are instantaneous static bounds, not dynamic trials.',fontsize=8)
    fig.tight_layout(rect=(0,.025,1,1));fig.savefig(root/'force_diagnosis.png',dpi=160);plt.close(fig)
    force_samples=sum(c['normal_n'] for c in cc if c['pyramid_utilization']>.95)/fn
    result=dict(schema='native-grasp-friction-root-cause-review/v1',closed_epoch_utc=time.time(),new_physics_steps=0,cumulative_native_steps_unchanged=46402,
        friction_enabled_and_measured=True,actual_contact_dimensions=[3],actual_sliding_friction_coefficients=[1.,1.],pyramidal_cone=True,
        max_observed_contact_tangential_force_n=max(c['tangent_n'] for c in cc),max_contact_sliding_speed_m_s=max(c['tangential_speed_m_s'] for c in cc),
        loaded_contact_normal_weighted_fraction_at_95percent_cone_boundary=force_samples,
        measured_lift_entry=dict(time_s=entry['time_s'],cup_weight_n=entry['weight_n'],hand_vertical_friction_n=entry['hand_friction_world_n'][2],hand_vertical_normal_n=entry['hand_normal_world_n'][2],hand_vertical_total_n=entry['hand_force_world_n'][2],desk_vertical_n=entry['desk_force_world_n'][2],index_vertical_normal_n=entry['groups']['index']['world_force_n'][2]-entry['groups']['index']['world_friction_n'][2],hand_torque_about_com_nm=entry['hand_torque_about_com_nm']),
        accepted_prelift_trigger=dict(time_s=before['time_s'],observed_force_groups=before['groups'],static_capacity_observed_contacts=before['static_capacity_contact_caps'],optimistic_capacity_group_redistribution=before['static_capacity_group_caps']),
        confirmed_software_defect='grip_groups.secure accepts summed scalar finger normal forces without world-force direction, torque balance, slip or load-bearing margin. It accepts index pressing downward on upper cup as useful gripping contact. At accepted trigger, even optimistically redistributed measured group preload supports only0.8714cup weights in static force/torque equilibrium.',
        measured_mechanism='Nonzero tangential friction is present. Downward index normal force cancels upward friction; lateral force and torque remain unbalanced and the desk initially carries cup weight. Cup then rotates/slides through contacts until hand contact disappears. No motor effort saturation in the frozen prior diagnosis.',
        causal_limits='Observed forces and static infeasibility identify an inadequate grasp trigger and insufficient measured loaded wrench margin, not a controlled intervention proving a unique best controller/pose. Does not establish that friction coefficient should be increased or that one global closure gain fixes retention.',
        process_error='Previous work checked symptoms, force magnitudes and motor saturation, but changed references before reconstructing tangent force, friction-cone utilization and force/torque balance. That diagnosis was incomplete.',
        next_change_required='Replace scalar-normal-only ready test with validated loaded-wrench/slip margin; plan contact locations/orientation and preload jointly. Diagnose first, freeze one falsifiable change, and perform a bounded physical counterfactual before claiming a fix. No new controller version was run in this diagnosis.',
        source_freeze_preserved=original['sources'],parent_review=_file_binding(parent/'FINAL_REVIEW.json'),reconstruction=_file_binding(root/'FRICTION_RECONSTRUCTION.json'),independent_check=_file_binding(root/'INDEPENDENT_FORCE_CHECK.json'),tests=_file_binding(root/'CAPACITY_TESTS.xml'),
        actual_step_force_check=_file_binding(root/'ACTUAL_STEP_FORCE_CHECK.json'),
        maximum_recorded_velocity_increment_reconstruction_error_m_s=step['maximum_payload_velocity_prediction_error_m_s'],
        figure=_file_binding(root/'force_diagnosis.png'),csv=_file_binding(root/'FORCE_TIMELINE.csv'),
        references=['https://mujoco.readthedocs.io/en/3.7.0/computation/index.html#contact','https://mujoco.readthedocs.io/en/3.7.0/APIreference/APIfunctions.html#mj-contactforce'],
        sources={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(root/'ROOT_CAUSE_REVIEW.json',result);print(dict(friction_enabled=True,mu=1.,entry_fz=entry['hand_force_world_n'][2],prelift_optimistic_capacity=before['static_capacity_group_caps']['maximum_weight_multiple'],new_physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
