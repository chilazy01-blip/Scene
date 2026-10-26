"""Panda/tool compatibility is a necessary gate BEFORE scene generation."""
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read, require, write_new, reference
from sage.experiments.embodied_scene_bridge.adapter import add_robot
from sage.experiments.embodied_simdata_v0.controller import PandaController
from sage.experiments.embodied_task_generation_v1.planner import perturbation_envelope
from .construction import templates, clearance_gap


def evaluate(config, output, protocol):
    import mujoco
    config=Path(config);output=Path(output);(output/'assets').mkdir()
    library=read(config/'library.json');selection=read(config/'selection.json')
    target=next(a for a in library['assets'] if a['asset_id']==selection['selected']['asset_id'])
    support=next(a for a in library['assets'] if a['asset_id']==selection['support_asset_id'])
    dims=np.array([target['dimensions'][k] for k in ['width','length','height']])
    sd=np.array([support['dimensions'][k] for k in ['width','length','height']])
    root=ET.Element('mujoco',model='pregen_original_panda');ET.SubElement(root,'compiler',angle='radian',autolimits='true')
    ET.SubElement(root,'asset');ET.SubElement(root,'worldbody');sources=add_robot(root,output,np.eye(4),{})
    path=output/'model.xml';ET.ElementTree(root).write(path,encoding='unicode')
    model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model);ctrl=PandaController(model,data)
    settings=protocol['tool_construction'];tools,error=templates(model,data,ctrl,float(dims[0]),settings)
    support_bounds=np.array([[[-sd[0]/2,-sd[1]/2,-sd[2]],[sd[0]/2,sd[1]/2,0.]]])
    start=np.eye(4);start[2,3]=dims[2]/2;goal=start.copy();goal[:2,3]=protocol['translation']['goal_offset_support_xy_m']
    rows=[]
    for roll in settings['grasp_roll_degrees']:
        grip=start.copy();grip[2,3]+=dims[2]/2-settings['grasp_offset_from_top_m']
        grip[:3,:3]=np.diag([1.,-1.,-1.])@Rotation.from_euler('x',roll,degrees=True).as_matrix()
        held=np.linalg.inv(grip)@start;frames={};gaps=[]
        for state,pose in [('start',start),('goal',goal)]:
            eef=pose@np.linalg.inv(held);bounds={}
            for mode,geoms in tools.items():
                for name,points in geoms.items():
                    world=points@eef[:3,:3].T+eef[:3,3];bounds[mode+':'+name]=np.array([world.min(0),world.max(0)])
            gap,witness=clearance_gap(bounds,support_bounds,settings['clearance_margin_m'],settings['minimum_release_gap_m'])
            frames[state]=dict(required_gap_m=gap,witnesses=witness);gaps.append(gap)
        rows.append(dict(roll_degrees=roll,states=frames,required_gap_m=max(gaps),passed=max(gaps)<=settings['maximum_release_gap_m']))
    policy=protocol['selection'];envelope=perturbation_envelope(dims,np.eye(3),policy['rotation_envelope_deg'])
    extent=envelope[:2]/2+policy['placement_margin_m']+policy['xy_offset_envelope_m']
    available=sd[:2]/2-policy['surface_edge_inset_m']
    footprint=bool(all(np.all(abs(pose[:2,3])+extent<=available) for pose in [start,goal]))
    opening=bool(dims[0]+protocol['pregen']['required_opening_margin_m']<=2*protocol['robot']['grip_open_m'])
    np.savez_compressed(output/'RAW.npz',support_bounds=support_bounds,**{mode+'__'+n:v for mode,g in tools.items() for n,v in g.items()})
    result=dict(passed=bool(footprint and opening and any(r['passed'] for r in rows)),opening_passed=opening,
        footprints_passed=footprint,candidates=rows,frame_error_m=error,target_dimensions_m=dims.tolist(),support_dimensions_m=sd.tolist(),
        raw=reference(output/'RAW.npz'),robot_sources=sources,new_generation_attempts=0,new_physics_steps=0,
        scope='declared dimensions and top plane only; necessary compatibility, not actual geometry, stability or path qualification')
    write_new(output/'RESULT.json',result);return result
