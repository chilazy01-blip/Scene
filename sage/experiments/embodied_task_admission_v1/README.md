# Generator task intake v1

This is an executable **post-generation handoff** for completed public scene
generator outputs and their `generator-container-task-package/v1` adapter packages.
It binds target/container/source-support identities, original asset bytes, poses,
placement intent, model, physical assumptions and the exact evidence scope.
No historical object name or qpos address is hardcoded.

`prepare_task(generator_output, package, static_record, intent, primitive_record)`
revalidates v1 static evidence and optionally recomputes v2 raw primitive evidence.
The explicit `asset-task-intent/v1` must match the task hash, role IDs, goal and
orientation, actual selected model hash/type and scope. Original and derived
models cannot share dynamic qualification. Missing evidence remains unknown;
the known failed candidate remains failed. Source colliders are described
separately from the selected candidate recipe.

`open_task(intake_path, intake_sha256, purpose=..., expected_combination_id=...)`
recomputes the handoff, then invokes the existing purpose-specific native model
loader. Failure returns no model and writes no success receipt. Successful
candidate inspection is not collection/export admission. Model loading creates
no `MjData`, physical integration or task execution.

Run in a registered P007 CPU service (≤8CPU, MemoryHigh12GiB/Max16GiB, ≤900s):

```sh
python -m sage.experiments.embodied_task_admission_v1 prepare \
  --request /new/run/request.json --request-sha256 REQUEST_PIN \
  --output /new/run/intake.json
python -m sage.experiments.embodied_task_admission_v1 open \
  --intake /new/run/intake.json --intake-sha256 INTAKE_PIN \
  --combination-id COMBINATION_ID --use qualified_collection \
  --output /new/run/admission.json
```

Request fields match the API arguments. `static_record` has `path`, `sha256`;
optional `primitive_record` has `root`, `path`, `sha256`. `intent` has `schema`,
`task_sha256`, `roles`, `placement`, `model`, `scope`. Concrete pinned examples
are in the validation run's `protocol/*_REQUEST.json`. Caller protocols pin
requests before execution. Content pins bind bytes, not authenticity or physical
truth. JSON outputs are new files outside the input trees; CLI rejection exits 2.

The current source adapter family chooses upright placement. This interface
does not search or alter placement orientation, infer a stable region from a
support polygon, calibrate materials, or produce new dynamics evidence.
Qualified collection/export still require the missing full robot task and
observation evidence. Learning additionally requires input-numerics and baseline
admission; this module has no training entry. Original generator/collector/export
scripts remain unchanged; callers must use this new handoff to obtain its checks.
This is not a completed production pipeline or a cross-asset qualification.

See [experiment guardrails](/data/wsj/main/scene/docs/EXPERIMENT_GUARDRAILS.md)
and [the bounded validation plan](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_task_admission_20260924_v1/PLAN.md).
