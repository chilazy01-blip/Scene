"""Freeze original initial states, source lineage and mesh-supported goals."""
from pathlib import Path
import itertools
import numpy as np
import mujoco as mj
from scipy.spatial.transform import Rotation
from .common import ROOT,PREVIOUS,ORIGINAL,safe_save,read_bound_json,_file_binding
from .build_models import OBJECTS
from sage.experiments.embodied_transport_native_v1.model import load_model

def run(key):
    sid,oid=key.split('_');folder=ROOT/'cases_v2'/key;folder.mkdir(parents=True,exist_ok=False)
    scene=read_bound_json(ROOT/'models_v2'/key/'SCENE.json');m=load_model(scene['model']['path']);d=mj.MjData(m)
    desk=m.body('generated_desk').id
    mj.mj_forward(m,d)
    table=np.asarray(d.flexvert_xpos)[np.asarray(m.flex_vertbodyid)==desk]
    top=float(table[:,2].max());surface=table[table[:,2]>=top-.003]
    shift=np.asarray(m.body_pos[desk])-np.array([2.351,2.,.365])
    scene_shift=shift.copy()
    if oid=='cup':shift=shift+np.array([0.,-.02,0.])
    c=read_bound_json(ORIGINAL/'trial_07/CASE.json');c.pop('content_sha256_excluding_this_field',None)
    for field in ('source_root_goal_xy_m','target_root_goal_xy_m','start_xy_m'):
        c[field]=(np.asarray(c[field])+shift[:2]).tolist()
    q=np.asarray(c['initial_robot_qpos']);q[:3]+=shift;c['initial_robot_qpos']=q.tolist()
    dims=np.asarray(OBJECTS[oid]['dimensions']);corners=np.array(list(itertools.product(*[[-x/2,x/2] for x in dims])))
    R=Rotation.from_euler('z',90,degrees=True).as_matrix() if oid!='book' else Rotation.from_euler('y',-90,degrees=True).as_matrix()
    source=np.array([2.1,2.2 if oid!='book' else 2.1,0.])+shift
    source[2]=top-float((corners@R.T)[:,2].min())+.0022
    target=source.copy();target[0]+=.5;target[1]=2.17+shift[1] if oid!='book' else source[1]
    fid=mj.mj_name2id(m,mj.mjtObj.mjOBJ_FLEX,'payload_surface');a=int(m.flex_vertadr[fid]);n=int(m.flex_vertnum[fid])
    local=np.asarray(m.flex_vert[a:a+n]);rot=local@R.T;base=rot[rot[:,2]<=rot[:,2].min()+.003]
    low=surface[:,:2].min(0)-base[:,:2].min(0)+.002
    high=surface[:,:2].max(0)-base[:,:2].max(0)-.002
    source_ok=bool(np.all(source[:2]>=low)&np.all(source[:2]<=high));target_ok=bool(np.all(target[:2]>=low)&np.all(target[:2]<=high))
    quat=Rotation.from_matrix(R).as_quat()[[3,0,1,2]].tolist()
    c.update(case_id=key,object_id=oid,scene_id=sid,source_object_xyz_m=source.tolist(),source_object_quat=quat,target_object_xyz_m=target.tolist(),mug_local_bounds_corners=corners.tolist(),support_top_m=top,world_translation_from_S01_m=shift.tolist(),scene_translation_from_S01_m=scene_shift.tolist(),source_admission_revision="Cup full bottom at old source extended 3.74mm beyond tabletop bound; workcell shifted inward20mm before dynamics, failed admission preserved.",orientation_axis=OBJECTS[oid]['orientation_axis'],orientation_definition='cover normal local X absolute dot world Z' if oid=='book' else 'local Z dot world Z',source_role='development_validation',dataset_split='unassigned',layout_source_group_id='sage_v2_locomotion_20261020_'+sid,asset_lineage_group_id=str(OBJECTS[oid]['asset']),fresh_original_initialization=True,reused_physical_prefix_steps=0,object_assumptions=scene['sources']['object_assumptions'])
    safe_save(folder/'CASE.json',c)
    old=read_bound_json(PREVIOUS/'target_y_minus_30mm/baseline_v2/PROTOCOL.json');b=np.load(old['reference']['path'],allow_pickle=False)
    arrays={k:b[k].copy() for k in b.files};arrays['q'][:,:3]+=shift
    np.savez_compressed(folder/'REFERENCE.npz',**arrays)
    d.qpos[:50]=q;pa=int(m.joint('payload_free').qposadr[0]);d.qpos[pa:pa+7]=[*source,*quat];mj.mj_forward(m,d)
    depth=max([0.]+[-float(x.dist) for x in d.contact])
    admission=dict(schema='generated-grasp-static-admission/v1',case=_file_binding(folder/'CASE.json'),scene=_file_binding(ROOT/'models_v2'/key/'SCENE.json'),reference=_file_binding(folder/'REFERENCE.npz'),source_full_base_supported=source_ok,target_full_base_supported=target_ok,tabletop_bounds_xy=[surface[:,:2].min(0).tolist(),surface[:,:2].max(0).tolist()],feasible_object_origin_xy=[low.tolist(),high.tolist()],initial_max_penetration_m=depth,initial_contacts=len(d.contact),passed=source_ok and target_ok and depth<=.01,physics_steps=0,limitations='Mesh base extent and collision initialization admission only; grasp reachability and dynamic feasibility remain to be tested.',implementation=_file_binding(Path(__file__)))
    safe_save(folder/'ADMISSION.json',admission);print({k:admission[k] for k in ['passed','source_full_base_supported','target_full_base_supported','initial_max_penetration_m']},flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
