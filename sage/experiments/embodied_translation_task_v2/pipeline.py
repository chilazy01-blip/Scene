"""One public generator call, then full-scene and two-pose binding."""
from pathlib import Path
import subprocess,sys,time,traceback
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_task_scene_v1.semantic import validate_roles
from sage.experiments.embodied_tool_task_v1.verify import verify
from .package import build
from .observation import observe
from .request import validate_config,compare_generation


def bind(config,protocol_path,name,stage):
    config=Path(config);protocol_path=Path(protocol_path);deps=[]
    for directory in ['embodied_task_scene_v1','embodied_task_generation_v1','embodied_task_clearance_v1','embodied_tool_task_v1',
        'embodied_simdata_v0','embodied_scene_quality_v1','embodied_scene_quality_v2','embodied_planner_m2_v2','embodied_scene_bridge','codex_trellis_scene_v2']:
        deps.extend(Path(__file__).parent.parent.joinpath(directory).glob('*.py'))
    extra={'pregen':reference(protocol_path.parent.parent/'pregen/RESULT.json')}
    evidence=protocol_path.parent.parent/'evidence'
    if stage=='robot':extra['stability']=reference(evidence/('STABILITY_VERIFIED.json' if (evidence/'STABILITY_VERIFIED.json').exists() else 'STABILITY.json'))
    extra['construction']=reference(config/('CONSTRUCTION_VERIFIED.json' if (config/'CONSTRUCTION_VERIFIED.json').exists() else 'CONSTRUCTION.json'))
    write_new(config/name,dict(schema='orientation-preserving-task-binding/v2',stage=stage,config=str(config.resolve()),
        request=read(config/'request.json'),protocol=reference(protocol_path),extra=extra,
        files={str(p):reference(p) for p in sorted(config.rglob('*')) if p.is_file() and '__pycache__' not in str(p)},
        implementation={str(p):reference(p) for p in sorted(set(deps+list(Path(__file__).parent.glob('*.py'))))},
        qualified_collection=False,qualified_export=False))


def run(config,protocol_path):
    config=Path(config);protocol_path=Path(protocol_path);p=read(protocol_path);request=read(config/'request.json')
    require(request in p['requests'],'unregistered_request');require(not (config/'GENERATION_STARTED.json').exists(),'generation_slot_used')
    require(read(protocol_path.parent.parent/'pregen/RESULT.json')['passed'],'pregen_rejected')
    validate_config(config,p)
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
        compare_generation(config)
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


def resume_conversion(config,protocol_path):
    """Never rerun the public generator; only continue the diagnosed verifier fix."""
    from .build import build as build_local
    from sage.experiments.embodied_scene_quality_v2.contracts import digest
    config=Path(config);p=read(protocol_path);old=read(config/'CONSTRUCTION.json')
    require(old.get('generation_passed') and old.get('error')=='native_ray_height','unsupported_resume')
    validate_config(config,p);require(read(config/'ASSET_PREVIEW_VERIFIED.json')['passed'],'asset_preview_mismatch')
    result=dict(generation_attempts=0,reused_original_generation=True,new_physics_steps=0,scene_prerequisites_passed=False)
    try:
        local=config/'local_contact_verified';build_local(config/'generator',local,read(config/'request.json'),read(config/'selection.json'),p)
        comparisons={name:dict(original=reference(config/'local_contact'/name),verified=reference(local/name)) for name in ['model.xml','target_visual.stl','target_collision.stl','support_visual.stl']}
        require(all(v['original']['sha256']==v['verified']['sha256'] for v in comparisons.values()),'physical_representation_changed')
        write_new(config/'CONVERSION_INVARIANCE.json',dict(passed=True,files=comparisons,threshold_m=1e-7,ray_count=p['geometry']['native_ray_check_count']))
        task=build(config,p);scene=verify(config/'package',p);start=np.array(task['start_pose_z_up']);goal=np.array(task['goal_pose_z_up']);support=np.array(task['support_pose'])
        delta=(goal[:3,3]-start[:3,3])@support[:3,:3]
        require(np.allclose(start[:3,:3],goal[:3,:3],rtol=0,atol=1e-9),'orientation_changed')
        require(np.allclose(delta[:2],p['translation']['goal_offset_support_xy_m'],rtol=0,atol=1e-9),'translation_changed')
        scene.update(translation_support_m=delta.tolist(),orientation_preserved=True);write_new(config/'SCENE_VERIFIED.json',scene)
        camera=observe(config,p,dict(passed=False))
        result.update(status='constructed',generation_passed=True,scene_verified=scene['passed'],geometry_passed=task['geometry_passed'],observation_passed=camera['passed'],
            scene_prerequisites_passed=bool(scene['passed'] and task['geometry_passed'] and camera['passed']))
    except BaseException as exc:result.update(status='construction_error',error=str(exc),traceback=traceback.format_exc())
    write_new(config/'CONSTRUCTION_VERIFIED.json',result);bind(config,protocol_path,'SCENE_BINDING_VERIFIED.json','scene');print(result,flush=True);return result
