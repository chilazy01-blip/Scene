"""Source-derived containment and actual MuJoCo bottom-support probes."""
import itertools
from pathlib import Path
import shutil
import mujoco
import numpy as np
from scipy.spatial import ConvexHull
from sage.experiments.embodied_scene_bridge.contracts import require, read, write, digest


def prepare_geometry(mesh, container, target, generator, evidence, output, pose):
    """Reuse the measured source voxel artifact with its GLB binding intact."""
    measurement = read(evidence/'GENERATED_CONTAINER_GEOMETRY.json')
    require(measurement['source_glb_sha256'] == digest(generator/'scene_codex_trellis_v2.glb'), 'container_geometry_source_changed')
    require(measurement['container']['id'] == container['id'], 'container_geometry_owner_changed')
    require(np.max(abs(mesh.bounds-np.asarray(measurement['bounds']))) < 1e-8, 'container_geometry_bounds_changed')
    with np.load(evidence/'generated_container_voxels.npz') as arrays:
        centers, sizes = arrays['centers'], arrays['half_sizes']
        occupied, origin, pitch = arrays['occupancy'], arrays['origin'], float(arrays['pitch'])
    require(pitch == .005, 'container_proxy_resolution')
    require(int(np.rint(2*sizes/pitch).prod(1).sum()) == int(occupied.sum()), 'container_cuboid_cover')
    lower, upper = centers-sizes, centers+sizes
    # Floor fragments are low source surfaces. High wall/rim cuboids are never support.
    bottom = upper[:, 2] <= mesh.bounds[0, 2]+.05
    dims = np.array([target['dimensions'][k] for k in ['width', 'length', 'height']])
    footprint = (lower[:, 0] <= dims[0]/2) & (upper[:, 0] >= -dims[0]/2) & (lower[:, 1] <= dims[1]/2) & (upper[:, 1] >= -dims[1]/2)
    require(np.any(bottom & footprint), 'container_source_bottom_absent')
    floor = float(upper[bottom & footprint, 2].max())
    rim = measurement['conservative_rim_z']-pitch
    inner_lo = np.array([-.1, -.11, mesh.bounds[0, 2]])
    inner_hi = np.array([.1, .11, rim])
    points = origin+np.argwhere(occupied)*pitch
    in_prism = ((points[:, 0]+pitch/2 > inner_lo[0]) & (points[:, 0]-pitch/2 < inner_hi[0])
                & (points[:, 1]+pitch/2 > inner_lo[1]) & (points[:, 1]-pitch/2 < inner_hi[1])
                & (points[:, 2]+pitch/2 > floor+pitch) & (points[:, 2]-pitch/2 < rim))
    require(not in_prism.any(), 'container_certified_prism_occupied')
    require(rim-floor-dims[2] >= .005, 'target_not_fully_below_real_rim')
    require(np.all(dims[:2]+.01 < inner_hi[:2]-inner_lo[:2]), 'target_does_not_fit_inner_xy')
    names = [f'container_bottom_col_{i}' if bottom[i] else f'container_wall_col_{i}' for i in range(len(centers))]
    shutil.copyfile(evidence/'generated_container_voxels.npz', output/'container_cuboids.npz')
    shutil.copyfile(evidence/'GENERATED_CONTAINER_GEOMETRY.json', output/'container_source_measurement.json')
    certificate = dict(schema='generated-container-cavity/v1', verified=True,
        scope='source geometry and conservative 5mm surface proxy; actual model/robot/load checks required',
        source_glb_sha256=measurement['source_glb_sha256'], semantic_id=container['id'], pose_z_up=pose.tolist(),
        inner_bounds_local_m=[inner_lo.tolist(), inner_hi.tolist()], bottom_surface_z_local_m=floor,
        rim_z_local_m=rim, measured_wall_rim_z_local_m=measurement['conservative_rim_z'],
        highest_collision_z_world_m=float(pose[2, 3]+upper[:, 2].max()),
        bottom_geoms=[name for name, flag in zip(names, bottom) if flag],
        wall_geoms=[name for name, flag in zip(names, bottom) if not flag],
        source_bottom_ray_coverage=measurement['bottom_ray_coverage'],
        proxy_pitch_m=pitch, surface_dilation_voxels=0, fill_interior=False,
        empty_prism_occupied_cells=int(in_prism.sum()), source_occupied_voxels=int(occupied.sum()),
        collider_cuboids=len(centers), missing_surface_fill=False, artificial_bottom_added=False,
        minimum_nominal_top_clearance_m=float(rim-floor-dims[2]),
        cuboids_sha256=digest(output/'container_cuboids.npz'),
        source_measurement_sha256=digest(output/'container_source_measurement.json'))
    write(output/'container_certificate.json', certificate)
    return centers, sizes, names, certificate


def object_corners(task, position, quaternion):
    rotation = np.empty(9)
    mujoco.mju_quat2Mat(rotation, np.asarray(quaternion, dtype=float))
    corners = np.array(list(itertools.product((-1., 1.), repeat=3))) * np.asarray(task['target_dimensions_m']) / 2
    return corners @ rotation.reshape(3, 3).T + position


def containment(task, position, quaternion):
    cavity = task['cavity']
    pose = np.asarray(cavity['pose_z_up'])
    local = (object_corners(task, position, quaternion) - pose[:3, 3]) @ pose[:3, :3]
    lo, hi = np.asarray(cavity['inner_bounds_local_m'])
    side = float(min(np.min(local[:, :2] - lo[:2]), np.min(hi[:2] - local[:, :2])))
    top = float(hi[2] - local[:, 2].max())
    bottom = float(local[:, 2].min() - lo[2])
    margin = task['success']['container_inner_margin_m']
    return dict(inside=bool(side >= margin and top >= margin and bottom >= margin),
                side_margin_m=side, rim_margin_m=top, bottom_margin_m=bottom,
                local_min=local.min(0).tolist(), local_max=local.max(0).tolist())


def bottom_probe(model, data, task):
    """Woven holes may miss rays; distributed real bottom must span the COM."""
    rotation = np.asarray(task['target_rotation'])
    dims = np.asarray(task['target_dimensions_m'])
    center = np.asarray(task['goal'])
    bottom = {model.geom(name).id for name in task['cavity']['bottom_geoms']}
    group = np.array([0, 0, 0, 1, 0, 0], dtype=np.uint8)
    xs = np.linspace(-dims[0]/2, dims[0]/2, max(5, int(np.ceil(dims[0]/.005))+1))
    ys = np.linspace(-dims[1]/2, dims[1]/2, max(5, int(np.ceil(dims[1]/.005))+1))
    points, samples = [], []
    for x, y in itertools.product(xs, ys):
        xy = (center + rotation @ [x, y, 0])[:2]
        origin = np.r_[xy, task['cavity']['highest_collision_z_world_m']+.02]
        geom = np.array([-1], dtype=np.int32)
        distance = mujoco.mj_ray(model, data, origin, np.array([0., 0., -1.]), group, 1,
                                 model.body(task['target_body']).id, geom)
        supported = distance >= 0 and int(geom[0]) in bottom
        if supported:
            points.append(xy)
        samples.append(dict(xy=xy.tolist(), geom=int(geom[0]), supported=bool(supported)))
    coverage = len(points) / len(samples)
    require(coverage >= .5 and len(points) >= 12, 'container_bottom_missing_or_blocked')
    hull = ConvexHull(np.asarray(points))
    distance = hull.equations[:, :2] @ center[:2] + hull.equations[:, 2]
    require(np.max(distance) <= -.005, 'container_bottom_does_not_span_target_COM')
    return dict(ray_coverage=coverage, samples=samples,
                COM_support_margin_m=float(-np.max(distance)),
                meaning='distributed source bottom; physical load test still required')
