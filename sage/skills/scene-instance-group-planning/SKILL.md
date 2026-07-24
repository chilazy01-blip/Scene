---
name: scene-instance-group-planning
description: Identify and compile paired or matched scene objects into typed instance-group contracts for coherent asset selection and bounded after-layout adjustment. Use when a prompt requests a pair, matching set, repeated coordinated objects, human-ordered placement, or when separate asset instances must behave as one layout unit without being merged for segmentation or collision.
---

# Scene Instance Group Planning

Represent one physical matched set with `instance_groups`. Keep the ownership tree and typed relations as the semantic source of truth; use the group only for asset coherence and bounded placement behavior.

## Recognition

Create an execution group only when the prompt provides direct evidence that the instances form one set:

- one pair of slippers, shoes, gloves, or similar counterparts;
- an explicitly matching repeated set;
- repeated modules that must share one design and arrangement.

Do not group objects merely because they are nearby or functionally related. A desk and chair remain related objects, not one instance group. Keep support and containment in the ownership tree and relation graph.

For unambiguous quantity phrases already parsed into exactly two instances, allow a deterministic `paired_instances` baseline. Let Codex refine its anchor and arrangement. For other sets, require Codex to quote an exact prompt fragment.

## Contract

Emit:

```json
{
  "group_id": "explicit_slipper_pair",
  "group_kind": "paired_instances",
  "cardinality": 2,
  "members": [
    {"object_id": "explicit_slipper_1", "role": "left_member"},
    {"object_id": "explicit_slipper_2", "role": "right_member"}
  ],
  "asset_contract": {
    "match_mode": "same_family",
    "fallback": "same_asset_reuse",
    "require_distinct_roles": true
  },
  "layout_contract": {
    "arrangement": "side_by_side",
    "reference_frame": "room",
    "anchor_id": "bed",
    "anchor_zone": "front",
    "anchor_min_gap": 0.05,
    "anchor_target_gap": 0.25,
    "anchor_max_gap": 0.8,
    "shared_orientation": true,
    "orientation_tolerance_degrees": 15,
    "min_gap": 0.03,
    "target_gap": 0.08,
    "max_gap": 0.2,
    "allow_member_respacing": true,
    "allow_rigid_translation": true
  },
  "source_evidence": "exact prompt fragment"
}
```

Use stable baseline object IDs. Preserve exact cardinality. Assign one member to at most one execution group, although it may appear in multiple advisory `constraint_scopes`.

## Asset resolution

Prefer in order:

1. an approved asset family with verified complementary roles;
2. one approved canonical asset reused for all members;
3. one shared generation specification and generated asset;
4. an explicit failure when the contract forbids fallback.

Record the selected family key and strategy on every member. Do not label reused identical geometry as a verified left/right pair. Report missing handedness as a soft QA limitation.

## Layout adjustment

Run after ordinary layout and typed-relation repair:

1. Preserve every member as an independent object.
2. Normalize world-facing direction using each asset's canonical front.
3. Adjust only the declared member order and bounded internal gap.
4. If an anchor is declared, form the compact set in the requested anchor zone.
5. Search collision-free candidates by translating the complete set rigidly.
6. Reject room-boundary, external collision, cardinality, role-order, anchor-gap, family, and orientation violations.

Do not permanently merge meshes, object IDs, instance masks, collision shapes, or ownership nodes. Do not use this bounded 2D pass as a substitute for later mesh/SDF contact optimization.

## Runtime files

Use:

- `instance_groups.py` for grounding, exclusivity, validation, and after-layout adjustment;
- `assets.py` for family-aware selection and shared-asset fallback;
- `repair.py` for the post-layout execution stage;
- `validator.py` for group hard/soft results;
- `scene_graph.py` to expose groups without changing hierarchy.

Inspect `instance_group_grounding.json`, `instance_group_asset_resolution.json`, `instance_group_resolution.json`, and `validation_final.json.metrics.instance_groups` when reviewing a run.
