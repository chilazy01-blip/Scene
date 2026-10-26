# Scene quality v1

CPU-only versioned quality sidecars and an actual gated static model preflight.
This version imports no controller and never creates `MjData`, steps, renders,
collects, trains, or executes old experiment launchers. Native compilation and
readback must run under the project's existing bounded CPU/P007 service.

The original M2 and position-preflight source files and frozen packages stay
unchanged. Supported inputs are explicitly limited to
`generator-container-task-package/v1`, `generated-task/v1` placement tasks,
legacy `generated-container-cavity/v1` at 5mm, top-level named scene bodies and
a named free target. Unsupported layouts fail with a reason. No qpos addresses
or particular T00 body names are hardcoded.

`quality.create_record(package, sources)` returns a `scene-quality-record/v1`.
`sources` maps `layout` and `request` to their original JSON paths; optional
context references are `legacy_endpoints`, `legacy_static_load`,
`contact_diagnostic_report`, and `contact_diagnostic_result`. Source GLB, source
asset and robot references come from the package manifest. The record includes
implementation, input hashes, exact use scope, original measurements, units,
threshold sources, applicability, four-state metrics, cost and rejection reasons.
The recorded source asset hashes identify current bytes; they do not prove the
whole earlier generation history.

Example, inside a registered CPU service:

```sh
python -m sage.experiments.embodied_scene_quality_v1 assess \
  --package /path/to/frozen/package --sources /path/to/sources.json \
  --output /path/to/new/quality.json
python -m sage.experiments.embodied_scene_quality_v1 preflight \
  --package /path/to/frozen/package --record /path/to/new/quality.json \
  --record-sha256 HASH_PINNED_BY_CALLING_PROTOCOL --use static_inspection \
  --output /path/to/new/preflight.json
```

Outputs must be new files outside the package. A successful `assess` command
means a report was written; inspect its qualifications. `preflight` exits 2
on stale/inadequate evidence and writes no success artifact. The Python API
`quality.load_admitted(...)` returns `(model, receipt)` only after admission.
The model is compiled from the same bytes that were hashed; no physics state
is created. Receipt pins are content bindings, not signatures or proof of
trusted physical evidence. Caller protocols must independently pin the expected
record. Validation re-evaluates supported metrics rather than trusting `pass`.

|Use|Required checks|v1 support|
|---|---|---|
|`static_inspection`|Package/source bindings, coordinates/recorded dimensions, legacy cavity, physical prior consistency and compiled solver readback|Available for supported packages|
|`qualified_collection`|Static checks plus contact fidelity, dynamic release range, numerical reliability, task feasibility|Refused until appropriate versioned evidence importers exist|
|`qualified_export`|Collection requirements plus observation/export qualification|Refused until appropriate versioned evidence importers exist|

Fixed rigid environment articulation is `not_applicable`. Missing evidence is
`unknown`; inconsistent inputs are `fail`. Mandatory checks cannot be waived by
N/A or a caller-supplied reduced requirement list. Unrelated unknowns do not
block static inspection. The current version does not issue calibrated material,
cross-asset, dynamic, learning-utility, or production-throughput qualifications.
Source geometry fidelity and runtime contact mixing remain unmeasured here.

This is a new preflight path. Existing collection/export/training entry points
are not globally migrated. A future qualified downstream path must consume a
valid purpose receipt and preserve its version/content pins. Do not label data
as qualified merely because static inspection passed.
