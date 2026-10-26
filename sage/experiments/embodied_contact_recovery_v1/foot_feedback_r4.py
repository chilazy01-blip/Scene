"""Saved-state contact window with online, unchanged locomotion inference."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import R,E,finish
from . import trace_r2
from sage.experiments.embodied_continuous_v2 import controller as c


def main(case_file):
    cfg=c.read(case_file)
    job=Path(os.environ['CONTINUOUS_JOB_DIR'])
    os.environ['NP_ROOT']=str(R);os.environ['NP_JOB']=str(job)
    source=R/'branches/A/source'
    sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(source))
    sys.modules['instrument']=trace_r2
    c.write(job/'USAGE.json',{k:0 for k in c.read(job/'REQUEST.json')['reservation']})
    tr=trace_r2.Trace(job/'episode','diagnostic');tr.install()
    start=cfg['start_row'];steps=cfg['saved_steps']
    assert start%8==0 and steps*.0025<=10
    from target_adapter import install
    install('A','gain_translation',job/'episode')
    import run
    folder=R/'jobs/A_target_02/episode'
    m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
    with h5py.File(folder/'TRACE.h5','r') as f:
        d.qpos[:]=f['substep/qpos'][start-1];d.qvel[:]=f['substep/qvel'][start-1]
        d.qacc_warmstart[:]=f['substep/qacc'][start-1];d.time=float(f['substep/time_before'][start])
        target_saved=f['substep/nominal_position_target'][start:start+steps]
        ctrl_saved=f['substep/ctrl'][start:start+steps]
        expected=f['substep/qpos'][start:start+steps]
        policy=f['policy/walker_onnx'];policy_rows=policy['physics_row'][:]
        inp=policy['input'][next(iter(policy['input']))][:].reshape(len(policy_rows),-1)
    mujoco.mj_forward(m,d)
    policies=[run.ONNXPolicy(str(source/(n+'.onnx'))) for n in ['walker','croucher','rotator']]
    ctrl=run.G1Controller(m,d,*policies,c.read(source/'model_config.json'))
    index=int(np.searchsorted(policy_rows,start))
    ctrl.last_action=inp[index,-32:-3].copy()
    first_error=None
    guard_state={}
    base_start=d.qpos[:3].copy()
    try:
        for k in range(steps):
            if k%8==0:
                idx=int(np.searchsorted(policy_rows,start+k))
                command=inp[min(idx,len(inp)-1),-3:].copy()
                if cfg.get('velocity_override'):command=np.asarray(cfg['velocity_override'],dtype=float)
                if cfg.get('velocity_cap'):
                    command=np.clip(command,-np.asarray(cfg['velocity_cap']),np.asarray(cfg['velocity_cap']))
                if cfg.get('measured_landing_brake'):
                    from .gait_contact import command as landing_command
                    command=landing_command(m,d,command,guard_state)
                ctrl.lin_vel_x,ctrl.lin_vel_y,ctrl.ang_vel_z=map(float,command)
                target=ctrl.step()
            ctrl.apply_pd_control(target)
            # The current task is still approaching, with both hands open.
            for aid in range(m.nu):
                if 'hand' in m.actuator(aid).name:d.ctrl[aid]=0.
            if first_error is None:first_error=float(np.max(np.abs(d.ctrl-ctrl_saved[0])))
            if cfg.get('landing_damping'):
                from .landing import damp_landing
                damp_landing(m,d,cfg['landing_damping'])
            mujoco.mj_step(m,d)
        summary=tr.close()
    except BaseException:
        tr.close();raise
    report={'case':cfg,'summary':summary,'first_command_max_difference':first_error,
            'endpoint_qpos_difference':float(np.max(abs(d.qpos-expected[-1]))),
            'final_base_height_m':float(d.qpos[2]),'final_base_upright':float(1-2*(d.qpos[4]**2+d.qpos[5]**2)),
            'base_displacement_m':(d.qpos[:3]-base_start).tolist(),'landing_brake_state':guard_state,'online_policy_feedback':True,'production_accepted':False}
    c.write(job/'DIAGNOSTIC.json',report);finish(report,tr.usage)


if __name__=='__main__':main(sys.argv[1])
