# bedroom_21_08_44 Full Flow Test

Date: 2026-07-05

Goal: run the current bedroom example through a complete Flow2 path using the already generated TRELLIS assets as reusable inputs, and record every recovery checkpoint.

## Step 0: Engineering Readiness

Status: complete.

Findings:

- No current engineering blocker is known for the full downstream Flow2 path.
- TRELLIS.2 `flash_attn` blocker has been resolved by the local `sdpa` sparse attention fallback.
- The current bedroom scene graph has 18 objects.
- Reusable TRELLIS assets are complete: 18 GLB files in:
  `/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_v3_sdpa/assets_trellis2`
- Blender assembly/render was already verified by recovery outputs:
  - `scene_tree_sage_flow2.glb`
  - `render_est_front_high_recovery.png`

Remaining non-engineering risk:

- Server/session instability can interrupt foreground processes.
- Layout quality may still fail validation because the previous recovered plan had aggregate/global collision failures.

## Step 1: Launch Full Flow With Reused Assets

Status: retrying.

Output directory:

`/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_test_reuse_v1`

Strategy:

- Use current bedroom prompt, reference image, fixed scene graph, and source images.
- Reuse existing `assets_trellis2` to avoid another long TRELLIS generation pass.
- Run the main Flow2 command in the background with stdout/stderr redirected to `flow.log`, so progress survives connection drops.

Attempt 1:

- Result: failed before launch.
- Cause: the combined `mkdir && nohup ... > flow.log & echo pid > flow.pid` style command was split by the sandbox/escalation wrapper, so the PID redirection ran before the output directory was visible.
- Fix: create the output directory as a separate step, then launch the background command.

Attempt 2:

- PID file written: `2792189`.
- Result: process exited immediately.
- `flow.log` was empty.
- Likely cause: `source .env && nohup ...` is not reliable under the command escalation/splitting wrapper; the environment does not persist into the launched segment.
- Fix: launch with explicit absolute paths and literal model/URL values instead of relying on `source .env`.

Attempt 3:

- PID file written: `2798614`.
- Result: process exited immediately and `flow.log` remained empty.
- Conclusion: the background `nohup ... > flow.log 2>&1 & echo pid` launch pattern itself is unreliable under the current tool wrapper.

Attempt 4:

- Launch mode: foreground session with explicit absolute paths.
- Session id: `20984`.
- Result so far: process stayed alive for at least the initial 30 seconds, so the full Flow2 command itself can start.
- Operational caveat: this foreground session is still exposed to connection instability; progress must be checkpointed by polling output files.

## Step 2: Early Agent Progress

Status: in progress.

Checkpoint at 2026-07-05 19:55:

- `selected_prompt.txt` written.
- Input scene graph guard/sanitize reports written.
- `floor_material_sampled_texture.png` written.
- `codex_object_semantics_request.txt`, response, stdout, and stderr written.
- `codex_relation_verifier_request.txt` written.
- Process session `20984` still running.

Checkpoint at 2026-07-05 19:57:

- `codex_relation_verifier_response.txt`, stdout, and stderr written.
- `reference_instance_overlay.png` written.
- `codex_reference_instance_grounding_request.txt`, response, stdout, and stderr written.
- `codex_reference_spatial_order_request.txt` written.
- Process session `20984` still running.

Checkpoint at 2026-07-05 19:59:

- `codex_reference_spatial_order_response.txt`, stdout, and stderr written.
- `codex_pose_expectation_request.txt`, response, stdout, and stderr written.
- `codex_asset_component_policy_request.txt` written.
- Process session `20984` still running.

Checkpoint at 2026-07-05 20:01:

- `codex_asset_component_policy_response.txt`, stdout, and stderr written.
- `codex_bedside_tabletop_reference_request.txt`, response, stdout, and stderr written.
- `reference_instance_pose_grounding_topdown.png` and `reference_instance_pose_grounding_sheet.png` written.
- `codex_reference_instance_pose_grounding_request.txt`, response, stdout, and stderr written.
- `codex_branch_reference_critic_request.txt` written.
- Process session `20984` still running.

## Step 3: Planning, Layout, And Asset Reuse Checkpoint

Status: complete.

Checkpoint at 2026-07-05 20:05:

- `codex_branch_reference_critic_*` completed.
- Core planning/layout artifacts written:
  - `scene_graph.json`
  - `support_tree.json`
  - `scene_hypergraph.json`
  - `branch_execution_plan.json`
  - `incremental_branch_report.json`
  - `aggregate_collision_report.json`
  - `global_validator_report.json`
  - `scene_plan.json`
  - `preview_topdown.png`
- Asset-stage artifacts written:
  - `asset_registry.json`
  - `asset_source_report.json`
  - `asset_source_image_qa_report.json`
  - `asset_router_report.json`
- Process session `20984` still running.

Interpretation:

- The full Flow2 command reached the post-layout asset stage.
- Existing reusable assets were accepted far enough to build an asset registry.

## Step 4: Full Flow Interruption

Status: blocked by engineering/runtime issue.

Checkpoint at 2026-07-05 20:07:

- Foreground session `20984` exited with code `137`.
- No Python traceback was printed.
- `run_summary.json` was not written.
- `scene_tree_sage_flow2.glb` was not written by the native full flow.
- `assets_trellis2/` contains all 18 reused GLB files.
- `assets_trellis2_cleaned/` exists but contains no GLB files.
- Output directory currently contains 180 files.
- Validation state at the interruption point:
  - `aggregate_collision_report.json`: `ok=false`, `conflict_count=6`.
  - `global_validator_report.json`: `ok=false`, `conflict_count=9`.

Interpretation:

- The current full Flow2 implementation still has a runtime/engineering obstacle under this server profile: the process can be killed with exit code 137 after post-layout asset reports and before native final assembly/summary.
- Exit code 137 usually means external SIGKILL, commonly OOM or a resource controller kill.
- The result is recoverable because `scene_plan.json`, `asset_registry.json`, and all 18 copied reusable GLB assets are present.

Next recovery step:

- Avoid the high-memory native continuation path.
- Assemble `scene_tree_sage_flow2.glb` directly from this test output's `scene_plan.json` and `assets_trellis2/`.
- Render a recovery reference view.
- Write a recovery summary for this test output.

## Step 5: Direct Recovery Assembly

Status: complete.

Checkpoint at 2026-07-05 20:18:

- Command: Blender background run of `sage/scripts/blender_assemble_sage_scene.py`.
- Inputs:
  - `scene_plan.json`
  - `assets_trellis2/` with 18 GLB files
- Output:
  - `scene_tree_sage_flow2.glb`
- Output size: 446M.
- Result: success.

Interpretation:

- The native full flow was killed before final assembly, but the downstream assembly path itself works when run as a small isolated step.

## Step 6: Recovery Reference Render

Status: complete.

Checkpoint at 2026-07-05 20:18:

- Command: Blender background run of `sage/scripts/render_reference_view_estimate.py`.
- Inputs:
  - `scene_tree_sage_flow2.glb`
  - `scene_plan.json`
- Outputs:
  - `render_est_front_high_recovery.png`
  - `render_est_front_high_recovery.json`
- Output size: 1.6M PNG.
- Visual check: nonblank bedroom render; bed, desk/chair, wardrobe, window/curtain, wall art, nightstands, lamp, plant, mug, and rug are visible.
- Result: success.

## Step 7: Recovery Summary

Status: complete.

Checkpoint at 2026-07-05 20:18:

- Wrote `run_summary_recovery.json`.
- Native `run_summary.json` is still absent.
- Current validation state:
  - `aggregate_collision_report.json`: `ok=false`, `conflict_count=6`.
  - `global_validator_report.json`: `ok=false`, `conflict_count=9`.

Final engineering conclusion for this run:

- TRELLIS asset generation is no longer an engineering blocker.
- Asset reuse, planning, layout report generation, direct Blender assembly, and direct Blender rendering all work.
- The remaining engineering/runtime blocker for the native monolithic full flow is exit code `137` before final native assembly/summary, likely external resource kill/OOM under the current server profile.
- The current result is recoverable and inspectable, but not a clean native full-flow completion.
- Layout quality is still not passing validation because aggregate/global collision reports remain false.

## Step 8: Exit 137 Diagnosis

Status: complete.

Checkpoint at 2026-07-05:

- `flow.log` is empty, so the main process did not exit through a Python traceback path.
- The process was reported as exit code `137`, which means it received `SIGKILL`.
- `/sys/fs/cgroup/user.slice/memory.events` shows `oom_kill 44`.
- `/sys/fs/cgroup/user.slice/memory.peak` is about 262GB, close to/above the machine's 251GiB physical RAM.
- Current swap was effectively full during inspection (`SwapTotal=2.0GiB`, `SwapFree=56kB`).
- The last native full-flow artifact before the kill was `asset_router_report.json`; native `asset_cleanup_report.json`, `scene_tree_sage_flow2.glb`, and `run_summary.json` were absent.

Interpretation:

- The `137` kill is most consistent with OOM/resource-controller SIGKILL.
- The likely high-memory region is after `asset_router_report.json`, when the monolithic flow enters asset cleanup and later final rendering/refinement.
- The quality-preserving fix should not skip core stages. It should split high-memory stages into isolated subprocess/checkpointed steps, especially per-asset cleanup and downstream Blender render/refinement, so each step releases memory before the next.

## Step 5: Engineering Workaround Attempt

Status: blocked before launch.

Reason:

- The default full-flow run was killed with exit code 137 after asset reports.
- `assets_trellis2_cleaned/` stayed empty, so the next suspected high-memory stage is asset cleaning or downstream processing that follows it.

Workaround:

- Run a second full-flow attempt in a fresh output directory with the same reused assets but `--no-clean-assets`.
- This keeps the full planning/layout/render path but skips the suspected high-memory asset cleaning stage.

Output directory:

`/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_test_reuse_v2_no_clean`

Attempt:

- Command: full Flow2 with reused assets and `--no-clean-assets`.
- Result: not launched.
- Reason: sandbox-external execution request was rejected.
- Note: this workaround still needs validation when execution approval is available.

## Step 6: Recovery Assembly And Render

Status: complete.

Checkpoint at 2026-07-05 20:20:

- Direct Blender assembly succeeded from:
  - `scene_plan.json`
  - `assets_trellis2/`
- Recovery GLB:
  - `scene_tree_sage_flow2_recovery.glb`
  - Size: 446M
- Recovery render:
  - `render_est_front_high_recovery.png`
  - Size: 1.6M
- Recovery summary:
  - `run_summary_recovery.json`

Conclusion:

- Current implementation has no blocker in TRELLIS asset availability or Blender assembly/render.
- Current default full-flow execution still has an engineering/runtime blocker: exit code 137 before native final summary and scene GLB.
- The likely next engineering task is to avoid or reduce the high-memory stage after `asset_router_report.json`; the first candidate workaround is `--no-clean-assets`, but that attempt was not validated because sandbox-external execution was rejected.
- The intermediate result remains recoverable because the saved plan and all 18 assets are enough to assemble and render the scene directly.
