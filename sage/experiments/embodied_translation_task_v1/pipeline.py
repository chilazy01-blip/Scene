"""One public generator call, then full-scene and two-pose binding."""
from pathlib import Path
import subprocess,sys,time,traceback
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_task_scene_v1.semantic import validate_roles
from sage.experiments.embodied_tool_task_v1.verify import verify
from .package import build
from .observation import observe


def bind(config,protocol_path,name,stage):
    config=Path(config);protocol_path=Path(protocol_path);deps=[]
    for directory in ['embodied_task_scene_v1','embodied_task_generation_v1','embodied_task_clearance_v1','embodied_tool_task_v1',
        'embodied_simdata_v0','embodied_scene_quality_v1','embodied_scene_quality_v2','embodied_planner_m2_v2','embodied_scene_bridge']:
        deps.extend(Path(__file__).parent.parent.joinpath(directory).glob('*.py'))
    extra={'pregen':reference(protocol_path.parent.parent/'pregen/RESULT.json')}
    if stage=='robot':extra['stability']=reference(protocol_path.parent.parent/'evidence/STABILITY.json')
    write_new(config/name,dict(schema='orientation-preserving-task-binding/v1',stage=stage,config=str(config.resolve()),
        request=read(config/'request.json'),protocol=reference(protocol_path),extra=extra,
        files={str(p):reference(p) for p in sorted(config.rglob('*')) if p.is_file() and '__pycache__' not in str(p)},
        implementation={str(p):reference(p) for p in sorted(set(deps+list(Path(__file__).parent.glob('*.py'))))},
        qualified_collection=False,qualified_export=False))


def run(config,protocol_path):
    config=Path(config);protocol_path=Path(protocol_path);p=read(protocol_path);request=read(config/'request.json')
    require(request in p['requests'],'unregistered_request');require(not (config/'GENERATION_STARTED.json').exists(),'generation_slot_used')
    require(read(protocol_path.parent.parent/'pregen/RESULT.json')['passed'],'pregen_rejected')
    args=[sys.executable,'-m','sage.experiments.codex_trellis_scene_v2.cli','--prompt-file',str(config/'prompt.txt'),
        '--furnishing-config',str(config/'furnishing.json'),'--output-dir',str(config/'generator'),'--profile','development',
        '--room-type','study','--window-wall','north','--expander','rules','--planner','rules','--no-codex-repair','--repair-iterations','2',
        '--asset-mode','reuse','--asset-library-manifest',str(config/'library.json'),'--seed',str(request['seed']),
        '--assemble','--no-render-preview','--no-scene-render-acceptance','--no-mujoco-check']
    write_new(config/'GENERATION_STARTED.json',dict(at=time.time(),arguments=args));result=dict(generation_attempts=1,new_physics_steps=0,scene_prerequisites_passed=False)
    try:
        done=subprocess.run(args,check=False,timeout=240);write_new(config/'GENERATION_RESULT.json',dict(returncode=done.returncode));require(done.returncode==0,'generator_failed')
        plan=read(config/'generator/layout_plan_final.json');validate_roles(plan['objects'],read(config/'roles.json'),read(config/'expected_counts.json'))
        require(len(plan['objects'])==sum(read(config/'expected_counts.json').values()),'extra_scene_object')
        require(read(config/'generator/run_summary.json')['profile_complete'] and read(config/'generator/validation_final.json')['ok'],'generation_not_accepted')
        result['generation_passed']=True
        task=build(config,p);scene=verify(config/'package',p);start=np.array(task['start_pose_z_up']);goal=np.array(task['goal_pose_z_up']);support=np.array(task['support_pose'])
        delta=(goal[:3,3]-start[:3,3])@support[:3,:3]
        require(np.allclose(start[:3,:3],goal[:3,:3],rtol=0,atol=1e-9),'orientation_changed')
        require(np.allclose(delta[:2],p['translation']['goal_offset_support_xy_m'],rtol=0,atol=1e-9),'translation_changed')
        scene['translation_support_m']=delta.tolist();scene['orientation_preserved']=True;write_new(config/'SCENE_VERIFIED.json',scene)
        camera=observe(config,p,dict(passed=False))
        result.update(status='constructed',scene_verified=scene['passed'],geometry_passed=task['geometry_passed'],observation_passed=camera['passed'],
            scene_prerequisites_passed=bool(scene['passed'] and task['geometry_passed'] and camera['passed']))
    except BaseException as exc:result.update(status='construction_error',error=str(exc),traceback=traceback.format_exc())
    write_new(config/'CONSTRUCTION.json',result);bind(config,protocol_path,'SCENE_BINDING.json','scene');print(result,flush=True);return result
