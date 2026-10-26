"""Read-only earliest-failure and task-progress review of a completed trace."""
import sys
import numpy as np
import h5py
import mujoco
from .work import E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

name=sys.argv[1]
folder=E/'jobs'/name/'episode'
m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'))
with h5py.File(folder/'TRACE.h5','r') as f:
    q=f['substep/qpos'][:];v=f['substep/qvel'][:];times=f['substep/time_before'][:]
    contacts=f['contacts/rows'][:]
    j=m.joint('red_block_joint').id;qa=int(m.jnt_qposadr[j])
    oq=q[:,qa:qa+7]
    bad=contacts[contacts[:,3]<-.01]
    first=None
    if len(bad):
        row=bad[0];k=int(row[0]);g1,g2=map(int,row[1:3])
        first={'row':k,'time':float(times[k]),'pair':[m.geom(g1).name,m.geom(g2).name],
               'penetration_m':float(-row[3]),'ctrl':f['substep/ctrl'][k].tolist()}
    policy=f['policy/walker_onnx'];input_key=next(iter(policy['input']))
    inputs=policy['input'][input_key][:].reshape(len(policy['physics_row']),-1)
    command=inputs[:,-3:]
    obj=m.body('red_block').id
    grip_rows=[]
    for row in contacts:
        a,b=map(int,row[1:3])
        if int(m.geom_bodyid[a])==obj or int(m.geom_bodyid[b])==obj:
            other=b if int(m.geom_bodyid[a])==obj else a
            if 'right_hand' in m.body(int(m.geom_bodyid[other])).name:grip_rows.append(int(row[0]))
    report={'no_integration':True,'source_task':name,'sim_seconds':float(times[-1]+m.opt.timestep),
            'base_xy_start':q[0,:2].tolist(),'base_xy_end':q[-1,:2].tolist(),
            'base_max_displacement_m':float(np.linalg.norm(q[:,:2]-q[0,:2],axis=1).max()),
            'min_base_height_m':float(q[:,2].min()),'first_over_10mm':first,
            'max_penetration_m':float(max(0.,-contacts[:,3].min())),
            'walker_command_min':command.min(axis=0).tolist(),'walker_command_max':command.max(axis=0).tolist(),
            'first_object_hand_contact_s':float(times[min(grip_rows)]) if grip_rows else None,
            'grasp_contact_steps':len(set(grip_rows)),
            'object_max_lift_m':float(oq[:,2].max()-oq[0,2]),
            'object_max_tilt_deg':float(np.degrees(np.arccos(np.clip(1-2*(oq[:,4]**2+oq[:,5]**2),-1,1))).max()),
            'complete_substep_state_present':all(k in f for k in ['substep/integration_before','substep/integration_after','contacts/world_force']),
            'production_accepted':False}
c.write(E/'reports'/(name+'_REVIEW.json'),report);finish(report)
