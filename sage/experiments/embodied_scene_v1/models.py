"""Compose existing robots and explicit task configurations with the scene package."""
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
import json

import numpy as np
from .package import vec, write_json

ARM_BASE = [.55, 1.92, .77]
BOOK_START = [.78, 1.48, .88]
BOOK_GOAL = [.78, 1.25, .88]
NAV_START = [4.95, .85, .004]
NAV_GOAL = [1.97, 1.98]


def merge(root, other):
    for child in other:
        if child.tag in ('compiler', 'option', 'visual', 'statistic', 'keyframe'): continue
        target = root.find(child.tag)
        if target is None:
            root.append(deepcopy(child))
        else:
            target.extend(deepcopy(list(child)))


def absolute_assets(root, directory, asset_subdir=''):
    directory = Path(directory)
    for a in root.findall('asset/*'):
        if a.get('file'):
            a.set('file', str((directory / asset_subdir / a.get('file')).resolve()))


def prune_assets(root):
    asset = root.find('asset')
    names = {v for e in root.iter() if e.tag not in ('mesh', 'texture', 'material') for k, v in e.attrib.items() if k in ('mesh', 'material', 'texture')}
    changed = True
    while changed:
        before = set(names)
        for a in asset:
            if a.get('name') in names:
                names.update(v for k, v in a.attrib.items() if k in ('texture', 'material'))
        changed = names != before
    for a in list(asset):
        # Unnamed robot meshes are referenced by filename stem.
        name = a.get('name', Path(a.get('file', '')).stem)
        if name not in names: asset.remove(a)


def make_task(package, output, task, variant='baseline', reference=False, physics_only=False):
    package, output = Path(package), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = ET.parse(package / f'scene_{variant}.xml').getroot()
    absolute_assets(root, package, 'assets')
    root.find('compiler').attrib.pop('meshdir', None)
    root.find('compiler').attrib.pop('texturedir', None)
    world = root.find('worldbody')
    book_source = deepcopy(world.find("body[@name='leaning_book_01']"))
    if reference:
        for e in list(world):
            if e.tag != 'light': world.remove(e)
        ET.SubElement(world, 'geom', name='floor', type='plane', size='8 8 .1', rgba='.65 .65 .65 1')
        if task == 'pick_place':
            ET.SubElement(world, 'geom', name='reference_table', type='box', pos='.58 1.4 .375', size='.36 .7 .375', rgba='.45 .3 .15 1')
    if task == 'pick_place':
        robot = ET.parse(package / 'robots/panda/robot.xml').getroot()
        gripper = ET.parse(package / 'robots/panda_gripper/panda_gripper.xml').getroot()
        absolute_assets(robot, package / 'robots/panda'); absolute_assets(gripper, package / 'robots/panda_gripper')
        robot.find("worldbody/body[@name='base']").set('pos', vec(ARM_BASE))
        robot.find("worldbody/body[@name='base']").set('quat', '.7071067812 0 0 -.7071067812')
        robot.find(".//body[@name='right_hand']").append(deepcopy(gripper.find('worldbody/body')))
        gripper.remove(gripper.find('worldbody'))
        merge(root, robot); merge(root, gripper)
        # A robot mounting fixture is part of the robot setup, not generated furniture.
        ET.SubElement(world, 'geom', name='robot_mount', type='box', pos=vec([*ARM_BASE[:2], .76]),
                      size=vec([.09, .09, .01]), rgba='.18 .2 .22 1')
        book_source.set('name', 'task_book'); book_source.set('pos', vec(BOOK_START)); book_source.set('quat', '1 0 0 0')
        for child in book_source:
            if child.get('name'): child.set('name', 'target_' + child.get('name'))
        for inertial in list(book_source.findall('inertial')): book_source.remove(inertial)
        ET.SubElement(book_source, 'freejoint', name='target_free')
        p = json.loads((package / 'target_physics.json').read_text())
        ET.SubElement(book_source, 'inertial', mass=str(p['mass_kg']), pos=vec(p['center_of_mass_body_m']),
                      diaginertia=vec(p['principal_inertia_kg_m2']), quat=vec(p['inertial_quaternion_wxyz']))
        world.append(book_source)
        spec = dict(task='pick_place', target_id='task_book', source_instance='leaning_book_01', start=BOOK_START, goal=BOOK_GOAL,
            robot='robosuite 1.5.1 Panda', controller='damped least-squares IK + torque-limited joint PD with model bias compensation; finite state pick/place',
            arm_base=ARM_BASE, success=dict(min_lift_m=.08, goal_xy_tolerance_m=.06, max_final_speed_m_s=.03,
                minimum_release_settle_s=1, required_gripper_target_bilateral_contact=True, required_support_contact=True,
                max_robot_scene_penetration_m=.003), mass_kg=p['mass_kg'], material_measured=False)
    elif task == 'navigate':
        robot = ET.parse(package / 'robots/stretch/stretch.xml').getroot()
        absolute_assets(robot, package / 'robots/stretch/assets')
        robot.find('worldbody/body').set('pos', vec(NAV_START))
        merge(root, robot)
        spec = dict(task='navigate', start=NAV_START, goal=NAV_GOAL, robot='MuJoCo Menagerie Stretch 2',
            controller='ground-truth occupancy A* + waypoint heading controller + wheel velocity feedback into original torque motors',
            success=dict(goal_xy_tolerance_m=.12, max_final_speed_m_s=.04, max_robot_scene_penetration_m=.003,
                         no_forbidden_furniture_contact=True), observation_policy='privileged state pilot, not visual policy',
            wheel_radius_m=.0508, wheel_track_m=.3407, planner_radius_m=.38)
    else: raise ValueError('Unknown task')
    spec.update(reference=reference, scene_variant=variant, dt_s=.001, control_interval_s=.001, seed=0,
        pose_writes_during_episode=False, target_welds=False, reset_only_initialization=True)
    if physics_only:
        # Strip only zero-mass Scene visual geoms; robot meshes may contribute inertia.
        for parent in root.iter():
            for child in list(parent):
                name=child.get('name','')
                if child.tag=='geom' and (name.startswith('vis_') or name.startswith('target_vis_')):
                    if child.get('mass')!='0' or child.get('contype')!='0' or child.get('conaffinity')!='0':
                        raise ValueError('Only inertial-free noncolliding visuals can be stripped')
                    parent.remove(child)
    spec['physics_only']=physics_only
    spec['rgb_scene_observations_available']=not physics_only
    prune_assets(root)
    ET.indent(root)
    ET.ElementTree(root).write(output / 'model.xml', encoding='unicode')
    write_json(output / 'task.json', spec)
    return spec
