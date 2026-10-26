"""One finite automatic candidate family, including closure and full-hand collision."""
from pathlib import Path
import numpy as np
import mujoco
from scipy.optimize import least_squares
from .native import Stretch, action
from .quality import contact_quality
from .build import write


class LimitReached(Exception):
    pass


def plan(config, task, binding, output):
    output = Path(output)
    (output/'PLANNING_ATTEMPT').open('x').close()
    p = config['planning']; m = mujoco.MjModel.from_xml_path(task['model']); d = mujoco.MjData(m)
    native = Stretch(m, binding); initial = d.qpos.copy(); count = 0; stored = []; trace = []
    target = native.target; floor = binding['floor_geom']; allowed = set(binding['allowed_ground_robot_geoms'])
    robot_geoms = np.array([g for g in range(m.ngeom) if int(m.geom_bodyid[g]) in native.robot and (m.geom_contype[g] or m.geom_conaffinity[g])])
    env = np.array([g for g in range(m.ngeom) if int(m.geom_bodyid[g]) not in native.robot and g != floor and (m.geom_contype[g] or m.geom_conaffinity[g])])
    def place(station, x, label):
        nonlocal count
        if count >= config['budget']['fk_configurations_per_combination']:
            raise LimitReached('total_configuration_budget')
        count += 1
        native.place_for_planning(d, initial, station, x)
        stored.append(d.qpos.copy()); trace.append(dict(index=count, kind=label, variables=x.tolist()))
        return native.geometry(d)
    def collision(allow_target=False):
        bad = []; pen = 0.
        for c in d.contact:
            g1,g2=int(c.geom1),int(c.geom2); b1,b2=map(int,m.geom_bodyid[[g1,g2]])
            if b1 not in native.robot and b2 not in native.robot:
                continue
            if (g1==floor and g2 in allowed) or (g2==floor and g1 in allowed):
                pen=max(pen,-float(c.dist));continue
            if allow_target and target in (b1,b2) and (b1 in native.hands or b2 in native.hands):
                if c.dist >= -p['closing_penetration_m']:
                    continue
            bad.append(dict(body1=m.body(b1).name,body2=m.body(b2).name,distance_m=float(c.dist)))
        minimum=.01; pair=None; ft=np.empty(6)
        for a in robot_geoms:
            lower=np.linalg.norm(d.geom_xpos[env]-d.geom_xpos[a],axis=1)-m.geom_rbound[env]-m.geom_rbound[a]
            for b in env[lower<=.01]:
                if allow_target and int(m.geom_bodyid[b])==target and int(m.geom_bodyid[a]) in native.hands:continue
                if not ((m.geom_contype[a]&m.geom_conaffinity[b]) or (m.geom_contype[b]&m.geom_conaffinity[a])):continue
                distance=float(mujoco.mj_geomDistance(m,d,int(a),int(b),.01,ft))
                if distance<minimum:minimum=distance;pair=[int(a),int(b)]
        return dict(passed=not bad and pen<=.01 and minimum>=p['nonfloor_clearance_m'],
                    contacts=bad,minimum_clearance_m=minimum,closest_geoms=pair)
    center=np.array(task['start'])+task['local_com']; vertices=np.asarray(task['local_vertices'])
    # Table bounds are source geometry, unchanged from the admitted full scene.
    lo=np.array([1.730000119162958,3.229999938246947]); hi=np.array([3.0700000649950153,3.889999961798567])
    stations=[]
    for side in p['side_order']:
        c=p['normal_clearance_m']
        if side=='front':pos=[center[0],lo[1]-c,0];tangent=[1,0,0];inward=[0,1,0];yaw=np.pi
        elif side=='back':pos=[center[0],hi[1]+c,0];tangent=[1,0,0];inward=[0,-1,0];yaw=0.
        elif side=='right':pos=[hi[0]+c,center[1],0];tangent=[0,1,0];inward=[-1,0,0];yaw=-np.pi/2
        else:pos=[lo[0]-c,center[1],0];tangent=[0,1,0];inward=[1,0,0];yaw=np.pi/2
        stations.append(dict(side=side,position=pos,tangent=tangent,inward=inward,yaw=float(yaw)))
    # Native aperture samples are geometry observations, never dynamics.
    aperture=[]
    for grip in np.linspace(-.005,.04,19):
        x=np.array([0.,.4,.06,0.,grip]); _,_,gap=place(stations[0],x,'native_aperture')
        aperture.append([grip,gap])
    lower=np.array([-.2,-.5,0.,-1.75,-.005]);upper=np.array([.2,.6,.52,4.,.04])
    candidates=[];selected=None
    for station in stations:
      for axis_index in p['axis_order']:
        row=dict(id=f'C{len(candidates)+1:02}',station=station,jaw_axis_index=axis_index,status='rejected')
        candidates.append(row)
        if selected is not None:row.update(status='not_attempted',reason='earlier_candidate_selected');continue
        width=float(np.ptp(vertices[:,axis_index]));row['object_projection_width_m']=width
        if width+.002>aperture[-1][1]:row['reason']='native_aperture';continue
        close_grip=float(np.interp(width-.001,np.array(aperture)[:,1],np.array(aperture)[:,0]))
        calls=0
        try:
            x=np.array([0.,p['home_lift'],p['home_extension'],0.,close_grip])
            mid,axis,_=place(station,x,'closed_seed')
            angle0=np.arctan2(axis[1],axis[0]); desired=axis_index*np.pi/2
            options=[desired+k*np.pi-angle0 for k in range(-3,4)]
            x[3]=min((v for v in options if lower[3]<=v<=upper[3]),key=abs)
            desired=angle0+x[3];mid,_,_=place(station,x,'oriented_seed')
            delta=center-mid;x[0]+=np.dot(delta,station['tangent']);x[1]+=delta[2];x[2]+=np.dot(delta,station['inward'])
            x=np.clip(x,lower+1e-10,upper-1e-10)
            def residual(v):
                nonlocal calls
                if calls>=p['max_ik_calls']:raise LimitReached('candidate_IK_budget')
                calls+=1;mid,axis,gap=place(station,v,'closed_ik')
                angle=np.arctan2(axis[1],axis[0])-desired
                return np.r_[mid-center,.1*np.arctan2(np.sin(angle),np.cos(angle)),gap-(width-.001)]
            sol=least_squares(residual,x,bounds=(lower,upper),max_nfev=60,xtol=1e-10,ftol=1e-10,gtol=1e-10)
            x=sol.x;mid,axis,gap=place(station,x,'closed_endpoint')
            angle=np.arctan2(axis[1],axis[0])-desired
            row.update(ik_calls=calls,closed_variables=x.tolist(),position_error_m=float(np.linalg.norm(mid-center)),jaw_angle_error_rad=float(abs(np.arctan2(np.sin(angle),np.cos(angle)))))
            if row['position_error_m']>p['position_tolerance_m'] or row['jaw_angle_error_rad']>p['angle_tolerance_rad']:
                row['reason']='IK_residual';continue
            # Opening does not alter the arm target solved for the closed contact COM.
            opened=x.copy();opened[4]=p['full_open'];place(station,opened,'open_endpoint')
            row['open_collision']=collision()
            if not row['open_collision']['passed']:row['reason']='open_full_hand_collision';continue
            closure=[];last=None
            for grip in np.linspace(p['full_open'],0.,p['closure_samples']):
                v=x.copy();v[4]=grip;place(station,v,'closure_sweep');check=collision(True)
                cs=native.contacts(d,actual_forces=False)
                quality=contact_quality(cs,d.xipos[target],d.xmat[target].reshape(3,3),task['mass_kg'],task['friction'][0],p['nominal_finger_force_N'])
                closure.append(dict(grip=float(grip),collision=check,quality=quality))
                if not check['passed']:break
                if all(quality[s]['force_N']>0 for s in ('left','right')):last=quality;break
            row['closure']=closure
            if not closure[-1]['collision']['passed']:row['reason']='closure_collision_or_penetration';continue
            if last is None:row['reason']='no_predicted_bilateral_contact';continue
            if any(last[s]['pad_fraction']<.8 for s in ('left','right')):row['reason']='predicted_contact_on_finger_links';continue
            if last['contact_com_offset_m']>p['max_contact_com_offset_m']:row['reason']='predicted_contact_off_COM';continue
            raised=opened.copy();raised[1]+=p['pregrasp_above_m']
            retract=raised.copy();retract[2]=p['home_extension'];home=retract.copy();home[1]=p['home_lift'];home[3]=0.
            if raised[1]+.02>upper[1]:row['reason']='lift_range';continue
            points=[home,retract,raised,opened];paths=[];qhome=None
            for start,end in zip(points[:-1],points[1:]):
                for t in np.linspace(0,1,p['path_samples']):
                    s=t**3*(10-15*t+6*t*t);v=start+s*(end-start);place(station,v,'approach_path')
                    if qhome is None:qhome=d.qpos.copy()
                    check=collision();paths.append(check)
                    if not check['passed']:break
                if not paths[-1]['passed']:break
            row['path_checks']=paths
            if not paths[-1]['passed']:row['reason']='approach_path_collision';continue
            # Predeclare transport through the extension coordinate; no base teleport.
            transport_delta=float(np.dot(np.array(task['goal'])-task['start'],station['inward']))
            orthogonal=np.array(task['goal'])-task['start']-transport_delta*np.array(station['inward'])
            if np.linalg.norm(orthogonal[:2])>1e-6:row['reason']='transport_not_along_native_arm';continue
            if not 0<=x[2]+transport_delta<=.52:row['reason']='transport_extension_range';continue
            row.update(status='plan_pass',reason=None,open_variables=opened.tolist(),waypoints=[v.tolist() for v in points],
                       transport_extension_delta_m=transport_delta,quality=last)
            selected=row;np.savez_compressed(output/'START.npz',qpos=qhome)
        except LimitReached as e:
            row.update(reason=str(e),ik_calls=calls)
    result=dict(status='plan_pass' if selected else 'planning_rejected',candidates=candidates,
                selected=None if selected is None else selected['id'],static_configurations=count,physics_steps=0)
    np.savez_compressed(output/'PLANNER_CONFIGURATIONS.npz',qpos=np.array(stored))
    write(output/'PLANNER_TRACE.json',trace);write(output/'PLAN_RESULT.json',result)
    if selected:write(output/'SELECTED.json',selected)
    return result
