# 真实轨迹的原生 LeRobot 导出与读取

`export_trajectory(binding, sha256, destination)` 将已验证的完整 HDF5 轨迹交给固定官方 `Gr00tDataExporter`，生成 LeRobot v2.1 Parquet、逐 episode 统计和元数据。`NativeTrajectoryDataset(binding, sha256)` 通过官方 `TypedLeRobotDataset` 读取真正保存的表，可以直接传给 PyTorch DataLoader。

运行时使用 `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_g1_runtime_20260926_v1/prefix/bin/python -I -B`。调用者需按该运行根 `tools/run_probe.py` 设置隔离缓存，并把项目根、固定 LeRobot 源码、G1 派生源码及其 RoboCasa 包加入导入路径；不修改共享 Python 环境。完整验证入口为同运行根 `tools/probe_native_roundtrip.py`，它只用于复现有预算的验证，不能在已存在输出目录盲目重跑。

数据含义保持源读取器定义：

- `observation.state`、`action`、`next.observation.state` 分别为步前本体反馈、原生命令和步后反馈，保留 float64。关节名称、单位和传动语义保存在特征名与 `meta/info.json` 的 `script_config.metadata` 中。
- LeRobot `timestamp` 按 episode 内行号从零计时；`source.time` 和 `source.next_time` 保留原始 float64 仿真时间，未丢弃第 N+1 个终态。
- `outcome.terminated/truncated/task_success` 是 int64 标记。A 的物理失败仍列为 discarded；B 只通过控制准入，不改写为成功取放。
- A 与 B 分别保存，不补齐异构动作维度。不创建相机或导出接触、世界位姿、实际力矩等特权审计数组。
- 默认用途仅 `inspection` / `proprio_development`；训练、生产和相机请求均拒绝。`SCENE_BINDING.json` 钉住来源、实现和所有原生产物；读取时检查哈希。

固定 LeRobot 标准读取器默认把 float64 转为 float32，实际尾行最大动作舍入误差分别为 1.37e-8、6.78e-9、2.98e-9。本模块采用同一官方任务仓库提供的 Typed 读取器保留类型，不修改原生读取器源码。

本次实际保存并重新读取 A_G01 13971、A_G02 14583、B_hand 800，共 29354 条转移；全部七类返回字段经真实 DataLoader 按值、类型逐项相等，12 项用途/模态/身份拒绝通过。原生绑定清单为运行根 `evidence/NATIVE_DATASET_BINDINGS.json`，报告为 `evidence/NATIVE_ROUNDTRIP.json`。

这项验证闭合的是保存数据的原生格式链路。合格自产训练 episode 仍为 0，完整取放与学习效果未取得；不能将原生格式兼容扩写为任务或训练资格。
