from pathlib import Path

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.trajectory_capture import (
    StateStreamCapture,
    load_policy_state,
    load_privileged_state,
)


def test_state_stream_default_reader_cannot_return_privileged(tmp_path: Path):
    capture = StateStreamCapture(4, lambda: 0)
    capture.model_signature = {"nq": 2, "nv": 2, "nu": 1, "dt": 0.01, "robot_joint_count": 1}
    for stream in (capture.policy, capture.privileged):
        for key in stream:
            stream[key].append(0.0)
    capture.finalize(tmp_path / "state")
    assert load_policy_state(tmp_path / "state")["sim_time_s"].shape == (1,)
    with pytest.raises(PermissionError):
        load_privileged_state(tmp_path / "state")
    assert np.asarray(load_privileged_state(tmp_path / "state", explicit=True)["qpos"]).size == 1
