import itertools

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.audit_sonic_walking_execution import (
    recount_steps,
)


def test_touchdown_must_complete_inside_active_window():
    samples = [
        {
            "feet": {
                "left": {
                    "ground_contact_force_max_n": force,
                    "sole_clearance_m": height,
                }
            }
        }
        for force, height in [(40.0, 0.0), (0.0, 0.005), (0.0, 0.02), (0.0, 0.006)]
    ]
    assert recount_steps(samples, "left") == 0
    samples.append(
        {
            "feet": {
                "left": {"ground_contact_force_max_n": 40.0, "sole_clearance_m": 0.0}
            }
        }
    )
    assert recount_steps(samples, "left") == 1


def test_sliding_foot_does_not_count_as_a_step():
    samples = [
        {
            "feet": {
                "right": {
                    "ground_contact_force_max_n": force,
                    "sole_clearance_m": height,
                }
            }
        }
        for force, height in [(40.0, 0.0), (0.0, 0.005), (40.0, 0.0)]
    ]
    assert recount_steps(samples, "right") == 0


def test_oriented_box_clearance_matches_all_eight_corners():
    mujoco = pytest.importorskip("mujoco")
    from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
        official_body_model_xml,
    )
    from sage.experiments.embodied_data_stability_v1.sonic_walk_shadow import (
        foot_metrics,
    )

    xml, _ = official_body_model_xml()
    model = mujoco.MjModel.from_xml_string(xml.decode())
    data = mujoco.MjData(model)
    joint = model.joint("left_ankle_roll_joint").qposadr[0]
    data.qpos[joint] = 0.2
    mujoco.mj_forward(model, data)
    geom = next(
        i
        for i in range(model.ngeom)
        if model.geom_bodyid[i] == model.body("left_ankle_roll_link").id
    )
    corners = (
        np.asarray(list(itertools.product((-1.0, 1.0), repeat=3)))
        * model.geom_size[geom]
    )
    world = corners @ data.geom_xmat[geom].reshape(3, 3).T + data.geom_xpos[geom]
    assert foot_metrics(mujoco, model, data)["left"][
        "sole_clearance_m"
    ] == pytest.approx(world[:, 2].min())
