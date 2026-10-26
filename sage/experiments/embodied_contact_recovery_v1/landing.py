"""Measured swing-foot landing damping through existing leg motor commands."""
import numpy as np
import mujoco


def damp_landing(model,data,damping=80.):
    applied=[]
    for side in ['left','right']:
        body=model.body(side+'_ankle_roll_link').id
        geoms=[g for g in range(model.ngeom) if model.geom_bodyid[g]==body
               and model.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE
               and (model.geom_contype[g] or model.geom_conaffinity[g])]
        if not geoms: continue
        g=min(geoms,key=lambda i:data.geom_xpos[i,2]-model.geom_size[i,0])
        point=data.geom_xpos[g].copy()
        height=point[2]-model.geom_size[g,0]
        jp=np.zeros((3,model.nv));jr=np.zeros_like(jp)
        mujoco.mj_jac(model,data,jp,jr,point,body)
        vz=float(jp[2]@data.qvel)
        if height>.025 or vz>=0: continue
        force=min(100.,damping*(-vz))*float(np.clip((.025-height)/.025,0,1))
        torques=[]
        for name in [side+'_'+part+'_joint' for part in
                     ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']]:
            jid=model.joint(name).id;aid=model.actuator(name).id
            delta=float(np.clip(jp[2,model.jnt_dofadr[jid]]*force,-8,8))
            before=float(data.ctrl[aid])
            data.ctrl[aid]=np.clip(before+delta,*model.actuator_ctrlrange[aid])
            torques.append(float(data.ctrl[aid]-before))
        applied.append([height,vz,force,*torques])
    return applied
