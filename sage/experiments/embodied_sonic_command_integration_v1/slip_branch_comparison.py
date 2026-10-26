"""Compare the shared prewalk grasp and terminal contact geometry in saved branches."""
import argparse
import os
import resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save


def run(root, output):
    destination=output/'BRANCH_CONTACT_COMPARISON.json'
    assert not destination.exists()
    reference=None;branches=[]
    for number in [21,22,24,25,26,27,28]:
        folder=root/f'attempt_{number}'
        force=read_bound_json(folder/'FORCE_CHECK.json')
        hover=next(row for row in force['rows'] if row['tick']==1300)['forensic']
        if reference is None:reference=hover
        assert hover==reference
        report=read_bound_json(folder/'full/REPORT.json')
        case=read_bound_json(Path(report['case']['path']))
        trace=read_bound_json(folder/'full/TRACE.json')
        loaded=[row for row in force['rows'] if row['stage'] in ['carry','target_stop'] and row['forensic']['groups']['thumb']['normal_n']>.01]
        last=loaded[-1];s=trace['records'][last['tick']-1]['substeps'][-1]
        R=np.asarray(s['object_rotation']).reshape(3,3);origin=np.array(s['object_m'])
        cc=[c for c in last['forensic']['contacts'] if c['role']=='thumb' and c['normal_n']>.01]
        points=np.array([(np.array(c['position_m'])-origin)@R for c in cc]);weights=np.array([c['normal_n'] for c in cc])
        centroid=np.average(points,weights=weights,axis=0)
        losses=[]
        for row in trace['records'][max(0,len(trace['records'])-12):]:
            for substep,state in enumerate(row['substeps']):
                if min(state['forces'][g] for g in ['thumb','index','middle'])<1e-5:
                    losses.append(dict(tick=row['tick'],substep=substep,time_s=state['time_after_s'],
                        forces_n={g:state['forces'][g] for g in ['thumb','index','middle']}))
        item=dict(number=number,report=_file_binding(folder/'full/REPORT.json'),trace=report['trace'],
            force=_file_binding(folder/'FORCE_CHECK.json'),same_hover_physics=True,
            last_sampled_thumb_loaded_tick=last['tick'],
            last_sampled_thumb_centroid_cup_m=centroid.tolist(),
            last_sampled_thumb_margin_below_top_m=float(np.max(case['mug_local_bounds_corners'],axis=0)[2]-centroid[2]),
            first_terminal_finger_loss=losses[0] if losses else None,
            stage=report['stage'],stop_reason=report['stop_reason'])
        branches.append(item);print(item,flush=True)
        del trace
    safe_save(destination,dict(schema='native-slip-branch-contact-comparison/v1',new_physics_steps=0,
        implementation=_file_binding(Path(__file__)),all_seven_branches_share_exact_hover_forensics=True,
        branches=branches,limitation='The last quality sample is100ms spaced; the recorded substep loss uses5ms states. Shared grasp ancestry is not seven independent trials.'))


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();run(args.root,args.output)
