# Scoped contact quality v2

This module adds a single source-derived contact recipe, finite isolated release
primitives, raw-evidence import, and an actual model admission entry. It does not
modify the frozen v1 quality module or the old 5mm M2 binding contract.

The supported source is a v1 generator container package with a v1 static
inspection receipt. The source layout remains in the package's sibling
`generator/layout_plan_final.json`. Named target/container/support roles and the
compiled free-joint addresses are used. Models with extra moving bodies after
robot removal are rejected. No T00 qpos address is assumed.

`geometry.make_candidate` partitions original bottom boxes at a declared XY
region. Inside the region, paired source-mesh rays determine each cell's upper
and lower surfaces. Missing or zero-thickness cells are omitted. No dilation,
invented thickness, hidden support plane or material change is allowed by this
recipe. Outside the region the original occupied volume is preserved. This is
a local vertical contact approximation; multiple layers within one column can
be merged. It is not a universal geometric or material truth claim. Independent
shifted rays report source/proxy coverage separately and gate local fidelity.

Both new comparison models remove the robot and decorative, noncolliding
visuals identically. All non-bottom collision geometry, target mass/inertia,
contact settings and solver options are preserved. Realistic appearance and
complete robot interaction are outside this primitive contract.

`primitives.run_attempt` executes only a registered, finite case with its frozen
complete integration state. Every attempt saves its initial state, full state
after each native step, qpos/qvel, all target contact positions/wrenches and
warnings. Contact forces refer to the native solve of the step; poses refer to
the state after integration. No controller, policy, teleports during stepping,
training or demonstration collection is used.

`evidence.assess(root, protocol_pin, bundle_pin)` checks the original inputs,
model/task/scope bindings and implementation, then recomputes containment,
support, drift, tilt, penetration and continuous stable time. It also computes
the registered timestep comparisons and fresh-process full-state replay errors.
It does not trust a saved `passed` or `placement_stable` summary.

The CLI assessment and admission commands **never run physics**:

```sh
python -m sage.experiments.embodied_scene_quality_v2 assess \
  --root /path/to/new/run --protocol-sha256 PROTOCOL_PIN \
  --bundle-sha256 BUNDLE_PIN --output /path/to/new/quality.json
python -m sage.experiments.embodied_scene_quality_v2 admit \
  --root /path/to/new/run --record /path/to/new/quality.json \
  --record-sha256 RECORD_PIN --scope-sha256 SCOPE_PIN \
  --use isolated_release_cases --output /path/to/new/admission.json
```

The API `evidence.load_admitted` returns `(model, receipt)` only after recomputing
the bound evidence. Missing evidence remains unknown; failed evidence fails;
N/A cannot waive a mandatory metric. File content pins are not signatures or
independent authentication of physical measurements. The calling protocol must
pin the expected record and finite case scope. Outputs use exclusive creation.

|Purpose|Required evidence|
|---|---|
|`candidate_inspection`|Valid input/model/task/implementation/scope bindings; useful even when scientific quality fails|
|`isolated_release_cases`|Bindings, geometry fidelity, all expected-stable cases, numerical checks, primitive feasibility|
|`qualified_collection`|All primitive checks plus complete robot-task evidence, currently unknown|
|`qualified_export`|Collection requirements plus observation/export evidence, currently unknown|

Qualification covers the exact registered cases for one development asset and
support combination. It does not interpolate to a continuous range, extend to
challenge cases, provide independent cross-asset validation, or restore policy
testing/training/expanded collection. Existing production collectors/exporters
are not globally migrated by this module.

Heavy generation of collision models, physics, and full evidence checks run in
registered serial P007 CPU services with inherited <=8 CPU affinity, 12/16GiB
memory bounds and <=900 seconds per service. The frozen run protocol owns the
case list, thresholds, actual integration budget and stop rules.
