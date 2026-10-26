"""Command handling regression using the actual old refused command, no mj_step."""
import json
from pathlib import Path
import numpy as np
import pytest
from .protocol_v4 import project_target
from .protocol import project_target as old_project

PARENT = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_object_transport_20261021_v1')


def test_real_rejected_command_now_projects_legally():
    import mujoco
    from sage.experiments.embodied_transport_native_v1.model import load_model
    from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
    trace = json.loads((PARENT / 'version_03/full/TRACE.json').read_text())
    scene = json.loads((PARENT / 'model/SCENE.json').read_text())
    m = load_model(scene['model']['path'])
    ids = native._model_ids(mujoco, m)
    lo, hi = m.jnt_range[ids['joint_ids']].T
    mixed = np.array(trace['rejected_command']['mixed'])
    previous = np.array(trace['records'][-1]['target_rad'])
    with pytest.raises(ValueError, match='large target range excess'):
        old_project(mixed, previous, lo, hi, native.MAX_CANDIDATE_STEP_RAD)
    legal, info = project_target(mixed, previous, lo, hi, native.MAX_CANDIDATE_STEP_RAD)
    assert np.array_equal(legal, np.clip(mixed, lo, hi))
    assert np.all(legal >= lo) and np.all(legal <= hi)
    assert info['maximum_projection_rad'] == pytest.approx(.065292551875, abs=1e-10)


@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_refused(bad):
    with pytest.raises(ValueError, match='nonfinite'):
        project_target([bad], [0], [-1], [1], .5)


def test_large_actual_command_jump_still_refused():
    with pytest.raises(ValueError, match='slew'):
        project_target([2], [0], [-1], [1], .5)


def test_large_raw_excess_can_still_be_small_legal_command():
    legal, info = project_target([30], [.9], [-1], [1], .5)
    assert legal.tolist() == [1] and info['maximum_projection_rad'] == 29
