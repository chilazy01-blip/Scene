# Scene V2

本仓库只有一个面向用户的正式场景生成入口：

```bash
python -m sage.experiments.codex_trellis_scene_v2 \
  --prompt "一间带沙发、茶几和电视柜的客厅" \
  --output-dir /data/wsj/main/scene_runs/my_scene \
  --profile development --asset-mode plan
```

`SceneRequest -> SceneBrief` 之后的资产、类型化关系、布局、修复、装配与验收均由 V2 核心拥有。旧的
`run_tree_sage_scene.py`、`run_tree_sage_text_scene.py` 和 `run_selfmade_trellis_scene.py` 默认只是兼容
adapter；`--legacy-engine` 只用于复现实验，不接收新算法。

正式交付必须使用 `--profile production` 并满足运行时锁、完整阶段 DAG、资源门、Blender 验收和最终
哈希审计；development/plan 的成功不能表述为可交付。

继续阅读：

- [真实架构](docs/ARCHITECTURE.md)
- [运行手册](docs/RUNBOOK.md)
- [研究状态](docs/RESEARCH_STATUS.md)
- [ADR：统一 V2 核心](docs/adr/0001-v2-canonical-core.md)

CLI 默认值、schema、模型 fingerprint、分层测试数量和 release 状态不在手写文档复制。运行下列命令
可从解析器、运行时锁和机器验证 manifest 生成单一事实快照：

```bash
python -m sage.experiments.codex_trellis_scene_v2.project_facts \
  --output /data/wsj/main/scene_runs/project_facts.json
```

历史 Flow2 说明和实验结论保留在 `docs/` 与 V2 实验报告中，仅作证据，不代表当前默认链。

## 具身训练数据实验（2026-09-27）

已完成48条件几何采集（开发32/40、验证8/8）和等量图像学习检验；整批产量门及视觉取放准入未通过，失败保留。可读取的条件化研究数据现有97条成功开发轨迹，其中44条含完整腕部RGB-D，11880个时刻。它们不具备真机或稳定量产资格。见[训练入口](docs/EMBODIED_TRAINING_DATA_20260927.md)和[实测结果](docs/EMBODIED_CAPABILITY_RESULTS_20260926.md)。
