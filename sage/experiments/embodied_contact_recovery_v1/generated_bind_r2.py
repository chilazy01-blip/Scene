"""Own-generated scene visuals and analytic native task colliders, unchanged G1."""
from pathlib import Path
from copy import deepcopy
import xml.etree.ElementTree as ET
import numpy as np
from .work import E,R,finish,c
from sage.experiments.embodied_scene_bridge.adapter import export_visuals,mesh_collider,pose
from sage.experiments.embodied_scene_v1.package import set_pose,vec
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb,_geometry,object_mass_frame

name='development_03';generator=E/'generated'/name/'generator';out=E/'generated'/name/'package'
out.mkdir(exist_ok=False);assets=out/'assets';assets.mkdir()
plan=c.read(generator/'layout_plan_final.json');assert c.read(generator/'validation_final.json')['ok']
glb=generator/'scene_codex_trellis_v2.glb';doc,_=_read_glb(glb)
ids={n.get('extras',{}).get('scene_object_id') for n in doc['nodes']}-{None}
declared={o['id'] for o in plan['objects']};openings={o['id']:o for key in ['doors','windows'] for o in plan['architecture'].get(key,[])}
assert declared<=ids and ids-declared<=set(openings)
groups,floor=_geometry(glb,dict(room=plan['room'],objects=[{'id':i} for i in sorted(ids)]))
root=ET.parse(R/'shared/target/MODEL.xml').getroot();world=root.find('worldbody');asset=root.find('asset')
world.find("geom[@name='ground']").set('group','5')
robot_before=ET.tostring(world.find("body[@name='base']"));actuator_before=ET.tostring(root.find('actuator'))
offset=np.array([2.,2.,0.]);poses={};bodies={};reports=[]
native=c.read(E/'generated/native_fixture_library_r2/BINDINGS.json')
for obj in plan['objects']:
 identifier=obj['id'];category=obj['category'];worldpose=pose(obj);parts=groups[identifier]
 allvertices=np.concatenate([p['vertices'] for p in parts]);local=(allvertices-worldpose[:3,3])@worldpose[:3,:3]
 dimensions=np.ptp(local,axis=0);expected=np.array([obj['dimensions'][k] for k in ['width','length','height']])
 assert np.max(abs(dimensions-expected))<1e-4,(identifier,dimensions,expected)
 if category in native:
  record=native[category];body=world.find("body[@name='"+record['source_body']+"']")
  source_origin=np.fromstring(body.get('pos'),sep=' ')
  oldbottom=np.array(record['source_world_origin'])
  frame=worldpose.copy();frame[:3,3]=[obj['x'],obj['y'],obj.get('z',0.)]
  frame[:3,3]+=frame[:3,:3]@(source_origin-oldbottom)
  moved=frame.copy();moved[:3,3]-=offset;set_pose(body,moved)
  for geom in body.findall('geom'):geom.set('rgba','0 0 0 0');geom.set('group','3')
  top=float(obj.get('z',0.)+obj['dimensions']['height'])
  top_points=allvertices[allvertices[:,2]>top-.001]
  assert len(top_points)>=4,('missing_horizontal_top',identifier)
  top_local=(top_points-worldpose[:3,3])@worldpose[:3,:3]
  assert np.max(abs(np.ptp(top_local[:,:2],axis=0)-expected[:2]))<1e-4,('top_support_plane_wrong',identifier)
  poses[identifier]=frame
  collider='Original analytic task fixture geoms; exact dimensions, materials and contact parameters preserved'
 else:
  moved=worldpose.copy();moved[:3,3]-=offset
  body=ET.SubElement(world,'body',name='scene_'+identifier);set_pose(body,moved)
  mesh_collider(asset,body,assets,'scene_col_'+identifier,local)
  poses[identifier]=worldpose
  collider='Static conservative convex hull of source mesh; cavities not traversable'
 bodies[identifier]=body
 reports.append({'id':identifier,'category':category,'actual_dimensions_m':dimensions.tolist(),'dimension_error_m':float(max(abs(dimensions-expected))),'collider':collider,'generated_world_pose':worldpose.tolist(),'simulation_offset_m':(-offset).tolist()})
for identifier in sorted(ids-declared):
 frame,local,extents=object_mass_frame(groups[identifier]);poses[identifier]=frame
 moved=frame.copy();moved[:3,3]-=offset
 body=ET.SubElement(world,'body',name='scene_'+identifier);set_pose(body,moved);bodies[identifier]=body
 mesh_collider(asset,body,assets,'scene_col_'+identifier,local)
architecture=ET.SubElement(world,'body',name='generated_architecture',pos=vec(-offset))
# The original ground plane remains the unique physical walking surface.
# Architecture visual floor top must coincide with it; walls retain hull colliders.
floor_bounds=[np.min(floor['vertices'],axis=0),np.max(floor['vertices'],axis=0)]
assert abs(floor_bounds[1][2])<.001,('floor_plane_mismatch',floor_bounds)
for i,part in enumerate(floor['other_architecture_parts']):mesh_collider(asset,architecture,assets,'architecture_col_'+str(i),part['vertices'])
before=set(map(id,list(world)))
visuals=export_visuals(glb,root,poses,bodies,out)
for child in list(world):
 if id(child) not in before and child.tag=='geom':world.remove(child);architecture.append(child)
# Free object retains source geometry/inertia and starts on the generated pick table.
# Task initialization will set the measured case pose before the first integration.
assert ET.tostring(world.find("body[@name='base']"))==robot_before
assert ET.tostring(root.find('actuator'))==actuator_before
ET.indent(root);ET.ElementTree(root).write(out/'MODEL.xml',encoding='unicode')
report={'prepared':True,'new_physics_steps':0,'new_render_passes':0,'source_glb_sha256':c.sha(glb),'layout_sha256':c.sha(generator/'layout_plan_final.json'),
        'model_xml_sha256':c.sha(out/'MODEL.xml'),'robot_and_actuator_XML_byte_equal':True,'world_offset_m':(-offset).tolist(),
        'all_generated_objects_retained':True,'objects':reports,'visual_primitives':len(visuals),'architecture_objects':sorted(ids-declared),
        'floor_visual_bounds_m':[v.tolist() for v in floor_bounds],'compile_and_contact_validation_pending':True,
        'material_calibration_pending':True,'production_accepted':False,'holdout':False}
c.write(out/'BINDING.json',report);finish(report)
