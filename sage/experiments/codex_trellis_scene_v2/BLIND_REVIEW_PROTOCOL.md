# SceneDNA 独立盲评操作规程

本规程覆盖已完成的 alpha-safe `20260823_v3_alpha_safe` 首轮实验，以及已完成解盲的
第二轮 beta 实验和当前待收集的第四轮 vNext 实验。公开题包不含方法标签；密钥文件不得复制给
评审者，也不得与题包放在同一个可共享目录中。

## 第四轮 vNext：已冻结，当前唯一可发的 SceneDNA 问卷

根目录：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_round4_20260828_v1
```

只把下面这个单文件发给评审者：

```text
SceneDNA_blind_review_2D_round4_offline.html
```

不要发送根目录、`sealed_blind_key_2d_round4.json`、`FREEZE_MANIFEST.json`、候选结果、自动分数或
联系表。页面为中文、完全离线，共 42 题：38 个独立 case 和 4 道隐藏重复题；vNext 在独立题左/右
各 19 次，重复题与原题至少间隔 23 位。拖鞋仍按单只资产评价。

本轮冻结前完成 100 个新 seed 批次，96 批成功、4 批真实硬拒绝；38 个双方都合格但选择不同的
case 进入公平配对问卷。76 张独立图片和双方各自的 38 张图均通过公开图严格卫生审计，固定为
`(224,224,224)` RGB 背景；与前两轮公开 case/图片哈希和历史候选 seed 均零重合。冻结清单中
`efficacy_claim_allowed_before_new_human_analysis=false`，所以问卷制作完成不等于效果已经提升。

请邀请 3–5 名没有参与本轮代码、阈值、候选生成或调试的新评审者。使用如 `round4_reviewer_01`
的匿名稳定编号，独立完成全部题目并下载 JSONL。收回文件后原样放入 `/data/wsj/main/test`，不要
手工编辑、合并或提前查看 sealed key。达到预注册人数后一次性统一解盲；此前禁止改页面、换图、
重排题目或追加类别特判。只有 2D semantic/form 门通过后才制作同 seed 配对 3D。

## 第三轮 vNext：冻结前卫生门失败，不发放问卷

第三轮根目录为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_vnext_round3_20260826_v2
```

100 个预注册独立批次已经全部完成，2 批真实语义拒绝、0 缺失；提取出 41 个干净的双方可比选择
差异，另有 22 个 vNext rescue 因缺少 current control 只报告覆盖率，不计算人工配对效应。但二次
色溢审计只有 138/140 张选中决策图通过，低于预注册 100% 门槛，其中一张失败图属于 changed pair。
`round3_extraction/extraction_report.json` 因此明确给出
`decision=do_not_build_round3_questionnaire`。

本轮没有 `SceneDNA_blind_review_2D_round3_offline.html`，也不得自行从 41 个干净对制作页面。禁止
就地修图、删掉失败 case、放宽门槛、复用 seed 或把未来答卷挂到本轮 sealed key。恢复与冻结审计
见 `RECOVERY_AUDIT_20260828.md`。下一份可发问卷只能来自修复卫生审计幂等性后、使用全新 seed
冻结的后续轮次。

## 第二轮 beta：已完成，不再继续收集

第二轮根目录：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_guard_blind_round2_20260824_v1
```

本轮曾只把下面这个中性命名的单文件网页发给评审者；现已达到三评审预注册最低人数，不再向新
评审者发放或追加答案：

```text
SceneDNA_blind_review_2D_beta_offline.html
```

不要发送根目录、`sealed_blind_key_2d_beta.json`、`FREEZE_MANIFEST.json`、候选结果或私有联系表。
页面包含 18 个独立 case 和 2 道隐藏重复题，共 20 题；实验方案在独立题中左右各出现 9 次，
重复题与原题至少间隔 4 位。建议由 3–5 名没有参与阈值设计或候选调试的新评审者独立完成，编号
使用 `beta_reviewer_01` 这一类不含姓名的稳定 ID。导出的 JSONL 原样收回到 `/data/wsj/main/test`。

本轮使用全新 seed 生成 60 批、240 张候选；47 批通过冻结硬门，13 批真实拒绝。只有当前综合
选择器与默认关闭的 `0.08` 形态改善门做出不同选择、且两张图均通过硬门的 18 个 case 进入问卷。
因此本轮测量的是“形态门实际改变决策时的人工偏好”，不是所有生成批次上的无条件平均收益。
问卷覆盖书堆、办公椅、台灯、植物、拖鞋和新增餐椅；休闲椅 6 批全部被现有形态门拒绝，收纳箱、
书架和落地灯没有产生选择差异，均作为泛化诊断保留但不伪造无意义 A/B 题。

冻结清单记录计划、公开题目、密钥和 HTML 哈希，并确认与首轮 case/image hash 零重合。问卷发出后
禁止重新排序、换图或调阈值；图片异常只能由评审者标记并在分析时排除。

三份完整答卷已于 2026-08-26 统一解盲，正式归档为：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_guard_review_3reviewers_20260826_v3_final
```

实验形态门的 semantic/form 偏好率为 `0.495370/0.453704`，主要指标 `0.474537`，没有通过预注册
门槛。形态门继续默认关闭；2D 必要门已经失败，因此本轮不再为晋级目的生成 3D non-regression。
类别差异只用于失败诊断，不允许据此添加类别特判。

后续图像卫生复核发现旧页面存在彩色背景边缘色溢：36 张独立候选中 18 张未通过新硬门，baseline
与 form guard 分别为 7 张和 11 张。该结果记录在
`scene_dna_beta_chroma_audit_20260826_v1`。因此 `0.474537` 降级为受混杂的诊断统计；它不能支持
启用 guard，也不能证明 guard 在干净图像上更差。禁止清理旧图片后复用旧答案。

新问卷必须满足：生成默认统一浅灰背景；RMBG 后通过隐藏 RGB/半透明边缘色溢清理；每张图片通过
`audit-images`；最终以 `(224,224,224)` RGB PNG 进入网页。任何一张失败都必须在冻结前重做，不能
依赖评审者事后发现。

## 评审者与样本

- 推荐 3–5 名没有参与本轮代码、阈值或候选调试的独立评审者。
- 每人使用稳定且不含姓名的 ID，例如 `reviewer_01`；不要使用默认 `anonymous`。
- 首轮 alpha-safe 30 题和第二轮 beta 20 题均已结束，仅保留归档；第四轮 42 题是当前唯一继续收集的 SceneDNA 问卷。
- 旧 v2 的 28 道 2D 与 8 道 3D 均已作废：2D 含误删主体的 alpha，3D GLB 也来自旧 alpha。
  第二轮 beta 的 3D non-regression 尚未生成，不得使用旧 3D 页面代替。
- 重复题只计算评审一致性，统计时归回原 case，不扩大独立样本量。

## 作答规则

- 在正常显示器、100% 浏览器缩放和稳定光照下完成；不要边看密钥、源文件名或自动分数边作答。
- 独立作答，评审期间不讨论；同一题分别判断 `semantic`、`form`、`style` 和 `overall`。
- `left/right` 表示一侧更好；两者同等合格用 `tie`；两者都明显不合格用 `neither`。
- 拖鞋题评估的是单只资产：按鞋子本身的语义、形态和风格评价，不因没有生成一双而扣分。
- 当前只完成新版 2D；每个题包尽量在一次会话中完成。

## 题包与密钥

实验根目录：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v3_alpha_safe
```

公开题包：

```text
blind_review_bundle_2d
```

仅分析者可见：

```text
sealed_blind_key_2d.json
```

服务启动后，答案追加到题包内的 `responses.jsonl`：

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.scene_dna_blind_review serve \
  --bundle-dir /data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_semantic_form_benchmark_20260823_v3_alpha_safe/blind_review_bundle_2d \
  --host 127.0.0.1 --port 8094
```

如需让同一局域网的其他机器访问，应在确认防火墙和访问范围后显式改用受控监听地址；不要把
密钥目录通过 Web 服务暴露。

### 无法访问服务器端口时的离线评审

评审者浏览器无法通过 SSH 转发访问服务器时，使用 `export-offline` 生成单文件 HTML。该文件
只内嵌公开题目和匿名图片，不内嵌 sealed key，也不会向服务器发送请求：

```bash
/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python \
  -m sage.experiments.codex_trellis_scene_v2.scene_dna_blind_review export-offline \
  --bundle-dir <public-bundle-dir> --output <offline.html> --label <bundle-label>
```

评审者把 HTML 下载到本机后直接双击打开。页面逐题把进度保存在浏览器 local storage；完成后
点击“下载最终结果 JSONL”。离线页面内的“清除本页进度”会删除当前浏览器中的该题包答案，
除非确实需要重做，否则不要使用。实验负责人收回 JSONL 后继续使用本文件既有的 `analyze`
入口。等新版 3D 配对完成后，2D 与 3D 仍必须分开提交、分开分析。

alpha-safe `20260823_v3_alpha_safe` 已生成：

```text
SceneDNA_blind_review_2D_alpha_safe_offline.html  # 30 题
```

当前页面采用中文题目说明、中文评分轴和中文按钮；导出的 JSONL 仍保留原有稳定字段，能够与此前的
英文页面结果合并分析。

## 冻结统计门槛

- 主要指标是 2D `semantic` 与 `form` 的 proposed 偏好；tie 按 0.5 计。
- 用独立 case 聚类 bootstrap；评审人数增加 rating 数，但独立 n 仍是 case 数。
- 只有主要偏好率至少 0.60、semantic/form 各自 case-clustered 95% CI 下界均大于 0.50，且
  3D/人工硬失败率不劣化时，才可讨论扩大 opt-in。
- 本次自动 3D 诊断为 1 个正向、3 个负向、3 个双分支硬失败，因此即使 2D 盲评较好，也不能
  直接替换默认资产选择链；需先解决 2D 选择到 3D 可生成性的落差。

## 三评审正式结果

三名独立评审者的 90 条答案已在不修改原始 JSONL 的前提下完成匿名归档。正式分析器从 v2 起只把
`tie` 计为 0.5；`neither` 表示两边均不可用，单独报告并从偏好率分母排除。结果为：

- semantic `0.508025`，case-clustered 95% CI `[0.379630, 0.638272]`；
- form `0.524691`，case-clustered 95% CI `[0.391975, 0.657407]`；
- semantic/form 主要指标 `0.516358`，`primary_gate_passed=false`；
- 主要维度隐藏重复一致率均为 `0.888889`；四维总体为 `0.805556`；
- 默认选择链替换仍禁止。

正式匿名归档、原始文件哈希、类别诊断、自动评分对人工判断以及 2D/3D join 位于：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/scene_dna_review_3reviewers_20260824_v5_final
```

`scene_dna_review_audit.py` 是可复现归档入口。类别结果仅用于归因：台灯、书架、办公椅偏正，植物、
拖鞋、收纳箱和部分书堆偏负。当前 SigLIP 语义差值与人工语义偏好相关系数为 `-0.605276`，形态
差值与人工形态偏好为 `0.342682`。由此提出的 `0.08` 形态改善门来自本轮开发标签，默认关闭；
任何本轮回放都不得表述成新收益，必须用新 seed、新候选批次和新评审者做下一轮隐藏验证。
