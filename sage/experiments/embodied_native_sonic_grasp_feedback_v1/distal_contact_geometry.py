"""Locate real contacts along distal capsules; geometry only, no new physics."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol import read_bound_json,safe_save,_file_binding
from .posture_screen import load_model,contact_pair

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    episode=root/'attempt_07/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);w=m.body('right_wrist_yaw_link').id;out=[]
    for tick in [1193,1194,1200,1210,1220,1224]:
        s=t['records'][tick]['substeps'][-1];d.qpos[:]=s['full_qpos_after'];mujoco.mj_forward(m,d);rows=[]
        for c in d.contact:
            pair=contact_pair(m,c);names=[a['name'] for a in pair]
            if 'payload_surface' not in names:continue
            side=names.index('payload_surface');other=pair[1-side]
            if other['body'] not in ('right_hand_thumb_2_link','right_hand_index_1_link','right_hand_middle_1_link'):continue
            gid=int(c.geom[1-side]);a=d.geom_xmat[gid].reshape(3,3)[:,2];center=d.geom_xpos[gid];half=m.geom_size[gid,1];ends=[center-a*half,center+a*half];prox=min(ends,key=lambda x:np.linalg.norm(x-d.xpos[w]));dist=max(ends,key=lambda x:np.linalg.norm(x-d.xpos[w]));direction=(dist-prox)/np.linalg.norm(dist-prox);fraction=float(np.dot(c.pos-prox,direction)/np.linalg.norm(dist-prox))
            rows.append(dict(body=other['body'],position_m=c.pos.tolist(),contact_distance_m=float(c.dist),distal_fraction_from_proximal_end=fraction,proximal_capsule_endpoint_m=prox.tolist(),distal_capsule_endpoint_m=dist.tolist(),normal_on_cup_vertical=float((1 if side==1 else -1)*c.frame[2])))
        out.append(dict(tick=tick,time_s=s['time_after_s'],contacts=rows))
    safe_save(root/'DISTAL_CONTACT_GEOMETRY.json',dict(new_physics_steps=0,rows=out,trace=r['trace'],report=_file_binding(episode/'REPORT.json'),implementation=_file_binding(Path(__file__)),limitation='Only actual-state contact geometry classification. Endpoint projection is not actual load capacity; use independently reconstructed forces.'))
    print([dict(tick=x['tick'],contacts=[{k:c[k] for k in ['body','distal_fraction_from_proximal_end','normal_on_cup_vertical']} for c in x['contacts']]) for x in out],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
