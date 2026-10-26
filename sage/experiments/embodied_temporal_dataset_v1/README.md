# 时序开发数据接口 v1

将已成功、已精确回放的V01轨迹转成明确动作语义的HDF5开发候选，并从原保存状态重建固定相机的全部351帧。该模块不调用动力学积分、IK或路径搜索。

[本轮计划](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_temporal_dataset_20260924_v1/PLAN.md)固定：一条历史同源开发轨迹、350个转移、351个观测；320×240原相机；不筛掉遮挡帧，不调整阈值，不重复渲染。

每个动作块为`(50,15)`，包含接下来50个1ms子步的7关节位置(rad)、7目标速度(rad/s)、1夹爪目标(m)。观测发生在动作块之前；参考值对应子步末端，控制作用于子步区间。不能用旧v0的20Hz八维位置保持动作直接替代。

`EpisodeDataset(binding, pin, purpose='development_dataset')`在返回数据前，真实验证来源和模型/控制器身份、完整时序、所有动作子步、原生状态对应、图像哈希与浮点统计、逐帧分割可见性、相机标定及开发分组。默认返回：

- `rgb`, `proprio`, `time`, `action`
- `next_rgb`, `next_proprio`, `next_time`

RGB为uint8，范围0..255；未暗中归一化。proprio的18维依次为7关节位置(rad)、2手指位置(m)、7关节速度(rad/s)、2手指速度(m/s)。单位与顺序也写入协议。完整状态、实际9执行器命令、分割和阶段字段属于审计信息，不暴露给默认观测。下游学习预处理尚未验证。

`inspection`允许读取保留的失败候选作诊断。`development_dataset`要求351帧全部通过原像素与可见比例门；生产采集/导出用途始终拒绝。真实任务成功、观察通过、数据契约通过与学习收益分别记账。失败的观察候选不能通过修改绑定的布尔标签取得资格。

入口：`python -m sage.experiments.embodied_temporal_dataset_v1 load --binding <path> --sha256 <pin> --purpose <purpose> --request-id O01`。

prepare/render入口仅由本轮受限CPU服务启动。渲染启动和每帧尝试排他记录，已开始帧不可重渲染。HDF5使用可重用容器，新动作块是本项目明确版本的契约，并非已经兼容所有外部训练框架。当前绝对来源绑定迁移时需要显式重绑定。
