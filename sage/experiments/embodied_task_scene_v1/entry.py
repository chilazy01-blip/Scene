"""Public, pinned whole-scene start/goal model entry; fail closed by purpose."""
from pathlib import Path
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,require,reference
from .verify import verify


def record(config,protocol_path,verification_path,preflight_path):
    config=Path(config);package=config/'package';here=Path(__file__).parent
    return dict(schema='full-task-scene-entry/v1',package_path=str(package),files=reference(package/'FILES.json'),
        protocol=reference(protocol_path),verification=reference(verification_path),robot_preflight=reference(preflight_path),
        implementation={str(p):reference(p) for p in sorted(here.glob('*.py'))},
        declared_purposes=['scene_inspection'],qualified_collection=False,qualified_export=False)


def open_scene(path,pin,request_id,state,purpose):
    entry=read(bound(path,pin));require(entry['schema']=='full-task-scene-entry/v1','entry_schema')
    protocol=read_ref(entry['protocol']);package=Path(entry['package_path'])
    require(read(package/'task.json')['request']['id']==request_id,'request_identity')
    require(protocol['request']['id']==request_id,'protocol_request_identity')
    require(state in ['start','goal'],'unknown_scene_state')
    require(purpose=='scene_inspection','purpose_requires_robot_execution_and_observation_qualification')
    require(entry['files']['path']==str((package/'FILES.json').resolve()),'package_files_identity')
    for ref in read_ref(entry['files']).values():bound(ref['path'],ref['sha256'])
    for ref in entry['implementation'].values():bound(ref['path'],ref['sha256'])
    require(read_ref(entry['verification'])['passed'],'missing_scene_verification')
    # Do not inherit an isolated release or robot success flag from another model.
    read_ref(entry['robot_preflight']);verified=verify(package,protocol)
    import mujoco
    model=mujoco.MjModel.from_binary_path(str(package/('model.mjb' if state=='start' else 'model_goal.mjb')))
    return model,verified
