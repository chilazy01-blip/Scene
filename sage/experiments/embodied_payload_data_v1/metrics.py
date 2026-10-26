"""Physical metrics from isolated queries of actual integrated states."""
import numpy as np,mujoco
from sage.experiments.embodied_fb2_repair_v1.quality import measure
class Metrics:
    def __init__(self,m,c):
        self.m=m;self.c=c;self.d=mujoco.MjData(m);self.qmap=np.array(c['qpos_by_pin']);self.gap=0.
        self.feet={}
        for side in ['left','right']:
            b=m.body('robot0_'+side+'_ankle_roll_link').id
            self.feet[side]=[i for i in range(m.ngeom) if m.geom_bodyid[i]==b and (m.geom_contype[i] or m.geom_conaffinity[i])]
        self.floor=float(m.geom_pos[m.geom('floor').id,2])
    def sample(self,live,command,root):
        m,d,c=self.m,self.d,self.c
        d.time=live.time;d.qpos[:]=live.qpos;d.qvel[:]=live.qvel;d.ctrl[:]=live.ctrl;d.qacc_warmstart[:]=live.qacc_warmstart
        mujoco.mj_forward(m,d)
        r=measure(m,d,c['names'],c['roles'],c['limits'],self.qmap,command,root)
        self.gap=0. if r['feet_ground'] else self.gap+m.opt.timestep
        r['ground_gap']=self.gap
        if self.gap>c['limits']['max_ground_gap_seconds']:r['violations'].append('ground_gap')
        load={s:0. for s in self.feet};slip={s:0. for s in self.feet}
        jac=np.zeros((3,m.nv))
        for i,ct in enumerate(d.contact):
            for side,gs in self.feet.items():
                if (ct.geom1 in gs and c['roles'][ct.geom2]=='floor') or (ct.geom2 in gs and c['roles'][ct.geom1]=='floor'):
                    force=np.zeros(6);mujoco.mj_contactForce(m,d,i,force)
                    load[side]+=max(0.,float(force[0]))
                    g=ct.geom1 if ct.geom1 in gs else ct.geom2
                    mujoco.mj_jac(m,d,jac,None,ct.pos,int(m.geom_bodyid[g]))
                    if force[0]>1.:slip[side]=max(slip[side],float(np.linalg.norm((jac@d.qvel)[:2])))
        r['foot_load']=load;r['foot_loaded_slip']=slip
        r['foot_clearance']={side:float((d.geom_xpos[gs,2]-m.geom_size[gs,0]).min()-self.floor) for side,gs in self.feet.items()}
        r['object_position']=d.qpos[50:53].tolist();r['object_linear_speed']=float(np.linalg.norm(d.qvel[49:52]));r['object_angular_speed']=float(np.linalg.norm(d.qvel[52:55]))
        r['hand_object_contacts']=sum(set(row['roles'])=={'hand','object'} and (row['distance']<0 or np.linalg.norm(row['force'][:3])>1e-4) for row in r['contacts'])
        return r
