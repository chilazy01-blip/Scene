"""Observation-only hooks for actual substeps, contacts, applied torques, and every ONNX call."""
from sage.experiments.embodied_continuous_v2.controller import read,write,sha
from sage.experiments.embodied_contact_recovery_v1.work import R
from pathlib import Path
import os,time,json,hashlib
import numpy as np
import h5py,mujoco,onnxruntime as ort

from .plant_guard import PlantGuard

class Trace:
 def __init__(self,folder,mode='task'):
  self.job=Path(os.environ['NP_JOB']);self.req=read(self.job/'REQUEST.json');self.usage=read(self.job/'USAGE.json');self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
  self.mode=mode;self.step_key='diagnostic_physics_steps' if mode=='diagnostic' else 'task_physics_steps';self.n=0;self.first=None;self.last=None;self.model=None;self.data=None;self.start=time.monotonic();self.buffers={};self.counts={};self.h=h5py.File(self.folder/'TRACE.h5','x');self.h.attrs['schema']='contact-recovery-substep/v2';self.h.attrs['mode']=mode
  self.old_step=mujoco.mj_step;self.old_init=ort.InferenceSession.__init__;self.old_run=ort.InferenceSession.run;self.old_render=mujoco.Renderer.render
  self.first_deviation=None;self.max_penetration=0.;self.max_force=0.;self.max_ext=0.
 def charge(self,key,n=1):
  assert self.usage.get(key,0)+n<=self.req['reservation'].get(key,0),f'job_reservation_{key}'
  self.usage[key]=self.usage.get(key,0)+n
 def append(self,key,value):
  self.buffers.setdefault(key,[]).append(np.array(value,copy=True))
 def flush(self):
  for key,values in self.buffers.items():
   if not values:continue
   a=np.asarray(values)
   if key not in self.h:
    self.h.create_dataset(key,data=a,maxshape=(None,*a.shape[1:]),chunks=True,compression='lzf')
   else:
    d=self.h[key];n=len(d);d.resize(n+len(a),axis=0);d[n:]=a
   values.clear()
  self.h.flush();write(self.job/'USAGE.json',self.usage)
  write(self.folder/'PROGRESS.json',{'physics_steps':self.n,'sim_time':float(self.data.time) if self.data is not None else None,'wall_seconds':time.monotonic()-self.start,'policy_forwards':self.usage.get('wbc_forwards',0),'render_passes':self.usage.get('render_passes',0),'max_penetration_m':self.max_penetration,'max_contact_force_N':self.max_force,'base_xyz':self.data.qpos[:3].tolist() if self.data is not None else None,'object_xyz':self.data.xpos[self.model.body('red_block').id].tolist() if self.model is not None else None})
 def initialize(self,m,d):
  self.model,self.data=m,d;self.plant_guard=PlantGuard(m);assert m.nu==43;assert m.opt.timestep>0
  assert not m.nmocap and not m.neq,'runtime_attachment_model'
  assert np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()
  if self.mode=='task':self.charge('task_attempts')
  write(self.job/'USAGE.json',self.usage)
  mujoco.mj_saveModel(m,str(self.folder/'MODEL.mjb'))
  spec=mujoco.mjtState.mjSTATE_INTEGRATION;state=np.empty(mujoco.mj_stateSize(m,spec));mujoco.mj_getState(m,d,state,spec);self.h.create_dataset('initial_integration_state',data=state)
  write(self.folder/'MODEL.json',{'nq':m.nq,'nv':m.nv,'nu':m.nu,'dt':m.opt.timestep,'integrator':int(m.opt.integrator),'joint_names':[m.joint(i).name for i in range(m.njnt)],'actuator_names':[m.actuator(i).name for i in range(m.nu)],'geom_names':[m.geom(i).name for i in range(m.ngeom)],'model_sha256':sha(self.folder/'MODEL.mjb'),'state_spec':int(spec),'source_model_research_only':True})
 def step(self,m,d,*a,**kw):
  assert not a and not kw,'one_substep_per_hook'
  if self.model is None:self.initialize(m,d)
  assert m is self.model and d is self.data,'no_secondary_dynamic_rollouts'
  self.plant_guard.check(m)
  if self.last is not None:
   assert np.array_equal(d.qpos,self.last[0]) and np.array_equal(d.qvel,self.last[1]) and d.time==self.last[2],'runtime_state_write_detected'
  assert d.time+m.opt.timestep<=300.0000001,'external_300s_limit'
  assert not np.any(d.qfrc_applied) and not np.any(d.xfrc_applied),'external_wrench'
  assert np.isfinite(d.ctrl).all()
  if hasattr(self,'position_provider'):self.append('substep/issued_position_target',self.position_provider())
  if hasattr(self,'nominal_provider'):self.append('substep/nominal_position_target',self.nominal_provider())
  self.charge(self.step_key);self.append('substep/time_before',d.time);self.append('substep/ctrl',d.ctrl)
  spec=mujoco.mjtState.mjSTATE_INTEGRATION;state=np.empty(mujoco.mj_stateSize(m,spec));mujoco.mj_getState(m,d,state,spec);self.append('substep/integration_before',state)
  self.old_step(m,d)
  self.n+=1;self.last=(d.qpos.copy(),d.qvel.copy(),d.time)
  mujoco.mj_getState(m,d,state,spec);self.append('substep/integration_after',state)
  assert np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all(),'nonfinite_dynamics'
  for key,v in [('qpos',d.qpos),('qvel',d.qvel),('qacc',d.qacc),('actuator_force',d.actuator_force),('qfrc_actuator',d.qfrc_actuator),('qfrc_constraint',d.qfrc_constraint),('solver_niter',d.solver_niter)]:self.append('substep/'+key,v)
  contacts=[]
  for i,c in enumerate(d.contact):
   force=np.zeros(6);mujoco.mj_contactForce(m,d,i,force);contacts.append([self.n-1,c.geom1,c.geom2,c.dist,*c.pos,*force]);self.max_penetration=max(self.max_penetration,-float(c.dist));self.max_force=max(self.max_force,float(np.linalg.norm(force[:3])))
  for c in contacts:self.append('contacts/rows',c)
  for i,contact in enumerate(d.contact):
   frame=contact.frame.reshape(3,3);local=np.asarray(contacts[i][7:10]);self.append('contacts/world_force',frame.T@local);self.append('contacts/frame',contact.frame)
  self.append('substep/ncon',d.ncon)
  if self.n%256==0:self.flush()
 def install(self):
  global ACTIVE_TRACE
  ACTIVE_TRACE=self
  tracer=self
  def init(session,path,*a,**k):
   tracer.old_init(session,path,*a,**k);session._np_path=str(path);session._np_sha=sha(path)
  def run(session,names,feeds,*a,**k):
   tracer.charge('wbc_forwards');out=tracer.old_run(session,names,feeds,*a,**k)
   prefix='policy/'+Path(session._np_path).name.replace('.','_');tracer.append(prefix+'/physics_row',tracer.n)
   group=tracer.h.require_group(prefix);group.attrs['source_path']=session._np_path;group.attrs['sha256']=session._np_sha
   for key,value in feeds.items():tracer.append(prefix+'/input/'+key,value)
   for i,value in enumerate(out):tracer.append(prefix+'/output/'+str(i),value)
   return out
  def render(renderer,*a,**k):
   tracer.charge('render_passes');return tracer.old_render(renderer,*a,**k)
  mujoco.mj_step=self.step;ort.InferenceSession.__init__=init;ort.InferenceSession.run=run;mujoco.Renderer.render=render
 def close(self):
  global ACTIVE_TRACE
  ACTIVE_TRACE=None
  self.flush();self.h.close();mujoco.mj_step=self.old_step;ort.InferenceSession.__init__=self.old_init;ort.InferenceSession.run=self.old_run;mujoco.Renderer.render=self.old_render
  report={'plant_parameters_unchanged_each_substep':hasattr(self,'plant_guard') and self.plant_guard.checks==self.n,'plant_guard_checks':self.plant_guard.checks if hasattr(self,'plant_guard') else 0,'plant_sha256':self.plant_guard.sha256 if hasattr(self,'plant_guard') else None,'physics_steps':self.n,'max_penetration_m':self.max_penetration,'max_contact_force_N':self.max_force,'runtime_state_continuity_verified':self.n>0,'external_wrenches_zero':True,'production_accepted':False,'wall_seconds':time.monotonic()-self.start}
  write(self.folder/'TRACE_SUMMARY.json',report);return report

def compare_traces(first,second):
 errors={}; shapes={}
 with h5py.File(Path(first)/'TRACE.h5','r') as a,h5py.File(Path(second)/'TRACE.h5','r') as b:
  paths=[];a.visititems(lambda n,x:paths.append(n) if isinstance(x,h5py.Dataset) else None)
  other=[];b.visititems(lambda n,x:other.append(n) if isinstance(x,h5py.Dataset) else None)
  assert paths==other,'dataset_set_difference'
  for name in paths:
   x,y=a[name],b[name];shapes[name]=[list(x.shape),list(y.shape)]
   if x.shape!=y.shape:errors[name]='shape_mismatch';continue
   delta=0.
   for start in range(0,len(x),128):delta=max(delta,float(np.max(np.abs(x[start:start+128].astype(float)-y[start:start+128].astype(float)),initial=0)))
   errors[name]=delta
 return {'passed':all(v==0 for v in errors.values()),'max_errors':errors,'shapes':shapes,'independent_process_continuous_reintegration_and_policy_recompute':True,'task_acceptance':False}
