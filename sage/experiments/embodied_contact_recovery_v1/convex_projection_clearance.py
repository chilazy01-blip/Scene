"""Certified positive separation lower bound along finite unit projection axes."""
import itertools
import numpy as np
import mujoco
from scipy.spatial import ConvexHull


class ProjectionClearance:
    def __init__(self,model,geoms):
        self.meshes={}
        for g in geoms:
            kind=model.geom_type[g]
            if kind==mujoco.mjtGeom.mjGEOM_BOX:
                vertices=np.array(list(itertools.product([-1.,1.],repeat=3)))*model.geom_size[g]
            elif kind==mujoco.mjtGeom.mjGEOM_MESH:
                mesh=int(model.geom_dataid[g]);first=int(model.mesh_vertadr[mesh])
                vertices=model.mesh_vert[first:first+int(model.mesh_vertnum[mesh])].copy()
            else:raise ValueError(('unsupported_projection_geometry',model.geom(g).name,int(kind)))
            hull=ConvexHull(vertices);normals=hull.equations[:,:3]
            normals=normals[np.linspace(0,len(normals)-1,min(20,len(normals)),dtype=int)]
            self.meshes[g]=(vertices[hull.vertices],normals)

    def gap(self,data,g,h):
        vg,ng=self.meshes[g];vh,nh=self.meshes[h]
        rg=data.geom_xmat[g].reshape(3,3);rh=data.geom_xmat[h].reshape(3,3)
        vg=vg@rg.T+data.geom_xpos[g];vh=vh@rh.T+data.geom_xpos[h]
        axes=np.r_[ng@rg.T,nh@rh.T,rg.T,rh.T,np.eye(3)]
        axes/=np.linalg.norm(axes,axis=1,keepdims=True)
        a=vg@axes.T;b=vh@axes.T
        return float(np.max(np.maximum(b.min(0)-a.max(0),a.min(0)-b.max(0))))
