# bedroom_fin_test Input Review

This example should be run as a staged full-flow test. Each stage must be manually reviewed before moving to the next stage.

## Phase 0: Prepared Inputs

- [x] Reference image exists: `213a6be9-3d27-45d3-b7d3-80eccc58816e.png`
- [x] Prompt exists: `prompt.txt`
- [ ] Fixed scene graph exists: `scene_graph_auto_v1.json`
- [ ] Human constraints exist if needed: `human_constraints/*.json`
- [ ] Image2 source images exist in `source_images/`, one PNG per scene graph object id

## Phase 1: Scene Graph And Reference Grounding

Run only scene graph / planning first, then review:

- `scene_graph.json`
- `reference_instance_overlay.png`
- `reference_instance_crops/`
- `reference_alignment_report.json`
- `scene_hypergraph_validation_report.json`
- `global_validator_report.json`

Manual acceptance criteria:

- Object list is compact and complete.
- Bounding boxes tightly cover the visible object.
- Bed, rug, desk, chair, nightstands, wardrobe, wall art, shelf, window, curtain rod, tabletop items, and slippers are not mixed into each other.
- Small objects with uncertain boxes are marked by human constraints or removed from the fixed graph.
- Support relations are semantically correct.

Do not proceed to asset generation until this phase is accepted.

## Phase 2: Source Images

Prepare one isolated front-view source image per accepted object id:

```text
source_images/<object_id>.png
```

Manual acceptance criteria:

- File names exactly match scene graph object ids.
- Each image contains one object, centered, with minimal background clutter.
- Soft bed textiles are integrated into the bed source image rather than separate objects.
- Wall/window/curtain assets are visually consistent with the reference.

## Phase 3: Full Flow

Run full Flow2 with:

- `--prompt-file prompt.txt`
- `--scene-graph-file scene_graph_auto_v1.json`
- `--asset-source-image-dir source_images`
- `--asset-source-image-required`
- `--no-clean-assets` unless cleanup is being tested explicitly

Review:

- `asset_registry.json`
- `assets_trellis2/*.glb`
- `scene_tree_sage_flow2.glb`
- `preview_topdown.png`
- final render images
- `aggregate_collision_report.json`
- `global_validator_report.json`
- `run_summary.json`
