# 全身参考调节器：独立过渡验证与任务约束（2026-09-28）

**固定8/8短时动态条件通过，参考约束已接入任务碰撞QP；完整FB2任务仍未通过。** 本轮补齐了原FB1没有腕部参考变化实测的缺口，但组件幅度与速度尚不能覆盖完整取放工作范围。

## 本轮范围与授权

用户“那就按照任务继续执行”接续已说明的参考生成器和独立短时动态验证任务，普通工程沿“后面都不需要等我回复”授权执行。新范围在GroundOnly测试腕部/双臂正负变化、降高和小幅步行，共8条件，每例10秒；没有物体取放。旧M的单次取放尝试没有重开，也没有重复FB1的20秒组成能力序列。固定最多8动态/40000步/4000动态前向、1300服务秒/512MiB，沿用原累计额度；首次硬性物理失败或累计3跟踪失败关闭，已初始化条件无重试。

## 实现与实际结果

`governor.py`按实际q/dq、上一参考及参考速度，限制0.1rad/s速度和0.5rad/s²加速度；将当前及一个控制周期线性速度外推的跟踪超前区间取交集。预览不改变控制状态，提交、历史快照恢复、连续tick校验和实际稳定观测计数均实现。线性外推是局部假设，不是未来动力学证明。

初始对称0.04rad目标在向内肩横摆越过原生边界，被零物理预检拒绝；原件保留。后继目标在原生范围内留0.001rad余量，向内肩横摆实际幅度0.009rad，其余对应通道名义0.04rad，不冒称对称覆盖。17项工程检查、4000算术tick、168私有静态姿态及16原生前向通过。

新组件的实验参考超前预算事前定义为原FB1关节残差绝对最大值加0.02rad、两侧对称；它不替换旧任务经验包络。硬性物理守卫复用原FB1：原生限位、禁止接触、穿透、姿态/高度、支撑力、速度和失去支撑时间。组件端点门是实际关节相对启动稳定窗的增量误差≤0.012rad，原完整任务的6mm末端门保持。

|固定条件|真实物理步|最大向外端点增量误差rad|结果|
|---|---:|---:|---|
|arms_negative_stand|5000|0.004437590|通过|
|arms_negative_walk|5000|0.006303183|通过|
|arms_positive_stand|5000|0.006059370|通过|
|arms_positive_walk|5000|0.007101099|通过|
|wrist_negative_lower|5000|0.003500167|通过|
|wrist_negative_stand|5000|0.003562113|通过|
|wrist_positive_lower|5000|0.003863764|通过|
|wrist_positive_stand|5000|0.003803660|通过|

8条件全部5000步完成；40000物理步和4000命令从保存数据独立重建。输入/目标/控制/原始力/接触最大重建误差：{'input': 0.0, 'target': 0.0, 'ctrl': 0.0, 'raw': 0.0, 'contact': 5.304912065184908e-11}；端点归约最大差4.163336342344337e-17rad。原生历史与调节器状态一致，初始化后无状态赋值或外力。所有条件的末窗双脚支撑比例1.0，身体稳定门通过；这8条是控制组件证据，新增成功任务episode为0。

## 已连续推进的任务接入

`task_planner.py`将参考的速度、加速度和q/dq区间直接作为原碰撞QP的不等式约束，同时保留原碰撞、原生范围和私有几何检查。旧启动第0/10步保存状态做4次私有求解，重复恢复完全一致；第10步最大参考变化0.0002rad、参考速度0.01rad/s、加速度0.5rad/s²，在旧瞬时经验域内，预测双掌残差约1.856/1.838mm。没有重新积分旧失败，也没有以这两个状态宣称整任务通过。

已复核完整原11条件/57650命令：57380条超出本次实测参考范围。边界内的命令也不能由边际范围推出联合状态、历史或接触负载资格。保持原阶段额外300tick，0.1rad/s复用旧关节端点时有33个条件—阶段违反时间下界；最差撤回至少24.01秒，原允许9秒。计入0.5rad/s²加减速及末尾25稳定tick，最差端点需要约0.304254415641rad/s。由此提出0.35rad/s候选及TASK_REQUIREMENTS中的任务参考范围；**更高速率和完整范围未验证，不能直接进入下一完整任务物理。**

下一项的具体输入、实现与门见[NEXT_TASK_ADMISSION](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/NEXT_TASK_ADMISSION.md)。应把全部任务姿态、身体与手动作、阶段过渡、原生历史和接触/负载纳入事前冻结的范围；不能扩大旧阶段时间上限或借组件通过重开原任务。后续达到完整任务资格，才连接FB2同步RGB-D/标准读取，再进入FB3自生成场景。

## 费用、历史保护与目标复查

本轮18服务/203.244204873秒，含4非零退出：原生目标预检、浮点幅度比较、端点归约比较、把零速度下界误判为无解。全部保留，没有物理失败重试；审计和计算错误只修保存数据代码。新根约184.52MiB，低于512MiB。共享586服务/21239.484046611/24000秒，余2760.515953389秒；原批准增量4500内已用1759.314117969，余2740.685882031秒，两个预算都约束后继。盘余约3.77GiB，无新GPU/训练/下载/渲染，18次旧预览渲染保持。

587条前轮服务记录、旧F356/C546/N248/M准备98及批准执行1196文件绑定全部保持。2369唯一文件通过完整性验证，原动态冻结保持，追加源码和审计修订另有计划/哈希。full-body累计11动态/54003积分、57672静态及5401动态前向；8个新动态均为独立组件。原单臂145成功开发/92完整RGB-D不变，full-body完整合格任务0，学习收益unknown。

质量：局部动态与审计通过；有效多样性：8个固定组件条件；产量：0个完整任务；单位成功任务成本：无分母；人工介入：本轮执行和普通修复未追加询问；学习效果：未训练/未评价。没有以组件数据量冒领full-body生产能力。

[结果](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/RESULT.json)、[动态审计](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/evidence/DYNAMIC_AUDIT.json)、[完整任务覆盖核查](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/evidence/TASK_SUPPORT.json)、[需求推导](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/evidence/TASK_REQUIREMENTS.json)、[历史完整性](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/reference_tracking/evidence/INTEGRITY.json)。当前无活动服务；账本用`T/tools/refresh_reference_tracking.py`并保持`-I -B`。
