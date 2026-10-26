# 任务要求驱动的有限开发入口 v1

用途是将任务要求前移至资产选择和生成输入，并以固定开发条件检验适配后的局部释放能力。它不建立成功资产白名单，不授予训练数据生产资格。

`planner.select(library, request, policy, cavity=None)` 根据资产尺寸求最薄轴朝上的平放姿态，检查声明的偏移、旋转和边缘余量；在固定目标池中按足迹面积和身份排序。筛选不读物理结果。已认证容腔装不下时明确拒绝，不缩放或换任务。这里只枚举登记的 0/90° 水平朝向，不能声称已搜索全部姿态。

`generation_inputs` 将选择结果变成公共生成器复用清单、任务支撑关系和请求文本。先用同一规则解析器取得真实对象节点 ID，再连接支撑关系，复用目标节点而非新增同类对象。`build.build` 从公共生成器输出的实际 GLB 和布局读取目标—支撑关系；同一资产的多个实例不能凭资产 ID 的首个匹配确定角色，必须唯一匹配支撑关系。

适配后的任务模型让目标视觉网格和碰撞网格随同一刚体姿态转动；源 GLB 仍是原生成产物，不宣称原布局表示已支持任意三维姿态。源支撑局部区域按 5mm 上下界柱表示，不补洞、不膨胀、不加隐藏平面。上下界可能合并垂直多层，只评价登记的局部接触用途。质量、惯性和摩擦是显式未标定先验。模型包含目标和局部支撑，不包含机器人及其余家具的碰撞。

`physics.freeze_initials` 保存全部零积分初态。`physics.run_attempt` 对每个开始名额持久记录，保存完整原生积分状态、每步位置速度、接触点、完整接触坐标系和六维接触力矩。采用相对任务名义姿态的误差，避免将平放误判为倾倒。执行固定主条件、步长减半及跨服务新进程回放；不根据结果追加搜索。

`evidence.recompute` 从绑定的原始数组重新计算几何、动态、数值和任务指标；汇总中的通过标记不能覆盖原始证据。用途要求复用质量合同 v2：候选检查需要输入绑定，隔离释放需要全部基元门，采集和导出还需完整机器人任务及观测证据。

实际原生加载入口：

```bash
python -m sage.experiments.embodied_task_generation_v1 \
  --evidence /absolute/config/EVIDENCE.json --sha256 EXTERNAL_PIN \
  --request-id D01 --purpose candidate_inspection
```

`isolated_release_cases` 只覆盖该版本的有限条件；`qualified_collection`、`qualified_export` 缺必需证据会在返回模型前拒绝。原采集器未全局迁移。

本轮方案和实际结果：[运行目录](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_task_conditioned_20260924_v1/PLAN.md)。3 个事前请求都是开发材料，书本同源，独立验证 0。D02 生成失败和 D01 初始请求重复目标问题保留；工程修订没有重跑原生成名额。最终资格、次数与成本以 REPORT.md、SEAL_COMPLETION.json、SEAL_COST.json 为准。
