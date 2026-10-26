"""Fixed goal-view evidence. Segmentation visibility is not export qualification."""
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference,bound


def assess(visible,unoccluded,limits):
    require(visible.dtype==bool and unoccluded.dtype==bool,'mask_dtype')
    require(visible.shape==unoccluded.shape==(limits['height'],limits['width']),'mask_shape')
    require(np.all(~visible|unoccluded),'visible_outside_target_projection')
    count=int(visible.sum());total=int(unoccluded.sum());fraction=count/total if total else 0.
    passed=(count>=limits['minimum_visible_target_pixels'] and total>=limits['minimum_unoccluded_target_pixels']
        and fraction>=limits['minimum_visible_fraction'])
    return dict(passed=passed,visible_pixels=count,unoccluded_pixels=total,visible_fraction=fraction,
        state='pass' if passed else 'fail',scope='this goal frame only; no robot or temporal coverage')


def camera_pose(goal,room,rule):
    target=np.asarray(goal)[:3,3];direction=np.array([room['width']/2,room['length']/2])-target[:2]
    norm=np.linalg.norm(direction);direction=direction/norm if norm>1e-12 else np.array([-1.,-1.])/np.sqrt(2)
    eye=target.copy();eye[:2]+=rule['horizontal_distance_m']*direction;eye[2]+=rule['height_above_target_m']
    margin=rule['wall_margin_m'];eye=np.clip(eye,[margin]*3,np.array([room['width'],room['length'],room['height']])-margin)
    look=target.copy();look[2]+=rule['look_at_z_offset_m'];forward=look-eye;forward/=np.linalg.norm(forward)
    right=np.cross(forward,[0.,0.,1.]);right/=np.linalg.norm(right);up=np.cross(right,forward)
    quat=Rotation.from_matrix(np.column_stack([right,up,-forward])).as_quat()[[3,0,1,2]]
    return eye,quat


def masks(full,alone,target_ids,geom_type):
    return tuple((a[:,:,1]==geom_type)&np.isin(a[:,:,0],target_ids) for a in [full,alone])


def check_view(row,limits):
    ref=row['segmentation'];path=bound(ref['path'],ref['sha256'])
    with np.load(path,allow_pickle=False) as raw:
        visible,alone=masks(raw['full'],raw['target_only'],row['target_geom_ids'],row['geom_object_type'])
        score=assess(visible,alone,limits)
    require(score==row['assessment'],'visibility_summary_mismatch')
    return score


def diagnose(protocol_path,output):
    import mujoco
    from PIL import Image
    from OpenGL.GL import glGetString,GL_RENDERER,GL_VENDOR
    p=read(protocol_path);limits=p['cameras'];config=Path(p['config']);package=config/'package'
    output=Path(output);output.mkdir(exist_ok=False)
    task=read(package/'task.json');manifest=read(package/'scene_manifest.json');layout=read(config/'generator/layout_plan_final.json')
    model=mujoco.MjModel.from_binary_path(str(package/'model_goal.mjb'));data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    names=[r['name'] for r in manifest['visuals'] if r['owner']==task['roles']['target_id']]
    target_ids=[model.geom(n).id for n in names];require(bool(target_ids),'target_visuals_missing')
    require(all(model.geom_group[i]==1 for i in target_ids),'target_visual_group')
    rows=[];option=mujoco.MjvOption();option.geomgroup[:]=0;option.geomgroup[1]=1
    rule=limits['revised'];revisedpos,revisedquat=camera_pose(task['goal_pose_z_up'],layout['room'],rule)
    with mujoco.Renderer(model,height=limits['height'],width=limits['width'],max_geom=max(10000,model.ngeom*2)) as renderer:
        vendor=glGetString(GL_VENDOR).decode();backend=glGetString(GL_RENDERER).decode()
        require('llvmpipe' in backend.lower() and 'mesa' in vendor.lower(),'registered_cpu_renderer_required')
        for name in limits['existing']+[rule['name']]:
            source=rule['source_camera'] if name==rule['name'] else name;cid=model.camera(source).id
            require(model.cam_bodyid[cid]==0,'camera_must_be_world_fixed')
            originalpos=model.cam_pos[cid].copy();originalquat=model.cam_quat[cid].copy()
            if name==rule['name']:model.cam_pos[cid]=revisedpos;model.cam_quat[cid]=revisedquat
            mujoco.mj_forward(model,data)
            renderer.disable_segmentation_rendering();renderer.update_scene(data,camera=source,scene_option=option);rgb=renderer.render().copy()
            require(rgb.shape==(limits['height'],limits['width'],3) and rgb.dtype==np.uint8,'rgb_shape_dtype')
            x=rgb.astype(np.float64);mean=x.mean((0,1));std=x.std((0,1))
            require(np.allclose(std,np.sqrt(np.mean((x-mean)**2,axis=(0,1))),rtol=0,atol=1e-10),'rgb_std_reference')
            png=output/(name+'.png');Image.fromarray(rgb).save(png);require(np.array_equal(np.asarray(Image.open(png)),rgb),'png_roundtrip')
            renderer.enable_segmentation_rendering();renderer.update_scene(data,camera=source,scene_option=option);full=renderer.render().copy()
            groups=model.geom_group.copy()
            try:
                model.geom_group[:]=0;model.geom_group[target_ids]=1
                renderer.update_scene(data,camera=source,scene_option=option);alone=renderer.render().copy()
            finally:model.geom_group[:]=groups
            geometry_type=int(mujoco.mjtObj.mjOBJ_GEOM);visible,unoccluded=masks(full,alone,target_ids,geometry_type)
            score=assess(visible,unoccluded,limits);rawpath=output/(name+'.npz');np.savez_compressed(rawpath,full=full,target_only=alone)
            row=dict(name=name,source_camera=source,camera_id=cid,original_position=originalpos.tolist(),original_quaternion=originalquat.tolist(),
                position=model.cam_pos[cid].tolist(),quaternion=model.cam_quat[cid].tolist(),target_geom_names=names,target_geom_ids=target_ids,
                geom_object_type=geometry_type,assessment=score,segmentation=reference(rawpath),rgb=reference(png),channel_mean=mean.tolist(),channel_std=std.tolist())
            write_new(output/(name+'.json'),row);rows.append(row);print(name,score,flush=True)
            model.cam_pos[cid]=originalpos;model.cam_quat[cid]=originalquat
    return dict(schema='goal-camera-visibility/v1',model=reference(package/'model_goal.mjb'),task=reference(package/'task.json'),
        manifest=reference(package/'scene_manifest.json'),layout=reference(config/'generator/layout_plan_final.json'),protocol=reference(protocol_path),
        implementation={str(f):reference(f) for f in sorted(Path(__file__).parent.glob('*.py'))},
        limits=limits,views=rows,renderer=backend,vendor=vendor,new_physics_steps=0,rgb_renders=len(rows),segmentation_renders=2*len(rows),
        robot_present=False,qualified_collection=False,qualified_export=False)
