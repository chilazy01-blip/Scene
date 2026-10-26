"""Finite recorded-control physics replay; audit only, not another task success."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def replay(root):
    import mujoco
    r=read_bound_json(root/"REPORT.json"); t=read_bound_json(Path(r["trace"]["path"]))
    for b in (r["model"],r["trace"]):
        if sha256_file(Path(b["path"]))!=b["sha256"]:raise ValueError("evidence changed")
    samples=t["warmup_substeps"]+[s for row in t["records"] for s in row["substeps"]]
    plan=root/"DYNAMICS_REPLAY_PROTOCOL.json"
    if plan.exists():raise FileExistsError(plan)
    save(plan,{"schema":"recorded-control-dynamics-replay/v1","report":_file_binding(root/"REPORT.json"),"implementation":_file_binding(Path(__file__)),
               "max_physics_steps":len(samples),"first_mismatch_exit":True,"position_velocity_tolerance":1e-11,
               "scope":"single initialization then recorded controls/wrenches only; never reset qpos/qvel during replay; observer forces explicitly replayed, active remains zero; audit not autonomous task replication"})
    m=mujoco.MjModel.from_xml_path(r["model"]["path"]);m.opt.timestep=.005;d=mujoco.MjData(m)
    d.qpos[:]=samples[0]["full_qpos_before"];d.qvel[:]=samples[0]["full_qvel_before"]
    mujoco.mj_forward(m,d)
    max_q=max_v=max_w=0.;mismatch=None;steps=0
    for index,s in enumerate(samples):
        before_q=float(np.max(np.abs(d.qpos-s["full_qpos_before"])));before_v=float(np.max(np.abs(d.qvel-s["full_qvel_before"])))
        if max(before_q,before_v)>1e-11:
            mismatch={"index":index,"phase":"before","q_error":before_q,"v_error":before_v};break
        d.ctrl[:]=s["all_ctrl"];d.xfrc_applied[:]=s["xfrc_applied"];d.qfrc_applied[:]=s["qfrc_applied"]
        mujoco.mj_step(m,d);mujoco.mj_forward(m,d);steps+=1
        qe=float(np.max(np.abs(d.qpos-s["full_qpos_after"])));ve=float(np.max(np.abs(d.qvel-s["full_qvel_after"])))
        we=float(np.max(np.abs(d.qacc_warmstart-s["qacc_warmstart_after"])))
        max_q=max(max_q,qe);max_v=max(max_v,ve);max_w=max(max_w,we)
        if max(qe,ve)>1e-11:
            mismatch={"index":index,"phase":"after","q_error":qe,"v_error":ve,"warmstart_error":we};break
    result={"schema":"recorded-control-dynamics-audit/v1","passed":mismatch is None and steps==len(samples),"physics_steps":steps,
            "max_qpos_error":max_q,"max_qvel_error":max_v,"max_warmstart_error":max_w,"mismatch":mismatch,
            "protocol":_file_binding(plan),"report":_file_binding(root/"REPORT.json"),"implementation":_file_binding(Path(__file__)),"autonomous_task_replication":False}
    save(root/"DYNAMICS_REPLAY.json",result);print(result)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);replay(p.parse_args().root)
