from pathlib import Path
import json,hashlib,shutil
b=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_expert_branch1_20261026_v1')
dest=Path('/data/wsj/main/scene/docs/experiments/expert_branch1_20261026');dest.mkdir(parents=True,exist_ok=True)
entries=[]
def copy(p,relative):
 assert p.is_file(),str(p)
 q=dest/relative;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
 entries.append(dict(source_path=str(p),repository_path=str(q.relative_to(Path('/data/wsj/main/scene'))),sha256=hashlib.sha256(q.read_bytes()).hexdigest(),size_bytes=q.stat().st_size))
roots=['AUTHORIZATION.json','PLAN.json','PLAN_v2.json','PLAN_v3.json','PLAN_v4.json','FINAL_REVIEW.json','DATASET_MANIFEST.json','COST_FINAL_SNAPSHOT.json','EXPERIENCE_CATALOG_V2.json','EXPERIENCE_UPDATE_CHECK.json','EXPERT_ALL_CALLS_REVIEW.json','CUP_REGRESSION_COMPARISON.json','FINAL_V004_FAILURE_DIAGNOSIS.json','S02_V002_FORCE_BALANCE_CHECK.json','S03_CLOSE_OBSERVATIONS.json','ROBOT_DATA_SCHEMA.json','FEEDBACK_FRAME_CORRECTION.json','FEEDBACK_STATE_ORDER_CORRECTION.json','PROPOSAL_POINTER_RECONCILIATION.json','V003_REVIEW_IMAGE_REUSE_CHECK.json','V004_REVIEW_IMAGE_REUSE_CHECK.json','CHECKPOINT_BOUND_EVIDENCE_PROTECTION.json','OLD_SOURCE_PROTECTION_CHECK_FINAL.json','FORK_PROVENANCE.json','SCOPE_IDENTITY_CHECK.json','TEST_PREFLIGHT_RESULT.json','HISTORICAL_CUP_PROMOTION_CHECK.json','HISTORICAL_BOTTLE_PROMOTION_REJECTION.json','PRIMARY_VISUAL_OBSERVATIONS.json','FINAL_ARTIFACT_CHECK.json','SESSION_CLOSEOUT.json','V004_RELEASE_PLOT.json']
for p in sorted(b.glob('CANDIDATE*CHECK.json')):roots.append(p.name)
for p in sorted(b.glob('CANDIDATE*REVIEW.json')):roots.append(p.name)
for p in sorted(b.glob('*FINAL*RETRIEVAL.json')):roots.append(p.name)
for name in dict.fromkeys(roots):copy(b/name,name)
copy(b/'V004_RELEASE_DIAGNOSIS.png','V004_RELEASE_DIAGNOSIS.png')
for name in ['TEST_PREFLIGHT.log','TEST_PREFLIGHT_V2.log','TEST_ACCOUNTING.log']:
 copy(b/name,Path('validation')/name)
for t in sorted((b/'trials').iterdir()):
 v=json.loads((t/'FINAL_VERIFICATION.json').read_text())
 for name in ['CASE.json','PROTOCOL.json','MEASUREMENTS.json','FINAL_VERIFICATION.json','PHASE_FEEDBACK_V3.json','SPATIAL_FEEDBACK.json','FEEDBACK_STATE_ORDER_CHECK.json','FORCE_CHECK.json','NATIVE_CALL_COUNT.json','JOB.json','full/REPORT.json']:
  copy(t/name,Path('trials')/t.name/name)
 for key in ['audit','delivery','replay']:
  if key in v['evidence']:
   p=Path(v['evidence'][key]['path']);copy(p,Path('trials')/t.name/p.relative_to(t))
 if (t/'full/AUDIT_v4.json').exists():
  for name in ['full/AUDIT_OBSERVATIONS_v3.json','full/AUDIT_v3.json']:
   copy(t/name,Path('trials')/t.name/name)
 for picture in v['primary_visual_observations']['files']:
  copy(t/picture,Path('trials')/t.name/picture)
for folder in sorted(b.glob('expert_*')):
 if (folder/'INVOCATION.json').exists():copy(folder/'INVOCATION.json',Path('expert_calls')/folder.name/'INVOCATION.json')
for name in ['PROPOSAL.json','PROPOSAL_V002.json','PROPOSAL_V003.json','PROPOSAL_V004.json']:
 copy(b/'workbench'/name,Path('proposals')/name)
for name in ['S02_V001_RELEASE_CAUSE.json','S02_V002_LOAD_SHARE_CAUSE.json','S02_V002_RELEASE_WRENCH_POSE.json','S02_V003_CONTACT_LOSS_CAUSE.json']:
 copy(b/'workbench/context'/name,Path('diagnoses')/name)
for name in ['native.py','check_feedback_state_order.py','verify_completed_v3.py','build_final_experience_catalog_v2.py','finalize_branch1_v2.py','plot_v004_diagnosis.py','complete_compact_feedback.py','check_final_artifacts.py','archive_branch1.py']:
 copy(b/'tools'/name,Path('tools')/name)
# Reviewable copies are archival; helpers with ROOT/parents bound to original B must
# be invoked in that declared context. An ended budget cannot be resumed by copying.
index=dict(schema='branch1-github-critical-source-bindings/v1',checkpoint_commit='2f2791348af1f80adf6dad17876b46e79641b28a',local_root=str(b),source_role='development_validation',dataset_split='unassigned',new_physics_steps=0,files=entries,not_uploaded='Full models, full TRACE, policy input archives, continuous replay state archive, full videos and cup NPZ remain local; exact paths and hashes in bound reports. Git contains critical reports and sampled actual review images.',historical_failure_policy='Earlier audit versions retained locally; official final audit path is bound in per-trial FINAL_VERIFICATION. V003/V004 base observation and metadata reconciliation reports included here. Preliminary mutable-progress reports are not authoritative final outputs.')
(dest/'SOURCE_BINDINGS.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
(dest/'README.md').write_text('''# 分支思路一：实际结果归档\n\n实验前断点：[2f27913](https://github.com/chilazy01-blip/Scene/commit/2f2791348af1f80adf6dad17876b46e79641b28a)。实施与结果说明见 [实验总结](../../EXPERT_BRANCH1_TRIAL_20261026.md)。\n\n`FINAL_REVIEW.json`、`DATASET_MANIFEST.json` 和各 trial 的 `FINAL_VERIFICATION.json` 是最终结果入口：杯回归合格但精确重复，五条瓶轨迹未完成，新增去重合格轨迹 0。新增物理 55548 步，累计 294686。\n\n`SOURCE_BINDINGS.json` 记录每份归档文件的原路径、仓库路径、SHA256 和大小。报告中的绝对路径指向原本地完整证据，可用索引对应到仓库副本。完整模型、TRACE、视频、连续复验状态和 NPZ 未上传，不能将本目录理解为可脱离本地依赖直接重放的完整数据包。抽样图片来自实际轨迹；全视频自动解码，主 agent 仅人工检查所声明的抽样帧。\n\n代码与归档工具保留原冻结运行上下文。本轮窗口已结束，不可通过复制脚本或重设 ROOT 复活同一预算。所有记录为 development_validation、split=unassigned；未训练或做隔离评测。\n''')
print(json.dumps(dict(files=len(entries),bytes=sum(x['size_bytes'] for x in entries),archive=str(dest))))
