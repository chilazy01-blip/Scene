# Codex + TRELLIS.2 text-to-scene V2

This directory is an isolated experimental pipeline. It does not modify or replace:

- `sage/scripts/run_codex_prompt_scene.py`
- `sage/scripts/run_tree_sage_text_scene.py`
- `sage/scripts/run_tree_sage_scene.py`

The initial V2 flow is:

```text
prompt
  -> structured SceneBrief expansion
  -> architecture planning (walls -> door -> windows -> floor/wall materials)
  -> curated asset reuse first
  -> local Flux + TRELLIS.2 only for missing assets
  -> Codex or deterministic layout planner
  -> canonical-front functional orientation resolution
  -> deterministic layout SDK validation and repair
  -> optional Codex repair
  -> optional Blender assembly and MuJoCo proxy check
```

## Typed scene graph

`scene_graph.py` compiles the flat architecture/object records into a typed scene graph with one
primary parent per node plus independent cross-node relations. The primary hierarchy is the stable
ownership, transform, and future optimization order; typed relations carry support, containment,
attachment, wall contact, facing, clearance, and other spatial/functional constraints without
forcing them into the tree.

Current hierarchy rules are:

- the room is the single root;
- walls and the floor are structural children of the room;
- each door/window opening is installed in its actual wall;
- ordinary furniture is contained by the room and separately supported by the floor;
- wall-mounted objects are children of their wall;
- support objects such as lamps and books are children of their supporting furniture.

Legacy `relations`, `support_id`, `preferred_wall`, and `facing_constraint` remain available for
the existing planners and validators. They are also normalized into relation records with a type,
constraint class, hard/soft strength, provenance, parameters, and directedness. After layout, each
object node records its world pose and records a parent-local pose when the parent frame is already
materialized; unresolved wall-local frames remain explicit rather than receiving invented XYZ
coordinates. Deterministic and Codex repair rebuild those poses after moving objects so the graph
cannot retain stale transforms.

Every run writes:

```text
scene_graph_initial.json   # architecture + requested object hierarchy before asset resolution
scene_graph_resolved.json  # same graph enriched with resolved asset metadata
scene_graph_final.json     # final world and parent-local layout poses
```

## Semantic grounding

Codex expansion now returns a typed delta in addition to prose: `relation_updates`,
`attribute_updates`, and `component_updates`. The model does not replace the deterministic
SceneBrief or generate an unconstrained graph. A local grounding pass validates stable object ids,
the bounded relation vocabulary, wall targets, relation strength, support-parent uniqueness, and
support cycles before mutating the canonical brief. Accepted and rejected updates are written to
`semantic_grounding.json` with provenance and source evidence. Room-policy side roles can carry a
locked reference frame. Grounding preserves that frame unless the cited prompt fragment explicitly
names a user viewpoint; attempted implicit overrides are normalized and recorded for audit.

Hard `supported_by` updates change the primary support parent; `against_wall` updates override the
room-policy wall default and create the corresponding functional-front constraint when applicable;
`faces` remains a cross-node relation. Target-facing yaw is solved after initial layout and again
after deterministic repair, so collision repair cannot silently discard a chair-to-desk facing
requirement. Grounded per-object appearance terms override category-level sentence scanning, which
prevents an attribute such as `ceramic` from leaking from a cup to a book stack mentioned in the
same sentence. Existing deterministic rules remain the fallback when Codex expansion is disabled.
The spatial validator independently checks locked side-role assignment and reports a hard
`side_role_assignment` violation if stable entities are mirrored, without deriving semantics from
entity-id suffixes.

Codex may also propose evidence-backed `constraint_scopes` for furniture semantics. These scopes
are advisory computation views over existing typed relations: local grounding validates exact
prompt evidence, object ids, domains, member uniqueness, and relation references, but never changes
the ownership tree or coordinates and never auto-merges overlapping scopes. Before asset resolution
and layout, `constraint_scope_envelopes.json` records a cheap minimum-dimension necessary-condition
bound for supported floor scopes. Its `not_ruled_out`, `potentially_infeasible`,
`insufficient_relations`, and `unsupported_domain` statuses do not block the pipeline in this first
version.

Validation also exposes a reporting-only `constraint_scope_failures` view. Raw relation
violations, hard/soft counts, `validation.ok`, and repair behavior remain unchanged. Failed
relations are aggregated only when they belong to the same accepted scope and form a connected
endpoint component; disconnected pairs inside one broad scope remain separate. A failed relation
omitted from `relation_refs` may be included for reporting when both endpoints are declared scope
members, and is marked in `membership_inferred_relation_ids`.

## Spatial relation CSP

`spatial_constraints.py` compiles `left_of`, `right_of`, `in_front_of`,
`separated_from`, `clearance_from`, `aligned_with`, and `mirror_symmetric` into executable 2D
footprint constraints. Directional relations use either the room axes or the target object's
canonical-front frame. `left_of/right_of` now express ordering and metric gap only; they no longer
silently require object centers to align on the transverse axis. Explicit center-line alignment
remains available through `alignment_mode=center` for compatible structured inputs.

`aligned_with` compares semantic `center/front_face/back_face/left_face/right_face` anchors along
the requested depth, left-right, x, or y axis. `mirror_symmetric` mirrors one object center across
a separate reference object, so a pair can be symmetric about a bed, table, or other stable anchor.
The bedroom policy uses these generic primitives for the two bedside tables: both back faces align
with the bed back face and the pair mirrors about the bed. Different object depths therefore do not
force their centers onto the same line. The validator and repair stage call the same evaluator so
they cannot disagree about whether a relation is satisfied.

Deterministic repair performs a bounded grid CSP search. It reuses the room candidate grid and adds
exact target-relative seeds, rejects candidates that violate room/door/window/wall/collision hard
constraints, then ranks the remaining candidates lexicographically by hard violation count, hard
residual, soft violation count, soft residual, and displacement. Only the relation source is moved;
the target remains the anchor. Search is repeated for a small fixed number of sweeps, followed by
target-facing yaw and support snapping. Unresolved relations remain explicit in `repair_history`
and validation rather than being silently dropped. Unsatisfied soft relations may trigger local SDK
search but remain soft and never trigger Codex repair by themselves.

The graph reserves a relation-aware SDF narrow phase, but this version does not generate SDFs or
infer relations from reference images. Existing AABB/footprint validation remains the active broad
phase and layout constraint system.

## Current scope

Supported room policies:

- `bedroom`
- `living_room`
- `kitchen`
- `study`
- `restroom`

Each room policy carries an object-count target and compactness budget:

| Room | Hard minimum | Auto-expansion target | Default objects | Target floor occupancy |
| --- | ---: | ---: | ---: | ---: |
| bedroom | 7 | 12 | 10 | 20%-38% |
| living_room | 8 | 12 | 8 | 15%-34% |
| kitchen | 7 | 11 | 7 | 17%-36% |
| study | 5 | 9 | 5 | 12%-32% |
| restroom | 5 | 8 | 5 | 16%-38% |

The hard minimum and required functional object ids are validation failures when missing.
`target_max` and `max_auto_inferred_objects` control only automatic semantic expansion. Explicit
user instances and room-policy requirements may exceed the target without a count penalty or
being merged. `hard_runtime_limit=40` is the separate fail-visible safety guard. Floor occupancy,
compactness status, and compactness score are written to `validation_final.json` and
`run_summary.json`.

Prompts can now materialize counted `book_stack`, `storage_box`, and `slipper` instances. A counted
`pillow` request is treated specially when the scene contains exactly one bed: the requested count
and local appearance terms become an integrated component requirement on the bed, and no standalone
pillow object is sent through asset resolution, generation, or layout. If there is no unique bed
parent, pillows remain standalone so the ambiguity stays visible instead of being guessed away.

Asset resolution writes `component_resolution.json`. A curated bed with manifest
`included_components` metadata can be verified; an older curated bed without that metadata is
explicitly marked `assumed_satisfied_by_composite_asset`. A generated or planned bed receives the
integrated pillow count in its single-asset Flux/TRELLIS prompt. A manifest that explicitly reports
too few pillows is marked `asset_manifest_component_shortfall` and blocks assembly readiness.

Use explicit wording such as `exactly two storage boxes`; do not use `such as` when every listed
item is mandatory. The canonical strict RGB-D bedroom benchmark prompt is
`prompts/bedroom_rgbd_front_strict.txt`. When it explicitly asks to avoid extra decorative
clutter, non-explicit room-policy optional decor is suppressed before Codex expansion.

Doors, windows, walls, and floor/wall materials live in a separate `architecture` layer and never count
toward the furniture budget. The pipeline freezes `architecture_plan.json` after text expansion
and before asset resolution or object layout. Every current room policy requires all four
enclosing walls, exactly one entry door, one or two windows, and a textured floor. Doors and
windows use different walls by default. Bedrooms use a stronger room-specific soft prior: the
main window prefers the wall opposite the entry door, and furniture assigned to that wall is
relocated by the room policy. `--window-wall` or an explicit prompt direction can override either
soft rule and records the decision in `constraint_overrides`.

Each door and window opening also carries an architecture asset policy. Asset resolution first
looks for an approved `door` or `window` entry in the curated manifest and stages it under
`assets_staged/architecture/`. When no approved entry exists, Blender uses the existing
parameterized frame/glass or static door-leaf fallback; missing architectural assets do not make
an otherwise complete furniture reuse run fail. The asset is fit into the already frozen opening
and is never allowed to move or resize that opening.

Eight generated floor presets are available: warm oak, light oak, walnut, gray-wash wood, beige
ceramic tile, gray stone tile, terrazzo, and polished concrete. Select one through prompt wording
or `--floor-material`. Blender rasterizes and embeds the selected image as a glTF
`baseColorTexture`, so it is present in both the GLB and the PNG preview. These procedural presets
are test materials for layout and architecture evaluation, not replacements for a production
material library.

The wall-finish layer uses one room-wide default and at most one per-wall override. Six deterministic
presets cover warm/cool plaster, beige limewash, light gray paint, muted sage paint, and blue-gray
paint. Blender embeds a subtle tileable PNG for each used wall material and projects UVs from
room-space coordinates, so panels split around a door or window retain aligned texture coordinates.
Use `--wall-material` for the default and pair `--accent-wall` with
`--accent-wall-material` for the optional override.

Implemented hard checks:

- rotated footprint inside room
- floor-object AABB collision
- east-wall entry clearance
- explicit hard-wall affinity; room-policy preferred-wall affinity is soft
- support containment and height
- grid reachability from entry to room center
- hard object-count minimum and required functional instances
- collisions between small objects sharing the same support surface
- wall-mounted object affinity and mounting height
- required architecture layer, door/window counts, and opening boundaries
- all four enclosing walls
- door clearance and window obstruction by furniture or wall fixtures
- required floor texture material
- required default wall texture material and valid single-wall override
- high-confidence functional fronts pointing into accessible room space
- hard typed directional, clearance, semantic-anchor alignment, and mirror-symmetry constraints

Implemented soft checks:

- layout-camera projection occlusion proxy
- room-specific floor occupancy range
- door and window on different walls unless explicitly overridden
- bedroom main window opposite the entry door unless explicitly overridden
- low-confidence functional-facing mismatch
- room-policy preferred-wall affinity
- soft typed spatial-relation residuals, optimized without being promoted to hard constraints

The brief and final plan carry structured `camera_requirements` and `render_requirements`.
`composition.py` projects planned rotated boxes through the requested south-to-north camera and
reports framing, primary-group centeredness, bedroom symmetry, and occlusion clarity. Explicit
complete-visibility and centered-composition failures are hard; moderate proxy occlusion remains
soft because boxes cannot determine real mesh visibility. The score is written to
`validation_final.json.metrics.composition` and `run_summary.json.composition_score`. This is a
pre-render layout gate, not a replacement for later RGB/depth/instance-mask scoring.

Wall-backed storage and work furniture carry a semantic `facing_constraint`: the back is the
default wall-contact face and the primary interaction face points into the room. Codex receives
and returns `facing_mode`/`contact_face`; `orientation.py` converts those semantics, the wall
inward normal, `asset_canonical_front` or external `asset_orientation`, and mesh-local offsets into
the final cardinal yaw. The validator reports angle error and treats a mismatch as hard when
canonical-front confidence is at least 0.75. Deterministic repair resolves facing before it
recomputes the rotated footprint and wall snap.

External libraries can provide `asset_orientation.canonical_front_axis`, confidence, and
`asset_affordance.allowed_wall_contact_faces`. Cache missing first-use visual orientation metadata
in a local overlay manifest; ordinary scene runs do not need repeated turntable/VLM analysis.

Door records keep `hinge_side` and `swing_direction`, but hinge articulation is deliberately marked
`deferred_static_metadata_only`. A rotated Blender door leaf is not yet a simulated revolute joint;
joint origin, axis, limits, collision shapes, and simulator export must be added together later.

The project-level planning guidance is in
`sage/skills/scene-architecture-planning/SKILL.md`; runtime behavior is implemented in
`architecture.py`, `assets.py`, `orientation.py`, `policies.py`, and `validator.py` so the skill and
executable chain share the same contract.

Generated TRELLIS.2 assets remain in the run's `assets_staged/` directory. They are not automatically promoted to a curated library. Geometry cleanup, turntable QA, canonical front-direction estimation, and promotion are intentionally separate future gates.

## Safe plan-only smoke

This makes no Codex or TRELLIS.2 call:

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2 \
  --prompt "A compact warm modern bedroom." \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_plan_smoke \
  --expander rules \
  --planner rules \
  --asset-mode plan
```

Override the default room budget only when a test needs it:

```bash
--hard-min-scene-objects 7 \
--target-max-scene-objects 12 \
--max-auto-inferred-assets 2
```

The legacy names `--soft-max-scene-objects` and `--max-optional-assets` remain CLI aliases.
The auto-inferred limit is additionally capped by the slots below the target. It is independent
of `--max-new-assets`, which limits TRELLIS.2 generation rather than scene composition.

## Asset dimensions

`dimensions.py` implements the first bounded adaptation gate. Every object now keeps
`requested_dimensions`, canonical manifest `source_dimensions`, effective layout `dimensions`, a
category/asset `dimension_policy`, and a complete `dimension_resolution`. Policies are
`fixed_physical`, `uniform_scalable`, `axis_scalable`, `opening_fit`, or `modular`.

Asset search removes dimension-incompatible candidates before style ranking. Fixed and modular
objects preserve canonical dimensions within a small tolerance; decor may scale uniformly inside
its range; selected furniture and soft architecture may change only declared axes; doors and
windows fit frozen openings. If no compatible reuse candidate remains, reuse mode fails visibly
and TRELLIS.2/plan mode records a size-specific generation request instead of stretching the
curated asset.

`asset_resolution.json` and `run_summary.json` record source/requested/effective dimensions,
per-axis adaptation scale, policy, reason, rejected candidates, and aggregate counts. The validator
hard-fails if effective dimensions change after resolution. Blender enforces the accepted contract,
records both canonical adaptation and raw-mesh normalization on each root, and exports those values
as glTF extras. This first version uses category defaults or upstream explicit target dimensions;
automatic packed-layout size optimization and natural-language numeric dimension extraction remain
later stages.

Architecture and floor overrides for deterministic tests:

```bash
--window-wall south \
--floor-material terrazzo_tile \
--wall-material warm_white_plaster \
--accent-wall north \
--accent-wall-material muted_sage_matte_paint
```

## Codex expansion and layout, without asset generation

```bash
cd /data/wsj/main/scene
source .env

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2 \
  --prompt "A bedroom." \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_codex_plan \
  --expander hybrid \
  --planner codex \
  --asset-mode plan \
  --codex-repair
```

`hybrid` calls Codex expansion only when the deterministic brief considers the prompt underspecified. Codex errors are not silently replaced with a fallback plan.

## Curated asset manifest

The optional manifest is read-only during a run:

```json
{
  "schema": "curated_scene_assets_v1",
  "assets": [
    {
      "asset_id": "bed_modern_001",
      "category": "bed",
      "styles": ["modern", "warm"],
      "qa_status": "approved",
      "glb_path": "bedroom/bed/bed_modern_001.glb",
      "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05}
    }
  ]
}
```

Run in strict reuse-only mode:

```bash
--asset-mode reuse \
--asset-library-manifest /path/to/manifest.json
```

The run fails before assembly if any required category is missing.

## Generate only missing assets with TRELLIS.2

Start the existing local Flux + TRELLIS.2 bridge first. Then run:

```bash
cd /data/wsj/main/scene
source .env

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2 \
  --prompt "A warm modern bedroom with balanced storage and clear walking space." \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_full_01 \
  --expander hybrid \
  --planner codex \
  --asset-mode trellis2 \
  --asset-library-manifest /path/to/manifest.json \
  --max-new-assets 8 \
  --trellis-url http://127.0.0.1:8082 \
  --trellis-pipeline-type 512 \
  --assemble \
  --mujoco-check
```

Asset resolution first writes `missing_asset_generation_plan.json`: the source scene prompt and
required inventory are compared with the curated manifest, then every missing instance receives a
bounded single-object specification and `bridge_input_prompt`. The full room prompt is retained
only as provenance and is never appended to the Flux input. Category-local appearance terms and
global style tags may be extracted from it. Equivalent missing instances share one generated GLB
and are staged under stable per-instance filenames. Exact metric dimensions remain structured
post-generation adaptation metadata; Flux receives only a visual proportion hint. The bridge then
generates one isolated reference image per unique specification and runs TRELLIS.2. The exact
composed prompt selected by the bridge is recorded as `final_flux_prompt` in
`asset_resolution.json` and in each generated asset sidecar.

Every V2 Blender assembly now renders two 960x720 dollhouse references. `scene_front_45.png`
keeps the existing front-left diagonal view and hides the south/west camera-facing walls.
`scene_front_center_45.png` places the camera on the room's front-center axis with a 45-degree
downward sightline and hides only the south wall. Walls are hidden only for rendering and the
exported GLB keeps the complete room. Rendering is enabled by default and can be skipped with
`--no-render-preview`.

The assembler cuts real openings into the wall panels. It imports approved door/window assets when
their bindings are available and uses parameterized door frames, an inward-open static door leaf,
window frames, and window glass as explicit fallbacks. The fixed front-left preview hides the south
and west walls, so a default bedroom's west-wall window remains present in the GLB even though it is
outside that single reference view.

## Single-asset TRELLIS.2 pilot

When a reference image already exists, Flux is not required. Start only the TRELLIS.2 bridge, then generate exactly one staging asset:

The pilot also accepts `--category door` with a 0.9 x 0.08 x 2.1 m architecture target. Door
pilots remain `pending_visual_review`; they are not added to the curated manifest until front-axis,
frame/opening fit, back-face quality, and static hinge metadata have been reviewed.

```bash
cd /data/wsj/main/scene
source .env

scripts/start_trellis2_bridge_512_no_webp.sh
```

In a second terminal:

```bash
cd /data/wsj/main/scene
source .env

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.pilot_asset \
  --category bed \
  --object-id pilot_wooden_bed_001 \
  --reference-image /data/wsj/main/scene/examples/bedroom_21_08_44/source_images/wooden_bed.png \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/asset_pilot_wooden_bed_001 \
  --trellis-url http://127.0.0.1:8082 \
  --pipeline-type 512 \
  --steps 12 \
  --texture-size 512
```

The command creates one GLB and one structural inspection report. Its manifest candidate remains `pending_review`; running the pilot never modifies a curated asset manifest automatically.

## Promote reviewed legacy image-scene assets

The promotion command keeps raw source copies, creates reduced-poly optimized GLBs, records corrected dimensions and front directions, quarantines the malformed TRELLIS rug, and replaces it with a procedural thin rug:

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.curate_legacy_assets \
  --source-dir /data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_manual_debug_no_clean_v1/assets_trellis2 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1
```

Use the resulting library with:

```bash
--asset-library-manifest /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/manifest.json
```

If the bridge fails offline while loading `briaai/RMBG-2.0`, create a local model overlay and restart the bridge with it:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.prepare_local_trellis_model \
  --source-model /data/wsj/models/trellis2_primary \
  --rembg-model /data/wsj/models/rmbg_2_0 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/trellis2_primary_local

SAGE_TRELLIS_MODEL=/data/wsj/main/scene_runs/codex_trellis_v2/trellis2_primary_local \
  scripts/start_trellis2_bridge_512_no_webp.sh
```

The overlay contains patched JSON plus a symlink to the original large checkpoint directory, so it does not duplicate model weights or alter `/data/wsj/models/trellis2_primary`.

## Important outputs

```text
selected_prompt.txt
architecture_plan.json
scene_brief.json
scene_brief_resolved.json
asset_resolution.json
layout_plan_initial.json
validation_00.json
validation_*_sdk.json
validation_*_codex.json
layout_plan_final.json
validation_final.json
layout_preview.svg
run_summary.json
assets_staged/                 # reuse/TRELLIS.2 mode
scene_codex_trellis_v2.glb     # --assemble
scene_front_45.png              # --assemble, unless --no-render-preview
scene_front_center_45.png       # --assemble, unless --no-render-preview
mujoco_check.json              # --mujoco-check
```

## Tests

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m unittest discover \
  -s sage/experiments/codex_trellis_scene_v2/tests \
  -t . \
  -v
```
