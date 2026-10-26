# 数据动作块消费适配器 v1

接受O01真实EpisodeDataset读出的`float64 (50,15)`动作块，按1ms间隔调用原VelocityReferenceController，再执行原生积分。每行依次为7关节位置(rad)、7目标速度(rad/s)、1夹爪位置(m)。不会生成参考轨迹、求IK、读保存力矩作为驱动，也不在初始化后写入物体状态。

`ActionBlockExecutor(model, data, contract).step(block, block_index=..., start_time=...)`先检查整块的形状、dtype、有限值、关节原生范围、夹爪0..0.04m、单位/次序/采样契约、块序号与开始时间，再执行任何子步。发生执行中错误后禁止继续使用该实例。原控制器仍使用原增益与原生力矩限幅；模型未声明统一速度上限，因此不虚构硬件速度资格。

返回值只有实际原生proprio与time，没有把数据集保存RGB当作实时渲染。源RGB在读者中正常读取/验证，但本轮0新渲染、0视觉策略前向。该适配器验证的是原生动作消费接口；浮点精度转换、视觉网络预处理、外部框架适配和学习策略闭环另行验证。

`ReferenceAudit`单独持有V01参考，仅比较实际控制、关节/物体状态、完整积分状态和完整接触。实际驱动由控制器根据当前状态与读取器提供的q/qdot/夹爪参考计算。所有差异使用冻结的1e-12容差；时戳允许原浮点累计误差1e-9秒。

本轮绑定入口只允许inspection和consumer_evaluation，正加载不代表执行成功，生产采集/导出资格拒绝。`consume`排他注册一个STARTED，只有一个17500步尝试，不追加重试或额外回放。

结果见[本轮计划](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_block_consumer_20260924_v1/PLAN.md)及同目录REPORT.md、RESULT.json、SEAL_COMPLETION.json。原模型、控制器、数据包和旧历史保持只读；通过后结束当前单例接口分支。
