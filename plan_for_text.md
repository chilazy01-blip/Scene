# 文生场景资产搜索与匹配设计备忘

## 文档状态

- 状态：设计备忘，尚未实施。
- 适用范围：TreeSAGE 文生场景为主，也可复用于图生场景的资产复用阶段。
- 当前目标：先为已有 TreeSAGE / Trellis2 GLB 建立小型、可验证、可解释的资产库；暂不直接接入大规模外部资产集，也不立即训练新模型。
- 相关入口：
  - 文生资产匹配：`sage/scripts/tree_sage_text/assets.py`
  - 图生资产复用：`sage/scripts/run_tree_sage_scene.py`
  - WebUI：`sage/webui/server.py`

## 背景与当前局限

当前文生资产库匹配的核心是 `_resolve_library_asset()`。它按以下顺序寻找文件：

1. alias 指向的直接路径；
2. `<library>/<alias>.glb`；
3. `<library>/<alias>`；
4. `<library>/<object_id>/<object_id>.glb`；
5. `<library>/<object_id>/asset.glb`。

这套机制适合已知对象 ID 的确定性复用，但本质上是路径解析，不是资产搜索。它目前不会判断：

- `desk` 与 `shelf` 是否语义相近但物理类别不同；
- 资产的真实长宽高和轴比例是否适合目标对象；
- 资产是落地、贴墙、挂墙还是吸顶物体；
- 桌面、床面、柜顶等支撑面是否真实可用；
- 颜色、材质和家具风格是否与整个场景一致；
- canonical front/up、推荐 yaw 和原始尺度是否可靠；
- GLB 是否损坏、含地面伪影、几何异常或不适合复用；
- 多个独立选出的资产组合后是否风格冲突或尺寸不协调。

因此，未来不应把 alias 文件无限扩展成手工检索数据库，而应保留 alias 作为显式覆盖层，在其下增加可解释的检索与验证系统。

## 设计目标

新的资产选择链建议采用：

```text
结构化查询
  -> 硬约束过滤
  -> 多模态 Top-K 召回
  -> 单资产精排
  -> 场景级联合选择
  -> 资产姿态/物理 QA
  -> 自动复用、人工确认或生成回退
```

核心原则：

1. 物理兼容优先于语义相似。
2. 召回和验证分离，低成本搜索不直接决定最终资产。
3. 对低置信度保持保守，不强行复用错误资产。
4. 单物体得分之外，还要考虑整个场景的风格和尺度一致性。
5. 每次选择都应生成报告，能够追溯候选、得分、拒绝原因和回退路径。

## 一、资产目录与元数据

### 1.1 建议的资产记录

第一版可以使用 JSONL 或 SQLite，每个资产至少保存：

```json
{
  "asset_id": "validated_wood_desk_001",
  "path": "/path/to/validated_wood_desk_001.glb",
  "category": "desk",
  "semantic_class": "furniture",
  "synonyms": ["writing desk", "office desk", "书桌", "办公桌"],
  "caption": "compact warm-oak writing desk with two drawers",
  "dimensions_m": {"width": 1.2, "length": 0.62, "height": 0.75},
  "placement_type": "floor",
  "attachment_class": "floor_against_wall",
  "support_capabilities": ["tabletop"],
  "style_tags": ["modern", "warm", "wood"],
  "material_tags": ["oak", "wood"],
  "color_tags": ["warm_brown"],
  "canonical_front_axis": "-Y",
  "canonical_up_axis": "+Z",
  "quality_status": "approved",
  "quality_flags": [],
  "license": "local_generated",
  "turntable_dir": "renders/validated_wood_desk_001",
  "embedding_refs": {
    "text": "embeddings/text/validated_wood_desk_001.npy",
    "image": "embeddings/image/validated_wood_desk_001.npy",
    "shape": null
  }
}
```

### 1.2 建议补充的几何与质量字段

- mesh/component 数量；
- 顶点、三角面数量；
- texture 是否存在、分辨率和格式；
- GLB 是否可加载；
- 原始 bounding box、质心和落地高度；
- 长宽高排序和轴比例；
- 是否包含明显大平面或地面伪影；
- 是否有可用碰撞代理；
- 是否经过 cleanup；
- 是否经过人工验收；
- 历史使用次数、成功率和被拒绝原因。

### 1.3 资产状态

建议至少有：

```text
approved       可自动复用
review         只能进入候选，需人工确认
quarantined    禁止自动复用
regenerate     已知不适合，应重新生成
```

## 二、结构化检索查询

不要直接用完整 prompt 搜索资产。应先把每个目标对象转换成结构化查询：

```json
{
  "object_id": "desk",
  "category": "desk",
  "description": "compact warm wooden writing desk",
  "dimensions_m": {"width": 1.25, "length": 0.65, "height": 0.75},
  "placement_type": "floor",
  "attachment_class": "floor_against_wall",
  "required_support_capabilities": ["tabletop"],
  "style_tags": ["modern", "warm", "wood"],
  "material_tags": ["oak", "wood"],
  "color_tags": ["warm_brown"],
  "reference_crop": null
}
```

文生场景主要使用文本、场景风格和尺寸字段；图生场景还可以加入 reference crop 或 source image。两条流程最终使用同一资产索引和评分接口。

## 三、硬约束过滤

以下条件应在向量召回前或精排前直接过滤，不能依赖相似度得分补偿：

1. 物理类别不兼容，例如 desk 不得匹配 wall shelf。
2. placement type 不兼容，例如 floor furniture 不得匹配 wall slab。
3. attachment class 不兼容，例如 window、curtain、door 与普通家具分离。
4. 目标需要支撑顶面，但资产没有相应 support capability。
5. 目标需要 articulation，但资产是刚性 GLB。
6. 单轴缩放倍率或轴比例超出安全范围。
7. GLB 损坏、缺失、被 quarantine 或 license 不允许使用。
8. canonical front/up 不可恢复，且对象对方向敏感。

建议继续沿用当前尺寸保护的保守思想：语义相似不能覆盖明显的物理矛盾。

## 四、多模态 Top-K 召回

### 4.1 文本召回

使用以下文本构造查询：

```text
category + subcategory + shape + material + color + style + affordance
```

资产侧同时保存人工标签、文件名、自动 caption 和历史 alias。第一版可以使用通用 text embedding；不建议只用 object ID 的字符串相似度。

### 4.2 多视图图像召回

为每个 GLB 统一生成 8 或 12 个 turntable 渲染视角，并保存：

- 单视图 embedding；
- 多视图平均 embedding；
- 最具区分度的正面/侧面 embedding；
- 带透明背景的缩略图和 contact sheet。

图生查询使用 reference crop 或 source image；文生查询可使用文本生成的 image2 source image。多视图匹配应使用最大相似度与平均相似度的组合，避免某一个偶然视角决定结果。

### 4.3 3D 几何召回

第二阶段再接入 OpenShape、ULIP-2 或 Uni3D，将 mesh 采样为规范化点云并生成 shape embedding。它适合区分：

- desk 与 console table；
- armchair 与 office chair；
- floating shelf 与 bookcase；
- panel curtain 与厚重家具；
- 具有相同文本类别但几何轮廓不同的候选。

第一版不依赖 shape embedding：现有 GLB 多视图渲染加尺寸过滤已经能覆盖大部分实际需求，部署成本也更低。

### 4.4 近邻索引

小型资产库可以直接遍历或使用 SQLite；规模增大后使用 FAISS/HNSW。召回阶段建议保留 20 到 50 个候选，精排后输出 Top-3 或 Top-5。

## 五、单资产精排

完成硬过滤后，可从以下初始权重开始：

| 信号 | 初始权重 | 说明 |
| --- | ---: | --- |
| 文本语义 | 0.30 | 类别、形状、材质、功能和描述 |
| 多视图视觉 | 0.25 | reference/source image 与资产渲染图 |
| 3D 几何 | 0.15 | 可选，第一版可先置零并重分配 |
| 尺寸相容 | 0.15 | 长宽高、轴比例和缩放倍率 |
| 风格相容 | 0.10 | 场景级 style/material/color |
| 资产质量 | 0.05 | 验收、加载、方向、纹理和历史稳定性 |

这些权重只是工程初值，后续应通过选择日志和验证结果调整。评分报告至少保存：

```json
{
  "target_object_id": "desk",
  "candidate_asset_id": "validated_wood_desk_001",
  "score": 0.86,
  "components": {
    "semantic": 0.93,
    "visual": 0.84,
    "geometry": 0.81,
    "dimensions": 0.90,
    "style": 0.78,
    "quality": 1.0
  },
  "scale_ratios": [1.04, 1.05, 1.0],
  "warnings": [],
  "decision": "candidate"
}
```

## 六、场景级联合选择

单物体最高分不一定构成最佳场景。每个对象完成 Top-K 后，应对候选组合进行二次选择：

- 床、床头柜、书桌和衣柜的木色是否协调；
- 多个金属/布料家具是否属于相近风格；
- 左右成对家具是否应该复用同一资产；
- 同一场景是否出现不合理的过度重复；
- 床与床头柜、桌与椅的绝对尺寸是否协调；
- 候选替换后是否显著增加布局碰撞；
- 资产的 front/up 与预期 wall/contact 关系是否一致。

可以将场景级目标写成：

```text
总单体得分
+ 风格一致奖励
+ 成对/系列一致奖励
- 尺度不协调惩罚
- 重复滥用惩罚
- 碰撞与支撑风险惩罚
```

第一版无需做复杂全局优化，可以采用：主锚点优先选择，然后按功能团簇逐个重排，例如 bed cluster、desk-chair cluster、window-curtain cluster。

## 七、资产验证与回退

候选选中后仍需经过：

1. GLB 加载检查；
2. 原始尺寸和单位检查；
3. canonical orientation 检查；
4. 支撑面和落地面检查；
5. 碰撞代理与地面伪影检查；
6. 单资产 turntable 或正交视图复核；
7. 放入场景后的碰撞、支撑和尺度验证。

建议的置信度分流：

```text
高置信度且验证通过       -> 自动复用
中等置信度               -> WebUI 展示 Top-3，等待人工确认
低置信度                 -> 生成新的 source image + Trellis2
物理结构不兼容           -> 禁止复用
已知坏资产               -> quarantine / regenerate
```

alias 应保留最高优先级，作为人工确认后的显式覆盖；但 alias 指向的资产也不能跳过损坏、尺寸和物理兼容检查。

## 八、WebUI 交互建议

未来可新增独立的“资产匹配”阶段：

1. 文生 plan-only 先生成 scene graph 和 asset query。
2. WebUI 展示每个对象的 Top-3 候选缩略图。
3. 每个候选显示总分、尺寸、风格、质量状态和拒绝警告。
4. 用户可选择“采用”“重新搜索”“从零生成”“固定为 alias”。
5. 确认结果写入 run-specific alias/selection 文件。
6. 完整运行只消费已经确认的资产选择，避免规划和资产生成耦合。

建议产物：

```text
asset_catalog.jsonl
asset_query_report.json
asset_retrieval_candidates.json
asset_scene_rerank_report.json
asset_selection.json
asset_validation_report.json
```

## 九、分阶段实施路线

### 阶段 A：确定性小型资产库

- 扫描现有已生成 GLB；
- 提取尺寸、mesh、texture 和路径元数据；
- 统一生成 turntable；
- 标记 approved/review/quarantined；
- 保留现有 exact ID 和 alias 行为；
- 输出完整索引与 QA 报告。

验收标准：已有验证资产可以稳定复用，坏资产不会被自动选中，所有决定可以追溯。

### 阶段 B：文本与多视图检索

- 自动 caption 或人工补充 category/synonym；
- 生成文本和图像 embedding；
- 实现硬过滤、Top-K 召回和尺寸/质量精排；
- WebUI 显示 Top-3；
- 记录人工选择反馈。

验收标准：不同 object ID 但同语义的资产无需手写 alias 也能进入候选；desk/shelf 等物理近邻不会混淆。

### 阶段 C：3D shape embedding

- 规范化 mesh/point cloud；
- 评估 OpenShape、ULIP-2、Uni3D 的依赖和本机运行成本；
- 离线生成 shape embedding；
- 比较几何检索对细分类别的增益。

验收标准：在文本和二维外观相近的 hard-negative 候选中，几何精排能稳定改善 Top-1/Top-3。

### 阶段 D：场景级重排与反馈学习

- 对功能团簇做组合选择；
- 纳入风格、尺度、碰撞和支撑信号；
- 使用人工选择与验证报告校准权重；
- 建立资产使用成功率、回退率和误匹配统计。

验收标准：整场景风格和比例优于逐物体独立 Top-1，并且不会以碰撞或物理失败为代价。

### 阶段 E：外部资产扩展

- 评估 3D-FUTURE、Objaverse/Objaverse-XL 等数据源；
- 先做 license、文件质量、方向、尺度、纹理和类别过滤；
- 外部资产默认进入 review/quarantined，而不是 approved；
- 通过统一 QA 后再并入本地检索库。

## 十、评估指标

离线检索：

- category Top-1 / Top-3 accuracy；
- hard-negative 误匹配率；
- 尺寸倍率超限率；
- attachment/support 不兼容率；
- 人工候选接受率；
- 新生成回退率。

场景运行：

- asset missing/failure 数量；
- 资产复用成功率；
- aggregate collision conflict 数量；
- support validation 失败数；
- canonical pose 修复次数；
- global validator 通过率；
- 资产 cleanup/regeneration 次数和资源消耗。

评估集应包含容易混淆的对象对，例如：

```text
desk / console table / wall shelf
office chair / dining chair / armchair
wardrobe / bookcase / cabinet
curtain panel / wall panel / room divider
rug / floor slab
table lamp / floor lamp / ceiling light
```

## 十一、参考工作及可借鉴点

### Holodeck

- 论文：[Holodeck: Language Guided Generation of 3D Embodied AI Environments](https://arxiv.org/abs/2312.09067)
- 可借鉴点：对象查询同时包含描述和尺寸；资产检索组合 CLIP 视觉相似度、Sentence-BERT 文本相似度和 3D bounding-box 尺寸；选择资产后再进入约束布局。

### OpenShape

- 论文：[OpenShape: Scaling Up 3D Shape Representation Towards Open-World Understanding](https://arxiv.org/abs/2305.10764)
- 可借鉴点：将文本、图像和点云对齐到共享空间，使用 cosine similarity/kNN 支持文本到 3D、图像到 3D 和形状到 3D 检索；适合作为后续几何检索层。

### Cap3D

- 论文：[Scalable 3D Captioning with Pretrained Models](https://arxiv.org/abs/2306.07279)
- 项目：[Cap3D](https://cap3d-um.github.io/)
- 可借鉴点：利用多视图渲染、图像 caption 和语言模型为 3D 资产生成可检索描述，适合批量补齐本地 GLB 的 caption 元数据。

### ULIP-2 与 Uni3D

- 论文：[ULIP-2: Towards Scalable Multimodal Pre-training for 3D Understanding](https://openaccess.thecvf.com/content/CVPR2024/html/Xue_ULIP-2_Towards_Scalable_Multimodal_Pre-training_for_3D_Understanding_CVPR_2024_paper.html)
- 论文：[Uni3D: Exploring Unified 3D Representation at Scale](https://openreview.net/forum?id=wcaE4Dfgt8)
- 可借鉴点：文本、图像和 3D 表征对齐，可作为 OpenShape 的替代候选；在第一版完成前不建议同时接入多个重型 3D encoder。

### 3D-FRONT 与 3D-FUTURE

- 论文：[3D-FRONT: 3D Furnished Rooms With layOuts and semaNTics](https://openaccess.thecvf.com/content/ICCV2021/html/Fu_3D-FRONT_3D_Furnished_Rooms_With_layOuts_and_semaNTics_ICCV_2021_paper.html)
- 论文：[3D-FUTURE: 3D Furniture shape with TextURE](https://arxiv.org/abs/2009.09633)
- 可借鉴点：室内家具的高质量纹理、类别和风格兼容信息；适合参考 catalog 字段和场景级家具组合逻辑。

### LayoutGPT 与 AnyHome

- 论文：[LayoutGPT: Compositional Visual Planning and Generation with Large Language Models](https://arxiv.org/abs/2305.15393)
- 论文：[AnyHome: Open-Vocabulary Generation of Structured and Textured 3D Homes](https://arxiv.org/abs/2312.06644)
- 可借鉴点：先生成结构化场景表示或空间约束，再做具体布局/几何处理；支持将文生对象查询和资产选择从自由文本中解耦。

### Objaverse-XL

- 论文：[Objaverse-XL: A Universe of 10M+ 3D Objects](https://arxiv.org/abs/2307.05663)
- 可借鉴点：提供极大规模的开放资产候选，但质量和来源高度多样；若未来接入，必须先经过 license、重复、网格、方向、尺度、纹理和安全过滤。

## 十二、当前推荐结论

若未来开始实施，优先选择以下最短路径：

1. 建立本地 GLB catalog 和 approved/quarantined 状态；
2. 生成统一多视图渲染；
3. 实现硬约束过滤；
4. 用文本 embedding + 多视图视觉 embedding + 尺寸重排得到 Top-3；
5. 接入 WebUI 人工确认和 alias 固化；
6. 收集真实误匹配后，再决定是否引入 OpenShape/ULIP-2/Uni3D。

这样可以在不训练模型、不下载超大资产集、不改变现有场景求解框架的前提下，先获得比纯文件名/alias 匹配更强的泛化能力，并保持每个决定可解释、可验证、可回退。
