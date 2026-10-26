"""Increase numerical contact storage only; preserve every physical parameter.

Actual original-init no-query replay proved CONTACTFULL19112 dropped contacts
at steps4..6 with 16MiB arena. 256MiB allows16x storage within16GiB worker cap;
this is declared before testing, with exact full physical-array comparison.
"""
from pathlib import Path
import xml.etree.ElementTree as E
import numpy as np
import mujoco as mj
from .common import ROOT,read_bound_json,safe_save,_file_binding
from .guard import plant_digest
from sage.experiments.embodied_transport_native_v1.model import load_model

def run(sid):
    key=sid+'_book';oldfolder=ROOT/'models_v2'/key;out=ROOT/'models_v3'/key;out.mkdir(parents=True,exist_ok=False)
    scene=read_bound_json(oldfolder/'SCENE.json');old=load_model(scene['model']['path'])
    x=E.parse(scene['model']['path']).getroot();size=x.find('size')
    if size is None:size=E.SubElement(x,'size')
    old_size=dict(size.attrib)
    size.attrib.pop('njmax',None);size.attrib.pop('nconmax',None);size.set('memory','256M')
    path=out/'model.xml';path.write_text(E.tostring(x,encoding='unicode'))
    model=mj.MjModel.from_xml_path(str(path))
    before=plant_digest(old);after=plant_digest(model)
    assert before==after, 'storage change altered frozen physical arrays'
    assert (model.nq,model.nv,model.nu,model.neq,model.nmocap)==(57,55,43,0,0)
    assert model.narena==256*1024**2 and old.narena==16*1024**2
    binary=out/'model.mjb';mj.mj_saveModel(model,str(binary),None)
    safe_save(out/'CACHE.json',dict(xml=_file_binding(path),binary=_file_binding(binary),mujoco_version=mj.__version__))
    scene.pop('content_sha256_excluding_this_field',None)
    scene.update(model=_file_binding(path),compiled_model_cache=_file_binding(out/'CACHE.json'),parent=_file_binding(oldfolder/'SCENE.json'),numerical_storage=dict(old_arena_bytes=int(old.narena),new_arena_bytes=int(model.narena),old_xml_size_attributes=old_size,physical_array_sha256=after.hex(),all_guarded_physical_arrays_and_options_exact=True,reason='CONTACTFULL in actual no-query original-init replay,19112 warning increments at first3colliding steps; reject old book physics for final qualification.',admission_requires='new original-init warmup probe with actual Data.warning counters all zero; final full successful replay also no numerical warnings'),implementation=_file_binding(Path(__file__)),physics_steps=0)
    safe_save(out/'SCENE.json',scene)
    # Source/target/robot/reference stay byte-identical; no resampling for repair.
    cdir=ROOT/'cases_v3'/key;cdir.mkdir(parents=True,exist_ok=False)
    import shutil
    oldcase=ROOT/'cases_v2'/key
    for name in ['CASE.json','REFERENCE.npz']:shutil.copyfile(oldcase/name,cdir/name)
    admission=read_bound_json(oldcase/'ADMISSION.json');admission.pop('content_sha256_excluding_this_field',None)
    admission.update(case=_file_binding(cdir/'CASE.json'),reference=_file_binding(cdir/'REFERENCE.npz'),scene=_file_binding(out/'SCENE.json'),static_only=True,numerical_admission_pending=True,parent=_file_binding(oldcase/'ADMISSION.json'),implementation=_file_binding(Path(__file__)))
    safe_save(cdir/'ADMISSION_STATIC.json',admission)
    print(dict(model=key,old_arena_mib=old.narena/1024**2,new_arena_mib=model.narena/1024**2,all_physics_exact=True,physics_steps=0),flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
