"""Real single-book generation evidence -> assembled GLB -> dynamics -> frames."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from .asset_source_policy import validate_trellis_generation_provenance
from .p021_physics_scene import revalidate_asset
from .collision_proxy import VoxelSDF
from .physical_mass import estimate_mass_properties
from .leaning_books import find_shelf_slot, arrange_leaning_books, prepare_dynamics, simulate
from .p021_physics import _bound, _json, _geometry, GLTF_TO_Z

BLENDER=Path('/data/wsj/tools/blender-4.3.2-linux-x64/blender')
REPO=Path(__file__).resolve().parents[3]
SCRIPT=REPO/'sage/scripts/blender_leaning_books.py'


def stage_guard(output,label):
    from .p021_full_workflow import guard,cgroup_directory
    report=guard(cgroup_directory(),set(os.sched_getaffinity(0)))
    _json(output/(label+'_admission.json'),report)
    if not report['accepted']:raise RuntimeError('Stage resource admission rejected: '+repr(report['errors']))


def check(record):
    value=_bound(Path(record['path']))
    if any(value[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('Input binding changed: '+record['path'])


def normalize(path,dimensions,book=False):
    source=trimesh.load(path,force='scene',process=False).to_geometry()
    points=trimesh.transform_points(source.vertices,GLTF_TO_Z)
    align=np.eye(4)
    if book:
        longest=int(np.ptp(points,axis=0).argmax())
        if longest!=2:
            align[:3,:3]=Rotation.from_euler('y' if longest==0 else 'x',-90 if longest==0 else 90,degrees=True).as_matrix()
        aligned=trimesh.transform_points(points,align)
        if np.ptp(aligned,axis=0)[:2].argmin()==1:
            horizontal=np.eye(4);horizontal[:3,:3]=Rotation.from_euler('z',90,degrees=True).as_matrix()
            align=horizontal@align
    points=trimesh.transform_points(points,align)
    extents=np.ptp(points,axis=0);scale=np.asarray(dimensions)/extents
    center=(points.max(axis=0)+points.min(axis=0))/2
    matrix=np.eye(4);matrix[:3,:3]=np.diag(scale);matrix[:3,3]=-center*scale
    matrix=matrix@align@GLTF_TO_Z
    metric=source.copy();metric.apply_transform(matrix)
    return source,metric,matrix,{'source_extents_m':extents.tolist(),'target_extents_m':list(dimensions),
        'axis_scales':scale.tolist(),'anisotropy':float(scale.max()/scale.min()),
        'normalization':'source_y_up_to_z_up_then_axis_alignment_and_declared_metric_dimensions'}


def blender(arguments,output,label):
    stage_guard(output,label)
    env=os.environ.copy()
    for name in ('BLENDER_USER_CONFIG','BLENDER_USER_SCRIPTS','BLENDER_USER_DATAFILES'):
        path=output/'blender_home'/name;path.mkdir(parents=True,exist_ok=True);env[name]=str(path)
    command=[str(BLENDER),'--background','--factory-startup','-t',str(len(os.sched_getaffinity(0))),
             '--python-exit-code','2','-P',str(SCRIPT),'--',*map(str,arguments)]
    _json(output/(label+'_command.json'),{'argv':command,'script':_bound(SCRIPT)})
    with (output/(label+'.log')).open('w') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env,check=True,timeout=3600)


def prepare(root,output):
    protocol=json.loads((root/'protocol.json').read_text())
    inventory=json.loads(Path(protocol['source_inventory']).read_text())
    shelf=next(r for r in inventory['selected_assets'] if r['inventory_id']==protocol['bookcase_inventory_id'])
    check(shelf['glb'])
    # Inventory reference_evidence is a summary, not the original complete
    # provider envelope. Reuse the existing frozen-source revalidation path.
    original=revalidate_asset(shelf)
    _json(output/'bookcase_source_revalidation.json',original)
    audit={'ok':True,'method':'original_frozen_source_and_scoped_review_revalidation',
           'details':_bound(output/'bookcase_source_revalidation.json')}
    entries=[{'id':'bookcase','category':'bookcase','glb':shelf['glb'],
        'dimensions_m':[.9,.32,1.6], 'physical_profile':{'category':'bookcase','material':'wood',
        'material_scope':'bulk','structure':'solid_panels','origin':'wooden_bookcase_generation_design'},
        'source_audit':audit}]
    jobs=set();hashes=set()
    for book in protocol['books']:
        directory=root/'generation'/book['id'];terminal=json.loads((directory/'terminal.json').read_text())
        if terminal['status']!='generated':raise ValueError('Book generation incomplete: '+book['id'])
        meta=json.loads((directory/'bridge_metadata.json').read_text())
        audit=validate_trellis_generation_provenance({'job_id':terminal['job_id'],'bridge_metadata':meta,
                                                     'image_provider':'builtin_imagegen'})
        if not audit['ok']:raise ValueError(audit)
        glb=_bound(directory/'asset.glb')
        if _bound(Path(meta['glb_path']))['sha256']!=glb['sha256']:raise ValueError('GLB differs from generation')
        job=terminal['job_id'];image=meta['selected_reference_evidence']['files']['source_rgb']['sha256']
        if job in jobs or image in hashes:raise ValueError('Books must come from distinct generation jobs and images')
        jobs.add(job);hashes.add(image)
        entries.append({**book,'glb':glb,'source_audit':audit,'generation_job_id':job,'source_image_sha256':image})
    _json(output/'source_audit.json',{'assets':entries,'distinct_book_jobs':len(jobs),'distinct_book_images':len(hashes)})
    sources=[];meshes=[];transforms=[];normalizations=[]
    for entry in entries:
        source,metric,matrix,info=normalize(entry['glb']['path'],entry['dimensions_m'],entry['category']=='single_book')
        sources.append(source);meshes.append(metric);transforms.append(matrix);normalizations.append(info)
    stage_guard(output,'prepare_shelf_mass')
    props=estimate_mass_properties(meshes[0],entries[0]['physical_profile'],output/'shelf_preparation',pitch_m=.005)
    proxy=VoxelSDF.load(Path(props['voxel_files'][-1]['path']))
    slot=find_shelf_slot(proxy,meshes[0].bounds)
    positions=arrange_leaning_books(meshes[1:],slot,angle_deg=protocol['test_plan']['book_angle_deg'])
    world=np.eye(4);world[:3,3]=[3.,2.5,.8];poses=[world,*[world@p for p in positions]]
    room={'width':6.,'length':5.,'height':2.4};assets=[]
    for entry,source,transform,pose,info in zip(entries,sources,transforms,poses,normalizations):
        matrix=pose@transform;points=trimesh.transform_points(source.vertices,matrix)
        assets.append({'id':entry['id'],'category':entry['category'],'source_glb':entry['glb'],
            'source_to_world_gltf':matrix.tolist(),'initial_body_matrix_z_up':pose.tolist(),
            'expected_world_bounds_m':[points.min(axis=0).tolist(),points.max(axis=0).tolist()],
            'physical_profile':entry['physical_profile'],'normalization':info})
    plan={'assets':assets,'room':room,'source_shelf_slot':slot,'protocol':_bound(root/'protocol.json')}
    _json(output/'assembly_plan.json',plan)
    scene=output/'scene.glb';blender(['assemble','--plan',output/'assembly_plan.json','--output',scene],output,'assemble')
    spec={'bookcase_id':'bookcase','objects':[{'id':e['id']} for e in entries],'room':room,
          'asset_frames_world_z_up':{a['id']:a['initial_body_matrix_z_up'] for a in assets},
          'physical_profiles':{e['id']:e['physical_profile'] for e in entries},'initial_lean_deg':10.,
          'target_support_world':{'shelf_z_m':slot['support_z_m']+world[2,3],
              'right_inner_x_m':slot['right_inner_x_m']+world[0,3], 'book_height_m':.24},
          'criteria':{'settled_last_s':1.,'linear_rms_m_s':.005,'angular_rms_rad_s':.03,
                      'final_lean_range_deg':[5,18],'basis':'declared_scene_reference_not_universal_engineering_standard'}}
    groups,_=_geometry(scene,spec);checks={}
    for asset,source in zip(assets,sources):
        expected=trimesh.transform_points(source.vertices,np.asarray(asset['source_to_world_gltf']))
        actual=np.concatenate([p['vertices'] for p in groups[asset['id']]])
        error=max(cKDTree(expected).query(actual)[0].max(),cKDTree(actual).query(expected)[0].max())
        checks[asset['id']]={'bidirectional_max_vertex_error_m':float(error),
                             'source_faces':len(source.faces),'assembled_faces':sum(len(p['faces']) for p in groups[asset['id']])}
        if error>2e-5 or checks[asset['id']]['source_faces']!=checks[asset['id']]['assembled_faces']:
            raise ValueError('Source geometry not preserved in assembly')
    _json(output/'assembly_geometry_checks.json',checks)
    stage_guard(output,'prepare_dynamics')
    binding=prepare_dynamics(scene,spec,output/'physics_binding')
    return binding


def compare(output,results):
    sensitivity={}
    for label in ('normal','low'):
        values=results[label];differences=[]
        for coarse,fine in zip(values,values[1:]):
            with np.load(Path(coarse['trajectory']['path']).parent/'dense_state.npz') as a,np.load(Path(fine['trajectory']['path']).parent/'dense_state.npz') as b:
                pa=a['matrix_world_z_up'];pb=b['matrix_world_z_up'][::2]
                differences.append({'coarse_dt_s':coarse['dt_s'],'fine_dt_s':fine['dt_s'],
                    'max_body_position_difference_m':float(np.linalg.norm(pa[:,:,:3,3]-pb[:,:,:3,3],axis=-1).max()),
                    'final_body_position_difference_m':float(np.linalg.norm(pa[-1,:,:3,3]-pb[-1,:,:3,3],axis=-1).max()),
                    'all_small_lean_classification_agrees':coarse['all_books_retain_small_lean']==fine['all_books_retain_small_lean'],
                    'settled_classification_agrees':coarse['all_books_settled']==fine['all_books_settled']})
        sensitivity[label]=differences
    normal=results['normal'][-1];low=results['low'][-1]
    effect={s:abs(low['metrics'][s]['final_lean_deg']-normal['metrics'][s]['final_lean_deg']) for s in normal['metrics']}
    with np.load(Path(normal['trajectory']['path']).parent/'dense_state.npz') as a,np.load(Path(low['trajectory']['path']).parent/'dense_state.npz') as b:
        if a['object_ids'].tolist()!=b['object_ids'].tolist():raise ValueError('Control object order differs')
        position_effect=float(np.linalg.norm(a['matrix_world_z_up'][-1,:,:3,3]-b['matrix_world_z_up'][-1,:,:3,3],axis=-1).max())
    numerical_variation=max(sensitivity[k][-1]['final_body_position_difference_m'] for k in sensitivity)
    healthy=all(r['all_finite'] and not r['simulator_warnings'] and r['exact_30_step_state_restore']
        and r['compiled']['no_kinematic_books'] for batch in results.values() for r in batch)
    result={'schema':'p021-leaning-comparison/v1','engineering_healthy':healthy,
        'normal_retains_requested_lean':normal['all_books_retain_small_lean'] and normal['all_books_settled'],
        'low_friction_retains_requested_lean':low['all_books_retain_small_lean'] and low['all_books_settled'],
        'final_position_friction_effect_m':position_effect,
        'fine_step_final_position_variation_m':numerical_variation,
        'friction_effect_exceeds_observed_step_variation':position_effect>numerical_variation,
        'scene_reference_effect_supported':bool(healthy and normal['all_books_retain_small_lean'] and normal['all_books_settled']
            and not (low['all_books_retain_small_lean'] and low['all_books_settled']) and position_effect>numerical_variation),
        'low_friction_final_angle_difference_deg':effect,'step_sensitivity':sensitivity,
        'runs':{k:[_bound(Path(r['trajectory']['path']).parent/'result.json') for r in v] for k,v in results.items()},
        'friction_effect_is_scene_specific':True,'real_world_material_calibration':False}
    _json(output/'comparison.json',result);return result


def run(root,output):
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    for name in ('p021_leaning_workflow.py','leaning_books.py','leaning_presentation.py','physical_mass.py','multilevel_proxy.py','collision_mesh_cleanup.py','p021_physics.py','p021_physics_scene.py','asset_source_policy.py'):
        dest=output/'source_snapshot'/name;dest.parent.mkdir(exist_ok=True);dest.write_bytes(Path(__file__).with_name(name).read_bytes())
    (output/'source_snapshot'/SCRIPT.name).write_bytes(SCRIPT.read_bytes())
    _json(output/'execution.json',{'protocol':_bound(root/'protocol.json'),'reference_criteria':_bound(root/'acceptance_reference.json'),
        'source_snapshot':[_bound(p) for p in sorted((output/'source_snapshot').iterdir())]})
    binding=prepare(root,output)
    blender(['inspect','--scene',output/'scene.glb','--binding',output/'physics_binding/geometry_binding.json',
             '--output',output/'asset_inspection'],output,'inspect')
    protocol=json.loads((root/'protocol.json').read_text());test=protocol['test_plan'];results={}
    for label,mu in [('normal',test['normal_mu']),('low',test['low_mu'])]:
        results[label]=[]
        for factor in test['step_checks']:
            dt=test['dt_s']*factor;path=output/'dynamics'/f'{label}_{dt:.6f}'
            stage_guard(output,f'{label}_{dt:.6f}')
            print(f'Simulating {label} dt={dt}',flush=True)
            result=simulate(binding,path,mu=mu,dt=dt,duration=test['duration_s']);results[label].append(result)
        blender(['render','--scene',output/'scene.glb','--binding',output/'physics_binding/geometry_binding.json',
                 '--trajectory',Path(results[label][-1]['trajectory']['path']),'--output',output/'renders'/label],output,'render_'+label)
    result=compare(output,results)
    from .leaning_presentation import write_presentation
    write_presentation(output)
    result['wall_seconds']=time.monotonic()-started
    _json(output/'workflow_result.json',result)
    print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.root,args.output)

if __name__=='__main__':main()
