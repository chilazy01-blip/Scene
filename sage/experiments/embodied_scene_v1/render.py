"""Render recorded integration states; RGB/depth/IDs share exact poses and time."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
from pathlib import Path
import json
import time
import numpy as np
import mujoco
from PIL import Image,ImageDraw
import imageio.v2 as imageio
from .package import write_json,bound
from .cameras import canonicalize_stretch_cameras


def render_episode(episode,output,fps=10):
    episode,output=Path(episode),Path(output);output.mkdir(parents=True,exist_ok=False)
    result=json.loads((episode/'result.json').read_text());task=result['task']['task'];started=time.monotonic()
    if result['task'].get('physics_only'):raise ValueError('Render the full visual episode; physics-only has no room RGB')
    model=(mujoco.MjModel.from_binary_path(str(episode/'model.mjb')) if (episode/'model.mjb').exists() else mujoco.MjModel.from_xml_path(str(episode/'model.xml')))
    optical_correction=canonicalize_stretch_cameras(model) if task=='navigate' else []
    data=mujoco.MjData(model);record=np.load(episode/'trajectory.npz',allow_pickle=False)
    states=record['state'];mask=mujoco.mjtState(int(record['state_spec']))
    camera=mujoco.MjvCamera()
    camera.lookat[:]=[2.8,2.5,.5] if task=='navigate' else [.62,1.5,1.0]
    camera.distance=8.6 if task=='navigate' else 2.35
    camera.azimuth=130 if task=='navigate' else 150;camera.elevation=-47 if task=='navigate' else -25
    option=mujoco.MjvOption();option.geomgroup[:]=[0,1,1,0,0,0];option.sitegroup[:]=0
    # Only rendering groups change; no simulation step or collision flags change.
    for i in range(model.ngeom):
        if mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i)=='robot_mount':model.geom_group[i]=1
    sensor_option=mujoco.MjvOption();sensor_option.geomgroup[:]=[0,1,1,0,1,0];sensor_option.sitegroup[:]=0
    robotcamera='camera_rgb' if task=='navigate' else 'eye_in_hand'
    camid=model.camera(robotcamera).id
    owners={};geoms={};owner_ids={};mapping={0:'background'}
    for g in range(model.ngeom):
        b=model.geom_bodyid[g]
        while model.body_parentid[b]!=0:b=model.body_parentid[b]
        owner=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,b) or 'architecture'
        if owner not in owner_ids:owner_ids[owner]=len(owner_ids)+1;mapping[owner_ids[owner]]=owner
        owners[g]=owner_ids[owner];geoms[g]=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g)
    renderer=mujoco.Renderer(model,height=360,width=480)
    writer=imageio.get_writer(output/'rollout.mp4',fps=fps,codec='libx264',quality=8,macro_block_size=1)
    frames=[];observations=[];tiles=[]
    # Recorded rate is 50 Hz. Sampling is explicit, not motion interpolation.
    stride=max(1,round(50/fps));selected=list(range(0,len(states),stride))
    tile_indices=set(np.linspace(0,len(selected)-1,6).astype(int))
    try:
        for n,index in enumerate(selected):
            mujoco.mj_setState(model,data,states[index],mask);mujoco.mj_forward(model,data)
            renderer.update_scene(data,camera=camera,scene_option=option)
            rgb=renderer.render().copy();writer.append_data(rgb)
            frames.append(dict(frame=n,state_index=index,time=float(data.time),phase=str(record['phase'][index])))
            if n in tile_indices:
                file=f'frame_{n:04d}.png';Image.fromarray(rgb).save(output/file);tiles.append((rgb,float(data.time),str(record['phase'][index])))
            if n % fps == 0:
                renderer.update_scene(data,camera=robotcamera,scene_option=sensor_option)
                robot_rgb=renderer.render().copy()
                renderer.enable_depth_rendering();depth=renderer.render().copy();renderer.disable_depth_rendering()
                renderer.enable_segmentation_rendering();seg=renderer.render().copy();renderer.disable_segmentation_rendering()
                ids=np.zeros(seg.shape[:2],dtype=np.uint16)
                for g in np.unique(seg[:,:,0]):
                    if g>=0:ids[(seg[:,:,0]==g)&(seg[:,:,1]==int(mujoco.mjtObj.mjOBJ_GEOM))]=owners[int(g)]
                stem=f'sensor_{n:04d}';Image.fromarray(robot_rgb).save(output/(stem+'.png'))
                np.savez_compressed(output/(stem+'.npz'),depth_m=depth,instance_id=ids,geom_segmentation=seg,time=data.time,
                    camera_position_world=data.cam_xpos[camid],camera_rotation_world=data.cam_xmat[camid].reshape(3,3))
                observations.append(dict(frame=n,state_index=index,time=float(data.time),rgb=stem+'.png',depth_and_instance=stem+'.npz',camera=robotcamera))
            if n%50==0:print(task,'render',n,'/',len(selected),flush=True)
    finally:writer.close();renderer.close()
    sheet=Image.new('RGB',(3*480,2*390),'white');draw=ImageDraw.Draw(sheet)
    for i,(rgb,t,phase) in enumerate(tiles):
        x=(i%3)*480;y=(i//3)*390;sheet.paste(Image.fromarray(rgb),(x,y));draw.text((x+8,y+366),f'{t:.2f} s  {phase}',fill='black')
    sheet.save(output/'contact_sheet.jpg',quality=92)
    focal=360/(2*np.tan(np.deg2rad(model.cam_fovy[camid])/2))
    write_json(output/'observation_manifest.json',dict(source_episode=bound(episode/'result.json'),source_trajectory=bound(episode/'trajectory.npz'),
        success=result['success'],optical_frame_correction=optical_correction,frames=frames,robot_observations=observations,instance_ids=mapping,geom_ids=geoms,
        camera_intrinsics=dict(width=480,height=360,fx=focal,fy=focal,cx=240,cy=180),camera_axes='local +X right, +Y up, -Z forward',
        semantics='RGB/depth/instance IDs from one mj_forward of the exact saved integration state; no trajectory interpolation',
        fps=fps,render_wall_seconds=time.monotonic()-started,visual_scope='original scene triangles, base-color textures capped at 512px; PBR normal/roughness maps are not reproduced',
        presentation_cutaway='south/east wall visuals hidden only in external overview; robot sensors see all walls; collision remains enabled'))
    print('Rendered',output,flush=True)
