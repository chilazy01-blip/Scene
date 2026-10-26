"""Close through the authority only at the original deadline; bind final controls."""
import time
from pathlib import Path
from .work import E,c
from . import controller_recovery_v4 as controller


def main():
    clock=c.read(E/'RUN_CLOCK.json')
    assert time.time()>=clock['deadline_epoch'],'original deadline has not arrived'
    assert not (E/'FINAL_SEAL.json').exists(),'final seal already exists'
    state=c.read(E/'STATE.json')
    assert state['status']=='active' and state['active'] is None
    assert not any(x['status']=='pending' for x in state['jobs'].values())
    assert all(x['closed'] for x in state['methods'].values())
    assert state['methods']['D_object_pose_planning']['scientific_failures']==5
    assert state['methods']['C_measured_contact_recovery']['scientific_failures']==3
    prepared=c.read(E/'PREPARED_EVIDENCE_SEAL.json')
    readback=c.read(E/'SEALED_MANIFEST_READBACK.json')
    manifest=c.read(E/'EVIDENCE_FILE_MANIFEST.json')
    assert prepared['complete'] and readback['passed']
    assert prepared['manifest_sha256']==readback['manifest_sha256']==c.sha(E/'EVIDENCE_FILE_MANIFEST.json')
    assert readback['regular_files_rehashed']==manifest['file_count']
    assert readback['logical_file_bytes_rehashed']==manifest['logical_file_bytes']
    assert readback['symlinks_checked']==len(manifest['symlinks'])
    assert c.read(E/'FINAL_IMMUTABLE_INPUT_AUDIT.json')['passed']
    ledger=c.read(E/'FINAL_RESOURCE_LEDGER_AUDIT.json');assert ledger['passed']
    audit_snapshot=c.read(E/'evidence/final_preseal_audit/STATE.json')
    extra_jobs={k:v for k,v in state['jobs'].items() if k not in audit_snapshot['jobs']}
    assert extra_jobs and all(v['status']=='succeeded' for v in extra_jobs.values())
    definitions={**c.read(E/'PLAN.json')['jobs'],**state['additional_jobs']}
    for key,entry in extra_jobs.items():
        assert definitions[key]['kind']=='seal' and definitions[key]['pool']=='export_seal'
        request=E/'jobs'/key/'REQUEST.json'
        receipt=c.read(E/'jobs'/key/'USAGE_FINAL.json')
        assert receipt['complete'] and receipt['request_sha256']==c.sha(request)
        assert c.read(request)==definitions[key]
        assert controller.evidence_ok(definitions[key]['inputs'])
        for resource,value in entry['usage'].items():
            if resource!='service_seconds':assert value==receipt['usage'].get(resource,0)
    extra_usage={k:sum(x['usage'].get(k,0) for x in extra_jobs.values()) for k in state['spent']}
    assert all(abs(state['spent'][k]-ledger['recomputed_spent'][k]-extra_usage[k])<1e-7 for k in state['spent'])
    assert all(extra_usage[k]==0 for k in extra_usage if k!='service_seconds')
    plan=c.read(E/'PLAN.json')
    assert plan['clock']==clock and all(state['spent'][k]<=plan['limits'][k] for k in state['spent'])
    assert all(all(value==0 for value in state['pool_spent'][pool].values()) for pool in ['comparison','holdout'])
    closure=controller.close(E,'deadline')
    assert closure['action']=='stop' and closure['reason']=='deadline' and not closure['objective_achieved']
    controller.inspect(E)
    final=c.read(E/'STATE.json');assert final['status']=='closed' and final['active'] is None
    new_usage={k:final['spent'][k]-plan['initial_spent'][k] for k in final['spent']}
    coordinator={'updated_epoch':time.time(),'status':'closed','closure_reason':'original_deadline',
        'controller':'controller_recovery_v4','clock':clock,'active':None,'spent':final['spent'],
        'new_run_usage':new_usage,'new_full_tasks':8,'new_task_cap':18,'C_failures':3,'D_failures':5,
        'all_methods_closed':True,'complete_numeric_tasks':8,'complete_numeric_frames':12306,
        'complete_RGBD_research_episodes':prepared['complete_RGBD_research_episodes'],
        'complete_RGBD_research_frames':prepared['complete_RGBD_research_frames'],
        'site_free_RGBD_episodes':prepared['site_free_RGBD_episodes'],
        'site_free_RGBD_frames':prepared['site_free_RGBD_frames'],
        'production_accepted':False,'qualified_episodes':0,'training_updates':0,
        'full_project_objective_achieved':False,'comparison_and_holdout_unadmitted_and_untouched':True,
        'next_scope':'Preserve this sealed run. New physical work needs a new bounded scope; prioritize foot numerical/physical validity before another full-task campaign.'}
    c.write(E/'COORDINATOR_STATUS.json',coordinator)
    agent=Path('/data/wsj/main/scene/AGENT.md');text=agent.read_text()
    marker='## 2026-10-11：18次任务接触恢复执行中（最新 HANDOFF）\n'
    assert marker in text
    note=f'''\n**2026-10-12 00:27最终断点：本轮已按原12小时时钟正式关闭并封存。** controller_recovery_v4.close以deadline为真实退出原因，原2026-10-11 12:27:26启动、23:57:26停止新研究、2026-10-12 00:27:26截止未重置。E/CLOSURE.json与FINAL_SEAL.json为最终权威；下方active/排队/尚未封存均为历史状态，不得恢复该旧目录的物理或工程队列。最高项目目标未达成，不能记作生产成功。\n\n新增完整任务8/18，开发8/8全用完；C科学失败3/3、D经用户修订后5/5，A/B继续关闭。全部8次完整独立重积分/策略重算与所有保存字段零差；比较4与最终测试6因质量/数值门未通过而未准入，额度未使用。新增任务/审计积分393668、诊断135994（全局139740/139746余6）、render30110、训练0；本轮实际服务{new_usage['service_seconds']:.3f}/48000秒，既有费用、科学失败与零积分工程核销证据完整保留。\n\n完整数值：8条12306帧，jobs/complete_numeric_research_collection_02/dataset，实际TypedLeRobot逐行状态/动作/掩码/时戳零差；完整RGBD研究数据：C3及D1—D5共6条6020帧，D的5条3005帧无调试site，C3旧3015帧视觉污染标签保留。全部为失败研究数据，合格生产0，学习验证0，同一原生物理场景不算生成多样性；自有development03/04/05只静态合格、动态成功0。目录COMPLETE_RESEARCH_RGBD_DATASET_REGISTRY_R2.json、费用COMPLETE_RESEARCH_PIPELINE_COST_REVIEW.json、完整任务证据COMPLETE_TASK_EVIDENCE_REVIEW.json/CSV；可复用采集/质检/标准导出/真实读取链路已保留。\n\n最终账本重算通过；FINAL_IMMUTABLE_INPUT_AUDIT覆盖460作业、13502输入文件、20.3449GB无缺失/哈希差异。EVIDENCE_FILE_MANIFEST登记19920文件/29.1967GB与1233有效符号链接；SEALED_MANIFEST_READBACK全部独立回读一致。FINAL_SEAL再绑定封存后回执、最终STATE/CLOSURE及资源增量，封存服务在原保护池内。足数值位置/速度门仍失败，经验物性/接触力校准仍缺证。下一轮应先解决共享足接触数值与物理可信性，再申请新的有界整任务方案，不通过改名重开C/D、不直接训练这些失败数据。\n\n'''
    agent.write_text(text.replace(marker,'## 2026-10-12：18次任务接触恢复已封存（最新 HANDOFF）\n'+note,1))
    known={x['path'] for x in manifest['files']}|{x['path'] for x in manifest['symlinks']}
    additions=[]
    for path in sorted(E.rglob('*')):
        relative=str(path.relative_to(E))
        if relative in known or relative=='FINAL_SEAL.json':continue
        if path.is_symlink():
            import os
            additions.append({'path':relative,'kind':'symlink','link_target':os.readlink(path)})
        elif path.is_file():additions.append({'path':relative,'bytes':path.stat().st_size,'sha256':c.sha(path)})
    report={'complete':True,'closed_epoch':time.time(),'reason':'original_12_hour_deadline',
        'closure_sha256':c.sha(E/'CLOSURE.json'),'state_sha256':c.sha(E/'STATE.json'),
        'prepared_seal_sha256':c.sha(E/'PREPARED_EVIDENCE_SEAL.json'),
        'base_manifest_sha256':c.sha(E/'EVIDENCE_FILE_MANIFEST.json'),
        'readback_sha256':c.sha(E/'SEALED_MANIFEST_READBACK.json'),
        'post_manifest_files':additions,'post_ledger_snapshot_jobs':list(extra_jobs),
        'post_ledger_snapshot_usage':extra_usage,'final_spent':final['spent'],'new_run_usage':new_usage,
        'protected_pool_usage':final['pool_spent'],'limits':plan['limits'],'clock':clock,
        'new_full_tasks':8,'new_task_cap':18,'complete_numeric_frames':12306,
        'complete_RGBD_research_episodes':prepared['complete_RGBD_research_episodes'],
        'complete_RGBD_research_frames':prepared['complete_RGBD_research_frames'],
        'qualified_production_episodes':0,'training_updates':0,'full_project_objective_achieved':False,
        'source_authority_code_sha256':c.sha(Path(controller.__file__)),
        'finalization_code_sha256':c.sha(Path(__file__)),'handoff_path':str(agent)}
    c.write(E/'FINAL_SEAL.json',report)
    print({'closed':True,'reason':'deadline','new_run_service_seconds':new_usage['service_seconds'],
           'qualified_episodes':0,'seal':str(E/'FINAL_SEAL.json')})


if __name__=='__main__':main()
