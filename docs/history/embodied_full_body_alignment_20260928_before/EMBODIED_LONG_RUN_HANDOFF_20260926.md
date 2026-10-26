# 具身数据长跑：当前交接与恢复入口

更新：2026-09-28。用户已批准独立6模型离线学习，本包训练、审计、报告及证据封存全部完成，固定学习门未通过。本页与AGENT顶部覆盖旧“待新训练范围批准”；更新前六份文档及哈希在[归档](history/embodied_mass_dynamics_approved_20260928_before/MANIFEST.json)。

## 当前成果与负结果

- MG固定56条件已完成：开发48/48、验证8/8成功，756000积分，0失败/未运行；原产量门通过。
- 151200状态/动作行、48完整腕部RGB-D的12960时刻/129600动作步已完成全量审计及官方读取；8×3验证稀疏观测隔离。
- 当前训练入口145成功开发/391500转移；其中92完整RGB-D/24840时刻/248400动作步。真实Torch全量及7类拒绝通过，旧97/44入口保持。
- 新MD离线学习：窄250g16源对多质量48源；同布局×几何、每模型2400窗口，种子7/17/27共6固定岭回归。六模型及索引在读取验证目标数组前冻结，8条MG验证仅评价。
- 配对宏误差比1.860885、1.967214、0.878913；中位1.860885超过≤0.90门，仅1/3对改善，三对平均0/8验证条件改善，五活动通道均恶化超过10%；所有预测有限。**固定学习门未通过，分支关闭，不重拟合或改门。**
- 独立审计重新加载保存权重，验证来源/隔离/等量分层采样及正规方程，复现全部72组结果，0新拟合。该负结果不证明多质量数据普遍有害，也未确定唯一根因。
- 无新任务策略成功、稳定量产或硬件资格；公开本体一步预测结果与采集质量分别报告。

## 阅读顺序与运行根

先读[AGENT顶部](../AGENT.md)，再读本页、[路线图](EMBODIED_DATA_ROADMAP_20260926.md)、[进展台账](EMBODIED_LONG_RUN_PROGRESS_20260926.md)、[结果详表](EMBODIED_CAPABILITY_RESULTS_20260926.md)和[训练说明](EMBODIED_TRAINING_DATA_20260927.md)。

`T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1`；`MD=T/capability_mass_dynamics_probe`。共享账本为同级G1运行时、RoboCasa控制和T三个根，旧费用不清零。

## 已批准授权与实际终态

|项目|实际状态|
|---|---|
|MD学习范围|已批准并完成；`MD/evidence/AUTHORIZATION.json`与`USER_APPROVAL.json`绑定原提案，不重问|
|MG计算|13500→19500已批准应用，56条件及数据交付完成，不重跑|
|磁盘|31GiB已批准；检查点剩余约4.11GiB，文档/账本有小幅变化|
|共享服务|461次、18215.343304/19500秒，余1284.656696秒；次数只统计|
|MD整包成本|4服务、106.421656/600秒，0新失败服务；6拟合模型、0物理/渲染/下载/GPU|
|MD空间|交付检查时共享新增3153920B，低于128MiB；含保存历史证据开销|
|MG历史成本|121服务4829.709496秒，加原静态142.079514秒，共4971.789009秒，保持|
|单项边界|8CPU、MemoryHigh12GiB/Max16GiB；单服务≤900秒、CPU子任务≤600秒；串行可终止|
|进程|无自有活动服务，主PID0、临时环境已清理；本轮所有PTY已结束|

精确资源读`T/evidence/LONG_RUN_CHECKPOINT.json`、`MD/evidence/CHECKPOINT.json`和原始`services/*/supervisor.json`。历史服务索引`T/evidence/SERVICE_LEDGER.json`已追加本轮，原476条各字段保持；元数据含出处，旧索引存`SERVICE_LEDGER_BEFORE_MASS_DYNAMICS.json`。共享额度不能与更早全部历史总费用混比，服务秒不包含全部开发/对话/人工时间。

## 当前恢复动作与后继准入

本批准包已完整结束，不能再运行`apply_mass_dynamics_scope.py`或固定训练worker；已冻结模型存在时入口会拒绝，不能删除凭据/模型绕过。文档中原prepared提案的“尚未批准”是冻结提案原文，以本轮有效授权凭据为准。

如只需恢复中断的文档工作，先读`MD/RESULT.json`、`evidence/AUDIT.json`、`evidence/DELIVERY.json`、`REPORT.md`及本轮服务终态，再更新文档/检查点。可用以下只做账本更新的入口；它不会训练、重采或改变模型：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_mass_dynamics_checkpoint.py
```

[下一独立任务检验前置](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/capability_mass_dynamics_probe/NEXT_TASK_ADMISSION.md)已准备，状态`not_admitted`：当前六模型仅预测速度增量，既无动作策略接口，也未通过本固定比较，不能直接转任务控制。原L/V/W关闭范围不重开。该说明只是缺口与准入要求，**不是ready整包、不含新训练/物理授权，不请求笼统“批准继续”**。

下一轮应先把部署可用观测下的新控制/数据分布方案做成可审查结果：明确因果动作接口、开发范围准入、独立新条件与完整资源预算，再作重要路线决定。优先新接触几何、支撑面和有效任务空间；不把背景扩充或一步分数代替数据任务价值。普通接口、分析与文档问题自主修复。当前收束原因是事前质量门失败及无已准入任务后继，不是半小时、服务数或资源耗尽。

## 关键交付与完整性

|用途|相对T路径|
|---|---|
|固定学习结果/条件级误差|`capability_mass_dynamics_probe/RESULT.json`、`REPORT.md`|
|六冻结权重/2400行索引|`capability_mass_dynamics_probe/models`、`evidence/MODELS_FROZEN.json`|
|独立审计|`capability_mass_dynamics_probe/evidence/AUDIT.json`，72组全部复现|
|误差图|`capability_mass_dynamics_probe/COMPARISON.png/.svg`|
|新完整性闭包|`capability_mass_dynamics_probe/BINDING.json`、`evidence/DELIVERY.json`|
|完整训练入口|`capability_mass_geometry/training_bundle/TRAINING_CATALOG.json`，145/92|
|MG原终态|`capability_mass_geometry/RESULT.json`、`evidence/SUCCESSOR_QUEUE.json`|
|MG历史审计|`evidence/MASS_GEOMETRY_SAVED_AUDIT.json`、`MASS_GEOMETRY_RGBD_NATIVE_READER.json`、`MASS_GEOMETRY_INTEGRITY.json`|

旧7389绑定逐项核验完全不变，包括全部已绑定原失败/数据/工具；原148模型、9旧B、31严格适配另行核验。旧`T/capability/BINDING.json`字节保持，MD单独绑定32新文件，SHA-256 `36cdc116abc1969de58e98211f68e1423f3e5e05a290017e251e1c6b2ebc3bd8`。旧绑定快照`T/evidence/CAPABILITY_BINDING_BEFORE_MASS_DYNAMICS.json`。新交付证明`T/evidence/MASS_DYNAMICS_INTEGRITY.json`。

U/P/MG三个训练入口哈希保持；MG统一目录为`87a18a44ff5aab748e36b99ee20a3273f6b94d037e5627e5f20d82c6926f53f0`。模型、复制、压缩或观测重建均不增加开发轨迹，验证和失败继续隔离。

## 长期边界

原B恢复已完成；D最小g1八失败和原整批产量门失败、W累计3物理无效/18未运行、低桌、L、旧V、A/G1关闭结论保持。MG采集通过与MD学习失败都不覆盖这些原结论。

有限有效出力/轮摩擦仍为仿真假设，外部gravcomp及外加力0，内部有限前馈保留；理想配准/FK/底盘反馈假设、严格SG3来源缺口及无硬件/稳定量产资格保持。所有Python继续`-I -B`，保留工作树既有改动，不运行git reset/clean、不擅自提交。
