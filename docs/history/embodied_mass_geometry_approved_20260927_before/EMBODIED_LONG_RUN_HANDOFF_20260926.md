# 具身数据长跑：当前交接与恢复入口

更新：2026-09-27，按用户“整理当前的各项进展到相应的计划文档中，我准备换对话续任务了”整理。**本页是当前执行断点**；本次仅更新文档，没有申请或执行新实验、没有应用下一批计算扩容。历史过程见[整理前原文](history/embodied_session_handoff_20260927_before/EMBODIED_LONG_RUN_HANDOFF_20260926.md)，其中旧“运行中”“待批准”和PTY编号均不能当作当前状态。

## 先看结论

项目目标仍是自有场景生成器支撑大批量高质量具身训练数据。已有条件化仿真研究数据与真实读取链路，尚未取得稳定量产或真机资格。原始B策略历史恢复及14通道非零手动作准入已完成，不再作为下一步。

- 已交付97条成功开发轨迹、261900条100Hz转移；其中44条完整27秒腕部RGB-D，11880个10Hz时刻、118800步对齐动作。44是97的子集。
- 几何D：48条件全部执行，开发32/40、验证8/8；最小g1盒8次失败保留，原整批产量门失败。成功范围g2–g5的独立专家复验F为24/24，各格3/3，通过该有限重复性门。
- 等量感知E：窄组3/24、多尺寸22/24初态过门（3模型×8条件）。实际视觉初始化任务W触发累计3次物理无效并关闭，18次未运行；不能将定位收益写成视觉任务可靠性。
- 无损P：32序列2248430526→727202757B，全部值/类型/形状/属性相同，原件保留；官方8640行及44源统一入口132读取点核验通过。副本不增加样本数。
- 下一尺寸×质量MG批：48开发+8验证，56实际初态静态预检全部通过，动态0次、积分0步。队列、审计、导出和158输入绑定已准备；动态结果仍unknown。
- 磁盘21→31GiB已获用户明确授权并执行；累计计算仍为13500服务秒。**下一包13500→19500服务秒（+6000）提案尚待明确批准。** 不把磁盘批准或本次整理文档当作计算批准。
- 最新检查点无自有活动服务，全部主PID0、临时环境文件清理；没有后台采集等待接管。

## 阅读顺序与文档分工

1. [AGENT.md顶部](../AGENT.md)：最高目标、长期执行规则、本次断点。
2. 本页：授权、资源、脚本、恢复条件及关键证据。
3. [路线图](EMBODIED_DATA_ROADMAP_20260926.md)：M1–M6实际完成度及结果驱动的后继。
4. [进展台账](EMBODIED_LONG_RUN_PROGRESS_20260926.md)：各阶段结果、失败、产物和关闭范围。
5. [结果详表](EMBODIED_CAPABILITY_RESULTS_20260926.md)、[训练入口](EMBODIED_TRAINING_DATA_20260927.md)：结论边界、数据划分及实际读取示例。

## 运行根与当前资源

工作目录：`/data/wsj/main/scene`。下文`T`指：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1
```

共享资源还覆盖同级`embodied_g1_runtime_20260926_v1`、`embodied_robocasa_control_20260926_v1`。以`T/protocol/PROTOCOL.json`及各共享根`services/*/supervisor.json`为准，不重置旧成本。

|资源/授权|当前状态|新对话注意事项|
|---|---|---|
|累计计算|已用13279.212152/13500服务秒，余220.787848秒|这是共享三个运行根的项目账本；不等于全部开发/推理工时，也不表示CPU硬件耗尽|
|项目磁盘|上限31GiB；检查点占用23472074752B，余9813921792B，约9.14GiB|用户增加约10G已执行，勿重问；字节数是检查点快照，后续文档/日志可有微小增加|
|CPU/内存|8 CPU；MemoryHigh 12GiB、MemoryMax 16GiB|单服务≤900秒、CPU子任务≤600秒，串行可终止|
|GPU/下载|本后继无GPU、0新下载；累计下载上限8GiB|完整历史下载账读检查点，不重复安装/下载现有环境|
|服务/工程修订次数|共享服务336次，仅统计|服务次数、普通修订次数、短包数量均不是审批或停止门|
|下一包计算|申请13500→19500，尚未应用|`T/capability_mass_geometry/evidence/AUTHORIZATION.json`不存在；本次文档整理不改变这一事实|

资源快照：[LONG_RUN_CHECKPOINT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/evidence/LONG_RUN_CHECKPOINT.json)。其中`shared_service_seconds`才与13500预算比较；`total_service_seconds`另含更早运行根，不能混用。顶层历史`qualified_task_episodes=0`/`learning_effect=unknown`属于严格原生路线旧口径，当前条件化结果读`conditional_phases`和各阶段RESULT，不能据此把97条研究数据写成0，也不能反向升级严格硬件资格。

磁盘授权凭据：[DISK_AUTHORIZATION.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/capability_lossless_storage/evidence/DISK_AUTHORIZATION.json)。旧+2GiB草案、旧协议、旧绑定已在T内归档，不能覆盖新+10GiB授权。

## 下一步：尺寸×质量整包

冻结方案：[MASS_GEOMETRY_COMPUTE_EXTENSION.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/prepared/MASS_GEOMETRY_COMPUTE_EXTENSION.md)及同名JSON。

|项目|冻结范围|
|---|---|
|开发48条件|SD01/SD02两布局×g2–g5四几何×100/250/400g三质量×两新初态；两条250g g3基线包含其中|
|验证8条件|两布局×v1/v2两验证几何×175/325g两未见质量；与D/W/F等旧初态种子无重叠|
|物理/数据上限|56次、756000积分步；最多48条成功开发完整腕部RGB-D，12960时刻/129600动作步；验证最多8×3稀疏观测，禁止训练|
|新增资源|最多6000服务秒、6GiB新文件；共享上限拟19500秒/31GiB；0下载、无GPU|
|物理退出|布局基线失败关闭布局；配置首次物理无效关闭该布局/几何/质量配置；累计3物理无效或连续5任务失败关闭整批|
|产量门|开发≥43/48且验证≥7/8；失败和未运行保留在固定分母中|
|其他门|原接触15N、放置15mm等不放宽；不训练新模型、不重开旧W/V评测调参|

静态准备已经花费约142.080服务秒，计入原13500额度；56静态通过只代表可以测试，不是56个成功任务。具体证据为`T/capability_mass_geometry/evidence/PREFLIGHT.json`、`PREPARED_QUEUE_CHECK.json`、`COUNTERS.json`。158提案输入哈希在本次整理前复核一致；未批准动态启动的真实负例在创建服务前拒绝。

### 新对话先做只读核对

检查`T/protocol/PROTOCOL.json`、MG授权凭据、计数、`RESULT.json`（当前不存在）、`evidence/QUEUE.json`和`DISPOSITIONS.json`（运行后产生）、相关`services/mass_geometry_*`日志及活动服务。不要沿历史PTY33554/91390等进程号恢复；它们已结束。不要重跑已完成D/E/W/F/P，也不要重做56初态预检来制造新进度。

如果仍没有新的明确计算授权，保留准备结果，说明待决定的就是上述完整+6000秒方案；不要把剩余220.8秒切成物理小包绕过整包准入。普通只读检查和文档修复不需再申请许可。

### 获得明确计算批准后执行

以下命令**仅适用于已取得这份计算提案的明确批准**。先确认凭据不存在、旧额度仍13500、158绑定和预检通过；已有有效授权凭据时跳过第一条，不能重复应用。若旧协议已变化而凭据缺失，先查明，不强写覆盖。

```bash
cd /data/wsj/main/scene
run_root=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1
/data/wsj/anaconda3/envs/simgen/bin/python -I -B "$run_root/prepared/apply_mass_geometry_compute_extension.py"
/data/wsj/anaconda3/envs/simgen/bin/python -I -B "$run_root/tools/run_capability_mass_geometry_queue.py"
```

队列经受限launcher依次执行实际任务、保存轨迹审计、官方有状态导出、成功开发全长腕部RGB-D、官方读取全量审计、独立验证稀疏观测和汇总。主解释器用`simgen`，真实任务环境由既有launcher选择；不要手工替换共享环境或直接裸跑worker。

恢复前先核对已消耗条件。队列会跳过完整结果并从原记录重建累计退出；普通软件错误自主定位修复并计费。若目录只留下不完整物理尝试，先审计该尝试，不能删目录或换服务名把同一物理条件再跑一遍。服务新名字只记工程修订，不重置动态/成本/失败计数。

批次终结后自主衔接：审计所有已运行结果，保留失败与未运行，按固定分母报告产量；只把审计通过的成功开发来源接入新的开发目录，旧97/44入口保留，验证与副本不混入。再按[路线图](EMBODIED_DATA_ROADMAP_20260926.md)整理覆盖/成本与后继学习设计。依赖、授权和资源足够的普通后继连续完成；新的重大路线或资源决定集中提出，不在每个短包结束时等待“继续”。

## 交付与证据索引

|用途|相对T路径|
|---|---|
|原始统一开发入口U|`capability_training_bundle/TRAINING_CATALOG.json`、`RESULT.json`|
|已验证无损替代入口P|`capability_lossless_storage/UNIFIED_TRAINING_CATALOG.json`、`RESULT.json`、`evidence/UNIFIED_CATALOG_VERIFIED.json`|
|几何D完整结果及开发来源|`capability_geometry_collection/RESULT.json`、`TRAINING_CATALOG.json`|
|感知E冻结模型/结果|`capability_geometry_perception/evidence/MODELS_FROZEN.json`、`RESULT.json`|
|视觉W失败诊断|`capability_geometry_visual_task/RESULT.json`、`evidence/FAILURE_DIAGNOSIS.json`|
|重复性F结果/原生审计|`capability_geometry_confirmation/RESULT.json`、`evidence/CONFIRMATION_AUDIT.json`|
|MG固定任务与零动态计数|`capability_mass_geometry/protocol/PROTOCOL.json`、`evidence/COUNTERS.json`|
|能力范围查询|`tools/query_capability.py`及各阶段`evidence/CAPABILITY_RECORDS.json`|
|完整性|`evidence/CAPABILITY_INTEGRITY_AFTER_STORAGE.json`、`capability/BINDING.json`|

完整性收尾已核验原148模型、9旧B、31严格适配文件；6107文件绑定、9已运行动态阶段及MG零动态账本一致。本次文档整理不改实验脚本、模型、数据、冻结协议或预算。绑定SHA-256为`4df6cef4c0942eb1cb42373b19490b6c6415e42c155b5f2dd2b5b0bed07abfaa`；无损统一目录SHA-256为`0de1f51543c29898058d28d932d21f45d31bd70ba7fc578edffb66120e62f8ff`。

## 不应遗失的范围和失败

所有成功仅在明确假设的有限有效出力/轮摩擦下成立。body gravcomp与外加力为0，内部有限执行器重力前馈保留。严格SG3努力/传动来源缺口仍在；理想相机配准/FK与底盘位姿反馈不代表真实传感/硬件能力。

SD01/SD02复用原5资产与任务桌面，主要变化窗墙/背景；g2–g5尺寸一起变动，不是新语义房型、多物体身份或单轴因果实验。原A/G1关闭配置、低桌Pold、直接学习L、旧视觉V、最小g1和W保持关闭。尤其W的1cm定位门未保证任务通过，事后横移预警在前瞻W中有误报/漏报，不能升级为可靠准入规则。

Python统一`-I -B`，避免在旧源目录写pyc。保留原始失败、训练/验证隔离和未跟踪文件；不运行git reset/clean，不擅自提交或把其他实验改动混入。本轮归档及各文档哈希见[归档清单](history/embodied_session_handoff_20260927_before/MANIFEST.json)。

## 可复制到新对话

```text
工作目录：/data/wsj/main/scene。
先读AGENT.md顶部及docs/EMBODIED_LONG_RUN_HANDOFF_20260926.md，按其中当前断点接续。
原B、D/E/W/F及无损交付均已闭合，不要重复运行。下一步是尺寸×质量56条件批次，当前仅静态通过。
磁盘31GiB已授权生效；13500→19500服务秒的计算提案尚待明确批准，先核对最新授权凭据与账本，不能把旧批准当作本次批准。
获得该计算授权后按固定入口连续推进，保留单项预算、质量门、累计退出及历史费用；普通修复和已明确后继自主完成，不按半小时或短实验结束停止。
```
