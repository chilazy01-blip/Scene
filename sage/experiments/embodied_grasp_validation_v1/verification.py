"""Saved-only evidence checks and real-interface positive/negative engineering fixtures."""
import copy
import gzip
import json
from pathlib import Path
import numpy as np
from .quality import contact_quality, contact_gate, relative_pose, pose_drift, test_lift_gate, TaskGate
from .native import Stretch, NAMES
from .execution import target_at
from .build import write


def regression(config, output, model=None, binding=None):
    p=config['quality']; checks={}
    cs=[dict(side=s,part='pad',normal_N=5.,position=[x,0,0]) for s,x in [('left',-.035),('right',.035)]]
    q=contact_quality(cs,np.zeros(3),np.eye(3),.25,.6)
    good=dict(contact_quality=q,relative_slip_m=.001,relative_rotation_rad=.01,object_lift_m=.03,support_clearance_m=.025,support_force_N=0.)
    samples=[copy.deepcopy(good) for _ in range(500)]
    checks['stable_contiguous_trial_lift_passes']=not test_lift_gate(samples,p,.001)
    checks['short_window_rejected']=bool(test_lift_gate(samples[:499],p,.001))
    for field,value in [('relative_slip_m',.012),('relative_rotation_rad',.18),('support_clearance_m',-.001),('support_force_N',2.),('object_lift_m',0.)]:
        bad=copy.deepcopy(samples);bad[250][field]=value
        checks[field+'_one_bad_frame_rejected']=field in test_lift_gate(bad,p,.001)
    bad=copy.deepcopy(q);bad['left']['pad_fraction']=0.;bad['right']['pad_fraction']=0.
    checks['bilateral_link_force_not_enough']=len(contact_gate(bad,p))==2
    bad=copy.deepcopy(q);bad['contact_com_offset_m']=float('nan')
    checks['nonfinite_COM_rejected']=bool(contact_gate(bad,p))
    # World translation and rotation leave hand-relative COM coordinates unchanged.
    angle=.7;r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
    hp=np.array([.3,.1,.2]);com=hp+np.array([.02,.01,0]);t=np.array([3,4,5])
    a=relative_pose(hp,np.eye(3),com,np.eye(3));b=relative_pose(r@hp+t,r,r@com+t,r)
    pos,rot=pose_drift(a,b);checks['relative_frame_invariant']=pos<1e-12 and rot<1e-7
    q_shift=contact_quality([dict(c,position=(np.array(c['position'])+[0,.06,0]).tolist()) for c in cs],np.array([0,.06,0]),np.eye(3),.25,.6)
    checks['inertial_COM_not_body_origin']=q_shift['contact_com_offset_m']<1e-12
    gate=TaskGate()
    try:gate.require_transport()
    except ValueError:checks['transport_without_test_rejected']=True
    else:checks['transport_without_test_rejected']=False
    gate.finish_test_lift(samples,p,.001);gate.require_transport();checks['transport_after_test_allowed']=True
    bad=copy.deepcopy(samples);bad[-1]['support_force_N']=1.
    gate.finish_test_lift(bad,p,.001)
    try:gate.require_transport()
    except ValueError:checks['failed_gate_cannot_reopen']=True
    else:checks['failed_gate_cannot_reopen']=False
    if model is not None:
        import mujoco
        native=Stretch(model,binding);data=mujoco.MjData(model);cmd=np.array([0,0,.4,.06,0,.04,0,0])
        native.command(data,cmd);checks['named_native_action_consumed']=np.array_equal(data.ctrl,cmd)
        for name,values,names,units in [('shape',cmd[:-1],NAMES,'native_m_rad'),('nan',cmd*np.nan,NAMES,'native_m_rad'),('range',cmd+100,NAMES,'native_m_rad'),('order',cmd,NAMES[::-1],'native_m_rad'),('units',cmd,NAMES,'degrees')]:
            before=data.ctrl.copy()
            try:native.command(data,values,names=names,units=units)
            except ValueError:checks['bad_action_'+name]=bool(np.array_equal(before,data.ctrl) and data.time==0)
            else:checks['bad_action_'+name]=False
    old=Path(config['old_negative']);binding_old=json.loads((old/'protocol/PICKUP_BINDING.json').read_text())
    with gzip.open(old/'trials/lift/contacts.jsonl.gz','rt') as f:
        for line in f:last=json.loads(line)
    contact_rows=[]
    for c in last['contacts']:
        b1,b2=(binding_old['geom_body'][c[k]] for k in ('g1','g2'))
        if binding_old['target_body'] not in (b1,b2):continue
        other=b2 if b1==binding_old['target_body'] else b1
        for side in ('left','right'):
            ids=binding_old[side+'_finger_bodies']
            if other in ids:contact_rows.append(dict(side=side,part='link' if other==ids[0] else 'pad',position=c['pos'],normal_N=max(0.,c['force'][0])))
    with np.load(old/'trials/lift/RAW.npz') as z:
        qp=z['qpos'][-1];pos=qp[binding_old['target_qpos']:binding_old['target_qpos']+3]
        # Identity is sufficient for COM offset magnitude; original body_ipos is zero.
        oldq=contact_quality(contact_rows,pos,np.eye(3),.25,.5)
    rejection=contact_gate(oldq,p)
    checks['old_book_saved_negative']=bool('left_pad_contact_insufficient' in rejection and 'right_pad_contact_insufficient' in rejection)
    result=dict(status='pass' if all(checks.values()) else 'fail',checks=checks,old_book=dict(quality=oldq,rejections=rejection,new_physics_steps=0,
                interpretation='new checker negative regression only; original failed task unchanged'),synthetic_fixtures_are_scientific_samples=False)
    write(output,result)
    assert all(checks.values()),checks
    return result


def audit(config, task, binding, output):
    output=Path(output);execution_path=output/'EXECUTION_RESULT.json'
    if not execution_path.exists():
        plan=json.loads((output/'PLAN_RESULT.json').read_text())
        result=dict(status='saved_audit_pass',scope='planning rejection only',no_physical_attempt=not (output/'PHYSICAL_ATTEMPT').exists(),
                    combinations=1,candidates=len(plan['candidates']),physics_steps=0)
        assert plan['selected'] is None and result['no_physical_attempt']
        write(output/'AUDIT.json',result);return result
    execution=json.loads(execution_path.read_text());contract=json.loads((output/'EXECUTION_CONTRACT.json').read_text())
    dt=contract['dt'];n=0;maximum=0.;metric_error=0.;ref=None;phase_checks=[]
    hands={}
    for i,name in enumerate(binding['body_names']):
        for side in ('left','right'):
            if name=='link_gripper_finger_'+side:hands[i]=(side,'link')
            if name=='rubber_tip_'+side:hands[i]=(side,'pad')
    target=binding['body_names'].index('target');support=binding['body_names'].index('support')
    for phase,result in zip(contract['phases'],execution['phases']):
        if result['status']=='skipped':continue
        out=output/phase['id']
        with np.load(out/'RAW.npz') as z:a={k:z[k] for k in z.files}
        with gzip.open(out/'METRICS.json.gz','rt') as f:metrics=json.load(f)
        steps=len(a['ctrl']);n+=steps;assert steps==result['steps'] and len(metrics)==steps
        assert np.max(abs(np.diff(a['time'])-dt))<1e-10
        desired=np.array([target_at(phase,i+1,dt) for i in range(steps)])
        gear=np.array(config['control']['wheel_gear']);l0=np.array(contract['initial_actuator_length'])
        raw=(config['control']['wheel_kp']*((l0[:2]-a['actuator_length'][:-1,:2])/gear)-config['control']['wheel_kd']*a['actuator_velocity'][:-1,:2]/gear)/gear
        desired[:,:2]=np.clip(raw,-1,1)
        maximum=max(maximum,float(np.max(abs(desired-a['ctrl']))));assert maximum<1e-12
        recomputed=[]
        with gzip.open(out/'CONTACTS.jsonl.gz','rt') as f:
            for i,line in enumerate(f):
                saved=json.loads(line);contacts=[];sf=0.
                for c in saved:
                    b1,b2=c['bodies']
                    if target not in (b1,b2):continue
                    other=b2 if b1==target else b1
                    if other==support:sf+=max(0.,c['force'][0])
                    if other in hands:
                        side,part=hands[other];contacts.append(dict(side=side,part=part,normal_N=max(0.,c['force'][0]),position=c['position']))
                quality=contact_quality(contacts,a['object_com'][i+1],a['object_rotation'][i+1],task['mass_kg'],task['friction'][0])
                current=relative_pose(a['hand_position'][i+1],a['hand_rotation'][i+1],a['object_com'][i+1],a['object_rotation'][i+1])
                slip,rotation=(0.,0.) if ref is None else pose_drift(ref,current)
                bottom=np.min(np.array(task['local_vertices'])@a['object_rotation'][i+1][2])+a['object_position'][i+1,2]
                row=dict(contact_quality=quality,relative_slip_m=slip,relative_rotation_rad=rotation,
                         object_lift_m=float(a['object_com'][i+1,2]-contract['object_com_reference'][2]),support_clearance_m=float(bottom-task['support_top_z']),support_force_N=sf)
                for k in ('relative_slip_m','relative_rotation_rad','object_lift_m','support_clearance_m','support_force_N'):
                    metric_error=max(metric_error,abs(row[k]-metrics[i][k]))
                for side in ('left','right'):
                    assert abs(quality[side]['force_N']-metrics[i]['contact_quality'][side]['force_N'])<1e-10
                    assert abs(quality[side]['pad_fraction']-metrics[i]['contact_quality'][side]['pad_fraction'])<1e-12
                recomputed.append(row)
        assert len(recomputed)==steps and metric_error<1e-10
        if phase['id']=='close':ref=relative_pose(a['hand_position'][-1],a['hand_rotation'][-1],a['object_com'][-1],a['object_rotation'][-1])
        if phase['id']=='test_hold' and steps==phase['steps']:
            failures=test_lift_gate(recomputed,config['quality'],dt)
            assert all(x in result['failures'] for x in failures)
            if result['status']=='pass':assert not failures
        phase_checks.append(dict(id=phase['id'],steps=steps))
    assert n==execution['physics_steps']
    result=dict(status='saved_audit_pass',physics_steps=n,new_physics_steps=0,command_max_error=maximum,quality_metric_max_error=metric_error,
                phases=phase_checks,scope='saved commands, timing, COM-relative motion, actual contact part/force, support clearance; other runtime gate metrics retained, not independently re-simulated',
                physical_status=execution['status'])
    write(output/'AUDIT.json',result);return result
