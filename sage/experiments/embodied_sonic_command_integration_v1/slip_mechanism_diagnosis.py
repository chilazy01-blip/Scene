"""Recorded-state slip diagnostics; no integration, no controller or case edits."""
import argparse
import os
import resource
from pathlib import Path
import numpy as np

from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import group


def contact_response(mj, model, data):
    pid = model.body('payload').id
    out = []
    for i, contact in enumerate(data.contact):
        pair = contact_pair(model, contact)
        names = [item['name'] for item in pair]
        if 'payload_surface' not in names:
            continue
        side = names.index('payload_surface')
        role = group(pair[1-side]['body'])
        if role not in ('thumb','index','middle'):
            continue
        force = np.zeros(6)
        mj.mj_contactForce(model, data, i, force)
        if force[0] <= .01:
            continue
        other = int(model.geom_bodyid[contact.geom[1-side]])
        jac = np.zeros((3,model.nv)); otherjac = jac.copy()
        jd = jac.copy(); otherjd = jac.copy()
        mj.mj_jac(model,data,jac,None,contact.pos,pid)
        mj.mj_jac(model,data,otherjac,None,contact.pos,other)
        mj.mj_jacDot(model,data,jd,None,contact.pos,pid)
        mj.mj_jacDot(model,data,otherjd,None,contact.pos,other)
        D = np.asarray(contact.frame).reshape(3,3)
        velocity = D @ ((jac-otherjac) @ data.qvel)
        acceleration = D @ ((jac-otherjac) @ data.qacc + (jd-otherjd) @ data.qvel)
        speed = float(np.linalg.norm(velocity[1:]))
        along = float(np.dot(velocity[1:],acceleration[1:])/max(speed,1e-12))
        rho = float(np.sum(np.abs(force[1:3])/contact.friction[:2])/force[0])
        # This is a local linear prediction at fixed contact geometry, not an mj_step.
        prediction = velocity[1:] + model.opt.timestep*acceleration[1:]
        efc = int(contact.efc_address)
        out.append(dict(role=role,normal_n=float(force[0]),pyramid_utilization=rho,
            slip_speed_m_s=speed,slip_direction_acceleration_m_s2=along,
            local_linear_next_slip_m_s=float(np.linalg.norm(prediction)),
            solref=np.asarray(contact.solref).tolist(),solimp=np.asarray(contact.solimp).tolist(),
            efc_regularizer=data.efc_R[efc:efc+4].tolist(),
            efc_force=data.efc_force[efc:efc+4].tolist(),
            force_world_on_cup_n=((1 if side==1 else -1)*D.T@force[:3]).tolist()))
    if not out:
        return dict(contacts=[],loaded_contacts=0)
    weights=np.array([item['normal_n'] for item in out])
    weighted=lambda key:float(np.average([item[key] for item in out],weights=weights))
    return dict(contacts=out,loaded_contacts=len(out),normal_sum_n=float(sum(weights)),
        force_world_on_cup_n=np.sum([item['force_world_on_cup_n'] for item in out],axis=0).tolist(),
        median_slip_m_s=float(np.median([item['slip_speed_m_s'] for item in out])),
        interior_loaded_contacts=sum(item['pyramid_utilization']<.9 for item in out),
        interior_slipping_contacts=sum(item['pyramid_utilization']<.9 and item['slip_speed_m_s']>.0005 for item in out),
        weighted_slip_m_s=weighted('slip_speed_m_s'),
        weighted_slip_direction_acceleration_m_s2=weighted('slip_direction_acceleration_m_s2'),
        weighted_local_linear_next_slip_m_s=weighted('local_linear_next_slip_m_s'))


def run(root, output):
    import mujoco as mj
    assert not output.exists(), output
    output.mkdir(parents=True)
    episode=root/'attempt_28/full'
    report=read_bound_json(episode/'REPORT.json')
    trace=read_bound_json(episode/'TRACE.json')
    model=load_model(report['model']['path']);model.opt.timestep=.005
    data=mj.MjData(model);h=hand_ids(model)
    original=dict(iterations=int(model.opt.iterations),tolerance=float(model.opt.tolerance),
                  noslip_iterations=int(model.opt.noslip_iterations))
    settings=[('recorded_native',original),
        ('convergence_only',dict(original,iterations=200,tolerance=1e-12)),
        ('diagnostic_noslip3',dict(original,noslip_iterations=3)),
        ('diagnostic_noslip20',dict(original,noslip_iterations=20))]
    results=[]
    for tick in [1200,1250,1300,1360,1400,1430,1450,1460,1465,1467,1468,1469]:
        sample=trace['records'][tick-1]['substeps'][-1]
        conditions={}
        for name,options in settings:
            for key,value in options.items():setattr(model.opt,key,value)
            load_after(mj,model,data,sample)
            conditions[name]=dict(settings=options,results=contact_response(mj,model,data),
                solver_niter=np.asarray(data.solver_niter).tolist())
            assert np.array_equal(data.qpos,sample['full_qpos_after'])
            assert np.array_equal(data.qvel,sample['full_qvel_after'])
        for key,value in original.items():setattr(model.opt,key,value)
        load_after(mj,model,data,sample)
        targets=np.asarray(sample['hand_target_rad'])
        motors=[]
        for i,name in enumerate(h['names']):
            if not name.startswith('right_'):continue
            q=float(data.qpos[h['qpos'][i]]);v=float(data.qvel[h['dofs'][i]])
            a=int(h['actuators'][i]);tau=float(data.actuator_force[a])
            motors.append(dict(joint=name,q_rad=q,velocity_rad_s=v,target_rad=float(targets[i]),
                target_error_rad=float(targets[i]-q),actual_torque_nm=tau,
                effort_limits_nm=model.actuator_ctrlrange[a].tolist(),
                physical_joint_limits_rad=model.joint(name).range.tolist(),
                effort_saturated=abs(tau)>=max(abs(model.actuator_ctrlrange[a]))-1e-6))
        entry=dict(tick=tick,stage=sample['stage'],time_s=sample['time_after_s'],
            object_local_m=sample['object_local_m'],conditions=conditions,motors=motors)
        results.append(entry)
        print(dict(tick=tick,stage=sample['stage'],conditions={name:{k:v for k,v in item['results'].items() if k!='contacts'} for name,item in conditions.items()}),flush=True)
    result=dict(schema='native-slip-recorded-state-mechanism/v1',
        report=_file_binding(episode/'REPORT.json'),trace=report['trace'],model=report['model'],
        implementation=_file_binding(Path(__file__)),new_physics_steps=0,
        diagnostic_only=True,all_original_states_qpos_qvel_and_ctrl_unchanged=True,
        native_case_and_model_files_unchanged=True,original_condition_not_replaced=True,
        solver_counterfactual_not_a_task_success_or_dynamic_rollout=True,
        limitation='NoSlip comparisons are explicit diagnostic solver counterfactuals at the same recorded states, never accepted original-task physics. Acceleration and local linear predictions do not demonstrate a successful trajectory.',
        native_options=dict(original,timestep=.005,cone=int(model.opt.cone),impratio=float(model.opt.impratio),solver=int(model.opt.solver)),
        results=results)
    safe_save(output/'RECORDED_STATE_MECHANISM.json',result)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();run(a.root,a.output)
