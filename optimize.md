# TreeSAGE 尺寸估计问题与优化记录

## 目的

本文记录 WebUI plan-only 任务
`webui_plan_smoke_v1_1784101264-59fe269d` 中严重尺寸异常的证据、根因、已选方案、
实现范围、验证结果和后续可选方向。

当前已执行用户选择的 **方案 A：保守止血**，并在新一轮 plan-only 暴露书桌墙面误判后，
继续实施 **方案 B：墙面关系解耦、候选仲裁与家具薄轴保护**。本轮不引入基于深度的绝对尺度估计，
不增加额外尺寸审查 Agent，也不重构完整布局框架。

## 问题表现

原始 scene graph agent 给出的尺寸基本合理：

| 对象 | Agent 原始尺寸（m） | 旧 normalize 后（m） | 旧 reference scale 后（m） |
| --- | --- | --- | --- |
| `left_slipper` | `0.12 x 0.28 x 0.07` | `1.10 x 0.825 x 0.2475` | `2.80 x 1.764 x 0.035` |
| `right_slipper` | `0.12 x 0.28 x 0.07` | `0.99 x 0.66 x 0.051` | `2.80 x 1.764 x 0.035` |
| `floating_shelf` | `0.90 x 0.18 x 0.05` | `1.045 x 0.209 x 0.855` | 保留错误高度 |
| `desk` | `1.25 x 0.62 x 0.75` | `1.25 x 0.16 x 0.75` | `1.25 x 0.75 x 0.75` |

证据入口：

- 原始 Agent 输出：
  `/data/wsj/main/scene_runs/webui/runs/webui_plan_smoke_v1_1784101264-59fe269d/initial_scene_graph_raw.json`
- 旧 reference scale 报告：
  `/data/wsj/main/scene_runs/webui/runs/webui_plan_smoke_v1_1784101264-59fe269d/reference_scale_prior_report.json`
- 旧 scale 写回报告：
  `/data/wsj/main/scene_runs/webui/runs/webui_plan_smoke_v1_1784101264-59fe269d/object_scale_prior_report.json`

## 根因

### 1. normalize 无条件覆盖合法 Agent 尺寸

旧 `normalize_scene_graph()` 对每个对象无条件调用 `_default_dimensions()`。
`_default_dimensions()` 又使用由 `id + category + description + asset_prompt` 组成的文本做
首个子串匹配，导致关系描述中的其他对象名称改变当前对象的物理类别：

- `slipper ... near ... bed` 命中 bed 尺寸规则。
- `slipper on the rug` 命中 rug 尺寸规则。
- `desk under the window` 进入 window 厚度限制。
- `rug under ... bed` 先命中 bed 规则。
- `floating shelf` 被通用 shelf/bookcase 下界放大。

### 2. floor-covering 判断读取关系描述

旧 `_is_floor_covering()` 使用包含 description 的 `_object_identity_text()`。
两只 slipper 的 description 含有 `rug`，即使：

```text
category=slipper
semantic_class=decor
```

仍被判为 `floor_covering`。

### 3. 错误类别被高置信度放大

错误的 floor-covering 基础置信度为 `0.58`，存在 bbox 增加 `0.06`，进入错误的
same-kind 分组再增加 `0.06`，最终 `0.70` 超过 `0.52` 阈值。

房间为 `5.2 x 4.2 m` 时，floor-covering 公式直接产生：

```text
min(5.2 * 0.58, 2.8) x min(4.2 * 0.42, 2.2) x 0.035
= 2.8 x 1.764 x 0.035 m
```

### 4. 缺少类别级硬保护和大倍率写回保护

旧代码没有 footwear 专属范围，generic 上限允许接近房间尺度；reference prior 即使将某一轴
放大十倍以上，也可以直接覆盖当前尺寸。

## 已实施方案 A

实现文件：`sage/scripts/run_tree_sage_scene.py`。

### A1. 保留合法 Agent 尺寸

`normalize_scene_graph()` 现在优先使用 `_validated_dimension_triplet()` 返回的正数有限尺寸；
只有尺寸缺失或非法时才调用 `_default_dimensions()`。

### A2. 分离对象身份和关系上下文

新增 `_object_dimension_identity_text()`，只包含：

```text
id + category + semantic_class + layout_role
```

description 和 asset prompt 不再参与物理尺寸类别判断。

### A3. 修正 floor-covering 与 footwear 分类

- `_is_floor_covering()` 改为使用 identity-only 文本。
- 新增 `_is_footwear_object()`。
- 排除 `shoe rack`、`shoe cabinet`、`shoe storage`、`boot rack` 等储物类身份。
- `_scale_kind()` 对 footwear 返回独立 `footwear` kind。
- 当 scene graph 已有明确 semantic class 时，不再允许 description fallback 改写物理身份。

### A4. 补充保守物理范围

footwear 范围：

```text
width:  0.06–0.28 m
length: 0.12–0.45 m
height: 0.015–0.20 m
```

缺失尺寸的 floating/wall shelf 使用低矮墙板默认值，而不是完整书架默认值。

### A5. 拒绝大倍率 reference-scale 写回

新增环境变量：

```text
SAGE_REFERENCE_SCALE_PRIOR_MAX_AXIS_RATIO
```

默认值为 `2.0`。仅对 `reference_scale_estimator` 生效；如果任一轴候选尺寸与当前尺寸的
双向倍率超过上限，则不写回，并在 `object_scale_prior_report.json` 中记录：

```text
reason=excessive_reference_scale_change
before
candidate
max_axis_ratio
limit
```

显式 `scale_prior_plan` 不受该保护影响，避免阻断用户明确提供的尺度覆盖。

## 自动化测试

新增：

```text
tests/test_dimension_estimation_guards.py
```

覆盖：

1. normalize 保留 slipper、desk、floating shelf 的合法 Agent 尺寸。
2. `slipper on rug near bed below window` 仍为 footwear，不是 floor covering。
3. identity-only 默认值不受关系对象名称污染。
4. footwear 使用专属物理边界。
5. reference scale 单轴变化超过 2 倍时拒绝写回。

验证命令：

```bash
cd /data/wsj/main/scene
source .env
"$SAGE_ORCH_PYTHON" -m py_compile \
  sage/scripts/run_tree_sage_scene.py \
  tests/test_dimension_estimation_guards.py
PYTHONPATH=/data/wsj/main/scene/sage/scripts:/data/wsj/main/scene \
  "$SAGE_ORCH_PYTHON" -m unittest -v tests.test_dimension_estimation_guards
```

结果：`Ran 5 tests ... OK`。

## 当前失败输入的离线重放结果

使用原任务的 `initial_scene_graph_raw.json`，依次重放：

```text
normalize_scene_graph
→ build_reference_scale_prior_report
→ apply_object_scale_priors
```

未调用 Codex、Trellis2 或 Blender。

| 对象 | 新 normalize（m） | kind | reference prior（m） | 写回后（m） |
| --- | --- | --- | --- | --- |
| `left_slipper` | `0.12 x 0.28 x 0.07` | `footwear` | 相同 | 相同 |
| `right_slipper` | `0.12 x 0.28 x 0.07` | `footwear` | 相同 | 相同 |
| `floating_shelf` | `0.90 x 0.18 x 0.05` | `generic` | 相同 | 相同 |
| `desk` | `1.25 x 0.62 x 0.75` | `table` | `1.25 x 0.75 x 0.75` | `1.25 x 0.75 x 0.75` |
| `area_rug` | `3.60 x 2.25 x 0.02` | `floor_covering` | `2.80 x 1.764 x 0.035` | 相同于 prior |

两只 slipper 和 floating shelf 在写回报告中均为 `already_close`，不再发生错误放大。

## 本方案未解决的范围

1. `scene_plan.json` 中 desk 最终厚度曾被压到 `0.035 m`，这是后续墙面姿态/墙面薄片处理链，
   不是本次 reference-scale 根因；方案 A 尚未修改该链。
2. 合法但由 Agent 严重误估的正数尺寸仍可能进入 normalize；后续类别 bounds 和 2 倍保护只能
   拦截部分错误。
3. 当前没有统一的 `dimension_estimation_report.json`，诊断信息仍分散在 scene graph、reference
   scale 和 object scale 报告中。
4. Depth Anything 当前主要提供前后关系，不直接给出可靠的绝对米制尺寸。

## 原后续规划（方案 B 已于本轮实施）

方案 A 完成后规划的方案 B 包括：

- 将物理类别、典型尺寸、hard bounds、aspect ratio 集中到独立 dimensions 模块。
- 建立人工约束、资产元数据、Agent 尺寸、类别先验、bbox 比例之间的明确来源优先级。
- 新增统一的尺寸候选、接受、拒绝和冲突报告。
- 对 category/semantic/kind 冲突实施硬拒绝。

方案 C 可在 B 稳定后再考虑：用 bbox、Depth Anything、房间尺度和相机估计作为相对修正因子，
但不应替代类别级物理硬保护。

## 已实施方案 B：墙面判定与家具薄轴保护

### 新一轮暴露的问题

验证任务：

```text
/data/wsj/main/scene_runs/webui/runs/image_scene_1784109379-3b5a89ad
```

该任务证明方案 A 已消除巨型拖鞋，但书桌仍从 Agent 给出的：

```text
1.25 x 0.62 x 0.74 m
```

在后续墙面姿态链中变为：

```text
1.25 x 0.08 x 0.74 m
```

同时书桌被绑定到 `wall_west`，与右窗帘碰撞，且 `wood_desk_top` 没有进入
`support_surface_registry.json`，导致 desk lamp 报告 `no_registered_support_surface`。

### B1. 解耦墙面接触、邻近和物理挂载类型

新增 `agent_semantics.wall_affinity`，分别保存：

```text
support_mode
attachment_class
contact_wall
contact_confidence
near_walls
ambiguous
candidate_margin
candidates
```

物理挂载类型分为：

- `floor_against_wall`：书桌、衣柜、床、沙发等落地家具。
- `wall_slab`：窗户、窗帘、门、画、镜子等薄墙板资产。
- `wall_fixture_volume`：墙架等有真实墙法向深度的墙面构件。
- `free_floor`：无墙面接触的普通落地物体。

因此角落书桌现在可以表达为：

```text
support_mode=floor
contact_wall=wall_north
near_walls=[wall_west]
attachment_class=floor_against_wall
```

图像边缘 bbox 只贡献 `near` 证据，不再直接升级为墙面接触。

### B2. 墙面多候选仲裁

新增 `resolve_wall_affinity_candidates()`，候选证据包括：

- `agent_semantics.wall_relation`
- `pose_constraints`
- scene graph 中 `against_wall` / `attached_to` / `near` 关系
- 参考图边缘的邻近证据
- 功能垂直关系，例如 floating shelf `above` desk

同一来源的重复语义采用最大置信度，不进行重复累加，避免一个早期错误被复制到
wall relation、pose constraints 和普通 relation 后形成虚假多数。

候选结果写入现有 `wall_affinity_arbitration_report.json` 的：

```text
candidate_resolution
```

`normalize_wall_pose_constraints()` 优先采用 resolved `contact_wall`；side-wall cluster 和 far-right
branch 在准备覆盖一个已有更强接触墙的功能锚点时会拒绝覆盖并写 warning。

### B3. 家具薄轴硬保护

所有墙法向压缩现在统一通过 `_clamp_wall_slab_thickness()`；只有
`attachment_class=wall_slab` 可以执行 `length <= 0.08/0.12`。

以下信息不再有权修改真实尺寸：

- support tree 暂时将对象放入虚拟墙分支
- `expected_pose=wall_flush`
- `placement_type=attached_to_wall`
- bbox 靠近图像边缘
- side-wall layout branch

`build_plan_from_scene_graph()` 在遇到错误的 `desk attached_to wall` 输入时，会先识别其为
`floor_against_wall`，保持地面支撑并保留完整尺寸。墙架属于 `wall_fixture_volume`，因此也保留
真实进深；窗户、画和窗帘等 `wall_slab` 仍可正常压缩墙法向厚度。

### B4. 尺寸来源与软 near-wall 约束

normalize 后新增：

```text
_dimension_baseline
_dimension_baseline_source
```

用于保留 Agent 合法尺寸来源，并传递到 scene plan。

另外，`near wall` 不再等价于 `against wall`：新增 `_nudge_floor_object_near_wall()`，只在对象离墙过远时
将其移动到邻近范围，不改变 yaw，也不强制接触墙面。

### B5. 修复桌面支撑面的同源身份泄漏

原 `_is_table_or_desk()` 使用包含 asset prompt 的 `_category_text()`。真实书桌 prompt 中的
`rectangular tabletop` 先命中排除词 `tabletop`，导致书桌被判断为非 table/desk，无法注册顶面。

现在 table/desk 支撑分类只读取 identity-only 字段；关系描述和资产 prompt 不再改变支撑类别。

### 自动化测试与离线全链重放

`tests/test_dimension_estimation_guards.py` 现有 8 项测试，新增覆盖：

1. `wall_north` 接触和 `wall_west` 邻近可以同时表达。
2. 侧墙功能簇不能覆盖更强的 contact wall。
3. 只有 wall slab 可进行薄轴压缩。
4. wall fixture volume 的真实进深保留。
5. 即使书桌错误地以 `attached_to wall` 进入 support tree，仍保持落地和原始尺寸。
6. 书桌最终必须生成 `desk_top` / `wood_desk_top` 支撑面。

验证结果：

```text
Ran 8 tests in 0.004s
OK
```

对新一轮真实 `initial_scene_graph_raw.json` 做无 Codex/Trellis/Blender 的离线链路重放，补入该轮
relation verifier 与 spatial-order agent 已产生的 north-wall / shelf-above-desk 证据后，结果为：

```text
contact_wall=wall_north
near_walls=[wall_west]
candidate_margin=0.075
final desk dimensions=1.25 x 0.75 x 0.75 m
placement_type=floor
registered support surface=wood_desk_top
```

侧墙 refiner 明确写出：

```text
side_wall_cluster_rejected_by_contact_wall
```

说明 west-wall bbox/cluster 证据不再覆盖更强的 north-wall 接触证据。

### 尚待在线验证

当前已完成静态编译、8 项 unittest、CLI `--help` smoke 和真实输入离线重放；尚未重新调用 WebUI
Agent 完成一轮新的在线 plan-only。因此下一轮应重点检查：

- `wall_affinity_arbitration_report.json -> candidate_resolution`
- `wood_desk.agent_semantics.wall_affinity`
- `scene_plan.json` 中书桌尺寸和 `contact_wall`
- `support_surface_registry.json` 是否包含 `wood_desk_top`
- 窗帘/书桌碰撞和 branch failed count 是否下降
