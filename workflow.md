# TreeSAGE Flow2 Workflow

本文档说明当前仓库代码在做什么、完整工作流是什么，以及要在当前服务器 `/data/wsj` 上跑通流程需要完成哪些 setup。

## 1. 当前代码做的事情

本仓库是 TreeSAGE Flow2 的复现包。目标是从一张 reference image、文本 prompt、可选 scene graph 和可选人工约束出发，生成一个带 3D 资产、空间布局、验证报告和最终 GLB 的室内场景。

核心入口是：

```bash
sage/scripts/run_tree_sage_scene.py
```

它做的事情可以概括为：

1. 读取输入：
   - 场景 prompt。
   - reference image，例如 `examples/bedroom_0610_113657/reference_0610_113657.png`。
   - 可选固定 scene graph，例如 `scene_graph_augmented_curtains_ceiling_raw_input.json`。
   - 可选人工约束，例如 `human_constraints_manual_bbox_v1.json`。
2. 清理和补全 scene graph：
   - 过滤或修正不适合独立建模的软装细节。
   - 标准化物体、房间、墙、支撑关系和空间关系。
   - 根据 prompt/reference 做 room size、room axis、wall affinity 等 grounding。
3. 调用 Codex/VLM JSON agents：
   - 语义检查、关系验证、reference instance grounding。
   - spatial order、pose、scale、asset component policy、fine spatial order 等视觉判断。
   - agent 调用由 `sage/scripts/tree_sage_flow2/agents/codex_runner.py` 封装，使用短生命周期 `codex exec`。
4. 构建 Flow2 布局结构：
   - `support_tree.json`：支撑树。
   - `scene_hypergraph.json`：布局/关系超图。
   - `branch_execution_plan.json`：分支处理顺序。
5. 生成或复用 3D 资产：
   - 优先读取逐物体 source images。
   - 调用本地 TRELLIS.2 bridge 生成 GLB。
   - 支持复用旧资产、参数化 fallback、component policy 修复。
6. 做场景布局和修复：
   - 分支增量布局。
   - parent packing。
   - aggregate collision repair。
   - spatial relation repair。
   - reference alignment。
   - fine spatial order refinement。
7. 做验证：
   - 几何碰撞报告。
   - MuJoCo 物理稳定性检查。
   - reference depth / view-conditioned 检查。
   - asset registry 和 component policy 检查。
8. 调用 Blender 组装并渲染：
   - 输出最终场景 GLB。
   - 输出 topdown preview、reference-vs-render 对比图、诊断图。

## 2. 代码模块分工

- `sage/scripts/run_tree_sage_scene.py`：主 orchestration 脚本，负责串起完整 Flow2。
- `sage/scripts/run_selfmade_trellis_scene.py`：资产生成、TRELLIS job polling、Blender 组装、preview 渲染等基础能力。
- `sage/scripts/tree_sage_flow2/agents/codex_runner.py`：Codex JSON agent 调用封装。
- `sage/scripts/tree_sage_flow2/reference/depth.py`：reference depth 分析。
- `sage/scripts/tree_sage_flow2/validation/mujoco.py`：MuJoCo 检查边界。
- `sage/server/trellis2_flux_bridge_server.py`：本地 TRELLIS.2 HTTP bridge，提供 `/generate`、`/job/<id>`、`/health`。
- `sage/server/flux2_klein_server.py`：可选 Flux2 Klein 服务，用于 fallback source image 生成。
- `sage/scripts/blender_*.py`：Blender 场景组装、诊断渲染、资产渲染。
- `examples/bedroom_0610_113657/`：当前可复现实验输入。
- `scripts/`：封装好的启动和复现脚本。
- `env/`：环境依赖和路径模板。

## 3. 完整工作流

### 3.1 输入准备

一次完整运行需要：

1. `prompt.txt`
2. reference image
3. 可选 scene graph
4. 可选人工约束文件
5. 每个物体对应的 source image

当前仓库内置的卧室例子是：

```text
examples/bedroom_0610_113657/
  README.md
  prompt.txt
  reference_0610_113657.png
  scene_graph_augmented_curtains_ceiling_raw_input.json
  human_constraints_manual_bbox_v1.json
  source_images_manifest.txt
```

缺失的大文件是：

```text
examples/bedroom_0610_113657/source_images/
```

完整资产复现必须把 `source_images_manifest.txt` 中列出的逐物体图片放进该目录，或设置：

```bash
export SAGE_BEDROOM_SOURCE_IMAGES="/path/to/source_images"
```

### 3.2 启动资产生成服务

Flow2 主脚本不直接加载 TRELLIS.2，而是通过本地 HTTP bridge 调用它。

推荐启动方式：

```bash
cd /data/wsj/main/scene
source .env
scripts/start_trellis2_bridge_512_no_webp.sh
```

该服务默认监听：

```text
http://127.0.0.1:8082
```

健康检查：

```bash
curl http://127.0.0.1:8082/health
```

当前默认资产生成策略：

```text
TRELLIS.2 pipeline_type=512
preprocess image
texture_size=512
decimation_target=500000
no-WebP GLB export
```

no-WebP 是重要约束，已有文档记录 WebP 纹理可能导致颜色偏移。

### 3.3 运行 planning smoke test

先跑不生成资产的最小路径：

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_plan_only_smoke"
scripts/run_bedroom_0610_113657_plan_only_smoke.sh
```

该脚本实际调用：

```bash
python sage/scripts/run_tree_sage_scene.py \
  --prompt-file examples/bedroom_0610_113657/prompt.txt \
  --flux-image examples/bedroom_0610_113657/reference_0610_113657.png \
  --pose-reference-image examples/bedroom_0610_113657/reference_0610_113657.png \
  --scene-graph-file examples/bedroom_0610_113657/scene_graph_augmented_curtains_ceiling_raw_input.json \
  --output-dir "$SAGE_OUTPUT_DIR" \
  --model "${SAGE_CODEX_MODEL:-gpt-5.6-sol}" \
  --no-reference-depth \
  --no-mujoco-check \
  --skip-asset-renders \
  --plan-only
```

期望输出：

```text
$SAGE_OUTPUT_DIR/
  initial_scene_graph_raw.json
  scene_graph.json
  support_tree.json
  scene_hypergraph.json
  branch_execution_plan.json
  scene_plan.json
  run_summary.json
```

注意：plan-only 仍可能调用 Codex JSON agents，因此需要 `codex` CLI 可用，并且支持 image input。

### 3.4 运行完整无人工约束复现

确认 source images 和 TRELLIS.2 bridge 都可用后运行：

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_0610_113657_no_manual"
scripts/run_bedroom_0610_113657_no_manual.sh
```

该流程会：

1. 读取卧室 prompt/reference/scene graph。
2. 读取逐物体 source images。
3. 通过 TRELLIS.2 bridge 生成每个物体 GLB。
4. 构建 support tree 和分支布局。
5. 做空间关系、pose、scale、collision、MuJoCo 等检查。
6. 调用 Blender 输出最终场景。

关键输出：

```text
$SAGE_OUTPUT_DIR/
  scene_tree_sage_flow2.glb
  scene_plan.json
  asset_registry.json
  preview_topdown.png
  reference_vs_render_est_front_high_fine_spatial_order.png
  fine_spatial_order_report.json
  mujoco_check.json
  run_summary.json
```

### 3.5 运行带人工约束复现

如果要使用人工 bbox projection overlap 约束：

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_0610_113657_manual"
scripts/run_bedroom_0610_113657_manual.sh
```

相对无人工约束版，它额外传入：

```bash
--human-constraints-file examples/bedroom_0610_113657/human_constraints_manual_bbox_v1.json
```

### 3.6 复用资产或只调布局

如果已有一轮合格资产，后续可以用主入口参数减少重复计算：

```bash
python sage/scripts/run_tree_sage_scene.py \
  ... \
  --reuse-asset-dir "/path/to/previous/assets" \
  --reuse-asset-alias-file sage/config/reuse_alias_img0610_113657_current.json
```

如果只需要检查布局逻辑：

```bash
python sage/scripts/run_tree_sage_scene.py \
  ... \
  --plan-only \
  --no-reference-depth \
  --no-mujoco-check \
  --skip-asset-renders
```

## 4. 当前服务器 setup

以下 setup 以当前服务器路径 `/data/wsj/main/scene` 为准。仓库内文档和脚本有不少 `/data/xy/...`、`/home/xy/...` 示例路径，必须改成本机真实路径。

### 4.1 代码和目录

当前代码目录：

```bash
cd /data/wsj/main/scene
```

建议把运行输出放到仓库外或单独目录：

```bash
mkdir -p /data/wsj/main/scene_runs
mkdir -p /data/wsj/main/scene_runtime/trellis2_bridge
mkdir -p /data/wsj/main/scene_runtime/flux2_images
mkdir -p /data/wsj/main/scene_runtime/hf
```

不要把模型权重、运行输出、GLB 资产批量提交到 Git。

### 4.2 Orchestration Python 环境

推荐 conda：

```bash
cd /data/wsj/main/scene
conda env create -f env/conda_orchestrator.yml
conda activate tree-sage-flow2
```

如果使用已有 Python 3.10 环境：

```bash
cd /data/wsj/main/scene
python -m pip install -r env/orchestrator_requirements.txt
```

需要的主要包：

```text
numpy
pillow
trimesh
scipy
shapely
requests
opencv-python
matplotlib
transformers
torch
torchvision
mujoco==3.3.4
```

### 4.3 TRELLIS.2 环境

TRELLIS.2 建议使用它自己的官方环境，然后补齐：

```bash
cd /data/wsj/main/scene
python -m pip install -r env/trellis2_bridge_requirements.txt
```

必须准备：

- 本地 TRELLIS.2 源码目录。
- 本地 `trellis2_primary` 权重目录。
- 本地 RMBG-2.0 权重目录。
- 包含 RMBG custom module 的 Hugging Face module cache。
- CUDA/PyTorch 与当前机器驱动匹配。
- NVIDIA GPU；512 pipeline 相对省显存，但完整资产生成仍建议有较大显存。

### 4.4 Blender

需要 Blender 4.3.2 或兼容版本。设置：

```bash
export SAGE_BLENDER_BIN="/path/to/blender"
```

验证：

```bash
"$SAGE_BLENDER_BIN" --version
```

### 4.5 Codex CLI

Flow2 的多个 JSON agents 依赖 `codex exec`，并且需要 image input 支持。

验证：

```bash
which codex
codex --version
```

主脚本中使用的 agent runner 会执行类似：

```bash
codex exec \
  --ignore-user-config \
  --ignore-rules \
  --disable plugins \
  --disable plugin_sharing \
  --disable plugin_hooks \
  --ephemeral \
  --sandbox read-only \
  --image /path/to/reference.png \
  -- ...
```

因此不要依赖用户本地 Codex rules 或插件来补齐主流程行为。

### 4.6 `.env` 配置

创建本地配置：

```bash
cd /data/wsj/main/scene
cp env/paths.example.env .env
```

建议在当前服务器改成类似形状：

```bash
export SAGE_ROOT="/data/wsj/main/scene"
export SAGE_DATA_ROOT="/data/wsj/main/scene_runs"

export SAGE_ORCH_PYTHON="/path/to/orchestration/python"
export SAGE_TRELLIS_PYTHON="/path/to/trellis2/python"
export SAGE_REFERENCE_DEPTH_PY="/path/to/reference_depth/python"
export SAGE_FLOW2_MUJOCO_PY="/path/to/mujoco/python"
export SAGE_FLUX2_PYTHON="/path/to/flux2/python"

export SAGE_BLENDER_BIN="/path/to/blender"

export SAGE_TRELLIS_REPO="/path/to/TRELLIS.2"
export SAGE_TRELLIS_MODEL="/path/to/trellis2_primary"
export SAGE_TRELLIS_OUTPUT_DIR="/data/wsj/main/scene_runtime/trellis2_bridge"
export SAGE_TRELLIS_URL="http://127.0.0.1:8082"
export SAGE_TRELLIS_HOST="127.0.0.1"
export SAGE_TRELLIS_PORT="8082"

export SAGE_RMBG_MODEL="/path/to/rmbg_2_0"
export SAGE_RMBG_MODULE_ROOT="/path/to/hf_home/modules"

export SAGE_REFERENCE_DEPTH_MODEL="/path/to/depth__large_relative"

export SAGE_FLUX2_MODEL="/path/to/FLUX.2-klein-9B"
export SAGE_FLUX2_OUTPUT_DIR="/data/wsj/main/scene_runtime/flux2_images"

export SAGE_CODEX_MODEL="gpt-5.6-sol"
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_0610_113657_no_manual"
```

最小 plan-only smoke 可以先只配置：

```bash
export SAGE_ROOT="/data/wsj/main/scene"
export SAGE_DATA_ROOT="/data/wsj/main/scene_runs"
export SAGE_ORCH_PYTHON="python"
export SAGE_CODEX_MODEL="gpt-5.6-sol"
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_plan_only_smoke"
```

完整资产生成必须补齐 TRELLIS.2、RMBG、Blender 等路径。

### 4.7 Source images

完整卧室复现要求：

```text
examples/bedroom_0610_113657/source_images/
```

如果已有 source image 目录：

```bash
cd /data/wsj/main/scene
export SAGE_BEDROOM_SOURCE_IMAGES="/path/to/source_images"
```

或复制到默认位置：

```bash
cd /data/wsj/main/scene
mkdir -p examples/bedroom_0610_113657/source_images
rsync -a /path/to/source_images/ examples/bedroom_0610_113657/source_images/
```

核对文件名：

```bash
cd /data/wsj/main/scene
while read -r f; do test -f "examples/bedroom_0610_113657/source_images/$f" || echo "missing $f"; done < examples/bedroom_0610_113657/source_images_manifest.txt
```

### 4.8 可选 Flux2 setup

如果没有逐物体 source images，或需要 fallback 生成 source images，可以启动 Flux2：

```bash
cd /data/wsj/main/scene
source .env
scripts/start_flux2_klein.sh
```

默认监听：

```text
http://127.0.0.1:8084
```

需要：

```bash
export SAGE_FLUX2_MODEL="/path/to/FLUX.2-klein-9B"
export SAGE_FLUX2_OUTPUT_DIR="/data/wsj/main/scene_runtime/flux2_images"
```

当前最佳复现路径仍是使用已检查过的 image2 source images，而不是临场 fallback 生成。

## 5. 推荐落地顺序

### Step 1: 基础检查

```bash
cd /data/wsj/main/scene
git status --short --branch
python --version
which codex
codex --version
```

### Step 2: 建 orchestration 环境

```bash
cd /data/wsj/main/scene
conda env create -f env/conda_orchestrator.yml
conda activate tree-sage-flow2
```

### Step 3: 写 `.env`

```bash
cd /data/wsj/main/scene
cp env/paths.example.env .env
```

把所有 `/data/xy/...`、`/home/xy/...` 替换成本机真实路径。

### Step 4: 跑 plan-only smoke

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_plan_only_smoke"
scripts/run_bedroom_0610_113657_plan_only_smoke.sh
```

如果失败，优先看：

```text
$SAGE_OUTPUT_DIR/run_summary.json
$SAGE_OUTPUT_DIR/*stderr*
$SAGE_OUTPUT_DIR/*agent*
```

### Step 5: 准备 source images

```bash
cd /data/wsj/main/scene
mkdir -p examples/bedroom_0610_113657/source_images
rsync -a /path/to/source_images/ examples/bedroom_0610_113657/source_images/
```

### Step 6: 启动 TRELLIS.2 bridge

在单独终端：

```bash
cd /data/wsj/main/scene
source .env
scripts/start_trellis2_bridge_512_no_webp.sh
```

检查：

```bash
curl http://127.0.0.1:8082/health
```

### Step 7: 跑完整无人工约束版

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_0610_113657_no_manual"
scripts/run_bedroom_0610_113657_no_manual.sh
```

### Step 8: 跑人工约束版

```bash
cd /data/wsj/main/scene
source .env
export SAGE_OUTPUT_DIR="/data/wsj/main/scene_runs/bedroom_0610_113657_manual"
scripts/run_bedroom_0610_113657_manual.sh
```

## 6. 关键输出如何看

- `run_summary.json`：先看这个，判断整体是否完成、关键报告路径、fine spatial order 是否 accepted。
- `scene_plan.json`：最终布局计划，包含物体尺寸、位置、朝向和支撑关系。
- `asset_registry.json`：资产生成/复用状态、资产路径、失败 ID。
- `asset_source_image_qa_report.json`：source image 质量检查。
- `fine_spatial_order_report.json`：细粒度空间顺序修复是否接受，以及未解决约束。
- `aggregate_collision_report.json`：碰撞问题。
- `mujoco_check.json`：物理稳定性。
- `preview_topdown.png`：俯视布局快速检查。
- `reference_vs_render_*.png`：reference 和渲染对比。
- `scene_tree_sage_flow2.glb`：最终 3D 场景。

## 7. 当前已知风险

- 仓库不包含模型权重、source images、大体积资产或历史输出。
- 默认路径仍带有原机器示例路径，必须本地化。
- plan-only 也可能依赖 Codex CLI agent；不是纯本地无模型脚本。
- 完整资产生成依赖 GPU、TRELLIS.2、RMBG、Blender、MuJoCo/reference depth 等多环境协作。
- source image 质量会直接影响 TRELLIS.2 资产质量；运行前应检查物体是否正确、背景是否干净、颜色是否接近 reference。
- TRELLIS.2 bridge 当前推荐 no-WebP GLB；不要随意去掉 `--no-glb-webp`。

## 8. 最小成功标准

当前服务器上实现流程可分三档：

1. Planning smoke 成功：
   - `scripts/run_bedroom_0610_113657_plan_only_smoke.sh` 完成。
   - 输出 `scene_plan.json` 和 `run_summary.json`。
2. 资产生成链路成功：
   - TRELLIS.2 bridge `/health` 正常。
   - 至少一个 source image 能经 `/generate` 生成 GLB。
   - `asset_registry.json` 中关键物体资产存在。
3. 完整复现成功：
   - manual 或 no-manual 脚本完成。
   - 输出 `scene_tree_sage_flow2.glb`。
   - 输出 `preview_topdown.png` 和 reference-vs-render 图。
   - `run_summary.json` 无关键失败项。
