"""Pinned start/goal visibility using the previously tested interior rule."""
from pathlib import Path
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_task_clearance_v1.visibility import camera_pose,assess,masks
from sage.experiments.embodied_task_scene_v1.robot import set_target


def observe(config,protocol,preflight,output_name='observations'):
    import mujoco
    from PIL import Image
    from OpenGL.GL import glGetString,GL_VENDOR,GL_RENDERER
    config=Path(config);package=config/'package';task=read(package/'task.json');manifest=read(package/'scene_manifest.json')
    limits=protocol['observation'];output=config/output_name;output.mkdir(exist_ok=False)
    path=package/('robot_mounted.xml' if preflight['passed'] else 'model.xml')
    model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model)
    cid=model.camera('overview').id;position,quat=camera_pose(task['goal_pose_z_up'],read(config/'generator/layout_plan_final.json')['room'],limits['rule'])
    model.cam_pos[cid]=position;model.cam_quat[cid]=quat
    names=[r['name'] for r in manifest['visuals'] if r['owner']==task['roles']['target_id']];ids=[model.geom(n).id for n in names]
    require(bool(ids),'target_visual_missing');bid=model.body(task['target_body']).id;qi=int(model.jnt_qposadr[model.body_jntadr[bid]])
    option=mujoco.MjvOption();option.geomgroup[:]=0;option.geomgroup[1]=1;rows=[]
    with mujoco.Renderer(model,height=limits['height'],width=limits['width'],max_geom=max(10000,model.ngeom*2)) as renderer:
        vendor=glGetString(GL_VENDOR).decode();backend=glGetString(GL_RENDERER).decode();require('mesa' in vendor.lower() and 'llvmpipe' in backend.lower(),'cpu_llvmpipe_required')
        for state in ['start','goal']:
            mujoco.mj_resetData(model,data);set_target(data,qi,np.asarray(task[state+'_pose_z_up']))
            if preflight['passed']:
                from sage.experiments.embodied_simdata_v0.controller import PandaController
                ctrl=PandaController(model,data);data.qpos[ctrl.qi]=ctrl.qhome if state=='start' else preflight['selected']['endpoints'][-1]['q']
                fi=[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']];data.qpos[fi]=[.04,-.04]
            mujoco.mj_forward(model,data)
            renderer.disable_segmentation_rendering();renderer.update_scene(data,camera=cid,scene_option=option);rgb=renderer.render().copy()
            require(rgb.dtype==np.uint8 and rgb.shape==(limits['height'],limits['width'],3),'rgb_layout')
            x=rgb.astype(np.float64);mean=x.mean((0,1));std=x.std((0,1));require(np.allclose(std,np.sqrt(np.mean((x-mean)**2,axis=(0,1))),rtol=0,atol=1e-10),'rgb_statistics')
            png=output/(state+'.png');Image.fromarray(rgb).save(png);require(np.array_equal(np.asarray(Image.open(png)),rgb),'png_roundtrip')
            renderer.enable_segmentation_rendering();renderer.update_scene(data,camera=cid,scene_option=option);full=renderer.render().copy();groups=model.geom_group.copy()
            try:
                model.geom_group[:]=0;model.geom_group[ids]=1;renderer.update_scene(data,camera=cid,scene_option=option);alone=renderer.render().copy()
            finally:model.geom_group[:]=groups
            typ=int(mujoco.mjtObj.mjOBJ_GEOM);visible,unoccluded=masks(full,alone,ids,typ);score=assess(visible,unoccluded,limits)
            raw=output/(state+'.npz');np.savez_compressed(raw,full=full,target_only=alone,qpos=data.qpos.copy())
            rows.append(dict(state=state,target_geom_names=names,target_geom_ids=ids,geom_object_type=typ,assessment=score,
                segmentation=reference(raw),rgb=reference(png),channel_mean=mean.tolist(),channel_std=std.tolist()))
            print('view',config.name,state,score,flush=True)
    value=dict(passed=all(r['assessment']['passed'] for r in rows),views=rows,model=reference(path),camera_id=cid,
        position=position.tolist(),quaternion=quat.tolist(),renderer=backend,vendor=vendor,robot_present=preflight['passed'],
        temporal_coverage_qualified=False,physics_steps=0,rgb_renders=2,segmentation_renders=4)
    write_new(output/'RESULT.json',value);return value
