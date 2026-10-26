"""Export the frozen bedroom to a portable MuJoCo scene package.

Visuals are decoded from the final GLB, never reconstructed as furniture.
Physics uses independently versioned colliders and declared parameter priors.
"""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import json
import shutil
import time

import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

from sage.experiments.codex_trellis_scene_v2.p021_physics import (
    _read_glb, _accessor, _node_matrix, GLTF_TO_Z, _geometry, metric_object_mesh)
from sage.experiments.codex_trellis_scene_v2.collision_proxy import build_voxel_sdf
from sage.experiments.codex_trellis_scene_v2.leaning_books import voxel_boxes
from .mujoco_textures import base_color_for_mujoco, TEXTURE_CONVENTION


def vec(a):
    return ' '.join(format(float(v), '.10g') for v in np.asarray(a).ravel())


def bound(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=h.hexdigest())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def verify_binding(row):
    actual = bound(row['path'])
    if actual['sha256'] != row['sha256']:
        raise ValueError('Source hash mismatch: ' + row['path'])
    return actual


def rigid(matrix):
    a = np.asarray(matrix, dtype=float)
    if a.shape != (4, 4) or not np.isfinite(a).all() or not np.allclose(a[3], [0, 0, 0, 1]):
        raise ValueError('Invalid rigid transform')
    if not np.allclose(a[:3, :3].T @ a[:3, :3], np.eye(3), atol=1e-8) or np.linalg.det(a[:3, :3]) < 0:
        raise ValueError('Physical pose must be a proper rigid transform')
    return a


def set_pose(body, matrix):
    a = rigid(matrix)
    body.set('pos', vec(a[:3, 3]))
    body.set('quat', vec(Rotation.from_matrix(a[:3, :3]).as_quat()[[3, 0, 1, 2]]))


def export_package(source, output, robot_dir):
    source, output, robot_dir = map(Path, (source, output, robot_dir))
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    glb = source / 'physics/scene_physics_final.glb'
    expected = '2886d3780a03665afbef575416d23a7940b1f1beb6369601af86b49cff05f391'
    if bound(glb)['sha256'] != expected:
        raise ValueError('Phase-one source differs from approved bedroom')
    binding_path = source / 'physics/binding/geometry_binding.json'
    binding = json.loads(binding_path.read_text())
    plan_path = source / 'physics/layout_plan_physics_final.json'
    plan = json.loads(plan_path.read_text())
    final = json.loads((source / 'physics/normal_0.000250/trajectory.json').read_text())['frames'][-1]['bodies']
    poses = {k: rigid(v['matrix_world_z_up']) for k, v in final.items()}
    assets = output / 'assets'; assets.mkdir()
    root = ET.Element('mujoco', model='scene_bedroom_phase1')
    ET.SubElement(root, 'compiler', angle='radian', autolimits='true', inertiafromgeom='auto', meshdir='assets', texturedir='assets')
    opt = ET.SubElement(root, 'option', timestep='.001', gravity='0 0 -9.81', integrator='implicitfast',
                        solver='Newton', iterations='100', tolerance='1e-10', cone='elliptic', impratio='5')
    ET.SubElement(opt, 'flag', multiccd='enable', nativeccd='enable')
    default = ET.SubElement(root, 'default')
    ET.SubElement(default, 'geom', friction='.5 .005 .0001', solref='.01 1', solimp='.95 .99 .001', condim='4')
    visual = ET.SubElement(root, 'visual')
    ET.SubElement(visual, 'global', offwidth='640', offheight='480')
    ET.SubElement(visual, 'map', znear='.01', zfar='30')
    asset = ET.SubElement(root, 'asset'); world = ET.SubElement(root, 'worldbody')
    ET.SubElement(world, 'light', pos='2.8 2.5 4', dir='0 0 -1', directional='true', diffuse='.8 .8 .8')
    ET.SubElement(world, 'light', pos='4 0 3', dir='-1 1 -1', diffuse='.4 .4 .4')
    bodies = {}; rows = {}; dependency = [bound(glb), bound(binding_path), bound(plan_path)]
    for name, obj in binding['objects'].items():
        body = ET.SubElement(world, 'body', name=name); set_pose(body, poses[name]); bodies[name] = body
        ET.SubElement(body, 'inertial', mass='0', diaginertia='0 0 0', pos='0 0 0')
        source_collider = verify_binding(obj['collider']['artifact']); dependency.append(source_collider)
        data = np.load(source_collider['path'], allow_pickle=False)
        if 'centers' in data:
            for i, (c, h) in enumerate(zip(data['centers'], data['half_sizes'])):
                ET.SubElement(body, 'geom', name=f'col_{name}_{i}', type='box', pos=vec(c), size=vec(h), group='3', mass='0')
        else:
            meshname = 'colmesh_' + name
            file = meshname + '.stl'
            trimesh.Trimesh(vertices=data['vertices'], faces=data['faces'], process=False).export(assets / file)
            ET.SubElement(asset, 'mesh', name=meshname, file=file)
            ET.SubElement(body, 'geom', name='col_' + name, type='mesh', mesh=meshname, group='3', mass='0')
        rows[name] = dict(role='static_environment', source_physics_role='static' if obj['static'] else 'free_book',
            task_role_change=None if obj['static'] else 'frozen at previously simulated final pose; original five-book experiment is separate',
            pose_z_up=poses[name].tolist(), dimensions_local_m=obj['metric_box_extents_m'],
            semantic_up_local=[0, 0, 1], collider=obj['collider'], mass=obj.get('mass_kg'),
            mass_origin=obj['mass_origin'], mass_range_kg=obj.get('mass_range_kg'), measured=False,
            friction=dict(value=.5, source='inherited declared scene prior', measured=False))
    # The fixed scene retains every architectural collider including the hidden south wall.
    architecture = [dict(name='floor', world_bounds_z_up=binding['floor']['world_bounds_z_up'])] + binding['room_boundaries']
    for row in architecture:
        a = np.asarray(row['world_bounds_z_up'])
        if row.get('collider'):
            dep = verify_binding(row['collider']['artifact']); dependency.append(dep)
            data = np.load(dep['path'], allow_pickle=False)
            file = 'arch_' + row['name'] + '.stl'
            trimesh.Trimesh(vertices=data['vertices'], faces=data['faces'], process=False).export(assets / file)
            ET.SubElement(asset, 'mesh', name='arch_' + row['name'], file=file)
            ET.SubElement(world, 'geom', name=row['name'], type='mesh', mesh='arch_' + row['name'], group='3')
        else:
            ET.SubElement(world, 'geom', name=row['name'], type='box', pos=vec(a.mean(0)), size=vec(np.ptp(a, axis=0)/2), group='3')
    print('Colliders exported', flush=True)
    document, binary = _read_glb(glb)
    materials = {}
    for i, mat in enumerate(document.get('materials', [])):
        pbr = mat.get('pbrMetallicRoughness', {})
        m = ET.SubElement(asset, 'material', name='scene_mat_' + str(i), rgba=vec(pbr.get('baseColorFactor', [1, 1, 1, 1])),
                          metallic=str(pbr.get('metallicFactor', 0)), roughness=str(pbr.get('roughnessFactor', .8)))
        if 'baseColorTexture' in pbr:
            image, _ = base_color_for_mujoco(document, binary, pbr, 512)
            file = 'texture_' + str(i) + '.png'; image.save(assets / file)
            ET.SubElement(asset, 'texture', name='scene_tex_' + str(i), type='2d', file=file)
            m.set('texture', 'scene_tex_' + str(i))
        materials[i] = m.get('name')
    visuals = []; geometry = {}; node_seen = set()
    def visit(index, parent, owner=None):
        if index in node_seen: raise ValueError('Repeated or cyclic node')
        node_seen.add(index)
        node = document['nodes'][index]; owner = node.get('extras', {}).get('scene_object_id', owner)
        mat = parent @ _node_matrix(node); transform = GLTF_TO_Z @ mat
        target = bodies[owner] if owner else world
        local = np.linalg.inv(poses[owner]) @ transform if owner else transform
        for j, primitive in enumerate(document['meshes'][node['mesh']]['primitives'] if 'mesh' in node else []):
            v = _accessor(document, binary, primitive['attributes']['POSITION'])
            v = v @ local[:3, :3].T + local[:3, 3]
            f = _accessor(document, binary, primitive['indices']).ravel().reshape(-1, 3).astype(int)
            if np.linalg.det(local[:3, :3]) < 0: f = f[:, ::-1]
            uv = _accessor(document, binary, primitive['attributes']['TEXCOORD_0']) if 'TEXCOORD_0' in primitive['attributes'] else None
            if uv is None and 'material' in primitive and 'baseColorTexture' in document['materials'][primitive['material']].get('pbrMetallicRoughness', {}):
                raise ValueError('Textured primitive has no TEXCOORD_0')
            name = f'vis_{index}_{j}'; file = name + '.obj'
            with (assets / file).open('w') as stream:
                np.savetxt(stream, v, fmt='v %.8f %.8f %.8f')
                if uv is not None:
                    np.savetxt(stream, uv, fmt='vt %.8f %.8f')
                    indices = np.repeat(f + 1, 2, axis=1)
                    np.savetxt(stream, indices, fmt='f %d/%d %d/%d %d/%d')
                else: np.savetxt(stream, f + 1, fmt='f %d %d %d')
            ET.SubElement(asset, 'mesh', name=name, file=file, maxhullvert='32')
            attr = dict(name=name, type='mesh', mesh=name, contype='0', conaffinity='0', mass='0', group='1')
            if 'material' in primitive: attr['material'] = materials[primitive['material']]
            # Presentation cutaway only; colliders remain in group 3 and fully enabled.
            if not owner and any(k in node.get('name', '') for k in ('wall_south', 'wall_east')): attr['group'] = '4'
            ET.SubElement(target, 'geom', **attr)
            visuals.append(dict(name=name, owner=owner or node.get('name'), vertices=len(v), faces=len(f)))
            if owner: geometry.setdefault(owner, []).append(trimesh.Trimesh(v, f, process=False))
        for child in node.get('children', []): visit(child, mat, owner)
    for node in document['scenes'][document.get('scene', 0)]['nodes']: visit(node, np.eye(4))
    print('Visuals exported', len(visuals), flush=True)
    axes = []
    planned = {o['id']: o for o in plan['objects']}
    for name, meshes in geometry.items():
        ext = np.ptp(np.concatenate([m.vertices for m in meshes]), axis=0)
        expected_ext = np.asarray(rows[name]['dimensions_local_m'])
        error = float(np.max(abs(ext - expected_ext)))
        axes.append(dict(id=name, actual_local_xyz_m=ext.tolist(), expected_xyz_m=expected_ext.tolist(), max_error_m=error, passed=error < 1e-5))
    if not all(a['passed'] for a in axes): raise ValueError('Semantic physical frame mismatch')
    # A separate task instance uses exactly the source book mesh, collider, and mass.
    book = binding['objects']['leaning_book_01']
    # Task instances are instantiated by models.py, not present in the frozen base scene.
    write_json(output / 'objects.json', rows)
    write_json(output / 'axis_audit.json', axes)
    ET.indent(root); ET.ElementTree(root).write(output / 'scene_baseline.xml', encoding='unicode')
    # Task-relevant cavity repair: source surface voxels, no global convex envelope or dilation.
    desk = trimesh.util.concatenate(geometry['explicit_desk'])
    proxy = build_voxel_sdf(desk, pitch=.01, padding_voxels=2, fill_interior=False, surface_dilation_voxels=0,
                            metadata={'source': bound(glb), 'object_id': 'explicit_desk', 'surface_shell_not_measured_solid': True})
    proxy.save(output / 'desk_surface_voxels.npz')
    centers, half_sizes = voxel_boxes(proxy)
    np.savez_compressed(output / 'desk_cuboids.npz', centers=centers, half_sizes=half_sizes)
    body = bodies['explicit_desk']
    for geom in list(body.findall('geom')):
        if geom.get('name', '').startswith('col_'): body.remove(geom)
    for i, (c, h) in enumerate(zip(centers, half_sizes)):
        ET.SubElement(body, 'geom', name=f'col_explicit_desk_{i}', type='box', pos=vec(c), size=vec(h), mass='0', group='3')
    ET.indent(root); ET.ElementTree(root).write(output / 'scene_repaired.xml', encoding='unicode')
    # Source-derived cavity measurements in physical local coordinates.
    points = np.array([[0, 0, -.15], [0, 0, 0], [0, 0, .34]])
    hull = desk.convex_hull
    hull_inside = hull.contains(points)
    voxel_inside = proxy.query(points) < 0
    repair = dict(object_id='explicit_desk', method='undilated 10 mm source surface voxels covered by disjoint cuboids',
        cuboid_count=len(centers), local_probe_points_m=points.tolist(), baseline_hull_occupied=hull_inside.tolist(),
        repaired_occupied=voxel_inside.tolist(), occupied_volume_m3=float(np.prod(half_sizes*2, axis=1).sum()),
        old_hull_volume_m3=float(hull.volume), mass_changed=False, visual_changed=False,
        approximation='10 mm surface shell may shift contact by up to a voxel; not true solid volume')
    write_json(output / 'repair.json', repair)
    # Copy the pinned robot package to keep the exported package movable.
    provenance_path=robot_dir.parent / 'PROVENANCE.json'
    provenance=json.loads(provenance_path.read_text())
    if provenance['commit'] != '8161bba264d7fa7c99ca301e91e7fb44737676ad':
        raise ValueError('Stretch source version differs from frozen pilot')
    for row in provenance['files']:
        verify_binding(dict(row,path=str(robot_dir.parent / row['path'])))
    shutil.copytree(robot_dir, output / 'robots/stretch')
    shutil.copy2(provenance_path,output / 'robots/STRETCH_PROVENANCE.json')
    panda_root = Path('/data/wsj/anaconda3/envs/simgen/lib/python3.10/site-packages/robosuite/models/assets')
    shutil.copytree(panda_root / 'robots/panda', output / 'robots/panda')
    shutil.copytree(panda_root / 'grippers/meshes/panda_gripper', output / 'robots/panda_gripper/meshes/panda_gripper')
    shutil.copy2(panda_root / 'grippers/panda_gripper.xml', output / 'robots/panda_gripper/panda_gripper.xml')
    shutil.copy2(panda_root.parents[2] / 'robosuite-1.5.1.dist-info/LICENSE',output / 'robots/PANDA_LICENSE')
    write_json(output / 'target_physics.json', book)
    write_json(output / 'manifest.json', dict(schema='scene-embodied-package/v1', package_revision='embodied-phase1-v3', source_scene_content_sha256=expected, source_scene_id=plan['scene_id'],
        units=dict(length='m', mass='kg', time='s', angle='rad'), axes='right-handed world Z up; object local semantic XYZ=width,length,height',
        dependencies=dependency, visual_source=bound(glb), visuals=visuals,
        texture_policy='base color only, capped at 512 px; no claim of PBR parity; original GLB retained as authoritative source',
        texture_convention=TEXTURE_CONVENTION, obj_uv_policy='original TEXCOORD_0 unchanged',
        visual_face_count=sum(v['faces'] for v in visuals), scene_objects=len(binding['objects']),
        simulator='MuJoCo 3.3.4', frozen_original_books=5, export_wall_seconds=time.monotonic()-started,
        target_templates={'task_book': {'source_instance':'leaning_book_01','role':'free_rigid_target','pose_source':'episode/task.json'}},
        robot_sources=dict(stretch='MuJoCo Menagerie pinned in baseline/menagerie/PROVENANCE.json', panda='robosuite 1.5.1; package model inertias are approximations')))
    print('Package exported', output, flush=True)
