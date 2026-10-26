# Fixed-anchor delta ACT development contrast

Reuses the immutable official ACT architecture and input preprocessing from
`embodied_learner_validation_v1`. Joint targets are relative to the seven
observed joint positions at the time the chunk is predicted. Finger commands
remain absolute half-openings. All ten future actions are decoded once with
that same anchor and queued as absolute targets.

The independent run is
`scene_runs/codex_trellis_v2/embodied_delta_validation_20260921_v1`.
Its protocol fixes one 6000-update training group and three development
initializations, at most 75 simulated seconds each. Step6000 is selected in
advance. Old models/data/results are read-only. Input/finger statistics are
unchanged; joint statistics use valid training anchor/future pairs, pooled
per feature. This changes physical loss weighting along with representation;
normalized losses cannot be compared across the two groups.

`tools/run_experiment.py` runs bounded serial services and refuses to repeat
a failed or incomplete service. Preflight must pass before the training
freeze is created. Final review, historical audit and sealing remain
separate completion steps. An implementation binding is not evidence that
the experiment or preflight has run.
