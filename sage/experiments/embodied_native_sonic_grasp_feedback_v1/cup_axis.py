"""Fit actual cup wall cross-section; body/AABB origin need not be cup axis."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.posture_screen import load_model,safe_save,read_bound_json,_file_binding

def run(root,source):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);d.qpos[:]=t['records'][-1]['substeps'][-1]['full_qpos_after'];mujoco.mj_forward(m,d);fid=m.flex('payload_surface').id;start=m.flex_vertadr[fid];num=m.flex_vertnum[fid];verts=np.array(d.flexvert_xpos[start:start+num]);pid=m.body('payload').id;low=verts[:,2].min();high=verts[:,2].max();rows=[];rng=np.random.default_rng(753)
    for level in [.35,.5,.65]:
        z=low+(high-low)*level;pts=verts[np.abs(verts[:,2]-z)<.003,:2];assert len(pts)>30;best=None
        for _ in range(1000):
            sample=pts[rng.choice(len(pts),3,replace=False)];A=2*(sample[1:]-sample[0]);b=(sample[1:]**2).sum(1)-(sample[0]**2).sum()
            if abs(np.linalg.det(A))<1e-9:continue
            c=np.linalg.solve(A,b);radius=np.linalg.norm(sample[0]-c)
            if not .02<radius<.065:continue
            residual=np.abs(np.linalg.norm(pts-c,axis=1)-radius);inliers=residual<.0025;score=int(inliers.sum())
            if best is None or score>best[0]:best=(score,c,radius,inliers)
        assert best;subset=pts[best[3]];fit=least_squares(lambda v:np.linalg.norm(subset-v[:2],axis=1)-v[2],np.r_[best[1],best[2]],loss='soft_l1',f_scale=.001);center=fit.x[:2];rows.append(dict(height_fraction=level,z_m=z,slice_vertices=len(pts),inliers=len(subset),center_xy_m=center.tolist(),radius_m=float(fit.x[2]),center_offset_from_body_xy_m=(center-d.xpos[pid,:2]).tolist(),median_radial_fit_error_m=float(np.median(np.abs(fit.fun)))))
    middle=rows[1];safe_save(root/'CUP_AXIS_GEOMETRY.json',dict(new_physics_steps=0,body_origin_m=d.xpos[pid].tolist(),physical_mass_com_m=d.xipos[pid].tolist(),world_mesh_bounds=[verts.min(0).tolist(),verts.max(0).tolist()],wall_sections=rows,selected_axis_offset_world_xy_m=middle['center_offset_from_body_xy_m'],source_model=r['model'],source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='Robust geometry estimate from actual full-mesh vertices; native mass/COM/model unchanged. RANSAC is for wall fitting, not a dynamic parameter sweep or proof of grasp.'))
    print(dict(body=d.xpos[pid].tolist(),sections=rows),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--source',type=Path,required=True);p=a.parse_args();run(p.root,p.source)
