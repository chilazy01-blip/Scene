"""Deterministic tick contract for the pinned G1 Decoupled WBC.

The official API updates teleoperation commands inside get_action, after its
observation has already been packed. This adapter latches them before packing.
It neither changes weights nor integrates physics. Joint order is Pinocchio.
"""
import copy

import numpy as np


class TickController:
    def __init__(self, policy, robot, lower_limits, upper_limits):
        self.policy = policy
        self.robot = robot
        self.lower = np.asarray(lower_limits, dtype=float)
        self.upper = np.asarray(upper_limits, dtype=float)
        self.lower_ids = robot.get_joint_group_indices("lower_body")
        self.last_tick = -1
        self.last_packet = None

    def validate(self, packet):
        required = {"tick", "dt", "frame", "units", "navigate", "height", "rpy", "q_reference"}
        if set(packet) != required:
            raise ValueError("packet_fields")
        if type(packet["tick"]) is not int or packet["tick"] != self.last_tick + 1:
            raise ValueError("nonconsecutive_tick")
        if packet["dt"] != 0.02 or packet["frame"] != "body_heading" or packet["units"] != "SI_rad":
            raise ValueError("clock_frame_units")
        nav = np.asarray(packet["navigate"], dtype=float)
        rpy = np.asarray(packet["rpy"], dtype=float)
        q = np.asarray(packet["q_reference"], dtype=float)
        height = float(packet["height"])
        if nav.shape != (3,) or rpy.shape != (3,) or q.shape != (43,):
            raise ValueError("command_shape")
        if not all(np.isfinite(x).all() for x in [nav, rpy, q, height]):
            raise ValueError("nonfinite_command")
        # This is the small FB1 command envelope, not the policy's full domain.
        if np.any(abs(nav) > [0.2, 0.1, 0.2]) or not 0.64 <= height <= 0.74 or np.any(abs(rpy) > 0.1):
            raise ValueError("command_envelope")
        if np.any(q < self.lower) or np.any(q > self.upper):
            raise ValueError("reference_joint_limits")
        return nav, height, rpy, q

    def step(self, observation, packet):
        nav, height, rpy, q = self.validate(packet)
        for key, shape in [("q", (43,)), ("dq", (43,)), ("floating_base_pose", (7,)), ("floating_base_vel", (6,))]:
            value = np.asarray(observation[key])
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError("invalid_observation:" + key)
        if abs(np.linalg.norm(observation["floating_base_pose"][3:]) - 1) > 1e-6:
            raise ValueError("invalid_quaternion")
        p = self.policy
        p.cmd = nav.copy()
        p.height_cmd = height
        p.roll_cmd, p.pitch_cmd, p.yaw_cmd = rpy
        p.use_teleop_policy_cmd = False
        p.use_policy_action = True
        p.set_observation(observation)
        action = p.get_action()["body_action"]
        target = q.copy()
        target[self.lower_ids] = action[0]
        if not np.isfinite(target).all() or np.any(target < self.lower) or np.any(target > self.upper):
            raise ValueError("policy_target_joint_limits")
        if np.any(action[1]) or np.any(action[2]):
            raise ValueError("unexpected_velocity_or_feedforward")
        self.last_tick = packet["tick"]
        self.last_packet = copy.deepcopy(packet)
        return target

    def snapshot(self):
        p = self.policy
        fields = ["obs_history", "obs_buffer", "obs_tensor", "observation", "action", "counter",
                  "target_dof_pos", "cmd", "height_cmd", "freq_cmd", "roll_cmd", "pitch_cmd", "yaw_cmd",
                  "gait_indices", "use_policy_action", "use_teleop_policy_cmd", "foot_indices", "clock_inputs"]
        return dict(last_tick=self.last_tick, last_packet=copy.deepcopy(self.last_packet),
                    policy={key: copy.deepcopy(getattr(p, key)) for key in fields if hasattr(p, key)})

    def restore(self, state):
        self.last_tick = state["last_tick"]
        self.last_packet = copy.deepcopy(state["last_packet"])
        for key, value in state["policy"].items():
            setattr(self.policy, key, copy.deepcopy(value))


def contact_role(a, b):
    """Classify roles, without assigning a universal force threshold."""
    roles = frozenset((a, b))
    if roles == {"foot", "floor"}:
        return "support"
    if roles == {"hand", "object"}:
        return "grasp"
    if roles in ({"object", "support_surface"}, {"object", "floor"}):
        return "object_support"
    if "robot" in roles or "hand" in roles or "foot" in roles:
        return "forbidden_body_contact"
    return "environment"
