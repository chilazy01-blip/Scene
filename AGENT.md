# Scene 当前接续断点

最后更新：2026-07-23

本文档只保留恢复工作所需的当前结论。不要继续追加逐次终端流水；新结论应替换已过期内容。

## 1. 当前唯一优先目标

当前研究与实现统一围绕独立 V2 实验目录：

```text
sage/experiments/codex_trellis_scene_v2
```

当前路线是：

```text
文本 Prompt
  -> 结构化 SceneBrief
  -> 门窗墙地板建筑层
  -> 类型化场景图（唯一父节点树 + 补充关系图）
  -> 审核资产优先复用，Flux + TRELLIS.2 只补缺口
  -> Codex 或规则布局
  -> 构图、碰撞、通道与功能朝向验证/修复
  -> 可选 Blender 装配与渲染
```

`sage/scripts/run_codex_prompt_scene.py` 保留为旧的单次 Codex 文本布局基线，不再承载当前场景图、组合组件和后续 relation-aware SDF 的实现。`run_tree_sage_text_scene.py`、`run_selfmade_trellis_scene.py`、`run_tree_sage_scene.py` 也不是当前改动入口，避免把 V2 结论误写回旧主链。

## 2. V2 Codex 路径的测试判据

模型统一使用当前账号已验证可用的标识：

```text
gpt-5.6-sol
```

测试必须添加：

```text
--no-fallback-if-codex-fails
```

否则 Codex 失败时脚本会改用固定 `fallback_plan`，造成“看似成功但没有使用 GPT”。

成功判据：

- 进程退出码为 0。
- `codex_response.txt` 存在且 JSON 可解析。
- `codex_plan.json` 中 `_planner == "codex_exec"`。
- `run_summary.json` 中 `planner == "codex_exec"`。
- 生成 layout JSON、GLB、`preview_topdown.png` 和 `mujoco_check.json`。
- `run_summary.json` 中 `mujoco_ok == true`，且 `mujoco_unstable_objects` 为空。

重点评价：

- Prompt 对象覆盖率与资产选择合理性。
- 房间尺寸、物体 `x/y/rotation_z` 的合理性。
- 越界、碰撞、桌椅朝向、靠墙关系和通道空间。
- 不同 Prompt 和不同运行之间的稳定性。
- Codex 延迟、失败率和 fallback 是否被触发。

## 3. 单次 Codex 链的本机路径状态

`run_codex_prompt_scene.py` 中原有的 `/data/xy/...` 和 `/home/xy/...` 硬编码已移除。现在支持：

- `--source-scene` / `SAGE_CODEX_SOURCE_SCENE`
- `--source-layout` / `SAGE_CODEX_SOURCE_LAYOUT`；未指定时自动查找 source scene 内唯一的 `layout*.json`
- `--output-dir` / `SAGE_CODEX_OUTPUT_DIR`
- `--export-script` / `SAGE_CODEX_EXPORT_SCRIPT`
- `--export-python` / `SAGE_CODEX_EXPORT_PYTHON`
- `--preview-script` / `SAGE_CODEX_PREVIEW_SCRIPT`
- `--preview-python` / `SAGE_CODEX_PREVIEW_PYTHON`
- `--mujoco-python` / `SAGE_CODEX_MUJOCO_PYTHON`
- `--mujoco-server-root` / `SAGE_CODEX_MUJOCO_SERVER_ROOT`

本机默认值已确定：

```text
source scene:
  /data/wsj/main/scene_data/SAGE-10k/scenes/20251215_175349_layout_d990801a
source layout:
  /data/wsj/main/scene_data/SAGE-10k/scenes/20251215_175349_layout_d990801a/layout_d990801a.json
output_dir:
  /data/wsj/main/scene_runs/codex_prompt_scene
export script:
  /data/wsj/main/scene_data/SAGE-10k/kits/export_glb.py
export Python:
  /data/wsj/anaconda3/envs/simgen/bin/python
preview/mujoco Python:
  /data/wsj/anaconda3/envs/tree-sage-flow2/bin/python
preview script:
  /data/wsj/main/scene/sage/scripts/render_layout_topdown.py
MuJoCo server root:
  /data/wsj/main/scene/sage/server
```

脚本会在清理或创建 output directory 之前检查 source scene、source layout、`objects/`、`materials/`、export script 和各 Python 路径。

已从官方 `nvidia/SAGE-10k` Hugging Face 数据集只下载原脚本使用的单场景 `20251215_175349_layout_d990801a.zip` 和 `kits/`，没有下载 870GB 完整数据集。校验结果：

- ZIP 完整，解压后有 layout JSON、`objects/`、`materials/` 和 preview。
- layout 含 1 个房间、27 个对象，覆盖 `desk/chair/shelf/cabinet/printer/router` 六类。
- 所有对象 `source_id` 对应的 PLY 均存在。
- 官方 exporter 在 `tree-sage-flow2` 环境缺少 `xatlas/pygltflib/plyfile`；本机已有 `simgen` 环境具备完整依赖，因此 export Python 固定使用 `simgen`。
- 已实际导出 55MB 的 `layout_d990801a.glb`；`trimesh` 可加载且包含 35 个 geometry；顶视图也生成成功。
- 上述路径已写入本机 `.env`。

官方 `NVlabs/sage` 已 shallow sparse clone 到忽略目录 `external/SAGE`，commit 为文档记录的 `fe3966013a495dc1642710de93a83ddf66e534a0`。官方 `server/isaacsim/isaac_mcp/server.py` 只支持 Isaac Sim socket，且导入当前环境没有的 `mcp` 包，不含本地 MuJoCo backend。

当前仓库已新增轻量兼容层：

```text
sage/server/isaacsim/isaac_mcp/server.py
sage/server/isaacsim/isaac_mcp/local_mujoco_backend.py
```

该兼容层保持 `create_single_room_layout_scene_from_room()` 和 `simulate_the_scene()` 调用形状，使用真实 MuJoCo 对房间、墙和对象 axis-aligned box proxy 做重力、碰撞和位移检查；它用于快速物理 sanity check，不替代最终 Isaac Sim 验证。稳定落地物体和悬空不稳定物体两个单测均通过，官方 27 对象 source scene 的独立 smoke 也通过，最大位移为 `0.00004m`。

第一次完整 Codex smoke 虽退出码为 0，但 Codex 使用房间中心为原点输出负坐标，旧 clamp 将对象挤到左下边界；MuJoCo 正确报告 9 个对象全部不稳定。已修复：

- prompt 明确 `(0,0)` 为西南角，禁止 centered/negative 坐标。
- clamp 会识别 centered-origin 输出并平移到西南角坐标系。
- 90/270 度旋转时交换 footprint width/length 后再做边界裁剪。
- MuJoCo report 和 `run_summary.json` 现在写出结构化 `mujoco_ok` 与 `mujoco_unstable_objects`。

修复后的完整 smoke：

```text
/data/wsj/main/scene_runs/codex_prompt_scene/smoke_20260717_gpt56sol_v2
```

结果：退出码 0，Codex response JSON 可解析，plan 与 summary 均为 `planner=codex_exec`，10 个对象无明显重叠，GLB 约 22.8MB 且含 18 个 geometry，MuJoCo `ok=true`、无 unstable object、最大位移 `0.00004m`。

当前命令形态：

```bash
cd /data/wsj/main/scene
source .env

cmd=(
  /data/wsj/anaconda3/envs/tree-sage-flow2/bin/python
  sage/scripts/run_codex_prompt_scene.py
  --prompt-file /path/to/prompt.txt
  --model "${SAGE_CODEX_MODEL:-gpt-5.6-sol}"
  --output-dir /data/wsj/main/scene_runs/codex_prompt_scene/example_run
  --no-fallback-if-codex-fails
)
"${cmd[@]}"
```

## 4. GPT 模型配置状态

当前运行时代码的 GPT/Codex 默认模型已统一为 `gpt-5.6-sol`：

- Flow2 主入口和共享 `codex_runner.py`
- WebUI 图生任务
- `run_codex_prompt_scene.py`
- `run_selfmade_trellis_scene.py`
- `run_codex_vlm_closed_loop_scene.py`
- 可选 Articraft worker
- `.env`、`env/paths.example.env` 和 bedroom 运行脚本

所有入口仍允许用 `SAGE_CODEX_MODEL` 或 `--model` 显式覆盖。

验证结果：

- 当前账号拒绝 `gpt-5` 和 `gpt-5.6`，但 `gpt-5.6-sol` 已真实返回正确 JSON。
- 相关 Python 文件编译通过。
- `tree-sage-flow2` 环境下 8 个尺寸/布局 guard unittest 通过。
- 可执行代码扫描未发现旧 GPT 默认模型。

历史记录中出现的 `gpt-5`、`gpt-5.5` 是旧实验事实，不代表当前配置。

## 5. Web 文生 MVP 的实际状态

Web 页面显示的资产链：

```text
风格规格 -> image2 单物体图 -> QA -> TRELLIS.2 -> 纹理 -> Blender
```

对应的是 `run_tree_sage_text_scene.py` 的 `generate_from_scratch/source_images` 分支，不是单次 Codex 文本布局链。

真实情况：

- 后台只生成 `text_scene_asset_style_spec.json` 和 `text_scene_image2_generation_plan.json`。
- 后台不会自动生成 image2 单物体图；图片必须由 Codex 对话侧或外部工具提前放入 `source_images`。
- 图片准备好后，后台才继续 QA -> TRELLIS.2 -> Blender。
- 该链的 layout 仍是固定模板，不应拿来测试 GPT-5.6 文本布局能力。

## 6. 图生 Flow2 遗留状态

图生主入口 `run_tree_sage_scene.py` 会使用 GPT/Codex 处理 scene graph、semantics、relations、reference grounding、spatial order、pose、asset policy、bedside/reference pose 和 branch critic。

最近 GPT-5.6 plan-only 结果：

```text
/data/wsj/main/scene_runs/webui/runs/gpt56_perf_r1_1784261912-b608a0ca
```

对应任务：

```text
/data/wsj/main/scene_runs/webui/jobs/1784261912-b608a0ca.json
```

该任务使用 `--model gpt-5.6-sol --plan-only --no-final-visual-critic-agent`，成功写出 10 组 Codex response。

工程结论：

- `--no-clean-assets` 的完整 Flow2 已成功跑通。
- 默认 asset cleanup 曾在首个资产附近快速增大内存并触发 exit 137；主要工程风险仍是 cleanup 资源峰值。
- 当前图生质量仍有 support、wall fixture、collision、branch execution 和 bbox/reference grounding 问题。
- 本地 `run_tree_sage_scene.py` 有未提交的尺寸、wall affinity、support surface 和布局修复；不要覆盖或 reset。
- `tree_sage_text/layout.py` 与上游一致，没有本地修改。

如果未来恢复图生调试，优先阅读：

- `workflow_new.md`
- `optimize.md`
- `protect.md`
- `tests/test_dimension_estimation_guards.py`

## 7. Codex + TRELLIS.2 V2 资产库状态

旧图生 Flow2 资产已通过独立 V2 工具纳入可复用库，没有修改旧运行产物：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1
```

关键入口和产物：

```text
promotion script:
  sage/experiments/codex_trellis_scene_v2/curate_legacy_assets.py
Blender optimizer:
  sage/experiments/codex_trellis_scene_v2/blender_optimize_asset_library.py
manifest:
  /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/manifest.json
promotion report:
  /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/reports/promotion_report.json
visual QA sheet:
  /data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/reports/turntable_contact_sheet.png
```

当前结论：

- 17 个旧 TRELLIS GLB 已保留 raw 副本并生成减面 optimized 版本。
- 原 `area_rug.glb` 的多层白色残片无法安全修复，已放入 `quarantine/`；manifest 使用新的 12 面参数化薄地毯。
- 第二个双抽屉柜同时注册为原型 `dresser` 派生条目；白色极简门完成入库后，manifest 当前共 20 个 approved 条目、18 个类别。
- 桌子、拖鞋等错误尺寸已更正；床、柜、桌、椅及单面墙面资产已记录 canonical front 和使用约束。
- V2 资产解析现在会继承尺寸、轴向、局部 yaw、canonical front 和 usage constraints；同类同分资产会轮换选取，因此左右床头柜使用不同变体。
- optimized 目录约 173MB；坏地毯隔离目录约 24MB；raw 目录约 360MB。
- V2 房型策略已加入“硬资产数下限 + 软资产数上限 + 地面占用率区间”；硬下限与功能核心缺失会判为硬失败，显式用户物件超过软上限时只产生软告警且不会被删除。
- 默认预算：bedroom `7/12`、living room `8/12`、kitchen `7/11`、study `5/9`、restroom `5/8`（前者为硬下限，后者为软上限）。
- bedroom 默认从 7 件扩充为 10 件：复用盆栽、闹钟、杯子，并用 support offset 避免与两侧台灯重叠。
- 新增 restroom 策略和墙挂物件约束；默认功能核心为马桶、洗手台、淋浴、镜子和洗衣篮。
- `validation_final.json` 和 `run_summary.json` 现在记录 soft violation、地面占用率、compactness status/score。
- 36 个 V2 unittest 通过。

严格复用装配 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/curated_library_reuse_assembly_smoke
```

旧 smoke 结果：卧室策略 7 个对象全部 `status=reused`，未调用 TRELLIS；`validation_ok=true`、`assembly_ok=true`。生成场景约 63.7MB、12 个 geometry、710056 faces。

数量预算与紧凑度 smoke：

```text
rules + plan bedroom:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_budget_sdk_smoke
rules + plan restroom:
  /data/wsj/main/scene_runs/codex_trellis_v2/restroom_budget_sdk_smoke
rules + reuse + Blender + MuJoCo bedroom:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_budget_reuse_smoke
Codex expansion + Codex layout bedroom:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_budget_codex_plan
```

结果：bedroom 10 件、占用率 `0.2564`，restroom 5 件、占用率 `0.1748`；两者均为 `compactness_status=balanced`、score `1.0`。10 件卧室严格复用装配 `validation_ok=true`、`assembly_ok=true`、`mujoco_ok=true`。Codex 初始布局仅有衣柜侵入门区，SDK 一轮修复后为 0 硬违规、0 软告警。

V2 Blender 装配现在默认在每次输出 GLB 时额外渲染两张 960x720 dollhouse 参考图：`scene_front_45.png` 保留原前左斜视角，渲染时隐藏南/西墙；`scene_front_center_45.png` 的相机位于房间正前方中轴线上，向下俯视 45°，只隐藏正面的南墙。GLB 始终保留完整房间。可用 `--no-render-preview` 同时关闭；路径分别写入 `run_summary.json.scene_render` 和 `scene_render_front_center`，assembly report 也记录两者。

真实渲染 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_render_preview_smoke
```

结果：`assembly_ok=true`，同时生成约 96MB GLB 和可正常查看的 PNG；默认相机能同时看到床、两侧床头区域、斗柜和衣柜。

V2 已增加独立 `architecture` 规划阶段，执行顺序为“文本扩写 -> 四墙/门/窗/地板与墙面材质 -> 资产解析 -> 家具布局”。门、窗、墙、地板不计入家具数量预算；所有当前房型要求四面围护墙、1 个入口门、1-2 扇窗和必需地板/墙面材质。门窗默认异墙是软约束；卧室进一步默认东墙门、西墙主窗，即主窗优先位于入口门对墙，并把斗柜从西墙迁到南墙避让。用户用 Prompt 或 `--window-wall` 明确指定其他墙时会记录 `door_window_opposite_wall` override，而不是硬失败。门洞继续驱动入口净空约束，窗户保留高家具/墙挂物遮挡硬检查。

Blender 不再生成完整实墙后贴门窗，而是按 opening 切分墙板。门窗先从审核资产清单按 `door/window` 类别解析到 `assets_staged/architecture/`；有资产时按冻结开口尺寸、墙法向和 canonical front 导入，缺失时回退为参数化门框/静态门扇或窗框/玻璃，不会为了资产移动开口。地板现有 8 个测试预设：暖橡木、浅橡木、胡桃木、灰洗木、米色瓷砖、灰石、水磨石和抛光混凝土；装配时生成 512x512 确定性贴图，设置平面 UV，并作为 glTF `baseColorTexture` 内嵌进 GLB。可用 Prompt 材质词或 `--floor-material` 选择。

墙面材质已进入 architecture contract：现有暖/冷白灰泥、米色 limewash、浅灰/鼠尾草绿/蓝灰哑光漆 6 个确定性预设；每个房间必须有一个全局默认墙面，最多允许一面 override。可用 `--wall-material` 设置默认值，并成对使用 `--accent-wall`、`--accent-wall-material` 设置强调墙。Blender 为每种实际使用的墙面材质生成并内嵌低对比可平铺 PNG；墙板按 room-space 坐标投影 UV，因此门窗 opening 切分出的多个 panel 保持连续坐标。validator 会硬检查默认墙面材质、override 墙名、override 数量和材质完整性。

墙面材质真实 smoke：

```text
plan-only:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_wall_finish_plan_smoke
reuse + Blender (最终采用):
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_wall_finish_assembly_smoke_v3
```

结果：全局 `warm_white_plaster`、北墙 `muted_sage_matte_paint`，0 硬违规、0 软告警、`assembly_ok=true`；GLB 约 104MB。GLB 只保留 1 个三墙共享的默认材质和 1 个北墙强调材质，两张墙面 PNG 均内嵌为 bufferView 并由 `baseColorTexture` 引用；9 个 opening 切分墙板全部含 `TEXCOORD_0`。西墙 panel 的 U 区间在 `1.9/3.3` 处连续，东墙在 `0.3/1.2` 处连续。两张 960x720 参考图正常，第一版过强周期条带已改为低对比可平铺多频纹理。该 smoke 不运行 MuJoCo，因为当前 proxy 不验证墙面材质或建筑资产。

门记录已预留 `hinge_side`、`swing_direction`，但状态明确为 `deferred_static_metadata_only`；当前只生成静态旋转门扇，不宣称资产库或 GLB 已支持可动铰链。以后必须同时补 joint origin/axis/limits、碰撞体和模拟器导出。

当前 `mujoco_ok` 只是从最终 layout plan 的 `dimensions/x/y/z/yaw` 构造家具 axis-aligned box proxy 做短时重力稳定性 sanity check；它不读取 Blender 导出的 GLB、装配后 world transform、真实 mesh、门窗 opening 或建筑资产，因此不能作为门资产、铰链或最终装配物理正确性的验收结论。深层物理验证暂缓为后续项目：等门资产库补齐可动铰链数据（joint origin/axis/limits、碰撞体、质量和模拟器导出）后，再由 Blender 装配结果导出 collision/articulation manifest，并基于该 manifest 验证门扇运动、把手/墙体净空、碰撞和家具交互。现阶段保留 MuJoCo 仅作为家具布局层 proxy 预检。

新增项目 skill：`sage/skills/scene-architecture-planning/SKILL.md`。它规定建筑先行顺序、门窗异墙与卧室对墙窗软约束、门窗资产绑定/参数化回退、开口硬约束、地板/墙面材质选择、单面 override 和铰链延期边界；已通过 `skill-creator` 的 `quick_validate.py`。

共享 Blender assembler 的新逻辑受 `plan.architecture` 和 `embed_generated_texture` 显式开关保护；旧 plan 没有 architecture 时仍生成原命名的 `wall_north/south/west/east` 完整墙体。已用旧卧室 plan 实际导出验证 `legacy_wall_names_preserved=true`，避免改变原链默认行为。

建筑结构真实 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_architecture_smoke
```

结果：10 件家具预算保持不变，`validation_ok=true`、0 硬违规、0 软告警、`assembly_ok=true`、`mujoco_ok=true`；GLB 约 96MB，包含门窗结构和内嵌地板 baseColorTexture。

建筑先行 + 水磨石 smoke：

```text
plan-only:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_architecture_plan_smoke
reuse + Blender:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_architecture_material_smoke
```

结果：`architecture_plan.json` 在资产解析前生成，东墙门/南墙窗、四墙和 `terrazzo_tile` 均被验证；0 硬违规、0 软告警、`assembly_ok=true`。导出 GLB 约 96MB、29 个 geometry，内嵌 PNG 名为 `floor_terrazzo_tile_procedural_terrazzo`，地板材质通过 `baseColorTexture` 引用；同时生成 672KB 的 `scene_front_45.png`。

V2 已加入功能面朝向语义：墙边储物/工作家具使用 `facing_constraint` 表达“背面接触墙、主交互面朝向室内”，Codex prompt 接收并返回 `facing_mode/contact_face`，新增 `orientation.py` 结合墙体内法向、`asset_canonical_front`、外部 `asset_orientation`、mesh local offset 和 footprint offset 求最终 yaw。高置信度前向错误是硬失败，低置信度/fallback 是软告警；deterministic repair 在重新计算 footprint 和贴墙前先修正朝向。外部资产的首次前向识别应缓存到本地 overlay manifest，不放进每轮生成链路。

衣柜朝向修复 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_orientation_semantics_smoke
```

结果：旧结果中东墙衣柜 `yaw=90`、正面朝墙；新结果自动改为 `yaw=270`，世界正面 `[-1,0]` 与东墙内法向一致，渲染可见柜门和把手朝向房间。4 个受约束家具全部通过，`max_angle_error_degrees=0`、0 硬违规、0 软告警、`assembly_ok=true`、`mujoco_ok=true`；GLB 约 100MB，45° PNG 约 691KB。

卧室对墙窗 + 门窗资产绑定 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_opposite_window_asset_smoke
```

结果：东墙入口门、西墙主窗，`door_window_opposite_wall=true`；斗柜位于南墙且功能面朝室内。审核窗户 `window_white_single_001` 实际导入 GLB，yaw `270`；该次运行时库中还没有审核门，因此入口门记录为 `parametric_fallback`。0 硬违规、0 软告警、`assembly_ok=true`、`mujoco_ok=true`，GLB 约 105MB。新增正前方 45° 图用于从房间正面检查整体构图；GLB 包含 `window_main_geometry_0/window_main_root`。V2 unittest 现为 36 个且全部通过，architecture skill UI metadata 已重新生成并通过 `quick_validate.py`。

Image2 -> TRELLIS.2 门资产 pilot：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/door_image2_trellis_pilot
```

三张 Image2 参考图均完成，TRELLIS.2 串行生成 3/3 成功，GLB 约 14-17MB 且均可被 `trimesh` 加载。Blender 转台确认 glTF 原始 bounds 为 Y-up，但 Blender 已自动转成 Z-up，入库元数据保持 `asset_axis_to_z=2`。白色极简门 `door_white_minimal_001` 已从 471936 面减至 60000 面，四视角、0.9x2.1m 东墙门洞、正反面、侧面厚度、把手、墙体交叉和正式 manifest 自动选择均通过，现已作为 `prototype_approved` 写入 `assets_curated_v1/manifest.json`；当前限制为静态关闭门、背面轻微铰链伪影和白墙低对比，不执行 `open_angle_degrees` 铰链开合。推广输出为 `/data/wsj/main/scene_runs/codex_trellis_v2/door_white_minimal_promotion_v1`。暖橡木门仍是待优化原型；胡桃木门仍只作 `front_only` 待修候选。

本次生成不能直接使用 `.env` 中的 `/data/wsj/models/trellis2_primary`：该目录的 BiRefNet 仍会在离线模式下查找 Hugging Face。若需重启 bridge 或重新生成门资产，启动前必须覆盖：

```bash
export SAGE_TRELLIS_MODEL=/data/wsj/main/scene_runs/codex_trellis_v2/trellis2_primary_local
```

该本地 overlay 已把 RMBG/BiRefNet 指向 `/data/wsj/models/rmbg_2_0`。本轮 3 个门任务完成后没有需要继续等待的串行任务。

Codex 功能面语义 plan 测试：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_orientation_codex_plan
```

结果：`planner=codex_exec`，模型响应主动为东墙衣柜输出 `facing_mode=into_room`、`contact_face=back`、`yaw=270`，为西墙斗柜输出 `yaw=90`；initial plan 的 `orientation_resolution=[]`，说明本轮 Codex 已直接给出正确 yaw，并非 SDK 事后改角度。确定性层仍完成 canonical-front 验证：4/4 合格、最大角误差 0、0 硬违规、0 软告警。

RGB-D dataset 风格复杂卧室 Prompt 的真实 `gpt-5.6-sol` plan-only 压力测试：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_prompt_gpt56sol_plan_r2
```

本轮强制 `--expander codex --planner codex --codex-repair`，共调用 text expansion、initial layout、layout repair 三次 Codex；总耗时 `115.77s`，各阶段 Codex CLI 报告 token 为 `9,044 / 14,416 / 13,957`。扩写正确理解 strict front-facing、eye-level、低透视、亮漫射光、清晰轮廓以及 books/boxes/pillows/slippers 等要求，并在剩余预算槽补入 `accent_chair`。初始布局为 `planner=codex_exec`，但衣柜侵入入口净空且主通道不可达；SDK 修掉入口侵入后仍不可达，Codex repair 第二次布局后才得到 0 硬违规、0 软告警、`walkway_reachable=true`。最终 12 件、占用率 `0.3299`、`compactness_score=1.0`，但床从居中 `x=2.6` 移到 `x=1.65`，说明当前 repair 会以通过通道硬约束为先而牺牲 Prompt 的居中构图。

该测试也暴露出管线覆盖上限，不能只按最终 0 违规评价模型：主家具 bed/two nightstands/desk/chair/wardrobe 均进入 plan，小物件只实际包含 lamp 和 cup；books、storage boxes、pillows、slippers 虽保留在 Codex 扩写文字里，却没有进入受限对象 schema。camera/lighting 也没有结构化计划字段，固定 45 度 Blender preview 无法执行 strict front-facing eye-level 请求。最终 relations 仍只有卧室默认五条，没有 `chair -> desk` 等新关系。审核库可复用 11/12 个计划对象，唯一缺口是 `accent_chair`；库里虽有 `office_chair`，当前类别映射不会替代，因此本轮不做失真的强行装配。

当前库足够覆盖 V2 默认 bedroom 家具、窗户与一个静态关闭的白色极简门，并覆盖部分 study 资产；扩展卧室 Prompt 仍可能受类别映射影响。living room 和 kitchen 的主要类别仍需后续生成、审核和入库。

RGB-D Prompt 的数量预算、显式小物件与构图前置评分已完成第一版：

```text
Prompt:
  sage/experiments/codex_trellis_scene_v2/prompts/bedroom_rgbd_front_strict.txt
rules smoke:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_composition_rules_smoke
gpt-5.6-sol plan:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_composition_gpt56sol_plan
```

`soft_max/max_optional_assets` 的运行语义已改为 `target_max/max_auto_inferred_objects`：目标数只限制 `codex_inferred_optional`，用户显式实例与房型功能核心即使超过目标也不会被删除、合并、扣 compactness 分或产生“过度布置”数量告警；另设 `hard_runtime_limit=40` 作为唯一绝对安全边界。旧 CLI 名仍是兼容别名。Prompt 若明确要求避免额外装饰，会去除没有显式提到的房型 optional decor。

对象 schema 新增 `book_stack/storage_box/pillow`，并支持明确复数实例与 paired slippers；新 Prompt 共 17 件，含两床头柜、两台灯、两收纳箱、两枕头和两只独立拖鞋，均进入最终 layout。相机/渲染要求已结构化；`composition.py` 用 south-to-north 眼平相机投影计划 bbox，输出 framing/clarity/centeredness/symmetry。显式居中或完整入画失败为硬违规，中等 bbox 遮挡为软告警。该分数是装配前 proxy，不能替代 Blender 后的 RGB/depth/instance-mask 可见性评分。

最终 `gpt-5.6-sol` plan 为 17 件、0 硬违规、1 个遮挡软告警、占用率 `0.3339`、compactness `1.0`、composition `0.8979`；framing/centeredness/symmetry 均 `1.0`，clarity `0.6597`。床保持 `x=2.6` 中轴且床头柜对称，没有复现旧测试中 repair 把床移到 `x=1.65` 的问题。39 个 V2 unittest 全部通过。

受约束资产尺寸适配第一版已实现，核心在 `dimensions.py`。每个对象保留 `requested_dimensions/source_dimensions/effective dimensions/dimension_policy/dimension_resolution`；策略分为 `fixed_physical/uniform_scalable/axis_scalable/opening_fit/modular`。资产检索先排除尺寸不兼容候选，再按近尺寸与风格选择；固定/模块化物件保持审核物理尺寸，装饰物只可有限等比缩放，桌/地毯/窗帘等只可在声明轴范围内变化，门窗按冻结 opening 适配。无兼容资产时，reuse 明确失败，plan/TRELLIS.2 转为目标尺寸生成请求，不再强拉审核资产。

`asset_resolution.json/run_summary.json/validation_final.json` 记录尺寸决策、候选拒绝和统计；validator 会硬拒绝解析后尺寸篡改。Blender 装配要求 accepted resolution，将 canonical adaptation scale 与 raw mesh normalization scale 分开，并通过 `export_extras=True` 写进 GLB root extras。本版目标尺寸来自类别默认或上游显式字段，尚未实现预布局自动压缩或自然语言数值尺寸解析，不能宣称已完成动态 packed-layout size optimization。

尺寸策略 smoke：

```text
plan:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_dimension_policy_plan_smoke
reuse + Blender:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_dimension_policy_reuse_smoke
```

现有审核卧室 10/10 家具均为 `exact_match`，策略分布为 fixed 7、modular 1、axis-scalable 1、uniform-scalable 1；西墙窗按 `opening_fit` 从 `1.04x0.08x1.296m` 适配到冻结 opening `1.4x0.1x1.15m`。最终 0 硬/软违规、`assembly_ok=true`，GLB 约 105MB，包含 11 个带尺寸 extras 的 root（10 家具 + 1 窗）。V2 unittest 现为 44 个且全部通过。

RGB-D 复杂卧室完整端到端测试已完成：

```text
Prompt:
  /data/wsj/main/scene/sage/experiments/codex_trellis_scene_v2/prompts/bedroom_rgbd_front_strict.txt
完整输出：
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_full_gpt56sol_trellis2
FLUX.1-schnell 本地目录：
  /data/wsj/models/text_to_image__primary
```

FLUX.1-schnell 的 Diffusers 快照现约 36GB，T5 两个分片和 Transformer 三个分片均按 Hugging Face ETag 做过 SHA-256 校验，index 与 safetensors 文件头也已验证。`simgen` 环境为 tokenizer 补装了 `sentencepiece 0.2.2` 和 `protobuf 5.29.6`。512x512、4 steps 的 Flux 书堆健康图在约 30 秒完成；随后 TRELLIS.2 生成约 15.1MB 的健康 GLB，`trimesh` 可加载。测试结束后 8082/8083 服务均已停止。

正式运行使用 `gpt-5.6-sol`、Codex expansion/layout/repair、审核 manifest、`asset-mode=trellis2`、`max-new-assets=8`、12 steps、2048 texture、500k decimation、Blender assembly/render，并明确关闭 MuJoCo。结果为 17 件、`planner=codex_exec`、5 件新资产全部生成、12 件审核资产复用、`validation_ok=true`、0 硬违规、1 个构图遮挡软告警、占用率 `0.3339`、compactness `1.0`、composition proxy `0.8901`、`assembly_ok=true`。最终 GLB 约 248.5MB，`trimesh` 可加载 32 个 geometry；两张 960x720 PNG 均正常。

```text
GLB:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_full_gpt56sol_trellis2/scene_codex_trellis_v2.glb
front-left 45°:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_full_gpt56sol_trellis2/scene_front_45.png
front-center 45°:
  /data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_full_gpt56sol_trellis2/scene_front_center_45.png
```

结构成功不代表本次视觉质量合格。五个缺失资产（`book_stack`、两个 `storage_box`、两个 `pillow`）的旧 Flux 参考图全部错误生成成完整卧室，而不是孤立单物体。Flux 日志明确显示 CLIP 77-token 与 T5 256-token 截断；原因是旧资产 prompt 在类别/尺寸/隔离约束后又附加了完整 scene context。TRELLIS.2 仍从这些错误参考图生成了 19-22MB、可结构加载的单 geometry GLB，但收纳箱在最终画面更像浅色纸盒/叠放物，枕头偏硬且床本体已有枕头，不能入审核库。

缺失资产 Prompt 隔离链已完成第一版。`scene_brief.json` 现在记录按类别汇总的 `asset_inventory`；资产库匹配完成后才写 `missing_asset_generation_plan.json`，其中保留原始场景 Prompt 作为审计依据，并逐实例记录单物体规格、类别局部外观词、目标尺寸元数据、最终 bridge input、字符/词数和生成/复用策略。完整场景文本不再进入单物体 Prompt，精确米制尺寸只作为 TRELLIS 后处理元数据，Flux 只接收视觉长宽高比例。相同类别、尺寸和 Prompt 的缺失实例共享一次生成：严格 RGB-D 卧室差集仍为 5 个实例，但只需生成 3 个唯一资产（书堆、收纳箱、枕头），第二个收纳箱和第二个枕头复制同一 GLB 到各自稳定实例路径。bridge 选中的实际 Flux Prompt 会回写 `asset_resolution.json` 与资产 sidecar；同时修复了 `platform` 子串误触发 `lamp` 专用约束的问题，并缩短 bridge 隔离约束。

不启动模型的真实审核库差集演练：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_isolated_asset_prompt_plan_v3
```

结果：17 个场景实例中复用 12 个、缺失 5 个、唯一生成规格 3 个；三个唯一 bridge input 均为 59-61 个英文词，不含 `Scene context`、完整房间物件清单或相机要求，`validation_ok=true`。`minimal occlusion` 也不会再被误当成 `minimal design` 风格。V2 unittest 现为 47 个且全部通过，其中覆盖 Prompt 隔离/长度、重复实例单次生成、实际 bridge Prompt 长度和最终 Prompt 审计字段。

新的隔离 Prompt 已完成低成本真实模型验收：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_missing_assets_quick_v3
```

本轮使用 FLUX.1-schnell 512x512/4 steps，TRELLIS.2 512 pipeline、8 steps、1024 texture、200k decimation；只生成书堆、收纳箱、枕头 3 个唯一资产，并将收纳箱和枕头各复用为两个实例。三张 Flux 图均为独立单物体，不再出现完整卧室污染；收纳箱和枕头轮廓干净，书堆类别正确但参考图带圆形展示底座，作为临时布局占位可接受，不进入审核资产库。5 个实例 GLB 均可由 `trimesh` 加载；重复收纳箱及重复枕头的文件 SHA-256 分别完全一致，确认没有重复生成。最终 17 件、复用 12 件、生成 5 个实例/3 个唯一资产，`validation_ok=true`、0 硬违规、1 个遮挡软告警、composition proxy `0.8808`、`assembly_ok=true`，场景 GLB 与两张预览图均已输出。该分支已达到“无资产库时用于布局测试”的可用水准，不继续做生成质量精修或资产入库。

Flux 的完整组合 Prompt 仍超过 CLIP 77-token 限制，日志会截断靠后的隔离负面词；对象类别和外观描述位于最前，T5 仍接收完整输入，本轮三张实际结果均正确。后续若再改此临时链，可继续压缩 bridge 重复约束，但不作为当前优先项。冷启动时本地模型权重磁盘读取很慢，bridge 的 600 秒 Flux 等待曾超时；实际运行应先让 Flux 常驻并完成首次健康生成，再提交场景任务，或提高 bridge 冷启动超时。

类型化场景图第一版已实现于 `sage/experiments/codex_trellis_scene_v2/scene_graph.py`。它保留一个唯一主父节点树作为所有权、局部变换和未来优化顺序，并把旧 `relations`、`support_id`、`preferred_wall`、`facing_constraint` 编译为独立的类型化关系边。房间是根；墙和地板属于房间；门窗安装在具体墙体；普通家具属于房间并另有 `supported_by floor`；墙挂物属于墙；台灯、书等支撑物属于实际父家具。节点已预留 `part_of_id/container_id/container_slot/included_components/support_surfaces/containment_volumes` 等资产组成与容纳接口，关系边记录 constraint class、hard/soft、方向、来源和参数。

布局完成后，图中物件节点会记录 world pose；有可解析物件父节点时同时计算 parent-local pose。rules/Codex layout 和 deterministic/Codex repair 都会刷新图，避免修复后位姿陈旧。管线新增 `scene_graph_initial.json`、`scene_graph_resolved.json`、`scene_graph_final.json`，验证器会把图中的重复节点、缺失父节点、层级环和悬空关系作为硬错误；run summary 记录图的路径、统计与验证结果。现有 AABB/footprint 仍是有效 broad phase，graph optimization contract 只预留 relation-aware SDF narrow phase，当前尚未实现 SDF 或参考图关系推断。

枕头重复问题已按“组合资产吸收”最小方案处理：当且仅当场景里有唯一一张床，显式枕头实例不会再进入独立资产解析、Flux/TRELLIS.2 生成或 layout，而是将数量、外观词和原实例 ID 记录为床的 `component_requirements`。生成/计划中的床会把该要求写进单资产 Prompt；审核床 manifest 若有 `included_components` 则核验数量，旧 manifest 缺少该字段时只标记 `assumed_satisfied_by_composite_asset`，不会谎称已验证；manifest 明示数量不足会阻止装配。审计结果写入 `component_resolution.json` 与 run summary。多床或无床的歧义场景仍保留独立枕头，不做猜测性吸收。

V2 无模型 unittest 已增至 49 个且全部通过。严格 RGB-D 卧室另完成 rules/plan-only 真实 manifest smoke：对象节点由 17 降为 15，两个枕头记录为床组件且不进入 generation plan；缺失资产由 5 个实例/3 个唯一规格降为书堆与两个收纳箱共 3 个实例/2 个唯一规格；类型化图验证通过、布局 0 个硬违规。当前 `bed_warm_oak_001` manifest 没有 `included_components`，因此本次状态正确为 `assumed_satisfied_by_composite_asset`，不是已验证包含两个枕头。未启动 Flux、TRELLIS.2 或 Blender。持久化 smoke 输出：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_pillow_component_plan_smoke_20260720
```

2026-07-22 新增针对类型化场景图与组合组件的关系密集 Prompt：

```text
/data/wsj/main/scene/sage/experiments/codex_trellis_scene_v2/prompts/bedroom_typed_graph_component_strict.txt
```

Codex expansion/planner 运行因当前租户策略禁止向外部 Codex 服务发送工作区派生 SceneBrief、布局及资产元数据而被拦截；用户已明确允许，但租户级限制仍不可覆盖，因此不要在同一环境重复尝试或绕过。完全本地 rules/plan-only 结果保存在：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_typed_graph_component_rules_plan_20260722
```

本地结果为部分通过：15 个物理对象，两个枕头正确吸收到床且不进入 generation plan；缺口仍为书堆和两个收纳箱共 3 个实例/2 个唯一规格；23 个图节点、44 条关系，initial/resolved/final 的节点父级保持一致，图验证无错误，最终 0 硬违规、1 个遮挡软告警。左右灯分别从属于左右床头柜，书堆从属于书桌，final graph 能解析书堆相对书桌的 local pose。测试同时暴露关系抽取尚未完成：Prompt 要求杯子在书桌上，但规则仍沿用 `bedside_mug -> nightstand_right`；椅子没有生成面向书桌的关系；书桌 east wall 和衣柜 west wall 要求未覆盖默认位置；`centered on the bed` 与 `fully recognizable` 未触发当前 `centered_composition/complete_required_objects_visible` 关键词；杯子与书堆位于同一句使 `ceramic` 外观词泄漏到书堆资产 Prompt。上述问题本轮只记录，未修改代码。

用户随后在普通终端成功完成同一 Prompt 的 `gpt-5.6-sol` Codex expansion/planner plan-only 测试；Agent 沙箱仍不可直接代跑，但不再是项目验证阻塞。结果位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_typed_graph_component_codex_plan_manual_r1
```

Codex 扩写准确复述了 `pillow part of bed`、`mug/book supported by desk`、`chair faces desk`、desk east wall 和 wardrobe west wall，说明模型语义理解本身没有失败。但这些扩写关系没有被编译回 SceneBrief：layout 对象仍携带旧的 `bedside_mug -> nightstand_right`、`wardrobe -> east_wall`，desk 无 wall relation，chair 无 facing relation。Codex 初始几何上把 desk 放到 east wall、chair 放在 desk 前并朝向 desk，但初始布局有 wardrobe 门区侵入和 bed-chair 碰撞；SDK 修复硬违规时把 desk 从 east wall 拉开并改变 chair 相对位置，因为图中没有对应关系可供保持。这证明当前主要缺口是 expansion 文本到 typed relations/executable constraints 的 grounding，而不是 `gpt-5.6-sol` 不理解关系。

Codex 最终仍保持 15 个物理对象、吸收 2 个枕头、3 个缺失实例/2 个唯一规格、23 个节点/44 条关系，图验证通过；SDK 一轮修复后由 2 个硬违规降为 0，保留 1 个遮挡软告警。composition proxy 从本地 rules 的 `0.8504` 提升到 `0.8938`，clarity 从 `0.5015` 提升到 `0.6459`，潜在遮挡对象从 8 个降至 6 个。书堆 Prompt 的 `ceramic` 属性泄漏以及相机显式开关漏触发仍存在。

上述 grounding 缺口的第一版代码已实现。Codex expansion schema 新增 `relation_updates/attribute_updates/component_updates`；本地 `apply_expansion_grounding()` 只接受稳定 baseline ID 和受限关系词表，验证 wall target、hard/soft、support target 与主父级环后才更新 canonical SceneBrief，并把接受/拒绝、覆盖前值、证据写入 `semantic_grounding.json`。`supported_by` 会改主父节点，`against_wall` 会覆盖房间默认墙面并为功能家具刷新入室朝向，`faces` 会形成补充边。布局归一化和 deterministic repair 都会重新求解 target-facing yaw，验证器新增 target-facing 指标和违规。对象级 `appearance_terms_grounded` 可覆盖句级类别扫描，解决 cup/book 同句的 `ceramic` 泄漏；组件更新只能细化已有 deterministic component requirement，不能修改显式数量或凭空创建组件。

V2 无模型 unittest 现为 84 个且全部通过，覆盖 grounding 关系覆盖、非法 ID、support cycle、图边生成、对象属性隔离、repair 后 chair-facing 保持，以及 target-local 旋转参考系、桌椅前方/净空、箱子左右/分离、soft 关系不升级、不可满足关系显式报告、`one pair of slippers -> 2` 物理实例、方向关系与中心对齐解耦、语义锚点对齐、镜像对称、锁定 side-role 参考系、重叠 constraint scope、组级失败聚合、软/硬墙面约束、实例组的互斥成员/资产复用/组级布局，以及 capability schema、raw Y-up 到 canonical Z-up、voxel SDF 符号/缓存、support-surface 对照和桌下 dense/sparse 分类一致性。纯本地 pipeline smoke 也通过，`semantic_grounding.json` 与 run summary 正常输出；rules 模式正确记录 `mode=deterministic_baseline`。

新版 typed-delta grounding 已由用户在普通终端完成真实 `gpt-5.6-sol` plan-only 验收：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_typed_graph_grounding_codex_plan_r2
```

Codex 返回的 37 项关系/属性/组件增量被接受，5 项被拒绝。关键关系均已落入 canonical SceneBrief、final graph 和修复后 layout：杯子主父级由右床头柜改为书桌，书桌为 east wall，衣柜由默认 east wall 改为 west wall，椅子保留 `in_front_of/faces/clearance_from -> desk`，书堆仍从属于书桌；床继续吸收两个枕头。书堆资产 Prompt 只含 `compact, stacked books`，不再泄漏 `ceramic`。5 项拒绝均为 Codex 将家具“朝向房间内部”误编码成 `faces -> wall`；本地验证器按 schema 正确拒绝，已有 `against_wall + facing_constraint` 完整覆盖相同语义，不构成关系丢失。

本轮图由 44 条增至 55 条关系且验证通过。初始布局有 desk 门区侵入；Codex repair 一度造成 floor collision，随后 SDK repair 一度使 chair-facing 超过 15 度容差，第二次 SDK repair 后恢复为 0 硬违规、1 个遮挡软告警，target-facing 1/1 有效、最大角误差 0。composition proxy 为 `0.9109`、clarity 为 `0.7029`，较旧 schema 的 `0.8938/0.6459` 提升；该分数仍只是 bbox 投影代理，不代表最终 RGB 视觉验收。相机关键词缺口仍存在：`centered on the bed` 与 `fully recognizable` 尚未触发 `centered_composition/complete_required_objects_visible`。

空间关系已从“图中记录”升级为可执行的轻量 CSP。`spatial_constraints.py` 统一编译和评估 `left_of/right_of/in_front_of/separated_from/clearance_from/aligned_with/mirror_symmetric`。`left_of/right_of` 现在只表达方向和间距，不再默认用横向 tolerance 强制中心线对齐；只有显式 `alignment_mode=center` 才保留旧行为。`aligned_with` 支持 `center/front_face/back_face/left_face/right_face` 锚点以及 depth/left-right/x/y 轴，`mirror_symmetric` 支持以独立参考物为中心镜像一对物体。卧室策略由通用原子关系表达两床头柜背面与床背面对齐、两柜关于床左右镜像，没有在求解器里写床或床头柜类别特判。Codex typed-delta schema 与提示也已支持这两种关系。

床头柜参考系语义已按“基线角色锁 + 显式视角优先 + 独立验证”修正。卧室策略在结构化 `left_of/right_of` 边中声明 `side_role/role_locked/role_reference_frame=room`；grounding 不再允许 Codex 仅凭“床左右两侧”把它改成 `target_local`，只有 `source_evidence` 是原提示词中的明确观察视角片段时才接受覆盖，并把所有接受/拒绝归一化写入 `semantic_grounding.json`。validator 新增硬错误 `side_role_assignment`，根据关系字段而不是 `_left/_right` ID 后缀检查稳定角色是否镜像翻转。使用 r4 原始 Codex expansion 离线回放时，两条错误 frame 覆盖均被拒绝并记录，左右柜恢复为 room-left/room-right，side-role 2/2 通过；未覆盖原 r4 输出目录。

家具语义分组采用“Codex 提案、本地形式验证”的最小实现。扩写 schema 新增可选 `constraint_scopes`，要求 exact prompt evidence、稳定对象 ID、显式 domain/root/member role 和已 grounding 的 `relation_refs`。本地只验证契约，不按家具类别推理，不跨 scope 自动合并；同一对象可合法出现在多个 scope，scope 不改 ownership tree、support parent 或坐标。`constraint_scopes.py` 在资产解析和正式布局之前生成 advisory `constraint_scope_envelopes.json`：当前只对 floor scope 的 `left_of/right_of/in_front_of` 计算最小尺寸必要条件，其他关系和空间域显式记录为 unsupported/insufficient，所有结果均不阻断 pipeline。rules pipeline smoke `/tmp/codex_trellis_constraint_scope_rules_smoke_20260722` 通过，0 scope fallback、类型化图和最终布局均有效。

Validator 已增加 reporting-only `constraint_scope_failures`。它不替换原始 `violations`，不改变 `validation.ok`、hard/soft count 或 repair 输入；只把同一 scope 内端点连通的失败关系聚合，互不相连的关系保持分组。若 Codex scope 漏列一个 relation_ref，但该失败关系两端都是 scope members，则仅在报告层按 membership 归组并写入 `membership_inferred_relation_ids`，不新增约束。对 `bedroom_constraint_scopes_codex_plan_r1` 只读回放保持原始 `false/4 hard/1 soft/5 violations` 完全不变，同时把 4 条 raw relation failures 汇总为 2 个 hard scope failures：衣柜-收纳箱组和床-拖鞋组。

成对/匹配物件问题已完成前两阶段实现，新增项目 skill `sage/skills/scene-instance-group-planning/SKILL.md` 和独立运行时模块 `instance_groups.py`。`instance_groups` 与 advisory `constraint_scopes` 明确分离：前者是成员互斥的执行组，后者允许重叠且只做计算/报告视图。显式且无歧义的一双物件可由确定性基线建组，Codex expansion schema 也可用 exact prompt evidence、稳定 ID、cardinality/member role、资产和布局 contract 提案或细化；本地会拒绝未知 ID、数量不符、重复角色和一个物件进入两个刚体组。组不会改变 ownership tree、support parent，也不会合并 mesh、对象 ID、instance mask 或 collision shape。

资产解析现在优先同一 `asset_family_id`；manifest 缺少 family 时按 contract 复用同一个审核资产，缺失资产则共享 generation spec/key，并在每个成员记录 group/family/strategy。布局完成和普通 relation CSP 修复后，再执行组级后处理：按各资产 canonical front 统一世界朝向，受限调整成员顺序和内部间距，然后以整组刚性平移搜索房间内、无外部碰撞的 anchor 区域。validator 会硬检查成员互斥、cardinality、role order、间距、anchor gap/direction、朝向和资产 family；“复用同一几何但没有真实左右脚角色”只记 soft QA，不伪装成已验证的成对资产。报告固定为 `instance_group_grounding.json`、`instance_group_asset_resolution.json`、`instance_group_resolution.json` 和 `validation_final.json.metrics.instance_groups`。

持久化 rules/plan-only 回归：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_instance_group_rules_plan_20260723
```

严格关系卧室 Prompt 自动建立 `explicit_slipper_pair`；两只拖鞋仍是两个独立实例，但都选择 `slipper_blue_left_001`，避免旧轮换选择产生款式/形状差异。组后处理把原 1.02m 间距收紧为 0.08m，并将整组移到床脚前方，床—组实际 gap 为 0.25m；最终 0 个硬违规、2 个软告警，composition proxy `0.8904`。两个软项分别是已有 bbox 遮挡和 `instance_group_handedness_unverified`。当前尚未修改 Blender 做镜像，也没有把现有两个质量不一致的左右拖鞋标为同一真实 family；因此本阶段达到布局测试可用，而不是最终左右脚资产 QA。第三阶段 group-first 联合布局、真实 pair bundle/镜像几何和 SDF narrow phase 均未实现。

墙面语义已区分 `preferred_wall` 与显式 `against_wall`：房型策略偏好默认是 soft，显式墙面要求和墙挂物保持 hard；旧 plan 缺少强度字段时继续按 hard 兼容。deterministic repair 仍优先尝试偏好墙面，但软偏好在冲突时允许使用全房间候选。validator 与 repair 共用同一关系 evaluator；无法满足的关系继续写入 `repair_history.spatial_relation_search.unresolved`。

不调用模型的完整 rules/plan-only 回归保存在 `/tmp/codex_trellis_anchor_alignment_rules_20260722`：17 个物理对象、0 硬违规、0 软告警；`left_of/right_of/aligned_with/mirror_symmetric` 共 5/5 通过，两床头柜背沿误差和镜像误差均为 0。对失败输出 `bedroom_spatial_csp_codex_plan_r3` 做只读重放后，两个床头柜从 `y=3.27` 恢复到北墙 `y=4.095`，原来的两项 `wall_affinity` 硬违规消失，左右关系仍通过；剩余 2 个硬违规均属于尚未处理的书桌—椅子可行性/朝向问题。原运行目录未覆盖。当前求解域仍是 cardinal 2D footprint/semantic-anchor bounded search，不是连续 yaw、全局最优或真实网格/SDF 验证。

本次相机要求也尚未真正验收：layout proxy 记录 south-to-north、1.55m、65mm、centered，但 Blender 仍只输出固定向下 45° dollhouse 两视角，不是提示词要求的严格正面眼平图。front-center 图中前景斗柜被画面裁切，不能把 `composition=0.8901` 解释为最终 RGB 可见性通过；以后必须增加真实请求相机渲染及 RGB/depth/instance-mask 评分。

最小 capability schema 与第一版 relation-aware SDF pilot 已于 2026-07-24 落地，但仍保持在独立实验层，不接完整 V2 repair。新增：

```text
capability contract/validator:
  sage/experiments/codex_trellis_scene_v2/capabilities.py
pilot registry:
  sage/experiments/codex_trellis_scene_v2/capabilities/pilot_desk_mug_v1.json
voxel proxy/SDF cache:
  sage/experiments/codex_trellis_scene_v2/collision_proxy.py
cup-on-desk comparison:
  sage/experiments/codex_trellis_scene_v2/sdf_pilot.py
desk/chair registry and under-desk comparison:
  sage/experiments/codex_trellis_scene_v2/capabilities/pilot_desk_chair_v1.json
  sage/experiments/codex_trellis_scene_v2/under_desk_pilot.py
真实输出：
  /data/wsj/main/scene_runs/codex_trellis_v2/cup_on_desk_sdf_pilot_20260724_v2
  /data/wsj/main/scene_runs/codex_trellis_v2/chair_under_desk_sparse_pilot_20260724_v1
```

真实审核 desk/mug GLB 都不是 watertight；proxy 使用 canonical normalization、filled voxel occupancy + EDT signed distance、source SHA-256 和压缩 NPZ 缓存。关键坐标问题已显式处理：raw glTF 经 `trimesh` 读取为 Y-up，而 Blender 导入后已是 Z-up，不能直接复用 Blender 侧 `asset_axis_to_z=2` 解释 raw mesh。desk 0.0125m proxy 首次构建约 2.82s、约 55KB；mug 0.004m proxy 约 0.16s、约 20KB；第二次均命中缓存。

`cup_on_desk` 对比 AABB-only、generic mesh SDF 和 capability-aware SDF。审核桌中心三者均为 0m 支撑间隙、0 禁止穿透，说明当前 AABB 顶面原本正确，不能虚报 SDF 连续指标提升；但桌面边缘 probe 中总体 AABB 接受极限边缘杯子位置，审核 usable support rectangle 正确拒绝该假阳性。mug fixed scale 保持 `[1,1,1]`。

`chair_tucked_under_desk` 第一版分类 pilot 也已完成：离线参考查询 166,249 个椅子渲染网格顶点，运行代理使用固定 seed 的 4,096 个表面点；`outside/tucked/overinserted` 三个位置分别得到 `outside/valid_under/collision`，两条路径 3/3 同判。点数减少 40.588 倍，本机三次纯查询约从 30.5ms 降至 1.0ms，观测约 31 倍加速；该时间不是跨机器基准。全顶点仍不是严格三角面相交真值，主 typed graph 也尚无正式 `tucked_under` 和命名 free-space capability，因此当前只证明独立几何分类与稀疏代理一致，未完成完整 repair 接入、位姿搜索和 chair-facing 保持。下一步先补齐这层语义 contract，再进入书架 solid/free-space/support。

## 8. 仓库与环境

- 仓库：`/data/wsj/main/scene`
- 当前工作分支：`checkpoint/codex-trellis-v2-20260724`
- 已推送远端检查点：`b7e786cb5659aedb0ec6ac7aeb5404042958ed90`
- 跟踪分支：`origin/checkpoint/codex-trellis-v2-20260724`
- 检查点基于 `ee1765c`；`upstream/main` 与该基线一致，`origin/main` 比基线落后 4 个提交。
- capability/SDF pilot 是检查点之后的新修改，尚未提交；`examples/` 与 `local_models/` 继续保持未跟踪且不得误入提交。

主要环境：

```text
Flow2/Codex orchestration:
  /data/wsj/anaconda3/envs/tree-sage-flow2/bin/python

TRELLIS.2 bridge:
  /data/wsj/anaconda3/envs/trellis2/bin/python
  http://127.0.0.1:8082

Blender:
  /data/wsj/tools/blender/blender
```

当前账号可调用 Codex CLI。普通沙箱访问本地 bridge 端口可能受限；需要本地网络验证时使用允许访问 loopback 的执行方式。

## 9. 下一窗口的第一步

1. 继续围绕独立目录 `sage/experiments/codex_trellis_scene_v2` 工作，不改旧主链，也不要覆盖工作树中的已有修改。
2. 临时缺失资产链已经达到布局测试可用水准，不继续为 Flux/TRELLIS.2 单物体生成做精修或审核入库；后续资产库建立后优先复用审核资产，仅把这条链保留为缺口兜底。
3. `cup_on_desk` 与桌椅 dense/sparse 分类第一版已经完成，不要重复。下一步为 typed graph/capability contract 增加可执行但最小化的 `tucked_under`/命名 free-space 表达，并在独立 pilot 中加入位姿搜索、尺寸锁和 chair-facing 保持；不要直接改完整 V2 repair。
4. 桌椅语义 contract 稳定后，为一个真正开放的审核书架定义 `solid proxy + containment_volume + support_surface`；必须先验证 voxel fill 不会封死开放柜格，再做 `books_in_open_shelf/box_in_open_cubby`。只有这些案例通过后才评估接入完整 repair。
5. SDF pilot 之后仍需加入真正的 south-to-north、1.55m、65mm 正面渲染，并对最终 RGB/depth/instance mask 的完整入画和遮挡重新评分；固定 45 度 dollhouse 图不能代替该验收。
6. 实例组前两阶段与 rules/plan-only 回归已经完成，不要重复实现；真实左右脚 family/镜像仍延期。`bed_warm_oak_001` 未经视觉审核前也不要向 manifest 写入 `included_components: {pillow: 2}`，继续保留 assumed 状态。
7. `door_white_minimal_001` 的 60k 面优化、独立 manifest、0.9x2.1m 门洞静态 QA 与正式入库已完成，不要重复。若需要第二种门风格，再处理 `door_warm_oak_modern_001`（目标约 70k faces）；胡桃木门只保留为 `front_only` 待修候选。
8. 当前审核门是静态关闭的门框-门扇组合资产；MuJoCo proxy 不包含建筑门资产，也不作为门候选验收项。铰链开合、`open_angle_degrees`、把手动态净空和门扇碰撞仍留待 articulation manifest 完成后验证。
9. 设计覆盖 bedroom、living room、kitchen、restroom 和 study 的多 Prompt 测试集，统计硬/软违规、结构核心覆盖、占用率、紧凑度和家具 layout-plan MuJoCo proxy 稳定性；不要把该指标表述为最终 GLB 或建筑铰链物理验证。
10. 后续在已有功能朝向之上补充柜门/抽屉正面操作净空，以及更一般的 `toward_object` 关系（椅子->桌、沙发->电视）和视觉关系评分，不针对单个 Prompt 手工硬编码。
11. 在把 RGB-D dataset 风格 Prompt 升级为完整端到端基准前，增加“预布局 -> 目标尺寸请求 -> 资产再选择”的 packed-layout 尺寸优化或自然语言数值尺寸解析，并在 Blender 请求视角完成装配后增加 RGB/depth/instance-mask 可见性与遮挡评分；当前尺寸目标仍来自类别默认/上游显式字段，layout bbox composition 也仍只是前置 proxy。

## 10. 文档维护规则

- 只记录当前结论、可复现命令、关键路径、阻塞和下一步。
- 新结论覆盖旧结论，不追加重复时间线。
- 不记录 token、密码、API key 或其他凭据。
- 历史细节应放入独立实验报告，不再堆入本文件。
