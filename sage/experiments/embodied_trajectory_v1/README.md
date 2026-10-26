# 具身真实轨迹读取 v1

`TrajectoryDataset` 实际读取来源钉住的 HDF5，并验证动作、本体反馈、时间、失败标签和源码身份；可直接传给 `torch.utils.data.DataLoader`。默认返回 `proprio/action/time/next_proprio/next_time/terminated/truncated`，不返回世界位姿、对象状态、接触、阶段或实际力矩审计字段。

本次固定开发来源为 A 两条完整失败尝试的已执行阶段，以及 B 的空场动手控制检查，共29354转移。保留 A 8维原生混合命令及16维传动反馈；B 43维关节位置目标及86维关节反馈，各自数据集读取，禁止补零混装。

A 前两动作是原生电机努力（N*m、gear作用前），其余为位置参考（m或rad），不是底盘速度。A本体坐标是原生执行器传动长度/速度，轮坐标包含gear=3与固定腱组合，不能解释为底盘xyz。B动作是43个原生MJCF关节的rad目标；actual motor ctrl(N*m)独立存在audit中。

每条有N+1观测和N动作；obs[i]在action[i]之前、obs[i+1]在其后；A每1ms，B每5ms，B下肢参考每20ms更新。跨阶段边界逐值验证并去除重复边界观测。失败最后转移terminated=true，B有限控制时域结束truncated=true；两者task_success始终false。

真实相机缺失，不创建补零图像。仅`inspection`或`proprio_development`用途可读；视觉/生产用途拒绝。HDF5是通用容器，此schema不是LeRobot/RLDS兼容声明；DataLoader读取通过不代表训练或环境动作消费已通过。

入口：

```bash
python -m sage.experiments.embodied_trajectory_v1 \
  --binding /absolute/path/BINDING_READER_V2.json --sha256 <binding_sha256>
```

本次有效绑定清单在 `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_trajectory_20260926_v1/evidence/READER_BINDINGS.json`。一次代码审查修订让读取器返回真实HDF5重载值，原源码和最初绑定保留供审计；不要用旧BINDING.json替代当前钉住绑定。所有29354条转移经真实PyTorch DataLoader逐值验证，17负例通过。学习unknown、合格训练episode0。
