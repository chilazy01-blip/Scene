# 具身数据长跑：当前交接与恢复入口

## 当前断点：全路径专家的固定开发矩阵未准入

本轮接续FB2后继，没有重跑FB0/FB1或旧关闭物理配置。新增碰撞约束双臂参考、绕障站位、观测残差反馈与全矩阵拒绝接口；名义59秒/2950tick/15阶段通过。参考版11条件4通过，反馈原矩阵5通过，1项纯数值边界修复复核通过，仍5项末端目标未达标。固定姿态正则诊断0/2，不调系数补数；不能宣布本体物理不可达。详见[本轮结果](EMBODIED_FULL_BODY_COLLISION_EXPERT_20260928.md)。

73750静态保存配置的几何与末端误差独立审计通过，误差最大7.77634e-16m；原FB2失败回归及6类矩阵拒绝通过，历史356绑定逐项不变。0新物理/策略推理/渲染/训练/下载，完整full-body任务仍0，单臂145/92保持。已关闭固定矩阵保存为回归；下一项是基座/身体与末端联合可行性、基于实际状态的阶段协调器，前置在`T/full_body_collision_expert/prepared/NEXT_TASK_ADMISSION.md`，没有ready物理包。

本包24服务/753.456018秒；共享505服务、19369.062063/19500秒，余130.937937秒，盘余约4.111GiB。历史500条服务行不变，无活动服务、主PID0、环境清理。下一完整静态复验实测估算260–320秒，当前余额不足；不能只检成功子集。先做具体新候选/冻结包再提出必要增量，本轮未申请或应用扩容、不重新问方向。精确入口`T/full_body_collision_expert/CHECKPOINT.json`及`T/evidence/LONG_RUN_CHECKPOINT.json`；新账本脚本`tools/refresh_collision_checkpoint.py`。本轮前五文档[已归档](history/embodied_collision_expert_20260928_before/MANIFEST.json)。

运行根`T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1`；`C=T/full_body_collision_expert`。恢复先读C的RESULT/CHECKPOINT、四份审计、NEXT_TASK_ADMISSION，再核对原始services/fbc_*。旧F的FB1与FB2结果保留，不以本轮静态结果替代。没有后台任务需要接管。

仅刷新当前账本（不积分/推理/训练）：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_collision_checkpoint.py
```

以下为上一断点历史；其中旧余额、下一项和旧刷新命令不代表当前状态。


**2026-09-28最新实测：FB0定型完成，FB1全身控制与独立保存审计通过；FB2第一固定完整任务按接触门失败关闭。** full-body方向保持，不回单臂扩量、不重复已完成B/FB0/FB1。先看[本轮详细结果](EMBODIED_FULL_BODY_FB0_20260928.md)、[三阶段目标](EMBODIED_FULL_BODY_GOALS_20260928.md)、[路线图](EMBODIED_DATA_ROADMAP_20260926.md)。

## 实际断点与下一项

- 本体/控制器：G1 29身体+14 Dex3手，固定Decoupled WBC Balance/Walk、官方GroundOnly，复用CPU隔离运行时。43通道映射与混合单位、50Hz高层/策略及500Hz原生命令已固定，350文件绑定。详见`T/full_body_bootstrap/REPORT.md`。
- FB1：20秒10000步，降高0.112307m、前进1.010276m、双臂/14手实际动作及稳定停止通过。1000策略输入、10000实际命令和接触力保存重建误差0，恢复状态与历史一致。它是组成能力资格，不是成功任务episode。
- FB2：250g刚性箱双手取起/携带/放置固定尝试，在7.966s/3983步左手中指触源支撑面（18.014538N/0.110111mm）关闭；未到取物/携带阶段。399输入/3983步独立重建，首个真实失败确定。禁止碰桌由角色门判定，不是单臂15N门。剩13017步不补跑。
- 原67静态姿态只覆盖抓握/升降/释放局部，漏掉完整走近和降高阶段。新增全tick覆盖拒绝及保存失败回归。下一项为**FB2全路径碰撞感知任务专家的静态准入**，要求实际基座/身体跟踪误差包络与所有阶段/过渡。`prepared/NEXT_TASK_ADMISSION.md`是明确前置，不是ready新动态包；关闭配置不能仅改时序/摆桌后重跑。
- 完整full-body合格任务0，FB3自生成场景/独立初态未准入；目标不降低，旧145/92单臂数据仅作工程底座。

## 恢复入口与资源

`T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1`；`F=T/full_body_bootstrap`。

先核对`F/RESULT.json`、`CHECKPOINT.json`、`evidence/FB1_AUDIT.json`、`evidence/FB2_AUDIT.json`、`full_task/FAILURE_DIAGNOSIS.json`、`prepared/NEXT_TASK_ADMISSION.md`及T的原始`services/fb*`。不能根据旧prepared文件或服务exit0推断科学通过。旧原生PnPBottleTableToTable/B与本次GroundOnly/箱体任务分别记账。

本轮20服务400.262740秒：FB0 226.213461秒，FB1 155.347785秒，FB2 18.701494秒，全部失败与被终止审计成本保留。共享481服务、18615.606045/19500服务秒，余884.393955秒；31GiB下余约4.14GiB；下载6434499284B不变，无GPU。8CPU/内存12与16GiB/单服务≤900秒保持。无自有活动服务、所有主PID0与临时环境清理。

只刷新账本时可运行（不会积分/推理/训练）：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_full_body_checkpoint.py
```

不要重新运行已完成的FB1或已关闭的FB2物理worker；服务目录/冻结/原始结果是消耗凭据。普通源码/接口/静态规划继续按已有授权处理，不人为增加修订次数审批。资源未耗尽，未提出重复31GiB/19500秒申请；新控制或任务实验范围先准备具体准入与累计退出。

## 历史保护与统计口径

原7389 capability绑定、32 MD绑定及9旧B输入全部未变。旧480历史服务行逐项保持，共享服务只是其中R/N/T三个根；原累计费用不能按阶段改名清零。新增2次动态13983步、6静态/1399动态推理均单独记入full_body；0渲染/训练/下载。旧单臂145成功开发/391500转移、92完整RGB-D仍保持；本轮全身控制/失败轨迹不混入成功任务训练目录。

更新前五计划与哈希在[归档](history/embodied_fb0_20260928_before/MANIFEST.json)。原最高目标、科学门、来源隔离与关闭分支保持；以下为MD/单臂历史快照，资源余额与旧“下一项”不代表当前队列。

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

## 已完成MD的历史恢复与原后继说明

本批准包已完整结束，不能再运行`apply_mass_dynamics_scope.py`或固定训练worker；已冻结模型存在时入口会拒绝，不能删除凭据/模型绕过。文档中原prepared提案的“尚未批准”是冻结提案原文，以本轮有效授权凭据为准。

如只需恢复中断的文档工作，先读`MD/RESULT.json`、`evidence/AUDIT.json`、`evidence/DELIVERY.json`、`REPORT.md`及本轮服务终态，再更新文档/检查点。可用以下只做账本更新的入口；它不会训练、重采或改变模型：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_mass_dynamics_checkpoint.py
```

[下一独立任务检验前置](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/capability_mass_dynamics_probe/NEXT_TASK_ADMISSION.md)已准备，状态`not_admitted`：当前六模型仅预测速度增量，既无动作策略接口，也未通过本固定比较，不能直接转任务控制。原L/V/W关闭范围不重开。该说明只是缺口与准入要求，**不是ready整包、不含新训练/物理授权，不请求笼统“批准继续”**。

上述NEXT_TASK_ADMISSION是MD结束时的前置说明，原件保留为历史；当前后继已由用户批准的新full-body路线接管，以本页FB0–FB3为准。MD按原质量门失败关闭，不能重训或转成任务策略；该科学负结果不阻止全身主线的独立选型与准备。

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
