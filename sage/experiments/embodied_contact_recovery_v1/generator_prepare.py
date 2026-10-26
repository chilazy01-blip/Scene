"""Own-generator input assets from unchanged task-fixture primitives."""
from pathlib import Path
import xml.etree.ElementTree as ET
import json
import numpy as np
import trimesh
from .work import P,R,E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

out=E/'generated/native_fixture_library';out.mkdir(parents=True,exist_ok=False)
source=R/'branches/A/source/scene.xml'
xml=ET.parse(source).getroot()
records=[];bindings={}
for body_name,category,color in [('table','desk',[145,100,60,255]),('table_white','side_table',[50,70,155,255])]:
    body=xml.find(".//body[@name='"+body_name+"']")
    origin=np.fromstring(body.get('pos'),sep=' ')
    meshes=[]
    for g in body.findall('geom'):
        size=np.fromstring(g.get('size'),sep=' ')
        if g.get('type')=='box':mesh=trimesh.creation.box(extents=2*size)
        elif g.get('type')=='cylinder':mesh=trimesh.creation.cylinder(radius=size[0],height=2*size[1],sections=32)
        else:raise ValueError('unsupported fixture geometry')
        mesh.apply_translation(origin+np.fromstring(g.get('pos','0 0 0'),sep=' '))
        mesh.visual.face_colors=color
        meshes.append((g.get('name'),mesh))
    bounds=np.array([np.min([m.bounds[0] for _,m in meshes],axis=0),np.max([m.bounds[1] for _,m in meshes],axis=0)])
    local_origin=np.r_[bounds.mean(axis=0)[:2],bounds[0,2]]
    scene=trimesh.Scene()
    for name,mesh in meshes:mesh.apply_translation(-local_origin);scene.add_geometry(mesh,node_name=name,geom_name=name)
    asset_id='contact_recovery_native_'+body_name
    path=out/(asset_id+'.glb');scene.export(path)
    extents=bounds[1]-bounds[0]
    dims=dict(zip(['width','length','height'],map(float,extents)))
    record={'asset_id':asset_id,'category':category,'styles':['modern','industrial'],
            'qa_status':'approved','quality_tier':'prototype_approved','asset_lifecycle_status':'curated',
            'glb_path':str(path),'raw_glb_path':str(path),'dimensions':dims,'asset_axis_to_z':2,
            'asset_local_yaw_offset_degrees':0.,'asset_canonical_front':{'axis':'-y','confidence':1.},
            'source':{'pipeline':'unchanged_task_fixture_primitive_conversion','source_xml':str(source),'source_sha256':c.sha(source),'new_asset_generation':False},
            'qa_scope':'Exact box extents and32-section cylinder visual conversion; original analytic physical colliders must be retained.'}
    records.append(record);bindings[category]={'source_body':body_name,'source_world_origin':local_origin.tolist(),'dimensions':dims,'asset_sha256':c.sha(path),'source_geoms':[g.attrib for g in body.findall('geom')]}
background=c.read(P/'generated/requests/GLOCAL_NEW/asset_manifest.json')['assets']
records += [r for r in background if r['category'] in ['office_chair','floor_lamp']]
c.write(out/'asset_manifest.json',{'library_id':'contact_recovery_verified_task_fixtures','assets':records})
c.write(out/'BINDINGS.json',bindings)
req=E/'generated/requests/development_01';req.mkdir(parents=True,exist_ok=False)
(req/'prompt.txt').write_text('A five by four metre modern study with exactly one desk, one side table, one office chair and one floor lamp. Keep a clear robot walking corridor near the two tables. Reuse the specified assets. No extra furnishings.\n')
poses={'desk':[2.351,2.,0.],'side_table':[1.8,1.2,0.],'office_chair':[4.,3.,0.],'floor_lamp':[4.7,3.4,0.]}
overrides={}
for record in records:
    key=record['category'];xyz=poses[key]
    overrides[key]={'dimensions':record['dimensions'],'requested_dimensions':record['dimensions'],
                    'initial_pose':dict(zip(['x','y','yaw'],xyz)),'preferred_wall':None,'facing_constraint':None}
c.write(req/'furnishing.json',{'schema':'scene-furnishing-groups/v1','object_overrides':overrides})
args=['--prompt-file',str(req/'prompt.txt'),'--furnishing-config',str(req/'furnishing.json'),
      '--output-dir',str(E/'generated/development_01/generator'),'--profile','development','--room-type','study',
      '--window-wall','north','--expander','rules','--planner','rules','--no-codex-repair','--repair-iterations','2',
      '--asset-mode','reuse','--asset-library-manifest',str(out/'asset_manifest.json'),'--seed','26101101',
      '--assemble','--no-render-preview','--no-scene-render-acceptance','--no-mujoco-check',
      '--hard-min-scene-objects','4','--target-max-scene-objects','4','--max-auto-inferred-assets','0','--max-new-assets','0']
c.write(req/'CLI.json',args)
finish({'prepared':True,'request':str(req),'fixtures':bindings,'new_physics_steps':0,'new_generated_scene':False,
        'holdout_cases_generated':False,'next':'Run actual own-generator public CLI, bind resulting layout and analytic colliders.'})
