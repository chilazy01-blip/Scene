# Generator → embodied task bridge

This independent M0/M1 module consumes the unchanged `codex_trellis_scene_v2.cli` output: final assembled GLB, layout, semantic IDs, support edges, and asset-resolution records. It does not use the v0 three-workspace builder or a frozen task scene as input.

- `contracts.py`: protocol checks, split leakage/empty holdout rejection, semantic task selection.
- `generate.py`: actual public CLI invocation and immutable attempt directories.
- `adapter.py`: GLB visuals, geometry-derived colliders, original Panda assets, relative-path XML and provenance.
- `environment.py`: bounded robot mount/endpoint checks, reset/step/proprio observations, separate contact/success diagnostics.
- `verify.py`: new adapter checks, missing-support/action negatives, semantic rename, isolated moved-package physics parity.

The supported development task is a single rigid book on a generated supporting surface. Static support geometry uses 10mm source-surface voxels; other colliders use conservative convex hulls. Mass/inertia/friction are unmeasured assumptions. Container categories without certified cavities reject; the container runtime is pending. Endpoint IK and a neutral hold probe do not establish collision-free task execution or a successful demonstration.

The current protocol, complete failed attempts, source snapshots and resource records live at:
`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_generator_m1_20260918_v1`.

On this shared host all simulation, generation and bulk verification must use that run's `tools/launch_cpu.py`. It retains P007, <=8 CPU affinity, 12/16GiB memory and a 900-second runtime cap. Use new attempt/service/revision names. Never restart historical v0 queues or overwrite evidence.

Public prompt expansion and furnishing IDs are generator inputs; task binding selects target category and generated support relation. Runtime body names are supplied by task.json, independently of the historical `explicit_desk` / `task_book` names. Robot joint names follow the pinned Panda model.
