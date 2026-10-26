"""Load a pinned native camera only after recomputing its visibility evidence."""
import argparse,json
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import bound,read,require,Rejected
from .visibility import check_view,camera_pose


def load_checked_camera(record_path,expected_sha256,name,purpose='target_visibility_inspection',model_path=None):
    require(purpose=='target_visibility_inspection','unsupported_purpose:'+purpose)
    record=read(bound(record_path,expected_sha256));require(record['schema']=='goal-camera-visibility/v1','schema')
    for ref in [record[k] for k in ['task','manifest','layout','protocol']]+list(record['implementation'].values()):bound(ref['path'],ref['sha256'])
    protocol=read(record['protocol']['path']);require(record['limits']==protocol['cameras'],'camera_limits_changed')
    require(record['robot_present'] is False and record['qualified_collection'] is False and record['qualified_export'] is False,'scope_changed')
    modelpath=bound(model_path or record['model']['path'],record['model']['sha256'])
    selected=[r for r in record['views'] if r['name']==name];require(len(selected)==1,'unknown_or_duplicate_camera');row=selected[0]
    score=check_view(row,record['limits']);require(score['passed'],'target_visibility_failed:'+name)
    import mujoco
    model=mujoco.MjModel.from_binary_path(str(modelpath));cid=model.camera(row['source_camera']).id
    require(cid==row['camera_id'] and model.cam_bodyid[cid]==0,'camera_identity')
    require(np.array_equal(model.cam_pos[cid],row['original_position']) and np.array_equal(model.cam_quat[cid],row['original_quaternion']),'camera_context_changed')
    task=read(record['task']['path']);manifest=read(record['manifest']['path'])
    names=[r['name'] for r in manifest['visuals'] if r['owner']==task['roles']['target_id']]
    require(names==row['target_geom_names'] and [model.geom(n).id for n in names]==row['target_geom_ids'],'target_identity')
    require(row['geom_object_type']==int(mujoco.mjtObj.mjOBJ_GEOM),'segmentation_type')
    rule=record['limits']['revised']
    if name==rule['name']:
        require(row['source_camera']==rule['source_camera'],'revision_source_camera')
        pos,quat=camera_pose(task['goal_pose_z_up'],read(record['layout']['path'])['room'],rule)
    else:
        require(name in record['limits']['existing'] and row['source_camera']==name,'unregistered_camera')
        pos,quat=model.cam_pos[cid].copy(),model.cam_quat[cid].copy()
    require(np.allclose(pos,row['position'],rtol=0,atol=1e-12) and np.allclose(quat,row['quaternion'],rtol=0,atol=1e-12),'camera_rule_mismatch')
    model.cam_pos[cid]=pos;model.cam_quat[cid]=quat
    return model,cid,score


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--record',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--camera',required=True);parser.add_argument('--purpose',default='target_visibility_inspection');parser.add_argument('--model')
    args=parser.parse_args()
    try:
        model,cid,score=load_checked_camera(args.record,args.sha256,args.camera,args.purpose,args.model)
        print(json.dumps(dict(loaded=True,camera_id=cid,position=model.cam_pos[cid].tolist(),quaternion=model.cam_quat[cid].tolist(),assessment=score,ngeom=model.ngeom)))
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps(dict(loaded=False,reason=str(exc))));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
