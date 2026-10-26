"""Prepare every numeric frame for the completed failed task, without rendering."""
import os
from pathlib import Path
import h5py,numpy as np,mujoco
from .work import E,finish,c
from .capture_contract import sample_schedule,regression
regression()
work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/C_development_03/episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
names=[m.joint(i).name for i in range(m.njnt) if m.jnt_type[i]==mujoco.mjtJoint.mjJNT_HINGE]
qa=np.array([m.jnt_qposadr[m.joint(n).id] for n in names]);da=np.array([m.jnt_dofadr[m.joint(n).id] for n in names]);aa=np.array([m.actuator(n).id for n in names])
with h5py.File(source/'TRACE.h5','r') as f,h5py.File(work/'numeric_frames.h5','w') as h:
 steps=len(f['substep/time_before']);frames,actions,valid=sample_schedule(steps,m.opt.timestep)
 count=len(frames);q=[];v=[];commands=np.zeros((count,2,43));action_times=np.zeros((count,2));previous=np.zeros((count,43));prevvalid=(frames>0).astype('u1')
 for i,k in enumerate(frames):
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);q.append(d.qpos.copy());v.append(d.qvel.copy())
  if k:previous[i]=f['substep/ctrl'][k-1][aa]
  for j,index in enumerate(actions[i]):
   action_times[i,j]=float(f['substep/time_before'][index]) if valid[i,j] else float(f['substep/time_before'][k])+j*.02
   if valid[i,j]:commands[i,j]=f['substep/ctrl'][index][aa]
 q=np.array(q);v=np.array(v);timestamps=f['substep/time_before'][frames];done=np.zeros(count,'u1');done[-1]=1
 values={'timestamp':timestamps,'joint_position':q[:,qa],'joint_velocity':v[:,da],'previous_command':previous,'previous_command_valid':prevvalid,
         'base_orientation_wxyz':q[:,3:7],'base_gyro_rps':v[:,3:6],'action_chunk':commands,'action_timestamps':action_times,
         'action_valid':valid.astype('u1'),'done':done}
 for k,value in values.items():h.create_dataset('trajectory/'+k,data=value,compression='lzf')
 h.create_dataset('source_substep_indices',data=frames)
 assert np.allclose(np.diff(timestamps),.04,rtol=0,atol=1e-10)
 assert len(frames)==len(range(0,steps,16))
 # Independently compare every pre-integration observation with the previous
 # saved post-integration state, rather than repeating the export extractor.
 for i,k in enumerate(frames):
  if k:
   assert np.array_equal(q[i],f['substep/qpos'][k-1]), ('previous_post_qpos',i)
   assert np.array_equal(v[i],f['substep/qvel'][k-1]), ('previous_post_qvel',i)
 h.attrs['source_task_success']=False
 h.attrs['source_terminal_time_s']=float(f['substep/time_before'][-1])+m.opt.timestep
 h.attrs['production_accepted']=False
 h.attrs['source_failure_reason']='contact_seat_not_stable_and_recorded_quality_failure'
report={'passed':True,'all_saved_physics_rows':steps,'complete25Hz_numeric_rows':count,'last_action_valid':valid[-1].tolist(),'first_previous_command_valid':int(prevvalid[0]),
        'tail_missing_action_zero_and_masked':bool(np.all(commands[~valid]==0)),'episode_end_flag_only_on_last_frame':True,'all_pre_observations_match_independent_previous_post_states':True,'numeric_h5_sha256':c.sha(work/'numeric_frames.h5'),
        'source_trace_sha256':c.sha(source/'TRACE.h5'),'new_render_passes':0,'new_physics_steps':0,'production_accepted':False,'image_capture_status':'not rendered; numeric-only preflight, not a complete visual dataset',
        'candidate_capture_chunks':{'frames_per_chunk':128,'chunk_count':int(np.ceil(count/128)),'separate_rgb_depth_passes_if_qualified':int(count*4)},'joint_names':names}
c.write(E/'C3_COMPLETE_NUMERIC_DATA_PREFLIGHT.json',report);finish(report)
