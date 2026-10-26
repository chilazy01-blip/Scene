# 分支思路一：实际结果归档

实验前断点：[2f27913](https://github.com/chilazy01-blip/Scene/commit/2f2791348af1f80adf6dad17876b46e79641b28a)。实施与结果说明见 [实验总结](../../EXPERT_BRANCH1_TRIAL_20261026.md)。

`FINAL_REVIEW.json`、`DATASET_MANIFEST.json` 和各 trial 的 `FINAL_VERIFICATION.json` 是最终结果入口：杯回归合格但精确重复，五条瓶轨迹未完成，新增去重合格轨迹 0。新增物理 55548 步，累计 294686。

`SOURCE_BINDINGS.json` 记录每份归档文件的原路径、仓库路径、SHA256 和大小。报告中的绝对路径指向原本地完整证据，可用索引对应到仓库副本。完整模型、TRACE、视频、连续复验状态和 NPZ 未上传，不能将本目录理解为可脱离本地依赖直接重放的完整数据包。抽样图片来自实际轨迹；全视频自动解码，主 agent 仅人工检查所声明的抽样帧。

代码与归档工具保留原冻结运行上下文。本轮窗口已结束，不可通过复制脚本或重设 ROOT 复活同一预算。所有记录为 development_validation、split=unassigned；未训练或做隔离评测。
