# Fixed learner development validation

This module consumes accepted image-backed LeRobot shards without changing their physics sources. `data.py` builds batches with per-episode padding and train-only normalization. `rendering.py` restores recorded camera parameters so the simulator and training see the same images. `learner.py` configures the unmodified installed ACT implementation and reports errors in physical action units.

`runtime.py` records admission, failures, signals, optional counters, and a durable terminal. Call it only through a spawn-safe `if __name__ == '__main__'` entry inside the existing resource-limited user service. A separate supervisor must reconcile uncatchable process death from the actual service exit evidence. A successful process exit is only an engineering status; task success still requires original physical quality and independent replay.

Reference execution and finite protocol:
`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_learner_validation_20260921_v1/QUICKSTART.md`.

All present data belongs to development. This module does not establish source/layout generalization, visual-data utility, generic unseen-container support, or production readiness. Source/sidecar target state is only used by rendering and auditing, never exposed as learned policy features.
