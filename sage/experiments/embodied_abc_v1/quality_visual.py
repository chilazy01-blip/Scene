"""Explicit appearance revision for paired rendering, with physical arrays checked."""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import mujoco
import numpy as np

PHYSICAL_ARRAYS = ['body_pos','body_quat','body_mass','body_inertia','body_ipos','body_iquat',
    'jnt_type','jnt_bodyid','jnt_pos','jnt_axis','jnt_range','dof_damping','dof_frictionloss',
    'geom_type','geom_bodyid','geom_contype','geom_conaffinity','geom_pos','geom_quat','geom_size',
    'geom_friction','geom_solref','geom_solimp','geom_dataid','mesh_vert','mesh_face',
    'actuator_gainprm','actuator_biasprm','actuator_ctrlrange','actuator_forcerange']

def build_pair(source):
    source=Path(source)
    baseline=mujoco.MjModel.from_xml_path(str(source/'model.xml'))
    root=ET.parse(source/'model.xml').getroot()
    for node in root.iter():
        if node.get('file'):node.set('file',str((source/node.get('file')).resolve()))
    world=root.find('worldbody')
    for light in world.findall('light'):
        light.set('diffuse','.32 .31 .30');light.set('ambient','.08 .08 .08')
        light.set('specular','.10 .10 .10');light.set('castshadow','true')
    for name,pos,direction,diffuse in [
        ('abc_window_fill','2.5 3.9 2.4','0 -1 -.8','.14 .15 .16'),
        ('abc_front_fill','2.4 1.9 2.0','0 1 -.5','.11 .11 .11')]:
        ET.SubElement(world,'light',dict(name=name,pos=pos,dir=direction,diffuse=diffuse,
            specular='.03 .03 .03',ambient='0 0 0',directional='true',castshadow='false'))
    improved=mujoco.MjModel.from_xml_string(ET.tostring(root,encoding='unicode'))
    improved.vis.headlight.ambient[:]=[.20,.20,.20]
    improved.vis.headlight.diffuse[:]=[.18,.18,.18]
    improved.vis.headlight.specular[:]=[.03,.03,.03]
    improved.vis.quality.shadowsize=4096
    improved.vis.quality.offsamples=4
    improved.mat_specular[:]=np.minimum(improved.mat_specular,.18)
    improved.mat_shininess[:]=np.minimum(improved.mat_shininess,.25)
    checks={k:bool(np.array_equal(getattr(baseline,k),getattr(improved,k))) for k in PHYSICAL_ARRAYS}
    assert all(checks.values())
    assert baseline.nq==improved.nq and baseline.nv==improved.nv and baseline.nu==improved.nu
    assert baseline.opt.timestep==improved.opt.timestep
    return baseline,improved,checks
