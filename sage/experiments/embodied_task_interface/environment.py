"""Interactive adapter; loading source episodes never writes to their directories.

Only native actuator controls are accepted. The reference Driver is deliberately
privileged; external policies receive the declared observation dictionary only.
No rendering, resampling, task generation or new control schedule is implied.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import gzip
import json
import os
import traceback

import mujoco
import numpy as np

from sage.experiments.embodied_scene_v2.config import validate
from sage.experiments.embodied_scene_v2.models import model_semantics
from sage.experiments.embodied_scene_v2.runner import Driver, Recorder
from .contracts import (ActionSpec, AuditRecord, EpisodeRecord, ObservationSpec,
                        SceneManifest, TaskSpec, audit_json, binding, digest, outcome, write)


@dataclass
class StepResult:
    observation: dict
    reward: None
    terminated: bool
    truncated: bool
    status: str
    phase: str


class FrozenTaskEnvironment:
    def __init__(self, source, *, observation_profile="robot_proprioception"):
        self.source = Path(source).resolve()
        self.config = validate(json.loads((self.source / "task.json").read_text()))
        if observation_profile not in ("robot_proprioception", "privileged_state"):
            raise ValueError("Unknown observation profile")
        names = ["model.mjb", "model_identity.json", "task.json", "request.json",
                 "objects.json", "reset_state.npz", "controller_plan.json"]
        bindings = {name: binding(self.source / name) for name in names}
        identity = json.loads((self.source / "model_identity.json").read_text())
        if bindings["model.mjb"]["sha256"] != identity["compiled_model"]["sha256"]:
            raise ValueError("Compiled model hash mismatch")
        request = json.loads((self.source / "request.json").read_text())
        if self.config.get("request_digest") != digest(request):
            raise ValueError("Request digest mismatch")
        if any(self.config.get(k) != v for k, v in request.items()):
            raise ValueError("Task/request mismatch")
        self.model = mujoco.MjModel.from_binary_path(str(self.source / "model.mjb"))
        if self.model.opt.timestep != self.config["dt_s"]:
            raise ValueError("Model timestep differs from frozen task")
        semantics = model_semantics(self.model)
        if digest(semantics) != digest(identity["semantics"]):
            raise ValueError("Model semantics mismatch")
        self.data = mujoco.MjData(self.model)
        self.mask = mujoco.mjtState.mjSTATE_INTEGRATION
        with np.load(self.source / "reset_state.npz", allow_pickle=False) as saved:
            if int(saved["state_spec"]) != int(self.mask):
                raise ValueError("Full integration state required")
            self.initial_state = saved["state"].copy()
        if (self.initial_state.shape != (mujoco.mj_stateSize(self.model, self.mask),)
                or not np.isfinite(self.initial_state).all()):
            raise ValueError("Invalid initial integration state")
        self.plan = json.loads((self.source / "controller_plan.json").read_text())
        self.limit = min(round(self.config["max_duration_s"] / self.config["dt_s"]),
                         18700 if self.config["task"] == "pick_place" else 60000)
        package_path = Path(self.config["source_package"]) / "manifest.json"
        package = json.loads(package_path.read_text())
        bindings["source_package_manifest"] = binding(package_path)
        self.scene_spec = SceneManifest(
            str(self.source), bindings, package, self.config["coordinate_frame"],
            package["units"], self.config["layout_id"], digest(semantics),
            dict(measured=self.config["material_measured"],
                 mass_multiplier=self.config["mass_multiplier"],
                 friction_multiplier=self.config["friction_multiplier"],
                 source="frozen declared parameters; no new physical measurements"),
            "Compiled model, reset/config/plan and source manifest bound; transitive visual assets not re-audited")
        self.task_spec = TaskSpec(
            self.config["task"], self.config["robot"], deepcopy(self.config),
            "round2-controller-v1/success-inequalities", binding(Path(__file__).with_name("contracts.py")),
            self.config["dt_s"], self.config["control_interval_s"],
            self.config["record_interval_s"], self.limit,
            "lift, bilateral grasp, release and stable support at goal" if self.config["task"] == "pick_place"
            else "reach goal XY and remain slow for the frozen stability interval",
            self.config["split"])
        privileged = observation_profile == "privileged_state"
        qi, vi = self._observation_indices(privileged)
        fields = dict(time="s, integration state time", qpos="MuJoCo generalized positions at qpos_indices",
                      qvel="MuJoCo generalized velocities at qvel_indices")
        if privileged:
            fields["goal"] = "explicit task goal in world metres; privileged target information"
        self.observation_spec = ObservationSpec(
            observation_profile, fields, qi, vi, privileged, privileged, [],
            "reset at t0; observation k+1 after one native mj_step; no extra mj_forward or interpolated sensors")
        m = self.model
        self.action_spec = ActionSpec(
            "native_actuator_ctrl", [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)],
            [m.nu], self.config["control_interval_s"], 1,
            m.actuator_ctrllimited.astype(bool).tolist(), m.actuator_ctrlrange.tolist(),
            {key: getattr(m, key).tolist() for key in
             ("actuator_trntype", "actuator_trnid", "actuator_gear", "actuator_gaintype",
              "actuator_gainprm", "actuator_biastype", "actuator_biasprm")},
            "native model units; Panda torque motors and finger position targets; Stretch mixed actuators as bound above")
        self.identity = digest(dict(scene=self.scene_spec.to_dict(), task=self.task_spec.to_dict(),
                                    observation=self.observation_spec.to_dict(), action=self.action_spec.to_dict()))
        self.out = None
        self.recorded = True

    def _observation_indices(self, privileged):
        m = self.model
        if privileged:
            return list(range(m.nq)), list(range(m.nv))
        root = m.body("base" if self.config["task"] == "pick_place" else "base_link").id
        qi, vi = [], []
        for j in range(m.njnt):
            body = int(m.jnt_bodyid[j])
            while body not in (0, root):
                body = int(m.body_parentid[body])
            if body != root:
                continue
            q_end = int(m.jnt_qposadr[j + 1]) if j + 1 < m.njnt else m.nq
            v_end = int(m.jnt_dofadr[j + 1]) if j + 1 < m.njnt else m.nv
            qi.extend(range(int(m.jnt_qposadr[j]), q_end))
            vi.extend(range(int(m.jnt_dofadr[j]), v_end))
        return qi, vi

    def reset(self, output, *, seed=None, checkpoint=None):
        if seed is not None and seed != self.config["seed"]:
            raise ValueError("Frozen reset seed cannot be changed")
        if not self.recorded:
            raise RuntimeError("Record or close the current segment before reset")
        out = Path(output).resolve()
        if out == self.source or self.source in out.parents or out in self.source.parents:
            raise ValueError("Output must be independent of the source episode")
        # Validate a checkpoint before creating any output or mutating the model.
        if checkpoint is not None:
            checkpoint = deepcopy(checkpoint)
            checksum = checkpoint.pop("sha256", None)
            if checksum != digest(checkpoint) or checkpoint["environment_identity"] != self.identity:
                raise ValueError("Checkpoint identity/hash mismatch")
            if checkpoint["stopped"]:
                raise ValueError("Cannot resume a terminal segment")
            saved_state = np.asarray(checkpoint["integration_state"], dtype=float)
            step = checkpoint["controller_state"]["step"]
            if (saved_state.shape != self.initial_state.shape or not np.isfinite(saved_state).all()
                    or type(step) is not int or not 0 <= step < self.limit):
                raise ValueError("Invalid checkpoint state/step")
            if checkpoint["policy"] not in (None, "frozen_privileged_driver", "external_native_actuator_policy"):
                raise ValueError("Unknown checkpoint policy")
            if checkpoint["policy"] == "frozen_privileged_driver" and not self.observation_spec.privileged_state:
                raise ValueError("Privileged controller checkpoint requires privileged observations")
        out.mkdir(parents=True, exist_ok=False)
        self.out = out
        mujoco.mj_resetData(self.model, self.data)
        state = self.initial_state if checkpoint is None else np.asarray(checkpoint["integration_state"])
        mujoco.mj_setState(self.model, self.data, state, self.mask)
        # Populate derived fields while preserving the exact integration buffer.
        mujoco.mj_forward(self.model, self.data)
        mujoco.mj_setState(self.model, self.data, state, self.mask)
        self.rec = Recorder(self.model, self.data, self.config, out)
        self.rec.contact_stream = gzip.open(out / "contacts_1khz_00.jsonl.gz", "wt", compresslevel=3)
        self.controller_state = dict(step=0, path_index=1, phase="reset", chosen_action=self.data.ctrl.tolist(),
                                     random_state=np.random.default_rng(self.config["seed"]).bit_generator.state)
        self.policy = None
        self.prefix = None
        if checkpoint is not None:
            self.controller_state = checkpoint["controller_state"]
            self.rec.metrics = checkpoint["metrics"]
            self.policy = checkpoint["policy"]
            self.prefix = checkpoint["prefix"]
        self.driver = Driver(self.model, self.data, self.config, out, deepcopy(self.plan))
        self.start_step = self.controller_state["step"]
        self.stopped = False
        self.reason = "running"
        self.recorded = False
        self.exceptions = []
        self.engineering = None
        self.shadow = None
        self.shadow_steps = 0
        self.shadow_equal = True
        self.actions, self.phases, self.action_times = [], [], []
        self.observations = [self.observe()]
        self.rec.sample(self.controller_state["phase"])
        self.controller_samples = [deepcopy(self.controller_state)]
        for name, spec in [("scene_manifest", self.scene_spec), ("task_spec", self.task_spec),
                           ("observation_spec", self.observation_spec), ("action_spec", self.action_spec)]:
            write(out / (name + ".json"), spec.to_dict())
        write(out / "segment.json", dict(start_step=self.start_step, prefix=self.prefix,
                                         reset_identity=digest(state.tolist()), seed=self.config["seed"]))
        return self.observe()

    def observe(self):
        spec = self.observation_spec
        result = dict(time=float(self.data.time), qpos=self.data.qpos[spec.qpos_indices].copy(),
                      qvel=self.data.qvel[spec.qvel_indices].copy())
        if spec.goal_information_allowed:
            result["goal"] = np.array(self.config["goal"], dtype=float)
        return result

    def _require_active(self):
        if self.recorded or self.stopped:
            raise RuntimeError("reset is required before stepping a closed/terminal episode")

    def _select_policy(self, name):
        if self.policy not in (None, name):
            raise ValueError("Cannot switch policy mode within an episode segment")
        self.policy = name

    def _start_shadow(self):
        # A branch check on the first 30 transitions of each segment; this adds
        # no steps to the live environment and includes reference controller state.
        if self.shadow is None:
            self.shadow = mujoco.MjData(self.model)
            mujoco.mj_setState(self.model, self.shadow, self.rec.state(), self.mask)
            self.shadow_state = deepcopy(self.controller_state)
            self.shadow_driver = Driver(self.model, self.shadow, self.config, self.out, deepcopy(self.plan))

    def step_reference(self):
        self._require_active()
        if not self.observation_spec.privileged_state:
            raise ValueError("Reference Driver requires the explicit privileged_state profile")
        self._select_policy("frozen_privileged_driver")
        self._start_shadow()
        try:
            self.driver.action(self.controller_state)
            return self._advance(self.data.ctrl.copy())
        except Exception as exc:
            self.fail(exc)
            raise

    def step(self, action):
        self._require_active()
        action = self._validate_action(action)
        self._select_policy("external_native_actuator_policy")
        self._start_shadow()
        self.controller_state.update(phase="external", chosen_action=action.tolist())
        try:
            return self._advance(action)
        except Exception as exc:
            self.fail(exc)
            raise

    def fail(self, error):
        """Keep execution errors separate from a policy's ordinary task failure."""
        if self.recorded:
            raise RuntimeError("No active segment to mark failed")
        self.stopped, self.reason, self.engineering = True, "exception", False
        self.exceptions.append(dict(type=type(error).__name__, message=str(error),
                                    traceback="".join(traceback.format_exception(type(error), error, error.__traceback__))))

    def _validate_action(self, action):
        action = np.asarray(action, dtype=float)
        if action.shape != (self.model.nu,) or not np.isfinite(action).all():
            raise ValueError("Action must be finite with shape (model.nu,)")
        limited = self.model.actuator_ctrllimited.astype(bool)
        ranges = self.model.actuator_ctrlrange
        if (np.any(action[limited] < ranges[limited, 0])
                or np.any(action[limited] > ranges[limited, 1])):
            raise ValueError("Action exceeds native actuator limits")
        return action.copy()

    def _advance(self, action):
        action = self._validate_action(action)
        self.action_times.append(float(self.data.time))
        self.actions.append(action.copy())
        self.data.ctrl[:] = action
        mujoco.mj_step(self.model, self.data)
        self.controller_state["step"] += 1
        self.phases.append(self.controller_state["phase"])
        self.observations.append(self.observe())
        self.rec.audit()  # Do not mj_forward before native contact evidence.
        if self.shadow_steps < 30:
            if self.policy == "frozen_privileged_driver":
                self.shadow_driver.action(self.shadow_state)
            else:
                self.shadow.ctrl[:] = action
                self.shadow_state.update(phase="external", chosen_action=action.tolist())
            mujoco.mj_step(self.model, self.shadow)
            self.shadow_state["step"] += 1
            state = np.empty_like(self.rec.state())
            mujoco.mj_getState(self.model, self.shadow, state, self.mask)
            self.shadow_equal &= np.array_equal(state, self.rec.state()) and self.shadow_state == self.controller_state
            self.shadow_steps += 1
        if self.controller_state["step"] % 20 == 0:
            self.rec.sample(self.controller_state["phase"])
            self.controller_samples.append(deepcopy(self.controller_state))
        healthy = (np.isfinite(self.rec.state()).all() and not any(w.number for w in self.data.warning)
                   and self.shadow_equal)
        if not healthy:
            self.stopped, self.reason, self.engineering = True, "numerical_or_restore_error", False
        elif (self.config["task"] == "navigate"
              and self.rec.metrics["stable_seconds"] >= self.config["acceptance"]["stable_seconds"]):
            self.stopped, self.reason = True, "native_navigation_stop"
        elif self.controller_state["step"] >= self.limit:
            self.stopped = True
            self.reason = "time_limit" if self.config["task"] == "navigate" or self.limit < 18700 else "native_plan_end"
        if self.stopped and self.engineering is not False:
            self.engineering = self._terminal_restore() if self.shadow_steps == 30 else None
            if self.engineering is False:
                self.reason = "terminal_restore_error"
        evaluation = self.evaluate()
        return StepResult(self.observe(), None, evaluation["terminated"], evaluation["truncated"],
                          evaluation["status"], self.controller_state["phase"])

    def _terminal_restore(self):
        # The old checker restores and mj_forwards live data. Use two independent
        # branches so evaluate/record cannot mutate the returned observation/state.
        a, b = deepcopy(self.data), mujoco.MjData(self.model)
        state = self.rec.state()
        mujoco.mj_setState(self.model, b, state, self.mask)
        for _ in range(30):
            mujoco.mj_step(self.model, a)
            mujoco.mj_step(self.model, b)
            sa, sb = np.empty_like(state), np.empty_like(state)
            mujoco.mj_getState(self.model, a, sa, self.mask)
            mujoco.mj_getState(self.model, b, sb, self.mask)
            if not np.array_equal(sa, sb) or not np.isfinite(sa).all():
                return False
        return not any(w.number for d in (a, b) for w in d.warning)

    def evaluate(self):
        return outcome(self.config, self.rec.metrics, stopped=self.stopped,
                       reason=self.reason, engineering=self.engineering)

    def checkpoint(self):
        self._require_active()
        value = dict(environment_identity=self.identity, integration_state=self.rec.state().tolist(),
                     controller_state=deepcopy(self.controller_state), metrics=deepcopy(self.rec.metrics),
                     policy=self.policy, stopped=self.stopped,
                     prefix=dict(output=str(self.out), end_step=self.controller_state["step"]))
        return dict(value, sha256=digest(value))

    def record(self):
        if self.recorded:
            raise RuntimeError("No unrecorded segment")
        if not self.stopped:
            self.stopped, self.reason = True, "caller_stop"
        if not np.array_equal(self.rec.states[-1], self.rec.state()):
            self.rec.sample(self.controller_state["phase"])
            self.controller_samples.append(deepcopy(self.controller_state))
        self.rec.contact_stream.close()
        self.rec.save()
        write(self.out / "controller_states.json", audit_json(self.controller_samples))
        observations = {key: np.asarray([row[key] for row in self.observations]) for key in self.observations[0]}
        np.savez_compressed(self.out / "observations.npz", **observations)
        np.savez_compressed(self.out / "actions.npz", action=np.asarray(self.actions).reshape(-1, self.model.nu),
                            time=np.asarray(self.action_times), phase=np.asarray(self.phases, dtype=str))
        assert len(self.observations) == len(self.actions) + 1
        episode = EpisodeRecord(
            "new execution of frozen development fixture", digest(self.scene_spec.to_dict()),
            digest(self.task_spec.to_dict()), digest(self.observation_spec.to_dict()), digest(self.action_spec.to_dict()),
            self.policy or "none", self.config["seed"], self.controller_state["random_state"],
            len(self.actions), len(self.observations), self.evaluate(),
            {name: binding(self.out / name) for name in ("actions.npz", "observations.npz", "segment.json")})
        write(self.out / "episode_record.json", episode.to_dict())
        import sage.experiments.embodied_scene_v2.runner as native
        import sage.experiments.embodied_scene_v1.runner as native_v1
        code_paths = (list(Path(__file__).parent.glob("*.py"))
                      + [Path(native.__file__).with_name(name) for name in ("runner.py", "config.py", "models.py", "planner.py")]
                      + [Path(native_v1.__file__).with_name(name) for name in ("runner.py", "models.py", "package.py")])
        audit = AuditRecord(
            {name: binding(self.out / name) for name in ("trajectory.npz", "audit_1khz.npz",
             "contacts_1khz_00.jsonl.gz", "contact_geom_mapping.json", "controller_states.json", "episode_record.json")},
            {str(path): binding(path) for path in code_paths}, mujoco.__version__, audit_json(self.rec.metrics),
            dict(branch_steps=self.shadow_steps, branch_equal=bool(self.shadow_equal),
                 scope="integration and reference controller" if self.policy == "frozen_privileged_driver"
                 else "integration with replayed actuator inputs; external policy memory not covered",
                 terminal_engineering_check=self.engineering),
            os.environ.get("ROUND2_RESOURCE_DIR"), self.exceptions)
        write(self.out / "audit_record.json", audit.to_dict())
        self.recorded = True
        return episode.to_dict()

    def close(self):
        if not self.recorded:
            self.record()
