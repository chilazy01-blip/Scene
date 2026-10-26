"""Pose-preserving coordinated arm IK on an isolated MuJoCo query state."""
import numpy as np,mujoco
from scipy.spatial.transform import Rotation
def smooth(x):x=np.clip(x,0.,1.);return x*x*x*(10+x*(-15+6*x))
def yaw(q):w,x,y,z=q;return np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z))
def wrap(x):return (x+np.pi)%(2*np.pi)-np.pi
class Arms:
    def __init__(self,m,c):
        self.m=m;self.d=mujoco.MjData(m);self.qmap=np.array(c['qpos_by_pin'])
        self.ids={side:np.array(c['inspection']['groups'][side+'_arm']) for side in ['left','right']}
        self.body={side:int(m.geom('gripper0_'+side+'_g0_col').bodyid) for side in ['left','right']}
        self.jp=np.zeros((3,m.nv));self.jr=np.zeros((3,m.nv))
        self.ranges={}
        for side,ids in self.ids.items():
            j=[int(np.flatnonzero(m.jnt_qposadr==v)[0]) for v in self.qmap[ids]]
            self.ranges[side]=m.jnt_range[j].copy()
    def poses(self,q):
        self.d.qpos[:]=q;mujoco.mj_kinematics(self.m,self.d)
        return {side:(self.d.xpos[b].copy(),self.d.xmat[b].reshape(3,3).copy()) for side,b in self.body.items()}
    def solve(self,q,targets,iterations=12):
        d=self.d;m=self.m;d.qpos[:]=q
        for _ in range(iterations):
            mujoco.mj_kinematics(m,d);mujoco.mj_comPos(m,d)
            peak=0
            for side,ids in self.ids.items():
                b=self.body[side];pos,rot=targets[side]
                errp=pos-d.xpos[b];errr=Rotation.from_matrix(rot@d.xmat[b].reshape(3,3).T).as_rotvec()
                err=np.r_[errp,errr*.3];peak=max(peak,float(abs(err).max()))
                mujoco.mj_jacBody(m,d,self.jp,self.jr,b)
                jac=np.vstack([self.jp[:,self.qmap[ids]-1],self.jr[:,self.qmap[ids]-1]*.3])
                delta=jac.T@np.linalg.solve(jac@jac.T+np.eye(6)*1e-7,err)
                ratio=min(1.,.12/max(float(abs(delta).max()),1e-12))
                d.qpos[self.qmap[ids]]=np.clip(d.qpos[self.qmap[ids]]+delta*ratio,self.ranges[side][:,0]+.005,self.ranges[side][:,1]-.005)
            if peak<1e-5:break
        mujoco.mj_kinematics(m,d)
        errors={side:dict(position=float(np.linalg.norm(targets[side][0]-d.xpos[b])),rotation=float(np.linalg.norm(Rotation.from_matrix(targets[side][1]@d.xmat[b].reshape(3,3).T).as_rotvec()))) for side,b in self.body.items()}
        return d.qpos.copy(),errors
