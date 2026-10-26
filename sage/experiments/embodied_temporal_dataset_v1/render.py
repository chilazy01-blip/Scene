from pathlib import Path
import hashlib,io,json,traceback
import numpy as np
import h5py
from PIL import Image
from .contract import arrays,statistics,source_evidence,SCHEMA
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,require,write_new,reference,bound
from sage.experiments.embodied_task_clearance_v1.visibility import assess,masks


def render(protocol_path,root):
    import mujoco
    from OpenGL.GL import glGetString,GL_VENDOR,GL_RENDERER
    from sage.experiments.embodied_velocity_reference_v1.entry import load
    protocol_path=Path(protocol_path);root=Path(root);p=read(protocol_path);limits=p['observation'];source_evidence(p)
    prepared=read(root/'evidence/PREPARE.json');a=arrays(bound(prepared['prepared']['path'],prepared['prepared']['sha256']))
    model,_=load(p['source_binding']['path'],p['source_binding']['sha256'],'controller_evaluation','V01');data=mujoco.MjData(model)
    cid=prepared['camera_id'];model.cam_pos[cid]=prepared['position'];model.cam_quat[cid]=prepared['quaternion']
    ids=prepared['target_geom_ids'];option=mujoco.MjvOption();option.geomgroup[:]=0;option.geomgroup[1]=1
    output=root/'candidate';path=output/'episode.h5';rows=[];rgb_count=seg_count=0
    write_new(output/'STARTED.json',dict(request_id=p['request_id'],attempt=1,registered_frames=351,new_physics_steps=0))
    failure=None;backend=vendor=None
    try:
        with h5py.File(path,'x') as f,mujoco.Renderer(model,height=limits['height'],width=limits['width'],max_geom=max(10000,model.ngeom*2)) as renderer:
            vendor=glGetString(GL_VENDOR).decode();backend=glGetString(GL_RENDERER).decode();require('mesa' in vendor.lower() and 'llvmpipe' in backend.lower(),'cpu_renderer_required')
            f.attrs.update(schema=SCHEMA,request_id=p['request_id'],split='development',physical_episode_success=True,state_spec=prepared['state_spec'],frames_written=0,
                action_semantics='7 joint positions rad; 7 desired velocities rad/s; 1 gripper position m',reference_sample=p['action']['reference_sample'],
                controller_formula=p['action']['controller_formula'],production_qualified=False,source_raw_sha256=p['source_raw']['sha256'])
            fields={'action':a['action'],'observation/proprio':a['proprio'],'observation/time':a['times'],'observation/step':a['steps'],
                'audit/integration_state':a['states'],'audit/actual_actuator_control':a['controls'],'audit/phase_ids':a['phase_ids'],
                'audit/observation_phase':a['observation_phase'],'audit/substep_start':a['substep_start'],'audit/substep_end':a['substep_end']}
            for name,value in fields.items():f.create_dataset(name,data=value,compression='gzip',compression_opts=1)
            f.create_dataset('observation/rgb',shape=(351,limits['height'],limits['width'],3),dtype='uint8',chunks=(1,limits['height'],limits['width'],3),compression='gzip',compression_opts=1)
            for name in ['full_segmentation','target_only_segmentation']:
                f.create_dataset('audit/'+name,shape=(351,limits['height'],limits['width'],2),dtype='int32',chunks=(1,limits['height'],limits['width'],2),compression='gzip',compression_opts=1)
            previews=output/'previews';previews.mkdir();seen=set()
            with (output/'FRAME_ATTEMPTS.jsonl').open('x') as attempts:
                for i,(step,state) in enumerate(zip(a['steps'],a['states'])):
                    attempts.write(json.dumps(dict(frame=i,step=int(step),status='started'))+'\n');attempts.flush()
                    mujoco.mj_setState(model,data,state,prepared['state_spec']);mujoco.mj_forward(model,data)
                    before=np.empty(mujoco.mj_stateSize(model,prepared['state_spec']));mujoco.mj_getState(model,data,before,prepared['state_spec'])
                    renderer.disable_segmentation_rendering();renderer.update_scene(data,camera=cid,scene_option=option);rgb=renderer.render().copy();rgb_count+=1
                    mean,std=statistics(rgb);require(np.all(std>0),'constant_rgb_channel')
                    png=io.BytesIO();Image.fromarray(rgb).save(png,format='PNG');png.seek(0);require(np.array_equal(np.asarray(Image.open(png)),rgb),'png_roundtrip')
                    renderer.enable_segmentation_rendering();renderer.update_scene(data,camera=cid,scene_option=option);full=renderer.render().copy();seg_count+=1
                    groups=model.geom_group.copy()
                    try:
                        model.geom_group[:]=0;model.geom_group[ids]=1;renderer.update_scene(data,camera=cid,scene_option=option);alone=renderer.render().copy();seg_count+=1
                    finally:model.geom_group[:]=groups
                    visible,unoccluded=masks(full,alone,ids,prepared['geom_object_type']);score=assess(visible,unoccluded,limits)
                    score['scope']='one saved full-robot trajectory frame; all registered frames required'
                    f['observation/rgb'][i]=rgb;f['audit/full_segmentation'][i]=full;f['audit/target_only_segmentation'][i]=alone
                    require(np.array_equal(f['observation/rgb'][i],rgb) and np.array_equal(f['audit/full_segmentation'][i],full) and np.array_equal(f['audit/target_only_segmentation'][i],alone),'hdf5_frame_roundtrip')
                    after=np.empty_like(before);mujoco.mj_getState(model,data,after,prepared['state_spec']);require(np.array_equal(before,after),'renderer_changed_state')
                    phase=prepared['phase_names'][int(a['observation_phase'][i])]
                    row=dict(frame=i,step=int(step),time_s=float(data.time),phase=phase,assessment=score,channel_mean=mean.tolist(),channel_std=std.tolist(),rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
                    rows.append(row);f.attrs['frames_written']=i+1
                    if phase not in seen or i==350:
                        (previews/(f'{i:03d}_{phase}.png')).write_bytes(png.getvalue());seen.add(phase)
                    if i%25==0 or i==350:
                        f.flush();print(json.dumps(dict(frame=i,phase=phase,visible=score['visible_pixels'],fraction=score['visible_fraction'],passed=score['passed'])),flush=True)
                    attempts.write(json.dumps(dict(frame=i,step=int(step),status='completed',visibility_passed=score['passed']))+'\n');attempts.flush()
            require(len(seen)==9,'phase_coverage')
            focal=.5*limits['height']/np.tan(np.deg2rad(prepared['fovy_deg'])*.5)
            camera_to_world=np.eye(4);camera_to_world[:3,:3]=data.cam_xmat[cid].reshape(3,3);camera_to_world[:3,3]=data.cam_xpos[cid]
            write_new(output/'CAMERA.json',dict(camera_id=cid,position=prepared['position'],quaternion_wxyz=prepared['quaternion'],fovy_deg=prepared['fovy_deg'],
                intrinsics=[[focal,0,limits['width']/2],[0,focal,limits['height']/2],[0,0,1]],mujoco_camera_to_world=camera_to_world.tolist(),optical_camera_to_world=(camera_to_world@np.diag([1.,-1.,-1.,1.])).tolist(),
                image_origin=prepared['image_origin'],mujoco_axes=prepared['optical_axes'],optical_axes='X right, Y down, Z forward',pixel_center_convention=prepared['pixel_center_convention'],
                width=limits['width'],height=limits['height'],vendor=vendor,renderer=backend,new_physics_steps=0))
    except BaseException as exc:
        failure=dict(error=str(exc),traceback=traceback.format_exc())
    phases={name:dict(frames=sum(r['phase']==name for r in rows),failed_frames=sum(r['phase']==name and not r['assessment']['passed'] for r in rows)) for name in prepared['phase_names']}
    value=dict(schema='temporal-render-evidence/v1',complete=len(rows)==351 and failure is None,passed=len(rows)==351 and failure is None and all(r['assessment']['passed'] for r in rows),
        request_id=p['request_id'],frames=rows,phase_coverage=phases,failed_frames=[r['frame'] for r in rows if not r['assessment']['passed']],failure=failure,
        renderer=backend,vendor=vendor,new_physics_steps=0,new_physical_attempts=0,rgb_renders=rgb_count,segmentation_renders=seg_count,
        protocol=reference(protocol_path),prepared=reference(root/'evidence/PREPARE.json'),hdf5=reference(path) if path.exists() else None)
    write_new(output/'RENDER.json',value)
    if failure:raise RuntimeError('render_failed:'+failure['error'])
    from .dataset import create_binding
    create_binding(protocol_path,root/'evidence/PREPARE.json',output)
    return value
