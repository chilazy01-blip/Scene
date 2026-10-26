# 原生 G1 抓杯搬运：SONIC 上层动作接入与遗漏检查

本轮解决的是控制来源不清、手部接口次序不一致和接口未进入实际循环的风险。任务仍为原生白杯抓取、真实走步搬运至少 0.25 米、放下、释放并稳定。交付为统一动作接口、实际任务引擎、独立审计/连续复验/视频/合格导出入口，以及 19 项接入清单。本轮新增物理步为 **0**，完整搬运合格正例仍为 **0**。

源码：`sage/experiments/embodied_sonic_command_integration_v1/`。

证据根：

```text
/data/wsj/main/scene_runs/codex_trellis_v2/embodied_sonic_command_integration_20261023_v1
```

关键证据为 `VERIFICATION.json`、`TESTS.xml`、`COVERAGE.json`、`READINESS.json` 和 `INTEGRATION_PROTOCOL.json`。协议已冻结全部新增 Python 源文件、验证结果及真实历史前缀；不得就地修改这些源码再使用同一协议。

## 实际接入的控制链

原任务专家提供操作参考和双手关节目标；SONIC 编码器将操作参考编码为 64 维 token。统一 `CommandFrame` 携带 token、左手 7 维、右手 7 维、帧号、时间和来源。SONIC 解码器输出全部 29 个身体关节参考，经过原范围/限速规则和原生 PD；14 个手指目标经过名称映射，由原生手指 PD 执行。每 20 毫秒锁存一次完整动作，四个 5 毫秒物理子步共享同一手部目标。

新 `engine.py` 实际调用统一解码器和 43 路驱动，逐帧存储完整命令。新 `audit.py` 独立重建任务参考、神经网络、PD、接触和命令来源/时间/双手目标。`replay.py` 保留原初始化一次、全部 43 路 ctrl 连续再积分规则；`render.py`、`visualize.py`、`delivery.py` 保留真实轨迹视频和合格才导出的规则，并共用旧成本账。

这次没有把手指控制交给 SONIC 身体网络。官方架构的身体 token 与双手动作本来就分开；当前上层来源仍是本任务专家，没有可直接宣称“接上即会抓稳”的通用抓力策略。

## 核对出的接口问题

| 接口 | 核对与处理 |
| --- | --- |
| 手部动作顺序 | 官方为 thumb/index/middle；原生模型为 thumb/middle/index。左右手均按完整关节名映射，以不同食指/中指数值测试。旧任务的具名参考不因此被判定为历史顺序错误。 |
| 手部观测顺序 | 官方按 Pinocchio 全配置索引拆分状态，与动作顺序不同。读取实际 URDF，由已有 NumPy1/Pinocchio 进程隔离查询，并与官方观测拆分函数对照。 |
| Pinocchio 运行环境 | 直接在现有 NumPy2 仿真环境导入旧 Pinocchio 会 ABI 崩溃。使用已有兼容环境查询关节顺序，没有安装或更改环境。 |
| 协议头 | 实际 Python 常量与 C++ 接收器均为 **1280 字节**。旧 docstring 中的 1024 已过时。新 v4 打包结果与官方函数逐字节一致。 |
| 不完整/失效动作 | 双手字段必须齐全；拒绝非法形状、NaN、重复字段、过期/乱序帧、耗尽的动作块。拒收不生成全零张手命令；仿真引擎在错误时结束该段。没有宣称硬件失联恢复能力。 |
| 硬件手指耦合 | 官方实机左手观测复制食指到中指属于硬件处理，原生 14 个独立关节默认不复制。 |
| 限位与松手 | 保留原生范围、原半闭手参考包络及抓紧时每 tick 0.006 rad 限速；保留原有 60 tick 平滑松手曲线。案例范围不能扩大原模型范围。 |

## 仍未启用的部分

| 部分 | 当前状态 | 对当前任务的影响 |
| --- | --- | --- |
| GR00T/VLA 任务策略 | `PolicyClient` 输入输出适配已实现；本地缺 `gr00t` 包、策略服务地址与本任务检查点。没有调用真实 GR00T 推理。 | 当前使用原任务专家生成参考和手指目标。若要求学习策略自主决定抓取，需要提供可用服务/模型。 |
| 匹配的第一视角输入 | RGB、具名 43 关节、基座姿态、时间戳及语言适配已测试；真实匹配相机与标定未提供。测试图片明确是夹具。 | 当前专家读取仿真状态，不依赖相机。外部诊断视频不能当作 VLA 第一视角输入。 |
| 在线反馈步态重规划 | 已有模型适配器；真实 planner 调用返回 44 帧/30 Hz，并转换为 50 Hz。 | 当前控制循环仍用冻结的 `WALK_REFERENCE_BASE.npz`，未启用在线重规划，不计为重规划动力学通过。 |
| VR/键盘/DDS 实机链 | 未连接；mode1 操作参考及身体/手部接口已核对。 | 原生自动专家任务不需要操作者或硬件设备。 |
| 接入版完整动态成功 | 尚未进行新候选积分、独立整段审计、成功连续复验及视频交付。 | 接口通过不能证明走步不会滑脱。 |

完整 19 项逐项状态见 `COVERAGE.json`，含状态历史、实际动作历史、参数/验收保护、数据来源身份和成本/时间入口检查。

## 已完成的验证

- **33 项测试通过**：30 项新增动作/观测/协议/时序/限速测试，加 3 项既有官方 C++ lower12 顺序回归。
- 使用真实缓存 encoder/decoder 重算 12 个历史时刻；身体原始输出、身体目标和按名恢复的双手目标完全一致。
- 在这 12 个时刻的全部四个子步上重算原生 PD；**48 个状态的全部 43 路 ctrl 均与历史记录完全一致**。v4 手部 float32 传输的微小量化误差另行记录，没有混称位级相同。
- 从真实 3960 步/980 active tick 的抓取前状态恢复原任务；实际执行新 `task_frame → decode → 43 路 PD`，核验状态未被推进或改变。
- 真实 planner 模型调用通过；未据此声称在线重规划接入控制循环。
- 新旧冻结源码绑定通过；旧 `COST.json` 未变。已确认过期时间窗口会在分配物理步之前拒绝启动。

这些都是零积分验证。PD 平衡目标仍是静态规划结果，原接触、摩擦、步态扰动下能否抓稳搬运，需要实际动力学验证。

## 接续方法与资源

旧账根：`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_grasp_feedback_20261023_v1`。原生实际累计 **61116/75000**。新候选最大 4960 后缀步，成功后完整原初始化复验最大 8920 步，最坏累计 **74996**。不得另建账把累计清零。

旧批准截止为 2026-10-23 14:24:47 CST；之前尚未批准的 15:24:47 CST 延时请求也已过期。按照 `AGENT.md`，新物理实验必须有用户实际答复的新时间窗口；不得把“接入”或未回答的请求伪造成时间批准。新的时间记录应绑定当前 `INTEGRATION_PROTOCOL.json`，记录用户原文、收到时间、新截止以及 cap=75000；保留旧批准文件不变。

获得新时间授权后，使用既有环境从以下入口接续，不重做前缀：

```bash
env PYTHONPATH=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009/native_parallel_12h_20261011/shared/env37 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/cpu_env/bin/python -B \
-m sage.experiments.embodied_sonic_command_integration_v1.engine \
--root /data/wsj/main/scene_runs/codex_trellis_v2/embodied_sonic_command_integration_20261023_v1 \
--output /data/wsj/main/scene_runs/codex_trellis_v2/embodied_sonic_command_integration_20261023_v1/attempt_18/full \
--ticks 2220
```

先查是否已有 attempt_18 输出，禁止重复启动。实际失败则保留负例、查实测接触和参考原因；成功则继续同包 `audit`、`replay`、`render`、`delivery`，全部原任务门与独立审计/原初始化 43ctrl 连续复验/真实视频检查均通过后才交付正例。没有训练、安装、下载、提交或委派；场景生成器既有脏改保持。

官方架构对照：[VLA workflow](https://nvlabs.github.io/GR00T-WholeBodyControl/tutorials/vla_workflow.html)、[ZMQ protocol](https://nvlabs.github.io/GR00T-WholeBodyControl/tutorials/zmq.html)、[Observation configuration](https://nvlabs.github.io/GR00T-WholeBodyControl/references/observation_config.html)。实际执行以本轮验证绑定的本地官方源码为准。
