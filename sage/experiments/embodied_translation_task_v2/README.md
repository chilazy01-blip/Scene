# 场景描述与任务参数分离的平移任务入口

本轮记录：[REPORT.md](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_translation_task_20260924_v2/REPORT.md)。

`request.py`保留scene_description原文，将以米为单位的task_spec独立保存；直接调用公共resolve_assets(mode=plan)，完整生成后逐项核对实际资产及尺寸解析结果。显式场景尺寸保持严格，公共自由语言数字作用域问题并未普遍修复。

`geometry.world_ray_height`使用与MuJoCo相同的世界射线求箱体首交点，避免局部边界容差查表选到相邻较高柱。此轮修订后局部XML/三份STL与失败版本字节一致，原31样本及1e-7m容差保持。原失败绑定/源码保留，新SCENE_BINDING_VERIFIED和TASK_BINDING区分修订结果。

实际验证：1次完整生成成功；4静置及2半步长比较通过；6IK/1固定路径/81状态通过；场景及机器人起终点4RGB/8分割通过。唯一真实执行在pregrasp末关节跟踪0.040088rad超过0.04rad停止，2000步失败回放状态/接触误差全0。共6物理尝试/19000步，36软件测试/12CLI检查通过。0完整搬运成功、0合格训练数据。

load的inspection、candidate_stability、robot_execution是不同前置范围；robot_execution可加载不表示任务已执行成功。qualified_collection/export继续拒绝。动态执行和回放分支本轮已实际到达，但抓取及之后阶段尚未验证。新控制假设留待下一轮，原控制器与公共生成器源码未改。
