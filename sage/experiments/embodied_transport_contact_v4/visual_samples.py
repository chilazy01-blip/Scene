"""Extract actual encoded video frames for manual visual review, no synthesis."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def extract(video):
    import cv2
    output=video/"visual_samples";output.mkdir(exist_ok=False)
    groups={"flow":[0,75,500,648,772,828,971,1115,1205],"walking":[772,790,810,828,847,855,875,920]}
    cap=cv2.VideoCapture(str(video/"motion.mp4"));images={}
    selected=set(i for group in groups.values() for i in group);frame=0
    while True:
        ok,picture=cap.read()
        if not ok:break
        if frame in selected:images[frame]=picture
        frame+=1
    cap.release()
    if set(images)!=selected:raise ValueError("missing requested real frames")
    for group,indices in groups.items():
        cols=3 if group=="flow" else 4
        cells=[cv2.resize(images[i],(480,300)) for i in indices]
        sheet=np.concatenate([np.concatenate(cells[i:i+cols],axis=1) for i in range(0,len(cells),cols)])
        cv2.imwrite(str(output/(group+".jpg")),sheet)
    save(output/"MANIFEST.json",{"video":_file_binding(video/"motion.mp4"),"implementation":_file_binding(Path(__file__)),"frame_indices":groups,
         "artifacts":{p.name:_file_binding(p) for p in output.glob("*.jpg")},"physics_steps":0,"synthesized_frames":0,"manual_visual_review_pending":True})
    print({"samples":str(output),"encoded_frames":frame})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--video",type=Path,required=True);extract(p.parse_args().video)
