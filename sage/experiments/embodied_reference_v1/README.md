# 外部参考记录检查

`ReferenceRows(path, sha256)` 读取真实 Parquet 行并验证身份、有限值、维度、episode/frame 连续性与时间递增。返回带 `source_` 前缀的原始观测、动作和索引，可由 PyTorch DataLoader 消费；默认不暴露模拟器状态或遥操作辅助字段。

此入口只接受 `inspection`。它不生成训练转移、不生成原生机器人命令，也不补相机或成功标签。读取器检查通过不会授予物理任务资格。

`diagnose_named_transfer(actions, binding_rows)` 使用已固定绑定的 Pinocchio 顺序，计算**假定来源使用同一顺序时**的逐关节限位差异。匹配 43 维不能证明来源顺序和模型身份；该诊断不取反、不裁剪，也不把 SDK 手部坐标当作原生 MJCF 坐标。

官方固定版本采集代码在 `env.step` 后传入观测，却在 step 前保存仿真状态；同版本回放导出另有步前记录路径。当前孤立 Parquet 缺 `script_config` 和生产入口身份，因此不能只凭邻接行决定动作属于哪次转移。待有完整来源包并验证时序、模型、任务后，应另行实现转换；这里保持拒绝。

`joint_mapping.indexed_joint_names` 按实际model dof_index绑定前缀名称，`permutation_by_names` 只重排同一组具名坐标，不推断轴或方向。固定官方转换器的14手关节索引错配已由实际Pinocchio模型复现；本组件的名称映射、43维往返及4负例通过。

`video.iter_source_camera` 用已有PyAV逐帧解码真实RGB，核对PTS、记录行数、shape/dtype后返回；缺帧、错时间或额外帧均拒绝。官方G1苹果放盘子episode0的683帧真实Torch CHW float32输入与独立float64参考已核对，0补零图像。这只验证图像消费和行时间，不证明动作因果时序或自有场景完整任务。

2026-09-26完整链路更正：Gr00tJointInfo中的顺序实际消费SyncEnv预打包的执行器坐标。直接传Pin坐标得到14差异不能证明同步控制错误；原始完整43通道链已验证。indexed_joint_names仅用于明确声明Pin坐标的接口，不应直接替换官方内部消费者。见runtime/evidence/FULL_CHAIN.json。
