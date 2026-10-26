# 原生混合执行器轨迹的 LeRobot 桥接 v2

沿用固定官方 `Gr00tDataExporter` 与 `TypedLeRobotDataset`，接受 trajectory v2 来源绑定，保留原生手伺服和身体电机的单位、时间和失败标签。v1代码和29354条已验证数据的哈希不变。

实际导出104条 G1 RoboCasa 失败转移，Parquet/metadata/episode stats及真实 DataLoader 重载全部逐值和逐类型一致。新增数据为 discarded；用途/模态/全力矩误标四项拒绝检查通过。当前共29458条接口开发转移，合格自产任务 episode 仍为0，学习效果 unknown。

入口 `export_trajectory`、`NativeTrajectoryDataset` 与 v1 调用方式相同，但来源必须是 v2 绑定。具体隔离运行命令和验证在新控制根 `tools/export_native_failure.py`，结果在 `evidence/NATIVE_FAILURE_DATASET.json`。没有真实相机输入，不生成补零图像。
