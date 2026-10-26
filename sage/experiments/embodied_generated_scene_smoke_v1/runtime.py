"""Runtime helpers shared by validation, rollout, and offline replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_custom_sim(source: Path, model_path: Path, spawn: Any):
    """Mirror Source-A build_sim, changing only the scene XML path."""
    import mujoco

    from ik import sim

    with (source / "model_config.json").open(encoding="utf-8") as stream:
        config = json.load(stream)
    joint_names = config["joint_names"]
    model = mujoco.MjModel.from_xml_path(str(model_path))
    model.opt.timestep = 0.005
    sim.set_armature(model, joint_names)
    data = mujoco.MjData(model)
    data.qpos[0], data.qpos[1], data.qpos[2] = spawn[0], spawn[1], 0.76
    data.qpos[3:7] = [1, 0, 0, 0]
    for name, value in config["default_joint_pos"].items():
        if name in joint_names:
            data.qpos[7 + joint_names.index(name)] = value
    mujoco.mj_forward(model, data)
    controller = sim.G1Controller(
        model,
        data,
        sim.ONNXPolicy(str(source / "walker.onnx")),
        sim.ONNXPolicy(str(source / "croucher.onnx")),
        sim.ONNXPolicy(str(source / "rotator.onnx")),
        config,
        right_reacher=sim.ONNXPolicy(str(source / "right_reacher.onnx")),
    )
    return model, data, controller


def geom_label(model: Any, mujoco: Any, geom_id: int) -> str:
    geom = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
    body_id = int(model.geom_bodyid[geom_id])
    body = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id)
    return geom or body or f"geom_{geom_id}"

