# 隔离CPU工作负载入口

`python -I entry.py --runtime <path> --runtime-sha256 <sha256> <output> <script> [args]`。

隔离解释器排除工作脚本目录与PYTHONPATH。入口仅添加项目包根，并按哈希复用既有有界worker；工作负载在P007健康准入、资源监视和WORKLOAD_STARTED持久化后才执行。工作脚本的同目录帮助模块应迁移到正式项目包，不能依赖隐式sys.path。

这是导入顺序修复，不是额外安全沙箱；调用者仍须用独有systemd用户服务限制8CPU、12/16GiB及RuntimeMaxSec，保留累计服务账本、结束计数和临时环境清理。GPU不在此入口范围。

本次真实软件夹具名为inspect.py，验证其不会遮蔽标准库；执行后记录来自Python标准库的inspect.__file__、已完成资源准入。非-I启动、错误runtime哈希在workload claim前拒绝。3项检查通过，无网络、物理、策略前向或旧失败实验重试。

2026-09-26后续修订：`-I`会忽略`PYTHONDONTWRITEBYTECODE`，因此入口在任何工作区/依赖导入前显式设置`sys.dont_write_bytecode=True`。新建子解释器统一使用`-I -B`，不依赖父进程Python标志或环境变量继承。实际受限worker导入夹具后无pyc，并复现环境变量被忽略/显式-B生效。修订前入口、136个近期旧依赖缓存的只读筛查和结果保存在`embodied_g1_stack_bootstrap_20260926_v1/evidence/`；未删除无法确认独占归属的缓存。原9个B输入与两份首次失败归档哈希保持。
