# Scene V2 真实架构

唯一执行主干是 `sage.experiments.codex_trellis_scene_v2`。

```text
text front end ─┐
                ├─> SceneRequest -> SceneBrief -> typed graph -> assets -> layout
image front end ┘                                             -> repair -> assembly
                                                               -> acceptance -> audit
```

文本与图片前端只能解释输入并形成共享 `SceneRequest`/`SceneBrief`。图片绑定是可追溯的 soft
observation，不能覆盖文本明确事实。V2 核心独占资产准入、关系契约、布局、通用修复、Blender 装配和
最终验收。

每一核心阶段由 content-addressed DAG 管理；输出绑定大小与 SHA-256，输入、配置或依赖改变会精确失效。
TRELLIS/Blender 等重任务必须先经过统一 broker 资源门。production 还必须验证 runtime lock，只有
terminal status 明确为 deliverable 才是交付。

旧 Flow2 文件保留是为了输入兼容和历史复现。默认执行会进入 V2 adapter，只有显式
`--legacy-engine` 才运行冻结旧实现。
