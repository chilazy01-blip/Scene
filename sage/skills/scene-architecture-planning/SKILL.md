---
name: scene-architecture-planning
description: Plan and review the architectural shell, door/window asset bindings, floor and wall finishes, structured cameras, composition constraints, bounded asset dimensions, and wall-backed furniture orientation for Codex TRELLIS scene generation. Use for room walls, openings, materials, front-facing or eye-level views, centered composition, object budgets, asset scaling policy, canonical fronts, architecture_plan.json, or changes to the V2 architecture-first pipeline.
---

# Scene Architecture Planning

Freeze the enclosing structure before resolving assets or choosing furniture coordinates. Treat the architecture plan as an input contract for every later stage.

## Planning order

Use this order:

1. Infer the room type and dimensions from the expanded prompt.
2. Require the north, south, east, and west enclosing walls.
3. Place the entry door and reserve its swing and approach clearance.
4. Place windows and reserve their horizontal and vertical openings. For a bedroom, prefer the main window on the wall opposite the entry door unless the prompt or envelope says otherwise.
5. Select the floor material, default wall finish, and at most one wall-material override; then freeze the architecture plan.
6. Parse camera and render requirements into structured fields before layout.
7. Resolve assets, canonical fronts, and canonical physical dimensions, then place furniture around the frozen openings.
8. Resolve functional facing before wall snapping and collision repair.
9. Validate structure and a layout-camera composition proxy, then render the requested view and a 45-degree diagnostic preview.

Never let furniture placement silently move or remove a door, window, wall, or floor decision.

## Constraints

Hard requirements:

- The architecture layer has exactly four enclosing walls.
- Door and window counts satisfy the room policy.
- Openings remain inside their wall and do not physically overlap.
- The entry swing and approach region stays free of floor furniture.
- Tall furniture and wall fixtures do not obstruct a window opening.
- The floor has a material with an embedded or referenced texture.
- The walls have a default finish with an embedded or referenced texture.
- Wall-finish overrides target valid walls and do not exceed the single-wall limit.

Soft requirements:

- Put the main door and window on different walls by default.
- For bedrooms, treat different walls as the minimum rule and prefer the main window on the wall opposite the entry door. This is a room-specific soft prior, not a global rule for kitchens, bathrooms, or inherited building envelopes.
- Prefer a window wall that will not compete with tall storage or primary wall fixtures.
- Preserve useful daylight, a visible entry route, and balanced wall composition.
- Allow an explicit user wall request to override the different-wall or bedroom opposite-wall rule, and record the override in `constraint_overrides`.

Doors, windows, walls, and floor finishes are architectural elements and do not count toward the furniture object budget.

Treat `target_max` as an auto-expansion target, never as permission to delete, merge, or penalize explicit instances. Limit only objects whose provenance is `codex_inferred_optional`; keep a separate high `hard_runtime_limit` as the fail-visible safety boundary.

## Camera and composition

- Materialize front-facing direction, eye height, centerline, focal length, aspect ratio, complete visibility, and occlusion requirements in `camera_requirements`.
- Project planned rotated boxes through that camera before accepting layout. Score framing, primary-group centeredness, bedroom symmetry, and occlusion clarity.
- Treat an explicitly requested off-center primary group or clipped required instance as hard. Keep moderate box-proxy occlusion soft because final mesh visibility requires render masks and depth.
- Pass composition violations to the same Codex repair loop as geometry violations. Do not repair a walkway by moving a requested centered bed or seating group off the centerline.
- Label the pre-render metric `layout_camera_projection_proxy`; do not present it as final RGB, depth, or instance-mask quality.

## Asset dimension policy

- Preserve manifest dimensions as canonical physical source dimensions. Do not let layout silently redefine them.
- Classify each category or asset as `fixed_physical`, `uniform_scalable`, `axis_scalable`, `opening_fit`, or `modular` before allowing size adaptation.
- Resolve a requested target size by preferring an exact variant, then bounded permitted scaling, another approved variant, size-specific TRELLIS.2 generation, and finally an explicit warning/failure.
- Record source dimensions, target dimensions, per-axis scale factors, policy, tolerance, and reason in the asset-resolution report.
- Reject unrestricted anisotropic furniture stretching. Keep door/window fitting under the existing frozen-opening `opening_fit` contract.
- Treat `dimensions.py` as the executable policy source. Require an accepted `dimension_resolution` before Blender assembly and hard-fail if later layout stages mutate its effective dimensions.
- Keep raw-mesh normalization distinct from canonical asset adaptation. Export both as glTF extras so QA can distinguish coordinate normalization from intentional physical scaling.
- In the first implementation, accept category defaults or upstream explicit targets. Do not claim packed-layout-driven dimension optimization until a preliminary layout stage supplies those targets.

## Door and window assets

- Freeze the wall, opening center, width, height, sill, and door clearance before resolving a door or window asset.
- Prefer an approved external-library asset whose category matches the opening. Fit it into the frozen opening and preserve its canonical-front and axis-normalization metadata.
- Use a parameterized frame, glass panel, or static door leaf when no approved asset is available. Record this as `parametric_fallback`; do not fail an otherwise valid room solely because an architectural asset is absent.
- Never resize or move an opening to accommodate a selected asset during asset resolution. Reject or fall back from assets whose topology or use constraints cannot represent the frozen opening.
- Keep the door hinge side and swing metadata even when the current visual asset is static. Asset reuse does not imply articulation support.

## Functional furniture orientation

For wall-backed storage and work furniture:

- Treat the face containing doors, drawers, handles, or accessible shelves as the primary interaction face.
- Put the declared `contact_face`, normally the back, toward the wall.
- Point the primary interaction face toward accessible room space.
- Record `front_clearance_depth` for the later functional-clearance pass; do not claim that clearance is validated unless the run report contains that check.
- Let Codex emit `facing_mode` and `contact_face`; let the deterministic orientation solver convert those semantics and asset canonical-front metadata into yaw.
- Apply asset-local normalization separately from scene yaw. Do not use semantic front metadata as an untracked mesh rotation.
- Treat a facing mismatch as hard when canonical-front confidence is at least 0.75, soft when using a low-confidence or policy fallback, and skip genuinely symmetric assets.
- Allow side contact, double-sided use, built-ins, corner cabinets, or room dividers only when the asset metadata or user prompt explicitly permits them.

For external libraries, read `asset_orientation.canonical_front_axis` when available and support legacy `asset_canonical_front.axis`. Cache first-use visual orientation review in a local overlay manifest instead of repeating it during every scene run.

## Floor materials

Choose from the runtime registry in `sage/experiments/codex_trellis_scene_v2/policies.py`:

- `warm_oak_plank`
- `light_oak_plank`
- `walnut_plank`
- `gray_wash_plank`
- `beige_ceramic_tile`
- `gray_stone_tile`
- `terrazzo_tile`
- `polished_concrete`

Use prompt material language when it is explicit. Otherwise use the room policy default. Use `--floor-material` for a deterministic test override.

## Wall materials

Choose from the wall-finish registry in `sage/experiments/codex_trellis_scene_v2/policies.py`:

- `warm_white_plaster`
- `cool_white_plaster`
- `soft_beige_limewash`
- `light_gray_matte_paint`
- `muted_sage_matte_paint`
- `blue_gray_matte_paint`

Use one default finish for all walls. Allow at most one override through the paired `--accent-wall` and `--accent-wall-material` options. Use `--wall-material` for a deterministic global override. Keep generated wall textures subtle, tileable, embedded in the GLB, and aligned in room-space UV coordinates across wall panels split by doors or windows.

## Hinges and articulation

Keep `hinge_side` and `swing_direction` as static door metadata. Mark hinge articulation as deferred until the asset schema, joint origin, axis, limits, collision shapes, and simulator export are implemented together. Do not report a visually rotated door leaf as a working articulated joint.

## Runtime contract

The source of truth is:

- `architecture.py`: selects and freezes structure decisions.
- `orientation.py`: converts functional facing and canonical fronts into world yaw.
- `assets.py`: selects dimension-compatible curated assets, stages size-specific generation gaps, binds openings, and records fallbacks.
- `dimensions.py`: classifies categories, rejects incompatible assets, and resolves bounded scale.
- `policies.py`: defines room defaults and floor/wall material presets.
- `validator.py`: enforces architecture hard and soft rules.
- `composition.py`: parses camera requirements and computes the pre-render projection score.
- `sage/scripts/blender_assemble_sage_scene.py`: cuts wall openings, preserves continuous wall UVs, and embeds generated floor/wall textures.

Inspect `architecture_plan.json`, `layout_plan_final.json.camera_requirements`, `layout_plan_final.json.orientation_resolution`, `validation_final.json.metrics.composition`, `validation_final.json.metrics.functional_facing`, the requested-view render, `scene_codex_trellis_v2.glb`, and `scene_front_45.png` when reviewing a run. A valid architecture plan must be created after text expansion and before `asset_resolution.json` or object layout.

## Command overrides

Use `--window-wall north|south|east|west` to express an intentional wall choice. If that wall also carries the door, keep the plan but require `door_window_same_wall_overridden=true` in validation metrics. If a bedroom choice is not opposite the door, require `door_window_opposite_wall_overridden=true`. Use `--floor-material <preset>` or `--wall-material <preset>` to test a default finish independently of prompt inference. Pair `--accent-wall <wall>` with `--accent-wall-material <preset>`; reject either option when supplied alone.
