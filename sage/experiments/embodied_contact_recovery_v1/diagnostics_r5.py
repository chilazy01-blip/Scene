"""Bounded counterfactuals initialized from a saved state, never full tasks."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import R, E, finish
from sage.experiments.embodied_continuous_v2 import controller as c


def run(case_file):
    cfg=c.read(case_file)
    approval=c.read(E/'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
    assert approval['approved'] and approval['proposal_sha256']==c.sha(E/'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
    job=Path(os.environ['CONTINUOUS_JOB_DIR'])
    folder=Path(cfg.get('source_folder',str(R/'jobs/A_target_02/episode')))
    m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'))
    d=mujoco.MjData(m)
    start=int(cfg['start_row']);count=int(cfg['saved_steps'])
    factor=int(cfg.get('subdivisions',1));assert factor in [1,2,4]
    solver_factor=int(cfg.get('solver_iteration_factor',1));assert solver_factor in [1,2]
    m.opt.timestep/=factor;m.opt.iterations*=solver_factor
    assert count*.0025<=10
    with h5py.File(folder/'TRACE.h5','r') as f:
        mujoco.mj_setState(m,d,f['substep/integration_before'][start],mujoco.mjtState.mjSTATE_INTEGRATION)
        commands=f['substep/ctrl'][start:start+count]
        expected=f['substep/qpos'][start:start+count]
    mujoco.mj_forward(m,d)
    os.environ['NP_JOB']=str(job)
    c.write(job/'USAGE.json',{k:0 for k in c.read(job/'REQUEST.json')['reservation']})
    from .trace_r4 import Trace
    trace=Trace(job/'episode','diagnostic')
    trace.install()
    try:
        for command in commands:
            for _ in range(factor):
                d.ctrl[:]=command
                if cfg.get('finger_preload_rad') is not None:
                    for aid in range(m.nu):
                        if m.actuator(aid).name.startswith('right_hand'):
                            jid=int(m.actuator_trnid[aid,0]);q=d.qpos[m.jnt_qposadr[jid]]
                            cap=cfg['finger_preload_rad']
                            d.ctrl[aid]=np.clip(d.ctrl[aid],q-cap,q+cap)
                # The retained adapter computes its model terms before every step.
                mujoco.mj_forward(m,d)
                if cfg.get('landing_damping'):
                    from .landing import damp_landing
                    damp_landing(m,d,cfg['landing_damping'])
                mujoco.mj_step(m,d)
        summary=trace.close()
    except BaseException:
        trace.close()
        raise
    delta=float(np.max(np.abs(d.qpos-expected[-1])))
    result={'case':cfg,'summary':summary,'endpoint_max_abs_qpos_difference':delta,
            'exact_integration_before_state_restored':True,'actual_commands_held_at_original_400Hz':True,'full_task':False,'production_accepted':False}
    c.write(job/'DIAGNOSTIC.json',result)
    finish(result,trace.usage)


if __name__=='__main__':
    run(sys.argv[1])
