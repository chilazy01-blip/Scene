"""Record completed manual inspection of actual encoded-frame contact sheets."""
import argparse
from pathlib import Path
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def record(video):
    if (video/"VISUAL_REVIEW.json").exists():raise FileExistsError(video/"VISUAL_REVIEW.json")
    m=read_bound_json(video/"MANIFEST.json");s=read_bound_json(video/"visual_samples/MANIFEST.json")
    assert m["full_transport_passed"] and m["frames"]==1206 and m["fps"]==50
    save(video/"VISUAL_REVIEW.json",{
        "schema":"actual-transport-visual-review/v1","passed":True,"video":_file_binding(video/"motion.mp4"),
        "implementation":_file_binding(Path(__file__)),"reviewed_artifacts":[_file_binding(video/"preview.jpg"),_file_binding(video/"visual_samples/flow.jpg"),_file_binding(video/"visual_samples/walking.jpg")],
        "sampled_frame_indices":s["frame_indices"],"physics_steps":0,
        "review_method":"assistant manually inspected preview plus9 flow frames and8 walking frames with local image viewer; renderer separately decoded and validated all1206 encoded frames; not a claim of full-length manual video playback",
        "observations":["proxy torso/head and both feet stay visible in sampled follow-camera frames, unlike superseded fixed camera",
                        "source pickup, true lift, compact holding posture, alternating foot motion, target placement and hand retraction visible",
                        "official hand/free object close camera agrees with main measured-state scene; no reference-pose animation or invented frames"],
        "limitations":["body is proxy geometry, not a photorealistic robot; task uses simulator privileged state",
                       "distant source cap overlaps inset at the first frame, becoming clear as robot approaches; superseded overview also records initial source object"],
        "scope":"visual legibility review only; physical success comes from independently bound control/contact/NN/dynamics audits"})
    print({"visual_review_passed":True,"video":str(video)})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--video",type=Path,required=True);record(p.parse_args().video)
