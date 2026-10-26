"""One source-derived local column recipe, with independent shifted-ray checks."""
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np

from .contracts import require, fingerprint


def vec(values):
    return ' '.join(format(float(v), '.17g') for v in np.asarray(values).ravel())


def source_mesh(context):
    import trimesh
    from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry
    manifest = context['docs']['scene_manifest.json']; task = context['docs']['task.json']
    objects = manifest['objects'] + manifest['architecture_objects']
    # The extractor needs only the room metadata and named semantic mesh groups.
    layout = __import__('json').loads((Path(context['path']).parent/'generator/layout_plan_final.json').read_text())
    groups, _ = _geometry(Path(manifest['source_glb']['path']),
                          dict(room=layout['room'], objects=[dict(id=o['semantic_id']) for o in objects]))
    obj = next(o for o in objects if o['semantic_id'] == task['container_semantic_id'])
    pose = np.asarray(obj['pose_z_up'])
    mesh = trimesh.util.concatenate([trimesh.Trimesh(
        (p['vertices']-pose[:3, 3]) @ pose[:3, :3], p['faces'], process=False)
        for p in groups[task['container_semantic_id']]])
    expected = context['docs']['container_source_measurement.json']
    require(np.allclose(mesh.bounds, expected['bounds'], rtol=0, atol=1e-8), 'source_mesh_bounds_mismatch')
    return mesh


def rays(mesh, xy, z, direction):
    result = np.full(len(xy), np.nan)
    origins = np.c_[xy, np.full(len(xy), z)]
    directions = np.tile([0., 0., direction], (len(xy), 1))
    hits, indices, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=False)
    result[indices] = hits[:, 2]
    return result


def box_heights(xy, centers, sizes):
    lower, upper = centers-sizes, centers+sizes
    result = np.full(len(xy), np.nan)
    for start in range(0, len(xy), 128):
        points = xy[start:start+128]
        mask = ((points[:, None, :] >= lower[None, :, :2]-1e-12)
                & (points[:, None, :] <= upper[None, :, :2]+1e-12)).all(2)
        z = np.max(np.where(mask, upper[None, :, 2], -np.inf), axis=1)
        result[start:start+len(points)] = np.where(np.isfinite(z), z, np.nan)
    return result


def outside_pieces(center, size, roi):
    """Partition a box minus an XY rectangle into <=4 nonoverlapping pieces."""
    lo, hi = center-size, center+size
    rlo, rhi = roi
    if np.any(hi[:2] <= rlo) or np.any(lo[:2] >= rhi):
        return [(center, size)]
    rectangles = [(lo[0], min(hi[0], rlo[0]), lo[1], hi[1]),
                  (max(lo[0], rhi[0]), hi[0], lo[1], hi[1]),
                  (max(lo[0], rlo[0]), min(hi[0], rhi[0]), lo[1], min(hi[1], rlo[1])),
                  (max(lo[0], rlo[0]), min(hi[0], rhi[0]), max(lo[1], rhi[1]), hi[1])]
    result = []
    for x0, x1, y0, y1 in rectangles:
        if x1-x0 > 1e-12 and y1-y0 > 1e-12:
            lower, upper = np.array([x0, y0, lo[2]]), np.array([x1, y1, hi[2]])
            result.append(((lower+upper)/2, (upper-lower)/2))
    return result


def bottom_boxes(context):
    task, root = context['docs']['task.json'], context['root']
    geoms = {g.get('name'): g for g in root.findall('.//geom')}
    names = task['cavity']['bottom_geoms']
    return (np.array([np.fromstring(geoms[n].get('pos'), sep=' ') for n in names]),
            np.array([np.fromstring(geoms[n].get('size'), sep=' ') for n in names]))


def make_candidate(mesh, original_centers, original_sizes, specification):
    roi = np.asarray(specification['roi_xy_m']); pitch = specification['pitch_m']
    count = np.rint((roi[1]-roi[0])/pitch).astype(int)
    require(np.allclose(count*pitch, roi[1]-roi[0], atol=1e-12), 'ROI_must_match_cell_grid')
    xs = roi[0, 0] + (np.arange(count[0])+.5)*pitch
    ys = roi[0, 1] + (np.arange(count[1])+.5)*pitch
    xx, yy = np.meshgrid(xs, ys, indexing='ij'); xy = np.c_[xx.ravel(), yy.ravel()]
    upper = rays(mesh, xy, 0., -1)
    lower = rays(mesh, xy, float(mesh.bounds[0, 2]-.01), 1)
    valid = np.isfinite(upper) & np.isfinite(lower) & (upper-lower > 1e-9)
    require(np.all(upper[valid] <= mesh.bounds[0, 2]+.05), 'ROI_intersects_nonbottom_surface')
    centers = np.c_[xy[valid], (upper[valid]+lower[valid])/2]
    sizes = np.c_[np.full((valid.sum(), 2), pitch/2), (upper[valid]-lower[valid])/2]
    outside = [part for c, s in zip(original_centers, original_sizes) for part in outside_pieces(c, s, roi)]
    if outside:
        centers = np.r_[centers, np.array([x[0] for x in outside])]
        sizes = np.r_[sizes, np.array([x[1] for x in outside])]
    require(len(centers) <= specification['max_bottom_boxes'], 'candidate_box_budget')
    require(np.isfinite(centers).all() and np.isfinite(sizes).all() and (sizes > 0).all(), 'invalid_candidate_boxes')
    return centers, sizes, dict(xy=xy, source_upper=upper, source_lower=lower, accepted_cell=valid,
        outside_piece_count=np.array(len(outside)), column_count=np.array(valid.sum()))


def fidelity(source, proxy):
    a, b = np.isfinite(source), np.isfinite(proxy)
    both = a & b
    errors = np.abs(proxy[both]-source[both])
    return dict(samples=len(source), source_coverage=float(a.mean()), proxy_coverage=float(b.mean()),
        proxy_only_sample_fraction=float((b & ~a).mean()), source_only_sample_fraction=float((a & ~b).mean()),
        height_abs_p95_m=float(np.quantile(errors, .95)) if len(errors) else None,
        height_abs_max_m=float(errors.max()) if len(errors) else None,
        height_signed_median_m=float(np.median(proxy[both]-source[both])) if len(errors) else None)


def fidelity_passed(measurement, thresholds):
    return (measurement['height_abs_p95_m'] is not None
            and measurement['height_abs_p95_m'] <= thresholds['height_abs_p95_m_max']
            and measurement['proxy_only_sample_fraction'] <= thresholds['proxy_only_sample_fraction_max']
            and measurement['source_only_sample_fraction'] <= thresholds['source_only_sample_fraction_max'])


def derived_xml(context, centers=None, sizes=None):
    """Remove the robot/decorative visuals identically; candidate replaces only bottom."""
    root = deepcopy(context['root']); task = context['docs']['task.json']
    world = root.find('worldbody'); removed = []
    for body in list(world.findall('body')):
        if body.get('name') != task['target_body'] and (body.findall('.//joint') or body.findall('.//freejoint')):
            removed.append(body.get('name')); world.remove(body)
    require(removed, 'unsupported_layout:no_robot_root_identified')
    for tag in ['actuator', 'sensor', 'tendon', 'equality', 'keyframe', 'contact', 'visual']:
        for node in list(root.findall(tag)):
            root.remove(node)
    for parent in list(root.iter()):
        for node in list(parent):
            if (node.tag == 'geom' and node.get('contype', '1') == '0' and node.get('conaffinity', '1') == '0') or node.tag in ('camera', 'light', 'site'):
                parent.remove(node)
    names = list(task['cavity']['bottom_geoms'])
    if centers is not None:
        body = root.find(".//body[@name='" + task['container_body'] + "']")
        for g in list(body.findall('geom')):
            if g.get('name') in names:
                body.remove(g)
        names = []
        for i, (c, s) in enumerate(zip(centers, sizes)):
            name = 'qc2_bottom_' + str(i); names.append(name)
            ET.SubElement(body, 'geom', name=name, type='box', pos=vec(c), size=vec(s), group='3', mass='0')
    used = {g.get('mesh') for g in root.findall('.//geom') if g.get('mesh')}
    asset = root.find('asset')
    for element in list(asset):
        if element.tag != 'mesh' or element.get('name') not in used:
            asset.remove(element)
        elif element.get('file'):
            require(element.get('file') in context['files'], 'unbound_derived_asset')
            element.set('file', str(Path(context['path'])/element.get('file')))
    # This fingerprint must match across both new variants.
    invariant = deepcopy(root)
    for parent in invariant.iter():
        for g in list(parent):
            if g.tag == 'geom' and g.get('name') in names:
                parent.remove(g)
    return ET.tostring(root, encoding='unicode'), names, dict(
        nonbottom_xml_sha256=fingerprint(ET.tostring(invariant, encoding='unicode')),
        removed_robot_roots=removed, decorative_visuals_removed=True)


def pose_metrics(task, position, rotation, roi):
    import itertools
    points = np.array(list(itertools.product((-1., 1.), repeat=3))) * np.asarray(task['target_dimensions_m'])/2
    world = points @ rotation.T + position
    pose = np.asarray(task['cavity']['pose_z_up'])
    local = (world-pose[:3, 3]) @ pose[:3, :3]
    low, high = local.min(0), local.max(0)
    bounds = np.asarray(task['cavity']['inner_bounds_local_m'])
    side = float(min(np.min(low[:2]-bounds[0, :2]), np.min(bounds[1, :2]-high[:2])))
    rim, bottom = float(bounds[1, 2]-high[2]), float(low[2]-bounds[0, 2])
    return side, rim, bottom, bool(np.all(low[:2] >= roi[0]-1e-9) and np.all(high[:2] <= roi[1]+1e-9))
