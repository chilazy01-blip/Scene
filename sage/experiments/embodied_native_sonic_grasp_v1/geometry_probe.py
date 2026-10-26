"""Finite private-data grasp candidate screening, no dynamics or physical writes."""
import argparse,itertools
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,parent):
    import mujoco
    p=read_bound_json(parent/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(parent/'version_04_ordered/full/TRACE.json')
    model=load_model(scene['model']['path']);d=mujoco.MjData(model);ik=IK(mujoco,model);h=hand_ids(model);obj=model.body('task_payload').id if mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'task_payload')>=0 else -1
    # Start at real last insert state, before any closing command.
    sample=next(r for r in t['records'] if r['stage']=='close')['substeps'][0]
    d.qpos[:]=sample['full_qpos_before'];q=d.qpos.copy();mujoco.mj_forward(model,d)
    payload=int(model.joint('payload_free').qposadr[0]);pos=q[payload:payload+3];w=model.body('right_wrist_yaw_link').id
    offsets=list(itertools.product([.13,.15],[.05,.07,.09],[-.025,-.04,-.055]));results=[]
    for offset in offsets:
        fit=ik.solve(q,pos-np.array(offset),np.eye(3),max_evaluations=100)
        if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:continue
        for closure in [.3,.45,.6]:
            d.qpos[:]=q;d.qpos[ik.qids]=fit['angles_rad']
            d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_forward(model,d)
            groups=set();maxdepth=0.;bad=[];contacts=[]
            for c in d.contact:
                pair=contact_pair(model,c);names=[x['name'] for x in pair];bodies=[x['body'] for x in pair]
                if 'payload_surface' in names:
                    other=pair[1] if names[0]=='payload_surface' else pair[0];role='desk' if other['body']=='generated_desk' else group(other['body'])
                    if role in ['thumb','index','middle','palm'] and c.dist<0:
                        groups.add(role);maxdepth=max(maxdepth,-float(c.dist));contacts.append(dict(role=role,distance_m=float(c.dist)))
                    if role=='other':bad.append(dict(pair=pair,distance_m=float(c.dist)))
                elif any('right_hand_' in b for b in bodies) and any(n.startswith('scene_collision_') for n in names) and c.dist<0:
                    bad.append(dict(pair=pair,distance_m=float(c.dist)))
            results.append(dict(offset_local_m=list(offset),closure=closure,groups=sorted(groups),max_virtual_finger_penetration_m=maxdepth,bad_non_grasp_contacts=bad,contacts=contacts,ik=fit,
                note='virtual target geometry, penetration reflects preload request only; actual dynamic penetration and force must pass unchanged physical gates'))
    qualified=[r for r in results if 'thumb' in r['groups'] and ('index' in r['groups'] or 'middle' in r['groups']) and not r['bad_non_grasp_contacts']]
    qualified.sort(key=lambda r:(-len(r['groups']),r['max_virtual_finger_penetration_m'],np.linalg.norm(np.array(r['offset_local_m'])-[.13,.07,-.04])))
    safe_save(root/'GRASP_GEOMETRY_PROBE.json',dict(schema='native-sonic29-grasp-geometry/v1',new_physics_steps=0,candidates=results,ranked_candidates=qualified,selected=None if not qualified else qualified[0],baseline_trace=_file_binding(parent/'version_04_ordered/full/TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='finite FK/contact feasibility only, not dynamic grasp proof'))
    print(dict(candidates=len(results),with_opposing_geometry=len(qualified),top=[{k:r[k] for k in ['offset_local_m','closure','groups','max_virtual_finger_penetration_m']} for r in qualified[:8]]),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
