# Protect Plan: Flow2 断点式人工约束测试与可泛化优化方案

本文档记录一个不改动 TreeSAGE Flow2 主代码框架的优化计划：从最初卧室图重新开始，按流程断点逐步加入人工约束，定位质量失败和资源峰值发生在哪些阶段，并将有效约束沉淀为可泛化的输入策略、运行策略和原仓库优化参考。

目标不是针对单张图硬调结果，而是找到对同类室内场景普遍有效的保护规则：减少错误传递、避免高风险资源峰值、提高布局验证通过率，并尽量保持原仓库已有代码逻辑不变。

## 1. 当前背景结论

基于 `bedroom_21_08_44` 的手动排查：

- `plan-only` 已成功，说明 scene graph、agent、planning、layout 主链路可执行。
- Blender 单独 assembly/render 已成功，峰值约 6GB，说明 Blender 后端不是主要工程阻塞。
- 独立 asset cleanup 在第一个对象 `wooden_bed` 处出现内存快速下降，说明 `trimesh` cleanup 是当前资源峰值高风险点。
- 使用 `--no-clean-assets` 后完整 monolithic Flow2 成功结束，写出 `run_summary.json` 和 `scene_tree_sage_flow2.glb`。
- 质量验证仍未通过，主要集中在 collision/support validity/reference order/branch execution/global validator，而不应简单归因于 asset cleanup。

因此后续优化应分成两条线：

- 工程稳定性：优先保护高风险 cleanup 阶段，避免资源峰值。
- 结果质量：通过断点式人工约束定位 layout/branch/support 哪一阶段产生不可恢复错误。

## 1.1 2026-07-10 当前 Step A 诊断状态

当前 protect 流程还停在 Step A：从原图生成 scene graph / bbox / reference instance / relations，并验证 plan-only layout。尚未建议进入 Step B fresh asset generation。

最新检查目录：

```text
/data/wsj/main/scene_runs/tree_sage_flow2/protect/step_a_scene_graph_terminal_v1_support_fix_check
```

关键判断：

- 本轮 scene graph 的物体类别和关系语义大体正确；主要问题不是“没识别出物体”，而是 `image_bbox` / `reference_instance.bbox` 对部分对象定位不准。
- `reference_instance_crops/` 是 bbox 派生的目检/诊断文件，不直接决定 support tree 或 GLB 生成；但 crop 错位说明上游 bbox/reference grounding 没有可靠校验。
- support tree 主要来自 `scene_graph["relations"]`；GLB 生成主要来自 `--asset-source-image-dir/<object_id>.png` 或 prompt fallback；但是 bbox/reference grounding 会影响初始 plan 坐标、scale prior、spatial order、support snap 和 validation。
- 当前 `reference_instance.bbox` 基本等于原始 `image_bbox`，且 `usable_for_spatial_order=true`，说明 reference grounding agent 没有把明显错误的 bbox 标为不可用，也没有有效纠偏。

已确认的 bbox/reference 问题：

- `alarm_clock_left_nightstand`：bbox 偏到闹钟右侧，crop 主要落在枕头/床边，不是闹钟主体；早期 `step_a_scene_graph_plan_only_v2/reference_instance_crops/R17_alarm_clock.png` 也存在同类严重错框。
- `mug_right_nightstand`：bbox 只覆盖杯子局部，偏小偏低。
- `desk_left`：bbox 混入椅子、桌腿和地面，无法作为干净 desk 实例。
- 左右床头柜 bbox 大体可用但不干净，包含床边/被子，影响 tabletop support surface。
- 窗户/窗帘/窗杆 bbox 大体语义对，但相互重叠且图像左边缘截断，需要 wall fixture cluster 专用处理。

仍需区分的两类问题：

- bbox/reference grounding 问题：小物体错框、桌椅混框，会直接影响位置、尺寸先验和支撑几何。
- layout/collision policy 问题：窗帘/窗户薄层重叠、台灯 shade footprint 大于真实底座 footprint，不应完全归因于 bbox。

下一步优先级：

1. 先改进 Step A bbox/reference grounding 校验：明显错框应 `usable_for_spatial_order=false` 或触发纠偏/人工约束，不应继续作为可靠空间依据。
2. 重点处理 `alarm_clock_left_nightstand`、`mug_right_nightstand`、`desk_left`/`office_chair_black` 混合区域。
3. 再处理 curtain/window/rod wall fixture overlap 容忍策略。
4. 重新跑 Step A plan-only，并用 `reference_instance_overlay.png`、`reference_instance_crops/`、`aggregate_collision_report.json`、`global_validator_report.json` 联合验收。
5. 只有当 bbox/reference/support/collision 收敛后，再进入 Step B fresh asset generation。

## 2. 总体原则

所有测试优先遵循以下原则：

- 不修改主代码框架，不新增全局 agent retry loop，不重写 Flow2 架构。
- 优先使用原仓库已有输入面：`scene_graph_file`、`human_constraints_file`、source images、prompt、运行参数、已有 reports。
- 每次只加入一类人工约束，避免多个变量同时变化。
- 每步都保存独立 output dir，禁止覆盖前一步结果。
- 每步都记录：
  - 输入文件和命令。
  - 是否生成 `run_summary.json`。
  - `aggregate_collision_ok`、`global_validator_ok`、`mujoco_ok`、`scene_hypergraph_validation_ok`。
  - 主要 conflict 对象对。
  - 是否存在资源峰值、断连、exit 137。
- 能泛化的才作为优化建议；只对单图生效的约束只能作为诊断，不应进入默认策略。

## 3. 推荐断点序列

### Step A: 原始输入基线

目的：确认不加人工约束时，错误从哪个阶段开始出现。

建议使用：

```bash
--scene-graph-file examples/bedroom_21_08_44/scene_graph_auto_v1.json
--asset-source-image-dir examples/bedroom_21_08_44/source_images
--asset-source-image-required
--no-clean-assets
```

检查重点：

- `run_summary.json`
- `aggregate_collision_report.json`
- `global_validator_report.json`
- `incremental_branch_report.json`
- `scene_hypergraph_validation_report.json`
- `fine_spatial_order_report.json`

记录问题类型：

- 是否主要是 support validity。
- 是否主要是 floor root 互相碰撞。
- 是否主要是 reference order mismatch。
- 是否主要是 branch execution failed。
- 是否主要是 MuJoCo instability。

泛化判断：

- 如果错误集中在小物体不在桌面/床头柜上，则应优先优化 support/surface 约束。
- 如果错误集中在大件前后顺序，则应优先优化 reference spatial order。
- 如果错误集中在窗帘/窗杆/窗户，则应优先优化 wall fixture assembly 约束。

### Step B: 固定房间与墙体坐标约束

目的：防止后续布局在 room axis、wall id、front/back 上产生系统性偏移。

适合加入的人工约束：

- room width/length 不变。
- wall_north/wall_south/wall_east/wall_west 与参考图方向一致。
- 床头、窗户、画框、衣柜等固定 wall affinity。

不建议加入：

- 精确到厘米级的每个对象坐标。
- 针对单个图像裁剪误差的硬编码偏移。

泛化价值：

- 室内图像的墙体方向错误会影响所有后续空间关系。
- 固定 wall affinity 是可泛化的，因为墙面附着物和靠墙大件通常应由 reference image 稳定推断。

### Step C: 大件 floor anchor 约束

目的：先稳定主要家具，再让小物体依附到正确 surface。

建议人工约束对象：

- bed
- desk
- chair
- wardrobe
- rug
- nightstands

建议约束类型：

- 大件的相对前后顺序。
- bed against back wall。
- nightstands 位于 bed 左右两侧。
- desk/chair 是工作区 cluster，不应被错误绑定为支撑关系。
- rug 是 underlay，不应被普通 collision 当作硬阻挡。

不建议约束：

- 每个大件绝对坐标。
- 每个对象 yaw 的精确值，除非已有 reference pose 明确支持。

泛化价值：

- 大件 floor anchors 决定全局布局质量。
- `rug` 作为 visual underlay 的处理可泛化到大多数卧室/客厅场景。

### Step D: support surface 约束

目的：针对当前常见失败：小物体没有正确落在 nightstand/desk top 上。

建议约束：

- `alarm_clock on left_nightstand`
- `bedside_table_lamp on left_nightstand`
- `potted_plant on right_nightstand`
- `white_mug on right_nightstand` 或 `on desk`，以 reference 为准。

约束应表达为语义关系和 support 关系，而不是绝对坐标。

检查重点：

- `support_surface_registry.json`
- `support_surface_application_report.json`
- `tabletop_sibling_scale_packing_report.json`
- `global_validator_report.json` 中的 `support_validity`

泛化价值：

- 桌面/床头柜小物体 support 是通用室内布局问题。
- 优化方向应是让 support relation 更早、更硬地进入 plan，而不是后处理才补救。

### Step E: wall fixture assembly 约束

目的：隔离窗户、窗帘、窗杆、画框等 wall-attached objects 的碰撞和错位。

建议约束：

- curtain rod 与 curtain panel 属于同一 wall fixture cluster。
- curtain panel 与 rod 允许轻微接触/重叠，不应作为普通硬碰撞处理。
- framed art 挂在 bed 上方墙面。
- window/curtain 依附同一 wall，但 panel 不应穿过 rod 或离窗过远。

检查重点：

- `wall_local_layout_plan_report.json`
- `wall_pose_constraint_normalization_report.json`
- `same_wall_collision_repair_report.json`
- `scene_hypergraph_validation_report.json`

泛化价值：

- wall fixture cluster 是卧室、客厅、办公室常见结构。
- 允许装配件之间的合理接触，比单图坐标约束更可泛化。

### Step F: branch execution 失败反馈诊断

目的：确认当前代码报告中的 `suggested_action: rerun_branch_executor_with_error_feedback` 是否集中指向某类 branch。

检查：

```bash
python -m json.tool "$OUT/global_validator_report.json"
python -m json.tool "$OUT/incremental_branch_report.json"
```

记录：

- failed branch root。
- failed conflict type。
- 是否是 stale collision。
- 是否是 support validity。
- 是否是 strict small object pose。

泛化判断：

- 如果多数 branch failure 是 support validity，应优化 support relation 输入。
- 如果多数 branch failure 是 locked branch collision，应优化 branch candidate 或 fixture assembly。
- 如果 failure 在最终 aggregate 已修复但仍被记录，应考虑在报告层区分 stale diagnostics 与 active failures。

### Step G: fine spatial order 约束

目的：定位 `fine_spatial_order` 被拒绝的根因。

当前已有结果显示：

```text
fine_spatial_order_accepted=false
reason=rejected_collision_or_physics_regression
```

测试策略：

- 先不加入细粒度空间顺序约束，只保留大件 anchor 和 support 关系。
- 若 collision/support 已明显改善，再加入前后/左右细粒度 order。
- 每次加入后检查 `fine_spatial_order_report.json` 中：
  - `pre_conflict_count`
  - `post_conflict_count`
  - `collision_regression`
  - `mujoco_regression`
  - unresolved required relations

泛化价值：

- 细粒度 order 应在 support/collision 基本稳定后生效。
- 如果过早强加细粒度关系，容易让修复器在 collision 与 reference order 之间震荡。

## 4. 人工约束文件建议格式

优先使用与现有 Flow2 输入兼容的结构化约束。若当前代码已有 `--human-constraints-file` 支持，应尽量用它，而不是修改 scene graph 内部逻辑。

建议约束类型包括：

```json
{
  "relations": [
    {"subject": "alarm_clock", "type": "on", "object": "left_nightstand"},
    {"subject": "bedside_table_lamp", "type": "on", "object": "left_nightstand"},
    {"subject": "wooden_bed", "type": "against", "object": "wall_north"}
  ],
  "spatial_order": [
    {"axis": "front_to_back", "before": "wooden_bed", "after": "area_rug", "confidence": 0.9}
  ],
  "wall_affinity": [
    {"object": "left_window", "wall": "wall_west"},
    {"object": "blue_curtain_panel", "wall": "wall_west"}
  ],
  "clusters": [
    {
      "id": "bedside_left_cluster",
      "type": "support_cluster",
      "root": "left_nightstand",
      "children": ["alarm_clock", "bedside_table_lamp"]
    }
  ]
}
```

实际字段应以当前 `run_tree_sage_scene.py` 对 `human_constraints_file` 的解析为准；若字段不兼容，应只使用已有解析器支持的字段。

## 5. 推荐输出目录命名

每步使用独立目录：

```bash
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_a_baseline
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_b_wall_room
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_c_floor_anchors
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_d_support
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_e_wall_fixture
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_f_branch_feedback
/data/wsj/main/scene_runs/tree_sage_flow2/protect_bedroom_step_g_fine_order
```

每步都保留：

- `full_no_clean.log`
- `run_summary.json`
- `scene_plan.json`
- `global_validator_report.json`
- `aggregate_collision_report.json`
- `incremental_branch_report.json`
- `scene_hypergraph_validation_report.json`
- `preview_topdown.png`
- final render png

## 6. 运行策略

短期建议固定：

```bash
--reuse-asset-dir "$PREV/assets_trellis2"
--no-clean-assets
--asset-source-image-required
```

原因：

- 当前目标是定位 layout/constraint 问题，不应让 asset cleanup 资源峰值干扰实验。
- 已验证跳过 cleanup 后完整主流程可跑通。
- 复用同一批 assets 可减少变量。

不建议在断点实验中同时改变：

- 模型。
- source images。
- texture size。
- decimation target。
- TRELLIS pipeline type。
- cleanup 开关。

## 7. 泛化优化候选

如果断点实验确认问题稳定出现，可向原仓库提出以下不改框架的优化建议：

### 7.1 资源保护

- 对 `bed`、`rug`、`curtain panel`、`wall art` 等大/薄/高纹理资产默认跳过 aggressive cleanup。
- cleanup 对象按类别启用，而不是全部对象默认启用。
- 对大 GLB 或大 mesh 仅做 registry QA，不做 split/export。
- cleanup 失败或超内存时 fallback 到 copy 原资产，并写入 report。
- 将 asset cleanup 设计为“流式安全执行”而不是 monolithic mesh 清理：
  - 每次只处理一个对象，独立 worker 子进程加载/清理/导出，主进程只收集 report。
  - 每个 worker 结束后释放进程级内存，而不是依赖 Python `gc` 回收 `trimesh` 中间对象。
  - 在每个对象之间记录 `free -h`、worker peak RSS、输入 GLB 大小、mesh/face/component 数量。
  - 设置单对象超时和内存阈值；超过阈值时终止该对象 cleanup，copy 原资产并标记 `cleanup_skipped_resource_guard`。
  - 按风险排序慢慢跑：先小物体和刚性家具，再 bed/rug/curtain/art 这类高风险大薄片资产。
  - 对 wall art、rug、curtain panel 这类扁平资产优先做轻量 metadata QA，只有确有必要再进入 split/export。
  - cleanup report 必须区分 `cleaned`、`copied_without_cleanup`、`skipped_by_resource_guard`、`failed_and_reused_original`，避免后续把未清理资产误认为已修复。
- 该方案暂不作为当前严格从头测试的前置条件；当前优先级仍是先验证 fresh asset generation 基础设施和 layout/support 问题。

### 7.2 support 优先

- 小物体 support relation 应早于细粒度 spatial order 应用。
- 对 tabletop children 先执行 support snap 和 sibling packing，再进入 global validator。
- 对 support validity 失败的对象优先修 `support_id/z/x/y`，而不是先修全局位置。

### 7.3 floor anchor 保护

- 大件 floor anchors 的前后/左右顺序应作为高置信约束，但避免绝对坐标硬编码。
- `rug` 应作为 visual underlay 或 soft collision 对象处理。
- bed/nightstand/desk/chair cluster 应优先保持功能关系。

### 7.4 wall fixture cluster

- window/curtain/rod/art 等 wall-attached 物体应在同一 wall-local coordinate 中处理。
- 装配件内部允许小幅合理接触，避免普通 collision 规则误杀。
- wall fixture repair 应在 final global validator 前重新刷新 branch audit。

### 7.5 validator 报告分层

- 区分 active failures 与 stale diagnostics。
- 若最终 aggregate collision 已修复，旧 branch collision 不应继续导致 global validator hard fail。
- support validity、reference order、MuJoCo instability 应分别计分，避免一个报告混合所有失败源后难以定位。

## 8. 成功标准

单步测试成功不要求所有指标全绿。分阶段标准如下：

- Step A 成功：能复现 baseline failure，且报告完整。
- Step B 成功：room/wall 相关 warning 不增加。
- Step C 成功：floor anchor collision 和 reference order warning 减少。
- Step D 成功：support validity conflicts 明显减少。
- Step E 成功：wall fixture locked collision 减少。
- Step F 成功：failed branches 可归类为少数稳定原因。
- Step G 成功：fine spatial order 不再因 collision/mujoco regression 被回滚，或至少能明确回滚原因。

最终理想目标：

```text
aggregate_collision_ok=true
global_validator_ok=true 或 active hard failures 显著减少
scene_hypergraph_validation_ok=true
mujoco_ok=true
```

若无法全绿，也应产出明确结论：

```text
当前失败是 support、branch、reference order、asset geometry 还是 MuJoCo 侧问题。
```

## 9. 不应采用的优化

以下做法容易过拟合，不建议作为原仓库优化依据：

- 给单个对象写死最终坐标。
- 只为了当前图片强行删除 validator。
- 关闭所有碰撞检测。
- 把所有 branch failure 都当作 stale。
- 为了通过 MuJoCo 任意缩小物体尺寸。
- 为了避开 cleanup OOM 永久禁用所有 asset QA，而不记录风险。
- 直接改 agent prompt 让其记住某张卧室图的对象位置。

## 10. 下一步建议

先从 Step A 到 Step D 执行，优先定位 support validity 和 floor anchor 问题。

若 Step D 后 `aggregate_collision_report` 只剩少数 wall fixture 或 reference order 问题，再继续 Step E-G。

若 Step D 后质量仍无改善，应回头检查 scene graph 中对象关系是否已经错误，而不是继续增加后处理约束。
