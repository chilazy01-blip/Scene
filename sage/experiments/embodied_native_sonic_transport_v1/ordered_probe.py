"""Reproduce the refused mode1 command from the exact saved physical/controller state."""
import argparse
from pathlib import Path
import numpy as np
from .task_ordered import Task
from .restore import restore
from .rate_adapter import project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES,ENCODER_ASSEMBLER,DECODER_ASSEMBLER,body_joint_target_from_raw_action
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import official_decoder_blocks,last_action_rows
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import _make_session
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=read_bound_json(root/'PROTOCOL.json');case=read_bound_json(root/'CASE_V4.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(root/'version_04/full/TRACE.json')
    model=load_model(scene['model']['path']);model.opt.timestep=.005;data=mujoco.MjData(model)
    ids=native._model_ids(mujoco,model);base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,model,case,base['q'],base['v'])
    actions=np.zeros((2210,29),dtype=np.float32);positions=[];velocities=[];quats=[];gyros=[]
    def history():
        positions.append(data.qpos[ids['qpos_ids']].copy());velocities.append(data.qvel[ids['dof_ids']].copy());quats.append(data.qpos[3:7].copy())
        gyro=np.zeros(6);mujoco.mj_objectVelocity(model,data,mujoco.mjtObj.mjOBJ_BODY,model.body('pelvis').id,gyro,1);gyros.append(gyro[:3].copy())
    info=restore(mujoco,model,data,task,t,actions,history,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES))
    tick=info['prefix_active_ticks'];task.update(tick,data,t['records'][-1]['substeps'][-1]);task.synchronize(tick,data);history()
    enc=np.array([ENCODER_ASSEMBLER.assemble(task.reference_blocks(tick,data,np.array(t['initial_qpos'])[3:7]))],dtype=np.float32)
    encoder=_make_session(Path(p['inputs']['encoder']['path']));decoder=_make_session(Path(p['inputs']['decoder']['path']))
    token=encoder.run(None,{encoder.get_inputs()[0].name:enc})[0]
    dec=np.array([DECODER_ASSEMBLER.assemble(official_decoder_blocks(native._mapping_inputs(positions,velocities,quats,gyros),tick+10,token,last_action_rows(actions,tick+10,legacy=False)))],dtype=np.float32)
    raw=decoder.run(None,{decoder.get_inputs()[0].name:dec})[0].reshape(29)
    prior_raw=np.asarray(t['rejected_command']['raw'],dtype=np.float32)
    assert not np.array_equal(raw,prior_raw)
    target=np.asarray(body_joint_target_from_raw_action(raw,phase='native_mug_transport',sim_time_s=data.time).position_target_rad)
    lower,upper=model.jnt_range[ids['joint_ids']].T
    limited,guard=project_target(target,t['records'][-1]['target_rad'],lower,upper,native.MAX_CANDIDATE_STEP_RAD,True)
    safe_save(root/'ORDERED_INTERFACE_PROBE.json',dict(**info,new_physics_steps=0,corrected_lower_order=True,old_refused_command_differs=True,raw_action=raw.tolist(),old_raw_action=prior_raw.tolist(),target_rad=target.tolist(),maximum_requested_target_delta_rad=float(np.max(np.abs(target-t['records'][-1]['target_rad']))),limited_command=limited.tolist(),guard=guard,
        parent_trace=_file_binding(root/'version_04/full/TRACE.json'),implementation=_file_binding(Path(__file__)),restorer=_file_binding(Path(__file__).with_name('restore.py')),
        note='No correction integration has occurred. Lower-body order corrected against official CPP registry, not the similarly named Isaac-order constant. Derived full episode must pass original-case continuous replay to qualify.'))
    print(dict(**info,corrected_lower_order=True,old_refused_command_differs=True,raw_action=raw.tolist(),old_raw_action=prior_raw.tolist(),target_rad=target.tolist(),maximum_requested_target_delta_rad=float(np.max(np.abs(target-t['records'][-1]['target_rad']))),slew_limited_joints=guard['slew_limited_joints']),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
