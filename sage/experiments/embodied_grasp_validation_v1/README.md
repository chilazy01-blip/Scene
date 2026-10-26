# 有限原生抓取验证入口

在具有 CPU/内存/时限/P007 限额的 worker 中运行：

```bash
python -m sage.experiments.embodied_grasp_validation_v1 prepare STAGE
python -m sage.experiments.embodied_grasp_validation_v1 execute STAGE --combination G01
python -m sage.experiments.embodied_grasp_validation_v1 audit STAGE
```

STAGE 必须有事前冻结的 `protocol/PROTOCOL.json`、源资产/完整场景/原生机器人绑定及输入哈希。prepare 运行软件正负夹具、保存数据旧书本负例、构建两个已声明目标、执行一次有限自动规划。execute 对该组合最多一次真实连续控制；无规划结果时不能积分。audit 只消费保存数据，永不物理回放。

`native.Stretch.command` 要求原生具名顺序和 `native_m_rad` 单位：轮前进/转动是原生归一化努力通道，lift/arm_extend/grip 为米，wrist/head 为弧度。轮反馈每1ms重算，原生关节驱动不修改。初始化后只写 ctrl，机器人自由基座，禁止对物体写位姿或附着。

`quality` 区分原生橡胶垫/指节、惯性质心/几何原点；静态预测使用单位接触权重，只证明几何接触部位，不能读作真实力。动态质量使用实际接触力及手—物相对变换。试提连续末窗须通过，才允许升高和搬运。重力摩擦裕度和接触偏心力矩是先验诊断，不是力闭合或真实物性认证。

本轮输出是专家特权几何/物理状态和失败质量记录。模型使用空杯/空瓶的刚性源凸包，杯内壁及把手物理保真未认证；完整任务成功也不自动产生训练合格 episode。相机观测、标准数据导出、跨场景重复性及学习效果需要各自真实验收。
