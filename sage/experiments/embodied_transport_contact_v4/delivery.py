"""Bound accepted evidence and a real-state video into a local handoff."""
import argparse
import html
import os
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def summarize(directory):
    compact=read_bound_json(directory/"COMPACT_AUDIT.json")
    if not compact["passed"]:
        raise ValueError("original lift/compact retention audit not passed")
    r=read_bound_json(directory/"REPORT.json"); a=read_bound_json(directory/"AUDIT.json"); p=read_bound_json(directory/"POLICY_AUDIT.json")
    if not a["full_transport_passed"] or not p["passed"]:
        raise ValueError("not a fully audited continuous transport")
    for b in (a["report"],p["report"],r["trace"]):
        if sha256_file(Path(b["path"]))!=b["sha256"]:
            raise ValueError("changed evidence")
    trace=read_bound_json(Path(r["trace"]["path"])); rows=[x for x in trace["records"] if x["sonic_candidate_consumed_by_physics"]]
    samples=[s for row in rows for s in row["substeps"]]; tail=samples[-100:]
    case=read_bound_json(Path(r["case"]["path"]))
    event={e["to"]:e for e in r["task_events"]}
    carry=event["carry"]; place=event["place"]
    carry_before=rows[carry["frame"]]["actual_root_xyz_before_m"]
    carry_after=rows[place["frame"]]["actual_root_xyz_before_m"]
    return {"report":_file_binding(directory/"REPORT.json"),"physical_audit":_file_binding(directory/"AUDIT.json"),"compact_audit":_file_binding(directory/"COMPACT_AUDIT.json"),"causal_policy_audit":_file_binding(directory/"POLICY_AUDIT.json"),
            "active_ticks":len(rows),"duration_s":len(rows)*.02,"events":[{"stage":e["to"],"time_s":e["frame"]*.02} for e in r["task_events"]],
            "source_to_final_object_xy_m":float(np.linalg.norm(np.array(event["done"]["object"]["world_position_m"])[:2]-case["source_object_xyz_m"][:2])),
            "carry_body_xy_displacement_m":float(np.linalg.norm(np.array(carry_after)[:2]-np.array(carry_before)[:2])),
            "max_held_slip_m":r["max_retention_slip_m"],"min_pelvis_height_m":min(s["pelvis_height_m"] for s in samples),
            "min_up":min(s["up_component"] for s in samples),"tail_peak_object_speed_m_s":max(float(np.linalg.norm(s["payload"]["linear_velocity_m_s"])) for s in tail),
            "tail_peak_body_speed_m_s":max(float(np.linalg.norm(s["root_velocity_after_m_s"][:2])) for s in tail),
            "task_gates":a["task_gates"],"full_transport_passed":True,"initial_start_xy_m":case["start_xy_m"],"source_role":"development_validation"}


def deliver(root,run,video,episode,repeats):
    output=root/"delivery"; output.mkdir(exist_ok=False)
    main=summarize(run)
    manifest=read_bound_json(video/"MANIFEST.json"); data=read_bound_json(episode/"EPISODE.json")
    if not manifest["full_transport_passed"] or not data["full_transport_passed"] or manifest["report"]["sha256"]!=main["report"]["sha256"] or data["report"]["sha256"]!=main["report"]["sha256"]:
        raise ValueError("video/data not bound to accepted main run")
    for b in [manifest["artifacts"]["motion.mp4"],data["arrays"]]:
        if sha256_file(Path(b["path"]))!=b["sha256"]:
            raise ValueError("changed delivered artifact")
    review={"schema":"continuous-transport-development-delivery/v1","baseline":main,"repeats":[summarize(p) for p in repeats],
            "video":_file_binding(video/"MANIFEST.json"),"episode":_file_binding(episode/"EPISODE.json"),"implementation":_file_binding(Path(__file__)),
            "physics_steps":0,"full_task_demonstrated":True,"visual_review":"must inspect preview and actual-state clip before declaring handoff complete",
            "scope":"one generated room, one50g cylinder, privileged simulator feedback, SONIC22+independent arm7; local development validation, not visual autonomy, held-out evaluation or mass-production readiness"}
    save(output/"REVIEW.json",review)
    relative=lambda p:html.escape(os.path.relpath(p,output),quote=True)
    (output/"index.html").write_text('<!doctype html><meta charset="utf-8"><title>连续自主搬运实测</title><body style="max-width:1080px;margin:30px auto;background:#151b25;color:#eee;font:18px sans-serif">'
        '<h1>连续自主搬运：开发验证通过</h1><p>同一次连续仿真：空手走近 → 真实抓取抬离 → 持物行走 → 停步放下 → 松手撤手 → 人和物停稳。没有片段拼接、物体重置、焊接或主动身体支撑。</p>'
        f'<video controls playsinline style="width:100%" src="{relative(video/"motion.mp4")}"></video>'
        f'<p>实测 {main["duration_s"]:.2f} 秒；物体起终点相距 {main["source_to_final_object_xy_m"]:.3f} 米；持物时身体移动 {main["carry_body_xy_displacement_m"]:.3f} 米；最大握持滑移 {main["max_held_slip_m"]*1000:.2f} 毫米。末100子步物体峰速 {main["tail_peak_object_speed_m_s"]*1000:.2f} 毫米/秒，左右脚真实迈步均经独立审计。</p>'
        '<p>限制：当前只验证同一生成房间中的50克圆柱；任务使用仿真状态反馈，不是视觉识别；身体是简化外观，手为官方精确模型。额外局部起点检查不代表泛化或生产可靠性。蓝/绿支架是明确添加的程序化任务夹具。</p>'
        f'<p><a href="{relative(output/"REVIEW.json")}">完整证据摘要</a> · <a href="{relative(episode/"EPISODE.json")}">数据说明</a> · <a href="{relative(episode/"episode.npz")}">逐步数值数据</a></p></body>',encoding="utf-8")
    save(output/"MANIFEST.json",{"review":_file_binding(output/"REVIEW.json"),"entry":_file_binding(output/"index.html"),"implementation":_file_binding(Path(__file__)),"full_transport_passed":True})
    print({"delivery":str(output),"duration_s":main["duration_s"],"additional_completed_conditions":len(repeats)})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--run",type=Path,required=True)
    p.add_argument("--video",type=Path,required=True);p.add_argument("--episode",type=Path,required=True);p.add_argument("--repeat",type=Path,action="append",default=[])
    a=p.parse_args();deliver(a.root,a.run,a.video,a.episode,a.repeat)
