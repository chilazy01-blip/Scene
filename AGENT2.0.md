# Scene 项目研究与问题台账（AGENT 2.0）

> 本文件是当前研究路线的长期状态文档。它不是一次性的实验日志，也不替代 `AGENT.md` 中的仓库与运行环境说明。
>
> 后续工作开始前应先读取本文件；遇到新问题时建立带编号的问题记录，解决后在原记录上更新状态、结论、证据和回归要求，不要只在文末追加时间线。

## 0. 文档状态

- 文档版本：2.2
- 最后更新：2026-07-24
- 工作目录：`/data/wsj/main/scene`
- 仓库、环境与接续断点：`/data/wsj/main/scene/AGENT.md`
- 当前实验主线：`sage/experiments/codex_trellis_scene_v2`
- 当前研究主题：capability/SDF pilot、请求相机，以及生成参考图 soft observation 的隔离验证
- 当前原则：先解决刚性物件的从属、支撑、包含和紧凑接触；软体、铰链与深层动态物理延后

### 状态枚举

| 状态 | 含义 |
|---|---|
| `OPEN` | 问题明确，但尚未完成方案设计 |
| `DESIGN` | 正在定义数据结构、算法或验收标准 |
| `IMPLEMENTING` | 已进入代码实现 |
| `VALIDATING` | 已实现，正在真实资产或多场景中验证 |
| `RESOLVED` | 已有可复现方案并通过当前验收 |
| `DEFERRED` | 有意延后，已记录重新启动条件 |
| `ACCEPTED_RISK` | 当前用途允许保留的已知限制 |

优先级采用 `P0/P1/P2/P3`：`P0` 阻塞主路线，`P1` 是近期核心，`P2` 是重要增强，`P3` 是后续研究。

## 1. 项目目标与当前边界

项目目标是从文本或参考图生成可编辑、结构清楚、空间合理并能逐步升级为物理可验证的室内 3D 场景。系统需要同时处理：

1. 房间建筑结构：地板、墙、门洞、窗洞及其附属构件。
2. 大型家具布局：床、桌、椅、柜、书架等。
3. 小物件关系：物件在桌面、床面、搁板、柜格或其他容纳空间中的放置。
4. 资产检索与临时生成：优先复用审核资产，资产库缺口才临时调用 FLUX/TRELLIS.2。
5. 几何合理性：避免不允许的穿透，同时建立有意的接触、支撑和包含。
6. 视觉合理性：满足请求相机、完整入画、遮挡、构图和 RGB-D 数据集风格要求。
7. 后续交互性：门、抽屉、铰链等 articulation，以及模拟器中的动态稳定性。

当前不把以下目标纳入第一版 SDF 试验：

- 枕头、被褥等软体形变。
- 门和抽屉的动态铰链/滑轨。
- 摩擦、倾倒、动态冲击等完整物理模拟。
- 将临时 TRELLIS.2 资产直接提升为审核资产。
- 用 SDF 取代所有 AABB、通道规划和建筑约束。

## 2. 已确认的当前基线

### 2.1 当前布局并非没有 bbox

V2 已有基于目标物理尺寸的旋转 footprint/AABB：

- `validator.py` 根据 `width/length/yaw` 计算顶视包围盒。
- AABB 用于房间边界、门口净空、地面家具碰撞、支撑对象碰撞、占用率和通道栅格。
- `repair.py` 使用相同 footprint 做确定性碰撞修复。
- `composition.py` 将尺寸盒投影到请求相机，估算完整入画和 bbox 遮挡。

因此当前缺口不是“没有碰撞概念”，而是：

> 只有由语义尺寸驱动的 2.5D 粗代理，没有基于最终 GLB 真实形状的 3D 窄相位碰撞、支撑和包含约束。

现有 AABB 仍应保留为 broad phase、房间占用、通道规划和快速布局工具。

### 2.2 类型化树骨架与关系图第一版已经落地

V2 现已生成 `scene_graph_initial/resolved/final.json`：

- room 是唯一根节点，建筑结构、opening、家具和子物件都有唯一主要父节点。
- `supported_by/contained_in/against_wall/faces/left_of/right_of/in_front_of/aligned_with/mirror_symmetric/clearance_from` 等作为补充关系边。
- layout 和 repair 后会刷新 world pose；可解析父节点同时记录 parent-local pose。
- validator 会硬检查重复节点、缺失父节点、层级循环、悬空关系、缺失镜像参考物和执行组成员冲突。

因此 `GRAPH-001/002` 的第一版已解决。尚未解决的是 capability graph 中真实支撑面、柜格、容纳空间，以及多来源关系置信度/冲突协议；这些继续由 `GRAPH-003`、`ASSET-002` 和 `VISION-002` 跟踪。

### 2.3 临时缺失资产链已达到布局测试可用水平

已完成 GLB 的历史测试目录（早于枕头组成吸收）：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_missing_assets_quick_v3
```

当前结论：

- 17 个场景实例中复用 12 个，缺失 5 个。
- 只生成书堆、收纳箱、枕头 3 个唯一资产。
- 重复收纳箱和枕头复用同一 GLB。
- 三张 FLUX 图不再受到完整卧室 Prompt 污染。
- 最终 GLB 可加载，Blender 装配成功。
- 该链只作为资产库缺失时的布局占位方案，不继续投入生成精修。
- 书堆仍带展示底座，不进入审核资产库。

上述 `17/5/3` 数量只描述该历史 GLB，不能作为当前 SceneBrief 数量。启用枕头组成吸收后，严格卧室为 15 个物理对象，缺失资产为书堆和两个收纳箱，共 3 个实例、2 个唯一生成规格；当前只完成 plan-only 回归，未重复投入临时资产生成。

### 2.4 枕头的当前保留策略

第一阶段将普通枕头视为床资产整体的一部分：

```text
bed_asset_policy = integrated_bedding
```

实现状态：

- 唯一床场景中的显式普通枕头会转成床的 `component_requirements`。
- 枕头不进入独立资产解析、FLUX/TRELLIS.2 生成或 layout。
- 审核资产 manifest 有 `included_components` 时核验数量；缺少字段时记录 `assumed_satisfied_by_composite_asset`，不谎称已验证。
- 多床、无床或明确要求可独立控制时保留独立实例，不做猜测性吸收。

软体接触和形变仍由 `SOFT-001` 延后。

### 2.5 成对/匹配实例已有独立执行层

`instance_groups` 与 ownership tree、typed relations、advisory `constraint_scopes` 分离：

- 每个成员仍是独立对象、独立 mesh/instance mask/collision shape。
- 一个对象最多属于一个执行组，但可出现在多个 advisory scope。
- 资产阶段优先同一 `asset_family_id`；缺少 family 时可按 contract 复用同一审核资产或共享生成规格。
- 普通 relation CSP 后再统一 canonical front、受限调整组内顺序/间距，并用刚性整体平移搜索 anchor 区域。
- validator 检查 cardinality、成员互斥、role order、间距、anchor、朝向和资产 family。

该层已达到布局测试可用水准；真实左右脚 family、镜像几何和 group-first 联合布局尚未完成。

## 3. 已达成的研究共识

### 3.1 主表示：树骨架 + 类型化关系图

不在“树”与“网络”之间二选一。目标表示由两部分组成：

1. **Primary hierarchy**：每个节点只有一个主要父节点，用于所有权、局部变换、生命周期和优化顺序。
2. **Typed relation graph**：允许跨分支关系，用于支撑、包含、朝向、对齐、邻接、操作净空和可见性。

纯树不足以表达“椅子属于房间但朝向桌子”“柜子属于房间但贴墙”“书从属于书架格位且由搁板支撑”等多重关系；完全自由的网络又容易产生循环、冲突和不确定的优化顺序。

### 3.2 建议的层级骨架

```text
room
├── envelope
│   ├── floor
│   ├── ceiling
│   ├── north_wall
│   ├── south_wall
│   │   └── entry_opening
│   │       └── entry_door
│   ├── east_wall
│   │   └── window_opening
│   │       └── window
│   └── west_wall
└── contents
    ├── bed
    ├── desk
    │   ├── book_stack
    │   └── cup
    └── bookshelf
        └── shelf_compartment_2
            └── books
```

层级名称不是最终 schema，但需保留以下语义：

- 门窗属于具体 opening，opening 属于具体墙。
- 家具属于房间 contents，不与墙、地板混为同类节点。
- 子物件应绑定具体支撑面或容纳槽，而不是只绑定父物体总体。

### 3.3 第一批关系类型

| 关系 | 含义 | 示例 |
|---|---|---|
| `part_of` | 不可独立布置的组成部件 | 门把手是门的一部分 |
| `included_by_asset` | 资产已经烘焙的视觉部件 | 床资产已经包含枕头 |
| `attached_to` | 固定附着 | 窗帘杆附着于墙 |
| `supported_by` | 受某表面支撑 | 杯子位于桌面 |
| `contained_in` | 位于有效容纳空间 | 书位于书架格位 |
| `against` | 靠墙或靠某表面 | 衣柜靠北墙 |
| `facing` | 功能朝向 | 椅子朝向书桌 |
| `aligned_with` | 轴向或中心线对齐 | 床与墙平行 |
| `adjacent_to` | 空间邻接 | 床头柜位于床旁 |
| `clearance_from` | 保留操作/通行净空 | 柜子避开门扇区域 |
| `visible_from` | 请求相机的可见性 | 显式物件完整入画 |

后续必须为关系增加 `hard/soft`、置信度、来源和冲突优先级，不能只有关系名称。

### 3.4 三类来源图

目标系统区分三种信息来源：

1. **Intent graph**：由 Prompt 得到，保存用户明确要求和允许的常识补全。
2. **Capability graph**：由实际资产得到，保存已有部件、支撑面、容纳空间、opening、关节状态和尺寸能力。
3. **Observation graph**：由参考图得到，保存视觉证据中的位置、朝向、遮挡、相对深度和关系置信度。

建议冲突优先级：

```text
用户明确要求
> 建筑与物理硬约束
> 实际资产能力
> 高置信参考图证据
> 房型常识先验
```

参考图是证据和修正来源，不是唯一事实来源。单张图无法可靠判断被遮挡或关闭柜门后的内容，也可能生成资产库无法支持的结构。

## 4. SDF 的预定职责

### 4.1 SDF 不替代场景语义

场景图定义“谁应该和谁发生什么关系”；SDF只负责“真实几何怎样实现这些关系”。SDF 本身不知道枕头应该接触床、书应该进入哪层搁板，也不知道哪些接触是允许的。

### 4.2 保留 AABB broad phase，增加 SDF narrow phase

建议流程：

```text
Prompt/参考图
→ 类型化场景图
→ 资产选择与组成消歧
→ AABB/footprint 粗布局
→ 获得真实 GLB 与碰撞代理
→ AABB broad phase 筛选候选对
→ 关系感知 SDF 窄相位优化
→ Blender 几何与请求相机验收
→ 必要时进入动态模拟
```

### 4.3 第一版 SDF 损失结构

概念目标：

```text
L = w_pose * L_pose
  + w_collision * L_collision
  + w_support * L_support
  + w_inside * L_inside
  + w_size * L_size_policy
  + w_semantic * L_relation_preservation
```

- `L_pose`：尽量保持粗布局、参考图和构图意图。
- `L_collision`：禁止与无关实体或父物体实体部分穿透。
- `L_support`：子物体底部与目标支撑面接近。
- `L_inside`：子物体留在指定容纳空间内。
- `L_size_policy`：禁止优化器破坏审核资产物理尺寸。
- `L_relation_preservation`：避免为消除碰撞而破坏 facing、against、adjacent 等功能关系。

### 4.4 柜体需要实体与容纳空间两种表示

书架/柜体不能只保存一个总体 SDF：

- `solid_sdf`：柜板、背板、搁板、柜门等不可穿透实体。
- `free_space/container_sdf`：具体柜格或搁板上方允许放置物件的空间。
- `support_surface`：该格位中实际承担重量的表面。

书放入书架的条件应同时满足：

1. 不进入柜板实体。
2. 位于指定格位容纳空间。
3. 底部接触指定搁板。
4. 保留用户或参考图要求的朝向与可见性。

### 4.5 不直接照搬 SceneThesis 的自由尺度优化

SceneThesis 会在多方向碰撞时缩小物件。当前项目已有 `fixed_physical/uniform_scalable/axis_scalable/opening_fit/modular` 尺寸策略，不能让 SDF 为了消除穿透任意缩小审核资产。

优化优先级暂定为：

1. 平移。
2. yaw。
3. 更换父槽位或局部重新布局。
4. 只有资产尺寸策略允许时才有限调整尺度。
5. 仍失败则报告约束不可满足，不伪造成功。

## 5. 参考图路线的定位

允许借用当前图生场景代码生成或解析参考图，但不把完整路线变成 SceneThesis 的直接复刻。

### 5.1 参考图适合提供的信息

- 左右、前后、相对距离。
- 功能朝向和局部排列。
- 物件是否明显位于开放格、桌面或床边。
- 相机相关遮挡和可见性。
- 文本没有明确描述的审美布局先验。

### 5.2 参考图不能单独决定的信息

- 被完全遮挡的物件。
- 关闭柜门后的内部物件。
- 单视图中的真实接触和穿透。
- 实际资产是否含有某个部件。
- 真实物理尺寸、摩擦、重心和铰链结构。

### 5.3 与 SceneThesis 的预定差异

如果完全复制“LLM → 参考图 → 分割/深度 → 场景图 → SDF → VLM judge”，研究路线会高度同质化。当前项目应把贡献集中在：

- 建筑结构与物件结构统一的类型化层级图。
- Prompt 对象与资产内部已有部件的消歧。
- 检索资产、生成资产共用的 capability graph。
- 支撑面、容纳空间、opening 和操作净空接口。
- Intent/capability/observation 三图的置信度融合和冲突处理。
- 关系感知 SDF，而不是统一的全场景排斥。
- 保留真实尺寸策略的几何优化。
- 同一结构同时服务 text-to-scene 与 image-to-scene。

## 6. 实施阶段与验收门槛

### Phase A：类型化场景图，不接参考图、不接 SDF

目标：把当前平级对象计划升级为主树与类型化关系边。

最低验收：

- 房间、墙、opening、门窗、家具、子物件有稳定层级。
- 每个节点只有一个 transform parent。
- 支持跨节点 typed relations。
- 关系记录来源和 hard/soft；跨 intent/capability/observation 的统一 confidence 继续由 `GRAPH-003` 跟踪。
- 能检测循环、孤儿节点和不可能关系。
- 旧平级 layout 能无损转换或提供兼容层。

当前状态：第一版 `RESOLVED`。真实 capability slots 和多来源冲突融合不计入本阶段完成条件。

### Phase B：资产 capability 与组成消歧

目标：选择父资产后重新核对其已经满足的子物件要求。

最低验收：

- 床自带枕头时不再生成普通独立枕头。
- 开放书架可以声明柜格、搁板和容纳空间。
- 资产缺少所需槽位时明确换资产、降级或报告失败。
- `included_by_asset` 不被当成可独立交互节点。

当前状态：`VALIDATING`。普通床—枕头组成消歧已完成；开放书架柜格、支撑面和容纳空间仍未实现。

### Phase C：刚性物件 SDF pilot

第一批只测试：

- 书进入开放书架格位。
- 杯子接触桌面。
- 收纳箱进入开放柜格。
- 椅子有限推进桌下且不穿透桌腿。

暂不测试枕头、被褥和铰链。

最低验收指标：

- AABB 假阳性/假阴性数量。
- 优化前后最大穿透深度。
- 支撑间隙或漂浮距离。
- 物件位移与 yaw 变化。
- 尺寸策略是否被保持。
- facing/against/adjacent 是否被破坏。
- 单资产 SDF 构建时间、缓存大小、单场景优化时间。

### Phase D：参考图 observation graph

目标：复用图生场景能力，输出带置信度的关系候选，并与 intent/capability graph 融合。

最低验收：

- 显式 Prompt 要求不会被低置信图像推断覆盖。
- 能记录冲突而不是静默选择。
- 单视图不能确定的 `inside/behind/occluded_by` 保留不确定状态。
- 参考图分支关闭时，文本主链仍可独立运行。

当前状态：`VALIDATING`（隔离布局位置先验）。已实现固定相机 FLUX 参考图、exact-ID
观察、对象/位置双置信阈值、拒绝审计和硬约束优先的有界 pose 投影；尚未实现完整
observation relation graph、三图通用冲突协议或默认主链接入。

### Phase E：请求相机与渲染后验收

目标：实现真正的 south-to-north、1.55m、65mm 正面眼平渲染，并在最终 RGB/depth/instance mask 上评估完整入画和遮挡。

当前 45° dollhouse 图只能用于调试，不能作为 strict front-facing Prompt 的最终验收。

### Phase F：动态物理与 articulation

重新启动条件：

- 刚性 SDF 支撑/包含已稳定。
- 资产 manifest 能表达 joint origin、axis、limits 和 collision shape。
- 门、抽屉等资产具备可分离活动部件。

## 7. 当前问题总表

| ID | 优先级 | 状态 | 问题 |
|---|---:|---|---|
| `GRAPH-001` | P0 | RESOLVED | 当前对象计划缺少统一的主层级 |
| `GRAPH-002` | P0 | RESOLVED | 纯树无法表达多重空间与功能关系 |
| `GRAPH-003` | P1 | VALIDATING | 关系冲突、来源、置信度和 hard/soft 协议 |
| `ASSET-001` | P0 | RESOLVED | Prompt 对象与资产内置部件重复 |
| `ASSET-002` | P0 | IMPLEMENTING | 最小 schema、审核桌面 support surface 和 desk/chair collision capability 已落地；命名 free-space 与柜格仍缺失 |
| `ASSET-003` | P1 | VALIDATING | 非 watertight GLB 的 voxel SDF proxy 与缓存已完成首个真实资产验证 |
| `GROUP-001` | P1 | RESOLVED | 成对/匹配实例缺少资产与布局执行组 |
| `GROUP-002` | P2 | OPEN | 审核库缺少可靠的真实 pair family、左右角色和镜像策略 |
| `SDF-001` | P0 | IMPLEMENTING | `cup_on_desk` 与桌下 dense/sparse 分类 pilot 已完成，尚未接入位姿搜索和完整 repair |
| `SDF-002` | P0 | IMPLEMENTING | `supported_by:desk.top` 与桌下禁止穿透已完成隔离 pilot，正式 `tucked_under` contract 尚缺 |
| `SDF-003` | P0 | OPEN | 包含关系需要 solid/free-space/support 三类约束 |
| `SDF-004` | P1 | VALIDATING | 首个 pilot 锁定 fixed scale 并验证尺寸策略保持，尚缺更多策略覆盖 |
| `SDF-005` | P1 | VALIDATING | desk/mug 构建与缓存、desk/chair dense/sparse 查询已测，尚缺分辨率与多资产压力测试 |
| `SDF-006` | P1 | OPEN | 碰撞修复可能破坏构图和功能关系 |
| `VISION-001` | P1 | VALIDATING | 参考图已作为可选 soft observation 进入隔离 A/B，尚缺多场景视觉验收 |
| `VISION-002` | P1 | IMPLEMENTING | exact-ID/双置信过滤和 hard-over-soft 已落地，通用三图冲突融合仍缺 |
| `CAMERA-001` | P1 | OPEN | 请求相机尚未在 Blender 最终渲染中实现 |
| `SOFT-001` | P3 | DEFERRED | 枕头等软体接触和形变 |
| `ARTICULATION-001` | P3 | DEFERRED | 门、柜门、抽屉的关节与动态碰撞 |
| `PHYSICS-001` | P2 | DEFERRED | MuJoCo 当前只适合作为后置 proxy，不是 SDF 替代品 |
| `LIBRARY-001` | P1 | ACCEPTED_RISK | 当前审核资产库覆盖不足，暂用生成资产占位 |

## 8. 问题详细记录

### GRAPH-001：缺少统一的主层级

- 状态：`RESOLVED`
- 现象：家具和小物件大体以平级列表存在，有限的 `support_id` 不能统一建筑、家具和子物件。
- 影响：局部坐标、父物体移动、SDF 优化顺序、删除传播和资产替换都难以保持一致。
- 最终方案：`scene_graph.py` 建立 room root、建筑层、opening 和物件节点的唯一 primary parent；布局和修复后物化 world/parent-local pose。
- 验收：所有节点可从 room root 到达；无循环；父节点移动时子节点保持局部关系。
- 证据：严格卧室 initial/resolved/final graph 均验证通过；当前 23 个节点、无重复、孤儿或循环。
- 回归要求：新节点类型必须声明主要父节点和 transform space；validator 不得把缺失父节点降为软告警。

### GRAPH-002：需要树骨架与跨节点关系图并存

- 状态：`RESOLVED`
- 现象：一个物件可能同时具有从属、支撑、朝向、靠墙和可见性关系。
- 影响：强行使用纯树会丢失关系；完全自由图会失去稳定优化顺序。
- 最终方案：唯一父树负责变换和生命周期，typed edges 负责支撑、包含、靠墙、朝向、顺序、对齐、镜像和净空；`constraint_scopes` 仅作可重叠计算/报告视图，`instance_groups` 仅作成员互斥执行视图。
- 验收：椅子可属于 room，同时 `facing desk`；书堆可从属于书桌并 `supported_by desk`。具体 shelf compartment/surface 节点依赖 `ASSET-002` capability 元数据。
- 证据：杯子和书堆可从属于书桌，椅子 `faces desk`、家具 `against_wall` 均进入 canonical brief、final graph 和 repair。
- 回归要求：新增关系不得改变 primary parent，除非关系本身是经过 grounding 的 ownership/support 更新。

### GRAPH-003：关系协议尚未统一

- 状态：`VALIDATING`
- 已完成：Codex typed-delta `relation_updates`、受限词表、稳定 ID、hard/soft、provenance、参数、exact evidence、本地拒绝/归一化报告；cardinal 2D CSP 已执行常见方向、间距、对齐、镜像和 target-facing。
- 尚缺：统一 confidence、跨 intent/capability/observation 的冲突状态、具体 capability slot，以及连续 yaw/真实几何执行。
- 风险：不同模块可能用相同名称表达不同物理含义。
- 验收：validator、planner、SDF 和渲染评分读取同一关系定义。

### ASSET-001：资产内置部件重复

- 状态：`RESOLVED`
- 当前案例：床资产已经带枕头，Prompt 又产生两个独立枕头。
- 最终方案：唯一床时把普通枕头实例吸收到床的 `component_requirements`，不进入独立资产生成和 layout；资产选择后再根据 `included_components` 核验或明确记录 assumed 状态。
- 长期方案：资产 manifest 声明 `included_components`；父资产选定后重新核对 Prompt 对象清单。
- 验收：床自带两个枕头且 Prompt 只要求普通两个枕头时，新增生成数量为 0。
- 证据：`bedroom_rgbd_pillow_component_plan_smoke_20260720` 中两个枕头从物理对象和 generation plan 移除。
- 回归要求：多床或无床不能猜测吸收；manifest 明示数量不足必须阻止装配。

### GROUP-001：成对/匹配实例缺少执行语义

- 状态：`RESOLVED`
- 优先级：`P1`
- 首次发现：2026-07-23
- 现象：两只拖鞋被当作两个无关实例轮换资产并分别修复，造成款式、canonical front、距离和床脚锚点不一致。
- 根因：`constraint_scopes` 只聚合报告，不改变资产选择和布局；ownership tree 也不适合表达“独立实例组成一个可整体调整的匹配集合”。
- 最终解决方案：新增 `instance_groups.py`、Codex/确定性 grounding、互斥成员 contract、同 family/同资产解析、组内间距与朝向归一化，以及 bounded rigid translation。
- 验收结果：严格卧室中两只拖鞋保持两个对象，复用同一审核资产，间距由 1.02m 收紧到 0.08m，整组位于床脚前方 0.25m；组验证 0 个硬违规。
- 证据/实验路径：`/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_instance_group_rules_plan_20260723`
- 回归要求：一个成员不得进入两个执行组；组不能修改 ownership/support；未验证左右几何只能是 soft QA，不能标记为真实 pair。

### GROUP-002：真实 pair family 与左右角色缺失

- 状态：`OPEN`
- 优先级：`P2`
- 首次发现：2026-07-23
- 现象：现有左右拖鞋 GLB 形状质量、raw extents 和 canonical front 不一致，不能可靠登记为同一审核 family。
- 当前临时方案：布局测试中复用同一审核资产以消除款式漂移，并报告 `instance_group_handedness_unverified`。
- 计划方案：优先引入已审核 pair bundle；其次定义 canonical asset + 几何镜像；manifest 增加 `asset_family_id/pair_role/mirror_policy`。
- 验收标准：左右成员属于同一 family、角色互补、几何与材质一致、Blender 装配朝向正确，且不靠名称猜测 handedness。
- 依赖项：资产 QA 与 Blender guarded mirror 支持。

### ASSET-002：缺少支撑面与容纳空间

- 状态：`IMPLEMENTING`
- 现象：只有总体尺寸，无法说明桌面、搁板、抽屉、柜格等局部可用区域。
- 已完成：新增最小 `codex_trellis_asset_capability_v1` contract、registry validator、`desk_warm_oak_001.top` 审核支撑面和 desk/chair collision capability；schema 同时保留 `containment_volumes` 空列表和组成字段。真实边缘探针中，父 AABB 接受极限边缘杯子位置，而审核 usable support rectangle 正确拒绝。桌椅 pilot 已能用足迹重叠与 SDF 无穿透区分桌外、合理推入和过度推入，但尚未把桌下空间声明为命名 capability。
- 计划方案：在保持当前 contract 最小化的前提下，为开放书架增加具体 `containment_volumes`、关联 `support_surface_id`、入口方向和开合/可见状态；`attachment_slots` 等到出现真实固定附着 pilot 再加入，不提前扩张 schema。
- 验收：书可以绑定具体格位与具体搁板，而不是只绑定整个书架。
- 证据：`capabilities/pilot_desk_mug_v1.json`、`capabilities/pilot_desk_chair_v1.json`、`/data/wsj/main/scene_runs/codex_trellis_v2/cup_on_desk_sdf_pilot_20260724_v2` 与 `/data/wsj/main/scene_runs/codex_trellis_v2/chair_under_desk_sparse_pilot_20260724_v1`。

### ASSET-003：真实 GLB 不一定适合直接构建 SDF

- 状态：`VALIDATING`
- 风险：TRELLIS.2 GLB 可能非 watertight、法线异常、多碎片、高面数或带展示底座。
- 已完成：新增 canonical mesh normalization、filled voxel occupancy + EDT signed-distance proxy、压缩 NPZ 缓存、source SHA-256 与坐标系校验。真实 desk/mug 均为非 watertight 且分别含大量 disconnected bodies，但 proxy 内外测试、保存/加载和缓存复用均通过。
- 关键修正：raw glTF 经 `trimesh` 读取时为 Y-up，不能直接沿用 Blender 导入后的 `asset_axis_to_z=2`；capability 现显式记录 `source_mesh_up_axis=y`，先转 Z-up 再做 canonical normalization。
- 验收：同一资产重复使用时不重复构建；符号在内部/外部测试点上稳定；代理不会封死需要保留的开放柜格。
- 当前边界：缓存复用和 desk/mug 符号已验证；开放柜格是否被 fill 错误封死仍未验证，因此不能关闭该问题。

### SDF-001：缺少 SDF 窄相位优化器

- 状态：`IMPLEMENTING`
- 计划方案：AABB 先筛候选对，SDF 只处理附近物件；按场景图从 architecture/anchor/parent/child 顺序增量优化。
- 非目标：删除现有 AABB 或使用全场景高分辨率稠密 SDF 替代通道规划。
- 验收：刚性 pilot 中能正确处理 AABB 无法表达的桌下和书架内部空间。
- 当前结果：隔离 `cup_on_desk` 已执行 AABB-only、generic mesh SDF、capability-aware SDF 三组对照。桌面中心三者均为 0m 支撑间隙、0 禁止穿透，说明当前审核桌 AABB 顶面本来就正确；capability 没有伪造数值提升。usable-surface 边缘探针则识别出 AABB 假阳性。桌下 pilot 使用真实审核 desk/chair，在 `outside/tucked/overinserted` 三个位置上由 166,249 顶点参考和 4,096 点运行代理得到 3/3 相同分类。
- 尚缺：杯子仍只优化 `translation_z`；桌椅当前只分类预设位置，尚未执行连续位姿搜索、正式 `tucked_under` typed relation 或完整 layout/repair。

### SDF-002：缺少关系感知碰撞策略

- 状态：`IMPLEMENTING`
- 现象：统一“零接触”会让杯子漂浮；统一“允许重叠”会导致实体穿透。
- 已完成第一片：`supported_by:desk.top` 允许杯底在 capability contact tolerance 内接触，其他 mug surface sample 继续执行 forbidden-penetration；桌椅 pilot 同时验证合理推入时 0 深度穿透、过度推入时 dense/sparse 均判 collision。报告分别记录 support gap、SDF 距离、穿透点数/比例和分类一致性。
- 计划方案：把同一 contract 泛化为 relation compiler 输出的 `allow_contact_with`、`forbid_penetration_with` 和容差，不在 optimizer 中硬编码 mug/desk 类别。
- 验收：杯底接触桌面但不进入桌板；椅子进入桌下但不穿透桌腿。

### SDF-003：包含关系不能只靠一个总体 SDF

- 状态：`OPEN`
- 计划方案：柜体分别维护 solid、free-space/container、support surface。
- 验收：书位于目标柜格、接触搁板且不进入柜板；换到关闭或无开放格的柜体时明确失败或换资产。

### SDF-004：优化器可能破坏真实尺寸

- 状态：`VALIDATING`
- 风险：照搬 SceneThesis 的 scale collision loss 会通过缩小床、椅、柜子来消除碰撞。
- 计划方案：接入现有尺寸策略；fixed 资产锁尺度，其余资产按声明范围加惩罚或硬限制。
- 验收：不存在未经策略允许的尺度变化；失败时报告约束不可满足。
- 当前证据：`cup_on_desk` 只开放 `translation_z`，mug fixed scale 全程保持 `[1,1,1]`，报告 `dimension_policy_preserved=true`。尚未覆盖 axis-scalable/modular 或不可满足场景。

### SDF-005：构建成本和符号稳定性未知

- 状态：`VALIDATING`
- 需要测量：代理生成时间、不同分辨率误差、GPU/CPU 内存、缓存大小、查询吞吐和多实例复用。
- 计划方案：优先测试 64³/128³ 或 narrow-band/sparse 表示，不预设最终技术。
- 验收：完整场景成本可控，且不会因非封闭网格产生大面积符号翻转。
- 当前测量：desk 0.0125m proxy 首次构建约 2.82s、约 55KB；mug 0.004m proxy 约 0.16s、约 20KB。第二次运行两个 proxy 均命中缓存。真实桌椅三个位置的 SDF 查询中，166,249 顶点参考约 30.5ms，4,096 点运行代理约 1.0ms，点数减少 40.588 倍、观测约 31 倍加速且 3/3 分类一致。该数据只覆盖当前资产、位置和 CPU 环境，不能外推为完整场景成本。

### SDF-006：物理修复可能破坏语义和构图

- 状态：`OPEN`
- 现象：只最小化穿透可能把椅子移离桌子、把床移出中轴或破坏贴墙关系。
- 计划方案：保留 pose、facing、against、adjacent、camera visibility 等约束，并对移动设置预算。
- 验收：碰撞改善不能以破坏硬语义关系为代价；软关系变化必须进入报告。

### VISION-001：参考图的角色

- 状态：`VALIDATING`
- 决策：参考图是 observation graph 的来源，是可选增强分支，不是唯一布局事实。
- 原因：单图受遮挡、幻觉、深度误差和资产差异影响。
- 已完成：实验分支 `experiment/reference-soft-layout-prior` 使用本地 FLUX.1-schnell
  生成固定 south-to-north 图；默认文本布局保持独立。高置信位置只作为 soft loss，
  靠墙物件只沿原墙切向移动，自由物件限制最大位移，任何候选必须通过原硬验证。
- 当前生成器决策：实验分支已把直接 Image API `gpt-image-2` 设为默认 provider；
  `flux1-schnell` 仅为显式本地回退，禁止静默回退以免污染模型来源。当前环境没有
  `OPENAI_API_KEY`，所以默认路径已由单元测试验证，但尚未完成已认证 API smoke。
- 真实证据：`reference_soft_prior_study_smoke_20260724_v4` 使用 120 词短空间契约；
  生成图仍出现重复椅子和额外柜体，观察器省略无法唯一匹配的 chair。0.75 双阈值后
  接受 4/5 个观察，RMSE `0.678722 -> 0.638185`，对象/尺寸/建筑/关系不变且 0 硬违规。
- 边界：该 RMSE 只证明遵循了已接受 observation，不证明最终 3D 视觉优于文本布局。
- 生成器对照：`reference_image_model_compare_study_20260724_v1` 使用同一 120 词 Prompt
  和同一视觉审计器。FLUX 目标数量 4/5、额外大型家具 4、墙面 0/4；Codex 内置图生
  目标数量 5/5、额外大型家具 0、墙面 3/4，但仍有 5 个附件和 5 个装饰物。两边关系和
  门窗均通过。Codex 内置工具未暴露后端模型 ID，不能标为已验证 API `gpt-image-2`；
  单样本与审计波动也不支持模型排名。
- 验收：关闭参考图分支后，文本场景图和 SDF 主链仍能独立运行。
- SDF 融合边界：参考图只生成带置信度的 observation 目标，不生成碰撞几何。真实 GLB
  的 solid SDF、support surface、containment/named free-space 和 dimension policy
  决定可行域；Prompt/typed relation 与建筑为硬约束。先用 AABB broad phase，再用
  稀疏表面点查询缓存 SDF；只在硬约束和穿透阈值通过的候选中最小化 observation、
  semantic relation 与 pose-change 软损失。首个接入目标是
  `chair_tucked_under_desk` 的命名 free-space、粗到细 tuck-depth/yaw 搜索和 facing 保持。
- SDF 融合实证：上述第一接入目标已在隔离 pilot 完成。capability schema 新增审核
  `free_space_volumes`；typed graph 新增 hard `tucked_under`，强制绑定 target-local
  `free_space_id`。v2 搜索以合成软 observation `(0.04,-0.40,0), yaw=170°, conf=0.85`
  为目标，在 833 个候选中拒绝 197 个空间外和 377 个 SDF 碰撞候选，选出
  `(0.0375,-0.53,0), yaw=173.75°`。4,096 点运行代理与 166,249 顶点离线检查同判
  `valid_under`；dense 最小距离 `-0.001641m`，小于 0.0125m voxel tolerance，0 个
  deep-penetrating vertices；fixed scale 与 15° facing 门禁通过。输出：
  `chair_under_desk_reference_guided_search_20260724_v2`。该目标是合成 observation
  contract，尚不是已认证 image2 观测。

### VISION-002：三图融合与冲突处理

- 状态：`IMPLEMENTING`
- 已完成：观察只允许 exact SceneBrief ID；未知、重复、非法坐标、低对象置信和低位置
  置信均进入拒绝报告。对象集合、尺寸、建筑和 hard relations 不可被 observation 覆盖；
  不可安全满足时保留原文本布局。
- 计划方案：融合 intent、capability、observation；保存每条关系来源和置信度；不静默覆盖冲突。
- 验收：低置信图像推断不能覆盖显式 Prompt；资产不具备格位时不能假装完成 `inside`。

### CAMERA-001：真实请求相机缺失

- 状态：`OPEN`
- 当前问题：layout proxy 已记录 south-to-north、1.55m、65mm，但 Blender 仍输出 45° dollhouse 预览。
- 影响：无法真正验收 strict front-facing、eye-level、完整入画和最终遮挡。
- 验收：输出请求相机 RGB/depth/instance mask，并在渲染结果而非计划 bbox 上重新评分。

### SOFT-001：软体关系

- 状态：`DEFERRED`
- 当前策略：普通枕头作为床整体的一部分生成，不参与第一批 SDF。
- 重新启动条件：刚性支撑/包含稳定，且项目确实需要可拆卸床品。
- 未来候选：类别特定软接触容差或简化形变模型，不预设使用刚性零穿透。

### ARTICULATION-001：铰链与抽屉

- 状态：`DEFERRED`
- 当前策略：门窗只做静态建筑装配，铰链数据库与动态验证延后。
- 重新启动条件：资产能提供分离部件、joint origin、axis、limits 和 collision shapes。

### PHYSICS-001：SDF 与 MuJoCo 的边界

- 状态：`DEFERRED`
- 结论：SDF 用于布局期几何可行性、接触和包含；MuJoCo 用于后置重力、摩擦、倾倒和 articulation 验证。
- 当前 MuJoCo proxy 不覆盖最终 GLB 精确网格和建筑铰链，不能替代 SDF，也不能被称为完整物理验证。

### LIBRARY-001：审核资产库覆盖不足

- 状态：`ACCEPTED_RISK`
- 当前策略：缺失资产才使用 FLUX/TRELLIS.2，生成到可用于布局占位即可，不做多轮精修。
- 长期方案：审核资产库形成后优先检索；生成链仅作为兜底。
- 风险：生成网格不稳定会增加 SDF collision proxy 的清理成本。

## 9. 已解决问题与当前方案

### RESOLVED-001：显式物件被软上限截断

- 状态：`RESOLVED`
- 方案：软上限只限制自动推断 optional，用户显式物件和功能核心不受其删除；保留 `hard_runtime_limit=40`。
- 证据：复杂卧室 17 个显式实例全部进入最终 layout。

### RESOLVED-002：构图分数含义不清

- 状态：`RESOLVED`
- 方案：明确 composition 是装配前的 bbox 相机投影 proxy，拆分 framing、clarity、centeredness、symmetry，不宣称是最终 RGB 评分。
- 剩余工作：`CAMERA-001` 负责真实渲染验收。

### RESOLVED-003：资产尺寸被布局任意拉伸

- 状态：`RESOLVED`
- 方案：引入 `fixed_physical/uniform_scalable/axis_scalable/opening_fit/modular` 尺寸策略和资产匹配过滤。
- 回归要求：未来 SDF 优化必须服从同一策略，见 `SDF-004`。

### RESOLVED-004：完整场景 Prompt 污染单物体生成

- 状态：`RESOLVED`
- 方案：建立 `missing_asset_generation_plan.json`，只向 FLUX 发送类别局部的单物体 Prompt；相同规格只生成一次并复用 GLB。
- 真实验证：`bedroom_rgbd_missing_assets_quick_v3` 中 3 张参考图均为单物体。
- 已知限制：组合 Prompt 仍可能超过 CLIP 77 tokens，但本轮实际输出可用；不作为当前优先项。

### RESOLVED-005：基础建筑材质过于空白

- 状态：`RESOLVED`
- 方案：地板使用程序化木板，墙壁使用程序化暖白灰泥；门窗与建筑 opening 已进入装配流程。
- 剩余工作：材质真实感不是 SDF 主线，不在本阶段继续精修。

### RESOLVED-006：类型化主树与补充关系图

- 状态：`RESOLVED`
- 方案：建立唯一父节点树、类型化跨节点关系、initial/resolved/final graph 和 parent-local pose 物化。
- 验证：图节点、父级、关系端点、循环和镜像参考检查已进入 validator；严格卧室图通过。
- 回归要求：保持旧 layout 兼容，不把 advisory scope 或执行组误写为 ownership parent。

### RESOLVED-007：Prompt 关系理解未进入可执行结构

- 状态：`RESOLVED`
- 方案：Codex expansion 输出 typed deltas，本地 grounding 编译到 canonical SceneBrief；layout/repair/validator 共享关系执行与 target-facing。
- 验证：杯子转属书桌、书桌/衣柜墙面、椅子朝向书桌均进入 final graph，SDK repair 后保持。
- 剩余工作：confidence 和三来源冲突融合继续由 `GRAPH-003/VISION-002` 跟踪。

### RESOLVED-008：匹配物件资产与布局各自漂移

- 状态：`RESOLVED`
- 方案：以 `instance_groups` 表达资产和布局执行集合，成员仍保持独立实例。
- 验证路径：`bedroom_instance_group_rules_plan_20260723`；当前 102 个 V2 无模型 unittest 全部通过，仓库根另有 12 个，skill `scene-instance-group-planning` 校验通过。
- 已知限制：真实左右脚 family 和 Blender 镜像未完成，见 `GROUP-002`。

## 10. 第一批实验设计

第一批 SDF pilot 不直接跑完整复杂卧室，建立一个可解释的小场景集合：

1. `cup_on_desk`：已完成第一版；验证刚性支撑、零漂浮、禁止穿透、usable support surface 和 proxy 缓存。
2. `chair_tucked_under_desk`：命名 free-space、正式 typed relation、参考目标引导的粗到细位姿搜索、尺寸锁、chair-facing 和 dense/sparse 最终候选同判均已完成；下一步把 whole-room observation 转为 target-local relation target 并接入普通 repair。
3. `books_in_open_shelf`：验证 solid/free-space/support 三重约束。
4. `box_in_open_cubby`：验证不同尺寸容纳和格位切换。

每个案例至少保存：

- 原始 layout JSON。
- 主层级和 typed relations。
- 资产 capability metadata。
- 原始 GLB 与 collision proxy。
- SDF 构建参数。
- 优化前后变换。
- 碰撞深度、支撑距离和关系保持报告。
- Blender 前后对比渲染。
- 运行时间和缓存统计。

成功标准不是“损失下降”，而是：视觉关系正确、尺寸策略保持、几何穿透受控、支撑成立；若 AABB 原结果已经正确，capability/SDF 必须保持无回归，并通过 usable surface、桌下空间或柜格等 AABB 无法表达的案例证明额外精度，不能强求或伪造连续指标提升。

## 11. SceneThesis 参考资料

本地材料：

```text
/data/wsj/main/materials/Scenethesis/arxiv.pdf
/data/wsj/main/materials/Scenethesis/summary.md
/data/wsj/main/materials/Scenethesis/physics_aware_optimization.py
/data/wsj/main/materials/Scenethesis/text_to_3d_interactive_scene_generation.py
```

外部资料：

- Paper: https://arxiv.org/abs/2505.02836
- Project: https://research.nvidia.com/labs/dir/scenethesis/
- OpenReview: https://openreview.net/forum?id=SzhezVoaNB

借鉴重点：层级优化、表面采样查询 SDF、collision/stability 联合约束、视觉指导。

不可直接照搬：自由尺度缩小、把参考图作为主事实、未适配当前资产尺寸政策和建筑 opening 的统一流程。

## 12. 下一步工作顺序

1. 不重复实现 `cup_on_desk`；先以当前报告和缓存作为 SDF 基线，并保留 raw glTF Y-up 与 Blender Z-up 的独立坐标契约。
2. 基于已完成的 desk/chair dense/sparse 分类，为 typed graph/capability contract 增加最小 `tucked_under`/命名 free-space 表达，并补位姿搜索、尺寸锁和 chair-facing 保持。
3. 桌椅语义 contract 稳定后，为一个真正开放的审核书架定义 `solid proxy + containment_volume + support_surface`；必须先验证 voxel fill 不会封死开放柜格。
4. 完成 `books_in_open_shelf` 和 `box_in_open_cubby`，再决定是否把 capability/SDF 接入完整 V2 repair。
5. 对不同 voxel pitch、缓存命中、查询吞吐和非 watertight 符号稳定性做小型消融；不预设当前 dense EDT grid 是最终表示。
6. 补齐真正的请求相机渲染和最终 RGB/depth/instance-mask 评分，作为 SDF 前后视觉关系保持门槛。
7. 对实例组做一次真实 `gpt-5.6-sol` plan 和可选 Blender GLB 视觉验收；不要把同资产复用误写成真实左右脚完成。
8. 参考图 soft-prior 已提前在隔离分支完成单个 study 安全 smoke；保持默认主链关闭，先做多 Prompt/seed、等资产 Blender A/B 和最终 RGB/depth/mask 评分，再决定是否扩大 observation graph，不复制完整 SceneThesis 管线。
9. 根据资产库需求处理 `GROUP-002`，但不为当前布局占位链投入过多资产精修。
10. 软体和 articulation 保持 deferred，直到各自重新启动条件满足。

## 13. 维护规则

每次工作窗口结束前：

1. 更新“文档状态”的最后更新时间和当前研究主题。
2. 新问题必须分配稳定 ID、优先级和状态。
3. 已有问题解决时更新原条目，不另建重复问题。
4. `RESOLVED` 必须记录方案、验证路径、测试结果和回归要求。
5. `DEFERRED` 必须写明延后原因和重新启动条件。
6. 实验输出必须使用新目录，不覆盖旧基准。
7. 失败实验也要记录失败原因和可复现路径，但不要把原始长日志粘贴进本文件。
8. 决策发生变化时保留旧决策的简短原因，并把当前有效结论写在最前。
9. 不记录 token、密码、API key 或其他凭据。
10. `AGENT.md` 继续保存仓库、环境和全局项目进度；本文件专注研究路线、问题生命周期和解决方案。

### 新问题模板

```markdown
### CATEGORY-NNN：问题标题

- 状态：`OPEN`
- 优先级：`P1`
- 首次发现：YYYY-MM-DD
- 现象：
- 根因或假设：
- 影响范围：
- 当前临时方案：
- 计划方案：
- 验收标准：
- 依赖项：
- 证据/实验路径：
- 最终解决方案：
- 回归要求：
```

### 决策记录模板

```markdown
### DEC-NNN：决策标题

- 日期：YYYY-MM-DD
- 决策：
- 原因：
- 被否决方案：
- 影响的问题 ID：
- 重新评估条件：
```
