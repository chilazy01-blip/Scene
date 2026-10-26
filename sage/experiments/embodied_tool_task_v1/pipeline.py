"""Real public generation plus scene, robot and observation construction."""
from pathlib import Path
import subprocess,sys,time,traceback
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_task_scene_v1.semantic import validate_roles
from .package import build
from .verify import verify
from .construction import construct
from .observation import observe


def run(config,protocol_path):
    config=Path(config);protocol_path=Path(protocol_path);protocol=read(protocol_path);request=read(config/'request.json')
    require(request in protocol['requests'],'unregistered_request');require(not (config/'GENERATION_STARTED.json').exists(),'generation_slot_used')
    args=[sys.executable,'-m','sage.experiments.codex_trellis_scene_v2.cli','--prompt-file',str(config/'prompt.txt'),
        '--furnishing-config',str(config/'furnishing.json'),'--output-dir',str(config/'generator'),'--profile','development',
        '--room-type','study','--window-wall','north','--expander','rules','--planner','rules','--no-codex-repair','--repair-iterations','2',
        '--asset-mode','reuse','--asset-library-manifest',str(config/'library.json'),'--seed',str(request['seed']),
        '--assemble','--no-render-preview','--no-scene-render-acceptance','--no-mujoco-check']
    write_new(config/'GENERATION_STARTED.json',dict(at=time.time(),arguments=args));result=dict(request_id=request['id'],generation_attempts=1,new_physics_steps=0,ready_for_execution=False)
    try:
        completed=subprocess.run(args,check=False,timeout=240);write_new(config/'GENERATION_RESULT.json',dict(returncode=completed.returncode));require(completed.returncode==0,'generator_failed')
        plan=read(config/'generator/layout_plan_final.json');validate_roles(plan['objects'],read(config/'roles.json'),read(config/'expected_counts.json'))
        require(len(plan['objects'])==sum(read(config/'expected_counts.json').values()),'extra_scene_object')
        require(read(config/'generator/run_summary.json')['profile_complete'] and read(config/'generator/validation_final.json')['ok'],'generation_not_accepted')
        result['generation_passed']=True
        task=build(config,protocol);scene=verify(config/'package',protocol);write_new(config/'SCENE_VERIFIED.json',scene)
        robot=construct(config,protocol);camera=observe(config,protocol,robot)
        result.update(status='constructed',scene_verified=scene['passed'],geometry_passed=task['geometry_passed'],robot_preflight=robot['passed'],observation_passed=camera['passed'],
            new_ik_queries=robot['new_ik_queries'],new_path_checks=robot['new_path_checks'],path_states=robot['path_states'],
            ready_for_execution=bool(scene['passed'] and task['geometry_passed'] and robot['passed'] and camera['passed']))
    except BaseException as exc:result.update(status='construction_error',error=str(exc),traceback=traceback.format_exc())
    write_new(config/'CONSTRUCTION.json',result)
    deps=[]
    for directory in ['embodied_task_scene_v1','embodied_task_generation_v1','embodied_task_clearance_v1','embodied_simdata_v0','embodied_scene_quality_v1','embodied_scene_quality_v2','embodied_planner_m2_v2','embodied_scene_bridge']:
        deps.extend(Path(__file__).parent.parent.joinpath(directory).glob('*.py'))
    files={str(p):reference(p) for p in sorted(config.rglob('*')) if p.is_file() and not p.is_symlink() and '__pycache__' not in str(p)}
    binding=dict(schema='tool-aware-task-binding/v1',config=str(config.resolve()),request=request,protocol=reference(protocol_path),files=files,
        implementation={str(p):reference(p) for p in sorted(set(deps+list(Path(__file__).parent.glob('*.py'))))},
        qualified_collection=False,qualified_export=False)
    write_new(config/'BINDING.json',binding);print(result,flush=True);return result
