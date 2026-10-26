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
        groups,floor=_geometry(package/('scene_'+mode+'.glb'),dict(room=original['room'],objects=[dict(id=i) for i in sorted(ids)]))
        allparts=[p for rows in groups.values() for p in rows]+[floor,*floor['other_architecture_parts']]
        expected[mode]={p['binding']['node_index']:p['vertices'] for p in allparts};parts[mode]=groups
    delta=np.asarray(manifest['glb_change']['world_delta_z_up']);target=task['roles']['target_id'];gltf_errors={}
    for owner in ids:
        a=np.concatenate([p['vertices'] for p in parts['start'][owner]]);b=np.concatenate([p['vertices'] for p in parts['goal'][owner]])
        wanted=a@delta[:3,:3].T+delta[:3,3] if owner==target else a
        require(a.shape==b.shape,'gltf_vertex_count');error=float(np.max(abs(wanted-b)));gltf_errors[owner]=error
        require(error<=protocol['full_scene']['visual_vertex_tolerance_m'],'gltf_pose_change:'+owner)
    require(_read_glb(package/'scene_start.glb')[1]==_read_glb(package/'scene_goal.glb')[1],'gltf_binary_changed')
    results={}
    for mode,stem in [('start','model'),('goal','model_goal')]:
        tree=ET.parse(package/(stem+'.xml'))
        for element in tree.findall('asset/*'):
            filename=element.get('file')
            if filename:require(not Path(filename).is_absolute() and (package/filename).is_file(),'nonportable_asset')
        require(not tree.findall('.//weld'),'weld_forbidden')
        model=mujoco.MjModel.from_binary_path(str(package/(stem+'.mjb')));data=mujoco.MjData(model);mujoco.mj_forward(model,data)
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


def render_diagnostics(package,output):
    import mujoco
    from PIL import Image
    from OpenGL.GL import glGetString,GL_RENDERER,GL_VENDOR
    output=Path(output);output.mkdir(exist_ok=False);model=mujoco.MjModel.from_binary_path(str(Path(package)/'model_goal.mjb'))
    data=mujoco.MjData(model);mujoco.mj_forward(model,data);records=[]
    with mujoco.Renderer(model,height=240,width=320,max_geom=max(10000,model.ngeom*2)) as renderer:
        vendor=glGetString(GL_VENDOR).decode();backend=glGetString(GL_RENDERER).decode()
        require('llvmpipe' in backend.lower() or 'softpipe' in backend.lower(),'software_renderer_required')
        option=mujoco.MjvOption();option.geomgroup[:]=0;option.geomgroup[1]=1
        for name in ['workspace','overview']:
            renderer.update_scene(data,camera=name,scene_option=option);rgb=renderer.render().copy()
            require(rgb.shape==(240,320,3) and rgb.dtype==np.uint8,'rgb_shape_dtype')
            x=rgb.astype(np.float64);mean=x.mean((0,1));std=x.std((0,1));reference_std=np.sqrt(np.mean((x-mean)**2,axis=(0,1)))
            require(np.allclose(std,reference_std,rtol=0,atol=1e-10) and np.all(std>1),'rgb_numeric_or_blank')
            path=output/(name+'.png');Image.fromarray(rgb).save(path)
            require(np.array_equal(np.asarray(Image.open(path)),rgb),'png_roundtrip')
            records.append(dict(camera=name,file=reference(path),channel_mean=mean.tolist(),channel_std=std.tolist()))
    return dict(passed=True,renderer=backend,vendor=vendor,frames=records,scope='diagnostic camera integrity; not learning or export qualification',new_physics_steps=0)
