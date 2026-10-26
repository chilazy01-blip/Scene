# Fixed robot position preflight

This experimental adapter checks task position changes without choosing a new
robot mount or aiming the camera at each new target. It is a data-production
preflight, not a learned policy or a physical demonstration collector.

The registered six-configuration run is
`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_position_preflight_20260921_v1`.
Its protocol, requests, configuration ledger and final receipts are authoritative.

## Input and output

`adapter.build(attempt, output, protocol)` consumes a completed public-generator
attempt with its actual GLB and layout plan. The caller must first verify requested
object offsets against the realized plan and measure the generated container
geometry. `protocol` supplies the existing success, control and difficulty
contracts plus an explicit `fixed_scene_contract`.

The fixed contract contains a world robot mount and two named cameras with local
poses, parent bodies, field of view and resolution. `fixed.apply_fixed_scene`
applies those values uniformly; it does not search for task-specific mounts.
Generated object poses, scales and visual meshes are retained.

Outputs are a portable MuJoCo package, task contract, generated-geometry evidence
and file bindings. A built package is not automatically admitted for collection.

## Common checks

`feasibility_v2.endpoints` checks the same initial proprioception and loaded
mount/camera values, support, eight nominal IK endpoints and three endpoints at
each of four initialization corners. Loaded poses are compared to the frozen
`.10g` XML serialization, with quaternion normalization, at `1e-12` tolerance.
The archived v1 incorrectly compared to the unrounded input. The correction
changes validation representation only; the packages and physical gates stay the
same.

`feasibility_v2.paths` checks one bounded nominal OMPL planning chain. Held-object
poses use an ideal rigid grasp transform only in kinematic collision checks.
The run also checks source geometry, missing-bottom and closed-opening negative
cases, a three-second static load and the saved initial camera observations.
The IK gate is the original norm of position error in meters concatenated with
orientation error in radians; its scalar is not a pure millimeter error.

## Limits and reuse

These results concern six finite task positions with one historical asset set
and layout family. Corner endpoints do not establish collision-free paths for
every initialization or a continuous feasible region. Planning and stationary
load do not establish physical grasp, transport, release or full-task success.
Initial visibility does not establish visibility throughout manipulation.

New positions can use the same interface under a separately frozen finite
protocol. A new container still needs its own geometry and physical certification;
the current basket profile is not a universal container model. Actual source
collection, independent replay and standard export form the next stage. No
collection seeds or attempts are registered by the current preflight packages.
