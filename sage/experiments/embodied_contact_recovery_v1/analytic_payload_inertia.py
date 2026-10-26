"""Independent analytic composite mass/inertia consistency, not empirical calibration."""
import math
import numpy as np
import mujoco
from .work import E, c, finish

evidence = c.read(E / 'PHYSICAL_PARAMETER_EVIDENCE.json')
parts = []
for component in evidence['object_components']:
    spec = component['source_XML']
    assert not any(name in spec for name in ['quat', 'euler', 'axisangle', 'xyaxes', 'zaxis'])
    size = np.array([float(x) for x in spec['size'].split()])
    center = np.array([float(x) for x in spec.get('pos', '0 0 0').split()])
    density = float(spec['density'])
    if spec['type'] == 'cylinder':
        radius, half_length = size
        mass = density * math.pi * radius**2 * 2 * half_length
        transverse = mass * (3 * radius**2 + (2 * half_length)**2) / 12
        tensor = np.diag([transverse, transverse, mass * radius**2 / 2])
    elif spec['type'] == 'box':
        mass = density * 8 * float(np.prod(size))
        tensor = np.diag([mass * (size[1]**2 + size[2]**2) / 3,
                          mass * (size[0]**2 + size[2]**2) / 3,
                          mass * (size[0]**2 + size[1]**2) / 3])
    else:
        raise AssertionError(spec['type'])
    parts.append({'name': spec['name'], 'mass_kg': mass, 'center': center, 'central_tensor': tensor})
total = sum(p['mass_kg'] for p in parts)
com = sum(p['mass_kg'] * p['center'] for p in parts) / total
tensor = np.zeros((3, 3))
for p in parts:
    offset = p['center'] - com
    tensor += p['central_tensor'] + p['mass_kg'] * (float(offset @ offset) * np.eye(3) - np.outer(offset, offset))
eigenvalues = np.linalg.eigvalsh(tensor)
assert min(eigenvalues) > 0 and max(eigenvalues) <= sum(eigenvalues) - max(eigenvalues) + 1e-15
results = []
paths = [('native_C3', E / 'jobs/C_development_03/episode/MODEL.mjb')]
paths += [(name, E / 'generated' / name / 'package/MODEL.mjb')
          for name in ['development_03', 'development_04', 'development_05']]
for name, path in paths:
    m = mujoco.MjModel.from_binary_path(str(path))
    body = m.body('red_block').id
    rotation = np.zeros(9); mujoco.mju_quat2Mat(rotation, m.body_iquat[body]); rotation = rotation.reshape(3, 3)
    compiled_tensor = rotation @ np.diag(m.body_inertia[body]) @ rotation.T
    mass_error = abs(total - float(m.body_mass[body]))
    com_error = float(np.max(abs(com - m.body_ipos[body])))
    tensor_error = float(np.max(abs(tensor - compiled_tensor)))
    passed = mass_error < 1e-14 and com_error < 1e-14 and tensor_error < 1e-16
    assert passed
    results.append({'model': name, 'model_sha256': c.sha(path), 'passed': passed,
                    'mass_absolute_error_kg': mass_error, 'COM_absolute_error_m': com_error,
                    'inertia_tensor_absolute_error_kg_m2': tensor_error})
report = {'analytical_specification_consistency_passed': True, 'physics_steps': 0, 'policy_calls': 0,
          'composite_mass_kg': total, 'center_of_mass_body_m': com.tolist(),
          'inertia_tensor_body_kg_m2': tensor.tolist(), 'principal_inertia_positive_and_triangle_valid': True,
          'parts': [{'name': p['name'], 'mass_kg': p['mass_kg'], 'center_body_m': p['center'].tolist(),
                     'central_inertia_tensor_kg_m2': p['central_tensor'].tolist()} for p in parts],
          'compiled_models': results, 'empirical_material_or_inertia_calibration': False,
          'contact_friction_or_force_threshold_validated': False, 'production_accepted': False,
          'scope': 'Closed-form cylinder/box inertias plus parallel-axis theorem against four compiled models. Source-declared100/10kg/m3 compound densities and additive overlapping components are retained; consistency is not independent real-world calibration.'}
c.write(E / 'PAYLOAD_ANALYTIC_MASS_INERTIA_CONSISTENCY.json', report); finish(report)
