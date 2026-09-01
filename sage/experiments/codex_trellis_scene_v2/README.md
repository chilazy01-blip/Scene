# Codex + TRELLIS.2 text-to-scene V2

SceneDNA 的约束感知混合资产协同闭环已接入资产解析：审核资产检索与缺失资产生成共享同一份风格合同，风格只能在尺寸、能力、朝向、手性和几何硬门禁之后参与软重排；缺失资产会执行四张 2D 候选的 SigLIP2 语义、类别无关形态、DINOv3 审核锚点与局部外观融合，评分不确定时以相同 seed 晋级两个 TRELLIS.2 候选，再做 Blender 四视角审核和最多两轮有界重生成。alpha-safe v3 的 3 名独立评审、27 个独立 case 已完成：语义/形态偏好率为 `0.508025/0.524691`，主要指标 `0.516358`，未通过预注册门槛；默认替换继续关闭。失败归因表明形态差值与人工判断正相关，而当前零样本语义差值明显反向。默认关闭的类别无关形态改善门现已完成全新 seed 的第二轮候选生成，并冻结为 18 个独立 case + 2 个隐藏重复题的中文离线问卷；尚未收集新人工标签。设计、产物和诚实验收边界见 [SCENE_DNA.md](SCENE_DNA.md)，人工实验步骤见 [BLIND_REVIEW_PROTOCOL.md](BLIND_REVIEW_PROTOCOL.md)。

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

当前完整回归数字以 `AGENT.md` 的最后一次全量运行记录为准。

## Detail review and repair agent (opt-in)

新增的细节审查闭环以现有 GLB 为冻结对照，按“四视角重新取证 -> 可解释问题清单 -> 有界局部
修复/单资产重生成 -> 几何、语义、风格回归门 -> 提交或回滚”运行。它不重生成整个场景、不覆盖
当前主链，也不把自动分数下降的提案当作成功。后续局部 face-ID 执行器已在开发回放将提交从
0/2 提升到 1/2；合成开发/留出各 6/6 全部通过。独立自然 TRELLIS v2 pilot 在 3 类 × 2 seed 中
完成 6/6，检测 3 个候选，提交 2 个四视图植物地台修复、对弱证据衣柜安全回退，提交硬回归 0。
自然正例仍只有一个类别，功能继续 opt-in，不能据此宣称跨类别泛化或替换默认链。
架构、复现命令、真实指标与下一阶段边界见 [DETAIL_REPAIR_AGENT.md](DETAIL_REPAIR_AGENT.md)。

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

Explicit `tucked under` wording is preserved as a hard `tucked_under` relation rather than
approximated as `in_front_of`. The expansion contract asks for the target-local
`free_space_id=under_desk`; a defensive local normalization restores that relation only when the
cited evidence is an exact fragment of the original prompt and the reviewed category pair is
`office_chair -> desk`. It never upgrades generic nearness or front-of wording. The real regression
run `tucked_under_grounding_regression_20260724_v1` produced the typed relation directly, with zero
normalizations and zero rejected grounding updates.

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

Existing AABB/footprint validation remains the active broad phase and layout constraint system.
The capability/SDF work and generated-reference work are isolated pilots rather than default
pipeline stages:

- `capabilities.py`, `collision_proxy.py`, `sdf_pilot.py`, and `under_desk_pilot.py` exercise
  audited support surfaces and relation-aware voxel-SDF queries on real desk/mug/chair assets;
- `reference_soft_prior.py` compares a text-only plan with an optional generated reference image
  observation without changing the ordinary text path.

## Generic relation geometry (opt-in)

The second geometry experiment no longer selects collision logic from category pairs.  It compiles
typed relations into asset-declared geometry primitives:

- `supported_by` uses a bounded support plane;
- `contained_in` uses a containment volume;
- `tucked_under` and `partially_inserted` use a free-space volume, entry direction, functional
  source anchor, and minimum entry depth;
- `against` and `contact` use a bounded contact plane;
- every relation adds bilateral solid non-penetration.

The executable contract is in `relation_geometry.py`; bounded pose generation is in
`relation_solver.py`; `relation_geometry_bridge.py` audits multiple relation types through one
opt-in interface.  Accepted poses receive hash-bound certificates, and conservative mode rejects a
missing collision direction.  The old single-relation reference bridge remains unchanged for
reproducibility.

`multilevel_proxy.py` implements component-aware coarse/fine voxel proxies.  Watertight connected
parts are filled separately so an open shelf or desk bay is not sealed by a whole-asset fill.  Very
fragmented TRELLIS meshes fall back to a global surface shell when the component budget is exceeded;
the fallback and approximation error are explicit in metadata.  `mesh_verifier.py` provides the
final adaptive triangle-intersection check.  It reports `exact_predicates=false`: this clean-room
Python implementation borrows OpenMeshCraft's broad/narrow-phase separation but is not a substitute
for its exact arithmetic.

Compile real proxies with the offline Python command:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.compile_collision_proxies \
  --capability-registry \
    sage/experiments/codex_trellis_scene_v2/capabilities/pilot_desk_chair_v1.json \
  --asset-root /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/relation_geometry_v1/proxies \
  --levels coarse:0.04:1,fine:0.02:1
```

`propose_capabilities.py` proposes support/contact surfaces, open free-space boxes, entry-axis
candidates and generic anchors from a normalized asset and its fine proxy.  Proposals always contain
`review_required=true`, `approved=false`, and `automatic_approval_forbidden=true`; geometry heuristics
cannot silently become production semantics.

The design, acceptance matrix, current real-asset evidence and known limitations are recorded in
`GEOMETRY_RELATIONS.md` and `RELATION_GEOMETRY_VALIDATION.md`.

Internal relation solving uses a right-handed Z-up frame.  A scene exported directly by `trimesh`
must not be written to glTF without an axis-boundary transform: glTF consumers interpret the file as
Y-up, and Blender would rotate a floor into a wall.  `gltf_export.py` applies the required -90 degree
X rotation to an export copy while leaving the solver scene unchanged.  Its conversion CLI is:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.gltf_export \
  --input-glb /path/to/incorrect-direct-z-up.glb \
  --output-glb /path/to/fixed-y-up.glb \
  --report /path/to/axis_export_report.json
```

`sage/scripts/blender_render_sage_diagnostics.py` now performs a Blender-side Z-up guard whenever a
named floor is present.  A vertical floor stops the command with a nonzero exit code; successful
manifests include the measured world extents under `axis_validation`.

`relation_geometry_bridge.reconcile_layout_validation_with_geometry_audit` can supersede a legacy
`floor_collision` AABB result for an intentional containment/insertion pair.  The waiver is narrow:
the exact source/target pair must have an accepted bilateral certificate with zero deep samples and
a completed triangle check reporting no surface intersection.  It never removes unrelated layout,
architecture, clearance, support, or collision failures.

Large Codex stages are passed through stdin rather than as one process argument.  This keeps complex
typed-graph layout requests above Linux's per-argument size limit reproducible while preserving the
same `request.txt`, `response.txt`, stdout, and stderr artifacts.

## Generated reference as a soft layout prior

`reference_soft_prior.py` generates one fixed south-to-north view, asks Codex vision
for uncertain normalized object-position observations, and validates every observation against the
exact SceneBrief catalog. Both object-recognition confidence and position confidence must meet the
threshold. Unknown, duplicate, ambiguous, low-confidence, or out-of-range observations are rejected.
The experiment now defaults to a direct `gpt-image-2` Image API request. It requires
`OPENAI_API_KEY` and records the requested model, size, quality, output path, and timing without
persisting the credential. `flux1-schnell` remains an explicit local provider; there is no silent
fallback because that would make the A/B provenance false.

The image is not allowed to add/remove/rename/resize objects, alter the frozen architecture, or
override typed hard relations. A conservative deterministic projection searches a few bounded pose
candidates:

- wall-associated objects move only tangent to their existing wall;
- free objects have a configurable maximum displacement;
- a move is accepted only when reference alignment strictly improves and the ordinary hard
  validator still passes;
- the unchanged text-only plan is always the fallback.

The run saves the raw image observation, accepted/rejected soft prior, initial and repaired plans,
candidate audit, both final layouts, both validations, and one A/B report. A lower soft-prior RMSE
only proves that the branch followed its accepted observations; it is not evidence of better final
3D visual quality. Equal-asset Blender renders, multiple prompts/seeds, and final RGB/depth/mask
scoring are still required.

`reference_image_compare.py` performs a generator-side smoke comparison with one shared vision
auditor. It separately reports exact catalog counts, duplicated/missing instances, unexpected
major furniture, small accessories, decor, preferred-wall adherence, relations, and architecture.
Major furniture and accessories are intentionally separate: a second chair or independent drawer
chest is a layout-level failure, while a desk lamp or storage bin is an extra accessory. Books
stocking an expected bookcase are treated as implied contents rather than dozens of catalog errors.
The raw audits remain available because the evaluator itself is model-generated and may vary.

The first study comparison used one local FLUX.1-schnell sample and one Codex built-in image
generation sample with the same 120-word prompt. The built-in tool did not expose its backend model
id, so the report does not label it as a verified API `gpt-image-2` call. This is a one-sample smoke,
not a model ranking.

Example:

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.reference_soft_prior \
  --prompt "A compact study with exactly one desk, one office chair, one bookcase, one cabinet, and one floor lamp." \
  --room-type study \
  --expander rules \
  --baseline-planner codex \
  --model gpt-5.6-sol \
  --reference-provider gpt-image-2 \
  --image2-quality medium \
  --image2-size 1024x1024 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/reference_soft_prior_image2_example
```

Explicit local fallback:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.reference_soft_prior \
  --prompt "A compact study with exactly one desk, one office chair, one bookcase, one cabinet, and one floor lamp." \
  --room-type study \
  --reference-provider flux1-schnell \
  --flux-python /data/wsj/anaconda3/envs/simgen/bin/python \
  --flux-model /data/wsj/models/text_to_image__primary \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/reference_soft_prior_flux_fallback
```

### Reference observation and SDF fusion contract

The RGB image is never converted into the collision SDF and is never treated as metric geometry.
It contributes a confidence-weighted `ObservationGraph`: approximate object position, wall side,
facing, visibility, and pairwise composition. The selected real GLB and its reviewed capability
provide the metric geometry: normalized solid proxy/SDF, usable support surface, containment or
named free-space volume, coordinate frame, and scale policy.

After asset resolution, the intended repair order is:

1. preserve explicit prompt/typed relations as hard constraints;
2. use AABB as broad phase and cached per-asset voxel SDF plus sparse surface samples as narrow phase;
3. optimize bounded translation and yaw against reference observations, semantic relations,
   support/containment, visibility, and minimum pose change;
4. reject any candidate that violates the object catalog, architecture, dimension policy, hard
   relation, or SDF penetration tolerance;
5. among hard-valid candidates, prefer the lower confidence-weighted observation loss and retain
   the text-only pose when no candidate improves it.

In compact form, the soft objective is
`L = w_img L_observation + w_rel L_semantic + w_pose L_change`, subject to hard SDF/capability,
architecture, catalog, and dimension constraints. `w_img` is multiplied by recognition, position,
and view/depth confidence, so an uncertain single-view depth estimate cannot overpower geometry.

For `chair_tucked_under_desk`, the image supplies only the desired tuck depth and facing. The desk
capability must expose a named under-desk free-space region; chair sparse surface points query the
desk solid SDF, and optimization searches along the desk-front axis with a bounded yaw while
preserving `faces desk`. For `mug supported_by desk`, the image supplies an approximate top-surface
location, while `desk.top` determines the valid footprint and contact height. This is the first
isolated integration target before attempting whole-room SDF repair.

`reference_sdf_bridge.py` implements the next opt-in bridge. It does not create a semantic relation
from an image: the plan must already contain a hard `tucked_under` relation with a target-local
`free_space_id`, and `pilot_reference_sdf_binding_v1.json` must explicitly bind both semantic object
ids to reviewed asset ids. Accepted source/target room observations are converted into a relative
target-local soft pose; capability yaw remains authoritative because the current image observer
does not estimate metric orientation. The sparse SDF search selects a legal local pose, the
all-vertex path checks that selected pose, and only then is it transformed back into room-world
coordinates.

The ordinary AABB validator still runs. Its floor-collision result may be waived only for the exact
bound source/target pair when the dense relation check is `valid_under` with zero deep-penetrating
vertices. Every other boundary, architecture, dimension, facing, relation, walkway, and collision
violation remains active. Missing observations, relations, asset bindings, hash matches, dimensions,
or capabilities reject the opt-in stage rather than silently changing the scene.

Opt-in flags:

```bash
--relation-sdf-repair \
--relation-sdf-binding \
  sage/experiments/codex_trellis_scene_v2/capabilities/pilot_reference_sdf_binding_v1.json \
--relation-sdf-capability-registry \
  sage/experiments/codex_trellis_scene_v2/capabilities/pilot_desk_chair_v1.json \
--relation-sdf-asset-root \
  /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1
```

The deterministic whole-room bridge smoke is stored at
`reference_sdf_bridge_study_20260724_v1`. Its two synthetic accepted observations produce local
soft target `(0.04, -0.40, 0)`, confidence `0.9025`; the text baseline is `(0, -1.08, 0)`. The
833-candidate search rejects 197 outside-free-space and 387 collision poses, then selects local
`(0.0375, -0.505, 0), yaw=180 degrees`, which maps to world
`(2.4375, 3.055, 0), yaw=180 degrees`. The 166,249-vertex check reports `valid_under`, minimum
signed distance `-0.007066 m`, and zero points beyond the `0.0125 m` penetration tolerance.
Relation-aware validation waives exactly one pair-specific AABB false positive and finishes with
zero hard violations. These observations are synthetic contract fixtures, not a claimed image2 API
measurement.

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

Explicit chiral pairs such as slippers use a separate handed-pair contract. The members remain two
independent instances with stable `left_member` and `right_member` roles. Asset resolution first
looks for approved entries sharing one `asset_family_id` with complementary `pair_role` metadata;
when that bundle is unavailable, it reuses one source GLB and marks exactly one member for a baked
canonical-local lateral reflection. The lateral axis is derived as perpendicular to the audited
asset canonical front, so changing handedness does not reverse the functional heading. Blender
performs the reflection in mesh vertices before world yaw and
placement, then records the baked axis in the exported node extras. An unreflected same-asset pair is
a hard validation failure rather than a warning.

Handedness is anatomical, not image-relative. A filename or source ID such as `left_slipper` may
mean only camera-left and is not role evidence. A mirrored fallback therefore needs an approved
source `pair_role`, `pair_role_semantics=anatomical_wearer`, canonical front, and local medial axis.
Resolution records the source role separately from the requested member role; validation applies
the same reflection and yaw to the medial axis and requires both medial sides to point toward the
pair center. Unknown source roles, incorrect reflection parity, and outward-facing medial axes are
hard failures.

For a pair at the functional front of an anchor, `heading_rule=anchor_front` makes the anchor's
canonical front the pair heading and its perpendicular axis the side-by-side axis. Thus slippers at
the foot of a rotated bed stay parallel, point away from the bed, and preserve local left/right
ordering instead of inheriting the first slipper's arbitrary initial yaw.

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
- chiral-pair role, geometry-source/reflection, anchor-relative heading, and local left/right order

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

## Capability-aware SDF pilot

The first isolated rigid-contact pilot keeps the existing semantic-dimension AABB as broad phase,
builds a cached voxel SDF from the reviewed mesh, and binds the typed
`mug supported_by desk` relation to the asset-specific `desk.top` capability:

```bash
cd /data/wsj/main/scene

/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.sdf_pilot \
  --asset-root /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/cup_on_desk_sdf_pilot_20260724_v2
```

The minimal registry is
`capabilities/pilot_desk_mug_v1.json`. It records canonical dimensions, source-mesh coordinate
frame, dimension policy, voxel-proxy settings, reviewed support surfaces, containment placeholders,
and source GLB hashes. The source-mesh frame is deliberately separate from Blender assembly
metadata: raw glTF loaded by `trimesh` is Y-up, while Blender's glTF importer has already converted
the asset to Z-up before applying `asset_axis_to_z`.

The command compares:

1. semantic parent AABB top;
2. generic bottom-points-to-parent-SDF contact;
3. capability-aware `supported_by:top` contact plus forbidden-penetration checks.

For the reviewed desk center, all three correctly produce a 0 m support gap and no forbidden
penetration; capability-aware SDF therefore matches rather than artificially claiming an
improvement over the already-correct AABB placement. A separate edge probe demonstrates the
semantic gain: the overall parent AABB accepts a mug at the extreme edge, while the reviewed usable
support rectangle rejects it. Fixed mug scale remains `[1, 1, 1]`.

The real non-watertight desk/mug proxies take about 2.82 s/0.16 s to build at their configured
resolutions and occupy about 55 KB/20 KB. A second run reuses both caches. This pilot only optimizes
vertical translation and is not yet connected to the full V2 repair pipeline. It does not validate
friction, tipping, mass, soft bodies, articulation, or container free space.

The second isolated pilot now covers both sparse/dense consistency and a reference-guided
coarse-to-fine pose search for `chair_tucked_under_desk`:

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.under_desk_pilot \
  --asset-root /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1 \
  --output-dir /data/wsj/main/scene_runs/codex_trellis_v2/chair_under_desk_reference_guided_search_20260724_v2
```

`capabilities/pilot_desk_chair_v1.json` locks the reviewed desk/chair hashes, coordinate frames,
canonical dimensions, dimension policies, collision settings, and an asset-specific named
`under_desk` free-space volume. The free-space capability includes its valid box, entry axis,
allowed category, minimum footprint overlap, translation bounds, target yaw, and yaw tolerance.
The typed graph now carries hard `chair tucked_under desk` and `chair faces desk` relations; the
first relation must bind `parameters.free_space_id` in the target-local frame.

The offline reference queries
all 166,249 normalized chair render-mesh vertices; the runtime path queries a deterministic 4,096
point surface sample. For `outside`, `tucked`, and `overinserted`, both paths classify the same
placements as `outside`, `valid_under`, and `collision`. On the current machine, the three SDF
queries in the final v2 report take about 31.0 ms for the dense reference and 1.1 ms for the sparse
proxy, an observed 28.3x query speedup and 40.6x point reduction. These timings are local
observations.

The v2 search uses a soft reference target `(x=0.04, y=-0.40, yaw=170 degrees, confidence=0.85)`.
That requested depth is geometrically overinserted. A deterministic 0.05/0.025/0.0125 m and
5/2.5/1.25 degree coarse-to-fine search evaluates 833 unique poses: 197 fail named free-space
overlap, 377 fail the desk solid-SDF gate, and 259 are hard-valid. It selects
`(x=0.0375, y=-0.53, yaw=173.75 degrees)`. The sparse runtime proxy and all-vertex offline check
both classify the selected pose as `valid_under`; the dense minimum signed distance is
`-0.001641 m`, inside the `0.0125 m` voxel tolerance, with zero deep-penetrating vertices. Chair
scale remains fixed and facing remains inside the 15-degree capability tolerance.

The agreement gate compares classification, not exact signed-distance values. It fails if any
sparse result disagrees with the dense reference. The dense path is still not exact
triangle-triangle collision ground truth: a coarse mesh can have intersecting faces without an
inside vertex. The default v2 reference target is a synthetic observation contract, not a claimed
image2 measurement. An actual extracted target can be supplied through `--reference-target-json`.
The opt-in bridge now covers whole-room observation to target-local conversion and repair invocation
for one explicitly bound `tucked_under` relation. An authenticated image2 run, multi-relation
scheduling, and default-pipeline integration remain open.

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
