"""Reuse completed canonical images; actual LeRobot/depth readback, no render."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import P,E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

source_name,canonical_job=sys.argv[1:]
work=Path(os.environ['CONTINUOUS_JOB_DIR'])
canonical=E/'jobs'/canonical_job/'data/canonical.h5'
sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
os.environ.update(HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from sage.experiments.embodied_payload_data_v1.dataset_export import features,frame
from sage.experiments.embodied_payload_data_v1.typed_reader import TypedLeRobotDataset
source=E/'jobs'/source_name/'episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'))
names=[m.joint(i).name for i in range(m.njnt) if m.jnt_type[i]==mujoco.mjtJoint.mjJNT_HINGE]
cams=['overhead','wrist_cam'];meta={'joint_names':names,'cameras':cams}
out=work/'lerobot'
dataset=LeRobotDataset.create(repo_id='local/native-g1-physical-rgbd',fps=25,features=features(meta),root=out,robot_type='G1',use_videos=False,video_backend='pyav')
with h5py.File(canonical,'r') as f:
    count=len(f['trajectory/timestamp'])
    assert np.allclose(np.diff(f['trajectory/timestamp'][:]),.04,rtol=0,atol=1e-10)
    for i in range(count):dataset.add_frame(frame(f,i,cams),task='Research failure excerpt; no successful task or production claim.',timestamp=i/25)
    dataset.save_episode();dataset.stop_image_writer()
reader=TypedLeRobotDataset(out);assert len(reader)==count
errors={};depth_rows=0
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
            assert depth.shape==valid.shape==(256,256) and np.isfinite(depth).all()
            depth_rows+=1
assert all(v==0 for v in errors.values())
report={'passed':True,'rows':count,'actual_depth_reads':depth_rows,'RGBD_hz':25,'cameras':cams,
        'image_size':[256,256],'new_render_passes':0,'new_physics_steps':0,'training_updates':0,
        'scope':'diagnostic failure excerpt; complete source trial independently audited',
        'public_numeric_RGB_max_errors':errors,'canonical_sha256':c.sha(canonical),
        'source_trace_sha256':c.sha(source/'TRACE.h5'),'export_root':str(out),
        'action_units_by_joint':{n:('rad_position' if m.actuator_biasprm[m.actuator(n).id,1]!=0 else 'Nm_torque') for n in names},
        'action_semantics':'Actual mixed actuator ctrl at t/t+20ms; source retains all400Hz commands; do not assume sample-and-hold replay',
        'depth_semantics':'float32 meters; clipping validity mask; no depth renormalization',
        'production_accepted':False,'task_learning_verified':False}
c.write(E/'GENERATOR_DATA_CONTRACT.json',report);finish(report)
