"""Independent native history/input/target verification without policy imports."""
from collections import deque
import numpy as np


def rotation_wxyz(quaternion):
    q=np.asarray(quaternion,dtype=float)
    if q.shape!=(4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1)>1e-6:raise ValueError('native_quaternion')
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def audit_records(qpos,commands,inputs,outputs,contract,config):
    qpos=np.asarray(qpos);inputs=np.asarray(inputs);outputs=np.asarray(outputs);n=len(commands)
    if qpos.shape!=(n,57) or inputs.shape!=(n,1,516) or outputs.shape!=(n,1,15) or n==0:raise ValueError('native_record_dimensions')
    if not all(np.isfinite(v).all() for v in [qpos,inputs,outputs]):raise ValueError('nonfinite_native_record')
    rows=contract['rows'];qadr=np.asarray([r['qpos'] for r in rows]);body=np.asarray([r['pin'] for r in rows if r['group']!='hand']);lower=np.asarray([r['pin'] for r in rows if r['group']=='lower'])
    if len(body)!=29 or len(lower)!=15 or not np.array_equal(body[:15],lower):raise ValueError('native_body_order')
    lo=np.asarray([r['lower'] for r in rows]);hi=np.asarray([r['upper'] for r in rows]);defaults=np.zeros(29,np.float32);defaults[:15]=config['default_angles'];previous=np.zeros(15,np.float32);history=deque(maxlen=6);max_input=max_target=0.
    expected={'tick','dt','frame','units','navigate','height','rpy','q_reference'}
    for tick,(q,record) in enumerate(zip(qpos,commands)):
        packet=record['packet']
        if set(packet)!=expected or packet['tick']!=tick or record['tick']!=tick:raise ValueError('native_packet_clock_or_fields')
        if packet['dt']!=.02 or packet['frame']!='body_heading' or packet['units']!='SI_rad':raise ValueError('native_packet_units')
        nav=np.asarray(packet['navigate']);rpy=np.asarray(packet['rpy']);reference=np.asarray(packet['q_reference']);height=float(packet['height'])
        if nav.shape!=(3,) or rpy.shape!=(3,) or reference.shape!=(43,):raise ValueError('native_command_dimensions')
        if not all(np.isfinite(v).all() for v in [nav,rpy,reference,height]):raise ValueError('native_command_finite')
        if np.any(abs(nav)>[.2,.1,.2]) or not .64<=height<=.74 or np.any(abs(rpy)>.1):raise ValueError('native_command_envelope')
        if np.any(reference<lo) or np.any(reference>hi):raise ValueError('native_reference_range')
        # Counterfactual source observations explicitly have zero velocities.
        single=np.concatenate([nav*config['cmd_scale'],[height],rpy,np.zeros(3),rotation_wxyz(q[3:7]).T@np.array([0.,0.,-1.]),(q[qadr][body]-defaults)*config['dof_pos_scale'],np.zeros(29),previous]).astype(np.float32)
        if single.shape!=(86,):raise ValueError('native_observation_layout')
        history.append(single)
        while len(history)<6:history.appendleft(np.zeros(86,np.float32))
        err=float(np.max(abs(np.concatenate(history)[None,:]-inputs[tick])));max_input=max(max_input,err)
        if err>=2e-6:raise ValueError('native_input_or_history')
        previous=outputs[tick,0].copy();target=reference.copy();target[lower]=previous*config['action_scale']+np.asarray(config['default_angles'],dtype=np.float32)
        if np.any(target<lo) or np.any(target>hi):raise ValueError('native_target_range')
        target_error=float(np.max(abs(target-np.asarray(record['target']))));max_target=max(max_target,target_error)
        if target_error>=1e-12:raise ValueError('native_target_reconstruction')
        if ('Walk' in record['mode'])!=(np.linalg.norm(nav)>=.05):raise ValueError('native_mode_selection')
    return dict(passed=True,commands_audited=n,max_input_error=max_input,max_target_error=max_target,history_mode_and_clock_verified=True,policy_forwards=0,physics_steps=0,counterfactual_zero_velocity_only=True,causal_task_success=False)
