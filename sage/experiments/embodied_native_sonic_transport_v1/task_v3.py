"""Close wrist tracking error through SONIC references, preserve SONIC29 actuation."""
import numpy as np
from scipy.spatial.transform import Rotation
from .task_v2 import Task as ParentTask
from .reference_feedback import ReferenceFeedback
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


class Task(ParentTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.reference_feedback=ReferenceFeedback()
        self.feedback_last_tick=None

    def synchronize(self,tick,data,force=False):
        if self.path is None or (not force and tick%5):return
        if self.feedback_last_tick==tick and not force:return
        position,orientation=self.desired(tick)
        position_error=position-data.xpos[self.wrist]
        rotation_error=Rotation.from_matrix(orientation@data.xmat[self.wrist].reshape(3,3).T).as_rotvec()
        dt=0. if self.feedback_last_tick is None else min(.1,max(0.,(tick-self.feedback_last_tick)*.02))
        bias,rbias=self.reference_feedback.update(position_error,rotation_error,dt)
        selected=None;rejected=[]
        for factor in (1.,.5,0.):
            seed=data.qpos.copy();knots=[];failed=False
            delta=Rotation.from_rotvec(factor*rbias).as_matrix()
            for offset in range(0,51,5):
                pos,R=self.desired(tick+offset)
                fit=self.ik.solve(seed,pos+factor*bias,delta@R,max_evaluations=60)
                self.last_ik=fit
                if fit['position_error_m']>.010 or fit['orientation_error_rad']>.05:
                    rejected.append(dict(factor=factor,offset=offset,ik=fit));failed=True;break
                seed[self.armq]=fit['angles_rad'];knots.append(fit['angles_rad'])
            if not failed:selected=(factor,knots);break
        if selected is None:
            self.failure='bounded_corrected_reference_unreachable'
            self.events.append(dict(kind='reference_feedback_ik_failure',tick=tick,rejected=rejected));return
        factor,knots=selected
        self.reference_feedback.position=factor*bias;self.reference_feedback.rotation=factor*rbias
        self.feedback_last_tick=tick
        end=min(len(self.q),tick+100);ages=np.arange(end-tick)
        for j,index in enumerate(ARM+7):
            self.q[tick:end,index]=np.interp(ages,np.arange(0,51,5),np.asarray(knots)[:,j])
            self.q[end:,index]=knots[-1][j]
        self.v=native._reference_velocities(self.q)
        self.events.append(dict(kind='sonic_reference_feedback',tick=tick,stage=self.stage,
            actual_wrist_m=data.xpos[self.wrist].tolist(),nominal_wrist_m=position.tolist(),
            position_error_m=position_error.tolist(),rotation_error_rad=rotation_error.tolist(),
            applied_position_bias_m=self.reference_feedback.position.tolist(),applied_rotation_bias_rad=self.reference_feedback.rotation.tolist(),
            feasibility_factor=factor,rejected=rejected,independent_motor_commands=False))
