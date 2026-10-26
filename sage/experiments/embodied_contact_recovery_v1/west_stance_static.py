"""D alternative placement stance from native/generated target table geometry."""
import os,sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,R,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work))
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r4 import install
install('A','gain_translation',work/'static_interface')
import run
from ik import pipeline as p
from ik.sim import ArmIK6
from .pose_planner_static_r3 import solve
from .object_pose_receding import segment_clear
source=E/'jobs/C_development_03/episode';native=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'))
with h5py.File(source/'TRACE.h5','r') as f:state=f['substep/integration_before'][25299]
native_names=[native.joint(i).name for i in range(native.njnt)];results=[]
for name in ['native','development_03','development_04','development_05']:
    path=source/'MODEL.mjb' if name=='native' else E/'generated'/name/'package/MODEL.mjb'
    m=mujoco.MjModel.from_binary_path(str(path));d=mujoco.MjData(m)
    assert [m.joint(i).name for i in range(m.njnt)]==native_names and m.nq==native.nq and m.nv==native.nv
    mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION)
    geo=p.scene_geometry(m);center=np.asarray(geo['blue_center'][:2]);half=np.asarray(geo['blue_half'][:2])
    stance=np.array([center[0]-half[0]-.36,center[1]+.15]);shift=stance-d.qpos[:2]
    d.qpos[:2]=stance;oa=int(m.jnt_qposadr[m.joint('red_block_joint').id]);d.qpos[oa:oa+2]+=shift
    d.qpos[int(m.jnt_qposadr[m.joint('left_elbow_joint').id])] -= .10
    mujoco.mj_forward(m,d)
    ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl)
    class Runner:
        model=m;data=d;cyl_bid=m.body('red_block').id
        def __init__(self):self.ik=ik
        def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
        def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
    runner=Runner();goal=np.array([center[0]-half[0]+.05,center[1]])
    initial_q=d.qpos.copy();result=solve(runner,geo,goal,allow_stance=False)
    check=segment_clear(runner,np.asarray(result['variables'][:-2]),samples=81) if result['valid'] else None
    assert np.array_equal(initial_q,d.qpos)
    results.append({'layout':name,'model_sha256':c.sha(path),'planned_base_xy':stance.tolist(),
                    'base_yaw_quat_unchanged_from_source':True,'table_west_edge_clearance_m':.36,
                    'object_goal_xy':goal.tolist(),'target_object_edge_margin_m':.05,'arm_plan':result,'arm_path':check})
report={'physics_steps':0,'policy_calls':0,'method':'D_object_pose_planning','source_row':25299,'plans':results,
        'scope':'Counterfactual scratch placement stances derived from each real table; no runtime base/object pose writes. Dynamic walking route and contact retention are unverified.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'D_WEST_STANCE_STATIC_PLANS.json',report);finish(report)
