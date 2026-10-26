"""Final bound-artifact, numeric-schema and frozen-source validation."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v3.control import ARM,SONIC
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES,ISAACLAB_TO_MUJOCO
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def validate(root,positive,video):
    import cv2
    review=read_bound_json(root/"delivery/REVIEW.json");cost=read_bound_json(root/"COST_REVIEW.json")
    bindings=[]
    def collect(value):
        if isinstance(value,dict):
            if "path" in value and "sha256" in value:bindings.append(value)
            else:
                for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    collect(review)
    collect(read_bound_json(root/"delivery/MANIFEST.json"))
    collect(read_bound_json(video/"MANIFEST.json"))
    collect(read_bound_json(video/"VISUAL_REVIEW.json"))
    summaries=[];sources={}
    for directory in positive:
        ep=read_bound_json(directory/"episode/EPISODE.json");collect(ep)
        path=Path(ep["report"]["path"]);r=read_bound_json(path)
        collect(r)
        arrays=np.load(directory/"episode/episode.npz",allow_pickle=False)
        assert all(np.isfinite(arrays[k]).all() for k in arrays.files)
        n=ep["samples"]
        assert all(len(arrays[k])==n for k in arrays.files)
        assert not arrays["quality_external_support_enabled"].any()
        raw=arrays["action_executed_mixed_raw_isaaclab"]
        decoded=np.array(DEFAULT_ANGLES)+raw[:,list(ISAACLAB_TO_MUJOCO)]*ACTION_SCALES
        target=arrays["action_body_target_rad"]
        error=float(np.max(np.abs(decoded-target)))
        assert error<1e-6
        candidate=np.array(DEFAULT_ANGLES)+arrays["action_policy_candidate_raw_isaaclab"][:,list(ISAACLAB_TO_MUJOCO)]*ACTION_SCALES
        assert np.max(np.abs(candidate[:,SONIC]-target[:,SONIC]))==0
        stage=arrays["privileged_task_stage_id"]
        assert ep["task_stage_ids"][int(stage[0])]=="approach" and ep["task_stage_ids"][int(stage[-1])]=="done"
        assert (stage==ep["task_stage_ids"].index("tuck")).any()
        summaries.append({"episode":_file_binding(directory/"episode/EPISODE.json"),"samples":n,"mixed_action_inverse_max_error":error})
    for item in cost["all_reports"]:
        r=read_bound_json(Path(item["report"]["path"]))
        for b in r["source_bindings"].values():sources[b["path"]]=b
    bindings.extend(sources.values())
    mismatches=sorted({b["path"] for b in bindings if sha256_file(Path(b["path"]))!=b["sha256"]})
    assert not mismatches,mismatches
    cap=cv2.VideoCapture(str(video/"motion.mp4"));frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
    manifest=read_bound_json(video/"MANIFEST.json")
    assert frames==manifest["frames"]==1206 and fps==50
    result={"schema":"continuous-transport-final-validation/v1","passed":True,"implementation":_file_binding(Path(__file__)),
            "delivery":_file_binding(root/"delivery/MANIFEST.json"),"bound_files_checked":len({b["path"] for b in bindings}),"frozen_source_files_checked":len(sources),
            "changed_bindings":mismatches,"positive_episodes":summaries,"accepted_full_samples":sum(x["samples"] for x in summaries),
            "video_frames":frames,"fps":fps,"physics_steps":0,"scope":"first complete flow and local sensitivity evidence; not production/held-out/visual autonomy"}
    save(root/"FINAL_VALIDATION.json",result);print(result)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--positive",type=Path,action="append",required=True);p.add_argument("--video",type=Path,required=True)
    a=p.parse_args();validate(a.root,a.positive,a.video)
