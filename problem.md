# Scene V2 待解决问题与执行断点

最后更新：2026-09-01

## 1. 文档目的

本文档集中记录当前讨论中发现、但尚未进入代码修复阶段的问题，供正在运行的任务结束后由 Codex
统一分析和解决。

当前阶段只允许：

- 记录问题、证据、影响、假设和验收标准。
- 对已有文件做只读核对。
- 补充后续执行思路。

当前阶段禁止：

- 修改正在运行的代码、配置、checkpoint 或输出。
- 覆盖、清理或“修饰”既有实验产物。
- 在当前任务结束前启动新的模型生成、Blender 装配或完整回归。

## 2. 执行原则

运行结束后，Codex 应按以下原则处理本文档中的问题：

1. **执行成功前持续思考和迭代。** 一次代码修改、一个单元测试通过或一个局部渲染正常，都不代表
   问题已经完成。若验证失败，应保留失败证据，更新根因假设，继续下一轮最小修复与验证。
2. **先复现和定位，再修改。** 先确认最终产物、layout、typed graph、资产元数据、实例组、朝向解析和
   Blender 装配之间的数据流，禁止仅凭渲染结果硬改坐标或 yaw。
3. **修复通用机制，不为单个场景写特判。** 修复应落在实例组传递、canonical front、墙面朝向求解、
   checkpoint 恢复或最终全场景验收等正确抽象层。
4. **逐层验证。** 推荐顺序为：结构化数据检查 -> 定向单测 -> 本地 plan/layout 回归 -> Blender GLB
   回读 -> 近景人工检查 -> 完整场景回归。
5. **不破坏历史证据。** 旧 GLB、旧 JSON、失败截图和日志均保留；新结果写入新的独立输出目录。
6. **只有满足该问题的全部验收标准，才可标记为完成。** 如果遇到必须由用户授权、外部服务或新数据
   才能解除的真实阻塞，应明确记录阻塞证据和恢复条件，不能把“暂时无法继续”写成成功。
7. **每完成一个问题，立即在本文档记录一个断点。** 断点必须包含修改范围、验证命令、关键结果、
   新产物路径、仍存在的风险和下一问题入口，确保后续 Codex 可以从该位置继续而不重复工作。

## 3. 问题索引

| ID | 问题 | 状态 | 严重度 | 当前结论 |
|---|---|---|---|---|
| P001 | 床尾拖鞋没有形成正确的左右鞋实例组 | 已完成 | 高 | 已恢复 pair contract、人体左右角色、单侧镜像与床锚点朝向 |
| P002 | 西墙衣柜的功能面朝向墙外 | 已完成 | 高 | 已按实际西墙接触面重算 yaw，柜门朝向室内 |
| P003 | 最终交付审计未覆盖全场景既有语义回归 | 已完成 | 高 | target/whole-scene 双门已覆盖 typed graph、实例组、朝向、support、opening、操作净空、关系几何和 GLB 变换 |
| P004 | 当前成果无法从一个受控代码版本完整复现 | 已完成 | 最高 | 正式源码、外部补丁、模型/环境指纹已冻结，干净检出 CPU、Blender 与最终审计复现通过 |
| P005 | QA、缓存和恢复证书没有闭合内容哈希链 | 已完成 | 最高 | generation、候选、staged、pilot 与四视图 QA 已形成规范化内容链，任一绑定输入变化都会失效 |
| P006 | “运行成功”与“完整可交付”没有统一机器定义 | 已完成 | 最高 | 四类 profile 与统一终态机已落地，只有 production 全部必需阶段闭合才可 deliverable=true |
| P007 | 重任务资源门和 TRELLIS bridge 缺少统一调度 | 已完成 | 最高 | lease broker 已统一 NVML/RAM/I/O/disk/cgroup admission，单 GPU 限一任务并以 429 背压 |
| P008 | 流程恢复仍依赖文件存在，缺少显式阶段 DAG | 已完成 | 高 | 11 阶段 content-addressed DAG 已接入 pipeline，resume 精确复用/失效并原子记录 attempt |
| P009 | Schema、坐标契约和运行环境缺少强约束与锁定 | 已完成 | 高 | 七类核心文档已有可执行强契约与规范化哈希，production 启动前强制核验四类运行时锁 |
| P010 | 最终 GLB 面数和体积明显过高 | 已完成 | 高 | 当前卧室已降至 88.7MB/992,676 faces，P001-P003、四条关系和多通道视觉 A/B 无回归 |
| P011 | 关系几何证书仍不是严格精确谓词证明 | 已完成 | 中高 | native expansion exact 谓词、局部 SDF 细化、全顶点 containment、持久目标索引和真实失败率已闭环 |
| P012 | 诊断渲染可用，但最终视觉表现和相机质量不足 | 已完成 | 中 | 双 profile、双机位覆盖搜索、最终分辨率对象掩码和成片质量门已闭环 |
| P013 | 缺失资产生成与长期资产库仍未形成正式闭环 | 已完成 | 高 | 生成子流、精确数量门、临时准入、显式生命周期与三资产/双风格审核库已闭环 |
| P014 | 测试以快速单测为主，缺少真实集成与故障恢复验证 | 待解决 | 高 | 测试全过仍不能证明 Blender/TRELLIS/恢复链可靠 |
| P015 | 三条流程和多份文档缺少统一事实源 | 待解决 | 中高 | V2、旧图生、旧文生以及文档口径仍在漂移 |
| P016 | WebUI 只是启动面板，尚不是可恢复的任务控制系统 | 待解决 | 中低 | 服务重启后缺少事务状态、队列和任务重新关联 |

状态只使用：`待讨论`、`待解决`、`处理中`、`验证中`、`已完成`、`真实阻塞`。

## 4. 当前问题详情

### P001：床尾拖鞋没有形成正确的左右鞋实例组

#### 现象

最终预览中的两只拖鞋摆放方向和左右手性明显异常：视觉上更像两个同型鞋体被横向排列，而不是
一双左右脚拖鞋沿床的功能前向平行摆放。

涉及最终产物：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_trellis2_20260829_v2/scene_sdf_complex_bedroom.glb
```

#### 已确认的结构化证据

`layout_plan_final.json` 中：

- `explicit_slipper_1` 与 `explicit_slipper_2` 均使用 `slipper_blue_left_001`。
- 两个实例均为 `yaw=0`。
- 两个实例虽然带有 `instance_group_id="explicit_slipper_pair"`，但顶层
  `instance_groups=[]`。
- `instance_group_resolution.group_count=0`、`adjusted_count=0`，说明组级后处理没有执行。
- 两个实例均未记录 `asset_reflection_axis`。
- 本次 plan 仍记录旧的 `asset_canonical_front.axis="+y"`；项目后续审核结论已经指出该资产的
  canonical front 应为 `+x`，且源几何实际是人体右鞋。

#### 影响

- 左右鞋手性没有得到验证，两只鞋可能是同一只脚的重复几何。
- 分离方向与鞋头方向没有基于床的 canonical front 求解。
- 当前摆法不符合可穿戴物件的自然使用状态。
- 说明最终 SDF 场景可能从旧卧室 plan 继承了拖鞋回归，而没有继承
  `bedroom_complete_relation_geometry_20260822_v3_anatomical_slippers` 中已经验证的修正逻辑。

#### 优先根因假设

1. SDF 复杂卧室准备阶段使用了早于 anatomical-slipper v3 的基础 plan。
2. plan 拷贝、场景合并或 checkpoint 恢复时只保留了对象上的 `instance_group_id`，丢失了顶层
   `instance_groups` 和 group contract。
3. 资产解析阶段没有重新读取最新 overlay manifest，因而保留了旧 canonical front。
4. 最终装配前没有运行 handedness hard gate，或最终交付审计没有读取该 gate。

#### 预期修复方向

- 追踪 `SceneBrief -> instance_groups -> asset resolution -> layout -> geometry stage -> Blender`
  的完整传递链，找到 group contract 丢失位置。
- 使用正式左右 bundle；没有真实 bundle 时，只允许同一审核源资产恰好一份做 canonical-local 横向镜像。
- 从审核资产元数据推导 source anatomical role、requested role、反射奇偶和 medial axis，禁止从文件名或
  画面左右猜测人体角色。
- 组级 heading 应以床的 canonical front 为 anchor，使两鞋鞋头同向、内侧相向、横向并列。
- 将实例组完整性和 handedness gate 加入最终全场景交付审计，而不只依赖对象局部字段。

#### 完成验收标准

- 顶层 `instance_groups` 中存在合法的拖鞋 pair contract，成员、角色、anchor 和 cardinality 完整。
- 两只鞋推导角色恰好为 `[left, right]`。
- 使用真实左右 bundle，或同一审核源资产且恰好一个成员做审核允许的横向镜像。
- 两鞋世界前向与床的功能前向一致，medial-facing 检查均通过。
- 导出 GLB 不保留负 determinant；镜像正确烘焙到 mesh。
- 近景可明确看出左右鞋平行、鞋头同向、内侧相向，且不位于主要通行线中央。
- 鞋子修复后，书架三排 containment、椅子 tucked-under 和其他既有硬约束无回归。

### P002：西墙衣柜的功能面朝向墙外

#### 现象

左前方大衣柜虽然贴近西墙，但柜门功能面朝向西侧墙外；从房间内部主要面对柜体背面。这不是单纯
构图问题，而是家具无法正常使用的功能朝向错误。

#### 已确认的结构化证据

`layout_plan_final.json` 中：

- 衣柜中心为 `x=0.39, y=0.88`，实际位于西墙。
- `preferred_wall` 仍为 `east`，与最终位置不一致。
- `asset_canonical_front.axis="-y"`、置信度 `0.9`。
- 最终 `yaw=270`；按该 canonical front 旋转后，世界功能面朝西，而不是朝东进入房间。
- `orientation_resolution=[]`，说明本轮没有留下重新求解衣柜朝向的记录。

项目已有正确对照结论：西墙上的同一衣柜应使用约 `yaw=90`，使 canonical `-y` 转为世界 `+x`
并朝向室内。最终值仍必须由通用 orientation solver 推导，不能为该衣柜硬编码 90 度。

#### 影响

- 柜门和把手朝墙，衣柜在功能上不可使用。
- `preferred_wall`、实际接触墙和功能面朝向三者互相矛盾。
- 说明物体被迁移到另一面墙时，没有同步重新求解 yaw 或刷新朝向证书。

#### 优先根因假设

1. 衣柜从东墙迁移到西墙后沿用了东墙姿态。
2. SDF 复杂卧室组装复用了旧 layout，未运行通用 `orientation.py` 刷新。
3. `preferred_wall` 与实际 hard/soft `against_wall` 关系没有在 repair 后统一刷新。
4. 最终审计只检查新增 SDF relations，没有检查所有高置信 canonical-front 家具。

#### 预期修复方向

- 在任何墙面迁移、repair 或 checkpoint 恢复后，按实际接触墙的室内法向重新运行通用朝向求解。
- 明确区分 `preferred_wall`、实际 resolved wall 和硬 `against_wall`，最终 plan 中不得留下相互矛盾的
  墙面字段。
- 朝向证书绑定对象 pose、实际墙面、canonical front 和资产 hash；任一输入变化后证书自动失效。
- 最终交付前对所有高置信功能面家具执行 world-front 与 wall inward normal 的夹角验证。

#### 完成验收标准

- 衣柜位置、resolved wall 和墙面关系一致，且不保留错误的 east-wall 元数据。
- 世界功能面朝向房间内部，角误差满足现有高置信朝向硬门。
- 柜门前存在合理操作净空，并且不阻塞入口到床、书桌或衣柜的通路。
- Blender GLB 回读后的真实节点变换与 layout 中的朝向一致。
- 至少一张室内视角能看到柜门和把手朝向房间，而非隔墙外侧。
- 修复不引入窗洞遮挡、墙体穿插或其他家具碰撞。

### P003：最终交付审计未覆盖全场景既有语义回归

#### 现象

`final_delivery_audit.json` 为 `ok=true`，但其核心视觉与几何验收只覆盖：

- 三排书分别 `contained_in` 开放书架。
- 办公椅 `tucked_under` 书桌。
- 必需节点存在、GLB 可加载、资源窗口健康和回归测试通过。

因此 P001/P002 可以在最终交付仍显示成功的情况下被遗漏。

#### 影响

最新生成文件通过的是“本轮新增关系交付”，而不是“完整卧室所有既有语义均无回归”。若继续沿用
该审计范围，未来新增局部能力时仍可能破坏其他家具朝向、实例组、support 或操作净空。

#### 预期修复方向

- 保留本轮四条关系的专项证书，同时增加全场景 non-regression audit。
- 全场景审计至少覆盖：typed graph 完整性、所有 hard relations、功能面朝向、实例组完整性与手性、
  support parent、建筑 opening、入口/通道、静态操作净空和 GLB 回读变换。
- 区分 `target_feature_ok` 与 `whole_scene_ok`，不得用前者替代后者。
- 最终视觉检查表应明确列出每个必需对象，而不是只描述新生成资产。

#### 完成验收标准

- 审计输出同时给出专项关系状态和完整场景状态。
- 人为构造“衣柜朝墙”与“鞋组丢失”fixture 时，全场景审计必须失败。
- 修复后的完整场景中 P001、P002 和原 4 条 relation geometry 全部通过。
- 最终 `ok=true` 只能在所有必需全场景门通过后产生。

### P004：当前成果无法从一个受控代码版本完整复现

#### 价值判断

这是必须保留的最高优先级问题。算法效果再好，如果无法从确定的提交、环境和模型重新生成，就无法
可靠交付、复现实验或安全修改。

#### 当前证据

- 2026-08-31 只读检查：当前分支为 `experiment/reference-soft-layout-prior`，HEAD 为 `b248160`。
- 工作树仍有 24 个已跟踪修改项和 80 个未跟踪条目。
- 当前复杂卧室依赖的部分 V2、关系几何、资源门、SceneDNA、Blender 工具和测试不一定能由 HEAD
  单独恢复。

#### 处理方向与完成标准

- 当前运行结束后先分类工作树：正式代码、测试、文档、实验产物、模型/缓存、个人临时文件。
- 在不误纳入运行产物、模型、密钥或用户实验文件的前提下，建立受控 release commit/tag。
- 生成 release manifest，冻结 Git commit、外部 TRELLIS commit、模型 fingerprint、Python 环境、
  Blender、CUDA/PyTorch 和关键配置。
- 从新的干净 checkout 运行 CPU 回归和至少一个不重新生成资产的 Blender smoke。
- 只有干净 checkout 能复现代码、配置和最终审计逻辑，才可标记完成。

### P005：QA、缓存和恢复证书没有闭合内容哈希链

#### 价值判断

这是最危险的逻辑缺口之一：旧审核文件可能为后来被覆盖的同名 GLB 背书，形成“证书通过、内容已变”
的假安全。

#### 当前证据

- `_require_trellis_multiview_qa()` 目前只检查资产 ID、`accepted` 和总体 `ok`，没有把 QA 中记录的
  GLB hash 与当前源 GLB 重新比较。
- 专项批处理看到旧 `pilot_report.json` 的 `ok=true` 就可跳过，没有绑定参考图、Prompt、seed、模型、
  pipeline 参数和代码版本。
- 通用 `generation_key` 目前主要来自类别、Prompt 和目标尺寸，尚不足以代表完整生成环境。

#### 处理方向与完成标准

- 建立规范化 content key，至少绑定参考图 hash、Prompt、类别、尺寸、seed、模型 fingerprint、RMBG、
  pipeline/steps/texture/decimation 和代码版本。
- 多视图 QA 证书绑定 GLB、所有视图、相机、渲染器、QA 规则和上游 generation key。
- 每次恢复都重新核对当前内容 hash；任一输入变化必须使相关阶段失效。
- 增加三类负向测试：审核后替换 GLB、替换参考图、改变 seed/模型/生成参数；旧证书均必须拒绝。

### P006：“运行成功”与“完整可交付”没有统一机器定义

#### 价值判断

这是从高级原型走向可信产品的核心问题。现在命令退出 0 可能只表示 plan 成功，并不表示资产生成、
装配、渲染和最终验收都完成。

#### 当前证据

- CLI 默认 `--asset-mode=plan`，默认不等于真实缺失资产生成。
- 装配、MuJoCo、relation geometry 和最终 RGB/depth/object-index 并非所有运行都强制执行。
- 逃生开关和失败前写出的 summary 可能被下游误读为正式结果。

#### 处理方向与完成标准

- 定义 `plan`、`development`、`production`、`benchmark` 四个明确 profile。
- `production` 强制完成 SceneBrief、建筑、图、资产检索/生成/QA、布局、关系几何、Blender、最终多通道
  渲染、结构/性能检查和哈希审计。
- 输出必须包含 `deliverable` 和不可含糊的 `terminal_status`；诊断失败产物只能标为
  `diagnostic_failure_preserved`。
- 用端到端测试证明缺少任何 production 必需阶段时都不能得到 `deliverable=true`。

### P007：重任务资源门和 TRELLIS bridge 缺少统一调度

#### 价值判断

该问题直接关系到长任务稳定性和其他用户任务安全，应在扩大生成规模前解决。

#### 当前证据

- 专项运行仍依赖已知进程名和固定稳定窗口，新的 CUDA/训练任务可能无法识别。
- `resource_health.py` 的核心门不等于完整 GPU 调度；GPU compute process、显存和温度需要统一纳入。
- bridge 当前每个 `/generate` 请求启动一个后台线程，缺少共享队列、明确并发上限和背压。

#### 处理方向与完成标准

- 建立统一 heavy-job broker：NVML GPU 状态、RAM、I/O、磁盘、cgroup 和 lease 共同决定调度。
- 同一 GPU 默认最多一个 TRELLIS heavy job；bridge 超过队列上限返回明确的 busy/429。
- 任务拥有 lease TTL、心跳、异常回收和 systemd/cgroup 资源限制。
- 不再以进程名字作为主要安全依据；固定 3600 秒改为可配置策略。
- 用两个并发请求、GPU 被外部任务占用和 worker 异常退出测试证明不会抢占或无限开线程。

### P008：流程恢复仍依赖文件存在，缺少显式阶段 DAG

#### 价值判断

这是 P005 的系统级修复。仅修几个 hash 检查无法避免以后在其他阶段重复出现 stale checkpoint。

#### 处理方向与完成标准

- 把流程显式化为 `expand -> architecture -> scene_graph -> asset_plan -> asset_generate -> asset_qa ->
  layout -> relation_geometry -> assemble -> render_acceptance -> delivery_audit`。
- 每阶段记录输入/输出 hash、schema、配置、attempt、状态、依赖、耗时和资源峰值，并采用原子提交。
- 恢复时由依赖 hash 自动计算失效范围，不以“文件存在”或单个 `ok=true` 决定复用。
- 模拟任意阶段中断后，应只重跑真正失效的阶段，并且不能混入旧 attempt 产物。

### P009：Schema、坐标契约和运行环境缺少强约束与锁定

#### 价值判断

鞋子和衣柜问题已经说明：字段存在不代表契约完整。弱类型字典、旧 schema 和环境漂移会制造难以察觉
的语义错误。

#### 处理方向与完成标准

- 优先强类型化 SceneBrief、TypedSceneGraph、Asset/QA Certificate、LayoutPlan、Relation Certificate、
  RunManifest 和 FinalDeliveryAudit。
- 明确定义单位、Z-up/Y-up 边界、canonical front、yaw、手性、未知字段策略和 schema migration。
- 使用规范化序列化计算 content hash，旧 schema 必须显式迁移或拒绝。
- 锁定 orchestrator、TRELLIS runtime、Blender tools 和 research 环境，并在启动前执行 preflight。
- 用旧字段、错误单位、错误轴向和缺失实例组构造测试，确保不会静默通过。

### P010：最终 GLB 面数和体积明显过高

#### 价值判断

这是明确而有价值的工程问题，但应在 P004-P009 稳定地基后处理，避免优化不可复现的流水线。

#### 当前证据

- 当前复杂卧室 GLB 为 252,089,564 bytes。
- 历史审阅统计整个场景约 340 万 faces；仅书架和三排书就接近 197 万 faces。
- 对简单书排和方正柜体统一使用接近 500k 的预算，性价比很低。

#### 处理方向与完成标准

- 使用类别/曲率/轮廓复杂度感知的面数预算，而不是统一 500k。
- 减面验收同时检查轮廓、法线、UV/材质、接触面、capability 槽位和关系证书。
- 逐步加入重复资产实例化、材质去重、meshopt/Draco、KTX2 和 LOD。
- 第一阶段目标：当前卧室低于 100 MB、约 100 万 faces 或更低，同时 P001-P003 和全部视觉关系无回归。

### P011：关系几何证书仍不是严格精确谓词证明

#### 价值判断

这是有前景的研究升级，但不是当前最先处理的阻塞。现有双向代理加三角终检已经比 AABB 强很多，应在
保留诚实置信等级的基础上继续升级。

#### 处理方向与完成标准

- 接入小型 native exact-predicate backend，并缓存静态目标 BVH。
- SDF ambiguous 比例过高时自动局部细化到更小 pitch；containment 增加可靠内外分类。
- 代理和 capability 证书绑定内容 hash，并记录可量化误差上界。
- exact backend 不可用时明确标为 `floating_point_verified`，不能使用含糊的“精确验证”。
- 在多种真实桌椅、书架/容器和接触关系上统计失败率后，才讨论替换默认 repair。

### P012：诊断渲染可用，但最终视觉表现和相机质量不足

#### 价值判断

这是用户最容易感知的问题，但不能靠后期渲染掩盖 P001/P002 这类结构错误。应在全场景语义门通过后
优化。

#### 当前问题

- 书架内壁、书本和部分木材有颗粒/噪点。
- 家具大多为相近浅木色，材质层次不足。
- 白墙、黑窗外和强调墙的曝光关系突兀。
- 全景相机遮挡衣柜或裁切家具，更像诊断图而非成片。

#### 处理方向与完成标准

- 分离“关系证据图”和“最终展示图”两个渲染 profile。
- 固定 Cycles/denoise、AgX/Filmic、白平衡、曝光和材质尺度规范。
- 自动搜索满足 required-object coverage、关系可见性和构图的相机候选。
- 增加过曝、纯黑窗洞、噪声和对象裁切指标，并保留人工最终复核。

### P013：缺失资产生成与长期资产库仍未形成正式闭环

#### 价值判断

第一轮书排生成成 10 本、6 本已经证明“GLB 可加载”远远不够。该问题直接决定系统能否从任意 Prompt
稳定补全资产。

#### 处理方向与完成标准

- 正式子流程应覆盖资产合同、2D 候选、alpha/语义/数量 QA、TRELLIS、多视图、尺寸、朝向、拓扑、
  capability 和临时入场证书。
- 对“五本书”等要求建立显式 count contract，正反面必须对应同一组对象，侧面不得出现第二排。
- 区分 `generated_for_run`、`scene_specific_approved`、`candidate_for_curation`、`curated` 和
  `rejected/deprecated`，禁止单场景成功自动入长期库。
- 高频类别逐步达到至少 3 个审核资产和 2 种风格签名，并包含 front、手性、尺寸策略、能力、许可证、
  QA hash 和已知失败场景。

### P014：测试以快速单测为主，缺少真实集成与故障恢复验证

#### 价值判断

282 项测试快速通过是优点，但不能代表 GPU、Blender、恢复、并发和完整交付可靠。

#### 处理方向与完成标准

- 建立提交级静态检查/单测、CPU integration、Blender headless integration 和 nightly GPU 四层测试。
- 增加 chaos cases：bridge 中断、GLB/metadata 半写入、QA 后替换 GLB、GPU 抢占、磁盘/I/O 压力、
  systemd 残留和旧输出目录污染。
- 每个 P001-P013 修复都必须至少有一个能复现原错误的负向测试。
- CI 产出机器可读的 release/status manifest，而不是手工在多份文档更新测试数量。

### P015：三条流程和多份文档缺少统一事实源

#### 价值判断

这是长期维护问题。若继续把新能力复制回旧 48k 行入口，修复会在不同链条反复丢失。

#### 处理方向与完成标准

- 定义共享核心领域对象；图生和文生只负责生成请求/SceneBrief，资产、关系、布局、装配和验收统一走
  V2 核心。
- 旧 Flow2 通过 adapter 迁移并进入兼容维护期，不再承载新算法。
- 建立唯一用户入口 README、真实架构、运行手册、研究状态和 ADR；历史实验结论留在实验报告。
- 测试数、默认参数、schema、模型 fingerprint 和 release 状态自动生成，避免 README/AGENT/研究文档漂移。

### P016：WebUI 只是启动面板，尚不是可恢复的任务控制系统

#### 价值判断

该问题有价值，但优先级低于正式主链。只有准备让其他人长期使用或多人排队运行时，才应集中投入。

#### 处理方向与完成标准

- 用 SQLite WAL 保存任务、阶段、attempt、日志位置和 artifact hash，并与 P007/P008 的 broker/DAG 对接。
- 服务重启后能重新关联 systemd/cgroup job，而不是直接变成未知状态。
- 明确展示诊断运行与正式交付、当前资源门原因、资产候选和人工批准状态。
- 若开放远程访问，再补认证、CSRF、路径 allowlist、请求体、并发和速率限制。

## 5. 研究能力的启用边界

以下内容有研究价值，但暂不作为“默认链缺陷”直接修复：

- SceneDNA vNext：第四轮独立盲评和预注册统计完成前继续默认关闭；不能因工程分数好看直接启用。
- 自动细节修复：目前自然正例和 operator 类型仍少，继续 opt-in、保留 rollback，不进入 production。
- reference soft prior：先做多 Prompt/seed 与等资产 Blender A/B，不能把 RMSE 降低当成视觉提升。
- 通用 relation geometry：在 exact backend 和跨资产统计完成前保持 opt-in postprocess。

这些方向应与工程稳定化并行，但不能抢占 P004-P009 的优先级，也不能绕过 P003 的全场景门。

## 6. 运行结束后的建议执行顺序

1. **冻结证据与代码（P004）：** 当前运行结束后，先记录失败 GLB、layout、audit、预览和代码状态，
   建立不包含运行产物的可恢复 release snapshot。
2. **修复眼前回归（P001-P003）：** 对比 anatomical-slipper v3 与当前 SDF plan，修鞋组和衣柜朝向，
   再把它们纳入全场景 non-regression audit。
3. **闭合正式交付地基（P005-P009）：** 内容哈希证书、production profile、heavy-job broker、阶段 DAG、
   强 schema 与环境锁必须形成一套相互衔接的运行契约。
4. **建立真实验证体系（P014）：** 先补负向集成和恢复测试，再扩大 nightly GPU 与 chaos coverage。
5. **降低交付成本（P010）：** 做类别感知减面、实例化与纹理压缩，以低于 100 MB 为首阶段目标。
6. **提升资产与视觉（P012-P013）：** 正式化缺失资产子流水线，扩充审核库，之后优化材质、灯光和相机。
7. **升级研究证明（P011）：** 接 exact predicate、局部细化和跨资产统计，成熟后再讨论默认启用。
8. **长期收敛（P015-P016）：** 统一图生/文生/V2 核心与事实源；有多人使用需求时再升级 WebUI。
9. 每完成一个问题立即记录断点；任一验收失败都保留证据、更新假设并继续迭代，不能用局部通过代替完成。

## 7. 完成断点记录

### 断点 CP-20260901-01：P001 已完成

- 完成时间：2026-09-01
- 根因：专项 SDF 构建默认继承 `bedroom_complete_relation_geometry_20260822_v1` 旧 plan；对象上虽有
  `instance_group_id`，但顶层 pair contract、最新 canonical front、人体源角色和镜像信息均未传入。
  首次恢复 pair 后又发现实例组求解器把 area rug 当成实体障碍，错误地把鞋组横移到房间左侧。
- 修改文件：
  `sage/experiments/codex_trellis_scene_v2/build_sdf_complex_bedroom.py`、
  `sage/experiments/codex_trellis_scene_v2/instance_groups.py`、
  `sage/experiments/codex_trellis_scene_v2/tests/test_build_sdf_complex_bedroom.py`。
- 新增/修改测试：恢复旧 plan 时必须建立一组拖鞋、从审核 manifest 刷新手性、只镜像一只鞋、按床前向
  排列；area rug 不得驱逐鞋组。
- 验证结果：拖鞋组 `1/1 valid`；推导角色 `[left,right]`；反射轴 `[y,null]`；两鞋 yaw 均 270°；
  内部 gap `0.08m`；床锚点 gap `0.25m`；medial-facing `[1.0,1.0]`。
- GLB 回读：左鞋 root extras 为 `asset_reflection_baked=true`、`asset_reflection_axis=y`、
  `asset_pair_role=left`；两个 root scale 均为正，没有遗留负 determinant。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_trellis2_20260901_v3_semantic_fixed`
- 关键文件 SHA-256：修正版 GLB
  `817c35961f359a817f96e13e710f8bcec6767f1e80e422b0682afe9b31c5cdf7`；鞋子近景
  `064a6e7e24a5c7962b48983e7c3f9e01485d45db2082cec9f4709157338b362b`。
- 人工检查结论：两鞋位于床尾中央、平行、鞋头同向，轮廓构成可穿的左右 pair。
- 未解决风险：长期仍应优先扩充真实左右 bundle；当前是审核右鞋源几何加单侧 canonical-local 镜像。
- 下一入口：P003 全场景交付门扩展。

### 断点 CP-20260901-02：P002 已完成

- 完成时间：2026-09-01
- 根因：衣柜从 east-wall 软偏好迁移到实际 west-wall 后，保留了旧 `preferred_wall=east`、
  facing wall 和 `yaw=270°`，专项构建未重新运行功能面求解。
- 修改文件：`sage/experiments/codex_trellis_scene_v2/build_sdf_complex_bedroom.py`。
- 新增/修改测试：软墙面家具的实际接触墙变化后，必须持久化 resolved wall 并重新计算 canonical-front yaw。
- 验证结果：衣柜 `preferred_wall/resolved_wall=west`、`yaw=90°`，世界 front `[1,0]` 与西墙室内法向
  `[1,0]` 一致，角误差 0°；五个受约束家具功能面全部通过。
- 新产物目录：同 CP-20260901-01。
- 关键文件 SHA-256：修正版 GLB
  `817c35961f359a817f96e13e710f8bcec6767f1e80e422b0682afe9b31c5cdf7`；正中预览
  `a81d75c1c5757854f111dd5bff5f8c7c64192e034209638673b3f719a6158dab`。
- 人工检查结论：正中视图可以看到衣柜门和把手朝向室内，原来朝墙的功能错误已消失。
- 未解决风险：动态柜门/操作扫掠体不在当前静态 GLB 验收范围内。
- 下一入口：P003 的操作净空门。

### 断点 CP-20260901-03：P003 阶段进展（未完成）

- 完成时间：2026-09-01
- 已完成范围：新增 `whole_scene_regression_audit.json`，检查 required object、实例组/手性、所有已声明
  into-room 功能面，以及四条 relation-geometry 证书；该门不通过时禁止 Blender 正式装配。
- 验证结果：required object 缺失 0；实例组 1/1 valid；功能面 5/5 accepted；关系几何 4/4 accepted；
  GLB 33 geometry/33 node，必需衣柜、两鞋、书桌椅、书架和三排书节点全部存在。
- 测试结果：定向 8/8、V2 包 282/282、仓库根 12/12；完整回归合计 294/294；Python compile 和
  `git diff --check` 通过。
- 额外进展：专项多视图 QA 现在重新核对当前 GLB 与 contact sheet SHA-256，替换审核后 GLB 的负向
  测试已经通过；这只是 P005 的专项子集，不能把 P005 标记完成。
- 交付审计：
  `/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_trellis2_20260901_v3_semantic_fixed/semantic_fix_delivery_audit.json`
- 尚未完成：通用 typed graph 完整性、support parent、建筑 opening、入口/柜门/椅子拉出操作净空和
  GLB world-transform 全覆盖仍需接入同一 production gate。
- 下一入口：从 support、opening、operation-clearance 三类现有 validator 抽取机器门，补失败 fixture 后
  才能把 P003 标为 `已完成`。

### 断点 CP-20260901-04：P003 已完成

- 完成时间：2026-09-01
- 根因：旧 `whole_scene_regression_audit_v1` 只覆盖 required object、实例组 validator、功能朝向和本轮四条
  relation geometry；专项 prepare 又在旧 graph materialize 后追加书架/书排，造成最终 plan 20 个对象而
  typed graph 仍只有 16 个对象节点。旧 validator 的二维 floor broad phase 还会把 `tucked_under`、
  `contained_in` 和垂直分层对象误报为普通 floor collision，无法直接作为完整交付门。最终复验又发现
  两个床头柜仍引用已丢失的 `matching_nightstand_pair` 顶层 contract。
- 修改文件：
  `sage/experiments/codex_trellis_scene_v2/whole_scene_audit.py`、
  `sage/experiments/codex_trellis_scene_v2/build_sdf_complex_bedroom.py`、
  `sage/experiments/codex_trellis_scene_v2/instance_groups.py`、
  `sage/experiments/codex_trellis_scene_v2/tests/test_whole_scene_audit.py`、
  `sage/experiments/codex_trellis_scene_v2/tests/test_build_sdf_complex_bedroom.py`。
- 新增/修改测试：追加对象但不刷新图、support parent 丢失、window obstruction、衣柜操作区被挡、衣柜
  朝墙、对象引用缺失 pair contract、GLB 平移偏差与负 determinant 均必须让 `whole_scene_ok=false`；只有
  Prompt 存在可逐字核对的 `exactly two matching <category>`、两对象同类同资产且角色完整时，才允许恢复
  legacy matched-set contract。
- 执行命令：
  `python -m unittest discover -s sage/experiments/codex_trellis_scene_v2/tests -t .`；
  `python -m unittest discover -s tests -p 'test_*.py'`；
  `python -m sage.experiments.codex_trellis_scene_v2.build_sdf_complex_bedroom --phase reaudit-existing ...`。
- 验证结果：`target_feature_ok=true`、`whole_scene_ok=true`；typed graph 20/20 object nodes、2/2 opening
  nodes且全部 hard relation 在图中；实例组 2/2 valid、0 orphan；功能面 5/5；support 5/5；opening/入口
  0 failure、walkway reachable；衣柜/斗柜/两床头柜/书桌与办公椅 pullout 共 6 个操作区 6/6；原四条
  relation geometry 4/4；GLB 20/20 对象中心、尺寸、yaw 与正 determinant 回读通过，door/window 节点齐全。
  正式回归为 V2 290/290、仓库根 12/12，共 302/302；compileall、全部结果 JSON 和 `git diff --check`
  通过。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_trellis2_20260901_v6_p003_whole_scene_final`。
  该目录通过 hardlink/copy 复用已审核 GLB 和资产，不重新生成 TRELLIS、不覆盖 v3；v5 失败目录保留为
  orphan nightstand group 的负面证据。
- 关键文件 SHA-256：GLB
  `817c35961f359a817f96e13e710f8bcec6767f1e80e422b0682afe9b31c5cdf7`；完整审计
  `88121f21c7e6ed2f588247676c8ab04f80ae8582315cb6a52f901af6725dcf78`；GLB transform 审计
  `728d7e9f9e333910fef6bf48982d4e96d8d155dce4565c3d0502834e90605b36`；reaudit report
  `5d283fd48009108be28cedc455e73367966c6afa8d891d8b636b3e2577e9a7b1`。
- 人工检查结论：沿用 P001/P002 已通过的同一 GLB 与近景证据；本轮没有改变任何 mesh 或 pose，只闭合
  全场景结构/关系/操作区/GLB 回读机器门，因此无需用新渲染掩盖旧视觉证据。
- 未解决风险：操作区仍是静态 cardinal AABB contract，不是动态铰链/人体轨迹仿真；非 cardinal 操作
  朝向会明确失败而不是近似通过。更强 schema 与动态能力证书分别归入 P009/P013。
- 下一入口：P004，先分类 dirty worktree，建立不含模型、缓存、运行产物和用户临时文件的受控 release
  snapshot，并从干净 checkout 复现 CPU 回归与无资产重生成 Blender smoke。

### 断点 CP-20260901-05：P004 已完成

- 完成时间：2026-09-01
- 根因：当前分支 HEAD 只包含早期实验提交，关系几何、SceneDNA、资源门、专项卧室构建、完整交付审计、
  Blender 工具及大量负向测试仍散落在工作树；外部 TRELLIS.2 虽有确定基准提交，实际运行还依赖 5 个
  未提交的 DINOv3/SDPA 兼容修改。只记录主仓库 HEAD 或外部提交号都不能恢复真实运行时。
- 修改范围：精确纳入 108 个正式源码/测试/文档文件，新增
  `release_manifest.py`、manifest 负向回归和 byte-exact 的外部 TRELLIS compatibility patch bundle；明确
  排除三组 `examples/` 用户输入、`local_models/`、`.env`、模型、缓存、GLB/Blend 和全部运行产物。
  密钥模式与危险扩展名扫描均为空，未使用 `git add -A`。
- 受控版本：候选源码提交 `d120064c6efa4b2a3d95fffe578b58e80791e747`；manifest byte-exact 修复提交
  `d812910390f11d182dd69ef9c12797ece2fed1cf`；正式 annotated tag 为
  `scene-v2-p004-20260901`，指向包含本断点的最终发布提交。
- 外部与模型冻结：TRELLIS.2 基准提交
  `75fbf0183001ed9876c8dbb35de6b68552ee08bd`；5 个本地修改文件全部逐文件 SHA-256，解码补丁
  SHA-256 为 `f79915a7eaeaa6c1895e3744cf18e74a973f5e47711698168162d766d72b6747`。TRELLIS 主模型
  74 个文件、16,385,131,413 bytes，完整逐文件 content fingerprint 为
  `22cda4b351ab87884530038d64126edd6ed650942c5466b0497c024b7a4ea605`。
- 环境冻结：orchestrator/trellis Python 均为 3.10.20，PyTorch `2.12.1+cu130`、CUDA build 13.0；两套
  `pip freeze` 指纹分别为 `d49b7cd63b10029f698d3c3e4d23b2d5ace1eac4ed8d47175446eb4db55f3dc4` 和
  `041341de14ce0f94a5b51b3029d28500e55c642fcd5ee1c166d244435e582400`。Blender 4.3.2 binary
  SHA-256 为 `23fa8e83d8152f11246d7172819baa5a00e8e1e706dbc204cc85912db3f368c4`；SDPA、sparse backend
  与 HF cache 只从显式安全白名单采集。当前受控沙箱无法与 NVIDIA driver 通信，manifest 如实记录
  `nvidia-smi returncode=9`，没有伪造 GPU 可用状态；P004 的强制验证本身不需要重新运行 GPU/TRELLIS。
- 干净检出验证：候选独立 worktree 无未提交项；V2 293/293、仓库根 12/12，共 305/305；compileall 与
  `git diff --check` 通过。资源门为可用内存 231.15 GiB、Dirty+Writeback 0.0003 GiB、blocked 最高 1、
  I/O wait 0.50%。Blender 在 `MemoryHigh=12G/MemoryMax=16G` cgroup 中复用既有 20 项资产装配成功，
  没有调用 FLUX/TRELLIS；输出 33 geometry，GLB world-transform 审计通过，且 GLB SHA-256 与 P003
  正式产物相同：`817c35961f359a817f96e13e710f8bcec6767f1e80e422b0682afe9b31c5cdf7`。
- 审计复现：从干净检出执行 `--phase reaudit-existing`，`target_feature_ok/whole_scene_ok/typed_graph/
  support/opening/operation_clearance/glb_world_transform` 全部为 true，源/输出 GLB 哈希一致，明确记录
  `asset_regeneration_performed=false`。
- 证据目录：候选失败 manifest 保留在
  `/data/wsj/main/scene_runs/codex_trellis_v2/p004_release_verification_d120064_candidate`；修正后的正式发布证据
  写入 `/data/wsj/main/scene_runs/codex_trellis_v2/p004_release_verification_final`，旧目录不覆盖。
- 人工检查：干净检出 Blender center preview 已查看，书架三排书、书桌椅、衣柜、床和拖鞋均存在，
  与 P003 视觉证据一致；P004 不以重渲染改善画面为目标。
- 未解决风险：release tag 尚未推送远端；远程 Git 凭据不属于本问题授权范围。manifest 已冻结可复现
  输入，但 GPU driver 当前不可见，因此真实 TRELLIS nightly 重生成属于 P014，而不是 P004 的 CPU/
  无生成 Blender 门。
- 下一入口：P005，从统一规范化 content key 开始闭合 generation、asset、multiview QA 和恢复证书哈希链，
  首先补“替换 GLB、替换参考图、改变 seed/模型/参数”三类负向测试。

### 断点 CP-20260901-06：P005 已完成

- 完成时间：2026-09-01
- 根因：旧 `generation_key` 只散列类别、Prompt 和目标尺寸；staged 资产恢复只检查 GLB/JSON 存在及少量
  字段；专项 batch 看到 `pilot_report.ok=true` 就跳过；多视图 QA 虽已补 GLB/contact-sheet 哈希，却没有
  用同一证书绑定生成参数、真实参考图、四个原始视图、相机、Blender renderer/脚本和 QA 规则。因此同名
  文件替换或 seed/model/pipeline 漂移后，旧阶段仍有被误复用的路径。
- 修改文件：新增 `content_chain.py` 与 `tests/test_content_chain.py`；修改 `assets.py`、`cli.py`、
  `pipeline.py`、`pilot_asset.py`、`run_sdf_bedroom_trellis_batch.py`、`scene_dna_multiview.py`、
  `build_sdf_complex_bedroom.py` 及对应卧室测试。
- 内容契约：规范化 JSON 禁止 NaN 并采用稳定 key 排序。规划 generation contract 绑定 category、完整隔离
  Prompt、目标尺寸、seed、TRELLIS model fingerprint、RMBG fingerprint、pipeline、steps、texture、
  decimation、preprocess 和 code version；真实候选 runtime contract 再绑定实际 attempt seed 与参考图
  bytes/SHA-256，使用完整 64 位十六进制 content key，不再截断为 16 位。
- 证书链：候选 checkpoint 绑定 runtime generation contract、SceneDNA contract、request、GLB 和 multiview
  report；staged sidecar 绑定 GLB、对象、生成 metadata 和 generation key；pilot report 绑定 GLB、参考图、
  generation metadata/contract 与 inspection rules；SceneDNA 多视图证书绑定 GLB、四个原始视图、contact
  sheet、Blender binary、turntable script、相机 contract、分辨率和 QA rule version。恢复时全部重新读取
  当前 bytes 校验，旧/缺失证书只会失效并重跑，不再因同名文件存在而放行。
- 专项 SDF 门：只接受 `codex_trellis_multiview_qa_v2`；每个资产必须有 generation contract、四视图、
  contact sheet、renderer binary/script、camera contract、QA rules 和完整 content certificate。旧 v1 文件
  明确报 `unbound legacy schema`，需要重新审核/迁移，不能静默兼容。
- 负向测试：审核后替换 GLB、替换参考图或任一视图，证书拒绝；改变 seed、TRELLIS model fingerprint、
  steps、texture 或 decimation，generation key 改变且旧 pilot/resume 拒绝；同一规范化 payload 的字典
  顺序变化不改变 key。专项 SDF 继续覆盖替换审核后 GLB，新增四视图/renderer/camera/rules 强制字段。
- 验证命令：`python -m unittest discover -s sage/experiments/codex_trellis_scene_v2/tests -t .`；
  `python -m unittest discover -s tests -p 'test_*.py'`；`python -m compileall -q
  sage/experiments/codex_trellis_scene_v2`；`git diff --check`。
- 验证结果：V2 296/296、仓库根 12/12，共 308/308；compileall 与 diff check 通过。没有启动 GPU、
  FLUX、TRELLIS 或 Blender，也没有覆盖 P001-P004 历史产物。
- 新产物目录：`/data/wsj/main/scene_runs/codex_trellis_v2/p005_content_chain_acceptance_20260901_v1`，保存
  机器可读负向验收与最终源码提交信息；旧 QA/checkpoint 原样保留作为 legacy 拒绝输入。
- 未解决风险：旧运行没有足够信息时不能凭空重建可信 generation contract，必须重新审核；这是安全失效，
  不是兼容缺陷。阶段间更一般的依赖失效范围与原子 attempt DAG 属于 P008；强类型 schema migration
  属于 P009。
- 下一入口：P006，定义 plan/development/production/benchmark 四种机器 profile，并保证只有 production
  必需阶段、最终 hash audit 和 terminal status 全部闭合时才允许 `deliverable=true`。

### 断点 CP-20260901-07：P006 已完成

- 完成时间：2026-09-01
- 根因：旧 CLI 的退出 0 和 `validation_ok` 只代表布局阶段；默认 `asset-mode=plan`、未装配、未做最终
  多通道渲染或 hash audit 的结果仍使用同一种 summary，消费者无法机器区分诊断运行与正式交付。
- 修改文件：新增 `delivery_status.py` 与 `tests/test_delivery_status.py`；修改 `cli.py` 和 `pipeline.py`。
- Profile 契约：`plan`、`development`、`production`、`benchmark` 各有固定 required-stage 列表；plan
  即使完整也只能得到 `plan_complete_non_deliverable`。production 禁止 `asset-mode=plan`，强制 assembly、
  preview、最终 RGB/depth/instance acceptance、MuJoCo structural/performance check，并关闭两个 allow-fail
  开关。
- 统一终态：所有 summary 都包含 `profile`、`terminal_status`、`deliverable`、`profile_complete`、
  `required_stages`、`missing_required_stages` 和逐阶段布尔状态。只有 production 的 SceneBrief、建筑、
  typed graph、资产计划与 QA、layout/validation、relation geometry、Blender、最终多通道渲染、结构性能和
  final hash audit 全为 true 时，才产生 `production_deliverable` 与 `deliverable=true`。
- 诚实 relation 门：无声明关系时 production 写出显式 `not_applicable_no_declared_relations` 证书；存在声明
  关系但没有 relation-geometry 证书时写 `required_relation_geometry_certificate_missing` 并保持不可交付，
  不用二维布局验证冒充几何证明。final hash audit 对九类关键产物逐文件记录 bytes/SHA-256，缺一项即失败。
- 失败保存：CLI 任意异常都会原子覆盖 `run_summary.json` 为
  `terminal_status=diagnostic_failure_preserved, deliverable=false` 并记录异常类型；逃生开关和失败前产物不再
  可能保留含糊的成功 summary。
- 负向测试：对 production 的 12 个必需阶段逐一置 false，全部必须不可交付且准确列入 missing；只有
  12/12 true 才可交付；plan 6/6 完整仍明确 non-deliverable。
- 验证结果：V2 298/298、仓库根 12/12，共 310/310；compileall 与 `git diff --check` 通过。未启动模型、
  GPU 或 Blender；这是终态定义修复，不以已有渲染冒充 production E2E。
- 未解决风险：production relation stage 的通用自动调度仍需随 P008 阶段 DAG 收敛；当前契约选择安全
  失败而不是静默跳过。GPU/Blender nightly 的真实成功路径纳入 P014。
- 下一入口：P007，建立基于 GPU/RAM/I/O/disk/cgroup lease 的统一 heavy-job broker，并用并发、外部 GPU
  占用和 worker 异常三类测试验证背压、TTL 与回收。

### 断点 CP-20260901-08：P007 已完成

- 完成时间：2026-09-01
- 根因：bridge 使用 `ThreadingHTTPServer`，每个 `/generate` 都无条件创建 daemon worker；外围 runner 的
  进程名白名单和固定 3600 秒稳定窗既看不到任意 CUDA 进程，也无法阻止两个 HTTP 请求同时加载模型。
- 修改文件：新增 `heavy_job_broker.py` 与 `tests/test_heavy_job_broker.py`；修改
  `trellis2_flux_bridge_server.py`、`run_sdf_bedroom_trellis_batch.py` 和 bridge 测试。
- Broker：用 `flock` + 原子 JSON 保存单 GPU active lease；记录 owner PID、job、GPU index、TTL、acquire/
  heartbeat/release 时间。每个已接受 worker 只有一个 heartbeat，finally 必定 release；过期 heartbeat 或死亡
  PID 可被后续请求回收，活 lease 不会被抢占。
- 资源门：每次 admission 联合检查 `resource_health` 的 RAM、Dirty/Writeback、blocked、I/O wait、data/tmp
  disk，NVML 的 GPU 名称、显存、温度和 compute/graphics PID，以及当前 cgroup 的
  `memory.high/max/current`。正式 bridge 默认要求 NVML 成功且 `memory.max<=16GiB`；不可见 GPU、无界
  cgroup、外部 GPU PID 或系统压力均安全拒绝。
- 并发与背压：broker 的机器限制为 `max_active=1,max_queue=0`；已有活 lease 时 `/generate` 返回 HTTP 429
  和结构化 `queue_full/retryable`，不会创建 JobStore 项或 worker thread。`/health` 暴露 broker snapshot。
- 配置：lease 文件、TTL、GPU index、NVML/cgroup 强门均有 CLI；旧 3600 秒 stability window 改为
  `--concurrency-clear-stability-seconds`，只作 legacy preflight，broker lease 才是权威门。systemd supervisor
  继续强制 `MemoryHigh=12G/MemoryMax=16G`、OOMPolicy 和独立日志。
- 负向测试：两个并发请求只有第一个取得 lease；外部 GPU PID 被拒；模拟 worker 死亡/heartbeat 超时后
  lease 可恢复；HTTP 429 路径不创建 job。测试完全使用 probe 注入，不加载 CUDA/TRELLIS。
- 验证结果：V2 302/302、仓库根 12/12，共 314/314；server/broker compileall 与 `git diff --check`
  通过。没有启动或打断任何真实 GPU 任务。
- 未解决风险：当前选择零长度等待队列，调用方需按 429 重试；这是明确背压策略，不是无限线程。跨主机
  分布式队列不在单机 P007 范围内。阶段 attempt 与 broker lease 的统一持久化关联进入 P008。
- 下一入口：P008，把全流程变成显式阶段 DAG，以输入/输出 hash 自动计算失效范围并原子提交 attempt。

### 断点 CP-20260901-09：P008 已完成

- 完成时间：2026-09-01
- 根因：旧 resume 分别用 `scene_brief.json`、staged 文件、`layout_plan_final.json` 和 `ok=true` 作存在性
  判断，没有统一依赖图；上游配置变化时无法可靠计算下游失效范围，运行中断也没有原子 attempt 边界。
- 修改文件：新增 `stage_dag.py` 与 `tests/test_stage_dag.py`，修改 `pipeline.py`。
- DAG：固定 11 阶段 `expand→architecture→scene_graph→asset_plan→asset_generate→asset_qa→layout→
  relation_geometry→assemble→render_acceptance→delivery_audit`。每个 attempt 记录 schema、规范化 inputs/config
  hash、依赖 output keys、状态、起止时间、耗时、逐输出路径/bytes/SHA-256 和进程/cgroup 资源峰值。
- 原子性：begin 先原子写 `running`；commit 只有在全部声明输出可读取并完成哈希后原子切换
  `committed`；异常/中断 attempt 永不复用，下一次使用新 attempt 编号。输出被替换后即使路径不变也不可
  复用；下游记录 `invalidated_by`，旧 attempt 保留为证据而不参与当前 output key。
- Pipeline：resume 现在必须有 `run_dag.json`；expand、architecture、scene graph、layout、Blender assembly
  和 render acceptance 使用 DAG 复用。资产阶段仍每次运行 P005 的只读证书核验，但证书有效时不做模型
  生成；staged GLB/JSON 全部纳入 asset_generate 输出 hash。relation/final delivery audit 也进入同一 DAG。
- 单测：任一 11 阶段模拟中断后只创建该阶段 attempt 2，所有上游仍可复用；改变 asset_plan 输入只失效
  自身及下游；失败 attempt 的残缺输出不进入下一 attempt；提交后篡改任一输出立即使 reuse=false。
- 真实 smoke：`p008_stage_dag_smoke_20260901_v2` 首次 rules/plan 成功；完全相同 resume 后 7 个已执行
  阶段 attempt 数全部保持 1、`layout_resumed=true`。只把 seed 2400 改成 2401 后，expand/architecture/
  scene_graph 仍为 1，asset_plan/asset_generate/asset_qa/layout 精确变为 attempt 2，未触发模型或 Blender。
- 验证结果：V2 305/305、仓库根 12/12，共 317/317；compileall、`git diff --check` 与两轮真实 CLI
  smoke 通过。
- 新产物目录：`/data/wsj/main/scene_runs/codex_trellis_v2/p008_stage_dag_smoke_20260901_v2`；v1 保留为
  发现 architecture 对 brief 有隐式 mutation、导致错误下游失效的失败证据，未覆盖。
- 未解决风险：远程/多机 artifact store 不在当前单机 DAG 范围；当前原子性依赖同一文件系统 rename。
  Schema 强类型与 migration 由 P009 处理。
- 下一入口：P009，冻结核心对象 schema、单位/坐标/手性契约和运行环境 preflight，旧 schema 只能显式
  迁移或拒绝。

### 断点 CP-20260901-10：P009 已完成

- 完成时间：2026-09-01
- 根因：主流程以宽松字典传递 SceneBrief、图、布局和审计；旧方向字段可与新 `yaw` 并存，资产 Y-up/
  Z-up 边界、右手系和 canonical front 没有同一机器契约。P004 虽冻结了环境证据，production 启动时却
  没有把当前可执行文件、依赖、TRELLIS 补丁、模型和 Blender 工具逐项与冻结值复验。
- 修改文件：新增 `contracts.py`、`runtime_lock.json`、`runtime_preflight.py` 和
  `tests/test_contracts.py`；修改 `cli.py`、`pipeline.py`、`stage_dag.py`。实现提交为
  `ecdb929625d2582a35677256813d7f4a99b3e695`。
- 强契约：SceneBrief、TypedSceneGraph、Asset/QA Certificate、LayoutPlan、Relation Certificate、
  RunManifest、FinalDeliveryAudit 七类文档均有精确 schema、必需字段、引用/计数/哈希验证。文档使用禁止
  NaN、稳定排序的规范化 JSON 生成 SHA-256；RunManifest 每次原子保存都重算自哈希。坐标契约固定米制、
  右手 Z-up、绕 +Z 逆时针 yaw，只允许显式 Y-up/Z-up 资产边界和四个平面 canonical-front 轴，坐标契约
  未知字段拒绝。
- migration：只有已注册的 `codex_trellis_layout_plan_v1/v2` 可显式迁移；v1 的 `yaw_degrees` 转为 `yaw`
  并补齐坐标/资产轴契约。未知 schema 和其他没有注册迁移器的文档安全拒绝，不做猜测性兼容。
- runtime preflight：锁定 orchestrator `tree-sage-flow2`、TRELLIS `trellis2`、research `simgen` 三个
  Python 环境的解释器/Python/pip-freeze 指纹（前两者另锁 PyTorch/CUDA build），并锁定 P004 release
  manifest、TRELLIS commit 与工作树补丁、74 文件模型 fingerprint、Blender 4.3.2 二进制、装配和诊断
  渲染脚本。production 在读取 Prompt 或启动阶段前强制执行，任一漂移即保存失败报告并中止。
- 负向测试：旧 `rotation_y`、错误 cm 单位、错误世界/资产轴、Y-up 到 Z-up 映射矛盾、缺少
  `instance_groups`、orphan group、未知坐标字段、篡改 content hash、未知 schema/未注册 migration、缺失
  research 环境和 runtime lock 未知字段均不能通过。
- 验证结果：V2 311/311、仓库根 12/12，共 323/323；compileall 与 `git diff --check` 通过。真实 plan
  smoke 首次与同参数 resume 均成功，第二次 7 个已执行阶段 attempt 数仍全为 1、`layout_resumed=true`。
  完整 runtime preflight 实际重读 74/74 模型文件（16,385,131,413 bytes）并核验三个环境、TRELLIS
  补丁、Blender 工具，`ok=true,reasons=[]`；没有启动 GPU、FLUX、TRELLIS 或 Blender。
- 新产物目录：契约/resume smoke 为
  `/data/wsj/main/scene_runs/codex_trellis_v2/p009_contract_smoke_20260901_v2`；完整环境证据为
  `/data/wsj/main/scene_runs/codex_trellis_v2/p009_contract_acceptance_20260901_v1/runtime_preflight_full.json`。
- 关键文件 SHA-256：完整 preflight
  `f753a6bfe54441730b4d494482e4c8898d520ef5c95f610a5795851465c66754`；resolved SceneBrief
  `3445b00763d83f6b14236b464b642e98bf7e077691e7b9d774f47687f3bd5e84`；TypedSceneGraph
  `fc3aebefb776ec0592a23010f6b534e0dd980304e9104327e8a3a33d97b5f09b`；LayoutPlan
  `f3dc40e4420a7925b465f54bb8312d6b91c919a227954b9deab8f37f14a8f8c7`；RunManifest
  `7dfe2c01f88d57da8443223c74643a038d81b0753d8c0391175bc1513c35c989`。
- 人工检查结论：本项改变的是语义/运行环境可执行门，不改变 mesh、材质或构图；JSON 契约、失败模式和
  resume attempt 已逐项检查，不用新渲染冒充 schema 验收。
- 未解决风险：runtime lock 是单机绝对路径锁，迁移到新机器必须显式生成并审核新锁；这属于预期的安全
  失败。远程 artifact store/容器镜像签名仍不在 P009 范围。
- 下一入口：P010，在保持 P001-P009 全部语义、关系、资产 QA 与视觉证据不回归的前提下，为最终 GLB
  建立分资产预算、可逆优化、几何/材质审计和小于 100MB 的正式交付门。

### 断点 CP-20260901-11：P010 已完成

- 完成时间：2026-09-01
- 根因：源 GLB 共有 3,409,625 faces/252,390,276 bytes；开放书架与三排书占约 197 万面，且所有类别
  沿用接近统一的高面数预算。单纯激进 collapse 会让碎片化 TRELLIS 表面出现孔洞/翻面；Blender
  `export_apply` 下直接链接重复 mesh 又会破坏床头柜材质和实例 mask，不能只按文件大小选结果。
- 修改文件：新增 `scene_delivery_optimization.py`、`blender_optimize_scene_delivery.py`、
  `blender_render_optimization_closeups.py` 和 `tests/test_scene_delivery_optimization.py`；优化
  `mesh_verifier.py` broad phase，用逐三角个体半径与向量化 AABB 过滤消除大三角导致的巨量假候选。
  实现提交为 `9ad031f647dbc0699a15ae4c634d5771608a3aca`。
- 预算策略：按类别基准、法线曲率 proxy 与三向投影 silhouette complexity 分配预算，并在总场景上限内
  归一化。最终保护完整 496,326-face 开放书架和完整 89,999-face 衣柜；三排结构简单的五本书各保留约
  19.7k faces，其余资产按曲面/轮廓复杂度分配。所有 decimate 后局部/世界 canonical bounds 恢复，UV
  层、材质槽、有限法线、零面积面和 1024 texture cap 逐 mesh 审计。
- 失败候选：v1 因 4mm bounds 门拒收；v2/v3 仍有衣柜边界或书架孔洞；v4 达到约 95.6MB/1M faces，
  但重复 mesh 两次 decimate 产生不同拓扑；v5 强制实例共享后床头柜变白且 instance mask 归属不稳；v6
  对非流形碎片全局重算法线导致多资产翻面；v7 衣柜细节退化；v8 的 10k-face 书排轮廓过碎。全部目录
  保留为负面证据，正式交付只认 v9。
- 实例化/压缩边界：重复资产 mesh-link 现为显式实验开关，默认因材质和 mask 回归关闭；没有用错误实例
  结果冒充优化。v9 在不依赖 Draco/meshopt/KTX2 的条件下已达到第一阶段硬目标；这些压缩和额外 LOD
  仍标记 deferred，不虚构支持。碰撞代理与 capability 证书未改，旧关系证书只作上游证据；优化后的视觉
  三角网格另行重验。
- 验证结果：最终 GLB 88,715,276 bytes、992,676 faces、33 geometry/33 nodes，较源文件体积减少
  64.85%、faces 减少 70.89%；trimesh 可加载。20/20 对象 bounds 通过 3mm center/6mm extent 门；
  P001-P003 whole-scene audit 为 true；桌椅 `tucked_under` 和三排书 `contained_in` 四组视觉网格均
  `complete=true/intersects=false/candidate_pair_count=0`。
- 视觉验收：源/优化 RGB、depth、20 个 required instance mask 均通过；尺度感知全场 silhouette 加权 IoU
  `0.937548`，关系关键对象 best IoU 均过 0.84，完整书架为 1.0、衣柜约 0.984。相同 768px 近景人工
  检查确认三层各五本书仍完整位于柜格内，椅座/扶手/轮脚仍清楚位于桌面与开口关系中；减面后的细节更
  棱角化，但没有对象缺失、穿插、朝向或关系退化。V2 315/315、仓库根 12/12，共 327/327；compileall
  与 `git diff --check` 通过。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/sdf_complex_bedroom_optimized_p010_20260901_v9`。
- 关键文件 SHA-256：GLB
  `eed1f5db3488fd41fee336b274ce9ed10f5fe0987d50b1d5139228d0c218ea9e`；优化几何审计
  `544a8b26e37e448b1beeca15291b517c63512ad5fa0fc3fb3365869c18a87fa1`；渲染 A/B
  `b3de931da374ff606f36ac2705fcdbf1261aab750e763e28d7bfff97df256254`；最终交付审计
  `94566c059e05a9b55994cc566b7e68bbfafb1f0b513838fd0acf087c3be40ae1`；书架/书排近景
  `abe7af67c58e31622118d093a8c28691a80d69ef732892869874aa6260a8ddf7`；桌椅近景
  `1d80b7a2e8f3f691357038e408fbaa9da49c32c7b754499ec37301b7f571faf1`。
- 未解决风险：当前 silhouette 门是 512px 多视图尺度感知 proxy，不是连续屏幕空间 Hausdorff 证明；
  collapse 会让近看表面更棱角化。更严格 exact predicate 属于 P011，材质/相机成片改善属于 P012；
  glTF 层 mesh+material 安全实例化、meshopt/Draco/KTX2 和额外 LOD 可继续降低传输/实时成本，但不再是
  P010 第一阶段交付阻塞。
- 下一入口：P011，引入 native exact-predicate 能力探测、SDF ambiguous 局部细化、静态目标 BVH 缓存
  和误差上界；backend 不可用时必须明确标为 `floating_point_verified`。

### 断点 CP-20260901-12：P011 已完成

- 完成时间：2026-09-01。
- 根因：旧三角终检只有 Python 浮点窄相位，目标 cKDTree 只在单次 audit 内存中复用；碰撞查询直接使用
  固定 2cm SDF，证书没有记录 capability 内容 hash、完整误差界或可靠的 containment 点基。更重要的是，
  旧书排 containment 只检查 8,000 个随机表面点；改为全 mesh 顶点后，真实发现下层书排有 85/293,604
  个顶点越过含 1cm clearance 的边界，最大越界 0.000074703m，证明旧证书确有采样漏检。
- 修改文件：新增 `native_exact_predicates.cpp`、`exact_predicates.py` 和
  `p011_relation_benchmark.py`；修改 `mesh_verifier.py`、`relation_geometry.py`、
  `relation_geometry_bridge.py`、`relation_solver.py`、`build_sdf_complex_bedroom.py` 及对应测试。实现提交为
  `6fdcc8b`。
- 精确谓词：服务器没有 CGAL、Boost.Multiprecision 或 GMP 开发头文件，因此实现自包含 C++17
  error-free binary64 expansion 的 `orient2d/orient3d`，以 `-fno-fast-math -ffp-contract=off` 编译并在
  加载时自检。native source SHA-256 为
  `bed013d603b0e600a38f71a96524e1bc6aad922aa1348796dac2abebdb5f0a6a`，冻结共享库 SHA-256 为
  `ba2f00060e7f83144d730e672c8a52f59f1939392adba8911e84f0b923bee0b8`。不可构建、显式禁用或单对输入
  超范围时均降级并明确写 `floating_point_verified`；零候选只写
  `conservative_broad_phase_verified`，不虚构 exact predicate 已执行。
- SDF 与 containment：多级代理先用 4cm coarse 排除明显分离点，所有 negative/ambiguous 点为安全性
  都局部查询 2cm fine；2% 阈值只标记高模糊升级，不再用于跳过少量可疑点。真实四条关系的 8 个方向
  均发生局部细化，64,000 个查询最终残留 1,349 个 conservative ambiguous（2.1078125%），全部继续由
  三角终检覆盖。`full_containment` 改为凸 box 对全部 mesh 顶点的有符号余量分类，记录 binary64 数值
  误差界；下层书排目标局部最小修复为 +0.000074713m，中层数值边界收敛为 -1e-8m，修复后四条关系
  4/4 接受。
- hash、误差界和缓存：关系 contract/证书显式绑定 source/target capability canonical hash、双侧 proxy
  build hash、姿态、点基和点数；记录 proxy discretization、关系 tolerance、分类 numeric error 和三角
  broad-phase tolerance。静态目标三角、AABB、中心/半径和空间索引以 mesh 内容 hash、姿态和 tolerance 为
  key 原子落盘；真实基准第二轮 13/13 命中持久缓存。
- 真实统计：最终优化卧室 GLB 上冻结桌椅、三层书架容器、杯/桌、植物/斗柜、闹钟/床头柜和双灯/床头柜
  9 个非穿透/接触容差案例，并从同一真实网格构造椅桌、书架侧板、杯桌、植物斗柜 4 个穿透负例。
  13/13 与预期一致，失败率 0；四个负例分别执行 383、3、22、2 个 native exact 三角对并检出相交。
  `supported_by` 的导出视觉网格保留微小接触间隙，因此正确期望是 tolerance 内支撑且不穿透，不把
  “表面必须精确相交”误写成验收条件。
- 验证结果：V2 325/325、仓库根 12/12，共 337/337；native Fraction 真值 oracle、近共线、共面、穿越、
  candidate budget、显式 fallback、跨调用缓存、低/高 ambiguous 细化、capability 失效和全顶点 solver
  均有测试。C++ 额外以 `-Wall -Wextra -Wpedantic` 编译无警告，compileall 与 `git diff --check` 通过。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/p011_exact_geometry_20260901_v2`。
- 关键文件 SHA-256：最终基准报告
  `22a24478e6102ca54cca327682ef3487653172932eca4035692e268e139b7782`；native library 如上。
- 未解决风险：13 个冻结案例只够形成 integration gate，不足以替换默认 repair；报告明确保持
  `default_repair_replacement.recommended=false`，后续需扩展 nightly 跨资产集。三角 broad phase 和退化面
  过滤仍是带量化 tolerance 的浮点保守步骤，不能描述为整条连续几何的全 exact 证明；逐三角 ctypes
  narrow phase 也有性能开销。最细 2cm SDF 后仍可能保留 ambiguous，但会触发三角升级而非静默放行。
- 下一入口：P012，分离关系证据与最终展示 profile，并建立相机、曝光、噪声、材质和裁切的量化门。

### 断点 CP-20260901-13：P012 已完成

- 完成时间：2026-09-01。
- 根因：旧流程复用诊断渲染参数，缺少展示图与关系证据图的用途隔离；固定机位没有按 required-object、
  关系可见性和裁切联合选优；全图黑像素比例会掩盖面积较小但纯黑的窗洞，且第一次材质修复没有处理
  纹理链接到 Principled Base Color 的窗户材质。候选方形 mask 也不能作为 4:3 最终成片的严格裁切证据。
- 修改文件：新增 `showcase_render.py`、`blender_render_showcase.py`、`render_showcase_delivery.py` 和
  `tests/test_showcase_render.py`。实现提交为 `f30d814`。
- 渲染与相机：关系证据固定 Eevee Next、768x768、64 samples、AgX、5500K、独立主体；最终展示固定
  Cycles、1024x768、64 samples、denoise、AgX Medium High Contrast、5200K、exposure 0.15。自动评估
  16 个四边/角落机位后选择 `south_2` 与 `east_0`，required、complete 和 relation pair coverage 均为
  1.0，且来自不同房间侧面。
- 质量门：最终成片同尺寸对象索引 mask 与投影边界共同检查裁切；逐图记录过曝、全图近黑、中间调、
  平坦区域残差噪声和均值亮度。窗户单独按 `architecture.windows` 语义 mask 计算，修复纹理窗材质的
  深蓝灰 screen 下限后，次视图窗体 15,287 个可见像素中的近黑比例为
  `0.0000654150585464774`，不再被全图统计掩盖。两个视图均无 required-object 裁切、过曝比例为 0，
  平坦区域残差分别为 `0.0018569368` 与 `0.0016945772`。
- 新增/修改测试：固定且分离的 profile、裁切惩罚与关系可见性、互补双机位选择、白帧/裁切拒绝、
  “全图正常但可见窗户纯黑”负例，共 5 项 P012 定向测试。
- 执行命令：资源门先检查四张 GPU 的显存/利用率/计算进程、主机 RAM 与数据盘；只有四卡均
  `16MiB/49140MiB, 0%` 且无计算进程、RAM available 230GiB、磁盘可用 6.4TiB 后才运行 Blender。
  回归使用 `tree-sage-flow2`：
  `python -m unittest discover -s sage/experiments/codex_trellis_scene_v2/tests -t .`、
  `python -m unittest discover -s tests -p 'test_*.py'`、`python -m compileall -q
  sage/experiments/codex_trellis_scene_v2` 和 `git diff --check`。
- 验证结果：质量报告 `ok=true`、0 failures；V2 330/330、仓库根 12/12，共 342/342，compileall 与
  `git diff --check` 通过。最终实际使用 OPTIX；人工逐张检查两张展示图和两张隔离关系图并接受。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/p012_showcase_quality_20260901_v2`。
- 关键文件 SHA-256：质量报告
  `1783ae36c943fa80859578bfd1c2e381563412ffe482c41cb9a25f3b45077f56`；渲染 manifest
  `0ea3536907c2f602b6fc9d619e555f7f9d4873b34a86a579549d7e2862c80f66`；人工复核
  `4678049acc0976b1f7e0d606093a8af3d53d59ec36f74a00fb3fa1b701f25690`；hero/secondary 分别为
  `c6ee06fdee3f3f327659a9db34864c305313af6af577e988bec30651d4528961`、
  `f300916c6e3bc1688d5d5f24a2b23d9e22271a3e0caaa19fef77f91de6cfe36a`。
- 人工检查结论：hero 中床、双床头柜、衣柜、书桌椅、书架和装饰均清晰，构图稳定；secondary
  提供互补方向并明确显示窗户。三层书排均可见于书架内部，椅子与书桌相邻关系无歧义。木材、织物、
  墙漆、陶瓷、植物、金属和深色软包可区分，窗户为可辨识深蓝黑而非纯黑洞。
- 未解决风险：secondary 保留了较大的前景门扇，生成桌面仍有可见重建划痕；这两项不影响覆盖、裁切或
  关系证据，但仍限制照片级写实度。平坦区域残差只是图像空间噪声 proxy，不是 path-tracer variance；
  人工审核因此仍是最终 profile 的强制步骤。
- 下一入口：P013，建立缺失资产从合同、2D QA、TRELLIS、多视图/几何/能力验收到生命周期与长期资产库
  准入的正式闭环。

### 断点 CP-20260901-14：P013 已完成

- 完成时间：2026-09-01。
- 根因：原生成链只把 GLB 可加载与一次人工多视图结论当作可用条件，没有把 2D 候选、精确部件数量、
  正反面同组、侧面层数、尺寸/正面/拓扑/capability 串成一个内容绑定的准入合同；场景成功与长期入库
  也没有不同生命周期。实跑另暴露 bridge 的 16 GiB 门值、缺失 `pynvml` 与客户端重试 429 会造成
  空转，离线缓存变量和已安装 attention backend 也会漂移。
- 修改文件：新增 `asset_admission.py`、`p013_asset_admission_audit.py`、
  `tests/test_asset_admission.py`；修改 `brief.py`、`assets.py`、`pipeline.py`、`pilot_asset.py`、
  `heavy_job_broker.py`、bridge 与相应测试。实现提交为 `526ee0c`。
- 完整子流：正式合同依次绑定 asset contract、2D alpha/semantic/count QA、TRELLIS、四视图、尺寸、
  canonical front、拓扑清理、capability 和临时入场证书。production 装配会拒绝仍为
  `generated_for_run` 的生成资产；registry 只复用 `curated`（兼容无 lifecycle 的旧清单）。
- 数量与生命周期：`exactly five books` 被编译成机器 count contract；正反面必须同一组五个成员，侧面
  最大一层且禁止第二排。生命周期固定为 `generated_for_run -> scene_specific_approved ->
  candidate_for_curation -> curated`，可转 rejected/deprecated，禁止单场景成功跳过独立审核自动入库。
- 真实资产验证：复查三组旧书排时，`book_row_trellis2_002` 的正反面实际显示 10 本且侧面为两层，
  推翻旧 QA 文本并由 `multiview_count` 门拒绝；资源健康后通过本地 TRELLIS.2 新生成
  `book_row_trellis2_004`，四视图确认同一组恰好五本、无第二排。生成服务 GPU0 独占，峰值约
  11.99 GiB VRAM，systemd unit 最终 `inactive/dead, Result=success, ExecMainStatus=0`。
- 资源与恢复修复：bridge 新增显式 `--maximum-cgroup-memory-gib` 并仍要求有限 cgroup；NVML 包缺失时
  只读回退到 `nvidia-smi`，继续保留外部 GPU PID 拒绝门；HTTP 429 响应被解析为终态错误，不再被
  `URLError` 继承关系误判为无限重试。本次实际离线运行使用本地 DINO/TRELLIS/RMBG 缓存和 PyTorch
  SDPA，没有联网下载。
- 新增/修改测试：精确五本通过、10-for-5、正反组不一致、侧面第二排、prompt 合同保留、GLB-only
  不足、生命周期禁止跳转/显式晋升、三资产双风格覆盖、registry 不复用候选、32 GiB 有界门、
  `nvidia-smi` 回退和 429 不重试，共 13 个直接负向/合同检查。
- 执行命令：真实 TRELLIS 与 Blender 四视图均经 RAM/disk/GPU/cgroup 门串行运行；回归使用
  `python -m unittest discover -s sage/experiments/codex_trellis_scene_v2/tests -t .`、
  `python -m unittest discover -s tests -p 'test_*.py'`、`python -m compileall -q
  sage/experiments/codex_trellis_scene_v2` 与 `git diff --check`。
- 验证结果：P013 审计 `ok=true`；4 个真实候选中 3 个 scene-specific approved 并经独立步骤 curated，
  1 个 count 拒绝。`book_stack` 覆盖为 3 个审核资产、3 个不同内容 hash、3 个 style signature，超过
  至少 3 资产/2 风格标准；V2 343/343、根测试 12/12，共 355/355，compileall/diff check 通过。
- 新产物目录：
  `/data/wsj/main/scene_runs/codex_trellis_v2/p013_asset_admission_20260901_v1`。
- 关键文件 SHA-256：准入审计
  `446f16ecd084175732259cb293d1b288e98699dfe06dcc42074214a203bbad3f`；审核库 manifest
  `7c9e5f5bda2647d906f44801011f70e5331c90adb941544211796a6eb6dd46de`；新 GLB
  `aa141c074ca1f38b41eb29d265752af3c84e16b14199af80057b3a32023d5ab7`；新 pilot report
  `e47db82e04f7aa75c8a3334b51270bd428f5a75400063ce28be8d0edb1b3b4c2`；新四视图 contact
  `08304f9b1b38ef24092071edc009e5a15a8b5da05e35ac7e17f99418663ee544`。
- 人工检查结论：三张 2D 来源各为隔离、透明背景、正好五本书；新 004 的 +/-y 清楚显示同一组五本，
  +/-x 仅显示同一排书籍深度差。旧 002 明确可见复制后的 10 本/双层，保留为拒收证据而未美化结论。
- 未解决风险：当前高频覆盖只正式验证 `book_stack` 一类，许可证范围诚实限定为 internal research；
  新 004 的侧轮廓深度不均，不适合要求齐平书脊的场景。count evidence 目前由人工或校准实例分割提供，
  未声称通用视觉模型可自动可靠计数。
- 下一入口：P014，建立提交级、CPU integration、Blender headless、nightly GPU 四层测试与 chaos
  恢复矩阵，并自动生成 release/status manifest。

每完成一个问题，按以下模板追加：

```markdown
### 断点 CP-YYYYMMDD-NN：PXXX 已完成

- 完成时间：
- 根因：
- 修改文件：
- 新增/修改测试：
- 执行命令：
- 验证结果：
- 新产物目录：
- 关键文件 SHA-256：
- 人工检查结论：
- 未解决风险：
- 下一入口：
```

## 8. 后续讨论记录规则

- 后续讨论发现的新问题，先分配新的稳定 ID，再写入“问题索引”和“当前问题详情”。
- 不把推测写成事实；推测必须放在“根因假设”，并附待验证方式。
- 同一根因造成的不同用户可见症状可以分成多个问题，但应明确依赖关系。
- 新证据推翻旧结论时，直接更新当前结论，并在断点中保留变更原因；不要堆叠互相矛盾的结论。
- 只有实际修复并完成全部验收后才能把状态改为 `已完成`。
