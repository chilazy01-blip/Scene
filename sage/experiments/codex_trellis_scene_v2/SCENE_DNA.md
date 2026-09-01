# SceneDNA：约束感知的混合资产协同

## 目标

SceneDNA 解决的不是“给 TRELLIS.2 Prompt 多加几个风格词”，而是让审核资产库检索与缺失资产生成共享同一份、可审计的场景设计合同。

它把两类约束分开：

- 硬约束：类别、物理尺寸、能力、canonical front、手性、支撑/容纳/碰撞/净空。任一失败都拒绝候选，风格分数不能补偿。
- 软约束：风格家族、冷暖、色板、材料、形态语言、细节密度和关系组一致性。只在硬约束已经通过的候选之间重排。

这避免了两种常见失败：为了风格选择尺寸错误的资产，以及为了全屋一致把办公椅、杯子、拖鞋等都强制变成同一种木材和颜色。

## 当前管线

```text
SceneBrief + typed scene graph + architecture
  -> 收集尺寸兼容且已审核的候选锚点
  -> 编译 scene_dna_contract.json
  -> 硬门禁过滤候选
  -> SceneDNA 分面软重排审核资产
  -> 对真正缺失的对象编译同一合同下的隔离单物体 Prompt
  -> Flux 生成 4 个隔离 2D 候选
  -> alpha/白底 QA + 类别/部件语义硬门 + 类别无关形态 profile 硬门
  -> 融合 SigLIP2 语义、单图形态、DINOv3 审核锚点和原外观分数
  -> 分数接近或评分器冲突时，Top-2 用同一 TRELLIS.2 seed 晋级
  -> Blender 正/反 X/Y 四视角结构与外观审核
  -> 失败时换 seed，最多重新生成 2 轮；保留最高分候选
  -> generated_asset_harmony_certificate.json
```

当前实现文件：

- `scene_dna.py`：合同、关系组、候选评分、生成规格扩展和证书。
- `assets.py`：两阶段锚点/重排接入、生成计划和证书落盘。
- `scene_dna_multiview.py`：透明转台渲染调度、四视角像素/轮廓/缩放审核和 contact sheet。
- `scene_dna_semantic.py`：SigLIP2 类别/必需部件/禁用部件评分、类别无关形态 profile、DINOv3 审核锚点和不确定性判定。
- `scene_dna_benchmark.py`、`scene_dna_candidate_benchmark_runner.py`：冻结的 7 类别 × 2 风格 × 3 seed × 4 候选基准。
- `scene_dna_candidate_rescore.py`：不重新生成图片，按新版合同迁移并离线重算已有冻结候选。
- `scene_dna_benchmark_analysis.py`：按全局、类别、风格和形态 profile 汇总硬失败、门禁、改选和 Top-2 诊断。
- `scene_dna_blind_review.py`：隐藏分支/左右随机化/10% 重复题的盲评页面，以及按原 case 聚类的 bootstrap 分析。
- `scene_dna_guard_blind_round.py`：提取当前选择器与形态门的 held-out 差异案例、硬资格复核、私有联系表和冻结清单。
- `scene_dna_3d_benchmark_runner.py`：固定 Prompt、seed、步数和尺寸，仅改变 2D 参考图的配对 GLB 测试；支持重算已有多视图评分。
- `scene_dna_effectiveness.py`：同批候选、同 seed 的第一候选基线与 SceneDNA 选择真实 GLB A/B。
- `trellis2_flux_bridge_server.py`：四张真实 2D 候选、硬 QA、SceneDNA 排序和延迟加载 TRELLIS。
- `blender_render_asset_turntables.py`：可选透明背景、目标尺寸适配和归一化审计。
- `pipeline.py`：在最终 summary 中暴露合同、证书和复核状态。

同一管线可用 `--scene-dna-mode` 做公平消融：

- `legacy_coarse_tags`：保留旧风格标签排序与旧单物体 Prompt。
- `user_prompt_only`：只使用用户文本风格，不使用资产锚点或局部关系组。
- `global_anchor_only`：只使用审核锚点的全局共识，不使用用户风格或局部关系组。
- `relation_aware`：默认完整 SceneDNA。

## 风格来源优先级

```text
明确用户文本
  > 用户参考图（接口预留，当前未接入）
  > 尺寸兼容且已审核资产的共识 + 已冻结建筑材料
  > 房型默认值
```

低优先级来源不能覆盖明确用户要求。例如用户明确要求暖色现代风时，冷色古典锚点不能把合同改成冷色古典。

关键词抽取使用英文词边界和更具体的风格短语；`reduced perspective` 不会被识别为 `red`，`minimal occlusion` 也不会被识别为极简风格。

## 全局、局部与个体

- 全局合同描述房间整体的风格家族、冷暖、主色板、材料和形态语言。
- 局部关系组由 typed scene graph 编译。`mirror_symmetric`、`supported_by`、`tucked_under`、`contained_in`、`faces` 等关系有不同审美耦合强度。
- 物件个体保留 grounded appearance terms；规则扩写没有该字段时，从包含该类别的用户原句提取局部外观。例如“白色暖调卧室中的米色编织收纳箱”会把 `beige/fabric/woven_fabric` 记为收纳箱个体要求，排序时优先于房间全局 `white`。暖木书桌仍可搭配现代黑色办公椅；两者共享现代语言，但不要求同材质同颜色。

当前元数据评分按 facet 计算，而不是要求候选命中所有标签。风格家族和冷暖权重较高，色板与材料允许对象级对比。分数只表示 manifest 元数据相容性，不等于视觉相容性。

## 三类审计产物

### `scene_dna_contract.json`

包含来源证据、全局描述、关系感知局部组、对象个体标签、硬门禁顺序、软阈值、生成预算与失败策略，并带稳定 `contract_hash`。

### `missing_asset_generation_plan.json`

每个缺失物件保留隔离单物体 Prompt、目标比例和尺寸元数据，并新增：

- `scene_dna_contract_hash`
- 对象的全局/局部/个体风格上下文
- `isolated_2d_candidates=4`
- `max_candidates_promoted_to_trellis2=2`
- `max_harmonization_loops=2`
- 生成后多视图验收要求

### `generated_asset_harmony_certificate.json`

证书绑定 SceneDNA 合同 hash、资产文件 SHA-256、Prompt SHA-256、尺寸门禁、2D 候选排序和生成后四视角报告。输入变化会产生不同证书 hash。

生成资产在没有多视图验收时只能是 `multiview_evaluation_required`；计划中的资产是 `generation_planned`。SigLIP2/DINOv3 是冻结模型的候选排序与拒绝证据，不等于人工语义真值；四视角自动检查通过时仍保持保守证书语义，独立盲评完成前不把“模型认为更像”写成“视觉质量已经证明提升”。

## 当前已完成与尚未完成

已完成：

- 同一合同参与审核资产选择和缺失资产 Prompt 编译。
- 风格排序位于尺寸等硬门禁之后。
- 关系感知的局部审美组与对象个体差异。
- 4 张真实 Flux 候选的 alpha/白底硬 QA，以及 SigLIP2 语义、7 类类别无关形态 profile、DINOv3 审核锚点和原像素风格分的可审计融合。
- 所有候选都不满足语义或形态硬门时整批失败/重试，不再选择“最不差但明显错误”的候选。
- Top-1/Top-2 分差过小或评分器冲突时，两个候选使用同一个 TRELLIS.2 seed 晋级并比较。
- 冻结 168 候选基准计划、候选生成器、2D/3D 隐藏标签盲评包、隐藏重复题、一致性统计和 case-clustered bootstrap 已实现。
- 三名独立评审者的 90 条 alpha-safe v3 答案已匿名归档并完成正式统计；主要指标 `0.516358`，未通过预注册门槛。
- 第二轮 beta 已用全新 seed 扩展到 10 类并生成 60 批/240 张图片；47 批通过旧硬门，18 个“当前选择器与形态门确实不同”的 case 已完成 20 题中文离线盲评。3 名新评审的原始主要指标为 `0.474537`；后续新增色溢审计发现 36 张独立候选中 18 张失败且两分支不平衡，因此该值只保留为受混杂的诊断，不能作为干净的 guard 负向证明。
- TRELLIS 延迟到 2D 筛选完成后才加载，避免 Flux 与 TRELLIS 同时争用显存。
- 生成 GLB 的透明四视角转台、正反视图一致性、碎片、紧凑物体轮廓、目标尺寸适配缩放和外观检查。
- 多视图失败后最多两轮换 seed 重生成；只有通过通用 3D 可用性硬门的候选可以装配，整批失败时明确终止，不再保留“最高分失败品”进入场景。
- 隔离 2D 生成默认统一浅灰背景；RMBG 后清零透明隐藏 RGB、清理半透明边缘色溢并硬拒残留。盲评图片统一预合成为 `(224,224,224)` RGB PNG，`audit-images` 在冻结前检查全部图片。
- 新链已用真实 FLUX.1-schnell 512x512 书堆验证：生成背景估计 `[229,225,217]`、色度范围 `12`，RMBG/bridge/问卷导出色溢门均通过；最终固定灰背景 RGB 图无可见彩色边缘。输出在 `chroma_gray_real_smoke_20260826_v1`。
- hash 绑定的审计证书与保守验收语义。
- 复杂卧室真实 manifest 计划级 smoke。
- 单收纳箱真实 4→1→TRELLIS→四视角闭环 smoke。

尚未完成：

- 尚未接入用户风格参考图的视觉编码。
- SigLIP2/DINOv3 修正评分器的冻结 168 候选全量运行和首轮独立人工盲评均已完成；人工结果未证明总体有效。SigLIP 语义差值在这批开发数据上与人工语义偏好反向，不能继续作为无条件正向替换依据。
- 最初 7 类开发 pilot 的 DINO 特征曾因 fp16 token 平均产生 NaN，旧代码又把非有限值错误夹成高分；该批排名已作废，不得作为效果证据。现在改为 fp32 全局 token、有限值硬检查，但必须重新跑。
- 拖鞋 Prompt/合同已改为明确的 open-back slide；`open_back_footwear` 形态 profile 用端部高度比例硬拒封闭高鞋跟/乐福鞋。人工结果显示冻结 proposed 拖鞋仍明显偏负；当前重评分已经把最严重的彩色地台候选判为 form 不合格，但仍需新批次验证。
- 当前形态特征仍是单视图 alpha 形态学，不能证明完整 3D 拓扑；多视图评估也不等于物理碰撞证明。
- 当前 manifest 主要只有粗粒度 `styles`；需要逐步补充 palette/material/form/detail 的审核字段或视觉 embedding。
- 第二轮隐藏问卷已收齐 3 名新评审者并解盲；semantic/form 偏好率为 `0.495370/0.453704`，没有支持形态门。后续色溢审计未通过，故该轮既不能晋级，也不能作为干净的负向证据；不再补做 3D non-regression。
- 新增休闲椅 6/6 批被 `skeletal_support` 硬门拒绝，餐椅仅 3/6 批可评估，说明单视图通用椅子轮廓门仍存在明显泛化缺口。

因此当前版本已是可运行的“合同、语义/形态/锚点融合、硬拒绝、不确定 Top-2、同 seed 配对 3D、四视角自动拒绝和盲评工具”闭环；首轮人工统计接近持平，第二轮 `form_improvement_guard` 隐藏验证反而低于持平，两轮均未过门槛，默认旧主链不得被替换。类别无关 `0.08` form guard 保持默认关闭，不应在相同数据上继续调阈值；后续必须更换证据设计并重新做全新隐藏验证。

第二轮冻结根目录是 `/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_guard_blind_round2_20260824_v1`；
评审者只能接收 `SceneDNA_blind_review_2D_beta_offline.html`。18 个独立题的实验方案左右严格 9:9，
2 道隐藏重复题与原题至少间隔 4 位，且与首轮公开 case 和图片 SHA-256 零重合。

## 真实闭环证据

最终样例：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_real_harmonization_storage_box_20260822_v8_final
```

固定 Prompt 为一个暖调现代卧室中的米色编织布收纳箱，Flux 生成 4 张候选并按对象局部 `beige/fabric/woven_fabric` 排序，最优候选分数 `0.911762`；CLIP tokenizer 实测最终模板在该样例为 71 tokens，不再截断核心类别/外观。单次 TRELLIS.2 生成即通过，GLB 约 3.48MB、60,287 vertices、95,370 faces。四视角自动分数 `0.809`，四图 bbox fill 为 `0.9229–0.9679`、detached component ratio 全为 0、正反视图最低一致性 `0.99187`、尺寸适配缩放各向异性 `1.755884`，合同 hash 在 2D 排序、多视图和证书中一致。

开发中旧样例 `scene_dna_real_4candidate_storage_box_20260822_v2` 虽得到旧像素分 `0.80539`，人眼四视图发现底部破洞和悬浮黑色碎片；新增紧凑轮廓/碎片硬门槛后会正确拒绝。该反例必须保留，不能只报告最终成功图。

语义/形态选择器的冻结开发基准位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v1
```

计划固定 7 个结构族（收纳箱、书架、书堆、办公椅、台灯、植物、成对拖鞋）、2 种风格、
3 个候选批次 seed、每批 4 图，共 168 个候选。公开盲评包不含 baseline/proposed 标签，默认
加入至少一道独立左右随机化的隐藏重复题；密钥单独保存，统计时重复题归回原 case，避免扩大
样本量。当前 2D 公开包与密钥为 `blind_review_bundle` / `sealed_blind_key.json`；透明修复后的
3D 版为 `blind_review_bundle_3d_alpha_fix_v2` / `sealed_blind_key_3d_alpha_fix_v2.json`（2 个独立
case + 1 个隐藏重复题）。旧 `blind_review_bundle_3d` 含修复前背景板，只作历史诊断，不得交给
评审者。它们是评测工具和开发样例，不是已经完成的人工实验。

最初一次每类单批 pilot 因 DINOv3 fp16 token 平均产生 NaN 且非有限值处理错误而失效；旧排名
不得引用。修复后使用 fp32 全局 token 并拒绝任何非有限分数，SigLIP2 的全部正负假设也合并
为一次前向。

修正代码的正式冻结候选运行位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v2
```

`candidate_results_full_v1` 共计划 42 批/168 图：41 批成功，1 个 office-chair 批次因 4 个候选
全不满足硬门而拒绝，硬批次失败率 `0.023810`；其余 164 个结构化候选的 alpha、form、semantic
和 joint-eligible 通过率为 `0.969512/0.804878/0.945122/0.756098`。成功批次中 25/41 改变
candidate-0，33/41 晋级 Top-2。table-lamp 的 form 候选通过率最低（`0.541667`），office-chair
是唯一整批失败类别。改选率与 Top-2 率只说明系统做了非平凡选择和不确定性保留，不是更好看的
证据。

修正包括：DINOv3 模型本身改用 fp32 前向并硬拒非有限特征；无匹配锚点时不加载 DINO；通用
required-part 默认不再作为类别硬门；开放书架允许实体背板并使用重复水平层结构；拖鞋增加
`open_back_footwear` 端部高度硬门。冻结全量运行可 deterministic shard/resume，批次失败会留存
结构化 artifact 而不是中止整个实验。

人工预检发现 v2 题包中的浅色收纳箱和部分书堆被 white-base repair 误删主体。旧 28 题 2D
和依赖旧 alpha 的 8 题 3D 包均已作废，不得作为正式收益证据。修复后的检测要求低位浅色区域
既足够宽，又与上方主体透明分离或仅窄连接；同宽连续主体和不足全物体 50% 宽的稀疏轮辐受到
保护。修复后还执行损伤审计，删除超过 35% 前景、触及受保护上部或造成内部水平断层时回滚。

`scene_dna_alpha_reprocess.py` 使用保存的原始 Flux RGB 重跑 RMBG，不重做 2D 生成或 GLB。新根目录
`scene_dna_semantic_form_benchmark_20260823_v3_alpha_safe` 中 41 个成功 case/164 张候选全部通过
alpha QA；48 处连续浅色主体受到保护，1 处宽地面残留被删除，0 次损伤回滚。重新计算 SigLIP2、
form 和 DINOv3 后 41 批全部可选，27 批改变旧式选择，33 批晋级 Top-2。

当前正式 2D 公共包为 v3 根目录下的 `blind_review_bundle_2d`，密钥为
`sealed_blind_key_2d.json`，含 27 个独立 case + 3 道隐藏重复题，共 30 题。离线单文件为
`SceneDNA_blind_review_2D_alpha_safe_offline.html`。alpha-safe v3 的预注册 7 类 3D 配对已在
独立 v4 目录重新生成；最终收益仍需独立人工标签与 case-clustered 95% CI 共同确认。

预注册的 7 类同 seed 配对 3D 位于 `paired_3d_stratified_v1`。每类按冻结顺序选首个“改选且
Top-2”的成功批次，不看 3D 后挑样本；7 个 case 的 baseline/proposed 共 14 个 GLB 和 14 份
四视角报告均生成，0 个生成异常。首轮回放暴露旧像素门会放过连接式地台、鞋下承载板和封闭
物体小面积破洞。现按形态合同增加内部孔洞率、下部相对过宽和下部持续满宽三项通用特征，并
对原 14 个 GLB 离线复算。修正后只有 potted-plant 为自动正向；storage-box、book-stack、
office-chair 为负向；bookcase、table-lamp、slipper 为双分支硬失败。该混合结果明确说明 2D
语义/形态/风格排序不能替代 TRELLIS 可生成性预测。

正式 3D 公共包为 `blind_review_bundle_3d`，密钥为 `sealed_blind_key_3d.json`，包含 7 个独立
case + 1 道隐藏重复题。评审规程见 `BLIND_REVIEW_PROTOCOL.md`。自动 3D 非回归门当前不通过，
所以默认替换继续禁止；人工盲评用于量化问题，不得覆盖已经观察到的 3D 硬失败。

透明输入的 3D 受控复测位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v1/paired_3d_alpha_fix_v2
```

旧 bridge 把已经抠图的 RGBA 以 `preprocess_image=false` 送入 TRELLIS.2，隐藏 RGB 背景会被
DINO 编码并重建成彩色平面。现在只要检测到有效透明度就强制执行 TRELLIS 的 alpha 裁切/预处理，
并同时记录 requested/effective 值。修复后椅子两分支的大背景板消失，均成为完整三维椅子；
自动结论为 `inconclusive_or_small_effect`。台灯基线仍把参考图中的电线/地面残留重建为巨大
矩形并失败，SceneDNA 选择分支生成完整台灯并通过，结论为 `positive_effect`。这证明透明预处理
修复和该台灯个案有效；两个开发 case 不能推广为 7 类总体收益。

多视图碎片门现读取 `semantic_form_contract.shape_profile`：办公椅等 `skeletal_support` 允许
脚轮/底座等合理投影分件，`slender_radial` 台灯仍保持严格分离比例，避免用统一 8% 阈值同时
错杀组件资产和放过电线/平台。已有渲染可通过 3D runner 的 `--refresh-evaluation` 重算，不需
重新生成 GLB。

## v4 工程安全与验收优化

工程安全优化期间没有改写正在收集答案的 30 题 v3 离线问卷，也没有提前读取或解盲首份人工答案。冻结页面仍为
10,032,325 bytes，SHA-256 为 `565483420c7b2e271debaf584cb85563b7910c13fda0ee30a421a5dee09d5e9d`。

新增能力：

- 材质按类别无关的形态 profile/部件角色编译适用范围。例如金属只能作为拖鞋扣件、书本装饰或
  花盆细节，不能把整只拖鞋、整摞书或整株植物变成金属。
- Top-K GLB 增加通用四视角可用性选择器，联合视角完整度、碎片、内部孔洞、下部地台、正反一致性
  和尺度各向异性；所有候选硬失败时整批拒绝。旧 7 类/14 GLB 历史回放中，4 组存在可用候选并
  可接受，3 组双分支失败被明确阻断。
- 最终 GLB 四视角增加冻结 SigLIP2 的类别/部件与风格对比证据；它参与排序和审计，但阈值在人工
  标签校准前保持实验性质，不能替代几何硬门或人工判断。
- 最终场景增加真实 RGB、归一化 depth 和遮挡后的 object-index 验收。实例图以单次发光材质编号
  渲染编码全部物件，不需要逐物件重渲；另新增 south-to-north、1.55m、65mm 正视检查。
- 后续新问卷源码支持图片加载失败标记、异常题跳过和返回重做；当前冻结问卷不回写，避免改变在途实验。
- 资产库新增覆盖审计。只有同类至少 3 个审核资产且至少 2 种显式风格签名时才称得上可以验证
  “选择重排”。当前 20 个审核资产覆盖 18 类；卧室 13 个必需类别全部低于该目标，因此没有虚构
  候选或自动入库。

alpha-safe v3 的真实重生成位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_v4_dev/paired_3d_alpha_safe_v4
```

冻结 7 个 case、同 seed A/B 共 14 个 GLB 全部生成成功。通用几何可用性统计为 baseline 4/7、
proposed 5/7；自动效果结论为 2 个 `positive_effect`、3 个小效应/不确定、2 个双分支硬失败。
proposed 的七类平均零样本语义分由 `0.408436` 升至 `0.493862`，平均风格对比分由 `0.515909`
变为 `0.497661`。这说明几何硬失败率没有恶化且语义证据改善，但书架与拖鞋仍失败、风格分没有
提升，不能据此开启默认替换。

完整卧室最终渲染验收位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_v4_dev/bedroom_render_acceptance_final
```

3 个正式视角的 RGB/depth/object-index 均有效，16/16 个 required 对象至少在一个视角真实可见，
12/16 至少在一个视角完整入画，0 个硬失败；床、右灯、左床头柜和衣柜仍有“没有任何一个投影
包围盒完全入画”的软告警。报告 `accepted=true`，但这些告警应留给后续相机覆盖优化。

本轮代码回归为 V2 203 项加仓库根 12 项，共 215 项全部通过。

## 后续实验

单物件真实候选选择 A/B 已加入
`scene_dna_effectiveness.py`。它复用同一批 4 张 2D 候选，以第一张作为旧式基线、排序最高张
作为 SceneDNA 分支，并固定对象 Prompt、TRELLIS.2 seed/steps/pipeline、纹理、减面目标、请求
尺寸和四视角评估器。首个收纳箱结果位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_effectiveness_storage_box_20260823
```

SceneDNA 2D 分数相对第一张为 `+0.005559`，生成后自动多视图分数为 `0.809000` 对
`0.806956`（`+0.002044`）；两者均通过结构门。尺寸适配各向异性由 `2.484680` 降到
`1.755884`，但参考外观分与正反一致性分别轻微下降 `0.004141` 和 `0.004520`。按预注册的
`0.02` 分差/通过状态/结构门判据，本次只能判为 `inconclusive_or_small_effect`，不能证明
SceneDNA 已带来稳定视觉提升。人工看图时，SceneDNA 分支具有更明确的箱盖、搭扣和完整箱体，
基线更简单但带有可疑侧面贴片；该观察未做盲评，不计作量化成功。

旧收纳箱结果说明原像素排序能改变 3D 结果但收益很小。多类别、多 batch、多 seed 的修正冻结
候选运行、预注册跨类别配对 GLB，以及隐藏分支标签和重复题工具现在已经完成；下一步不再扩
接口，而是邀请与开发无关的评审者分别判断类别语义、形态完整性、风格和总体偏好，并把 3D
孔洞、地台和断连作为 2D 候选可生成性负标签。只有主要指标
的 case-clustered 95% bootstrap 区间下界超过 0.5，并且硬失败率不升，才能考虑扩大试用；
否则继续保持实验 opt-in。

固定相同 SceneBrief、布局、尺寸、seed 和生成预算，对比：

1. 旧的粗风格标签 Prompt。
2. 只使用用户 Prompt。
3. 只使用全局资产锚点平均风格。
4. SceneDNA 的关系感知合同。

至少报告硬约束通过率、元数据/视觉风格分数、多视图一致性、人工盲选偏好、生成成功率、耗时/显存成本，以及跨卧室、书房、客厅、厨房、卫生间的风格坍缩率。不能只展示单个成功卧室。

首个受控 plan 消融保存在：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_ablation_20260822_v1
```

四种模式固定了 Prompt、SceneBrief 规则、建筑、请求尺寸、manifest 和生成预算。复杂卧室在四种模式下都复用 12 个资产、缺失 3 个实例并合并为 2 次生成；差异体现在风格证据和关系组。当前每个主要类别通常只有一个尺寸兼容审核候选，因此这个结果只证明消融接口与控制变量成立，不能证明 SceneDNA 已改善检索或视觉质量。要验证重排收益，必须先为同一类别加入多个经过审核但风格不同的真实候选。

## vNext 通用可生成性与第三、第四轮冻结结论

旧 `0.08` form guard 在第二轮人工盲评没有得到支持，而且会把休闲椅等整类拒绝。vNext 因此不再
让某个类别的单轮廓规则决定替换，而把每张候选拆成几类通用证据：主体是否完整入画、alpha 边缘
是否可信、结构是否连贯、轻微形态开运算后是否稳定、下部是否像额外平台、必需语义部件是否存在、
禁用部件是否出现，以及原 form 合同提供的软证据。选择顺序固定为：硬可生成性门、最弱证据、
平衡可生成性分、当前 semantic/form/style 综合分、稳定尝试顺序。没有类别特判，默认关闭。

工程 pilot 位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_pilot_20260826_v1
```

8 类/32 张全新 seed 中 8/8 批完成；原始尝试卫生率 31/32，失败草图被硬拒且未被选中；可评审
选择 11/11 通过。7 个双方都有 control 的 case 中 3 个改变选择，另安全救回 1 个当前选择器无
合格项的休闲椅 case。这是工程可行性，不是人工偏好证据。

正式第三轮位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_round3_20260826_v2
```

计划在看不到第三轮人工标签前冻结 10 类、2 风格、每组合 5 seed，共 100 独立批次与 400 个全局
唯一候选 seed；和第二轮、pilot 均零重合。连接中断恢复审计见
`RECOVERY_AUDIT_20260828.md`。最终 100/100 批完成，2 批被真实语义硬门拒绝，0 缺失；41 个干净
case 中 current 与 vNext 都合格但选择不同，另有 22 个 vNext rescue 因没有 current control 只作
覆盖诊断、不进入配对人工效应。

冻结没有通过：二次 chroma audit 的选中图卫生率为 `138/140 = 0.985714`，低于预注册 `1.0`；
一张失败图属于相同选择，另一张属于 changed pair，后者已排除。即使剩余 41 个干净差异对超过
30 题最低数，也禁止用删题绕过“全部选中图卫生 100%”门。因此没有生成第三轮离线问卷，没有
人工收益结论，也不生成晋级用配对 3D。默认链、旧 form guard 和 vNext 均保持关闭。

卫生问题随后在独立数据上修复：bridge 记录源图真实背景色，最终只审计 alpha=0 隐藏 RGB；公开
准备阶段使用该 provenance 做非变异审计，不再把已清理的黄色/暖色主体边缘当背景重新估计。合成
回归和真实 FLUX+RMBG 灰背景 smoke 均通过，第三轮数据没有被重处理或复用。

第四轮根目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_round4_20260828_v1
```

先冻结独立 10 类/40 图 preflight；40/40 原始图和 14/14 选中决策图通过卫生门，每类都有可生成
候选，工程门全部通过后才冻结正式 10 类 × 2 风格 × 5 seed = 100 批、400 个新候选 seed。正式
100 批全部有终态：96 批成功，3 批被必需语义合同拒绝，1 批被可生成性门拒绝；2 个早期 timeout
文件已有同 case 成功结果，只保留作基础设施审计。双方选择器都合格且选择不同的公平 case 为 38，
另有 16 个 vNext rescue 不进入配对效应。134 张决策相关图的透明边缘卫生和统一中性背景均为
`1.0`，达到预注册冻结门。

公开第四轮为 `SceneDNA_blind_review_2D_round4_offline.html`，含 38 个独立题和 4 道隐藏重复题；
vNext 在独立题左/右各 19 次，与前两轮公开 case、图片哈希和历史候选 seed 零重合。公开 HTML
不含 sealed key、方法标签或分数。当前只能说“工程门通过且具备盲测条件”，不能说 vNext 已改善
人工偏好。收集 3–5 名未参与开发的新评审者后，按预注册 semantic/form 指标统一分析；只有 2D
通过后才生成同 seed 配对 3D，且 3D 硬失败率不劣化后才讨论扩大 opt-in。默认选择链保持不变。
