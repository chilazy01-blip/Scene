"""Native evidence frames for fixed-ID round-two pairs, bound to real states."""
from .gpu_egl import bind,proof
BINDING=bind()
from pathlib import Path
from copy import deepcopy
from xml.etree import ElementTree as ET
import json,gc
import mujoco
import numpy as np
from PIL import Image,ImageDraw
from .config import ROOT,write_json
from .models import make_task,model_semantics
from sage.experiments.embodied_scene_v1.package import bound

def frames(episode,tag):
    c=json.loads((episode/'request.json').read_text());c['physics_only']=False
    out=ROOT/'presentation/round2_evidence'/tag;out.mkdir(parents=True,exist_ok=False)
    modeldir=ROOT/'presentation/round2_models'/tag
    make_task(c,modeldir)
    root=ET.parse(modeldir/'model.xml').getroot()
    for texture in root.findall('asset/texture'):
        if texture.get('name','').startswith('scene_tex_'):texture.set('file',str(ROOT/'presentation/textures_2048'/Path(texture.get('file')).name))
    ET.ElementTree(root).write(modeldir/'model.xml',encoding='unicode')
    m=mujoco.MjModel.from_xml_path(str(modeldir/'model.xml'))
    original=json.loads((episode/'model_identity.json').read_text())['semantics'];assert model_semantics(m)==original
    d=mujoco.MjData(m);rec=np.load(episode/'trajectory.npz');states=rec['state'];times=states[:,0];mask=mujoco.mjtState(int(rec['state_spec']))
    renderer=mujoco.Renderer(m,width=1440,height=1080);backend=proof(BINDING)
    camera=mujoco.MjvCamera();camera.lookat[:]=[.67,1.5,1.05];camera.distance=2.3;camera.azimuth=150;camera.elevation=-25
    opt=mujoco.MjvOption();opt.geomgroup[:]=[0,1,1,0,0,0];opt.sitegroup[:]=0
    for i in range(m.ngeom):
        if mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,i)=='robot_mount':m.geom_group[i]=1
    rows=[]
    try:
        for target in [5.5,8.,15.5]:
            index=int(np.argmin(abs(times-target)));mujoco.mj_setState(m,d,states[index],mask);mujoco.mj_forward(m,d)
            renderer.update_scene(d,camera=camera,scene_option=opt);rgb=renderer.render().copy();path=out/f't{target:.1f}.png';Image.fromarray(rgb).save(path)
            rows.append(dict(time_s=float(d.time),state_index=index,phase=str(rec['phase'][index]),image=bound(path)))
    finally:renderer.close()
    write_json(out/'manifest.json',dict(source_result=bound(episode/'result.json'),source_trajectory=bound(episode/'trajectory.npz'),source_model=bound(episode/'model.mjb'),visual_model=bound(modeldir/'model.xml'),physics_semantics_equal_before_transfer=True,frames=rows,backend=backend,native_size=[1440,1080],texture_cap=2048))
    return rows

def build():
    pairs=[];groups=json.loads((ROOT/'REPAIR_GROUPS.json').read_text())
    for split in ['development','holdout']:
        available=[g for g in groups if g['config']['split']==split]
        if not available:continue
        group=available[0];comparison=json.loads((ROOT/'repairs'/group['group_id']/'result.json').read_text())
        method=next((m for m in comparison['methods'] if m['method']=='D' and m['selected'] is not None),None)
        if method is None:method=next((m for m in comparison['methods'] if m['method']=='G' and m['selected'] is not None),None)
        if method is None:continue
        before=Path(group['episode']);selected=method['selected'];after=ROOT/'experiments'/f"repair__{group['group_id']}__{method['method']}__candidate{selected['index']}"
        pairs.append(dict(label=group['group_id'],split=split,stratum=group['stratum'],before=str(before),after=str(after),scope='I0 selected candidate, not unseen initialization validation',method=method['method']))
    if not pairs:
        for path in sorted((ROOT/'experiments').glob('L*__pick_place__C1/result.json')):
            r=json.loads(path.read_text())
            if not r['success'] and (path.parent/'trajectory.npz').exists():
                pairs.append(dict(label='matched_failure',split=r['task']['split'],stratum='natural',before=str(path.parent.with_name(path.parent.name.replace('__C1','__C0'))),after=str(path.parent),scope='Same initialization C0/C1 matched failure; no repair gain claimed',method='C0_vs_C1'));break
    for pi,pair in enumerate(pairs[:2]):
        images=[]
        for side in ['before','after']:
            images.append(frames(Path(pair[side]),f'pair{pi}_{side}'));gc.collect()
        sheet=Image.new('RGB',(1440,800),'white');draw=ImageDraw.Draw(sheet)
        for side,rows in enumerate(images):
            for j,row in enumerate(rows):
                im=Image.open(row['image']['path']);im.thumbnail((480,360));sheet.paste(im,(480*j,400*side));draw.text((480*j+8,400*side+365),f'{"before" if side==0 else "after"} | {row["time_s"]:.2f}s',fill='black')
        sheet.save(ROOT/'presentation/round2_evidence'/f'pair{pi}_sheet.jpg',quality=94)
    write_json(ROOT/'presentation/round2_evidence/PAIRS.json',pairs[:2])
    print('Round-two fixed-ID native evidence pairs',len(pairs[:2]),flush=True)
