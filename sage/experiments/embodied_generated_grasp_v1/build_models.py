"""Rebuild generated room triangle surfaces around the exact admitted G1 plant.

No physics integration here. New object masses/inertias are declared assumptions,
not measurements. Mesh dimensions come from the previously approved asset manifest.
"""
import argparse
from copy import deepcopy
import itertools
from pathlib import Path
import resource
import os
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import mujoco as mj
from .common import ROOT, safe_save, read_bound_json, _file_binding
from sage.experiments.embodied_transport_native_v1.model import load_model

B = ROOT.parent
TEMPLATE = B/'embodied_native_object_transport_20261021_v1/model/SCENE.json'
OBJECTS = {
    'cup': dict(mass=.15, dimensions=[.12,.09,.11], orientation_axis=[0,0,1],
        asset=B/'assets_curated_v1/optimized/mug_white_001.glb', assumed=False),
    'bottle': dict(mass=.2, dimensions=[.0749679643,.07495568255,.25], orientation_axis=[0,0,1],
        asset=B/'living_room_reconstruction_20260914_v1/generation/glass_bottle/asset.glb', assumed=True),
    'book': dict(mass=.25, dimensions=[.03,.16,.24], orientation_axis=[1,0,0],
        asset=B/'p021_material_leaning_20260908_v1/generation/leaning_book_01/asset.glb', assumed=True),
}

def vec(a): return ' '.join(format(float(x),'.12g') for x in np.asarray(a).ravel())

def run(scene_id, object_id):
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    key=scene_id+'_'+object_id; out=ROOT/'models'/key; out.mkdir(exist_ok=False)
    parent=read_bound_json(TEMPLATE); source=B/'embodied_locomotion_pipeline_20261020_v1/scenes'/scene_id
    scene=read_bound_json(source/'physics_v2/SCENE.json')
    x=ET.parse(parent['model']['path']).getroot(); s=ET.parse(scene['model']['path']).getroot()
    asset=x.find('asset'); world=x.find('worldbody'); deform=x.find('deformable')
    for n in list(world):
        if n.tag=='geom' or (n.tag=='body' and n.get('name') not in ('pelvis','payload')):world.remove(n)
    for n in list(deform):
        if n.get('name')!='payload_surface':deform.remove(n)
    for n in list(asset):
        if n.get('name','').startswith(('scene_','texture_')):asset.remove(n)
    dependencies=[]
    # Prefix all newly generated scene asset names; retain their exact source files.
    names={n.get('name'):'new_'+n.get('name') for n in s.find('asset') if n.get('name')}
    for a in s.find('asset'):
        if a.get('name') not in names:continue
        n=deepcopy(a)
        for k,v in list(n.attrib.items()):
            if k=='file':
                path=(Path(scene['model']['path']).parent/v).resolve();n.set(k,str(path));dependencies.append(_file_binding(path))
            elif v in names:n.set(k,names[v])
        asset.append(n)
    for n in s.find('worldbody'):
        if not (n.tag=='geom' and n.get('name','').startswith('scene_visual_') or n.tag=='body' and n.get('name','').startswith(('generated_','explicit_'))):continue
        n=deepcopy(n)
        for b in [n,*n.findall('.//body')]:
            for g in list(b.findall('geom')):
                if not g.get('name','').startswith('scene_visual_'):b.remove(g)
        for g in ([n] if n.tag=='geom' else n.findall('.//geom')):
            for k in ('mesh','material'):
                if g.get(k) in names:g.set(k,names[g.get(k)])
        world.append(n)
    meshes={a.get('name'):a for a in asset.findall('mesh')}; surfaces=[]
    for body in [world,*world.findall('.//body')]:
        for geom in body.findall('geom'):
            if not geom.get('name','').startswith('scene_visual_'):continue
            path=Path(meshes[geom.get('mesh')].get('file')); mesh=trimesh.load(path,force='mesh',process=False)
            v=np.asarray(mesh.vertices); f=np.asarray(mesh.faces)
            name='native_floor' if geom.get('name')=='scene_visual_0_0' else 'scene_collision_'+geom.get('name')
            fl=ET.SubElement(deform,'flex',name=name,dim='2',body=body.get('name','world'),vertex=vec(v),element=' '.join(map(str,f.ravel())),radius='.001',group='5',rgba='0 0 0 0')
            ET.SubElement(fl,'contact',selfcollide='none',internal='false',contype='2',conaffinity='1',friction='.8 .005 .0001',condim='3')
            surfaces.append(dict(name=name,body=body.get('name','world'),source=_file_binding(path),vertices=len(v),triangles=len(f),bounds_local_m=mesh.bounds.tolist(),radius_m=.001))
    spec=OBJECTS[object_id]; payload=world.find("body[@name='payload']")
    if object_id!='cup':
        loaded=trimesh.load(spec['asset'],force='scene',process=False)
        mesh=loaded.dump(concatenate=True)
        vertices=np.asarray(mesh.vertices)[:,[0,2,1]]*np.array([1,-1,1])
        bounds=np.array([vertices.min(0),vertices.max(0)])
        # Fixed manifest normalization, shared across all layouts and grasp trials.
        vertices=(vertices-bounds.mean(0))*np.asarray(spec['dimensions'])/(bounds[1]-bounds[0])
        faces=np.asarray(mesh.faces); mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
        obj=out/'object.obj';mesh.export(obj)
        a=asset.find("mesh[@name='native_mug_visual_mesh']"); a.set('file',str(obj));a.attrib.pop('scale',None)
        dependencies.append(_file_binding(obj))
        fl=deform.find("flex[@name='payload_surface']");fl.set('vertex',vec(vertices));fl.set('element',' '.join(map(str,faces.ravel())))
        d=np.asarray(spec['dimensions']); inertia=spec['mass']/12*np.array([d[1]**2+d[2]**2,d[0]**2+d[2]**2,d[0]**2+d[1]**2])
        inertial=payload.find('inertial');inertial.set('mass',str(spec['mass']));inertial.set('diaginertia',vec(inertia))
    xml=out/'model.xml';xml.write_text(ET.tostring(x,encoding='unicode'))
    model=mj.MjModel.from_xml_path(str(xml));old=load_model(parent['model']['path'])
    assert (model.nq,model.nv,model.nu,model.neq,model.nmocap)==(57,55,43,0,0)
    # Compare every robot inertial parameter and all actuator/joint properties.
    checks={}
    for field in ('actuator_ctrlrange','actuator_forcerange','actuator_gainprm','actuator_biasprm','jnt_range','dof_damping','dof_frictionloss','dof_armature'):
        checks[field]=bool(np.array_equal(getattr(model,field),getattr(old,field)))
    for field in ('body_mass','body_inertia','body_ipos','body_iquat'):
        checks[field]=all(np.array_equal(getattr(model,field)[i],getattr(old,field)[old.body(mj.mj_id2name(model,mj.mjtObj.mjOBJ_BODY,i)).id]) for i in range(1,model.nbody) if mj.mj_id2name(model,mj.mjtObj.mjOBJ_BODY,i) not in ('payload',) and not mj.mj_id2name(model,mj.mjtObj.mjOBJ_BODY,i).startswith(('generated_','explicit_')))
    assert all(checks.values()),checks
    binary=out/'model.mjb';mj.mj_saveModel(model,str(binary),None)
    safe_save(out/'CACHE.json',dict(xml=_file_binding(xml),binary=_file_binding(binary),mujoco_version=mj.__version__))
    object_assumptions=dict(object_id=object_id,asset=_file_binding(spec['asset']),dimensions_m=spec['dimensions'],mass_kg=spec['mass'],mass_inertia_are_assumptions=spec['assumed'],inertia_basis='unchanged original cup; manifest bounding-box rigid-body inertia for new objects',geometry='full original triangles, fixed manifest dimensions; no grasp-dependent scaling',friction='payload native contact unchanged from cup template',semantic_local_up_or_cover_axis=spec['orientation_axis'],acceptance='axis dot world up >=.98' if object_id!='book' else 'abs cover-normal dot world up >=.98',book_cover_basis='thin local X dimension .03m; cover spans local YZ',bottle_basis='empty rigid bottle, no fluid',physics_steps=0)
    safe_save(out/'OBJECT_ASSUMPTIONS.json',object_assumptions)
    sources={k:_file_binding(source/('generator/'+k if k!='GENERATION.json' else k)) for k in ['GENERATION.json','layout_plan_final.json','validation_final.json','scene_codex_trellis_v2.glb']}
    sources['object_assumptions']=_file_binding(out/'OBJECT_ASSUMPTIONS.json')
    assets={a['path']:a for a in [*parent['assets'],*dependencies,_file_binding(spec['asset'])]}
    safe_save(out/'SCENE.json',dict(**{k:v for k,v in parent.items() if k not in ('content_sha256_excluding_this_field','model','sources','assets','scene_id','native_collision_surfaces','implementation','task_object')},schema='generated-fullbody-native-scene/v1',scene_id=scene_id,model=_file_binding(xml),assets=list(assets.values()),sources=sources,native_collision_surfaces=surfaces,task_object=object_assumptions,implementation=_file_binding(Path(__file__)),robot_parameters_exact=checks,physics_steps=0))
    print(dict(model=key,nq=model.nq,nu=model.nu,nflex=model.nflex,robot_exact=all(checks.values()),physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('scene');ap.add_argument('object');a=ap.parse_args();run(a.scene,a.object)
