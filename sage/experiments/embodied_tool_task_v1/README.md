# 工具感知的场景—任务构造入口

公共生成器 → 完整起点/目标场景 → 原生工具净空规则 → 全部端点 → 固定关节插值 → 起点/目标可见性 → 按用途加载。只对全部前置项通过的请求开放有限机器人执行，不开放合格采集/导出。

```bash
python -m sage.experiments.embodied_tool_task_v1 construct \
  --config /absolute/config --protocol /absolute/protocol/PROTOCOL.json
python -m sage.experiments.embodied_tool_task_v1 load \
  --binding /absolute/config/BINDING.json --sha256 <binding_sha256> \
  --request-id T01 --purpose inspection
```

config 必须是协议事前列明的请求，包含 request、selection、library、furnishing、roles、expected_counts 和 prompt。每个目录仅一次生成槽，构造失败或任务预检拒绝保留；禁止原地重跑。`robot_execution` 要求接触几何、原生端点/路径和两帧可见性全部通过，`qualified_collection`/`qualified_export` 均拒绝。入口核对所有模型/资产/协议/实现绑定，并重算工具边界和原始分割；绝对证据引用迁移须显式重新绑定。

工具规则包含 link7、手掌、两个手指和指垫，闭合及张开状态一起检查。四个事前抓持转角保持夹爪闭合轴，解析计算支撑代理上方的保守间隙；超过30mm就拒绝，不通过循环加高改变任务。工具 AABB 可能保守拒绝，不能当作源网格干涉或全局无解证明。整个机器人参与端点及路径的原生碰撞检查，任何端点失败就不检查该候选路径。

存储版打包器沿用 `embodied_task_scene_v1` 的完整几何/姿态/材质转换，区别是只保留 XML、不重复保存 MJB 和起点 GLB；起点直接绑定本轮生成器输出。目标 GLB、家具、墙体、开口和所有碰撞表示保留。物性仍是未经标定的先验，碰撞体明确是源表面柱/体素与凸包近似。

条件执行不焊接目标、不在初始化后写物体状态、不重新求 IK。真实执行器运行保存端点和固定时序，记录完整状态、原始控制和带完整坐标系的接触，每个启动样本有一次独立控制回放。静态观察两帧不证明整条轨迹的观测质量；工程入口、科学执行结果和生产资格分别报告。

本轮具体结果和分母见 `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_tool_task_20260924_v1/REPORT.md`，执行分支是否实际获得可运行请求以封存结果为准，不能仅凭代码存在宣称动态验证通过。
