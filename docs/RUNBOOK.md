# Scene V2 运行手册

先在仓库根目录加载本机环境，然后用 `python -m sage.experiments.codex_trellis_scene_v2 --help` 查看由
解析器提供的当前参数。不要从历史文档复制默认值。

常用运行：

```bash
# 仅规划，CPU 可执行
python -m sage.experiments.codex_trellis_scene_v2 --prompt "..." \
  --output-dir /data/wsj/main/scene_runs/example_plan --profile plan --asset-mode plan

# 中断后恢复；prompt 和 SceneRequest 内容必须一致
python -m sage.experiments.codex_trellis_scene_v2 --prompt "..." \
  --output-dir /data/wsj/main/scene_runs/example_plan --profile plan --asset-mode plan --resume
```

需要生成缺失资产时选 `--asset-mode trellis2`；需要复用审核库时选 `reuse` 并传正式 manifest。重任务遇到
资源门拒绝时应读取结构化 reason，等待健康窗口，不能绕过 GPU/RAM/I/O/disk/cgroup 限制。

排障顺序：读取 `run_summary.json` 的 terminal status，再读取 `run_dag.json` 最后 attempt；检查 broker
admission reason；确认 staged GLB/metadata 的哈希；最后检查 Blender acceptance 与
`final_delivery_audit.json`。失败产物保留在原 attempt，修复后使用 resume。

正式发布前生成 `project_facts.json`，并运行四层验证。测试数与 release eligibility 只以该机器事实快照
及其绑定的验证 manifest 为准。
