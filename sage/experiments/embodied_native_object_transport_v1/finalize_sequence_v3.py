"""Bind the complete negative sequence attempt without altering prior evidence."""
import argparse
from pathlib import Path
from .protocol_v3 import authorize
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def check(binding):
    assert sha256_file(Path(binding["path"])) == binding["sha256"], binding["path"]


def run(root):
    authorize(root)
    output=root/"SEQUENCE_V3_FINAL_REVIEW.json"
    assert not output.exists()
    phase=read_bound_json(root/"PHASE_01_PARTIAL_REVIEW.json")
    current=read_bound_json(root/"SEQUENCE_V3_ATTEMPT_REVIEW.json")
    for b in [*phase["sources"].values(), *current["sources"].values()]:
        check(b)
    assert not current["task_passed"] and current["all_applied_physics_safe"]
    assert current["executed_physics_steps"] == 1024
    assert current["new_physics_total"] == 7088
    assert all(v for k,v in current["independent_audit_gates"].items() if k != "bounded_complete_episode")
    decoded=read_bound_json(root/"version_03_video_review/REVIEW.json")
    assert decoded["all256frames_decoded"] and not decoded["task_completed"]
    cause=read_bound_json(root/"COMMAND_REFERENCE_CAUSAL_PROBE_V3.json")
    assert cause["actual_rejected_command_bitwise_reproduced"]
    import xml.etree.ElementTree as ET
    tests=ET.parse(root/"SEQUENCE_V3_TESTS.xml").getroot()
    suites=list(tests) if tests.tag == "testsuites" else [tests]
    assert sum(int(s.attrib["tests"]) for s in suites)==10
    assert all(int(s.attrib.get("failures",0))==0 and int(s.attrib.get("errors",0))==0 for s in suites)
    dependencies={str(f.relative_to(root)):_file_binding(f) for f in (
        root/"VERSION_03_PROTOCOL.json",root/"SEQUENCE_V3_ATTEMPT_REVIEW.json",
        root/"COMMAND_REFERENCE_CAUSAL_PROBE_V3.json",root/"SEQUENCE_V3_TESTS.xml",
        root/"version_03/diagnostic_video/MANIFEST.json",root/"version_03/diagnostic_video/motion.mp4",
        root/"version_03_video_review/REVIEW.json",root/"version_03_video_review/decoded_review.jpg")}
    safe_save(output,{
        "schema":"native-mug-sequence-attempt-final-review/v3",
        "overall_transport_goal_achieved":False,"attempt_closed":True,"positive_episode_count":0,
        "user_requested_sequence":"walk naturally near desk, stop, then reach; preserve failed attempts as completely as safely possible",
        "actual_result":"5.12s1024steps; initial stand -> approach; unexecuted right ankle target0.588892552rad vs original0.5236rad max; rejected before write; no arm raise, pickup or carry tested",
        "rejected_right_ankle_target_rad":.5888925518751408,"original_upper_rad":.5236,
        "unexecuted_excess_deg":cause["outcomes"][0]["right_ankle_excess_deg"],
        "all_executed_physics_safe":True,"independent_reconstruction_exact":True,
        "all256frames_decoded_and_timed":True,
        "manual_visual_review":{"performed":True,"method":"agent view_image of six actual decoded MP4 frames, not claim to have manually watched every frame",
                                "full_robot_visible":True,"arms_not_preextended":True,"task_not_completed":True},
        "new_native_physics_total":7088,"cumulative_native_physics_total":25147,
        "new_attempt_physics_steps":1024,"new_reintegration_steps":0,
        "scope":"sequence change did not eliminate pre-write target rejection; it does not establish sole cause, post-stop grasp viability, grasp failure, or dynamic success of any reference ablation",
        "next_recommended_work":"review empty-hand gait and grasp-controller handoff against qualified native walking baseline before changing further reach poses; target/physical gates unchanged in this attempt",
        "dependencies":dependencies,"implementation":_file_binding(Path(__file__)),
    })
    print({"attempt_closed":True,"task_completed":False,"positive_episodes":0,"physics_steps":1024},flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);run(ap.parse_args().root)
