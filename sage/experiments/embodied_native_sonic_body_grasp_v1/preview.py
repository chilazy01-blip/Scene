"""Restore the exact early prefix and validate open-hand approach/closure geometry."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol import authorize,make_task,read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group


def run(root):
    import mujoco as mj
    p=authorize(root);c=read_bound_json(Path(p['case']['path']));trace=read_bound_json(Path(p['prefix_trace']['path']))
    m=load_model(p['scene']['path'] if False else read_bound_json(Path(p['scene']['path']))['model']['path']);m.opt.timestep=.005;d=mj.MjData(m)
    base=np.load(p['reference']['path'],allow_pickle=False);task=make_task(p,mj,m,c,base['q'],base['v']);actions=np.zeros((p['full_ticks']+10,29),dtype=np.float32)
    info=restore(mj,m,d,task,trace,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES))
    before=d.qpos.copy();velocity=d.qvel.copy();last=trace['records'][-1]['substeps'][-1]
    task.update(980,d,last);task.synchronize(980,d)
    assert np.array_equal(before,d.qpos) and np.array_equal(velocity,d.qvel)
    h=hand_ids(m);private=mj.MjData(m);bad=[];goal=np.array(c['body_grasp_wrist_goal_m']);R=np.array(c['body_grasp_rotation']);origin=d.xpos[task.wrist].copy()
    def inspect(q,kind,alpha):
        private.qpos[:]=q;mj.mj_fwdPosition(m,private)
        for co in private.contact:
            pair=contact_pair(m,co);names=[x['name'] for x in pair];bodies=[x['body'] for x in pair]
            if co.dist>=-.001:continue
            if 'payload_surface' in names and any(x.startswith('right_hand_') or x=='right_wrist_yaw_link' for x in bodies):
                bad.append(dict(kind=kind,fraction=alpha,pair=pair,depth=-float(co.dist)))
            elif any(n.startswith('scene_collision_') for n in names) and any(x.startswith('right_hand_') for x in bodies):bad.append(dict(kind=kind,fraction=alpha,pair=pair,depth=-float(co.dist)))
    fit=None
    for alpha in np.linspace(0,1,21):
        fit=task.ik.solve(before,origin*(1-alpha)+goal*alpha,R,max_evaluations=150)
        if fit['position_error_m']>.01 or fit['orientation_error_rad']>.05:bad.append(dict(kind='IK',fraction=float(alpha),fit=fit));continue
        q=before.copy();q[task.armq]=fit['angles_rad'];q[h['qpos']]=0;inspect(q,'open_approach',float(alpha))
    for alpha in np.linspace(0,1,31):
        q=before.copy();q[task.armq]=fit['angles_rad'];q[h['qpos']]=[c['equilibrium_physical_touch_rad'].get(n,0.)*alpha for n in h['names']];inspect(q,'finger_closure',float(alpha))
    result=dict(passed=not task.failure and not bad,new_physics_steps=0,restore=info,first_stage=task.stage,
        first_reference_origin_m=task.path['origin'].tolist(),goal_m=task.path['goal'].tolist(),
        physical_qpos_qvel_unchanged=True,bad=bad,task_failure=task.failure,
        protocol=_file_binding(root/'PROTOCOL.json'),implementation=_file_binding(Path(__file__)))
    assert not (root/'PREVIEW.json').exists();safe_save(root/'PREVIEW.json',result)
    print(dict(passed=result['passed'],bad_count=len(bad),first_bad=bad[:3],task_failure=task.failure),flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();run(a.root)
