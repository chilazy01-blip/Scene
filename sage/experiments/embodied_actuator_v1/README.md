# 原生执行器重力前馈与准入检查

当前能力：在固定 Stretch MuJoCo 模型上，计算并核验执行器坐标中的重力前馈；在写入前拒绝缺失来源、错误单位、非有限值和越界指令。**尚未取得物理控制、取放或训练数据资格。**

`StretchTransmission` 从真实 `actuator_moment`（兼容 CSR）、关节和等式约束构造 `dq = S dz`。10 个坐标依次是左右轮角、升降、总臂伸长、腕 yaw/pitch/roll、夹爪滑块、头 pan/tilt。伸缩臂四段各占总伸长的四分之一；两根手指角对滑块的导数各为 10。执行器矩阵为 `B = S.T @ actuator_moment.T`，重力前馈解 `B f = S.T g`，轮子原生 gear=3 进入该矩阵。

`gravity()` 只接受零速度、无外加力、无 body_gravcomp 的已完成 FK 数据。动态调用者必须另外计算同姿态、零速度的数据，不能把含科氏项的 `qfrc_bias` 当纯重力。该函数只处理受驱动坐标；自由底盘和物体的六维重力没有被抵消。

`AffineServo.diagnostic()` 是不写状态的诊断接口：保留原生增益/偏置，通过 `ctrl = native_reference + gravity_force / gain` 实现前馈。参考值使用原生执行器长度/速度坐标；尤其轮子的参考是齿轮缩放后的速度，不能直接传入 m/s。它不证明受力可行，也不授予执行许可。

`prepare()` 和 `apply()` 要求全 10 通道有经过审查的来源、正确坐标与单位、有限双向努力范围。已有 lift ±70 N、arm ±56 N 被取交集保留。指令或努力越界时整条命令拒绝，不能静默截断重力补偿。`apply()` 仅在全部检查完成后写入努力上限及 ctrl；不改增益，不写外力，不执行积分。

来源真实性由调用方根据绑定清单审核；`qualified` 不是自动标定结果。当前实际 `EFFORT_REGISTRY.json` 不完整，因此不能用于物理试验。测试中的虚构宽限幅只检查软件分支，不得复制到生产登记表。

验证产物位于 `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/adaptation/evidence/`：

- `STATIC_V2.json` / `STATIC_ARRAYS_V2.npz`：原生 home、20 个微小势能差分配置；10 通道虚功及 MuJoCo 仿射执行器力核对。
- `COUPLED.json`：倾斜姿态下非零臂/夹爪重力的独立势能差分；来源登记表拒绝后零部分写入。
- `SOURCE_AUDIT.json`：官方硬件、驱动和四份电机手册的已知值、推测及缺口分开记录。

累计 27 次静态配置（含一次 CSR 接口修订前的失败），0 积分。最大势能差分误差 9.59e-9；原生仿射执行器力核对误差 0。6 类错误输入被拒绝。原始物理模型、此前 B 输入和已验证视觉数据保持原件。
