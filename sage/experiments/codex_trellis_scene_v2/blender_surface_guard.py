"""Deterministic two-way surface and UV checks for mesh simplification."""
from __future__ import annotations

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def surface_snapshot(objects):
    vertices, faces, uvs, materials = [], [], [], []
    offset = 0
    for obj in objects:
        mesh = obj.data; mesh.calc_loop_triangles()
        xyz = np.empty(len(mesh.vertices)*3, dtype=np.float64)
        mesh.vertices.foreach_get('co', xyz); xyz = xyz.reshape(-1,3)
        matrix = np.asarray(obj.matrix_world)
        vertices.append(xyz @ matrix[:3,:3].T + matrix[:3,3])
        tri = np.array([t.vertices[:] for t in mesh.loop_triangles], dtype=np.int32)
        faces.append(tri+offset); offset += len(xyz)
        if mesh.uv_layers.active:
            uv = np.empty(len(mesh.loops)*2, dtype=np.float64)
            mesh.uv_layers.active.data.foreach_get('uv',uv); uv=uv.reshape(-1,2)
            loops=np.array([t.loops[:] for t in mesh.loop_triangles],dtype=np.int32)
            uvs.append(uv[loops])
        else:
            uvs.append(np.zeros((len(tri),3,2)))
        materials.extend(str(obj.data.materials[t.material_index].name) if len(obj.data.materials) else '' for t in mesh.loop_triangles)
    v=np.concatenate(vertices); f=np.concatenate(faces); triangles=v[f]
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-20)
    return dict(vertices=v,faces=f,triangles=triangles,normals=normals,uv=np.concatenate(uvs),materials=materials,
                tree=BVHTree.FromPolygons(v.tolist(),f.tolist(),all_triangles=True))


def compare_surfaces(source, candidate, sample_limit=24000):
    diagonal=float(np.linalg.norm(np.ptp(source['vertices'],axis=0)))
    directions=[]
    for a,b in ((source,candidate),(candidate,source)):
        indices=np.unique(np.linspace(0,len(a['faces'])-1,min(sample_limit,len(a['faces'])),dtype=int))
        distances=[]; angles=[]; uv_errors=[]; wrong_material=0; misses=0
        for i in indices:
            point=a['triangles'][i].mean(axis=0)
            location,normal,j,distance=b['tree'].find_nearest(Vector(point))
            if location is None:
                misses+=1;continue
            distances.append(float(distance)/max(diagonal,1e-12))
            angles.append(float(np.degrees(np.arccos(np.clip(np.dot(a['normals'][i],b['normals'][j]),-1,1)))))
            tri=b['triangles'][j]; p=np.array(location)-tri[0]
            e0,e1=tri[1]-tri[0],tri[2]-tri[0]
            d00,d01,d11=np.dot(e0,e0),np.dot(e0,e1),np.dot(e1,e1)
            denominator=d00*d11-d01*d01
            if abs(denominator)>1e-25:
                d20,d21=np.dot(p,e0),np.dot(p,e1)
                v=(d11*d20-d01*d21)/denominator; w=(d00*d21-d01*d20)/denominator
                uv=(1-v-w)*b['uv'][j,0]+v*b['uv'][j,1]+w*b['uv'][j,2]
                uv_errors.append(float(np.linalg.norm(a['uv'][i].mean(axis=0)-uv)))
            wrong_material += a['materials'][i]!=b['materials'][j]
        directions.append(dict(samples=len(indices),misses=misses,max_distance_relative=max(distances,default=float('inf')),
            normal_angle_p95=float(np.percentile(angles,95)) if angles else 180.,
            uv_error_p99=float(np.percentile(uv_errors,99)) if uv_errors else float('inf'),
            material_mismatch_fraction=wrong_material/max(len(indices),1)))
    passed=all(x['misses']==0 and x['max_distance_relative']<=.0005 and x['normal_angle_p95']<=20.
               and x['uv_error_p99']<=.005 and x['material_mismatch_fraction']<=.001 for x in directions)
    return dict(passed=passed,source_diagonal=diagonal,directions=directions,
                limits=dict(max_distance_relative=.0005,normal_angle_p95=20.,uv_error_p99=.005,material_mismatch_fraction=.001),
                scope='deterministic bidirectional triangle-centroid sampling; not a proof of watertightness or all-point equivalence')
