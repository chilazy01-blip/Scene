"""Four preregistered static trials, re-evaluated from full saved states/contact frames."""
from pathlib import Path
import time,traceback
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,require,write_new,reference
from sage.experiments.embodied_task_generation_v1.planner import corners


def contacts(model,data,step,target,support):
    import mujoco
    rows=[];frames=[]
    for i,c in enumerate(data.contact):
        if target not in [c.geom1,c.geom2]:continue
        other=c.geom2 if c.geom1==target else c.geom1;w=np.zeros(6);mujoco.mj_contactForce(model,data,i,w)
        frame=np.array(c.frame).reshape(3,3);normal_z=float(frame[0,2])*(-1 if c.geom1==target else 1)
        rows.append([step,c.geom1,c.geom2,1 if other in support else 3,c.dist,*c.pos,normal_z,*w])
        frames.append(frame.ravel())
    return np.asarray(rows,dtype=float).reshape(-1,15),np.asarray(frames,dtype=float).reshape(-1,9)


def evaluate(raw,descriptor,task,protocol):
    limits=protocol['stability'];expected=round(limits['duration_s']/descriptor['dt_s'])
    n=len(raw['times']);checks={'complete':n==expected,'no_runtime_error':descriptor['runtime_error'] is None}
    arrays=['times','qpos','qvel','states','contacts','frames','initial_contacts','initial_frames']
    checks['finite']=all(np.isfinite(raw[k]).all() for k in arrays)
    checks['no_native_warning']=bool(not np.any(raw['warnings']))
    initial_pen=max(0.,-float(np.min(raw['initial_contacts'][:,4]))) if len(raw['initial_contacts']) else 0.
    checks['initial_contact']=initial_pen<=limits['initial_penetration_max_m']
    all_contacts=raw['contacts'];pen=max(0.,-float(np.min(all_contacts[:,4]))) if len(all_contacts) else 0.
    checks['penetration']=pen<=limits['max_penetration_m']
    other=all_contacts[all_contacts[:,3]==3];otherpen=max(0.,-float(np.min(other[:,4]))) if len(other) else 0.
    checks['non_support_contact']=otherpen<=limits['non_support_penetration_max_m']
    metrics=dict(steps=n,expected_steps=expected,initial_penetration_m=initial_pen,maximum_penetration_m=pen,non_support_penetration_m=otherpen)
    tail=np.flatnonzero(raw['times']>=limits['duration_s']-limits['tail_s']-1e-10)
    checks['tail_present']=len(tail)>=round(limits['tail_s']/descriptor['dt_s'])
    if len(tail) and checks['finite']:
        q=raw['qpos'][tail];v=raw['qvel'][tail];q0=raw['initial_qpos'];rot=Rotation.from_quat(q[:,[4,5,6,3]])
        angle=np.rad2deg((rot*Rotation.from_quat(q0[[4,5,6,3]]).inv()).magnitude())
        drift=np.linalg.norm(q[:,:2]-q0[:2],axis=1);speed=np.linalg.norm(v[:,:3],axis=1);omega=np.linalg.norm(v[:,3:6],axis=1)
        checks.update(orientation=bool(np.max(angle)<=limits['orientation_max_deg']),xy_drift=bool(np.max(drift)<=limits['xy_drift_max_m']),
            speed=bool(np.max(speed)<=limits['speed_max_m_s']),angular_speed=bool(np.max(omega)<=limits['angular_speed_max_rad_s']))
        support=np.asarray(task['support_pose']);bounds=np.asarray(task['support_bounds_local_m']);points=corners(task['target_dimensions_m'])
        world=np.einsum('nij,kj->nki',rot.as_matrix(),points)+q[:,:3,None].transpose(0,2,1)
        local=(world-support[:3,3])@support[:3,:3];margin=float(min(np.min(local[:,:,:2]-bounds[0,:2]),np.min(bounds[1,:2]-local[:,:,:2])))
        checks['support_margin']=margin>=limits['support_margin_m']
        fz=np.zeros(n);rows=all_contacts[all_contacts[:,3]==1];frames=raw['frames'][all_contacts[:,3]==1].reshape(-1,3,3)
        if len(rows):
            forces=np.einsum('nij,ni->nj',frames,rows[:,9:12]);sign=np.where(rows[:,1]==descriptor['target_geom_id'],-1.,1.)
            indices=rows[:,0].astype(int)-1;require(np.all((indices>=0)&(indices<n)),'contact_step_index')
            np.add.at(fz,indices,forces[:,2]*sign)
        ratios=fz[tail]/(task['physical_prior']['mass_kg']*9.81)
        checks['support_contact_every_tail_step']=bool(np.all(ratios>0.))
        checks['support_mean_weight']=bool(limits['support_weight_ratio'][0]<=np.mean(ratios)<=limits['support_weight_ratio'][1])
        metrics.update(tail_orientation_max_deg=float(max(angle)),tail_xy_drift_max_m=float(max(drift)),tail_speed_max_m_s=float(max(speed)),
            tail_angular_speed_max_rad_s=float(max(omega)),support_margin_m=margin,tail_support_weight_mean=float(np.mean(ratios)),tail_support_weight_min=float(min(ratios)))
    else:
        for key in ['orientation','xy_drift','speed','angular_speed','support_margin','support_contact_every_tail_step','support_mean_weight']:checks[key]=False
    return dict(passed=all(checks.values()),checks=checks,metrics=metrics,scope='fixed full-scene model and two registered poses; no robot or real-world stability claim')


def run(config,protocol_path,case,output):
    import mujoco
    from .entry import load
    config=Path(config);output=Path(output);output.mkdir(exist_ok=False);protocol=read(protocol_path)
    require(case in protocol['stability']['cases'],'unregistered_static_case')
    model,_=load(config/'SCENE_BINDING.json',reference(config/'SCENE_BINDING.json')['sha256'],'candidate_stability',read(config/'request.json')['id'])
    task=read(config/'package/task.json')
    if case['pose']=='goal':model=mujoco.MjModel.from_xml_path(str(config/'package/model_goal.xml'))
    require(model.nq==7 and model.nv==6 and model.nu==0,'unexpected_static_layout');model.opt.timestep=case['dt_s']
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    target=model.geom('target_collision').id;sb=model.body(task['support_body']).id
    support={i for i in range(model.ngeom) if model.geom_bodyid[i]==sb and (model.geom_contype[i] or model.geom_conaffinity[i])}
    spec=int(mujoco.mjtState.mjSTATE_INTEGRATION);size=mujoco.mj_stateSize(model,spec)
    def state():
        out=np.zeros(size);mujoco.mj_getState(model,data,out,spec);return out
    initial=state();q0=data.qpos.copy();c0,f0=contacts(model,data,0,target,support)
    descriptor=dict(case=case,dt_s=case['dt_s'],state_spec=spec,state_size=size,target_geom_id=target,support_geom_ids=sorted(support),
        model=reference(config/'package'/('model_goal.xml' if case['pose']=='goal' else 'model.xml')),runtime_error=None,pose_writes_after_initialization=0)
    write_new(output/'STARTED.json',dict(at=time.time(),case=case,initial_state=initial.tolist(),descriptor=descriptor))
    ts=[];qs=[];vs=[];states=[];cs=[];fs=[];warnings=[]
    try:
        require(not len(c0) or np.min(c0[:,4])>=-protocol['stability']['initial_penetration_max_m'],'initial_penetration_rejected')
        for k in range(round(protocol['stability']['duration_s']/case['dt_s'])):
            mujoco.mj_step(model,data);mujoco.mj_forward(model,data)
            ts.append(data.time);qs.append(data.qpos.copy());vs.append(data.qvel.copy());states.append(state());warnings.append([int(w.number) for w in data.warning])
            c,f=contacts(model,data,k+1,target,support);cs.append(c);fs.append(f)
            require(np.isfinite(states[-1]).all(),'nonfinite_state')
            require(not len(c) or np.min(c[:,4])>=-protocol['stability']['max_penetration_m'],'penetration_hard_stop')
            require(not any(warnings[-1]),'native_warning')
    except BaseException as exc:descriptor.update(runtime_error=str(exc),traceback=traceback.format_exc())
    raw=dict(times=np.asarray(ts),qpos=np.asarray(qs).reshape(-1,7),qvel=np.asarray(vs).reshape(-1,6),states=np.asarray(states).reshape(-1,size),
        warnings=np.asarray(warnings,dtype=int).reshape(-1,len(data.warning)),initial_state=initial,initial_qpos=q0,initial_contacts=c0,initial_frames=f0,
        contacts=np.concatenate(cs) if cs else np.empty((0,15)),frames=np.concatenate(fs) if fs else np.empty((0,9)))
    np.savez_compressed(output/'RAW.npz',**raw);write_new(output/'DESCRIPTOR.json',descriptor)
    result=evaluate(raw,descriptor,task,protocol);result.update(case=case,raw=reference(output/'RAW.npz'),descriptor=reference(output/'DESCRIPTOR.json'),new_physical_attempts=1,new_physics_steps=len(ts))
    write_new(output/'RESULT.json',result);print(case['key'],result,flush=True);return result


def compare(base,half,protocol):
    if not (base['passed'] and half['passed']):return dict(passed=False,reason='both_complete_static_passes_required',compared_samples=0)
    with np.load(bound(base['raw']['path'],base['raw']['sha256']),allow_pickle=False) as a,np.load(bound(half['raw']['path'],half['raw']['sha256']),allow_pickle=False) as b:
        require(len(b['times'])==2*len(a['times']),'half_step_count')
        require(np.allclose(a['times'],b['times'][1::2],atol=1e-9,rtol=0),'half_step_times')
        pos=float(np.max(np.linalg.norm(a['qpos'][:,:3]-b['qpos'][1::2,:3],axis=1)))
        ra=Rotation.from_quat(a['qpos'][:,[4,5,6,3]]);rb=Rotation.from_quat(b['qpos'][1::2][:,[4,5,6,3]])
        angle=float(np.max(np.rad2deg((ra*rb.inv()).magnitude())))
        speed=float(np.max(np.linalg.norm(a['qvel'][:,:3]-b['qvel'][1::2,:3],axis=1)))
        p=protocol['numerical'];return dict(passed=pos<=p['position_tolerance_m'] and angle<=p['orientation_tolerance_deg'] and speed<=p['speed_tolerance_m_s'],
            maximum_position_error_m=pos,maximum_orientation_error_deg=angle,maximum_velocity_error_m_s=speed,compared_samples=len(a['times']))


def recompute(path,task,protocol):
    summary=read(path)
    if summary.get('status')=='skipped':return dict(passed=False,cases=[],comparisons=[],reason=summary['reason'])
    cases=[]
    require([x['case'] for x in summary['cases']]==protocol['stability']['cases'],'static_case_set')
    for row in summary['cases']:
        descriptor=read_ref(row['descriptor']);require(descriptor['case']==row['case'] and descriptor['dt_s']==row['case']['dt_s'],'static_case_binding')
        bound(descriptor['model']['path'],descriptor['model']['sha256'])
        with np.load(bound(row['raw']['path'],row['raw']['sha256']),allow_pickle=False) as raw:score=evaluate(raw,descriptor,task,protocol)
        require(score['passed']==row['passed'] and score['checks']==row['checks'] and score['metrics']==row['metrics'],'static_summary_mismatch')
        cases.append(dict(row,passed=score['passed']))
    bykey={r['case']['key']:r for r in cases};comparison=[compare(bykey[state+'_base'],bykey[state+'_half'],protocol) for state in ['start','goal']]
    require(comparison==summary['comparisons'],'numerical_summary_mismatch')
    passed=all(r['passed'] for r in cases+comparison);require(passed==summary['passed'],'static_gate_mismatch')
    return dict(passed=passed,cases=cases,comparisons=comparison)
