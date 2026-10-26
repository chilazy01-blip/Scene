"""Free rigid books leaning in a source-bound, stationary bookcase.

The shelf collider is an exact disjoint-box cover of an undilated voxel proxy;
the visual GLB is never replaced. Books have six free DOFs with no welds,
springs, imposed velocities, sleep tricks or pose resets after release.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from xml.etree import ElementTree as ET

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .collision_proxy import VoxelSDF
from .physical_mass import estimate_mass_properties
from .p021_physics import (_geometry, _hull, _vec, _bound, _json,
                          object_mass_frame, metric_object_mesh)


def voxel_boxes(proxy: VoxelSDF, *, maximum_boxes: int=12000) -> tuple[np.ndarray,np.ndarray]:
    """Greedy disjoint cuboids whose union equals the occupied voxel set."""
    grid=proxy.occupancy.copy();shape=grid.shape;centers=[];sizes=[]
    original_count=int(grid.sum());covered=0
    for a,b,c in np.argwhere(grid):
        if not grid[a,b,c]:continue
        cc=c+1
        while cc<shape[2] and grid[a,b,cc]:cc+=1
        bb=b+1
        while bb<shape[1] and grid[a,bb,c:cc].all():bb+=1
        aa=a+1
        while aa<shape[0] and grid[aa,b:bb,c:cc].all():aa+=1
        lower=np.array([a,b,c]);upper=np.array([aa,bb,cc])
        covered+=int(np.prod(upper-lower));grid[a:aa,b:bb,c:cc]=False
        centers.append(proxy.origin+(lower+upper-1)*proxy.pitch/2)
        sizes.append((upper-lower)*proxy.pitch/2)
        if len(centers)>maximum_boxes:raise ValueError('Static collider cuboid budget exceeded')
    if covered!=original_count or grid.any():raise ValueError('Voxel cuboid union is incomplete')
    return np.asarray(centers),np.asarray(sizes)


def find_shelf_slot(proxy: VoxelSDF, bounds: np.ndarray, book_height: float=.24) -> dict:
    """Locate shelf slabs and a right side wall in actual occupied geometry."""
    bounds=np.asarray(bounds);lo,hi=bounds;span=hi-lo
    xyz=[proxy.origin[a]+np.arange(proxy.occupancy.shape[a])*proxy.pitch for a in range(3)]
    xs=(xyz[0]>lo[0]+span[0]*.2)&(xyz[0]<hi[0]-span[0]*.2)
    ys=(xyz[1]>lo[1]+span[1]*.2)&(xyz[1]<lo[1]+span[1]*.65)
    fraction=proxy.occupancy[xs][:,ys,:].mean(axis=(0,1))
    solid=fraction>.55
    edges=np.diff(np.r_[False,solid,False].astype(int))
    starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)-1
    candidates=[]
    for start,end in zip(starts,ends):
        top=float(xyz[2][end]+proxy.pitch/2)
        if top+book_height+.04>=hi[2]:continue
        above=(xyz[2]>top+.025)&(xyz[2]<top+book_height+.03)
        if not above.any() or proxy.occupancy[xs][:,ys,:][:,:,above].mean()>.03:continue
        y=(lo[1]+span[1]*.425)
        band_y=(xyz[1]>y-.07)&(xyz[1]<y+.07)
        band_z=(xyz[2]>top+.04)&(xyz[2]<top+book_height-.015)
        side=proxy.occupancy[:,band_y,:][:,:,band_z].mean(axis=(1,2))
        right=np.flatnonzero((xyz[0]>lo[0]+.65*span[0])&(side>.65))
        if not len(right):continue
        inner=float(xyz[0][right[0]]-proxy.pitch/2)
        candidates.append({'support_z_m':top,'right_inner_x_m':inner,'book_center_y_m':float(y),
                           'support_voxel_z_range':[int(start),int(end)],
                           'right_panel_voxel_x':int(right[0]),'pitch_m':proxy.pitch,
                           'source':'undilated_actual_bookcase_voxel_occupancy'})
    if not candidates:raise ValueError('No source-derived open shelf slot fits the books')
    # Prefer an interior shelf for readable pictures; the choice is geometric.
    return min(candidates,key=lambda x:abs(x['support_z_m']-(lo[2]+.4*span[2])))


def arrange_leaning_books(meshes: list, slot: dict, *, angle_deg: float=10., clearance_m: float=.0005) -> list[np.ndarray]:
    """Position separate hulls with common tilt and nonoverlapping support planes."""
    rotation=Rotation.from_euler('y',angle_deg,degrees=True).as_matrix()
    normal=rotation[:,0]
    positions=[None]*len(meshes);previous=None
    for index in reversed(range(len(meshes))):
        points=np.asarray(meshes[index].vertices)@rotation.T
        z=slot['support_z_m']-points[:,2].min()+clearance_m
        if previous is None:
            x=slot['right_inner_x_m']-points[:,0].max()-clearance_m
        else:
            prev_points,prev_center=previous
            support=np.dot(normal,prev_center)+(prev_points@normal).min()
            x=(support-(points@normal).max()-clearance_m-normal[2]*z)/normal[0]
        center=np.array([x,slot['book_center_y_m'],z]);matrix=np.eye(4)
        matrix[:3,:3]=rotation;matrix[:3,3]=center;positions[index]=matrix
        previous=points,center
    return positions


def prepare_dynamics(scene: Path,spec: dict,output: Path) -> dict:
    output.mkdir(parents=True,exist_ok=False)
    groups,floor=_geometry(scene,spec)
    objects={};colliders={};static_id=spec['bookcase_id']
    dynamic_ids=set(spec.get('dynamic_object_ids', [s for s in groups if s!=static_id]))
    if not dynamic_ids or not dynamic_ids <= set(groups) or static_id in dynamic_ids:
        raise ValueError('Invalid dynamic book group')
    for identifier,parts in sorted(groups.items()):
        if 'asset_frames_world_z_up' in spec:
            body=np.asarray(spec['asset_frames_world_z_up'][identifier],dtype=float).copy()
            rotation=body[:3,:3]
            if not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-10) or np.linalg.det(rotation)<0:
                raise ValueError('Declared physical frame must be a proper rigid transform')
            points=(np.concatenate([p['vertices'] for p in parts])-body[:3,3])@rotation
            bounds=np.array([points.min(axis=0),points.max(axis=0)])
            body[:3,3]+=rotation@bounds.mean(axis=0);extents=np.ptp(bounds,axis=0)
        else:
            body,_,extents=object_mass_frame(parts)
        mesh=metric_object_mesh(parts,body)
        if identifier!=static_id and identifier not in dynamic_ids:
            vertices,faces=_hull(mesh.vertices);path=output/(identifier+'_static_hull.npz')
            np.savez_compressed(path,vertices=vertices,faces=faces)
            objects[identifier]={'initial_body_matrix_z_up':body.tolist(), 'static':True,
                'metric_box_extents_m':extents.tolist(), 'mesh_binding':[p['binding'] for p in parts],
                'world_bounds_z_up':mesh.bounds.tolist(),
                'collider':{'method':'stationary_visual_convex_hull','artifact':_bound(path),
                            'vertex_count':len(vertices)},
                'mass_origin':'not_applicable_stationary_environment'}
            continue
        profile=spec['physical_profiles'][identifier]
        props=estimate_mass_properties(mesh,profile,output/'mass',pitch_m=.005 if identifier==static_id else .002)
        row={'initial_body_matrix_z_up':body.tolist(),'metric_box_extents_m':extents.tolist(),
             'physical_frame_definition':'declared_metric_asset_z_up' if 'asset_frames_world_z_up' in spec else 'asset_root',
             'semantic_up_axis_body':[0.,0.,1.],
             'mesh_binding':[p['binding'] for p in parts], 'mass_properties':_bound(Path(props['artifact'])),
             'mass_kg':props['mass_kg'],'center_of_mass_body_m':props['center_of_mass_m'],
             'principal_inertia_kg_m2':props['principal_inertia_kg_m2'],
             'inertial_quaternion_wxyz':props['inertial_quaternion_wxyz'],
             'mass_origin':props['mass_origin'],'mass_range_kg':props['mass_range_kg'],
             'mass_resolution_sensitivity':props['resolution_sensitivity'],
             'world_bounds_z_up':[np.concatenate([p['vertices'] for p in parts]).min(axis=0).tolist(),
                                  np.concatenate([p['vertices'] for p in parts]).max(axis=0).tolist()]}
        if identifier==static_id:
            proxy=VoxelSDF.load(Path(props['voxel_files'][-1]['path']))
            centers,sizes=voxel_boxes(proxy)
            path=output/'bookcase_cuboids.npz';np.savez_compressed(path,centers=centers,half_sizes=sizes)
            row.update(static=True,collider={'method':'disjoint_cuboids_of_undilated_component_voxels',
                       'box_count':len(centers),'pitch_m':proxy.pitch,'artifact':_bound(path),
                       'occupied_volume_m3':float(np.prod(sizes*2,axis=1).sum())})
            colliders[identifier]=(centers,sizes)
        else:
            vertices,faces=_hull(mesh.vertices);path=output/(identifier+'_hull.npz')
            np.savez_compressed(path,vertices=vertices,faces=faces)
            row.update(static=False,collider={'method':'single_book_visual_convex_hull',
                       'artifact':_bound(path),'vertex_count':len(vertices)})
            colliders[identifier]=(vertices,faces)
        objects[identifier]=row
    boundaries=[]
    for part in floor.get('other_architecture_parts',[]):
        vertices=part['vertices'];bounds=np.array([vertices.min(axis=0),vertices.max(axis=0)])
        import trimesh
        mesh=trimesh.Trimesh(vertices=vertices,faces=part['faces'],process=True)
        row={'name':part['binding']['name'],'world_bounds_z_up':bounds.tolist(),'mesh_binding':part['binding']}
        if not mesh.is_volume or not np.isclose(mesh.volume,np.prod(np.ptp(bounds,axis=0)),rtol=1e-5):
            if not spec.get('allow_stationary_architecture_hulls',False):
                raise ValueError('Room boundary must be a source-bound rectangular slab')
            vertices,faces=_hull(vertices);path=output/f'architecture_{len(boundaries):04d}.npz'
            np.savez_compressed(path,vertices=vertices,faces=faces)
            row['collider']={'method':'stationary_visual_convex_hull','artifact':_bound(path)}
        boundaries.append(row)
    binding={'schema':'p021-leaning-binding/v1','scene_glb':_bound(scene),'objects':objects,
             'floor':{'world_bounds_z_up':floor['world_bounds_z_up']},'spec':spec,
             'room_boundaries':boundaries,
             'bookcase_boundary':'stationary_environment','books_have_six_free_dofs':True,
             'material_ground_truth_available':False}
    _json(output/'geometry_binding.json',binding)
    return binding


def make_model(binding: dict,mu: float,dt: float,output: Path):
    root=ET.Element('mujoco',model='independent_leaning_books')
    ET.SubElement(root,'compiler',angle='radian',inertiafromgeom='false')
    option=ET.SubElement(root,'option',timestep=_vec([dt]),gravity='0 0 -9.81',integrator='implicitfast',
                         solver='Newton',cone='elliptic',iterations='100',tolerance='1e-10',impratio='5')
    ET.SubElement(option,'flag',multiccd='enable',nativeccd='enable')
    default=ET.SubElement(root,'default')
    ET.SubElement(default,'geom',condim='3',friction=_vec([mu,0,0]),margin='0',gap='0',
                  solref='.004 1',solimp='.95 .99 .001 .5 2')
    assets=ET.SubElement(root,'asset');world=ET.SubElement(root,'worldbody')
    fb=np.asarray(binding['floor']['world_bounds_z_up'])
    ET.SubElement(world,'geom',name='floor',type='box',pos=_vec(fb.mean(axis=0)),size=_vec(np.ptp(fb,axis=0)/2),
                  contype='2',conaffinity='1')
    geom_owners={'floor':'floor'}
    for row in binding.get('room_boundaries',[]):
        bounds=np.asarray(row['world_bounds_z_up']);geom_owners[row['name']]=row['name']
        if row.get('collider'):
            with np.load(row['collider']['artifact']['path'],allow_pickle=False) as data:
                meshname='architecture_mesh_'+row['name']
                ET.SubElement(assets,'mesh',name=meshname,vertex=_vec(data['vertices']),face=_vec(data['faces']))
                ET.SubElement(world,'geom',name=row['name'],type='mesh',mesh=meshname,contype='2',conaffinity='1')
        else:
            ET.SubElement(world,'geom',name=row['name'],type='box',pos=_vec(bounds.mean(axis=0)),
                          size=_vec(np.ptp(bounds,axis=0)/2),contype='2',conaffinity='1')
    for index,(identifier,obj) in enumerate(binding['objects'].items()):
        matrix=np.asarray(obj['initial_body_matrix_z_up'])
        body=ET.SubElement(world,'body',name=identifier,pos=_vec(matrix[:3,3]),
                           quat=_vec(Rotation.from_matrix(matrix[:3,:3]).as_quat()[[3,0,1,2]]))
        with np.load(obj['collider']['artifact']['path'],allow_pickle=False) as data:
            if obj['static'] and 'centers' in data:
                for i,(center,half) in enumerate(zip(data['centers'],data['half_sizes'])):
                    name=f'bookcase_box_{i:05d}';geom_owners[name]=identifier
                    ET.SubElement(body,'geom',name=name,type='box',pos=_vec(center),size=_vec(half),mass='0',contype='2',conaffinity='1')
            elif obj['static']:
                meshname='static_mesh_'+identifier;geomname='static_geom_'+identifier;geom_owners[geomname]=identifier
                ET.SubElement(assets,'mesh',name=meshname,vertex=_vec(data['vertices']),face=_vec(data['faces']))
                ET.SubElement(body,'geom',name=geomname,type='mesh',mesh=meshname,mass='0',contype='2',conaffinity='1')
            else:
                ET.SubElement(body,'freejoint',name='free_'+identifier)
                ET.SubElement(body,'inertial',pos=_vec(obj['center_of_mass_body_m']),mass=_vec([obj['mass_kg']]),
                              diaginertia=_vec(obj['principal_inertia_kg_m2']),quat=_vec(obj['inertial_quaternion_wxyz']))
                meshname='mesh_'+identifier;geomname='geom_'+identifier;geom_owners[geomname]=identifier
                ET.SubElement(assets,'mesh',name=meshname,vertex=_vec(data['vertices']),face=_vec(data['faces']))
                ET.SubElement(body,'geom',name=geomname,type='mesh',mesh=meshname,mass='0',contype='1',conaffinity='3')
    xml=ET.tostring(root,encoding='unicode');(output/'model.xml').write_text(xml+'\n')
    model=mujoco.MjModel.from_xml_string(xml);data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    compiled={'mujoco_version':mujoco.__version__,'gravity':model.opt.gravity.tolist(),'dt_s':float(model.opt.timestep),
              'mu':mu,'body_count':model.nbody,'geom_count':model.ngeom,'free_dof_count':model.nv,
              'equality_constraint_count':model.neq,'damping':model.dof_damping.tolist(),
              'no_kinematic_books':model.nv==6*sum(not o['static'] for o in binding['objects'].values()) and model.neq==0,
              'bodies':{}}
    for identifier,obj in binding['objects'].items():
        b=model.body(identifier).id
        if not obj['static']:
            if not np.isclose(model.body_mass[b],obj['mass_kg'],rtol=1e-12):raise ValueError('Compiled book mass differs')
            if not np.allclose(model.body_ipos[b],obj['center_of_mass_body_m'],atol=1e-12):raise ValueError('Compiled COM differs')
            if not np.allclose(model.body_inertia[b],obj['principal_inertia_kg_m2'],atol=1e-12,rtol=1e-12):
                raise ValueError('Compiled principal inertia differs')
            rotation=Rotation.from_quat(model.body_iquat[b][[1,2,3,0]]).as_matrix()
            expected=Rotation.from_quat(np.asarray(obj['inertial_quaternion_wxyz'])[[1,2,3,0]]).as_matrix()
            tensor=rotation@np.diag(model.body_inertia[b])@rotation.T
            if not np.allclose(tensor,expected@np.diag(obj['principal_inertia_kg_m2'])@expected.T,atol=1e-12,rtol=1e-12):
                raise ValueError('Compiled full inertia differs')
        compiled['bodies'][identifier]={'body_id':b,'mass_kg':float(model.body_mass[b]),'center_of_mass_body_m':model.body_ipos[b].tolist()}
    owners={model.geom(name).id:identifier for name,identifier in geom_owners.items()}
    return model,data,owners,compiled


def simulate(binding: dict,output: Path,*,mu: float,dt: float,duration: float=5.) -> dict:
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    model,data,owners,compiled=make_model(binding,mu,dt,output)
    initial_penetrations=[{'objects':[owners[int(c.geom1)],owners[int(c.geom2)]],
        'depth_m':-float(c.dist),'position_m':c.pos.tolist()} for c in data.contact if c.dist<0]
    ids=list(binding['objects']);bookids=[s for s in ids if not binding['objects'][s]['static']]
    bids=[model.body(s).id for s in ids];steps=round(duration/dt)
    for identifier in bookids:
        up=data.xmat[model.body(identifier).id].reshape(3,3)@np.asarray(binding['objects'][identifier].get('semantic_up_axis_body',[0,0,1]))
        initial_angle=float(np.degrees(np.arccos(np.clip(up[2],-1,1))))
        if 'initial_lean_deg' in binding['spec'] and abs(initial_angle-binding['spec']['initial_lean_deg'])>1e-3:
            raise ValueError('Semantic book height axis disagrees with the initial lean')
    state_spec=int(mujoco.mjtState.mjSTATE_INTEGRATION)
    states=np.empty((steps+1,mujoco.mj_stateSize(model,state_spec)))
    matrices=np.empty((steps+1,len(ids),4,4));linear=np.empty((steps+1,len(ids),3));angular=np.empty_like(linear)
    contact_counts=np.zeros((steps+1,len(bookids)),dtype=int);contacts={};max_pen=0.;min_normal=0.;cone_excess=0.
    contact_force=np.zeros((steps+1,len(bookids),3));contact_torque=np.zeros_like(contact_force)
    support_counts=np.zeros((steps+1,len(bookids),2),dtype=int)
    book_indices={s:i for i,s in enumerate(bookids)}
    tail_contacts={};tail_pair_steps={};support_target=binding['spec'].get('target_support_world')
    row_axis=np.asarray(binding['spec'].get('lean_axis_world',[1.,0.,0.]))
    transverse_axis=np.cross([0.,0.,1.],row_axis)
    for step in range(steps+1):
        step_pairs=set()
        mujoco.mj_getState(model,data,states[step],state_spec)
        for index,bid in enumerate(bids):
            matrix=np.eye(4);matrix[:3,:3]=data.xmat[bid].reshape(3,3);matrix[:3,3]=data.xpos[bid];matrices[step,index]=matrix
            velocity=np.zeros(6);mujoco.mj_objectVelocity(model,data,mujoco.mjtObj.mjOBJ_BODY,bid,velocity,0)
            angular[step,index]=velocity[:3];linear[step,index]=velocity[3:]
        for c in range(data.ncon):
            contact=data.contact[c];a,b=owners[int(contact.geom1)],owners[int(contact.geom2)]
            force=np.zeros(6);mujoco.mj_contactForce(model,data,c,force)
            if force[0]<=1e-8:continue
            key='|'.join(sorted((a,b)));record=contacts.setdefault(key,{'samples':0,'max_normal_n':0.,'max_tangent_n':0.})
            step_pairs.add(key)
            record['samples']+=1;record['max_normal_n']=max(record['max_normal_n'],float(force[0]))
            record['max_tangent_n']=max(record['max_tangent_n'],float(np.linalg.norm(force[1:3])))
            frame=contact.frame.reshape(3,3);world_force=frame.T@force[:3]
            if step*dt>=duration-1:
                tail_contacts[key]=tail_contacts.get(key,0)+1
            for identifier,sign in ((a,-1),(b,1)):
                if identifier not in book_indices:continue
                bi=book_indices[identifier];bid=model.body(identifier).id
                contact_force[step,bi]+=sign*world_force
                contact_torque[step,bi]+=np.cross(contact.pos-data.xipos[bid],sign*world_force)+sign*(frame.T@force[3:])
                other=b if identifier==a else a
                if other==binding['spec']['bookcase_id']:
                    normal=sign*frame[0]
                    on_target_shelf=(support_target is None or abs(contact.pos[2]-support_target['shelf_z_m'])<.02)
                    on_right_panel=(support_target is None or (np.dot(contact.pos,row_axis)>support_target['right_inner_x_m']-.02
                        and support_target['shelf_z_m']+.025<contact.pos[2]<support_target['shelf_z_m']+support_target['book_height_m']+.025))
                    if normal[2]>.7 and on_target_shelf:support_counts[step,bi,0]+=1
                    if abs(np.dot(normal,row_axis))>.7 and on_right_panel:support_counts[step,bi,1]+=1
            max_pen=max(max_pen,-float(contact.dist));min_normal=min(min_normal,float(force[0]))
            cone_excess=max(cone_excess,float(np.linalg.norm(force[1:3])-mu*force[0]))
            for identifier in (a,b):
                if identifier in bookids:contact_counts[step,bookids.index(identifier)]+=1
        if step*dt>=duration-1:
            for key in step_pairs:tail_pair_steps[key]=tail_pair_steps.get(key,0)+1
        if not np.isfinite(states[step]).all():raise ValueError('Nonfinite simulation state')
        if step<steps:
            mujoco.mj_step(model,data)
            # Forward only derived fields; saved states include its warmstart state.
            mujoco.mj_forward(model,data)
    times=np.arange(steps+1)*dt
    dense_path=output/'dense_state.npz'
    np.savez_compressed(dense_path,time_s=times,object_ids=np.array(ids),matrix_world_z_up=matrices,
                        linear_velocity_m_s=linear,angular_velocity_rad_s=angular,integration_state=states,
                        integration_state_spec=state_spec,mujoco_version=mujoco.__version__,
                        model_sha256=_bound(output/'model.xml')['sha256'],contact_counts=contact_counts)
    metrics={};tail=times>=duration-1
    for identifier in bookids:
        i=ids.index(identifier)
        up=matrices[:,i,:3,:3]@np.asarray(binding['objects'][identifier].get('semantic_up_axis_body',[0,0,1]))
        # Source normalization keeps the longest book axis upright before leaning.
        angle=np.degrees(np.arctan2(up@row_axis,up[:,2]))
        total_tilt=np.degrees(np.arccos(np.clip(up[:,2],-1,1)))
        displacement=np.linalg.norm(matrices[:,i,:3,3]-matrices[0,i,:3,3],axis=1)
        metrics[identifier]={'initial_lean_deg':float(angle[0]),'final_lean_deg':float(angle[-1]),
            'final_total_tilt_from_vertical_deg':float(total_tilt[-1]),
            'final_out_of_row_plane_tilt_deg':float(np.degrees(np.arctan2(up[-1]@transverse_axis,up[-1,2]))),
            'max_translation_m':float(displacement.max()),'final_translation_m':float(displacement[-1]),
            'tail_linear_rms_m_s':float(np.sqrt(np.mean(np.sum(linear[tail,i]**2,axis=1)))),
            'tail_angular_rms_rad_s':float(np.sqrt(np.mean(np.sum(angular[tail,i]**2,axis=1)))),
            'tail_lean_range_deg':float(np.ptp(angle[tail])),
            'retained_small_lean':bool(5<=total_tilt[-1]<=18 and angle[-1]>0),
            'macroscopically_settled':bool(np.sqrt(np.mean(np.sum(linear[tail,i]**2,axis=1)))<.005
                                         and np.sqrt(np.mean(np.sum(angular[tail,i]**2,axis=1)))<.03)}
        bi=book_indices[identifier];weight=binding['objects'][identifier]['mass_kg']*9.81
        residual=contact_force[tail,bi]+np.array([0,0,-weight])
        metrics[identifier].update({'tail_mean_force_imbalance_over_weight':float(np.linalg.norm(residual.mean(axis=0))/weight),
            'tail_mean_contact_torque_nm':contact_torque[tail,bi].mean(axis=0).tolist(),
            'tail_fraction_with_shelf_support':float((support_counts[tail,bi,0]>0).mean()),
            'tail_fraction_with_side_support':float((support_counts[tail,bi,1]>0).mean())})
    np.savez_compressed(output/'contact_wrenches.npz',time_s=times,book_ids=np.array(bookids),
                        contact_force_n=contact_force,contact_torque_about_com_nm=contact_torque,
                        shelf_side_contact_counts=support_counts)
    warnings=[{'index':i,'count':int(w.number),'lastinfo':int(w.lastinfo)} for i,w in enumerate(data.warning) if w.number]
    # Exact continuation check from a saved complete integration state.
    middle=steps//2;restored=mujoco.MjData(model);mujoco.mj_setState(model,restored,states[middle],state_spec)
    matches=[]
    for j in range(1,31):
        mujoco.mj_step(model,restored);mujoco.mj_forward(model,restored)
        actual=np.empty(states.shape[1]);mujoco.mj_getState(model,restored,actual,state_spec)
        matches.append(bool(np.array_equal(actual,states[middle+j])))
    frame_indices=sorted(set([0,steps,*[round(t/dt) for t in (.1,.25,.5,1,2,3,4) if t<duration]]))
    frames=[]
    for step in frame_indices:
        frames.append({'time_s':float(times[step]),'dense_sample_index':step,
                       'bodies':{s:{'matrix_world_z_up':matrices[step,i].tolist(),
                                    'linear_velocity_m_s':linear[step,i].tolist(),
                                    'angular_velocity_rad_s':angular[step,i].tolist()} for i,s in enumerate(ids)}})
    trajectory={'schema':'p021-leaning-trajectory/v1','scene_glb':binding['scene_glb'],
                'dense_state':_bound(dense_path),'frames':frames}
    _json(output/'trajectory.json',trajectory)
    result={'schema':'p021-leaning-result/v1','status':'completed','mu':mu,'dt_s':dt,'duration_s':duration,
            'compiled':compiled,'metrics':metrics,'contact_pairs':contacts,'simulator_warnings':warnings,
            'initial_penetrations':initial_penetrations,'tail_contact_pairs':tail_contacts,
            'tail_contact_pair_active_step_fraction':{k:v/int(tail.sum()) for k,v in tail_pair_steps.items()},
            'contact_wrenches':_bound(output/'contact_wrenches.npz'),
            'max_contact_penetration_m':max_pen,'max_coulomb_cone_excess_n':cone_excess,
            'all_finite':bool(np.isfinite(states).all()),'exact_30_step_state_restore':all(matches),
            'all_books_retain_small_lean':all(v['retained_small_lean'] for v in metrics.values()),
            'all_books_settled':all(v['macroscopically_settled'] for v in metrics.values()),
            'trajectory':_bound(output/'trajectory.json'),'wall_seconds':time.monotonic()-started}
    _json(output/'result.json',result);return result
