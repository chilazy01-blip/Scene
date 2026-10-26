"""Isolated collision tests, explicitly separate from robot task success."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
from pathlib import Path
from xml.etree import ElementTree as ET
import time
import numpy as np
import mujoco
from .models import absolute_assets,prune_assets
from .package import write_json,bound


def cavity_probe(package,output):
    package,output=Path(package),Path(output);output.mkdir(parents=True,exist_ok=False)
    results=[]
    for variant in ['baseline','repaired']:
        root=ET.parse(package/f'scene_{variant}.xml').getroot()
        absolute_assets(root,package,'assets')
        root.find('compiler').attrib.pop('meshdir',None);root.find('compiler').attrib.pop('texturedir',None)
        world=root.find('worldbody')
        for e in list(world):
            if e.tag!='body' or e.get('name')!='explicit_desk':world.remove(e)
        # Geometry isolation: same free sphere, same velocity, no gravity or friction.
        root.find('option').set('gravity','0 0 0')
        for e in root.iter('geom'):e.set('friction','0 0 0')
        body=ET.SubElement(world,'body',name='diagnostic_probe',pos='1.12 1.4 .4')
        ET.SubElement(body,'freejoint',name='probe_free')
        ET.SubElement(body,'geom',name='probe',type='sphere',size='.04',mass='.2')
        prune_assets(root);xml=output/f'{variant}.xml';ET.ElementTree(root).write(xml,encoding='unicode')
        m=mujoco.MjModel.from_xml_path(str(xml));d=mujoco.MjData(m);d.qvel[0]=-.5;mujoco.mj_forward(m,d)
        rows=[];count=0;maxpen=0.;started=time.monotonic()
        for i in range(1000):
            mujoco.mj_step(m,d)
            count+=d.ncon
            for c in d.contact:maxpen=max(maxpen,-float(c.dist))
            if i%10==0:rows.append([float(d.time),*d.qpos[:3].tolist(),*d.qvel[:3].tolist()])
        result=dict(variant=variant,final_xyz=d.qpos[:3].tolist(),contact_count=count,max_penetration_m=maxpen,
                    cleared_desk_front=bool(d.qpos[0]<.75),trajectory=rows,wall_seconds=time.monotonic()-started,model=bound(xml))
        results.append(result)
    write_json(output/'result.json',dict(test='under-desk collision isolation; calibration probe is not a robot or furniture asset',
        gravity=[0,0,0],friction=0,sphere_radius_m=.04,initial_velocity_m_s=[-.5,0,0],duration_s=1,dt_s=.001,
        sole_variant='desk collision representation',visual_and_mass_unchanged=True,results=results,
        cavity_restored=not results[0]['cleared_desk_front'] and results[1]['cleared_desk_front']))
