"""Actual assembled GLB -> portable Panda package, preserving every scene object.

Derived from embodied_production_pilot_v1; explicit fixed robot/cameras, no mount search.
All furniture visuals come from the public generator. Only the robot mounting
fixture and task marker are added. No generated object is moved or rescaled.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import time
import traceback
from xml.etree import ElementTree as ET

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from sage.experiments.codex_trellis_scene_v2.p021_physics import (
    _read_glb, _accessor, _node_matrix, GLTF_TO_Z, _geometry, _hull, object_mass_frame)
from sage.experiments.codex_trellis_scene_v2.collision_proxy import build_voxel_sdf
from sage.experiments.codex_trellis_scene_v2.leaning_books import voxel_boxes
from sage.experiments.embodied_scene_v1.package import vec, set_pose
from sage.experiments.embodied_scene_v1.models import absolute_assets, merge
from sage.experiments.embodied_scene_v1.mujoco_textures import base_color_for_mujoco, TEXTURE_CONVENTION
from sage.experiments.embodied_scene_bridge.contracts import digest, read, require, write
from sage.experiments.embodied_container_m2.cavity import prepare_geometry

ROBOT_SOURCE = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_phase1_20260913_v1/package_v3/robots')


def pose(obj):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler('z', obj['yaw'], degrees=True).as_matrix()
    matrix[:3, 3] = [obj['x'], obj['y'], obj.get('z', 0) + obj['dimensions']['height'] / 2]
    return matrix


def mesh_collider(asset, body, assets, name, vertices, faces=None):
    vertices, faces = _hull(vertices)
    filename = name + '.stl'
    trimesh.Trimesh(vertices, faces, process=False).export(assets / filename)
    ET.SubElement(asset, 'mesh', name=name, file='assets/' + filename)
    ET.SubElement(body, 'geom', name=name, type='mesh', mesh=name, group='3', mass='0')


def add_robot(root, output, support_pose, dimensions):
    robot = ET.parse(ROBOT_SOURCE / 'panda/robot.xml').getroot()
    gripper = ET.parse(ROBOT_SOURCE / 'panda_gripper/panda_gripper.xml').getroot()
    absolute_assets(robot, ROBOT_SOURCE / 'panda')
    absolute_assets(gripper, ROBOT_SOURCE / 'panda_gripper')
    robot.find(".//body[@name='right_hand']").append(deepcopy(gripper.find('worldbody/body')))
    gripper.remove(gripper.find('worldbody'))
    merge(root, robot)
    merge(root, gripper)
    dependencies = []
    for element in root.findall('asset/*'):
        filename = element.get('file')
        if not filename or not Path(filename).is_absolute():
            continue
        path = Path(filename)
        target = output / 'assets' / (digest(path)[:12] + '_' + path.name)
        shutil.copyfile(path, target)
        element.set('file', 'assets/' + target.name)
        dependencies.append(dict(source=str(path), sha256=digest(path), file=element.get('file')))
    shutil.copyfile(ROBOT_SOURCE / 'PANDA_LICENSE', output / 'PANDA_LICENSE')
    return dependencies


def export_visuals(glb, root, poses, bodies, output):
    doc, binary = _read_glb(glb)
    asset, world = root.find('asset'), root.find('worldbody')
    for i, mat in enumerate(doc.get('materials', [])):
        pbr = mat.get('pbrMetallicRoughness', {})
        e = ET.SubElement(asset, 'material', name=f'scene_material_{i}',
                          rgba=vec(pbr.get('baseColorFactor', [1, 1, 1, 1])))
        if 'baseColorTexture' in pbr:
            img, _ = base_color_for_mujoco(doc, binary, pbr, 512)
            filename = f'assets/texture_{i}.png'
            img.save(output / filename)
            ET.SubElement(asset, 'texture', name=f'scene_texture_{i}', type='2d', file=filename)
            e.set('texture', f'scene_texture_{i}')
    rows, seen = [], set()

    def visit(index, parent, owner=None):
        require(index not in seen, 'repeated_GLTF_node')
        seen.add(index)
        node = doc['nodes'][index]
        owner = node.get('extras', {}).get('scene_object_id', owner)
        require(owner is None or owner in bodies, 'unknown_geometry_owner')
        matrix = parent @ _node_matrix(node)
        transform = GLTF_TO_Z @ matrix
        local = np.linalg.inv(poses[owner]) @ transform if owner else transform
        for j, primitive in enumerate(doc['meshes'][node['mesh']]['primitives'] if 'mesh' in node else []):
            vertices = _accessor(doc, binary, primitive['attributes']['POSITION'])
            vertices = vertices @ local[:3, :3].T + local[:3, 3]
            indices = (_accessor(doc, binary, primitive['indices']).ravel() if 'indices' in primitive else np.arange(len(vertices)))
            faces = indices.reshape(-1, 3).astype(int)
            if np.linalg.det(local[:3, :3]) < 0:
                faces = faces[:, ::-1]
            uv = _accessor(doc, binary, primitive['attributes']['TEXCOORD_0']) if 'TEXCOORD_0' in primitive['attributes'] else None
            name = f'scene_visual_{index}_{j}'
            filename = f'assets/{name}.obj'
            with (output / filename).open('w') as stream:
                np.savetxt(stream, vertices, fmt='v %.9f %.9f %.9f')
                if uv is None:
                    np.savetxt(stream, faces + 1, fmt='f %d %d %d')
                else:
                    np.savetxt(stream, uv, fmt='vt %.9f %.9f')
                    np.savetxt(stream, np.repeat(faces + 1, 2, axis=1), fmt='f %d/%d %d/%d %d/%d')
            ET.SubElement(asset, 'mesh', name=name, file=filename, maxhullvert='32')
            attrs = dict(name=name, type='mesh', mesh=name, contype='0', conaffinity='0', group='1', mass='0')
            if 'material' in primitive:
                attrs['material'] = f"scene_material_{primitive['material']}"
            ET.SubElement(bodies[owner] if owner else world, 'geom', **attrs)
            rows.append(dict(name=name, owner=owner, node=node.get('name'), vertices=len(vertices), faces=len(faces)))
        for child in node.get('children', []):
            visit(child, matrix, owner)

    for index in doc['scenes'][doc.get('scene', 0)]['nodes']:
        visit(index, np.eye(4))
    return rows


def build(attempt, output, protocol):
    generator = attempt / 'generator'
    request = read(attempt / 'request.json')
    plan = read(generator / 'layout_plan_final.json')
    require(plan['coordinate_contract']['units'] == 'm' and plan['coordinate_contract']['world_up'] == '+z'
            and plan['coordinate_contract']['handedness'] == 'right_handed', 'unsupported_coordinates')
    require(read(generator / 'validation_final.json')['ok'], 'generator_layout_rejected')
    targets = [o for o in plan['objects'] if o['category'] in request['target_selector']['categories']]
    containers = [o for o in plan['objects'] if o['category'] in request['container_selector']['categories']]
    require(len(targets) == len(containers) == 1, 'container_task_binding_not_unique')
    target, container = targets[0], containers[0]
    support = next(o for o in plan['objects'] if o['id'] == target.get('support_id'))
    require(container.get('support_id') == support['id'], 'container_and_target_support_mismatch')
    require(request['task'] == 'place_in_container', 'container_task_required')
    glb = generator / 'scene_codex_trellis_v2.glb'
    document, _ = _read_glb(glb)
    ids = {n.get('extras', {}).get('scene_object_id') for n in document['nodes']} - {None}
    declared = {o['id'] for o in plan['objects']}
    openings = {o['id']: o for key in ('doors', 'windows') for o in plan['architecture'].get(key, [])}
    require(ids - declared <= set(openings), 'unknown_extra_GLTF_object')
    require(declared <= ids, 'missing_GLTF_object')
    groups, floor = _geometry(glb, dict(room=plan['room'], objects=[dict(id=i) for i in sorted(ids)]))
    poses = {o['id']: pose(o) for o in plan['objects']}
    assets = output / 'assets'
    assets.mkdir()
    root = ET.Element('mujoco', model='generated_scene_task')
    ET.SubElement(root, 'compiler', angle='radian', autolimits='true')
    ET.SubElement(root, 'option', timestep='.001', gravity='0 0 -9.81', integrator='implicitfast',
                  solver='Newton', iterations='100', tolerance='1e-10', cone='elliptic', impratio='5')
    default = ET.SubElement(root, 'default')
    ET.SubElement(default, 'geom', friction='.5 .005 .0001', solref='.01 1', solimp='.95 .99 .001', condim='4')
    visual = ET.SubElement(root, 'visual')
    ET.SubElement(visual, 'global', offwidth='640', offheight='480')
    asset = ET.SubElement(root, 'asset')
    world = ET.SubElement(root, 'worldbody')
    ET.SubElement(world, 'light', pos='2 2 4', dir='0 0 -1', directional='true')
    bodies, objects = {}, []
    for obj in plan['objects']:
        name = obj['id']
        matrix = poses[name]
        parts = groups[name]
        vertices = np.concatenate([p['vertices'] for p in parts])
        local = (vertices - matrix[:3, 3]) @ matrix[:3, :3]
        dims = np.ptp(local, axis=0)
        expected = np.array([obj['dimensions'][k] for k in ('width', 'length', 'height')])
        require(np.max(abs(dims - expected)) < 1e-4, 'actual_GLTF_dimension_mismatch:' + name)
        body = ET.SubElement(world, 'body', name='scene_' + name)
        set_pose(body, matrix)
        bodies[name] = body
        if name != target['id']:
            ET.SubElement(body, 'inertial', pos='0 0 0', mass='0', diaginertia='0 0 0')
        method = 'source_vertices_convex_hull; cavities conservatively occupied'
        if name == support['id']:
            meshes = [trimesh.Trimesh((p['vertices'] - matrix[:3, 3]) @ matrix[:3, :3], p['faces'], process=False) for p in parts]
            proxy = build_voxel_sdf(trimesh.util.concatenate(meshes), pitch=.01, padding_voxels=2,
                                    fill_interior=False, surface_dilation_voxels=0)
            centers, sizes = voxel_boxes(proxy)
            np.savez_compressed(output / 'support_cuboids.npz', centers=centers, half_sizes=sizes)
            for i, (center, size) in enumerate(zip(centers, sizes)):
                ET.SubElement(body, 'geom', name=f'support_col_{i}', type='box', pos=vec(center), size=vec(size), group='3', mass='0')
            method = 'undilated 10 mm source surface voxel cuboids; contact error up to one voxel'
        elif name == container['id']:
            meshes = [trimesh.Trimesh((p['vertices'] - matrix[:3, 3]) @ matrix[:3, :3], p['faces'], process=False) for p in parts]
            centers, sizes, names, certificate = prepare_geometry(trimesh.util.concatenate(meshes), container, target, generator, attempt.parents[1]/'evidence', output, matrix)
            for geom_name, center, size in zip(names, centers, sizes):
                ET.SubElement(body, 'geom', name=geom_name, type='box', pos=vec(center), size=vec(size), group='3', mass='0')
            method = 'source-derived 5 mm undilated surface cuboids; actual cavity and woven bottom retained'
        else:
            mesh_collider(asset, body, assets, 'scene_col_' + name, local)
        if name == target['id']:
            width = float(min(dims[:2]))
            limits = protocol['difficulty']['grasp_width_m']
            require(limits[0] <= width <= limits[1] and width + .01 <= .08, 'gripper_width_rejected')
            ET.SubElement(body, 'freejoint', name='task_target_free')
            mass = .25
            inertia = mass * np.array([dims[1]**2+dims[2]**2, dims[0]**2+dims[2]**2, dims[0]**2+dims[1]**2]) / 12
            ET.SubElement(body, 'inertial', pos=vec((local.min(0)+local.max(0))/2), mass=str(mass), diaginertia=vec(inertia))
        objects.append(dict(semantic_id=name, body='scene_'+name, category=obj['category'], support_id=obj.get('support_id'),
            pose_z_up=matrix.tolist(), actual_dimensions_m=dims.tolist(), dimension_error_m=float(max(abs(dims-expected))),
            collider=method, role='dynamic_task_target' if name == target['id'] else 'static_environment',
            mass_kg=.25 if name == target['id'] else None, inertia_origin='uniform bbox prior' if name == target['id'] else 'static',
            friction=.5, measured=False))
    architecture_objects = []
    for name in sorted(ids - declared):
        matrix, local, extents = object_mass_frame(groups[name])
        poses[name] = matrix
        body = ET.SubElement(world, 'body', name='scene_' + name)
        set_pose(body, matrix)
        bodies[name] = body
        ET.SubElement(body, 'inertial', pos='0 0 0', mass='0', diaginertia='0 0 0')
        mesh_collider(asset, body, assets, 'scene_col_' + name, local)
        architecture_objects.append(dict(semantic_id=name, role='static_architecture_opening',
            actual_dimensions_in_GLTF_root_frame_m=extents.tolist(), pose_z_up=matrix.tolist(),
            source_binding=openings[name].get('asset_binding'),
            articulation='static; no hinge functionality asserted'))
    for i, part in enumerate([floor, *floor['other_architecture_parts']]):
        mesh_collider(asset, world, assets, 'floor' if i == 0 else f'architecture_col_{i}', part['vertices'])
    visuals = export_visuals(glb, root, poses, bodies, output)
    robot_sources = add_robot(root, output, poses[support['id']], support['dimensions'])
    start = poses[target['id']][:3, 3]
    support_pose = poses[support['id']]
    cavity_pose = poses[container['id']]
    goal_local = np.array([0., 0., certificate['bottom_surface_z_local_m'] + target['dimensions']['height']/2])
    goal = cavity_pose[:3, 3] + cavity_pose[:3, :3] @ goal_local
    require(.18 <= np.linalg.norm((goal-start)[:2]) <= .40, 'transfer_difficulty')
    task = dict(schema='generated-task/v1', task=request['task'], seed=request['seed'], split='development',
        target_body='scene_'+target['id'], target_semantic_id=target['id'], support_body='scene_'+support['id'],
        support_semantic_id=support['id'], start=start.tolist(), target_quat=Rotation.from_matrix(poses[target['id']][:3,:3]).as_quat()[[3,0,1,2]].tolist(),
        target_dimensions_m=[target['dimensions'][k] for k in ('width','length','height')],
        grasp_height_offset_m=target['dimensions']['height']/2-.02,
        grasp_height_origin='target top minus 20mm pad overlap; endpoint collision checks required',
        target_rotation=poses[target['id']][:3,:3].tolist(), goal=goal.tolist(), support_pose=support_pose.tolist(),
        support_dimensions_m=[support['dimensions'][k] for k in ('width','length','height')],
        support_top_z_m=support.get('z',0)+support['dimensions']['height'],
        success=protocol['success'], initialization_xy_jitter_m=.02,
        control=protocol['control'], instruction='Pick up the single book and place it fully inside the open storage basket, then release it on the real bottom.',
        execution_feasibility='unknown until M2 planner executes', material_measured=False)
    task.update(container_body='scene_'+container['id'], container_semantic_id=container['id'], cavity=certificate)
    ET.SubElement(world, 'geom', name='robot_mount', type='box', pos='0 0 .01', size='.09 .09 .01', rgba='.2 .2 .2 1')
    ET.SubElement(world, 'site', name='goal_marker', type='box', pos=vec([*goal[:2],goal[2]-task['target_dimensions_m'][2]/2+.002]),
                  size=vec([.04,.10,.001]), rgba='.05 .7 .2 .5')
    # The camera is a diagnostic addition, not part of policy training in M1.
    camera_pos = support_pose[:3,3] + support_pose[:3,:3] @ [-1.5,-1.7,1.6]
    forward = start-camera_pos; forward /= np.linalg.norm(forward)
    right = np.cross(forward,[0.,0.,1.]); right /= np.linalg.norm(right)
    ET.SubElement(world, 'camera', name='workspace', pos=vec(camera_pos), xyaxes=vec(np.r_[right,np.cross(right,forward)]), fovy='50')
    write(output / 'task.json', task)
    write(output / 'objects.json', objects)
    ET.indent(root)
    ET.ElementTree(root).write(output / 'model_unmounted.xml', encoding='unicode')
    from .fixed import apply_fixed_scene
    mount = apply_fixed_scene(root, task, protocol['fixed_scene_contract'])
    write(output / 'mount_candidates.json', mount)
    task['robot_mount'] = mount['selected']
    write(output / 'task.json', task)
    ET.indent(root)
    ET.ElementTree(root).write(output / 'model.xml', encoding='unicode')
    sources = read(generator / 'asset_resolution.json')['results']
    write(output / 'scene_manifest.json',dict(schema='generator-container-task-package/v1',scene_id=plan.get('scene_id'),
        source_glb=dict(path=str(glb),sha256=digest(glb)),layout_sha256=digest(generator/'layout_plan_final.json'),
        request_sha256=digest(attempt/'request.json'),objects=objects,architecture_objects=architecture_objects,
        visuals=visuals,asset_resolution=sources,
        architecture_resolution=read(generator / 'asset_resolution.json')['architecture_results'],robot_sources=robot_sources,
        no_scene_pose_or_scale_edits=True,all_generated_objects_retained=True,texture_convention=TEXTURE_CONVENTION,
        texture_scope='base-color capped 512px; not full PBR parity',new_assets=False,split='development',
        source_asset_group=request['source_asset_group'],layout_family=request['layout_family'],cavity_certificate_sha256=digest(output/'container_certificate.json')))
    write(output / 'FILES.json', {str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*'))
                               if p.is_file() and p.name not in ('ADAPTATION.json','FILES.json')})
    return dict(objects=len(objects),visual_primitives=len(visuals),target=target['id'],support=support['id'],
                source_glb_sha256=digest(glb),task_feasibility='unknown; M1 is not a task rollout')
