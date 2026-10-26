"""An explicit new native-scene adaptation, without source-fidelity claims."""
from pathlib import Path
import hashlib,json
import numpy as np
import pyarrow.parquet as pq

def load_benchmark(directory):
    root=Path(directory)
    info=json.loads((root/'info.json').read_text())
    d=pq.read_table(root/'episode_000000.parquet').to_pydict()
    a=lambda k:np.asarray(d[k])
    config=info['script_config'];dt=1./config['control_frequency']
    lengths=a('observation.sim.mujoco_state_len').reshape(-1)
    seeds=a('observation.sim.seed').reshape(-1)
    if not np.all(lengths==113) or not np.all(seeds==111): raise ValueError('fixed sample identity mismatch')
    arrays=dict(states=a('observation.sim.mujoco_state')[:,:113],actions=a('action'),navigate=a('teleop.navigate_command'),height=a('teleop.base_height_command').reshape(-1),wrist=a('action.eef'),upper=a('observation.sim.target_upper_body_pose'))
    n=len(arrays['states']);shapes=dict(states=(n,113),actions=(n,43),navigate=(n,3),height=(n,),wrist=(n,14),upper=(n,31))
    for k,v in arrays.items():
        if v.shape!=shapes[k] or not np.isfinite(v).all():raise ValueError('invalid array:'+k)
    if n!=922 or not np.allclose(np.diff(arrays['states'][:,0]),dt,atol=1e-9,rtol=0):raise ValueError('source clock or length mismatch')
    if config['robot']!='G1' or config['task_name']!='LMBoxTableToShelf':raise ValueError('wrong task or robot')
    return dict(arrays=arrays,config=config,seed=int(seeds[0]),count=n-1,control_dt=dt,parquet_sha256=hashlib.sha256((root/'episode_000000.parquet').read_bytes()).hexdigest(),source_fidelity_verified=False)

def native_scene(source):
    from humanoidmimicgen.dataset_playback import PlaybackConfig
    from humanoidmimicgen.wbc_runtime import get_env
    c=PlaybackConfig.from_dict(source['config'])
    c.save_video=c.enable_onscreen=c.enable_offscreen=False
    c.sim_frequency=200
    env=get_env(c,onscreen=False,offscreen=False)
    env.reset(seed=source['seed'])
    env.reset_to(dict(states=source['arrays']['states'][0].copy()))
    return env
