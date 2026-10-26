"""Summarize actual load test, preserve limitations and repair aliased metadata."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids


def run(root,episode):
    r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');rows=t['records'];timeline=[]
    # Stable names from the frozen original hand_ids function ordering; obtain via model metadata in old diagnosis.
    from sage.experiments.embodied_transport_native_v1.model import load_model
    model=load_model(r['model']['path']);h=hand_ids(model)
    for a in rows[r['checkpoint_continuation']['prefix_active_ticks']:]:
        s=a['substeps'][-1];q=a.get('wrench_quality');gc={}
        for n,v in zip(h['names'],s['hand_target_rad']):
            if n in RIGHT_CLOSED:gc[group(n)]=float(v/RIGHT_CLOSED[n])
        timeline.append(dict(tick=a['tick'],time_s=s['time_after_s'],stage=a['stage'],actual_group_closures=gc,forces=s['forces'],object_m=s['object_m'],object_local_m=s['object_local_m'],wrist_m=a['wrist_position_m'],wrist_reference_m=a['wrist_reference_m'],wrench_quality=q,hand_scene_force_n=s['hand_scene_force_n'],safe=s['safe']))
    qrows=[a for a in timeline if a['wrench_quality'] is not None];caps=[a['wrench_quality']['capacity'].get('maximum_weight_multiple') or 0 for a in qrows]
    sample_indices=sorted(set([0,len(timeline)-1]+[i for i in range(len(timeline)) if timeline[i]['tick']%25==0]))
    x=dict(schema='native-sonic-loaded-grasp-causal-review/v1',report=_file_binding(episode/'REPORT.json'),trace=r['trace'],new_physics_steps=0,actual_new_integration_steps=r['new_physics_steps'],grasp_test_passed=r['grasp_test_passed'],load_probe_passed=r['load_probe_passed'],full_task_passed=r['task_passed'],stop_reason=r['stop_reason'],stage=r['stage'],maximum_observed_static_weight_capacity=max(caps,default=0.),qualified_quality_ticks=sum(a['wrench_quality']['qualified'] for a in qrows),preload_targets_n=read_bound_json(Path(r['case']['path']))['loaded_preload_targets_n'],maximum_actual_group_normal_n={g:max((a['forces'][g] for a in timeline),default=0.) for g in ['thumb','index','middle']},samples=[timeline[i] for i in sample_indices],all_actual_steps_physical_safe=all(s['safe'] for row in rows for s in row['substeps']),metadata_correction='engine row.group_closures and quality event.group_closures retain mutable Python dict references, so they may show final values. Actual immutable per-substep hand_target_rad and all43ctrl are authoritative. actual_group_closures here are reconstructed from recorded hand targets, and independently causal-audited. Wrench snapshots and physical controls are not affected.',limitation='Static margin is an optimistic instantaneous equilibrium bound; real10mm load transfer and1s off-table hold are separately required. A failed or unexecuted probe is not successful grasp.',implementation=_file_binding(Path(__file__)))
    safe_save(episode.parent/'CAUSAL_REVIEW.json',x)
    safe_save(episode.parent/'FINGER_REFERENCE_TIMELINE.json',dict(rows=timeline,source_trace=r['trace'],new_physics_steps=0))
    print({k:x[k] for k in ['stop_reason','stage','grasp_test_passed','load_probe_passed','maximum_observed_static_weight_capacity','qualified_quality_ticks','maximum_actual_group_normal_n']},flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--episode',type=Path,required=True);a=p.parse_args();run(a.root,a.episode)
