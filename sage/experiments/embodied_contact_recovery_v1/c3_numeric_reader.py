"""Full C3 numeric LeRobot export and real public reader, with failure labels."""
import os,sys
from pathlib import Path
import numpy as np
import h5py
from .work import E,P,c,finish

work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/C3_complete_numeric_export_01/numeric_frames.h5'
report=c.read(E/'C3_COMPLETE_NUMERIC_DATA_PREFLIGHT.json');meta={'joint_names':report['joint_names'],'cameras':[]}
sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
cache=work/'hf_cache';cache.mkdir();os.environ.update(HF_HOME=str(cache),HF_DATASETS_CACHE=str(cache/'datasets'),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from sage.experiments.embodied_payload_data_v1.dataset_export import features,frame
from sage.experiments.embodied_payload_data_v1.typed_reader import TypedLeRobotDataset
schema=features(meta)
schema['observation.previous_command_valid']={'dtype':'uint8','shape':(1,),'names':['valid']}
schema['episode.task_success']={'dtype':'uint8','shape':(1,),'names':['success']}
def numeric_frame(f,i):
    value=frame(f,i,[])
    value['observation.previous_command_valid']=np.array([f['trajectory/previous_command_valid'][i]],dtype='u1')
    value['episode.task_success']=np.zeros(1,dtype='u1')
    return value
dataset=LeRobotDataset.create(repo_id='local/g1-full-failed-numeric',fps=25,features=schema,root=work/'lerobot',robot_type='G1',use_videos=False,video_backend='pyav')
with h5py.File(source,'r') as f:
    count=len(f['trajectory/timestamp'])
    for i in range(count):dataset.add_frame(numeric_frame(f,i),task='Complete failed research task; contact quality and object placement failed. Numeric-only.',timestamp=i/25)
    dataset.save_episode();dataset.stop_image_writer()
reader=TypedLeRobotDataset(work/'lerobot');assert len(reader)==count
errors={}
with h5py.File(source,'r') as f:
    for i in range(count):
        actual=reader[i]
        for key,expected in numeric_frame(f,i).items():
            got=actual[key].numpy();errors[key]=max(errors.get(key,0.),float(np.max(abs(got.astype(float)-expected.astype(float)))))
    end=float(f.attrs['source_terminal_time_s'])
assert all(v==0 for v in errors.values())
result={'passed':True,'rows':count,'fps':25,'actual_public_reader':type(reader).__name__,'numeric_max_errors':errors,
        'source_terminal_time_s':end,'complete_physical_task_record':True,'task_success':False,
        'images_present':False,'depth_present':False,'production_accepted':False,'task_learning_verified':False,
        'numeric_source_sha256':c.sha(source),'new_physics_steps':0,'new_render_passes':0,'training_updates':0,
        'scope':'Complete failed-task numeric LeRobot episode, not a multimodal or accepted training episode.'}
c.write(E/'C3_NUMERIC_PUBLIC_READER.json',result);finish(result)
