# 固定 Panda 轨迹的目标速度参考

本模块只验证一个控制修订：在已登记的位置轨迹上，向原 Panda PD 控制器提供解析目标关节速度。

`tau = Kp * (q_ref - q) + Kd * (qdot_ref - qdot) + qfrc_bias`

`q_ref` 沿用原三次插值及相同的 `k/count` 取样；`qdot_ref` 是该插值对秒的解析导数。沿用原增益、原生力矩范围、手指符号、阶段时长和物理模型。没有新增 IK、路径搜索、目标物体状态写入或焊接约束。

开发记录：[V01 计划](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_velocity_reference_20260924_v1/PLAN.md)。最终试验结果、失败原因及成本以该轮 RESULT.json、REPORT.md、SEAL_COMPLETION.json 和 SEAL_COST.json 为准。

- `controller.py`：位置/速度参考和原生执行器控制。
- `entry.py`：绑定旧场景证据与新控制试验，核对来源、实现和不变条件；仅支持 inspection、controller_evaluation，拒绝采集/导出。
- `execution.py`：一个有阶段门的实际执行与一个独立保存控制回放；逐步保存目标位置/速度、实际关节状态、实际控制、对象姿态，以及每十步和末步的完整积分状态与接触。
- `test_controller.py`：解析导数、轨迹一致性、边界、单位和执行器接口的八项检查。原生加载、输入拒绝及状态重算由本轮受限服务验证。

执行入口 `python -m sage.experiments.embodied_velocity_reference_v1 execute --protocol <固定协议>` 只能在本轮受限服务中使用；输出目录采用排他创建，不能覆盖已开始的物理样本。正加载只证明当前控制试验的前置条件满足，不能代表任务成功。

当前绑定是一个历史同源开发组合，不授予跨资产、扰动、完整时序观察、标准数据导出或下游学习资格。
