# 原生混合执行器轨迹 v2

新增 `robocasa_native_v1` 适配器，读取经过保存审计的真实 G1 RoboCasa 控制轨迹。动作是43个具名关节的 rad 目标；特权审计中的实际控制严格区分29个身体电机努力（N*m）与14个手部位置伺服参考（rad）。旧 v1 实现及已绑定数据保持原样。

原始两个保存段在完整积分状态处逐值核对，去掉重复边界观测后得到104条转移、105个观测。第104步左手与桌面碰撞终止，失败标签保留；尚未进入非零手动作，不具有训练/视觉/生产资格。

`export` 实际写入 HDF5，`TrajectoryDataset` 验证来源与保存数组，读取真实保存值；默认只返回本体反馈、动作、前后时间和终止标记。运行时、证据和绑定位于 `scene_runs/codex_trellis_v2/embodied_robocasa_control_20260926_v1` 的 `evidence/NATIVE_FAILURE_DATASET.json`。所有104条转移已与官方 LeRobot Typed 读取器的真实 DataLoader 逐值、逐类型核对。
