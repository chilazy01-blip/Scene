# 具身数据长跑：当前交接与恢复入口

## 2026-10-07 19:40：以FB2验收为持续目标，四小时为汇报间隔（最新 HANDOFF）

### 2026-10-07 23:35更新：近四小时汇报断点与完整性核验

**2026-10-07 23:46当前执行状态：blocked（待第五候选范围批准），FB2未完成。** 连续3轮核实同一依赖：已批准最多4候选全部失败关闭，第五候选方案/代码已准备但未收到对应范围回复；物理准入仍为false。可独立完成的数据准备与预检已完成，剩余实际采集/数据审计/导出/读取验证需要先取得合格完整物理轨迹。`O/SCOPE_BLOCKER_AUDIT_R3.json`通过后，目标工具已返回blocked；未缩小目标或标记成功。实际服务0，最后驱动PID/启动标识已退出；原预算、提案与封存不变。明确批准第五候选后从`passive_damping_r1`接续，并重新核对资源门、PID与服务终态。

**2026-10-07 23:44接续补充：** 独立数据审计代码`embodied_fb2_data_v1/independent_audit.py`已准备；新增`audit_fb2_success_data_r1.py`，以及强制先通过该审计的`export_fb2_success_lerobot_r2.py`。`P/fb2_delivery_preparation_r1/INDEPENDENT_AUDIT_PREFLIGHT_R1.json`复核四个失败源全部拒绝、两个固定状态相机接口可用，物理/策略/渲染新增均0。完整成功源的数据审计分支尚未执行，仍不能计作FB2通过。准备计划为`PLAN_R2.json`。第80个服务耗时3.054875秒，最新共同21170.795928/24000、全局44870.480819/48000秒；所有动作计数保持。第五候选范围批准仍未收到，后台服务0。

本轮四个真实候选均失败并独立复核，**FB2仍未通过，合格任务/数据episode均0**。最新运动证据确认命令几何安全不代表实际动态安全；右中指碰桌前主要受手臂向下速度影响。第五方案逐5ms限幅手臂阻尼的准备/预检已完成，物理效果未验证；原“至多4候选”范围已用完，`O/PENDING_CANDIDATE_SCOPE_DECISION_R1.json`仍待明确回复。提案不增加任何资源，只使用原剩余1组件试次；不得把此前静态推理增额回复当成第五候选批准。当前真实活动服务0，驱动原启动标识全部退出；目标仍未完成。

`O/REPORT_CHECKPOINT_VERIFICATION_R2.json`复核7417个冻结文件、70份递归清单与79个驱动身份通过；R1清单格式兼容失败记录保留。`sage/experiments/embodied_fb2_data_v1`准备25Hz双相机RGB-D、50Hz全身命令块、5ms传感器时差、LeRobot导出和真实读取入口。`P/fb2_delivery_preparation_r1/CODE_PREFLIGHT_R2.json`仅证明导入/结构/四个失败源拒绝门通过，**实际采集、独立数据审计、导出、训练读取均未验证**；没有新渲染和合格样本。

最新共同服务21167.741053/24000、全局44867.425945/48000秒；本轮79服务2499.414216秒。静态91431/92000，动态1900计费/1748已知实际，物理13290计费/12960已知实际，组件7/8、完整0/1。共同磁盘14789423104/18GiB、全局44471275520/47GiB、下载6723717619/8GiB，历史费用全部保留。台账入口仍为`N/tools/refresh_fb2_goal_ledger_r3.py`。恢复指针与SCIENTIST_STATE已同步到第五候选待范围决定，O/STATE保留最后作业真实终态；阶段报告`O/FOUR_HOUR_REPORT_R1.json`。四小时是汇报间隔，当前等待由已批准候选范围产生，不由时长产生。

用户最新要求：“那就继续推进吧。以完成FB2为目标。约4小时为单次汇报界限，在未完成前不断地进行尝试。”已建立持续目标；**四小时是汇报间隔，不是终止或再次审批点**。本次首个汇报点约 2026-10-07 23:40:52 +0800。旧18:05:16窗口属于历史；此授权更新执行时间方式，不增加累计资源或放宽科学退出。

**阶段边界纠正：FB2是至少一条完整全身物体交互任务、同步公开观察/全身命令、独立审计、标准导出与真实训练读取；自生成场景扩展和冻结小批复验属于FB3。** 不能把自有场景扩展混入FB2而不断抬高验收范围，也不能把外部诊断或静态成功直接冒领原任务资格。新原生任务实例的来源、模型、物性、任务门须事前固定并完整验收。

当前工作O=`N/execution/fb2_goal_20261007_01`，P=`N/prepared/phase_feedback_20261007`，新代码`sage/experiments/embodied_expert_task_v3`。目标是执行器响应匹配、实际手指到位后推进、物体相对目标修正的专家控制。上一轮 `expert_adaptation_20261007/physics_direct_r1` 和更早候选均关闭，只作为离线回归输入；不恢复其物理试次。启动前1092项旧封存文件、旧PID启动标识和服务终态已核对。

[当前进展](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/fb2_goal_20261007_01/PROGRESS.json)、[执行计划](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/fb2_goal_20261007_01/PLAN.json)、[台账](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/fb2_goal_20261007_01/CURRENT_LEDGER.json)。串行作业入口 **N/tools/run_fb2_goal_job_r2.py**，台账 **N/tools/refresh_fb2_goal_ledger_r1.py**。先读取RECOVERY_POINTER和O/STATE核对真正活动PID/启动标识与实验服务，接管仍先请求STOP_REQUESTED并核验退出。持续目标标记不等于后台进程。

本轮开始共同18668.326837407/24000、全局42368.011728738/48000服务秒；静态83593/84000（余407）、动态650/23450、物理8290/234500、组件3/8、完整任务0/1，诊断渲染220/220。18GiB共同、47GiB全局、8GiB下载、CPU8/内存12–16GiB保持。所有费用与已预留差额继续累计。**当前控制代码在准备/几何检查中，未获物理准入，FB2未通过。**



### 2026-10-07 21:00更新：静态增额生效，首个新物理候选已失败

用户已明确批准仅增加8000次静态策略推理，上限84000→92000；追加账本在 `P/static_extension_r1`，原账本及全局48000/共同24000服务秒、物理次数/步数、磁盘、下载、渲染和科学门均保持。当前台账入口 **N/tools/refresh_fb2_goal_ledger_r2.py**。

新事件推进/物体相对目标控制完成1843帧几何、1893次完整原生名义检查和62次保持检查及独立审计。真实 `P/physics_component_r1` 共174动态前向、696物理步，在3.48秒/参考阶段71.5因手臂6.560855rad/s超过原6rad/s关闭；未抓箱，未启动完整任务。独立审计正在核对策略观察与实际积分状态的采样对应，尚未出完整通过凭据。保留失败；后继需要处理保持/跟随切换时的命令跳变，不能重复该失败试次。任务模型主体箱体9.855g，含两个把手总质量13.5206g，具体身份见P/TASK_INSTANCE_R1.json。

四小时仍是汇报间隔，目标继续；当前无新资源待批准。实际活动作业依RECOVERY_POINTER、O/STATE及PID启动标识核对。

### 2026-10-07 21:55更新：第二候选进入真实组件试验

首候选 `phase_feedback_20261007/physics_component_r1` 的696步失败已由独立审计复核，37294个接触条目、控制重建和策略历史误差均0；确认为保持/跟随切换时命令突跳，3.48秒手臂速度超过原6rad/s门。其141项封存保持，不能重跑。原生公开q/dq比命令时刻滞后5ms，后继已显式记录传感器与命令两个时间。

第二候选 `P/smooth_command_r1`，代码 `sage/experiments/embodied_expert_task_v4/phase_controller_r2.py`，加入持续位置命令速度/加速度限制、导航平滑和5帧可行性迟滞。1843帧几何、1893次原生覆盖、62次保持检查及独立审计全部通过；模型/物性与原质量门保持。物理冻结 `F/PHYSICAL_BINDING_R1.json`，真实组件 `smooth_component_01` 正在执行，**静态通过不能代替物理通过，FB2合格episode仍0**。活动状态以O/STATE、PID启动标识和实际服务为准。

累计静态87513/92000，动态825、物理8990为组件启动前计费数；共同19631.030093/24000、全局43330.714984/48000服务秒。当前台账入口 **N/tools/refresh_fb2_goal_ledger_r3.py**，包含嵌套后继目录；所有历史费用保留。四小时约23:40:52为汇报点，目标继续，无待批准资源。

### 2026-10-07 23:06更新：四候选均已独立审计关闭，阻尼后继已准备待范围决定

**FB2仍未通过，完整任务/合格数据episode均0。** 本轮4个新物理候选均已关闭并封存，各自首败与完整独立审计保留：①phase_feedback：3.48秒、阶段71.5、696步，手臂6.560855rad/s>原6；②smooth_command_r1：3.095秒、阶段35.5、619步，左腕/躯干接触；③stage_aware_r1：9.46秒、阶段156、1892步，目标不可达并连续保持3秒超时，未触发实际物理质量门；④wbc_intent_r1：8.295秒、阶段158、1659步，右中指/桌面接触1.634635mm。四项独立审计均通过，不能将“审计准确复核失败”误读成任务通过。

代码路径分别v3/v4/v5/v6。阶段接近解决了早期过约束；v6修复源WBC躯干姿态意图被腰部实际/参考关节角替代的问题，策略输入逐项核验误差0，但仍发生实际碰桌。C4命令终点和实际到命令的21点几何插值均有间隙，实际手指却以约1m/s向下运动，主要来自手臂速度。**可靠运动诊断为 `P/wbc_intent_r1/MOTION_DIAGNOSTICS_R2.json`**：直接网格/桌面距离与真实接触误差3.12e-17m；R1的mj_geomDistance原始负距离不可信，R1里复制的C2部位标签也已明确纠正，旧字节保留。人工核验图 `P/actual_progress_comparison_r1/actual_trials.png` 是真实状态科学图，未新增仿真渲染。

新准备 `P/passive_damping_r1`，代码 `sage/experiments/embodied_expert_task_v7/arm_damping.py`：每5ms对14个手臂原生力矩施加限幅速度阻尼，原生控制随后恢复，模型/努力范围和所有实际质量门保持。1659个保存状态限幅/耗散及返回/异常恢复预检通过，物理效果未验证。高层控制器、观察、策略历史和43位置命令未变，原生静态检查引用v6原证据，`NATIVE_REUSE_CERTIFICATE_R1.json`明示0新增策略前向，不能冒领新物理成功。

用户刚批准的静态增额方案明确至多4候选，已全部用完；因此已提交具体 `P/passive_damping_r1/CANDIDATE_SCOPE_PROPOSAL_R1.json` 请求范围4→5，**不增加任何累计预算**，只使用原剩余最后1个组件试次，成功并独立审计后才运行原有完整任务1次。第五候选准备绑定已冻结；`PHYSICAL_ADMISSION_PENDING_R1.json`仍为false，须收到明确范围批准后写匹配提案哈希的 `CANDIDATE_SCOPE_APPROVAL_R1.json` 才能启动。不要把旧静态增额批准当成第五候选批准。物理入口已准备 `N/tools/run_fb2_goal_job_r5.py`，worker `run_fb2_damping_physics_r1.py`；实际服务最长900秒来自原授权，累计秒数不变。

当前账本：共同21153.572880/24000、全局44853.257771/48000服务秒；本轮77服务2485.246042秒，新增静态7838、动态1217、物理4866。静态91431/92000；动态1900计费/1748已知实际；物理13290计费/12960已知实际；组件7/8，完整0/1；诊断渲染220/220、成功数据渲染0。共同磁盘14789287936/18GiB、全局44471050240/47GiB、下载6723717619/8GiB。当前全部服务终态；以O/PROGRESS和实际PID启动标识恢复。**台账入口N/tools/refresh_fb2_goal_ledger_r3.py**。四小时23:40:52仍只是汇报点，当前唯一待决定项是第五候选范围。

## 2026-10-07 17:10：完整参考/原生检查通过，迁移物理首败，进度观察器完成回测（最新 HANDOFF）

用户“继续下一步”已实际执行。**FB2仍未通过，自有合格任务/数据 episode 均0**；FB0/FB1、full-body数据生产主线和历史 V9/P11/P12/人类示范候选关闭状态保持。详情见[本轮场景迁移报告](EMBODIED_EXPERT_ADAPTATION_20261007.md)。

唯一结果：[expert_adaptation_20261007_01/RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/expert_adaptation_20261007_01/RESULT.json)，status=`scientific_exit_native_expert_adaptation_after_physics_and_bounded_diagnostics`。当前P=`N/prepared/expert_adaptation_20261007`，O=`N/execution/expert_adaptation_20261007_01`。恢复台账入口 **N/tools/refresh_adaptation_ledger_r3.py**。后台无活动驱动、实验服务全终态；按PID启动标识核对，先看实际STATE与RECOVERY_POINTER，勿恢复旧驱动。

922/922完整修正参考与末态原生谓词通过；新增975次静态策略调用（4预检+971覆盖）及独立输入/历史审计通过。以独立冻结的原生场景迁移进行一次真实物理：**214动态前向、856步、4.28秒左中指碰桌，禁止接触穿入0.328885mm，首次科学失败关闭 `physics_direct_r1`**。实际状态连续、无中途重置；独立审计40367接触条目距离误差0。最终采用按关节名字分组的审计R2，R1错误分组诊断保留；原28关节指令映射正确。没有真实完整任务通过。

根因证据：失败时根部位置误差<1mm、手臂误差0.05631rad、手指误差0.510108rad，箱体偏差约14.23mm；执行器输入无额外缩放。仅改手指静态姿态会引入箱体深穿透，必须同步处理实际抓握与物体相对位姿。四个固定快照的速度/逆动力学补偿未通过关节/力矩可行性，不取得新物理准入。新增进度观察器能在记录3.315秒发出HOLD，比失败早0.965秒；**只是代码和回测通过，安全保持/重定位控制与新闭环实际成功尚未验证**。

[实际数值诊断图](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/diagnostics_r2/actual_failure.png)没有新增仿真渲染。诊断渲染220/220；本轮RGB-D/成功数据/训练0。

费用：本轮45个串行服务664.521215715秒；共同18668.326837407/24000，全局42368.011728738/48000；下载6723717619/8589934592字节。原账本静态83593/84000（余407）、动态650计费/531已知实际、物理8290计费/8094已知实际、组件3/8、完整任务0/1。所有费用/未用预留/历史证据保留，4854历史绑定文件核验一致。原18:05:16 +0800截止不重置，无资源增额或待批准项。

接续依据[下一执行合同](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/NEXT_EXECUTION_CONTRACT_R1.json)：保留成熟WBC与专家采集接口，准备依据实际箱体与手指状态推进的抓握控制；先证明保持/重定位动作可行并核算新的原生覆盖，再给新方法独立物理准入。**当前没有已准入物理后继**，不得换名重跑已失败候选或把922参考/971静态/观察器通过写成FB2通过。完整外部实测及审计通过后才进入自有生成场景、合格数据与学习验证。


## 2026-10-07 13:57：专家示范路线已修改并实测，按质量与来源门收束（最新 HANDOFF）

用户已授权沿“复用完整任务专家示范/控制 → 完整 episode → 数据闭环”修改和尝试。本轮主线已纠偏，**不再以继续 P12 动力学控制研究为默认后继**。最终目标、FB0/FB1、旧 V9/P11/P12 关闭证据和全部累计费用保留。

唯一当前结果：[expert_task_20261007_01/RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/expert_task_20261007_01/RESULT.json)，status=`scientific_exit_expert_sources_unqualified`。详情见[专家路线实测报告](EMBODIED_EXPERT_TASK_TRIAL_20261007.md)。全部实验服务终态、按 PID 启动标识核对退出；新恢复指针已发布，台账入口 **N/tools/refresh_expert_ledger_r1.py**。旧 O=research_run_20261007_01 的结果/STATE 均是历史，不恢复执行。

新代码 `sage/experiments/embodied_expert_task_v1` 已接通 CPU 控制、严格示范读取、来源资格判断和精确模型保存。复用既有同哈希两份 ONNX 权重，第一条动作与人类源一致。实际外部桌到架目标驱动试验：303 动态前向、302 完整命令、1209 积分步，**6.045 秒因右手/箱体把手穿透 11.009523 mm > 原 10 mm 失败**；箱子已抬高约 10.7 cm。仅一次初态恢复、无中途写状态，首次科学失败后候选 `prepared/expert_task_20261007/goal_control_r1` 关闭。独立审计用原始模型重建后全部接触距离误差 0；普通导出 XML 不等价，新增二进制快照往返逐数组一致。6 项输入/模型检查和 4 项来源资格回归通过。**这些不是 FB2 通过：自有合格完整任务/数据 episode 仍 0，未新增 RGB-D/导出/训练。**

另两条来源已核查：policy replay 的桌到架记录被发布方明确标注任务失败，本地 1250 保存状态也均未成功，未新增物理；训练库第一分片第 0 条（922 行）有完整控制字段，但缺逐 episode 的模型、静态摆放和版本合同，未准入物理。真实仿真间隔 20 ms，不能盲从 script_config 的 20 Hz 数据频率重放。不得把“九任务回放 PASS”当成九任务均成功。

费用：本轮 23 个串行服务累计 **180.817550883 秒**；共同 **18003.805621692/24000**、全局 **41703.490513023/48000 秒**；下载 **6723716334/8589934592 字节**。动作原台账：静态 82618/84000，动态 425 计费/317 已知实际，物理 7390 计费/7238 已知实际；旧差额及新部分预留均保留。组件 claim 2/8（原 P12 一次、本轮外部诊断一次），完整任务 0/1；诊断渲染 220/220、成功数据渲染 0。当前无资源增额或待批准事项。五小时上限窗口保留 PLAN，按有限科学退出收束，不为填满时长盲跑。

下一步先补齐完整专家源的准确场景/版本合同；或单列有明确身份与独立准入的场景迁移方案。保留现有控制接口与数据工程，优先合格完整任务产出，不退回单臂、不重开旧矩阵、不放宽原门、不将已失败试次改名重启。当前**没有已准入的物理后继**。完整成功及独立审计后，才进入同步 RGB-D、标准导出和真实训练读取；FB3 未准入。

## 2026-10-07 05:40：P12 几何/原生全通过，真实物理首败及有限动力学后继已收束（最新 HANDOFF）

最终完整性核验已通过：六组历史/当前绑定去重4362个文件全部哈希一致，历史驱动PID均已消失，实际活动实验服务0，原动作账本未改写，全部原累计预算均未超限。核验收据为 O/FINAL_VERIFICATION_R1.json。

本轮从01:30:28持续推进，五小时窗口原截止06:30:28 +0800不变；本次按**真实物理第一科学失败及有限数值后继退出**收束，没有耗尽时间来替代科学判断。FB2仍未通过，合格自有完整任务/数据episode均0。普通工程修订已自主处理，没有逐包待批准。FB0/FB1既有结论保留，full-body主线不变。

**唯一有效总结果：** [RESEARCH_RESULT_R1.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/research_run_20261007_01/RESEARCH_RESULT_R1.json)，status=`scientific_exit_after_bounded_dynamic_followup`。所有本轮驱动均已退出、全部实验服务终态，无活动编排器；物理驱动1367551/66440170和原生驱动1356609/66298865仅是历史身份。实际恢复入口 N/RECOVERY_POINTER、O/SCIENTIST_STATE 和 T/evidence/LONG_RUN_CHECKPOINT 已统一发布分层结果，台账刷新入口改为 **T/tools/refresh_effective_relative_closed_r1.py**。O/STATE保留最后诊断作业的真实终态，不覆盖历史执行记录。V9、P11、P12均不得重开；P12成功的几何/原生证据可以作为有明确来源的新方法输入，不能重跑或继承为新控制器物理成功。

| 验证层级 | 本次实际结果 | 不能据此宣称 |
| --- | --- | --- |
| 外部G1正对照 | 1249记录动作、4996步精确回放与独立审计通过 | 自有场景或自有FB2成功 |
| P11几何 | 6通过/3非通过/2未运行，按第三非通过关闭 | 继续补跑未运行工况 |
| P12几何 | 11/11工况，各15/15阶段、接触/停止违规0，全部独立审计通过 | 动态跟踪或任务通过 |
| P12原生反事实 | 11/11、82588次策略前向、完整独立审计通过 | 实际闭环物理成功 |
| P12真实组件 | 1个试次，140物理步、14条命令，0.28秒科学失败；失败独立审计通过 | 组件通过、完整任务或训练数据 |
| 动力学后继 | 固定输入消融和逐步审计完成；两种受限力矩数值方案均首快照失败，未获得物理准入 | 新控制器已经验证通过 |

P12方法ID ac021b110dbed1f412a5d4038603ee52df00a9286fae051d53805c3b58d8805c；GEOMETRY_BINDING 3458项、NATIVE_BINDING_R1 4015项保持。真实物理冻结SHA256 48960884c0eaee2729a4132eed124425d66753d6460a361d3ac3cf6ed49b145b；**CAUSAL_SCIENTIFIC_CLOSURE_R1 4192项**保留首败与服务费用；**POSTMORTEM_BINDING_R1 214项**追加有限诊断、数值失败和回归证据。两项绑定均不可改写。

物理失败发生在settle：右肘误差0.144885505770rad，原上界0.144598397325rad，超出0.000287108446rad；命令14在0.28秒被拒绝，尚未接近/抓取。COMPONENT_AUDIT准确重建140步/14命令，输入、目标、力矩、接触最大误差均0，失败原因复核通过。原measure_task截至退出无碰撞/跌倒等物理门失败；这不代表误差域始终成立。独立逐2ms审计发现**0.054/0.056秒右肩短暂越界**，随后恢复；右肘从0.274秒越界，0.28秒才落到20ms命令检查点。共有6个保存子步越出原域。新增sage/experiments/embodied_task_space_v12/offline_tracking_audit_r1.py；实际早期退出、20ms采样漏过瞬态、历史校准前500步和缺帧拒绝四项回归均通过；只是离线审计能力，未改已关闭物理试验。

人工核验：[真实失败慢放](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/task_relative_v12/diagnostics/startup_video_r1/fb2_actual_startup_failure.mp4)（8个真实保存状态，0.28秒放慢至8秒，64编码帧；没有新增物理）；[逐步误差图](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/task_relative_v12/diagnostics/continuous_domain_r1/continuous_domain.png)；[几何进展图](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/diagnostics/p12_geometry_report_20261007/layout_r2/geometry_progress.png)。最后8次诊断渲染已使用，累计**220/220**；成功数据渲染仍0。视频已解码检查并人工查看关键帧。

费用与动作全部保留：共同**17822.988070809/24000**、全局**41522.672962140/48000服务秒**；共同已分配12891533312字节/18GiB，全局42563076096字节/47GiB；下载6716647671/8589934592字节。静态82616/84000（82588覆盖+28诊断），动态**100计费/14实际审计**，物理合计**6090计费/6029已知实际**（外部5890/5889，自有200/140）；61步预留差额和86次未用动态预留不退回、不清零。组件claim1/8已真实消耗并科学失败，完整任务0/1；通用used-minus-completed里的component1是已消耗claim，不能误解为未知是否执行。详见 [ACTION_RECONCILIATION_R1.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/research_run_20261007_01/ACTION_RECONCILIATION_R1.json)，原234500步/23450动态/8组件/1全任务限额保持。

下一步瓶颈是**接触非线性下的全身动态跟踪及逐物理步准入**。当前没有通过预检且已获物理准入的后继，不能从components目录重启已消耗试次、跳过组件去跑全任务，或用放宽旧误差上界制造通过。后续应准备有独立控制合同与准入的新方法，明确处理脚接触、底座/上肢耦合和连续误差域，保留原接触、力矩、末端任务质量门。更换控制律所需的新验证必须单独证明；当前完整新原生覆盖若需重新推理82588次，剩余1384次额度不足，不能通过更名重置。纯代码或数值准备不等于物理验证。

本轮方法改变和诊断依据：

- P12用物体相对6D关键帧、位置优先IK、同条件已审计整条参考初始化和原硬约束投影，解决P11横向偏移与端点退化；正式搜索、6mm/12mrad终门没有放宽。此前数值r2/r3/r4、原生同名common导入失败43.532秒、离线审计首版语法失败均保留原字节/费用；没有未解决的工程报错。
- 原误差包络来自旧native_skills单条发展轨迹的观测极值，原文件就明确“不作统计覆盖保证”。新旧已比较的机器人质量、惯量、阻尼与执行器参数相同；机器人初始qpos仅全局x平移-0.4m、qvel相同，上肢参考前0.28秒差异小于8.6e-7rad。新启动加入实测底座位置反馈，旧启动导航为0。不能仅从两轨迹差异认定唯一因果。
- 28次固定输入消融中，14次事实策略输出逐位复现；只把保存历史的导航输入置零，下肢目标最多改变0.011499643326rad。观察和先前动作仍是事实历史，没有积分替代轨迹，不能推断“关掉反馈即可完成任务”。直接加完整上肢偏置力矩也只做瞬时动力学假设检查，显示明显反向加速度，不是物理成功方案。
- 上肢14执行器受限修正和全身29执行器受限修正，都保留旧误差/原执行器力矩界，另设固定保守的25%附加修正及底座加速度变化界，在初态固定局部线性规划即失败；各余13快照按预设首败退出未跑。Farkas证书残差分别4.12e-15/1.11e-16、负间隙-17.017/-2.117，证实的只是这两组固定线性约束不可行，**不是全身任务无解**。
- 全身固定初态的三项附加假设消融不修改原试验或任务门。移除附加保守界后，线性规划有解，但相同状态用MuJoCo mj_forward复核，原误差屏障的关节加速度约束仍超差约12.022或66.085rad/s²；一项底座俯仰加速度变化达-104.25rad/s²。由此不能把局部线性有解当成接触非线性下的可执行控制。所有这些预检和证书：0新物理步、0新动态调用、0新组件试次。

## 2026-10-07 05:10：P12 原生11/11已封存，真实物理组件执行中（最新 HANDOFF）

几何11/11及全部独立审计保持通过；原生11/11、82588次真实策略前向及全部独立审计也已通过，原生驱动1356609/66298865退出、服务全部终态。M=N/task_relative_v12 的 NATIVE_BINDING_R1 已封存4015项，覆盖所有失败和成功原生服务。原生仍为零速度反事实覆盖，不等于物理成功，不重跑任何已完成矩阵。

真实物理执行已准入：M/protocol/PHYSICAL_EXECUTION_FREEZE_R1 共4081项，SHA256 **48960884c0eaee2729a4132eed124425d66753d6460a361d3ac3cf6ed49b145b**。P=N/prepared/task_relative_causal_20261007_r1 的原协议、预检、工程修复和全部依赖保持原字节。控制层 CAUSAL_CONTROL_ADDENDUM_R1 只减少外层重复读取，实际run/audit/capture/export_relative_*_r2进程仍完整校验物理准入；缓存与完整准入一致检查通过。早一次缓存准备在完整校验仍运行时读空JSON失败，未建附录、0动作；完整校验终态后已成功准备。

**当前唯一因果物理驱动 1367551 / 66440170，入口 N/tools/run_relative_causal_matrix_r3.py**，实际状态 M/execution/CAUSAL_STATE、O=N/execution/research_run_20261007_01/STATE 和 fbts_template_lr_relative_causal_* 服务。接管先请求 M/execution/STOP_REQUESTED 并核对PID启动标识与服务终态。实际工作入口run_relative_causal_trial_r2/audit_relative_causal_trial_r2；控制作业run_relative_causal_job_r3；台账T/tools/refresh_effective_relative_causal_r3。8组件是同一条积分历史的连续范围，无段间重置；只有全8和独立审计通过才试一次单独完整任务。首个物理科学失败关闭候选，不重启已消耗试次。数据入口capture_relative_rgbd_r2/export_relative_native_r2仍为条件式准备，尚未物理成功，不可宣称FB2通过。

原生最终共同17385.215660331/24000、全局41084.900551663/48000服务秒，当前物理另计。外部5890计费/5889确认步与1未确认预留保持。静态82588/84000、动态23450、物理234500步、8组件/1全任务，18GiB共同/47GiB全局/8GiB下载、诊断渲染212/220及06:30:28 +0800截止均保持。旧V9/P11关闭，自有FB2合格完整任务仍0。

## 2026-10-07 05:01：原生入口已修复，R4 唯一驱动继续；物理入口改为 R2（最新 HANDOFF）

P12 几何 **11/11通过且完整独立审计通过**、3458项 GEOMETRY_BINDING 保持，原几何驱动已退出，不重跑。原生首个服务因为同名common.py导入顺序选中N/tools/common.py，在读取错误WORKSPACE.json时退出；**0策略前向、0物理步**。失败进程43.532140180秒以及全部服务费用保留，nominal新剩余累计子进程上限256.467859820秒，不重置300秒。旧驱动1354679/66268554已退出且服务已终态，其 NATIVE_CONTROL_FAILURE_R3 已归档。

实际修复 cover_relative_native_r2 在使用原生公共模块前明确解析 Mparent/tools/common.py；native_worker_admission_r2 仍先完成原native_admission_r1全量校验，再验证 NATIVE_WORKER_REPAIR_R1。原native科学身份 **eb32a5d05a07f449c8eb2dcb4ab96b2d93be537be247dbd6f5b217d42f04b2af** 与原配额/第一科学失败退出均保持。R4控制附录保留R2/R3和失败证据，未放宽科学门。

**当前唯一原生驱动 1356609 / 66298865，入口 run_relative_native_matrix_r4.py**；已审计 [('nominal', True), ('xminus', True), ('xplus', True), ('yminus', True), ('yplus', True), ('yawminus', True), ('yawplus', True)]。实际状态 M/execution/NATIVE_STATE、O/STATE与服务优先；接管先请求 M/execution/STOP_REQUESTED，核对驱动启动标识与服务终态。台账入口 **T/tools/refresh_effective_relative_native_r3.py**。原生终态用 **seal_relative_native_r4.py**，连同全部失败/成功服务、R4控制附录封存；只有全11原生覆盖和审计通过后，才生成NATIVE_BINDING_R1并衔接物理。

P=N/prepared/task_relative_causal_20261007_r1 的原 INPUT_FREEZE_R1/PLAN_R1/PREFLIGHT_R1 和6项控制检查均保留。真实初态第一命令预检通过；合成历史6859拍越界仅为诊断，真实动态跟踪未验证。同名common导入修复已版本化应用于未执行物理/数据入口，新增 **ENGINEERING_REPAIR_R1**：后续必须 **freeze_relative_physics_r2 → run_relative_causal_matrix_r2**，内部 run/audit_relative_causal_trial_r2、admit_relative_physics_r2、run_relative_causal_job_r2；台账T/tools/refresh_effective_relative_causal_r2。capture_relative_rgbd_r2/export_relative_native_r2也已准备。R1旧入口全部保留但不再执行。**目前物理执行冻结尚未创建、物理组件及全任务均未运行，不能声称FB2通过。**

原生服务最近结算共同 17023.202667559/24000、全局 40722.887558890/48000秒，另有活动服务待结算。所有失败费用、外部5890计费/5889确认物理步与1未确认预留不清零；静态调用从原共享84000额度扣减，物理234500步/动态23450/8组件/1完整任务保持。仍 **06:30:28 +0800截止**，共同18GiB/全局47GiB/下载8GiB，诊断渲染212/220。几何对比图见 N/diagnostics/p12_geometry_report_20261007/layout_r2/geometry_progress.png，明确仅几何结果。

## 2026-10-07 04:42：P12 全11几何工况通过，原生覆盖已启动（最新 HANDOFF）

**M=N/task_relative_v12 已11/11工况、各15/15阶段完整几何和独立审计通过，0非通过、0未运行；正常接触与停止接触违规全0。** 方法ID ac021b110dbed1f412a5d4038603ee52df00a9286fae051d53805c3b58d8805c 保持。原驱动1330528/65941977已退出、全部几何服务已终态；M/GEOMETRY_BINDING.json 已封存3458项，scope=complete_local_geometry_and_audits。**这不是FB2物理通过。** 原几何矩阵不可重跑，旧V9/P11历史保持关闭。

真实初态零步预检 P=N/prepared/task_relative_causal_20261007_r1/PREFLIGHT_R1 已通过，3661项 INPUT_FREEZE_R1 保留前瞻协议、原物理门及因果/数据依赖。初条实际命令通过；合成上一拍参考+采样误差的诊断仍6859/7450拍越出旧误差域，最大0.007rad，不能当成真实物理失败或成功，真实控制必须发送前逐拍检查。预检服务12.113秒已计费，物理/策略0。

原生执行冻结 M/protocol/NATIVE_EXECUTION_FREEZE.json 已准入，SHA256 **eb32a5d05a07f449c8eb2dcb4ab96b2d93be537be247dbd6f5b217d42f04b2af**，82588参考帧、84000累计静态调用上限、第一原生科学失败退出。NATIVE_CONTROL_ADDENDUM_R3 仅去除编排层重复完整哈希，并修复恢复指针；**cover_relative_native_r1 / audit_relative_native_r1 仍在每个真正执行进程内完整验证全部字节和语义**。原方法/科学门/配额/300秒累计原生单例不变，5项R2控制检查及R3身份一致检查通过。r1/r2原生驱动均未启动。

**当前唯一原生驱动 1354679 / 66268554，入口 N/tools/run_relative_native_matrix_r3.py**，实际状态 M/execution/NATIVE_STATE、O/STATE 和 codex-stretch-ai-20260926-fbts_relative_native_* 服务。当前从nominal开始覆盖，禁止另起驱动。台账入口 T/tools/refresh_effective_relative_native_r2.py；接管先 M/execution/STOP_REQUESTED，并核对PID启动标识和服务终态。原生结束须使用 **seal_relative_native_r2.py**，它保留R3控制附录；全通过才生成 NATIVE_BINDING_R1，否则原生科学退出，禁止后续物理。

物理后继 P/PLAN_R1 的8段连续任务范围组件及单独全任务入口仍为已冻结准备，**未PHYSICAL_EXECUTION_FREEZE、未运行**。原生全通过且服务终态后 freeze_relative_physics_r1 → run_relative_causal_matrix_r1；第一物理科学失败关闭该候选，不能重启消耗的试次。组件是同一条积分历史8段，不是8独立episode；全任务与数据验收必须单列。capture_relative_rgbd_r1/export_relative_native_r1 仅条件式代码准备，不能计作实验成功。

最近终态共同 **16169.351815276/24000**、全局 **39869.036706607/48000服务秒**，另有当前原生服务待结算；外部5890计费/5889已确认物理步与1未确认预留保持。共同18GiB、全局47GiB、下载8GiB、诊断渲染212/220和本轮 **06:30:28 +0800截止**均保持。自有FB2合格完整物理任务0，无新资源授权问题。

## 2026-10-07 04:25：P12 横向偏移已完整通过，矩阵继续，物理后继仅准备（最新 HANDOFF）

M=N/task_relative_v12 仍由唯一 **1330528 / 65941977** 驱动运行，入口 run_relative_matrix_r1.py，方法ID ac021b110dbed1f412a5d4038603ee52df00a9286fae051d53805c3b58d8805c 与2938项冻结均保持。当前 matrix_service_requested / tracking_min / relative_case_tracking_min_01；已审计 [('nominal', True), ('xminus', True), ('xplus', True), ('yminus', True), ('yplus', True), ('yawminus', True), ('yawplus', True), ('body_low', True), ('body_high', True)]。yminus 第3次更新正常/停止违规均0、15/15通过，搜索151.004秒；yplus 15/15通过，搜索140.843秒。body_high 已搜索通过、80.255秒，独立审计阶段以实时STATE为准。旧V9/P11关闭证据不改，不重开，不重复运行已有案例。

N/tools/seal_relative_geometry_r1.py 已准备，须矩阵驱动退出及实际服务全部终态后使用：全11通过才创建 M/GEOMETRY_BINDING，否则创建科学关闭绑定。原第三非通过退出仍生效。N/tools/diagnose_relative_contacts_r1.py 仅失败后保存路径诊断的代码准备，**未运行**。

原生后继新入口 run_relative_native_matrix_r1.py、freeze_relative_native_r1.py，M/protocol/NATIVE_PREPARED_R1_FREEZE 已封存3089项，修正旧审计变量索引、原生单例累计进程计时、有效窗口和已批准84000静态调用标志。采用已测批量预留100调用；原7450/8088行、总82588、第一原生科学失败退出、零物理反事实语义保持。缺全几何绑定负检查通过。**原生尚未冻结执行、尚未运行**。只有全11几何通过后才能 freeze_relative_native_r1 → run_relative_native_matrix_r1；原生全通过后 seal_relative_native_r1 创建 NATIVE_BINDING_R1。

P=N/prepared/task_relative_causal_20261007_r1 的因果物理后继仍为代码准备，尚未INPUT_FREEZE、初态数值预检或物理准入。采用全部 nominal 参考连续分成8段（850/1000/900/850/1150/850/900/950控制拍），仿真状态和策略历史连续，**不是8个独立episode**；组件共74500物理步，保留原每例40秒及全部原任务/接触/旧经验跟踪边界。组件全部及审计通过后才尝试独立完整任务1次≤74500步，再做物理审计、RGB-D和真实训练读取。原8组件/1全任务/234500步/23450动态调用限额保持且包含外部对照费用。首个科学失败关闭候选、消耗试次不重启。新 causal_reference_r1 有6项纯控制检查通过（无物理/策略），真实初态须后续 prepare_relative_causal_r1 → run_research_job_r1(preflight_relative_causal_r1.py)验证；再经原生全通过和 freeze_relative_physics_r1 才能 run_relative_causal_matrix_r1。**所有这些代码仍需实际阶段验证，不能宣称FB2通过。**

最近已结算共同 15866.355295365/24000服务秒，全局 39566.040186696/48000秒，另有活动服务待结算；18GiB共同/47GiB全局/8GiB下载保持。本轮截止06:30:28 +0800不延长，无待批准新资源。实际STATE优先于恢复指针历史杂项。外部5890计费/5889已确认步及1未确认预留、诊断渲染212/220、自有合格完整物理任务0保持。

## 2026-10-07 03:55：P12 完整几何矩阵已准入运行（最新 HANDOFF）

全部11条件初始化准备及独立审计通过，P/PREPARATION_RESULT_R5 已封存。新 M=N/task_relative_v12 已正式冻结2938项，方法ID **ac021b110dbed1f412a5d4038603ee52df00a9286fae051d53805c3b58d8805c**，M/protocol/MATRIX_EXECUTION_FREEZE_R1 SHA256 **0ea67c9a6b4762b1d5baa9392444ef16c384ea2bd786f65ea87f418d57f7f77f**。初始化 task_relative_seed_r5 使用物体相对6D关键帧、位置优先IK、同工况完整已审计起点、连续拟合与原硬约束投影；正式搜索保持 component_search_r2，最终质量门没有放宽。

唯一矩阵驱动 **1330528 / 65941977**，N/tools/run_relative_matrix_r1.py；当前状态 **matrix_service_requested / xplus**，已独立审计案例 [('nominal', True), ('xminus', True)]。实际状态查看 M/execution/STATE、O=N/execution/research_run_20261007_01/STATE 及 codex-stretch-ai-20260926-fbts_* 实际用户服务。不要另起驱动；需接管先 M/execution/STOP_REQUESTED，请求现驱动在边界退出并核对PID启动标识及服务终态。旧准备驱动1324859/65865871已退出。

台账入口 T/tools/refresh_effective_relative_r1.py。最近终态共同 **14667.707013746/24000服务秒**、全局 **38367.391905077/48000秒**，另有活动服务待结算；共同18GiB/全局47GiB/下载8GiB保持。当前五小时窗口截止 **06:30:28 +0800**，无新授权问题。11工况、15阶段、6迭代、300秒累计单例与第三非通过退出保持。全部几何通过后才能接续原生覆盖，后继目前仅代码准备，不能声称原生或物理已通过。

C=P11 已6通过/3非通过/2未运行科学退出、2792项关闭绑定保持；V9也已关闭，不得重开。外部 G1 正对照独立成功、5890计费/5889已确认物理步及1未确认预留保持，不能计入自有FB2。诊断渲染212/220、自有FB2合格完整物理任务仍0。

## 2026-10-07 03:36：P12 最终初始化正在独立审计，完整几何矩阵尚未启动（最新 HANDOFF）

C=P11 的6通过/3非通过/2未运行和2792项关闭绑定保持。当前后继 P=N/prepared/task_relative_initialization_v12，最新算法 **task_relative_seed_r5 / PLAN_R6 / INPUT_FREEZE_R5（2884项）**。已有完整已审计同工况参考用于逆运动学初值；名义物体相对目标仍取原整轨迹，掌心位置未达0.5mm时先解位置，再改善朝向。终端目标留5mm内部余量，最终门仍6mm。原所有运动硬行、完整源序列、20ms控制网格和手指参考保留，无物理准入。

早期 reference_r2/r3/r4 全部保留：r2 连续拟合退化；r3 tracking_min 固定旧近似解引入7条约1e-10源进度硬冲突，且非有限失败诊断触发JSON保存异常；r4 修复该数值冲突但 body_high 局部IK仍30mm。r5 使用同工况已审计完整姿态起点及位置优先，body_high 抬升末端1.165mm、各阶段最大5.036mm，yminus 最大5.008mm。仅初始化数值结果，完整路径接触/刹停尚未验证。tracking_min 数值修复保留原硬行，允许有界进度系数微调；r4 实测源进度最大变化6.96e-8，不得声称该工况与旧进度逐位相同。

当前唯一参考准备驱动 **1324859 / 65865871**，N/tools/run_task_relative_preparation_r3.py；实际状态 P/execution_r3/STATE 与 O=N/execution/research_run_20261007_01/STATE，接管先请求 O/STOP_REQUESTED 并核对服务终态。前两个准备驱动均已终态、旧输出不覆盖。新 M=N/task_relative_v12 的执行/审计/资源入口已准备，**未冻结、未启动**。待 PREPARATION_RESULT_R5 显示全部11参考审计通过且驱动终态，执行 prepare_relative_matrix_r1.py → run_relative_matrix_r1.py；新身份、全11工况、6迭代/300秒累计单例、第三非通过退出保持。6个已通过工况只复用整条初始参考，必须重新完整计算/独立审计，不能继承成功。

最近终态共同14361.695072743/24000服务秒、全局38061.379964074/48000秒，另有活动服务待结算。仍截至06:30:28 +0800，无资源增额问题。外部回放补充 GRIPPER_DISTANCE_AUDIT_R1 已通过：底座净位移1.325m、箱体质量0.0146065kg，官方条件为至少一夹爪距物体≤0.4m。其成功不得替代自有FB2；外部5890计费物理步、1未确认预留保持，诊断渲染212/220，FB2合格完整任务仍0。

## 2026-10-07 03:00：P11 已科学退出，物体相对初始化正在数值预检（最新 HANDOFF）

当前 C=N/component_endpoint_v11 已完成 **6通过/3非通过/2未运行**，按原第三非通过规则科学退出；通过 nominal/xminus/xplus/yawminus/yawplus/body_low，非通过 yminus/yplus/body_high，tracking_min/max 未运行。全部9工况的完整路径与接受/拒绝决策已独立审计。body_high 已零接触违规、14/15阶段，只剩 rise_lift 掌心6.04661275mm 高于6mm，仍按非通过记录。yminus/yplus 最大掌心约73mm且仍有接触违规。2792项 SCIENTIFIC_CLOSURE_BINDING_R1 保留原方法和所有证据；驱动1287282/65407101及实验服务已终态，**不得重开 C 或补跑其两项未运行条件**。

后继 P=N/prepared/task_relative_initialization_v12：固定规则在新矩阵前保留 C 已通过工况的整条已审计参考，其余工况按名义手掌相对物体的位置与朝向迁移关键帧、连续样条拟合，再投影到原运动硬约束；原源身体/物体轨迹、源时间与手指参考不变，不是站位重规划。原11工况完整重验、6迭代/300秒累计单例/第三非通过退出及物理门均保持，不能继承 C 的通过结论。

首个 yminus 数值准备 reference_r2 原约束证书和独立关键帧审计通过，但连续拟合/投影使部分端点误差增至47.64mm；**仅参考约束通过，不是几何通过，未准入新矩阵**。首版输出、审计和费用保留。新 task_relative_seed_r3 将终端 IK 关节值作为初始化投影等式，后续正式搜索仍使用原任务空间门；PLAN_R4 与2810项 INPUT_FREEZE_R3 已冻结，当前作业 relative_reference_yminus_02 正在预检。实际研究作业状态读 O=N/execution/research_run_20261007_01/STATE，不因 C 已退出而重复启动服务。

本轮仍截至 **06:30:28 +0800**，无新资源授权问题。最近结算共同14119.328682406/24000服务秒、全局37819.013573737/48000秒，另有当前准备服务待结算；18GiB共同/47GiB全局及8GiB下载限额保持。外部 G1 1249动作/4996步精确回放及独立审计成功仍为单独外部正对照；含中断合计5890计费/5889确认完成步，1未确认预留保持费用。诊断渲染212/220、自有FB2合格完整任务0。外部夹爪距离/质量补充审计入口已准备，尚未运行。只有当前准备通过、独立审计和新科学身份冻结后才能启动后继完整几何矩阵。

## 2026-10-07 02:19：研究方案已实际测试，外部回放通过，P11 新矩阵继续（最新 HANDOFF）

用户最新“那就按照当前思路去测试”已用于本次版本化五小时窗口，O=N/execution/research_run_20261007_01，截止 **2026-10-07 06:30:28 +0800**；原窗口 PLAN 原字节、既有批准额度和累计费用均保持。无待用户授权事项。V9 已从原 yplus 断点执行并独立审计，达到 **2通过/3非通过/6未运行**，按第三非通过科学退出；2025 项 SCIENTIFIC_CLOSURE_BINDING_R2 保留证据，不得重开。

当前 C=N/component_endpoint_v11 是有实质变化的新方法：保护接触失败阶段中原本已合格的掌心/手分量。数值预检发现旧径向单平面保护允许横向误差逃逸（yminus 预测掌心49.14mm），故在矩阵准入前改为旋转坐标系八面体完整向量保护，未放宽最终6mm/12mrad。r2 数值独立证书通过，xplus/yminus close 线性预测5.514/4.731mm。2119 项 MATRIX_EXECUTION_FREEZE_R2 已准入，方法ID d9f013a3a98145c85e58e2a922c01e26d46505b7a09b20fbb8b66553b91f215e；原11条件、6次迭代、300秒累计单例、第三非通过退出均保持。

C 的 nominal/xminus 已完整15/15阶段及独立审计通过；xplus 已搜索到15/15完整路径，正在独立审计。为串行执行外部对照曾请求矩阵退出，原驱动1276530/65272842已核对终态，STOP_REQUESTED 已归档为 STOP_REQUESTED_EXTERNAL_CONTROL_COMPLETED_R1.json。**唯一恢复驱动1287282/65407101，入口 N/tools/run_component_matrix_r2.py**；从已有 xplus 审计继续，不重跑前三例。实际进度以 C/execution/STATE、O/STATE 与 services 为准。接管须先请求退出并确认实际服务终态。

外部正对照 P=N/prepared/hmg_external_control_20261007 已验证：官方 HumanoidMimicGen 固定源码、G1 03_box_lift 固定动作数据，在隔离 MuJoCo3.2.6/robosuite1.5.1 环境实际执行1249动作、4996物理步；1249×113状态与原数据逐元素精确一致，官方任务最后成功。独立审计通过高度、无桌面接触及状态对照；夹爪距离条件仍由官方原生谓词验证，未独立重建。仅允许开头一次恢复初态，中途无状态注入、无新策略前向。结果 P/recorded_control_r2/RESULT、INDEPENDENT_AUDIT_R1、external_control_validation.png。该外部任务的物体/成功条件不同，**不得计入自有FB2通过**。

第一次外部回放因逐步同步日志磁盘延迟主动中止，893已完成物理步及894预留计费全部保留；新批量预留计费经3项工程检查，再执行同一固定动作。合计外部5890计费/5889确认完成物理步，1未确认预留保持计费。既有共享234500步额度内扣除，不扩大额度；诊断渲染仍212/220，新策略/训练0，自有FB2物理合格完整任务仍0。

最近外部审计终态累计共同12348.890848159/24000服务秒、全局36048.575739490/48000秒，另有当前矩阵活动服务待结算；下载6716647671/8589934592字节。共同18GiB/全局47GiB磁盘限额保持。C 当前台账入口 T/tools/refresh_effective_component_r2.py；通用研究作业内部旧刷新器可能临时指回V9，不能据此重开旧矩阵。

物体相对关键帧初始化 task_relative_seed_r1 仅代码准备，无数值预检、无新路径、无矩阵准入。仅在当前 C 合法收束且证据支持后考虑该后继；不能把它或外部成功写成FB2实现。当前路线仍 full-body 自有场景数据闭环，不回到单臂、不重开旧矩阵。

## 2026-10-06 18:25：批准已应用，yminus已执行并审计，原窗口结束后断点在yplus（最新 HANDOFF）

**用户“批准”已应用为一次完整续接授权，无待资源批准问题。** 额度仍有效：共同包24000服务秒/18GiB、全局48000秒/47GiB、静态84000调用；body_high几何参考8088、矩阵参考82588帧。原物理次数/步数、科学退出、历史费用不变。完整授权与GEOMETRY_SCOPE凭据见V9/evidence/RESOURCE_EXTENSION_R2和V9/protocol/GEOMETRY_AUTHORITY_R1。不要重复申请或再次应用同一增额。

批准到达时18:09，本轮原18:25:04 +0800窗口现已结束。V9=N/whole_template_transfer_v9现为 **2通过/2非通过/7未运行**，下一断点 **yplus**；nominal/xminus保留通过，xplus/yminus非通过。没有达到第三非通过，不得关闭/重开V9。yplus的作业目录template_case_yplus_01只记录启动前时间门拒绝，没有启动实验服务、没有新案例目录，不算已消耗案例。后续继续需版本化建立新的获用户授权工作窗口，保留原O/PLAN字节及四个已审计案例；资源额度不再申请、不清零。

yminus实际执行13条完整保存路径，最后i3_s0p125仍11/15阶段通过。settle掌心80.7198→44.4204mm；close最后掌心56.3008mm、手85.2445mrad，rise_lift掌心22.8782mm，carry仍有接触违规；最终正常1067处、停止9572处违规。原单例300秒上限保持，搜索282.8165秒，进程/服务开销实际记账。独立几何、QP和接触记忆审计通过，只证明记录及原接受规则一致，不代表任务通过。新CASE_BINDING_R1封存已完成yminus，矩阵保持可恢复。

此次新服务合计 **436.882078411秒**（搜索服务298.245404802、审计138.636673609）。共同累计 **10949.684467976/24000秒**，余13050.315532024；全局 **34649.369359308/48000秒**。包磁盘快照6531874816/19327352832字节，下载6443180321字节。原渲染累计212，新增策略/物理/训练0、FB2合格完整任务0。台账入口仍T/tools/refresh_effective_template_r3.py。窗口结束时1906项历史/新证据绑定复核一致；精确终态O/WINDOW_CHECKPOINT_R3.json、O/SCIENTIST_STATE及N/RECOVERY_POINTER。

唯一恢复矩阵驱动1069468/62488130、搜索作业1069500/62488805、审计1072060/62520103、时间门作业1073437/62535878均核对退出，实际服务全部终态，无后台继续实验。旧矩阵、原三例及累计失败记录均保留。最终汇总器曾误以为审计生成旧CASE_BINDING.json，未发生实验/数据修改；FINALIZATION_FAILURE_R1保留错误，新CASE_BINDING_R1据实际AUDIT/WITNESS_AUDIT封存。

有依据后继P11=N/prepared/component_endpoint_guard_v11：新证据显示现规则只保护“整阶段已通过”的端点，contact失败阶段原本合格的掌心/手可以被交换掉。yminus第一次接受将close掌心1.0279→11.9400mm、手9.3944→24.8020mrad，随后退化更大。新增独立端点分量保护辅助函数，在四工况共24个原决策回放中全部复现旧结论；它额外拒绝xplus/yminus各一次原接受更新，xminus成功路径三次更新均保留。这是原轨迹上的影子规则比较，拒绝后未来状态没有重新生成。

P11的component_acceptance_r1和component_compiler_r1为代码准备，PREPARATION_STATUS_R2明确：新QP求解0、新完整路径0、尚未接入新搜索适配器、没有新数值证书/矩阵准入。约束拟保护contact失败阶段中已合格的掌心/手，配合原P10软内部余量；原硬行和最终门不放宽。必须在当前V9合法收束后，再进行完整窗口线性约束数值对照、独立QP证书、完整非线性接受与路径审计，不可把回放或代码准备当新方法通过。

额外P=N/prepared/window_audit_20261006_r1准备了严格原截止时间内、仅核验已结束案例的审计入口r2；互斥/禁止新搜索两项负检查通过，实际没有用它启动服务，因为yminus已由原审计正常完成。该工具不是新工作窗口授权，也不能替代case搜索。

## 2026-10-06 18:12：完整续接方案已批准并一次性应用，yminus正在运行（最新 HANDOFF）

用户最新明确回复“批准”，对应P=N/prepared/fb2_continuation_20261006_r1/COMPLETE_PROPOSAL_R2.md及GEOMETRY_SCOPE_ADDENDUM_R1。真实回复、双提案哈希和批准范围保存在V9/evidence/RESOURCE_EXTENSION_R2/USER_APPROVAL.json；apply_fb2_continuation_extension_r2已完成，APPLIED及GEOMETRY_AUTHORITY_R1已生效，**无待用户批准的资源决定，不重复申请**。共同包24000服务秒/18GiB、全局48000秒/47GiB、静态调用84000次；body_high参考上限8088、全矩阵82588，原物理次数/步数、质量门和历史费用保持。

本轮18:25:04 +0800截止不变。批准到达时已18:09，不能把此次批准自动解释为另起五小时。1801项RESUME_EXECUTION_FREEZE_R1已通过，原方法ID67fffa720eb48d021502d0991c191bee2a3b94bbf7a3ead21d75719c5dbb21f4保持；nominal/xminus/xplus原三例均未重跑。唯一矩阵驱动 **1069468/62488130**，入口N/tools/run_template_matrix_r3.py，已从yminus启动。实际状态读V9/execution/STATE及O/STATE和服务；需要接管先请求退出、核对终态，禁止重复编排。

当前累计终态共同10512.802389565/24000秒、全局34212.487280897/48000秒，另有活动服务待结算。权威台账改为T/tools/refresh_effective_template_r3.py；不要再调用旧pending/r2刷新器。当前仍2通过/1非通过/8未运行，待yminus及独立审计完成再更新。原6次迭代、300秒累计单例、第三非通过退出不变；P10后继仅数值准备，必须等待当前方法合法关闭。FB2物理合格完整任务仍0，准备通过不等于实验通过。

## 2026-10-06 15:56：两个完整几何工况通过，对比视频已交付，续接整包决定待回复（最新 HANDOFF）

当前 **V9=N/whole_template_transfer_v9 为2通过/1非通过/8未运行**；nominal、xminus均15/15阶段及独立审计通过。xplus最终13/15，正常接触2处/停止3处违规，已按原累计单例上限收束并审计；不是通过。当前断点yminus之前的真实磁盘预留门，尚未第三非通过，不得关闭/重开V9或重跑前三例。V9驱动973273/61367382、旧G/C驱动及最后诊断驱动991485/61552722均已核对退出，实际服务全部终态，无后台正在实验。

当前原有效额度仍为共同16000服务秒/6GiB、全局40000秒/35GiB；共同累计 **10512.802389565秒**、全局 **34212.487280897秒**。磁盘快照6037143552/6442450944字节，余405307392字节，而下一完整案例预留1013138373字节，不能启动。下载累计6443180321字节；所有失败费用保持。1572个唯一历史绑定哈希复核一致，没有删除证据。精确快照O/RESOURCE_CHECKPOINT_R2.json；待决定期间台账用T/tools/refresh_template_pending_r1.py，不能用旧刷新器把pending置false。

**新的完整续接申请尚未收到回复、尚未应用。** P=N/prepared/fb2_continuation_20261006_r1，最新可读提案是P/COMPLETE_PROPOSAL_R2.md：新增8000服务秒/12GiB/2000静态策略调用，应用后包24000秒/18GiB、全局48000秒/47GiB、静态84000次；同时明确仅将body_high几何参考上限7450→8088帧、全11条件参考81950→82588帧。原控制周期、每阶段最多300额外帧、物理尝试/步数和质量门均不变，本轮仍截至18:25:04 +0800。补充是同一待答复申请，不能叠加第二份资源；旧“那就按照当前想法去执行”已用于之前8000秒/4GiB批准，绝不能再次复用。

几何长度补充纠正前一申请只写82588静态调用、却未显式列出原几何长度限额的遗漏。body_high仅有纯参考表示准备，没有实际完整机器人路径；已运行前三例全部7450帧，原实验科学身份与结论保持。P/GEOMETRY_SCOPE_ADDENDUM_R1.json绑定原实际批准提案与表示准备。真实新批准须同时绑定RESOURCE_PROPOSAL.json及该补充哈希，并明确geometry_clock_extension_approved、max_controls_per_case=8088、max_reference_states=82588。最新执行顺序 **apply_fb2_continuation_extension_r2 → freeze_template_resume_r2 → run_template_matrix_r3**；缺批准时两个实际入口均已验证拒绝，8项补充检查及隔离事务幂等检查通过。原r1申请/控制冻结均保留；新SCOPE_SUPPLEMENT_BINDING_R1另行封存。实际USER_APPROVAL/APPLIED/GEOMETRY_AUTHORITY均尚未创建。

新的22秒视频已完成并独立解码核验：[旧新几何对比](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/diagnostics/visual_review_20261006/video_r3/fb2_nominal_progress_comparison.mp4)、[对比关键帧](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/diagnostics/visual_review_20261006/video_r3/comparison_sheet.png)。到达目标最差掌心20.020→5.64768mm、下放20.680→5.87197mm。132帧/6fps/960×540，60次新增原生诊断渲染，累计212/220；服务16.657566933秒已入账。R/DELIVERY_AUDIT_R3及DELIVERY_BINDING_R3保留来源、解码、哈希和费用。严格为保存几何回放，物理/策略/训练新增0，不是FB2物理通过录像。

P10内部余量方法仅数值准备通过：1750软目标行增加0.5mm余量，1416048行QP原问题独立证书通过，close整25帧线性预测5.5577mm，全部硬约束/最终阈值保持；新完整机器人候选0，不能宣称新方法实验成功或替换当前V9。只能在当前方法合法关闭后按明确后继准入。V9原生/物理/数据接口也只是准备，全部11条件几何通过等原前置仍必须满足。FB2合格完整任务仍0，FB3未准入。

## 2026-10-06 15:00：首条完整几何通过已保留，整条模板迁移正在独立准入检查（最新 HANDOFF）

**15:34更新：新整包资源问题已通过异步工具提出，尚未收到新回复、尚未应用。提案P=N/prepared/fb2_continuation_20261006_r1/RESOURCE_PROPOSAL.md：新增8000服务秒/12GiB/2000静态策略调用，总上限包24000秒/18GiB、全局48000秒/47GiB、静态84000次，保留本轮18:25:04截止和原物理范围。旧+8000秒/+4GiB仍已生效，不能把本次等待或旧“按照当前想法执行”再次当成这次新额度批准。真实新回复必须绑定P/RESOURCE_PROPOSAL.json哈希，写V9/evidence/RESOURCE_EXTENSION_R2/USER_APPROVAL后，才运行apply_fb2_continuation_extension_r1。应用工具9项检查、同方法接续控制4项检查通过；批准后freeze_template_resume_r1→run_template_matrix_r3从yminus续跑，已有3例和method_id保持。当前仍是旧16000/6GiB额度。**

P10内部余量数值准备已实际通过：复现V9 xplus完整最终路径，仅1750软目标行增加0.5mm内部余量，全部硬矩阵/边界保持；1416048行QP原问题独立证书通过，close整25帧线性预测5.5577mm，所有阶段预测掌心低于6mm，手误差低于12mrad。新增机器人候选路径0、物理0、策略0；不能宣称新方法实验通过或替换V9。数值服务61.516126194秒计入后，共同10496.144822632、全局34195.829713964秒。整个包剩余逐字节重复内容最多35.5MB，仍不足下例预留；没有删除历史证据。

等待资源回复期间，正在原220次诊断渲染总额度内生成旧U与新G nominal的60次渲染对比（video_r3），严格为保存几何回放，不是物理视频。实际状态查看O/STATE，不要因矩阵驱动已退出而忽略这个短诊断服务；完成后检查R/RENDERS和N/execution/COUNTERS的累计诊断帧数。待新资源决定期间台账补充入口T/tools/refresh_template_pending_r1.py保持pending状态；r2旧刷新器会把恢复指针pending置false，真实问题状态以O/SCIENTIST_STATE.json为准。

**15:17更新：V9当前2通过/1非通过/8未运行，nominal和xminus完整15/15及独立审计通过；xplus 13/15、正常2处/停止3处违规，已按累计单例上限结束并审计。xplus多次全步虽然零接触违规，却使已合格close阶段达到6.001～6.003mm，故被原规则拒绝。尚未达第三非通过，不能关闭或重开V9。唯一驱动973273/61367382已退出，实际服务全部终态。当前断点yminus的磁盘预留：共同包5914050560/6442450944字节，完整案例预留1013138373字节不足；共同10434.628696438/16000服务秒，全局34134.313587770/40000秒，计算未耗尽。已封存副本去重保留全部路径/哈希，净回收170381312字节，正在检查整个包的剩余重复副本。P10=prepared/interior_endpoint_guard_v10仅准备内部余量数值诊断，未验证、未准入新矩阵，不能覆盖当前V9断点。**

**15:04更新：18项控制检查、原生完整nominal复现及独立审计均通过（7450参考状态、49673停止状态，全部数组逐字节一致）。V9已正式准入并启动：1565项执行冻结，方法ID 67fffa720eb48d021502d0991c191bee2a3b94bbf7a3ead21d75719c5dbb21f4，冻结SHA256 69da117f99371245ad816358b6d89b2075b05b315ccedf2496ed593b5b9d04a4。唯一矩阵驱动973273/启动标识61367382，入口run_template_matrix_r2；当前nominal搜索服务运行，禁止重复编排。最近终态共同9825.868934900、全局33525.553826231秒，包分配4972957696字节，另有活动服务待结算。下文15:00“尚未准入”为当时状态。**

G=N/gate_restoration_v8 已科学退出：**1通过、3非通过、7未运行**。nominal 15/15阶段及独立全路径/接触记忆审计通过，stop_target 5.64768mm、lower_place 5.87197mm；xminus、xplus、yminus仍失败。1458项 SCIENTIFIC_CLOSURE_BINDING_R1 保留G全部证据，原驱动946739/61092895及服务已核对终态；不得重开该矩阵或补跑未运行条件。

有依据后继V9=N/whole_template_transfer_v9：采用合格nominal的完整参考曲线作为所有原条件的起点，所有阶段允许调整，实际条件来源、目标、跟踪残差和接触重新计算。P9=N/prepared/whole_template_transfer_v9/representation_preflight_r5 与 INDEPENDENT_REFERENCE_RESULT_R1 已验证全部11条件参考硬约束和独立系数重建，新增完整机器人路径0。body_high原源样本比nominal多450帧，按源样本比例延长三个阶段至总8088状态；tracking_min需完整变量硬约束投影，830291行原问题独立证书通过，残差7.97e-10；其余条件参考未改。没有删除条件、截断源数据或继承其他条件的通过结论。

1534项V9/protocol/PREPARATION_FREEZE已封存，当前正运行run_template_preflight_job_r2的控制预检，随后做原生nominal重建审计；**尚未正式准入V9矩阵**。新协议是CANDIDATE_R4/MATRIX_EXECUTION_R4，编译器template_compiler_r3，原11条件、6迭代、300秒累计单例、第三非通过退出和最终质量门不变。准入后唯一入口run_template_matrix_r2。V9/execution/STATE、O=N/execution/witness_run_20261006_01/STATE和实际服务为准，接管先请求退出且核对终态。

准备失败费用全保留；r3/r4预检分别暴露body_high时间网格、tracking_min边界问题。准备过程中曾复用失败预检的协议路径，PREPARATION_VERSION_RECONCILIATION_R1保存原字节及哈希映射，后续改用独立版本文件；不能声称旧r3清单原路径仍匹配。生成脚本一次引号错误导致空作业目录template_representation_04，尚未启动服务，未删证据。旧实验冻结未改。

最近终态费用共同9744.643102145/16000秒、全局33444.327993477/40000秒，下载6443180321字节；6GiB包、35GiB全局和18:25:04 +0800窗口保持。当前台账入口T/tools/refresh_effective_template_r2.py，无待批准的新计算/磁盘额度。实际全部新参考共有82588状态，若全部几何通过，原82000次原生静态覆盖额度将差588次；该额度未扩大，须到后继做真实准入决定。新策略/物理/训练仍0，FB2合格完整任务0。普通修复和有证据后继继续自主执行。

## 2026-10-06：验收一致终端窗口方法已完成准入，完整矩阵正在运行（最新 HANDOFF）

**14:21更新：nominal新完整路径实际15/15阶段通过，独立几何和接触记忆审计均通过；到达目标5.64768mm、下放5.87197mm，正常及刹停接触违规均0。当前正接续xminus；单工况几何成功仍不等于FB2物理任务成功。**

当前新根 **G=N/gate_restoration_v8**，编译器gate_compiler_r3；1140项执行冻结已通过，方法ID 3cb7b01dc28f007f48fcb20b03668a7cd6a1e533ea7bc2425b8d2e2038bdc306。唯一矩阵驱动PID **946739 / 启动标识 61092895**，从nominal完整热启动开始；实时读G/execution/STATE.json与O=N/execution/witness_run_20261006_01/STATE.json，接管先请求G/execution/STOP_REQUESTED和O/STOP_REQUESTED并核实服务终态。当前不能重复编排。

C=contact_witness_v7保持0通过/3非通过/8未运行科学退出，SCIENTIFIC_CLOSURE_BINDING_R1封存全部旧证据；旧U行政替换记录也保持。新方法有实质变化：以原验收超标量替代已合格阶段更严的软坐标目标、覆盖375个终端样本、失败掌心寻求0.5mm内部余量、保留已合格末端半数距离余量且上限0.5mm。原接触硬保护、最终6mm/12mrad、原11条件15阶段、6迭代/300秒单例/第三非通过退出不变。三个已运行工况均从其C的完整已审计最终路径热启动，全部接受和拒绝试探的接触记忆都继承，没有阶段拼接。

P=N/prepared/gate_restoration_v8的原生准备复现旧数组和原硬约束，nominal新线性窗口预测5.65/5.80mm；这是预测，尚非新路径通过。xminus新1516540行QP证书通过，但预测下放仍61.17mm，风险明确。性能改进复用固定MuJoCo3.3.2原生包围球及稀疏行：xminus全部矩阵/边界/接触描述逐字节一致，查询6668048→606330，建模34.43→12.00秒；3项边界/无界检查通过。17项准入检查及独立原生热启动审计通过，复现7450参考/49670停止状态。旧输出目录错误和生成脚本错误及费用均保留，未以准备替代实验结论。

当前权威台账 **T/tools/refresh_effective_gate_r1.py**；最近终态共同8426.979256358/16000、全局32126.664147690/40000秒，另有活动服务待结算，下载6443180321字节、诊断渲染历史152不变。已批准6GiB包/35GiB全局及18:25:04 +0800窗口保持，无待用户授权。新物理/策略/训练仍0，FB2合格完整任务0；全部11几何条件通过才准入后继。普通修复和有依据的后继继续自主执行。

## 2026-10-06：接触记忆矩阵已科学退出，验收目标不一致已获数值证据（最新 HANDOFF）

C=N/contact_witness_v7 已于13:50左右按原规则封存：**0通过、3非通过、8未运行**；nominal/xminus/xplus的全部保存路径、接受规则、QP证书和接触记忆均获独立审计，审计通过不是任务通过。nominal达到14/15阶段、接触/停止违规均0，下放掌心6.7227166mm仍高于6mm；xminus与xplus分别6/15、11/15，仍有明显违规并按原300秒累计单例限额收束。主驱动921663/60822482已退出，实际实验服务全部终态；不得重开C或补跑其8个未运行条件。

原新增资源批准已生效且不重复申请：共同包16000服务秒/6GiB，全局40000秒/35GiB，窗口截至18:25:04 +0800。最近终态共同8076.644678239秒、全局31776.329569570秒，包分配磁盘2958995456字节，下载6443180321字节；旧失败费用不清零。权威台账仍T/tools/refresh_effective_witness_r1.py，后续活动以实时STATE与服务为准。无新策略/物理/渲染/训练；FB2合格完整任务仍0。

两个保存QP对照均有独立证书且新路径0：额外接触间距不是冻结下限主因，去掉它仅将下放末帧线性预测6.72→6.58mm；原软目标被已合格release阶段的更严坐标目标主导。改为原验收超标量和欧氏范数支持平面后，最大软松弛趋零，但真实线性预测范数仍6.12mm，尚未通过。后继准备P=N/prepared/gate_restoration_v8/PLAN.json：完整25帧终端窗口、原验收一致目标、失败末端内部余量与已合格末端距离保护；新矩阵尚未准入。旧C原字节和科学分母保持，继续有依据的准备与原累计预算内验证。

第一诊断的120秒计划因监督器路径替换遗漏实际仍为原300秒子进程上限，真实耗时4.7215秒；偏差写入CONTROL_RECONCILIATION并保留旧绑定。第二诊断已实际验证120秒上限，耗时4.7709秒。不能声称第一诊断也已强制120秒。普通修复自主执行，无待用户决定。

## 2026-10-06：新增资源已明确批准，接触记忆新方法完整矩阵已启动（最新 HANDOFF）

用户已回复“那就按照当前想法去执行”，对应上一条明确的+8000服务秒/+4GiB整包申请及新算法方案；**批准已一次性应用，无待用户决定，不再重复询问同一额度。** 真实回复和提案哈希在U=local_spline_v6/evidence/USER_APPROVAL.json，AUTHORIZATION_APPLIED记载事务；包总上限16000服务秒/6GiB、全局40000服务秒/35GiB，旧费用不清零。旧五小时PLAN原字节保留；新窗口O=N/execution/witness_run_20261006_01，截止2026-10-06 18:25:04 +0800。

旧U依据已批准的方法改变行政替换收束，**1非通过/10未运行，不是3非通过科学退出**。U/ADMINISTRATIVE_SUPERSESSION.json与677项PARTIAL_EVIDENCE_BINDING保留旧nominal及全部原证据；不要续旧xminus或重跑旧nominal。新当前根 **C=N/contact_witness_v7**；新787文件MATRIX_EXECUTION_FREEZE、witness_compiler_r4及witness_trust_r1正式准入完整几何搜索。nominal从U最后一条完整已审计路径热启动，保持原仿射表示，预置215个已核验历史停止位置；没有阶段拼接。其他原11条件、原6迭代/300秒单例/第三非通过退出、原物理/数据门保持。

14项准入正负检查通过；原生r2预检逐数组复现7450参考状态/49142停止状态，新增独立接触记忆审计通过。原生r1曾因通配导入覆盖根路径失败，3.058625072服务秒已保留；修复版本r2通过，未重写旧冻结。新编译器保存每条接受/拒绝路径的接触位置和累计记忆；独立审计重新计算这些位置，并验证进入后续子问题。

当前主矩阵驱动PID **921663 / 启动标识 60822482**，真实进度读C/execution/STATE.json、O/STATE.json和实际services/fbts_witness_*，不要重复编排。接管先写C/execution/STOP_REQUESTED与O/STOP_REQUESTED，等待当前服务终态再操作。首个nominal搜索已运行，初始13/15阶段；未有新几何通过或FB2完成结论。旧8000/32000及“等待批准”记录只作历史。

当前权威台账入口 **T/tools/refresh_effective_witness_r1.py**，保留原服务/下载/动作总账并指向新方法；原台账可作为内部依赖，不用旧入口覆盖当前指针。最近已终态累计共同7066.591838167/16000，全局30766.276729498/40000秒，另有正在运行的服务待结算；下载6443180321字节，诊断渲染累计152。几何结果必须逐案例独立审计；全部11条件通过才可准入原生与物理后继。FB2合格完整任务仍0，FB3未准入。普通修复、证据核验与有依据后继持续自主推进。

## 2026-10-06：接触记忆与步幅更新新方案已准备，数值对照有改善但尚未路径验证（最新 HANDOFF）

2026-10-06 13:11 +0800响应用户“有没有新的解决方案，尝试改变”：已在原额度内完成保存QP的步幅半径对照，并准备 **witness_compiler_r4 + witness_trust_r1**。新规则继承r3的全部试探接触记忆及停止终点延长；若本轮发现新的接触位置，先保持原半径让新约束进入下一轮，否则沿用v6的缩步规则。完整路径接受条件、原6次迭代/300秒单例/0.25半径上限均不变。6项工程回归通过，覆盖拒绝路径不被误接受、新约束进入下一模型、数值证书失败退出及迭代上限；测试环境曾漏time引用，失败源码与记录已保留，修复后通过。此处是工程准备，未准入新矩阵。

同一v7保存QP保持接触/端点约束不变，仅将半径0.01125→0.045→0.25，两个失败阶段的**末帧线性预测**掌心误差19.2575→13.5266→6.8320mm；原解复核及两次新求解均获954294行独立原问题证书。6.8320mm仍高于6mm，且不是25帧稳定窗口或非线性路径结果；新候选路径/几何搜索/物理/策略/渲染/训练均0。不能宣称v7已解决FB2。最新[准备结果](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/contact_witness_v7/PREPARATION_RESULT_R2.json)、PREPARATION_BINDING_R2保留55文件绑定；旧PREPARATION_RESULT/BINDING保持原字节。后续执行不能错用旧r3指针作为最新已准备编译器。

本次数值服务10.591045765秒已累计；共同fbts_* **7036.814980801/8000秒**，余963.185019199，全局 **30736.499872133/32000秒**；账本快照包磁盘余79036416字节（约75.4MiB）。下载不变，累计诊断渲染仍152。trust_probe_r1/STATE中的PID及启动标识已核对退出，实际无活动服务；旧U的589绑定保持，仍1非通过/10未运行，xminus资源断点未改、nominal未重跑。额外8000服务秒/4GiB整包方案仍未应用，不能把本轮要求新方案当作资源批准。

后续顺序见N/prepared/contact_witness_v7/witness_trust_preparation_r1/NEXT_VALIDATION_PLAN_R1.json：先合法完成或明确记录当前U的方法替换（不得把10未运行改成失败或追认3非通过科学退出），再为新方法绑定完整初始化、所有试探接触记录、独立全路径审计和预算。完整nominal是下一新方法验证单位，原11条件及第三非通过退出保持；任何后继物理准入仍须全部前置通过。旧五小时窗口已结束，恢复实验需新建版本化窗口，不改旧PLAN。权威费用刷新入口仍为T/tools/refresh_effective_local_r3.py。

## 2026-10-06：人工诊断视频已交付，实验断点和资源门保持（最新 HANDOFF）

2026-10-06 12:00 +0800应用户“为何卡住、提供人工核验视频”请求，已从封存的nominal路径生成[27秒诊断视频](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/diagnostics/visual_review_20261006/video_r2/fb2_nominal_diagnostic.mp4)与[关键帧拼图](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/diagnostics/visual_review_20261006/video_r2/contact_sheet.png)。**这是保存几何姿态及原离散停止预测的回放，不是物理执行录像，也不是训练数据或FB2通过证据。** 12秒起为stop_target，16秒起为lower_place，20秒起为release刹停对比；绿圈是6mm目标容差，橙点是掌心，红线是误差。两失败阶段的最差掌心误差为20.02/20.68mm，不代表两只手都误差20mm。原第6次被拒全步在参考时刻113.46秒、停止步21，左拇指/方块预测穿透5.174806mm，超过原5mm门；保留四分之一步没有此违规。

本次含两次预览和最终视频累计50.974774567服务秒、152次原生诊断渲染；新候选路径/物理步/策略调用/训练均0。诊断渲染单列于COUNTERS，不能用任务范围render_frames=0声称本次未渲染。当前共同fbts_* **7026.223935037/8000秒**，全局 **30725.908826368/32000秒**；账本快照包磁盘余79835136字节（约76.1MiB），下载6443180321字节不变。596项输入绑定复核一致，视频161帧/6fps/960×540、解码及哈希检查通过。驱动887408/60249603已退出，实际服务全部终态，无后台。原证据及失败费用保持，未应用额外8000秒/4GiB。

实验仍从U=local_spline_v6的xminus接续，1非通过/10未运行，未达到科学退出；本次没有重跑、重开或切换矩阵。v7约束修复仍只有准备及历史预检，尚未新候选搜索/完整任务验证；FB2合格完整任务仍0。详细来源、视频时轴、费用与PID终态在N/diagnostics/visual_review_20261006/DELIVERY_AUDIT.json、video_r2/RESULT.json及TIMELINE.json。当前权威账本入口继续为T/tools/refresh_effective_local_r3.py；恢复实验仍需按下方资源断点处理，并建立新的工作窗口，保留旧PLAN原字节。

## 2026-10-06：自主长跑已推进约4小时33分，nominal已审计，资源断点保留（最新 HANDOFF）

2026-10-06 06:35 +0800终态核对。本轮自02:02连续推进至此，原五小时窗口截止07:02。普通修复、预检和短实验包结束没有触发逐包确认；目前形成真实资源检查点，额外8000服务秒、4GiB磁盘的完整决定仍待用户回复，未应用新额度。**没有后台继续运行；FB2仍未完成，合格完整任务0，FB3未准入。** 旧后台676211/56393450、V驱动722694/57347485、U驱动758089/58010681和最后预检777042/58293278均已核对不存活，实际服务全部回收。

**当前实验接续仍是U=N/local_spline_v6的xminus。** nominal已经完成固定6次迭代、15条完整保存路径；独立审计复现111750参考状态及736460停止状态。当前接触违规42→0、停止违规1034→0，通过13/15阶段；stop_target/lower_place掌心仍20.02/20.68mm，未达6mm，故实验未通过。矩阵现在1非通过、10未运行，尚未达到3非通过退出；不要关闭/重开矩阵、重跑nominal或改写589文件MATRIX_RESUMABLE_FREEZE和本案例CASE_BINDING。V的3非通过/8未运行关闭结论保持。

实际累计fbts_* **6975.249160470/8000秒**，余1024.750839530；全局 **30674.934051801/32000秒**。本次快照包磁盘余83611648字节（约79.7MiB），xminus完整案例预留810510699字节，不能启动。下载6443180321/8589934592字节；保留全部历史费用及失败。当前权威刷新入口 **T/tools/refresh_effective_local_r3.py**，按实际旧/新资源额度刷新服务并从不可变历史基线核对持久动作额度；23项日志检查、10项总账集成检查通过，实际动作日志尚未创建，本轮新策略/物理/渲染/训练均0。冻结中的几何驱动内部r2刷新不计动作，几何终态后再用r3统一核对。

真实诊断发现：8条拒绝路径包含release停止接触违规，但U只收集已接受路径的停止位置；6次子问题都缺release停止行。后继仅准备在 **N/prepared/contact_witness_v7**：保留所有已审计试探的接触位置，并对超出当前停止时长的位置使用原停止终点的静止延长。修复一个漏导入错误后，3条原路径逐数组重建一致；215个历史停止位置全部形成约束，release停止行74→3236，原第6次全步/半步违规方向被提前拒绝。原已接受的四分之一步也被更保守的约束拒绝，收敛改善仍未知。新954294行/2385变量QP独立证书通过（原始可行残差6.6321e-11）；**新候选路径0、新方法搜索0、无实验准入**。最新代码witness_compiler_r3，准备结果与绑定见PREPARATION_RESULT/PREPARATION_BINDING；不能用准备结果替换当前U或清零案例预算。

后继接口准备已接入稳定科学身份：原生最新NATIVE_PREPARED_R4_FREEZE（700绑定），freeze_local_native_r4/run_local_native_matrix_r4及r4作业接入动作总账；三个实际入口均因当前完整几何绑定缺失而正确拒绝。渲染/导出r2读取当前U完整路径来源。上述均只是准备，原生覆盖没有运行；前瞻任务范围组件、因果边界、真实物理控制器/独立物理审计及数据交付仍待完成。连续身高与旧逐帧静态假设最多差45.89mm，不能把旧反事实覆盖当物理证书。

资源决定到达后的顺序：记录真实用户回复及方案哈希→apply_local_resource_extension_r1一次→refresh_effective_local_r3→核验nominal CASE_BINDING→**直接run_local_matrix_r2从xminus续跑**。不要执行旧freeze_local_execution_r1；科学身份和累计费用不变。若恢复时已超过07:02，保留O/PLAN原字节，先版本化建立新的工作窗口再续，不改旧冻结。当前U未完成时不得静默切到准备中的v7；任何非通过均拒绝物理准入。

精确机器状态：N/execution/longrun_20261006_02/RESOURCE_CHECKPOINT_20261006.json、SCIENTIST_STATE.json、U/execution/STATE.json。此次末次复核806个唯一绑定文件保持，所有旧账本与失败证据保留。


## 2026-10-06：新局部曲线 nominal 已实际执行并独立审计，接续 xminus（最新 HANDOFF）

2026-10-06 05:55 +0800核对：去重释放的原额度容纳了一个完整案例，U=N/local_spline_v6 已在**原8000/32000秒及2/31GiB上限内**实际执行 nominal；没有应用增额。新驱动758089/58010681已正常退出，实际服务全部回收，当前无后台。矩阵停在xminus之前的资源预留门：当前只有1非通过、10未运行，**尚未达到3非通过科学退出，不能封闭/重开或重跑nominal**。

nominal完成原固定6次迭代，15条完整保存路径、6次接受更新；111750参考状态和736460停止状态独立审计通过。最终正常接触违规42→0、停止违规1034→0，保住13/15阶段；stop_target和lower_place掌心端点误差仍20.02mm/20.68mm，未达6mm，因此几何未通过、FB2合格完整任务仍0。全部试探与费用保留；case/CASE_BINDING封存本案例，不代表整个矩阵关闭。

当前采用589文件MATRIX_RESUMABLE_FREEZE及matrix_admission_local_r2，固定科学身份不随明确资源增额变化，累计每案例300秒不重置。run_local_matrix_r2会先预留完整案例的证据空间和搜索/审计费用；xminus预留约810.5MB，现有余量不足。待用户明确回复的完整扩容仍为额外8000服务秒、4GiB磁盘，物理次数/质量门不变。**无需再冻结/重开新矩阵**；批准后一次性apply_local_resource_extension_r1、刷新台账、核验nominal CASE_BINDING，再直接续run_local_matrix_r2。

最新终态共同fbts_*6719.021226407/8000秒，余1280.978773593；全局30418.706117739/32000。下载累计6443180321/8589934592字节。当前台账入口T/tools/refresh_effective_local_r2.py按实际已应用额度选择旧/新刷新器，原费用不清零。精确磁盘、案例进程秒与资源申请状态读N/execution/longrun_20261006_02/SCIENTIST_STATE.json和U/execution/STATE.json。

原生/渲染/导出接口仅准备，未运行新策略/物理/渲染/训练；已知原生与交付旧准备入口仍需要接入本次稳定科学身份，不能直接当成后继已验证链路。所有11几何条件通过及原生覆盖后才允许前瞻任务范围组件。用户五小时窗口02:02—07:02保持，普通后继准备继续；旧V及H/J/K矩阵封存保持。

## 2026-10-06：局部样条矩阵准备已核验，完整资源决定仍待回复（最新 HANDOFF）

2026-10-06 05:25 +0800接续快照，用户五小时窗口02:02—07:02保持。无活动服务；所有旧后台和minimax矩阵均已结束且终态核实。V三非通过关闭、8未运行，FB2合格完整任务仍0；不重开旧矩阵。

U=N/local_spline_v6的新几何矩阵准备完成：575文件准备冻结、21项准入/事务检查通过；独立原路径审计3/3通过。**MATRIX_EXECUTION_FREEZE不存在，U新几何搜索0，未准入运行。** 申请额外8000服务秒和4GiB磁盘的完整方案仍待用户明确回复；未应用新额度。准备冻结不能冒充执行冻结，已实际验证缺USER_APPROVAL时拒绝生成执行冻结。

在等待决定期间继续完成后继接口：22350条反事实命令格式检查、15600条旧原生输入/六帧历史/目标独立审计误差0；持久额度日志17项与完整几何准入桥13项检查通过。连续身高控制保留原0.0004m/tick和导航增益，与原控制器逐项一致；源目标复核保留x±扰动反馈。但连续身高与旧逐帧设定假设最多差0.0458913m，必须经前瞻任务范围组件验证，不能将这些准备当物理成功。0新策略调用/物理/渲染/训练。

对逐字节相同且已封存的数组透明去重，释放275148800字节，2611历史绑定哈希保持，未删除历史路径或字节。当前终态共同fbts_*6347.727351646/8000秒，余1652.272648354；全局30047.412242977/32000；下载6443180321/8589934592字节。现行台账仍T/tools/refresh_feasibility_guard_r2.py，原上限保持。旧预算预检控制器已版本化run_longrun_job_r3以保留真实待资源决定标识。

最新状态与完整接口清单读N/execution/longrun_20261006_02/SCIENTIST_STATE.json。明确资源回复后才执行apply_local_resource_extension_r1→新台账refresh_local_spline_r1→freeze_local_execution_r1→run_local_matrix_r1，复核单一进程、启动标识、资源门、累计费用及截止窗口。所有11条件独立通过后才seal_local_geometry_r2及后续原生命令覆盖；原生、组件、完整物理和数据流程仍待接入验证。P/DOWNSTREAM_PREPARATION_R1_FREEZE只冻结准备证据，不授予这些阶段资格。

## 2026-10-06：五小时长跑接续，旧方法关闭，新局部曲线前置通过（最新 HANDOFF）

2026-10-06 04:56 +0800快照。长跑窗口仍为02:02—07:02；旧后台676211/56393450和minimax驱动722694/57347485均已终态核实，无活动实验服务。V=N/minimax_restoration_v5已按3非通过关闭：0通过/3非通过/8未运行，169文件封存保持。nominal通过阶段10→13但仍未整体合格；独立审计通过不能算任务通过。FB0/FB1完成，FB2合格完整任务仍0，FB3未准入。

后继U=N/local_spline_v6采用完整旧曲线作为精确锚、失败及相邻阶段的局部三次样条变形、固定未触及阶段及凸二次恢复目标；不是重开旧矩阵。P=N/prepared/local_refinement_v6的表示、QP、无损存储、原生零变形等价和独立审计均已通过。3原路径22350参考状态与164842停止状态审计通过，原数组/停止轨迹差0；新候选搜索0，物理/策略/渲染0。U执行控制与冻结仍在准备，代码准备不等于实验验证。

实际终态共同fbts_*6320.324569377/8000秒，剩1679.675430623；全局30020.009460708/32000秒；共享下载6443180321/8589934592字节。原2GiB包磁盘余量已不足完整后继矩阵。完整条件性资源方案P/RESOURCE_EXTENSION_PROPOSAL.json已提出：额外8000服务秒与4GiB磁盘，包上限16000秒/6GiB、全局40000秒/35GiB；用户尚未回复，**未应用新增额度，原上限继续生效**。普通准备继续，不能将沉默当授权，物理次数和科学门不变。

当前读N/execution/longrun_20261006_02/SCIENTIST_STATE.json、STATE、QUEUE及实际服务。现行台账入口仍T/tools/refresh_feasibility_guard_r2.py；新的refresh_local_spline_r1.py仅准备，必须有明确新增资源决定和完整应用凭据后才切换。接管先请求当前STATE对应后台退出并核对服务终态。所有失败成本/旧矩阵/来源隔离保持。

## 2026-10-06：五小时自主长跑进行中，minimax新矩阵已准入（最新 HANDOFF）

2026-10-06T03:55:50+08:00核对：用户要求约5小时自主长跑，窗口02:02—07:02 +0800。旧后台676211/56393450已正常结束并核对服务终态，未重复编排。当前唯一新矩阵驱动PID722694/启动标识57347485，读实时V/execution/STATE.json及N/execution/longrun_20261006_02/STATE.json；活动服务费用尚未进入终态账本。需接管时先写V/execution/STOP_REQUESTED（阶段边界退出），同时N/execution/longrun_20261006_02/STOP_REQUESTED，等待实际服务终态后再操作。

N原xplus LP经等价数值诊断仍未获得证书，原N矩阵没有启动，不能追认成功。已独立冻结实质不同后继V=N/minimax_restoration_v5：单阶段最大违约量恢复替代旧接触最优值窄界分层，保留每个已合格接触分量及通过阶段身份；最终原几何/停止/端点标准不变。新保存子问题1028519行全原单位证书及独立模型变换审计通过；实际原生957884行子问题证书通过，两个完整保存路径数组/元数据差0，保护规则正负例通过。第一次原生预检漏导入time的失败及费用保持，r2修复验证通过。

新编译/独立审计/串行驱动已冻结257绑定，准入正例及11负例通过；当前从nominal按原11条件15阶段运行，累计单例300秒、第三非通过退出保持。FB0/FB1完成；FB2合格完整任务仍0，物理、策略、渲染、训练未新增，预检通过不代表矩阵或FB2成功。旧H/J/K矩阵保持关闭。

截至本快照，终态fbts_*累计5197.180951347/8000，余2802.819048653秒（另有活动服务待结算）；全部实际失败成本保留。共享下载累计6443180321/8589934592字节，本长跑增加8681037字节，用于隔离的Clarabel/HiGHS/GLPK依赖及元数据。唯一当前账本入口已版本化为T/tools/refresh_feasibility_guard_r2.py，修复旧刷新器丢失新增下载计数的问题；不要使用旧入口覆盖。所有原CPU/内存/磁盘/累计服务预算和物理准入保持，无新增资源额度或待审批。

长跑方案与证据：N/execution/longrun_20261006_02/PLAN.json、SCIENTIST_STATE.json；新冻结V/protocol/MATRIX_EXECUTION_FREEZE.json。短包结束不结束长跑；矩阵达到科学退出后保留证据，继续有依据的后继准备，不重开旧矩阵。


## 2026-10-06：新会话已核验接续，新增静态矩阵接入准备（最新 HANDOFF）

2026-10-06 01:49:59 +0800实际核对：后台PID 676211、启动标识56393450匹配且心跳正常，仍persistent_wait_resource；无活动实验服务。保持唯一后台，未接管/重复编排；每120秒采样，准入截止13:15:17 +0800。最新I/O阻塞70>16，原资源门保持，无待审批。

新增N/tools/compile_case_v4_static_r1.py、audit_case_v4_static_r1.py和matrix_admission_r1.py准备稿，移除旧策略运行库导入接入并要求实际获证书的后端/源码身份绑定。17项标准库准入契约检查通过；两个入口在缺执行冻结时、重库导入前拒绝。准备冻结PREPARED_STATIC_MATRIX_R1_FREEZE不授予实验资格；原生等价性、真实xplus证书、矩阵驱动和执行冻结仍待完成，完整任务仍0。

原10份冻结清单及203唯一覆盖文件重算保持，792行账本字节不变。实际监督器重新累计fbts_*4373.140858677/8000、余3626.859141323；全局28072.825750008/32000。本轮新增实验0。证据N/execution/chat_resume_20261006_02；继续读实时STATE/QUEUE，后台完成两项预检后自主接续数值判断。旧矩阵、科学退出及唯一当前台账入口不变。

[本轮实现、验证边界与剩余步骤](EMBODIED_FULL_BODY_STATIC_INTEGRATION_20261006.md)。

## 2026-10-06：新对话接续总交接已整理（最新 HANDOFF）

用户准备换新对话，已重新核对实际状态并整理[完整接续说明](EMBODIED_NEW_CHAT_HANDOFF_20261006.md)，覆盖目标/阶段、已完成与未验证内容、活动后台、安全接管、代码缺口、下一实验顺序、预算、冻结证据及可复制续跑指令。核对时间2026-10-06 01:28:20 +0800，快照在N/evidence/NEW_CHAT_HANDOFF_20261006；新对话必须重新核对动态状态。

FB0/FB1完成，FB2完整任务0，FB3未准入；当前N=T/full_body_milestone/feasibility_guard_v4。后台PID 676211及启动标识已核实仍存活，状态persistent_wait_resource，每120秒采样，准入窗口至2026-10-06 13:15:17 +0800。当前无新实验服务。后台保持运行，不因换对话停止；不要重复启动第二套编排。

数值诊断/原生静态预检尚无结果；保护与等价简化代码已实现但真实xplus证书仍缺。compile_case_v4/audit_case_v4仍是准备稿，导入/后端接入和新矩阵驱动尚待完成，不可直接当成已验证流程运行。先读实时STATE、QUEUE、RECOVERY_POINTER，再按总交接接续；主动接管须先请求后台退出并核验服务终态。

预算快照：共同fbts_*已用4373.140858677/8000、余3626.859141323秒；全局28072.825750008/32000；792行账本保留。唯一当前台账T/tools/refresh_feasibility_guard.py，原资源门/科学退出/物理条件/历史证据保持，普通工程无需重复批准。

## 2026-10-06：后台资源接续已实际启动（最新 HANDOFF）

用户再次询问为何停止。原因含主机I/O持续阻塞，以及上轮600秒一次性监测结束后没有保留接续进程。本轮已修订并实际启动后台低频监测，当前PID 676211（必须同时核验STATE中的启动标识），每120秒采样，准入窗口截止2026-10-06 13:15:17 +0800。此时状态persistent_wait_resource，后台在运行，实验未启动；下方“无后台进程”为历史。

资源门通过后自动串行运行保存LP缩放诊断与新版静态等价性/保护预检，沿用原监督器、服务台账和8000/32000预算。自动化范围仅到这两项预检及结果落盘；工程失败不会自动重跑，后续数值判断仍需读取证据。控制决策9项检查和独立后台进程核验通过；没有声称实验通过或完整任务成功。

当前入口N/execution/persistent_resume_20261006_01/STATE、QUEUE、RECOVERY_POINTER；后台持有PERSISTENT_RESUME.lock。后续会话先读状态与PID启动标识，避免重复编排；主动接管前用STOP_REQUESTED请求退出并核验服务终态。N为T/full_body_milestone/feasibility_guard_v4，台账仍T/tools/refresh_feasibility_guard.py。

部署时792条旧账本保持，新增实验服务0；全部fbts_*累计4373.140858677/8000、剩3626.859141323，共享28072.825750008/32000。控制等待墙钟和CPU另存STATE，实际实验费用仍完整累计。FB0/FB1完成，FB2完整任务0，FB3未准入；旧矩阵与科学退出保持，无待用户审批。详见[后台接续范围与证据](EMBODIED_FULL_BODY_BACKGROUND_RESUME_20261006.md)。

## 2026-10-06：断点接续已执行，600秒自动等待仍未获资源准入（最新 HANDOFF）

用户要求沿断点继续后，N轻量接续监测实际运行600.525秒，21次资源采样均未通过，I/O阻塞进程24–36超过原门16，内核I/O压力约90%。未启动新实验服务，当前无活动服务、无后台恢复进程、无待审批；真实外部阻塞保持。

已新增并冻结“旧完整路径/审计逐项等价性预检”和独立完整原约束LP证书审计，语法与新源哈希核验通过，运行测试尚未执行。FB0/FB1完成，FB2完整任务0，FB3未准入；旧矩阵不重开。

本轮新增实验服务秒0，接续前792行账本不变；全部fbts_*累计4373.140858677/8000、剩3626.859141323，共享28072.825750008/32000。600.525秒轻量编排墙钟单独记载；所有既有预算、失败费用和科学退出继续保留。

恢复读N/execution/QUEUE、RECOVERY_POINTER、CHECKPOINT及N/execution/recovery_watch_20261006_01/RESULT。健康门通过后先保存LP缩放诊断，再新版静态等价性预检，原行证书及独立审计通过才进新矩阵；无需重复批准。详见[本次接续证据](EMBODIED_FULL_BODY_RESUME_20261006.md)。

## 2026-10-06：意外中断已核实，恢复遇主机I/O资源门（最新 HANDOFF）

当前N=`T/full_body_milestone/feasibility_guard_v4`，无活动服务、无后台恢复进程、无待用户审批。上轮原生预检导入PyTorch超180秒后被回收，下一诊断工具调用又遇自动审批检查超时而未启动。本轮恢复服务已实际尝试，但主机I/O阻塞进程24–25超过原准入上限16，诊断代码未执行；后续复查仍24。普通执行工具现已可用，当前真实外部阻塞为主机资源门。

接触保护/等价LP简化代码已落地；真实保存LP仍缺数值证书，新矩阵未启动。静态适配器已去除不需要的策略运行库导入并完成语法、封存输入和事前冻结核验，原生运行验证尚未执行。FB0/FB1完成，FB2完整任务0，FB3未准入；0新物理/ONNX/训练/下载，旧矩阵不重开。

N累计7服务536.507766392秒；全部fbts_*累计4373.140858677/8000、剩3626.859141323，共享28072.825750008/32000。新增资源0，785原账本行保持；所有历史失败费用、质量门、物理额度及退出不变。

当前入口N/execution/QUEUE、RECOVERY_POINTER、CHECKPOINT；台账T/tools/refresh_feasibility_guard.py。主机健康门通过后从保存LP缩放诊断和新版静态原生预检接续，不等待同一授权的再次确认。详见[中断原因、工程进展与恢复条件](EMBODIED_FULL_BODY_INTERRUPTION_20261006.md)。

## 2026-10-05：接触保护与等价约束简化已授权实现（最新 HANDOFF）

用户明确“那就按照当前想法去实现”。新根N=`T/full_body_milestone/feasibility_guard_v4`，落实接触/已通过阶段保护、可证明等价的LP简化和完整路径可行性优先更新，再按原11条件15阶段与3非通过退出执行新冻结方法。旧K/L方法与证据封存不变，不重开旧矩阵。FB2完整任务0，物理未准入。

新增资源0，全部H/J/K/L/N的fbts_*共同扣原8000与共享32000，接续前包余4163.366907715秒。完整条件性路线估算4100秒，含数值/矩阵/审计、原生覆盖、新任务范围组件/完整物理任务、数据和失败分支，估算不增加授权。所有原物理次数、磁盘、CPU/内存、累计单例时间及科学退出保持。

当前恢复读N/execution/QUEUE、RECOVERY_POINTER、CHECKPOINT及services/fbts_guard_*；唯一当前台账入口T/tools/refresh_feasibility_guard.py。普通工程自主衔接，不因短包结束等待回复。


## 2026-10-05：保存LP数值修复1/2通过，完整任务仍未打通（最新 HANDOFF）

L=`T/full_body_milestone/saved_lp_equilibration_v1`完成固定等价缩放检查。xminus保存LP通过全部原约束及修正后原单位对偶证书，独立复核通过；xplus在60秒求解限仍超时。新完整任务0，新机器人路径/物理/ONNX/渲染/训练/下载均0。K三非通过固定方法与667文件封存不变，不追认旧矩阵成功。

已纠正上轮封存后未接续前置工程的问题并实际执行本轮。当前无活动服务；数值修复仅1/2通过，接触保护仍未接入新规划器。下一断点为未解保存LP结构诊断和有依据的等价方案、再满足新方法事前冻结；不靠同参延时反复运行。普通工程自主授权保持，无新审批点。

本轮6服务158.775806582秒（1工程非零保留）；H/J/K/L累计3836.633092285/8000、剩4163.366907715，共享27536.317983616/32000。新增资源0，779原账本行不变，原质量门、物理次数和旧退出不变。恢复读L/RESULT、NEXT_TASK_ADMISSION、RECOVERY_POINTER和CHECKPOINT；当前账本入口T/tools/refresh_saved_lp_equilibration.py。

[停滞原因及本轮证据](EMBODIED_FULL_BODY_NUMERICAL_STATUS_20261005.md)。


## 2026-10-05：接续保存LP的等价缩放验证（最新 HANDOFF）

当前L=`T/full_body_milestone/saved_lp_equilibration_v1`，只在K保存的xminus/xplus任务LP上验证固定四轮正数二次幂缩放、完整原单位原始/对偶残差；每求解60秒、进程100秒，预计数值工程340服务秒，新增资源0。K固定方法与667文件封存保持，禁止重开其矩阵；0新机器人路径/物理/ONNX，FB2完整任务0。

原普通工程自主授权持续有效。本轮接续纠正封存后未自动衔接前置数值工作的执行问题。H/J/K/L全部fbts_*费用共同扣原8000、共享32000及原磁盘边界，不重新获得预算；起点包余4322.142714297秒。当前以L/execution/QUEUE及services/fbts_equil_*核对实际状态，账本入口T/tools/refresh_saved_lp_equilibration.py。旧K及更早刷新器不再作为当前入口。


## 2026-10-05：接触分层矩阵三非通过关闭，退化反例已复现（最新 HANDOFF）

K=`T/full_body_milestone/contact_hierarchical_v3`已按原退出条件关闭：11条件0通过/3非通过/8未运行。FB0/FB1完成，FB2完整任务0，FB3未准入。名义候选总分下降但接触恶化，通过阶段10→1；另外两条件任务LP未获数值证书。不能把评分下降或独立审计通过当作任务通过，不得重开旧矩阵。

52150保存状态条目与417040停止配置独立审计复现，包含重复初始化；去重4条路径/29800状态/258305停止配置，其中仅1条新几何试探。接触保护原型已拒绝保存反例；精确行筛选尚无全行证书，新机器人后继未执行。下一断点为保存LP数值验证及实质不同后继的事前冻结；普通工程自主授权保持，不是待用户回复。

本轮25服务1002.644031019秒（3工程非零保留）；H/J/K共3677.857285703/8000秒，剩4322.142714297；共享27377.542177034/32000秒。新增资源0，0新物理/ONNX/渲染/训练/下载。12份旧绑定、754条原账本行不变，无活动服务。

恢复入口K/CLOSED_RESULT、NEXT_TASK_ADMISSION、RECOVERY_POINTER和CHECKPOINT。唯一当前台账入口T/tools/refresh_contact_hierarchical_closed.py；旧矩阵及旧刷新器不再运行。所有历史成本、累计单例300秒和退出保持。下方旧执行中、PTY及待批准文字按历史解释。

[本轮完整证据与限制](EMBODIED_FULL_BODY_CONTACT_HIERARCHY_20261005.md)。

## 2026-10-05：接触分层规划后继已授权执行（最新 HANDOFF）

用户明确“那就按照计划去执行”。当前K=`T/full_body_milestone/contact_hierarchical_v3`，从保存数值问题的收敛核验，接续接触分层规划、完整路径实际改进验收与原11条件/15阶段；物理和数据仍按原门条件性衔接。J464文件封存保持，不重开旧矩阵。FB0/FB1完成，FB2完整任务0，FB3未准入。

新增资源0，全部H/J/K的fbts_*服务共同扣原8000、共享32000；接续前已用2675.213254684、剩5324.786745316服务秒。CPU8、12/16GiB、单服务900秒、共享31GiB及H/J/K共同2GiB保持。完整后继估算5300秒包含条件性物理/数据及失败分支，估算不是新授权；普通工程不逐包审批。

第一项保存问题线性子问题已在1008102原约束上取得全行原始/对偶残差通过，没有生成机器人新路径，也没有声称旧二次目标已优化。当前数值/编译预检工作继续，实际以K/execution/QUEUE、CHECKPOINT及services/fbts_contact_*为准。新账本入口T/tools/refresh_contact_hierarchical.py；旧J刷新器及关闭队列不再作为当前入口。所有原科学退出和历史成本保持。

## 2026-10-05：跨阶段联合矩阵三失败关闭，独立审计完成（最新 HANDOFF）

J=`T/full_body_milestone/task_space_chain_v2`固定方法已完成：原11条件0通过/3非通过/8未运行，14条迭代路径的104300保存状态与725115停止配置独立审计复现。审计通过不等于任务通过；FB0/FB1保持完成，FB2完整任务0，FB3未准入。禁止重开旧矩阵或拼接不同迭代阶段。

全行数值修复及一次导入故障已自主处理、历史结果和费用保留。共享边界确已调整，仍有手指/物体穿透、手/桌禁止接触及放置端点误差。QP未提供最优性证明；360秒协作式截止分别延迟约3.031/28.985/39.127秒，全部实际费用计账。新数值/非线性步验收原型通过合成例，机器人后继优化器未执行，不据此启动物理。

J共15服务1616.936473538秒（1工程非零）；H/J共44服务2675.213254684/8000秒，余5324.786745316；共享735服务26374.898146015/32000秒。新增资源0；有限失败分支228.859592700秒。0新物理/ONNX/渲染/训练/下载。11份旧绑定、5938文件与739原账本行不变，无活动服务。

当前入口J/CLOSED_RESULT、NEXT_TASK_ADMISSION、RECOVERY_POINTER和CHECKPOINT；账本只用T/tools/refresh_task_space_chain.py。后继为接触分层可行性恢复与完整路径实际改进验收，具体要求及合成原型在J/prepared；普通工程授权保持，已关闭方法和已消耗物理次数不重新获得资格。以下旧“运行中”、PTY与待批准文字按历史解释。

[本轮执行与后继](EMBODIED_FULL_BODY_CHAIN_20261005.md)。

## 2026-10-05：跨阶段联合规划已授权接续（最新 HANDOFF）

用户明确“那就按照计划继续执行”。新根J=`T/full_body_milestone/task_space_chain_v2`，从共享阶段边界原型补齐联合几何/停止优化和独立预检，再按原11条件15阶段、累计3失败退出及条件性动态/数据门连续推进。新科学方法与旧逐阶段固定方法分别记账，H839文件封存和全部失败保持，不重开旧矩阵。

本次新增资源0；原8000包已用1058.276781146秒、余6941.723218854；共享32000上限保持。H/J全部fbts_*服务共同扣原包，磁盘共同受2GiB新增范围和31GiB共享限制。6550是本次完整后继估算，不重新获得8000。普通工程修复及后继不逐包审批。当前物理仍未准入，FB2完整任务0、FB3未准入。

恢复先核对J/execution/QUEUE、CHECKPOINT及services/fbts_chain_*；新台账入口T/tools/refresh_task_space_chain.py。AUTHORIZATION记录本次原文和零新增资源，旧M/H授权与历史成本不变。以下旧未执行、停止、旧队列等为历史，不覆盖本节。


## 2026-09-30：任务空间固定方法关闭，跨阶段后继已准备（最新 HANDOFF）

FB0/FB1完成，FB2完整任务0、FB3未准入。H=`T/full_body_milestone/task_space_milestone_v1`。连接和原生表示数值故障已恢复；初版0通过/3数值未解/8未运行保持。接续名义、xminus、xplus分别通过10/8/9个阶段后在放置/搬运/目标停步失败，固定方法累计3失败关闭，另8条件未运行；不得改参或更名重开。

37700保存状态、193640完整停止配置独立审计复现，包含正负例与复用前缀，不是训练episode。三个来源任务端点各自通过，但从新进入姿态的连续路径未通过。跨阶段共享关节边界代数原型已验证15阶段/7450行/1372变量；0新几何搜索，后继具体方案已准备、未执行，估算6550秒且新增资源0。

本包29服务1058.276781146秒（2非零），剩6941.723218854/8000；共享720服务24757.961672477/32000。0新物理/ONNX/渲染/训练/下载，原动态凭据及Q8保持。10份旧绑定及5137唯一文件校验通过，710旧账本行未变，无活动服务。原授权只应用一次，不再叠加或重复询问同一额度。

当前入口H/CLOSED_RESULT、NEXT_TASK_ADMISSION、BINDING_VERIFIED与CHECKPOINT；台账入口T/tools/refresh_task_space_milestone_closed.py。旧执行队列32821/46911/69709已结束，不再重跑。原冻结方案的科学退出后仅作有限诊断和下一准入准备，已完成；后继见H/prepared/CROSS_PHASE_SUCCESSOR。最高full-body目标和普通工程自主执行规则继续有效。

[本轮完整证据与限制](EMBODIED_FULL_BODY_TASK_SPACE_20260930.md)。以下旧当前、待批准、费用与PTY均为历史。


## 2026-09-30：连接恢复，任务空间矩阵数值故障已定位（最新 HANDOFF）

工具登录问题已恢复，原+8000/累计32000授权继续有效，不再次应用。当前H=`T/full_body_milestone/task_space_milestone_v1`；新编译器联合28关节、原身体/物体路径单调进度和自由任务端点。基础导数及原生模型预检通过；末端原6毫米门保持。

H/geometry初版按3非通过返回关闭：0通过、3数值未解、8未运行，原结果不改写。三个首未解阶段均有独立硬约束可行见证；进入边界仅有7.4e-17至4.23e-13弧度越界噪声。H/boundary_canonicalization在保存断点上作≤1e-12弧度规范化，3/3局部窗口通过原几何/全停止门；不是完整任务资格。工程分类、旧结果哈希和费用见H/evidence/NUMERICAL_FAILURE_CLASSIFICATION.json。

初版6400保存状态与42098停止配置独立审计通过（H/geometry/AUDIT）；第一阶段400状态/4919停止配置的可行原始解恢复另存H/numerical_primal_recovery。接下来验证严格原生范围的参考输出，再复用已审计前缀和恢复窗口，接续未完成阶段。普通数值/接口修复不设置新的审批点，也不清除真实科学失败退出。FB2完整任务0，FB3未准入，0新物理/ONNX/渲染/训练/下载。

实际费用和服务状态以T/tools/refresh_task_space_milestone.py、H/CHECKPOINT、execution/QUEUE及services/fbts_*为准。最新全部活动原生任务需先核对；旧几何整矩阵队列76608已结束。下方旧待批准、旧额度与执行中描述均为历史。

## 2026-09-29：任务空间完整里程碑已批准，接续执行（最新 HANDOFF）

用户已明确批准前一完整方案：新增8000服务秒、累计24000→32000，已一次性应用。新根H=`T/full_body_milestone/task_space_milestone_v1`；授权见H/evidence/AUTHORIZATION及AUTHORIZATION_APPLIED，原M/RUN_PHASE、旧授权与已消耗物理凭据不变。不能再次叠加相同额度或重复询问同一整包。普通工程与条件性后继连续自主推进。

批准前共享691服务23699.684891331秒；新包自身≤8000秒，全球余额8300.315108669秒，CPU8/内存12与16GiB/单服务900秒/共享31GiB保持。先完成新任务空间编译器、原11条件15阶段完整参考及独立停止/来源审计、原生命令覆盖；全部门通过才可进入最多8个新任务范围组件和1次新完整任务，再按门进入RGB-D/导出/真实消费者。预算授权不代表当前物理已准入。

G已905文件封存，绑定315a3a3224c5f3bb25b8fe9c6093296f8d099d0e89bed3e2571ae96aa1af2ba4；旧20200状态及全部失败保留。FB0/FB1完成、FB2完整任务0、FB3未准入。恢复先读H/execution/QUEUE与实际services/fbts_*；当前账本入口T/tools/refresh_task_space_milestone.py。以下未批准、24000上限和旧PTY为历史，不覆盖本节。

## 2026-09-29：异常会话恢复，几何与停止范围已闭合（最新 HANDOFF）

已核对最后审计服务正常完成、MainPID0及环境清理；无活动服务，旧PTY8857已失效，未重跑实验。FB0/FB1保持完成，FB2完整任务0、FB3未准入。G=`T/full_body_milestone/geometry_feasibility`全部静态候选已关闭，20200保存参考配置独立审计通过，不计训练episode。

主要证据：原6毫米要求是阶段末端25稳定tick门，旧整段6毫米候选保持原失败；xplus放置局部原门与7300停止配置通过。新携带名义路径通过但2167停止配置违规；任务空间起身3条边通过，后续携带6边均失败，原close连接仍缺资格。巨型LP超时为unknown，原生伪可行解被完整残差检查拒绝。不能从这些局部结果启动物理。

39服务1096.677160597秒（5非零退出保留）；共享691服务23699.684891331/24000秒、余300.315108669；原+4500范围余280.485037311。G约109MiB/256MiB、共享31GiB约余3.482GiB。0新物理/ONNX/渲染/训练/下载，历史全身11动态/54003步及单臂145/92保持。9份旧绑定和671基线账本行不变。

唯一当前账本入口为`T/tools/refresh_geometry_feasibility_closed.py`；恢复读G/CLOSED_RESULT、NEXT_TASK_ADMISSION、CHECKPOINT和封存凭据，勿运行旧关闭队列。下一完整任务空间里程碑方案已准备：+8000、累计24000→32000，包含条件性任务范围组件/一次新完整任务、数据交付与有限失败处理；**尚未授权或应用**。现有预算未耗尽，但不足这一完整包；新物理还需全部事前准入。普通工程授权持续有效，内部服务/短包不是审批点。

[本轮证据与后继](EMBODIED_FULL_BODY_GEOMETRY_FEASIBILITY_20260929.md)。以下执行中、当前、PTY和预算均为历史，不覆盖本节。更新前五文档已原样存于G/evidence/RECOVERY_DOCS。


## 2026-09-29：速率可行初始化与身体进度联合规划（执行中 HANDOFF）

已接续 FB2 新根 G=`T/full_body_milestone/geometry_feasibility`。固定身体全维几何可行性候选3窗口均失败、已关闭；3600保存状态独立复现。携带硬约束反例定位到右肩原生限位端点与旧保守停止近似；新逐关节离散减速3000路径边界检查通过，不能追认旧停止结果。

当前新冻结 `G/body_phase` 联合28关节与原身体/物体路径的单调进度，原时限、速度/加速度、6毫米和接触门保持。先核对该目录各窗口RESULT与services/fbm_gf_body_*，执行队列为G/tools/run_body_regressions.py。新账本入口T/tools/refresh_geometry_feasibility.py；仍扣原24000及+4500，G全范围不超过1377.1621979083867秒，包含前面失败。旧V/O及物理尝试不重跑；0新物理/ONNX。普通后继自主衔接，不等待回复。


## 2026-09-29：停止反例与整段规划闭环（当前 HANDOFF）

FB0/FB1保持完成，FB2完整任务仍0、FB3未准入。W六候选888文件已封存；后继V停止参考路径1/11（3失败7未运行），但139737停止配置审计发现511起始参考会越过原生关节范围，因此停止资格失败。新范围辅助函数通过3000条路径检查，旧矩阵不重跑。

已自主衔接O整段规划：165原阶段中11个旧关节路径无法仅重定时满足0.35rad/s；固定11困难窗口的速率投影前三例几何失败、其余8未运行，2050配置审计通过。整段几何原型的保守内接盒误拒绝已修正；两个放置窗口因算法信赖域不足而受限，携带完整LP两种求解器均超时、可行性仍unknown。603变量样条受限族不可行不替代完整LP结论。全身未新增成功数据。

当前根O=`T/full_body_milestone/offline_reference_projection`，V同级`collision_stopping_reference`。先读O/CLOSED_RESULT、O/NEXT_TASK_ADMISSION与evidence/INTEGRITY；唯一最新台账入口T/tools/refresh_offline_projection.py。下一工程是满足速率的可行初始化、整段几何可行性与连续阶段边界，必要时联合身体进度；旧内接盒、关闭矩阵和物理尝试不重跑。普通工程不等回复，没有新物理ready包。

V/O合计24服务522.099553902秒；共享652服务22603.007730734/24000秒，余1396.992269266，原批准增量余1377.162197908；盘约余3.59GiB，无活动服务/PTY。0新物理/ONNX/训练/下载/渲染（此处仅指V/O）；历史全身11动态/54003步、Q8/8组件及单臂145/92保持。旧绑定逐项不变，预算未耗尽也未扩容。

[本轮报告](EMBODIED_FULL_BODY_OFFLINE_REFERENCE_20260929.md)。以下“当前”、费用、PTY和执行中说明均为历史，不覆盖本节。

## 2026-09-29：任务参考六候选关闭，后继为提前制动（当前 HANDOFF）

最新连续身体/参考候选名义15阶段通过，固定11条件中1通过/3失败/7未运行；六候选均按各自累计3失败关闭。57720参考状态、77900来源插值及104快照/208复算独立审计通过。腕部距离尚在3毫米规划余量外时已因速度/加速度失去可行性；另一个放置条件参考速度未降到0.08稳定门。完整任务仍0、FB3未准入，0新物理/ONNX，旧单次物理和8/8组件不重跑。

W=`T/full_body_milestone/reference_task_workspace`，机器终态W/WORKSPACE_RESULT.json；W/NEXT_TASK_ADMISSION.md明确碰撞停止距离与端点稳定后继。普通工程自主推进，不等回复；新物理未准入。42服务841.424130221秒，共享628服务22080.908176832/24000秒、余1919.091823168，原批准增量余1899.261751811；31GiB约余3.655GiB。当前无活动服务，账本入口T/tools/refresh_reference_workspace_closed.py。

[本轮完整报告](EMBODIED_FULL_BODY_REFERENCE_WORKSPACE_20260929.md)。旧F/C/N/M/批准执行/Q绑定及605之前服务行保持；源码/结果另行封存。以下“当前”、费用和执行中状态均为历史，不覆盖本节。

## 2026-09-29：连续身体推进与参考联合求解（当前 HANDOFF）

Q原8/8小幅组件及385文件绑定保持。W=`T/full_body_milestone/reference_task_workspace`已完成四个独立静态候选：v1 0通过/3失败/8未运行；braking_v2 1/3/7；coupled_timing_v3 0/3/8；body_admission_v4 0/3/8。每个均按累计3失败关闭，12个负例保留；原300额外tick、6毫米与接触门未放宽，0新物理/ONNX。

已实现原生限位制动与a/v反馈、带负余量恢复的碰撞约束、事务式身体推进/保持。四版共32016个参考状态独立审计通过；v3重定时来源77900行另有独立插值审计。保持身体能恢复局部可行，但离散停走仍超时，不能延长阶段补跑。

当前独立原型把连续身体推进比例与28个双臂/手参考纳入同一求解器。三个固定超时端点均存在正向进度（约1、0.784、0.422），含身体朝向坐标修正和恢复验证。局部正例不授予整路径或物理资格；下一固定11条件在W/coupled_progress_v5，工具tools/run_queue_v5.py。先核对实际RESULT、QUEUE、各case/ATTEMPT及services/fbm_rw_v5_*，不可覆盖旧矩阵或恢复已关闭物理尝试。

W全部版本共用1800服务秒/768MiB，计入原+4500及累计24000；没有新资源授权。当前账本入口T/tools/refresh_reference_workspace_v5.py，精确费用读CHECKPOINT。原FB0/FB1不重跑，FB2完整任务仍0、FB3未准入。普通工程自主推进不等回复，新的物理范围仍须独立事前完整准入。

以下为较早执行记录，旧“当前”和费用不覆盖实际账本。

## 2026-09-29：完整任务范围验证执行中（当前 HANDOFF）

Q固定8/8小幅组件结果保持。当前在`W=T/full_body_milestone/reference_task_workspace`推进0.35rad/s完整任务路径兼容性，0物理/0ONNX；11条件固定，原300额外tick与6毫米门保持。首候选3/3失败、后8未运行，1131保存状态已独立审计；原Q385文件绑定未变。诊断明确限位制动距离不足和一步QP目标反复换向；新`W/braking_v2`通过制动距离约束与按a/v推导增益修正，源码单独冻结，准备代数不变量及同分母静态矩阵。

W预算1800服务秒计入原累计24000及+4500，不新增资源；实际累计查T/evidence/LONG_RUN_CHECKPOINT和原始services/fbm_rw_*。原完整任务单次尝试和Q8动态均关闭，不重跑。当前账本入口`T/tools/refresh_reference_workspace_v2.py`；先核对W/braking_v2实际结果与QUEUE，普通修复和后继自主执行，不等用户回复。完整任务仍0，FB3未准入。

以下为前轮已封存交接，不覆盖本节执行状态。

## 当前：8/8参考过渡组件通过，任务工作范围尚未准入

新观测参考调节器已完成：固定8/8独立GroundOnly条件全部通过，40000真实积分、4000动态与16静态前向；双臂最大端点增量误差0.007101rad，腕部0.003864rad。全量保存审计的输入/目标/控制/原始力误差0，接触力最大重建差5.31e-11N，端点归约差4.16e-17rad。两次零物理预检失败、一次审计比较失败及一次需求计算错误均保留并自主修复，无物理重试。

已把速度/加速度及观测参考区间接入任务碰撞QP，旧启动保存状态回归和恢复通过。原11条件57650命令中57380条超出当前小幅组件参考范围，33个条件—阶段在0.1rad/s下沿用旧关节端点会超时。保持原300额外tick，推导下一候选需约0.304254rad/s以上的端点速度能力；0.35rad/s仅为待验证候选，尚无完整任务物理资格。下一项是覆盖真实任务范围与过渡的准入，见`Q/NEXT_TASK_ADMISSION.md`。

本轮18服务/203.244204873秒，4个非零退出费用保留；共享586服务/21239.484046611/24000秒，余2760.515953389秒，原批准增量另余2740.685882031秒；盘余约3.77GiB。无新渲染/训练/下载/GPU，无活动服务。full-body累计11动态/54003步、57672静态与5401动态前向；其中本轮8次是独立组件测试，原完整任务一次尝试仍关闭，合格完整任务仍0。单臂145/92保持。

当前根`Q=T/full_body_milestone/reference_tracking`，结果Q/RESULT；新账本入口`T/tools/refresh_reference_tracking.py`。用户已接受独立短时验证任务，来源与冻结在Q/evidence/DYNAMIC_SCOPE；未扩大累计资源。587条之前服务记录和旧F356/C546/N248/M98/批准执行1196绑定均保持；源码与新结果单独封存。普通工程与具体后继设计不等回复，旧物理消耗凭据和科学退出不重开。

恢复先读[Q/RESULT](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/RESULT.json)、[下一准入](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/NEXT_TASK_ADMISSION.md)、[本轮报告](EMBODIED_FULL_BODY_REFERENCE_GOVERNOR_20260928.md)、DYNAMIC_SCOPE和各trial/ATTEMPT。当前无活动PTY；原6099队列已结束，审计代码修订后保存数据审计通过，不重新执行物理队列。

只刷新账本：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_reference_tracking.py
```

以下旧无ready状态、余额和PTY对应当时范围；最新后继以Q/NEXT_TASK_ADMISSION为准。

## 前轮完整任务包：FB2物理参考域退出，后继因果准入证据不足

完整FB2里程碑已实际执行并科学闭合：原候选8/11、第二候选10/11，第三候选11/11几何通过；57650次真实原生前向及独立输入/目标重建通过。10个未进入恢复分支的第二候选轨迹哈希复用，第三候选只新增body_high路径5650状态；不将复用计为新增样本。

本包唯一物理尝试在0.04秒/20步因参考跟踪域退出，实际2次动态前向，独立输入/目标/控制/原始力/接触重建误差均0；无物理守卫或禁止接触失败。已定位第10步新参考使6个腕部残差越出旧经验包络，第20步原门才拒绝。新发令前检查能在第10步识别；57650命令过渡审计、区间约束与1002既有因果区间提取均完成。旧FB1参考变化不覆盖新候选，未放宽门或重试物理。

累计568服务、21036.239841738/24000秒，余2963.760158262秒；批准后55服务/1556.069913095秒（其中2个工程失败保留），含准备共58服务/1604.548574045秒。磁盘31GiB内约余3.95GiB，无新下载/训练/GPU，无活动服务；full-body累计3动态/14003步、57656静态与1401动态前向、18次准备预览渲染。合格完整full-body任务仍0，FB3未准入，旧单臂145/92保持。

当前后继是命令变化与因果跟踪证据，具体代码、已提取数据和缺口见`M/successor_v3/NEXT_TASK_ADMISSION.md`。当前包的一次物理尝试已消耗，不启动第二次，也不以静态通过启动成功数据导出。普通工程授权持续有效，不等待用户回复；本轮科学退出和费用都不清零。当前根`M=T/full_body_milestone`，结果根`A=M/successor_v3`，账本入口`T/tools/refresh_milestone_closed.py`。旧PTY与旧待批准文字均为历史。

先读[A/RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/successor_v3/RESULT.json)、[诊断与下一准入](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/successor_v3/NEXT_TASK_ADMISSION.md)、[执行报告](EMBODIED_FULL_BODY_MILESTONE_EXECUTION_20260928.md)以及`M/evidence/GLOBAL_PHYSICAL_ATTEMPT.json`。凭据已存在且对应20步，禁止恢复任何物理队列。`M/RESULT.json`和`M/prepared/*`仍是准备历史。当前无PTY或后台服务需要接管。

只刷新账本：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_milestone_closed.py
```

529历史账本行及F356/C546/N248/M98旧绑定已逐项保持。更新前文档[归档](history/embodied_milestone_execution_20260928_before/MANIFEST.json)。

以下为历史接续；旧执行中、等待批准、PTY与余额不代表当前状态。

## 执行中历史：successor_v3原生命令覆盖

完整里程碑授权持续有效：累计24000服务秒、本包新增4500、磁盘31GiB，用户要求后续不等待回复。原M候选8/11、第二候选successor 10/11均已独立审计并保留关闭。当前successor_v3已11/11几何通过，审计57650状态；10个未进入恢复分支的原轨迹哈希复用，body_high完整新路径5650状态。6毫米门、每阶段额外300tick、原11扰动均保持。

当前在successor_v3执行真实原生命令覆盖（PTY19752），已10/11通过，预计共57650前向；独立输入/目标重建、条件性一次物理及审计/RGB-D/官方消费者队列已具体绑定，尚未执行物理。全局唯一物理尝试凭据M/evidence/GLOBAL_PHYSICAL_ATTEMPT.json当前不存在；存在后绝不重复积分。新队列为M/tools/run_native_coverage_v3.py与run_physical_delivery_v3.py；账本用T/tools/refresh_milestone_active.py，原静态准备RESULT仅作历史。当前科学终态以successor_v3下实际文件为准，普通错误自主修复并保留费用。

下方为本轮早期执行记录，旧活动PTY和状态不覆盖本节。

## 批准后早期历史：完整里程碑开始执行

用户已明确“批准。后面都不需要等我回复”。完整FB2里程碑+4500服务秒已应用，累计19500→24000；31GiB/CPU8/内存12与16GiB及原科学门保持。M/evidence/AUTHORIZATION.json已绑定完整提案，不能重复应用或再询问同一授权；旧+600静态子包不执行。普通工程、失败诊断和阶段衔接持续自主推进。

已启动M/tools/run_milestone.py完整串行队列。先核对execution/QUEUE、各静态case和覆盖RESULT、trial尝试凭据及原始services/fbm_*；终态由实际结果决定。开始前共享513服务19480.169929秒，历史费用保持，本包最多新增4500服务秒。没有重新运行FB0/FB1或旧关闭物理配置。

`M=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone`。活动队列本会话PTY75702；若终端已结束，先读实际结果和服务日志，再恢复队列，勿直接重跑物理。以下是批准前历史状态，不覆盖本节。

## 批准前历史：完整FB2里程碑准备

已按用户持续执行要求，把FB2完整参考矩阵、原生命令覆盖、条件性一次物理、独立审计、全长双相机RGB-D、官方/真实消费者与有限失败闭合准备为一个里程碑队列。初始动作/恢复/旧触桌守卫及数据尾部预检通过，6RGB-D相机对/18渲染pass预览通过，45项队列/计数工程检查与26份源码编译通过；整矩阵、物理和完整消费者尚未执行，合格full-body任务仍0。详见[本轮结果](EMBODIED_FULL_BODY_MILESTONE_20260928.md)。

本轮3服务48.478660950秒，含一次导入超时且保留；共享513服务、19480.169928643/19500秒，余19.830071357秒，盘余约4.106GiB。0新物理/推理/训练/下载，无活动服务、主PID0、环境清理。旧F356/C546/N248绑定及529历史服务行不变，FB0/FB1不重跑、旧物理失败不重开、单臂145/92保持。

完整提案申请累计19500→24000（+4500服务秒），包括自动条件性后继与失败分支，磁盘31GiB/CPU8/内存12与16GiB保持；1203输入冻结。**尚未授权/应用**。旧+600静态提案保留为历史子包，不再单独申请、不叠加应用。当前准备已完成，仅完整实验包确需这一新累计资源决定；普通工程不再按小包等待“继续”。

运行根`M=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone`。恢复先读[M/RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/RESULT.json)、[具体完整提案](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/prepared/MILESTONE.md)、[唯一恢复入口](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/prepared/NEXT_TASK_ADMISSION.md)及实际services/fbm_*。原生矩阵/物理/数据尚未执行，不能把准备代码或静态预览当成新任务资格。

明确批准新+4500后，按入口应用一次；不要运行旧N的+600授权脚本。队列自动衔接，不因服务结束反复要求回复。失败或中断必须保留全部费用；物理trial已创建即不再启动第二次。只有重要新范围/真实资源限制才需要决定。

仅刷新账本：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_milestone_checkpoint.py
```

以下全文为历史交接，旧“当前”“下一项”和余额不覆盖上方。

## 历史执行补充：减少人为停点

用户指出每隔半小时到一小时仍需回复。已按既有持续执行要求纠偏，详见[执行方式修正](EMBODIED_CONTINUOUS_EXECUTION_CORRECTION_20260928.md)。下方600秒方案只覆盖静态子包，保留原件且仍未授权；当前优先自主补齐原生协调、条件性物理、审计/数据交付和有限失败后继的完整里程碑方案及总体估算，再提出必要的新资源决定。不能再等待“继续”来做普通准备，也不能把本次质疑当作新增预算。19500秒上限及68.308732秒余额、原科学退出保持。本补充覆盖下方旧“只等待600秒批准”的执行安排，不改写实验结果。


## 2026-09-28：阶段协调与局部站位恢复已验证，完整静态包待新计算额度（历史 HANDOFF）

已接续FB2后继：新增观测驱动阶段协调器、限幅与6秒恢复退出、快照恢复及原生43通道动作包适配。固定五类失败的首个失败端点×七候选共35局部诊断，4类可恢复、yminus网格失败关闭；另对齐原既定站位，原4/5通过，漏计FB1原生偏航的坐标域错误单独修复后，该例复核通过。五类局部恢复证据不改变旧整矩阵失败，不等于完整任务通过。详见[本轮结果](EMBODIED_FULL_BODY_PHASE_COORDINATOR_20260928.md)。

4500保存配置/41候选结果独立审计通过，误差最大8.84709e-17m；15项协调器检查、40个原生动作包、7类矩阵拒绝通过。旧F356/C546绑定及原524服务行保持。0新物理/策略推理/渲染/训练/下载，完整full-body任务仍0，单臂145/92保持。未重复FB0/FB1，没有ready物理包。

具体下一包已冻结928输入：原11条件、15阶段、每条件5200静态参考状态，含全部站位恢复与原误差重引入，最多57200；可恢复队列与独立审计已准备但尚未执行。静态通过仍缺原生协调器全部命令/真实任务守卫覆盖；不能直接物理。运行根 `T/full_body_phase_coordinator`，入口 `tools/run_geometry_queue.py`。

本轮5服务/62.629205秒；共享510服务、19431.691268/19500秒，余68.308732秒，盘余约4.109GiB。无活动服务、主PID0、环境清理。整包预留600秒，已提交[具体计算增量](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_phase_coordinator/prepared/COMPUTE_EXTENSION.md)：累计19500→20100（+600），31GiB/8CPU/12与16GiB不变，0物理/下载/训练。**尚未批准或应用**；请求源于真实累计额度，不能将“继续下一轮”当扩容，不重新问full-body方向。明确获批后按提案应用一次并续队列；已有qualification/AUTHORIZATION.json则直接恢复。原结果与费用保留。

当前账本刷新 `T/tools/refresh_phase_checkpoint.py`；精确终态 `T/full_body_phase_coordinator/CHECKPOINT.json`。本轮前五文档[已归档](history/embodied_phase_coordinator_20260928_before/MANIFEST.json)。

恢复先核对 `T/full_body_phase_coordinator/RESULT.json`、`CHECKPOINT.json`、`evidence/AUDIT.json`、`READY_INTERFACE_CHECK.json`、`prepared/COMPUTE_EXTENSION.md/.json` 及 `qualification/AUTHORIZATION.json` 是否存在。当前无授权凭据，不能启动完整矩阵；旧七候选和旧C失败均不能补跑。审批只针对新增600服务秒，不涉及方向、已完成阶段或物理资格。

仅刷新账本（不会运行矩阵）：

```bash
/data/wsj/anaconda3/envs/simgen/bin/python -I -B /data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/tools/refresh_phase_checkpoint.py
```

以下是前轮交接原文；“当前/下一步/没有扩容申请”与旧余额均为当时状态，不能覆盖上方。


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
