# Scene 当前接续断点

最后更新：2026-09-01

本文档只保留恢复工作所需的当前结论。不要继续追加逐次终端流水；新结论应替换已过期内容。

## 0B. 高密度碰撞关系客厅的 SceneDNA + 真实 TRELLIS.2 交付已完成（2026-09-01）

本轮用户要求的独立客厅目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/living_room_collision_scene_dna_trellis2_20260831_v3
```

最终主产物：

- `scene_codex_trellis_v2.glb`：348,187,036 bytes，SHA-256
  `eece9a93a481e482a243f015ce3b5af4fc282f502b089fb4cb727fa7d30f68ef`；`trimesh` 可加载，含 33 个
  geometry/33 个 geometry node，20 个家具/摆件实例全部有对应最终节点。
- `scene_collision_relationship_result.png`：1800x1120 RGB，SHA-256
  `b5fe3405cb0b381512f1cd85b27cbccbd5cc44aa253f17eb5a20f03ffde03c13`；左侧为最终渲染，右侧为顶视
  碰撞/间距关系图，明确标注 20 instances、0 hard collisions、72 graph relations 和 8 TRELLIS types。
- `scene_front_45.png`、`scene_front_center_45.png` 及 render-acceptance 的 top/corner/front/desk-close
  视角均已实际检查。RGB/depth/instance 门确认 20/20 必需对象可见，且每个对象至少在一个视角完整。
  `agent_visual_review.json` 保存逐项人工结论和未美化的局限，`final_delivery_audit.json` 保存最终哈希、
  指标、资源与测试证据。

完整资产流程没有用参数化资产冒充缺失项：

- 10 个实例来自真实 TRELLIS.2，按 8 个唯一生成类型去重：sofa、coffee_table、tv_stand、tv、
  accent_chair、side_table、floor_lamp、bookcase；另外 10 个实例复用审核库资产，最终 missing=0。
- SceneDNA 使用 `relation_aware` opt-in，contract hash 为
  `8ee95cc1de62a5a5c4183125dc7e04fe95eef1e6fb76600edaad00ef5166e877`。8 类共比较 46 个 3D 候选，
  最终 8/8 通过硬 3D 可装配门；自动完整多视图软门只有 1/8，故 harmony certificate 正确保留
  `claims_visual_harmony_pass=false`、`style_review_required=true`。人工多视图确认八类均可辨识且四向结构
  一致，但部分资产仍带参考图展示底面或小道具残留；这不造成硬碰撞，却是后续生产级清理点。不得把
  本轮描述为 SceneDNA 已证明有效或资产美术质量完美，vNext 默认替换仍关闭。
- 恢复流程新增逐候选原子 checkpoint（路径、大小、SHA-256、contract hash、完整 metadata/multiview），
  可在服务重启后跳过已验证候选。floor_lamp 6 个、bookcase 4 个候选均有可校验 checkpoint；前 6 类
  已在新增机制前完整落盘并由 selection report 恢复。

几何、关系、资源和工程验收：

- `validation_final.json` 为 `ok=true`、0 hard violations、0 raw/scoped relation failures，20/20 空间关系
  有效，6/6 功能朝向有效，walkway reachable；floor occupancy 0.2618、compactness balanced。仅有两条
  wall-affinity 软偏好告警（accent chair、floor lamp），不是碰撞或越界。
- 两幅 wall art 实际硬挂在南墙 `y=0.1025m, z=1.55m`；剖视图隐藏相机侧南墙但保留墙饰，因此看似
  悬空，不是布局关系失败。
- TRELLIS 每个有界批次都由 `trellis_fresh_cgroup_supervisor.py` 启动新的 user systemd cgroup，
  `MemoryHigh=12G/MemoryMax=16G`。第一次恢复暴露进程内 allocator 在卸载 SceneDNA scorer 后没有真正
  归还 RSS，并触发 systemd-oomd；bridge 现执行 `gc.collect()` + glibc `malloc_trim(0)`，且服务使用
  `MALLOC_ARENA_MAX=2`，之后各批次稳定完成。最终 FLUX、TRELLIS 和主 pipeline unit 全部
  inactive/dead、Result=success、ExecMainStatus=0。
- 本轮正式回归为 V2 包 282/282、仓库根 12/12，共 294/294；V2 compileall、运行目录全部 JSON 解析、
  `git diff --check` 均通过。此前一次遗漏 unittest `-t .` 的收集错误不计入正式结果。

该客厅交付已完成，不要再次启动 FLUX/TRELLIS 或覆盖最终资产；若继续精进，优先实现生成资产的
instance-mask/geometry-component 展示底面与额外道具清理，并复用现有多视图、场景渲染和关系门复验。

## 0A. relation-aware SDF 复杂卧室的真实 TRELLIS.2 交付已完成（2026-08-30）

最终独立目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_trellis2_20260829_v2
```

最终产物：

- `scene_sdf_complex_bedroom.glb`：252,089,564 bytes，SHA-256
  `76e76da2632e41bd3f8dc259c8665b1981d2d6d8a85d9e17c6c3e2611309b5c2`。`trimesh` 可加载，含
  33 个 geometry/33 个 geometry node；桌、椅、开放书架和三排书六类必需节点全部存在。
- `scene_relationships_bookshelf_desk.png`：1280x900 sRGB，SHA-256
  `6b6a72758f10f622416c42580cce2a17aae10bc1e5ea38bac2d4f9e13a74112e`。已人工检查：三排各五本书
  分别清楚位于三层开放格内，办公椅的椅背、座面、扶手、底座和脚轮整体位于书桌开口下方，无明显
  穿插或相机遮挡。`scene_front_45.png` 与 `scene_front_center_45.png` 的全景检查也通过。

书架与书排不再使用参数化替代：

- `open_bookcase_trellis2_001` 和 `book_row_trellis2_001/002/003` 均为本地 TRELLIS.2 真实生成 GLB；
  `layout_plan_final.json` 中四者的 `asset_source` 全部为
  `trellis2_scene_specific_multiview_approved`，`trellis_assets/multiview_qa.json` 为 4/4 accepted，
  `parametric_fallback_used=false`。
- 第一轮三组书排因多视图出现约 10 本、6 本或含糊额外书体而被拒收，原 GLB、pilot report 和拒收
  原因保存在 `trellis_assets/rejected_multiview_v1/`，未覆盖或美化。第二轮使用三张严格五本、透明
  背景的 imagegen 参考图和新 seed 重建；`trellis_multiview_v2/*_contact.png` 的正反面均能明确数出
  正好五本，侧面仅有同一排的正常深度遮挡。
- 四个最终 TRELLIS GLB 的 SHA-256 分别为书架
  `5f8bba8c623fb1964203d8d790cd3273a5b512072f889ae6a561893263fcb281`、三排书
  `aba9f072554a0bef3d67409d7e7e728c9aff9f0b7ada9855da0e81ef881e46af`、
  `c8bbdeb0b57099810be2d85c7390036cc7fdb5031eb24ea9c2a9940ea6043930`、
  `603d53edef5a7384e741e827076967aeea0c8fbdbaed24942e489ac439678683`。

几何、关系与资源验收：

- 六个资产均完成 collision-only 清理和多级代理，visual mesh 保留；没有 hole filling 或全局 voxel
  remesh。四条 hard relations（椅子 `tucked_under`、三排书 `contained_in`）4/4 accepted；每条
  source-to-target/target-to-source `deep_count=0`，原三角网格终检均
  `complete=true/intersects=false/candidate_pair_count=0`。
- TRELLIS、geometry、Blender 均串行运行在 `MemoryHigh=12G/MemoryMax=16G` 的 user systemd 服务中；
  heavy launch/运行门仍为 96/64 GiB available，12 GiB 连续 RSS、4 GiB Dirty+Writeback、blocked 和
  I/O wait 门均启用。TRELLIS 第二轮三项峰值进程树 RSS 为 11.160、9.961、10.238 GiB，全部
  `ok=true/signal=null/termination_reason=null`。
- 生成前发现 GPU 0 的声学训练后把本任务迁到 GPU 1；又发现四卡 CUDA FEA 几何任务后补充
  `round11b_cuda_fea480`/`formalize_one_node1.py` 进程标记并重新累计完整 3600 秒稳定窗口，没有终止
  其他用户任务。最终成功窗口从 `2026-08-30T14:03:43Z` 到 `15:45:28Z` 共 202 个资源样本，全部
  healthy；最低 available 224.509 GiB、最大 Dirty+Writeback 0.188 GiB、最大 blocked 2、最大
  I/O wait 0.515%。
- `tree-sage-flow2` 完整 V2 包回归 270 项、仓库根测试 12 项，共 282 项全部通过；Python compile、
  JSON 校验和 `git diff --check` 通过。

旧参数化诊断目录 `/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_optimized_20260829_v1`
仍仅作历史诊断，不得替代上述最终 v2 交付。工作树原有大量用户/前序修改与未跟踪实验文件均保留，
未 reset、checkout 或清理。

## 0. 换对话接续摘要（2026-08-28）

SceneDNA vNext 第四轮已经完成生成、工程验收和公开包冻结，不需要继续启动 FLUX/TRELLIS 或重新
制作问卷。当前没有 tmux 生成服务在运行，四张 GPU 均已释放。实验根目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_round4_20260828_v1
```

当前唯一 SceneDNA 行动是把根目录中的
`SceneDNA_blind_review_2D_round4_offline.html` 单独发给 3–5 名未参与开发的新评审者，并把导出的
原始 JSONL 不修改地放入 `/data/wsj/main/test`。达到预注册人数后才统一解盲分析；现在不要读取
sealed key 后人工挑图、不要调选择器、不要生成配对 3D，也不要打开默认 vNext。第四轮为 38 个独立
case + 4 道隐藏重复，公开图卫生 100%，正式 100 批全部有终态；工程通过不等于人工效果已提升。

首轮旧 v2、受色溢混杂的第二轮 beta 和卫生门失败的第三轮均只作历史诊断，不得复用图片、seed 或
答案。第四轮完整恢复、服务器 `/dev/sdb` I/O 阻塞证据、固定控制变量、公开哈希和 269 项回归结果
见 `scene_dna_vnext_round4_20260828_v1/RECOVERY_AND_FREEZE_AUDIT_20260828.md`。若新对话的用户询问
“接下来做什么”，先等待/收集第四轮独立评审数据；除非用户明确切换到其他项目分支，不要再次生成
第四轮候选或问卷。

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
  -> 可选生成参考图 soft observation（独立 A/B 分支，不覆盖文本事实）
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

布局完成后，图中物件节点会记录 world pose；有可解析物件父节点时同时计算 parent-local pose。rules/Codex layout 和 deterministic/Codex repair 都会刷新图，避免修复后位姿陈旧。管线新增 `scene_graph_initial.json`、`scene_graph_resolved.json`、`scene_graph_final.json`，验证器会把图中的重复节点、缺失父节点、层级环和悬空关系作为硬错误；run summary 记录图的路径、统计与验证结果。现有 AABB/footprint 仍是默认 broad phase；通用 relation-aware geometry narrow phase 已在独立 opt-in 层实现，但尚未替换默认 V2 repair。

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

V2 无模型 unittest 现为 133 个且全部通过；除原有 grounding、类型图、布局 CSP、capability、单关系 SDF 和参考图测试外，新增覆盖通用关系编译、双向碰撞、开放书架、不认识类别、语义锚点入口深度、证书失效、多级代理、高部件预算回退、三角形复核、通用姿态求解、多关系 opt-in bridge 和自动 capability 提议。仓库根另有 12 个 unittest 通过，合计 145 个。纯本地 pipeline smoke 继续通过；默认流程未切换到新 geometry bridge。

桌下文本 grounding 的真实失败已修复。此前 expansion schema 的关系枚举漏掉
`tucked_under`，导致模型只能把 “tucked under the desk” 近似为 `in_front_of`。schema
现已加入 `tucked_under/free_space_id/preserve_facing`，并明确禁止该降级；本地另有窄范围
防御性归一化，只在 source evidence 是原 Prompt 明确片段且类别为审核
`office_chair -> desk` 时恢复 hard `tucked_under/under_desk`。相同 study Prompt 的真实
`gpt-5.6-sol` plan-only 复验直接输出正确关系、0 normalization、0 rejected update，typed
graph 验证通过。输出：
`/data/wsj/main/scene_runs/codex_trellis_v2/tucked_under_grounding_regression_20260724_v1`。

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

成对/匹配物件问题已完成前三阶段实现，已有项目 skill `sage/skills/scene-instance-group-planning/SKILL.md` 和独立运行时模块 `instance_groups.py`。`instance_groups` 与 advisory `constraint_scopes` 明确分离：前者是成员互斥的执行组，后者允许重叠且只做计算/报告视图。显式且无歧义的一双物件可由确定性基线建组，Codex expansion schema 也可用 exact prompt evidence、稳定 ID、cardinality/member role、资产和布局 contract 提案或细化；本地会拒绝未知 ID、数量不符、重复角色和一个物件进入两个刚体组。组不会改变 ownership tree、support parent，也不会合并对象 ID、instance mask 或 collision shape。

具有左右手性的 pair（当前类别策略覆盖 slipper/shoe/glove）不再允许 `same_asset_reuse`。资产解析先选同一 `asset_family_id` 下带互补 `pair_role=left/right` 的审核 bundle；找不到时复用一份源 GLB，并只给另一成员写入 `asset_reflection_axis`。默认 `mirror_axis=lateral` 会根据审核 `asset_canonical_front` 选择与前向垂直的本地轴，避免镜像左右脚时同时把鞋头翻向相反方向；TRELLIS 缺失资产也强制共享一次生成结果再镜像，不再生成两个未经配对的形状。Blender assembler 在 canonical-local 空间把反射烘焙进 mesh 顶点、翻转法线后再执行世界 yaw/placement，导出节点 extras 记录轴、mesh 和 vertex 数，GLB 不遗留负 determinant。

组级后处理现在真正用 anchor canonical front，而不是第一成员初始朝向：`heading_rule=anchor_front` 同时决定成员世界前向和并列横轴。床脚拖鞋因此平行、鞋头沿床的功能前向、按床局部左右排序。validator 新增 anchor-relative heading gate；对于 `requires_handedness=true` 的已物化资产，只有真实 manifest pair 或同一资产且恰好一份审核横向镜像才算 `handedness_verified`，否则 `instance_group_handedness_unverified` 为 hard，不能再带警告输出最终 GLB。Codex 对确定性拖鞋组的细化不能降级该 contract、交换稳定角色或移除床 anchor。报告仍为 `instance_group_grounding.json`、`instance_group_asset_resolution.json`、`instance_group_resolution.json` 和 `validation_final.json.metrics.instance_groups`。

持久化 rules/plan-only 回归：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_instance_group_rules_plan_20260723
```

旧严格关系卧室输出 `bedroom_complete_relation_geometry_20260822_v1` 保留原样，里面两只拖鞋仍是改动前的同一几何复用结果，不得把该旧 GLB 表述为已修正。新代码对同一完整卧室 Prompt 的 rules/plan 离线回归选择一份 `slipper_blue_left_001`，第二成员做本地 Y 镜像；两只均为 `yaw=270°`、内部 gap `0.08m`、床—组 gap `0.25m`，instance-group 验证 0 hard/0 soft。视觉 smoke 保存在 `/data/wsj/main/scene_runs/codex_trellis_v2/slipper_pair_mirror_smoke_20260822_v1`：Blender 日志确认 Y 轴烘焙镜像，GLB 11,536,660 bytes、7 geometry、100,060 faces，回读后镜像匹配中位误差约 0.000149m，近景 `slipper_pair_closeup.png` 已人工确认两鞋纵向平行、鞋头同向、轮廓互为左右。该审核同时把 manifest 中 `slipper_blue_left_001.asset_canonical_front` 从错误 `+y` 改为 `+x`；现有独立 right 资产仍未冒充同一真实 family。

旧 `bedroom_complete_relation_geometry_20260822_v2_handed_slippers` 虽实现了一次镜像和正确
并列朝向，但把来源 `left_slipper` 的 camera-left 命名误当成左脚语义，实际把右鞋几何放到
左脚位置；不得再把 v2 表述为最终修正版。审核 manifest 现明确记录
`slipper_blue_left_001.pair_role=right`、`pair_role_semantics=anatomical_wearer`、canonical front
`+x` 和 source medial axis `+y`。资产解析分别记录 source role 与 requested role，镜像奇偶必须
推导出请求角色；validator 还会把 medial axis 经过同一反射/yaw 变换并硬检查两鞋内侧相向。
文件名、source ID 和画面左右不再能充当人体左右证据。

最终完整卧室修正版为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_complete_relation_geometry_20260822_v3_anatomical_slippers
```

v3 只改变拖鞋资产手性字段与对应 group contract，其他物体、relations、room 和 architecture
与 v2 完全相同。左成员 `explicit_slipper_1`（世界 `x=2.7`）由审核右鞋做 local Y 镜像，右成员
`explicit_slipper_2`（`x=2.5`）保持右鞋源几何；两者均 yaw 270°，鞋头沿床前向。验证推导角色
为 `[left,right]`，medial-facing scores 为 `[1.0,1.0]`，0 hard/0 soft。新 GLB
`scene_complete_bedroom_anatomical_slippers.glb` 为 160,050,440 bytes、29 geometry、
1,442,138 faces；导出节点全部正 scale determinant，镜像已烘焙进左鞋顶点。近景
`slipper_pair_anatomical_closeup.png` 与两张完整预览已人工核对。MuJoCo box proxy 2 秒检查
`ok=true`、无 unstable，最大位移 0.094557m；两只拖鞋均仅 0.00004m。派生与范围审核见
`anatomical_slipper_derivation.json`。

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

`chair_tucked_under_desk` v2 已完成：capability schema 新增审核 `free_space_volumes`，
desk 注册 `under_desk` 空间、入口方向、允许类别、位姿边界和 facing tolerance；typed graph
新增 hard `tucked_under` 并强制绑定 target-local `free_space_id`。离线参考仍查询 166,249
个椅子顶点，运行代理使用 4,096 个固定 seed 表面点；三个固定位置仍 3/3 同判。参考引导
搜索使用合成 observation `(0.04,-0.40,0), yaw=170°, confidence=0.85`，在 833 个候选中
拒绝 197 个 free-space 外和 377 个 SDF 碰撞候选，选出
`(0.0375,-0.53,0), yaw=173.75°`。稀疏与全顶点都判 `valid_under`；dense 最小距离
`-0.001641m` 在 0.0125m voxel tolerance 内且 0 个 deep-penetrating vertices，固定尺寸和
15° facing 门禁通过。真实输出：
`/data/wsj/main/scene_runs/codex_trellis_v2/chair_under_desk_reference_guided_search_20260724_v2`。
默认参考目标是合成 observation contract，不是假称 image2 测量；下述 bridge 已继续处理
whole-room accepted observation 到 target-local relation target 和 opt-in repair 的连接。

上述 whole-room 桥接现已完成 opt-in 第一版。`reference_sdf_bridge.py` 不从图片创造关系：
计划必须已有 hard `tucked_under`，并由 `pilot_reference_sdf_binding_v1.json` 显式绑定语义
对象和审核 desk/chair asset。真实资产 smoke 将两个合成 accepted room observation 转为
desk-local 软目标 `(0.04,-0.40,0), confidence=0.9025`；833 个候选中拒绝 197 个空间外和
387 个 SDF 碰撞位置，选出 local `(0.0375,-0.505,0), yaw=180°`，再写回 world
`(2.4375,3.055,0), yaw=180°`。166,249 顶点检查为 `valid_under`，最小距离
`-0.007066m` 且 0 个 deep-penetrating vertices。relation-aware validator 只对该显式绑定
关系豁免一次 AABB 假碰撞，其他硬门禁全部保留，最终 0 hard violation。输出：
`/data/wsj/main/scene_runs/codex_trellis_v2/reference_sdf_bridge_study_20260724_v1`。该
observation 仍是合成 fixture；当前缺少 `OPENAI_API_KEY`，未冒充已认证 image2 端到端证据。

生成参考图作为软布局先验的隔离分支已实现于
`experiment/reference-soft-layout-prior`，不修改默认文本主链。`reference_soft_prior.py`
现默认通过直接 Image API 请求 `gpt-image-2`；本地 FLUX.1-schnell 仅保留为显式 provider，
不允许静默回退。当前环境没有 `OPENAI_API_KEY`，因此默认选择、请求 contract 和凭据不落盘
已由单元测试验证，但已认证 API smoke 尚未执行。观察器只接受 SceneBrief
中已有对象的高置信位置观察，拒绝未知、重复、低置信和非法坐标。图像不得修改对象集合、
尺寸、建筑或硬关系。靠墙物件只允许沿原墙切向移动，自由物件有 0.8m 位移上限；每个候选
必须同时降低 soft-prior RMSE 并通过现有硬验证，原文本布局始终是 fallback。

最终真实 smoke：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/reference_soft_prior_study_smoke_20260724_v4
```

FLUX 提示已从约 1,200 词压缩到 120 词，并把 exact objects、墙面、门窗和关系放在最前，
降低 T5 256-token 截断关键约束的风险。768x768、4 steps、seed 20260724 的图像生成耗时
约 17.4s。生成图仍出现两把椅子和额外柜体，观察器主动省略无法唯一匹配的 chair；按
0.75 双置信阈值最终接受 4/5 个观察。16/16 投影候选通过硬验证，接受 4 次移动，归一化
RMSE 从 `0.678722` 降到 `0.638185`；对象 ID、尺寸、房间、建筑和关系全部保持，最终
validation 为 0 硬违规。该结果只证明“高置信图像证据可被安全地软应用”，不证明视觉质量
优于文本基线；生成图的对象计数服从性仍是明确风险。下一步需做多 Prompt/seed、等资产
Blender A/B 与 RGB/depth/instance-mask 评分。

同一 120 词 Prompt 的首个参考图生成器对照保存在：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/reference_image_model_compare_study_20260724_v1
```

统一 `gpt-5.6-sol` 视觉审计结果：FLUX.1-schnell 的目标数量为 4/5，出现 1 把重复椅子和
3 个独立抽屉柜等 4 个额外大型家具，4 个墙面偏好 0/4；Codex 内置图生为目标数量 5/5、
额外大型家具 0、墙面 3/4。两者的 `chair faces desk` 与 east-door/north-window 均通过。
Codex 图仍额外生成 5 个小附件和 5 个装饰物，落地灯也未位于 south wall，因此“全部物件
严格通过”为 false。内置工具未暴露后端模型 ID，不能把本结果标为已验证的 API
`gpt-image-2`。该结论只有一个 Prompt、每侧一张图，且审计器本身可波动，不能外推为
统计性模型排名。

参考图与 SDF 的融合边界已确定：RGB 图只产生带置信度的 observation graph，不直接生成
SDF 或充当度量几何；所选真实 GLB 的 solid proxy/SDF、support surface、containment 或
named free-space、坐标系和 dimension policy 定义可行域。运行时先做 AABB broad phase，
再用稀疏表面代理查询缓存 SDF；Prompt、typed hard relations、建筑、对象集合和尺寸策略是
硬门禁。在硬门禁通过的候选中，才最小化 image observation、semantic relation 和最小位姿
变化软损失。首个隔离接入已给 desk 增加命名 under-desk free-space，并对
`chair_tucked_under_desk` 完成粗到细 tuck-depth/yaw 搜索与 `faces desk` 门禁；参考图只提供
目标插入深度和构图方向，不能覆盖碰撞结果。whole-room observation 的 target-local 转换与
opt-in repair 调用现已由下述 bridge 覆盖单个显式绑定关系。

第二代通用关系几何层已于 2026-08-21 在同一独立目录完成首版，不再以
`office_chair -> desk` 等类别对选择算法。`relation_geometry.py` 将 `supported_by`、
`contained_in`、`tucked_under/partially_inserted`、`against/contact` 分别编译为审核资产上的
bounded support plane、containment volume、free-space + entry portal/anchor 和 contact plane；
类别只允许作为 authoring filter，求解器不含类别分支。所有关系叠加双向 solid 查询，保守
模式缺任一方向即拒绝；证书绑定 relation、pose 和 proxy hash，输入变化后自动陈旧。

新增核心文件：

```text
relation contract/evaluator:
  sage/experiments/codex_trellis_scene_v2/relation_geometry.py
generic bounded pose solver:
  sage/experiments/codex_trellis_scene_v2/relation_solver.py
multi-relation opt-in bridge:
  sage/experiments/codex_trellis_scene_v2/relation_geometry_bridge.py
component-aware multilevel proxy:
  sage/experiments/codex_trellis_scene_v2/multilevel_proxy.py
adaptive triangle verifier:
  sage/experiments/codex_trellis_scene_v2/mesh_verifier.py
automatic review-only proposals:
  sage/experiments/codex_trellis_scene_v2/capability_proposer.py
  sage/experiments/codex_trellis_scene_v2/propose_capabilities.py
Z-up scene to glTF Y-up export boundary:
  sage/experiments/codex_trellis_scene_v2/gltf_export.py
design and validation:
  sage/experiments/codex_trellis_scene_v2/GEOMETRY_RELATIONS.md
  sage/experiments/codex_trellis_scene_v2/RELATION_GEOMETRY_VALIDATION.md
```

RobustCage 可借鉴部分已按 clean-room Python 方式落实为“逐连通部件、粗细多级、显式离散
误差、manifest 最后提交”。若 TRELLIS 网格碎成过多部件则不实例化数千个 mesh：desk
实测 16,170 个、chair 8,022 个，超过 512 预算后退化为不做全局 fill 的 surface shell，既
避免 exit 137，也不封闭空腔。该 fallback 不是带严格 Hausdorff 证明的 RobustCage cage，
不能冒充同等保证。OpenMeshCraft 可借鉴部分落实为退化面过滤、空间 broad phase 和三角形
narrow phase；当前 Python verifier 明示 `exact_predicates=false`，后续仍需小型 native exact
backend，未复制 GPL 代码。

真实 desk/chair/mug 两级 proxy 已生成在：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/relation_geometry_v1/proxies
```

旧 15% whole-surface 桌下比例会接受真实相交姿态，已由 triangle verifier 揭示并拒绝。chair
现增加审核 `seat_front` anchor，desk free-space 增加 0.05m minimum entry depth；通用 solver
找到 local `(0,-0.52,0), yaw=180°`，anchor 进入 0.09m，双向各 8,000 点均无超误差深穿透，
triangle broad phase 为 0 candidate pair。真实 mug 支撑位置为 `(0.25,0,0.74893)`，桌面 footprint
全包含、contact sample 17.7%、双向无深穿透。一个 bridge audit 同时审核这两条 hard relation
并返回 2/2 accepted。合成五部件 open shelf fixture 继续作为稳定回归；另用已下载 SAGE-10k
真实开放书架 `102e68cd.ply`（27,198 faces、单连通 watertight）做未入库 smoke，proposer 找到
多个正面开放柜格。一个此前未参与开发的 book box 经同一 `contained_in` solver 从 192 个候选
中选出 `(0.3075,-0.0425,0.2125)`，100% containment、双向 0 deep、triangle candidate pair=0。
该真实 target 仍未进入 curated manifest，不能表述为已审核资产。

关系几何最终装配 smoke 已补做真实 GLB 导出和 Blender 回读。首版直接用 `trimesh` 将内部
Z-up 场景写入 glTF，文件结构与关系证书虽通过，但 Blender 按 glTF Y-up 规则导入后将地面
转成竖直平面。现由 `gltf_export.py` 在导出边界显式绕 X 轴 `-90°`，不修改内部求解坐标；
诊断渲染器也会检查命名 floor 的 Blender world extents，竖直地面立即以非零退出码失败。
修复输出为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/relation_geometry_glb_smoke_20260821_v2
```

Blender 回读 floor 为 `4.0 x 3.0 x 0.04m`，shelf 为
`1.032 x 0.330 x 1.293m`，轴向检查通过；三视图已重新生成。旧 v1 保留为 guard 的失败
fixture，不再视为可交付 GLB。书架原始 PLY 仍缺少审核材质和 canonical front 标注，当前
中性诊断材质只改善可见性，不等同资产入库 QA。新增轴向、Codex stdin transport 和几何
加入手性 pair、anchor heading、人体源角色、内侧相向、镜像资产和 SceneDNA A/B 回归后 V2 目录
167 tests、根目录 12 tests 全部通过。

在上述能力基础上已生成一个完整卧室，不调用 TRELLIS 新生成资产：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_complete_relation_geometry_20260822_v1
```

该运行使用 `gpt-5.6-sol` 做 expansion/layout/repair，复用 16 个审核资产实例，typed graph 有
57 条关系，包含 5.2x4.4x2.7m 房间、四墙、地面、审核门窗、床/双床头柜/双灯、衣柜、斗柜、
书桌椅、地毯、挂画、绿植、杯子、闹钟和一双拖鞋。默认 AABB 只把椅子停在桌前；opt-in
generic solver 在 975 个候选中找到 desk-local `(0,-0.555,0), yaw=180°`，139 个候选通过，
双向各 8,000 点均 0 deep，triangle verifier 0 intersection。`relation_geometry_bridge.py`
现可只对同一已认证 pair 的 `floor_collision` AABB 假阳性做定向豁免，要求 bilateral complete、
0 deep 且 triangle complete/no-intersection；其他违规不会被移除。最终 0 hard、1 soft
（wardrobe 未遵循 east-wall 软偏好）。

Blender 最终 GLB 为 159,749,728 bytes、29 geometry、1,442,138 faces，`trimesh` 可回读；
Blender 二次导入 floor 为 `5.2x4.4x0.05m` 且水平。MuJoCo box-proxy 2 秒检查无 unstable，
最大位移 0.094557m，主要来自 box proxy 对桌椅插入的近似响应，低于 0.18m 阈值。两个正式
预览和 top/corner 诊断图均已人工检查，家具完整且椅子视觉上位于桌下。

本次复杂 typed-graph layout request 约 150KB，曾触发 Linux 单参数 128KB 上限；
`io_utils.py` 的文本与图像 Codex 请求现统一以 stdin 传递，request artifact 仍完整保留。

自动 capability proposer 已在真实 desk 上找到 z=0.74993m 的顶部支撑面，以及近似
`[-0.63,-0.36,0] -> [0.63,0.25,0.57]` 的开放空间；同时也因体积接触地面错误提出向下入口。
所有提议固定 `review_required=true/approved=false/automatic_approval_forbidden=true`，该误提
正是必须人工审核的证据。默认 V2 pipeline 和旧 `reference_sdf_bridge.py` 均未被替换。

混合审核资产与 TRELLIS.2 缺失资产的 SceneDNA MVP 已接入 V2 资产解析。新增
`scene_dna.py` 和 `SCENE_DNA.md`；`scene_dna_contract.json` 统一约束资产库软重排与缺失资产
Prompt 编译，来源优先级为明确用户文本 > 预留用户参考图 > 尺寸兼容审核锚点共识/建筑材料
> 房型默认。类别、QA、尺寸、能力、canonical front、手性和关系几何继续作为先于风格的
硬门禁，风格分数不能补偿硬失败。typed scene graph 会编译局部审美关系组，分面评分允许
办公椅等物件在保持风格家族一致时使用不同色板/材料，避免全屋同色同材质的风格坍缩。

缺失资产计划写出 4 个隔离 2D 候选、最多 2 个晋级 TRELLIS.2、最多 2 轮的机器可读预算。
`scene_dna_semantic.py` 现把 SigLIP2 类别/必需部件/禁用部件、7 个类别无关 alpha 形态 profile、
DINOv3 审核锚点和原有局部外观分融合；语义或形态候选全灭时整批失败/重试，分差小或评分器
冲突时 Top-2 用相同 TRELLIS seed 晋级。TRELLIS 仍延迟到 2D 筛选后加载。
`generated_asset_harmony_certificate.json` 继续绑定合同、资产、Prompt、排序和四视角 hash；
冻结视觉模型分数只是筛选证据，不是人工语义真值。

冻结基准入口为 `scene_dna_benchmark.py`（7 类 × 2 风格 × 3 seed × 4 图 = 168 候选），
候选运行器为 `scene_dna_candidate_benchmark_runner.py`，同 seed 配对 GLB 为
`scene_dna_3d_benchmark_runner.py`。`scene_dna_blind_review.py` 会隐藏方法标签、随机左右、加入
至少 10% 隐藏重复题，并按原 case 做 clustered bootstrap，重复题只用于评审一致性、不扩大 n。
当前实验根目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v1
```

首轮每类单批开发 pilot 已作废：DINOv3 的 fp16 token 平均产生 NaN，旧 `_clip01` 又把非有限
值错误处理成高分。现在使用 fp32 global/CLS token 并硬拒非有限值；SigLIP2 正负假设合为一次
前向。任何旧 pilot 的“4 类改变选择/5 类 Top-2 不确定”都不得引用为收益证据，必须用修正代码
重跑冻结计划。拖鞋合同已明确 open-back slide，并把 closed-back shoe/loafer/moccasin 作为
硬负类；尚缺修正模型下多 seed 验证。

旧 3D 配对 pilot 还暴露 bridge 的透明输入错误：抠图 RGBA 以 `preprocess_image=false` 进入
TRELLIS，隐藏 RGB 背景会被重建成彩色平面。bridge 现检测有效透明度并强制执行 alpha 裁切，
同时记录 requested/effective 值。修复后的椅子/台灯配对测试位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v1/paired_3d_alpha_fix_v2
```

椅子两分支背景板消失且均为完整 3D，保守结论 `inconclusive_or_small_effect`；台灯基线把电线/
地面残留重建成巨大矩形并失败，SceneDNA 分支为完整灯体并通过，结论 `positive_effect`。这只
证明透明修复与该台灯个案，不能推广到全类别。多视图碎片门现读取 semantic form profile：
`skeletal_support` 允许脚轮/底座等合理分件，`slender_radial` 仍严格拒绝电线/平台；runner 的
`--refresh-evaluation` 可在不重做 GLB 的情况下复算旧 render。

旧收纳箱闭环 `scene_dna_real_harmonization_storage_box_20260822_v8_final` 与 A/B
`scene_dna_effectiveness_storage_box_20260823` 继续保留为回归；后者仅 `+0.002044`，结论仍是
`inconclusive_or_small_effect`。四模式计划消融 `scene_dna_ablation_20260822_v1` 只证明控制
变量接口成立。

修正评分器的冻结全量基准已在不改计划、不看图后挑样本的前提下完成，根目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v2
```

正式候选结果在 `candidate_results_full_v1`：42 个批次中 41 个成功，1 个 office-chair 批次因
4 张图全部不满足 alpha/form 硬门而拒绝，批次硬失败率 `0.023810`；实际结构化评分 164 张图，
alpha/form/semantic/joint 候选通过率分别为 `0.969512/0.804878/0.945122/0.756098`。41 个成功
批次中 25 个改变旧的 candidate-0 选择，33 个因分差或评分器冲突晋级 Top-2。按类别诊断，
table-lamp 的 form 候选通过率最低（`0.541667`），office-chair 是唯一出现整批失败的类别，
potted-plant 全部通过。该结果只证明硬门、排序和不确定性机制会产生非平凡决策，不证明这些
决策视觉上更好。

DINOv3 的修正现在是模型本身以 fp32 前向，不再只在已经产生 NaN 后把 token 转成 fp32；
无匹配审核锚点时也不会无意义加载 DINO。通用 required-part 默认阈值由 `0.04` 改为 `0`，
高风险类别必须显式 opt in；开放书架允许有实体背板，并以重复水平层结构判定。拖鞋改用
`open_back_footwear` 形态合同，以端部高度比例硬拒封闭高鞋跟/乐福鞋，旧开发候选回放可正确
保留唯一 open-back slide。全量运行支持 deterministic shard、resume 和单批失败留证；分析入口
为 `scene_dna_benchmark_analysis.py`，离线迁移/复算入口为 `scene_dna_candidate_rescore.py`。

v2 的 28 题 2D 包已作废：人工预检发现 white-base repair 会把浅米色收纳箱下半部和部分书页
误当地台删除，旧 alpha QA 又错误放行。依赖这些旧 alpha 的 v2 3D GLB/8 题包也不得继续收集
正式标签。旧文件保留为诊断证据，不得交给新评审者。

预注册的跨类别同 seed 配对 3D 已完成，目录为 `paired_3d_stratified_v1`：7 个 case、14 个 GLB、
14 份四视角报告全部生成，生成失败 0。首次自动回放暴露旧门禁会放过连接式地台/承载板和封闭
物体破洞，并把分件灯体的断连与地台问题混在一起。`scene_dna_multiview.py` 现从形态合同启用
三项类别无关证据：封闭紧凑轮廓内部孔洞、细长物体下部过宽、鞋类下部持续满宽；4 个合成回归
和已有 14 个 GLB 离线复算通过。修正后的诊断为：potted-plant 1 个自动正向；storage-box、
book-stack、office-chair 3 个负向；bookcase、table-lamp、slipper 3 个双分支硬失败。台灯基线的
地台与 proposed 的灯体断连、拖鞋两边的大承载板、收纳箱 proposed 的孔洞现在都不会再被误报
为通过。

正式 3D 公开包是 `blind_review_bundle_3d`，密钥是 `sealed_blind_key_3d.json`，含 7 个独立 case
以及 1 道隐藏重复题，共 8 题。操作规程为 `BLIND_REVIEW_PROTOCOL.md`。当前 3D 非回归已经不成立，
因此即使后续 2D 人工偏好较高也不能直接替换默认链；应优先解决“2D 看起来合格但 TRELLIS 后
产生破洞、地台或断连”的可生成性预测。在独立人工统计前也不得把 selection-change/Top-2 rate
表述为收益。

首次评审启动时确认评审者浏览器与服务器不在同一网络命名空间，loopback 页面虽返回 HTTP 200
但浏览器不可达；为避免把无认证提交接口暴露到局域网，未改用全网卡监听。盲评工具现新增
`export-offline`：把公开 `trials.json` 与匿名图片内嵌成单文件 HTML，使用浏览器 local storage
续存进度并导出与既有分析器兼容的 JSONL，sealed key 不进入页面。冻结 v2 根目录已生成
`SceneDNA_blind_review_2D_offline.html`（28 题，约 9.2MB）和
`SceneDNA_blind_review_3D_offline.html`（8 题，约 2.2MB）；离线操作规程已写入
`BLIND_REVIEW_PROTOCOL.md`。离线页面只改变答案采集通道，不改变随机顺序、隐藏重复题或统计门槛。

white-base 检测现把颜色降为候选线索，并增加通用拓扑/损伤保护：低位浅色区域必须至少覆盖
主体宽度 50%，且与主体透明分离或只通过窄支撑连接才可判地台；同宽连续箱体/书页与稀疏椅脚
不会被删除。删除超过前景 35%、触及受保护上部或造成内部水平断层会回滚。新增
`scene_dna_alpha_reprocess.py`，用保存的原始 Flux RGB 重跑 RMBG，不重新生成 Flux/TRELLIS。

新冻结目录为 `scene_dna_semantic_form_benchmark_20260823_v3_alpha_safe`。41 个成功 case 的 164 张
候选重处理后全部 alpha QA 通过：48 处连续浅色主体受到保护，1 处宽地面残留被安全删除，0 次
回滚。重新计算 SigLIP2/form/DINOv3 后 41 批全部可选，27 批改变旧式选择，33 批晋级 Top-2。
正式 2D 包现为该目录下 `blind_review_bundle_2d` / `sealed_blind_key_2d.json`，含 27 个独立 case
+ 3 道隐藏重复题，共 30 题；离线文件是 `SceneDNA_blind_review_2D_alpha_safe_offline.html`。
全量联系表已人工检查，未再发现主体被 alpha 截断；题中仍允许保留生成模型自身产生的地台或
结构错误，供 `neither`/分支偏好测量。旧 v2 3D 包继续作废；alpha-safe v3 的新 3D 配对已在
独立 v4 目录生成，但尚未导出为人工题包。

三份独立人工结果已收齐并从 `/data/wsj/main/test` 只读匿名归档。正式结果位于
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_review_3reviewers_20260824_v5_final`：3 名评审、
90 条评分、27 个独立 case、0 异常题；semantic/form 偏好率 `0.508025/0.524691`，主要指标
`0.516358`，两项 CI 下界均未超过 `0.5`，`primary_gate_passed=false`。主要维度隐藏重复一致率均
`0.888889`。原始 JSONL 未修改，真实姓名只在原始文件中，派生结果使用 `reviewer_01..03`。

正式分析器已修正口径：`tie` 按 `0.5`，`neither` 作为双边不可用单独统计并从偏好率分母排除。
类别描述性结果显示 table_lamp/bookcase/office_chair 偏正，potted_plant/slipper/storage_box 和部分
book_stack 偏负。自动分与人工对齐暴露 SigLIP 语义差值对人工语义偏好的相关系数 `-0.605276`，
form 差值为 `0.342682`，combined 对 overall 近零。因此新增默认关闭、无类别特判的 form 改善门：
实验候选相对当前 eligible legacy control 的 form 分必须至少提高 `0.08` 才允许替换；否则回退。
该阈值来自当前标签，只能用于下一轮新 seed/新候选/新评审的隐藏验证，本轮两候选回放 `0.570988`
不得宣称为新收益；当前候选快照还有 4 个第三候选未被旧问卷评价。

在不改写当前 30 题冻结问卷、不读取首份答案的前提下，SceneDNA 完成一轮工程安全优化。材质词
现通过形态 profile/部件角色限制适用范围，避免全金属拖鞋、书本或植物；Top-K GLB 使用通用
四视角可用性选择器，整批硬失败时禁止“最高分失败品”装配；最终四视角新增 SigLIP2 类别/部件
和风格对比证据。未来问卷源码新增图片异常标记、跳过和返回重做，但在途 v3 HTML 保持 10,032,325
bytes 未重导出。

新真实 3D 输出为
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_v4_dev/paired_3d_alpha_safe_v4`：冻结 7 类、
14 个 GLB 全部成功；baseline/proposed 通用几何可用率分别为 4/7 与 5/7，自动结论 2 正向、
3 小效应/不确定、2 双分支硬失败。proposed 平均零样本语义分 `0.493862` 高于 baseline
`0.408436`，平均风格分 `0.497661` 略低于 `0.515909`。书架与拖鞋仍失败，默认替换门继续关闭。

新增独立 opt-in 细节审查闭环，设计与诚实结论见
`sage/experiments/codex_trellis_scene_v2/DETAIL_REPAIR_AGENT.md`。它冻结当前 GLB 为 control，先用
自适应相机重新取证，再从通用几何、语义和风格证据编译问题，依次尝试有界局部网格编辑或同 seed
单资产重生成，并只在无硬回归、语义/风格不显著退化且确有改善时提交；否则自动回滚。主链、冻结
问卷在收集完成前未改动/读取；达到三名评审门槛后才执行上述解盲统计。

严格真实 pilot 位于
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_detail_agent_dev/final_strict_v1`：旧执行器在 2 个冻结
case 上 verified repair 为 0。后续 opt-in 开发回放位于
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_detail_agent_dev/localized_face_final_v1`。转台现在可输出
对齐的 face-ID/depth/normal/camera 证据；图像低位缺陷掩码通过可见 ray hit 与遮挡面 centroid projection
映射回稳定 mesh polygon，局部执行器只扩展并删除完整位于归一化高度 28% 以下的 seed-connected 面，
默认删除上限为 50%，同时验证材质图 hash、纹理/node 参数和存活面材质分配未变。拖鞋 4 个视角共同确认
缺陷，删除 40,059/95,629 面（0.418900）后地台 footprint ratio 为 2.638709（上限 2.8），无新增硬错误，
semantic delta -0.048128、automated delta -0.060803 均过门，最终 1 次修复获准提交；书柜安全重拍后
已可用，0 次网格误编辑。相对同两 case 旧版 0/2 提升到 1/2，提交硬回归仍为 0，但这是开发集回放，
不是 held-out 泛化结论，默认链继续关闭。

随后冻结的合成开发/留出各 6/6 均达到 face precision/recall/repair success 1.0，保护面删除和
clean false trigger 均为 0。自然 TRELLIS v2 使用 canonical `plus_y`、3 类 × 2 个全新 seed：6/6
完成，3 个地台候选中两盆植物通过四视图强证据、局部删除和回归门后提交，弱证据衣柜安全回退，
提交硬回归 0。只有足迹比至少 8 且四视图一致时，tessellation-aware 例外才允许 85% 面数上限；
最低 28% 高度、材质和修复后硬门仍不可绕过。自然隐藏 pilot 为 2 个独立题 + 1 个重复题，不足以
证明跨类别泛化。当前最大缺口是更多类别的自然正例和通用重建算子：现仅支持 typed
forbidden-platform 低位删除，尚无 cage deformation、exact local remeshing 或缺失部件重建。

最终卧室已新增真实 RGB/depth/object-index 验收和 south-to-north 1.55m/65mm 正视图，输出为
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_v4_dev/bedroom_render_acceptance_final`：16/16
required 对象至少一视角可见、12/16 至少一视角完整入画、0 硬失败、4 个相机覆盖软告警，报告
`accepted=true`。资产库覆盖审计位于同一 v4 根目录：当前 20 个审核资产/18 类，卧室 13 个必需
类别均未达到每类 3 个资产和 2 种风格签名的验证目标。

默认关闭的 `0.08` form 改善门第二轮隐藏问卷已经制作并冻结，根目录为
`/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_guard_blind_round2_20260824_v1`。冻结计划使用全新
seed，覆盖原 7 类并增加休闲椅、餐椅和落地灯，共 60 批/240 张图片；47 批通过硬门，13 批真实
拒绝。当前综合选择器与 form 门在 18 个 hard-eligible case 上选择不同，最终中文离线问卷为
`SceneDNA_blind_review_2D_beta_offline.html`：18 个独立题 + 2 个隐藏重复题，共 20 题。实验方案在
独立题左右严格 9:9，重复题距原题至少 4 位，与首轮 case/image SHA-256 零重合。只可把该 HTML
发给 3–5 名新评审者；sealed key、私有联系表、候选分数和根目录不得外发。休闲椅 6/6 批被当前
`skeletal_support` 门整体拒绝，餐椅仅 3/6 批可评估，属于需要保留的泛化失败，不能临时改阈值。
FLUX 服务同时新增单 pipeline 生成互斥，避免冷启动重试并发进入 tokenizer/pipeline。

第二轮 beta 的三份独立答案已收齐并统一解盲。正式匿名归档为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_guard_review_3reviewers_20260826_v3_final
```

3 名评审共 60 条评分、18 个独立 case、0 评审者主动标记的图片异常；形态门相对当前 combined selector 的
semantic/form 偏好率为 `0.495370/0.453704`，主要指标 `0.474537`，对应区间分别为
`[0.356481,0.634259]` 与 `[0.314815,0.592593]`，`primary_gate_passed=false`。隐藏重复一致率
semantic/form 为 `0.666667/1.0`，四维合计 `0.791667`。类别结果仅作诊断：office chair 与
potted plant 偏向形态门，book stack、slipper、table lamp 明显偏向原 combined selector，dining
chair 持平；每类仅 2-4 case，禁止据此加类别特判。form 自动差值与人工 form 偏好相关系数为
`-0.130759`，未支持 `0.08` 阈值。形态门必须继续默认关闭；由于 2D 必要门已失败，不为晋级目的
继续生成本轮 3D non-regression。分析器现会根据 comparison manifest 区分第一轮候选实验与第二轮
guard 实验，避免沿用“形态证据正向”的旧报告措辞；原始 `/data/wsj/main/test` JSONL 未修改。

用户随后指出问卷部分候选有红色泛光。新增的通用透明边缘色溢审计对冻结 beta 做只读回放后，
36 张独立图片中 18 张失败：baseline `7/18`、guard treatment `11/18`。机器报告与说明位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_beta_chroma_audit_20260826_v1
```

根因不是网页有意效果，而是旧 FLUX 重试轮换 cyan/magenta/green 饱和背景，RMBG 虽将背景 alpha
置零，透明像素隐藏 RGB 与半透明边缘仍保留背景色；旧 QA 只看轮廓、边界和白色地台，未检查
chroma spill。由于两实验分支失败数不平衡，`0.474537` 仍是对实际所见图片的正确统计，但降级为
受图像卫生混杂的诊断结果，不能证明 guard 在干净图片上更差；它同样不能支持启用 guard。

修复已进入代码但不改旧问卷：bridge 默认背景改为统一浅灰；新增 `alpha_hygiene.py`，清零 alpha=0
的隐藏 RGB、保守修正半透明边缘并硬拒残留色溢或过度清理；盲评准备阶段不再复制原 RGBA，而是
先过色溢硬门，再统一合成为 `(224,224,224)` RGB PNG，并把 QA 写入 sealed key。新增
`scene_dna_blind_review audit-images` 只读审计入口。彩色 contrast 模式只保留为显式诊断选项，不是
默认评审路径。旧 beta HTML、sealed key 和答卷均保持冻结，不得清理后与旧答案混用。

真实 FLUX + RMBG 色溢 smoke 已完成：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/chroma_gray_real_smoke_20260826_v1
```

FLUX.1-schnell 用新默认提示生成 512x512 浅灰背景书堆；背景估计 RGB 为 `[229,225,217]`、chroma
range `12`，正确判为非彩色背景。`trellis2` 环境运行本地 RMBG 后，bridge alpha QA、色溢硬门和
盲评导出二次 QA 均 `ok=true`、无理由；最终 `review_gray_rgb.png` 是固定 `[224,224,224]` 背景的
RGB 图，人工检查无红/绿/青边缘。测试结束后 FLUX 服务已停止。`tree-sage-flow2` 环境缺 `timm`，
不能独立加载 RMBG；真实 alpha smoke 与生产 bridge 均应继续使用依赖完整的 `trellis2` 环境。

汇报用的真实 FLUX + TRELLIS.2 完整场景已生成到
`/data/wsj/main/scene_runs/presentation_20260824/full_flux_trellis`。卧室最终 18 件，13/13 空间关系、
6/6 功能朝向通过，0 硬/软违规；衣柜固定西墙，canonical `-y` 经 yaw 90° 后柜门朝东/室内，
朝向误差 0°。客厅最终 13 件，6/6 空间关系、7/7 功能朝向通过，0 硬违规、2 个非阻塞墙面偏好
软告警；开放书柜同样位于西墙且开口朝东/室内。两份 GLB 均通过 assembly、MuJoCo proxy 和最终
RGB/depth/object-index 验收；SceneDNA 自动证书仍要求人工风格复核，不能把几何验收表述为风格已
被证明最优。卧室 GLB 为 226,320,452 bytes，客厅 GLB 为 287,124,968 bytes。

V2 CLI 新增 `--resume`，可从匹配 Prompt 的 scene brief、合法最终布局以及已成对落盘的 staged
GLB/metadata 继续运行；半写入 metadata、缺少 `asset_id` 或尺寸决议未通过的 checkpoint 会被拒绝并
重做。实例组恢复优先复用完整 direct checkpoint，避免中断发生在第二个共享实例时重复调用 FLUX/
TRELLIS.2。诊断渲染同时修复 `floor_lamp_geometry_0` 被子串误判为建筑地板的问题。

SceneDNA 新增默认关闭的 vNext 选择器，不再把单一类别形态分当成唯一替换门，而是用统一的取景、
alpha 确定性、连通/开运算稳定性、下部平台轮廓、语义部件完整性、禁用部件和原 form 合同作为
类别无关证据；先过硬可生成性门，再最大化最弱证据、平衡分和当前综合分。8 类/32 张全新 seed
工程 pilot 中 8/8 批完成，原始生成 31/32 通过卫生门，11/11 个可评审选择通过；7 个双方都有
control 的 case 中 3 个改变选择，并额外安全救回 1 个当前选择器无合格项的休闲椅 case。这只证明
工程可行和行为非平凡，不是人工收益。

第三轮正式计划冻结为 10 类 × 2 风格 × 5 seed = 100 个独立批次、400 个全局唯一候选 seed，且与
第二轮和 pilot seed 零重合。2026-08-28 VS Code/SSH 链路中断后，服务器未重启、无 RAM/磁盘/GPU
故障；旧会话把 FLUX 恢复到缺少 Diffusers 的错误环境，造成 36 个基础设施失败，另有 6 批未启动。
恢复审计位于 `scene_dna_vnext_round3_20260826_v2/RECOVERY_AUDIT_20260828.md`。任务改由 tmux 托管，
FLUX 固定 `simgen`、bridge 固定 `trellis2`、SigLIP 固定 CUDA/FP16；保留 56 个成功结果与 2 个真实
语义拒绝，只重试 42 个未完成/基础设施失败，最终 100/100 完成并释放全部 GPU。

正式提取有 41 个干净的双方可比选择差异，另有 22 个 vNext rescue 因没有公平 current control
只报告、不进问卷；但二次色溢审计仅 138/140 选中图通过（`0.985714`，要求 `1.0`），其中一张属于
真实 changed pair。冻结门因此失败，未生成第三轮公开问卷，也未改图、阈值、类别或候选绕门。
第三轮继续永久作废，不得就地修图、删题或复用候选。

第四轮位于 `scene_dna_vnext_round4_20260828_v1`。alpha 审计已改为使用 bridge 记录的真实源背景，
只审计最终透明像素而不二次改变暖色主体；独立 10 类/40 图 preflight 为 40/40 原始卫生通过、
14/14 选中图通过，之后才冻结全新 100 批/400 个唯一 seed 的正式计划。正式运行 100/100 有终态：
96 批成功，3 批被必需语义契约拒绝，1 批被 vNext 可生成性门拒绝；38 个双方都合格且选择不同的
公平 case 进入盲测，16 个没有 current control 的 vNext rescue 只作覆盖诊断。134 张决策相关图的
卫生与统一中性背景均为 `1.0`，冻结门通过。

2026-08-28 本次 VS Code 断联时，`/data` 对应 `/dev/sdb`，`jbd2/sdb-8` 及其他用户扫描任务处于
不可中断 I/O 等待，而系统仍有约 228 GiB 可用内存、四卡显存最终均能释放；这次异常最符合服务器
存储层阻塞，不是显存不足。FLUX 改为 `--preload --no-cpu-offload` 常驻，bridge 临时图转到 `/tmp`
完成恢复；77 MiB 临时源资产随后持久化回本轮目录，重新提取前仅替换路径指针。迁移前后公开
trials 和 HTML 哈希完全相同。完整恢复与冻结证据见本轮 `RECOVERY_AND_FREEZE_AUDIT_20260828.md`。

第四轮公开文件为 `SceneDNA_blind_review_2D_round4_offline.html`：38 个独立 case + 4 道隐藏重复，
vNext 在独立题左右各 19 次；与首轮/第二轮公开 case、图片哈希及历史候选 seed 均零重合。现在只把
该 HTML 发给 3–5 名未参与阈值/候选调试的新评审者，原始 JSONL 放入 `/data/wsj/main/test`。
新人工分析前禁止宣称 vNext 有效；2D 通过预注册门后才生成同 seed 配对 3D，默认链与 vNext 继续关闭。

候选 runner 现把连接超时、断开以及缺少 Diffusers 明确识别为可重试基础设施失败，同时保留真实
语义硬拒绝。正式冻结器会验证方法标签隔离、左右平衡、隐藏重复题、RGB 图片格式、历史 case/图片/
seed 零重合与关键文件 SHA-256。本轮回归更新为 V2 257 项加根测试 12 项，共 269 项全部通过；
`git diff --check` 通过，`trellis2` 环境也已验证可导入新增
`alpha_hygiene` 与 bridge 代码。

## 8. 仓库与环境

- 仓库：`/data/wsj/main/scene`
- 当前工作分支：`experiment/reference-soft-layout-prior`
- capability/SDF 本地检查点：`3bf1247`（`checkpoint/codex-trellis-v2-20260724`）
- 远端 `origin/checkpoint/codex-trellis-v2-20260724` 仍为 `b7e786c`；当前环境缺少 GitHub HTTPS 凭据，`3bf1247` 尚未推送。
- `origin`：`https://github.com/chilazy01-blip/Scene.git`
- 检查点基于 `ee1765c`；`upstream/main` 与该基线一致，`origin/main` 比基线落后 4 个提交。
- 参考图 soft-prior 修改位于实验分支；`examples/` 与 `local_models/` 继续保持未跟踪且不得误入提交。

主要环境：

```text
Flow2/Codex orchestration:
  /data/wsj/anaconda3/envs/tree-sage-flow2/bin/python

TRELLIS.2 bridge:
  /data/wsj/anaconda3/envs/trellis2/bin/python
  http://127.0.0.1:8082
  HF_HOME=/data/wsj/cache/hf_home
  HF_HUB_CACHE=/data/wsj/cache/hf_home/hub
  ATTN_BACKEND=sdpa
  SPARSE_ATTN_BACKEND=sdpa
  SPARSE_CONV_BACKEND=flex_gemm

Blender:
  /data/wsj/tools/blender/blender
```

当前账号可调用 Codex CLI。普通沙箱访问本地 bridge 端口可能受限；需要本地网络验证时使用允许访问 loopback 的执行方式。
当前 `trellis2` 环境没有 `flash_attn` Python 模块；启动 bridge 时必须使用上述 SDPA 环境变量，
并保留本地 Hugging Face cache 变量，否则会分别在采样阶段或 DINOv3 离线加载阶段失败。

## 9. 下一窗口的第一步

1. 继续围绕独立目录 `sage/experiments/codex_trellis_scene_v2` 工作，不改旧主链，也不要覆盖工作树中的已有修改。
2. SceneDNA v2 旧 2D/3D、受色溢混杂的 beta 第二轮和卫生门失败的第三轮都只作历史诊断；`0.08` form guard 与 vNext 默认关闭。第四轮已用新 seed 完成 preflight、100 批正式生成、100% 决策图卫生门和公开包冻结。下一步不要再生成问卷或调选择器，而是只把 `scene_dna_vnext_round4_20260828_v1/SceneDNA_blind_review_2D_round4_offline.html` 发给 3–5 名独立新评审者，原始 JSONL 不修改地放入 `/data/wsj/main/test`；达到预注册人数后统一解盲。只有 semantic/form 主要指标和 CI 通过后才做同 seed 配对 3D，3D 不劣化后才讨论扩大 opt-in。细节闭环的合成留出与 6-case 自然 pilot 已完成；其页面只能作方向检查，只有两个同类自然正例，不得宣称跨类别泛化或改默认链。
3. 通用 relation geometry、双向 proxy、generic solver、多关系 opt-in bridge、证书驱动的定向 AABB 豁免和完整卧室 desk/chair 应用均已完成，不要退回类别对特判或重复旧 pilot。该豁免仍是 opt-in postprocess，尚未进入默认 pipeline。下一步先把当前 Python adaptive verifier 接到小型 native exact-predicate backend，并缓存静态目标 BVH；在 exact backend 与跨资产统计完成前仍不得替换默认 V2 repair。
4. 合成开放书架和未入库 SAGE `102e68cd` 真实书架均已通过 `book contained_in` 与三角形终检；后者同时覆盖未见源形状且没有新增类别分支。GLB 全局轴向和站立高度 QA 已完成；下一步审核并标注书架 canonical front、材质和具体柜格，再把一个 open bookcase/cubby 正式注册到 curated manifest，并在更多真实 storage 资产上统计 proposal precision/recall。
5. 自动 capability proposer 只能生成待审核候选，真实 desk 已暴露“向下入口”误提。下一步补 review/overlay 工作流、入口方向排序和审核后的 schema 合并；任何自动提议不得直接成为 production hard constraint。
6. south-to-north、1.55m、65mm 正面渲染和最终 RGB/depth/object-index 可见性验收已接入并通过完整卧室 smoke；仍需处理床、右灯、左床头柜和衣柜没有任何投影包围盒完全入画的 4 个软告警，并在更多房型验证相机覆盖。
7. 参考图 soft-prior 单 study smoke 已通过安全门槛但证据有限；下一步先做多 Prompt/seed 与等资产 Blender A/B，不把 RMSE 下降表述成最终视觉提升，也暂不并入默认 planner。
8. 实例组真实左右 bundle 优先、审核横向镜像 fallback、anchor-relative heading、anatomical source role、medial-facing 和 hard handedness gate 均已实现，不要退回 `same_asset_reuse`、固定 X 镜像或用文件名/画面左右猜人体角色。完整卧室最终修正版在 `bedroom_complete_relation_geometry_20260822_v3_anatomical_slippers`；v1 是同几何复用，v2 是左右鞋型对调，两者都不得当作修正版。现有两个独立拖鞋资产仍未被标成同一真实 family；当前只审核了 `slipper_blue_left_001` 实际为人体右鞋并以镜像生成左鞋。`bed_warm_oak_001` 未经视觉审核前也不要向 manifest 写入 `included_components: {pillow: 2}`，继续保留 assumed 状态。
9. `door_white_minimal_001` 的 60k 面优化、独立 manifest、0.9x2.1m 门洞静态 QA 与正式入库已完成，不要重复。若需要第二种门风格，再处理 `door_warm_oak_modern_001`（目标约 70k faces）；胡桃木门只保留为 `front_only` 待修候选。
10. 当前审核门是静态关闭的门框-门扇组合资产；MuJoCo proxy 不包含建筑门资产，也不作为门候选验收项。铰链开合、`open_angle_degrees`、把手动态净空和门扇碰撞仍留待 articulation manifest 完成后验证。
11. 设计覆盖 bedroom、living room、kitchen、restroom 和 study 的多 Prompt 测试集，统计硬/软违规、结构核心覆盖、占用率、紧凑度和家具 layout-plan MuJoCo proxy 稳定性；不要把该指标表述为最终 GLB 或建筑铰链物理验证。
12. 后续在已有功能朝向之上补充柜门/抽屉正面操作净空，以及更一般的 `toward_object` 关系（椅子->桌、沙发->电视）和视觉关系评分，不针对单个 Prompt 手工硬编码。
13. 在把 RGB-D dataset 风格 Prompt 升级为完整端到端基准前，增加“预布局 -> 目标尺寸请求 -> 资产再选择”的 packed-layout 尺寸优化或自然语言数值尺寸解析；最终 Blender RGB/depth/object-index 可见性验收已经接入，但当前尺寸目标仍来自类别默认/上游显式字段，layout bbox composition 也仍只是前置 proxy。

## 10. 文档维护规则

- 只记录当前结论、可复现命令、关键路径、阻塞和下一步。
- 新结论覆盖旧结论，不追加重复时间线。
- 不记录 token、密码、API key 或其他凭据。
- 历史细节应放入独立实验报告，不再堆入本文件。
