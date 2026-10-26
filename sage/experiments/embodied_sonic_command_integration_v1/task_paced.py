"""Same task/grip/SONIC29 with slower loaded reference phase; approach remains exact."""
from .task_preload import Task as Previous
from .paced_reference import retime

class Task(Previous):
    def walk(self,tick,data,loaded):
        if loaded and not getattr(self,'loaded_paced',False):
            before=len(self.baseq);self.baseq,self.basev=retime(self.baseq,self.basev,.65)
            self.loaded_paced=True
            self.events.append(dict(kind='loaded_walk_reference_phase_paced',tick=tick,phase_rate=.65,original_reference_frames=before,paced_reference_frames=len(self.baseq),joint_velocity_references_scaled=True,policy_hz=50,physics_hz=200,all29_body_outputs_still_sonic=True,original_task_and_motor_acceptance=True))
        return super().walk(tick,data,loaded)
