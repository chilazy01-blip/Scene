"""Zero-step exact controller/history restoration for arbitrary proven prefixes."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol import authorize,make_task,read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_transport_native_v1.model import load_model
from .restore_scheduled import restore
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES


def run(root):
    import mujoco as mj
    p=authorize(root);c=read_bound_json(Path(p['case']['path']));trace=read_bound_json(Path(p['prefix_trace']['path']))
    m=load_model(read_bound_json(Path(p['scene']['path']))['model']['path']);m.opt.timestep=.005;d=mj.MjData(m)
    base=np.load(p['reference']['path'],allow_pickle=False);task=make_task(p,mj,m,c,base['q'],base['v']);actions=np.zeros((p['full_ticks']+10,29),dtype=np.float32)
    info=restore(mj,m,d,task,trace,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES),protocol=p)
    q=d.qpos.copy();v=d.qvel.copy();tick=p['prefix_active_ticks'];task.update(tick,d,trace['records'][-1]['substeps'][-1]);task.synchronize(tick,d)
    assert np.array_equal(q,d.qpos) and np.array_equal(v,d.qvel)
    result=dict(passed=not task.failure,new_physics_steps=0,restore=info,stage=task.stage,task_failure=task.failure,physical_state_unchanged=True,protocol=_file_binding(root/'PROTOCOL.json'),implementation=_file_binding(Path(__file__)))
    assert not (root/'RESTORE_PREVIEW.json').exists();safe_save(root/'RESTORE_PREVIEW.json',result);print(result,flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();run(a.root)
