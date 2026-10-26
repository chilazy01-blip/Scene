"""Analytic native hand-mesh support points over the actual table box.

An approach guard uses actual point velocity. Its conservative trigger is not a
certified braking envelope; validation status is exposed, never fabricated.
"""
import itertools
import numpy as np
import mujoco


class TableApproachGuard:
    def __init__(self,model,margin=.02,reaction_seconds=.025,lookahead_seconds=.15):
        self.model=model;self.data=mujoco.MjData(model)
        self.table=model.geom('table_collider_box_f3b4e739').id
        self.margin=margin;self.reaction=reaction_seconds;self.lookahead=lookahead_seconds
        self.meshes=[]
        for g in range(model.ngeom):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g) or ''
            if not name.startswith('gripper0_') or not name.endswith('_col') or not (model.geom_contype[g] or model.geom_conaffinity[g]):continue
            kind=int(model.geom_type[g]);size=model.geom_size[g]
            if kind==mujoco.mjtGeom.mjGEOM_MESH:
                mid=model.geom_dataid[g];start=model.mesh_vertadr[mid];count=model.mesh_vertnum[mid]
                vertices=model.mesh_vert[start:start+count].copy()
            else:
                if kind==mujoco.mjtGeom.mjGEOM_SPHERE:extent=np.repeat(size[0],3)
                elif kind==mujoco.mjtGeom.mjGEOM_CAPSULE:extent=np.array([size[0],size[0],size[1]+size[0]])
                elif kind==mujoco.mjtGeom.mjGEOM_CYLINDER:extent=np.array([size[0],size[0],size[1]])
                elif kind in (mujoco.mjtGeom.mjGEOM_BOX,mujoco.mjtGeom.mjGEOM_ELLIPSOID):extent=size.copy()
                else:raise ValueError('unsupported_hand_collision_primitive:'+name)
                vertices=np.array(list(itertools.product([-1.,1.],repeat=3)))*extent
            self.meshes.append((g,name,vertices))
        if not self.meshes:raise ValueError('no_hand_meshes')

    def evaluate(self,qpos,qvel):
        m,d=self.model,self.data;d.qpos[:]=qpos;d.qvel[:]=qvel
        mujoco.mj_kinematics(m,d);mujoco.mj_comPos(m,d)
        table_rotation=d.geom_xmat[self.table].reshape(3,3);normal=table_rotation[:,2]
        center=d.geom_xpos[self.table];size=m.geom_size[self.table]
        rows=[];safe=True
        for gid,name,vertices in self.meshes:
            world=vertices@d.geom_xmat[gid].reshape(3,3).T+d.geom_xpos[gid]
            local=(world-center)@table_rotation
            # A projected AABB overlap is deliberately conservative near table edges.
            if np.any(local[:,:2].max(axis=0)<-size[:2]) or np.any(local[:,:2].min(axis=0)>size[:2]):continue
            kind=int(m.geom_type[gid]);rotation=d.geom_xmat[gid].reshape(3,3)
            nlocal=rotation.T@normal;dimensions=m.geom_size[gid]
            if kind in (mujoco.mjtGeom.mjGEOM_MESH,mujoco.mjtGeom.mjGEOM_BOX):
                point=world[int(np.argmin(local[:,2]))]
            else:
                if kind==mujoco.mjtGeom.mjGEOM_SPHERE:support=-dimensions[0]*nlocal
                elif kind==mujoco.mjtGeom.mjGEOM_CAPSULE:
                    support=-dimensions[0]*nlocal;support[2]-=np.sign(nlocal[2])*dimensions[1]
                elif kind==mujoco.mjtGeom.mjGEOM_CYLINDER:
                    support=np.r_[-dimensions[0]*nlocal[:2]/max(np.linalg.norm(nlocal[:2]),1e-15),-np.sign(nlocal[2])*dimensions[1]]
                else:support=-dimensions*dimensions*nlocal/max(np.linalg.norm(dimensions*nlocal),1e-15)
                point=d.geom_xpos[gid]+rotation@support
            gap=float(normal@(point-center)-size[2])
            jac=np.zeros((3,m.nv));mujoco.mj_jac(m,d,jac,None,point,int(m.geom_bodyid[gid]))
            speed=float(normal@jac@d.qvel);closing=max(0.,-speed)
            required=self.margin+closing*(self.reaction+self.lookahead)
            risk=gap<0 or (gap<required and closing>.005)
            safe=safe and not risk
            rows.append(dict(geom=name,gap_m=gap,normal_velocity_mps=speed,
                             trigger_distance_m=required,risk=risk))
        return dict(safe_to_approach=bool(safe),points=rows,
                    braking_envelope_certified=False,
                    method='measured_velocity_lookahead_trigger_requires_dynamic_validation')
