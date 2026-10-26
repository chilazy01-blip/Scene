"""Per-hand forces and relative motion from the actual integrated step."""
import numpy as np
import mujoco
from ..repair_v2.observations import IntegratedEvidence as PriorEvidence


class IntegratedEvidence(PriorEvidence):
    def prepare(self):
        super().prepare()
        self.pose_before=self.data.qpos.copy()
        self.velocity_before=self.data.qvel.copy()

    def finish(self):
        row=super().finish()
        q,d=self.query,self.data
        hands={s:dict(world_force=np.zeros(3),normal_force=0.,peak_contact_force=0.) for s in q.palms}
        for i,c in enumerate(d.contact):
            ids=[c.geom1,c.geom2];roles=[q.roles[g] for g in ids]
            if set(roles)!={'object','hand'}:continue
            obj=roles.index('object');hand=ids[1-obj]
            side='left' if 'left' in q.names[hand] else 'right'
            force=np.zeros(6);mujoco.mj_contactForce(q.m,d,i,force)
            hands[side]['world_force']+=(c.frame.reshape(3,3).T@force[:3])*(1 if obj==1 else -1)
            hands[side]['normal_force']+=max(0.,float(force[0]))
            hands[side]['peak_contact_force']=max(hands[side]['peak_contact_force'],float(np.linalg.norm(force[:3])))
        rotation=np.zeros(9);mujoco.mju_quat2Mat(rotation,self.pose_before[53:57]);rotation=rotation.reshape(3,3)
        obj=self.pose_before[50:53];vel=self.velocity_before
        relative={};jac=np.zeros((3,q.m.nv))
        object_joint=int(np.flatnonzero(q.m.jnt_qposadr==50)[0])
        object_body=int(q.m.jnt_bodyid[object_joint])
        object_jac=np.zeros((3,q.m.nv));angular_jac=object_jac.copy()
        mujoco.mj_jac(q.m,d,object_jac,angular_jac,obj,object_body)
        omega=angular_jac@vel;object_velocity=object_jac@vel
        for side,body in q.palms.items():
            palm=d.xpos[body].copy();mujoco.mj_jac(q.m,d,jac,None,palm,body)
            relative[side]=dict(position=(rotation.T@(palm-obj)).tolist(),
                speed=float(np.linalg.norm(jac@vel-object_velocity-np.cross(omega,palm-obj))))
            hands[side]['world_force']=hands[side]['world_force'].tolist()
            hands[side]['impulse_Ns']=hands[side]['normal_force']*row['dt']
        row.update(hand_forces=hands,hand_object_relative=relative,object_position=obj.tolist())
        return row
