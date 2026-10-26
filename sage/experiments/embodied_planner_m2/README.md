# M2 development collector

OMPL RRTConnect plans arm joint paths in the unchanged generated M1 MuJoCo scene.
The state machine executes finite actuator torques, and advances on measured
tracking, bilateral contact, lift, release and stability. Planning assumes a
rigid grasp transform only inside its separate collision-query MjData. The
physical environment does not weld or teleport the target.

Run each episode in a **fresh process**: OMPL's global RNG cannot be reseeded
after sampling starts. `JointPlanner` rejects a second instance in one process.
The driver, pinned dependency and resource-guarded launchers are in
`scene_runs/codex_trellis_v2/embodied_planner_m2_20260918_v1`.
Use its `QUICKSTART.md`, protocol and attempt budget before launching work.

Scope: privileged planned experts on one development scene. This is neither a
learned policy nor an independent scene test. Output HDF5 is a custom contract;
official LeRobot/ACT compatibility has not been implemented. Renderer output
is saved-state presentation, not synchronous training RGB.

`environment.py` extends the frozen M1 environment for full 1 kHz contact logs
and robot self-collision checks. `planner.py` rejects invalid endpoints and
samples every edge at <=0.01 rad, then independently checks <=0.005 rad joint
increments. This is sampled collision checking, not analytic swept-volume proof.
