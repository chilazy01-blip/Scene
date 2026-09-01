# Scene detail review and repair branch

## Status and claim boundary

This is an independent, opt-in experiment. It keeps the existing SceneDNA/TRELLIS output as an
immutable control and never replaces the default image-to-scene or text-to-scene path. The first
strict real-GLB pilot produced no accepted repair. A later frozen-case development replay now
accepts one evidence-localized slipper repair while leaving the bookcase unchanged. A later frozen
synthetic held-out benchmark passes all localization/safety gates, and a separate natural TRELLIS
pilot accepts two real platform removals out of six new generated assets with zero committed hard
regressions. The natural pilot is still small and concentrated in one repaired category, so it does
not justify enabling the branch by default.

The implementation is deliberately a measured agent loop rather than an unconstrained visual
language model rewriting a whole scene:

```text
frozen control GLB
  -> reacquire four-view evidence with safe camera fit
  -> compile evidence-grounded findings
  -> choose the cheapest bounded intervention
  -> render and measure the proposal
  -> hard geometry + semantic + style regression gates
  -> commit only a verified improvement; otherwise roll back
```

The code is split into:

- `detail_repair_agent.py`: category-independent diagnosis, repair planning, reference ranking,
  and commit/rollback verification;
- `detail_repair_runner.py`: immutable-control A/B orchestration, generation budget, reports, and
  hidden-side human calibration exports;
- `detail_face_localizer.py`: multi-view defect-mask projection to stable mesh object/polygon IDs,
  including bounded centroid projection for faces hidden behind the visible surface;
- `../../scripts/blender_repair_localized_region.py`: seed-connected low-region editing with
  deletion scope and material-preservation certificates;
- `../../scripts/blender_trim_forbidden_lower_platform.py`: auditable local mesh executor with a
  60% maximum-face-removal safety stop, retained as a fallback baseline;
- `../../scripts/blender_render_asset_turntables.py`: adaptive evidence framing and layered 3D
  footprint measurements plus aligned face-ID/depth/normal buffers and camera matrices;
- `scene_dna_multiview.py`: structure-profile lookup and combined 2D/3D platform evidence.

## What the critic can currently see

All automatic actions must be backed by measurements. Current findings cover clipped or missing
views, detached fragments, compact-silhouette deformation, unintended holes, ground/platform
artifacts, opposite-view inconsistency, destructive proportion scaling, semantic/required-part
mismatch, and style-detail mismatch. The critic does not infer a mesh edit from free-form prose.

The camera is checked first because a bad diagnostic image can make a correct GLB look broken. This
already corrected the bookcase case: the unchanged control changed from a false hard failure to a
usable `open_repeated_frame` assessment after safe re-rendering. No geometry was altered.

## Allowed interventions

The current executor budget is intentionally narrow:

1. Re-render the same asset with safe framing; this costs no generation budget and does not mutate
   the GLB.
2. For a measured lower-platform failure, form lower-image masks in four orthographic views, map
   ray hits and projected 3D face centroids back to stable polygon IDs, and edit only seed-connected
   faces whose complete geometry lies below 28% of normalized asset height. Automatic editing needs
   multi-view defect confirmation and normally refuses removal above 50% of the source faces.
   Because uniform remeshing can put most triangles on a semantically unimportant flat platform,
   the cap may rise to 85% only when the normalized lower/upper footprint ratio is at least 8 and
   all four horizontal views independently confirm the broad lower overhang. The 28% height bound,
   material certificate, and post-edit regression gates remain mandatory. Legacy
   low-component/low-slab variants remain fallback development operators.
3. Rank unused, already gate-passing 2D references according to the observed failure and regenerate
   only the failed asset with the same frozen TRELLIS seed.

Whole-scene regeneration is forbidden. The source control directory is never written. A proposal
is accepted only if it is scene-assembly usable, introduces no new hard failure, does not regress
semantic score by more than `0.05`, style by more than `0.08`, or the aggregate automatic score by
more than `0.08`, and resolves a hard problem or makes a material soft improvement.

For a certified localized edit, a zero-shot text "style" drop may be replaced by stronger direct
appearance evidence: material/node/texture hashes must remain identical, surviving face material
assignments must be unchanged, and no whole-asset regeneration may occur. Semantic identity,
aggregate score, hard failures, and the removal limit still gate the edit. This distinction is
needed because the old text contrast score treated removal of the unwanted platform silhouette as
a style change. It does not prove that every design detail is preserved; hidden human evaluation
is still required.

The local mesh idea borrows the useful engineering boundary from RobustCage and OpenMeshCraft:
operate on a bounded geometric region, retain explicit geometric evidence, and verify the result
after the edit. It is not a port or reproduction of either algorithm. In particular, the current
trim executor has no exact-predicate remeshing, learned part correspondence, or deformation cage.

## Strict real-GLB pilot

The frozen failing categories were one open-back slipper and one open bookcase. The final report is:

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_detail_agent_dev/final_strict_v1/
  detail_repair_branch_results.json
  detail_repair_quality_summary.json
  blind_review_trials.json
  private_blind_key.json
```

Results:

| Measure | Result |
|---|---:|
| Cases completed | 2 / 2 |
| Local mesh attempts | 5 |
| Single-asset regeneration attempts | 2 |
| Attempts that removed at least one hard failure | 2 |
| Verified repairs committed | 0 |
| Cases rolled back | 2 |
| Hard regressions committed | 0 |

For the slipper, two low-slab variants removed the measured platform failure. The stronger of them
kept semantic regression within the allowed range (`-0.049401`) but style fell by `-0.197154`, so it
was rejected. A deeper cut also failed semantic and style gates. Other local variants and the
unused-reference regeneration retained the platform failure. For the bookcase, corrected evidence
capture showed that the original GLB was already geometrically usable. The alternate reference was
also usable but regressed style by `-0.224504`, so the original remained selected.

`blind_review_trials.json` compares each control with the strongest rolled-back proposal for
calibrating the automatic gates. It is not a list of accepted repairs. Keep
`private_blind_key.json` separate from reviewers.

## Frozen-case localized-face replay

The new replay uses the same two frozen controls and no TRELLIS regeneration budget:

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_detail_agent_dev/localized_face_final_v1/
  detail_repair_branch_results.json
```

| Measure | Old strict pilot | Localized-face replay |
|---|---:|---:|
| Cases completed | 2 / 2 | 2 / 2 |
| Intervention attempts | 7 | 1 |
| Verified repairs committed | 0 | 1 |
| Hard regressions committed | 0 | 0 |
| Unnecessary bookcase mesh edits | 0 | 0 |

For the slipper, four views confirmed the defect. The localizer selected 39,120 evidence-backed
seed faces and the connected executor removed 40,059 of 95,629 faces (`0.418900`), below its `0.50`
safety limit. The lower/upper footprint ratio changed from failing to `2.638709` against a maximum
of `2.8`; all hard geometry gates then passed and no new hard failure appeared. Semantic delta was
`-0.048128` (limit `-0.05`) and automatic-score delta was `-0.060803` (limit `-0.08`). The material
graph hash was identical before and after, textures/node parameters were untouched, and surviving
face material assignments were verified. The proposal was therefore committed. Visual inspection
of the four-view sheet confirms that the circular display platform disappeared while the pink
slipper upper, strap, and sole remained.

For the bookcase, safe evidence capture removed the apparent clipping failure without altering the
GLB. The localized operator was not invoked. This is the intended abstention behavior.

The exact replay ran 220 V2 tests and 12 repository-root tests successfully. The localized Blender
executor was also rerun directly after adding the material-assignment certificate and reproduced
the same 40,059-face bounded edit.

## Frozen synthetic held-out and natural TRELLIS pilot

The category-independent benchmark at
`scene_detail_agent_heldout_20260824_v1` uses three development and three held-out curated asset
categories, two defect variants, and two frozen seeds. Both 6-case splits score `1.0` macro face
precision, `1.0` macro face recall, and `1.0` repair success. Protected source-face removal is
0/359,998 on development and 0/899,998 on held-out; clean-control false triggers and committed hard
regressions are zero. This proves removal of the injected low platform, not natural efficacy.

Natural protocol v2 is frozen at:

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_detail_agent_natural_20260824_v2
```

It uses the curated canonical `plus_y` front view, new seeds `626262/737373`, and three held-out
categories (office chair, potted plant, wardrobe). All 6/6 generations completed. Three outputs
triggered the platform proposal; both four-view plant cases passed the tessellation-aware edit and
post-repair gates, while the weaker two-view wardrobe case remained behind the 50% safety stop and
fell back to its immutable control. Two repairs were committed and no hard regression was
committed. Visual inspection confirms that the square platforms disappeared while pots and foliage
remained.

Natural v1 used `plus_x`, a side view in this asset convention. It produced thin malformed subjects
and widespread platforms and is retained only as a diagnostic capture failure. The eligible v2
pilot questionnaire is
`scene_detail_agent_natural_blind_20260824_v1/SceneDetail_natural_pilot_blind_offline.html`; it has
two independent comparisons and one hidden repeat, with no sealed key embedded. Both positive cases
are potted plants, so this is a direction check rather than a cross-category generalization claim.

## Reproduction command

With the local TRELLIS bridge running and SigLIP2 available offline:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python -m \
  sage.experiments.codex_trellis_scene_v2.detail_repair_runner \
  --source-3d-root \
    /data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_v4_dev/paired_3d_alpha_safe_v4 \
  --candidate-root \
    /data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v3_alpha_safe/candidate_results_alpha_safe_v1/cases \
  --output-dir /path/to/new_detail_branch_run \
  --case-id case_5d2721c47d1e \
  --case-id case_ba5284f356bf \
  --maximum-generation-attempts 0 \
  --blender /data/wsj/tools/blender/blender \
  --semantic-model \
    /data/wsj/cache/hf_home/hub/models--google--siglip2-base-patch16-naflex/snapshots/b53b807d3a2d5e2b3911292f2d69e5341cdc064c \
  --semantic-device cpu
```

Use a new output directory for every run. Reusing the control root as output is outside the
experiment contract.

## What remains unsolved

The next priority is expanding beyond the current typed `forbidden_platform` deletion. The evidence
renderer and image-to-face mapping are generic infrastructure, but the only automatic reconstruction
operator still deletes a connected low region; it cannot rebuild missing geometry, repair arbitrary
surface defects, or preserve topology through exact-predicate local remeshing/cage deformation.
The second priority is extending the critic from isolated assets to full-scene relations:
left/right handedness, pair membership, object counts, opening direction, support/contact, and
fine orientation. The synthetic localization and small natural pilot are now complete. The next
evidence gap is a larger natural study with enough independently generated defects across multiple
repaired categories, prompts and seeds, followed by hidden-label human A/B calibration. Until that
cross-category study passes, this branch must remain opt-in and the default pipeline must stay
unchanged.
