# Relation geometry validation report

Date: 2026-08-21.  Status: first opt-in implementation complete; default V2 repair unchanged.

## What is implemented

- Category-independent compilation for `supported_by`, `contained_in`, `tucked_under`,
  `partially_inserted`, `against`, and `contact`.
- Generic bounded pose search from target slots, including an unseen source category test.
- Bilateral proxy checks, declared discretization uncertainty, hash-bound certificates and stale
  certificate rejection.
- Component-aware coarse/fine proxy compilation with an explicit high-component fallback.
- Adaptive Python triangle-level final verification with a candidate budget and inconclusive state.
- Automatic but never auto-approved proposals for support/contact planes, free-space boxes,
  entry axes and semantic anchors.
- One opt-in bridge that evaluates multiple hard relation types in a scene.

## Synthetic regression evidence

The tests cover cup/desk support, hover rejection, deep-penetration rejection, chair/desk partial
entry, functional anchor entry depth, book/box containment in a five-part open shelf, vertical
contact, missing reverse-check rejection, stale certificates, triangle intersection/coplanar
contact, candidate-budget failure, multilevel save/load and an unseen category.  The open shelf's
interior and front portal remain positive free space after proxy construction.

## Real curated asset evidence

Generated proxies live outside Git at:

```text
/data/wsj/main/scene_runs/codex_trellis_v2/relation_geometry_v1/proxies
```

The desk, chair and mug all compiled successfully at two levels.  The desk reports 16,170 source
components and the chair 8,022, so both correctly use `global_surface_budget_fallback` instead of
materializing thousands of tiny `Trimesh` objects.  Manifests are written last as commit markers.

The original whole-surface `minimum_footprint_overlap=0.15` criterion produced a proxy-accepted
chair pose near `(0.05, -0.48, 0), yaw=165 degrees`, but triangle verification found a real surface
intersection.  It was rejected.  A reviewed chair `seat_front` anchor plus a 0.05 m minimum entry
depth found target-local `(0, -0.52, 0), yaw=180 degrees`: the anchor is 0.09 m past the portal,
both 8,000-sample directions have zero deep penetrations beyond the proxy error bound, and the final
triangle broad phase has zero candidate pairs.

For the real mug and desk, the solver selected `(0.25, 0, 0.74893), yaw=0`.  The bounded top-plane
predicate reports full footprint inclusion and 17.7% contact samples; both collision directions
have zero deep penetrations.  Triangle contact exists and is expected for `supported_by`, showing
why relation semantics must interpret final intersection results.

One bridge audit containing both hard relations returns `ok=true`, two of two accepted and complete
bilateral checks.  The real desk capability proposer found a top plane at 0.74993 m and an open box
approximately `[-0.63,-0.36,0] -> [0.63,0.25,0.57]`, close to the reviewed desk top and leg bay.  It
also proposed downward entry because the volume touches the floor boundary; this is intentionally
left for human rejection and demonstrates why automatic approval is forbidden.

An existing SAGE-10k real open-shelf mesh (`102e68cd.ply`, 27,198 faces, one watertight component)
was then used as an uncurated experimental target.  The proposer found three cabinet bays open on
positive Y.  A previously unused synthetic book mesh was solved into one bay: 192 candidates, 168
proxy-valid, selected pose `(0.3075, -0.0425, 0.2125), yaw=0`, full containment, zero deep samples in
both directions, and zero triangle broad-phase candidate pairs.  This supplies real target geometry
plus an unseen source shape without adding a category branch.  Its proxy is stored at
`relation_geometry_v1/proxies/sage_102e68cd_open_shelf`; the asset is not yet curated or approved.

## Remaining limitations before default integration

- The Python triangle verifier uses adaptive floating point, not OpenMeshCraft exact predicates.
- High-component fallback is a conservative surface shell, not a RobustCage-quality watertight
  component cage with a proved Hausdorff bound.
- The checked-in open-shelf regression is synthetic, and the real SAGE shelf smoke is uncurated;
  the manifest still has no reviewed open bookcase.
- Support optimization is yaw-only and currently requires a horizontal support plane.
- Contact intersection is detected but penetration/contact classification still relies on the
  relation predicate and SDF depth; a native exact backend should expose richer classification.
- Capability proposals need a review UI/workflow and broader real-asset evaluation.
- Soft bodies, articulation, dynamics and joint swept volumes remain out of scope.

## Reproducible tests

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m unittest discover \
  -s sage/experiments/codex_trellis_scene_v2/tests -t .

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m unittest discover -s tests
```

Current result: 133 V2 tests and 12 repository-root tests pass, 145 total.
