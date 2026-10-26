# Frozen MuJoCo task interface v1

This optional adapter loads an existing v2 navigation or pick/place episode. It
adds a common lifecycle and six serialized contracts without changing the v2
Driver, Recorder, model, timestep or success inequalities. It does not build new
scenes, install external platforms, provide a visual policy or establish training
benefits. The source fixtures remain development data.

```python
from sage.experiments.embodied_task_interface.environment import FrozenTaskEnvironment

# Run inside the project's P007/CPU/memory/runtime guard.
env = FrozenTaskEnvironment(source_episode, observation_profile="privileged_state")
try:
    observation = env.reset(new_output_directory)
    while not env.stopped:
        transition = env.step_reference()
    episode = env.record()
finally:
    env.close()
```

An external policy uses `FrozenTaskEnvironment(source_episode)` (the default
`robot_proprioception` profile), `observation = env.reset(new_output_directory)`
and `env.step(policy(observation))`. Controls must have shape `(model.nu,)`, be
finite, and respect the compiled actuator limits. No implicit clipping or action
rescaling occurs. Every call advances exactly one 1 ms physics step; changing the
frequency requires a new protocol. The native model's actuator gains,
transmissions, gears and ranges are written into `action_spec.json`.

`robot_proprioception` exposes only generalized positions/velocities of joints
under the robot root and simulation time. It excludes the target object's free
joint, goals, scene poses, contacts and acceptance metrics. `privileged_state`
explicitly exposes all qpos/qvel and the task goal. The old reference Driver also
uses the simulator and its precomputed IK/path plan; it is an explicitly trusted,
privileged policy, not a policy constrained to the observation dictionary. It is
rejected under the robot-only profile. These are API boundaries, not a security
sandbox against Python code that can inspect the environment object.

The six records are:

| Record | Identity and meaning |
|---|---|
| `scene_manifest.json` | Compiled model hash and physical semantics, reset/config/plan/objects bindings, original package manifest, layout and declared material provenance |
| `task_spec.json` | Full frozen task, objects, robot, goals, initialization, allowed contacts, acceptance thresholds, criterion code and effective step limit |
| `observation_spec.json` | Allowed fields, coordinate indices, explicit goal access, privilege declaration and timestamps; no cameras or rendered sensors in this version |
| `action_spec.json` | Native actuator controls, units/semantics, limits and one-step schedule |
| `episode_record.json` | Policy, random state, outcome, T actions and T+1 observations with hashes; reward is undefined |
| `audit_record.json` | Native integration snapshots, controller state, contacts, metrics, code identities, restoration checks, resource evidence and exceptions |

The `actions.npz` row k acts on `observations.npz` row k; row k+1 is the
post-step observation. These are actual actions and observations from the new
execution, never reconstructed from old 50 Hz snapshots. `trajectory.npz` retains
the native 50 Hz full integration samples plus the terminal sample.
`audit_1khz.npz` and `contacts_1khz_00.jsonl.gz` retain original evidence at every
physics step. Contacts and derived transforms in the old recorder refer to the
solver time t-dt; observation qpos/qvel refer to integration time t. The adapter
does not call `mj_forward` after the step to disguise this distinction.

`evaluate()` returns `unvalidated` while running or when interrupted by the
caller. Only native completion and successful engineering checks can yield
`success` or `task_failure`. An unsuccessful time limit is `timeout`, with
`truncated=True`. Numerical/restoration errors are `infrastructure_error`.
Success can occur at a time boundary and takes precedence. An arm run at the
native 18,700-step plan end uses `task_failure` on failure; a shorter configured
duration uses `timeout`. Original results are never relabeled. Live checks use
the same strict/inclusive inequalities as the old runner, including its 1e-8 s
stability tolerance. A failed reference policy does not prove scene infeasibility.

`checkpoint()` exports the full integration state, controller memory/RNG,
accumulated metrics and identity checksum. Resume with
`env.reset(another_new_directory, checkpoint=saved)`. A resumed segment records
only its own T actions/T+1 observations and explicitly links the prior segment;
it does not fabricate prefix actions. Save/record the preceding segment too.
External policy memory belongs to the caller and is not captured or verified.
Each segment checks 30 branch steps (reference controller plus integration, or
integration with replayed external actions), and native completion also checks
30 steps from an uninterrupted data copy against a restored branch. Short
segments without full checks remain unvalidated. Reset with a different seed is
rejected; new seeds require a newly bound source task.

Every reset requires a new output directory. `record()` finalizes it once, and
`close()` records unfinished work as unvalidated. The CLI runs one explicitly
selected reference fixture:

```text
python -m sage.experiments.embodied_task_interface --source SOURCE_EPISODE --output NEW_OUTPUT
```

The caller must use the existing P007 resource guard for real executions. CLI
exceptions preserve a failure record. The initial source loader supports bound,
compiled v2 episodes only; direct scene-generation integration, visual sensor
calibration, external-policy memory serialization, new task predicates and
training interfaces remain subsequent work.
