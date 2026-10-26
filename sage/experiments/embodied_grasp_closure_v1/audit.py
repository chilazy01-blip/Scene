import json,gzip
from pathlib import Path
import numpy as np
from .control import ClosureContract,ClosureController
from .execution import target_at,CLOSED_PHASES
from .verification import matrix
from sage.experiments.embodied_grasp_validation_v1.quality import contact_quality,relative_pose,pose_drift,test_lift_gate
from sage.experiments.embodied_grasp_validation_v1.build import write
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
    contract['phases']=json.loads((output/'REALIZED_PHASES.json').read_text())
    with gzip.open(output/'CLOSURE_DECISIONS.json.gz','rt') as f:decisions=json.load(f)
    controller=ClosureController(ClosureContract(**config['closure_contracts'][task['id']]))
    previous_metric=None;events=[];last_state='closing';force_error=0.;max_com_error=0.
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
        assert not steps or np.max(abs(np.diff(a['time'])-dt))<1e-10
        rows=[x for x in decisions if x['phase']==phase['id']]
        if phase['id'] in CLOSED_PHASES:
            assert len(rows) in (steps,steps+1)
            for i,row in enumerate(rows):
                ob=row['observation'];assert row['before_step']==i+1
                for key,value in [('time',a['time'][i]),('position',a['actuator_length'][i,5]),('velocity',a['actuator_velocity'][i,5]),('native_force',a['actuator_force'][i,5])]:assert abs(ob[key]-value)<1e-12
                passive_dofs=[j['dof'] for j in binding['joints'] if j['name'] in ['rubber_left_x','rubber_left_y','rubber_right_x','rubber_right_y']]
                assert abs(ob['passive_speed']-np.max(abs(a['qvel'][i,passive_dofs])))<1e-12
                previous=metrics[i-1] if i else previous_metric
                assert previous is not None
                for side in ['left','right']:
                    assert abs(ob[side+'_force']-previous['contact_quality'][side]['force_N'])<1e-10
                    assert abs(ob[side+'_pad_fraction']-previous['contact_quality'][side]['pad_fraction'])<1e-12
                if previous['contact_quality']['contact_com_offset_m'] is None:assert ob['com_offset'] is None
                else:assert abs(ob['com_offset']-previous['contact_quality']['contact_com_offset_m'])<1e-12
                replay=controller.update(float(target_at(phase,i+1,dt)[5]),ob)
                assert replay==row['decision']
                if replay['state']!=last_state:events.append(dict(phase=phase['id'],before_step=i+1,time=ob['time'],state=replay['state'],reason=replay['reason']));last_state=replay['state']
                if i<steps:
                    assert replay['command'] is not None
                    expected_force=controller.c.kp*a['ctrl'][i,5]-controller.c.kp*ob['position']-controller.c.kd*ob['velocity']
                    assert abs(expected_force)<=controller.c.effort_limit+1e-9
                    assert abs(a['ctrl'][i,5]-ob['position'])<=controller.c.max_target_deflection+1e-12
                    force_error=max(force_error,abs(expected_force-replay['predicted_native_force']))
                else:assert replay['state']=='failed'
        else:assert not rows
        desired=np.array([target_at(phase,i+1,dt) for i in range(steps)]).reshape(-1,8)
        gear=np.array(config['control']['wheel_gear']);l0=np.array(contract['initial_actuator_length'])
        raw=(config['control']['wheel_kp']*((l0[:2]-a['actuator_length'][:-1,:2])/gear)-config['control']['wheel_kd']*a['actuator_velocity'][:-1,:2]/gear)/gear
        desired[:,:2]=np.clip(raw,-1,1)
        if phase['id'] in CLOSED_PHASES:
            desired[:,5]=[x['decision']['command'] for x in rows[:steps]]
        if steps:maximum=max(maximum,float(np.max(abs(desired-a['ctrl']))))
        assert maximum<1e-12
        for i in range(steps+1):
            rotation=matrix(a['qpos'][i,3:7]);assert np.max(abs(rotation-a['object_rotation'][i]))<1e-12
            com=a['qpos'][i,:3]+rotation@np.array(task['local_com']);max_com_error=max(max_com_error,float(np.max(abs(com-a['object_com'][i]))))
        assert max_com_error<1e-12
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
                if quality['contact_com_offset_m'] is None:assert metrics[i]['contact_quality']['contact_com_offset_m'] is None
                else:assert abs(quality['contact_com_offset_m']-metrics[i]['contact_quality']['contact_com_offset_m'])<1e-12
                recomputed.append(row)
        assert len(recomputed)==steps and metric_error<1e-10
        if phase['id']=='close':ref=relative_pose(a['hand_position'][-1],a['hand_rotation'][-1],a['object_com'][-1],a['object_rotation'][-1])
        if phase['id']=='test_hold' and steps==phase['steps']:
            failures=test_lift_gate(recomputed,config['quality'],dt)
            assert all(x in result['failures'] for x in failures)
            if result['status']=='pass':assert not failures
        if metrics:previous_metric=metrics[-1]
        phase_checks.append(dict(id=phase['id'],steps=steps))
    assert n==execution['physics_steps']
    result=dict(status='saved_audit_pass',physics_steps=n,new_physics_steps=0,command_max_error=maximum,quality_metric_max_error=metric_error,
                phases=phase_checks,scope='saved commands, timing, COM-relative motion, actual contact part/force, support clearance; other runtime gate metrics retained, not independently re-simulated',
                physical_status=execution['status'],closure_state_events=events,predicted_force_independent_max_error_N=force_error,COM_qpos_max_error_m=max_com_error,controller_state=controller.state)
    write(output/'AUDIT.json',result);return result
