"""Zero integration admission at the frozen original task initialization."""
from pathlib import Path
import numpy as np
from .protocol import authorize,make_task,read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_transport_native_v1.model import load_model

def run(root):
    import mujoco as mj
    p=authorize(root);c=read_bound_json(Path(p['case']['path']))
    m=load_model(read_bound_json(Path(p['scene']['path']))['model']['path']);m.opt.timestep=.005;d=mj.MjData(m)
    d.qpos[:50]=c['initial_robot_qpos'];a=int(m.joint('payload_free').qposadr[0]);d.qpos[a:a+7]=[*c['source_object_xyz_m'],*c['source_object_quat']];mj.mj_forward(m,d)
    q=d.qpos.copy();v=d.qvel.copy();base=np.load(p['reference']['path'],allow_pickle=False)
    task=make_task(p,mj,m,c,base['q'],base['v'])
    assert np.array_equal(q,d.qpos) and np.array_equal(v,d.qvel)
    result=dict(passed=not task.failure,new_physics_steps=0,stage=task.stage,task_failure=task.failure,physical_state_unchanged=True,fresh_original_initialization=True,restored_prefix_steps=0,initial_contacts=len(d.contact),maximum_initial_penetration_m=max([0.]+[-float(x.dist) for x in d.contact]),protocol=_file_binding(root/'PROTOCOL.json'),implementation=_file_binding(Path(__file__)))
    if result['maximum_initial_penetration_m'] > .01:raise ValueError('initial penetration exceeds original safety gate')
    assert not(root/'RESTORE_PREVIEW.json').exists();safe_save(root/'RESTORE_PREVIEW.json',result);print(result,flush=True)
