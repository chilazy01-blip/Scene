"""Real model/state/43-control verification with zero physics integrations."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import resource
import xml.etree.ElementTree as ET
import numpy as np
from .contract import load_contract
from .commands import CommandFrame
from .runtime import SonicRuntime,NativeDriver
from .wire import pack,unpack
from .planner import PlannerSource
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol_preserved import authorize
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.task_equilibrium import Task
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES,ENCODER_ASSEMBLER
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import initialize_context
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

def verify(root,ledger_root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    assert not (root/'VERIFICATION.json').exists()
    cost_before=sha256_file(ledger_root/'COST.json');p=authorize(ledger_root)
    contract=load_contract();report=read_bound_json(ledger_root/'attempt_17/full/REPORT.json')
    model=load_model(report['model']['path']);data=mujoco.MjData(model)
    driver=NativeDriver(mujoco,model);names=driver.hand['names']
    assert tuple(model.joint(int(j)).name for j in driver.ids['joint_ids'])==contract.body_names
    bounds=np.array([[min(0.,RIGHT_CLOSED.get(n,0.)*.5),max(0.,RIGHT_CLOSED.get(n,0.)*.5)] for n in names])
    driver=NativeDriver(mujoco,model,bounds)
    runtime=SonicRuntime.from_paths(contract,p['inputs']['decoder']['path'],p['inputs']['encoder']['path'])
    trace=read_bound_json(ledger_root/'attempt_17/full/TRACE.json');io=np.load(ledger_root/'attempt_17/full/POLICY_IO.npz',allow_pickle=False)
    rows=[];max_wire_pd=0.
    for tick in (50,355,790,979,1000,1117,1144,1214,1312,1362,1422,1480):
        row=trace['records'][tick];step=row['substeps'][0]
        token=runtime.encode(io['encoder_inputs'][tick])
        hands=np.asarray(step['hand_target_rad'])
        frame=CommandFrame.from_task(contract,token,names,hands,frame_index=tick,observation_time_s=step['time_before_s'],source='recorded_native_task_fixture')
        decoded=runtime.decode(frame,io['decoder_inputs'][tick],names,step['time_before_s'])
        assert np.array_equal(decoded.raw_body,np.asarray(row['raw_sonic_isaaclab'],np.float32)),tick
        assert np.array_equal(decoded.body_target,row['raw_sonic_target_rad']),tick
        assert np.array_equal(decoded.hand_target,hands),tick
        assert np.array_equal(token,io['decoder_inputs'][tick,:64]),tick
        for substep in row['substeps']:
            data.qpos[:]=substep['full_qpos_before'];data.qvel[:]=substep['full_qvel_before'];data.time=substep['time_before_s']
            mujoco.mj_forward(model,data)
            ctrl,body,fingers=driver.torques(data,row['target_rad'],decoded.hand_target)
            assert np.array_equal(ctrl,substep['all_ctrl']),(tick,np.max(np.abs(ctrl-substep['all_ctrl'])))
            # Early frozen prefixes archive all43 ctrl, but predate the extra
            # requested-torque diagnostics. Never manufacture missing evidence.
            if 'body_requested_torque_nm' in substep:assert np.array_equal(body,substep['body_requested_torque_nm'])
            if 'finger_requested_torque_nm' in substep:assert np.array_equal(fingers,substep['finger_requested_torque_nm'])
            wire=unpack(pack(frame,contract),contract,observation_time_s=step['time_before_s'])
            wire_ctrl,_,_=driver.torques(data,row['target_rad'],wire.native_hands(contract,names))
            max_wire_pd=max(max_wire_pd,float(np.max(np.abs(wire_ctrl-ctrl))))
        rows.append(dict(tick=tick,stage=row['stage'],encoder_decoder_bitwise=True,named_hands_bitwise=True,all43_ctrl_bitwise_in_all4_substeps=True))
    assert max_wire_pd<1e-7
    print(dict(real_ONNX_and43PD_samples=len(rows),physics_integrations=0),flush=True)
    # Execute the exact current task provider at its real pre-close checkpoint.
    original=read_bound_json(ledger_root/'attempt_09/full/TRACE.json');original['records']=original['records'][:980]
    reference=np.load(p['reference']['path'],allow_pickle=False);case=read_bound_json(ledger_root/'CASE_EQUILIBRIUM_PREVIEW.json')
    task=Task(mujoco,model,case,reference['q'],reference['v']);actions=np.zeros((2500,29),np.float32)
    info=restore(mujoco,model,data,task,original,actions,lambda:None,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES))
    assert info['prefix_physics_steps']==3960
    qbefore=data.qpos.copy();vbefore=data.qvel.copy()
    task.update(980,data,original['records'][-1]['substeps'][-1]);task.synchronize(980,data)
    current=SonicRuntime(contract,runtime.decoder,runtime.encoder)
    frame=current.task_frame(task,980,data,original['initial_qpos'][3:7],names)
    old_io=np.load(ledger_root/'attempt_09/full/POLICY_IO.npz',allow_pickle=False)
    actual_encoder=np.asarray(ENCODER_ASSEMBLER.assemble(task.reference_blocks(980,data,original['initial_qpos'][3:7])),dtype=np.float32)
    assert np.array_equal(actual_encoder,old_io['encoder_inputs'][980]),float(np.max(np.abs(actual_encoder-old_io['encoder_inputs'][980])))
    decoded=current.decode(frame,old_io['decoder_inputs'][980],names,float(data.time))
    target,_=driver.body_target(decoded,np.asarray(original['records'][-1]['target_rad']))
    ctrl,_,_=driver.torques(data,target,decoded.hand_target)
    assert len(ctrl)==43 and np.isfinite(ctrl).all()
    assert np.array_equal(qbefore,data.qpos) and np.array_equal(vbefore,data.qvel)
    # Range intersection must not let a wider case override original limits.
    driver_wide=NativeDriver(mujoco,model,np.tile([-100.,100.],(14,1)))
    try:driver_wide.torques(data,target,np.ones(14)*99)
    except ValueError:pass
    else:raise AssertionError('case bounds widened original joint limits')
    print(dict(actual_current_task_frame=True,new_physics_steps=0),flush=True)
    planner=PlannerSource(p['inputs']['planner']['path'])
    motion,planner_check=planner.plan(initialize_context(DEFAULT_ANGLES),mode=0)
    assert motion.shape[1]==36 and np.isfinite(motion).all()
    assert PlannerSource.next_context(motion).shape==(1,4,36)
    # Ensure the rollout calls the adapter, rather than merely shipping a utility.
    engine=Path(__file__).with_name('engine.py');tree=ast.parse(engine.read_text())
    calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert {'decode','torques','from_task'}<=calls
    modules=('engine','audit','replay','render','visualize','delivery','protocol','observation')
    for name in modules:__import__(__package__+'.'+name)
    tests=ET.parse(root/'TESTS.xml').getroot();suites=list(tests.iter('testsuite'))
    assert suites and all(int(s.get('failures','0'))==int(s.get('errors','0'))==0 for s in suites)
    assert cost_before==sha256_file(ledger_root/'COST.json')
    result=dict(schema='sonic-command-integration-zero-step-verification/v1',passed=True,new_physics_steps=0,physics_integrations=0,cost_ledger_unchanged=True,tests=sum(int(s.get('tests','0')) for s in suites),sampled_ticks=rows,sampled43PD_substeps=len(rows)*4,maximum_official_float32_wire_PD_difference_nm=max_wire_pd,task_provider=dict(executed=True,checkpoint=info,command=frame.record(),state_unchanged=True,all43_outputs_finite=True),planner=dict(planner_check,real_model_called=True,current_task_uses_online_planner=False),gr00t=dict(client_package_available=importlib.util.find_spec('gr00t') is not None,server_configured=False,task_checkpoint_supplied=False,calibrated_ego_RGB_available=False,live_policy_connected=False),sources={str(f):_file_binding(f) for f in contract.source_files},models=p['inputs'],case=_file_binding(ledger_root/'CASE_EQUILIBRIUM_PREVIEW.json'),recorded_report=_file_binding(ledger_root/'attempt_17/full/REPORT.json'),tests_report=_file_binding(root/'TESTS.xml'),implementation=_file_binding(Path(__file__)),limitations=['Zero-step interface/model/control verification only. No new walking or grasping success is claimed.','GR00T service/checkpoint and calibrated ego camera are not supplied.','The active task keeps its original offline walking reference; optional online replanning has only a model-call check.'])
    safe_save(root/'VERIFICATION.json',result);print(json.dumps(dict(passed=True,tests=result['tests'],real_samples=len(rows),new_physics_steps=0,planner=planner_check)),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--ledger-root',type=Path,required=True);args=parser.parse_args();verify(args.root,args.ledger_root)
