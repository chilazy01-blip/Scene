"""Exact-time public samples from independently admitted continuous episodes."""
from pathlib import Path
import numpy as np
from .runtime import *
def admitted_source(name):
    if name=='T6':
        folder=LEGACY_K/'results/T6';a=read(LEGACY_K/'delivery/ACCEPTANCE.json')
        physics=read(folder/'INDEPENDENT_PHYSICS/RESULT.json');native=read(folder/'NATIVE_TASK_AUDIT/RESULT.json')
        model=LEGACY_K/'MODEL_NATIVE_CCD.mjb'
        assert a['passed'] and physics['passed'] and native['passed']
    else:
        folder=K/'results'/name;a=read(folder/'ACCEPTANCE.json')
        physics=read(folder/'INDEPENDENT_PHYSICS/RESULT.json');native=read(folder/'NATIVE_TASK_AUDIT/RESULT.json')
        model=Path(read(folder/'METHOD.json')['model_path'])
        assert a['passed'] and physics['passed'] and native['passed']
    trace_hash=digest(folder/'TRACE.npz')
    assert trace_hash==physics['trace_sha256']==native['trace_sha256']
    assert digest(model)==physics['model_sha256']==native['model_sha256']
    result=read(folder/'RESULT.json')
    assert result['completed_task_controller'] and result['failure'] is None and result['mid_episode_state_writes']==0
    return folder,model,dict(trace_sha256=trace_hash,model_sha256=digest(model),physics_audit_sha256=digest(folder/'INDEPENDENT_PHYSICS/RESULT.json'),native_audit_sha256=digest(folder/'NATIVE_TASK_AUDIT/RESULT.json'))
def align(name):
    folder,model,binding=admitted_source(name);trace=np.load(folder/'TRACE.npz')
    c=read(J/'results/B1/CONTRACT.json');qmap=np.array(c['qpos_by_pin'])
    before=trace['before'];after=trace['after'];cmd=trace['commands'];count=len(cmd)
    assert before.shape==after.shape==(count*4,113)
    assert np.array_equal(before[1:],after[:-1])
    assert np.isfinite(before).all() and np.isfinite(after).all() and np.isfinite(cmd).all()
    assert np.allclose(after[:,0]-before[:,0],.005,rtol=0,atol=1e-11)
    assert np.allclose(np.diff(before[::4,0]),.02,rtol=0,atol=1e-11)
    starts=np.arange(0,count,2);indices=starts[:,None]+np.arange(2)[None,:]
    valid=indices<count;bounded=np.minimum(indices,count-1);states=before[4*starts].copy()
    previous=np.zeros((len(starts),43),np.float64);has_previous=starts>0;previous[has_previous]=cmd[starts[has_previous]-1]
    fields=dict(timestamp=states[:,0],command_timestamp=before[4*starts,0],
        joint_position=states[:,1+qmap].astype('f4').astype('f8'),
        joint_velocity=states[:,58+qmap-1].astype('f4').astype('f8'),
        previous_command=previous,action_chunk=cmd[bounded],
        action_timestamps=before[4*bounded,0],action_valid=valid,
        done=np.arange(len(starts))==len(starts)-1,
        base_orientation_wxyz=states[:,4:8].copy())
    assert np.array_equal(fields['action_chunk'][valid],cmd)
    assert np.array_equal(fields['timestamp'],fields['command_timestamp'])
    assert int(valid.sum())==count
    binding.update(source_name=name,source_trial=str(folder),model_path=str(model),commands=count,rows=len(starts),joint_names=c['joint_names'],source_role='accepted_native_single_episode',physics_data_only=True)
    return fields,states,binding
