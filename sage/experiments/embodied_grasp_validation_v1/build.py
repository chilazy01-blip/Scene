"""Replace only the declared target using a frozen existing source asset."""
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import trimesh
import mujoco
from sage.experiments.codex_trellis_scene_v2.asset_geometry_dimensions import canonical_vertices


def write(path, value):
    path = Path(path)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def build(config, combination, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    source = Path(combination['asset_file'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == combination['asset_sha256']
    mesh = trimesh.load(source, force='scene').dump(concatenate=True)
    mesh.vertices = canonical_vertices(mesh.vertices, combination['asset'])
    dims = np.array([combination['asset']['dimensions'][k] for k in ('width', 'length', 'height')])
    scale = dims / mesh.extents
    assert scale.max()/scale.min() < 1.001, 'source_proportions_changed'
    mesh.apply_scale(float(np.mean(scale)))
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    hull = mesh.convex_hull
    assert hull.is_watertight and hull.volume > 0
    mesh.export(output/'target_visual.stl')
    hull.export(output/'target_collision.stl')
    tree = ET.parse(config['source_model'])
    root = tree.getroot()
    body = root.find(".//body[@name='target']")
    target_geoms = body.findall('geom')
    assert len(target_geoms) == 2
    for geom, filename in zip(target_geoms, ('target_collision.stl', 'target_visual.stl')):
        asset = root.find("./asset/mesh[@name='"+geom.get('mesh')+"']")
        asset.set('file', str((output/filename).resolve()))
        geom.set('friction', ' '.join(map(str, combination['friction'])))
    target_geoms[1].attrib.pop('material', None)
    target_geoms[1].set('rgba', '.75 .82 .87 1')
    mass = combination['mass_kg']
    inertia = hull.moment_inertia * mass/hull.mass
    inertial = body.find('inertial')
    inertial.attrib.clear()
    inertial.set('mass', str(mass))
    inertial.set('pos', ' '.join(map(str, hull.center_mass)))
    inertial.set('fullinertia', ' '.join(map(str, [*np.diag(inertia), inertia[0,1], inertia[0,2], inertia[1,2]])))
    # First compile places the target above all support rays, before any integration.
    xy = np.array(combination['start_xy_m'])
    body.set('pos', ' '.join(map(str, [*xy, 2.])))
    body.set('quat', '1 0 0 0')
    model_path = output/'model.xml'
    tree.write(model_path)
    m = mujoco.MjModel.from_xml_path(str(model_path)); d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    target = m.body('target').id; support = m.body('support').id
    heights = []
    for center in (xy, xy + np.array(combination['goal_delta_world_m'][:2])):
        samples = []
        for dx in np.linspace(-dims[0]/2, dims[0]/2, 5):
            for dy in np.linspace(-dims[1]/2, dims[1]/2, 5):
                origin = np.r_[center+[dx,dy], 1.4]
                hit = np.array([-1], np.int32)
                distance = mujoco.mj_ray(m, d, origin, np.array([0.,0.,-1.]), np.array([1,0,0,1,0,0],np.uint8), 1, target, hit)
                assert distance >= 0 and m.geom_bodyid[hit[0]] == support, 'missing_support_under_footprint'
                samples.append(float(origin[2]-distance))
        heights.append(samples)
    assert max(map(max, heights))-min(map(min, heights)) < .004, 'support_height_variation'
    z = max(heights[0]) - hull.bounds[0,2] + 1e-6
    start = [*xy, z]
    goal = np.r_[xy + np.array(combination['goal_delta_world_m'][:2]), max(heights[1])-hull.bounds[0,2]+1e-6]
    body.set('pos', ' '.join(map(str,start)))
    tree.write(model_path)
    task = dict(id=combination['id'], asset_id=combination['asset']['asset_id'], model=str(model_path),
                support_asset_id=combination['support_asset_id'], start=start, goal=goal.tolist(),
                local_vertices=hull.vertices.tolist(), local_com=hull.center_mass.tolist(),
                mass_kg=mass, inertia_kg_m2=inertia.tolist(), friction=combination['friction'],
                support_top_z=max(map(max, heights)), support_ray_heights=heights,
                dimensions_m=mesh.extents.tolist(), physical_prior_measured=False,
                collision_shape='source convex hull; cavity and handle contact fidelity unqualified',
                placement=combination['placement'], physics_steps=0)
    write(output/'TASK.json', task)
    return task
