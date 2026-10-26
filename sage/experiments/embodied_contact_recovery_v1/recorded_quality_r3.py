"""Whole saved-trajectory quality, using logged forces and forward kinematics only."""
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,P,finish,c

folder=Path(sys.argv[1]);label=sys.argv[2]
m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
limits=c.read(P/'generated/GLOCAL_NEW/package_r2/CONTRACT.json')['limits']
with h5py.File(folder/'TRACE.h5','r') as f:
 q=f['substep/qpos'][:];v=f['substep/qvel'][:];t=f['substep/time_before'][:]
 initial=f['initial_integration_state'][:];mujoco.mj_setState(m,d,initial,mujoco.mjtState.mjSTATE_INTEGRATION)
 q_before=np.concatenate([d.qpos[None].copy(),q[:-1]],axis=0);v_before=np.concatenate([d.qvel[None].copy(),v[:-1]],axis=0)
 contacts=f['contacts/rows'][:];forces=f['substep/actuator_force'][:];ctrl=f['substep/ctrl'][:]
 world_force=f['contacts/world_force'][:] if 'contacts/world_force' in f else None
n=len(q);dt=m.opt.timestep;last=round(1/dt)
obj=m.body('red_block').id;oa=m.jnt_qposadr[m.joint('red_block_joint').id];od=m.jnt_dofadr[m.joint('red_block_joint').id]
target=m.geom('table_white_top').id
roles=[];side_by_geom={};feet={};foot_body={}
for side in ['left','right']:
 b=m.body(side+'_ankle_roll_link').id;foot_body[side]=b;feet[side]=[g for g in range(m.ngeom) if m.geom_bodyid[g]==b and m.geom_contype[g]]
 for g in feet[side]:side_by_geom[g]=side
for g in range(m.ngeom):
 b=int(m.geom_bodyid[g]);name=m.body(b).name
 ancestors=[];a=b
 while a:ancestors.append(m.body(a).name);a=int(m.body_parentid[a])
 if b==obj:role='object'
 elif m.geom(g).name=='ground':role='floor'
 elif g in side_by_geom:role='foot'
 elif any('hand' in x for x in ancestors):role='hand'
 elif 'base' in ancestors:role='robot'
 else:role='environment'
 roles.append(role)
hand=np.zeros(n,bool);support=np.zeros(n);loads={s:np.zeros(n) for s in feet};positions={s:np.zeros((n,3)) for s in feet};forbidden={}
for i,row in enumerate(contacts):
 k,g,h=map(int,row[:3]);pair={roles[g],roles[h]};loaded=np.linalg.norm(row[7:10])>1e-4 or row[3]<-1e-6
 allowed=pair in ({'foot','floor'},{'hand','object'}) or not bool(pair&{'foot','robot','hand'})
 if loaded and not allowed:
  key='|'.join([m.geom(g).name or str(g),m.geom(h).name or str(h)])
  entry=forbidden.setdefault(key,{'first_step':k,'first_time':float(t[k]),'contact_rows':0,'max_penetration_m':0.,'max_force_N':0.})
  entry['contact_rows']+=1;entry['max_penetration_m']=max(entry['max_penetration_m'],float(-row[3]));entry['max_force_N']=max(entry['max_force_N'],float(np.linalg.norm(row[7:10])))
 if pair=={'hand','object'} and loaded:hand[k]=True
 if target in (g,h) and (m.geom_bodyid[g]==obj or m.geom_bodyid[h]==obj):
  # New traces preserve the contact-frame transformed force. Legacy horizontal-table normal force is explicit fallback.
  support[k]+=float(world_force[i,2]*(1 if m.geom_bodyid[h]==obj else -1)) if world_force is not None else max(0.,float(row[7]))
 if pair=={'foot','floor'}:
  foot=g if roles[g]=='foot' else h;side=side_by_geom[foot];load=max(0.,float(row[7]));loads[side][k]+=load;positions[side][k]+=load*row[4:7]
height={s:np.zeros(n) for s in feet};slip={s:np.zeros(n) for s in feet};margins=[];com_margins=[]
object_geoms=[g for g in range(m.ngeom) if m.geom_bodyid[g]==obj]
for k in range(n):
 d.qpos[:]=q_before[k];mujoco.mj_kinematics(m,d);mujoco.mj_comPos(m,d)
 for side,gs in feet.items():
  assert all(m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE for g in gs)
  height[side][k]=min(d.geom_xpos[g,2]-m.geom_size[g,0] for g in gs)
  if loads[side][k]>=5:
   jp=np.zeros((3,m.nv));mujoco.mj_jac(m,d,jp,None,positions[side][k]/loads[side][k],foot_body[side]);slip[side][k]=np.linalg.norm((jp@v_before[k])[:2])
 if k>=n-last:
  rt=d.geom_xmat[target].reshape(3,3);gaps=[]
  for g in object_geoms:
   rel=rt.T@(d.geom_xpos[g]-d.geom_xpos[target]);rg=rt.T@d.geom_xmat[g].reshape(3,3)
   if m.geom_type[g]==mujoco.mjtGeom.mjGEOM_BOX:ext=abs(rg[:2])@m.geom_size[g]
   else:axis=rg[:,2];ext=m.geom_size[g,1]*abs(axis[:2])+m.geom_size[g,0]*np.sqrt(np.maximum(0,1-axis[:2]**2))
   gaps.append(float(min(m.geom_size[target,:2]-abs(rel[:2])-ext)))
  margins.append(min(gaps));rel=rt.T@(d.xipos[obj]-d.geom_xpos[target]);com_margins.append(float(min(m.geom_size[target,:2]-abs(rel[:2]))))
def episodes(mask):
 starts=np.flatnonzero(mask&~np.r_[False,mask[:-1]]);ends=np.flatnonzero(mask&~np.r_[mask[1:],False])+1
 return list(zip(starts,ends))
events=[];slip_stats={}
for side in feet:
 for start,end in episodes(height[side]>=.01):
  if (end-start)*dt>=.08:events.append({'side':side,'start':float(t[start]),'end':float(t[end-1]+dt),'duration':(end-start)*dt})
 interior=np.zeros(n,bool);margin=round(.04/dt)
 for start,end in episodes(loads[side]>=5):
  if end-start>2*margin:interior[start+margin:end-margin]=True
 samples=slip[side][interior];slip_stats[side]={'samples':len(samples),'p95_mps':float(np.percentile(samples,95)) if len(samples) else None,'max_mps':float(max(samples,default=0)),'raw_loaded_max_mps':float(max(slip[side]))}
events.sort(key=lambda x:x['start']);alternating=[]
for event in events:
 if not alternating or event['side']!=alternating[-1]['side']:alternating.append(event)
counts={s:sum(x['side']==s for x in alternating) for s in feet}
lift=q[:,oa+2]-q[0,oa+2];carried=np.flatnonzero(hand&(lift>=.05));carry=float(np.max(np.linalg.norm(q[carried,oa:oa+2]-q[carried[0],oa:oa+2],axis=1))) if len(carried) else 0.
excess=0.;arm_speed=0.;hand_speed=0.
for j in range(m.njnt):
 if m.jnt_type[j]!=mujoco.mjtJoint.mjJNT_HINGE:continue
 a=m.jnt_qposadr[j];vd=m.jnt_dofadr[j];name=m.joint(j).name
 excess=max(excess,float(np.max(m.jnt_range[j,0]-q[:,a])),float(np.max(q[:,a]-m.jnt_range[j,1])))
 if 'hand' in name:hand_speed=max(hand_speed,float(np.max(abs(v[:,vd]))))
 elif any(p in name for p in ['shoulder','elbow','wrist']):arm_speed=max(arm_speed,float(np.max(abs(v[:,vd]))))
base_tilt=np.arccos(np.clip(1-2*(q[:,4]**2+q[:,5]**2),-1,1));ground=(loads['left']>=5)|(loads['right']>=5)
gap=max(((b-a)*dt for a,b in episodes(~ground)),default=0.)
terminal={'full_second':n>=last,'no_hand':not bool(hand[-last:].any()),'support_fraction_min':float(min(support[-last:])/(m.body_mass[obj]*9.81)),
'footprint_margin_min_m':min(margins),'COM_margin_min_m':min(com_margins),'linear_speed_max_mps':float(np.max(np.linalg.norm(v[-last:,od:od+3],axis=1))),
'angular_speed_max_rps':float(np.max(np.linalg.norm(v[-last:,od+3:od+6],axis=1)))}
metrics={'max_penetration_m':float(max(0,-contacts[:,3].min())),'max_contact_force_N':float(np.max(np.linalg.norm(contacts[:,7:10],axis=1))),
'joint_limit_excess_rad':excess,'max_arm_speed_rps':arm_speed,'max_hand_speed_rps':hand_speed,'max_base_tilt_rad':float(max(base_tilt)),'min_base_height_m':float(min(q[:,2])),
'max_ground_gap_seconds':gap,'swing_events':events,'alternating_counts':counts,'object_max_lift_m':float(max(lift)),'grasped_carry_m':carry,'slip':slip_stats,'terminal':terminal}
gates={'penetration':metrics['max_penetration_m']<=.01,'forbidden_contact':not forbidden,'joint_limits':excess<=limits['joint_limit_tolerance_rad'],'arm_speed':arm_speed<=limits['max_arm_speed_rps'],
'hand_speed':hand_speed<=limits['max_hand_speed_rps'],'base_tilt':max(base_tilt)<=.25,'base_height':min(q[:,2])>=.55,'ground_gap':gap<=.1,
'alternating_steps':min(counts.values())>=2,'lift':max(lift)>=.05,'carry':carry>=.2,'terminal_support':terminal['support_fraction_min']>=.9,'terminal_hand_free':terminal['no_hand'],
'footprint_margin':terminal['footprint_margin_min_m']>=.005,'COM_margin':terminal['COM_margin_min_m']>=.01,'object_final_linear_speed':terminal['linear_speed_max_mps']<=.02,'object_final_angular_speed':terminal['angular_speed_max_rps']<=.1}
gates={k:bool(v) for k,v in gates.items()}
report={'physics_steps':0,'scope':'Every saved400Hz physical state/contact; contact kinematics and timestamps use integration-before state matching logged Euler forces; post-step state used for joint/object motion metrics','source':str(folder),'source_sha256':c.sha(folder/'TRACE.h5'),
'metrics':metrics,'gates':gates,'forbidden_pairs':forbidden,'production_accepted':False,'unresolved':['material/force/transient calibration','complete inherited tracking/reference audit'],'joint_torque_and_finger_position_units_retained':True}
c.write(E/'reports'/(label+'_RECORDED_QUALITY.json'),report);finish(report)
