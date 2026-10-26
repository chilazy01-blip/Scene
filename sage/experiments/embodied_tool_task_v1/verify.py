"""Independent GLB/OBJ/native verification; no integration or learning data."""
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,bound,write_new,reference
from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry,_read_glb


def vertices(path):
    return np.array([[float(x) for x in line.split()[1:]] for line in Path(path).read_text().splitlines() if line.startswith('v ')])


def verify(package,protocol):
    import mujoco
    package=Path(package);task=read(package/'task.json');manifest=read(package/'scene_manifest.json')
    for ref in read(package/'FILES.json').values():bound(ref['path'],ref['sha256'])
    original=read(manifest['source_layout']['path']);ids={o['semantic_id'] for o in manifest['objects']}
    require({o['id'] for o in original['objects']}<=ids,'missing_generated_object')
    expected_names={o['id'] for o in original['objects']}|{o['id'] for k in ['doors','windows'] for o in original['architecture'].get(k,[])}
    require(ids==expected_names,'unknown_semantic_object')
    expected={};parts={}
    for mode in ['start','goal']:
        groups,floor=_geometry((Path(manifest['source_glb']['path']) if mode=='start' else package/'scene_goal.glb'),dict(room=original['room'],objects=[dict(id=i) for i in sorted(ids)]))
        allparts=[p for rows in groups.values() for p in rows]+[floor,*floor['other_architecture_parts']]
        expected[mode]={p['binding']['node_index']:p['vertices'] for p in allparts};parts[mode]=groups
    delta=np.asarray(manifest['glb_change']['world_delta_z_up']);target=task['roles']['target_id'];gltf_errors={}
    for owner in ids:
        a=np.concatenate([p['vertices'] for p in parts['start'][owner]]);b=np.concatenate([p['vertices'] for p in parts['goal'][owner]])
        wanted=a@delta[:3,:3].T+delta[:3,3] if owner==target else a
        require(a.shape==b.shape,'gltf_vertex_count');error=float(np.max(abs(wanted-b)));gltf_errors[owner]=error
        require(error<=protocol['full_scene']['visual_vertex_tolerance_m'],'gltf_pose_change:'+owner)
    require(_read_glb(Path(manifest['source_glb']['path']))[1]==_read_glb(package/'scene_goal.glb')[1],'gltf_binary_changed')
    results={}
    for mode,stem in [('start','model'),('goal','model_goal')]:
        tree=ET.parse(package/(stem+'.xml'))
        for element in tree.findall('asset/*'):
            filename=element.get('file')
            if filename:require(not Path(filename).is_absolute() and (package/filename).is_file(),'nonportable_asset')
        require(not tree.findall('.//weld'),'weld_forbidden')
        model=mujoco.MjModel.from_xml_path(str(package/(stem+'.xml')));data=mujoco.MjData(model);mujoco.mj_forward(model,data)
        poses={o['semantic_id']:np.asarray(o[mode+'_pose_z_up']) for o in manifest['objects']}
        actual={};native_errors=[]
        for row in manifest['visuals']:
            local=vertices(package/'assets'/(row['name']+'.obj'));matrix=poses[row['owner']] if row['owner'] is not None else np.eye(4)
            world=local@matrix[:3,:3].T+matrix[:3,3];index=int(row['name'].split('_')[2]);actual.setdefault(index,[]).append(world)
            gid=model.geom(row['name']).id;mid=int(model.geom_dataid[gid]);start=int(model.mesh_vertadr[mid]);count=int(model.mesh_vertnum[mid])
            native=model.mesh_vert[start:start+count]@data.geom_xmat[gid].reshape(3,3).T+data.geom_xpos[gid]
            distance=max(cKDTree(world).query(native)[0].max(),cKDTree(native).query(world)[0].max());native_errors.append(float(distance))
        require(set(actual)==set(expected[mode]),'visual_node_set')
        errors=[]
        for index,rows in actual.items():
            actual_vertices=np.concatenate(rows);require(actual_vertices.shape==expected[mode][index].shape,'obj_vertex_count')
            errors.append(float(np.max(abs(actual_vertices-expected[mode][index]))))
        require(max(errors)<=protocol['full_scene']['visual_vertex_tolerance_m'],'obj_to_gltf_pose')
        require(max(native_errors)<=protocol['full_scene']['visual_vertex_tolerance_m'],'native_visual_pose')
        pose=np.asarray(task[mode+'_pose_z_up']);bid=model.body(task['target_body']).id
        require(np.max(abs(data.xpos[bid]-pose[:3,3]))<=protocol['full_scene']['position_tolerance_m'],'native_target_position')
        require(np.max(abs(data.xmat[bid].reshape(3,3)-pose[:3,:3]))<=protocol['full_scene']['quaternion_tolerance'],'native_target_orientation')
        prior=task['physical_prior'];require(abs(model.body_mass[bid]-prior['mass_kg'])<1e-12,'mass_changed')
        require(np.allclose(model.body_inertia[bid],prior['inertia_body_kg_m2'],atol=1e-12,rtol=1e-9),'inertia_changed')
        target_geom=model.geom('target_collision').id;support=model.body(task['support_body']).id;contacts=[]
        for c in data.contact:
            if target_geom not in [c.geom1,c.geom2]:continue
            other=int(c.geom2 if c.geom1==target_geom else c.geom1)
            contacts.append(dict(other=model.geom(other).name,penetration_m=max(0.,-float(c.dist)),support=bool(model.geom_bodyid[other]==support)))
        require(not any(not c['support'] and c['penetration_m']>protocol['robot']['max_static_penetration_m'] for c in contacts),'target_environment_penetration')
        results[mode]=dict(visual_nodes=len(errors),obj_glb_max_error_m=max(errors),native_visual_max_error_m=max(native_errors),
            target_contacts=contacts,maximum_target_penetration_m=max([0.]+[c['penetration_m'] for c in contacts]),
            nq=model.nq,nv=model.nv,ngeom=model.ngeom)
    return dict(passed=True,gltf_pose_errors_m=gltf_errors,models=results,all_instances_retained=True,
        only_target_pose_changed=True,geometry_passed=task['geometry_passed'],new_physics_steps=0)
