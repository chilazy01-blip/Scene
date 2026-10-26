"""Assemble new declarative workspaces using audited source meshes."""
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import json
import shutil

import numpy as np
from PIL import Image, ImageOps
from scipy.spatial.transform import Rotation

from sage.experiments.embodied_scene_v1.models import make_task, prune_assets
from sage.experiments.embodied_scene_v1.package import bound, vec, set_pose
from .common import write, digest

SOURCE = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_phase1_20260913_v1/package_v3')


def validate_requirements(spec):
    """Reject impossible declared grasp and passage dimensions before building."""
    for key in ('grasp_width_m', 'gripper_max_opening_m', 'clearance_m'):
        if not np.isfinite(spec[key]) or spec[key] <= 0:
            raise ValueError('invalid_dimension:' + key)
    if spec['grasp_width_m'] + 2 * spec['clearance_m'] > spec['gripper_max_opening_m']:
        raise ValueError('gripper_too_narrow')
    if spec.get('navigation'):
        nav = spec['navigation']
        values = [nav[k] for k in ('passage_width_m', 'robot_width_m', 'clearance_m')]
        if not np.isfinite(values).all() or min(values) <= 0:
            raise ValueError('invalid_navigation_dimensions')
        if values[0] < values[1] + 2 * values[2]:
            raise ValueError('passage_too_narrow')


def camera_axes(position, target):
    forward = np.asarray(target) - position
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0., 0., 1.]); right /= np.linalg.norm(right)
    return np.r_[right, np.cross(right, forward)]


def build_workspace(output, specification, source=SOURCE):
    """Source meshes are reused; placement, task and room are new inputs."""
    output, source = Path(output), Path(source)
    spec = deepcopy(specification)
    validate_requirements(spec['functional'])
    make_task(source, output, 'pick_place', 'repaired', False, False)
    root = ET.parse(output / 'model.xml').getroot()
    world = root.find('worldbody')
    retained = {'explicit_desk', 'explicit_bookcase', 'explicit_office_chair', 'task_book', 'base'}
    for child in list(world):
        if child.tag == 'light' or (child.tag == 'body' and child.get('name') in retained):
            continue
        world.remove(child)
    yaw = float(spec['workspace_yaw_rad'])
    rot = Rotation.from_euler('z', yaw).as_matrix()
    origin = np.array([.58, 1.4, 0.])
    center = np.r_[spec['desk_xy_m'], 0.]

    def point(x):
        return rot @ (np.asarray(x) - origin) + center

    for name in ('explicit_desk', 'base', 'task_book'):
        body = world.find(f"body[@name='{name}']")
        pos = np.fromstring(body.get('pos'), sep=' ')
        q = np.fromstring(body.get('quat', '1 0 0 0'), sep=' ')
        transform = np.eye(4)
        transform[:3, :3] = rot @ Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix()
        transform[:3, 3] = point(pos)
        set_pose(body, transform)
    for name in ('explicit_bookcase', 'explicit_office_chair'):
        body = world.find(f"body[@name='{name}']")
        body.set('pos', vec(spec['background'][name]['position_m']))
        a = spec['background'][name]['yaw_rad']
        body.set('quat', vec([np.cos(a / 2), 0, 0, np.sin(a / 2)]))
    ET.SubElement(world, 'geom', name='floor', type='box', pos='2.1 1.9 -.04',
                  size='2.1 1.9 .04', rgba='.68 .65 .60 1', friction='.5 .005 .0001')
    for name, pos, size in [('north', '2.1 3.82 1.4', '2.1 .02 1.4'),
                            ('west', '-.02 1.9 1.4', '.02 1.9 1.4'),
                            ('east', '4.22 1.9 1.4', '.02 1.9 1.4'),
                            ('south', '2.1 -.02 1.4', '2.1 .02 1.4')]:
        ET.SubElement(world, 'geom', name='wall_' + name, type='box', pos=pos, size=size,
                      rgba='.85 .87 .87 1')
    base_pos = point([.55, 1.92, .77])
    ET.SubElement(world, 'geom', name='robot_mount', type='box',
                  pos=vec(base_pos - [0, 0, .01]), size='.09 .09 .01', rgba='.18 .2 .22 1')
    goal = point([.78, 1.25, .88])
    # A declared noncolliding task marker, not a substitute for support geometry.
    ET.SubElement(world, 'site', name='goal_marker', type='box', pos=vec([*goal[:2], .765]),
                  size='.045 .105 .001', rgba='.05 .7 .2 .5')
    camera = spec['camera']
    ET.SubElement(world, 'camera', name='front', pos=vec(camera['position_m']),
                  xyaxes=vec(camera_axes(camera['position_m'], [*center[:2], .95])), fovy=str(camera['fovy_deg']))
    root.find('visual/global').set('offwidth', '960')
    root.find('visual/global').set('offheight', '720')
    root.find('visual').append(ET.Element('quality', shadowsize='2048', offsamples='2'))
    prune_assets(root)
    asset_dir = output / 'assets'; asset_dir.mkdir()
    sources = []
    for element in root.findall('asset/*'):
        filename = element.get('file')
        if not filename:
            continue
        source_path = Path(filename)
        identity = hashlib.sha256(str(source_path).encode()).hexdigest()[:10]
        destination = asset_dir / (identity + '_' + source_path.name)
        corrected = element.tag == 'texture' and source_path.parent == source / 'assets'
        if corrected:
            with Image.open(source_path) as img:
                ImageOps.flip(img).save(destination)
        else:
            shutil.copyfile(source_path, destination)
        element.set('file', 'assets/' + destination.name)
        sources.append(dict(source=bound(source_path), delivered=destination.name,
                            sha256=bound(destination)['sha256'], legacy_texture_rows_flipped=corrected))
    shutil.copyfile(source / 'robots/PANDA_LICENSE', output / 'PANDA_LICENSE')
    ET.indent(root); ET.ElementTree(root).write(output / 'model.xml', encoding='unicode')
    task = dict(task='pick_place', robot='Panda', scene_id=spec['scene_id'],
                start=point([.78, 1.48, .88]).tolist(), goal=goal.tolist(),
                workspace_rotation=rot.tolist(), grasp_yaw_rad=yaw,
                instruction='Pick up the upright book and place it in the green region on the desk.',
                dt_s=.001, policy_dt_s=.05, duration_s=18.7,
                initialization_xy_jitter_m=.012, material_measured=False,
                support_owner='explicit_desk',
                acceptance=dict(goal_xy_tolerance_m=.06, max_final_speed_m_s=.03,
                                stable_seconds=1., max_robot_scene_penetration_m=.003,
                                min_lift_m=.08, min_bilateral_force_n=1., min_bilateral_seconds=.05),
                allowed_robot_contact_owners=['base', 'task_book'],
                allowed_robot_contact_geoms=['floor', 'robot_mount'])
    write(output / 'task.json', task)
    write(output / 'scene_request.json', spec)
    write(output / 'scene_manifest.json', dict(schema='scene-workspace/v0', request_digest=digest(spec),
          source_manifest=bound(source / 'manifest.json'), dependencies=sources, assets_reused=True,
          new_asset_generation=False, original_source_scene_replayed=False,
          scope='three new workspace arrangements in one family; source meshes shared with development history',
          texture_policy='one row flip on original legacy package textures; robot textures copied unchanged',
          physics='source-derived desk surface cuboids and book convex hull; declared unmeasured mass/friction',
          license_status='Panda license included; generated-scene provenance retained; commercial redistribution not asserted'))
    return task


def workspace_specs():
    result = []
    for i, (xy, yaw) in enumerate([([1.8, 1.5], 0.), ([1.85, 1.6], .12), ([1.75, 1.55], -.12)]):
        result.append(dict(scene_id=f'workspace_{i:02d}', desk_xy_m=xy, workspace_yaw_rad=yaw,
            functional=dict(grasp_width_m=.03, gripper_max_opening_m=.08, clearance_m=.005),
            camera=dict(position_m=[3.15, .35, 2.25], fovy_deg=45),
            background={'explicit_bookcase':dict(position_m=[.9 + .5*i, 3.5, .8], yaw_rad=0.),
                        'explicit_office_chair':dict(position_m=[3.4, 2.7-.3*i, .525], yaw_rad=-.5+.5*i)}))
    return result
