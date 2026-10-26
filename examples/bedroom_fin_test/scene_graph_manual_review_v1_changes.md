# scene_graph_manual_review_v1 changes

- Source: `/data/wsj/main/scene/examples/bedroom_fin_test/scene_graph_auto_v1.json`
- Output: `/data/wsj/main/scene/examples/bedroom_fin_test/scene_graph_manual_review_v1.json`
- Original object count: `20`
- Manual object count: `20`
- Original relation count: `55`
- Manual relation count: `55`

## Dimension Fixes
- `wardrobe`: `{'width': 1.0725, 'length': 0.62, 'height': 1.87}` -> `{'width': 1.35, 'length': 0.62, 'height': 2.25}`
- `floating_shelf`: `{'width': 1.05, 'length': 0.41250000000000003, 'height': 0.3375}` -> `{'width': 1.05, 'length': 0.18, 'height': 0.08}`
- `framed_landscape_art`: `{'width': 1.1, 'length': 0.8250000000000001, 'height': 0.55}` -> `{'width': 1.05, 'length': 0.04, 'height': 0.65}`
- `curtain_rod`: `{'width': 1.35, 'length': 0.05, 'height': 0.7}` -> `{'width': 1.45, 'length': 0.05, 'height': 0.06}`
- `desk_lamp`: `{'width': 0.77, 'length': 0.41250000000000003, 'height': 0.55}` -> `{'width': 0.22, 'length': 0.22, 'height': 0.55}`
- `bedside_table_lamp`: `{'width': 0.30250000000000005, 'length': 0.24750000000000003, 'height': 0.42}` -> `{'width': 0.24, 'length': 0.24, 'height': 0.42}`
- `alarm_clock`: `{'width': 0.30250000000000005, 'length': 0.24750000000000003, 'height': 0.27}` -> `{'width': 0.16, 'length': 0.08, 'height': 0.14}`
- `potted_plant`: `{'width': 0.30250000000000005, 'length': 0.24750000000000003, 'height': 0.28}` -> `{'width': 0.2, 'length': 0.2, 'height': 0.28}`
- `white_mug`: `{'width': 0.30250000000000005, 'length': 0.24750000000000003, 'height': 0.27}` -> `{'width': 0.1, 'length': 0.1, 'height': 0.12}`
- `area_rug`: `{'width': 2.8, 'length': 2.3, 'height': 0.24750000000000003}` -> `{'width': 3.2, 'length': 2.4, 'height': 0.025}`
- `left_slipper`: `{'width': 1.1, 'length': 0.8250000000000001, 'height': 0.24750000000000003}` -> `{'width': 0.16, 'length': 0.3, 'height': 0.08}`
- `right_slipper`: `{'width': 1.1, 'length': 0.8250000000000001, 'height': 0.24750000000000003}` -> `{'width': 0.16, 'length': 0.3, 'height': 0.08}`

## Relation Fixes
- Removed `rel_011`: `framed_landscape_art on double_bed`; replaced with `framed_landscape_art above double_bed`.
- Removed noisy image-plane relations around `desk`, `office_chair`, `desk_lamp`, and curtain ordering.
- Deduplicated repeated `reference_tabletop_support_054` relation ids.
- Added manual window fixture cluster relations for curtains/window/rod.

## Notes
- Object ids are unchanged so `source_images/<object_id>.png` remains compatible.
- This is intended as a manual-review comparison baseline, not a final gold graph.
