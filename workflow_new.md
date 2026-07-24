# Scene 手动排查流程：定位 Flow2 资源峰值/exit 137

本文档记录 `bedroom_21_08_44` 当前完整 Flow2 复现的手动测试命令清单。目标是在服务器或 VSCode 连接异常断开后，可以快速恢复上下文并重新执行分段测试，定位究竟是哪一步触发内存峰值、资源控制器 kill 或 `exit code 137`。

建议在 `tmux` 或 `screen` 中执行长命令，避免 VSCode/SSH 连接断开导致终端会话丢失。

## 0. 使用 tmux 保持长任务

新建会话：

```bash
tmux new -s scene_debug
```

临时离开但不终止任务：

```text
Ctrl+b
d
```

重新连接会话：

```bash
tmux attach -t scene_debug
```

查看已有会话：

```bash
tmux ls
```

结束会话：

```bash
exit
```

如果机器没有 `tmux`，可用 `screen`：

```bash
screen -S scene_debug
screen -r scene_debug
```

## 1. 基础环境

```bash
cd /data/wsj/main/scene
source .env

export EX=/data/wsj/main/scene/examples/bedroom_21_08_44
export BASE=/data/wsj/main/scene_runs/tree_sage_flow2
export PREV=/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_v3_sdpa
export OUT=$BASE/bedroom_21_08_44_manual_debug_v1

mkdir -p "$OUT"
```

检查关键环境变量和 orchestrator 依赖：

```bash
printf 'PY=%s\nMODEL=%s\nTRELLIS=%s\nBLENDER=%s\n' \
  "$SAGE_ORCH_PYTHON" "$SAGE_CODEX_MODEL" "$SAGE_TRELLIS_URL" "$SAGE_BLENDER_BIN"

"$SAGE_ORCH_PYTHON" -c 'import trimesh, numpy, PIL, shapely, requests, mujoco; print("orchestrator deps OK")'
```

## 2. 启动 TRELLIS.2 bridge

另开一个终端，建议同样放在 tmux 里：

```bash
cd /data/wsj/main/scene
source .env
scripts/start_trellis2_bridge_512_no_webp.sh
```

健康检查：

```bash
curl -sS --max-time 10 "$SAGE_TRELLIS_URL/health"
```

预期返回中应包含 `healthy`、`gpu_available=true` 等字段。

## 3. 开系统监控终端

另开一个终端执行：

```bash
watch -n 2 'date; free -h; ps -eo pid,ppid,rss,vsz,pmem,pcpu,comm,args --sort=-rss | head -25; nvidia-smi'
```

如果某一步被杀或服务器断连，重新连接后检查 OOM 记录：

```bash
dmesg -T | grep -iE 'out of memory|oom|killed process' | tail -80
```

如果需要 sudo：

```bash
sudo dmesg -T | grep -iE 'out of memory|oom|killed process' | tail -80
```

## 4. plan-only：确认 planning 主链路

该步骤不生成资产、不跑 MuJoCo、不跑最终渲染。用于确认 agent、planning、scene graph 主链路是否能通过。

```bash
set -o pipefail

/usr/bin/time -v "$SAGE_ORCH_PYTHON" sage/scripts/run_tree_sage_scene.py \
  --prompt-file "$EX/prompt.txt" \
  --flux-image "$EX/bedroom_21_08_44.png" \
  --pose-reference-image "$EX/bedroom_21_08_44.png" \
  --scene-graph-file "$EX/scene_graph_auto_v1.json" \
  --output-dir "$OUT" \
  --model "${SAGE_CODEX_MODEL:-gpt-5.6-sol}" \
  --no-reference-depth \
  --no-mujoco-check \
  --skip-asset-renders \
  --plan-only \
  2>&1 | tee "$OUT/01_plan_only.log"
```

查看输出：

```bash
find "$OUT" -maxdepth 1 -type f | sort
```

## 5. 单独测试 Blender 组装

该步骤复用已有 18 个 TRELLIS GLB，不走完整主流程。

```bash
/usr/bin/time -v "$SAGE_BLENDER_BIN" --background \
  --python sage/scripts/blender_assemble_sage_scene.py -- \
  --plan "$PREV/scene_plan.json" \
  --asset-dir "$PREV/assets_trellis2" \
  --output-glb "$OUT/scene_tree_sage_flow2_assembly_test.glb" \
  2>&1 | tee "$OUT/02_blender_assembly.log"
```

若该步骤通过，说明 Blender 最小组装能力不是主要阻塞。

## 6. 单独测试 Blender 渲染

```bash
/usr/bin/time -v "$SAGE_BLENDER_BIN" --background \
  --python sage/scripts/render_reference_view_estimate.py -- \
  --scene-glb "$OUT/scene_tree_sage_flow2_assembly_test.glb" \
  --plan "$PREV/scene_plan.json" \
  --output "$OUT/render_est_front_high_test.png" \
  --camera front_high \
  --resolution-x 1600 \
  --resolution-y 900 \
  2>&1 | tee "$OUT/03_blender_render.log"
```

若该步骤通过，说明 Blender 组装与渲染单步均可用。

## 7. 单独测试 asset cleanup

这是当前最值得单独验证的疑似高内存步骤之一。该命令把资产清理从 monolithic Flow2 中拆出来单独执行。

```bash
/usr/bin/time -v "$SAGE_ORCH_PYTHON" sage/scripts/preclean_tree_sage_assets.py \
  --plan "$PREV/scene_plan.json" \
  --source-dir "$PREV/assets_trellis2" \
  --output-dir "$OUT/assets_trellis2_cleaned_test" \
  --report "$OUT/asset_cleanup_report_test.json" \
  --trellis-url "${SAGE_TRELLIS_URL:-http://127.0.0.1:8082}" \
  --asset-source-image-dir "$EX/source_images" \
  --asset-source-image-required \
  --texture-size 512 \
  --decimation-target 500000 \
  --steps 12 \
  --seed 1700 \
  2>&1 | tee "$OUT/04_preclean_assets.log"
```

如果该步骤出现 `exit code 137`、服务器断连、或 `dmesg` 中出现 OOM/killed process 记录，基本可以锁定 asset cleanup/mesh 处理阶段是主要资源峰值来源。

2026-07-06 手动观察记录：

- `01_plan_only` 已通过并写出 `run_summary.json`。
- `02_blender_assembly` 已通过，`Maximum resident set size` 约 `6175308 KB`，输出 `scene_tree_sage_flow2_assembly_test.glb`。
- `03_blender_render` 已通过，`Maximum resident set size` 约 `6499592 KB`，输出 `render_est_front_high_test.png`。
- `04_preclean_assets` 启动后，用户在 `watch free -h` 中观察到 free memory 快速下降，接近低于 10GB 前主动终止。
- 终止后检查：`04_preclean_assets.log` 为 0 字节，`asset_cleanup_report_test.json` 未写出，`assets_trellis2_cleaned_test/` 下无 cleaned GLB，仅有 `_cleanup_worker/objects/wooden_bed.json`。
- 结论：该次内存快速下降发生在第一个 cleanup worker `wooden_bed` 刚启动后，尚未进入多对象累积阶段；当前最可疑的资源峰值点是 `trimesh` 资产清理 worker 内部的 mesh load/split/copy/export 流程。

## 8. 完整流程，但跳过 asset cleanup

该步骤用于验证 `--no-clean-assets` 是否能绕过当前资源峰值。

```bash
export OUT_NO_CLEAN=$BASE/bedroom_21_08_44_manual_debug_no_clean_v1
mkdir -p "$OUT_NO_CLEAN"

set -o pipefail

/usr/bin/time -v "$SAGE_ORCH_PYTHON" sage/scripts/run_tree_sage_scene.py \
  --prompt-file "$EX/prompt.txt" \
  --flux-image "$EX/bedroom_21_08_44.png" \
  --pose-reference-image "$EX/bedroom_21_08_44.png" \
  --scene-graph-file "$EX/scene_graph_auto_v1.json" \
  --output-dir "$OUT_NO_CLEAN" \
  --trellis-url "${SAGE_TRELLIS_URL:-http://127.0.0.1:8082}" \
  --trellis-pipeline-type 512 \
  --trellis-preprocess-image \
  --reuse-asset-dir "$PREV/assets_trellis2" \
  --asset-source-image-dir "$EX/source_images" \
  --asset-source-image-required \
  --texture-size 512 \
  --decimation-target 500000 \
  --steps 12 \
  --seed 1700 \
  --blender-bin "$SAGE_BLENDER_BIN" \
  --mujoco-python "$SAGE_ORCH_PYTHON" \
  --model "${SAGE_CODEX_MODEL:-gpt-5.6-sol}" \
  --no-clean-assets \
  2>&1 | tee "$OUT_NO_CLEAN/full_no_clean.log"
```

如果该步骤能通过，但默认完整流程失败，说明默认 asset cleanup 很可能是主因。

2026-07-06 手动验证结果：

- `bedroom_21_08_44_manual_debug_no_clean_v1` 使用 `--no-clean-assets` 完整流程成功结束，`Exit status: 0`。
- 总耗时 `24:20.20`，`Maximum resident set size` 为 `6577352 KB`，约 `6.3 GB`。
- 已写出原生完整流程产物：
  - `run_summary.json`
  - `scene_tree_sage_flow2.glb`，约 `466843280` bytes
  - `preview_topdown.png`
  - 多张 `render_est_front_high_*.png`
- `run_summary.json` 中 `plan_only=false`、`scene_graph_object_count=18`、`plan_object_count=18`、`asset_registry_ok=true`。
- 质量状态仍未通过：`mujoco_ok=false`、`aggregate_collision_ok=false`、`global_validator_ok=false`、`scene_hypergraph_validation_ok=false`，`fine_spatial_order_accepted=false/rejected_collision_or_physics_regression`。
- 结论：monolithic full Flow2 本身在跳过 asset cleanup 后可稳定跑通；此前 `exit code 137` 的主要工程阻塞可以归因到 asset cleanup 资源峰值，而非 planning、Blender assembly/render 或完整主流程后段不可执行。

## 9. 默认完整流程

该步骤最可能复现 `exit code 137`。建议只在前面分段测试已有日志后再执行。

```bash
export OUT_FULL=$BASE/bedroom_21_08_44_manual_debug_full_clean_v1
mkdir -p "$OUT_FULL"

set -o pipefail

/usr/bin/time -v "$SAGE_ORCH_PYTHON" sage/scripts/run_tree_sage_scene.py \
  --prompt-file "$EX/prompt.txt" \
  --flux-image "$EX/bedroom_21_08_44.png" \
  --pose-reference-image "$EX/bedroom_21_08_44.png" \
  --scene-graph-file "$EX/scene_graph_auto_v1.json" \
  --output-dir "$OUT_FULL" \
  --trellis-url "${SAGE_TRELLIS_URL:-http://127.0.0.1:8082}" \
  --trellis-pipeline-type 512 \
  --trellis-preprocess-image \
  --reuse-asset-dir "$PREV/assets_trellis2" \
  --asset-source-image-dir "$EX/source_images" \
  --asset-source-image-required \
  --texture-size 512 \
  --decimation-target 500000 \
  --steps 12 \
  --seed 1700 \
  --blender-bin "$SAGE_BLENDER_BIN" \
  --mujoco-python "$SAGE_ORCH_PYTHON" \
  --model "${SAGE_CODEX_MODEL:-gpt-5.6-sol}" \
  2>&1 | tee "$OUT_FULL/full_clean.log"
```

## 10. 判断标准

- `03_blender_render` 能通过：Blender 组装/渲染单步不是主要阻塞。
- `04_preclean_assets` 被 kill：高概率是 asset cleanup 内存峰值。
- `08 full_no_clean` 能通过但 `09 full_clean` 失败：基本确认 cleanup 是主因。
- `08 full_no_clean` 也失败，但 `05/06/07` 单步都通过：问题更像 monolithic 主流程后段没有及时释放内存，或 final feedback/summary 阶段累计占用过高。
- 任意步骤出现 `exit code 137`：马上检查 `dmesg`。如果有 `Killed process ... python`、`Out of memory` 或 OOM 相关记录，即可确认是 OOM/资源控制层面的 kill。

## 11. 当前已知上下文

- 现有可恢复输出目录：

```bash
/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_v3_sdpa
```

- 已有 18 个 TRELLIS GLB：

```bash
/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_v3_sdpa/assets_trellis2
```

- 已有 plan：

```bash
/data/wsj/main/scene_runs/tree_sage_flow2/bedroom_21_08_44_full_no_manual_v3_sdpa/scene_plan.json
```

- 当前核心疑点：
  - 默认完整 Flow2 在 `asset_router_report.json` 后、原生最终 GLB/`run_summary.json` 前以 `exit code 137` 被 kill。
  - 更像资源峰值或外部资源控制器 kill，不像 TRELLIS、资产生成或 Blender 单步能力失败。
  - `--no-clean-assets` 是尚待验证的重要 workaround。
