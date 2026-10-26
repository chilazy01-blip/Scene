# Generated red-object isolation smoke

This is the third link in the controlled diagnosis:

1. Source-A scene plus its analytic compound red cylinder.
2. SAGE-recreated room/tables plus the same analytic compound red cylinder
   (`embodied_generated_scene_smoke_20261015_v4`).
3. The exact accepted scene/controller from link 2, replacing only the red
   object's visual/collision geometry with a newly generated builtin-imagegen
   → TRELLIS.2 asset normalized to the same 40 × 40 × 70 mm envelope.

The new mesh keeps the original object's compiled mass, diagonal inertia,
friction, free joint, spawn draw and public controller-facing names. MuJoCo
renders the generated mesh and uses its compiled convex hull for contact. The
old cap names remain as 1 µm non-colliding sentinels because Source-A updates
friction by all three names without checking for a missing geom.

Before the single dynamic attempt, `pose_replay` restores every recorded v4
qpos and recomputes both models' contacts with `mj_forward`; it advances zero
physics steps. The dynamic rollout remains limited to one trajectory.

This is diagnostic evidence, not production training data.

## Observed result (2026-10-15)

- Asset admission passed: 40 × 40 × 70 mm, convex-hull/analytic-cylinder
  volume ratio 0.9821, maximum section radius ratio 1.1681.
- Same-qpos, zero-step contact replay changed the hand/object peak from
  27.4431 mm to 27.3713 mm (-0.0718 mm); the peak pair stayed
  `red_cylinder <-> right_hand_thumb_2_link`.
- The one dynamic attempt advanced 2,056 steps (10.28 s). The generated mesh
  tipped from 0° to 85.0° by 3.74 s and 89.3° by 4.60 s, before grasp.
- The dynamic peak was instead 20.5448 mm between `red_cylinder` and
  `table_top`; Source-A then aborted at `at_pick` with `no_grasp_ik`.

The dynamic trial is therefore not a full-task penetration comparison. The
valid same-pose counterfactual provides no support for the original analytic
cylinder being the cause of the roughly 28 mm hand/object penetration. The
dynamic trial separately shows that a visually acceptable generated asset can
still have an unusable collision hull/contact behavior.
