# Full-body data stability S0–S3

This module implements the static admission step before native controller
reproduction.  It does not load controller weights, run physics, render RGB-D,
train a policy, or authorize a long run.

Candidate acquisition is intentionally separate because it may require network
approval.  After pinned source material has been placed under an S0 run's
`staging/` directory, freeze the local facts and host gaps with:

```bash
python -m sage.experiments.embodied_data_stability_v1.stage_local_candidates \
  --run-root /absolute/path/to/the/s0/run
```

This staging command performs no network access, candidate imports, model
forwards, or physics.  It distinguishes complete archives from partial failed
downloads and distinguishes Git LFS pointers from real model bytes.  It writes
source pins, native-entrypoint definitions, weight manifests, environment
probes, component-license evidence, and partial control contracts.  Unknown
contract fields remain gaps rather than being guessed.

The frozen inputs define the candidate inventory, common capability matrix,
control-contract requirements, and finite resource proposal.  Run:

```bash
python -m sage.experiments.embodied_data_stability_v1.audit_candidates \
  --output-dir /absolute/path/to/a/new/s0/run
```

Five reports are written atomically.  `S0_GATE.json` distinguishes successful
execution of the audit, S0 admission, and S1 native-runtime readiness.  S0 only
requires pinned identities, explicit license boundaries, documented native
entrypoints, the frozen matrix, and the bounded resource policy.  S1 readiness
additionally requires complete source, real weights, dependencies, and a locally
executable entrypoint.  Missing S0 artifacts produce `s0_exit_passed=false`; use
`--require-s0-pass` only after staging and reviewing every candidate.
Exact copies of all five input configurations are stored under `inputs/` and
bound by SHA-256 from the gate report.

License evidence is inventory evidence, not legal advice.  The script never
upgrades a candidate to redistributable based only on matching text markers.

S1 bounded native runners are deliberately separate from the S0 audit.  They
write into fresh run directories, verify source/weight/runtime identity before
physics, disable rendering and training, and preserve every attempt.  Source A
uses `run_source_a_native`.  The GR00T-family comparator uses
`run_groot_decoupled_native`; it is explicitly the Decoupled-WBC MuJoCo track,
not the separately selected SONIC-v1.1 track.  Its headless protocol freezes a
single `stand_settle -> forward_walk -> stand_stop` attempt and verifies the
real Balance/Walk ONNX bytes against the pinned Git-LFS object IDs.

`finalize_s1` binds the immutable S0/S1 evidence and freezes the first selection
without upgrading it to production acceptance.  S2 starts in
`neutral_adapter.py`: a bounded mixed action, structured task instruction, and
physically separate policy/privileged streams.  The default reader exposes only
the policy stream.  `run_source_a_adapter_smoke` exercises the selected primary
expert through the neutral stance seam and requires parity with its native run,
including physics-step and model-forward counts, before the adapter can pass.

`run_s3_task_smoke` is the final pre-pause command.  It observes Source A's
state/contact-driven milestones, records 50 Hz policy-visible proprioception in
a stream separate from full simulator state/contact truth, applies frozen task,
motion, and data gates, and emits `PAUSE_PACKET.json`.  Missing RGB-D or a
quality-gate failure makes an otherwise intact episode `diagnostic`, never
silently `qualified`.  The command does not authorize or launch a 20-episode
batch.

`render_s3_diagnostic_replay` restores the recorded privileged state into the
same pinned, randomized Source-A model and produces an offline visual review.
It does not advance physics, rerun the controller, alter the source episode, or
retroactively count the derived images as synchronized policy RGB-D.

## Source-A quality-repair prototype (rejected by bounded smoke)

`source_a_quality_repair.py` is a reversible experiment-layer overlay; it does
not edit the pinned Source-A tree.  It implements per-physical-finger contact
latching, bounded preload/recovery, an 8 mm hand/object guard, stop-on-support
release, and collision-primitive clearance planning for untuck/pre-place.
`contact_diagnostics.py` additionally separates hand/object, object/table, and
foot/ground peaks instead of reporting only one global maximum.

Two same-seed bounded smokes exhausted the authorized repair budget.  Both
reduced hand/object penetration below the frozen 10 mm gate, but both lost the
object during lift: the successful S3 baseline moved the cylinder 12.1 mm into
the palm during squeeze, while the repair variants moved it only 0.7 mm and
1.3 mm.  Consequently the path and release branches were not dynamically
exercised.  The variants are preserved as rejected diagnostics, not production
controllers, and must not be promoted or batch-run:

```text
/data/wsj/main/scene_runs/codex_trellis_v2/
  embodied_data_stability_source_a_repair_20261016_v1/
  embodied_data_stability_source_a_repair_20261016_v2/
```

The authoritative comparison is `v2/REPAIR_COMPARISON.json`.  Its next gate is
a zero/low-physics pregrasp/closure-geometry study that finds an opposing cage
without exceeding the penetration guard; continuing a scalar preload sweep is
explicitly rejected.  `run_source_a_quality_repair` remains an experimental
reproduction entry point and does not authorize further physical attempts.

## Dormant SONIC shadow seam

`sonic_shadow.py` provides a fail-closed integration seam for SONIC v1.1.  It
validates the common 29-body-joint contract, reports whether the locally staged
encoder, decoder, observation configuration, and planner are real files, and
can compare synchronous Source-A and SONIC joint-position targets in radians.
It has no simulator dependency and exposes no actuation method: SONIC candidate
targets are always marked `candidate_consumed_by_physics=false`.

Run the static preflight with the frozen S0 contracts:

```bash
python -m sage.experiments.embodied_data_stability_v1.sonic_shadow \
  --sonic-source-root /absolute/path/to/staging/groot_wbc_sonic/source \
  --sonic-contract /absolute/path/to/staging/groot_wbc_sonic/CONTROL_CONTRACT.json \
  --source-a-contract /absolute/path/to/staging/source_a_g1_manipulation/CONTROL_CONTRACT.json \
  --output /absolute/path/to/SONIC_SHADOW_PREFLIGHT.json
```

This command performs no controller import, model forward, physics, rendering,
or download.  `dormant_adapter_ready=true` means only that the software seam and
joint mapping are valid.  `shadow_inference_ready` remains a separate resource
gate.  A later shadow runner must keep Source A as the sole physics controller;
an actual performance comparison requires independent matched A/B episodes.
