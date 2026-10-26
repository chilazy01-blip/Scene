"""Actuator rollouts, 1 kHz contact audit and resumable controller state."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
from pathlib import Path
from copy import deepcopy
import gzip,json,time,traceback
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_v1.runner import PandaController,wrap,restore_check
from sage.experiments.embodied_scene_v1.package import bound
from .config import ROOT,PACKAGE,write_json,digest,validate,ledger,checkpoint
from .models import make_task,model_semantics
from .planner import occupancy_path

class Driver:
    def __init__(self,m,d,c,out,plan=None):
        self.m,self.d,self.c=m,d,c;self.plan=plan
        self.arm=c['task']=='pick_place'
        if self.arm:
            self.ctrl=PandaController(m,d)
            self.ctrl.kp*=c['controller_gain_multiplier'];self.ctrl.kd*=c['controller_gain_multiplier']
            self.ctrl.target_rot=Rotation.from_euler('z',c['grasp_yaw_rad']).as_matrix()@np.diag([1.,-1.,-1.])
        else:
            self.bid=m.body('base_link').id;self.jid=m.body_jntadr[self.bid]
            self.left=m.jnt_dofadr[m.joint('joint_left_wheel').id];self.right=m.jnt_dofadr[m.joint('joint_right_wheel').id]
            self.ai=m.actuator('forward').id;self.ti=m.actuator('turn').id
        if plan is None:
            if self.arm:
                d.qpos[self.ctrl.qi]=self.ctrl.qhome
                d.qpos[m.jnt_qposadr[m.joint('finger_joint1').id]]=.04
                d.qpos[m.jnt_qposadr[m.joint('finger_joint2').id]]=-.04
                mujoco.mj_forward(m,d)
                s=c['start'];g=c['goal'];z=s[2]+.08
                phases=[('approach',3.,[*s[:2],z+.15],.04),('descend',2.,[*s[:2],z],.04),
                    ('close',1.2,[*s[:2],z],0.),('lift',2.,[*s[:2],z+.16],0.),
                    ('transfer',3.,[*g[:2],z+.16],0.),('lower',2.,[*g[:2],z+.005],0.),
                    ('release',1.5,[*g[:2],z+.005],.04),('retreat',2.,[*g[:2],z+.20],.04),('settle',2.,[*g[:2],z+.20],.04)]
                qprev=self.ctrl.qhome.copy();plan=[];step=0
                for phase,seconds,position,grip in phases:
                    qgoal,error=self.ctrl.ik(position,qprev)
                    plan.append(dict(phase=phase,seconds=seconds,start_step=step,steps=round(seconds/c['dt_s']),
                        qprev=qprev.tolist(),qgoal=qgoal.tolist(),ik_error=error,grip=grip,position=position))
                    qprev=qgoal;step+=plan[-1]['steps']
                write_json(Path(out)/'controller_plan.json',plan)
                if max(p['ik_error'] for p in plan)>.015:raise ValueError('IK did not converge within 15 mm/rad residual')
            else:
                d.ctrl[m.actuator('lift').id]=-.2;d.qpos[m.jnt_qposadr[m.joint('joint_lift').id]]=-.2
                # Yaw is already in model qpos0: never orient toward the first waypoint.
                mujoco.mj_forward(m,d)
                plan=occupancy_path(out,c['start'],c['goal']).tolist()
                write_json(Path(out)/'controller_plan.json',plan)
            self.plan=plan

    def action(self,state):
        m,d,c=self.m,self.d,self.c
        # Rebuild state-derived kinematics/bias before feedback, identically on
        # uninterrupted and restored paths. Contacts are audited after mj_step.
        mujoco.mj_forward(m,d)
        if self.arm:
            p=next((p for p in self.plan if state['step']<p['start_step']+p['steps']),self.plan[-1])
            k=state['step']-p['start_step'];alpha=min(1.,k*c['dt_s']/max(.01,p['seconds']*.8));alpha=alpha*alpha*(3-2*alpha)
            q=np.array(p['qprev'])*(1-alpha)+np.array(p['qgoal'])*alpha
            self.ctrl.action(q,p['grip']);state['phase']=p['phase'];state['chosen_action']=d.ctrl.tolist()
        else:
            path=np.asarray(self.plan);pos=d.xpos[self.bid,:2];rot=d.xmat[self.bid].reshape(3,3);yaw=np.arctan2(rot[1,0],rot[0,0])
            index=state['path_index']
            while index<len(path)-1 and np.linalg.norm(pos-path[index])<.18:index+=1
            delta=path[index]-pos;dist=np.linalg.norm(delta);reached=np.linalg.norm(pos-c['goal'])<c['acceptance']['goal_xy_tolerance_m']
            angle_error=wrap(np.arctan2(delta[1],delta[0])-yaw)
            v=0. if reached else min(.22,.7*dist)*max(0.,np.cos(angle_error))
            w=0. if reached else np.clip(2.*angle_error,-.7,.7)
            wl=-(v-w*.3407/2)/.0508;wr=-(v+w*.3407/2)/.0508
            forward=(wl+wr-d.qvel[self.left]-d.qvel[self.right])/2
            turn=(wr-wl-d.qvel[self.right]+d.qvel[self.left])/2
            d.ctrl[self.ai]=np.clip(c['controller_gain_multiplier']*(.3*(wl+wr)/2+.8*forward)/1.5,-1,1)
            d.ctrl[self.ti]=np.clip(c['controller_gain_multiplier']*(.3*(wr-wl)/2+.8*turn)/1.5,-1,1)
            state.update(path_index=index,phase='stop' if reached else 'navigate',chosen_action=d.ctrl.tolist())

class Recorder:
    def __init__(self,m,d,c,out):
        self.m,self.d,self.c,self.out=m,d,c,Path(out)
        self.mask=mujoco.mjtState.mjSTATE_INTEGRATION
        self.names={i:mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,i) or '' for i in range(m.ngeom)}
        self.owners={}
        for i in range(m.ngeom):
            b=m.geom_bodyid[i]
            while m.body_parentid[b]!=0:b=m.body_parentid[b]
            self.owners[i]=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,b) or 'world'
        self.metrics=dict(max_lift_m=0.,bilateral_seconds=0.,target_floor_contact_steps=0,forbidden_contact_steps={},
            max_robot_scene_penetration_m=0.,max_contact_penetration_m=0.,stable_seconds=0.,effective_friction={},
            max_target_angular_speed_rad_s=0.,initial_invalid_contacts=[])
        self.states=[];self.phases=[];self.audit_rows=[];self.contact_stream=None
    def state(self):
        state=np.empty(mujoco.mj_stateSize(self.m,self.mask));mujoco.mj_getState(self.m,self.d,state,self.mask);return state
    def sample(self,phase):
        self.states.append(self.state());self.phases.append(phase)
    def audit(self):
        m,d,c=self.m,self.d,self.c;a=c['acceptance'];v=self.metrics;pads=set();finger=False;support_force=0.;support=False;rows=[]
        for index,contact in enumerate(d.contact):
            i,j=int(contact.geom1),int(contact.geom2);names=[self.names[i],self.names[j]];owners=[self.owners[i],self.owners[j]]
            if not any(o in ('task_book','base','base_link') for o in owners):continue
            f=np.zeros(6);mujoco.mj_contactForce(m,d,index,f)
            penetration=max(0.,-float(contact.dist));v['max_contact_penetration_m']=max(v['max_contact_penetration_m'],penetration)
            pair='|'.join(sorted(names));v['effective_friction'][pair]=contact.friction.tolist()
            if 'task_book' in owners:
                for name in names:
                    if name.startswith('finger') and 'collision' in name:
                        finger=True
                        if f[0]>a['min_bilateral_force_n']:pads.add(name[6])
                if 'floor' in names:v['target_floor_contact_steps']+=1
                if c['support_owner'] in owners and f[0]>0:
                    k=owners.index('task_book');normal=contact.frame[:3]*(1 if k==1 else -1)
                    if normal[2]>.5:support=True;support_force+=float(f[0])*float(normal[2])
            for k in (0,1):
                if owners[k] not in ('base','base_link'):continue
                other=1-k
                allowed=owners[other] in c['allowed_robot_contact_owners'] or names[other] in c['allowed_robot_contact_geoms']
                if not allowed:
                    v['forbidden_contact_steps'][pair]=v['forbidden_contact_steps'].get(pair,0)+1
                    v['max_robot_scene_penetration_m']=max(v['max_robot_scene_penetration_m'],penetration)
            rows.append(dict(g=[i,j],dist=float(contact.dist),force=f.tolist(),friction=contact.friction.tolist(),position=contact.pos.tolist()))
        v['bilateral_seconds']+=c['dt_s'] if len(pads)==2 else 0.
        if c['task']=='pick_place':
            j=m.joint('target_free').id;adr=m.jnt_dofadr[j];speed=float(np.linalg.norm(d.qvel[adr:adr+3]));angular=float(np.linalg.norm(d.qvel[adr+3:adr+6]))
            pos=d.body('task_book').xpos;v['max_lift_m']=max(v['max_lift_m'],float(pos[2]-c['start'][2]))
            v['max_target_angular_speed_rad_s']=max(v['max_target_angular_speed_rad_s'],angular)
            stable=support and not finger and speed<a['max_final_speed_m_s']
        else:
            b=m.body('base_link').id;j=m.body_jntadr[b];adr=m.jnt_dofadr[j];speed=float(np.linalg.norm(d.qvel[adr:adr+2]));angular=0.
            pos=d.xpos[b];stable=np.linalg.norm(pos[:2]-c['goal'][:2])<a['goal_xy_tolerance_m'] and speed<a['max_final_speed_m_s']
        v['stable_seconds']=v['stable_seconds']+c['dt_s'] if stable else 0.
        v.update(final_support_contact=support,final_support_force_n=support_force,final_finger_contact=finger,
            final_speed_m_s=speed,final_angular_speed_rad_s=angular,goal_xy_error_m=float(np.linalg.norm(pos[:2]-c['goal'][:2])))
        self.audit_rows.append([float(d.time),float(d.time-c['dt_s']),speed,angular,support_force,float(finger),float(len(pads)==2),v['goal_xy_error_m']])
        self.contact_stream.write(json.dumps(dict(state_time=float(d.time),solver_time=float(d.time-c['dt_s']),contacts=rows),separators=(',',':'))+'\n')
    def save(self):
        np.savez_compressed(self.out/'trajectory.npz',state=np.asarray(self.states),phase=np.asarray(self.phases),state_spec=int(self.mask),dt=self.c['dt_s'])
        np.savez_compressed(self.out/'audit_1khz.npz',rows=np.asarray(self.audit_rows),columns=np.array(['state_time','solver_time','speed','angular_speed','support_vertical_force','finger_contact','bilateral_contact','goal_error']))
        write_json(self.out/'contact_geom_mapping.json',dict(names=self.names,owners=self.owners))

def configure_pairs(m,c):
    """Explicitly override effective pair friction without altering filtering.

    At contact creation time, MuJoCo chooses these parameters by priority and
    mixing. The declaration below adjusts only matching geom pairs via XML
    before final compilation; record every effective runtime friction value.
    """
    pairs=[]
    if not c['explicit_contact_pairs']:return pairs
    def name(i):return mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,i) or ''
    if c['task']=='pick_place':
        first=[i for i in range(m.ngeom) if name(i).startswith('finger') and 'collision' in name(i)]
        second=[i for i in range(m.ngeom) if name(i).startswith('target_col_')]
    else:
        first=[i for i in range(m.ngeom) if 'wheel' in name(i) and (m.geom_contype[i] or m.geom_conaffinity[i])]
        second=[i for i in range(m.ngeom) if name(i)=='floor' or name(i).startswith('col_explicit_area_rug')]
    for i in first:
        for j in second:
            if m.geom_priority[i]==m.geom_priority[j]:friction=np.maximum(m.geom_friction[i],m.geom_friction[j]);condim=max(m.geom_condim[i],m.geom_condim[j])
            else:
                k=i if m.geom_priority[i]>m.geom_priority[j] else j;friction=m.geom_friction[k];condim=m.geom_condim[k]
            f=[friction[0]*c['friction_multiplier']]*2+[friction[1],friction[2],friction[2]]
            pairs.append(dict(geom1=name(i),geom2=name(j),friction=' '.join(map(str,f)),condim=str(int(condim))))
    if not pairs:raise ValueError('No declared friction pairs matched')
    return pairs

def load_model(out,c,run_root=None):
    from xml.etree import ElementTree as ET
    started=time.monotonic();xml=out/'model.xml'
    if c['explicit_contact_pairs']:
        probe=mujoco.MjModel.from_xml_path(str(xml));pairs=configure_pairs(probe,c)
        root=ET.parse(xml).getroot();contact=root.find('contact')
        if contact is None:contact=ET.SubElement(root,'contact')
        for pair in pairs:
            i=probe.geom(pair['geom1']).id;j=probe.geom(pair['geom2']).id
            # Match baseline parameter mixing; friction alone changes.
            if probe.geom_priority[i]!=probe.geom_priority[j]:
                k=i if probe.geom_priority[i]>probe.geom_priority[j] else j
                solref=probe.geom_solref[k];solimp=probe.geom_solimp[k]
            else:
                w=probe.geom_solmix[i]/max(1e-15,probe.geom_solmix[i]+probe.geom_solmix[j]);solref=w*probe.geom_solref[i]+(1-w)*probe.geom_solref[j];solimp=w*probe.geom_solimp[i]+(1-w)*probe.geom_solimp[j]
            ET.SubElement(contact,'pair',**pair,solref=' '.join(map(str,solref)),solimp=' '.join(map(str,solimp)))
        ET.ElementTree(root).write(xml,encoding='unicode');write_json(out/'declared_pairs.json',pairs);del probe
    code={name:bound(Path(__file__).with_name(name))['sha256'] for name in ['config.py','models.py','runner.py','planner.py']}
    code.update({'v1_'+name:bound(Path(__file__).parent.parent/'embodied_scene_v1'/name)['sha256'] for name in ['runner.py','models.py','package.py']})
    key=digest(dict(xml=bound(xml)['sha256'],source_manifest=bound(PACKAGE/'manifest.json')['sha256'],version=mujoco.__version__,code=code))
    cache=(Path(run_root) if run_root is not None else ROOT)/'cache'/key;cache.mkdir(parents=True,exist_ok=True)
    binary=cache/'model.mjb'
    if binary.exists() and (cache/'COMPLETE.json').exists():m=mujoco.MjModel.from_binary_path(str(binary));hit=True
    else:
        m=mujoco.MjModel.from_xml_path(str(xml));mujoco.mj_saveModel(m,str(binary),None);hit=False
        write_json(cache/'COMPLETE.json',dict(key=key,binary=bound(binary),source=bound(xml),code=code))
    (out/'model.mjb').symlink_to(binary)
    write_json(out/'model_identity.json',dict(key=key,cache_hit=hit,compiled_model=bound(binary),semantics=model_semantics(m)))
    return m,time.monotonic()-started

def run(config,output,resume=False,interrupt_at_step=None,*,run_root=None):
    out=Path(output);began=time.monotonic();rec=None;c=None
    case=config.get('case_id','invalid');ledger(dict(case_id=case,event='attempt_start',output=str(out),resume=resume),root=run_root)
    try:
        c=validate(config)
        if resume:
            if json.loads((out/'request.json').read_text())!=config:raise ValueError('Resume request mismatch')
            identity=json.loads((out/'model_identity.json').read_text());m=mujoco.MjModel.from_binary_path(str(out/'model.mjb'));compile_s=0.
            assert bound(out/'model.mjb')['sha256']==identity['compiled_model']['sha256']
        else:
            c=make_task(config,out);m,compile_s=load_model(out,c,run_root=run_root)
        d=mujoco.MjData(m);rec=Recorder(m,d,c,out)
        if resume:
            saved=np.load(out/'resume.npz');meta=json.loads((out/'resume.json').read_text())
            mujoco.mj_setState(m,d,saved['state'],rec.mask)
            state=meta['controller_state'];rec.metrics=meta['metrics'];rec.states=list(saved['states']);rec.phases=list(saved['phases']);rec.audit_rows=list(saved['audit_rows'])
            driver=Driver(m,d,c,out,meta['controller_plan'])
        else:
            driver=Driver(m,d,c,out)
            state=dict(step=0,path_index=1,phase='reset',chosen_action=d.ctrl.tolist(),random_state=np.random.default_rng(c['seed']).bit_generator.state)
            np.savez_compressed(out/'reset_state.npz',state=rec.state(),state_spec=int(rec.mask))
            rec.sample('reset')
            invalid=[]
            for ct in d.contact:
                owners=[rec.owners[int(ct.geom1)],rec.owners[int(ct.geom2)]]
                if 'task_book' in owners and ct.dist<-.001:invalid.append(dict(owners=owners,dist=float(ct.dist)))
                if c['task']=='navigate' and 'base_link' in owners and not any(o=='explicit_area_rug' for o in owners) and all(rec.names[int(g)]!='floor' for g in (ct.geom1,ct.geom2)) and ct.dist<-.001:invalid.append(dict(owners=owners,dist=float(ct.dist)))
            write_json(out/'initial_contact_audit.json',dict(invalid=invalid))
            if invalid:raise ValueError('Illegal initial interpenetration')
        segment=len(list(out.glob('contacts_1khz_*.jsonl.gz')))
        rec.contact_stream=gzip.open(out/f'contacts_1khz_{segment:02d}.jsonl.gz','wt',compresslevel=3)
        shadow=None;shadow_driver=None;shadow_state=None;resume_equal=True;shadow_steps=0
        limit=min(round(c['max_duration_s']/c['dt_s']),18700 if driver.arm else 60000)
        while state['step']<limit:
            # Test complete controller+integration restoration on an independent branch.
            if state['step']==1000:
                shadow=mujoco.MjData(m);mujoco.mj_setState(m,shadow,rec.state(),rec.mask)
                shadow_driver=Driver(m,shadow,c,out,deepcopy(driver.plan));shadow_state=deepcopy(state)
            driver.action(state);mujoco.mj_step(m,d);state['step']+=1;rec.audit()
            if shadow is not None and shadow_steps<30:
                shadow_driver.action(shadow_state);mujoco.mj_step(m,shadow);shadow_state['step']+=1
                ss=np.empty_like(rec.state());mujoco.mj_getState(m,shadow,ss,rec.mask)
                resume_equal &= np.array_equal(ss,rec.state()) and shadow_state==state;shadow_steps+=1
            if state['step']%20==0:rec.sample(state['phase'])
            if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all() or any(w.number for w in d.warning):break
            if state['step']%1000==0 or state['step']==interrupt_at_step:
                tmp=out/'resume.tmp.npz';np.savez_compressed(tmp,state=rec.state(),states=np.asarray(rec.states),phases=np.asarray(rec.phases),audit_rows=np.asarray(rec.audit_rows));tmp.replace(out/'resume.npz')
                rec.contact_stream.flush()
                write_json(out/'resume.json',dict(controller_state=state,controller_plan=driver.plan,metrics=rec.metrics,contact_segment=segment,state_time=float(d.time),semantics='Full controller phase/path index/action/RNG plus integration state and accumulated audit'))
                if state['step']==interrupt_at_step:
                    ledger(dict(case_id=case,event='intentional_interrupt',step=state['step'],output=str(out)),root=run_root);return dict(status='interrupted')
            if not driver.arm and rec.metrics['stable_seconds']>=c['acceptance']['stable_seconds']:break
        if not np.array_equal(rec.states[-1],rec.state()):rec.sample(state['phase'])
        finite=bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all());warnings=[int(w.number) for w in d.warning]
        exact=restore_check(m,d) if finite and not any(warnings) else False
        engineering=finite and not any(warnings) and exact and resume_equal
        v=rec.metrics;a=c['acceptance']
        success=engineering and v['goal_xy_error_m']<a['goal_xy_tolerance_m'] and v['stable_seconds']+1e-8>=a['stable_seconds'] and not v['forbidden_contact_steps'] and v['max_robot_scene_penetration_m']<a['max_robot_scene_penetration_m']
        if driver.arm:success &= v['max_lift_m']>=a['min_lift_m'] and v['bilateral_seconds']>a['min_bilateral_seconds'] and v['target_floor_contact_steps']==0
        result=dict(schema='scene-robot-episode/v2',task=c,success=bool(success),task_success=bool(success),engineering_success=bool(engineering),
            status='success' if success else ('task_failure' if engineering else 'engineering_failure'),admitted=True,**v,
            finite=finite,warning_counts=warnings,exact_30_step_restore=exact,controller_restore_30_steps_exact=bool(resume_equal),controller_restore_steps=shadow_steps,
            simulation_s=float(d.time),wall_seconds=time.monotonic()-began,compile_seconds=compile_s,model_counts=dict(nq=m.nq,nv=m.nv,nu=m.nu,ngeom=m.ngeom),
            final_state_saved=True,final_target_quaternion=d.body('task_book').xquat.tolist() if driver.arm else None,
            final_xyz=d.body('task_book' if driver.arm else 'base_link').xpos.tolist(),simulator=mujoco.__version__,
            controller_plan=driver.plan,timeout=bool(not driver.arm and state['step']>=limit and not success),
            frame_semantics='50 Hz exact integration states plus terminal; 1 kHz contact at solver time t-dt; no runtime pose writes')
        rec.save();write_json(out/'result.json',result)
    except Exception as exc:
        out.mkdir(parents=True,exist_ok=True)
        write_json(out/'request.json',config)
        if rec is not None and rec.states:rec.save()
        msg=str(exc);status='configuration_rejected' if ('Invalid' in msg or 'Illegal' in msg or 'Outside' in msg or 'Acceptance' in msg) else 'engineering_failure'
        if 'IK did not converge' in msg or 'clearance' in msg or 'path' in msg:status='task_failure'
        result=dict(schema='scene-robot-episode/v2',task=config,success=False,task_success=False,engineering_success=status=='task_failure',status=status,admitted=status!='configuration_rejected',error=msg,traceback=traceback.format_exc(),wall_seconds=time.monotonic()-began)
        write_json(out/'result.json',result)
    finally:
        if rec is not None and rec.contact_stream is not None:rec.contact_stream.close()
    result['logical_exit_code']=0 if result['success'] else (2 if result['status']=='task_failure' else 1)
    result['resource_evidence']=os.environ.get('ROUND2_RESOURCE_DIR')
    result['resource_scope']='bounded service; peak shared by episodes when batched'
    write_json(out/'result.json',result)
    ledger(dict(case_id=case,event='attempt_end',status=result['status'],success=result['success'],result=bound(out/'result.json')),root=run_root)
    print(case,result['status'],result.get('goal_xy_error_m'),result.get('error',''),flush=True)
    return result
