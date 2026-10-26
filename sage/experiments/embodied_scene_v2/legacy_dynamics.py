"""Frozen legacy dynamics with only a positive time-constant multiplier and peak witness added."""
import json,time
from pathlib import Path
from xml.etree import ElementTree as ET
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.codex_trellis_scene_v2.p021_physics import _vec,_bound,_json

def make_model(binding: dict,mu: float,dt: float,output: Path):
    if dt>.004*binding.get('round2_timeconst_multiplier',1.)/2+1e-12:raise ValueError('Positive solref dt safety condition')
    root=ET.Element('mujoco',model='independent_leaning_books')
    ET.SubElement(root,'compiler',angle='radian',inertiafromgeom='false')
    option=ET.SubElement(root,'option',timestep=_vec([dt]),gravity='0 0 -9.81',integrator='implicitfast',
                         solver='Newton',cone='elliptic',iterations='100',tolerance='1e-10',impratio='5')
    ET.SubElement(option,'flag',multiccd='enable',nativeccd='enable')
    default=ET.SubElement(root,'default')
    ET.SubElement(default,'geom',condim='3',friction=_vec([mu,0,0]),margin='0',gap='0',
                  solref=_vec([.004*binding.get('round2_timeconst_multiplier',1.),1.]),solimp='.95 .99 .001 .5 2')
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
    contact_counts=np.zeros((steps+1,len(bookids)),dtype=int);contacts={};peak_witness=None;max_pen=0.;min_normal=0.;cone_excess=0.
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
            if -float(contact.dist)>max_pen:
                peak_witness=dict(sample_index=step,time_s=float(data.time),owners=[a,b],geom_ids=[int(contact.geom1),int(contact.geom2)],position_m=contact.pos.tolist(),normal=contact.frame[:3].tolist(),dist_m=float(contact.dist),force=force.tolist(),solref=contact.solref.tolist())
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
            'max_contact_penetration_m':max_pen,'peak_contact_witness':peak_witness,'max_coulomb_cone_excess_n':cone_excess,
            'all_finite':bool(np.isfinite(states).all()),'exact_30_step_state_restore':all(matches),
            'all_books_retain_small_lean':all(v['retained_small_lean'] for v in metrics.values()),
            'all_books_settled':all(v['macroscopically_settled'] for v in metrics.values()),
            'trajectory':_bound(output/'trajectory.json'),'wall_seconds':time.monotonic()-started}
    _json(output/'result.json',result);return result
