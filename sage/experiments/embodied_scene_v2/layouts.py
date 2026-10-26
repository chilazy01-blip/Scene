"""Seeded rigid layout derivations, admitted by existing scene contracts."""
from copy import deepcopy
import json
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.codex_trellis_scene_v2.validator import validate_layout
from sage.experiments.embodied_scene_v1.package import bound,rigid
from .config import ROOT,PACKAGE,default,write_json,digest

SOURCE_PLAN=ROOT.with_name('bedroom_composition_detail_20260909_v1')/'mainline_full_v2/physics/layout_plan_physics_final.json'
WORKSPACE=['explicit_desk','explicit_office_chair','desk_monitor','desk_mug','desk_plant','desktop_tower','desk_floor_lamp']

def derive(plan,objects,dx,dy,yaw,chair_xy,chair_yaw,storage_y):
    p=deepcopy(plan);poses={};pivot=np.asarray(objects['explicit_desk']['pose_z_up'])[:3,3]
    t=np.eye(4);t[:3,:3]=Rotation.from_euler('z',yaw,degrees=True).as_matrix();t[:3,3]=pivot+np.array([dx,dy,0])-t[:3,:3]@pivot
    for name in WORKSPACE:poses[name]=t@np.asarray(objects[name]['pose_z_up'])
    chair=poses['explicit_office_chair'];chair[:2,3]+=chair_xy
    chair[:3,:3]=Rotation.from_euler('z',chair_yaw,degrees=True).as_matrix()@chair[:3,:3]
    storage=np.asarray(objects['wardrobe_storage_box']['pose_z_up']);storage[1,3]+=storage_y;poses['wardrobe_storage_box']=storage
    for obj in p['objects']:
        if obj['id'] not in poses:continue
        pose=poses[obj['id']];obj.update(x=float(pose[0,3]),y=float(pose[1,3]),yaw=float(np.degrees(np.arctan2(pose[1,0],pose[0,0]))))
    for name,pose in poses.items():rigid(pose)
    return p,{name:pose.tolist() for name,pose in poses.items()},t

def prepare():
    if (ROOT/'cases.json').exists():raise ValueError('Frozen cases already exist')
    source=json.loads(SOURCE_PLAN.read_text());objects=json.loads((PACKAGE/'objects.json').read_text())
    basecheck=validate_layout(source)
    proposals=[];layouts=[];rng=np.random.default_rng(20260913)
    for i in range(160):
        if i==0:params=[0.,0.,0.,[0.,0.],0.,0.]
        else:params=[*rng.uniform(-.1,.1,2),float(rng.uniform(-5,5)),rng.uniform(-.1,.1,2).tolist(),float(rng.uniform(-10,10)),float(rng.uniform(-.08,.08))]
        plan,poses,t=derive(source,objects,*params);check=validate_layout(plan)
        violations=check.get('violations',[])
        # Preserve all existing mandatory geometry/relationship gates.
        rejected=[v for v in violations if v.get('severity') in ('hard','soft')]
        row=dict(proposal_index=i,seed=20260913,parameters=params,accepted=not rejected,violations=rejected,validation=check)
        proposals.append(row)
        if rejected:continue
        lid=f'L{len(layouts):02d}'
        directory=ROOT/'layouts'/lid;directory.mkdir(parents=True,exist_ok=False)
        write_json(directory/'layout_plan.json',plan);write_json(directory/'validation.json',check)
        # Rigid transforms preserve source meshes, local semantic W/D/H and up/front.
        axis=[]
        for name,old in objects.items():
            pose=np.asarray(poses.get(name,old['pose_z_up']));axis.append(dict(id=name,local_dimensions_m=old['dimensions_local_m'],proper_rigid=bool(np.allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),atol=1e-8)),unchanged_local_mesh=True))
        write_json(directory/'axis_audit.json',axis)
        row=dict(layout_id=lid,split='development' if len(layouts)<4 else 'holdout',proposal_index=i,object_poses=poses,workspace_transform=t.tolist(),parameters=params,source=bound(SOURCE_PLAN))
        layouts.append(row)
        if len(layouts)==8:break
    write_json(ROOT/'LAYOUT_PROPOSALS.json',dict(cap=160,proposals=proposals,base_validation=basecheck,admitted=len(layouts),no_robot_planning_or_rollout_filter=True))
    cases=[]
    initializations=[dict(nav_xy=[0,0],nav_yaw=0,book_xy=[0,0],goal_xy=[0,0]),
        dict(nav_xy=[-.12,.12],nav_yaw=15,book_xy=[.018,-.012],goal_xy=[-.012,.012]),
        dict(nav_xy=[.12,-.12],nav_yaw=-15,book_xy=[-.018,.012],goal_xy=[.012,-.012])]
    for layout in layouts:
        t=np.asarray(layout['workspace_transform']);angle=np.arctan2(t[1,0],t[0,0])
        def world(xyz):return (t@np.r_[xyz,1])[:3].tolist()
        for ii,init in enumerate(initializations):
            for task in ['navigate','pick_place']:
                for cv,variant in [('C0','baseline'),('C1','repaired')]:
                    name=f"{layout['layout_id']}__I{ii}__{task}__{cv}";c=default(task,name)
                    c.update(layout_id=layout['layout_id'],split=layout['split'],initialization_id=f'I{ii}',scene_variant=variant,object_poses=layout['object_poses'],seed=2026091300+len(cases))
                    c['arm_base']=world(c['arm_base']);c['arm_yaw_rad']+=angle;c['grasp_yaw_rad']+=angle
                    if task=='navigate':
                        c['goal']=world([*c['goal'],0])[:2];c['start'][:2]=(np.asarray(c['start'][:2])+init['nav_xy']).tolist();c['start_yaw_rad']+=np.deg2rad(init['nav_yaw'])
                    else:
                        c['start']=world((np.asarray(c['start'])+[*init['book_xy'],0]).tolist());c['goal']=world((np.asarray(c['goal'])+[*init['goal_xy'],0]).tolist());c['start_yaw_rad']+=angle
                        # Check full target XY footprint against its designated tabletop.
                        desk=np.asarray(c['object_poses']['explicit_desk']);half=np.asarray(objects['explicit_desk']['dimensions_local_m'])[:2]/2
                        for key in ['start','goal']:
                            local=np.linalg.inv(desk)@np.r_[c[key],1]
                            if np.any(np.abs(local[:2])+[.08,.015]>half+1e-7):raise ValueError('Target footprint leaves table')
                    c['parent_local_coordinates']=dict(workspace_transform=layout['workspace_transform'],initialization=init)
                    cases.append(c)
    write_json(ROOT/'layouts.json',layouts);write_json(ROOT/'cases.json',cases)
    write_json(ROOT/'CASE_FREEZE.json',dict(cases=bound(ROOT/'cases.json'),layouts=bound(ROOT/'layouts.json'),initializations=initializations,planned_conditions=96,realized_conditions=len(cases),missing_conditions=96-len(cases),reason_if_short='Original mandatory layout gates; never filter A*/IK' if len(cases)<96 else None))
    print('Frozen',len(layouts),'layouts',len(cases),'cases from',len(proposals),'proposals',flush=True)
