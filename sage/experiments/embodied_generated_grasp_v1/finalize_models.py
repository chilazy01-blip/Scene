"""Complete metadata from successfully compiled native models; zero integration.

The first builder compiled and verified the model but duplicated schema/physics
keywords in dict construction. Preserve original logs/source/models; this separate
metadata finalizer does not alter XML, binary, geometry or any physical parameter.
"""
from pathlib import Path
import xml.etree.ElementTree as E
import numpy as np
import mujoco as mj
from .common import ROOT,read_bound_json,safe_save,_file_binding
from .build_models import OBJECTS,TEMPLATE,B
from sage.experiments.embodied_transport_native_v1.model import load_model

def run(key):
    sid,oid=key.split('_');out=ROOT/'models'/key
    assert not(out/'SCENE.json').exists()
    m=load_model(out/'model.xml');old=load_model(read_bound_json(TEMPLATE)['model']['path'])
    original=read_bound_json(TEMPLATE);source=B/'embodied_locomotion_pipeline_20261020_v1/scenes'/sid
    base=read_bound_json(source/'physics_v2/SCENE.json')
    checks={}
    for field in ('actuator_ctrlrange','actuator_forcerange','actuator_gainprm','actuator_biasprm','jnt_range','dof_damping','dof_frictionloss','dof_armature'):
        checks[field]=bool(np.array_equal(getattr(m,field),getattr(old,field)))
    for field in ('body_mass','body_inertia','body_ipos','body_iquat'):
        checks[field]=all(np.array_equal(getattr(m,field)[i],getattr(old,field)[old.body(mj.mj_id2name(m,mj.mjtObj.mjOBJ_BODY,i)).id]) for i in range(1,m.nbody) if mj.mj_id2name(m,mj.mjtObj.mjOBJ_BODY,i)!='payload' and not mj.mj_id2name(m,mj.mjtObj.mjOBJ_BODY,i).startswith(('generated_','explicit_')))
    assert all(checks.values())
    xml=E.parse(out/'model.xml').getroot()
    paths={str(Path(a.get('file')).resolve()) for a in xml.findall('asset/*') if a.get('file')}
    sources={k:_file_binding(source/('generator/'+k if k!='GENERATION.json' else k)) for k in ['GENERATION.json','layout_plan_final.json','validation_final.json','scene_codex_trellis_v2.glb']}
    sources.update(object_assumptions=_file_binding(out/'OBJECT_ASSUMPTIONS.json'),compile_implementation=_file_binding(Path(__file__).with_name('build_models.py')))
    scene=dict(schema='generated-fullbody-native-scene/v1',scene_id=sid,model=_file_binding(out/'model.xml'),compiled_model_cache=_file_binding(out/'CACHE.json'),assets=[_file_binding(Path(p)) for p in sorted(paths|{str(OBJECTS[oid]['asset'])})],sources=sources,official_robot_meshes=original['official_robot_meshes'],official_robot_model=original['official_robot_model'],robot_parameters_exact=checks,robot_restored_geoms=original['robot_restored_geoms'],room=base['room'],obstacles=base['obstacles'],task_object=read_bound_json(out/'OBJECT_ASSUMPTIONS.json'),no_payload=False,no_task_fixtures=True,all_official_robot_geoms_retained=True,native_floor=dict(collision_geom='native_floor',type='exact source triangles with 1mm shell',different_floor_representation_from_S01_box=True),native_collision_surfaces=[dict(name=mj.mj_id2name(m,mj.mjtObj.mjOBJ_FLEX,i),vertices=int(m.flex_vertnum[i]),triangles=int(m.flex_elemnum[i]),radius_m=float(m.flex_radius[i])) for i in range(m.nflex)],limitations=['Full generated scene triangle shells including floor; compared with S01 exact cuboid floor collision representation this is a declared different native contact representation.','New object masses and box inertias are explicit assumptions, not physical asset measurements.'],physics_steps=0,implementation=_file_binding(Path(__file__)),metadata_repair='Original compiled binary/XML unchanged; fix duplicate schema/physics_steps keyword failure in first metadata builder.')
    safe_save(out/'SCENE.json',scene)
    print(dict(finalized=key,robot_exact=True,nq=m.nq,nv=m.nv,nu=m.nu,physics_steps=0),flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
