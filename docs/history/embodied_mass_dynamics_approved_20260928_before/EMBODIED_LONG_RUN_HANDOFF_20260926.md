# 具身数据长跑：当前交接与恢复入口

更新：2026-09-27，MG整包采集、审计、导出与目录整合已结束。本页与AGENT顶部覆盖历史“待MG批准/执行中”；完整批准前文档及哈希在[归档](history/embodied_mass_geometry_approved_20260927_before/MANIFEST.json)。

## 当前成果

- MG固定56条件：开发48/48、验证8/8成功，756000积分，失败0、未运行0；原开发≥43/48且验证≥7/8门通过。
- 全部151200状态/动作行审计与官方读取通过，最大力重建误差2.842170943040401e-14。
- 48成功开发完整腕部RGB-D：12960时刻、129600动作步、3383691080B HDF5；官方无损RGB/动作及精确深度/掩码全量连接读取通过。
- 8验证各3稀疏时刻单独保存，全部评价专用。观测总计38952渲染调用、12984保存状态前向、672射线查询，0新积分，原上限保持。
- 新统一开发入口145条、391500转移；其中92完整RGB-D、24840腕部时刻、248400对齐动作步。92是145的子集。原97/44入口和无损P32原件/副本均保留。
- 真实Torch24840行跨episode逐值/逐类型、7类拒绝、旧入口哈希均通过。
- 尚无MG学习结果、稳定量产或硬件资格；不能从任务成功率或条数直接升级资格。

## 阅读顺序与运行根

先读[AGENT顶部](../AGENT.md)，再读本页、[路线图](EMBODIED_DATA_ROADMAP_20260926.md)、[进展台账](EMBODIED_LONG_RUN_PROGRESS_20260926.md)、[结果详表](EMBODIED_CAPABILITY_RESULTS_20260926.md)和[训练说明](EMBODIED_TRAINING_DATA_20260927.md)。

`T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1`；工作目录`/data/wsj/main/scene`。共享账本包含同级G1运行时、RoboCasa控制和T三个根，旧费用不清零。

## 已批准资源与实际终态

|项目|实际状态|
|---|---|
|MG计算批准|13500→19500已应用，`capability_mass_geometry/evidence/AUTHORIZATION.json`存在；本包完成，不重问|
|磁盘|31GiB已批准生效；检查点占用28869365760B，余4416630784B约4.11GiB；文档/日志可有小幅变化|
|共享服务|457次，仅统计；18108.921648/19500秒，余1391.078352秒|
|MG成本|121服务、4829.709496秒，0新失败服务；旧静态准备142.079514秒另保留，合计4971.789009秒，约103.579秒/成功完整开发RGB-D|
|MG文件|4598546432B约4.28GiB，低于6GiB阶段上限|
|单项边界|8CPU，MemoryHigh12GiB/Max16GiB；单服务≤900秒、CPU子任务≤600秒；串行、可终止|
|下载/GPU|本包0下载/无GPU；历史下载6434499284B载荷及保留量不变|
|进程状态|所有自有主PID0，无活动服务，临时环境已清理；旧PTY46450/56665均结束|

精确账本为`T/evidence/LONG_RUN_CHECKPOINT.json`和共享根`services/*/supervisor.json`。 `T/evidence/SERVICE_LEDGER.json`已从原始记录重建为476条全历史索引，其中457条属于当前共享预算；原83条索引已归档且各字段完全一致，详情`SERVICE_LEDGER_METADATA.json`。服务秒不含全部开发、对话、推理或人工时间；不把总历史字段`total_service_seconds`与共享额度混比。顶层旧严格路线0合格/learning unknown不代表当前条件化研究开发数据为0。

## 当前待决定：独立离线学习范围

[整包提案](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/prepared/MASS_DYNAMICS_LEARNING_PROPOSAL.md)及同名JSON、[设计](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/prepared/MASS_DYNAMICS_LEARNING_DESIGN.md)已准备，123实际数据/代码输入哈希一致，完整预算可容纳。**只缺新的模型训练范围批准；不申请提高19500秒或31GiB，不重问已完成的MG批准。** 原MG方案明确“本包不拟合新的学习模型”，本次MG批准不覆盖这一新对照。

固定窄250g的16开发源对多质量48开发源，均覆盖两布局×四几何；相同60维公开本体状态/动作/历史速度输入，固定lambda1岭回归，三对采样种子，每模型2400窗口。目标是下一10ms速度增量，8条MG验证仅评价；六模型/训练索引在读取验证目标数组前冻结。通过门、固定分母与不调参规则见设计。它只检验离线预测收益，不检验动作策略或完整任务可靠性。

上限600新增服务秒、128MiB，0新物理/渲染/下载、无GPU；当前余1391.078秒/约4.11GiB。现有模型数0，`T/capability_mass_dynamics_probe/evidence/AUTHORIZATION.json`不存在；未授权入口真实拒绝在拟合之前，没有新阶段目录。不要擅自启动或把当前余量切成小训练试验绕过整包决定。

### 获得该新范围的明确批准后

先核对提案123输入、现行协议、共享服务账本和新范围凭据。已有有效凭据时跳过apply；若存在半成品阶段，先审计恢复，不能覆盖或重新拟合已消费模型。

```bash
cd /data/wsj/main/scene
run_root=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1
/data/wsj/anaconda3/envs/simgen/bin/python -I -B "$run_root/prepared/apply_mass_dynamics_scope.py"
/data/wsj/anaconda3/envs/simgen/bin/python -I -B "$run_root/tools/launch_mass_dynamics_probe.py" mass_dynamics_fixed_comparison "$run_root/tools/run_cpu_probe.py" MASS_DYNAMICS_FIXED_COMPARISON run_mass_dynamics_probe.py
```

apply只登记新范围并复制已绑定工具，不修改共享额度；会再次核验完整600秒/128MiB余量。运行后保留失败与费用，冻结后不重拟合、不在旧评测调参，更新学习结论与路线。普通工程修复自主完成，不因服务次数或短包结束等待“继续”。新的重大路线/资源决定集中提出。

## 已完成MG的恢复与证据

正常情况不重跑。若用户中断的是文档整理，先核对以下终态，直接接文档即可：

|用途|相对T路径|
|---|---|
|MG固定物理结果/终态队列|`capability_mass_geometry/RESULT.json`、`evidence/QUEUE.json`、`evidence/DISPOSITIONS.json`|
|已完成后继|`capability_mass_geometry/evidence/SUCCESSOR_QUEUE.json`|
|新统一训练入口|`capability_mass_geometry/training_bundle/TRAINING_CATALOG.json`、`RESULT.json`|
|MG开发原生选择|`capability_mass_geometry/TRAINING_CATALOG.json`；原生全目录含8评价，按开发索引选择|
|覆盖与图|`capability_mass_geometry/CAPABILITY_BY_MASS_GEOMETRY.json`、`PLACEMENT_BY_MASS_GEOMETRY.png/.svg`|
|审计|`evidence/MASS_GEOMETRY_SAVED_AUDIT.json`、`MASS_GEOMETRY_NATIVE_PROPRIO.json`、`MASS_GEOMETRY_RGBD_NATIVE_READER.json`|
|完整性|`evidence/MASS_GEOMETRY_INTEGRITY.json`、`capability/BINDING.json`|
|原绑定归档|`evidence/CAPABILITY_BINDING_BEFORE_MASS_GEOMETRY_EXECUTION.json`|
|新学习准备证明|`evidence/MASS_GEOMETRY_LEARNING_DESIGN.json`|

新目录SHA-256：`87a18a44ff5aab748e36b99ee20a3273f6b94d037e5627e5f20d82c6926f53f0`。新绑定7389文件，SHA-256：`e9a06f440d74984013a54e0dab516949e40f4539cd9b994d094479d612ee1cf6`。逐项核验旧6107绑定：6105完全不变，只有获批全局预算元数据与MG累计计数改变；原148模型、9旧B、31严格适配文件均保留。实时后继队列封套和检查点明确不纳入静态绑定，原始物理、数据和失败证据均纳入。

原U为`capability_training_bundle/TRAINING_CATALOG.json`，原P为`capability_lossless_storage/UNIFIED_TRAINING_CATALOG.json`，97/44入口均保留。MG观测新来源48条，复制、压缩和目录变体不增加样本。

## 长期边界

原B恢复已完成；D最小g1的8失败及原整批产量门失败、W累计3物理无效退出/18未运行、低桌Pold、L、旧V和原A/G1关闭范围全部保持。MG通过不覆盖这些失败，也不证明新房型/物体身份或95%可靠率。

场景仍复用原资产和任务桌面；有限有效出力/轮摩擦为仿真假设，外部gravcomp和外加力为0，内部有限前馈保留。相机配准/FK与底盘反馈理想化，严格SG3硬件来源缺口不变。下一步按路线图推进有效分布与数据价值，不要求每个场景先单独训练策略。

所有Python继续`-I -B`；保留旧证据、开发/验证隔离和工作树既有改动，不运行git reset/clean、不擅自提交。
