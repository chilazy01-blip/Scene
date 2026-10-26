"""Plan a tabletop clearance arc while preserving the measured tripod endpoint."""
import numpy as np,mujoco
from scipy.spatial.transform import Rotation,Slerp
from .planned_tripod_r2 import FINGER_NAMES,forbidden_robot_contacts,hand_contacts
from .safe_approach_r3 import hand_bounds


def plan_arc(runner,grasp,height=.02):
    m,live,ik=runner.model,runner.data,runner.ik;q0=live.qpos.copy();d=mujoco.MjData(m);d.qpos[:]=q0;d.qvel[:]=0.
    arm0=q0[ik.qpos_idx].copy();arm1=np.asarray(grasp['arm_target_rad']);finger0=np.asarray(grasp['initial_finger_rad']);finger1=np.asarray(grasp['finger_target_rad'])
    fa=np.array([m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in FINGER_NAMES]);sid=ik.site_id
    mujoco.mj_forward(m,d);p0=d.site_xpos[sid].copy();r0=d.site_xmat[sid].reshape(3,3).copy();d.qpos[ik.qpos_idx]=arm1;mujoco.mj_forward(m,d);p1=d.site_xpos[sid].copy();r1=d.site_xmat[sid].reshape(3,3).copy()
    rotation=Slerp([0.,1.],Rotation.from_matrix([r0,r1]));fractions=np.linspace(0.,1.,21);arms=[];errors=[];previous=arm0.copy()
    for t in fractions:
        goal=(1-t)*p0+t*p1+np.array([0.,0.,height*np.sin(np.pi*t)])
        if t==0:arm=arm0.copy();err=rot_err=0.
        elif t==1:arm=arm1.copy();err=rot_err=0.
        else:
            d.qpos[:]=q0;d.qpos[ik.qpos_idx]=previous;mujoco.mj_forward(m,d)
            arm,err,rot_err=ik.solve(d,goal,rotation(t).as_matrix(),iters=100)
        arms.append(np.asarray(arm).copy());errors.append([float(err),float(rot_err)]);previous=arm.copy()
    arms=np.array(arms);required=float(max(np.max(abs(np.diff(arms,axis=0)/np.diff(fractions)[:,None]))/.18,np.max(abs(finger1-finger0))/.18,.4))
    top=float(live.geom_xpos[m.geom('table_top').id,2]+m.geom_size[m.geom('table_top').id,2]);bad=[];gaps=[];max_pen=0.
    for t in np.linspace(0.,1.,201):
        d.qpos[:]=q0;d.qvel[:]=0.;d.qpos[ik.qpos_idx]=[np.interp(t,fractions,arms[:,j]) for j in range(7)];d.qpos[fa]=(1-t)*finger0+t*finger1;mujoco.mj_forward(m,d)
        forbidden=forbidden_robot_contacts(m,d,runner.cyl_bid)
        if forbidden:bad.append({'fraction':float(t),'pairs':forbidden})
        lo,_=hand_bounds(m,d);gaps.append(float(lo[2]-top));contacts,_=hand_contacts(m,d,runner.cyl_bid);max_pen=max(max_pen,max([-float(x.dist) for x in contacts],default=0.))
    assert np.array_equal(q0,live.qpos)
    return {'valid':not bad and min(gaps)>=.006 and max_pen<=.002 and max(x[0] for x in errors)<=.003 and max(x[1] for x in errors)<=1. and required<=5.8,'arch_height_m':height,'fractions':fractions.tolist(),'arm_path_rad':arms.tolist(),'minimum_hand_table_vertical_clearance_m':min(gaps),'path_forbidden':bad,'max_hand_object_penetration_m':max_pen,'ik_errors':errors,'required_duration_s':required,'endpoint_arm_identical':bool(np.array_equal(arms[-1],arm1)),'no_live_state_write':True,'path_samples':201}
