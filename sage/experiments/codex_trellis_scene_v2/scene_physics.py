"""Optional main-pipeline integration for a source-bound free leaning-book group.

The visual binary buffers are preserved byte for byte. Only bound object-node
transforms change; the final render consumes the simulated GLB itself.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import struct


def read_config(path):
    if path is None:
        return None
    config=json.loads(Path(path).read_text())
    if config.get('schema')!='scene-leaning-physics/v1':
        raise ValueError('Unsupported physics configuration')
    for key,lo,hi in [('mu',0.,2.),('angle_deg',1.,20.),('duration_s',1.,30.)]:
        value=config[key]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('Invalid physics setting: '+key)
    if not isinstance(config['book_count'],int) or not 2<=config['book_count']<=12:
        raise ValueError('Invalid independent book count')
    return config


def extend_brief(brief,config):
    """Ground an explicitly configured contained group before graph/asset stages."""
    if not config:return
    if config.get('room_dimensions'):
        brief['room'].update(config['room_dimensions'])
    shelves=[o for o in brief['objects'] if o['category']=='bookcase']
    if len(shelves)!=1:raise ValueError('Physics group requires exactly one bookcase')
    shelf=shelves[0]
    dims=config['bookcase_dimensions']
    shelf['dimensions']=dict(zip(('width','length','height'),dims))
    shelf['requested_dimensions']=deepcopy(shelf['dimensions'])
    shelf['dimension_policy'].pop('request_origin', None)
    shelf['dimension_grounding']='explicit_physics_configuration_matches_source_asset'
    removed={o['id'] for o in brief['objects'] if o['category']=='single_book' or
             (config.get('replace_compound_books') and o['category']=='book_stack')}
    brief['independent_book_group_grounding']={'replaces_parsed_object_ids':sorted(removed),
        'reason':'explicit_individual_books_instead_of_compound_stack','count':config['book_count']}
    brief['objects']=[o for o in brief['objects'] if o['id'] not in removed]
    for index in range(config['book_count']):
        dimensions=dict(zip(('width','length','height'),config['book_dimensions']))
        brief['objects'].append({'id':f'leaning_book_{index+1:02d}', 'category':'single_book',
            'required':True,'priority':90,'placement_type':'contained','container_id':shelf['id'],
            'dimensions':dimensions,'requested_dimensions':deepcopy(dimensions),
            'dimension_policy':{'mode':'fixed_physical','relative_tolerance':.08,'enforce_at_assembly':True},
            'provenance':'user_explicit_physics_group','physics_role':'free_rigid_book'})
    for obj in brief['objects']:
        override=config.get('object_overrides',{}).get(obj['id'],{})
        if set(override)-{'preferred_wall','wall_constraint_strength','facing_constraint','mount_height','support_id','support_offset','initial_pose'}:
            raise ValueError('Unsupported physics-scene layout override')
        obj.update(deepcopy(override))
    brief['physics_configuration']=deepcopy(config)
    budget=brief['object_budget']
    budget['required_object_ids']=[o['id'] for o in brief['objects'] if o.get('required',True)]
    if len(brief['objects'])>budget['hard_runtime_limit']:
        raise ValueError('Physics group exceeds existing runtime object budget')


def transform_objects(source,target,deltas):
    """Apply world-Z-up rigid deltas once per bound GLB subtree, preserving buffers."""
    import numpy as np
    from .p021_physics import _read_glb,_node_matrix,GLTF_TO_Z
    document,binary=_read_glb(Path(source));nodes=document['nodes'];seen=set();changed={}
    def visit(index,parent,inherited=None):
        node=nodes[index];own=node.get('extras',{}).get('scene_object_id')
        local=_node_matrix(node);world=parent@local
        identifier=own or inherited
        if identifier in deltas and inherited!=identifier:
            delta=np.asarray(deltas[identifier])
            if not np.allclose(delta[:3,:3].T@delta[:3,:3],np.eye(3),atol=1e-9) or not np.isclose(np.linalg.det(delta[:3,:3]),1.):
                raise ValueError('Visual pose delta must be rigid')
            moved=np.linalg.inv(parent)@np.linalg.inv(GLTF_TO_Z)@delta@GLTF_TO_Z@world
            for key in ('translation','rotation','scale'):node.pop(key,None)
            node['matrix']=moved.T.reshape(-1).tolist()
            changed[identifier]=changed.get(identifier,0)+1
        if index in seen:raise ValueError('Non-tree scene graph')
        seen.add(index)
        # Descendants retain local transforms; do not apply a delta twice.
        for child in node.get('children',[]):visit(child,world,identifier)
    for index in document['scenes'][document.get('scene',0)]['nodes']:visit(index,np.eye(4))
    if set(changed)!=set(deltas):raise ValueError('Visual pose IDs missing from GLB')
    raw=json.dumps(document,separators=(',',':')).encode();raw+=b' '*((-len(raw))%4)
    binary+=b'\0'*((-len(binary))%4)
    Path(target).write_bytes(struct.pack('<4sII',b'glTF',2,28+len(raw)+len(binary))+
        struct.pack('<I4s',len(raw),b'JSON')+raw+struct.pack('<I4s',len(binary),b'BIN\0')+binary)
    return changed


def run_scene_physics(scene,plan,output,config):
    import numpy as np
    from scipy.spatial.transform import Rotation
    from .p021_physics import _geometry,metric_object_mesh,_bound,_json,_read_glb
    from .physical_mass import estimate_mass_properties
    from .collision_proxy import VoxelSDF
    from .leaning_books import find_shelf_slot,arrange_leaning_books,prepare_dynamics,simulate
    from .p021_leaning_workflow import stage_guard
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    stage_guard(output,'initial_geometry')
    objects=plan['objects'];shelf=next(o for o in objects if o['category']=='bookcase')
    books=sorted((o for o in objects if o.get('physics_role')=='free_rigid_book'),key=lambda o:o['id'])
    if len(books)!=config['book_count']:raise ValueError('Mainline book count differs from physical request')
    spec={'room':plan['room'],'objects':[{'id':o['id']} for o in objects], 'bookcase_id':shelf['id'],
          'dynamic_object_ids':[o['id'] for o in books], 'allow_stationary_architecture_hulls':True,
          'initial_lean_deg':config['angle_deg']}
    document,_=_read_glb(Path(scene))
    bound_ids={n.get('extras',{}).get('scene_object_id') for n in document['nodes']} - {None}
    architecture_ids={o['id'] for key in ('doors','windows') for o in plan['architecture'].get(key,[])}
    extra_ids=bound_ids-{o['id'] for o in objects}
    if not extra_ids<=architecture_ids:raise ValueError('Unrecognized extra scene object IDs')
    spec['objects'].extend({'id':identifier} for identifier in sorted(extra_ids))
    groups,_=_geometry(Path(scene),spec);frames={};meshes={}
    for obj in [*objects,*[{'id':identifier} for identifier in sorted(extra_ids)]]:
        identifier=obj['id'];rotation=Rotation.from_euler('z',obj.get('yaw',0.),degrees=True).as_matrix()
        points=np.concatenate([p['vertices'] for p in groups[identifier]])
        local=points@rotation;center=(local.min(axis=0)+local.max(axis=0))/2
        frame=np.eye(4);frame[:3,:3]=rotation;frame[:3,3]=rotation@center
        frames[identifier]=frame;meshes[identifier]=metric_object_mesh(groups[identifier],frame)
    profile={'category':'bookcase','material':'wood','material_scope':'bulk','structure':'solid_panels',
             'origin':'declared_wooden_bookcase_source_design'}
    props=estimate_mass_properties(meshes[shelf['id']],profile,output/'shelf_preparation',pitch_m=.005)
    proxy=VoxelSDF.load(Path(props['voxel_files'][-1]['path']))
    slot=find_shelf_slot(proxy,meshes[shelf['id']].bounds,config['book_dimensions'][2])
    poses=arrange_leaning_books([meshes[b['id']] for b in books],slot,angle_deg=config['angle_deg'])
    shelf_frame=frames[shelf['id']];deltas={}
    for book,pose in zip(books,poses):
        identifier=book['id'];world=shelf_frame@pose
        deltas[identifier]=world@np.linalg.inv(frames[identifier]);frames[identifier]=world
    initial=output/'scene_initial_lean.glb';transform_objects(scene,initial,deltas)
    axis=shelf_frame[:3,0]
    spec.update(asset_frames_world_z_up={k:v.tolist() for k,v in frames.items()},lean_axis_world=axis.tolist(),
        physical_profiles={shelf['id']:profile,**{b['id']:{'category':'single_book','material':'paper',
            'material_scope':'bulk','structure':'bound_paper_block','origin':'declared_paper_page_block_design'} for b in books}},
        target_support_world={'shelf_z_m':slot['support_z_m']+shelf_frame[2,3],
            'right_inner_x_m':slot['right_inner_x_m']+float(axis@shelf_frame[:3,3]),
            'book_height_m':config['book_dimensions'][2]})
    _json(output/'initialization.json',{'input_scene':_bound(Path(scene)), 'slot':slot,'spec':spec,
        'initial_transform_deltas':{k:v.tolist() for k,v in deltas.items()}})
    stage_guard(output,'prepare_dynamics')
    binding=prepare_dynamics(initial,spec,output/'binding')
    results=[]
    for dt in (.001,.0005,.00025):
        stage_guard(output,f'normal_{dt:.6f}')
        print(f'Mainline normal friction mu={config["mu"]}, dt={dt}',flush=True)
        results.append(simulate(binding,output/f'normal_{dt:.6f}',mu=config['mu'],dt=dt,duration=config['duration_s']))
    fine=results[-1]
    if not all(r['all_finite'] and not r['simulator_warnings'] and r['exact_30_step_state_restore'] and
               r['compiled']['no_kinematic_books'] for r in results):
        raise ValueError('Mainline dynamics failed numerical health checks')
    if not all(r['all_books_settled'] and r['all_books_retain_small_lean'] for r in results[-2:]):
        raise ValueError('Normal-friction books did not settle in the requested lean')
    with np.load(output/'normal_0.000250/dense_state.npz') as data:
        ids=data['object_ids'].tolist();final=data['matrix_world_z_up'][-1].copy()
    with np.load(output/'normal_0.000500/dense_state.npz') as data:
        difference=float(np.linalg.norm(final[:,:3,3]-data['matrix_world_z_up'][-1,:,:3,3],axis=1).max())
    final_deltas={b['id']:final[ids.index(b['id'])]@np.linalg.inv(np.asarray(binding['objects'][b['id']]['initial_body_matrix_z_up'])) for b in books}
    final_scene=output/'scene_physics_final.glb';transform_objects(initial,final_scene,final_deltas)
    final_groups,_=_geometry(final_scene,spec);checks={}
    initial_groups,_=_geometry(initial,spec)
    for identifier in groups:
        before=np.concatenate([p['vertices'] for p in initial_groups[identifier]])
        after=np.concatenate([p['vertices'] for p in final_groups[identifier]])
        delta=final_deltas.get(identifier,np.eye(4));expected=before@delta[:3,:3].T+delta[:3,3]
        error=float(np.abs(after-expected).max())
        checks[identifier]={'max_vertex_coordinate_error_m':error,'stationary':identifier not in final_deltas}
        if error>1e-8:raise ValueError('Final render geometry differs from simulation')
    final_plan=deepcopy(plan)
    for obj in final_plan['objects']:
        if obj['id'] not in final_deltas:continue
        matrix=final[ids.index(obj['id'])];points=np.concatenate([p['vertices'] for p in final_groups[obj['id']]])
        obj.update(x=float(matrix[0,3]),y=float(matrix[1,3]),z=float(points[:,2].min()),
            rigid_body_pose_matrix_z_up=matrix.tolist(),physical_pose_source=str(output/'normal_0.000250/dense_state.npz'))
    from .scene_graph import materialize_scene_graph
    from .contracts import stamp_document
    final_plan['scene_graph']=materialize_scene_graph(final_plan['scene_graph'],final_plan['objects'])
    final_plan['physics_result']=str(output/'physics_result.json');stamp_document(final_plan)
    final_plan_path=output/'layout_plan_physics_final.json';_json(final_plan_path,final_plan)
    report={'schema':'scene-mainline-physics-result/v1','ok':True,'mu':config['mu'],'gravity_m_s2':9.81,
        'duration_s':config['duration_s'],'dynamic_book_count':len(books),'stationary_object_count':len(binding['objects'])-len(books),
        'input_scene':_bound(Path(scene)),'initial_scene':_bound(initial),'final_scene':_bound(final_scene),
        'final_layout_plan':_bound(final_plan_path),'normal_fine_result':_bound(output/'normal_0.000250/result.json'),
        'normal_fine_step_final_position_difference_m':difference,'render_pose_checks':checks,
        'physical_reference_passed':True,'real_material_calibration':False,'config':config}
    _json(output/'physics_result.json',report)
    return report
