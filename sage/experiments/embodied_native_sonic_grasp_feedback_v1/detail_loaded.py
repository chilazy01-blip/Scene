"""Close views of actual recorded grasp states, no integrations or interpolation."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def run(episode):
    import mujoco,cv2
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(episode/'REPORT.json');assert sha256_file(Path(r['trace']['path']))==r['trace']['sha256']
    t=read_bound_json(Path(r['trace']['path']));out=episode.parent/'grasp_detail';out.mkdir(exist_ok=False)
    model=load_model(r['model']['path']);d=mujoco.MjData(model);model.vis.global_.offwidth=960;model.vis.global_.offheight=720
    model.vis.headlight.ambient[:]=.45;model.vis.headlight.diffuse[:]=.8;opt=mujoco.MjvOption();opt.geomgroup[:]=1;opt.flexgroup[:]=0
    for i in range(model.ngeom):
        if (model.geom(i).name or '').startswith('robot_') and (model.geom_contype[i] or model.geom_conaffinity[i]):model.geom_rgba[i]=[0,0,0,0]
    ren=mujoco.Renderer(model,height=720,width=960);cam=mujoco.MjvCamera();cam.type=mujoco.mjtCamera.mjCAMERA_FREE
    rows=t['records'];ids={min(1000,len(rows)-1),len(rows)-1}
    for phase in ['close','load_probe','loaded_balance','lift','loaded_hover','probe_lower','probe_release','tuck','carry','release']:
        ix=[i for i,a in enumerate(rows) if a['stage']==phase]
        if ix:ids.update([ix[0],ix[len(ix)//2],ix[-1]])
    files={};panels=[]
    for i in sorted(ids):
        row=rows[i];s=row['substeps'][-1];d.qpos[:]=s['full_qpos_after'];mujoco.mj_kinematics(model,d);mujoco.mj_comPos(model,d)
        cam.lookat[:]=d.xpos[model.body('payload').id];cam.distance=.48;cam.azimuth=225;cam.elevation=-25
        ren.update_scene(d,camera=cam,scene_option=opt);rgb=ren.render().copy();bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        cv2.rectangle(bgr,(0,0),(960,68),(24,24,24),-1)
        cv2.putText(bgr,f'ACTUAL STATE  t={s["time_after_s"]:.2f}s  {row["stage"]}',(12,27),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1)
        f=s['forces'];cv2.putText(bgr,f'thumb {f["thumb"]:.2f}N / index {f["index"]:.2f}N / middle {f["middle"]:.2f}N',(12,53),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
        path=out/f'tick_{row["tick"]:04d}.jpg';cv2.imwrite(str(path),bgr);files[path.name]=_file_binding(path);panels.append(cv2.resize(bgr,(480,360)))
    ren.close();grid=np.zeros((360*((len(panels)+2)//3),1440,3),dtype=np.uint8)
    for i,panel in enumerate(panels):grid[(i//3)*360:(i//3+1)*360,(i%3)*480:(i%3+1)*480]=panel
    path=out/'review.jpg';cv2.imwrite(str(path),grid);files[path.name]=_file_binding(path)
    safe_save(out/'MANIFEST.json',dict(schema='actual-recorded-native-grasp-closeups/v1',new_physics_steps=0,report=_file_binding(episode/'REPORT.json'),files=files,implementation=_file_binding(Path(__file__))))
    print(dict(output=str(out),actual_state_panels=len(panels),new_physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--episode',type=Path,required=True);run(ap.parse_args().episode)
