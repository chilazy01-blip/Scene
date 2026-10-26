"""New adapter acceptance only; never replays old v0 experiments."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import traceback
from xml.etree import ElementTree as ET

import mujoco
import numpy as np

from .contracts import digest, read, require, write, validate_split_registry, verify_freeze
from .environment import TaskEnvironment, support_probe


def verify(root, name, revision):
    root = Path(root)
    verify_freeze(root)
    attempt = root/'attempts'/name
    package = attempt/revision
    output = attempt/(revision+'_verification')
    output.mkdir(exist_ok=False)
    began = time.monotonic()
    result = dict(passed=False,checks={},task_execution_attempts=0,demonstrations=0)
    write(output/'VERIFICATION.json',result)
    checks = result['checks']
    try:
        for file,sha in read(package/'FILES.json').items():
            require(digest(package/file) == sha, 'package_file_changed:'+file)
        checks['package_hashes'] = True
        manifest = read(package/'scene_manifest.json')
        source = Path(manifest['source_glb']['path'])
        require(digest(source)==manifest['source_glb']['sha256'],'source_geometry_changed')
        plan = read(attempt/'generator/layout_plan_final.json')
        require({o['id'] for o in plan['objects']} == {o['semantic_id'] for o in manifest['objects']}, 'missing_generated_objects')
        require(all(o['dimension_error_m']<1e-4 for o in manifest['objects']), 'dimension_contract')
        checks['all_objects_and_real_dimensions'] = dict(objects=len(plan['objects']),max_error_m=max(o['dimension_error_m'] for o in manifest['objects']))
        # Independently read delivered OBJ vertices and map them back to world
        # coordinates for comparison against the actual final GLB triangles.
        from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry
        objects = manifest['objects'] + manifest['architecture_objects']
        groups,floor = _geometry(source,dict(room=plan['room'],objects=[dict(id=o['semantic_id']) for o in objects]))
        parts = [p for group in groups.values() for p in group] + [floor,*floor['other_architecture_parts']]
        expected = {p['binding']['node_index']:p['vertices'] for p in parts}
        poses = {o['semantic_id']:np.array(o['pose_z_up']) for o in objects}
        actual = {}
        for row in manifest['visuals']:
            node_index = int(row['name'].split('_')[2])
            vertices = np.array([[float(v) for v in line.split()[1:]]
                                 for line in (package/'assets'/(row['name']+'.obj')).read_text().splitlines() if line.startswith('v ')])
            if row['owner'] is not None:
                matrix = poses[row['owner']]
                vertices = vertices @ matrix[:3,:3].T + matrix[:3,3]
            actual.setdefault(node_index,[]).append(vertices)
        require(set(actual)==set(expected),'visual_nodes_missing')
        errors=[]
        for node,points in actual.items():
            vertices=np.concatenate(points)
            require(vertices.shape==expected[node].shape,'visual_vertex_count')
            errors.append(float(np.max(abs(vertices-expected[node]))))
        require(max(errors)<1e-6,'visual_world_geometry_changed')
        checks['delivered_visual_vertices_match_final_GLB'] = dict(nodes=len(errors),maximum_world_error_m=max(errors),
                                                                  architecture_openings=len(manifest['architecture_objects']))
        xml = ET.parse(package/'model.xml').getroot()
        for element in xml.findall('asset/*'):
            file = element.get('file')
            if file:
                require(not Path(file).is_absolute() and (package/file).is_file(), 'nonportable_asset')
        require(not xml.findall('.//weld'),'target_weld_forbidden')
        env = TaskEnvironment(package)
        obs = env.reset(918102)
        reset_state = env.state().copy()
        require(set(obs)=={'proprio'} and obs['proprio'].shape==(18,),'policy_observation_leak')
        require(not env.evaluate()['success'],'reset_false_success')
        checks['policy_truth_separation_and_no_reset_success'] = True
        checks['support'] = dict(start=support_probe(env.model,env.data,env.task,env.start),
                                 goal=support_probe(env.model,env.data,env.task,env.task['goal']))
        for invalid in (np.zeros(7),np.full(8,np.nan),np.full(8,100),np.r_[env.ctrl.qhome,.041]):
            before=env.state().copy()
            try:
                env.step(invalid)
            except ValueError:
                require(np.array_equal(before,env.state()),'invalid_action_advanced_physics')
            else:
                raise AssertionError('invalid_action_accepted')
        checks['invalid_action_no_state_change'] = True
        # Move the actual support colliders away in this disposable model. The
        # original package/GLB is untouched; the goal marker remains present.
        support_id = env.model.body(env.task['support_body']).id
        ids = np.flatnonzero((env.model.geom_bodyid==support_id)&(env.model.geom_group==3))
        saved = env.model.geom_pos[ids].copy()
        env.model.geom_pos[ids,2] -= 2
        mujoco.mj_forward(env.model,env.data)
        try:
            support_probe(env.model,env.data,env.task,env.task['goal'])
        except ValueError as exc:
            require(str(exc)=='target_region_has_no_real_support','negative_support_wrong_rejection')
            checks['marker_without_geometry_rejected'] = True
        else:
            raise AssertionError('missing_actual_support_accepted')
        finally:
            env.model.geom_pos[ids] = saved
        env.reset(918102)
        require(np.array_equal(reset_state,env.state()),'seed_reset_not_exact')
        action=np.r_[env.ctrl.qhome,.04]
        observations=[env.observe()['proprio']]
        states=[env.state()]
        for _ in range(10):
            observations.append(env.step(action)['proprio']);states.append(env.state())
        evaluation=env.evaluate()
        require(np.isfinite(states).all() and env.native_steps==500,'physics_probe_failed')
        require(not evaluation['success'] and not evaluation['metrics']['floor_contact'], 'hold_probe_failed')
        np.savez_compressed(output/'hold_probe.npz',state=np.array(states),proprio=np.array(observations),
                            action=np.tile(action,(10,1)),state_spec=int(env.mask),physics_dt_s=.001,action_dt_s=.05)
        checks['finite_torque_physics_probe'] = dict(native_steps=500,actions=10,observations=11,
                                                   duration_s=float(env.data.time),evaluation=evaluation,
                                                   purpose='interface hold probe; not a pick-place demonstration')
        # Independent process loads only the moved package assets and adapter.
        moved=output/'relocated_package'
        shutil.copytree(package,moved)
        child="""from pathlib import Path
import sys,numpy as np
from sage.experiments.embodied_scene_bridge.environment import TaskEnvironment
p=Path(sys.argv[1]);e=TaskEnvironment(p);e.reset(918102);states=[e.state()]
for i in range(10): e.step(np.r_[e.ctrl.qhome,.04]);states.append(e.state())
np.save(sys.argv[2],np.array(states))
"""
        runtime=output/'runtime'
        runtime.mkdir()
        for relative in ('sage','sage/experiments','sage/experiments/embodied_scene_bridge','sage/experiments/embodied_simdata_v0'):
            directory=runtime/relative;directory.mkdir(parents=True,exist_ok=True)
            (directory/'__init__.py').write_text('')
        repo=Path(__file__).resolve().parents[3]
        for relative in ('sage/experiments/embodied_scene_bridge/environment.py',
                         'sage/experiments/embodied_scene_bridge/contracts.py',
                         'sage/experiments/embodied_simdata_v0/controller.py'):
            shutil.copyfile(repo/relative,runtime/relative)
        write(output/'RUNTIME_FILES.json',{str(p.relative_to(runtime)):digest(p) for p in runtime.rglob('*.py')})
        command=[sys.executable,'-c',child,str(moved),str(output/'relocated_states.npy')]
        child_env=dict(os.environ,PYTHONPATH=str(runtime),PYTHONDONTWRITEBYTECODE='1')
        run=subprocess.run(command,cwd='/tmp',env=child_env,capture_output=True,text=True)
        (output/'relocation_stdout.txt').write_text(run.stdout+run.stderr)
        require(run.returncode==0,'relocated_process_failed')
        require(np.array_equal(np.load(output/'relocated_states.npy'),np.array(states)), 'relocation_state_mismatch')
        checks['relative_package_separate_process_exact_500_steps'] = True
        # Bind an actual copy using arbitrary semantic body names to ensure
        # there is no runtime dependence on a particular desk/book identifier.
        renamed=output/'renamed_package'
        shutil.copytree(package,renamed)
        task=read(renamed/'task.json');tree=ET.parse(renamed/'model.xml')
        for field,new in [('target_body','another_rigid_object'),('support_body','another_support')]:
            tree.find(f"worldbody/body[@name='{task[field]}']").set('name',new)
            task[field]=new
        tree.write(renamed/'model.xml',encoding='unicode');write(renamed/'task.json',task)
        renamed_env=TaskEnvironment(renamed);renamed_env.reset(918102)
        require(np.array_equal(renamed_env.state(),reset_state),'semantic_rename_changed_state')
        renamed_env.step(action)
        require(np.array_equal(renamed_env.state(),states[1]),'semantic_rename_changed_physics')
        checks['actual_renamed_body_binding_exact_50_steps'] = True
        source_rows=manifest['asset_resolution']+manifest['architecture_resolution']
        assets = sorted({digest(p['source']) for p in source_rows if p.get('source') and Path(p['source']).is_file()})
        registry=[dict(scene=name,split='development',source_asset_groups=[manifest['source_asset_group']],
                       asset_content_sha256=assets,layout_families=[manifest['layout_family']])]
        validate_split_registry(registry)
        try:
            validate_split_registry(registry,True)
        except ValueError as exc:
            require(str(exc)=='learning_splits_not_frozen','learning_gate_wrong_reason')
            checks['learning_collection_blocked_until_independent_groups'] = True
        else:
            raise AssertionError('unfrozen_learning_splits_accepted')
        write(output/'SPLIT_REGISTRY.json',dict(rows=registry,learning_ready=False))
        result['passed']=True
    except BaseException:
        result['traceback']=traceback.format_exc()
        raise
    finally:
        result['wall_seconds']=time.monotonic()-began
        write(output/'VERIFICATION.json',result)
    return result
