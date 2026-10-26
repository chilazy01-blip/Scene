# 专家完整任务场景迁移：实测、归因与接续（2026-10-07）

本轮执行用户“继续下一步”，保留原 18:05:16 +0800 截止和全部累计预算。没有后台接管冲突；从历史终态核对 PID 启动标识后串行执行。目标仍是自有 full-body 场景的数据闭环，FB0/FB1 保持，未重开单臂或旧 V9/P11/P12。

**结论：完整参考几何与原生策略检查通过；真实物理试验失败，FB2 仍未通过，自有合格任务/数据 episode 均为 0。** 此前外部人类示范候选的 6.045 秒失败仍保留、没有重启。本次是单独冻结的新原生场景迁移，不宣称还原了发布方的原始场景。

## 本轮交付与证据层级

| 层级 | 实际结果 | 证据 |
| --- | --- | --- |
| 来源 | 固定 benchmark07/shard000/episode0，922 状态、921 原始命令；缺逐 episode 原始模型合同 | [来源检查](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/PROVENANCE_INSPECTION_R1.json) |
| 新场景 | 固定源版本与 seed111，保存精确 MJB；工厂模型与快照逐数组相同 | [模型](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/NATIVE_SCENE_R2.mjb) |
| 完整参考 | 922/922 修正姿态独立审计通过；末态原生任务谓词成立 | [完整参考审计](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/full_reference_r7/INDEPENDENT_AUDIT_R2.json) |
| 原生策略 | 4 次预检与 971 次完整反事实前向，共 975 次 CPU 推理；输入/历史/指令重组审计误差 0 | [原生审计](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/native_coverage_r1/INDEPENDENT_AUDIT_R1.json) |
| 新指令适配 | 腿/腰保留原生 WBC；28 个手臂、手指目标直接使用修正姿态，按实际模型限位裁剪 | [971 条指令检查](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/direct_prepare_r3/RESULT.json) |
| 实际物理 | 214 次动态前向，213 条完整命令，856 个 5ms 物理步；4.28 秒左手中指碰桌退出 | [物理结果](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/physics_direct_r1/RESULT.json) |
| 独立物理审计 | 856 步状态连续、无中途重置；40367 个接触条目重建距离误差 0，指令重组误差 0 | [最终审计 R2](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/physics_direct_r1/INDEPENDENT_AUDIT_R2.json) |
| 后继准备 | 四个固定执行器快照的简单补偿未通过；进度观察器代码/回归通过，但无安全保持控制与真实闭环成功 | [执行器检查](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/ACTUATOR_FEASIBILITY_RESULT_R1.json)、[观察器回测](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/PROGRESS_GUARD_BACKTEST_R1.json) |

参考修正只证明几何可行。初始原生场景的记录姿态存在 597 帧超过穿透门、502 帧禁止接触，最大穿透约 20.11mm。修正保留箱体轨迹、根部高度/姿态和脚锚点，为手/物接触增加约 5mm 的目标裕量；其他允许接触继续使用原 10mm 上限，禁止接触目标间隙 0.2mm。没有把原验收上限放宽。完整参考仍没有证明动力学/力矩可行。原生箱体质量约9.855g，外部任务成功也不能直接替代自有场景与目标物质量下的FB2验收。

把姿态差叠加到原专家目标，会保留原目标中的大幅接触偏置：四个固定状态的指令姿态穿透达到 52–92mm。因此物理前改为绝对修正上肢目标；全部 971 条最终指令静态检查最大手/箱穿透约 5.00001mm、全部接触最大 6.45432mm。原生 NN 的输入、原始目标与内部历史未变，复用已有 971 次反事实推理；真实物理每拍仍从实际观测新推理，没有复用静态 NN 输出充当动态控制。

## 实际失败发生在哪里

[查看实际数值诊断图](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/diagnostics_r2/actual_failure.png)（另有 [SVG](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/diagnostics_r2/actual_failure.svg)）。图来自真实保存状态，不是模拟成功视频；本轮无新增仿真渲染，诊断渲染仍 220/220。

4.280 秒，`gripper0_left_left_hand_middle_1_link_col` 与桌碰撞，穿入 0.32888457mm。它是**禁止的手/桌接触**，即便未达到一般 10mm 穿透上限也应退出；没有用总穿透阈值替代接触类别门。

失败时根部位置相对当前参考差约 0.80mm，手臂最大关节误差 0.05631rad，而手指最大误差 0.510108rad。实际左中指目标 −0.684748rad、位置 −0.174640rad，仍在以 −2.620357rad/s 闭合。指令到 MuJoCo 执行器输入逐步误差 0，排除了额外缩放。原生该手指 kp=3、kd=0.5，力矩范围 ±1.4；不能沿用旧场景 kp=15 的文字作为本模型合同。

实际箱体也相对当前参考偏移约 14.23mm。仅把手指替换为参考姿态的零步快照虽然消除了碰桌，却产生约 26.65mm 的箱体穿透；同时替换手指与箱体后才回到原接触门内。这说明需要同步处理实际抓握状态与箱体位姿，单独追快手指不足以证明安全。静态替换不是实际动态干预证据。

实际全段最大手臂速度 3.90567rad/s、手指速度 2.62036rad/s、倾角 0.11279rad；最初双脚自然落地前离地持续 25ms，小于原 100ms 上限。精确源初态脚底离地 8.798mm，未做隐含暖启动或中途写状态，也没有冒充自有站立初态校准通过。

审计中发现 Pinocchio 的上肢顺序是“左臂7、左手7、右臂7、右手7”，旧诊断按连续14/14拆分不正确。R2 独立审计改为按实际关节名字分组，完整复查确认没有漏过更早的速度违规；真实指令的全28关节映射一直正确。保留原代码、错误审计与修正记录，以 R2 审计为准。

## 有限后继与接续

在固定 200/210/213/358 帧做零物理执行器数值检查，速度补偿的关节指令最高越界 0.00608rad，逆动力学补偿最高越界 0.05693rad、手指所需力矩最高超出 0.26238。参考逆动力学还要求非零的未驱动根部/箱体广义力，因此这些计算不能作为动力学可行证书。两种直接补偿未取得物理准入，没有换名重跑失败试次。

新增 `progress_guard.py` 只实现进度观察器：手指误差超过 0.1rad 或箱体位置偏差超过 5mm 时不应继续推进参考时钟。对实际记录回测，3.315 秒首先因箱体偏差发出 HOLD，4.160 秒识别手指未到位，分别早于碰撞 0.965 秒和 0.120 秒。名称重排、非有限输入、正/负例检查均通过。**它尚不是可执行的闭环控制器，停住后的安全保持动作、接触重定位、整个任务的实际成功均未验证。**

[下一执行合同](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/expert_adaptation_20261007/NEXT_EXECUTION_CONTRACT_R1.json)要求：利用实际箱体位姿修正双手相对目标，在抓握到位之前不进入下一动作段，先补齐保持/重定位动作的关节与力矩可行性和逐物理步安全检查，再给新方法独立准入。涉及时间与 NN 历史变化时，不能继承旧 971 次推理为新覆盖；静态剩余只有 407 次，需先如实核算。现候选 `physics_direct_r1` 已关闭。

后继仍须服务于“合格完整专家任务 → 自有生成场景 → RGB-D/标准数据 → 实际训练读取与学习验证”。本轮没有自有物理迁移、合格 RGB-D、成功数据导出或训练，不进入 FB3，也不回到长期 P12 控制研究或单臂扩量。

## 资源与恢复

45 个串行服务累计 664.521215715 秒，包括全部工程失败；本轮新增下载 1285 字节目录元数据。共同 18668.326837407/24000、全局 42368.011728738/48000 服务秒，下载 6723717619/8589934592 字节。磁盘共同 14006935552 字节、全局 43681554432 字节（以最新台账为准），原18GiB/47GiB上限不变。

原动作账本静态 83593/84000，动态 650 计费/531 已知实际，物理 8290 计费/8094 已知实际；组件 claim 3/8、完整任务 0/1。当前物理新增计费900/实际856、动态计费225/实际214，未用预留不退回。所有历史计数及差额保留，未因脚本版本或服务更名清零。4854 个历史绑定文件已核对哈希一致。

唯一恢复结果：[O/RESULT.json](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/execution/expert_adaptation_20261007_01/RESULT.json)，新范围 P=`prepared/expert_adaptation_20261007`、O=`execution/expert_adaptation_20261007_01`。入口 [refresh_adaptation_ledger_r3.py](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/tools/refresh_adaptation_ledger_r3.py)。`RECOVERY_POINTER`、`SCIENTIST_STATE`、`QUEUE` 与各级 `CHECKPOINT` 均已更新。STATE 保留最后作业的真实 PID/启动标识；无运行编排器、实验服务均终态。最终封存与核验见 O/CLOSURE_BINDING_R1 和 O/FINAL_VERIFICATION_R1。

停止原因是首个真实科学失败和有限补偿后继未取得准入，不是服务数或普通工程次数上限；没有待重复批准的普通工作。原 18:05:16 截止不顺延，新对话先读取当前结果、实际服务与累计预算，不从已消费试次重新启动。
