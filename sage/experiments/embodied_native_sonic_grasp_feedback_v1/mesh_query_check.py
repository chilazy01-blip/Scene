"""Verify native mesh geometry and a separate positive-distance query model."""
import argparse,copy,os,resource
from pathlib import Path
import numpy as np
from .posture_screen import load_model,contact_pair
from .protocol import read_bound_json,safe_save,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(root/'attempt_07/full/REPORT.json');t=read_bound_json(root/'attempt_07/full/TRACE.json');m=load_model(r['model']['path']);orig_margin=m.geom_margin.copy();query=copy.copy(m);ids=[i for i in range(m.ngeom) if m.body(int(m.geom_bodyid[i])).name.startswith('right_hand_') and (m.geom_contype[i] or m.geom_conaffinity[i])];metadata=[]
    for gid in ids:
        assert m.geom_type[gid]==mujoco.mjtGeom.mjGEOM_MESH
        mid=int(m.geom_dataid[gid]);verts=m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid]+m.mesh_vertnum[mid]];metadata.append(dict(geom=m.geom(gid).name,body=m.body(int(m.geom_bodyid[gid])).name,type=int(m.geom_type[gid]),type_name='mjGEOM_MESH',mesh_vertices=len(verts),geom_size_is_mesh_half_extents=m.geom_size[gid].tolist(),mesh_vertex_min=verts.min(axis=0).tolist(),mesh_vertex_max=verts.max(axis=0).tolist()));query.geom_margin[gid]=.015
    def get(model,data,q):
        data.qpos[:]=q;mujoco.mj_fwdPosition(model,data);out={}
        for c in data.contact:
            pair=contact_pair(model,c);names=[x['name'] for x in pair]
            if 'payload_surface' not in names:continue
            other=pair[1-names.index('payload_surface')]
            if other['body'].startswith('right_hand_'):out[other['body']]=min(out.get(other['body'],float('inf')),float(c.dist))
        return out
    a=mujoco.MjData(m);b=mujoco.MjData(query);tests=[]
    for tick in [1193,1200,1220,1224]:
        q=t['records'][tick]['substeps'][-1]['full_qpos_after'];native=get(m,a,q);expanded=get(query,b,q);tests.append(dict(tick=tick,native_min_distances=native,query_min_distances=expanded,overlap_max_difference_m=max([abs(v-expanded[k]) for k,v in native.items()],default=0.)))
    assert np.array_equal(m.geom_margin,orig_margin)
    result=dict(new_physics_steps=0,metadata=metadata,checks=tests,maximum_native_overlap_difference_m=max(x['overlap_max_difference_m'] for x in tests),actual_model_unchanged=True,query_only_margin_m=.015,query_model_never_integrated_or_used_for_actual_control=True,model=r['model'],report=_file_binding(root/'attempt_07/full/REPORT.json'),implementation=_file_binding(Path(__file__)),correction='Native hand collision geoms are mesh7, not capsule3. geom_size are mesh half extents, not capsule radius/half-length. Earlier endpoint-plane, capsule radius/circle and along-capsule fraction inferences are invalid geometric proxies; actual physical traces and independently reconstructed forces used unchanged native meshes and remain valid. Recompute from native mesh vertices and native contact distance queries. Positive query margin is only on a separate copied planning model; native physical model/asset/parameters remain unchanged.')
    safe_save(root/'NATIVE_MESH_GEOMETRY_CORRECTION.json',result);print(dict(metadata=metadata,checks=tests,max_error=result['maximum_native_overlap_difference_m']),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
