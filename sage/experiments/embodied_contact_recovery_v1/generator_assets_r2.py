"""Correct raw glTF up axis and bind fixture materials before new generator assembly."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from .work import R,E,finish,c
from sage.experiments.codex_trellis_scene_v2.p021_physics import GLTF_TO_Z
out=E/'generated/native_fixture_library_r2';out.mkdir(exist_ok=False)
root=ET.parse(R/'branches/A/source/scene.xml').getroot()
records=c.read(E/'generated/requests/development_02/asset_manifest.json')['assets']
fix=c.read(E/'generated/native_fixture_library/BINDINGS.json');transforms={}
for category,color in [('desk',[145,100,60,255]),('side_table',[50,70,155,255])]:
 bind=fix[category];body=root.find(".//body[@name='"+bind['source_body']+"']");origin=np.fromstring(body.get('pos'),sep=' ')
 scene=trimesh.Scene()
 for g in body.findall('geom'):
  size=np.fromstring(g.get('size'),sep=' ')
  mesh=trimesh.creation.box(extents=2*size) if g.get('type')=='box' else trimesh.creation.cylinder(radius=size[0],height=2*size[1],sections=32)
  mesh.apply_translation(origin+np.fromstring(g.get('pos','0 0 0'),sep=' ')-np.asarray(bind['source_world_origin']))
  mesh.visual=trimesh.visual.texture.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=color,metallicFactor=0.,roughnessFactor=.65))
  # GLTF raw coordinates are Y-up. Blender converts them to Z-up on import.
  mesh.apply_transform(np.linalg.inv(GLTF_TO_Z))
  scene.add_geometry(mesh,node_name=g.get('name'),geom_name=g.get('name'))
 path=out/(bind['source_body']+'.glb');scene.export(path)
 record=next(r for r in records if r['category']==category)
 record['glb_path']=record['raw_glb_path']=str(path);record['asset_id']+='__y_up_r2';record['source']['coordinate_conversion']='Z_up_native_to_Y_up_glTF'
 record['qa_scope']='Analytic visual geometry converted to proper glTF Y-up; must pass assembled support-plane verification.'
 bind['asset_sha256']=c.sha(path);transforms[category]=np.linalg.inv(GLTF_TO_Z).tolist()
c.write(out/'asset_manifest.json',{'assets':records});c.write(out/'BINDINGS.json',fix)
req=E/'generated/requests/development_03';req.mkdir(exist_ok=False)
previous=E/'generated/requests/development_02'
(req/'prompt.txt').write_bytes((previous/'prompt.txt').read_bytes())
c.write(req/'furnishing.json',c.read(previous/'furnishing.json'))
args=c.read(previous/'CLI.json')
for flag,value in {'--prompt-file':str(req/'prompt.txt'),'--furnishing-config':str(req/'furnishing.json'),'--asset-library-manifest':str(out/'asset_manifest.json'),'--output-dir':str(E/'generated/development_03/generator')}.items():args[args.index(flag)+1]=value
c.write(req/'CLI.json',args)
report={'prepared':True,'physics_steps':0,'new_render_passes':0,'cause':'Raw trimesh GLB vertices were Z-up although glTF coordinates are Y-up; bounding dimensions alone failed to detect a sideways support surface. Explicit glTF conversion and material binding correct the input.',
        'rejected_generated_scene':'development_02','rejected_scene_preserved':True,'support_geometry_validation_required':True,'transforms':transforms,'next_request':str(req),'production_accepted':False}
c.write(E/'GENERATOR_VISUAL_CORRECTION.json',report);finish(report)
