"""Identify whether measured digit contacts lie on payload sidewall or caps."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish


def main(config_path):
    cfg=c.read(config_path);records=[]
    for name in cfg['jobs']:
        folder=E/'jobs'/name/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));obj=m.body('red_block').id
        with h5py.File(folder/'TRACE.h5','r') as f:rows=f['contacts/rows'][:]
        groups={}
        for r in rows:
            if r[3]>0:continue
            gs=list(map(int,r[1:3]));bs=[int(m.geom_bodyid[g]) for g in gs]
            if obj not in bs:continue
            hand=[i for i,b in enumerate(bs) if m.body(b).name.startswith('right_hand')]
            if not hand:continue
            i=hand[0];digit=m.body(bs[i]).name.split('_')[2];surface=m.geom(gs[1-i]).name;key=digit+'|'+surface
            groups.setdefault(key,[]).append([int(r[0]),float(-r[3]),float(r[7]),float(np.linalg.norm(r[8:10]))])
        records.append({'job':name,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'surfaces':{k:{'contact_rows':len(v),'first_row':v[0][0],'last_row':v[-1][0],'max_penetration_m':max(r[1] for r in v),'normal_force_min_N':min(r[2] for r in v),'normal_force_max_N':max(r[2] for r in v),'normal_force_mean_N':float(np.mean([r[2] for r in v]))} for k,v in groups.items()}})
    report={'new_physics_steps':0,'sources':records,'scope':'Measured contact-surface association; cap-edge fragility is a geometric hypothesis, dynamic counterfactual required.','production_accepted':False};c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
