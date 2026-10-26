# M2 v2: audited contacts, bound inputs and interruption records

This module is a separate revision. The frozen `embodied_planner_m2`, M1 model,
old trajectories and reports are not modified. The run directory is
`scene_runs/codex_trellis_v2/embodied_planner_m2_fixes_20260919_v1`.

- `contacts.py` supplies a single allowlist for planning, live auditing and
  offline qualification. Only the specific base-link/mount pair is exempt;
  permitted fingers/target and target/support pairs remain explicit. The
  planner applies its narrower phase context and original 1 mm threshold;
  execution/qualification retain the original 3 mm threshold.
- `binding.py` verifies the frozen protocol/code, dependency lock/version,
  source manifest and all referenced model/package files before loading the
  model. Task success/control must match the protocol, even with a consistent
  regenerated package manifest. Input binding is written with each attempt.
- `recorder.py` journals an action before dispatch. Completed 50-step actions
  keep the N/N+1 convention even if the step later raises. A shorter action has
  an explicit interruption record, actual substep count and terminal state.
  Successful demonstrations cannot contain an interrupted or errored action.
- `quality.py` uses explicit registration and recorded data, never a directory
  naming convention. It checks seed/reset identity, metadata, timing, proprio,
  command limits, shared contact rules and task evidence.

Each episode needs a fresh process because OMPL's global RNG cannot be safely
reseeded. Heavy operations must use the existing resource-guarded launcher.
The original total budget of 10 attempts includes the previous 7 attempts.

This remains a privileged planning collector in a development scene, with a
custom HDF5 schema; it is not official LeRobot data or a learned policy.
