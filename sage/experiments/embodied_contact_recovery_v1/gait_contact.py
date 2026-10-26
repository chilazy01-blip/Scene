"""Temporary command braking for a measured descending swing foot."""
import numpy as np
import mujoco


def command(model,data,requested,state):
    braking=False
    for side in ['left','right']:
        body=model.body(side+'_ankle_roll_link').id
        gs=[g for g in range(model.ngeom) if model.geom_bodyid[g]==body
            and model.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE
            and (model.geom_contype[g] or model.geom_conaffinity[g])]
        if not gs:continue
        g=min(gs,key=lambda g:data.geom_xpos[g,2]-model.geom_size[g,0])
        height=float(data.geom_xpos[g,2]-model.geom_size[g,0])
        jp=np.zeros((3,model.nv));jr=np.zeros_like(jp)
        mujoco.mj_jac(model,data,jp,jr,data.geom_xpos[g],body)
        vz=float(jp[2]@data.qvel)
        if height>.025:state[side]=True
        if state.get(side) and height<.05 and vz<-.12:braking=True
        if height<.004 and abs(vz)<.10:state[side]=False
    if braking:
        state['braking_ticks']=state.get('braking_ticks',0)+1
        return np.clip(requested,[-.2,-.15,-.3],[.2,.15,.3])
    return requested
