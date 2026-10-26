# B 连续恢复与原生命名动作 v1

对应隔离运行目录 `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_b_native_20260926_v1`。

`control.py` 将 Body29 与 Hand14 分开验证，使用 MJCF 原生手限位、已有 kp/kd/努力限幅；名字、单位、坐标系、时刻及范围全部通过才写 ctrl。旧零位消费者保持原用途。

恢复包含完整 INTEGRATION、6×86历史、上一15维动作、Balance开关、命令/高度/rpy、gait及派生缓存、上一观测、控制相位和最后目标。官方未使用的counter/target_dof_pos也保存。先 forward 建缓存，再重新 setState，保证积分状态逐值不变。历史恢复以旧倒数控制样本重建最后一次已知推理验证。

`runtime.py` 继承既有 b_common 数值与官方策略方法，只将运行根显式绑定到新目录、Runtime日志目录显式传参。先共享SymPy后隔离NumPy/Pinocchio/ORT的导入顺序保持。`native_hand.py` 为既有消费者逐字节副本。

前置服务0积分；动态须前置通过和FREEZE完整验证，唯一800步/200前向上限；审计只读取保存数组。该接口不是家庭抓取或训练数据资格。
