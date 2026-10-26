"""Official mode1 finite encoder/decoder response at a real prior task state, zero steps."""
import argparse
from pathlib import Path
import numpy as np
from .task_v4 import Task
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import _make_session
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import ENCODER_ASSEMBLER,body_joint_target_from_raw_action
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=read_bound_json(root/'PROTOCOL.json');c=read_bound_json(root/'CASE_V3.json');scene=read_bound_json(Path(p['scene']['path']))
    t=read_bound_json(root/'version_03/full/TRACE.json');row=t['records'][-1]
    model=load_model(scene['model']['path']);data=mujoco.MjData(model);data.qpos[:]=row['substeps'][-1]['full_qpos_after'];data.qvel[:]=row['substeps'][-1]['full_qvel_after'];mujoco.mj_forward(model,data)
    base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,model,c,base['q'],base['v'])
    task.q[:]=row['reference_qpos'];task.v[:]=row['reference_velocity'];task.stage='insert'
    event=next(e for e in reversed(t['events']) if e.get('kind')=='cartesian_path')
    task.path=dict(tick=event['tick'],duration=event['duration'],origin=np.array(event['origin']),initial_R=data.xmat[task.wrist].reshape(3,3).copy(),goal=np.array(event['goal']),R=np.array(event['rotation']))
    task.synchronize(row['tick'],data,force=True)
    values=task.reference_blocks(row['tick'],data,np.asarray(t['initial_qpos'])[3:7]);enc=np.array([ENCODER_ASSEMBLER.assemble(values)],dtype=np.float32)
    encoder=_make_session(Path(p['inputs']['encoder']['path']));decoder=_make_session(Path(p['inputs']['decoder']['path']))
    token=encoder.run(None,{encoder.get_inputs()[0].name:enc})[0]
    io=np.load(root/'version_03/full/POLICY_IO.npz',allow_pickle=False);dec=io['decoder_inputs'][-1:].copy();dec[:,:64]=token
    raw=decoder.run(None,{decoder.get_inputs()[0].name:dec})[0]
    assert np.isfinite(token).all() and np.isfinite(raw).all() and raw.shape==(1,29)
    result=dict(schema='native-sonic-official-teleop-preflight/v1',passed=True,new_physics_steps=0,
        encoder_shape=list(enc.shape),token_shape=list(token.shape),decoder_shape=list(dec.shape),action_shape=list(raw.shape),
        mode=values['encoder_mode_4'].tolist(),lower_positions=values['motion_joint_positions_lowerbody_10frame_step5'].tolist(),
        target_positions_root=values['vr_3point_local_target'].tolist(),target_orientations_root_wxyz=values['vr_3point_local_orn_target'].tolist(),
        inactive_full_joint_block_zero=not np.any(values['motion_joint_positions_10frame_step5']),
        action_changed_from_g1=not np.array_equal(raw[0],np.asarray(row['raw_sonic_isaaclab'],dtype=np.float32)),
        raw_action=raw[0].tolist(),reference_only=True,physical_state_modified=False,
        previous_trace=_file_binding(root/'version_03/full/TRACE.json'),implementation=_file_binding(Path(__file__)),
        official_sources=dict(cpp=_file_binding(Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_readmission_20261018_v1/source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/g1_deploy_onnx_ref.cpp')),
            config=_file_binding(Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_native_full_20261019_v1/official_bundle/policy/sonic_v1_1/observation_config.yaml'))),
        limitation='interface/coordinate/finiteNN proof only; not execution or successful manipulation')
    safe_save(root/'TELEOP_INTERFACE_PREFLIGHT.json',result);print({k:result[k] for k in ('passed','mode','action_shape','action_changed_from_g1')},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
