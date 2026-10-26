"""Accepted continuous-task numeric episodes with privileged channels separated."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_shadow import SONIC_BODY_JOINT_ORDER
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import ISAACLAB_TO_MUJOCO


def export(root,output):
    import mujoco
    r=read_bound_json(root/"REPORT.json"); audit=read_bound_json(root/"AUDIT.json"); policy=read_bound_json(root/"POLICY_AUDIT.json")
    if not audit["task_passed"] or not policy["passed"]:
        raise ValueError("only fully audited completed tasks are positive-eligible")
    for binding in (audit["report"],policy["report"],r["trace"],r["model"],r["case"]):
        if sha256_file(Path(binding["path"]))!=binding["sha256"]:
            raise ValueError("changed evidence")
    c=read_bound_json(Path(r["case"]["path"])); trace=read_bound_json(Path(r["trace"]["path"]))
    rows=[x for x in trace["records"] if x["sonic_candidate_consumed_by_physics"]]
    m=mujoco.MjModel.from_xml_path(c["model_path"]); qid=int(m.joint("payload_free").qposadr[0])
    before=np.array([x["substeps"][0]["full_qpos_before"] for x in rows])
    stages=["approach","source_stop","reach","close","lift","carry","target_stop","place","release","retract","settle","done"]
    arrays={
        "episode_time_s":np.arange(len(rows))*.02,
        "observation_body_position_rad":np.array([x["actual_qpos"] for x in rows]),
        "observation_body_velocity_rad_s":np.array([x["actual_qvel"] for x in rows]),
        "observation_base_quaternion_wxyz":np.array([x["actual_quaternion"] for x in rows]),
        "observation_base_gyro_rad_s":np.array([x["actual_gyro"] for x in rows]),
        "observation_finger_position_rad":np.array([x["substeps"][0]["hand_pd"]["positions_before_rad"] for x in rows]),
        "observation_finger_velocity_rad_s":np.array([x["substeps"][0]["hand_pd"]["velocities_before_rad_s"] for x in rows]),
        "action_policy_candidate_raw_isaaclab":np.array([x["raw_action_isaaclab"] for x in rows]),
        "action_executed_mixed_raw_isaaclab":np.array([x["applied_raw_action_isaaclab"] for x in rows]),
        "action_body_target_rad":np.array([x["hybrid_target_rad"] for x in rows]),
        "action_body_torque_substeps_nm":np.array([[s["body_torque_nm"] for s in x["substeps"]] for x in rows]),
        "action_arm_motor_feedforward_substeps_nm":np.array([[s["body_feedforward_nm"] for s in x["substeps"]] for x in rows]),
        "action_finger_target_rad":np.array([x["substeps"][0]["hand_pd"]["target_rad"] for x in rows]),
        "action_finger_torque_substeps_nm":np.array([[s["hand_pd"]["torque_nm"] for s in x["substeps"]] for x in rows]),
        "privileged_full_qpos_before":before,
        "privileged_full_qpos_after":np.array([x["substeps"][-1]["full_qpos_after"] for x in rows]),
        "privileged_object_pose_before_wxyz":before[:,qid:qid+7],
        "privileged_task_stage_id":np.array([stages.index(x["task"]["stage"]) for x in rows],dtype=np.int16),
        "quality_opposing_contact_fraction":np.array([sum(s["payload"]["opposing"] for s in x["substeps"])/4 for x in rows]),
        "quality_source_supported_fraction":np.array([sum(s["payload"]["source_supported"] for s in x["substeps"])/4 for x in rows]),
        "quality_target_supported_fraction":np.array([sum(s["payload"]["target_supported"] for s in x["substeps"])/4 for x in rows]),
        "quality_external_support_enabled":np.array([any(s["support_enabled"] for s in x["substeps"]) for x in rows]),
    }
    if len(rows)!=r["active_control_ticks"] or any(len(x["substeps"])!=4 for x in rows) or not all(np.isfinite(v).all() for v in arrays.values()):
        raise ValueError("incomplete/nonfinite episode")
    output.mkdir(parents=True,exist_ok=False)
    np.savez_compressed(output/"episode.npz",**arrays)
    with np.load(output/"episode.npz",allow_pickle=False) as loaded:
        if set(loaded.files)!=set(arrays) or any(not np.array_equal(v,loaded[k]) for k,v in arrays.items()):
            raise ValueError("numeric roundtrip failed")
    raw_order=[None]*29
    for i,j in enumerate(ISAACLAB_TO_MUJOCO):raw_order[j]=SONIC_BODY_JOINT_ORDER[i]
    result={"schema":"g1-continuous-transport-development-episode/v1","task_mode":c["task_mode"],
            "full_transport_passed":audit["full_transport_passed"],"samples":len(rows),"control_hz":50,"physics_hz":200,
            "report":_file_binding(root/"REPORT.json"),"physical_audit":_file_binding(root/"AUDIT.json"),"causal_policy_audit":_file_binding(root/"POLICY_AUDIT.json"),
            "arrays":_file_binding(output/"episode.npz"),"array_shapes":{k:list(v.shape) for k,v in arrays.items()},
            "body_joint_order":list(SONIC_BODY_JOINT_ORDER),"raw_action_order":raw_order,
            "finger_joint_order":rows[0]["substeps"][0]["hand_pd"]["joint_names"],"task_stage_ids":stages,"quaternion_order":"wxyz",
            "control":"SONIC22 plus independent rightarm7; candidate policy arm7 NOT executed; actual mixed action and declared motor bias explicitly exported",
            "privileged_channels":["world full/object pose","task stage and contact quality","controller uses simulator-state task feedback"],
            "rgb":"replay only; no RGB policy observations","source_identity":{"scene_id":c["scene_id"],"scene_manifest":c["scene_manifest"],"model":r["model"],"case":r["case"],"protocol":r["protocol"]},
            "source_role":"development_validation","dataset_split":"unassigned","held_out_evaluation":False,"production_accepted":False,
            "preloaded_grasp_not_pickup":False,"continuous_episode":True,"implementation":_file_binding(Path(__file__))}
    save(output/"EPISODE.json",result)
    print({"exported_samples":len(rows),"mode":c["task_mode"],"full_transport_passed":audit["full_transport_passed"]})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();export(a.root,a.output)
