"""Native loading that recomputes raw static and observation evidence by purpose."""
from pathlib import Path
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,require
from sage.experiments.embodied_task_clearance_v1.visibility import check_view
from .construction import clearance_gap


def check_robot(config,protocol):
    rule=read(config/'package/TOOL_RULE.json');limits=protocol['tool_construction'];task=read(config/'package/task.json')
    require([r['roll_degrees'] for r in rule['candidates']]==limits['grasp_roll_degrees'],'grasp_candidate_set')
    with np.load(bound(rule['raw']['path'],rule['raw']['sha256']),allow_pickle=False) as raw:
        for row in rule['candidates']:
            at_goal=np.asarray(task['goal_pose_z_up'])@np.linalg.inv(np.asarray(row['held_transform']));bounds={}
            for mode in ['closed','open']:
                for name in limits['tool_geoms']:
                    points=raw[mode+'__'+name]@at_goal[:3,:3].T+at_goal[:3,3];key=mode+':'+name
                    bounds[key]=np.array([points.min(0),points.max(0)])
                    require(np.allclose(bounds[key],row['tool_bounds_at_goal'][key],rtol=0,atol=1e-12),'tool_bounds_summary_mismatch')
            gap,_=clearance_gap(bounds,raw['support_bounds'],limits['clearance_margin_m'],limits['minimum_release_gap_m'])
            require(abs(gap-row['required_gap_m'])<1e-12,'tool_gap_summary_mismatch')
            require(row['in_task_range']==(gap<=limits['maximum_release_gap_m']),'tool_gap_range_mismatch')
    camera=read(config/'observations_robot/RESULT.json') if (config/'observations_robot/RESULT.json').exists() else read(config/'observations/RESULT.json');scores=[check_view(v,protocol['observation']) for v in camera['views']]
    robot=read(config/'package/PREFLIGHT.json');require(robot['passed']==(robot['selected'] is not None),'selected_candidate_mismatch')
    if robot['passed']:
        selected=robot['selected'];require(selected in robot['candidates'] and selected['status']=='preflight_passed','candidate_identity')
        require(selected['release_gap_m']<=limits['maximum_release_gap_m'],'release_gap_out_of_scope')
        phases=['pregrasp','grasp','close','lift','transfer','release','open','retreat']
        require([e['phase'] for e in selected['endpoints']]==phases and [p['phase'] for p in selected['paths']]==phases,'incomplete_robot_preflight')
        require(all(not e['violations'] and e['position_error_m']<=protocol['robot']['ik_position_tolerance_m'] and e['orientation_error_deg']<=protocol['robot']['ik_orientation_tolerance_deg'] for e in selected['endpoints']),'endpoint_failed')
        require(all(not p['violations'] and p['checked']==p['planned'] for p in selected['paths']),'path_failed')
    ready=bool(task['geometry_passed'] and robot['passed'] and all(s['passed'] for s in scores))
    return ready


def load(path,pin,purpose,request_id):
    require(purpose in ['inspection','candidate_stability','robot_execution'],'unsupported_purpose:'+purpose)
    record=read(bound(path,pin));require(record['schema']=='orientation-preserving-task-binding/v1','binding_schema')
    require(not record['qualified_collection'] and not record['qualified_export'],'production_scope_changed')
    protocol=read_ref(record['protocol']);require(record['request']['id']==request_id and record['request'] in protocol['requests'],'request_identity')
    for ref in list(record['files'].values())+list(record['implementation'].values())+list(record['extra'].values()):bound(ref['path'],ref['sha256'])
    config=Path(record['config']);result=read(config/'CONSTRUCTION.json')
    require(result['status']=='constructed' and read(config/'SCENE_VERIFIED.json')['passed'],'scene_not_constructed')
    camera=read(config/'observations/RESULT.json');scores=[check_view(v,protocol['observation']) for v in camera['views']]
    task=read(config/'package/task.json');pregen=read_ref(record['extra']['pregen'])
    scene_ready=bool(task['geometry_passed'] and pregen['passed'] and all(x['passed'] for x in scores))
    require(scene_ready==result['scene_prerequisites_passed'],'scene_summary_mismatch')
    ready=False;stable=None;robot=False
    if record['stage']=='robot':
        from .stability import recompute
        stable=recompute(record['extra']['stability']['path'],task,protocol)
        preflight=read(config/'package/PREFLIGHT.json')
        if (config/'package/TOOL_RULE.json').exists():robot=check_robot(config,protocol)
        else:require(not preflight['passed'] and preflight['selected'] is None,'missing_tool_rule')
        ready=bool(scene_ready and stable['passed'] and robot)
        require(ready==read(config/'TASK_RESULT.json')['ready_for_execution'],'execution_summary_mismatch')
    if purpose=='candidate_stability':require(scene_ready and record['stage']=='scene','scene_prerequisites_failed')
    if purpose=='robot_execution':require(record['stage']=='robot' and ready,'full_preflight_not_passed')
    import mujoco
    model=mujoco.MjModel.from_xml_path(str(config/'package'/('robot_mounted.xml' if purpose=='robot_execution' else 'model.xml')))
    return model,dict(scene_prerequisites_passed=scene_ready,ready_for_execution=ready,stability_passed=None if stable is None else stable['passed'],
        robot_preflight=robot,visibility=scores,qualified_collection=False,qualified_export=False)
