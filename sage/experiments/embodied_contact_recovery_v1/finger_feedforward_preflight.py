"""Actual saved-model regression for free-motion feedforward and unchanged hold."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
from .planned_tripod_r2 import PlannedFingerServo as Old
from .planned_tripod_feedforward import PlannedFingerServo as New


def main():
    reports=[]
    for name in ['D_sidewall_tripod_window_01','D_tripod_window_01']:
        folder=E/'jobs'/name/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'))
        with h5py.File(folder/'TRACE.h5','r') as f:
            for k in [0,len(f['substep/qpos'])//2,len(f['substep/qpos'])-1]:
                state=f['substep/integration_before'][k];desired=f['finger_governor/control'][k,:,4]
                a,b=mujoco.MjData(m),mujoco.MjData(m)
                for d in [a,b]:mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
                old,new=Old(m),New(m);first=old.apply(m,a,desired);second=new.apply(m,b,desired,np.zeros(7));assert np.array_equal(first,second) and np.array_equal(a.ctrl,b.ctrl) and old.reference==new.reference
                q=b.qpos.copy();v=b.qvel.copy();before=b.ctrl.copy();updated=new.apply(m,b,desired,np.array([.04,-.04,-.08,.15,.15,.15,.15]));held=updated[:,1]==2
                assert np.array_equal(b.qpos,q) and np.array_equal(b.qvel,v)
                assert np.array_equal(b.ctrl[new.aids[held]],before[new.aids[held]])
                assert np.all(abs(b.ctrl[new.aids[held]]-b.qpos[new.qa[held]])<=.030000000001)
                assert new.free_speed==.20 and new.cap==.03
                reports.append({'job':name,'row':k,'zero_feedforward_exact':True,'contact_hold_unchanged':True,'held_joints':int(sum(held)),'free_joints':int(sum(~held)),'no_live_state_write':True})
    result={'passed':True,'physics_steps':0,'saved_state_checks':reports,'original_contact_preload_rad':.03,'original_free_speed_limit_rad_s':.20,'production_accepted':False};c.write(E/'D_FINGER_FEEDFORWARD_PREFLIGHT.json',result);finish(result)


if __name__=='__main__':main()
