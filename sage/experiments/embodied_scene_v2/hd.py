"""Native recorded-state replay; texture restoration and bounded video chunks."""
from pathlib import Path
import json,time,gc
from xml.etree import ElementTree as ET
from .gpu_egl import bind
# Select the EGL vendor/device before any dependency imports MuJoCo/OpenGL.
EARLY_BINDING=bind()
import numpy as np
from PIL import Image
from sage.experiments.embodied_scene_v1.package import bound
from sage.experiments.embodied_scene_v1.mujoco_textures import base_color_for_mujoco, TEXTURE_CONVENTION
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb
from .config import ROOT,P1,write_json

SOURCE_GLB=ROOT.with_name('bedroom_composition_detail_20260909_v1')/'mainline_full_v2/physics/scene_physics_final.glb'

def prepare(task, output_root=None, episode_root=None, source_glb=None):
    import mujoco
    from .models import model_semantics
    destination=Path(output_root) if output_root is not None else ROOT
    episodes=Path(episode_root) if episode_root is not None else P1
    source_glb=Path(source_glb) if source_glb is not None else SOURCE_GLB
    out=destination/'presentation/models'/task;out.mkdir(parents=True,exist_ok=False)
    textures=destination/'presentation/textures_2048';textures.mkdir(exist_ok=True)
    if not (textures/'manifest.json').exists():
        document,binary=_read_glb(source_glb);rows=[]
        for i,mat in enumerate(document.get('materials',[])):
            pbr=mat.get('pbrMetallicRoughness',{})
            if 'baseColorTexture' not in pbr:continue
            image,source_size=base_color_for_mujoco(document,binary,pbr,2048)
            path=textures/f'texture_{i}.png';image.save(path)
            rows.append(dict(material=i,source_size=source_size,export_size=image.size,file=bound(path)))
        write_json(textures/'manifest.json',dict(source=bound(source_glb),textures=rows,texture_convention=TEXTURE_CONVENTION,obj_uv_policy='original TEXCOORD_0 unchanged',upscaled=False,pbr_scope='original base-color; normal/roughness maps still not reproduced'))
        del document,binary;gc.collect()
    cached=json.loads((textures/'manifest.json').read_text())
    if cached.get('texture_convention')!=TEXTURE_CONVENTION or cached['source']['sha256']!=bound(source_glb)['sha256']:
        raise ValueError('Texture cache has a different source/convention; use a new output root')
    for row in cached['textures']:
        if bound(row['file']['path'])['sha256']!=row['file']['sha256']:
            raise ValueError('Texture cache binding mismatch')
    episode=episodes/'experiments'/(task+'_repaired_v2')
    old=mujoco.MjModel.from_binary_path(str(episode/'model.mjb'));semantic=model_semantics(old);del old;gc.collect()
    root=ET.parse(episode/'model.xml').getroot();root.find('visual/global').set('offwidth','1440');root.find('visual/global').set('offheight','1080')
    for tex in root.findall('asset/texture'):
        if tex.get('name','').startswith('scene_tex_'):
            candidate=textures/(Path(tex.get('file')).name)
            if not candidate.exists():raise ValueError('Missing restored source texture')
            tex.set('file',str(candidate))
    ET.ElementTree(root).write(out/'model.xml',encoding='unicode')
    m=mujoco.MjModel.from_xml_path(str(out/'model.xml'))
    assert model_semantics(m)==semantic,'HD model changes physics/state layout'
    mujoco.mj_saveModel(m,str(out/'model.mjb'),None)
    write_json(out/'manifest.json',dict(source_episode=str(episode),source_model=bound(episode/'model.xml'),source_trajectory=bound(episode/'trajectory.npz'),native_model=bound(out/'model.xml'),compiled_model=bound(out/'model.mjb'),physics_and_state_layout_equal=True,textures=bound(textures/'manifest.json')))
    print('HD model prepared',task,flush=True)

def selection(times,fps=25,t0=None,t1=None):
    times=np.asarray(times,float)
    if np.any(np.diff(times)<=0):raise ValueError('Non-monotonic saved times')
    start=times[0] if t0 is None else max(times[0],t0)
    end=times[-1] if t1 is None else min(times[-1],t1)
    requested=np.arange(start,end+1e-9,1/fps)
    indices=np.searchsorted(times,requested)
    indices=np.minimum(indices,len(times)-1)
    previous=np.maximum(indices-1,0);indices=np.where(abs(times[previous]-requested)<abs(times[indices]-requested),previous,indices)
    if len(set(indices))!=len(indices) or np.max(abs(times[indices]-requested))>.01001:raise ValueError('Cannot sample requested FPS from saved states')
    return indices

def render(task,tag,indices=None,width=1440,height=1080,texture=2048,closeup=False,start_frame=0,frame_count=10,crf=16,png_only=False,t0=None,t1=None,output_root=None,episode_root=None,shadowmap_size=None):
    from .gpu_egl import bind,proof
    binding=EARLY_BINDING
    import mujoco
    import imageio.v2 as imageio
    destination=Path(output_root) if output_root is not None else ROOT
    episodes=Path(episode_root) if episode_root is not None else P1
    out=destination/'presentation'/tag;out.mkdir(parents=True,exist_ok=False);began=time.monotonic()
    source=episodes/'experiments'/(task+'_repaired_v2')
    modeldir=destination/'presentation/models'/task if texture==2048 else source
    if texture==2048:
        manifest=json.loads((modeldir/'manifest.json').read_text())
        texture_manifest=Path(manifest['textures']['path'])
        if bound(texture_manifest)['sha256']!=manifest['textures']['sha256'] or json.loads(texture_manifest.read_text()).get('texture_convention')!=TEXTURE_CONVENTION:
            raise ValueError('HD model requires the corrected, bound texture convention')
        if bound(modeldir/'model.mjb')['sha256']!=manifest['compiled_model']['sha256']:
            raise ValueError('HD model binding mismatch')
    m=mujoco.MjModel.from_binary_path(str(modeldir/'model.mjb'));d=mujoco.MjData(m)
    m.vis.global_.offwidth=max(width,1440);m.vis.global_.offheight=max(height,1080)
    if shadowmap_size is not None:
        if shadowmap_size not in (1024,2048,4096,8192):raise ValueError('Unsupported bounded shadow map size')
        m.vis.quality.shadowsize=shadowmap_size
    records=np.load(source/'trajectory.npz');states=records['state'];mask=mujoco.mjtState(int(records['state_spec']))
    times=states[:,0]
    selected=selection(times,t0=t0,t1=t1)
    indices=selected[start_frame:start_frame+frame_count] if indices is None else np.asarray(indices,int)
    camera=mujoco.MjvCamera();camera.lookat[:]=[2.8,2.5,.5] if task=='navigate' else [.62,1.5,1.0]
    camera.distance=8.6 if task=='navigate' else (1.18 if closeup else 2.35)
    if closeup:camera.lookat[:]=[.77,1.4,1.0]
    camera.azimuth=130 if task=='navigate' else 150;camera.elevation=-47 if task=='navigate' else -25
    opt=mujoco.MjvOption();opt.geomgroup[:]=[0,1,1,0,0,0];opt.sitegroup[:]=0
    for i in range(m.ngeom):
        if mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,i)=='robot_mount':m.geom_group[i]=1
    renderer=mujoco.Renderer(m,height=height,width=width);backend=proof(binding)
    write_json(out/'backend.json',backend)
    load_s=time.monotonic()-began;frames=[];writer=None
    if not png_only:writer=imageio.get_writer(out/'chunk.mp4',fps=25,codec='libx264',pixelformat='yuv420p',macro_block_size=1,ffmpeg_params=['-crf',str(crf),'-preset','medium','-movflags','+faststart'],quality=None)
    try:
        for n,index in enumerate(indices):
            frame_start=time.monotonic();mujoco.mj_setState(m,d,states[index],mask);mujoco.mj_forward(m,d)
            renderer.update_scene(d,camera=camera,scene_option=opt);rgb=renderer.render().copy()
            if writer is not None:writer.append_data(rgb)
            if png_only or n in (0,len(indices)//2,len(indices)-1):Image.fromarray(rgb).save(out/f'frame_{start_frame+n:05d}.png')
            frames.append(dict(frame=start_frame+n,state_index=int(index),time=float(d.time),phase=str(records['phase'][index]),wall_seconds=time.monotonic()-frame_start))
    finally:
        if writer is not None:writer.close()
        renderer.close()
    write_json(out/'manifest.json',dict(task=task,source_episode=str(source),source_trajectory=bound(source/'trajectory.npz'),source_model=bound(modeldir/'model.mjb'),width=width,height=height,fps=25,texture_cap=texture,closeup=closeup,crf=crf,shadowmap_size=int(m.vis.quality.shadowsize),offscreen_samples=int(m.vis.quality.offsamples),physical_steps=0,frames=frames,total_selected_frames=len(selected),load_seconds=load_s,wall_seconds=time.monotonic()-began,backend=backend,camera=dict(lookat=camera.lookat.tolist(),distance=camera.distance,azimuth=camera.azimuth,elevation=camera.elevation),no_interpolation=True,native_render=True))
    print('Rendered',tag,len(frames),'frames in',round(time.monotonic()-began,2),flush=True)

def pilot(task):
    source=P1/'experiments'/(task+'_repaired_v2');rec=np.load(source/'trajectory.npz');times=rec['state'][:,0]
    moments=[times[0],times[len(times)//2],times[-1]] if task=='navigate' else [5.5,8.,15.5]
    idx=[int(np.argmin(abs(times-t))) for t in moments]
    for width,height,texture in [(480,360,512),(1440,1080,512),(1440,1080,2048)]:
        render(task,f'pilot_v2/{task}_{width}_{texture}',indices=idx,width=width,height=height,texture=texture,png_only=True)
