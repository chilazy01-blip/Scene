"""Read frozen packages, validate static declarations and compile without stepping.

Supported layout: generator-container-task-package/v1 with named scene bodies,
one named free target, legacy cavity/v1 and self-contained MJCF. No qpos offsets
or T00 body identifiers are assumed. Other layouts receive an explicit rejection.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from .contracts import (Rejected, digest, digest_bytes, finite, fingerprint, loads,
                        metric, relative_name, require)


def snapshot(package):
    package = Path(package).resolve()
    manifest_bytes = (package / 'FILES.json').read_bytes()
    files = loads(manifest_bytes)
    required = {'model.xml', 'task.json', 'scene_manifest.json', 'objects.json',
                'container_certificate.json', 'container_cuboids.npz',
                'container_source_measurement.json'}
    require(isinstance(files, dict) and required <= files.keys(), 'incomplete_package_manifest')
    blobs = {}
    for name, expected in files.items():
        relative_name(name)
        path = package / name
        require(path.resolve().is_relative_to(package), 'escaping_package_reference:' + name)
        require(path.is_file(), 'missing_package_file:' + name)
        data = path.read_bytes()
        require(digest_bytes(data) == expected, 'package_file_changed:' + name)
        blobs[name] = data
    root = ET.fromstring(blobs['model.xml'])
    require(root.tag == 'mujoco', 'unsupported_model_format')
    require(root.find('.//include') is None and root.find('.//plugin') is None,
            'unsupported_model_layout:include_or_plugin')
    compiler = root.find('compiler')
    require(compiler is not None and compiler.get('angle') == 'radian', 'unsupported_compiler_units')
    require(not any(compiler.get(k) for k in ('meshdir', 'texturedir', 'assetdir')),
            'unsupported_model_layout:asset_directory')
    for node in root.iter():
        if node.get('file'):
            require(relative_name(node.get('file')) in blobs, 'unbound_model_reference:' + node.get('file'))
    docs = {name: loads(blobs[name]) for name in required if name.endswith('.json')}
    require(finite(docs), 'nonfinite_package_declaration')
    return dict(path=str(package), manifest_sha256=digest_bytes(manifest_bytes),
                files=files, blobs=blobs, root=root, docs=docs)


def source_bindings(context, sources):
    """Missing external evidence stays unknown; provided inconsistent evidence fails."""
    manifest = context['docs']['scene_manifest.json']
    refs = dict(sources)
    refs['assembled_glb'] = manifest['source_glb']['path']
    for row in manifest['asset_resolution']:
        refs['asset:' + row['object_id']] = row['source']
    for i, row in enumerate(manifest.get('robot_sources', [])):
        refs['robot:' + str(i)] = row['source']
    bindings, missing, errors, documents = {}, [], [], {}
    expected = {'assembled_glb': manifest['source_glb']['sha256'],
                'layout': manifest['layout_sha256'], 'request': manifest['request_sha256']}
    for key in ('layout', 'request'):
        if key not in refs:
            missing.append(key)
    for key, path in sorted(refs.items()):
        p = Path(path).resolve()
        if not p.is_file():
            missing.append(key)
            bindings[key] = dict(path=str(p), sha256=None, bytes=None)
            continue
        if p.suffix == '.json':
            data = p.read_bytes()
            actual = digest_bytes(data)
            documents[key] = loads(data)
        else:
            actual = digest(p)
        bindings[key] = dict(path=str(p), sha256=actual, bytes=p.stat().st_size)
        if key in expected and actual != expected[key]:
            errors.append(key + '_binding_mismatch')
    for i, row in enumerate(manifest.get('robot_sources', [])):
        b = bindings['robot:' + str(i)]
        if b['sha256'] is not None and b['sha256'] != row['sha256']:
            errors.append('robot_source_binding_mismatch:' + str(i))
    state = 'fail' if errors else 'unknown' if missing else 'pass'
    evidence = ['sources:' + name for name in bindings]
    m = metric(state, dict(missing=missing, errors=errors, assets=len(manifest['asset_resolution'])),
               'sha256', {'rule': 'source GLB/layout/request and robot hashes match original manifest; '
                                    'source asset bytes identified now, no historical generation claim',
                          'source': 'scene_manifest.json'}, evidence,
               ';'.join(errors + missing) or 'Bound assembled source and current asset identities')
    return bindings, documents, m


def static_checks(context, documents):
    import numpy as np
    from io import BytesIO

    docs, root = context['docs'], context['root']
    task, manifest, objects, cert = [docs[k] for k in
        ('task.json', 'scene_manifest.json', 'objects.json', 'container_certificate.json')]
    require(manifest['schema'] == 'generator-container-task-package/v1'
            and task['schema'] == 'generated-task/v1' and task['task'] == 'place_in_container',
            'unsupported_package_schema_or_task')
    require(objects == manifest['objects'], 'object_manifest_mismatch')
    require(cert == task['cavity'], 'task_certificate_mismatch')
    require(manifest['cavity_certificate_sha256'] == context['files']['container_certificate.json'],
            'certificate_manifest_mismatch')
    require(len({o['semantic_id'] for o in objects}) == len(objects), 'duplicate_object_identity')
    by_body = {o['body']: o for o in objects}
    require(len(by_body) == len(objects), 'duplicate_body_identity')
    for role in ('target', 'support', 'container'):
        require(task[role + '_body'] in by_body, 'missing_role_body:' + role)
        require(by_body[task[role + '_body']]['semantic_id'] == task[role + '_semantic_id'],
                'role_identity_mismatch:' + role)
    target = by_body[task['target_body']]
    require(task.get('split') == manifest.get('split'), 'task_manifest_split_mismatch')
    require(np.allclose(task['start'], np.asarray(target['pose_z_up'])[:3, 3], rtol=0, atol=1e-8)
            and np.allclose(task['target_rotation'], np.asarray(target['pose_z_up'])[:3, :3], rtol=0, atol=1e-8)
            and np.allclose(task['support_pose'], by_body[task['support_body']]['pose_z_up'], rtol=0, atol=1e-8)
            and np.allclose(cert['pose_z_up'], by_body[task['container_body']]['pose_z_up'], rtol=0, atol=1e-8),
            'task_role_pose_declaration_mismatch')
    expected_goal = np.asarray(cert['pose_z_up'])[:3, 3] + np.asarray(cert['pose_z_up'])[:3, :3] @ np.array(
        [0., 0., cert['bottom_surface_z_local_m'] + task['target_dimensions_m'][2]/2])
    require(np.allclose(task['goal'], expected_goal, rtol=0, atol=1e-8), 'task_goal_pose_declaration_mismatch')
    require([o['body'] for o in objects if o['role'] == 'dynamic_task_target'] == [task['target_body']],
            'unsupported_model_layout:dynamic_scene_bodies')
    body_nodes = {n.get('name'): n for n in root.findall('.//body')}
    for o in objects:
        require(o['body'] in body_nodes, 'missing_model_body:' + o['body'])
        body = body_nodes[o['body']]
        require(body in list(root.find('worldbody')), 'unsupported_model_layout:nested_scene_body')
        require(body.get('childclass') is None, 'unsupported_model_layout:scene_childclass')
    body = body_nodes[task['target_body']]
    require(len(body.findall('freejoint')) == 1 and not body.findall('joint'),
            'unsupported_model_layout:target_joint')
    require(body.find('freejoint').get('name'), 'unsupported_model_layout:unnamed_freejoint')
    require(cert['schema'] == 'generated-container-cavity/v1' and cert['verified'] is True
            and cert['proxy_pitch_m'] == .005, 'legacy_cavity_contract_requires_5mm')
    require(cert['fill_interior'] is False and cert['artificial_bottom_added'] is False
            and cert['missing_surface_fill'] is False and cert['surface_dilation_voxels'] == 0,
            'unsupported_cavity_proxy')
    require(cert['semantic_id'] == task['container_semantic_id'], 'cavity_owner_mismatch')
    require(cert['source_glb_sha256'] == manifest['source_glb']['sha256'], 'cavity_source_mismatch')
    require(cert['cuboids_sha256'] == context['files']['container_cuboids.npz']
            and cert['source_measurement_sha256'] == context['files']['container_source_measurement.json'],
            'cavity_evidence_binding_mismatch')
    names = cert['bottom_geoms'] + cert['wall_geoms']
    require(len(names) == len(set(names)) == cert['collider_cuboids'] and cert['bottom_geoms']
            and cert['wall_geoms'], 'invalid_cavity_geometry_names')
    geoms = {g.get('name'): g for g in body_nodes[task['container_body']].findall('geom')}
    colliding_names = {name for name, g in geoms.items()
                       if g.get('contype', '1') != '0' or g.get('conaffinity', '1') != '0'}
    require(colliding_names == set(names), 'uncertified_container_collision_geometry')
    bounds = np.asarray(cert['inner_bounds_local_m'], float)
    require(bounds.shape == (2, 3) and np.isfinite(bounds).all() and (bounds[1] > bounds[0]).all()
            and 0 <= cert['source_bottom_ray_coverage'] <= 1, 'invalid_cavity_dimensions_or_coverage')
    clearance = cert['rim_z_local_m'] - cert['bottom_surface_z_local_m'] - task['target_dimensions_m'][2]
    require(abs(clearance-cert['minimum_nominal_top_clearance_m']) < 1e-12 and clearance >= .005,
            'cavity_clearance_report_mismatch')
    with np.load(BytesIO(context['blobs']['container_cuboids.npz']), allow_pickle=False) as z:
        centers, sizes = z['centers'], z['half_sizes']
        require(centers.shape == sizes.shape == (len(names), 3) and np.isfinite(centers).all()
                and np.isfinite(sizes).all() and (sizes > 0).all(), 'invalid_cuboid_arrays')
        require(float(z['pitch']) == cert['proxy_pitch_m'], 'cavity_pitch_mismatch')
    # Names are an explicit legacy schema convention; reject unrecognized labels.
    used = []
    for name in names:
        require(name.startswith(('container_bottom_col_', 'container_wall_col_')),
                'unsupported_model_layout:cavity_geom_label')
        i = int(name.rsplit('_', 1)[1]); used.append(i)
        require(name in geoms and 0 <= i < len(centers), 'cavity_geom_missing:' + name)
        g = geoms[name]
        require(g.get('type') == 'box' and not any(g.get(k) for k in ('quat', 'euler', 'axisangle', 'xyaxes', 'zaxis')),
                'unsupported_model_layout:cavity_box_transform')
        require(np.allclose(np.fromstring(g.get('pos', ''), sep=' '), centers[i], rtol=0, atol=1e-9)
                and np.allclose(np.fromstring(g.get('size', ''), sep=' '), sizes[i], rtol=0, atol=1e-9),
                'cavity_geom_parameter_mismatch:' + name)
    require(sorted(used) == list(range(len(centers))), 'cavity_index_binding_mismatch')
    result = {'legacy_cavity_binding': metric('pass', dict(proxy_pitch_m=cert['proxy_pitch_m'],
        cuboids=len(names), source_ray_coverage=cert['source_bottom_ray_coverage'],
        proxy_ray_coverage=None, nominal_top_clearance_m=cert['minimum_nominal_top_clearance_m']),
        {'proxy_pitch': 'm', 'nominal_top_clearance': 'm', 'coverage': 'fraction'},
        {'source': 'embodied_container_m2/cavity.py and binding.py legacy v1',
         'rule': '5mm legacy certificate and actual XML cuboids agree; no dynamic claim'},
        ['container_certificate.json', 'container_cuboids.npz', 'container_source_measurement.json', 'model.xml'],
        'Legacy geometry certificate only; source and proxy coverage remain separate')}
    if 'layout' not in documents:
        result['coordinates_dimensions'] = metric('unknown', None, 'm',
            {'source': 'legacy adapter', 'dimension_error_lt_m': 1e-4}, [], 'Missing bound layout coordinate evidence')
    else:
        layout = documents['layout']; coordinate = layout['coordinate_contract']
        require(coordinate['units'] == 'm' and coordinate['world_up'] == '+z'
                and coordinate['handedness'] == 'right_handed' and coordinate['yaw_axis'] == '+z'
                and coordinate['yaw_positive'] == 'counterclockwise', 'coordinate_units_or_axes_mismatch')
        declared = {o['id']: o for o in layout['objects']}
        require(set(declared) == {o['semantic_id'] for o in objects}, 'layout_object_identity_mismatch')
        errors = []
        for o in objects:
            d = declared[o['semantic_id']]
            actual = np.asarray(o['actual_dimensions_m'], float)
            expected = np.asarray([d['dimensions'][k] for k in ('width', 'length', 'height')], float)
            pose = np.asarray(o['pose_z_up'], float)
            require(actual.shape == (3,) and (actual > 0).all() and np.isfinite(actual).all(), 'invalid_dimensions')
            error = float(np.max(abs(actual - expected)))
            require(error < 1e-4 and abs(error-o['dimension_error_m']) < 1e-12, 'dimension_report_mismatch')
            require(pose.shape == (4, 4) and np.isfinite(pose).all()
                    and np.allclose(pose[3], [0, 0, 0, 1])
                    and np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-10)
                    and abs(np.linalg.det(pose[:3, :3])-1) < 1e-10, 'invalid_pose_or_scale')
            yaw = np.deg2rad(d['yaw']); co, si = np.cos(yaw), np.sin(yaw)
            expected_rot = np.array([[co, -si, 0], [si, co, 0], [0, 0, 1]])
            require(np.allclose(pose[:3, :3], expected_rot, rtol=0, atol=1e-10)
                    and np.allclose(pose[:3, 3], [d['x'], d['y'], d.get('z', 0)+d['dimensions']['height']/2], rtol=0, atol=1e-8),
                    'layout_pose_mismatch')
            errors.append(error)
        require(np.allclose(task['target_dimensions_m'], target['actual_dimensions_m'], rtol=0, atol=1e-4),
                'task_target_dimensions_mismatch')
        result['coordinates_dimensions'] = metric('pass', dict(coordinate=coordinate,
            max_recorded_dimension_error_m=max(errors), scale='baked by original adapter'), 'm',
            {'source': 'legacy adapter.py dimension gate', 'dimension_error_lt_m': 1e-4,
             'pose_serialization_atol_m': 1e-8}, ['sources:layout', 'objects.json', 'model.xml'],
            'Reconciles existing dimension reports; does not remeasure source mesh vertices')
    context['target_joint_name'] = body.find('freejoint').get('name')
    return result


def compiled_checks(context):
    import mujoco
    import numpy as np

    # Use the exact bytes that passed hashing, including every referenced asset.
    model = mujoco.MjModel.from_xml_string(context['blobs']['model.xml'].decode(),
                                         assets=context['blobs'])
    task = context['docs']['task.json']; objects = context['docs']['objects.json']
    target = next(o for o in objects if o['body'] == task['target_body'])
    bid = model.body(task['target_body']).id
    joint = model.joint(context['target_joint_name']).id
    require(model.jnt_bodyid[joint] == bid and model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE,
            'compiled_target_joint_mismatch')
    target_rotation = np.empty(9)
    task_quat = np.asarray(task['target_quat'], float)
    require(task_quat.shape == (4,) and np.isfinite(task_quat).all()
            and abs(np.linalg.norm(task_quat)-1) < 1e-8, 'invalid_target_quaternion')
    mujoco.mju_quat2Mat(target_rotation, task_quat)
    require(np.allclose(target_rotation.reshape(3, 3), task['target_rotation'], rtol=0, atol=1e-8),
            'target_quaternion_rotation_mismatch')
    for o in objects:
        i = model.body(o['body']).id; pose = np.asarray(o['pose_z_up'])
        rotation = np.empty(9); mujoco.mju_quat2Mat(rotation, model.body_quat[i])
        require(np.allclose(model.body_pos[i], pose[:3, 3], rtol=0, atol=1e-8)
                and np.allclose(rotation.reshape(3, 3), pose[:3, :3], rtol=0, atol=1e-8),
                'compiled_body_pose_mismatch:' + o['body'])
        if i != bid:
            require(model.body_jntnum[i] == 0, 'unsupported_model_layout:moving_environment')
    dims = np.asarray(target['actual_dimensions_m']); mass = float(target['mass_kg'])
    require(mass > 0 and target['measured'] is False and task['material_measured'] is False
            and target['inertia_origin'] == 'uniform bbox prior', 'unsupported_or_invalid_mass_prior')
    expected = mass * (np.sum(dims**2) - dims**2) / 12
    inertia_rotation = np.empty(9); mujoco.mju_quat2Mat(inertia_rotation, model.body_iquat[bid])
    axes = inertia_rotation.reshape(3, 3)
    tensor = axes @ np.diag(model.body_inertia[bid]) @ axes.T
    require(np.isfinite(model.body_mass).all() and np.isfinite(model.body_inertia).all()
            and (model.body_inertia[bid] > 0).all()
            and abs(model.body_mass[bid]-mass) < 1e-12
            and np.allclose(tensor, np.diag(expected), rtol=1e-8, atol=1e-12),
            'mass_or_bbox_inertia_mismatch')
    require(2 * max(model.body_inertia[bid]) <= sum(model.body_inertia[bid]) + 1e-12,
            'inertia_triangle_inequality')
    inertial = context['root'].find(".//body[@name='" + task['target_body'] + "']/inertial")
    require(inertial is not None and np.allclose(model.body_ipos[bid],
            np.fromstring(inertial.get('pos', '0 0 0'), sep=' '), rtol=0, atol=1e-12), 'COM_readback_mismatch')
    require(np.isfinite(model.geom_friction).all() and (model.geom_friction >= 0).all()
            and np.isfinite(model.geom_solref).all() and np.isfinite(model.geom_solimp).all(),
            'illegal_contact_parameters')
    contact_groups = Counter()
    for o in objects:
        i = model.body(o['body']).id
        for g in range(model.ngeom):
            if model.geom_bodyid[g] != i or not (model.geom_contype[g] or model.geom_conaffinity[g]):
                continue
            require(np.allclose(model.geom_friction[g], [o['friction'], .005, .0001], rtol=0, atol=1e-12)
                    and np.allclose(model.geom_solref[g], [.01, 1], rtol=0, atol=1e-12)
                    and np.allclose(model.geom_solimp[g], [.95, .99, .001, .5, 2], rtol=0, atol=1e-12)
                    and model.geom_condim[g] == 4 and model.geom_priority[g] == 0,
                    'contact_declaration_mismatch:' + model.geom(g).name)
            contact_groups[(tuple(model.geom_friction[g]), tuple(model.geom_solref[g]),
                            tuple(model.geom_solimp[g]), int(model.geom_condim[g]))] += 1
    require(model.npair == 0, 'unsupported_model_layout:explicit_contact_pairs')
    parameters = dict(target_body=task['target_body'], mass_kg=float(model.body_mass[bid]),
        center_of_mass_body_m=model.body_ipos[bid].tolist(), inertia_tensor_body_kg_m2=tensor.tolist(),
        inertial_quaternion_wxyz=model.body_iquat[bid].tolist(),
        contact_groups=[dict(friction=list(k[0]), solref=list(k[1]), solimp=list(k[2]), condim=k[3], count=n)
                        for k, n in sorted(contact_groups.items())],
        source='legacy adapter: fixed mass, uniform bbox inertia, default contacts',
        measured=False, real_parameter_uncertainty=None,
        static_environment='fixed rigid bodies; physical mass and structural compliance unmeasured',
        contact_scope='compiled per-geom parameters; actual runtime contact mixing unmeasured')
    option = model.opt
    solver = dict(mujoco_version=mujoco.__version__, timestep_s=float(option.timestep),
                  gravity_m_s2=option.gravity.tolist(), integrator=int(option.integrator),
                  solver=int(option.solver), iterations=int(option.iterations),
                  tolerance=float(option.tolerance), cone=int(option.cone), impratio=float(option.impratio))
    require(option.timestep == task['control']['physics_dt_s'] == .001
            and np.allclose(option.gravity, [0, 0, -9.81], rtol=0, atol=1e-12)
            and option.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
            and option.solver == mujoco.mjtSolver.mjSOL_NEWTON and option.iterations == 100
            and option.tolerance == 1e-10 and option.cone == mujoco.mjtCone.mjCONE_ELLIPTIC
            and option.impratio == 5, 'solver_or_timestep_declaration_mismatch')
    require(task['control']['action_units'] == ['rad']*7+['m']
            and task['control']['action_dt_s'] == .05, 'action_units_or_timing_mismatch')
    metrics = {
        'physical_parameters': metric('pass', parameters,
            {'mass': 'kg', 'COM': 'm', 'inertia': 'kg*m^2', 'friction': 'MuJoCo sliding/torsional/rolling'},
            {'source': 'objects.json and legacy adapter v1 modeling assumptions',
             'rule': 'positive finite mass/inertia; model readback equals declared prior',
             'rtol': 1e-8, 'atol': 1e-12}, ['model.xml', 'objects.json'],
            'Declared uncalibrated priors are consistent; this is not measured material validation'),
        'solver_parameters': metric('pass', solver, {'time': 's', 'gravity': 'm/s^2'},
            {'source': 'legacy adapter.py / task.json control', 'rule': 'compiled options match legacy declarations'},
            ['model.xml', 'task.json'], 'Compiled parameter readback only; no numerical accuracy claim'),
    }
    return metrics, model
