"""XML scene package; source-bound start GLB and no duplicated compiled models."""
from pathlib import Path
from copy import deepcopy
from xml.etree import ElementTree as ET
import shutil
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference,fingerprint
from .build import build as build_local,pose
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb,_geometry,object_mass_frame
from sage.experiments.codex_trellis_scene_v2.collision_proxy import build_voxel_sdf
from sage.experiments.codex_trellis_scene_v2.leaning_books import voxel_boxes
from sage.experiments.embodied_scene_bridge.adapter import mesh_collider,export_visuals
from sage.experiments.embodied_scene_v1.package import set_pose,vec
from sage.experiments.embodied_scene_quality_v2.geometry import outside_pieces
from sage.experiments.embodied_task_scene_v1.semantic import validate_roles
from sage.experiments.embodied_task_scene_v1.glb import transform_glb


def build(config,protocol):
    import mujoco
    config=Path(config);generator=config/'generator';output=config/'package';output.mkdir(exist_ok=False)
    request=read(config/'request.json');roles=read(config/'roles.json');plan=read(generator/'layout_plan_final.json')
    target,support=validate_roles(plan['objects'],roles,read(config/'expected_counts.json'))
    local_dir=config/'local_contact'
    if local_dir.exists():
        prior=read(local_dir/'BINDING.json')
        require(prior['protocol_sha256']==fingerprint(protocol),'reused_contact_protocol')
        from sage.experiments.embodied_scene_quality_v2.contracts import bound
        for ref in list(prior['files'].values())+list(prior['sources'].values()):bound(ref['path'],ref['sha256'])
        localtask=read(local_dir/'task.json')
    else:localtask=build_local(generator,local_dir,request,read(config/'selection.json'),protocol)
    binding=read(local_dir/'BINDING.json');geometry=read(local_dir/'GEOMETRY.json')
    document,_=_read_glb(generator/'scene_codex_trellis_v2.glb')
    ids={n.get('extras',{}).get('scene_object_id') for n in document['nodes']}-{None}
    declared={o['id'] for o in plan['objects']}
    openings={o['id']:o for k in ['doors','windows'] for o in plan['architecture'].get(k,[])}
    require(declared<=ids and ids-declared<=set(openings),'gltf_semantic_set')
    groups,floor=_geometry(generator/'scene_codex_trellis_v2.glb',dict(room=plan['room'],objects=[dict(id=i) for i in sorted(ids)]))
    poses={o['id']:pose(o) for o in plan['objects']}
    # Local contact conversion recenters the target bbox without altering its shape.
    poses[target['id']]=poses[target['id']].copy()
    poses[target['id']][:3,3]+=poses[target['id']][:3,:3]@np.asarray(binding['target_source_bbox_recentering_m'])
    start=poses[target['id']].copy();goal=np.eye(4)
    goal[:3,:3]=Rotation.from_quat(np.asarray(localtask['nominal_quaternion_wxyz'])[[1,2,3,0]]).as_matrix();goal[:3,3]=localtask['goal']
    delta=goal@np.linalg.inv(start)
    glb_change=transform_glb(generator/'scene_codex_trellis_v2.glb',output/'scene_goal.glb',target['id'],delta)
    root=ET.parse(local_dir/'model.xml').getroot();root.set('model','full_task_scene')
    root.find('size').set('memory','512M')
    asset=root.find('asset');world=root.find('worldbody');assets=output/'assets';assets.mkdir()
    for name in ['target_visual','support_visual']:
        for parent in root.iter():
            for child in list(parent):
                if child.tag in ['geom','mesh'] and child.get('name')==name:parent.remove(child)
    shutil.copyfile(local_dir/'target_collision.stl',output/'target_collision.stl')
    target_body=world.find("body[@name='target']");support_body=world.find("body[@name='support']")
    set_pose(target_body,start)
    bodies={target['id']:target_body,support['id']:support_body};objects=[]
    for obj in plan['objects']:
        name=obj['id'];matrix=poses[name];parts=groups[name]
        local=np.concatenate([(p['vertices']-matrix[:3,3])@matrix[:3,:3] for p in parts])
        if name not in bodies:
            body=ET.SubElement(world,'body',name='scene_'+name);set_pose(body,matrix);bodies[name]=body
            ET.SubElement(body,'inertial',pos='0 0 0',mass='0',diaginertia='0 0 0')
            mesh_collider(asset,body,assets,'scene_col_'+name,local)
        objects.append(dict(semantic_id=name,body=bodies[name].get('name'),asset_id=obj['asset_id'],category=obj['category'],
            start_pose_z_up=matrix.tolist(),goal_pose_z_up=(goal if name==target['id'] else matrix).tolist(),
            collider='source contact surface with outer voxel surface' if name==support['id'] else 'source convex hull',
            role='dynamic_target' if name==target['id'] else 'static_environment'))
    # Retain the source support outside the previously declared contact ROI.
    sm=trimesh.util.concatenate([trimesh.Trimesh((p['vertices']-poses[support['id']][:3,3])@poses[support['id']][:3,:3],p['faces'],process=False) for p in groups[support['id']]])
    proxy=build_voxel_sdf(sm,pitch=.01,padding_voxels=2,fill_interior=False,surface_dilation_voxels=0)
    centers,sizes=voxel_boxes(proxy);pieces=[]
    for c,s in zip(centers,sizes):pieces.extend(outside_pieces(c,s,np.asarray(localtask['roi_xy_m'])))
    for i,(c,s) in enumerate(pieces):
        ET.SubElement(support_body,'geom',name='outer_support_'+str(i),type='box',pos=vec(c),size=vec(s),group='3',mass='0')
    np.savez_compressed(output/'support_outer_cuboids.npz',centers=np.array([c for c,s in pieces]),half_sizes=np.array([s for c,s in pieces]))
    for name in sorted(ids-declared):
        matrix,local,extents=object_mass_frame(groups[name]);poses[name]=matrix
        body=ET.SubElement(world,'body',name='scene_'+name);set_pose(body,matrix);bodies[name]=body
        ET.SubElement(body,'inertial',pos='0 0 0',mass='0',diaginertia='0 0 0')
        mesh_collider(asset,body,assets,'scene_col_'+name,local)
        objects.append(dict(semantic_id=name,body=body.get('name'),category='architecture_opening',start_pose_z_up=matrix.tolist(),
            goal_pose_z_up=matrix.tolist(),collider='source convex hull',role='static_architecture'))
    for i,part in enumerate([floor,*floor['other_architecture_parts']]):
        mesh_collider(asset,world,assets,'floor' if i==0 else 'architecture_col_'+str(i),part['vertices'])
    visuals=export_visuals(generator/'scene_codex_trellis_v2.glb',root,poses,bodies,output)
    visual=ET.SubElement(root,'visual');ET.SubElement(visual,'global',offwidth='320',offheight='240')
    ET.SubElement(world,'light',pos='2 2 4',dir='0 0 -1',directional='true')
    for name,offset in [('workspace',[-1.2,-1.4,1.2]),('overview',[1.8,1.8,2.0])]:
        eye=goal[:3,3]+np.asarray(localtask['support_pose'])[:3,:3]@offset
        forward=goal[:3,3]-eye;forward/=np.linalg.norm(forward);right=np.cross(forward,[0.,0.,1.]);right/=np.linalg.norm(right)
        ET.SubElement(world,'camera',name=name,pos=vec(eye),xyaxes=vec(np.r_[right,np.cross(right,forward)]),fovy='50')
    ET.indent(root);ET.ElementTree(root).write(output/'model.xml',encoding='unicode')
    goalroot=deepcopy(root);set_pose(goalroot.find("worldbody/body[@name='target']"),goal)
    ET.ElementTree(goalroot).write(output/'model_goal.xml',encoding='unicode')
    models={}
    for stem in ['model','model_goal']:
        model=mujoco.MjModel.from_xml_path(str(output/(stem+'.xml')));data=mujoco.MjData(model);mujoco.mj_forward(model,data)
        require(model.nq==7 and model.nv==6 and model.nu==0,'scene_free_target_layout')
        models[stem]=dict(ngeom=model.ngeom,nbody=model.nbody,nmesh=model.nmesh,nq=model.nq,nv=model.nv,
            target_pose_qpos=data.qpos.tolist(),contacts=int(data.ncon))
    task=dict(schema='full-task-scene/v1',request=request,roles=roles,target_body='target',support_body='support',
        target_dimensions_m=localtask['target_dimensions_m'],start_pose_z_up=start.tolist(),goal_pose_z_up=goal.tolist(),
        support_pose=localtask['support_pose'],support_bounds_local_m=localtask['support_bounds_local_m'],
        target_hull_vertices=localtask['target_hull_vertices'],physical_prior=localtask['physical_prior'],
        geometry_passed=geometry['passed'],source_local_package=reference(local_dir/'BINDING.json'),
        scope='all generated objects retained; no robot in scene package; conservative non-task collision approximation',
        robot_task_execution='unknown',qualified_collection=False,qualified_export=False)
    write_new(output/'task.json',task)
    write_new(output/'scene_manifest.json',dict(objects=objects,visuals=visuals,source_glb=reference(generator/'scene_codex_trellis_v2.glb'),
        source_layout=reference(generator/'layout_plan_final.json'),glb_change=glb_change,all_generated_instances_retained=True,
        target_pose_change_only=True,outer_support_columns=len(pieces),local_support_columns=len(localtask['contact_names']),
        texture_scope='original base color converted once at 512px; no PBR or RGB learning quality claim'))
    write_new(output/'BUILD_RESULT.json',dict(models=models,geometry=geometry,physics_steps=0))
    write_new(output/'FILES.json',{str(p.relative_to(output)):reference(p) for p in sorted(output.rglob('*')) if p.is_file()})
    return task
