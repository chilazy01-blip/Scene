# Scene V2 Local Control Plane

WebUI 是 V2 的本地、可恢复任务控制面，不是另一条场景算法链。图生/文生表单只形成兼容请求，执行仍
进入 Scene V2 核心。

## 启动

```bash
cd /data/wsj/main/scene
source .env
"$SAGE_ORCH_PYTHON" sage/webui/server.py --host 127.0.0.1 --port 8787
```

只允许 loopback 地址。当前版本故意不提供远程模式，因此没有制造一个缺少认证/CSRF 的公网入口；若
未来开放远程，必须在同一变更中加入身份认证、CSRF、路径 allowlist、请求体/并发/速率限制。

## 持久状态与恢复

默认数据库为 `/data/wsj/main/scene_runs/webui/jobs.sqlite3`，强制 SQLite WAL。数据库事务保存：

- job、诊断/正式 profile、资源门快照与稳定 systemd unit；
- V2 DAG 的 stage 和每次 attempt；
- stdout/stderr 路径及实时大小/hash；
- 每个 stage artifact 的路径、大小与 SHA-256；
- 资产候选、生成状态和人工批准/拒绝记录。

任务由 `scene-webui-<job-id>.service` user unit 执行，并设置 cgroup 内存上限。WebUI 重启时查询 unit 的
`ActiveState/Result/ExecMainStatus/MainPID/ControlGroup` 重新关联，再从输出目录导入 V2 DAG；不再依赖
服务器内存里的 `Popen` 对象。找不到 unit 时明确标为 `orphaned`，不会伪造成功或使用含糊的 unknown。

历史 `jobs/*.json` 会非破坏性导入一次，原文件继续作为旧证据，之后 SQLite 是权威状态。

## 状态解释

- `diagnostic` 对应 development/plan，不是正式交付。
- `formal_delivery` 对应 production，仍须 V2 最终 terminal status 为 deliverable。
- `waiting_for_resources` 会同时显示 RAM/I/O/disk、GPU 和 P007 broker lease 原因。
- 资产列表分别显示 generation status 和 manual approval status，二者不可互相替代。

## API

- `GET /api/config`
- `POST /api/jobs/preview`
- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/cancel`
- `POST /api/jobs/{id}/assets/{candidate}/review`

所有输出目录必须位于 `SAGE_WEBUI_OUTPUT_ROOT` allowlist 内，请求体上限为 1 MiB。
