"""Independently repair a pre-790 audit assumption, without reexecuting physics.

Retain the original full NN/PD/contact/state audit verbatim. Independently rebuild
every legal target/projection/history from its NN-verified raw body targets, using
the always-on bounded adapter explicitly bound in the actual engine source.
No acceptance threshold is relaxed. The base audit remains an attached artifact.
"""
import ast
from pathlib import Path
import numpy as np
from .common import check,read_bound_json,safe_save,_file_binding
from .protocol import authorize
from sage.experiments.embodied_native_sonic_transport_v1.rate_adapter import project_target
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab

def run(root):
    import mujoco as mj
    p=authorize(root);episode=root/'full';out=episode/'AUDIT_v2.json'
    assert not out.exists()
    base=read_bound_json(episode/'AUDIT.json');report=read_bound_json(episode/'REPORT.json')
    assert base['report']==_file_binding(episode/'REPORT.json')
    check(base['implementation']);check(report['trace']);check(report['engine']);check(report['model'])
    # Verify the execution condition from frozen source, not a post-hoc choice.
    tree=ast.parse(Path(report['engine']['path']).read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='body_target']
    assert len(calls)==1 and isinstance(calls[0].args[-1],ast.Constant) and calls[0].args[-1].value is True
    trace=read_bound_json(Path(report['trace']['path']));model=load_model(report['model']['path']);ids=native._model_ids(mj,model)
    lo,hi=model.jnt_range[ids['joint_ids']].T
    previous=np.asarray(trace['warmup_substeps'][-1]['body_position_target_rad'])
    saturation=np.zeros(29,dtype=int);maximum=0.;mismatches=[];history_mismatches=[]
    for row in trace['records']:
        mixed=np.asarray(row['raw_sonic_target_rad'])
        target,guard=project_target(mixed,previous,lo,hi,native.MAX_CANDIDATE_STEP_RAD,allow_slew=True)
        saturation=np.where(mixed!=target,saturation+1,0)
        guard['saturation_run_ticks']=saturation.tolist()
        guard['sustained_one_second_joints']=np.flatnonzero(saturation>=50).tolist()
        maximum=max(maximum,float(np.max(np.abs(target-row['target_rad']))))
        if mixed.tolist()!=row['mixed_target_rad'] or target.tolist()!=row['target_rad'] or guard!=row['projection']:mismatches.append(row['tick'])
        action=reorder_mujoco_to_isaaclab((target-np.asarray(DEFAULT_ANGLES))/np.asarray(ACTION_SCALES))
        if not np.array_equal(np.asarray(row['applied_action_isaaclab'],dtype=np.float32),np.asarray(action,dtype=np.float32)):history_mismatches.append(row['tick'])
        previous=target.copy()
    gates=dict(base['gates'])
    gates['actual_mixed_and_projected_targets']=not mismatches and not history_mismatches and maximum==0.
    gates['projection_adapter_condition_verified_from_frozen_execution_source']=True
    passed=all(gates.values())
    result=dict(base)
    result.pop('content_sha256_excluding_this_field',None)
    result.update(schema='native-independent-audit-with-projection-supplement/v2',gates=gates,control_passed=passed,executed_control_reconstruction_passed=all(v for k,v in gates.items() if k!='bounded_complete_episode'),task_passed=passed and report['task_passed'] and all(report['gates'].values()),base_full_independent_audit=_file_binding(episode/'AUDIT.json'),base_gate_replaced='actual_mixed_and_projected_targets',reconstruction_basis='Base audit independently recomputed NN/encoder/decoder, raw transforms, hand/body PD, contact, geometry, state/time chains and policy archive. This supplement independently recomputes all target/projection/history fields using the exact bound always-on adapter. Original base report remains unchanged.',projection_target_maximum_error_rad=maximum,projection_mismatch_ticks=mismatches,projection_history_mismatch_ticks=history_mismatches,projection_ticks=len(trace['records']),new_physics_steps=0,implementation=_file_binding(Path(__file__)))
    safe_save(out,result)
    print(dict(audit=str(out),control_passed=passed,executed_control_reconstruction_passed=result['executed_control_reconstruction_passed'],failed=[k for k,v in gates.items() if not v],projection_error=maximum),flush=True)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True,type=Path);run(ap.parse_args().root)
