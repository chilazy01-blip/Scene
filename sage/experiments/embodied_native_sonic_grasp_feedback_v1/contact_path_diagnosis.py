"""Compare full-hand reference overlap with actual contact links, zero integration."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .posture_screen import hand_ids,RIGHT_CLOSED,contact_pair,load_model,safe_save,read_bound_json,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    episode=root/'attempt_05/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);h=hand_ids(m);out=[]
    def get(label,q,v=None,target=None):
        d.qpos[:]=q;d.qvel[:]=0 if v is None else v;mujoco.mj_forward(m,d);rows=[]
        for i,c in enumerate(d.contact):
            pair=contact_pair(m,c);names=[x['name'] for x in pair]
            if 'payload_surface' not in names:continue
            other=pair[1-names.index('payload_surface')]
            if 'right_hand_' not in other['body']:continue
            f=np.zeros(6);mujoco.mj_contactForce(m,d,i,f);rows.append(dict(body=other['body'],distance_m=float(c.dist),normal_n=float(f[0]),position_m=c.pos.tolist(),normal_vertical=float(c.frame[2]*(1 if names.index('payload_surface')==1 else -1))))
        out.append(dict(label=label,contacts=rows,maximum_depth_m=max([-x['distance_m'] for x in rows],default=0.),actual_finger_angles=d.qpos[h['qpos']].tolist(),requested_finger_angles=target))
    for tick in [1067,1124,1184,1189,1204,1325]:
        row=t['records'][tick];s=row['substeps'][-1];get('actual_after_tick_'+str(tick),s['full_qpos_after'],s['full_qvel_after'],s['hand_target_rad'])
    src=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full/TRACE.json');old=read_bound_json(src);q=np.array(old['records'][-1]['substeps'][-1]['full_qpos_after']);c=read_bound_json(root/'TOP_PROTOCOL.json')['selected'];from .posture_screen import IK
    ik=IK(mujoco,m);q[ik.qids]=c['ik']['angles_rad'];q[h['qpos']]=[RIGHT_CLOSED.get(n,0)*c['closure'] for n in h['names']];get('private_planned_contact_reference',q)
    safe_save(root/'CONTACT_PATH_DIAGNOSIS.json',dict(new_physics_steps=0,rows=out,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],reference=_file_binding(root/'TOP_PROTOCOL.json'),implementation=_file_binding(Path(__file__)),limitation='Reference overlap is commanded geometry, not a physically executed state or proof of a stable contact path. Actual before/after motor forces are retained in original trace; this check classifies contact links/geometry.'))
    print([{k:x[k] for k in ['label','maximum_depth_m']}|dict(link_depths={b:min(c['distance_m'] for c in x['contacts'] if c['body']==b) for b in set(c['body'] for c in x['contacts'])}) for x in out],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
