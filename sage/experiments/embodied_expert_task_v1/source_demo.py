"""Strict input contract for one complete HMG human expert demonstration.

Recorded states are reference evidence. Only states[0] may initialize execution.
A source bundle is not evidence of closed-loop success or a qualified episode.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import h5py


def load_demo(path):
    path = Path(path)
    with h5py.File(path, "r") as handle:
        data = handle["data"]
        if list(data) != ["demo_1"]:
            raise ValueError("expected exactly one explicitly selected source episode")
        demo = data["demo_1"]
        config = json.loads(data.attrs["script_config"])
        env_info = json.loads(data.attrs["env_info"])
        arrays = {key: np.asarray(demo[key]) for key in (
            "states", "actions", "wbc_goal/navigate_cmd",
            "teleop_cmd/base_height_command", "wbc_goal/wrist_pose",
            "wbc_goal/target_upper_body_pose")}
        xml = demo.attrs["model_file"]
    count = len(arrays["actions"])
    if count < 1 or arrays["actions"].shape != (count, 43):
        raise ValueError("expected nonempty 43-channel G1 recorded controls")
    shapes = {"states": (count + 1, 113), "wbc_goal/navigate_cmd": (count, 3),
              "teleop_cmd/base_height_command": (count,),
              "wbc_goal/wrist_pose": (count, 14),
              "wbc_goal/target_upper_body_pose": (count, 31)}
    for key, array in arrays.items():
        if key in shapes and array.shape != shapes[key]:
            raise ValueError("source field shape mismatch: " + key)
        if not np.isfinite(array).all():
            raise ValueError("non-finite source field: " + key)
    dt = 1.0 / config["control_frequency"]
    if not np.allclose(np.diff(arrays["states"][:, 0]), dt, atol=1e-9, rtol=0):
        raise ValueError("source clock does not match actual control transitions")
    if config["robot"] != "G1" or config["task_name"] != "LMBoxTableToShelf":
        raise ValueError("source task or embodiment changed")
    goals = [dict(navigate_cmd=arrays["wbc_goal/navigate_cmd"][i].copy(),
                  base_height_command=arrays["teleop_cmd/base_height_command"][i].copy(),
                  wrist_pose=arrays["wbc_goal/wrist_pose"][i].copy(),
                  target_upper_body_pose=arrays["wbc_goal/target_upper_body_pose"][i].copy())
             for i in range(count)]
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                config=config, seed=env_info["seeds"][0], xml=xml,
                arrays=arrays, goals=goals, count=count, control_dt=dt,
                source="external_human_expert", qualified_fb2_episodes=0)


def make_runtime(source, weights, *, session_factory=None):
    from humanoidmimicgen.dataset_playback import PlaybackConfig, ActionEnv
    from humanoidmimicgen.wbc_runtime import get_env, get_policies, get_robot_type_and_model
    import onnxruntime as ort
    config = PlaybackConfig.from_dict(source["config"])
    config.save_video = config.enable_onscreen = config.enable_offscreen = False
    config.wbc_model_path = ",".join(str(Path(weights[k]).resolve()) for k in ("stand", "walk"))
    config.action_source = "wbc-goal"
    config.sim_frequency = 200
    original = ort.InferenceSession
    def cpu_session(path, *args, **kwargs):
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        session = original(path, sess_options=options, providers=["CPUExecutionProvider"])
        if session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("CPU-only provider contract violated")
        return session_factory(session) if session_factory else session
    ort.InferenceSession = cpu_session
    try:
        sync = get_env(config, onscreen=False, offscreen=False)
        kind, model = get_robot_type_and_model(config.robot, config.enable_waist)
        policy, _, _ = get_policies(config, kind, model, activate_keyboard_listener=False)
    finally:
        ort.InferenceSession = original
    env = ActionEnv(sync, policy, default_base_height=config.controller_initial_base_height)
    env.reset(seed=source["seed"])
    env.reset_to({"states": source["arrays"]["states"][0].copy(), "model_file": source["xml"]})
    return env, policy, model
