# FB2完整里程碑工程准备结果（2026-09-28）

本轮解决“只准备短静态包，反复要求用户回复”的执行瓶颈。新增观测驱动专家、真实物体/接触/支撑守卫、原生命令全覆盖、一次条件性物理、独立因果审计、完整RGB-D/官方消费者与失败闭合的串行队列。**工程准备通过；完整任务资格尚未获得。** 三阶段目标及full-body方向不变。

## 已执行的证据

|检查|实际结果|
|---|---|
|初始原生动作包/专家快照恢复|通过；未调用ONNX、未积分|
|旧FB2触桌失败回归|仍被禁止接触角色门拒绝；未重新物理执行|
|阶段等待/超时/损坏快照|通过，等待使用原6秒恢复额度|
|63物理步/7命令合成尾部数据|动作块、掩码、43控制重排、HDF5/Torch值与类型一致；夹具不进训练|
|相机|头部+辅助观察相机，3历史静态姿态×2相机，6RGB-D对/18渲染pass，CPU llvmpipe|
|相机物理等价|19组动力学数组一致；3保存姿态前向动力学比较通过|
|配准与可见性|最大射线误差3.574913339e-7m；头部目标1419/3812/2881像素，辅助195/170/143像素；只代表这3姿态|
|队列、失败恢复、账本|45项合成工程检查通过，26源码编译通过；未授权入口在创建执行目录前拒绝|
|旧证据|F356、C546、N248文件逐项哈希不变；原529服务账本行完全保持|

预检原次在导入期超时，12.636697860秒/exit143保留，无新物理/推理；收紧可终止只读任务停止预留后r2以13.134438860秒通过。相机服务22.707524230秒。本轮合计3服务48.478660950秒。合成测试新增渲染中断夹具后，上界预期漏计1次，已留证并修正测试预期；生产计数原本正确。

## 尚未执行与限制

新参考矩阵、真实原生命令全矩阵、因果物理、全长双相机观测与新全身官方消费者都尚未运行。原生命令矩阵使用零速度反事实观察，不能替代物理全身跟踪/真实抓握成功。相机预览也不证明完整任务全阶段可见。整个新队列只经过上述部分实测和工程验证，后续普通实现问题须保留失败后自主修复。

本轮0新动态/积分/策略前向/训练/下载，18次预览渲染；完整full-body合格episode仍0，FB3未准入。历史全身2动态/13983步、静态6/动态1399前向保持，旧单臂145开发/92完整RGB-D保持。学习收益unknown，无硬件/稳定量产资格。

## 资源与交付

共享513服务，19480.169928643/19500秒，余19.830071357秒；检查点盘余4408598528B（约4.106GiB），下载6434499284B不变。无活动服务、全部主PID0、临时网络环境已清理。服务次数仅统计，费用不因失败或改名清零；服务秒不包含全部开发/对话时间。

完整提案[prepared/MILESTONE.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/prepared/MILESTONE.md)申请+4500服务秒/累计24000，涵盖条件性物理、审计、数据交付及有限失败分支；当前未批准/应用，不再另行催批600秒。磁盘仍31GiB、CPU8、内存12/16GiB，无GPU/下载/训练。1203冻结输入、935静态矩阵输入保持原11条件/15阶段/5200覆盖与全部原阈值。

入口[prepared/NEXT_TASK_ADMISSION.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/prepared/NEXT_TASK_ADMISSION.md)；机器结果[RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/RESULT.json)，精确账本[CHECKPOINT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/CHECKPOINT.json)。输入冻结不是运行通过证明；本轮最终BINDING封存准备代码/服务/文档，未来执行目录和可变账本另记。

完整运行报告：[M/REPORT.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/REPORT.md)。更新前五文档已[归档](history/embodied_milestone_20260928_before/MANIFEST.json)。
