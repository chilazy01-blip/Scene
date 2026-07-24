# bedroom_fin_test Full Workflow Test 1

## Goal

Run `/data/wsj/main/scene/examples/bedroom_fin_test` through the full TreeSAGE Flow2 path step by step, with manual review after each major phase.

This test intentionally starts from the current automatically generated scene graph, even though it has known issues. The purpose is to observe how the uncorrected graph affects source image generation, TRELLIS.2 asset generation, layout, and validation.

## Inputs

- Example directory: `/data/wsj/main/scene/examples/bedroom_fin_test`
- Reference image: `213a6be9-3d27-45d3-b7d3-80eccc58816e.png`
- Prompt: `prompt.txt`
- Fixed scene graph: `scene_graph_auto_v1.json`
- Source images: `source_images/`
- Source image contact sheet: `source_images_contact_sheet.png`

## Progress

### Step 0: Input Preparation

Status: complete.

- Created prompt following the structure of `examples/bedroom_0610_113657/prompt.txt`.
- Created human-only review notes in `INPUT_REVIEW.md` and `human_constraints/README.md`.
- Generated plan-only scene graph run:
  `/data/wsj/main/scene_runs/tree_sage_flow2/protect/bedroom_fin_test_phase1_scene_graph_v1`
- Saved fixed graph:
  `/data/wsj/main/scene/examples/bedroom_fin_test/scene_graph_auto_v1.json`

Known scene graph issues to preserve for this test:

- Several object dimensions are inflated by later scale priors, especially slippers, rug, desk lamp, mug, clock, floating shelf, and curtain rod.
- `framed_landscape_art` relation cleanup left a bad support-like relation risk.
- Curtain/window/rod wall fixture overlaps are likely.
- Desk/chair overlap and desk lamp support ratio are likely.

### Step 1: Source Images

Status: complete.

Implementation route:

- Traced the prior `bedroom_21_08_44/source_images` workflow.
- Confirmed those images were generated with Codex built-in `imagegen`, then copied from `/data/wsj/.codex/generated_images/...` into the example directory.
- Reused the same route for `bedroom_fin_test`.

Outputs:

- `/data/wsj/main/scene/examples/bedroom_fin_test/source_images/`
- `/data/wsj/main/scene/examples/bedroom_fin_test/source_images_contact_sheet.png`

Check:

- `object_count=20`
- `image_count=20`
- `missing=[]`
- `extra=[]`

Manual review note:

- The generated images are usable for the next TRELLIS.2 asset test.
- The images intentionally preserve bad-graph signals: oversized slippers, thick rug, bulky curtain rod, and bulky desk lamp.

### Step 2: TRELLIS.2 Asset / Full Flow Run

Status: complete.

Output directory:

`/data/wsj/main/scene_runs/tree_sage_flow2/protect/bedroom_fin_test_full_from_bad_graph_v1`

Bridge startup:

```bash
cd /data/wsj/main/scene
source .env
SAGE_TRELLIS_MODEL=/data/wsj/main/scene/local_models/trellis2_primary \
ATTN_BACKEND=sdpa \
scripts/start_trellis2_bridge_512_no_webp.sh
```

Health check result:

- `status=healthy`
- `gpu_available=true`
- `trellis_model=/data/wsj/main/scene/local_models/trellis2_primary`

Full run command:

```bash
cd /data/wsj/main/scene
source .env
EX=/data/wsj/main/scene/examples/bedroom_fin_test
REF="$EX/213a6be9-3d27-45d3-b7d3-80eccc58816e.png"
OUT=/data/wsj/main/scene_runs/tree_sage_flow2/protect/bedroom_fin_test_full_from_bad_graph_v1
mkdir -p "$OUT"
/usr/bin/time -v "$SAGE_ORCH_PYTHON" sage/scripts/run_tree_sage_scene.py \
  --prompt-file "$EX/prompt.txt" \
  --flux-image "$REF" \
  --pose-reference-image "$REF" \
  --scene-graph-file "$EX/scene_graph_auto_v1.json" \
  --asset-source-image-dir "$EX/source_images" \
  --asset-source-image-required \
  --output-dir "$OUT" \
  --model "${SAGE_CODEX_MODEL:-gpt-5.5}" \
  --trellis-url "${SAGE_TRELLIS_URL:-http://127.0.0.1:8082}" \
  --trellis-pipeline-type 512 \
  --trellis-preprocess-image \
  --no-reference-depth \
  --no-mujoco-check \
  --skip-asset-renders \
  --no-clean-assets \
  > "$OUT/run.log" 2>&1
```

Run result:

- Exit status: `0`
- Wall time: `57:10.65`
- Max RSS: `5232348 KB`
- `run_summary.json` written.
- `scene_tree_sage_flow2.glb` written.
- Blender/front render artifacts written.

Core outputs:

- `scene_tree_sage_flow2.glb`
- `preview_topdown.png`
- `render_est_front_high_density_residual_refined.png`
- `reference_vs_render_est_front_high_density_residual_refined.png`
- `run_summary.json`
- `scene_graph.json`
- `scene_plan.json`
- `asset_registry.json`
- `asset_source_report.json`
- `assets_trellis2/`

Asset generation result:

- Input fixed scene graph object count: `20`
- Final run scene graph object count: `19`
- Removed object before asset generation: `desk_lamp`
- TRELLIS.2 generated `19` GLB files and `19` JSON sidecar files.
- `asset_registry_ok=true`
- Source image QA: `enabled=true`, `required=true`, `strict=true`, `count=19`, `bad=[]`

Generated asset ids:

`double_bed`, `left_nightstand`, `right_nightstand`, `wardrobe`, `desk`, `office_chair`, `floating_shelf`, `framed_landscape_art`, `window`, `left_curtain`, `right_curtain`, `curtain_rod`, `bedside_table_lamp`, `alarm_clock`, `potted_plant`, `white_mug`, `area_rug`, `left_slipper`, `right_slipper`.

Asset review warnings:

- `framed_landscape_art`: wall-attached asset requires extreme axis compression; consider regenerating as a flat wall-mounted asset.
- `left_curtain`: wall-attached asset requires extreme axis compression; consider regenerating as a flat wall-mounted asset.
- `right_curtain`: wall-attached asset requires extreme axis compression; consider regenerating as a flat wall-mounted asset.

Validation summary from `run_summary.json`:

- `plan_only=false`
- `scene_graph_object_count=19`
- `plan_object_count=19`
- `aggregate_collision_ok=false`
- `aggregate_conflict_count=2`
- `global_validator_ok=false`
- `scene_hypergraph_validation_ok=true`
- `scene_hypergraph_validation_warning_count=0`
- `branch_execution_ok=false`
- `branch_execution_failed_count=3`
- `final_layout_polish_ok=false`
- `mujoco_ok=true`

Major remaining failures:

- Aggregate collision has 2 conflicts: `left_curtain` vs `window`, and `right_curtain` vs `window`.
- Global validator has 5 conflicts:
  - The two aggregate curtain/window conflicts.
  - `window_exec_branch` failed because of curtain/window wall fixture collision.
  - `left_nightstand_exec_branch` failed: `left_nightstand` vs `floating_shelf`, plus `alarm_clock` and `bedside_table_lamp` support ratios at `0.0`.
  - `right_nightstand_exec_branch` failed: `potted_plant` and `white_mug` support ratios at `0.0`; `white_mug` strict small-object footprint ratio also failed.

Interpretation:

- Source-image-driven TRELLIS asset generation is not the blocker in this run; it completed for all 19 final objects.
- The uncorrected scene graph still causes downstream problems, but the failures are now localized:
  - wall fixture handling for curtain/window overlap,
  - nightstand tabletop support placement for small objects,
  - shelf/nightstand branch collision,
  - and unexpected removal of `desk_lamp` before final asset generation.
- This run is useful as the baseline for "bad graph, no manual correction" because it reached final assembly and produced concrete validation reports.

Next manual review targets:

- Inspect `reference_vs_render_est_front_high_density_residual_refined.png`.
- Inspect `preview_topdown.png`.
- Compare input `scene_graph_auto_v1.json` with output `scene_graph.json` to identify why `desk_lamp` was removed.
- Open `global_validator_report.json` and `aggregate_collision_report.json` before making any corrective code change.

### Step 3: Manual-Review Scene Graph Comparison

Status: complete.

Manual graph files:

- `/data/wsj/main/scene/examples/bedroom_fin_test/scene_graph_manual_review_v1.json`
- `/data/wsj/main/scene/examples/bedroom_fin_test/scene_graph_manual_review_v1_changes.md`

Manual graph policy:

- Kept all 20 object ids unchanged so the existing `source_images/<object_id>.png` files remain reusable.
- Fixed obviously bad dimensions for thin wall objects, small tabletop objects, the rug, slippers, curtain rod, framed wall art, and desk lamp.
- Removed the bad support-like relation `framed_landscape_art on double_bed`; replaced it with `framed_landscape_art above double_bed`.
- Removed noisy image-plane relations around `desk`, `office_chair`, `desk_lamp`, and curtain ordering.
- Deduplicated repeated `reference_tabletop_support_054` relation ids.
- Added explicit manual notes/relations for the window-curtain-rod wall fixture cluster.

Run output:

`/data/wsj/main/scene_runs/tree_sage_flow2/protect/bedroom_fin_test_manual_graph_v1`

Run result:

- The run was initially suspected to have been interrupted, but inspection on 2026-07-15 confirmed it completed.
- `run_summary.json` exists.
- `scene_tree_sage_flow2.glb` exists, size about `485M`.
- Output directory size: about `927M`.
- `assets_trellis2/` contains `20` GLB files and `20` JSON sidecar files.

Manual graph summary:

- `plan_only=false`
- `scene_graph_object_count=20`
- `plan_object_count=20`
- `asset_registry_ok=true`
- `aggregate_collision_ok=false`
- `aggregate_conflict_count=4`
- `global_validator_ok=false`
- `scene_hypergraph_validation_ok=false`
- `scene_hypergraph_validation_warning_count=1`
- `branch_execution_ok=false`
- `branch_execution_failed_count=10`
- `final_layout_polish_ok=false`
- `mujoco_ok=true`

A/B comparison against Step 2 bad graph baseline:

- Bad graph baseline removed `desk_lamp` and generated `19/19` assets.
- Manual graph kept `desk_lamp` and generated `20/20` assets.
- Bad graph baseline had `aggregate_conflict_count=2`, `branch_execution_failed_count=3`, and `scene_hypergraph_validation_ok=true`.
- Manual graph has `aggregate_conflict_count=4`, `branch_execution_failed_count=10`, and `scene_hypergraph_validation_ok=false`.

Main manual-graph failures:

- `desk_lamp` support on `desk` failed: `support_ratio=0.124373`, `center_ok=false`.
- `desk_lamp` also collides with `right_curtain` inside the `wall_west` branch.
- `left_curtain` vs `window` and `right_curtain` vs `window` wall fixture collisions remain.
- `global_validator_report.json` has `conflict_count=17`, including aggregate collisions, desk lamp support, one reference alignment warning, one spatial order warning, one hypergraph warning, and multiple branch commit failures.

Interpretation:

- The manual graph improved object retention: `desk_lamp` is no longer removed, and source-image TRELLIS generation works for all 20 objects.
- The manual graph did not improve final layout quality; keeping `desk_lamp` exposed a new desk/support/window-side collision problem.
- The next useful action is not another full run. First inspect why `desk_lamp` is assigned/kept in a `wall_west` branch position that collides with the curtain, and whether the desk lamp should be folded into the desk asset or constrained more tightly to the desktop.
