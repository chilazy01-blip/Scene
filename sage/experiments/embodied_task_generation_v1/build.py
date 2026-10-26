"""Extract an isolated release model from a fresh public-generator GLB."""
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from sage.experiments.embodied_scene_quality_v1.contracts import read, require, write_new, digest, fingerprint
from sage.experiments.embodied_scene_quality_v2.contracts import reference
from sage.experiments.embodied_scene_quality_v2.geometry import rays, box_heights, fidelity, fidelity_passed, vec
from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry, _read_glb, _hull
from .planner import corners


def pose(obj):
    matrix=np.eye(4);matrix[:3,:3]=Rotation.from_euler('z',obj['yaw'],degrees=True).as_matrix()
    matrix[:3,3]=[obj['x'],obj['y'],obj.get('z',0)+obj['dimensions']['height']/2]
    return matrix


def extract(generator, target_asset_id, support_asset_id):
    plan=read(generator/'layout_plan_final.json');summary=read(generator/'run_summary.json')
    require(summary['profile_complete'] and read(generator/'validation_final.json')['ok'], 'generator_not_complete')
    require(plan['coordinate_contract']['units']=='m' and plan['coordinate_contract']['world_up']=='+z', 'coordinate_contract')
    supports=[o for o in plan['objects'] if o.get('asset_id')==support_asset_id]
    require(len(supports)==1, 'ambiguous_support_instance')
    support=supports[0]
    targets=[o for o in plan['objects'] if o.get('asset_id')==target_asset_id and o.get('support_id')==support['id']]
    require(len(targets)==1, 'ambiguous_task_target_instance')
    target=targets[0]
    require(target['support_id']==support['id'], 'task_support_edge_not_generated')
    doc,_=_read_glb(generator/'scene_codex_trellis_v2.glb')
    ids={n.get('extras',{}).get('scene_object_id') for n in doc['nodes']}-{None}
    groups,_=_geometry(generator/'scene_codex_trellis_v2.glb',dict(room=plan['room'],objects=[dict(id=i) for i in sorted(ids)]))
    meshes={};poses={}
    for role,obj in [('target',target),('support',support)]:
        matrix=pose(obj);poses[role]=matrix
        mesh=trimesh.util.concatenate([trimesh.Trimesh((p['vertices']-matrix[:3,3])@matrix[:3,:3],p['faces'],process=False) for p in groups[obj['id']]])
        expected=[obj['dimensions'][k] for k in ('width','length','height')]
        require(np.max(abs(mesh.extents-expected))<1e-4,'actual_generated_dimensions_mismatch:'+role)
        meshes[role]=mesh
    return target,support,meshes,poses


def build(generator, output, request, selection, protocol):
    import mujoco
    generator=Path(generator);output=Path(output);output.mkdir(exist_ok=False)
    selected=selection['selected'];target,support,meshes,poses=extract(generator,selected['asset_id'],selection['support_asset_id'])
    require(request['task']=='place_on_surface','container_rejection_must_not_reach_surface_builder')
    mesh=meshes['target'];center=mesh.bounds.mean(0);mesh.apply_translation(-center)
    hull=mesh.convex_hull
    rotation=np.asarray(selected['orientation']);support_mesh=meshes['support']
    world_rotation=poses['support'][:3,:3]@rotation
    nominal_quat=Rotation.from_matrix(world_rotation).as_quat()[[3,0,1,2]]
    extents=np.ptp(mesh.vertices@rotation.T,axis=0);pitch=protocol['geometry']['pitch_m']
    radius=np.ceil((extents[:2]/2+protocol['geometry']['roi_extra_m'])/pitch)*pitch
    roi=np.array([-radius,radius]);counts=np.rint(2*radius/pitch).astype(int)
    xs=-radius[0]+(np.arange(counts[0])+.5)*pitch;ys=-radius[1]+(np.arange(counts[1])+.5)*pitch
    xx,yy=np.meshgrid(xs,ys,indexing='ij');xy=np.c_[xx.ravel(),yy.ravel()]
    upper=rays(support_mesh,xy,support_mesh.bounds[1,2]+.01,-1)
    lower=rays(support_mesh,xy,support_mesh.bounds[0,2]-.01,1)
    valid=np.isfinite(upper)&np.isfinite(lower)&(upper-lower>1e-9)
    centers=np.c_[xy[valid],(upper[valid]+lower[valid])/2]
    sizes=np.c_[np.full((valid.sum(),2),pitch/2),(upper[valid]-lower[valid])/2]
    require(0<len(centers)<=protocol['geometry']['max_columns'],'contact_column_budget')
    gx,gy=protocol['geometry']['measurement_grid']
    xx,yy=np.meshgrid(np.linspace(-radius[0]+pitch*.37,radius[0]-pitch*.37,gx),
        np.linspace(-radius[1]+pitch*.29,radius[1]-pitch*.29,gy),indexing='ij');evalxy=np.c_[xx.ravel(),yy.ravel()]
    source_height=rays(support_mesh,evalxy,support_mesh.bounds[1,2]+.01,-1)
    proxy_height=box_heights(evalxy,centers,sizes)
    support_quality=fidelity(source_height,proxy_height)
    rotated=mesh.copy();rotated.vertices=mesh.vertices@rotation.T
    rotated_hull=hull.copy();rotated_hull.vertices=hull.vertices@rotation.T
    xx,yy=np.meshgrid(np.linspace(rotated.bounds[0,0]+1e-5,rotated.bounds[1,0]-1e-5,gx),
        np.linspace(rotated.bounds[0,1]+1e-5,rotated.bounds[1,1]-1e-5,gy),indexing='ij');targetxy=np.c_[xx.ravel(),yy.ravel()]
    target_source=rays(rotated,targetxy,rotated.bounds[0,2]-.01,1)
    target_proxy=rays(rotated_hull,targetxy,rotated.bounds[0,2]-.01,1)
    target_quality=fidelity(target_source,target_proxy)
    geometric_pass=bool(fidelity_passed(support_quality,protocol['geometry']) and
        target_quality['height_abs_p95_m'] is not None and target_quality['height_abs_p95_m']<=protocol['geometry']['target_hull_underside_p95_m_max'])
    goal_local=np.array([0.,0.,float(np.max(upper[valid])-np.min(hull.vertices@rotation.T,axis=0)[2])])
    goal=poses['support'][:3,3]+poses['support'][:3,:3]@goal_local
    bounds=np.array(support_mesh.bounds);bounds[0,:2]+=protocol['selection']['surface_edge_inset_m'];bounds[1,:2]-=protocol['selection']['surface_edge_inset_m']
    mass=protocol['selection']['target_mass_kg'];dims=mesh.extents
    inertia=mass*(np.sum(dims**2)-dims**2)/12
    mesh.export(output/'target_visual.stl');hull.export(output/'target_collision.stl');support_mesh.export(output/'support_visual.stl')
    root=ET.Element('mujoco',model='task_conditioned_'+request['id']);ET.SubElement(root,'compiler',angle='radian',autolimits='true')
    ET.SubElement(root,'size',memory='256M')
    ET.SubElement(root,'option',timestep=str(protocol['physics']['base_dt_s']),gravity='0 0 -9.81',integrator='implicitfast',solver='Newton',iterations='100',tolerance='1e-10',cone='elliptic',impratio='5')
    default=ET.SubElement(root,'default');ET.SubElement(default,'geom',friction=vec(protocol['selection']['friction']),solref='.01 1',solimp='.95 .99 .001',condim='4')
    asset=ET.SubElement(root,'asset')
    for name in ('target_visual','target_collision','support_visual'):
        ET.SubElement(asset,'mesh',name=name,file=name+'.stl')
    world=ET.SubElement(root,'worldbody')
    sb=ET.SubElement(world,'body',name='support',pos=vec(poses['support'][:3,3]),quat=vec(Rotation.from_matrix(poses['support'][:3,:3]).as_quat()[[3,0,1,2]]))
    ET.SubElement(sb,'geom',name='support_visual',type='mesh',mesh='support_visual',contype='0',conaffinity='0',group='1')
    names=[]
    for index,(c,s) in enumerate(zip(centers,sizes)):
        name='contact_'+str(index);names.append(name);ET.SubElement(sb,'geom',name=name,type='box',pos=vec(c),size=vec(s),group='3')
    tb=ET.SubElement(world,'body',name='target',pos=vec(goal),quat=vec(nominal_quat));ET.SubElement(tb,'freejoint',name='target_free')
    ET.SubElement(tb,'inertial',pos='0 0 0',mass=str(mass),diaginertia=vec(inertia))
    ET.SubElement(tb,'geom',name='target_visual',type='mesh',mesh='target_visual',contype='0',conaffinity='0',group='1')
    ET.SubElement(tb,'geom',name='target_collision',type='mesh',mesh='target_collision',group='3')
    (output/'model.xml').write_text(ET.tostring(root,encoding='unicode'))
    model=mujoco.MjModel.from_xml_path(str(output/'model.xml'))
    require(model.nq==7 and model.nv==6 and model.nu==0,'isolated_layout')
    bid=model.body('target').id;require(np.allclose(model.body_inertia[bid],inertia,rtol=1e-9,atol=1e-12),'body_inertia_readback')
    require(abs(model.body_mass[bid]-mass)<1e-12,'mass_readback')
    mujoco.mj_saveModel(model,str(output/'model.mjb'),None)
    # Native rays independently check the actual compiled support columns.
    data=mujoco.MjData(model);data.qpos[:3]=goal+[0,0,1.];mujoco.mj_forward(model,data)
    errors=[]
    for index in np.linspace(0,len(evalxy)-1,protocol['geometry']['native_ray_check_count'],dtype=int):
        local=np.r_[evalxy[index],support_mesh.bounds[1,2]+.01]
        origin=poses['support'][:3,3]+poses['support'][:3,:3]@local
        group=np.array([0,0,0,1,0,0],dtype=np.uint8);hit=np.array([-1],dtype=np.int32)
        distance=mujoco.mj_ray(model,data,origin,np.array([0.,0.,-1.]),group,1,bid,hit)
        actual=local[2]-distance if distance>=0 else np.nan;expected=proxy_height[index]
        require(np.isfinite(actual)==np.isfinite(expected),'native_ray_coverage')
        if np.isfinite(actual):errors.append(abs(actual-expected))
    require(not errors or max(errors)<1e-7,'native_ray_height')
    spec=int(mujoco.mjtState.mjSTATE_INTEGRATION)
    task=dict(schema='task-conditioned-release/v1',request=request,selection=selection,
        target_body='target',support_body='support',target_dimensions_m=dims.tolist(),
        target_hull_vertices=hull.vertices.tolist(),goal=goal.tolist(),nominal_quaternion_wxyz=nominal_quat.tolist(),
        support_pose=poses['support'].tolist(),support_bounds_local_m=bounds.tolist(),roi_xy_m=roi.tolist(),
        maximum_support_height_local_m=float(np.max(upper[valid])),contact_names=names,
        source_roles=dict(target=target['id'],support=support['id']),source_assets=[target['asset_id'],support['asset_id']],
        source_group='historical_development; book variants share one source family',
        physical_prior=dict(mass_kg=mass,inertia_body_kg_m2=inertia.tolist(),friction=protocol['selection']['friction'],measured=False),
        state_spec=spec,state_size=mujoco.mj_stateSize(model,spec),mujoco_version=mujoco.__version__,
        visual_collision_transform='same target body frame and quaternion; convex hull shape approximation explicitly measured',
        isolated_scope='target and source-derived local support only; no robot, furniture collisions, or visual export qualification')
    np.savez_compressed(output/'GEOMETRY_RAW.npz',source_height=source_height,proxy_height=proxy_height,
        target_source=target_source,target_proxy=target_proxy,centers=centers,sizes=sizes,evaluation_xy=evalxy)
    write_new(output/'GEOMETRY.json',dict(passed=geometric_pass,support=support_quality,target=target_quality,
        native_ray_max_error_m=max(errors,default=0.),native_ray_samples=protocol['geometry']['native_ray_check_count'],
        contact_columns=len(centers),new_physics_steps=0))
    write_new(output/'task.json',task)
    inputs={str(generator/name):reference(generator/name) for name in ('scene_codex_trellis_v2.glb','layout_plan_final.json','run_summary.json','validation_final.json')}
    write_new(output/'BINDING.json',dict(schema='task-conditioned-binding/v1',protocol_sha256=fingerprint(protocol),
        files={p.name:reference(p) for p in sorted(output.iterdir()) if p.is_file()},sources=inputs,
        target_source_bbox_recentering_m=center.tolist(),geometric_qualification=geometric_pass))
    return task
