"""D static acquisition planner against each actual generated scene's geometry."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish

layout = sys.argv[1]
assert layout in ['development_03', 'development_04', 'development_05']
work = Path(os.environ['CONTINUOUS_JOB_DIR'])
os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(R / 'branches/A/source'))
from .target_adapter_r4 import install
install('A', 'gain_translation', work / 'static_interface')
import run
from ik import pipeline as p
from ik.sim import ArmIK6
from .planned_tripod import plan
source = E / 'jobs/C_development_02/episode'
native = mujoco.MjModel.from_binary_path(str(source / 'MODEL.mjb')); original = mujoco.MjData(native)
with h5py.File(source / 'TRACE.h5', 'r') as f:
    mujoco.mj_setState(native, original, f['substep/integration_before'][15200], mujoco.mjtState.mjSTATE_INTEGRATION)
mujoco.mj_forward(native, original)
path = E / 'generated' / layout / 'package/MODEL.mjb'
m = mujoco.MjModel.from_binary_path(str(path)); d = mujoco.MjData(m)
assert [m.joint(i).name for i in range(m.njnt)] == [native.joint(i).name for i in range(native.njnt)]
for field in ['qpos', 'qvel', 'act', 'ctrl', 'qacc_warmstart', 'qfrc_applied', 'userdata']:
    dst, src = getattr(d, field), getattr(original, field)
    assert dst.shape == src.shape
    dst[:] = src
d.time = original.time
old_geo, geo = p.scene_geometry(native), p.scene_geometry(m)
xy = np.array(geo['brown_center'][:2]) - old_geo['brown_center'][:2]
dz = float(geo['brown_top_z'] - old_geo['brown_top_z'])
oa = int(m.jnt_qposadr[m.joint('red_block_joint').id])
d.qpos[:2] += xy; d.qpos[oa:oa + 3] += np.r_[xy, dz]
d.qpos[int(m.jnt_qposadr[m.joint('left_elbow_joint').id])] -= .10
mujoco.mj_forward(m, d)
ctrl = run.G1Controller(m, d, None, None, None, c.read(R / 'branches/A/source/model_config.json'))
ik = ArmIK6(m, ctrl)
# The different tabletop height must not be implemented by lifting the base
# away from its ground support. Solve only the actual7arm joints in this fixture.
palm_goal = original.site_xpos[native.site(m.site(ik.site_id).name).id] + np.r_[xy, dz]
wrist_goal = original.site_xmat[native.site(m.site(ik.site_id).name).id].reshape(3, 3)
arm, position_error, rotation_error = ik.solve(d, palm_goal, wrist_goal, iters=100)
assert position_error <= .003 and rotation_error <= 1.
d.qpos[ik.qpos_idx] = arm
mujoco.mj_forward(m, d)
class Runner:
    model = m
    data = d
    cyl_bid = m.body('red_block').id
    def __init__(self): self.ik = ik
    def palm_pose(self): return d.site_xpos[ik.site_id].copy(), d.site_xmat[ik.site_id].reshape(3, 3).copy()
    def cyl_pos(self): return d.xpos[self.cyl_bid].copy()
fixture = d.qpos.copy()
selected = c.read(E / 'D_TRIPOD_SELECTED_PLAN.json')['selected']
result = plan(Runner(), selected)
assert np.array_equal(fixture, d.qpos), 'planner_modified_fixture'
report = {'layout': layout, 'physics_steps': 0, 'policy_calls': 0,
          'generated_model_sha256': c.sha(path), 'source_fixture_row': 15200,
          'brown_table_xy_shift_m': xy.tolist(), 'brown_table_height_shift_m': dz,
          'pregrasp_fixture_arm_position_error_m': float(position_error),
          'pregrasp_fixture_arm_rotation_error_deg': float(rotation_error),
          'base_ground_height_unchanged': bool(d.qpos[2] == original.qpos[2]),
          'planned_grasp': result, 'static_planner_passed': result['valid'],
          'fixture_not_an_actual_reached_state': True,
          'scope': 'Actual generated model with ground-preserving named-state fixture and7joint arm IK adapting tabletop geometry, followed by full81point collision/contact planning. No navigation, acquisition or lift executed.',
          'dynamic_admission': False, 'production_accepted': False}
c.write(E / ('D_GENERATED_TRIPOD_' + layout + '.json'), report); finish(report)
