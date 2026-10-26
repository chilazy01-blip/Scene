"""Independent affine-effort checks, state-transition tests and saved-data consumer."""
from dataclasses import asdict
from pathlib import Path
import gzip,json
import numpy as np
from .control import ClosureContract,ClosureController,observation
from sage.experiments.embodied_grasp_validation_v1.quality import contact_quality,contact_gate


def matrix(q):
    w,x,y,z=np.asarray(q,float)
    return np.array([[w*w+x*x-y*y-z*z,2*(x*y-w*z),2*(x*z+w*y)],
                     [2*(x*y+w*z),w*w-x*x+y*y-z*z,2*(y*z-w*x)],
                     [2*(x*z-w*y),2*(y*z+w*x),w*w-x*x-y*y+z*z]])


def checks(contract):
    c=contract;results={}
    def obs(i=0,**kw):
        return dict(dict(time=i*c.dt,position=.025,velocity=0.,native_force=-c.nominal_preload,
              left_force=c.contact_force_min*1.25,right_force=c.contact_force_min*1.25,
              left_pad_fraction=1.,right_pad_fraction=1.,com_offset=.01,passive_speed=0.),**kw)
    ctrl=ClosureController(c);row=ctrl.update(0.,obs())
    results['contact_enters_confirmation']=row['state']=='confirming'
    results['holding_retains_native_damping']=abs(c.kp*(row['command']-.025)+c.nominal_preload)<1e-10
    for i in range(1,round(c.confirm_seconds/c.dt)):row=ctrl.update(0.,obs(i))
    results['continuous_contact_enters_hold']=row['state']=='holding'
    for i in range(round(c.confirm_seconds/c.dt),round(c.confirm_seconds/c.dt)+round(c.loss_seconds/c.dt)):
        row=ctrl.update(0.,obs(i,left_force=0.))
    results['loss_stops_hold']=row['reason']=='contact_quality_lost'
    results['failed_controller_cannot_restart']=ctrl.update(0.,obs(999))['state']=='failed'
    for key,change,reason in [('velocity',dict(passive_speed=c.max_passive_speed+.1),'passive_speed'),
                               ('actual_effort',dict(native_force=-c.effort_limit-.1),'measured_native_effort')]:
        results[key+'_rejected']=ClosureController(c).update(0.,obs(**change))['reason']==reason
    ctrl=ClosureController(c);ctrl.update(0.,obs())
    results['compression_rejected']=ctrl.update(0.,obs(1,position=.025-c.max_extra_compression-.0001))['reason']=='extra_compression'
    ctrl=ClosureController(c)
    for i in range(round(c.timeout_seconds/c.dt)):
        row=ctrl.update(0.,obs(i,left_force=0.,right_force=0.,left_pad_fraction=0.,right_pad_fraction=0.,com_offset=None,native_force=0.))
    results['no_contact_times_out']=row['reason']=='closure_timeout'
    ctrl=ClosureController(c);before=vars(ctrl).copy()
    try:ctrl.update(0.,obs(position=float('nan')))
    except ValueError:results['invalid_input_atomic']=vars(ctrl)==before
    else:results['invalid_input_atomic']=False
    ctrl.update(0.,obs());before=vars(ctrl).copy()
    try:ctrl.update(0.,obs(3))
    except ValueError:results['timestamp_gap_atomic']=vars(ctrl)==before
    else:results['timestamp_gap_atomic']=False
    # Sweep real input ranges independently of the state-machine implementation.
    maximum=0.;admitted=0;rejected=0
    for q in [-.004,0.,.02,.039]:
      for v in [-.1,-.02,0.,.02,.1]:
       for nominal in [-.005,0.,.02,.04]:
        row=ClosureController(c).update(nominal,obs(position=q,velocity=v,native_force=0.,left_force=0.,right_force=0.,com_offset=None))
        if row['state']=='failed':rejected+=1;continue
        admitted+=1;u=row['command'];force=c.kp*u-c.kp*q-c.kd*v;maximum=max(maximum,abs(force))
        assert c.ctrl_min-1e-12<=u<=c.ctrl_max+1e-12 and abs(u-q)<=c.max_target_deflection+1e-12
        assert abs(force)<=c.effort_limit+1e-10
    results['independent_affine_force_and_deflection_bounds']=admitted>0 and maximum<=c.effort_limit+1e-10
    return dict(checks=results,passed=all(results.values()),command_sweep=dict(total=80,admitted=admitted,rejected=rejected,max_predicted_effort_N=maximum))


def consume_baseline(source, cid, contract):
    out=Path(source)/'combinations'/cid
    with np.load(out/'close/RAW.npz') as z:a={k:z[k] for k in z.files}
    with gzip.open(out/'close/METRICS.json.gz','rt') as f:metrics=json.load(f)
    # Match live control timing: state/contacts at saved step i precede command i+1.
    ctrl=ClosureController(contract);events=[];previous='closing';commands=[]
    for i in range(1,len(metrics)):
        q=metrics[i-1]['contact_quality'];passive=float(np.max(abs(a['qvel'][i,[22,23,25,26]])))
        ob=observation(a['time'][i],a['actuator_length'][i,5],a['actuator_velocity'][i,5],a['actuator_force'][i,5],q,passive)
        row=ctrl.update(float(a['target'][i,5]),ob)
        if row['state']!=previous:events.append(dict(before_next_step=i+1,time=float(a['time'][i]),**row));previous=row['state']
        if row['state']=='failed':break
        commands.append(row['command'])
    return dict(events=events,commands_computed=len(commands),input_is_unchanged_old_physics=True,
                inference='open-loop saved observation consumer only; new commands did not generate these observations; no closed-loop success claim')


def book_frame_regression(old_stage):
    old=Path(old_stage);binding=json.loads((old/'protocol/PICKUP_BINDING.json').read_text())
    with np.load(old/'trials/lift/RAW.npz') as z:qp=z['qpos'][-1]
    rot=matrix(qp[3:7]);contacts=[]
    with gzip.open(old/'trials/lift/contacts.jsonl.gz','rt') as f:
        for line in f:last=json.loads(line)
    for row in last['contacts']:
        b1,b2=(binding['geom_body'][row[k]] for k in ('g1','g2'))
        if binding['target_body'] not in (b1,b2):continue
        other=b2 if b1==binding['target_body'] else b1
        for side in ('left','right'):
            ids=binding[side+'_finger_bodies']
            if other in ids:contacts.append(dict(side=side,part='link' if other==ids[0] else 'pad',position=row['pos'],normal_N=max(0.,row['force'][0])))
    quality=contact_quality(contacts,qp[:3],rot,.25,.5)
    # Independently reconstruct weighted center -> local coordinates -> world.
    errors=[]
    for side in ('left','right'):
        rows=[x for x in contacts if x['side']==side and x['normal_N']>0]
        center=np.average([x['position'] for x in rows],axis=0,weights=[x['normal_N'] for x in rows])
        errors.append(float(np.max(abs(rot@np.array(quality[side]['com_local_m'])+qp[:3]-center))))
    assert max(errors)<1e-12
    return dict(passed=True,quality=quality,frame='object body orientation, origin at inertial COM; old model body_ipos=0',world_roundtrip_max_error_m=max(errors),new_physics_steps=0)
