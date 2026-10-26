"""Measured RGB-D export/reader test from complete saved substep states."""
import os
import sys
import time
from pathlib import Path
import numpy as np
import mujoco
import h5py
from .work import E,finish
from sage.experiments.embodied_continuous_v2 import controller as c


def main(source_name, rows='32', start_seconds='0'):
    source=E/'jobs'/source_name/'episode'
    work=Path(os.environ['CONTINUOUS_JOB_DIR'])
    output=work/'data';output.mkdir()
    canonical=output/'canonical.h5'
    m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
    cams=['overhead','wrist_cam']
    names=[m.joint(i).name for i in range(m.njnt) if m.jnt_type[i]==mujoco.mjtJoint.mjJNT_HINGE]
    qa=np.array([m.jnt_qposadr[m.joint(n).id] for n in names]);da=np.array([m.jnt_dofadr[m.joint(n).id] for n in names]);aa=np.array([m.actuator(n).id for n in names])
    count=int(rows);period=round(.04/m.opt.timestep);chunk=round(.02/m.opt.timestep)
    assert len(names)==43 and abs(period*m.opt.timestep-.04)<1e-10
    renderer=mujoco.Renderer(m,256,256)
    usage={'render_passes':0}
    began=time.monotonic()
    # No physical replay is disguised as rendering/export.
    def no_step(*a,**kw):raise RuntimeError('export cannot integrate')
    mujoco.mj_step=no_step
    try:
        with h5py.File(source/'TRACE.h5','r') as f,h5py.File(canonical,'w') as out:
            times=f['substep/time_before'][:]
            k0=int(np.searchsorted(times,float(start_seconds)))
            ks=k0+np.arange(count)*period
            assert ks[-1]+chunk<len(times)
            states=[];vels=[]
            for k in ks:
                mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION)
                states.append(d.qpos.copy());vels.append(d.qvel.copy())
            q=np.array(states);v=np.array(vels)
            values={'timestamp':times[ks],'joint_position':q[:,qa],'joint_velocity':v[:,da],
                    'previous_command':np.array([f['substep/ctrl'][max(0,k-1)][aa] for k in ks]),
                    'base_orientation_wxyz':q[:,3:7],'base_gyro_rps':v[:,3:6],
                    'action_chunk':np.array([[f['substep/ctrl'][k][aa],f['substep/ctrl'][k+chunk][aa]] for k in ks]),
                    'action_timestamps':np.array([[times[k],times[k+chunk]] for k in ks]),
                    'action_valid':np.ones((count,2),dtype='u1'),'done':np.zeros(count,dtype='u1')}
            for key,value in values.items():out.create_dataset('trajectory/'+key,data=value)
            out.create_dataset('source_substep_indices',data=ks)
            for cam in cams:
                for key,shape,dtype in [('rgb',(count,256,256,3),'u1'),('depth_m',(count,256,256),'f4'),
                                      ('valid',(count,256,256),'u1'),('K',(count,3,3),'f8'),('optical_to_base',(count,4,4),'f8')]:
                    out.create_dataset('cameras/'+cam+'/'+key,shape=shape,dtype=dtype,chunks=True,compression='lzf')
            for i,k in enumerate(ks):
                mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION)
                mujoco.mj_forward(m,d)
                rb=np.zeros(9);mujoco.mju_quat2Mat(rb,d.qpos[3:7]);rb=rb.reshape(3,3)
                for cam in cams:
                    cid=m.camera(cam).id
                    renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam)
                    usage['render_passes']+=1;rgb=renderer.render().copy()
                    renderer.enable_depth_rendering();usage['render_passes']+=1;depth=renderer.render().astype('f4')
                    assert np.isfinite(depth).all() and (depth>0).all()
                    near=float(m.vis.map.znear*m.stat.extent);far=float(m.vis.map.zfar*m.stat.extent)
                    valid=((depth>near)&(depth<far*(1-1e-5))).astype('u1')
                    focal=128/np.tan(np.radians(m.cam_fovy[cid])/2)
                    K=np.array([[focal,0,128],[0,focal,128],[0,0,1]],float)
                    T=np.eye(4);T[:3,:3]=rb.T@d.cam_xmat[cid].reshape(3,3)@np.diag([1,-1,-1]);T[:3,3]=rb.T@(d.cam_xpos[cid]-d.qpos[:3])
                    for key,value in [('rgb',rgb),('depth_m',depth),('valid',valid),('K',K),('optical_to_base',T)]:out['cameras/'+cam+'/'+key][i]=value
                c.write(work/'USAGE.json',usage)
        render_seconds=time.monotonic()-began
    finally:renderer.close()
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from sage.experiments.embodied_payload_data_v1.dataset_export import features,frame
    from sage.experiments.embodied_payload_data_v1.typed_reader import TypedLeRobotDataset
    meta={'joint_names':names,'cameras':cams}
    dataset=LeRobotDataset.create(repo_id='local/native-g1-physical-rgbd',fps=25,features=features(meta),root=output/'lerobot',robot_type='G1',use_videos=False,video_backend='pyav')
    with h5py.File(canonical,'r') as f:
        for i in range(count):dataset.add_frame(frame(f,i,cams),task='Research diagnostic excerpt; task success is not asserted.',timestamp=i/25)
        dataset.save_episode();dataset.stop_image_writer()
    reader=TypedLeRobotDataset(output/'lerobot');assert len(reader)==count
    errors={}
    with h5py.File(canonical,'r') as f:
        for i in range(count):
            actual=reader[i]
            for key,expected in frame(f,i,cams).items():
                got=actual[key].numpy()
                if key.startswith('observation.images.'):got=np.rint(got.transpose(1,2,0)*255).astype('u1')
                errors[key]=max(errors.get(key,0.),float(np.max(np.abs(got.astype(float)-expected.astype(float)))))
            for cam in cams:
                depth=f['cameras/'+cam+'/depth_m'][i];valid=f['cameras/'+cam+'/valid'][i]
                assert depth.dtype==np.float32 and valid.dtype==np.uint8
                assert np.isfinite(depth).all()
    assert all(value==0 for value in errors.values())
    report={'passed':True,'scope':'diagnostic excerpt with real LeRobot read; not a complete accepted training episode',
            'rows':count,'RGBD_hz':25,'size':[256,256],'cameras':cams,'new_physics_steps':0,
            'render_passes':usage['render_passes'],'render_seconds':render_seconds,
            'seconds_per_pass':render_seconds/usage['render_passes'],'exact_public_read_errors':errors,
            'depth':'float32 metric meters with explicit clipping validity mask',
            'action_units_by_joint':{n:('rad_position' if m.actuator_biasprm[a,1]!=0 else 'Nm_torque') for n,a in zip(names,aa)},
            'action_semantics':'Actual mixed actuator ctrl samples at t/t+20ms; full400Hz commands retained in source trace; samples alone are not a zero-order-hold replay',
            'source_trace_sha256':c.sha(source/'TRACE.h5'),'canonical_sha256':c.sha(canonical),
            'production_accepted':False,'task_learning_verified':False}
    c.write(work/'DATA_READ_REPORT.json',report);finish(report,usage)


if __name__=='__main__':main(*sys.argv[1:])
