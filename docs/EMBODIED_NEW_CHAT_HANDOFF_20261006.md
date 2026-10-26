# Full-body项目：新对话接续交接（2026-10-06）

## 2026-10-08：交接至新对话，优先复盘仿真与控制方案（最新 HANDOFF）

完整复盘与证据索引：[FB2方案复盘交接](EMBODIED_FB2_REVIEW_HANDOFF_20261008.md)。本节优先于以下历史“最新”记录。

**用户因FB2进展过慢，要求整理记录并换新对话深层优化方案。本次仅交接；下一步优先复盘仿真、控制接口、专家来源与实验设计，不默认运行第五阻尼候选。** 最终full-body数据生产目标、FB0/FB1及原科学质量门保持。

**FB2仍未通过：本轮4个候选均失败并独立复核，合格抓握组件、完整任务和数据episode均0。** 后两候选到参考阶段156/158，但不能换算成完成百分比。最新手指碰桌前向下运动约1m/s是直接失败过程；尚未把最终原因在控制设计、接口/执行器适配、仿真参数与数值误差之间分离。模型一致性和失败可复现不等于仿真已正确适配专家轨迹。历史XML重建不等价已用精确MJB解决；原专家完整模型合同及同任务成功对照仍有缺口。以C4 `MOTION_DIAGNOSTICS_R2.json`为准，R1距离查询/部位标签问题均保留并纠正。

第五候选 `P/passive_damping_r1` 仅准备/保存状态预检通过，制动诊断有正有负，物理效果未验证；旧范围批准至多4候选，未收到第五批准。新对话先评估路线与最小因果验证的价值，再决定是否使用最后1组件试次。数据采集、独立审计、LeRobot导出和读取代码已准备并通过有限预检，实际成功分支全部未验证。本文档整理不构成新实验或资源授权。

2026-10-08重查：活动实验服务0，最后驱动2019851/73117445已退出，服务MainPID=0、inactive/dead；目标工具仍blocked，未完成。费用保持：共同21170.795928/24000、全局44870.480819/48000服务秒；静态91431/92000，动态1900计费/1748已知实际，物理13290计费/12960已知实际；组件7/8、完整0/1；诊断渲染220/220、成功数据渲染0。80服务共2502.469091秒，下载6723717619/8GiB。所有失败、预留差额和历史费用保留。恢复前重查实际服务、PID与台账；若有后台活进程，先请求退出再核验。

本轮O=`N/execution/fb2_goal_20261007_01`，P=`N/prepared/phase_feedback_20261007`。机器交接 `O/PLAN_REVIEW_HANDOFF_20261008_R1.json`；恢复指针已改为先方案复盘。账本入口仍为 `N/tools/refresh_fb2_goal_ledger_r3.py`，其旧自动状态字段不能覆盖新复盘意图。旧试验结果、批准和封存不改写。


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


核对时间：2026-10-06 01:28:20 +0800。这是一份交接快照；后台可能在新对话开始前继续推进，启动任何工作前必须重新核对STATE、PID启动标识、实际服务和预算。最高目标与持续执行规则以AGENT.md顶部为准。

## 后续补充：新会话已经接续（2026-10-06 01:49:59 +0800）

已重新核验唯一后台PID676211/启动标识56393450、实际服务及累计费用；仍因I/O资源门等待，未重复编排。新增静态编译/审计准备稿及17项标准库准入契约检查，尚无真实数值/原生预检通过，执行配置/矩阵驱动/执行冻结未完成。原稿及旧证据不改，下文仍保留01:28交接快照；最新实现与恢复说明见[EMBODIED_FULL_BODY_STATIC_INTEGRATION_20261006](EMBODIED_FULL_BODY_STATIC_INTEGRATION_20261006.md)，证据在N/execution/chat_resume_20261006_02。资源预算及科学退出不变，继续以实时STATE为准。

## 1. 当前结论

- 工作目录：`/data/wsj/main/scene`。方向已经固定为full-body人形全身任务与自有场景生成器的数据生产闭环。
- FB0完成：固定G1，29身体+14手关节、Decoupled WBC及全身动作/时钟/观测接口。
- FB1完成：原生组成控制准入通过。不得因为最早任务提到FB0就重做本体选型或已完成阶段。
- FB2进行中：**合格完整任务episode为0**，目前卡在连续路径的数值证书和几何/接触/停止条件。FB3自生成场景小批复验未准入；学习收益和批量生产能力尚未证明。
- 近期目标仍是一个本体、一类完整全身任务在原生和自生成场景的数据闭环；中期多任务/多场景及独立学习价值；最终可持续批量生产。不要回到单臂扩量，也不要用诊断状态条目、审计通过或视频帧数冒充合格episode。

原任务模板：走近支撑面→降高与双臂取物→起身→携物移动→放置→恢复稳定。目标、路线与台账分别见`EMBODIED_FULL_BODY_GOALS_20260928.md`、`EMBODIED_DATA_ROADMAP_20260926.md`、`EMBODIED_LONG_RUN_PROGRESS_20260926.md`。

## 2. 唯一当前工作根与后台状态

```text
D=/data/wsj/main/scene
T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1
M=T/full_body_milestone
N=M/feasibility_guard_v4
H=M/task_space_milestone_v1           已关闭
J=M/task_space_chain_v2              已关闭
K=M/contact_hierarchical_v3          已关闭
L=M/saved_lp_equilibration_v1        已封存数值结果
RUNTIME=T的同级目录/embodied_g1_runtime_20260926_v1
```

当前活动的是轻量后台控制进程，不是机器人实验：PID **676211**，启动标识`56393450`，状态`persistent_wait_resource`。进程身份已用/proc复核；无活动实验服务，`fbts_guard_auto_*`尚未产生。

实时入口：

- `N/execution/persistent_resume_20261006_01/STATE.json`：心跳、当前步骤、进程身份、已启动服务与完成项。
- `N/execution/persistent_resume_20261006_01/HEALTH.jsonl`：资源采样。
- `N/execution/QUEUE.json`、`N/RECOVERY_POINTER.json`：执行入口。
- `N/evidence/PERSISTENT_RESUME.stdout`、`.stderr`：后台日志。
- `T/services/fbts_guard_auto_*/supervisor.json`与`N/evidence/auto_*_PROCESS.json`：若后台已启动实验，以这里的终态和实际费用为准。

后台每120秒采样，接收新任务窗口截止 **2026-10-06 13:15:17 +0800**。原资源门通过后自动串行运行`diagnose_reduced_scale.py`和`preflight_protection_static_equivalence.py`，使用原launch/runtime/child监督器。实际自动服务名为`fbts_guard_auto_scale_XXXX`、`fbts_guard_auto_static_XXXX`；QUEUE里旧槽名是历史顺序提示，不要据此另启一套任务。

**自动化范围只到这两项预检和结果落盘。** 它不会自动解释数值诊断、修算法、跑完整矩阵、物理或训练。工程错误/超时/结果缺失会保存证据并结束，不能把后台退出自动视为成功。只有明确资源准入拒绝且子进程未启动才重新等资源。后续代理沿既有授权自主读取证据、修复和接续，不需要用户批准每个短包。

## 3. 新对话首先做什么

1. 先读AGENT.md顶部、`EMBODIED_LONG_RUN_HANDOFF_20260926.md`和本文件，再读实时STATE/QUEUE、实际systemd服务和最新费用。CHECKPOINT的状态可能晚于后台心跳，不能单独据其`no_active_services`推断“无后台”。
2. 核对STATE PID的`/proc/<pid>/stat`第22字段是否与`orchestrator_start_ticks`一致，并检查心跳时间、TERMINAL和日志。PID数字相同不等于仍是原进程；新对话到达时截止时间也可能已过。
3. 如果后台存活且正在等待/执行，不要重复启动第二套编排。它持有`N/execution/PERSISTENT_RESUME.lock`。只换对话不需要停止它。
4. 若确需主动接管，在当前后台执行目录创建`STOP_REQUESTED`，等待它记录终态，再核对当前实验服务已经结束/回收及监督器证据。停止请求不是强制回收已启动实验；不要在原实验仍运行时另启重计算。
5. 若进程已退出，先处理TERMINAL及不完整服务凭据；资源问题依原门等候，普通可修复工程错误自主修订。不得重复使用已消耗的服务槽，也不得重置累计费用/单例时间。
6. 后台若完成，目标状态是`resource_resume_preflights_ready_for_numerical_decision`。读取两个实际输出后继续第6节的实验路线。不要在内部短包结束时再次要求用户说“继续”。

当前真实主机阻塞为`blocked_processes_above_threshold`：最近核对约25–27个I/O阻塞进程，原门上限16；此前21次/600秒监测均为24–36，I/O压力指标约90%。不是预算耗尽，也没有新增授权需求。不要放宽原资源门或操作其他用户任务来强行继续。

## 4. 已完成、已失败与尚未验证

|范围|实际状态|下一对话应如何处理|
|---|---|---|
|H任务空间、J跨阶段联合、K接触分层固定方法|各自触发原3非通过退出，原11条件没有整体通过|保持关闭及完整分母，禁止改名/改参重开|
|K退化反例|名义候选总分5.753→3.480，但通过阶段10→1，接触明显恶化|保留为新保护规则的回归负例，不追认为成功|
|L保存LP等价缩放|xminus原行证书通过且独立复核；xplus限时未通过|L已封存，后继只版本化数值工程|
|N等价约束简化|合成例通过；xplus原1,028,428行中777,129行盒界冗余、18,693行重复被证明简化|仍必须检查完整原约束；简化比例不是求解成功|
|N真实xplus求解|IPM约40.665秒、dual simplex约16.797秒均返回HiGHS NotSet，未获完整证书|读诊断后有依据地修数值实现，不能直接准入矩阵|
|N接触/阶段保护规划器|代码已实现；按当前/最坏停止的每tick角色分量保护接触，保住原已通过阶段身份，完整路径可行性优先接受|原生预检尚未通过，不能说新机器人方法验证成功|
|N静态上下文|去除不需要的Torch/ONNX导入，复用MuJoCo原模型及封存43关节映射，语法/封存输入校验通过|新版原生路径等价性和保护预检未运行|
|独立原行证书审计|`original_certificate.py`、`audit_original_lp.py`已写好/冻结/语法检查|运行正负例和真实原行核验尚未执行|
|后台接续|9项控制决策单元检查及独立进程/心跳核验通过|保持实际实验资源门，记录编排CPU/墙钟；不等于科学验证|

先前预检有缺协议工程错误及180秒Torch导入超时；数值导入也遇到文件读取阻塞。所有失败凭据和费用保留。自动审批工具调用曾超时导致未启动，当前普通工具可用。600秒一次性监测已封存，现用12小时低频后台接续，不再启动旧一次性监测覆盖当前状态。

截至本交接核对，下面文件**均尚不存在**：`N/numerics/SCALE_DIAGNOSIS.json`、`N/preflight/RESULT.json`、`N/numerics_ds/AUDIT.json`、`N/geometry/RESULT.json`。新对话必须重新检查，后台可能已产生结果。

## 5. 代码、冻结与实现缺口

仓库实现：`D/sage/experiments/embodied_task_space_v4/`。

- `certified_reduction.py`、`certified_reduction_ds.py`：盒界/精确比例行简化、缩放与完整原单位证书。
- `protected_acceptance.py`、`protected_compiler.py`、`protected_compiler_ds.py`：保护接触与原已通过阶段，接受整条路径，不拼接不同迭代的好阶段。
- `static_context.py`：静态原生模型适配器，禁止物理推进、渲染、策略运行库。
- `original_certificate.py`：独立证书公式及原门。

N工具：`diagnose_reduced_scale.py`、`preflight_protection_static_equivalence.py`、`audit_original_lp.py`。数值诊断要核对系数/界的极值及简化前后见证残差；“极小系数归一化被过度放大”只是待验证假设，尚未确认，不能凭猜测改参重试。

**剩余工程缺口：** `compile_case_v4.py`与`audit_case_v4.py`只是准备稿，前者仍接旧导入链及DS审计路径；尚未接入经过原生等价性验证的静态上下文及最终数值后端。新矩阵驱动尚未编写。只有前置门通过后，版本化接入这些工具、补齐驱动和独立审计，再事前冻结执行。不能看到文件存在就直接开跑。

以下冻结及其覆盖文件不要原地修改：`N/protocol/FREEZE.json`（166文件）、`STATIC_CONTEXT_FREEZE.json`、`STATIC_EQUIVALENCE_FREEZE.json`、`ORIGINAL_CERTIFICATE_FREEZE.json`、`RUNTIME_REPAIR_FREEZE.json`、`RESOURCE_RESUME_FREEZE.json`、`PERSISTENT_RESUME_FREEZE.json`、`PERSISTENT_RESUME_R1_FREEZE.json`，以及`N/numerics/FREEZE.json`、`DS_REPAIR_FREEZE.json`。修订用新文件/新清单，保留旧输出。后台还会核验冻结源，活动期间修改覆盖文件将导致它报错。

## 6. 明确的下一步路线

1. 从真实资源/后台状态继续；取得保存LP缩放诊断与原生静态预检结果。两项独立前置，不能互相代替。
2. 数值修复有完整原单位原始/对偶证书才算通过；使用独立审计，原primal≤1e-8，scaled stationarity/dual sign/complementarity≤1e-6，目标与完整原问题保持。合成例或后端成功标志不足以准入。
3. 静态预检应重算两条旧完整路径并逐项复核数组/元数据，拒绝已知接触退化和“通过阶段计数相同但身份交换”，接受受保护的改善，并检查两个LP的零步可行见证及原通过阶段的250个稳定终端tick。
4. 两项前置及独立审计通过后完成上节工程接入，冻结并运行新N的原11条件/15阶段矩阵。保留未运行分母，累计3非通过退出，单例进程累计300秒（修复不清零）；每条试探完整原生审计，禁止跨试探拼阶段。
5. 矩阵与独立几何/停止审计通过后，才依原条件性路线进入原生覆盖、新任务范围组件、完整物理任务、采集/质检/标准导出与训练读取。原已关闭组件/任务不能重跑。
6. 若新方法达到真实科学退出，封存其证据，按已授权范围准备有实质区别的轨迹表示后继；不能将数值失败简单更名后重开。当前N矩阵尚未开始，不能提前当作已达到退出。

## 7. 预算、物理门与记账

|项目|本次核对值|
|---|---:|
|H/J/K/L/N共同fbts_*服务预算|8000秒|
|共同已用 / 剩余|4373.140858677 / 3626.859141323秒|
|共享全局已用 / 总额|28072.825750008 / 32000秒|
|共享全局剩余|3927.174249992秒|
|当前N已完成服务|7个，536.507766392秒|
|历史账本行|792；原N起点785行仍保留|
|本轮新增实验、物理、ONNX、渲染、训练、下载|0|

后台若启动服务，以上数字立即可能过期；重读服务supervisor和最新账本。唯一当前台账入口`T/tools/refresh_feasibility_guard.py`，账本`T/evidence/SERVICE_LEDGER.json`，检查点N/CHECKPOINT、M/CHECKPOINT、T/evidence/LONG_RUN_CHECKPOINT。活动实验结束并完成回收凭据后再刷新，禁止使用旧H/J/K/L刷新器覆盖当前状态。控制进程的等待墙钟/CPU单独记录，不隐去任何实际实验服务费用。

CPU最多8；MemoryHigh/Max=12/16GiB；单实验服务最多900秒；共享磁盘31GiB，H/J/K/L/N共同新增包2GiB。N的4100秒路线分配只是旧估算，不是新增授权，也不是普通工程重试次数上限。

条件性物理额度以`H/protocol/MILESTONE.json`和既有授权为准：静态策略forward最多82000；新任务范围8×40秒组件加1完整任务，共最多234500物理步、23450动态forward，全部必须满足前置门。旧M/RUN_PHASE是旧层级记录，不能单独拿它覆盖后继已批准范围；也不能把未使用额度当自动准入。当前N新增物理/策略调用0，项目历史已有FB1等实测。

## 8. 环境与证据保护

普通编排Python：`/data/wsj/anaconda3/envs/simgen/bin/python -I -B`；原生实验Python：`RUNTIME/prefix/bin/python -I -B`（由既有guard调用）。已有环境冻结，不要为导入慢盲重装或下载。普通sandbox曾反复报bubblewrap mountinfo错误；本会话使用require_escalated完成受控操作，自动检查超时时先核对实际是否执行，不能重复消耗已有槽。

仓库有大量既有dirty/untracked内容，当前实现/文档未提交；不要reset、clean或替用户提交。旧BINDING覆盖内容不可变；下列仅为本次读取的清单哈希，未在本次交接重算每份旧内容：

- `task_space_milestone_v1`：839文件，`82589b2d314d4d965dc628d079ece68a884a03f1c5436452c1f357e9d55d5c12`。
- `task_space_chain_v2`：464文件，`0b0f782dcb01e6c9c34315a2d59cca08e00caf5e62812c317db1f5ffaaea9f87`。
- `contact_hierarchical_v3`：667文件，`097bd49d2b5b0a94a73686b0bbc9985ae7988506b39206338c0eeeec0ec6e6cf`。
- `saved_lp_equilibration_v1`：138文件，`4798daad0f29093c74079b467b0c89c80ad394680e3c4a4c0d12d8c1631d7b0a`。

本交接快照与此前活动文档副本在`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/evidence/NEW_CHAT_HANDOFF_20261006`。后台保持运行，未因用户准备换对话而停止它。

## 9. 可直接发给新对话的指令

```text
工作目录：/data/wsj/main/scene。先读取AGENT.md顶部最新交接、docs/EMBODIED_LONG_RUN_HANDOFF_20260926.md和docs/EMBODIED_NEW_CHAT_HANDOFF_20261006.md，再核对实际后台STATE、PID启动标识、实验服务与累计预算。从FB2的feasibility_guard_v4断点继续；FB0/FB1已完成，full-body方向已确认，不回到单臂扩量、不重开旧矩阵。可能仍有后台资源监测运行，先核验，避免重复编排；需接管时先请求它退出并核对服务终态。普通工程自主推进，无需重复确认，保留所有历史证据、累计费用、资源门和科学退出。代码存在不等于验证通过，按交接中的数值证书、静态等价性预检和新矩阵准入顺序继续。
```
