"""Locate the recorded grip's rim contact and its loss, without any integration."""
import argparse
import os
import resource
from pathlib import Path
import numpy as np

from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model


def run(root, output):
    import mujoco as mj
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    destination=output/'RIM_CONTACT_EVIDENCE.json'
    assert not destination.exists()
    report=read_bound_json(root/'attempt_28/full/REPORT.json')
    trace=read_bound_json(root/'attempt_28/full/TRACE.json')
    forces=read_bound_json(root/'attempt_28/FORCE_CHECK.json')
    case=read_bound_json(Path(report['case']['path']))
    model=load_model(report['model']['path'])
    ledger=Path(read_bound_json(root/'INTEGRATION_PROTOCOL.json')['ledger_root'])/'COST.json'
    before=_file_binding(ledger)
    top=float(np.max(case['mug_local_bounds_corners'],axis=0)[2])
    frames=[]
    for tick in [1250,1300,1360,1430,1460,1465]:
        row=next(row for row in forces['rows'] if row['tick']==tick)
        state=trace['records'][tick-1]['substeps'][-1]
        R=np.asarray(state['object_rotation']).reshape(3,3)
        origin=np.asarray(state['object_m']);axis=R[:,2]
        groups={}
        for role in ('thumb','index','middle'):
            cc=[c for c in row['forensic']['contacts'] if c['role']==role and c['normal_n']>.01]
            points=np.array([(np.array(c['position_m'])-origin)@R for c in cc])
            weights=np.array([c['normal_n'] for c in cc])
            max_axial=[];normal_axial=[]
            for c in cc:
                D=np.asarray(c['frame']).reshape(3,3)
                u,v=c['friction'][:2];sign=c['object_sign']
                rays=sign*np.array([[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]])@D
                maximum=float(np.max(rays@axis));max_axial.append(maximum)
                normal_axial.append(float(sign*D[0]@axis))
                actual=float(np.asarray(c['world_force_on_cup_n'])@axis)
                assert actual<=c['normal_n']*maximum+1e-8
            centroid=np.average(points,weights=weights,axis=0)
            groups[role]=dict(contact_count=len(cc),normal_sum_n=float(sum(weights)),
                points_in_cup_m=points.tolist(),normals_n=weights.tolist(),
                centroid_in_cup_m=centroid.tolist(),
                centroid_distance_below_cup_top_m=float(top-centroid[2]),
                weighted_normal_axial_component=float(np.average(normal_axial,weights=weights)),
                maximum_axial_force_per_observed_normal=float(np.average(max_axial,weights=weights)),
                all_contact_friction_rays_axially_downward=bool(all(value<0 for value in max_axial)))
        frames.append(dict(tick=tick,source_stage=state['stage'],time_s=state['time_after_s'],
            cup_axis_world=axis.tolist(),object_local_to_wrist_m=state['object_local_m'],
            capacity_weight_multiple=row['forensic']['static_capacity_contact_caps']['maximum_weight_multiple'],
            measured_maximum_contact_slip_m_s=max(c['tangential_speed_m_s'] for c in row['forensic']['contacts'] if c['role'] in groups),
            groups=groups))
    loss=[]
    for row in trace['records'][1463:1470]:
        for substep,state in enumerate(row['substeps']):
            loss.append(dict(active_tick=row['tick'],substep=substep,time_s=state['time_after_s'],
                forces_n={g:state['forces'][g] for g in ('thumb','index','middle')},
                opposing=state['opposing']))
    first=next(item for item in loss if item['forces_n']['thumb']<1e-5)
    all_lost=next(item for item in loss if max(item['forces_n'].values())<1e-5)
    assert first['time_s']<all_lost['time_s'] and first['forces_n']['index']>0 and first['forces_n']['middle']>0
    hover=next(event for event in report['events'] if event.get('kind')=='loaded_hover_passed')
    frame=next(frame for frame in frames if frame['tick']==hover['tick'])
    assert frame['tick']==1300 and frame['source_stage']=='loaded_hover'
    assert 0<frame['groups']['thumb']['centroid_distance_below_cup_top_m']<.0015
    assert frames[-1]['groups']['thumb']['all_contact_friction_rays_axially_downward']
    # Exact rigid-flex vertices, used only to draw the original cup in its own frame.
    flex=mj.mj_name2id(model,mj.mjtObj.mjOBJ_FLEX,'payload_surface')
    start=int(model.flex_vertadr[flex]);count=int(model.flex_vertnum[flex])
    vertices=np.asarray(model.flex_vert[start:start+count])*1000
    assert np.max(np.abs(np.max(vertices,axis=0)-np.max(case['mug_local_bounds_corners'],axis=0)*1000))<1e-7
    colors=dict(thumb='#d62728',index='#1f77b4',middle='#2ca02c')
    fig,axes=plt.subplots(2,2,figsize=(11,10))
    for col,tick in enumerate([1300,1465]):
        f=next(frame for frame in frames if frame['tick']==tick)
        for line in range(2):
            ax=axes[line,col]
            ax.scatter(vertices[:,1],vertices[:,2],s=.15,c='#888888',alpha=.15,rasterized=True)
            ax.axhline(top*1000,color='black',ls='--',lw=1,label='cup top, 55 mm')
            for role,g in f['groups'].items():
                points=np.asarray(g['points_in_cup_m'])*1000
                ax.scatter(points[:,1],points[:,2],s=18,c=colors[role],label=role,zorder=4)
            ax.set_xlabel('Cup-local y (mm)');ax.set_ylabel('Cup-local z (mm)')
            ax.grid(alpha=.2)
            if line==0:
                ax.set_xlim(-53,53);ax.set_ylim(-60,61);ax.set_aspect('equal')
                ax.set_title(f'tick {tick}: '+('hover admitted' if tick==1300 else 'before loss'))
                ax.legend(loc='lower right',fontsize=8)
            else:
                ax.set_xlim(34,46);ax.set_ylim(49,57);ax.set_aspect('equal')
                ax.set_title('Thumb / rim close-up; centroid z = '+f"{f['groups']['thumb']['centroid_in_cup_m'][2]*1000:.2f} mm")
    fig.suptitle('Recorded physical contact points on original cup; no new simulation',fontsize=12)
    fig.tight_layout();fig.savefig(output/'RIM_CONTACTS.png',dpi=160);plt.close(fig)
    assert before==_file_binding(ledger)
    result=dict(schema='native-grasp-rim-loss-forensics/v1',new_physics_steps=0,
        source_report=_file_binding(root/'attempt_28/full/REPORT.json'),source_trace=report['trace'],
        source_force_check=_file_binding(root/'attempt_28/FORCE_CHECK.json'),case=report['case'],model=report['model'],
        mechanism_comparison=_file_binding(output/'RECORDED_STATE_MECHANISM.json'),
        implementation=_file_binding(Path(__file__)),ledger_unchanged=before,
        cup_top_local_z_m=top,rigid_original_mesh=True,hover_admission_event=hover,
        admission_contacts_speed_limit_m_s=.02,admission_relative_translation_limit_m=.015,
        admission_consecutive_ready_ticks=50,policy_hz=50,
        first_thumb_loss=first,first_all_fingers_loss=all_lost,
        time_between_thumb_loss_and_all_loss_s=all_lost['time_s']-first['time_s'],
        frames=frames,final_substeps=loss,plot=_file_binding(output/'RIM_CONTACTS.png'),
        conclusion='The admitted grasp loads the upper rim with about1.24mm centroid margin. Recorded slow slip migrates the thumb contact across that rim; all remaining thumb friction rays push down the cup axis at1465. Thumb load disappears first, then all opposition collapses10ms later. Soft-contact drift contributes before walking; this is not absence of friction or motor effort clipping.',
        limitations='Rim margin is a geometric centroid measurement, not an allowed translation distance or a global stability certificate. Solver counterfactuals are instantaneous, not a validated repaired task. Do not change original acceptance or physical settings silently.')
    safe_save(destination,result)
    print(dict(saved=str(destination),hover_thumb_margin_mm=frame['groups']['thumb']['centroid_distance_below_cup_top_m']*1000,
        first_thumb_loss_s=first['time_s'],all_loss_s=all_lost['time_s'],new_physics_steps=0),flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();run(args.root,args.output)
