"""Read measured hand clearance and arm progress from a completed bounded window."""
import sys
import numpy as np,h5py,mujoco
from .work import E,c,finish
from .safe_approach import hand_bounds
name=sys.argv[1];folder=E/'jobs'/name/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
rows=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 n=len(f['substep/qpos']);q=f['substep/qpos'][:];v=f['substep/qvel'][:]
 for k in sorted(set([0,*range(400,n,400),n-1])):
  d.qpos[:]=q[k];mujoco.mj_forward(m,d);lo,hi=hand_bounds(m,d);g=m.geom('table_top').id;top=float(d.geom_xpos[g,2]+m.geom_size[g,2]);sid=m.site('right_palm').id
  rows.append({'row':k,'time':float(f['substep/time_before'][k])+.0025,'palm_xyz':d.site_xpos[sid].tolist(),'hand_min_z':float(lo[2]),'hand_max_x':float(hi[0]),'table_top_z':top,'hand_vertical_clearance_m':float(lo[2]-top),'base_xyz':q[k,:3].tolist()})
 goals=f['safe_approach/goal'][:].tolist() if 'safe_approach/goal' in f else []
 states=f['safe_approach/stage'][:].tolist() if 'safe_approach/stage' in f else []
report={'physics_steps':0,'source':str(folder),'rows':rows,'stage_goals':goals,'stages':states,'last_hand_clear':rows[-1]['hand_vertical_clearance_m']>=.025,'max_recorded_arm_speed_rps':float(max(np.max(abs(v[:,m.jnt_dofadr[m.joint(side+'_'+name+'_joint').id]])) for side in ['left','right'] for name in ['shoulder_pitch','shoulder_roll','shoulder_yaw','elbow','wrist_roll','wrist_pitch','wrist_yaw'])),'production_accepted':False}
c.write(E/'reports'/(name+'_HAND_REVIEW.json'),report);finish(report)
