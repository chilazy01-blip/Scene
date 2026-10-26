"""No-integration safety contracts, not robot-task success evidence."""

import numpy as np
import pytest
from .protocol import project_target


def test_small_excess_projected_and_recorded():
    target=np.array([.503567,.2])
    out,report=project_target(target,[.49,.2],[-.5,-.5],[.5,.5],.5434)
    assert np.array_equal(out,[.5,.2])
    assert report['projected_joints']==[0]
    assert report['maximum_projection_rad']==pytest.approx(.003567)


@pytest.mark.parametrize('target,previous', [([.54],[.49]),([float('nan')],[0.]),([.5],[-.5])])
def test_large_excess_nonfinite_and_original_slew_rejected(target,previous):
    with pytest.raises(ValueError):project_target(target,previous,[-.5],[.5],.5434)


def test_no_projection_keeps_exact_command():
    target=np.array([.2,-.2])
    out,report=project_target(target,[.1,-.1],[-.5,-.5],[.5,.5],.5434)
    assert np.array_equal(out,target)
    assert report['maximum_projection_rad']==0
