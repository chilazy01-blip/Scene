"""Describe saved contacts without advancing or reconstructing a simulator state.

All force quantities use the saved vertical *normal* force only. Tangential
contact frames were not saved, so these are not complete resultant wrenches.
"""
import itertools
import numpy as np
from scipy.spatial import ConvexHull


def rotations(quaternions):
    q = np.asarray(quaternions, dtype=float)
    if q.ndim != 2 or q.shape[1] != 4 or not np.isfinite(q).all():
        raise ValueError('invalid_quaternions')
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError('zero_quaternion')
    w, x, y, z = (q/norms).T
    return np.stack([1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y),
                     2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x),
                     2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)], axis=1).reshape(-1, 3, 3)


def support_margin(points, query):
    """Signed 2D convex-support margin (m); point/line sets have zero area.

    Negative means outside. Inside polygon margin is distance to its nearest
    edge. For degenerate sets return minus distance to the point/segment.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    query = np.asarray(query, dtype=float)
    if not np.isfinite(points).all() or not np.isfinite(query).all():
        raise ValueError('nonfinite_support')
    points = np.unique(points, axis=0)
    if not len(points):
        return np.nan, 0., 0
    centered = points-points.mean(0)
    if len(points) == 1:
        return -float(np.linalg.norm(query-points[0])), 0., 1
    _, sv, vt = np.linalg.svd(centered, full_matrices=False)
    if len(points) == 2 or sv[-1] < 1e-10:
        along = centered @ vt[0]
        a, b = points[np.argmin(along)], points[np.argmax(along)]
        fraction = np.clip(np.dot(query-a, b-a)/np.dot(b-a, b-a), 0., 1.)
        return -float(np.linalg.norm(query-(a+fraction*(b-a)))), 0., 2
    hull = ConvexHull(points)
    margin = -float(np.max(hull.equations[:, :2] @ query + hull.equations[:, 2]))
    return margin, float(hull.volume), len(hull.vertices)


def first_run(mask, dt, duration=0.):
    """Index of the start of the first run, rather than its confirmation time."""
    needed = max(1, int(np.ceil(duration/dt-1e-10)))
    count = 0
    for i, value in enumerate(mask):
        count = count+1 if value else 0
        if count >= needed:
            return i-needed+1
    return None


def finite_summary(values):
    v = np.asarray(values); v = v[np.isfinite(v)]
    if not len(v):
        return dict(count=0, minimum=None, median=None, maximum=None)
    return dict(count=len(v), minimum=float(v.min()), median=float(np.median(v)), maximum=float(v.max()))


def trace(raw, initial, description, task, roi, diagnostics, dt):
    q, v, contacts = (np.asarray(raw[k]) for k in ['qpos', 'qvel', 'contacts'])
    n = len(q)
    if n == 0 or q.shape != (n, 7) or v.shape != (n, 6) or contacts.ndim != 2 or contacts.shape[1] != 15:
        raise ValueError('invalid_trace_shape')
    if not all(np.isfinite(raw[k]).all() for k in raw):
        raise ValueError('nonfinite_trace')
    if not np.allclose(raw['time'], np.arange(1, n+1)*dt, atol=1e-10, rtol=0):
        raise ValueError('invalid_trace_clock')
    pre = np.concatenate([np.asarray(initial['qpos'])[None, :], q[:-1]])
    qa, qb = description['state_target_qpos_slice']
    if not np.array_equal(raw['full_state'][:-1, qa:qb], pre):
        raise ValueError('pre_state_mismatch')
    rr, pre_rr = rotations(q[:, 3:]), rotations(pre[:, 3:])
    com = pre[:, :3] + np.einsum('nij,j->ni', pre_rr, description['target_ipos'])
    corners = np.array(list(itertools.product((-1., 1.), repeat=3)))*np.asarray(task['target_dimensions_m'])/2
    world = np.einsum('nij,kj->nki', rr, corners)+q[:, None, :3]
    pose = np.asarray(task['cavity']['pose_z_up'])
    local = (world-pose[:3, 3]) @ pose[:3, :3]
    within = (local[:, :, :2].min(1) >= roi[0]-1e-9).all(1) & (local[:, :, :2].max(1) <= roi[1]+1e-9).all(1)
    tilt = np.degrees(np.arccos(np.clip(rr[:, 2, 2], -1, 1)))
    pitch = np.degrees(np.arctan2(rr[:, 0, 2], rr[:, 2, 2]))
    drift = np.linalg.norm(q[:, :2]-initial['qpos'][:2], axis=1)
    support = np.zeros(n); wall = np.zeros(n); penetration = np.zeros(n)
    cop = np.full((n, 2), np.nan); margin = np.full(n, np.nan); area = np.zeros(n)
    active = np.zeros(n, int); outside_force = np.zeros(n)
    count_normal_down = 0
    if len(contacts):
        steps = contacts[:, 0].astype(int)
        if not np.array_equal(steps, contacts[:, 0]) or steps.min() < 0 or steps.max() >= n:
            raise ValueError('invalid_contact_step')
        if np.any(np.diff(steps) < 0):
            raise ValueError('unordered_contact_steps')
        g1, g2, kind = contacts[:, [1, 2, 3]].astype(int).T
        first_target = np.isin(g1, description['target_geom_ids'])
        if not np.all(first_target != np.isin(g2, description['target_geom_ids'])):
            raise ValueError('contact_target_mismatch')
        other = np.where(first_target, g2, g1)
        expected = np.where(np.isin(other, description['bottom_geom_ids']), 0,
            np.where(np.isin(other, description['wall_geom_ids']), 1,
                np.where(np.isin(other, description['desk_geom_ids']), 2, 3)))
        if not np.array_equal(expected, kind):
            raise ValueError('contact_category_mismatch')
        np.maximum.at(penetration, steps, np.maximum(0., -contacts[:, 4]))
        np.add.at(wall, steps[kind == 1], np.maximum(0., contacts[kind == 1, 9]))
        nz = contacts[:, 8]; epsilon = diagnostics['positive_vertical_normal_force_epsilon_N']
        count_normal_down = int(np.sum((kind == 0) & (nz <= 0) & (contacts[:, 9] > epsilon)))
        mask = (kind == 0) & (nz > diagnostics['support_normal_z_min_exclusive'])
        normal_vertical = np.maximum(0., nz[mask]*contacts[mask, 9])
        np.add.at(support, steps[mask], normal_vertical)
        selected = contacts[mask & (np.maximum(0., nz*contacts[:, 9]) > epsilon)]
        if len(selected):
            keys, starts = np.unique(selected[:, 0].astype(int), return_index=True)
            stops = np.r_[starts[1:], len(selected)]
            for index, start, stop in zip(keys, starts, stops):
                records = selected[start:stop]; weights = records[:, 8]*records[:, 9]
                xy = records[:, 5:7]
                cop[index] = np.average(xy, weights=weights, axis=0)
                margin[index], area[index], _ = support_margin(xy, com[index, :2])
                active[index] = len(records)
                local_points = (records[:, 5:8]-pose[:3, 3]) @ pose[:3, :3]
                outside = ((local_points[:, :2] < roi[0]-1e-9) | (local_points[:, :2] > roi[1]+1e-9)).any(1)
                outside_force[index] = weights[outside].sum()
    cop_relative = cop-com[:, :2]
    epsilon = diagnostics['positive_vertical_normal_force_epsilon_N']
    sustained = diagnostics['sustained_event_s']
    event_masks = {'first_bottom_support': support > epsilon,
        'first_wall_force': wall > epsilon, 'first_penetration_3mm': penetration > .003,
        'first_footprint_outside_roi': ~within, 'first_bottom_contact_outside_roi': outside_force > epsilon,
        'first_drift_10mm': drift > diagnostics['drift_event_m'],
        'support_COM_outside_20ms': np.isfinite(margin) & (margin < -1e-6)}
    for degrees in diagnostics['tilt_events_deg']:
        event_masks[f'first_tilt_{degrees}deg'] = tilt > degrees
    events = {}
    for name, mask in event_masks.items():
        index = first_run(mask, dt, sustained if name == 'support_COM_outside_20ms' else 0.)
        contacts_clock = name in {'first_bottom_support', 'first_wall_force', 'first_penetration_3mm', 'first_bottom_contact_outside_roi', 'support_COM_outside_20ms'}
        events[name] = None if index is None else dict(index=index,
            native_contact_time_s=index*dt if contacts_clock else None,
            post_state_time_s=(index+1)*dt, tilt_deg=float(tilt[index]),
            com_support_margin_m=float(margin[index]) if np.isfinite(margin[index]) else None,
            vertical_normal_support_N=float(support[index]))
    first = first_run(support > epsilon, dt)
    windows = []
    for seconds in diagnostics['time_windows_s']:
        start = first or 0; stop = min(n, start+int(round(seconds/dt)))
        mm = margin[start:stop]; loaded = np.isfinite(mm)
        windows.append(dict(seconds_after_first_support=seconds, observed_seconds=(stop-start)*dt,
            loaded_step_fraction=float(loaded.mean()),
            COM_outside_fraction_among_loaded=float((mm[loaded] < -1e-6).mean()) if loaded.any() else None,
            support_margin_m=finite_summary(mm), cop_minus_com_x_m=finite_summary(cop_relative[start:stop, 0]),
            tilt_end_deg=float(tilt[stop-1]), pitch_end_deg=float(pitch[stop-1])))
    arrays = dict(time=raw['time'], native_contact_time=np.arange(n)*dt, com_pre_m=com,
        tilt_deg=tilt, pitch_deg=pitch, drift_m=drift, footprint_inside_roi=within,
        vertical_normal_support_N=support, wall_normal_force_N=wall, max_penetration_m=penetration,
        cop_xy_m=cop, cop_minus_com_xy_m=cop_relative, com_support_margin_m=margin,
        support_polygon_area_m2=area, active_support_contacts=active, outside_roi_vertical_normal_support_N=outside_force)
    summary = dict(events=events, windows=windows, steps=n, dt_s=dt,
        downward_bottom_contact_records=count_normal_down,
        minimum_support_margin_m=finite_summary(margin)['minimum'],
        maximum_tilt_deg=float(tilt.max()), maximum_drift_m=float(drift.max()),
        first_contact_relative_cop_xy_m=None if first is None else cop_relative[first].tolist())
    return arrays, summary


def coupled_envelope(xy, support_height, target_lower, center_xy, bands):
    """Nominal vertical-translation envelope on fixed samples, not dynamics."""
    valid = np.isfinite(support_height) & np.isfinite(target_lower)
    required_center_height = support_height[valid]-target_lower[valid]
    if not len(required_center_height):
        return {'samples':0, 'bands':[]}, np.full(len(xy), np.nan)
    top = float(required_center_height.max()); gap = np.full(len(xy), np.nan)
    gap[valid] = top-required_center_height
    rows = []
    for band in bands:
        mask = np.isfinite(gap) & (gap <= band)
        margin, area, vertices = support_margin(xy[mask], center_xy)
        rows.append(dict(band_m=band, samples=int(mask.sum()), com_projection_margin_m=margin,
            area_m2=area, hull_vertices=vertices))
    return dict(samples=int(valid.sum()), nominal_center_height_local_m=top,
        required_height_range_m=float(np.ptp(required_center_height)), bands=rows), gap
