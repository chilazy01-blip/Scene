"""Check unused original index-joint reference reserve with native mesh queries."""
import argparse,copy,os,resource
from pathlib import Path
import numpy as np
from .posture_screen import load_model,contact_pair
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    episode=root/'attempt_12/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');case=read_bound_json(Path(r['case']['path']));name='right_hand_index_0_joint';reserve=RIGHT_CLOSED[name]*.5-case['mesh_finger_template'][name]*.5;assert 0<reserve<.03;m=load_model(r['model']['path']);old=m.geom_margin.copy();query=copy.copy(m)
    for gid in range(m.ngeom):
        if m.body(int(m.geom_bodyid[gid])).name.startswith('right_hand_') and (m.geom_contype[gid] or m.geom_conaffinity[gid]):query.geom_margin[gid]=.015
    d=mujoco.MjData(query);qa=int(m.joint(name).qposadr[0]);out=[]
    for tick in [1360,1385,1421,1450,1490]:
        s=t['records'][tick]['substeps'][-1]
        for change in [0.,.005,.01,.02,reserve]:
            d.qpos[:]=s['full_qpos_after'];d.qpos[qa]+=change;mujoco.mj_fwdPosition(query,d);gaps={}
            for contact in d.contact:
                pair=contact_pair(query,contact);names=[a['name'] for a in pair]
                if 'payload_surface' not in names:continue
                other=pair[1-names.index('payload_surface')]
                if other['body'].startswith('right_hand_'):gaps[other['body']]=min(gaps.get(other['body'],1.),float(contact.dist))
            out.append(dict(tick=tick,actual_index_normal_n=s['forces']['index'],virtual_joint_angle_increment_rad=change,query_gaps_m=gaps))
    assert np.array_equal(m.geom_margin,old);safe_save(root/'INDEX_NATIVE_RESERVE_QUERY.json',dict(new_physics_steps=0,original_halfclosed_index0_reference_cap_rad=RIGHT_CLOSED[name]*.5,existing_template_index0_cap_rad=case['mesh_finger_template'][name]*.5,unused_original_reference_reserve_rad=reserve,rows=out,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],implementation=_file_binding(Path(__file__)),actual_model_unchanged=True,limitation='Private mesh signed-distance query at recorded physical states; perturbing private actual joint angles only estimates geometry sensitivity. Does not establish that this reserve will realize a requested force or a successful task. No physical settings or reference bounds changed.'));print(dict(reserve_rad=reserve,rows=out),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
