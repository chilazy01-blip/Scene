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
    "fallback": "mirror_primary",
    "require_distinct_roles": true,
    "requires_handedness": true,
    "requires_medial_facing": true,
    "medial_facing_tolerance_degrees": 35,
    "mirror_axis": "lateral"
  },
  "layout_contract": {
    "arrangement": "side_by_side",
    "reference_frame": "anchor_local",
    "anchor_id": "bed",
    "anchor_zone": "front",
    "anchor_min_gap": 0.05,
    "anchor_target_gap": 0.25,
    "anchor_max_gap": 0.8,
    "heading_rule": "anchor_front",
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

Use the handedness fields only for chiral counterparts such as slippers, shoes, or gloves. Matching
but non-chiral objects such as nightstands may share one asset without reflection. Do not let a model
refinement weaken a deterministic chiral contract, exchange its stable member roles, or remove an
evidence-backed functional anchor.

Treat member roles as anatomical roles in the wearer's forward frame. Never infer anatomy from an
asset ID, filename, source object ID, or image-space labels such as `left_slipper`: `left` may only
mean camera-left. A mirrored fallback needs an approved source `pair_role`,
`pair_role_semantics=anatomical_wearer`, audited canonical front, and audited local medial axis.
For footwear facing away from a bed, the wearer's left position is determined from the footwear
forward vector, not from the viewer's left side.

## Asset resolution

Prefer in order:

1. an approved asset family with verified complementary roles;
2. one approved canonical asset, with exactly one member baked as its local lateral reflection;
3. one shared generation result, again with exactly one member baked as its lateral reflection;
4. an explicit failure when the contract forbids fallback.

`lateral` means the local axis perpendicular to the asset's audited canonical front: use local Y for
an X-facing asset and local X for a Y-facing asset. Audit or correct canonical-front metadata before
trusting this result. Rotation changes heading but never changes handedness.

Record family, role, strategy, reflection axis, and handedness provenance on every member. For a
materialized chiral pair, unreflected identical geometry or unverified roles are hard failures, not
soft QA. Do not claim two independently generated shapes form a pair merely because their prompts
match.

Record the source mesh role separately from the requested member role. Reflection must change the
source role exactly once: an audited right source becomes left only when laterally reflected. After
world placement, transform each audited medial axis through the same reflection and yaw and require
both medial axes to point toward the pair center. Missing source-role evidence, incorrect reflection
parity, or outward-facing medial axes are hard failures.

## Layout adjustment

Run after ordinary layout and typed-relation repair:

1. Preserve every member as an independent object.
2. Resolve an explicit anchor heading first. `anchor_front` uses the anchor canonical front for
   every member; otherwise preserve the first member's heading.
3. Adjust only the declared member order and bounded internal gap.
4. If an anchor is declared, use its perpendicular lateral axis for side-by-side order and form the
   compact set in the requested anchor zone.
5. Search collision-free candidates by translating the complete set rigidly.
6. Reject room-boundary, external collision, cardinality, role-order, anchor-gap, family, and orientation violations.

Do not permanently merge meshes, object IDs, instance masks, collision shapes, or ownership nodes. Do not use this bounded 2D pass as a substitute for later mesh/SDF contact optimization.

## Runtime files

Use:

- `instance_groups.py` for grounding, exclusivity, validation, and after-layout adjustment;
- `assets.py` for verified family-pair selection or one-source mirrored fallback;
- `blender_assemble_sage_scene.py` for baked canonical-local reflection before world placement;
- `repair.py` for the post-layout execution stage;
- `validator.py` for group hard/soft results;
- `scene_graph.py` to expose groups without changing hierarchy.

Inspect `instance_group_grounding.json`, `instance_group_asset_resolution.json`, `instance_group_resolution.json`, and `validation_final.json.metrics.instance_groups` when reviewing a run.
