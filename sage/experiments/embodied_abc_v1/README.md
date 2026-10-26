# Scene RGB and ACT development experiment

The run and all executable evidence are in
`scene_runs/codex_trellis_v2/embodied_abc_20260920_v1`.
Read that directory's checkpoint and report for completion status; the
presence of an implementation file does not mean its experiment passed.

- `visual.py`: camera mounting/intrinsics and diagnostic-geometry visibility.
- `quality_visual.py`: the selected B appearance revision and physical-array comparison.
- `observations.py`: the same selected appearance and cameras for online inference.
- `learning_data.py`: official-reader-derived image cache and temporal batches.
- `control.py`: explicit joint speed/acceleration limits for policy requests.

The validated C appearance uses `quality_visual.build_pair` followed by
`visual.configure(..., appearance='baseline')`; the alternative
`configure(..., appearance='improved')` branch is not the selected B/C profile.
The selected profile is frozen and named `quality_v2` in run evidence.

Training uses the unmodified official LeRobot 0.4.0 ACT implementation in
an isolated environment. Robot state and two camera images are the policy
inputs. Object poses, contacts, task success metrics, phases, and timestamps
are excluded from the ACT features. Successful policy action traces are
replayed independently; this is not a claim of bitwise reproducibility of
GPU policy inference itself.

C source groups remain development-only. Its disjoint initialization roles
must not be described as independent asset/layout train-validation-test
splits. The old formal split gate remains unchanged and closed.
