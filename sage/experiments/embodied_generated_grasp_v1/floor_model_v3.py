"""Evidence-based exact cuboid recognition for generated native floors.

The original triangle-shell models/failures remain frozen. Retain every furniture
and object triangle; recognize the generated floor's exact eight-corner closed
cuboid, then use the already validated same-volume native box representation.
No geometry extension, extra support, actuator or acceptance change.
"""
from pathlib import Path
from copy import deepcopy
import xml.etree.ElementTree as E
import numpy as np
import mujoco as mj
from .common import ROOT,read_bound_json,safe_save,_file_binding
from .build_models import TEMPLATE
from sage.experiments.embodied_transport_native_v1.model import load_model

def run(key):
    parent=ROOT/'models'/key;out=ROOT/'models_v2'/key;out.mkdir(parents=True,exist_ok=False)
    scene=read_bound_json(parent/'SCENE.json');old=load_model(scene['model']['path'])
    x=E.parse(scene['model']['path']).getroot();f=x.find("deformable/flex[@name='native_floor']")
    verts=np.fromstring(f.get('vertex'),sep=' ').reshape(-1,3);lo=verts.min(0);hi=verts.max(0)
    unique,inverse=np.unique(verts,axis=0,return_inverse=True)
    assert len(unique)==8
    assert all(np.all(np.isclose(v,lo,atol=1e-8)|np.isclose(v,hi,atol=1e-8)) for v in unique)
    faces=inverse[np.fromstring(f.get('element'),sep=' ',dtype=int).reshape(-1,3)]
    edge_count={}
    for tri in faces:
        for a,b in zip(tri,np.roll(tri,-1)):
            edge=tuple(sorted((int(a),int(b))));edge_count[edge]=edge_count.get(edge,0)+1
    assert len(faces)==12 and all(n==2 for n in edge_count.values())
    template=read_bound_json(TEMPLATE);t=E.parse(template['model']['path']).getroot()
    floor=t.find("worldbody/geom[@name='native_floor']")
    assert floor is not None and floor.get('type')=='box'
    center=np.fromstring(floor.get('pos'),sep=' ');half=np.fromstring(floor.get('size'),sep=' ')
    assert np.max(np.abs(center-half-lo))<1e-8 and np.max(np.abs(center+half-hi))<1e-8
    x.find('deformable').remove(f);x.find('worldbody').append(deepcopy(floor))
    xml=out/'model.xml';xml.write_text(E.tostring(x,encoding='unicode'))
    model=mj.MjModel.from_xml_path(str(xml))
    for field in ('body_mass','body_inertia','body_ipos','body_iquat','jnt_range','dof_damping','dof_frictionloss','dof_armature','actuator_ctrlrange','actuator_forcerange','actuator_gainprm','actuator_biasprm'):
        assert np.array_equal(getattr(model,field),getattr(old,field)),field
    assert model.nflex==old.nflex-1 and (model.nq,model.nv,model.nu)==(57,55,43)
    binary=out/'model.mjb';mj.mj_saveModel(model,str(binary),None)
    safe_save(out/'CACHE.json',dict(xml=_file_binding(xml),binary=_file_binding(binary),mujoco_version=mj.__version__))
    scene.pop('content_sha256_excluding_this_field',None)
    scene.update(model=_file_binding(xml),compiled_model_cache=_file_binding(out/'CACHE.json'),parent=_file_binding(parent/'SCENE.json'),native_floor=dict(collision_geom='native_floor',type='exact generated closed cuboid, same-volume native box',bounds=[lo.tolist(),hi.tolist()],source_triangles=12,source_unique_vertices=8,closed_edges_verified=True,maximum_bound_error_m=float(max(np.max(np.abs(center-half-lo)),np.max(np.abs(center+half-hi)))),different_floor_representation_from_S01_box=False),implementation=_file_binding(Path(__file__)),physics_steps=0)
    scene['native_collision_surfaces']=[v for v in scene['native_collision_surfaces'] if v['name']!='native_floor']
    scene['limitations']=['Official robot link collisions use original convex link meshes; furniture/object retain original rigid triangle shells.','Floor recognized as exact closed cuboid, same-volume conversion independently checked; not an added support plane.','New object mass/inertia assumptions remain fixed, not measured.']
    safe_save(out/'SCENE.json',scene)
    print(dict(model=key,exact_floor_box=True,nflex=model.nflex,physics_steps=0),flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
