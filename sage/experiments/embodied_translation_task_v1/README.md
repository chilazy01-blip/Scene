# 固定朝向的平移任务入口

执行记录：[REPORT.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_translation_task_20260924_v1/REPORT.md)。当前版本为开发检查入口，不是合格采集或导出入口。

`pregen.evaluate` 在场景生成前用原 Panda 和声明资产尺寸检查开度、两落点和工具净空；`pipeline.run` 唯一调用公共生成器，然后条件构造完整起终点模型；`stability` 保存并重算静置原始状态、完整接触坐标系和半步长结果；`entry.load` 按 inspection / candidate_stability / robot_execution 分别准入。机器人构造沿用固定工具、端点优先和固定关节插值，执行仅使用实际执行器，禁止执行中写目标姿态。

本轮 `U01` 实际结果：工具初筛通过，公共生成因尺寸来源作用域错误失败，所有后续物理和机器人阶段跳过。原提示里的 `by 10 cm` 会使公共解析器把各类默认尺寸当作严格约束；此问题尚未在本版本修复，不要直接重新调用已使用槽位。见本轮 `LESSONS.md` 和 `NEXT_STEP.md`。

最终29项软件测试、9项真实CLI拒绝检查通过；本轮无完整场景加载正例、无静置积分、无机器人路径/执行/回放或新相机帧。相关条件分支存在不代表完成真实任务验证。原库、旧实验和公共生成器未修改。
