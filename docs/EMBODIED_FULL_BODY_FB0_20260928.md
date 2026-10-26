# FB0接续结果：G1全身控制已准入，完整任务仍未通过

2026-09-28。按用户确认的full-body方向，从原始账本/进程/文件状态接续。FB0完成固定本体、控制器、分层接口与有限预算；自主执行FB1并衔接一次固定FB2。近期/中期/最终目标保持，不回单臂扩量。

|阶段|实际结果|
|---|---|
|FB0|G1 29身体+14手、Decoupled WBC Balance/Walk、官方GroundOnly、CPU运行时固定；43通道/单位/50Hz与500Hz/历史恢复通过；6静态推理与9负例通过|
|FB1|一次20秒10000步/1000推理；降高0.112307m、前进1.010276m；双臂/14手实际动作、末窗双脚支撑100%且稳定停止；独立审计通过|
|FB2|一次250g箱体双手取放固定任务，在3983步/7.966秒左中指触源支撑面，18.014538N、0.110111mm；关闭该配置，不补剩13017步|
|FB3|未准入；自生成场景与独立初态复验不能由空场控制通过替代|

当前完整full-body合格任务**0**；新增13983实际转移是控制/失败开发记录，未冒充完整任务训练数据。原单臂145成功/92完整RGB-D、MG56/56、MD失败结论保持。

根因证据：67静态姿态只涵盖预抓取/抓取/携带/释放局部，未覆盖走近后的降高过渡。FB2在手臂预抓取参考开始之前触桌；这证明全阶段碰撞检查是必要前置，不证明G1平台不能完成任务。新增覆盖拒绝回归，不能把事后检查回填为事前通过。

两条保存轨迹全部重建：FB1 1000输入/10000命令，FB2 399输入/3983命令；接触力、原生PD和输入误差0。最初微小力差来自审计warmstart阶段错误，按[MuJoCo3.3.2源码](https://github.com/google-deepmind/mujoco/blob/3.3.2/src/engine/engine_forward.c)正确重建后通过，原负结果和费用保留，未调门或重新积分。

本轮20服务400.262740秒，含5个非零worker与独立完整性核验；共享481服务、18615.606045/19500服务秒，余884.393955秒；31GiB下余约4.14GiB。全部主PID0、临时环境清理、无自有后台。原480服务索引逐项保持；7389 capability+32 MD绑定及9旧B输入全部未变。无新训练/权重/下载/GPU/渲染。每合格完整全身episode成本目前不可定义，学习效果unknown，未授予生产/真机资格；本轮未额外要求用户介入，开发/人工工时未虚构计入服务秒。

- [完整报告](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/REPORT.md)
- [精确检查点](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/CHECKPOINT.json)
- [FB1独立审计](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/evidence/FB1_AUDIT.json)
- [FB2失败诊断](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/full_task/FAILURE_DIAGNOSIS.json)
- [历史完整性](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/evidence/INTEGRITY.json)
- [后继全路径任务准入要求](/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_bootstrap/prepared/NEXT_TASK_ADMISSION.md)

下一项是**FB2碰撞感知完整任务专家的静态准入**。当前固定包已按科学退出收束，资源未耗尽；没有新ready动态包或重复预算申请。保持旧配置关闭，不将移桌或调整单个阶段时刻包装成新成功。所有Python继续`-I -B`，旧工作树/P017/模型/数据不改。
