"""Recover the measured local grasp-center calibration from archived geometry."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
folder=R/'jobs/A_target_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
# Runner performs2s settle,0.8s close,0.5s hold before measuring this local centroid.
row=1319;sid=m.site('right_palm').id if mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_SITE,'right_palm')>=0 else None
if sid is None:
 sites=[m.site(i).name for i in range(m.nsite) if 'palm' in m.site(i).name and 'right' in m.site(i).name]
 assert len(sites)==1;sid=m.site(sites[0]).id
with h5py.File(folder/'TRACE.h5','r') as f:q=f['substep/qpos'][row-1];v=f['substep/qvel'][row-1];t=float(f['substep/time_before'][row])+.0025
assert abs(t-3.3)<1e-8
d.qpos[:]=q;d.qvel[:]=v;mujoco.mj_forward(m,d);p=d.site_xpos[sid].copy();rot=d.site_xmat[sid].reshape(3,3).copy()
links=['right_hand_index_1_link','right_hand_middle_1_link','right_hand_thumb_2_link'];local=[rot.T@(d.xpos[m.body(n).id]-p) for n in links];offset=np.mean(local,axis=0)
assert np.max(abs(offset-np.array([.038,.043,-.006])))<.001
# Local link centroid is invariant under rigid body translation/rotation of the arm.
original=d.qpos.copy();qa=m.jnt_qposadr[m.joint('right_elbow_joint').id];d.qpos[qa]-=.21;mujoco.mj_forward(m,d)
p2=d.site_xpos[sid];r2=d.site_xmat[sid].reshape(3,3);offset2=np.mean([r2.T@(d.xpos[m.body(n).id]-p2) for n in links],axis=0)
error=float(np.max(abs(offset-offset2)));assert error<1e-12
report={'physics_steps':0,'source_trace':str(folder/'TRACE.h5'),'source_sha256':c.sha(folder/'TRACE.h5'),'source_model_sha256':c.sha(folder/'MODEL.mjb'),'source_row':row,'measurement_time_s':t,'geometry_time_s':t-.0025,'geometry_semantics':'Euler derived geometry at integration-before state; exactly matches source centroid read after mj_step','site_name':m.site(sid).name,'link_names':links,'local_centroid_m':offset.tolist(),'stow_rigid_transform_invariance_error_m':error,'provenance':'Archived same-robot measured closed-hand local geometry; its old self-contact is not accepted as new task data. Reusing this calibration avoids repeating empty-hand self-collision. Actual grasp/carry still require separate qualification.','dynamic_admission':False}
c.write(E/'ARCHIVED_GRASP_CENTER_CALIBRATION_R2.json',report)
contract=c.read(R.parent/'generated/GLOCAL_NEW/package_r2/CONTRACT.json')
with h5py.File(E/'jobs/C_development_01r/episode/TRACE.h5','r') as f:targets=f['substep/nominal_position_target'][0]
legs={n:float(targets[i]) for i,n in enumerate(contract['joint_names']) if any(t in n for t in ['hip','knee','ankle'])}
assert len(legs)==12
c.write(E/'INTERPOLATION_INITIAL_TARGETS.json',{'source':str(E/'jobs/C_development_01r/episode/TRACE.h5'),'source_row':0,'leg_position_targets_rad':legs,'purpose':'Exact causal interpolation initial memory used in admitted bounded startup windows; no inference or dynamic state replacement'})
finish(report)
